import os
import logging
import shlex
import subprocess
import tempfile
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Lock
from typing import Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor, as_completed

import google.generativeai as genai

logger = logging.getLogger(__name__)


@dataclass
class AudioChunk:
    path: Path
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _guess_language(text: str) -> Optional[str]:
    total = len(text) or 1
    # 日语假名检测 (平假名 + 片假名)
    hiragana = sum(1 for ch in text if '\u3040' <= ch <= '\u309f')
    katakana = sum(1 for ch in text if '\u30a0' <= ch <= '\u30ff')
    jp_kana = hiragana + katakana
    # 汉字 (中日共用)
    kanji = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
    # 英文字母
    en = sum(1 for ch in text if (ch.isascii() and ch.isalpha()))

    # 如果有假名，基本可以确定是日语
    if jp_kana / total > 0.05:
        return 'ja'
    # 如果只有汉字没有假名，判定为中文
    if kanji / total > 0.2:
        return 'zh'
    if en / total > 0.2:
        return 'en'
    return None


class ObsidianTranscriber:
    """基于 Gemini File API 的转写器。

    思路：
    - 使用 File API 上传音频（支持最大 2GB / 8.4 小时）；
    - 如果音频超过 8 小时，才进行切片处理；
    - 通过 google-generativeai 调用模型进行转写；
    - 仅返回纯文本；最后拼接为一份完整的逐字稿。
    """

    # File API 支持的最大音频时长（秒）：8.4 小时 = 30240 秒，保守取 8 小时
    MAX_AUDIO_DURATION = 8 * 60 * 60  # 28800 秒

    def __init__(self, segment_seconds: int = 28800, parallelism: Optional[int] = None):
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise RuntimeError('未设置 GEMINI_API_KEY')
        genai.configure(api_key=api_key)
        self.model_name = os.getenv('GEMINI_MODEL', 'gemini-3-pro-preview')
        # google-generativeai 期待短名称
        if self.model_name.startswith('models/'):
            self.model_name = self.model_name.split('/', 1)[-1]
        self.segment_seconds = segment_seconds
        # 并行度：优先读取环境变量 TRANSCRIBE_CONCURRENCY/OBSIDIAN_CONCURRENCY
        if parallelism is None:
            par_env = os.getenv('TRANSCRIBE_CONCURRENCY') or os.getenv('OBSIDIAN_CONCURRENCY')
            try:
                self.parallelism = int(par_env) if par_env else 0
            except Exception:
                self.parallelism = 0
        else:
            self.parallelism = int(parallelism)
        # 合理默认：0或<1 则根据CPU与网络取一个小值（例如3）
        if self.parallelism < 1:
            cpu_default = os.cpu_count() or 4
            self.parallelism = min(6, max(3, cpu_default // 2 or 1))

        self._system_instruction = (
            'You are a professional multilingual transcriber. Your task is to transcribe the audio file VERBATIM (word-for-word) into text.\n\n'
            '**CRITICAL REQUIREMENTS:**\n'
            '- **TRANSCRIBE THE ENTIRE AUDIO FROM START TO FINISH.** Do NOT skip, truncate, or omit any part.\n'
            '- **DO NOT SUMMARIZE.** Every single word must be transcribed.\n'
            '- **OUTPUT MUST BE IN THE SAME LANGUAGE AS SPOKEN IN THE AUDIO.** NEVER translate to any other language.\n'
            '- If the audio is long, you MUST continue transcribing until the very end. Never stop early.\n\n'
            '**GUIDELINES:**\n'
            '1. **Languages:** The audio may contain **Mandarin Chinese**, **English**, and/or **Japanese**.\n'
            '   - Transcribe exactly as spoken in the original language.\n'
            '   - **DO NOT TRANSLATE.** (e.g., If spoken in English, write in English; if in Japanese, write in Japanese Kanji/Kana).\n'
            '2. **Speaker Identification:** Identify different speakers. Label them as "**Speaker 1:**", "**Speaker 2:**", etc. Start a new paragraph every time the speaker changes.\n'
            '3. **Accuracy:** Do not correct grammar. Do not paraphrase. Include every detail, every word, every sentence.\n'
            '4. **Format:** Output plain text with clear paragraph breaks.\n'
            '5. **Noise:** Ignore non-speech sounds (like [laughter], [silence], [typing sounds]).\n\n'
            'Begin transcription now and continue until the audio ends.'
        )
        self._transcribe_prompt = (
            'Transcribe this ENTIRE audio file from beginning to end. '
            'Do NOT skip or truncate any part. Do NOT summarize. '
            'Include every single word spoken. Output only the complete transcript text.'
        )
        self._generation_config = genai.types.GenerationConfig(
            temperature=0.0,
            response_mime_type='text/plain',
            max_output_tokens=65536,
        )
        self._model_lock = Lock()
        self._max_models = max(1, self.parallelism)
        self._model_queue: Queue = Queue(maxsize=self._max_models)
        self._models_created = 0
        self._prime_model()

    def _ffprobe_duration(self, path: Path) -> float:
        try:
            out = subprocess.check_output([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', str(path)
            ]).decode().strip()
            return float(out) if out else 0.0
        except Exception:
            return 0.0

    def _split_audio(self, audio_path: Path) -> tuple[List[AudioChunk], Path]:
        """静音对齐的分片：尽量以 segment_seconds 为目标，优先在±5s 静音点切分。返回(片段信息列表, 工作目录)。"""
        workdir = Path(tempfile.mkdtemp(prefix='obs_work_', dir=str(audio_path.parent)))
        norm_wav = workdir / 'normalized.wav'
        # 规范化为 16kHz/mono WAV
        cmd_norm = f"ffmpeg -hide_banner -loglevel error -y -i {shlex.quote(str(audio_path))} -ac 1 -ar 16000 {shlex.quote(str(norm_wav))}"
        subprocess.check_call(cmd_norm, shell=True)

        duration = self._ffprobe_duration(norm_wav)
        if duration <= 0:
            raise RuntimeError('无法探测音频时长')

        # 使用 silencedetect 检测静音区间（阈值约 -30dB，窗口 0.3s）
        cmd_sil = (
            f"ffmpeg -hide_banner -nostats -i {shlex.quote(str(norm_wav))} "
            f"-af silencedetect=noise=-30dB:d=0.3 -f null - 2>&1"
        )
        try:
            out = subprocess.check_output(cmd_sil, shell=True, stderr=subprocess.STDOUT).decode('utf-8', 'ignore')
        except subprocess.CalledProcessError as e:
            out = e.output.decode('utf-8', 'ignore') if e.output else ''

        # 解析静音起止
        silence_points: List[float] = []
        for line in out.splitlines():
            m = re.search(r"silence_(start|end):\s*([0-9.]+)", line)
            if m:
                t = float(m.group(2))
                silence_points.append(t)
        silence_points = sorted(set(silence_points))

        # 根据目标分割点寻找±5s 内最近静音
        MAX = self.segment_seconds
        SEARCH = 5.0
        MIN_SEG = 1.0
        cuts: List[Tuple[float, float]] = []
        start = 0.0
        while start < duration:
            desired = start + MAX
            if desired >= duration:
                end = duration
            else:
                # 找最近静音
                cand = [t for t in silence_points if (desired-SEARCH) <= t <= (desired+SEARCH)]
                if cand:
                    end = min(cand, key=lambda t: abs(t - desired))
                    if end - start < MIN_SEG:
                        end = min(desired, duration)
                else:
                    end = min(desired, duration)
            if end - start >= MIN_SEG:
                cuts.append((start, end))
            start = end

        # 生成片段
        outdir = workdir / 'chunks'
        outdir.mkdir(parents=True, exist_ok=True)
        files: List[AudioChunk] = []
        if not cuts:
            raise RuntimeError('音频切分失败，未生成片段')

        if len(cuts) == 1 and abs(cuts[0][0]) < 1e-3 and abs(cuts[0][1] - duration) < 1e-3:
            target = outdir / 'chunk_001.wav'
            shutil.copy2(norm_wav, target)
            files.append(AudioChunk(target, cuts[0][0], cuts[0][1]))
            return files, workdir

        segment_points = ','.join(f"{end:.3f}" for _, end in cuts[:-1])
        cmd_cut = [
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-i', str(norm_wav),
            '-f', 'segment',
            '-segment_times', segment_points,
            '-segment_start_number', '1',
            '-reset_timestamps', '1',
            '-c', 'copy',
            str(outdir / 'chunk_%03d.wav'),
        ]
        subprocess.check_call(cmd_cut)

        produced = sorted(outdir.glob('chunk_*.wav'))
        if len(produced) != len(cuts):
            raise RuntimeError(f'分片数量不匹配，期望 {len(cuts)} 实际 {len(produced)}')

        ordered: List[AudioChunk] = []
        for idx, src in enumerate(produced, 1):
            start, end = cuts[idx - 1]
            ordered.append(AudioChunk(src, start, end))
        return ordered, workdir

    def _get_mime_type(self, path: Path) -> str:
        """根据文件扩展名返回正确的 MIME 类型。"""
        ext = path.suffix.lower()
        mime_map = {
            '.wav': 'audio/wav',
            '.mp3': 'audio/mpeg',
            '.m4a': 'audio/mp4',
            '.aac': 'audio/aac',
            '.ogg': 'audio/ogg',
            '.flac': 'audio/flac',
            '.webm': 'audio/webm',
        }
        return mime_map.get(ext, 'audio/mp4')  # 默认使用 audio/mp4

    def _gen_text(self, chunk: AudioChunk) -> str:
        """使用 File API 上传音频并转写（支持最大 2GB / 8.4 小时）。"""
        model = self._acquire_model()
        uploaded = None
        try:
            # 优先使用 File API（支持更大文件，最大 2GB）
            uploaded = genai.upload_file(path=str(chunk.path))
            # 必须同时传递音频文件和文本提示词
            resp = model.generate_content(
                [uploaded, self._transcribe_prompt],
                generation_config=self._generation_config
            )
            return self._extract(resp)
        except Exception as e:
            logger.warning(f'File API 失败，尝试内联方式: {chunk.path.name}: {e}')
            # Fallback: 内联数据方式（限制 20MB）
            try:
                with chunk.path.open('rb') as f:
                    data = f.read()
                # 使用正确的 MIME 类型
                mime_type = self._get_mime_type(chunk.path)
                resp = model.generate_content(
                    [{"mime_type": mime_type, "data": data}, self._transcribe_prompt],
                    generation_config=self._generation_config
                )
                return self._extract(resp)
            except Exception as e2:
                logger.error(f'内联方式也失败: {chunk.path.name}: {e2}')
                return ''
        finally:
            self._release_model(model)
            # 清理上传的文件（File API 文件会保留 2 天）
            if uploaded:
                try:
                    genai.delete_file(uploaded.name)
                except Exception:
                    pass

    def _build_model(self):
        return genai.GenerativeModel(self.model_name, system_instruction=self._system_instruction)

    def _prime_model(self):
        model = self._build_model()
        self._model_queue.put(model)
        self._models_created = 1

    def _acquire_model(self):
        try:
            return self._model_queue.get_nowait()
        except Empty:
            with self._model_lock:
                if self._models_created < self._max_models:
                    model = self._build_model()
                    self._models_created += 1
                    return model
        return self._model_queue.get()

    def _release_model(self, model):
        try:
            self._model_queue.put_nowait(model)
        except Exception:
            # Queue may be full if models were created opportunistically; drop gracefully.
            pass

    def _extract(self, resp) -> str:
        try:
            acc = []
            for cand in getattr(resp, 'candidates', []) or []:
                content = getattr(cand, 'content', None)
                parts = getattr(content, 'parts', None)
                if parts:
                    for p in parts:
                        t = getattr(p, 'text', None)
                        if t:
                            acc.append(t)
            return '\n'.join(acc).strip()
        except Exception:
            return ''

    def _fmt_duration(self, seconds: float) -> str:
        try:
            m = int(seconds // 60)
            s = int(round(seconds - m * 60))
            if s == 60:
                m += 1
                s = 0
            return f"{m} min {s} s"
        except Exception:
            return f"{seconds:.1f}s"

    def _fmt_size(self, size_bytes: int) -> str:
        try:
            mb = size_bytes / (1024 * 1024)
            return f"{mb:.1f} MB"
        except Exception:
            return f"{size_bytes} bytes"

    def transcribe(self, audio_path: Path, language: Optional[str] = None) -> Tuple[str, Optional[str]]:
        p = Path(audio_path)
        if not p.exists():
            raise FileNotFoundError(f'音频文件不存在: {p}')
        size = p.stat().st_size
        dur = self._ffprobe_duration(p)
        logger.info(f"[obsidian] 文件: {p.name}, 大小: {self._fmt_size(size)}, 时长: {self._fmt_duration(dur)}, 模型: {self.model_name}")

        # 如果音频时长在限制内，直接上传整个文件，不切片
        if dur <= self.MAX_AUDIO_DURATION and dur <= self.segment_seconds:
            logger.info(f"[obsidian] 音频时长 {self._fmt_duration(dur)} <= 8小时，直接上传不切片")
            workdir = Path(tempfile.mkdtemp(prefix='obs_work_', dir=str(p.parent)))
            # 创建单个 chunk 代表整个文件
            chunks = [AudioChunk(p, 0.0, dur)]
        else:
            chunks, workdir = self._split_audio(p)
            logger.info(f"[obsidian] 切片完成，共 {len(chunks)} 段，准备并行转写（并行度={self.parallelism}）")

        texts_by_index: dict[int, str] = {}
        # 在线程池中并行处理每个分片，保持输出顺序
        with ThreadPoolExecutor(max_workers=self.parallelism) as ex:
            futures = {}
            for idx, chunk in enumerate(chunks, 1):
                logger.info(
                    f"[obsidian] 排队分片 {idx}/{len(chunks)}: {chunk.path.name} ~{self._fmt_duration(chunk.duration)}"
                )
                fut = ex.submit(self._gen_text, chunk)
                futures[fut] = idx

            done_count = 0
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    t = fut.result()
                except Exception as e:
                    logger.error(f"[obsidian] 分片 {idx} 处理异常: {e}")
                    t = ''
                if t:
                    texts_by_index[idx] = t
                else:
                    logger.warning(f"[obsidian] 分片无文本输出: chunk_{idx:03d}.wav")
                done_count += 1
                if done_count % max(1, len(chunks)//10) == 0 or done_count == len(chunks):
                    logger.info(f"[obsidian] 并行转写进度: {done_count}/{len(chunks)} 完成")

        # 按原顺序合并
        texts_ordered: List[str] = [texts_by_index.get(i, '') for i in range(1, len(chunks)+1)]
        body = '\n\n'.join([t for t in texts_ordered if t]).strip()
        det = language or _guess_language(body)
        # 返回 Markdown 与语言检测
        lines = [
            '# Video Transcription', '',
            f'**Detected Language:** {det or "unknown"}',
            f'**Model:** {self.model_name}', '',
            '## Transcription Content', '',
            body, ''
        ]
        # 清理工作目录
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass
        return ('\n'.join(lines), det)

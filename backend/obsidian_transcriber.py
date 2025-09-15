import os
import logging
import shlex
import subprocess
import tempfile
import re
import shutil
from pathlib import Path
from typing import Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor, as_completed

import google.generativeai as genai

logger = logging.getLogger(__name__)


def _guess_language(text: str) -> Optional[str]:
    total = len(text) or 1
    zh = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
    en = sum(1 for ch in text if (ch.isascii() and ch.isalpha()))
    if zh / total > 0.2:
        return 'zh'
    if en / total > 0.2:
        return 'en'
    return None


class ObsidianTranscriber:
    """基于已验证的“分片 + 顺序上传”思路的转写器。

    思路：
    - 保持下载音频不变；
    - 使用 ffmpeg 切分为固定时长 wav 片段（默认 30s）；
    - 逐片通过 google-generativeai 调用模型（默认 gemini-2.5-pro 或 .env 中的配置）；
    - 仅返回纯文本；最后拼接为一份完整的逐字稿。
    """

    def __init__(self, segment_seconds: int = 300, parallelism: Optional[int] = None):
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise RuntimeError('未设置 GEMINI_API_KEY')
        genai.configure(api_key=api_key)
        self.model_name = (os.getenv('GEMINI_TRANSCRIBE_MODEL')
                           or os.getenv('GEMINI_MODEL')
                           or 'gemini-2.5-pro')
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
            self.parallelism = 3

    def _ffprobe_duration(self, path: Path) -> float:
        try:
            out = subprocess.check_output([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', str(path)
            ]).decode().strip()
            return float(out) if out else 0.0
        except Exception:
            return 0.0

    def _split_audio(self, audio_path: Path) -> tuple[List[Path], Path]:
        """静音对齐的分片：尽量以 segment_seconds 为目标，优先在±5s 静音点切分。返回(片段列表, 工作目录)。"""
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
        files: List[Path] = []
        for idx, (ss, ee) in enumerate(cuts, 1):
            outp = outdir / f'chunk_{idx:03d}.wav'
            cmd_cut = (
                f"ffmpeg -hide_banner -loglevel error -y -ss {ss:.3f} -to {ee:.3f} -i {shlex.quote(str(norm_wav))} "
                f"-ac 1 -ar 16000 {shlex.quote(str(outp))}"
            )
            subprocess.check_call(cmd_cut, shell=True)
            files.append(outp)
        if not files:
            raise RuntimeError('音频切分失败，未生成片段')
        return files, workdir

    def _gen_text(self, wav_path: Path) -> str:
        # 仅返回纯文本（无前缀标记），更接近“逐字稿”
        instr = (
            'You transcribe audio to plain text. Output only the verbatim transcript. '
            'If the language is Chinese, use Simplified Chinese characters. No headings, no preface.'
        )
        model = genai.GenerativeModel(self.model_name, system_instruction=instr)
        with wav_path.open('rb') as f:
            data = f.read()
        # 优先 audio-first，再 prompt-first
        for parts in ([{"mime_type": "audio/wav", "data": data}],
                      ['Transcribe the audio. Output plain text only.', {"mime_type": "audio/wav", "data": data}]):
            try:
                resp = model.generate_content(parts, generation_config=genai.types.GenerationConfig(
                    temperature=0.0, response_mime_type='text/plain', max_output_tokens=4096
                ))
                txt = self._extract(resp)
                if txt:
                    return txt
            except Exception as e:
                logger.info(f'分片生成失败重试: {wav_path.name}: {e}')
                continue
        # 尝试上传文件路径
        uploaded = genai.upload_file(path=str(wav_path))
        resp = model.generate_content([uploaded], generation_config=genai.types.GenerationConfig(
            temperature=0.0, response_mime_type='text/plain', max_output_tokens=4096
        ))
        return self._extract(resp)

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

        chunks, workdir = self._split_audio(p)
        logger.info(f"[obsidian] 切片完成，共 {len(chunks)} 段，准备并行转写（并行度={self.parallelism}）")

        texts_by_index: dict[int, str] = {}
        # 在线程池中并行处理每个分片，保持输出顺序
        with ThreadPoolExecutor(max_workers=self.parallelism) as ex:
            futures = {}
            for i, c in enumerate(chunks, 1):
                c_dur = self._ffprobe_duration(c)
                logger.info(f"[obsidian] 排队分片 {i}/{len(chunks)}: {c.name} ~{self._fmt_duration(c_dur)}")
                fut = ex.submit(self._gen_text, c)
                futures[fut] = i

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

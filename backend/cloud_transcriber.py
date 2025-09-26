import os
import logging
from pathlib import Path
from typing import Optional, Tuple

import google.generativeai as genai
import subprocess
import shlex
import tempfile

logger = logging.getLogger(__name__)


class CloudTranscriber:
    """Gemini 云端转写（使用 google-generativeai）。"""

    def __init__(self, model: Optional[str] = None):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("未设置 GEMINI_API_KEY，无法进行云端语音转写")

        genai.configure(api_key=api_key)

        # e.g., gemini-2.5-pro (google-generativeai expects plain names, not 'models/<name>')
        raw = model or os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
        self.model = raw.split("/", 1)[-1] if raw.startswith("models/") else raw
        logger.info(f"Gemini STT model: {self.model}")

    def _format_time(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        response_format: str = "plain",
    ) -> Tuple[str, Optional[str]]:
        """
        调用 OpenAI 进行语音转写。

        Returns: (markdown_transcript, detected_language)
        """
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"音频文件不存在: {path}")

        logger.info(f"上传音频进行转写: {path}")

        # 基本健康检查：文件大小与时长
        try:
            size = path.stat().st_size
        except Exception:
            size = 0
        logger.info(f"音频文件大小: {size} bytes")
        if size < 10 * 1024:  # <10KB 视为无效
            raise RuntimeError(f"音频文件过小，可能下载失败或无音频数据: {path}")

        def _probe_duration(p: Path) -> float:
            try:
                out = subprocess.check_output(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(p)]
                ).decode().strip()
                return float(out) if out else 0.0
            except Exception:
                return 0.0

        duration = _probe_duration(path)
        logger.info(f"音频时长: {duration:.2f}s")
        if duration < 1.0:
            raise RuntimeError(f"音频时长异常（<1s），可能下载失败或文件损坏: {path}")

        # 识别 mime 类型
        mime = "audio/mp4"
        suf = path.suffix.lower()
        if suf in [".mp3"]:
            mime = "audio/mpeg"
        elif suf in [".wav"]:
            mime = "audio/wav"
        elif suf in [".m4a", ".mp4"]:
            mime = "audio/mp4"
        elif suf in [".webm"]:
            mime = "audio/webm"

        with path.open("rb") as f:
            audio_bytes = f.read()

        # 构建提示
        prompt = (
            "You are a precise transcription assistant. Detect the language, then transcribe the audio verbatim.\n"
            "Output format strictly as follows:\n"
            "DETECTED_LANG: <lang_code>\n\n"
            "<transcript text in the original language>\n"
        )

        # 依次尝试候选模型名（plain 与 'models/' 前缀，及常见备选）
        user_name = self.model
        candidates = []
        # 用户指定名（plain 与带前缀）
        if user_name:
            candidates.append(user_name)
            pref = f"models/{user_name}" if not user_name.startswith("models/") else user_name
            if pref not in candidates:
                candidates.append(pref)
        # 通用备选（兼容不同区域或可用性）
        for base in ["gemini-2.5-pro", "gemini-2.0-flash", "gemini-1.5-pro"]:
            if base not in candidates:
                candidates.append(base)
            pref2 = f"models/{base}"
            if pref2 not in candidates:
                candidates.append(pref2)

        resp = None
        last_err = None
        gen_config = genai.types.GenerationConfig(
            temperature=0.0,
            max_output_tokens=8192,
            response_mime_type="text/plain",
        )

        # Optional: relax safety blocks for transcription if configured
        safety_settings = None
        try:
            if os.getenv("GEMINI_SAFETY_BLOCK_NONE", "true").lower() in ("1", "true", "yes", "on"):
                HCat = genai.types.HarmCategory
                HB = genai.types.HarmBlockThreshold
                safety_settings = [
                    genai.types.SafetySetting(category=HCat.HARM_CATEGORY_HARASSMENT, threshold=HB.BLOCK_NONE),
                    genai.types.SafetySetting(category=HCat.HARM_CATEGORY_HATE_SPEECH, threshold=HB.BLOCK_NONE),
                    genai.types.SafetySetting(category=HCat.HARM_CATEGORY_SEXUAL_CONTENT, threshold=HB.BLOCK_NONE),
                    genai.types.SafetySetting(category=HCat.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=HB.BLOCK_NONE),
                    genai.types.SafetySetting(category=HCat.HARM_CATEGORY_VIOLENCE, threshold=HB.BLOCK_NONE),
                ]
        except Exception:
            safety_settings = None
        for name in candidates:
            # 两种输入顺序尝试
            for order_name, parts in (
                ("audio-first", [ {"mime_type": mime, "data": audio_bytes}, prompt ]),
                ("prompt-first", [ prompt, {"mime_type": mime, "data": audio_bytes} ]),
            ):
                try:
                    logger.info(f"尝试转写模型: {name}，顺序: {order_name}")
                    model = genai.GenerativeModel(name, system_instruction="You are a transcription tool. Always return text. This is for compliance transcription only.")
                    resp = model.generate_content(parts, generation_config=gen_config, safety_settings=safety_settings)
                    break
                except Exception as e:
                    last_err = e
                    resp = None
                    continue
            if resp is not None:
                break
            # upload_file 方案
            try:
                logger.info(f"尝试通过 upload_file 使用模型: {name}")
                up = genai.upload_file(path=str(path))
                model = genai.GenerativeModel(name, system_instruction="You are a transcription tool. Always return text. This is for compliance transcription only.")
                resp = model.generate_content([up, prompt], generation_config=gen_config, safety_settings=safety_settings)
                break
            except Exception as e:
                msg = str(e)
                last_err = e
                if "GenerateContentRequest.model" in msg or "not found" in msg or "InvalidArgument" in msg:
                    logger.warning(f"模型不可用或格式错误，切换候选: {name} -> 下一个")
                    continue
                raise
        if resp is None:
            # 尝试分片转写作为兜底
            logger.warning("直接转写失败，尝试分片转写…")
            text, det = self._chunked_transcribe(path, candidates, prompt, gen_config, safety_settings, mime)
            if text:
                return self._format_markdown(text, det)
            raise last_err or RuntimeError("Gemini transcription failed: no usable model (after chunking)")

        # Extract text without using resp.text (avoid quick accessor errors)
        text = self._extract_text(resp)
        if not text:
            # 尝试分片转写作为兜底
            logger.warning("返回内容为空，尝试分片转写…")
            text2, det2 = self._chunked_transcribe(path, candidates, prompt, gen_config, safety_settings, mime)
            if text2:
                return self._format_markdown(text2, det2)
            # Surface safety reasons if present
            try:
                reasons = []
                for cand in getattr(resp, "candidates", []) or []:
                    fr = getattr(cand, "finish_reason", None)
                    if fr is not None:
                        reasons.append(f"finish_reason={fr}")
                    for r in getattr(cand, "safety_ratings", []) or []:
                        reasons.append(f"{getattr(r,'category',None)}:{getattr(r,'probability',None)}")
                raise RuntimeError("Gemini returned no text. " + "; ".join(reasons))
            except Exception:
                raise RuntimeError("Gemini returned no text and provided no candidates.")
        detected_language = None
        if text.startswith("DETECTED_LANG:"):
            first_line, _, rest = text.partition("\n")
            detected_language = first_line.split(":", 1)[-1].strip()
            body = rest.lstrip("\n")
        else:
            body = text

        # 组装 Markdown
        lines = [
            "# Video Transcription",
            "",
            f"**Detected Language:** {detected_language or 'unknown'}",
            f"**Model:** {self.model}",
            "",
            "## Transcription Content",
            "",
            body,
            "",
        ]

        markdown = "\n".join(lines)
        return markdown, detected_language

    def _format_markdown(self, body_text: str, detected_language: Optional[str]) -> Tuple[str, Optional[str]]:
        lines = [
            "# Video Transcription",
            "",
            f"**Detected Language:** {detected_language or 'unknown'}",
            f"**Model:** {self.model}",
            "",
            "## Transcription Content",
            "",
            body_text,
            "",
        ]
        return "\n".join(lines), detected_language

    def _chunked_transcribe(self, path: Path, candidates, prompt, gen_config, safety_settings, mime: str,
                             seg_seconds: int = 60) -> Tuple[Optional[str], Optional[str]]:
        """分片转写兜底：将音频切分为小段逐段转写并拼接。"""
        try:
            tmpdir = Path(tempfile.mkdtemp(prefix="chunks_", dir=str(path.parent)))
        except Exception:
            tmpdir = path.parent / f"chunks_{os.getpid()}"
            tmpdir.mkdir(parents=True, exist_ok=True)

        # 切分为 wav 片段，避免封装问题
        outpat = tmpdir / "chunk_%03d.wav"
        cmd = f"ffmpeg -hide_banner -loglevel error -y -i {shlex.quote(str(path))} -ac 1 -ar 16000 -f segment -segment_time {seg_seconds} {shlex.quote(str(outpat))}"
        try:
            subprocess.check_call(cmd, shell=True)
        except Exception as e:
            logger.error(f"分片失败: {e}")
            return None, None

        chunk_files = sorted(tmpdir.glob("chunk_*.wav"))
        if not chunk_files:
            return None, None

        detected_language = None
        texts = []
        for c in chunk_files:
            try:
                with c.open("rb") as f:
                    data = f.read()
                # 与主流程一致：尝试多个候选模型
                resp = None
                for name in candidates:
                    try:
                        model = genai.GenerativeModel(name, system_instruction="You are a transcription tool. Always return text.")
                        try:
                            resp = model.generate_content([
                                {"mime_type": "audio/wav", "data": data},
                                prompt,
                            ], generation_config=gen_config, safety_settings=safety_settings)
                        except Exception:
                            resp = model.generate_content([
                                prompt,
                                {"mime_type": "audio/wav", "data": data},
                            ], generation_config=gen_config, safety_settings=safety_settings)
                        break
                    except Exception as e:
                        msg = str(e)
                        if "GenerateContentRequest.model" in msg or "not found" in msg or "InvalidArgument" in msg:
                            continue
                        raise
                if resp is None:
                    continue
                t = self._extract_text(resp)
                if t:
                    # 提取 DETECTED_LANG
                    if detected_language is None and t.startswith("DETECTED_LANG:"):
                        first_line, _, rest = t.partition("\n")
                        detected_language = first_line.split(":", 1)[-1].strip()
                        t = rest.lstrip("\n")
                    texts.append(t)
            except Exception as e:
                logger.warning(f"片段转写失败 {c.name}: {e}")
                continue
        if not texts:
            return None, None
        return "\n\n".join(texts), detected_language

    def _extract_text(self, resp) -> str:
        """从 candidates/parts 提取文本，避免使用 resp.text 快捷访问器。"""
        try:
            acc = []
            for cand in getattr(resp, "candidates", []) or []:
                content = getattr(cand, "content", None)
                parts = getattr(content, "parts", None)
                if parts:
                    for p in parts:
                        t = getattr(p, "text", None)
                        if t:
                            acc.append(t)
            return "\n".join(acc).strip()
        except Exception:
            return ""

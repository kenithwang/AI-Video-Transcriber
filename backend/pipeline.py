import asyncio
import logging
import uuid
from pathlib import Path
import os
from typing import Awaitable, Callable, Optional, Tuple

from .video_processor import VideoProcessor
from .obsidian_transcriber import ObsidianTranscriber
from .summarizer import Summarizer
from .translator import Translator

logger = logging.getLogger(__name__)


def _sanitize_title_for_filename(title: str) -> str:
    """Sanitize video title for safe filenames."""
    import re
    if not title:
        return "untitled"
    safe = re.sub(r"[^\w\-\s]", "", title)
    safe = re.sub(r"\s+", "_", safe).strip("._-")
    return safe[:80] or "untitled"


async def process_video(
    url: str,
    summary_language: str,
    temp_dir: Path,
    on_update: Optional[Callable[[dict], Awaitable[None]]] = None,
    skip_optimize: bool = False,
    skip_translate: bool = False,
    skip_summary: bool = True,
    keep_audio: bool = False,
) -> dict:
    """
    Full processing pipeline used by CLI: download → transcribe → maybe translate → (optional summary) → write files.

    Returns a result dict with output file names and detected language.
    """
    temp_dir.mkdir(parents=True, exist_ok=True)

    def emit(update: dict):
        if on_update:
            return on_update(update)
        return asyncio.sleep(0)

    short_id = uuid.uuid4().hex[:6]
    status = {
        "status": "processing",
        "progress": 0,
        "message": "starting",
        "url": url,
    }
    await emit(status)

    video_processor = VideoProcessor()
    # 使用 Obsidian 风格分片转写（默认 300s 静音对齐）
    transcriber = ObsidianTranscriber(segment_seconds=300)
    summarizer = Summarizer()
    translator = Translator()

    # 环境开关：如果设置 NO_TRANSLATE/DISABLE_TRANSLATION，则跳过翻译
    def _env_flag(name: str, default: str = "0") -> bool:
        val = os.getenv(name, default)
        if val is None:
            return False
        return str(val).strip().lower() in ("1", "true", "yes", "y", "on")
    env_no_translate = _env_flag("NO_TRANSLATE") or _env_flag("DISABLE_TRANSLATION")

    # 1) Download + convert
    status.update({"progress": 10, "message": "downloading video..."})
    await emit(status)
    audio_path, video_title = await video_processor.download_and_convert(url, temp_dir)

    status.update({"progress": 35, "message": "video downloaded; transcribing..."})
    await emit(status)

    # 2) Transcribe
    # OpenAI 云端转写（同步调用，封装为线程避免阻塞）
    import asyncio as _asyncio
    def _do_transcribe():
        return transcriber.transcribe(Path(audio_path))
    raw_script, detected_language = await _asyncio.to_thread(_do_transcribe)

    # Persist raw whisper output for reference
    safe_title = _sanitize_title_for_filename(video_title)
    raw_md_filename = f"raw_{safe_title}_{short_id}.md"
    raw_md_path = temp_dir / raw_md_filename
    with raw_md_path.open("w", encoding="utf-8") as f:
        f.write((raw_script or "") + f"\n\nsource: {url}\n")

    # 3) Use raw transcript directly (skip optimization)
    script = raw_script
    script_with_title = f"# {video_title}\n\n{script}\n\nsource: {url}\n"

    # detected_language 已由云端返回；如无则保持 None

    # 4) Conditional translation
    translation_filename = None
    if (not skip_translate) and (not env_no_translate) and detected_language and translator.should_translate(detected_language, summary_language):
        await emit({**status, "progress": 65, "message": "generating translation..."})
        translation_content = await translator.translate_text(script, summary_language, detected_language)
        translation_with_title = f"# {video_title}\n\n{translation_content}\n\nsource: {url}\n"
        translation_filename = f"translation_{safe_title}_{short_id}.md"
        (temp_dir / translation_filename).write_text(translation_with_title, encoding="utf-8")

    # 5) Summarize
    summary_filename = None
    if not skip_summary:
        await emit({**status, "progress": 80, "message": "generating summary..."})
        summary = await summarizer.summarize(script, summary_language, video_title)
        summary_with_source = summary + f"\n\nsource: {url}\n"

    # 6) Persist files
    # transcript file
    tmp_script_path = temp_dir / f"transcript_{short_id}.md"
    tmp_script_path.write_text(script_with_title, encoding="utf-8")
    transcript_filename = f"transcript_{safe_title}_{short_id}.md"
    transcript_path = temp_dir / transcript_filename
    try:
        tmp_script_path.rename(transcript_path)
    except Exception:
        transcript_path = tmp_script_path  # fallback

    # summary file
    if not skip_summary:
        summary_filename = f"summary_{safe_title}_{short_id}.md"
        (temp_dir / summary_filename).write_text(summary_with_source, encoding="utf-8")

    # Optional cleanup of downloaded audio
    audio_deleted = False
    if not keep_audio:
        try:
            Path(audio_path).unlink(missing_ok=True)
            audio_deleted = True
        except Exception:
            audio_deleted = False

    # 清理 temp 下的非 .md 临时文件/目录（仅音视频及切片）
    try:
        import shutil
        for entry in temp_dir.iterdir():
            if entry.is_file():
                if entry.suffix.lower() in ('.m4a', '.mp3', '.wav', '.webm', '.mp4'):
                    try:
                        entry.unlink()
                    except Exception:
                        pass
            elif entry.is_dir():
                name = entry.name.lower()
                if name.startswith('obs_work_') or name.startswith('chunks'):
                    try:
                        shutil.rmtree(entry, ignore_errors=True)
                    except Exception:
                        pass
    except Exception:
        pass

    await emit({**status, "progress": 100, "message": "completed", "status": "completed"})

    return {
        "status": "completed",
        "video_title": video_title,
        "detected_language": detected_language,
        "raw_script_file": raw_md_filename,
        "transcript_file": transcript_filename,
        "summary_file": summary_filename,
        "translation_file": translation_filename,
        "short_id": short_id,
        "audio_file": None if audio_deleted else audio_path,
        "audio_deleted": audio_deleted,
    }

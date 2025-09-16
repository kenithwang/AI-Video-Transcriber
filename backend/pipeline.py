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
from .editor import Editor

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
    edit_mode: Optional[str] = None,
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

    async def _write_file(path: Path, content: str) -> None:
        await asyncio.to_thread(path.write_text, content, encoding="utf-8")

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
    editor = Editor()

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
    await _write_file(raw_md_path, (raw_script or "") + f"\n\nsource: {url}\n")

    # 3) Use raw transcript directly (skip optimization)
    script = raw_script
    script_with_title = f"# {video_title}\n\n{script}\n\nsource: {url}\n"

    # detected_language 已由云端返回；如无则保持 None

    # 4) Conditional translation
    translation_task = None
    translation_filename = None
    if (not skip_translate) and (not env_no_translate) and detected_language and translator.should_translate(detected_language, summary_language):
        await emit({**status, "progress": 65, "message": "generating translation..."})

        async def _generate_translation() -> Optional[str]:
            try:
                translation_content = await translator.translate_text(script, summary_language, detected_language)
                translation_with_title = f"# {video_title}\n\n{translation_content}\n\nsource: {url}\n"
                fname = f"translation_{safe_title}_{short_id}.md"
                await _write_file(temp_dir / fname, translation_with_title)
                return fname
            except Exception as exc:
                logger.error(f"translation failed: {exc}")
                return None

        translation_task = asyncio.create_task(_generate_translation())

    # 5) Summarize
    summary_task = None
    summary_filename = None
    if not skip_summary:
        await emit({**status, "progress": 80, "message": "generating summary..."})

        async def _generate_summary() -> Optional[str]:
            try:
                summary = await summarizer.summarize(script, summary_language, video_title)
                summary_with_source = summary + f"\n\nsource: {url}\n"
                fname = f"summary_{safe_title}_{short_id}.md"
                await _write_file(temp_dir / fname, summary_with_source)
                return fname
            except Exception as exc:
                logger.error(f"summary failed: {exc}")
                return None

        summary_task = asyncio.create_task(_generate_summary())

    # 6) Persist files
    # transcript file
    tmp_script_path = temp_dir / f"transcript_{short_id}.md"
    await _write_file(tmp_script_path, script_with_title)
    transcript_filename = f"transcript_{safe_title}_{short_id}.md"
    transcript_path = temp_dir / transcript_filename
    try:
        tmp_script_path.rename(transcript_path)
    except Exception:
        transcript_path = tmp_script_path  # fallback

    # 7) Optional Edit Note (use optimized transcript if present in future; currently use 'script')
    editnote_filename = None
    editnote_task = None
    if edit_mode:
        await emit({**status, "progress": 85, "message": f"generating edit note: {edit_mode}..."})

        async def _generate_edit_note() -> Optional[str]:
            try:
                edit_note = await editor.generate(edit_mode, script)
                fname = f"editnote_{edit_mode}_{safe_title}_{short_id}.md"
                await _write_file(temp_dir / fname, edit_note + f"\n\nsource: {url}\n")
                return fname
            except Exception as exc:
                logger.error(f"edit note failed: {exc}")
                return None

        editnote_task = asyncio.create_task(_generate_edit_note())

    if translation_task:
        translation_filename = await translation_task

    if summary_task:
        summary_filename = await summary_task

    if editnote_task:
        editnote_filename = await editnote_task
        if editnote_filename:
            await emit({**status, "progress": 95, "message": "edit note saved"})

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
        "editnote_file": editnote_filename,
        "short_id": short_id,
        "audio_file": None if audio_deleted else audio_path,
        "audio_deleted": audio_deleted,
    }

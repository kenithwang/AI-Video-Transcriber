import asyncio
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .video_processor import VideoProcessor
from .obsidian_transcriber import ObsidianTranscriber

logger = logging.getLogger(__name__)


def _create_emitter(on_update: Optional[Callable[[dict], Awaitable[None]]]):
    """创建进度回调封装函数。"""
    def emit(update: dict):
        if on_update:
            return on_update(update)
        return asyncio.sleep(0)
    return emit


async def _write_file(path: Path, content: str) -> None:
    """异步写入文件。"""
    await asyncio.to_thread(path.write_text, content, encoding="utf-8")


def _sanitize_title_for_filename(title: str, max_bytes: int = 200) -> str:
    """Sanitize video title for safe filenames.

    Truncates by byte length (not character count) to avoid
    'File name too long' errors with multi-byte characters (e.g. CJK).
    """
    import re
    if not title:
        return "untitled"
    safe = re.sub(r"[^\w\-\s]", "", title)
    safe = re.sub(r"\s+", "_", safe).strip("._-")
    if not safe:
        return "untitled"
    # Truncate to max_bytes without splitting multi-byte characters
    encoded = safe.encode("utf-8")
    if len(encoded) <= max_bytes:
        return safe
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated.rstrip("._-") or "untitled"


async def process_video(
    url: str,
    temp_dir: Path,
    on_update: Optional[Callable[[dict], Awaitable[None]]] = None,
    keep_audio: bool = False,
    *,
    segment_seconds: Optional[int] = None,
    parallelism: Optional[int] = None,
    video_info: Optional[dict] = None,
) -> dict:
    """
    Simplified processing pipeline used by CLI: download video, transcribe audio, and write raw/transcript files.

    Args:
        video_info: 预获取的视频元数据（可选），避免重复调用 yt-dlp。

    Returns a result dict with output file names and detected language.
    """
    temp_dir.mkdir(parents=True, exist_ok=True)
    emit = _create_emitter(on_update)

    short_id = uuid.uuid4().hex[:6]
    work_dir = temp_dir / f".work_{short_id}"
    status = {
        "status": "processing",
        "progress": 0,
        "message": "starting",
        "url": url,
    }
    await emit(status)

    video_processor = VideoProcessor()
    # 使用 File API 转写，默认不切片（8小时内直接上传）
    # segment_seconds 优先取显式参数，其次取环境变量，默认 28800（8小时）
    seg_env = os.getenv("SEGMENT_SECONDS") or os.getenv("OBSIDIAN_SEGMENT_SECONDS")
    seg_final: int
    if segment_seconds is not None:
        seg_final = int(segment_seconds)
    else:
        try:
            seg_final = int(seg_env) if seg_env else 28800
        except Exception:
            seg_final = 28800

    transcriber = ObsidianTranscriber(segment_seconds=seg_final, parallelism=parallelism)
    warnings: list[str] = []

    # 1) Download + convert
    status.update({"progress": 10, "message": "downloading video..."})
    await emit(status)
    audio_path, video_title = await video_processor.download_and_convert(url, work_dir, video_info=video_info)

    status.update({"progress": 35, "message": "video downloaded; transcribing..."})
    await emit(status)

    # 2) Transcribe
    # OpenAI 云端转写（同步调用，封装为线程避免阻塞）
    import asyncio as _asyncio
    def _do_transcribe():
        return transcriber.transcribe(Path(audio_path))
    raw_script, detected_language, transcribe_warnings = await _asyncio.to_thread(_do_transcribe)
    warnings.extend(transcribe_warnings)

    safe_title = _sanitize_title_for_filename(video_title)
    script_with_title = f"# {video_title}\n\n{raw_script}\n\nsource: {url}\n"

    # detected_language 已由云端返回；如无则保持 None

    # 4) Persist files
    # transcript file
    transcript_filename = f"transcript_{safe_title}_{short_id}.md"
    transcript_path = temp_dir / transcript_filename
    await _write_file(transcript_path, script_with_title)

    # Optional cleanup of downloaded audio and this job's private work directory.
    audio_deleted = False
    if not keep_audio:
        try:
            Path(audio_path).unlink(missing_ok=True)
            audio_deleted = True
        except Exception as e:
            logger.warning(f"删除音频文件失败: {audio_path}, 错误: {e}")
            audio_deleted = False
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception as e:
            logger.debug(f"清理工作目录失败: {work_dir}, 错误: {e}")
    else:
        try:
            audio_resolved = Path(audio_path).resolve(strict=False)
            for entry in work_dir.iterdir():
                if entry.is_file() and entry.suffix.lower() in ('.m4a', '.mp3', '.wav', '.webm', '.mp4'):
                    if entry.resolve(strict=False) == audio_resolved:
                        continue
                    entry.unlink(missing_ok=True)
        except Exception as e:
            logger.debug(f"清理当前任务多余媒体文件失败: {e}")

    final_status = {**status, "progress": 100, "status": "completed"}
    final_status["message"] = "completed (with warnings)" if warnings else "completed"
    await emit(final_status)

    return {
        "status": "completed",
        "video_title": video_title,
        "detected_language": detected_language,
        "transcript_file": transcript_filename,
        "short_id": short_id,
        "audio_file": None if audio_deleted else audio_path,
        "audio_deleted": audio_deleted,
        "warnings": warnings,
    }


async def process_transcript_input(
    transcript: str,
    temp_dir: Path,
    *,
    on_update: Optional[Callable[[dict], Awaitable[None]]] = None,
    video_title: Optional[str] = None,
    source_language: Optional[str] = None,
) -> dict:
    """处理现有转录文本，仅保存标准化转录文件。"""

    temp_dir.mkdir(parents=True, exist_ok=True)
    emit = _create_emitter(on_update)

    transcript = transcript or ""
    if not transcript.strip():
        raise ValueError("transcript content is empty")


    short_id = uuid.uuid4().hex[:6]
    safe_title = _sanitize_title_for_filename(video_title or "manual_transcript")

    status = {
        "status": "processing",
        "progress": 5,
        "message": "preparing transcript",
        "video_title": video_title or safe_title,
    }
    await emit(status)

    detected_language = (source_language or "").strip().lower() if source_language else None

    status.update({"progress": 15, "message": "transcript ready"})
    await emit(status)

    script_with_title = transcript if transcript.startswith("# ") else f"# {video_title or safe_title}\n\n{transcript}\n"

    warnings: list[str] = []

    # 写出整理后的转录
    transcript_filename = f"transcript_{safe_title}_{short_id}.md"
    transcript_path = temp_dir / transcript_filename
    await _write_file(transcript_path, script_with_title)

    final_status = {**status, "progress": 100, "status": "completed"}
    final_status["message"] = "completed (with warnings)" if warnings else "completed"
    await emit(final_status)

    return {
        "status": "completed",
        "video_title": video_title or safe_title,
        "detected_language": detected_language,
        "transcript_file": transcript_filename,
        "short_id": short_id,
        "warnings": warnings,
    }

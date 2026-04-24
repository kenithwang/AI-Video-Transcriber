"""
Channel subscription monitor.

Monitors configured YouTube/Bilibili channels for new videos
and processes them using the existing transcription pipeline.
"""

import json
import os
import re
import shutil
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

import requests
import yaml
import yt_dlp

# B站 API 请求间隔（秒），避免触发风控
BILIBILI_API_DELAY = 0.3

from .processed_store import ProcessedStore
from .sync_config import build_rclone_copy_command


# 简短摘要生成的 prompt
BRIEF_SUMMARY_PROMPT = """请根据以下视频转录内容，生成一个简短摘要（150-300字）。

要求：
1. 用简体中文书写
2. 概括视频的主要议题和核心观点
3. 保留关键人名、公司名、技术术语用英文
4. 不需要完整复述，只需要让读者快速了解视频讲了什么

转录内容：
{transcript}

请直接输出摘要，不需要任何前缀或解释。"""


@dataclass
class VideoDigestEntry:
    """Entry for video digest JSON output."""
    video_id: str
    title: str
    channel: str
    url: str
    timestamp: str
    summary: str = ""
    note_file: str = ""


@dataclass
class VideoDigestFailure:
    """Failed video entry for digest."""
    video_id: str
    title: str
    channel: str
    url: str
    timestamp: str
    error: str


@dataclass
class ChannelConfig:
    """Configuration for a single channel."""

    url: str
    name: Optional[str]
    enabled: bool
    lookback_hours: int
    note_mode: Optional[int] = None  # Note generation mode (1-7)


@dataclass
class VideoInfo:
    """Information about a video from a channel."""

    video_id: str
    url: str
    title: str
    channel_id: str
    channel_name: str
    upload_date: Optional[datetime]
    duration: int
    note_mode: Optional[int] = None  # Note generation mode from channel config
    live_status: Optional[str] = None  # is_upcoming, is_live, was_live, or None


class ChannelMonitor:
    """Monitors channels for new videos and processes them."""

    def __init__(self, config_path: Path, store_path: Optional[Path] = None):
        """
        Initialize the channel monitor.

        Args:
            config_path: Path to channels.yaml configuration file
            store_path: Optional override for processed videos store path
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()

        # Determine store path
        if store_path:
            self._store_path = Path(store_path)
        else:
            store_file = self.config.get("settings", {}).get(
                "processed_store", ".processed_videos.json"
            )
            self._store_path = self.config_path.parent / store_file

        self.store = ProcessedStore(self._store_path)

        # Load settings with defaults
        settings = self.config.get("settings", {})
        self.default_lookback_hours = settings.get("lookback_hours", 24)
        self.max_video_age_days = settings.get("max_video_age_days", 7)
        self.processing_delay = settings.get("processing_delay", 5)
        self.rate_limit_cooldown = settings.get("rate_limit_cooldown", 3600)

        # yt-dlp configuration
        self._cookie_file = os.getenv("YDL_COOKIEFILE")
        self._js_interpreter = os.getenv("YDL_JS_INTERPRETER") or shutil.which(
            "node"
        ) or shutil.which("nodejs")

        # Digest output path
        self._digest_path = Path.home() / ".video_digest.json"

        # Collect results for digest
        self._digest_processed: list[VideoDigestEntry] = []
        self._digest_failed: list[VideoDigestFailure] = []

    def _generate_brief_summary(self, transcript: str) -> str:
        """Generate a brief summary (150-300 chars) from transcript."""
        from google import genai
        from google.genai import types

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return ""

        client = genai.Client(api_key=api_key)
        model_name = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
        if model_name.startswith("models/"):
            model_name = model_name.split("/", 1)[-1]

        # Truncate transcript to avoid token limits (use first 8000 chars)
        truncated = transcript[:8000] if len(transcript) > 8000 else transcript
        prompt = BRIEF_SUMMARY_PROMPT.format(transcript=truncated)

        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=30000,
                ),
            )
            # Extract text from response
            for cand in getattr(resp, "candidates", []) or []:
                content = getattr(cand, "content", None)
                parts = getattr(content, "parts", None)
                if parts:
                    for p in parts:
                        t = getattr(p, "text", None)
                        if t:
                            return t.strip()
            return ""
        except Exception as e:
            print(f"    [!] Brief summary generation failed: {e}")
            return ""

    def _load_existing_digest(self) -> dict:
        """Load existing digest file or return empty structure."""
        if self._digest_path.exists():
            try:
                with open(self._digest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Ensure expected structure (dict-based)
                    if "processed" not in data or not isinstance(data["processed"], dict):
                        data["processed"] = {}
                    if "failed" not in data or not isinstance(data["failed"], dict):
                        data["failed"] = {}
                    return data
            except (json.JSONDecodeError, IOError) as e:
                print(f"[!] Warning: Failed to load existing digest: {e}")
        return {"processed": {}, "failed": {}}

    def _cleanup_old_digest_entries(self, data: dict, max_age_days: int = 3) -> int:
        """Remove digest entries older than max_age_days. Returns count removed."""
        cutoff = datetime.now() - timedelta(days=max_age_days)
        removed = 0

        for section in ["processed", "failed"]:
            to_remove = []
            for video_id, entry in data.get(section, {}).items():
                timestamp_str = entry.get("timestamp", "")
                try:
                    # Try parsing the timestamp
                    dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    if dt < cutoff:
                        to_remove.append(video_id)
                except ValueError:
                    pass

            for video_id in to_remove:
                del data[section][video_id]
                removed += 1

        return removed

    def _save_digest(self) -> None:
        """Save video digest to JSON file (append mode with cleanup)."""
        # Load existing digest
        digest = self._load_existing_digest()

        # Append new processed entries (keyed by video_id)
        for entry in self._digest_processed:
            digest["processed"][entry.video_id] = asdict(entry)

        # Append new failed entries (keyed by video_id)
        for entry in self._digest_failed:
            digest["failed"][entry.video_id] = asdict(entry)

        # Cleanup entries older than 3 days
        removed = self._cleanup_old_digest_entries(digest, max_age_days=3)
        if removed > 0:
            print(f"[i] Cleaned up {removed} old digest entries (>3 days)")

        # Update metadata
        digest["updated_at"] = datetime.now().isoformat()

        try:
            with open(self._digest_path, "w", encoding="utf-8") as f:
                json.dump(digest, f, ensure_ascii=False, indent=2)
            print(f"\n[i] Video digest saved to: {self._digest_path}")
        except Exception as e:
            print(f"[!] Failed to save video digest: {e}")

    def _load_config(self) -> dict:
        """Load and validate YAML configuration."""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Channel configuration not found: {self.config_path}\n"
                f"Please create it from channels.example.yaml"
            )

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        if "channels" not in config:
            config["channels"] = []

        return config

    def get_channels(self) -> list[ChannelConfig]:
        """Get list of configured channels."""
        channels = []
        for ch in self.config.get("channels", []):
            if not ch.get("url"):
                continue
            channels.append(
                ChannelConfig(
                    url=ch["url"],
                    name=ch.get("name"),
                    enabled=ch.get("enabled", True),
                    lookback_hours=ch.get("lookback_hours", self.default_lookback_hours),
                    note_mode=ch.get("note_mode"),
                )
            )
        return channels

    def get_enabled_channels(self) -> list[ChannelConfig]:
        """Get list of enabled channels only."""
        return [ch for ch in self.get_channels() if ch.enabled]

    def fetch_channel_videos(
        self, channel_url: str, limit: int = 30
    ) -> list[VideoInfo]:
        """
        Fetch recent videos from a channel using yt-dlp.

        Args:
            channel_url: URL of the channel/user page
            limit: Maximum number of videos to fetch

        Returns:
            List of VideoInfo objects
        """
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,  # Fast metadata-only extraction
            "playlistend": limit,
        }

        if self._cookie_file:
            cookie_path = Path(self._cookie_file).expanduser()
            if cookie_path.exists():
                ydl_opts["cookiefile"] = str(cookie_path)

        if self._js_interpreter:
            ydl_opts["js_interpreter"] = self._js_interpreter

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(channel_url, download=False)
            except yt_dlp.utils.DownloadError as e:
                print(f"[!] Failed to fetch channel: {e}")
                return []

        if not info:
            return []

        videos = []
        entries = info.get("entries") or []

        for entry in entries:
            if not entry:
                continue

            video_id = entry.get("id")
            if not video_id:
                continue

            # Build proper video URL
            url = entry.get("url") or entry.get("webpage_url")
            if not url:
                # Construct URL based on platform
                if "youtube" in channel_url.lower() or "youtu.be" in channel_url.lower():
                    url = f"https://www.youtube.com/watch?v={video_id}"
                elif "bilibili" in channel_url.lower():
                    url = f"https://www.bilibili.com/video/{video_id}"
                else:
                    continue

            upload_date = self._parse_upload_date(entry.get("upload_date"))

            videos.append(
                VideoInfo(
                    video_id=video_id,
                    url=url,
                    title=entry.get("title", "Unknown"),
                    channel_id=info.get("channel_id")
                    or info.get("uploader_id")
                    or "",
                    channel_name=info.get("channel")
                    or info.get("uploader")
                    or info.get("title")
                    or "",
                    upload_date=upload_date,
                    duration=entry.get("duration") or 0,
                    live_status=entry.get("live_status"),
                )
            )

        return videos

    def _parse_upload_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse upload_date from yt-dlp format (YYYYMMDD)."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            return None

    def _check_bilibili_video_type(self, bvid: str) -> tuple[Optional[str], Optional[str]]:
        """
        Check Bilibili video type via API.

        Returns:
            Tuple of (video_type, title):
            - video_type: "normal", "cooperation", "paid", "error", or None
            - title: Video title if available
        """
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            data = resp.json()

            if data.get("code") == -404:
                return "paid", None  # 充电专属或已删除

            if data.get("code") == -352:
                # 风控，返回 error 让调用者决定如何处理
                return "error", None

            if data.get("code") != 0:
                # 其他 API 错误
                return "error", None

            video_data = data.get("data", {})
            title = video_data.get("title")
            rights = video_data.get("rights", {})

            if rights.get("is_cooperation") == 1:
                return "cooperation", title

            return "normal", title

        except requests.exceptions.Timeout:
            return "error", None
        except Exception:
            return "error", None

    def filter_new_videos(
        self,
        videos: list[VideoInfo],
        lookback_hours: int,
    ) -> list[VideoInfo]:
        """
        Filter videos to only include new, unprocessed ones.

        Logic:
        1. Video ID not in processed store
        2. Skip upcoming or currently live streams (only process was_live)
        3. Skip videos shorter than 300 seconds (auto-mark as processed & sent)
        4. Not older than lookback_hours (primary filter)
        5. Not older than max_video_age_days (hard limit fallback)
        6. For Bilibili: skip paid (充电专属) and cooperation (合作) videos
        """
        now = datetime.now()
        lookback_cutoff = now - timedelta(hours=lookback_hours)
        max_age_cutoff = now - timedelta(days=self.max_video_age_days)

        new_videos = []
        for video in videos:
            # Skip if already processed
            if self.store.is_processed(video.video_id):
                continue

            # Skip upcoming or currently live streams (can't transcribe yet)
            if video.live_status in ("is_upcoming", "is_live"):
                continue

            # Skip videos shorter than 300 seconds (5 minutes)
            # Auto-mark as processed and sent to avoid future processing
            if video.duration and video.duration < 300:
                print(f"      [skip] 视频时长过短 ({video.duration}s < 300s): {video.title}")
                self.store.mark_processed(
                    video_id=video.video_id,
                    title=video.title,
                    url=video.url,
                    channel_name=video.channel_name,
                    sent=True,  # Mark as sent to completely ignore
                )
                continue

            # Check age constraints
            if video.upload_date:
                # Skip if older than lookback_hours (primary filter)
                if video.upload_date < lookback_cutoff:
                    continue
                # Also skip if older than max_video_age_days (hard limit)
                if video.upload_date < max_age_cutoff:
                    continue

            # Filter Bilibili paid/cooperation videos
            if video.video_id.startswith("BV"):
                video_type, api_title = self._check_bilibili_video_type(video.video_id)
                display_title = api_title or video.title or video.video_id

                if video_type == "paid":
                    print(f"      [skip] 充电专属: {display_title}")
                    time.sleep(BILIBILI_API_DELAY)
                    continue
                if video_type == "cooperation":
                    print(f"      [skip] 合作视频: {display_title}")
                    time.sleep(BILIBILI_API_DELAY)
                    continue
                if video_type == "error":
                    # API 错误时跳过，避免处理可能无法访问的视频
                    print(f"      [skip] API错误: {display_title}")
                    time.sleep(BILIBILI_API_DELAY)
                    continue

                # Update title if we got it from API
                if api_title and video.title in ("Unknown", None, ""):
                    video.title = api_title

                # 添加请求间隔，避免触发风控
                time.sleep(BILIBILI_API_DELAY)

            new_videos.append(video)

        return new_videos

    async def process_new_videos(
        self,
        videos: list[VideoInfo],
        outdir: Path,
        on_update: Optional[Callable] = None,
        keep_audio: bool = False,
    ) -> dict[str, bool]:
        """
        Process videos sequentially using the existing pipeline.

        Args:
            videos: List of videos to process
            outdir: Output directory for transcripts
            on_update: Optional progress callback
            keep_audio: Whether to keep audio files

        Returns:
            Dict mapping video_id to success status
        """
        import asyncio
        import subprocess

        from .pipeline import process_video
        from .note_generator import NoteGenerator, generate_note_filename

        results = {}
        failed_log_path = outdir / "failed_videos.log"

        def is_rate_limited(message: str) -> bool:
            text = message.lower()
            markers = (
                "rate-limited",
                "too many requests",
                "http error 429",
            )
            return any(marker in text for marker in markers)

        def log_failure(video: VideoInfo, stage: str, error: str):
            """Log failed video to file."""
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = (
                f"\n{'='*60}\n"
                f"[{timestamp}] 处理失败\n"
                f"频道: {video.channel_name}\n"
                f"标题: {video.title}\n"
                f"URL: {video.url}\n"
                f"阶段: {stage}\n"
                f"原因: {error}\n"
            )
            with open(failed_log_path, "a", encoding="utf-8") as f:
                f.write(log_entry)
            print(f"    [!] 已记录到 {failed_log_path}")

        for i, video in enumerate(videos, 1):
            print(f"\n[{i}/{len(videos)}] Processing: {video.title}")
            print(f"    URL: {video.url}")
            if video.note_mode:
                print(f"    Note mode: {video.note_mode}")

            # Pre-download live check (flat extraction doesn't always return accurate live_status)
            try:
                check_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'skip_download': True,
                }
                if self._cookie_file:
                    cookie_path = Path(self._cookie_file).expanduser()
                    if cookie_path.exists():
                        check_opts['cookiefile'] = str(cookie_path)
                if self._js_interpreter:
                    check_opts['js_interpreter'] = self._js_interpreter

                with yt_dlp.YoutubeDL(check_opts) as ydl:
                    info = ydl.extract_info(video.url, download=False)
                    if info.get('is_live'):
                        print(f"    [skip] 正在直播，跳过")
                        continue
            except Exception as e:
                # If check fails, proceed with download attempt (will fail there if truly unavailable)
                print(f"    [!] 直播检查失败: {e}，继续尝试下载")

            try:
                result = await process_video(
                    url=video.url,
                    temp_dir=outdir,
                    on_update=on_update,
                    keep_audio=keep_audio,
                )

                transcript_file = result.get("transcript_file")
                print(f"    [OK] Transcript: {transcript_file}")

                # Generate note if note_mode is specified
                note_file = None
                if video.note_mode and transcript_file:
                    try:
                        print(f"    [i] Generating note...")
                        transcript_path = outdir / transcript_file
                        transcript_content = transcript_path.read_text(encoding="utf-8")

                        generator = NoteGenerator()

                        def _do_generate():
                            return generator.generate_note(
                                transcript_content, mode_index=video.note_mode
                            )

                        note_content = await asyncio.to_thread(_do_generate)

                        video_title = result.get("video_title", video.title)
                        note_filename = generate_note_filename(video_title)
                        note_path = outdir / note_filename
                        note_path.write_text(note_content, encoding="utf-8")
                        note_file = note_filename

                        print(f"    [OK] Note: {note_filename}")

                        sync_cmd = build_rclone_copy_command(note_path)
                        sync_success = False
                        if sync_cmd:
                            try:
                                sync_result = subprocess.run(
                                    sync_cmd,
                                    capture_output=True,
                                    timeout=120,
                                )
                                if sync_result.returncode == 0:
                                    print("    [OK] Synced to configured Rclone remote")
                                    sync_success = True
                                else:
                                    print("    [!] Rclone sync failed")
                            except FileNotFoundError:
                                pass  # rclone not installed
                            except subprocess.TimeoutExpired:
                                print("    [!] Rclone sync timeout")
                        else:
                            print("    [i] RCLONE_REMOTE_PATH 未配置，跳过远端同步")

                        # Local files kept for news_summary to send as email attachments
                        # news_summary will cleanup these files after sending
                        # (see news_summary/video_tracker.py:cleanup_sent_notes)
                        if sync_success:
                            print(f"    [OK] Synced, local files retained for email delivery")

                    except Exception as e:
                        error_msg = f"{type(e).__name__}: {e}"
                        print(f"    [!] Note generation failed: {error_msg}")
                        log_failure(video, "Note生成", error_msg)

                # Generate brief summary for digest
                brief_summary = ""
                if transcript_file:
                    print(f"    [i] Generating brief summary...")
                    transcript_path = outdir / transcript_file
                    try:
                        transcript_content = transcript_path.read_text(encoding="utf-8")
                        brief_summary = await asyncio.to_thread(
                            self._generate_brief_summary, transcript_content
                        )
                        if brief_summary:
                            print(f"    [OK] Brief summary generated ({len(brief_summary)} chars)")
                    except Exception as e:
                        print(f"    [!] Brief summary failed: {e}")

                # Add to digest
                self._digest_processed.append(VideoDigestEntry(
                    video_id=video.video_id,
                    title=video.title,
                    channel=video.channel_name,
                    url=video.url,
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    summary=brief_summary,
                    note_file=str((outdir / note_file).resolve()) if note_file else "",
                ))

                # Mark as processed
                self.store.mark_processed(
                    video_id=video.video_id,
                    title=video.title,
                    url=video.url,
                    channel_name=video.channel_name,
                    transcript_file=transcript_file,
                )

                results[video.video_id] = True

            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                print(f"    [!] Failed: {error_msg}")
                log_failure(video, "转录", error_msg)

                # Add to digest failures
                self._digest_failed.append(VideoDigestFailure(
                    video_id=video.video_id,
                    title=video.title,
                    channel=video.channel_name,
                    url=video.url,
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    error=error_msg,
                ))

                results[video.video_id] = False

                if is_rate_limited(error_msg) and self.rate_limit_cooldown > 0:
                    print(
                        f"    [!] 检测到限速，等待 {self.rate_limit_cooldown} 秒后继续..."
                    )
                    await asyncio.sleep(self.rate_limit_cooldown)

            # Delay between videos to avoid rate limiting
            if i < len(videos) and self.processing_delay > 0:
                await asyncio.sleep(self.processing_delay)

        return results

    async def run_check(
        self,
        outdir: Path,
        on_update: Optional[Callable] = None,
        lookback_override: Optional[int] = None,
        dry_run: bool = False,
        keep_audio: bool = False,
    ) -> dict:
        """
        Main entry point: check all enabled channels and process new videos.

        Args:
            outdir: Output directory for transcripts
            on_update: Optional progress callback
            lookback_override: Override default lookback hours
            dry_run: If True, only show what would be processed
            keep_audio: Whether to keep audio files

        Returns:
            Summary dict with statistics
        """
        channels = self.get_enabled_channels()

        if not channels:
            print("[!] No enabled channels configured")
            return {
                "channels_checked": 0,
                "new_videos_found": 0,
                "videos_processed": 0,
                "errors": [],
            }

        all_new_videos = []
        errors = []

        print(f"[i] Checking {len(channels)} channel(s)...")

        for channel in channels:
            display_name = channel.name or channel.url
            print(f"\n[>] {display_name}")

            try:
                videos = self.fetch_channel_videos(channel.url)
                print(f"    Found {len(videos)} video(s)")

                lookback = lookback_override or channel.lookback_hours
                new_videos = self.filter_new_videos(videos, lookback)

                if new_videos:
                    print(f"    New videos: {len(new_videos)}")
                    for v in new_videos:
                        # Attach note_mode from channel config
                        v.note_mode = channel.note_mode
                        age_str = ""
                        if v.upload_date:
                            age = datetime.now() - v.upload_date
                            if age.days > 0:
                                age_str = f" ({age.days}d ago)"
                            else:
                                hours = age.seconds // 3600
                                age_str = f" ({hours}h ago)"
                        print(f"      - {v.title}{age_str}")
                    all_new_videos.extend(new_videos)
                else:
                    print(f"    No new videos")

            except Exception as e:
                print(f"    [!] Error: {e}")
                errors.append(f"{display_name}: {e}")

        summary = {
            "channels_checked": len(channels),
            "new_videos_found": len(all_new_videos),
            "videos_processed": 0,
            "videos_sent": 0,
            "errors": errors,
        }

        if not all_new_videos:
            print("\n[i] No new videos to process")
            return summary

        if dry_run:
            print(f"\n[DRY RUN] Would process {len(all_new_videos)} video(s)")
            return summary

        print(f"\n[i] Processing {len(all_new_videos)} video(s)...")

        # Clear previous digest data
        self._digest_processed = []
        self._digest_failed = []

        results = await self.process_new_videos(
            all_new_videos, outdir, on_update, keep_audio
        )

        summary["videos_processed"] = sum(1 for v in results.values() if v)

        # Save video digest for news_summary integration
        if self._digest_processed or self._digest_failed:
            self._save_digest()


        return summary


def extract_video_id(url: str) -> Optional[str]:
    """
    Extract video ID from various URL formats.

    Supports:
    - YouTube: youtube.com/watch?v=XXX, youtu.be/XXX, youtube.com/shorts/XXX
    - Bilibili: bilibili.com/video/BVXXX, bilibili.com/video/avXXX
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""

    if "youtube.com" in host or "youtu.be" in host:
        if "youtu.be" in host:
            return parsed.path.strip("/").split("/")[0]
        if "watch" in parsed.path:
            return parse_qs(parsed.query).get("v", [None])[0]
        if "/shorts/" in parsed.path:
            return parsed.path.split("/shorts/")[-1].split("/")[0]

    elif "bilibili.com" in host:
        match = re.search(r"/video/(BV[a-zA-Z0-9]+|av\d+)", parsed.path)
        if match:
            return match.group(1)

    return None

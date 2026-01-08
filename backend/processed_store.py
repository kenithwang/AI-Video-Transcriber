"""
Processed videos tracking store.

Maintains a persistent JSON store of processed video IDs to avoid
duplicate transcriptions across runs.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional


class ProcessedStore:
    """Manages the persistent store of processed video IDs."""

    def __init__(self, store_path: Path | str):
        """Initialize the store, loading existing data if present."""
        self.store_path = Path(store_path)
        self._data = self._load()

    def _load(self) -> dict:
        """Load existing store or create empty structure."""
        if self.store_path.exists():
            try:
                with open(self.store_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Ensure expected structure
                    if "videos" not in data:
                        data["videos"] = {}
                    return data
            except (json.JSONDecodeError, IOError) as e:
                print(f"[!] Warning: Failed to load processed store: {e}")
                print(f"[!] Starting with empty store")
                return {"version": 1, "videos": {}}
        return {"version": 1, "videos": {}}

    def save(self) -> None:
        """Persist store to disk atomically."""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file first, then rename for atomicity
        fd, temp_path = tempfile.mkstemp(
            dir=self.store_path.parent, suffix=".json.tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.store_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def is_processed(self, video_id: str) -> bool:
        """Check if a video has already been processed."""
        return video_id in self._data["videos"]

    def mark_processed(
        self,
        video_id: str,
        title: str,
        url: str,
        channel_name: Optional[str] = None,
        transcript_file: Optional[str] = None,
        sent: bool = False,
    ) -> None:
        """Mark a video as processed and save immediately."""
        self._data["videos"][video_id] = {
            "title": title,
            "url": url,
            "channel_name": channel_name,
            "transcript_file": transcript_file,
            "processed_at": datetime.now().isoformat(),
            "sent": sent,
        }
        self.save()

    def get_unsent_videos(self) -> dict[str, dict]:
        """Get all videos that have been processed but not yet sent via email."""
        return {
            video_id: info
            for video_id, info in self._data["videos"].items()
            if not info.get("sent", False)
        }

    def mark_sent(self, video_id: str) -> None:
        """Mark a video as sent and save immediately."""
        if video_id in self._data["videos"]:
            self._data["videos"][video_id]["sent"] = True
            self.save()

    def mark_sent_batch(self, video_ids: list[str]) -> None:
        """Mark multiple videos as sent and save once."""
        for video_id in video_ids:
            if video_id in self._data["videos"]:
                self._data["videos"][video_id]["sent"] = True
        if video_ids:
            self.save()

    def get_all_video_ids(self) -> set[str]:
        """Get all processed video IDs."""
        return set(self._data["videos"].keys())

    def get_video_info(self, video_id: str) -> Optional[dict]:
        """Get stored info for a processed video."""
        return self._data["videos"].get(video_id)

    def count(self) -> int:
        """Return number of processed videos."""
        return len(self._data["videos"])

    def cleanup_old(self, max_age_days: int) -> int:
        """
        Remove entries older than max_age_days.
        Returns number of entries removed.
        """
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=max_age_days)
        to_remove = []

        for video_id, info in self._data["videos"].items():
            processed_at = info.get("processed_at")
            if processed_at:
                try:
                    dt = datetime.fromisoformat(processed_at)
                    if dt < cutoff:
                        to_remove.append(video_id)
                except ValueError:
                    pass

        for video_id in to_remove:
            del self._data["videos"][video_id]

        if to_remove:
            self.save()

        return len(to_remove)

import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import yt_dlp

from backend.channel_monitor import ChannelMonitor, VideoInfo


class FailingYoutubeDL:
    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def extract_info(self, url, download=False):
        raise yt_dlp.utils.DownloadError("channel unavailable")


class ChannelMonitorExperienceTests(unittest.TestCase):
    def _config(self, root: Path) -> Path:
        path = root / "channels.yaml"
        path.write_text(
            """
settings:
  processed_store: processed.json
channels:
  - url: https://example.test/channel
    name: Demo
    enabled: true
""".strip(),
            encoding="utf-8",
        )
        return path

    def test_dry_run_does_not_write_skipped_videos_to_processed_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            monitor = ChannelMonitor(self._config(root))
            short_video = VideoInfo(
                video_id="short",
                url="https://example.test/short",
                title="Short video",
                channel_id="demo",
                channel_name="Demo",
                upload_date=datetime.now(),
                duration=60,
            )

            with patch.object(
                monitor, "fetch_channel_videos", return_value=[short_video]
            ):
                result = asyncio.run(monitor.run_check(root, dry_run=True))

            self.assertEqual(0, result["new_videos_found"])
            self.assertFalse((root / "processed.json").exists())
            self.assertFalse(monitor.store.is_processed("short"))

    def test_channel_download_error_is_reported_in_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            monitor = ChannelMonitor(self._config(root))

            with patch("backend.channel_monitor.yt_dlp.YoutubeDL", FailingYoutubeDL):
                result = asyncio.run(monitor.run_check(root, dry_run=True))

            self.assertEqual(1, len(result["errors"]))
            self.assertIn("channel unavailable", result["errors"][0])
            self.assertEqual(1, result["channel_errors"])

    def test_invalid_config_shapes_raise_clear_value_errors(self) -> None:
        invalid_configs = [
            "- not\n- a\n- mapping\n",
            "settings: []\nchannels: []\n",
            "settings: {}\nchannels: {}\n",
            "settings: {}\nchannels:\n  - invalid\n",
            "settings: [\n",
        ]

        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "channels.yaml"
            for content in invalid_configs:
                with self.subTest(content=content):
                    config.write_text(content, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "Invalid channel configuration"):
                        ChannelMonitor(config)


if __name__ == "__main__":
    unittest.main()

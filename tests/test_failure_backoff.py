import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from backend.channel_monitor import ChannelMonitor, VideoInfo
from backend.processed_store import ProcessedStore


class FakeYoutubeDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def extract_info(self, url, download=False):
        return {"is_live": False}


class FailureBackoffTests(unittest.TestCase):
    def test_record_failure_tracks_count_and_marks_processed_on_third_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store_path = tmp_path / "processed.json"
            store = ProcessedStore(store_path)

            first = store.record_failure(
                video_id="v1",
                title="Broken Video",
                url="https://example.test/v1",
                channel_name="Channel",
                error="first failure",
            )
            second = store.record_failure(
                video_id="v1",
                title="Broken Video",
                url="https://example.test/v1",
                channel_name="Channel",
                error="second failure",
            )

            self.assertEqual(1, first)
            self.assertEqual(2, second)
            self.assertFalse(store.is_processed("v1"))

            config_path = tmp_path / "channels.yaml"
            config_path.write_text(
                """
settings:
  processing_delay: 0
  rate_limit_cooldown: 0
channels: []
""".strip(),
                encoding="utf-8",
            )
            monitor = ChannelMonitor(config_path, store_path=store_path)
            video = VideoInfo(
                video_id="v1",
                url="https://www.youtube.com/watch?v=v1",
                title="Broken Video",
                channel_id="channel-id",
                channel_name="Channel",
                upload_date=datetime.now(),
                duration=600,
            )

            async def fail_process_video(**kwargs):
                raise RuntimeError("download failed again")

            with patch("backend.channel_monitor.yt_dlp.YoutubeDL", FakeYoutubeDL):
                with patch("backend.pipeline.process_video", fail_process_video):
                    results = asyncio.run(
                        monitor.process_new_videos([video], tmp_path)
                    )

            self.assertFalse(results["v1"])
            reloaded = ProcessedStore(store_path)
            self.assertTrue(reloaded.is_processed("v1"))
            info = reloaded.get_video_info("v1")
            self.assertEqual("Broken Video", info["title"])
            self.assertTrue(info["sent"])
            self.assertEqual(3, info["failed_attempts"])
            self.assertIn("download failed again", info["skip_reason"])


if __name__ == "__main__":
    unittest.main()

import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from backend.channel_monitor import ChannelMonitor, VideoInfo


class FakeXiaoyuzhouClient:
    def list_episodes_with_fallback(self, podcast_id, limit=30):
        return [{
            "eid": "a" * 24,
            "pid": podcast_id,
            "podcast_title": "Podcast",
            "title": "Episode",
            "duration": 3600,
            "pub_date": "2026-07-12T01:00:00.000Z",
            "audio_url": "https://cdn.test/episode.mp3",
            "episode_url": "https://www.xiaoyuzhoufm.com/episode/" + "a" * 24,
        }]


class XiaoyuzhouMonitorTests(unittest.TestCase):
    def _monitor(self, tmp: str, channels: str = "channels: []") -> ChannelMonitor:
        config = Path(tmp) / "channels.yaml"
        config.write_text(
            "settings:\n  processing_delay: 0\n  processed_store: processed.json\n"
            + channels,
            encoding="utf-8",
        )
        return ChannelMonitor(config)

    def test_fetch_podcast_maps_episode_without_ytdlp(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor = self._monitor(tmp)
            with patch("backend.channel_monitor.XiaoyuzhouClient", FakeXiaoyuzhouClient):
                with patch("backend.channel_monitor.yt_dlp.YoutubeDL") as ydl:
                    videos = monitor.fetch_channel_videos(
                        "https://www.xiaoyuzhoufm.com/podcast/" + "b" * 24
                    )
        ydl.assert_not_called()
        self.assertEqual("a" * 24, videos[0].video_id)
        self.assertEqual("https://cdn.test/episode.mp3", videos[0].media_url)
        self.assertEqual("Podcast", videos[0].channel_name)
        self.assertIsInstance(videos[0].upload_date, datetime)

    def test_processing_uses_media_url_and_skips_live_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor = self._monitor(tmp)
            video = VideoInfo(
                video_id="a" * 24,
                url="https://www.xiaoyuzhoufm.com/episode/" + "a" * 24,
                title="Episode",
                channel_id="b" * 24,
                channel_name="Podcast",
                upload_date=datetime.now(),
                duration=3600,
                media_url="https://cdn.test/episode.mp3",
            )
            captured = {}

            async def fake_process_video(**kwargs):
                captured.update(kwargs)
                transcript = Path(kwargs["temp_dir"]) / "transcript.md"
                transcript.write_text("body", encoding="utf-8")
                return {"transcript_file": "transcript.md", "video_title": "Episode"}

            monitor._generate_brief_summary = lambda transcript: ""
            with patch("backend.channel_monitor.yt_dlp.YoutubeDL") as ydl:
                with patch("backend.pipeline.process_video", fake_process_video):
                    asyncio.run(monitor.process_new_videos([video], Path(tmp)))

        ydl.assert_not_called()
        self.assertEqual(video.url, captured["url"])
        self.assertEqual(video.media_url, captured["download_url"])

    def test_baseline_marks_only_enabled_xiaoyuzhou_episodes_sent(self):
        channels = """channels:
  - url: https://www.xiaoyuzhoufm.com/podcast/bbbbbbbbbbbbbbbbbbbbbbbb
    name: Podcast
    enabled: true
  - url: https://www.xiaoyuzhoufm.com/podcast/cccccccccccccccccccccccc
    name: Disabled
    enabled: false
  - url: https://www.youtube.com/@example/videos
    name: YouTube
    enabled: true
"""
        with tempfile.TemporaryDirectory() as tmp:
            monitor = self._monitor(tmp, channels)
            episode = VideoInfo(
                video_id="a" * 24,
                url="https://www.xiaoyuzhoufm.com/episode/" + "a" * 24,
                title="Episode",
                channel_id="b" * 24,
                channel_name="Podcast",
                upload_date=datetime.now(),
                duration=3600,
                media_url="https://cdn.test/episode.mp3",
            )
            second_episode = VideoInfo(
                video_id="d" * 24,
                url="https://www.xiaoyuzhoufm.com/episode/" + "d" * 24,
                title="Episode 2",
                channel_id="b" * 24,
                channel_name="Podcast",
                upload_date=datetime.now(),
                duration=3600,
                media_url="https://cdn.test/episode-2.mp3",
            )
            calls = []

            def fake_fetch(url, limit=30):
                calls.append((url, limit))
                return [episode, second_episode]

            monitor.fetch_channel_videos = fake_fetch
            with patch.object(monitor.store, "save", wraps=monitor.store.save) as save:
                result = monitor.baseline_xiaoyuzhou()

        self.assertEqual(1, result["channels"])
        self.assertEqual(2, result["episodes"])
        self.assertEqual(1, save.call_count)
        channels_url = "https://www.xiaoyuzhoufm.com/podcast/" + "b" * 24
        self.assertEqual([(channels_url, None)], calls)
        self.assertTrue(monitor.store.get_video_info("a" * 24)["sent"])


if __name__ == "__main__":
    unittest.main()

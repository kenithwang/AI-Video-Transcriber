import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.video_processor import VideoProcessor


class VideoProcessorConfigTests(unittest.TestCase):
    def test_get_video_info_uses_bilibili_headers_and_cookie(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "bilibili_cookies.txt"
            cookie_path.write_text("# cookies\n", encoding="utf-8")

            captured_opts: dict = {}

            class FakeYoutubeDL:
                def __init__(self, opts):
                    captured_opts.update(opts)

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return None

                def extract_info(self, url, download=False):
                    return {"title": "title", "duration": 1}

            with patch.dict(os.environ, {"BILIBILI_COOKIE_FILE": str(cookie_path)}, clear=False):
                with patch("backend.video_processor.yt_dlp.YoutubeDL", FakeYoutubeDL):
                    VideoProcessor().get_video_info("https://www.bilibili.com/video/BV123")

            self.assertEqual(str(cookie_path), captured_opts.get("cookiefile"))
            self.assertEqual(
                "https://www.bilibili.com/",
                captured_opts.get("http_headers", {}).get("Referer"),
            )
            self.assertIn("User-Agent", captured_opts.get("http_headers", {}))


if __name__ == "__main__":
    unittest.main()

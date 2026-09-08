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

    def test_youtube_cookies_warn_when_login_fields_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "www.youtube.com_cookies.txt"
            cookie_path.write_text(
                "# Netscape HTTP Cookie File\n"
                ".youtube.com\tTRUE\t/\tTRUE\t0\tPREF\tf7=4150\n",
                encoding="utf-8",
            )
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

            with patch.dict(os.environ, {"YDL_COOKIEFILE": str(cookie_path)}, clear=False):
                with patch("backend.video_processor.yt_dlp.YoutubeDL", FakeYoutubeDL):
                    with self.assertLogs("backend.video_processor", level="WARNING") as logs:
                        VideoProcessor().get_video_info("https://www.youtube.com/watch?v=abc")

            self.assertEqual(str(cookie_path), captured_opts.get("cookiefile"))
            self.assertTrue(any("LOGIN_INFO" in message for message in logs.output))

    def test_youtube_cookies_copy_master_over_runtime_before_ytdlp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            master_path = Path(tmp) / "www.youtube.com_cookies.master.txt"
            runtime_path = Path(tmp) / "youtube_cookies.txt"
            master_path.write_text(
                "# Netscape HTTP Cookie File\n"
                ".youtube.com\tTRUE\t/\tTRUE\t0\tLOGIN_INFO\tmaster-login\n"
                ".youtube.com\tTRUE\t/\tFALSE\t0\tSID\tmaster-sid\n"
                ".youtube.com\tTRUE\t/\tTRUE\t0\tSAPISID\tmaster-sapisid\n",
                encoding="utf-8",
            )
            runtime_path.write_text(
                "# Netscape HTTP Cookie File\n"
                ".youtube.com\tTRUE\t/\tTRUE\t0\tPREF\tstale\n",
                encoding="utf-8",
            )
            captured_opts: dict = {}

            class FakeYoutubeDL:
                def __init__(self, opts):
                    captured_opts.update(opts)
                    cookiefile = Path(opts["cookiefile"])
                    captured_opts["_runtime_at_open"] = cookiefile.read_text(encoding="utf-8")
                    cookiefile.write_text(
                        "# Netscape HTTP Cookie File\n"
                        ".youtube.com\tTRUE\t/\tTRUE\t0\tPREF\tyt-dlp-wrote-this\n",
                        encoding="utf-8",
                    )

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return None

                def extract_info(self, url, download=False):
                    return {"title": "title", "duration": 1}

            env = {
                "YDL_COOKIE_MASTER": str(master_path),
                "YDL_COOKIEFILE": str(runtime_path),
            }
            with patch.dict(os.environ, env, clear=False):
                with patch("backend.video_processor.yt_dlp.YoutubeDL", FakeYoutubeDL):
                    VideoProcessor().get_video_info("https://www.youtube.com/watch?v=abc")

            self.assertEqual(str(runtime_path), captured_opts.get("cookiefile"))
            self.assertNotEqual(str(master_path), captured_opts.get("cookiefile"))
            self.assertIn("LOGIN_INFO", captured_opts["_runtime_at_open"])
            self.assertIn("master-login", captured_opts["_runtime_at_open"])
            self.assertIn("master-login", master_path.read_text(encoding="utf-8"))
            self.assertNotIn("yt-dlp-wrote-this", master_path.read_text(encoding="utf-8"))
            self.assertIn("yt-dlp-wrote-this", runtime_path.read_text(encoding="utf-8"))

    def test_youtube_cookies_recopy_master_on_every_ytdlp_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            master_path = Path(tmp) / "www.youtube.com_cookies.master.txt"
            runtime_path = Path(tmp) / "youtube_cookies.txt"
            master_path.write_text(
                "# Netscape HTTP Cookie File\n"
                ".youtube.com\tTRUE\t/\tTRUE\t0\tLOGIN_INFO\tmaster-login\n"
                ".youtube.com\tTRUE\t/\tFALSE\t0\tSID\tmaster-sid\n"
                ".youtube.com\tTRUE\t/\tTRUE\t0\tSAPISID\tmaster-sapisid\n",
                encoding="utf-8",
            )
            seen_at_open: list[str] = []

            class FakeYoutubeDL:
                def __init__(self, opts):
                    cookiefile = Path(opts["cookiefile"])
                    seen_at_open.append(cookiefile.read_text(encoding="utf-8"))
                    cookiefile.write_text("mutated-by-yt-dlp\n", encoding="utf-8")

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return None

                def extract_info(self, url, download=False):
                    return {"title": "title", "duration": 1}

            env = {
                "YDL_COOKIE_MASTER": str(master_path),
                "YDL_COOKIEFILE": str(runtime_path),
            }
            with patch.dict(os.environ, env, clear=False):
                with patch("backend.video_processor.yt_dlp.YoutubeDL", FakeYoutubeDL):
                    processor = VideoProcessor()
                    processor.get_video_info("https://www.youtube.com/watch?v=one")
                    processor.get_video_info("https://www.youtube.com/watch?v=two")

            self.assertEqual(2, len(seen_at_open))
            self.assertTrue(all("master-login" in text for text in seen_at_open))
            self.assertIn("master-login", master_path.read_text(encoding="utf-8"))
            self.assertEqual("mutated-by-yt-dlp\n", runtime_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

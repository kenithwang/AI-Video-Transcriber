import os
import io
import asyncio
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


class SubtitleRetrievalTests(unittest.TestCase):
    def make_ydl(self, info, responses=None):
        from unittest.mock import MagicMock
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        ydl.extract_info.return_value = info
        if responses is not None:
            ydl.urlopen.side_effect = responses
        return ydl

    def test_fetch_uses_no_audio_and_preserves_network_configuration(self):
        info = {"title": "Original", "http_headers": {"Referer": "https://video.test"},
                "automatic_captions": {"en-orig": [{"ext": "vtt", "url": "https://subs.test",
                                                     "http_headers": {"User-Agent": "Test"}}]}}
        ydl = self.make_ydl(info, [io.BytesIO(b"WEBVTT\n\n00:00.000 --> 00:02.000\nHello world.")])
        processor = VideoProcessor()
        processor.ydl_opts["proxy"] = "http://proxy.test"
        processor.ydl_opts["extractor_args"] = {"youtube": {"player_client": ["web"]}}
        with patch("backend.video_processor.yt_dlp.YoutubeDL", return_value=ydl) as factory:
            caption = processor.get_subtitle_transcript("https://video.test", video_info={"title": "Cached"})
        self.assertEqual(("Hello world.", "Cached", "en", "automatic"),
                         (caption.text, caption.title, caption.language, caption.kind))
        opts = factory.call_args.args[0]
        self.assertTrue(opts["skip_download"])
        self.assertNotIn("postprocessors", opts)
        self.assertNotIn("format", opts)
        self.assertEqual("http://proxy.test", opts["proxy"])
        self.assertEqual(["web"], opts["extractor_args"]["youtube"]["player_client"])
        self.assertIn("translated_subs", opts["extractor_args"]["youtube"]["skip"])
        ydl.extract_info.assert_called_once_with("https://video.test", download=False)
        request = ydl.urlopen.call_args.args[0]
        self.assertEqual("https://video.test", request.headers["Referer"])
        self.assertEqual("Test", request.headers["User-Agent"])

    def test_failed_manual_and_empty_format_can_fall_back_to_native_asr(self):
        info = {"title": "Title", "subtitles": {"en": [{"ext": "srt", "url": "https://manual.test"}]},
                "automatic_captions": {"en-orig": [
                    {"ext": "json3", "url": "https://json.test"},
                    {"ext": "vtt", "data": "00:00.000 --> 00:03.000\nAutomatic captions."}]}}
        ydl = self.make_ydl(info, [OSError("unavailable"), io.BytesIO(b'{"events": []}')])
        with patch("backend.video_processor.yt_dlp.YoutubeDL", return_value=ydl):
            result = VideoProcessor().get_subtitle_transcript("https://video.test")
        self.assertEqual("automatic", result.kind)
        self.assertEqual(2, ydl.urlopen.call_count)

    def test_inline_bilibili_captions_need_no_second_download(self):
        info = {"title": "B站字幕", "subtitles": {"zh": [{"ext": "srt", "data":
                "1\n00:00:00,000 --> 00:00:03,000\n你好，世界。"}]}}
        ydl = self.make_ydl(info)
        with patch("backend.video_processor.yt_dlp.YoutubeDL", return_value=ydl):
            result = VideoProcessor().get_subtitle_transcript("https://video.test")
        self.assertEqual("你好，世界。", result.text)
        ydl.urlopen.assert_not_called()

    def test_no_subtitles_and_extractor_failure_return_none(self):
        for info, error in [({"title": "No captions"}, None), (None, RuntimeError("network"))]:
            with self.subTest(info=info):
                ydl = self.make_ydl(info)
                ydl.extract_info.side_effect = error
                with patch("backend.video_processor.yt_dlp.YoutubeDL", return_value=ydl):
                    self.assertIsNone(VideoProcessor().get_subtitle_transcript("https://video.test"))

    def test_cancellation_is_not_swallowed(self):
        ydl = self.make_ydl(None)
        ydl.extract_info.side_effect = asyncio.CancelledError()
        with patch("backend.video_processor.yt_dlp.YoutubeDL", return_value=ydl):
            with self.assertRaises(asyncio.CancelledError):
                VideoProcessor().get_subtitle_transcript("https://video.test")


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from backend.subtitles import subtitle_candidates, subtitles_to_text


def track(language="en", ext="vtt", **kwargs):
    return {"ext": ext, "url": f"https://captions.test/?lang={language}&fmt={ext}", **kwargs}


class SubtitleSelectionTests(unittest.TestCase):
    def test_native_manual_then_native_automatic_excludes_translation_and_chat(self):
        info = {
            "formats": [{"language": "en-US", "format_note": "English original"}],
            "subtitles": {"fr": [track("fr")], "en": [track()],
                          "live_chat": [{"ext": "json", "url": "https://chat.test"}]},
            "automatic_captions": {"en-orig": [track(ext="json3")],
                                   "zh": [track("zh", url="https://captions.test/?tlang=zh")]},
        }
        choices = subtitle_candidates(info)
        self.assertEqual([("en", "manual"), ("en", "automatic")],
                         [(language, kind) for language, kind, _ in choices])

    def test_original_asr_beats_manual_translation(self):
        info = {"subtitles": {"en": [track()]},
                "automatic_captions": {"ja-orig": [track("ja")]}}
        self.assertEqual([("ja", "automatic")],
                         [(lang, kind) for lang, kind, _ in subtitle_candidates(info)])

    def test_bilibili_inline_asr_and_danmaku(self):
        info = {"subtitles": {"danmaku": [{"ext": "xml", "data": "chat"}],
                              "ai-zh": [track(ext="srt", data="captions")]}}
        self.assertEqual([("zh", "automatic")],
                         [(lang, kind) for lang, kind, _ in subtitle_candidates(info)])

    def test_json3_preferred_and_duplicate_original_url_requested_once(self):
        info = {"automatic_captions": {"en": [track(), track(ext="json3")],
                                       "en-orig": [track(), track(ext="json3")]}}
        self.assertEqual(["json3", "vtt"],
                         [item[2]["ext"] for item in subtitle_candidates(info)])

    def test_auto_translations_excluded_even_without_original_language(self):
        info = {"automatic_captions": {"en": [track(url="https://subs.test/?tlang=en")]}}
        self.assertEqual([], subtitle_candidates(info))


class SubtitleParsingTests(unittest.TestCase):
    def test_json3_preserves_unicode_and_removes_rolling_overlap(self):
        data = json.dumps({"events": [
            {"tStartMs": 0, "dDurationMs": 5000,
             "segs": [{"utf8": "Hello "}, {"utf8": "world"}]},
            {"tStartMs": 3000, "dDurationMs": 5000,
             "segs": [{"utf8": "Hello world &amp; 大家好"}]},
        ]})
        self.assertEqual("Hello world\n& 大家好", subtitles_to_text(data, "json3"))

    def test_vtt_ignores_metadata_and_cleans_markup(self):
        data = ("\ufeffWEBVTT\nKind: captions\nLanguage: en\n\n"
                "NOTE private annotation\nnot spoken\n\n"
                "STYLE\n::cue { color: red; }\n\n"
                "cue-1\n00:00.000 --> 00:02.000 align:start\n"
                "<v Alice>Hello <00:00:01.000><c>world</c></v>\n\n"
                "00:02.000 --> 00:04.000\nA &amp; B\n")
        self.assertEqual("Hello world\nA & B", subtitles_to_text(data, "vtt"))

    def test_srt_keeps_later_repeated_speech(self):
        data = ("1\r\n00:00:00,000 --> 00:00:01,000\r\nHello\r\n\r\n"
                "2\r\n00:00:02,000 --> 00:00:03,000\r\nHello\r\n")
        self.assertEqual("Hello\nHello", subtitles_to_text(data, "srt"))

    def test_bilibili_json(self):
        data = json.dumps({"body": [{"from": 0, "to": 3, "content": "你好，世界。"}]})
        self.assertEqual("你好，世界。", subtitles_to_text(data, "json"))

    def test_invalid_empty_and_non_speech_responses_rejected(self):
        for data, ext in [("<html>Error</html>", "vtt"), ("{}", "json3"),
                          ('{"events": [{"tStartMs": 0, "segs": [{"utf8": "[Music]"}]}]}', "json3"),
                          ("00:00.000 --> 00:01.000\n...", "vtt"),
                          ("not JSON", "json3")]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                subtitles_to_text(data, ext)

    def test_truncated_long_video_subtitles_rejected(self):
        data = "00:00.000 --> 00:30.000\nAn excerpt with enough words to be real speech."
        with self.assertRaisesRegex(ValueError, "coverage"):
            subtitles_to_text(data, "vtt", duration=3600)

    def test_only_last_part_of_video_rejected(self):
        data = "00:50:00.000 --> 01:00:00.000\nAn excerpt with enough words to be real speech."
        with self.assertRaisesRegex(ValueError, "coverage"):
            subtitles_to_text(data, "vtt", duration=3600)

    def test_full_caption_timeline_accepted(self):
        data = ("00:00.000 --> 00:10.000\nThe beginning of this video.\n\n"
                "00:09:30.000 --> 00:09:50.000\nThe end of this video.")
        self.assertIn("The end", subtitles_to_text(data, "vtt", duration=600))

    def test_invalid_timing_rejected(self):
        for timing in [(-1, 10), (10, 1), (0, float("nan")), (0, float("inf"))]:
            data = json.dumps({"body": [{"from": timing[0], "to": timing[1], "content": "hello"}]})
            with self.subTest(timing=timing), self.assertRaises(ValueError):
                subtitles_to_text(data, "json")


if __name__ == "__main__":
    unittest.main()

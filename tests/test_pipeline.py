import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend import pipeline
from backend.subtitles import SubtitleTranscript
from backend.transcription_checkpoint import TranscriptionCheckpoint


class FakeVideoProcessor:
    last_url = None

    def get_subtitle_transcript(self, url, *, video_info=None):
        return None

    async def download_and_convert(self, url, output_dir, *, video_info=None):
        FakeVideoProcessor.last_url = url
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / "audio_current.m4a"
        audio_path.write_bytes(b"audio")
        return str(audio_path), "Current Video"


class FakeTranscriber:
    checkpoint_root = None
    transcribed_key = None
    cleared_keys = []

    def __init__(self, *args, **kwargs):
        FakeTranscriber.checkpoint_root = kwargs.get("checkpoint_root")

    def transcribe(self, audio_path, checkpoint_key=None):
        FakeTranscriber.transcribed_key = checkpoint_key
        return ("transcript body", "en", [])

    def clear_checkpoint(self, checkpoint_key):
        FakeTranscriber.cleared_keys.append(checkpoint_key)


class FailingTranscriber:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, audio_path, checkpoint_key=None):
        raise RuntimeError("transcription failed")


class PipelineCleanupTests(unittest.TestCase):
    def test_process_video_cleans_private_work_dir_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)

            with patch.object(pipeline, "VideoProcessor", FakeVideoProcessor):
                with patch.object(pipeline, "ObsidianTranscriber", FailingTranscriber):
                    with self.assertRaisesRegex(RuntimeError, "transcription failed"):
                        asyncio.run(
                            pipeline.process_video("https://example.test/v", temp_dir)
                        )

            self.assertEqual([], list(temp_dir.glob(".work_*")))

    def test_process_video_cleans_private_work_dir_after_persist_failure(self) -> None:
        async def fail_write(path, content):
            raise OSError("transcript write failed")

        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            FakeTranscriber.cleared_keys = []

            with patch.object(pipeline, "VideoProcessor", FakeVideoProcessor):
                with patch.object(pipeline, "ObsidianTranscriber", FakeTranscriber):
                    with patch.object(pipeline, "_write_file", fail_write):
                        with self.assertRaisesRegex(OSError, "transcript write failed"):
                            asyncio.run(
                                pipeline.process_video(
                                    "https://example.test/v", temp_dir
                                )
                            )

            self.assertEqual([], list(temp_dir.glob(".work_*")))
            self.assertEqual([], FakeTranscriber.cleared_keys)

    def test_process_video_does_not_delete_unrelated_media_in_temp_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            unrelated = temp_dir / "other_job.m4a"
            unrelated.write_bytes(b"keep")

            with patch.object(pipeline, "VideoProcessor", FakeVideoProcessor):
                with patch.object(pipeline, "ObsidianTranscriber", FakeTranscriber):
                    asyncio.run(pipeline.process_video("https://example.test/v", temp_dir))

            self.assertTrue(unrelated.exists())

    def test_process_video_downloads_media_url_but_preserves_public_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            FakeTranscriber.cleared_keys = []
            public_url = "https://www.xiaoyuzhoufm.com/episode/" + "a" * 24
            media_url = "https://cdn.test/episode.mp3"

            with patch.object(pipeline, "VideoProcessor", FakeVideoProcessor):
                with patch.object(pipeline, "ObsidianTranscriber", FakeTranscriber):
                    result = asyncio.run(
                        pipeline.process_video(
                            public_url,
                            temp_dir,
                            download_url=media_url,
                        )
                    )

            transcript = (temp_dir / result["transcript_file"]).read_text(encoding="utf-8")
            self.assertEqual(media_url, FakeVideoProcessor.last_url)
            self.assertIn(f"source: {public_url}", transcript)
            self.assertEqual(temp_dir / ".transcription_checkpoints", FakeTranscriber.checkpoint_root)
            self.assertEqual(public_url, FakeTranscriber.transcribed_key)
            self.assertEqual([public_url], FakeTranscriber.cleared_keys)


class SubtitlePipelineTests(unittest.TestCase):
    def setUp(self):
        self.caption = SubtitleTranscript("Complete caption text.", "Captioned Video", "en", "manual")

    def test_caption_hit_never_constructs_model_or_downloads_audio_even_with_keep_audio(self):
        for keep_audio in (False, True):
            with self.subTest(keep_audio=keep_audio), tempfile.TemporaryDirectory() as tmp:
                processor = Mock(spec=FakeVideoProcessor)
                processor.get_subtitle_transcript.return_value = self.caption
                root = Path(tmp)
                url = "https://www.youtube.com/watch?v=captioned"
                checkpoint = TranscriptionCheckpoint(root / ".transcription_checkpoints", url)
                checkpoint.prepare({"test": True})
                with patch.dict("os.environ", {"SUBTITLES_FIRST": "1", "OPENROUTER_API_KEY": ""}), \
                     patch.object(pipeline, "VideoProcessor", return_value=processor), \
                     patch.object(pipeline, "ObsidianTranscriber") as model:
                    result = asyncio.run(pipeline.process_video(url, root, keep_audio=keep_audio))
                model.assert_not_called()
                processor.download_and_convert.assert_not_called()
                self.assertEqual("subtitles", result["transcript_source"])
                self.assertEqual("manual", result["subtitle_type"])
                self.assertIsNone(result["audio_file"])
                self.assertEqual("en", result["detected_language"])
                text = (root / result["transcript_file"]).read_text()
                self.assertIn("# Captioned Video\n\nComplete caption text.", text)
                self.assertIn(f"source: {url}", text)
                self.assertFalse(checkpoint.job_dir.exists())
                self.assertEqual([], list(root.glob(".work_*")))

    def test_missing_or_failed_captions_fall_back_to_audio(self):
        for failure in (None, RuntimeError("captions unavailable")):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                with patch.object(FakeVideoProcessor, "get_subtitle_transcript", return_value=None,
                                  side_effect=failure), \
                     patch.object(pipeline, "VideoProcessor", FakeVideoProcessor), \
                     patch.object(pipeline, "ObsidianTranscriber", FakeTranscriber):
                    result = asyncio.run(pipeline.process_video("https://video.test", Path(tmp)))
                self.assertEqual("audio", result["transcript_source"])
                self.assertIsNone(result["subtitle_type"])
                self.assertIn("transcript body", (Path(tmp) / result["transcript_file"]).read_text())

    def test_disabled_and_direct_podcast_skip_subtitle_requests(self):
        for setting, media in (("0", None), ("1", "https://cdn.test/podcast.mp3")):
            with self.subTest(setting=setting, media=media), tempfile.TemporaryDirectory() as tmp:
                with patch.dict("os.environ", {"SUBTITLES_FIRST": setting}), \
                     patch.object(FakeVideoProcessor, "get_subtitle_transcript") as lookup, \
                     patch.object(pipeline, "VideoProcessor", FakeVideoProcessor), \
                     patch.object(pipeline, "ObsidianTranscriber", FakeTranscriber):
                    result = asyncio.run(pipeline.process_video("https://video.test", Path(tmp), download_url=media))
                lookup.assert_not_called()
                self.assertEqual("audio", result["transcript_source"])

    def test_failed_caption_persistence_preserves_existing_audio_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            url = "https://video.test"
            checkpoint = TranscriptionCheckpoint(root / ".transcription_checkpoints", url)
            checkpoint.prepare({"test": True})
            processor = Mock(spec=FakeVideoProcessor)
            processor.get_subtitle_transcript.return_value = self.caption
            with patch.object(pipeline, "VideoProcessor", return_value=processor), \
                 patch.object(pipeline, "_write_file", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    asyncio.run(pipeline.process_video(url, root))
            self.assertTrue(checkpoint.manifest_path.exists())


class AtomicPersistenceTests(unittest.TestCase):
    def test_atomic_write_accepts_maximum_length_ascii_and_chinese_names(self):
        for name in ("a" * 252 + ".md", "中" * 84 + ".md"):
            with self.subTest(name_bytes=len(name.encode())), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / name
                asyncio.run(pipeline._write_file(path, "完整内容"))
                self.assertEqual("完整内容", path.read_text(encoding="utf-8"))
                self.assertEqual([path], list(Path(tmp).iterdir()))

    def test_failed_replace_preserves_existing_transcript_and_cleans_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.md"
            path.write_text("original", encoding="utf-8")
            with patch.object(pipeline.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    asyncio.run(pipeline._write_file(path, "replacement"))
            self.assertEqual("original", path.read_text(encoding="utf-8"))
            self.assertEqual([path], list(Path(tmp).iterdir()))

    def test_long_video_titles_save_from_subtitles_and_manual_transcript(self):
        title = "超长中文标题" * 80
        for source in ("subtitles", "manual"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                if source == "subtitles":
                    processor = Mock(spec=FakeVideoProcessor)
                    processor.get_subtitle_transcript.return_value = SubtitleTranscript(
                        "完整字幕正文", title, "zh-cn", "manual",
                    )
                    with patch.dict("os.environ", {"SUBTITLES_FIRST": "1"}), \
                         patch.object(pipeline, "VideoProcessor", return_value=processor), \
                         patch.object(pipeline, "ObsidianTranscriber") as model:
                        result = asyncio.run(pipeline.process_video("https://video.test", root))
                    model.assert_not_called()
                    processor.download_and_convert.assert_not_called()
                else:
                    result = asyncio.run(pipeline.process_transcript_input(
                        "完整字幕正文", root, video_title=title,
                    ))
                path = root / result["transcript_file"]
                self.assertLessEqual(len(path.name.encode()), 255)
                self.assertIn(title, path.read_text(encoding="utf-8"))
                self.assertIn("完整字幕正文", path.read_text(encoding="utf-8"))
                self.assertFalse(list(root.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()

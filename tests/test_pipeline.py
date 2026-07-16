import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import pipeline


class FakeVideoProcessor:
    last_url = None

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


if __name__ == "__main__":
    unittest.main()

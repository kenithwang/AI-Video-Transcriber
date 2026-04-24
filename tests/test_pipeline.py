import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import pipeline


class FakeVideoProcessor:
    async def download_and_convert(self, url, output_dir, *, video_info=None):
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / "audio_current.m4a"
        audio_path.write_bytes(b"audio")
        return str(audio_path), "Current Video"


class FakeTranscriber:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, audio_path):
        return ("transcript body", "en", [])


class PipelineCleanupTests(unittest.TestCase):
    def test_process_video_does_not_delete_unrelated_media_in_temp_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            unrelated = temp_dir / "other_job.m4a"
            unrelated.write_bytes(b"keep")

            with patch.object(pipeline, "VideoProcessor", FakeVideoProcessor):
                with patch.object(pipeline, "ObsidianTranscriber", FakeTranscriber):
                    asyncio.run(pipeline.process_video("https://example.test/v", temp_dir))

            self.assertTrue(unrelated.exists())


if __name__ == "__main__":
    unittest.main()

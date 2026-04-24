import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.obsidian_transcriber import AudioChunk, ObsidianTranscriber


class PartialFailureTranscriber(ObsidianTranscriber):
    def __init__(self):
        self.model_name = "test-model"


class ObsidianTranscriberTests(unittest.TestCase):
    def test_transcribe_raises_when_any_chunk_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.m4a"
            audio.write_bytes(b"audio")
            chunks = [
                AudioChunk(Path(tmp) / "chunk_001.wav", 0, 10),
                AudioChunk(Path(tmp) / "chunk_002.wav", 10, 20),
            ]
            for chunk in chunks:
                chunk.path.write_bytes(b"chunk")

            transcriber = PartialFailureTranscriber()
            transcriber.parallelism = 1

            with patch.object(transcriber, "_ffprobe_duration", return_value=1300):
                with patch.object(transcriber, "_split_audio", return_value=(chunks, Path(tmp))):
                    with patch.object(transcriber, "_gen_text", side_effect=["ok", ""]):
                        with self.assertRaises(RuntimeError):
                            transcriber.transcribe(audio)


if __name__ == "__main__":
    unittest.main()

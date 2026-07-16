import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.obsidian_transcriber import (
    AudioChunk,
    ChunkResult,
    ObsidianTranscriber,
    TranscriptionIncompleteError,
)


class PartialFailureTranscriber(ObsidianTranscriber):
    def __init__(self):
        self.model_name = "test-model"
        self.segment_seconds = 1200
        self.parallelism = 1
        self.max_chunk_attempts = 3
        self.retry_delay_seconds = 0
        self.checkpoint_root = None
        self._system_instruction = "system"
        self._transcribe_prompt = "prompt"


class ObsidianTranscriberTests(unittest.TestCase):
    def test_extract_response_includes_finish_reason_and_message(self) -> None:
        response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    finish_reason="MALFORMED_RESPONSE",
                    finish_message="Malformed function call",
                    content=SimpleNamespace(parts=[]),
                )
            ]
        )

        result = PartialFailureTranscriber()._extract_response(response)

        self.assertEqual("", result.text)
        self.assertEqual("MALFORMED_RESPONSE", result.finish_reason)
        self.assertEqual("Malformed function call", result.finish_message)

    def test_chunk_retries_independently_after_empty_response(self) -> None:
        transcriber = PartialFailureTranscriber()
        chunk = AudioChunk(Path("chunk.wav"), 0, 10)

        with patch.object(
            transcriber,
            "_gen_text",
            side_effect=[
                ChunkResult(
                    text="",
                    finish_reason="MALFORMED_RESPONSE",
                    finish_message="bad response",
                ),
                ChunkResult(text="complete text", finish_reason="STOP"),
            ],
        ) as generate:
            result = transcriber._transcribe_chunk_with_retry(chunk, 1)

        self.assertEqual("complete text", result.text)
        self.assertEqual(2, result.attempts)
        self.assertEqual(2, generate.call_count)

    def test_chunk_retries_when_finish_reason_indicates_truncation(self) -> None:
        transcriber = PartialFailureTranscriber()
        chunk = AudioChunk(Path("chunk.wav"), 0, 10)

        with patch.object(
            transcriber,
            "_gen_text",
            side_effect=[
                ChunkResult(text="partial text", finish_reason="MAX_TOKENS"),
                ChunkResult(text="complete text", finish_reason="STOP"),
            ],
        ) as generate:
            result = transcriber._transcribe_chunk_with_retry(chunk, 1)

        self.assertEqual("complete text", result.text)
        self.assertEqual(2, result.attempts)
        self.assertEqual(2, generate.call_count)

    def test_transcribe_resumes_only_missing_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "audio.m4a"
            audio.write_bytes(b"audio")
            chunks = [
                AudioChunk(root / "chunk_001.wav", 0, 10),
                AudioChunk(root / "chunk_002.wav", 10, 20),
            ]
            for chunk in chunks:
                chunk.path.write_bytes(b"chunk")

            transcriber = PartialFailureTranscriber()
            transcriber.checkpoint_root = root / "checkpoints"
            first_work = root / "first-work"
            first_work.mkdir()

            with patch.object(transcriber, "_ffprobe_duration", return_value=1300):
                with patch.object(transcriber, "_split_audio", return_value=(chunks, first_work)):
                    with patch.object(
                        transcriber,
                        "_transcribe_chunk_with_retry",
                        side_effect=[
                            ChunkResult(text="first", finish_reason="STOP", attempts=1),
                            ChunkResult(
                                text="",
                                finish_reason="MALFORMED_RESPONSE",
                                finish_message="bad response",
                                attempts=3,
                            ),
                        ],
                    ):
                        with self.assertRaises(TranscriptionIncompleteError) as caught:
                            transcriber.transcribe(audio, checkpoint_key="video-url")

            self.assertEqual([2], caught.exception.failed_chunks)

            resumed = PartialFailureTranscriber()
            resumed.checkpoint_root = root / "checkpoints"
            second_work = root / "second-work"
            second_work.mkdir()
            with patch.object(resumed, "_ffprobe_duration", return_value=1300):
                with patch.object(resumed, "_split_audio", return_value=(chunks, second_work)):
                    with patch.object(
                        resumed,
                        "_transcribe_chunk_with_retry",
                        return_value=ChunkResult(text="second", finish_reason="STOP", attempts=1),
                    ) as generate:
                        markdown, _, _ = resumed.transcribe(audio, checkpoint_key="video-url")

            generate.assert_called_once_with(chunks[1], 2)
            self.assertIn("first\n\nsecond", markdown)

    def test_transcribe_reuses_completed_checkpoint_without_gemini_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "audio.m4a"
            audio.write_bytes(b"audio")
            chunk = AudioChunk(root / "chunk_001.wav", 0, 10)
            chunk.path.write_bytes(b"chunk")

            first = PartialFailureTranscriber()
            first.checkpoint_root = root / "checkpoints"
            first_work = root / "first-work"
            first_work.mkdir()
            with patch.object(first, "_ffprobe_duration", return_value=1300):
                with patch.object(first, "_split_audio", return_value=([chunk], first_work)):
                    with patch.object(
                        first,
                        "_transcribe_chunk_with_retry",
                        return_value=ChunkResult(text="saved text", finish_reason="STOP"),
                    ):
                        first.transcribe(audio, checkpoint_key="video-url")

            resumed = PartialFailureTranscriber()
            resumed.checkpoint_root = root / "checkpoints"
            second_work = root / "second-work"
            second_work.mkdir()
            with patch.object(resumed, "_ffprobe_duration", return_value=1300):
                with patch.object(resumed, "_split_audio", return_value=([chunk], second_work)):
                    with patch.object(resumed, "_transcribe_chunk_with_retry") as generate:
                        markdown, _, _ = resumed.transcribe(audio, checkpoint_key="video-url")

            generate.assert_not_called()
            self.assertIn("saved text", markdown)


if __name__ == "__main__":
    unittest.main()

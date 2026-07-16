import tempfile
import unittest
from pathlib import Path

from backend.transcription_checkpoint import TranscriptionCheckpoint


class TranscriptionCheckpointTests(unittest.TestCase):
    def test_persists_chunk_results_and_completion_across_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            signature = {"model": "test-model", "chunks": [[0.0, 10.0], [10.0, 20.0]]}

            checkpoint = TranscriptionCheckpoint(root, "https://example.com/episode/1")
            checkpoint.prepare(signature)
            checkpoint.record_success(
                1,
                "first chunk",
                attempts=2,
                finish_reason="STOP",
                finish_message="",
            )
            checkpoint.record_failure(
                2,
                attempts=3,
                finish_reason="MALFORMED_RESPONSE",
                finish_message="malformed response",
                error="empty response",
            )

            reloaded = TranscriptionCheckpoint(root, "https://example.com/episode/1")
            reloaded.prepare(signature)

            self.assertEqual({1: "first chunk"}, reloaded.load_completed_texts())
            manifest = reloaded.manifest
            self.assertEqual("completed", manifest["chunks"]["1"]["status"])
            self.assertEqual("failed", manifest["chunks"]["2"]["status"])
            self.assertEqual("MALFORMED_RESPONSE", manifest["chunks"]["2"]["finish_reason"])

            reloaded.mark_complete()
            self.assertTrue(TranscriptionCheckpoint(root, "https://example.com/episode/1").is_complete)
            self.assertEqual([], list(reloaded.job_dir.glob("*.tmp")))

            reloaded.clear()
            self.assertFalse(reloaded.job_dir.exists())

    def test_incompatible_signature_discards_old_chunk_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            checkpoint = TranscriptionCheckpoint(root, "source-key")
            checkpoint.prepare({"model": "model-a", "chunks": [[0.0, 10.0]]})
            checkpoint.record_success(
                1,
                "old text",
                attempts=1,
                finish_reason="STOP",
                finish_message="",
            )

            checkpoint.prepare({"model": "model-b", "chunks": [[0.0, 10.0]]})

            self.assertEqual({}, checkpoint.load_completed_texts())
            self.assertEqual("model-b", checkpoint.manifest["signature"]["model"])
            self.assertFalse((checkpoint.job_dir / "chunk_001.txt").exists())


if __name__ == "__main__":
    unittest.main()

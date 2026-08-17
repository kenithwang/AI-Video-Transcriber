import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.ai_client import (
    DEFAULT_MODEL,
    OpenRouterClient,
    audio_format_for_path,
    get_model_name,
    normalize_finish_reason,
)


class AiClientTests(unittest.TestCase):
    def test_default_model_is_openrouter_gemini_37_flash(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENROUTER_MODEL", None)
            self.assertEqual("google/gemini-3.7-flash", DEFAULT_MODEL)
            self.assertEqual("google/gemini-3.7-flash", get_model_name())

    def test_normalize_openrouter_finish_reasons(self) -> None:
        self.assertEqual("STOP", normalize_finish_reason("stop"))
        self.assertEqual("MAX_TOKENS", normalize_finish_reason("length"))
        self.assertEqual("SAFETY", normalize_finish_reason("content_filter"))
        self.assertEqual("UNKNOWN", normalize_finish_reason(None))

    def test_audio_format_prefers_mp3_for_upload(self) -> None:
        self.assertEqual("mp3", audio_format_for_path(Path("chunk_001.mp3")))
        self.assertEqual("mp3", audio_format_for_path(Path("talk.m4a")))

    def test_generate_audio_sends_base64_input_audio(self) -> None:
        session = MagicMock()
        response = MagicMock()
        response.ok = True
        response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "hello speaker"},
                    "finish_reason": "stop",
                }
            ]
        }
        session.post.return_value = response

        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "chunk.mp3"
            audio.write_bytes(b"ID3-audio")
            client = OpenRouterClient(api_key="sk-or-test", model=DEFAULT_MODEL, session=session)
            result = client.generate_audio(audio, "Transcribe this", system="sys")

        self.assertEqual("hello speaker", result.text)
        self.assertEqual("STOP", result.finish_reason)
        payload = session.post.call_args.kwargs["json"]
        self.assertEqual("google/gemini-3.7-flash", payload["model"])
        user = payload["messages"][1]["content"]
        audio_part = next(part for part in user if part["type"] == "input_audio")
        self.assertEqual("mp3", audio_part["input_audio"]["format"])
        self.assertEqual(
            base64.b64encode(b"ID3-audio").decode("ascii"),
            audio_part["input_audio"]["data"],
        )

    def test_complete_raises_openrouter_error_body(self) -> None:
        session = MagicMock()
        response = MagicMock()
        response.ok = False
        response.status_code = 401
        response.json.return_value = {"error": {"message": "No auth credentials found"}}
        session.post.return_value = response
        client = OpenRouterClient(api_key="sk-or-test", session=session)

        with self.assertRaisesRegex(RuntimeError, "401"):
            client.generate_text("hi")
        self.assertEqual(1, session.post.call_count)

    def test_complete_retries_502_then_succeeds(self) -> None:
        session = MagicMock()
        fail = MagicMock()
        fail.ok = False
        fail.status_code = 502
        fail.json.return_value = {"error": {"message": "Bad Gateway"}}
        ok = MagicMock()
        ok.ok = True
        ok.json.return_value = {
            "choices": [{"message": {"content": "recovered"}, "finish_reason": "stop"}]
        }
        session.post.side_effect = [fail, ok]
        client = OpenRouterClient(api_key="sk-or-test", session=session)

        with patch("backend.ai_client.time.sleep"):
            result = client.generate_text("hi")

        self.assertEqual("recovered", result.text)
        self.assertEqual(2, session.post.call_count)

    def test_complete_retries_empty_choices(self) -> None:
        session = MagicMock()
        empty = MagicMock()
        empty.ok = True
        empty.json.return_value = {"choices": []}
        ok = MagicMock()
        ok.ok = True
        ok.json.return_value = {
            "choices": [{"message": {"content": "later"}, "finish_reason": "stop"}]
        }
        session.post.side_effect = [empty, ok]
        client = OpenRouterClient(api_key="sk-or-test", session=session)

        with patch("backend.ai_client.time.sleep"):
            result = client.generate_text("hi")

        self.assertEqual("later", result.text)
        self.assertEqual(2, session.post.call_count)


if __name__ == "__main__":
    unittest.main()

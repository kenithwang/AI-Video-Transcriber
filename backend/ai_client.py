"""OpenRouter chat client used for transcription, notes, and summaries."""

from __future__ import annotations

import base64
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests

DEFAULT_MODEL = "google/gemini-3.7-flash"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT_SECONDS = 600
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
DEFAULT_HTTP_RETRIES = 5
MP3_BITRATE = "64k"

_FINISH_REASON_MAP = {
    "stop": "STOP",
    "length": "MAX_TOKENS",
    "content_filter": "SAFETY",
    "tool_calls": "STOP",
}


@dataclass
class ChatResult:
    text: str
    finish_reason: str
    finish_message: str = ""


def get_api_key() -> str:
    key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("未设置 OPENROUTER_API_KEY")
    return key


def get_model_name(override: Optional[str] = None) -> str:
    if override and override.strip():
        return override.strip()
    return (os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def normalize_finish_reason(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    raw = str(value).strip()
    if not raw:
        return "UNKNOWN"
    mapped = _FINISH_REASON_MAP.get(raw.lower())
    if mapped:
        return mapped
    name = getattr(value, "name", None)
    if name:
        return str(name)
    if "." in raw and raw.split(".", 1)[0].lower().endswith("finishreason"):
        return raw.rsplit(".", 1)[-1]
    return raw


def audio_format_for_path(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    mapping = {
        "wav": "wav",
        "wave": "wav",
        "mp3": "mp3",
        "mpeg": "mp3",
        "m4a": "mp3",
        "aac": "mp3",
        "ogg": "ogg",
        "flac": "mp3",
        "webm": "mp3",
    }
    return mapping.get(ext, "mp3")


class TransientOpenRouterError(RuntimeError):
    """Retryable OpenRouter failure such as 502 or empty choices."""


def encode_audio_for_upload(path: Path) -> Path:
    """Return an MP3 suitable for OpenRouter. WAV is only used as a local temp."""
    src = Path(path)
    if src.suffix.lower() == ".mp3":
        return src
    dest = src.with_name(f"{src.stem}.upload.mp3")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "libmp3lame",
        "-b:a",
        MP3_BITRATE,
        str(dest),
    ]
    subprocess.check_call(cmd)
    return dest


class OpenRouterClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        session: Optional[requests.Session] = None,
    ):
        self.api_key = api_key or get_api_key()
        self.model = get_model_name(model)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/ken-wang/AI-Video-Transcriber",
                "X-Title": "AI Video Transcriber",
            }
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 65536,
    ) -> ChatResult:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        attempts = max(1, int(os.getenv("OPENROUTER_HTTP_RETRIES", str(DEFAULT_HTTP_RETRIES))))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return self._post_once(payload)
            except TransientOpenRouterError as exc:
                last_error = exc
            except requests.RequestException as exc:
                last_error = TransientOpenRouterError(str(exc))
            if attempt < attempts:
                time.sleep(min(32.0, 2.0 ** attempt))
        raise RuntimeError(f"OpenRouter 多次重试后仍失败: {last_error}")

    def _post_once(self, payload: dict[str, Any]) -> ChatResult:
        response = self.session.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            json=payload,
            timeout=self.timeout,
        )
        try:
            data = response.json()
        except ValueError as exc:
            if response.status_code in RETRYABLE_STATUS:
                raise TransientOpenRouterError(
                    f"OpenRouter 非 JSON 响应 ({response.status_code})"
                ) from exc
            response.raise_for_status()
            raise RuntimeError(f"OpenRouter 返回了非 JSON 响应: {response.text[:200]}") from exc

        if not response.ok:
            detail = data.get("error") if isinstance(data, dict) else data
            message = f"OpenRouter 请求失败 ({response.status_code}): {detail}"
            if response.status_code in RETRYABLE_STATUS:
                raise TransientOpenRouterError(message)
            raise RuntimeError(message)

        choices = data.get("choices") or []
        if not choices:
            raise TransientOpenRouterError("empty choices")

        choice = choices[0]
        message = choice.get("message") or {}
        text = (message.get("content") or "").strip()
        if not text:
            raise TransientOpenRouterError("empty content")
        return ChatResult(
            text=text,
            finish_reason=normalize_finish_reason(choice.get("finish_reason")),
            finish_message=str(choice.get("native_finish_reason") or ""),
        )

    def generate_text(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 65536,
    ) -> ChatResult:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.complete(messages, temperature=temperature, max_tokens=max_tokens)

    def generate_audio(
        self,
        audio_path: Path,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 65536,
    ) -> ChatResult:
        source = Path(audio_path)
        upload_path = encode_audio_for_upload(source)
        try:
            audio_bytes = upload_path.read_bytes()
            encoded = base64.b64encode(audio_bytes).decode("ascii")
            user_content = [
                {"type": "text", "text": prompt},
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": encoded,
                        "format": audio_format_for_path(upload_path),
                    },
                },
            ]
            messages: list[dict[str, Any]] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": user_content})
            return self.complete(messages, temperature=temperature, max_tokens=max_tokens)
        finally:
            if upload_path != source:
                upload_path.unlink(missing_ok=True)

"""Atomic, file-backed checkpoints for chunked transcription jobs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TranscriptionCheckpoint:
    """Persist completed chunk text and response metadata for one source."""

    VERSION = 1

    def __init__(self, root: Path | str, source_key: str):
        self.root = Path(root)
        self.source_hash = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
        self.job_dir = self.root / self.source_hash
        self.manifest_path = self.job_dir / "manifest.json"

    @property
    def manifest(self) -> dict[str, Any]:
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}

    @property
    def is_complete(self) -> bool:
        return bool(self.manifest.get("complete", False))

    def prepare(self, signature: dict[str, Any]) -> None:
        current = self.manifest
        if current.get("version") != self.VERSION or current.get("signature") != signature:
            shutil.rmtree(self.job_dir, ignore_errors=True)
            self.job_dir.mkdir(parents=True, exist_ok=True)
            self._write_manifest(
                {
                    "version": self.VERSION,
                    "source_hash": self.source_hash,
                    "signature": signature,
                    "complete": False,
                    "chunks": {},
                    "updated_at": self._now(),
                }
            )
        else:
            self.job_dir.mkdir(parents=True, exist_ok=True)

    def load_completed_texts(self) -> dict[int, str]:
        completed: dict[int, str] = {}
        for raw_index, info in self.manifest.get("chunks", {}).items():
            if not isinstance(info, dict) or info.get("status") != "completed":
                continue
            try:
                index = int(raw_index)
                text = self._chunk_path(index).read_text(encoding="utf-8")
            except (TypeError, ValueError, OSError):
                continue
            if text.strip():
                completed[index] = text
        return completed

    def record_success(
        self,
        index: int,
        text: str,
        *,
        attempts: int,
        finish_reason: str,
        finish_message: str,
    ) -> None:
        self._atomic_write_text(self._chunk_path(index), text)
        self._record_chunk(
            index,
            {
                "status": "completed",
                "attempts": attempts,
                "finish_reason": finish_reason,
                "finish_message": finish_message,
                "error": "",
                "text_chars": len(text),
            },
        )

    def record_failure(
        self,
        index: int,
        *,
        attempts: int,
        finish_reason: str,
        finish_message: str,
        error: str,
    ) -> None:
        try:
            self._chunk_path(index).unlink()
        except FileNotFoundError:
            pass
        self._record_chunk(
            index,
            {
                "status": "failed",
                "attempts": attempts,
                "finish_reason": finish_reason,
                "finish_message": finish_message,
                "error": error,
                "text_chars": 0,
            },
        )

    def mark_complete(self) -> None:
        data = self.manifest
        data["complete"] = True
        data["updated_at"] = self._now()
        self._write_manifest(data)

    def clear(self) -> None:
        shutil.rmtree(self.job_dir, ignore_errors=True)

    def _record_chunk(self, index: int, info: dict[str, Any]) -> None:
        data = self.manifest
        chunks = data.setdefault("chunks", {})
        info["updated_at"] = self._now()
        chunks[str(index)] = info
        data["complete"] = False
        data["updated_at"] = self._now()
        self._write_manifest(data)

    def _chunk_path(self, index: int) -> Path:
        return self.job_dir / f"chunk_{index:03d}.txt"

    def _write_manifest(self, data: dict[str, Any]) -> None:
        self._atomic_write_text(
            self.manifest_path,
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        )

    def _atomic_write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            self._fsync_directory(path.parent)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

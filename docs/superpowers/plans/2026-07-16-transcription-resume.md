# Gemini Chunk Retry and Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist successful Gemini transcription chunks, expose finish reasons, retry only failed chunks, and resume incomplete jobs without permanent skipping.

**Architecture:** Add a small atomic file-backed checkpoint store keyed by source URL. Refactor `ObsidianTranscriber` to return structured chunk results and let its coordinator persist each completed future; wire lifecycle finalization through the pipeline and classify incomplete transcription separately in the monitor.

**Tech Stack:** Python 3.13, google-genai, pathlib/json/os.replace, unittest/pytest.

---

### Task 1: Atomic checkpoint store

**Files:**
- Create: `backend/transcription_checkpoint.py`
- Create: `tests/test_transcription_checkpoint.py`

- [x] Write tests that prepare a checkpoint, atomically save success/failure metadata, reload completed text, invalidate incompatible signatures, mark complete, and clear the job.
- [x] Run `uv run --with pytest pytest tests/test_transcription_checkpoint.py -q`; expect import failure because the store does not exist.
- [x] Implement `TranscriptionCheckpoint` with SHA-256 job directories, `manifest.json`, `chunk_NNN.txt`, atomic writes, compatibility reset, and clear.
- [x] Re-run the checkpoint tests; expect all pass.

### Task 2: Structured finish reasons and per-chunk retries

**Files:**
- Modify: `backend/obsidian_transcriber.py`
- Modify: `tests/test_obsidian_transcriber.py`

- [x] Add failing tests for response finish reason extraction and a malformed/empty first attempt followed by a successful second attempt.
- [x] Run the focused tests and confirm failures are caused by missing `ChunkResult` and retry behavior.
- [x] Implement `ChunkResult`, normalized finish reason/message extraction, response logging, configurable attempts, and exponential retry around one chunk only.
- [x] Re-run focused tests; expect all pass.

### Task 3: Resume orchestration

**Files:**
- Modify: `backend/obsidian_transcriber.py`
- Modify: `tests/test_obsidian_transcriber.py`

- [x] Add failing tests proving successful chunks are persisted immediately, a new transcriber runs only the missing chunk, and a complete checkpoint reconstructs the transcript without Gemini calls.
- [x] Run focused tests and confirm the resume assertions fail.
- [x] Integrate `TranscriptionCheckpoint` into `transcribe(checkpoint_key=...)`, persist each completed future, raise `TranscriptionIncompleteError` for missing chunks, and expose `clear_checkpoint()`.
- [x] Re-run focused tests; expect all pass.

### Task 4: Pipeline lifecycle and monitor classification

**Files:**
- Modify: `backend/pipeline.py`
- Modify: `backend/channel_monitor.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_failure_backoff.py`

- [x] Add failing tests that the pipeline passes a stable key and clears only after transcript persistence, and that recoverable transcription failures are not permanently marked processed at the threshold.
- [x] Run the focused tests and confirm the new assertions fail.
- [x] Pass checkpoint root/key through the pipeline, clear after durable output, and exempt `TranscriptionIncompleteError` from permanent skip.
- [x] Re-run focused tests; expect all pass.

### Task 5: Documentation and verification

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `README_ZH.md`

- [x] Document `TRANSCRIBE_CHUNK_MAX_ATTEMPTS`, `TRANSCRIBE_RETRY_DELAY_SECONDS`, checkpoint location, resume behavior, and cleanup-on-success.
- [x] Run `uv run --with pytest pytest -q`; expect 0 failures.
- [x] Run `uv run python -m compileall -q backend cli.py`; expect exit 0.
- [x] Review `git diff --check` and `git status --short`, then commit only scoped files.

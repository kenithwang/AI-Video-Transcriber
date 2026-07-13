# CLI Monitoring Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make channel monitoring truthful, failure-safe, observable, and easier to operate without changing existing configuration or processed-store formats.

**Architecture:** Keep the current CLI and monitor structure, but separate read-only discovery from mutations, centralize watch outcome classification, and add small testable CLI helpers for status and stale-work cleanup. Cleanup remains scoped to per-job `.work_*` directories.

**Tech Stack:** Python 3.13, argparse, asyncio, pathlib, pytest/unittest, uv.

---

### Task 1: Failure-safe work directories

**Files:** `tests/test_pipeline.py`, `backend/pipeline.py`

- [x] Add a test whose transcriber raises after an audio file is created and assert no `.work_*` directory remains.
- [x] Run the focused test and confirm it fails because the directory remains.
- [x] Add exception-safe cleanup while preserving `--keep-audio` semantics.
- [x] Run the focused pipeline tests.

### Task 2: Pure dry-run and visible channel failures

**Files:** `tests/test_channel_monitor_experience.py`, `backend/channel_monitor.py`

- [x] Add tests proving dry-run does not create the processed store and fetch errors appear in `errors`.
- [x] Run the tests and confirm the current mutation and swallowed-error behavior fails them.
- [x] Add a mutation flag to filtering and propagate yt-dlp download errors.
- [x] Pass `mutate=not dry_run` from `run_check()` and run monitor tests.

### Task 3: Truthful watch status

**Files:** `tests/test_cli_experience.py`, `cli.py`, `backend/channel_monitor.py`

- [x] Add table-driven tests for `SUCCESS`, `PARTIAL`, and `FAILED` log outcomes.
- [x] Add channel-error counts to returned statistics and a helper deciding full-run failure.
- [x] Return a nonzero exit when discovered work wholly fails or every channel check fails.
- [x] Run focused CLI tests.

### Task 4: Status and stale-work cleanup

**Files:** `tests/test_cli_experience.py`, `cli.py`

- [x] Add tests for status aggregation and age-scoped cleanup.
- [x] Implement `--status`, `--cleanup`, and `--cleanup-hours` with no network access.
- [x] Verify fresh work directories and non-work files are never deleted.

### Task 5: Optional Note flow and quiet help

**Files:** `tests/test_cli_experience.py`, `tests/test_pipeline.py`, `cli.py`, `backend/note_generator.py`

- [x] Add tests for interactive `0` skip and transcript-mode Note generation.
- [x] Implement `--no-note`, mode `0`, and pass explicit note mode into transcript processing.
- [x] Move dotenv loading after argparse so `--help` is quiet.
- [x] Change yt-dlp update instructions to uv-native commands.

### Task 6: Documentation and verification

**Files:** `README.md`, `README_ZH.md`

- [x] Document status, cleanup, no-note, watch exit behavior, and `uv run --with pytest pytest -q`.
- [x] Run `uv run --with pytest pytest -q` and require all tests to pass.
- [x] Run `uv run python -m compileall -q cli.py backend tests`.
- [x] Smoke-test `--help`, `--status`, and cleanup against an isolated temporary directory.
- [x] Inspect `git diff --check` and confirm runtime data and the pre-existing `uv.lock` change were not overwritten.

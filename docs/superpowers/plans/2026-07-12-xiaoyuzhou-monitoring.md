# Xiaoyuzhou Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Monitor nine selected Xiaoyuzhou podcasts through the existing watch pipeline while baselining all current episodes as processed and sent.

**Architecture:** Add a focused authenticated Xiaoyuzhou client with RSSHub fallback, map podcast episodes into `VideoInfo`, and pass direct audio URLs through the existing pipeline without changing the public source URL. Add an explicit baseline command so historical episodes never enter the transcription queue.

**Tech Stack:** Python 3.13, requests, stdlib XML, yt-dlp, pytest/unittest, YAML.

---

### Task 1: Xiaoyuzhou client

**Files:**
- Create: `backend/xiaoyuzhou_client.py`
- Create: `tests/test_xiaoyuzhou_client.py`

- [ ] Write failing tests for podcast-id parsing, paginated episode normalization, 401 refresh/retry, atomic token persistence, and RSSHub fallback.
- [ ] Run `uv run --with pytest pytest tests/test_xiaoyuzhou_client.py -q` and confirm failures are caused by the missing client.
- [ ] Implement the minimal client using `requests.Session`, repository-external credentials, and stdlib RSS parsing.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: ChannelMonitor source adapter

**Files:**
- Modify: `backend/channel_monitor.py`
- Create: `tests/test_xiaoyuzhou_monitor.py`

- [ ] Write failing tests proving podcast URLs bypass yt-dlp, API records become `VideoInfo` with eid and media URL, live checks are skipped, and processing passes separate public/download URLs.
- [ ] Run the focused tests and confirm expected failures.
- [ ] Add source dispatch, ISO date parsing, `media_url`, and pipeline arguments with no behavior change for YouTube/Bilibili.
- [ ] Re-run focused and existing monitor tests.

### Task 3: Direct-media pipeline support

**Files:**
- Modify: `backend/pipeline.py`
- Modify: `tests/test_pipeline.py`

- [ ] Write a failing test proving `download_url` is downloaded while the transcript source remains the public episode URL.
- [ ] Run the focused test and confirm it fails on the missing argument.
- [ ] Implement the optional `download_url` parameter.
- [ ] Re-run pipeline tests.

### Task 4: Safe baseline command

**Files:**
- Modify: `backend/channel_monitor.py`
- Modify: `cli.py`
- Modify: `tests/test_xiaoyuzhou_monitor.py`

- [ ] Write failing tests proving only enabled Xiaoyuzhou channels are baselined and every fetched eid is stored with `sent=true` without invoking transcription.
- [ ] Run the focused tests and confirm expected failures.
- [ ] Implement `baseline_xiaoyuzhou()` and `--baseline-xiaoyuzhou`.
- [ ] Re-run CLI/monitor tests.

### Task 5: Configuration and operational rollout

**Files:**
- Modify: `.env.example`
- Modify: `channels.example.yaml`
- Runtime-only: `/home/ken-wang/AI-Video-Transcriber/.env`
- Runtime-only: `/home/ken-wang/AI-Video-Transcriber/channels.yaml`
- Runtime-only: `/home/ken-wang/AI-Video-Transcriber/.processed_videos.json`

- [ ] Document token/RSSHub variables and a disabled Xiaoyuzhou example.
- [ ] Run the full test suite and `compileall` in the worktree.
- [ ] Integrate the code into main without overwriting the user's dirty `uv.lock`.
- [ ] Configure the nine podcast URLs and repository-external token path; verify no Zhang Xiaojun YouTube channel remains.
- [ ] Back up `.processed_videos.json`, run `--baseline-xiaoyuzhou`, and verify every configured podcast's current eid exists with `sent=true`.
- [ ] Run `--watch --dry-run` and verify zero historical Xiaoyuzhou episodes are queued.

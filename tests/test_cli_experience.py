import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import cli
from backend.note_generator import interactive_select_mode
from backend.processed_store import ProcessedStore


class WatchOutcomeTests(unittest.TestCase):
    def test_success_requires_no_video_or_channel_failures(self) -> None:
        self.assertEqual(
            "SUCCESS",
            cli.classify_watch_outcome(
                found=2, processed=2, failed=0, channel_errors=0
            ),
        )

    def test_partial_means_some_work_succeeded(self) -> None:
        self.assertEqual(
            "PARTIAL",
            cli.classify_watch_outcome(
                found=3, processed=2, failed=1, channel_errors=0
            ),
        )

    def test_failed_means_nothing_succeeded(self) -> None:
        self.assertEqual(
            "FAILED",
            cli.classify_watch_outcome(
                found=3, processed=0, failed=3, channel_errors=0
            ),
        )

    def test_partial_means_only_some_channel_checks_failed(self) -> None:
        self.assertEqual(
            "PARTIAL",
            cli.classify_watch_outcome(
                found=0,
                processed=0,
                failed=0,
                channel_errors=1,
                channels_checked=2,
            ),
        )

    def test_nonzero_exit_requires_all_channel_checks_to_fail(self) -> None:
        partial_channel_failure = {
            "found": 0,
            "processed": 0,
            "failed": 0,
            "channel_errors": 1,
            "channels_checked": 2,
        }
        all_channels_failed = {
            **partial_channel_failure,
            "channel_errors": 2,
        }

        self.assertFalse(cli.watch_run_failed(partial_channel_failure))
        self.assertTrue(cli.watch_run_failed(all_channels_failed))

    def test_dry_run_only_fails_when_all_channel_checks_fail(self) -> None:
        preview_with_work = {
            "found": 2,
            "processed": 0,
            "failed": 2,
            "channel_errors": 0,
            "channels_checked": 1,
        }
        all_channels_failed = {
            "found": 0,
            "processed": 0,
            "failed": 0,
            "channel_errors": 2,
            "channels_checked": 2,
        }

        self.assertFalse(cli.watch_run_failed(preview_with_work, dry_run=True))
        self.assertTrue(cli.watch_run_failed(all_channels_failed, dry_run=True))

    def test_watch_log_reports_partial_and_pending_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "watch.log"
            with patch.object(cli, "WATCH_LOG_PATH", log_path):
                cli.write_watch_log(
                    found=2,
                    processed=1,
                    sent=0,
                    failed=1,
                    channel_errors=1,
                )

            line = log_path.read_text(encoding="utf-8")
            self.assertIn("[PARTIAL]", line)
            self.assertIn("待发送 1 个", line)
            self.assertIn("频道错误 1 个", line)
        self.assertEqual(
            "FAILED",
            cli.classify_watch_outcome(
                found=0, processed=0, failed=0, channel_errors=2
            ),
        )


class RuntimeStatusTests(unittest.TestCase):
    def test_preflight_reuses_fresh_update_cache_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "yt-dlp-check.json"
            cache.write_text(
                json.dumps(
                    {
                        "checked_at": 1_000.0,
                        "notices": ["cached update notice"],
                    }
                ),
                encoding="utf-8",
            )

            with patch("yt_dlp.update.Updater") as updater:
                notices = cli.preflight_checks(
                    cache_path=cache,
                    now=1_100.0,
                    max_age_hours=24,
                )

            self.assertEqual(["cached update notice"], notices)
            updater.assert_not_called()

    def test_collect_runtime_status_summarizes_operational_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "channels.yaml"
            config.write_text(
                yaml.safe_dump(
                    {
                        "settings": {"processed_store": "processed.json"},
                        "channels": [
                            {"url": "https://a", "enabled": True},
                            {"url": "https://b", "enabled": False},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            store = ProcessedStore(root / "processed.json")
            store.mark_processed("done", "Done", "https://done", sent=True)
            store.mark_processed("unsent", "Unsent", "https://unsent")
            store.record_failure("broken", "Broken", "https://broken", error="x")
            outdir = root / "temp"
            (outdir / ".work_old").mkdir(parents=True)

            status = cli.collect_runtime_status(config, outdir)

            self.assertEqual(2, status["channels_total"])
            self.assertEqual(1, status["channels_enabled"])
            self.assertEqual(2, status["processed"])
            self.assertEqual(1, status["unsent"])
            self.assertEqual(1, status["failures"])
            self.assertEqual(1, status["workdirs"])

    def test_custom_outdir_watch_log_is_visible_to_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "channels.yaml"
            config.write_text("channels: []\n", encoding="utf-8")
            outdir = root / "custom-output"
            log_path = outdir / "watch.log"

            cli.write_watch_log(0, 0, 0, 0, log_path=log_path)
            status = cli.collect_runtime_status(config, outdir)

            self.assertIn("[SUCCESS]", status["last_watch"])

    def test_cleanup_stale_workdirs_only_removes_old_private_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp)
            old = outdir / ".work_old"
            fresh = outdir / ".work_fresh"
            unrelated = outdir / "keep"
            old.mkdir()
            fresh.mkdir()
            unrelated.mkdir()
            old_time = time.time() - 7200
            os.utime(old, (old_time, old_time))

            result = cli.cleanup_stale_workdirs(outdir, older_than_hours=1)

            self.assertEqual(1, result["removed"])
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(unrelated.exists())

    def test_cleanup_stale_workdirs_skips_directory_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp)
            target = outdir / "target"
            target.mkdir()
            link = outdir / ".work_link"
            link.symlink_to(target, target_is_directory=True)
            old_time = time.time() - 7200
            os.utime(target, (old_time, old_time))

            result = cli.cleanup_stale_workdirs(outdir, older_than_hours=1)

            self.assertEqual(0, result["removed"])
            self.assertTrue(link.is_symlink())
            self.assertTrue(target.is_dir())


class NoteExperienceTests(unittest.TestCase):
    def test_interactive_note_mode_accepts_zero_to_skip(self) -> None:
        with patch("builtins.input", side_effect=["0", "1"]):
            self.assertIsNone(interactive_select_mode())

    def test_help_is_quiet_and_lists_no_note(self) -> None:
        result = subprocess.run(
            [sys.executable, "cli.py", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, result.returncode)
        self.assertFalse(result.stdout.startswith("[i] 已加载环境文件"))
        self.assertNotIn("video_transcriber completed", result.stdout)
        self.assertNotIn("[FAILED]", result.stdout)
        self.assertIn("--no-note", result.stdout)

    def test_transcript_mode_generates_note_when_mode_is_explicit(self) -> None:
        async def fake_process_transcript_input(**kwargs):
            outdir = kwargs["temp_dir"]
            (outdir / "transcript_manual.md").write_text("body", encoding="utf-8")
            return {
                "video_title": "Manual",
                "detected_language": "zh",
                "transcript_file": "transcript_manual.md",
                "warnings": [],
            }

        calls = []

        async def fake_generate_note(**kwargs):
            calls.append(kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "backend.pipeline.process_transcript_input",
                fake_process_transcript_input,
            ):
                with patch.object(
                    cli, "generate_note_from_transcript", fake_generate_note
                ):
                    asyncio.run(
                        cli.run_transcript_pipeline(
                            "body",
                            Path(tmp),
                            title="Manual",
                            note_mode=2,
                        )
                    )

        self.assertEqual(1, len(calls))
        self.assertEqual(2, calls[0]["mode_index"])


if __name__ == "__main__":
    unittest.main()

import asyncio
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from backend import runtime_diagnostics as diagnostics

SECRET = "https://private.test/watch?token=SECRET cookie=PRIVATE title=PRIVATE prompt=PRIVATE"


class RuntimeDiagnosticsTests(unittest.TestCase):
    def collect(self, action):
        stream = io.StringIO()
        collector = diagnostics.WatchDiagnostics(Path("/tmp"), stream=stream)
        with patch.object(diagnostics, "collect_metrics", return_value={}), patch.object(
            diagnostics, "WatchDiagnostics", return_value=collector
        ):
            with diagnostics.watch_diagnostics(Path("/tmp")):
                action(collector)
        return [json.loads(line) for line in stream.getvalue().splitlines()]

    def test_phase_lifecycle_redacts_content_and_preserves_errors(self):
        def action(collector):
            with diagnostics.phase("video", url=SECRET, title=SECRET, input_bytes=12):
                with diagnostics.phase("upload_encode", concurrency=2, prompt=SECRET):
                    pass
                with self.assertRaisesRegex(RuntimeError, "SECRET"):
                    with diagnostics.phase("cloud_request", exception_message=SECRET):
                        raise RuntimeError(SECRET)
            self.assertFalse(collector.active)
            self.assertIsNone(collector.job_id)
        records = self.collect(action)
        text = json.dumps(records)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("PRIVATE", text)
        self.assertNotIn("https://", text)
        self.assertTrue(any(r["event"] == "watch_start" for r in records))
        starts = [r for r in records if r["event"] == "phase_start"]
        ends = [r for r in records if r["event"] == "phase_end"]
        self.assertEqual(3, len(starts))
        self.assertEqual({r["phase_id"] for r in starts}, {r["phase_id"] for r in ends})
        self.assertEqual(1, len({r["job_id"] for r in starts}))
        failed = next(r for r in ends if r["phase"] == "cloud_request")
        self.assertEqual(("failed", "RuntimeError"), (failed["status"], failed["error_type"]))
        self.assertTrue(all(r["duration_seconds"] >= 0 for r in ends))

    def test_async_wrapper_and_cancellation_preserve_outcomes(self):
        @diagnostics.diagnosed("download")
        async def success():
            return "unchanged"
        async def action_async():
            self.assertEqual("unchanged", await success())
            with self.assertRaises(asyncio.CancelledError):
                with diagnostics.phase("cloud_request"):
                    raise asyncio.CancelledError(SECRET)
        records = self.collect(lambda _: asyncio.run(action_async()))
        cancelled = next(r for r in records if r.get("status") == "cancelled")
        self.assertEqual("CancelledError", cancelled["error_type"])
        self.assertNotIn(SECRET, json.dumps(records))

    def test_unknown_exception_name_and_fields_do_not_enter_log(self):
        class PrivateTokenException(Exception):
            pass
        def action(collector):
            collector.emit("phase_start", phase="download", phase_id="a" * 12,
                           job_id=SECRET, status=SECRET, error_type=SECRET,
                           input_bytes=float("nan"), duration_seconds=10**1000, cookie=SECRET)
            with self.assertRaises(PrivateTokenException):
                with diagnostics.phase("download"):
                    raise PrivateTokenException(SECRET)
        records = self.collect(action)
        self.assertNotIn(SECRET, json.dumps(records))
        self.assertNotIn("PrivateTokenException", json.dumps(records))
        self.assertEqual("Exception", next(r for r in records if r.get("status") == "failed")["error_type"])

    def test_bounded_queue_and_failed_output_never_change_work(self):
        collector = diagnostics.WatchDiagnostics(Path("/tmp"), stream=io.StringIO())
        for _ in range(500):
            collector.emit("watch_start")
        self.assertEqual(128, collector.queue.qsize())
        self.assertEqual(372, collector.dropped)
        with patch.object(diagnostics, "WatchDiagnostics", side_effect=OSError(SECRET)):
            with diagnostics.watch_diagnostics(Path("/tmp")):
                self.assertEqual(42, 40 + 2)
        self.assertIsNone(diagnostics._current)
        def action(active):
            with patch.object(active, "emit", side_effect=OSError(SECRET)):
                with diagnostics.phase("video"):
                    result = "unchanged"
            self.assertEqual("unchanged", result)
            self.assertFalse(active.active)
            self.assertIsNone(active.job_id)
        self.collect(action)

    def test_blocked_output_does_not_block_pipeline_or_shutdown(self):
        blocked, release = threading.Event(), threading.Event()
        class BlockedStream:
            def write(self, value):
                blocked.set()
                release.wait(3)
            def flush(self):
                pass
        collector = diagnostics.WatchDiagnostics(Path("/tmp"), stream=BlockedStream())
        started = time.monotonic()
        try:
            with patch.object(diagnostics, "collect_metrics", return_value={}), patch.object(
                diagnostics, "WatchDiagnostics", return_value=collector
            ):
                with diagnostics.watch_diagnostics(Path("/tmp")):
                    self.assertTrue(blocked.wait(1))
                    with diagnostics.phase("download"):
                        result = "unchanged"
            self.assertEqual("unchanged", result)
            self.assertLess(time.monotonic() - started, 1.5)
        finally:
            release.set()
            collector.thread.join(timeout=1)

    def test_heartbeat_continues_during_synchronous_phase(self):
        stream, observed = io.StringIO(), threading.Event()
        collector = diagnostics.WatchDiagnostics(Path("/tmp"), interval=1, stream=stream)
        def sample(_):
            with collector.lock:
                if any(info["phase"] == "channel_fetch" for info in collector.active.values()):
                    observed.set()
            return {}
        with patch.object(diagnostics, "collect_metrics", side_effect=sample), patch.object(
            diagnostics, "WatchDiagnostics", return_value=collector
        ):
            with diagnostics.watch_diagnostics(Path("/tmp")):
                with diagnostics.phase("channel_fetch"):
                    self.assertTrue(observed.wait(2))
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertTrue(any(r["event"] == "heartbeat" and any(
            p["phase"] == "channel_fetch" for p in r["active_phases"]
        ) for r in records))

    def test_cgroup_and_child_metrics_are_bounded_and_ignore_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc, cg = root / "proc", root / "cgroup"
            def write(path, content):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            write(proc / "self/cgroup", "0::/system.slice/video.service\n")
            group = cg / "system.slice/video.service"
            for name, content in {
                "memory.current": "1024", "memory.peak": "2048", "memory.swap.current": "512",
                "memory.events": "oom 1\noom_kill 1\nhigh 3\n",
                "memory.stat": "anon 128\nfile 256\nshmem 32\nsecret 999\n",
                "cpu.stat": "usage_usec 123\nnr_throttled 2\nthrottled_usec 45\n",
                "io.stat": "8:0 rbytes=123 wbytes=456 rios=1 wios=2\n",
                "cgroup.procs": f"{os.getpid()}\n1111111\n1111112\n",
                "memory.pressure": "some avg10=1.00 avg60=2.00 total=3\nfull avg10=0.10 total=1\n",
            }.items():
                write(group / name, content)
            for pid in [os.getpid(), 1111111]:
                write(proc / str(pid) / "status", "VmRSS:\t12 kB\nVmSwap:\t3 kB\n")
                write(proc / str(pid) / "io", "read_bytes: 7\nwrite_bytes: 9\n")
                write(proc / str(pid) / "cmdline", SECRET)
                write(proc / str(pid) / "environ", SECRET)
            metrics = diagnostics.collect_metrics(root, proc_root=proc, cgroup_root=cg)
            self.assertEqual(12288, metrics["self"]["VmRSS"])
            self.assertEqual(2048, metrics["cgroup"]["memory.peak"])
            self.assertEqual(123, metrics["cgroup"]["io.stat"]["rbytes"])
            self.assertEqual(1, metrics["cgroup"]["other_process_sampled_count"])
            self.assertEqual(7, metrics["cgroup"]["other_process_totals"]["read_bytes"])
            self.assertNotIn(SECRET, json.dumps(metrics))
            self.assertNotIn("secret", metrics["cgroup"]["memory.stat"])
            write(group / "cgroup.procs", "1111111\n" * 100)
            bounded = diagnostics.collect_metrics(root, proc_root=proc, cgroup_root=cg)
            self.assertEqual(64, bounded["cgroup"]["other_process_sampled_count"])
            self.assertEqual(16, len(bounded["cgroup"]["other_process_samples"]))
            write(group / "memory.current", "invalid")
            malformed = diagnostics.collect_metrics(root, proc_root=proc, cgroup_root=cg)
            self.assertNotIn("memory.current", malformed["cgroup"])
            self.assertEqual(2048, malformed["cgroup"]["memory.peak"])
            write(proc / "self/cgroup", "0::/../../private\n")
            escaped = diagnostics.collect_metrics(root, proc_root=proc, cgroup_root=cg)
            self.assertNotIn("cgroup", escaped)

    def test_missing_or_malformed_metrics_and_file_stat_are_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(diagnostics.file_size(root / "missing"))
            metrics = diagnostics.collect_metrics(root, proc_root=root, cgroup_root=root)
            self.assertNotIn("self", metrics)
            self.assertNotIn("cgroup", metrics)


if __name__ == "__main__":
    unittest.main()

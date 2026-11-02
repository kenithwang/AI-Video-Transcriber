"""Bounded, best-effort watcher evidence; never logs input or provider content."""
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import inspect
import json
import math
import os
from pathlib import Path
from queue import Empty, Full, Queue
import sys
from threading import Event, Lock, Thread
import time
import uuid

PHASES = frozenset({
    "watch_prepare", "channel_fetch", "live_probe", "video", "subtitles", "download_convert",
    "download_probe", "download", "duration_probe", "remux", "normalize",
    "silence_detect", "split", "split_encode", "transcribe", "transcribe_queue", "chunk_attempt",
    "upload_prepare", "upload_read", "upload_encode", "cloud_request", "persist",
    "note", "sync",
})
FIELDS = frozenset({"item_index", "item_count", "chunk_index", "chunk_count",
                    "attempt", "concurrency", "input_bytes", "duration_seconds"})
ERRORS = frozenset({"Exception", "RuntimeError", "ValueError", "OSError",
                    "TimeoutError", "CalledProcessError", "HTTPError",
                    "CancelledError", "KeyboardInterrupt", "SystemExit",
                    "TranscriptionIncompleteError"})
_current = None


def file_size(path):
    try:
        return Path(path).stat().st_size
    except Exception:
        return None


def _read(path, limit=16384):
    with Path(path).open() as handle:
        return handle.read(limit)


def _proc(pid, proc_root):
    root = proc_root / str(pid)
    values = {}
    for line in _read(root / "status").splitlines():
        if line.startswith(("VmRSS:", "VmSwap:")):
            key, raw = line.split(":", 1)
            values[key] = int(raw.split()[0]) * 1024
    for line in _read(root / "io").splitlines():
        key, raw = line.split(":", 1)
        if key in {"read_bytes", "write_bytes"}:
            values[key] = int(raw.strip())
    return values


def _pressure(path):
    result = {}
    for line in _read(path, 1024).splitlines():
        parts = line.split()
        if parts and parts[0] in {"some", "full"}:
            fields = dict(item.split("=", 1) for item in parts[1:])
            if "avg10" in fields:
                result[parts[0] + "_avg10"] = float(fields["avg10"])
    return result


def collect_metrics(temp_dir, *, proc_root=Path("/proc"), cgroup_root=Path("/sys/fs/cgroup")):
    """Fixed schema; bounded reads/PID count, no argv/environ or file tree scan."""
    metrics = {}
    try:
        metrics["self"] = _proc(os.getpid(), proc_root)
    except Exception:
        pass
    cgroup = None
    try:
        for line in _read(proc_root / "self/cgroup", 4096).splitlines():
            if line.startswith("0::/"):
                candidate = (cgroup_root / line[4:]).resolve()
                if candidate.is_relative_to(cgroup_root.resolve()):
                    cgroup = candidate
                break
    except Exception:
        pass
    if cgroup is not None:
        group = {}
        for name in ("memory.current", "memory.peak", "memory.swap.current"):
            try:
                group[name] = int(_read(cgroup / name, 64).strip())
            except Exception:
                pass
        for name, allowed in (("memory.events", {"low", "high", "max", "oom", "oom_kill", "oom_group_kill"}),
                              ("memory.stat", {"anon", "file", "shmem"}),
                              ("cpu.stat", {"usage_usec", "nr_throttled", "throttled_usec"})):
            try:
                pairs = (line.split() for line in _read(cgroup / name).splitlines())
                group[name] = {key: int(value) for key, value in pairs if key in allowed}
            except Exception:
                pass
        try:
            totals = {key: 0 for key in ("rbytes", "wbytes", "rios", "wios")}
            for line in _read(cgroup / "io.stat", 4096).splitlines():
                for pair in line.split()[1:]:
                    key, value = pair.split("=", 1)
                    if key in totals:
                        totals[key] += int(value)
            group["io.stat"] = totals
        except Exception:
            pass
        totals, processes, count = {}, [], 0
        try:
            for raw in _read(cgroup / "cgroup.procs", 4096).splitlines()[:64]:
                pid = int(raw)
                if pid == os.getpid():
                    continue
                try:
                    values = _proc(pid, proc_root)
                except Exception:
                    continue
                count += 1
                for key, value in values.items():
                    totals[key] = totals.get(key, 0) + value
                if len(processes) < 16:
                    processes.append({"pid": pid, **values})
            group["other_process_sampled_count"] = count
            group["other_process_totals"] = totals
            group["other_process_samples"] = processes
        except Exception:
            pass
        for kind in ("memory", "io", "cpu"):
            try:
                group[kind + ".pressure"] = _pressure(cgroup / (kind + ".pressure"))
            except Exception:
                pass
        metrics["cgroup"] = group
    for label, path in (("project_temp_fs", temp_dir), ("system_tmp_fs", Path("/tmp"))):
        try:
            fs = os.statvfs(path)
            metrics[label] = {"free_bytes": fs.f_bavail * fs.f_frsize,
                              "used_bytes": (fs.f_blocks - fs.f_bfree) * fs.f_frsize,
                              "free_inodes": fs.f_favail}
        except Exception:
            pass
    return metrics


class WatchDiagnostics:
    def __init__(self, temp_dir, *, interval=15, stream=None):
        self.temp_dir = Path(temp_dir)
        self.interval = max(1, interval)
        self.stream = stream if stream is not None else sys.stderr
        self.run_id = uuid.uuid4().hex
        self.started = time.monotonic()
        self.queue = Queue(maxsize=128)
        self.stop = Event()
        self.lock = Lock()
        self.active = {}
        self.job_id = None
        self.dropped = 0
        self.thread = Thread(target=self._loop, name="watch-evidence", daemon=True)

    def emit(self, event, **fields):
        if event not in {"watch_start", "watch_end", "phase_start", "phase_end"}:
            return
        safe = {key: value for key, value in fields.items() if key in FIELDS
                and type(value) in (int, float) and 0 <= value < 2**63 and math.isfinite(value)}
        for key in ("phase_id", "job_id"):
            value = fields.get(key)
            if isinstance(value, str) and len(value) == 12 and all(c in "0123456789abcdef" for c in value):
                safe[key] = value
        if isinstance(fields.get("phase"), str) and fields["phase"] in PHASES:
            safe["phase"] = fields["phase"]
        if isinstance(fields.get("status"), str) and fields["status"] in {"ok", "failed", "cancelled"}:
            safe["status"] = fields["status"]
        if isinstance(fields.get("error_type"), str) and fields["error_type"] in ERRORS:
            safe["error_type"] = fields["error_type"]
        record = {"diagnostic": "video_watcher", "event": event, "run_id": self.run_id,
                  "pid": os.getpid(), "utc": datetime.now(timezone.utc).isoformat(),
                  "elapsed_seconds": round(time.monotonic() - self.started, 3), **safe}
        try:
            self.queue.put_nowait(record)
        except Full:
            self.dropped += 1

    def _write(self, record):
        try:
            self.stream.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")
            self.stream.flush()
        except Exception:
            pass

    def _loop(self):
        next_sample = time.monotonic()
        while not self.stop.is_set() or not self.queue.empty():
            try:
                if not self.stop.is_set() and time.monotonic() >= next_sample:
                    with self.lock:
                        active = list(self.active.values())[:32]
                    self._write({"diagnostic": "video_watcher", "event": "heartbeat",
                                 "run_id": self.run_id, "pid": os.getpid(),
                                 "utc": datetime.now(timezone.utc).isoformat(),
                                 "elapsed_seconds": round(time.monotonic() - self.started, 3),
                                 "active_phases": active, "dropped_events": self.dropped,
                                 "metrics": collect_metrics(self.temp_dir)})
                    next_sample = time.monotonic() + self.interval
                wait = max(0.01, next_sample - time.monotonic()) if not self.stop.is_set() else 0
                self._write(self.queue.get(timeout=wait))
            except Empty:
                pass
            except Exception:
                next_sample = time.monotonic() + self.interval


@contextmanager
def watch_diagnostics(temp_dir):
    global _current
    previous, collector = _current, None
    try:
        collector = WatchDiagnostics(temp_dir)
        collector.thread.start()
        _current = collector
        collector.emit("watch_start")
    except Exception:
        if collector is not None:
            collector.stop.set()
        _current = previous
        collector = None
    try:
        yield
    finally:
        _current = previous
        if collector is not None:
            try:
                collector.emit("watch_end")
                collector.stop.set()
                collector.thread.join(timeout=0.5)
            except Exception:
                pass


@contextmanager
def phase(name, **fields):
    collector, token, previous_job = _current, None, None
    info, started = None, time.monotonic()
    try:
        if collector is not None and name in PHASES:
            safe = {key: value for key, value in fields.items() if key in FIELDS
                    and type(value) in (int, float) and 0 <= value < 2**63 and math.isfinite(value)}
            token = uuid.uuid4().hex[:12]
            with collector.lock:
                previous_job = collector.job_id
                if name == "video":
                    collector.job_id = uuid.uuid4().hex[:12]
                info = {"phase": name, "phase_id": token, **safe}
                if collector.job_id is not None:
                    info["job_id"] = collector.job_id
                if len(collector.active) < 32:
                    collector.active[token] = info
            collector.emit("phase_start", **info)
    except Exception:
        pass
    error = None
    try:
        yield
    except BaseException as exc:
        error = type(exc).__name__
        raise
    finally:
        if token is not None:
            try:
                with collector.lock:
                    collector.active.pop(token, None)
                    if name == "video":
                        collector.job_id = previous_job
                outcome = "cancelled" if error in {"CancelledError", "KeyboardInterrupt", "SystemExit"} else "failed" if error else "ok"
                extra = {"error_type": error if error in ERRORS else "Exception"} if error else {}
                if info is not None:
                    # Phase metadata may include input duration; end duration is elapsed time.
                    end_info = {key: value for key, value in info.items() if key != "duration_seconds"}
                    collector.emit("phase_end", **end_info, status=outcome,
                                   duration_seconds=round(time.monotonic() - started, 3), **extra)
            except Exception:
                pass


def diagnosed(name):
    def decorate(function):
        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def asynchronous(*args, **kwargs):
                with phase(name):
                    return await function(*args, **kwargs)
            return asynchronous
        @wraps(function)
        def synchronous(*args, **kwargs):
            with phase(name):
                return function(*args, **kwargs)
        return synchronous
    return decorate

"""Sweep caching and a minimal background-job registry.

A full NCC sweep is ~3 minutes, far past any sane request timeout, so the panel
kicks one off as a job and polls. Results are cached on disk keyed by video +
the parameters that affect them, so re-opening a video is instant and changing a
threshold does not silently serve a stale trace.
"""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

CACHE_DIR = Path("/app/data/sam-training/sweeps")


def cache_key(video_path, stride: int) -> str:
    raw = f"{Path(video_path).resolve()}|{stride}".encode()
    return hashlib.sha1(raw).hexdigest()[:16]


def cache_file(video_path, stride: int, root: Path | None = None) -> Path:
    root = root or CACHE_DIR
    return root / f"{Path(video_path).stem[:60]}.{cache_key(video_path, stride)}.npz"


def load_sweep(video_path, stride: int, root: Path | None = None):
    path = cache_file(video_path, stride, root)
    if not path.is_file():
        return None
    try:
        d = np.load(path)
        return d["frames"], d["scores"], int(d["n_frames"])
    except (OSError, KeyError, ValueError):
        return None                 # a corrupt cache is a miss, never a crash


def save_sweep(video_path, stride: int, frames, scores, n_frames,
               root: Path | None = None) -> None:
    path = cache_file(video_path, stride, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, frames=frames, scores=scores, n_frames=n_frames)
    tmp.replace(path)               # atomic: a killed sweep leaves no half-file


@dataclass
class Job:
    id: str
    kind: str
    state: str = "running"          # running | done | error
    progress: float = 0.0
    message: str = ""
    result: object = None
    started_at: float = field(default_factory=time.time)


class JobRegistry:
    """In-process, deliberately. This is a debug panel — a job dying with the
    container is fine, and the sweep it was computing is cached anyway."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, fn) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job

        def run():
            try:
                job.result = fn(job)
                job.state = "done"
                job.progress = 1.0
            except Exception as exc:                # noqa: BLE001 - surfaced to UI
                job.state = "error"
                job.message = f"{type(exc).__name__}: {exc}"[:400]

        threading.Thread(target=run, daemon=True, name=f"job-{kind}").start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def prune(self, older_than: float = 3600.0) -> None:
        cutoff = time.time() - older_than
        with self._lock:
            for jid in [j for j, job in self._jobs.items()
                        if job.state != "running" and job.started_at < cutoff]:
                del self._jobs[jid]


registry = JobRegistry()

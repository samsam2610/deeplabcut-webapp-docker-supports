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


def cache_key(video_path, stride: int, sig: str = "") -> str:
    """Identity of a cached sweep.

    ``sig`` MUST cover everything that changes the result. It was omitted, so
    the key was (path, stride) alone: after moving the pellet box, a sweep
    returned the previous result instantly and the placement had no effect —
    silently, and indistinguishable from success. A stale cache that looks fresh
    is worse than no cache.
    """
    raw = f"{Path(video_path).resolve()}|{stride}|{sig}".encode()
    return hashlib.sha1(raw).hexdigest()[:16]


def model_signature(model, video_stem: str = "", marks=None) -> str:
    """Everything about the detector that changes a sweep, as a short string.

    Per-video box overrides are included via ``video_stem``, so moving one
    video's box does not invalidate every other video's cache.

    ``marks`` are the onset sidecar's rows, which are the source of truth for
    the box. They win over ``PelletModel.videos``, whose coordinates are a
    leftover from before placement moved into the sidecar: reading those would
    key the cache on a box the detector is not using.
    """
    if model is None:
        return ""
    parts = [f"thr={getattr(model, 'threshold', '')}",
             f"d3={getattr(model, 'max_3d_dist', '')}",
             f"ref={getattr(model, 'ref_3d', None)}"]
    for name in sorted(getattr(model, "cameras", {})):
        cam = model.cameras[name]
        cx, cy = cam.cx, cam.cy
        box = getattr(model, "box_for", None)
        if box and video_stem:
            found = box(video_stem, name)
            if found:
                cx, cy = found
        for mk in (marks or []):            # sidecar wins
            if mk.get("kind") == "box" and mk.get("cam") == name:
                cx, cy = float(mk["x"]), float(mk["y"])
                break
        parts.append(f"{name}:{cx:.2f},{cy:.2f},{cam.half},{cam.margin},"
                     f"{len(getattr(cam, 'seed_b64', '') or '')},"
                     f"{len(getattr(cam, 'exemplars', []) or [])}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def cache_file(video_path, stride: int, root: Path | None = None,
               sig: str = "") -> Path:
    root = root or CACHE_DIR
    return root / f"{Path(video_path).stem[:60]}.{cache_key(video_path, stride, sig)}.npz"


def load_sweep(video_path, stride: int, root: Path | None = None, sig: str = ""):
    path = cache_file(video_path, stride, root, sig)
    if not path.is_file():
        return None
    try:
        d = np.load(path)
        return d["frames"], d["scores"], int(d["n_frames"])
    except (OSError, KeyError, ValueError):
        return None                 # a corrupt cache is a miss, never a crash


def save_sweep(video_path, stride: int, frames, scores, n_frames,
               root: Path | None = None, sig: str = "") -> None:
    path = cache_file(video_path, stride, root, sig)
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

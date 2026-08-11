"""The exemplar bank: DINOv3 embeddings of human-tagged onset frames.

This is the only thing in the pipeline carrying task knowledge. DINOv3 itself is
frozen and has never seen this rig, so **holding a session's exemplars out is
sufficient to hold that session out** — there is no equivalent of the training
contamination that complicates evaluating a DLC-based approach here.

Exemplars are label-matched at query time: a trial closing on `f` is scored only
against `start-failure` onsets. That is not leakage — the outcome is a human
input, known before the search starts.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config, notes, tracked

# What the embedder sees. Wide enough to hold the aperture and the pedestal, so
# the embedding captures paw-relative-to-pellet rather than just the paw.
CROP = (150, 420, 320, 520)             # y0, y1, x0, x1

CACHE_DIR = Path("/app/data/sam-training/exemplars")


@dataclass
class Bank:
    embeddings: np.ndarray              # (n, d) L2-normalised
    labels: np.ndarray                  # "s" | "f"
    videos: np.ndarray                  # source video stem per exemplar
    frames: np.ndarray                  # 1-based onset frame per exemplar

    def __len__(self) -> int:
        return len(self.embeddings)

    def for_query(self, outcome: str, exclude_video: str | None = None):
        """Label-matched exemplars, optionally excluding one session.

        ``exclude_video`` is what makes leave-one-session-out honest, and what
        the panel uses so a session is never scored against its own tags.
        """
        keep = self.labels == outcome
        if exclude_video:
            keep &= self.videos != exclude_video
        return self.embeddings[keep]


def crop_rgb(frame):
    import cv2
    y0, y1, x0, x1 = CROP
    return cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)


def cache_file(project_path, per_session: int, root: Path | None = None) -> Path:
    root = root or CACHE_DIR
    key = hashlib.sha1(f"{project_path}|{per_session}|{CROP}".encode()).hexdigest()[:16]
    return root / f"bank.{key}.npz"


def load(project_path, per_session: int = 40, root: Path | None = None):
    path = cache_file(project_path, per_session, root)
    if not path.is_file():
        return None
    try:
        d = np.load(path, allow_pickle=False)
        return Bank(d["embeddings"], d["labels"].astype(str),
                    d["videos"].astype(str), d["frames"])
    except (OSError, KeyError, ValueError):
        return None                     # corrupt cache is a miss, not a crash


def save(bank: Bank, project_path, per_session: int, root: Path | None = None):
    path = cache_file(project_path, per_session, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, embeddings=bank.embeddings, labels=bank.labels,
                        videos=bank.videos, frames=bank.frames)
    tmp.replace(path)


def build(project_path, per_session: int = 40, progress=None) -> Bank:
    """Embed up to ``per_session`` human onset frames from every Tag=Done video.

    Only `Tag = Done` sessions contribute: a session still being tagged has
    onsets that may move, and a moving target is a bad exemplar.
    """
    from . import ncc, models

    videos = [config.to_local(p) for p in sorted(tracked.tag_done_videos(project_path))]
    imgs, labels, vids, frames = [], [], [], []
    for vi, video in enumerate(videos):
        if not Path(video).is_file():
            continue
        rows = notes.read_notes(video)
        trials = [t for t in notes.pair_trials(rows) if not t.is_orphan][:per_session]
        got = ncc.read_frames(video, [t.onset_frame - 1 for t in trials])
        for t in trials:
            key = t.onset_frame - 1
            if key not in got:
                continue
            imgs.append(crop_rgb(got[key]))
            labels.append(t.outcome)
            vids.append(Path(video).stem)
            frames.append(t.onset_frame)
        if progress:
            progress(vi + 1, len(videos))

    emb = models.embed(imgs)
    return Bank(emb, np.array(labels), np.array(vids), np.array(frames, dtype=np.int64))


def get(project_path, per_session: int = 40, root: Path | None = None,
        progress=None) -> Bank:
    bank = load(project_path, per_session, root)
    if bank is None:
        bank = build(project_path, per_session, progress=progress)
        save(bank, project_path, per_session, root)
    return bank

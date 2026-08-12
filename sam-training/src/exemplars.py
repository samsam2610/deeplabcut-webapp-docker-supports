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

# What the embedder sees, as offsets from that camera's PELLET CENTRE:
# (dy_top, dy_bottom, dx_left, dx_right). Wide enough to hold the aperture and
# the pedestal, so the embedding captures paw-relative-to-pellet, not just paw.
#
# Anchored rather than absolute because the two cameras see the pellet in
# different places — cam1's is 177 px right and 62 px down — so one fixed
# rectangle frames the wrong part of cam1 entirely. Anchoring also means the
# crop follows a re-placed box instead of needing a second constant to maintain.
CROP_OFFSETS = (-238, 32, -96, 104)

# The cam0 rectangle these offsets reproduce, kept as the default for callers
# with no camera model. Tuned on banh-mi-1 2026-07-02.
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


def crop_for(cam, width: int = 800, height: int = 600):
    """This camera's crop box, anchored on its pellet centre.

    Shifted, never shrunk, when it would leave the frame: a smaller crop would
    embed at a different content scale, and the two cameras' similarities would
    stop being comparable. Silently letting a negative start through is worse
    still — numpy wraps it and the crop comes from the far side of the image.
    """
    dy0, dy1, dx0, dx1 = CROP_OFFSETS
    h, w = dy1 - dy0, dx1 - dx0
    y0 = int(round(cam.cy + dy0))
    x0 = int(round(cam.cx + dx0))
    y0 = max(0, min(y0, height - h))
    x0 = max(0, min(x0, width - w))
    return (y0, y0 + h, x0, x0 + w)


def crop_rgb(frame, box=None):
    import cv2
    y0, y1, x0, x1 = box or CROP
    return cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)


def cache_file(project_path, per_session: int, root: Path | None = None,
               cam: str = "cam0") -> Path:
    root = root or CACHE_DIR
    key = hashlib.sha1(
        f"{project_path}|{per_session}|{CROP_OFFSETS}|{cam}".encode()).hexdigest()[:16]
    # The camera is in the NAME as well as the key: these files get inspected by
    # hand when a bank looks wrong, and a bare hash says nothing.
    return root / f"bank.{cam}.{key}.npz"


def load(project_path, per_session: int = 40, root: Path | None = None,
         cam: str = "cam0"):
    path = cache_file(project_path, per_session, root, cam)
    if not path.is_file():
        return None
    try:
        d = np.load(path, allow_pickle=False)
        return Bank(d["embeddings"], d["labels"].astype(str),
                    d["videos"].astype(str), d["frames"])
    except (OSError, KeyError, ValueError):
        return None                     # corrupt cache is a miss, not a crash


def save(bank: Bank, project_path, per_session: int, root: Path | None = None,
         cam: str = "cam0"):
    path = cache_file(project_path, per_session, root, cam)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, embeddings=bank.embeddings, labels=bank.labels,
                        videos=bank.videos, frames=bank.frames)
    tmp.replace(path)


def build(project_path, per_session: int = 40, progress=None,
          cam: str = "cam0") -> Bank:
    """Embed up to ``per_session`` human onset frames from every Tag=Done video.

    Only `Tag = Done` sessions contribute: a session still being tagged has
    onsets that may move, and a moving target is a bad exemplar.

    For ``cam1`` the frames are read from the SIBLING video at the same frame
    numbers. The cameras are hardware-synced and the notes live on cam0 only, so
    a cam1 bank costs no new human labelling — the same human onsets, seen from
    the other side.
    """
    from . import ncc, models, pellet_model as pm

    model = pm.load(project_path)
    camera = (model.cameras.get(cam) if model else None)
    if camera is None and cam != "cam0":
        # crop_rgb falls back to the cam0 rectangle when given no box. For cam0
        # that IS the tuned crop; for any other camera it would embed cam0's
        # region of a different view — every exemplar background, the bank
        # looking perfectly healthy, and that camera's similarity pure noise.
        raise ValueError(f"no {cam} in the pellet model, so its crop is unknown")
    box = crop_for(camera) if camera else None

    videos = [config.to_local(p) for p in sorted(tracked.tag_done_videos(project_path))]
    imgs, labels, vids, frames = [], [], [], []
    for vi, video in enumerate(videos):
        if not Path(video).is_file():
            continue
        rows = notes.read_notes(video)
        trials = [t for t in notes.pair_trials(rows) if not t.is_orphan][:per_session]
        source = video
        if cam != "cam0":
            sibling = pm.sibling_video(video)
            if sibling is None:
                continue            # no partner file: this session sits out
            source = str(sibling)
        got = ncc.read_frames(source, [t.onset_frame - 1 for t in trials])
        for t in trials:
            key = t.onset_frame - 1
            if key not in got:
                continue
            imgs.append(crop_rgb(got[key], box))
            labels.append(t.outcome)
            # keyed on the cam0 stem in both banks, so exclude_video still
            # holds a session out of ITS OWN scoring whichever camera is asked
            vids.append(Path(video).stem)
            frames.append(t.onset_frame)
        if progress:
            progress(vi + 1, len(videos))

    emb = models.embed(imgs)
    return Bank(emb, np.array(labels), np.array(vids), np.array(frames, dtype=np.int64))


def get(project_path, per_session: int = 40, root: Path | None = None,
        progress=None, cam: str = "cam0") -> Bank:
    bank = load(project_path, per_session, root, cam)
    if bank is None:
        bank = build(project_path, per_session, progress=progress, cam=cam)
        save(bank, project_path, per_session, root, cam)
    return bank

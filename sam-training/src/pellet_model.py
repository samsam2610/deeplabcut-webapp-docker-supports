"""Project-level pellet model: per-camera template, box, and a 3D reference point.

Replaces the single hand-cut template that shipped in `assets/`. That one was
86 % dark post and 11 % pellet with the pellet clipped by the frame edge, so
inside a 140x160 band it could slide 80 px and lock onto a white paw — scoring
0.87 on frames with no pellet at all. See the `reference-pellet-detection`
memory for the full post-mortem.

Four signals, in increasing order of strength:

1. **Template cut from DLC pellet positions at `start-*` tags.** Centred on where
   the pellet actually is, so the pellet dominates the correlation (40 % bright)
   instead of contributing a tenth of it.
2. **A box the user owns.** The pedestal drifts — hand-labelled y went 354 in May
   to 399 in July — so the box is editable per project and per camera rather than
   a constant somebody has to notice is wrong.
3. **Both cameras.** The rig is hardware-synced, so a paw faking the pellet in one
   view will not coincide in the other.
4. **3D agreement.** Triangulated through the anipose calibration, the armed
   pellet sits at a fixed point: over 138 tags, sd (0.29, 0.22, 0.31) with a
   max deviation of 1.03. Nearly a hard gate.

The model is PER PROJECT, not per session: one template pooled over every tagged
onset generalises (each patch matches the pooled mean at median NCC 0.90 across
sessions and animals), and a user correction should improve every video rather
than one.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, asdict, field, replace
from pathlib import Path

import numpy as np

MODEL_FILENAME = "sam_training_pellet.json"

# Half-size of the template patch cut around a pellet position. 22 -> 44x44,
# which comfortably contains the pellet without dragging in the post below it.
PATCH_HALF = 22

# How far around the expected position to search. Generous enough for the
# observed drift (project envelope x 404-423, y 374-405, and May sessions sit
# ~20 px higher still) but nowhere near the 80 px of slide that broke the old
# detector.
DEFAULT_MARGIN = 40

# A match must clear this to count as "pellet here" in one camera.
DEFAULT_THRESHOLD = 0.55

# Max distance from the reference 3D point for a two-camera match to be accepted.
#
# Tuned on banh-mi-1 Jul 6 (143 tagged onsets) against BOTH sides, because this
# threshold trades recall for precision and the curve has a sharp knee:
#
#     max3d   armed   recall   precision
#       1.0    6.1%    60.1%     96.8%
#       1.2    8.0%    75.0%     96.1%
#       1.5   14.3%    92.3%     95.3%
#     > 2.0   16.0%    97.9%     94.2%   <- knee
#       3.0   16.8%    97.9%     92.6%
#       inf   22.4%    99.3%     78.2%   <- no 3D gate at all
#
# 3.0 bought no extra recall and cost precision; 1.2 (which the distance
# histogram of an UNTAGGED video suggested on its own) would have cost 23 points
# of recall. Never tune this on a video with no tags to measure the cost.
#
# The gate as a whole is worth +16 points of precision for -1.4 of recall.
DEFAULT_MAX_3D_DIST = 2.0


@dataclass
class Exemplar:
    """One pellet patch contributed by a user click."""
    b64: str
    video: str = ""
    frame: int = 0
    x: float = 0.0
    y: float = 0.0

    def patch(self):
        import cv2
        buf = np.frombuffer(base64.b64decode(self.b64), dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)


@dataclass
class CameraModel:
    """Template POOL and search geometry for one camera.

    The template is the mean of a pool, not a fixed image:

      * ``seed_b64`` / ``seed_n`` — the mean of the DLC-derived pellet positions
        at `start-*` tags. This is the starting point and never changes.
      * ``exemplars`` — patches the user added by clicking stationary pellets on
        a new video. Individually removable, so a bad click is undone rather
        than baked in.

    ``template()`` re-averages the two. Growing the pool is the iteration
    mechanism: if a new video misses a lot, add clicks until it does not.
    Earlier versions either REPLACED the seed with the clicks (three clicks wiped
    a 261-sample template) or ignored the clicks for appearance entirely; both
    were wrong.
    """
    cx: float                       # expected pellet centre, full-frame pixels
    cy: float
    half: int = PATCH_HALF          # template is (2*half) square
    margin: int = DEFAULT_MARGIN    # search box extends this far around (cx, cy)
    seed_b64: str = ""              # mean of the DLC-derived pool, PNG+base64
    seed_n: int = 0
    seed_weight: float = 1.0        # <1 lets clicks outvote a large seed pool
    exemplars: list = field(default_factory=list)

    @property
    def n_samples(self) -> int:
        return int(self.seed_n) + len(self.exemplars)

    @property
    def template_box(self) -> tuple[int, int, int, int]:
        """(y0, y1, x0, x1) of the template patch itself — what the UI draws."""
        return (int(self.cy - self.half), int(self.cy + self.half),
                int(self.cx - self.half), int(self.cx + self.half))

    @property
    def search_box(self) -> tuple[int, int, int, int]:
        h = self.half + self.margin
        return (max(0, int(self.cy - h)), int(self.cy + h),
                max(0, int(self.cx - h)), int(self.cx + h))

    def seed(self):
        if not self.seed_b64:
            return None
        import cv2
        buf = np.frombuffer(base64.b64decode(self.seed_b64), dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)

    def set_seed(self, patch, n: int) -> None:
        self.seed_b64 = _encode(patch)
        self.seed_n = int(n)

    def add_exemplar(self, patch, video="", frame=0, x=0.0, y=0.0) -> None:
        self.exemplars.append(Exemplar(b64=_encode(patch), video=str(video),
                                       frame=int(frame), x=float(x), y=float(y)))

    def template(self):
        """Weighted mean of the seed and every user exemplar."""
        parts, weights = [], []
        seed = self.seed()
        if seed is not None and self.seed_n:
            parts.append(seed.astype(np.float32))
            weights.append(float(self.seed_n) * float(self.seed_weight))
        for ex in self.exemplars:
            patch = ex.patch()
            if patch is None:
                continue
            if parts and patch.shape != parts[0].shape:
                continue                        # size changed; skip rather than crash
            parts.append(patch.astype(np.float32))
            weights.append(1.0)
        if not parts:
            return None
        w = np.asarray(weights, dtype=np.float32)
        stack = np.stack(parts)
        return (stack * w[:, None, None]).sum(axis=0) / w.sum()

    def template_u8(self):
        t = self.template()
        return None if t is None else t.astype(np.uint8)


def _encode(patch) -> str:
    import cv2
    ok, buf = cv2.imencode(".png", np.asarray(patch).astype(np.uint8))
    if not ok:
        raise ValueError("could not encode patch")
    return base64.b64encode(buf.tobytes()).decode("ascii")


@dataclass
class VideoBox:
    """Per-video box position, confirmed by eye.

    The TEMPLATE is per project — the pellet looks the same everywhere. The
    POSITION is not: the pedestal drifts between sessions (hand-labelled y went
    354 in May to 399 in July), and on banh-mi-1 Jul 7 the project default lands
    somewhere useless. So each video pair carries its own centres and must be
    confirmed before it can be swept: a wrong box does not fail loudly, it
    quietly fills the mask with paws.
    """
    cx0: float | None = None
    cy0: float | None = None
    cx1: float | None = None
    cy1: float | None = None
    confirmed: bool = False


@dataclass
class PelletModel:
    cameras: dict[str, CameraModel] = field(default_factory=dict)
    videos: dict[str, VideoBox] = field(default_factory=dict)
    threshold: float = DEFAULT_THRESHOLD
    max_3d_dist: float = DEFAULT_MAX_3D_DIST
    ref_3d: list[float] | None = None      # reference pellet position, or None
    corrections: list[dict] = field(default_factory=list)   # user clicks

    def camera(self, cam: str) -> CameraModel | None:
        return self.cameras.get(cam)

    def box_for(self, video_stem: str, cam: str) -> tuple[float, float] | None:
        """Centre to use for this video: its own if set, else the project default."""
        base = self.cameras.get(cam)
        vb = self.videos.get(video_stem)
        if vb is not None:
            cx = vb.cx0 if cam == "cam0" else vb.cx1
            cy = vb.cy0 if cam == "cam0" else vb.cy1
            if cx is not None and cy is not None:
                return float(cx), float(cy)
        return (base.cx, base.cy) if base else None

    def is_confirmed(self, video_stem: str) -> bool:
        vb = self.videos.get(video_stem)
        return bool(vb and vb.confirmed)

    def camera_for(self, video_stem: str, cam: str) -> CameraModel | None:
        """The camera model with this video's box position applied.

        Returns a copy so the project default is never mutated by a per-video
        override — that bug would silently move every other video's box.
        """
        base = self.cameras.get(cam)
        if base is None:
            return None
        pos = self.box_for(video_stem, cam)
        if pos is None or (pos[0] == base.cx and pos[1] == base.cy):
            return base
        return replace(base, cx=pos[0], cy=pos[1])

    def to_json(self) -> str:
        return json.dumps({
            "cameras": {k: asdict(v) for k, v in self.cameras.items()},
            "threshold": self.threshold,
            "max_3d_dist": self.max_3d_dist,
            "ref_3d": self.ref_3d,
            "corrections": self.corrections,
            "videos": {k: asdict(v) for k, v in self.videos.items()},
        }, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "PelletModel":
        d = json.loads(text)
        cams = {}
        for k, v in (d.get("cameras") or {}).items():
            v = dict(v)
            v["exemplars"] = [Exemplar(**e) for e in (v.get("exemplars") or [])]
            cams[k] = CameraModel(**v)
        vids = {k: VideoBox(**v) for k, v in (d.get("videos") or {}).items()}
        return cls(cameras=cams, videos=vids,
                   threshold=float(d.get("threshold", DEFAULT_THRESHOLD)),
                   max_3d_dist=float(d.get("max_3d_dist", DEFAULT_MAX_3D_DIST)),
                   ref_3d=d.get("ref_3d"),
                   corrections=list(d.get("corrections") or []))


def model_path(project_path) -> Path:
    return Path(project_path) / MODEL_FILENAME


def load(project_path) -> PelletModel | None:
    p = model_path(project_path)
    if not p.is_file():
        return None
    try:
        return PelletModel.from_json(p.read_text())
    except (OSError, ValueError, TypeError, KeyError):
        return None                 # a stale or corrupt model is a miss, not a crash


def save(project_path, model: PelletModel) -> None:
    p = model_path(project_path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(model.to_json())
    tmp.replace(p)                  # atomic


def build_camera(patches, positions) -> CameraModel:
    """Seed a camera from DLC-derived patches. Clicks are added later."""
    if not len(patches):
        raise ValueError("no patches to build from")
    stack = np.stack(patches).astype(np.float32)
    pos = np.asarray(positions, dtype=float)
    cam = CameraModel(cx=float(np.median(pos[:, 0])), cy=float(np.median(pos[:, 1])),
                      half=stack.shape[1] // 2)
    cam.set_seed(stack.mean(axis=0).astype(np.uint8), len(patches))
    return cam


def match(gray, cam: CameraModel):
    """Best NCC inside the camera's search box.

    Returns (score, (x, y)) with the position at the CENTRE of the matched patch
    in full-frame coordinates — callers want where the pellet is, not where the
    patch's corner landed.
    """
    import cv2
    template = cam.template_u8()
    if template is None:
        return -1.0, (0.0, 0.0)
    y0, y1, x0, x1 = cam.search_box
    region = gray[y0:y1, x0:x1]
    if (region.size == 0 or region.shape[0] < template.shape[0]
            or region.shape[1] < template.shape[1]):
        return -1.0, (0.0, 0.0)
    res = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, best, _, loc = cv2.minMaxLoc(res)
    return (float(best),
            (float(loc[0] + x0 + template.shape[1] / 2.0),
             float(loc[1] + y0 + template.shape[0] / 2.0)))


def agree(score0: float, score1: float, threshold: float) -> bool:
    """Both cameras must see it. The single-camera detector's failure mode was a
    paw at the pedestal position; requiring the synced partner view removes it."""
    return score0 >= threshold and score1 >= threshold


def sibling_video(video_path):
    """The other camera's file for this recording, or None.

    NOT a `_cam0_`->`_cam1_` string swap: the two files do not always share a
    timestamp. banh-mi-1 Jul 7 is cam0 `...110532...` against cam1 `...110542...`,
    ten seconds apart, so a swap silently finds nothing and the session drops out
    of a two-camera build without saying so.

    Mirrors dlc/triangulate_range.py:_resolve_cam1 — prefix and date must match,
    camera index must differ.
    """
    import re
    p = Path(video_path)
    m = re.match(r"^(.+?)_cam(\d+)_(\d{8})", p.stem)
    if not m:
        return None
    prefix, cam_idx, date = m.group(1), int(m.group(2)), m.group(3)
    exts = {".avi", ".mp4", ".mov", ".mkv"}
    for f in sorted(p.parent.iterdir()):
        if f == p or f.suffix.lower() not in exts:
            continue
        m2 = re.match(r"^(.+?)_cam(\d+)_(\d{8})", f.stem)
        if m2 and m2.group(1) == prefix and m2.group(3) == date \
                and int(m2.group(2)) != cam_idx:
            return f
    return None

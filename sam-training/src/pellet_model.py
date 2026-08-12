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
from dataclasses import dataclass, asdict, field
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
# Measured spread is max 1.03 over 138 tags, so 3.0 is ~3x the worst observed.
DEFAULT_MAX_3D_DIST = 3.0


@dataclass
class CameraModel:
    """Template and search geometry for one camera."""
    cx: float                       # expected pellet centre, full-frame pixels
    cy: float
    half: int = PATCH_HALF          # template is (2*half) square
    margin: int = DEFAULT_MARGIN    # search box extends this far around (cx, cy)
    template_b64: str = ""          # PNG bytes, base64 — keeps the model one file
    n_samples: int = 0              # how many positions it was averaged from

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

    def template(self) -> np.ndarray | None:
        if not self.template_b64:
            return None
        import cv2
        buf = np.frombuffer(base64.b64decode(self.template_b64), dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)

    def set_template(self, patch) -> None:
        import cv2
        ok, buf = cv2.imencode(".png", patch)
        if not ok:
            raise ValueError("could not encode template")
        self.template_b64 = base64.b64encode(buf.tobytes()).decode("ascii")


@dataclass
class PelletModel:
    cameras: dict[str, CameraModel] = field(default_factory=dict)
    threshold: float = DEFAULT_THRESHOLD
    max_3d_dist: float = DEFAULT_MAX_3D_DIST
    ref_3d: list[float] | None = None      # reference pellet position, or None
    corrections: list[dict] = field(default_factory=list)   # user clicks

    def camera(self, cam: str) -> CameraModel | None:
        return self.cameras.get(cam)

    def to_json(self) -> str:
        return json.dumps({
            "cameras": {k: asdict(v) for k, v in self.cameras.items()},
            "threshold": self.threshold,
            "max_3d_dist": self.max_3d_dist,
            "ref_3d": self.ref_3d,
            "corrections": self.corrections,
        }, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "PelletModel":
        d = json.loads(text)
        cams = {k: CameraModel(**v) for k, v in (d.get("cameras") or {}).items()}
        return cls(cameras=cams,
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
    """Average aligned patches into one template centred on the median position."""
    if not len(patches):
        raise ValueError("no patches to build from")
    stack = np.stack(patches).astype(np.float32)
    mean = stack.mean(axis=0)
    pos = np.asarray(positions, dtype=float)
    cam = CameraModel(cx=float(np.median(pos[:, 0])), cy=float(np.median(pos[:, 1])),
                      half=stack.shape[1] // 2, n_samples=len(patches))
    cam.set_template(mean.astype(np.uint8))
    return cam


def match(gray, cam: CameraModel):
    """Best NCC inside the camera's search box.

    Returns (score, (x, y)) with the position at the CENTRE of the matched patch
    in full-frame coordinates — callers want where the pellet is, not where the
    patch's corner landed.
    """
    import cv2
    template = cam.template()
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

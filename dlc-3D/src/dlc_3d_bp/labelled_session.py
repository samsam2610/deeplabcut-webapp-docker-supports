"""Read one DeepLabCut labelled-data session as camera pairs.

READ-ONLY. Nothing here writes to the DLC project.

Each session folder holds extracted frames named
`img_cam{C}_{seq}_{videoframe}.png`, a CollectedData_*.h5 of human annotations,
and its own calibration.toml. Only frames labelled in BOTH cameras are useful,
because the epipolar constraint needs a marker in the trusted view.
"""
from __future__ import annotations

import glob
import os
import re

import numpy as np
import pandas as pd

_IMG_RE = re.compile(r"img_cam(\d+)_(\d+)_(\d+)\.png$")


def load_labelled_session(session_dir) -> dict:
    """Return {bodyparts, calibration_path, pairs}. See the plan for the shape."""
    session_dir = str(session_dir)
    h5s = sorted(glob.glob(os.path.join(session_dir, "CollectedData_*.h5")))
    if not h5s:
        raise FileNotFoundError("no CollectedData_*.h5 in " + session_dir)
    lab = pd.read_hdf(h5s[0])
    bodyparts = list(dict.fromkeys(lab.columns.get_level_values("bodyparts")))

    # The index is a filename in older DLC and a (dir, sub, file) tuple in newer
    # ones; take the last component either way.
    names = [i if isinstance(i, str) else i[-1] for i in lab.index]
    xy = lab.xs("x", level="coords", axis=1).to_numpy(dtype=float)
    yy = lab.xs("y", level="coords", axis=1).to_numpy(dtype=float)

    by_cam = {}
    for row, name in enumerate(names):
        m = _IMG_RE.search(str(name))
        if not m:
            continue
        cam, frame = int(m.group(1)), int(m.group(3))
        by_cam.setdefault(cam, {})[frame] = (row, str(name))

    pairs = []
    for frame in sorted(set(by_cam.get(0, {})) & set(by_cam.get(1, {}))):
        r0, n0 = by_cam[0][frame]
        r1, n1 = by_cam[1][frame]
        pairs.append({
            "frame": frame,
            "cam0_image": os.path.join(session_dir, n0),
            "cam1_image": os.path.join(session_dir, n1),
            "cam0_xy": np.stack([xy[r0], yy[r0]], axis=1),
            "cam1_xy": np.stack([xy[r1], yy[r1]], axis=1),
        })

    return {
        "bodyparts": bodyparts,
        "calibration_path": os.path.join(session_dir, "calibration.toml"),
        "pairs": pairs,
    }

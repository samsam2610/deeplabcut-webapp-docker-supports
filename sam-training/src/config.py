"""Rig geometry and sweep defaults.

The camera is fixed and has not moved across animals or months, so these are
good starting values — but stage 0 re-locates the pedestal per session rather
than trusting them, because a nudged camera would silently poison every window.

All boxes are ``(y0, y1, x0, x1)`` in the 800x600 frame, half-open in the numpy
slicing sense.
"""
from __future__ import annotations

import os

# ── Rig geometry (800x600 grayscale) ─────────────────────────────────────────

# The pellet sitting on top of the black pedestal. Measured from
# banh-mi-1 2026-07-02; transfers to khoai-lang and eggtart unchanged.
PELLET_TEMPLATE_BOX = (330, 390, 355, 445)

# Where stage 0/1 look for that template. Wider than the template so a small
# camera nudge or a re-seated pedestal is still found.
PELLET_SEARCH_BOX = (290, 430, 320, 480)

# The vertical slot the paw reaches through, above the pellet. Static, so SAM
# never has to find it — see the spec.
APERTURE_BOX = (150, 320, 360, 505)

# ── Sweep ────────────────────────────────────────────────────────────────────

# Every 5th frame. At 200fps that is 25ms resolution against a ~1.9s trial —
# ample for bracketing, and 5x cheaper than dense. Measured throughput at this
# stride: ~1063 frames/s single-threaded including MJPEG decode, so a full
# 252k-frame video sweeps in ~4 minutes on CPU.
SWEEP_STRIDE = 5

# ── Video ────────────────────────────────────────────────────────────────────

FPS = 200.0

# ── Paths ────────────────────────────────────────────────────────────────────

# Where per-session rig calibration is cached, relative to the project root.
CALIBRATION_FILENAME = "sam_training_rig.json"

USER_DATA_DIR = os.environ.get("USER_DATA_DIR", "/user-data")

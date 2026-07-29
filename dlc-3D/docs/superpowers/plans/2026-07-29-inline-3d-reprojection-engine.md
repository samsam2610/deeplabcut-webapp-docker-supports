# Epipolar Reprojection Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the epipolar reprojection engine that judges a weak camera's 2D DeepLabCut markers against epipolar lines induced by the trusted camera, and writes corrected `_reprojected.h5` files for both cameras.

**Architecture:** Two new modules in `dlc-3D/src/dlc_3d_bp/`. `epipolar_core.py` is pure math — arrays in, arrays out, no file or network I/O, imports only `numpy` and `cv2`, so it runs under the host's Python 3.9 test environment. `reprojection.py` does all I/O: parses `calibration.toml`, reads the h5 pair, drives the core, writes the three output artifacts. Flask routes come in Task 8.

**Tech Stack:** Python, numpy, OpenCV (`cv2.Rodrigues`, `cv2.undistortPoints`), pandas + pytables for HDF5, `toml` for calibration parsing, pytest.

## Global Constraints

- **Python 3.9-compatible syntax.** The host pytest runner is Python 3.9.23; the container is 3.10.20. Start every new module with `from __future__ import annotations` and quote any `X | Y` annotations, matching `routes.py`.
- **`epipolar_core.py` must import only `numpy` and `cv2`.** No `toml`, no `pandas`, no `anipose_src`. The host has no `toml` and no `tomllib`, and the `dlc-3d` container has no `numba`, so `anipose_src.cameras` cannot be imported there at all — `from numba import jit` fails at module load.
- **`toml` is used only in `reprojection.py`**, which is exercised by container-side tests, never by host unit tests.
- **Never write to the original session data.** All engine functions that write take an explicit `out_dir` which defaults to the source h5's parent; verification runs pass an override.
- **Mirror the source h5 storage contract, read at run time — never hardcode it.** For this project's files that is HDF5 key `df_with_missing`, `format="table"`, `float32` columns, plain integer index, column level names `['scorer', 'bodyparts', 'coords']`.
- **`cv2.undistortPoints` must be called with `P=K`** to return pixels. Without it the function returns normalized coordinates, and mixing those with a pixel-space `F` produces a near-constant residual (~101.7 px for every bodypart) that looks like real data.
- **Tests run under the existing `dlc-3D/pytest.ini`**, whose `tests/conftest.py` cleanup hooks are mandatory. This project previously leaked 614 GB into `/tmp` from unhooked runs. Never bypass them.
- Run tests from `dlc-3D/` with `python3 -m pytest`.
- **Baseline is not clean.** Ten tests already fail on the host environment at
  the branch point (numpy 2.x `isinstance(np.int64, int)`, missing browser for
  the playwright e2e pair, ffmpeg-dependent LP transcode tests). They are
  unrelated to this work. Do NOT fix them, and do not treat them as regressions:

  - tests/e2e/test_analyzed_viewer.py::test_card_opens_and_lists_project_content[chromium]
  - tests/e2e/test_sync_frame.py::test_f2_focus_swap_then_marker_routes_to_sibling[chromium]
  - tests/test_inline_analysis_3d_ui_isolation.py::test_finalize3d_confirms_before_overwrite
  - tests/test_lp_csv_to_h5.py::test_csv_to_h5_writes_table_format
  - tests/test_lp_csv_to_h5.py::test_emit_h5_sidecars_filters_metric_csvs
  - tests/test_lp_predict_pairing.py::test_transcode_skips_when_mp4_exists
  - tests/test_lp_predict_pairing.py::test_transcode_invokes_ffmpeg_stream_copy
  - tests/test_lp_predict_pairing.py::test_transcode_falls_back_on_copy_failure
  - tests/test_lp_predict_pairing.py::test_prepare_predict_inputs_end_to_end_multiview
  - tests/test_lp_predict_pairing.py::test_prepare_predict_inputs_singleview_transcodes_only

  A suite run is clean when these ten — and only these ten — fail.


## File Structure

| File | Responsibility |
| --- | --- |
| `src/dlc_3d_bp/epipolar_core.py` | Camera model, F matrix, undistortion, epipolar distance, line clipping, DLT triangulation, threshold estimation, classification, 3D gate, verdict application. Pure. |
| `src/dlc_3d_bp/reprojection.py` | `calibration.toml` parsing, h5 pair loading, run orchestration, artifact writing. |
| `src/dlc_3d_bp/routes.py` | Modify: four new endpoints. |
| `tests/unit/test_epipolar_core.py` | Host-runnable unit tests with synthetic cameras and known ground truth. |
| `tests/test_reprojection_io.py` | Host-runnable tests for parsing and h5 round-tripping using small synthetic fixtures. |
| `tests/test_reprojection_routes.py` | Host-runnable route tests (validation, error paths) with monkeypatched engine. |
| `scripts/verify_reprojection.py` | Opt-in verification against the real 070126 session. Not a pytest test — the fixtures are 50 MB each, too large to commit. |

## Verdict codes

Used consistently across every task and written to the npz:

```python
UNJUDGED = 0
REJECT = 1
RESCUE = 2
RESCUE_REJECTED = 3
CONFIRM = 4
AMBIGUOUS = 5
```

---

### Task 1: Camera model and fundamental matrix

**Files:**
- Create: `src/dlc_3d_bp/epipolar_core.py`
- Test: `tests/unit/test_epipolar_core.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Cam` dataclass with fields `name: str`, `K: np.ndarray` (3,3), `dist: np.ndarray` (5,), `rvec: np.ndarray` (3,), `tvec: np.ndarray` (3,), `size: tuple`. Functions `extrinsics(cam) -> (R, t)` returning world→camera rotation (3,3) and translation (3,), `fundamental_matrix(ref: Cam, tgt: Cam) -> np.ndarray` (3,3).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_epipolar_core.py
import numpy as np
import pytest

from dlc_3d_bp.epipolar_core import Cam, extrinsics, fundamental_matrix


def make_cam(name="0", f=1000.0, cx=400.0, cy=300.0, rvec=(0, 0, 0),
             tvec=(0, 0, 0), dist=(0, 0, 0, 0, 0)):
    """Synthetic pinhole camera. Defaults: at the world origin, no distortion."""
    K = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1]], dtype=float)
    return Cam(
        name=name, K=K, dist=np.asarray(dist, dtype=float),
        rvec=np.asarray(rvec, dtype=float), tvec=np.asarray(tvec, dtype=float),
        size=(800, 600),
    )


def test_extrinsics_identity_for_zero_rvec():
    R, t = extrinsics(make_cam(rvec=(0, 0, 0), tvec=(1, 2, 3)))
    assert np.allclose(R, np.eye(3))
    assert np.allclose(t, [1, 2, 3])


def test_fundamental_matrix_is_rank_two():
    ref = make_cam("0")
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0))
    F = fundamental_matrix(ref, tgt)
    assert F.shape == (3, 3)
    sv = np.linalg.svd(F, compute_uv=False)
    # A valid fundamental matrix has exactly rank 2: its smallest
    # singular value must be negligible next to the largest.
    assert sv[2] / sv[0] < 1e-10


def test_fundamental_matrix_is_zero_for_identical_cameras():
    ref = make_cam("0")
    F = fundamental_matrix(ref, make_cam("1"))
    assert np.allclose(F, 0.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dlc_3d_bp.epipolar_core'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/dlc_3d_bp/epipolar_core.py
"""Pure epipolar geometry for two-camera 2D marker verification.

No file or network I/O. Imports only numpy and cv2 so this module is
importable under the host's Python 3.9 test environment. In particular it must
NOT import anipose_src, whose cameras module requires numba, which is absent
from the dlc-3d container.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Verdict codes, written to the audit npz as uint8.
UNJUDGED = 0
REJECT = 1
RESCUE = 2
RESCUE_REJECTED = 3
CONFIRM = 4
AMBIGUOUS = 5

VERDICT_NAMES = {
    UNJUDGED: "UNJUDGED",
    REJECT: "REJECT",
    RESCUE: "RESCUE",
    RESCUE_REJECTED: "RESCUE_REJECTED",
    CONFIRM: "CONFIRM",
    AMBIGUOUS: "AMBIGUOUS",
}


@dataclass
class Cam:
    """One camera's intrinsics, distortion and world->camera pose."""

    name: str
    K: np.ndarray       # (3, 3) intrinsic matrix
    dist: np.ndarray    # (5,) cv2-order distortion: k1, k2, p1, p2, k3
    rvec: np.ndarray    # (3,) Rodrigues rotation, world -> camera
    tvec: np.ndarray    # (3,) translation, world -> camera
    size: tuple         # (width, height) in pixels


def extrinsics(cam: "Cam") -> "tuple[np.ndarray, np.ndarray]":
    """Return (R, t) mapping world coordinates into this camera's frame."""
    R, _ = cv2.Rodrigues(np.asarray(cam.rvec, dtype=float).reshape(3, 1))
    return R, np.asarray(cam.tvec, dtype=float).reshape(3)


def _skew(v: np.ndarray) -> np.ndarray:
    return np.array([
        [0.0, -v[2], v[1]],
        [v[2], 0.0, -v[0]],
        [-v[1], v[0], 0.0],
    ])


def fundamental_matrix(ref: "Cam", tgt: "Cam") -> np.ndarray:
    """Fundamental matrix mapping a point in `ref` to its epipolar line in `tgt`.

    Acts on UNDISTORTED pixel coordinates. Derived from calibration rather than
    from point correspondences, so it is exact up to calibration error.
    """
    R_ref, t_ref = extrinsics(ref)
    R_tgt, t_tgt = extrinsics(tgt)
    R = R_tgt @ R_ref.T
    t = t_tgt - R @ t_ref
    E = _skew(t) @ R
    return np.linalg.inv(tgt.K).T @ E @ np.linalg.inv(ref.K)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/epipolar_core.py dlc-3D/tests/unit/test_epipolar_core.py
git commit -m "feat(reprojection): camera model and calibration-derived fundamental matrix"
```

---

### Task 2: Undistortion and epipolar distance

**Files:**
- Modify: `src/dlc_3d_bp/epipolar_core.py`
- Test: `tests/unit/test_epipolar_core.py`

**Interfaces:**
- Consumes: `Cam`, `fundamental_matrix` from Task 1.
- Produces: `undistort_to_pixels(cam, pts) -> np.ndarray` (N,2), `undistort_to_normalized(cam, pts) -> np.ndarray` (N,2), `project_point(cam, xyz) -> np.ndarray` (N,2), `epipolar_distance(F, ref_pix, tgt_pix) -> np.ndarray` (N,) in target-view pixels. All accept and return `(N, 2)` float arrays and propagate NaN.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_epipolar_core.py`:

```python
from dlc_3d_bp.epipolar_core import (
    epipolar_distance,
    project_point,
    undistort_to_normalized,
    undistort_to_pixels,
)


def test_undistort_is_identity_without_distortion():
    cam = make_cam(dist=(0, 0, 0, 0, 0))
    pts = np.array([[400.0, 300.0], [123.4, 567.8]])
    assert np.allclose(undistort_to_pixels(cam, pts), pts, atol=1e-6)


def test_undistort_to_pixels_differs_from_normalized():
    """Regression guard: cv2.undistortPoints without P=K returns normalized
    coordinates. Mixing those with a pixel-space F yields a near-constant
    residual that looks like real data. These two must not be confused."""
    cam = make_cam(dist=(-0.15, 0, 0, 0, 0))
    pts = np.array([[600.0, 500.0]])
    pix = undistort_to_pixels(cam, pts)
    nrm = undistort_to_normalized(cam, pts)
    assert np.linalg.norm(pix - nrm) > 100.0
    # Converting normalized back through K must reproduce the pixel form.
    h = np.array([nrm[0, 0], nrm[0, 1], 1.0])
    assert np.allclose((cam.K @ h)[:2], pix[0], atol=1e-6)


def test_triangulated_correspondence_has_zero_epipolar_distance():
    """A projected 3D point is an exact correspondence, so its residual is 0."""
    ref = make_cam("0")
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0))
    xyz = np.array([[10.0, -5.0, 500.0], [0.0, 0.0, 800.0]])
    p_ref = project_point(ref, xyz)
    p_tgt = project_point(tgt, xyz)
    d = epipolar_distance(fundamental_matrix(ref, tgt), p_ref, p_tgt)
    assert np.allclose(d, 0.0, atol=1e-6)


def test_perpendicular_displacement_gives_that_distance():
    """Displacing the target point by delta perpendicular to its epipolar line
    must produce a residual of exactly delta."""
    ref = make_cam("0")
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0))
    xyz = np.array([[10.0, -5.0, 500.0]])
    p_ref = project_point(ref, xyz)
    p_tgt = project_point(tgt, xyz)
    F = fundamental_matrix(ref, tgt)
    line = F @ np.array([p_ref[0, 0], p_ref[0, 1], 1.0])
    normal = line[:2] / np.linalg.norm(line[:2])
    for delta in (0.5, 7.0, 42.0):
        moved = p_tgt + delta * normal
        d = epipolar_distance(F, p_ref, moved)
        assert np.allclose(d, delta, atol=1e-6)


def test_epipolar_distance_propagates_nan():
    ref, tgt = make_cam("0"), make_cam("1", tvec=(100, 0, 0))
    F = fundamental_matrix(ref, tgt)
    d = epipolar_distance(F, np.array([[np.nan, np.nan]]), np.array([[1.0, 2.0]]))
    assert np.isnan(d[0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py -v`
Expected: FAIL — `ImportError: cannot import name 'undistort_to_pixels'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/dlc_3d_bp/epipolar_core.py`:

```python
def _as_points(pts: np.ndarray) -> np.ndarray:
    return np.asarray(pts, dtype=np.float64).reshape(-1, 2)


def undistort_to_pixels(cam: "Cam", pts: np.ndarray) -> np.ndarray:
    """Undistort (N, 2) pixel coordinates, returning ideal-pinhole PIXELS.

    P=cam.K is essential: without it cv2 returns normalized coordinates.
    """
    p = _as_points(pts)
    out = np.full_like(p, np.nan)
    ok = np.isfinite(p).all(axis=1)
    if ok.any():
        u = cv2.undistortPoints(
            p[ok].reshape(-1, 1, 2), cam.K, np.asarray(cam.dist, dtype=float),
            P=cam.K,
        )
        out[ok] = u.reshape(-1, 2)
    return out


def undistort_to_normalized(cam: "Cam", pts: np.ndarray) -> np.ndarray:
    """Undistort (N, 2) pixel coordinates to NORMALIZED image coordinates."""
    p = _as_points(pts)
    out = np.full_like(p, np.nan)
    ok = np.isfinite(p).all(axis=1)
    if ok.any():
        u = cv2.undistortPoints(
            p[ok].reshape(-1, 1, 2), cam.K, np.asarray(cam.dist, dtype=float),
        )
        out[ok] = u.reshape(-1, 2)
    return out


def project_point(cam: "Cam", xyz: np.ndarray) -> np.ndarray:
    """Project (N, 3) world points to (N, 2) distorted pixels."""
    p = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
    proj, _ = cv2.projectPoints(
        p, np.asarray(cam.rvec, dtype=float).reshape(3, 1),
        np.asarray(cam.tvec, dtype=float).reshape(3, 1),
        cam.K, np.asarray(cam.dist, dtype=float),
    )
    return proj.reshape(-1, 2)


def epipolar_distance(
    F: np.ndarray, ref_pix: np.ndarray, tgt_pix: np.ndarray
) -> np.ndarray:
    """Perpendicular distance from each target point to its epipolar line.

    Both inputs must already be UNDISTORTED pixels. Result is in target-view
    pixels. NaN in either input yields NaN.
    """
    a = _as_points(ref_pix)
    b = _as_points(tgt_pix)
    lines = np.c_[a, np.ones(len(a))] @ F.T
    num = np.abs(np.sum(lines * np.c_[b, np.ones(len(b))], axis=1))
    den = np.sqrt(lines[:, 0] ** 2 + lines[:, 1] ** 2)
    with np.errstate(invalid="ignore", divide="ignore"):
        return num / np.where(den > 1e-12, den, np.nan)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/epipolar_core.py dlc-3D/tests/unit/test_epipolar_core.py
git commit -m "feat(reprojection): undistortion and epipolar point-to-line distance"
```

---

### Task 3: Epipolar line endpoints for the UI overlay

**Files:**
- Modify: `src/dlc_3d_bp/epipolar_core.py`
- Test: `tests/unit/test_epipolar_core.py`

**Interfaces:**
- Consumes: `fundamental_matrix`, `undistort_to_pixels` from Tasks 1–2.
- Produces: `epiline_endpoints(F, ref_pix_point, width, height) -> "tuple | None"` returning `((x1, y1), (x2, y2))` clipped to the target image rectangle, or `None` when the line misses the image entirely or the input is NaN.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_epipolar_core.py`:

```python
from dlc_3d_bp.epipolar_core import epiline_endpoints


def test_epiline_endpoints_lie_on_the_line_and_inside_the_image():
    ref = make_cam("0")
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0))
    F = fundamental_matrix(ref, tgt)
    xyz = np.array([[10.0, -5.0, 500.0]])
    p_ref = project_point(ref, xyz)
    w, h = tgt.size
    seg = epiline_endpoints(F, p_ref[0], w, h)
    assert seg is not None
    line = F @ np.array([p_ref[0, 0], p_ref[0, 1], 1.0])
    nrm = np.hypot(line[0], line[1])
    assert nrm > 0
    for (x, y) in seg:
        assert -1e-6 <= x <= w + 1e-6
        assert -1e-6 <= y <= h + 1e-6
        # Normalised point-line distance: the endpoint must lie ON the line.
        assert abs(line[0] * x + line[1] * y + line[2]) / nrm < 1e-6


def test_epiline_endpoints_passes_through_the_true_correspondence():
    ref = make_cam("0")
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0))
    F = fundamental_matrix(ref, tgt)
    xyz = np.array([[10.0, -5.0, 500.0]])
    p_ref = project_point(ref, xyz)
    p_tgt = project_point(tgt, xyz)[0]
    (x1, y1), (x2, y2) = epiline_endpoints(F, p_ref[0], *tgt.size)
    # Distance from the true target point to the segment's infinite line is 0.
    dx, dy = x2 - x1, y2 - y1
    norm = np.hypot(dx, dy)
    cross = abs(dx * (y1 - p_tgt[1]) - dy * (x1 - p_tgt[0])) / norm
    assert cross < 1e-3


def test_epiline_endpoints_returns_none_for_nan_input():
    ref, tgt = make_cam("0"), make_cam("1", tvec=(100, 0, 0))
    F = fundamental_matrix(ref, tgt)
    assert epiline_endpoints(F, np.array([np.nan, np.nan]), 800, 600) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py -v`
Expected: FAIL — `ImportError: cannot import name 'epiline_endpoints'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/dlc_3d_bp/epipolar_core.py`:

```python
def epiline_endpoints(
    F: np.ndarray, ref_pix_point: np.ndarray, width: int, height: int
) -> "tuple | None":
    """Clip the epipolar line of one undistorted reference point to the target
    image rectangle.

    Returns ((x1, y1), (x2, y2)) or None when the input is not finite, the line
    is degenerate, or the line misses the image.
    """
    p = np.asarray(ref_pix_point, dtype=np.float64).reshape(2)
    if not np.isfinite(p).all():
        return None
    a, b, c = F @ np.array([p[0], p[1], 1.0])
    if not np.isfinite([a, b, c]).all() or (abs(a) < 1e-12 and abs(b) < 1e-12):
        return None

    hits = []
    if abs(b) > 1e-12:                      # intersect left and right edges
        for x in (0.0, float(width)):
            y = -(a * x + c) / b
            if -1e-9 <= y <= height + 1e-9:
                hits.append((x, y))
    if abs(a) > 1e-12:                      # intersect top and bottom edges
        for y in (0.0, float(height)):
            x = -(b * y + c) / a
            if -1e-9 <= x <= width + 1e-9:
                hits.append((x, y))
    if len(hits) < 2:
        return None

    # Keep the two most distant hits; corner cases produce duplicates.
    best, far = None, -1.0
    for i in range(len(hits)):
        for j in range(i + 1, len(hits)):
            d = np.hypot(hits[i][0] - hits[j][0], hits[i][1] - hits[j][1])
            if d > far:
                far, best = d, (hits[i], hits[j])
    if far <= 1e-9:
        return None
    return best
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/epipolar_core.py dlc-3D/tests/unit/test_epipolar_core.py
git commit -m "feat(reprojection): clip epipolar lines to the target image rectangle"
```

---

### Task 4: Batched DLT triangulation

**Files:**
- Modify: `src/dlc_3d_bp/epipolar_core.py`
- Test: `tests/unit/test_epipolar_core.py`

**Interfaces:**
- Consumes: `Cam`, `extrinsics`, `undistort_to_normalized`, `project_point`.
- Produces: `triangulate_dlt(ref: Cam, tgt: Cam, ref_pix, tgt_pix) -> np.ndarray` shape `(N, 3)`, NaN rows where either input is NaN. Batched — must handle 300,000+ points in one call.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_epipolar_core.py`:

```python
from dlc_3d_bp.epipolar_core import triangulate_dlt


def test_triangulate_recovers_known_3d_points():
    ref = make_cam("0")
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0))
    xyz = np.array([[10.0, -5.0, 500.0], [0.0, 0.0, 800.0], [-30.0, 20.0, 650.0]])
    got = triangulate_dlt(ref, tgt, project_point(ref, xyz), project_point(tgt, xyz))
    assert got.shape == (3, 3)
    assert np.allclose(got, xyz, atol=1e-4)


def test_triangulate_recovers_points_with_distortion():
    ref = make_cam("0", dist=(-0.035, 0, 0, 0, 0))
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0), dist=(-0.15, 0, 0, 0, 0))
    xyz = np.array([[10.0, -5.0, 500.0], [-30.0, 20.0, 650.0]])
    got = triangulate_dlt(ref, tgt, project_point(ref, xyz), project_point(tgt, xyz))
    assert np.allclose(got, xyz, atol=1e-3)


def test_triangulate_returns_nan_rows_for_nan_input():
    ref = make_cam("0")
    tgt = make_cam("1", tvec=(100, 0, 0))
    a = np.array([[400.0, 300.0], [np.nan, np.nan]])
    b = np.array([[410.0, 300.0], [410.0, 300.0]])
    got = triangulate_dlt(ref, tgt, a, b)
    assert np.isfinite(got[0]).all()
    assert np.isnan(got[1]).all()


def test_triangulate_handles_large_batches():
    ref = make_cam("0")
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0))
    rng = np.random.default_rng(0)
    xyz = np.c_[
        rng.uniform(-50, 50, 50_000),
        rng.uniform(-50, 50, 50_000),
        rng.uniform(400, 900, 50_000),
    ]
    got = triangulate_dlt(ref, tgt, project_point(ref, xyz), project_point(tgt, xyz))
    assert np.nanmax(np.abs(got - xyz)) < 1e-3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py -v`
Expected: FAIL — `ImportError: cannot import name 'triangulate_dlt'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/dlc_3d_bp/epipolar_core.py`:

```python
def triangulate_dlt(
    ref: "Cam", tgt: "Cam", ref_pix: np.ndarray, tgt_pix: np.ndarray
) -> np.ndarray:
    """Triangulate correspondences into world coordinates by batched DLT.

    Inputs are (N, 2) DISTORTED pixels; undistortion to normalized coordinates
    happens here. Rows with NaN in either view come back as NaN.
    """
    a = undistort_to_normalized(ref, ref_pix)
    b = undistort_to_normalized(tgt, tgt_pix)
    n = len(a)
    out = np.full((n, 3), np.nan)
    ok = np.isfinite(a).all(axis=1) & np.isfinite(b).all(axis=1)
    if not ok.any():
        return out

    R_ref, t_ref = extrinsics(ref)
    R_tgt, t_tgt = extrinsics(tgt)
    P_ref = np.hstack([R_ref, t_ref.reshape(3, 1)])
    P_tgt = np.hstack([R_tgt, t_tgt.reshape(3, 1)])

    ua, ub = a[ok], b[ok]
    m = len(ua)
    A = np.empty((m, 4, 4))
    A[:, 0] = ua[:, 0:1] * P_ref[2] - P_ref[0]
    A[:, 1] = ua[:, 1:2] * P_ref[2] - P_ref[1]
    A[:, 2] = ub[:, 0:1] * P_tgt[2] - P_tgt[0]
    A[:, 3] = ub[:, 1:2] * P_tgt[2] - P_tgt[1]

    # Smallest right singular vector per point is the homogeneous solution.
    _, _, vt = np.linalg.svd(A)
    h = vt[:, 3, :]
    with np.errstate(invalid="ignore", divide="ignore"):
        xyz = h[:, :3] / h[:, 3:4]
    xyz[~np.isfinite(xyz).all(axis=1)] = np.nan
    out[ok] = xyz
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py -v`
Expected: PASS, 15 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/epipolar_core.py dlc-3D/tests/unit/test_epipolar_core.py
git commit -m "feat(reprojection): batched DLT triangulation"
```

---

### Task 5: Per-bodypart threshold estimation

**Files:**
- Modify: `src/dlc_3d_bp/epipolar_core.py`
- Test: `tests/unit/test_epipolar_core.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (operates on residual arrays).
- Produces: `auto_threshold(d, lik_ref, lik_tgt, high_conf=0.9, k1=3.0, k2=8.0, min_n=200, pooled=None) -> dict` with keys `med`, `mad`, `t_ok`, `t_bad`, `n_highconf`, `threshold_source` (one of `"self"`, `"pooled"`, `"default"`). Module constants `DEFAULT_T_OK = 10.0`, `DEFAULT_T_BAD = 25.0`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_epipolar_core.py`:

```python
from dlc_3d_bp.epipolar_core import DEFAULT_T_BAD, DEFAULT_T_OK, auto_threshold


def _highconf(n, d_values):
    """n high-confidence pairs carrying the given residuals."""
    return np.asarray(d_values), np.ones(n), np.ones(n)


def test_auto_threshold_recovers_injected_median_and_mad():
    rng = np.random.default_rng(1)
    d = np.abs(rng.normal(0.0, 2.0, 5000)) + 3.0
    stats = auto_threshold(*_highconf(5000, d), k1=3.0, k2=8.0)
    assert stats["threshold_source"] == "self"
    assert abs(stats["med"] - np.median(d)) < 1e-9
    expected_mad = 1.4826 * np.median(np.abs(d - np.median(d)))
    assert abs(stats["mad"] - expected_mad) < 1e-9
    assert abs(stats["t_ok"] - (stats["med"] + 3.0 * stats["mad"])) < 1e-9
    assert abs(stats["t_bad"] - (stats["med"] + 8.0 * stats["mad"])) < 1e-9


def test_auto_threshold_uses_only_high_confidence_pairs():
    """Low-confidence junk must not move the estimate."""
    d = np.concatenate([np.full(1000, 1.0), np.full(1000, 900.0)])
    lik_ref = np.concatenate([np.ones(1000), np.ones(1000)])
    lik_tgt = np.concatenate([np.ones(1000), np.zeros(1000)])
    stats = auto_threshold(d, lik_ref, lik_tgt, high_conf=0.9)
    assert stats["n_highconf"] == 1000
    assert abs(stats["med"] - 1.0) < 1e-9


def test_auto_threshold_falls_back_to_pooled_when_too_few_samples():
    d, lr, lt = _highconf(50, np.full(50, 4.0))
    pooled = {"med": 2.0, "mad": 0.5}
    stats = auto_threshold(d, lr, lt, min_n=200, k1=3.0, k2=8.0, pooled=pooled)
    assert stats["threshold_source"] == "pooled"
    assert abs(stats["t_ok"] - (2.0 + 3.0 * 0.5)) < 1e-9


def test_auto_threshold_falls_back_to_defaults_without_pooled():
    d, lr, lt = _highconf(5, np.full(5, 4.0))
    stats = auto_threshold(d, lr, lt, min_n=200, pooled=None)
    assert stats["threshold_source"] == "default"
    assert stats["t_ok"] == DEFAULT_T_OK
    assert stats["t_bad"] == DEFAULT_T_BAD


def test_auto_threshold_ignores_nan_residuals():
    d = np.array([1.0, np.nan, 1.0, 1.0])
    stats = auto_threshold(d, np.ones(4), np.ones(4), min_n=1)
    assert stats["n_highconf"] == 3


def test_auto_threshold_survives_zero_mad():
    """Identical residuals give mad == 0; thresholds must stay finite and
    ordered so classification cannot degenerate."""
    d, lr, lt = _highconf(500, np.full(500, 2.0))
    stats = auto_threshold(d, lr, lt)
    assert np.isfinite(stats["t_ok"]) and np.isfinite(stats["t_bad"])
    assert stats["t_ok"] <= stats["t_bad"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py -v`
Expected: FAIL — `ImportError: cannot import name 'auto_threshold'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/dlc_3d_bp/epipolar_core.py`:

```python
DEFAULT_T_OK = 10.0
DEFAULT_T_BAD = 25.0

# Floor on mad so a degenerate (all-identical) residual distribution cannot
# collapse t_ok and t_bad onto the median and reject everything.
_MAD_FLOOR = 1e-3


def auto_threshold(
    d: np.ndarray,
    lik_ref: np.ndarray,
    lik_tgt: np.ndarray,
    high_conf: float = 0.9,
    k1: float = 3.0,
    k2: float = 8.0,
    min_n: int = 200,
    pooled: "dict | None" = None,
) -> dict:
    """Estimate (t_ok, t_bad) for one bodypart from high-confidence agreement.

    Frames where BOTH views exceed `high_conf` are presumed correct
    correspondences, so their residual spread measures this session's real
    geometric noise for this bodypart.
    """
    d = np.asarray(d, dtype=float)
    hi = (
        np.isfinite(d)
        & (np.asarray(lik_ref, dtype=float) > high_conf)
        & (np.asarray(lik_tgt, dtype=float) > high_conf)
    )
    n = int(hi.sum())

    if n >= min_n:
        sample = d[hi]
        med = float(np.median(sample))
        mad = float(1.4826 * np.median(np.abs(sample - med)))
        source = "self"
    elif pooled is not None:
        med, mad, source = float(pooled["med"]), float(pooled["mad"]), "pooled"
    else:
        return {
            "med": float("nan"), "mad": float("nan"),
            "t_ok": DEFAULT_T_OK, "t_bad": DEFAULT_T_BAD,
            "n_highconf": n, "threshold_source": "default",
        }

    mad = max(mad, _MAD_FLOOR)
    return {
        "med": med, "mad": mad,
        "t_ok": med + k1 * mad, "t_bad": med + k2 * mad,
        "n_highconf": n, "threshold_source": source,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py -v`
Expected: PASS, 21 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/epipolar_core.py dlc-3D/tests/unit/test_epipolar_core.py
git commit -m "feat(reprojection): per-bodypart MAD threshold estimation with fallbacks"
```

---

### Task 6: Classification and the 3D plausibility gate

**Files:**
- Modify: `src/dlc_3d_bp/epipolar_core.py`
- Test: `tests/unit/test_epipolar_core.py`

**Interfaces:**
- Consumes: verdict code constants from Task 1.
- Produces:
  - `classify(d, lik_ref, lik_tgt, t_ok, t_bad, gate_ref=0.6, low_tgt=0.6) -> np.ndarray` of `uint8` codes. `RESCUE` here means *rescue candidate*, pre-gate.
  - `plausibility_gate(pts3d, codes, max_gap=10, expand=0.2, speed_pct=99.0) -> np.ndarray` of `bool`, True where a candidate passes.
  - `apply_gate(codes, gate_pass) -> np.ndarray` — demotes failing `RESCUE` to `RESCUE_REJECTED`.
  - `apply_verdicts(xy, lik, codes, rescue_floor=0.9) -> (np.ndarray, np.ndarray)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_epipolar_core.py`:

```python
from dlc_3d_bp.epipolar_core import (
    AMBIGUOUS,
    CONFIRM,
    REJECT,
    RESCUE,
    RESCUE_REJECTED,
    UNJUDGED,
    apply_gate,
    apply_verdicts,
    classify,
    plausibility_gate,
)


def test_classify_covers_every_verdict():
    #                UNJUDGED  REJECT  RESCUE  CONFIRM  AMBIGUOUS  UNJUDGED(nan ref)
    d = np.array([        1.0,   99.0,    1.0,     1.0,       7.0,      np.nan])
    lik_ref = np.array([  0.1,    1.0,    1.0,     1.0,       1.0,         1.0])
    lik_tgt = np.array([  1.0,    1.0,    0.2,     0.9,       0.9,         0.9])
    got = classify(d, lik_ref, lik_tgt, t_ok=5.0, t_bad=20.0,
                   gate_ref=0.6, low_tgt=0.6)
    assert list(got) == [UNJUDGED, REJECT, RESCUE, CONFIRM, AMBIGUOUS, UNJUDGED]


def test_classify_rejects_regardless_of_target_likelihood():
    """A geometrically impossible point goes whatever DLC thought of it."""
    d = np.array([99.0, 99.0])
    got = classify(d, np.ones(2), np.array([0.01, 0.99]), t_ok=5.0, t_bad=20.0)
    assert list(got) == [REJECT, REJECT]


def test_classify_reject_outranks_rescue():
    """Precedence: REJECT is evaluated before RESCUE."""
    got = classify(np.array([99.0]), np.ones(1), np.array([0.1]),
                   t_ok=5.0, t_bad=20.0)
    assert got[0] == REJECT


def test_plausibility_gate_rejects_points_outside_the_working_volume():
    codes = np.array([CONFIRM] * 20 + [RESCUE], dtype=np.uint8)
    pts = np.zeros((21, 3))
    pts[:20] = np.linspace(0, 1, 20)[:, None] + np.array([10.0, 10.0, 500.0])
    pts[20] = [10.0, 10.0, 5000.0]           # far outside in z
    assert plausibility_gate(pts, codes)[20] == False


def test_plausibility_gate_accepts_a_point_among_the_confirms():
    codes = np.array([CONFIRM] * 20 + [RESCUE], dtype=np.uint8)
    pts = np.zeros((21, 3))
    pts[:20] = np.linspace(0, 1, 20)[:, None] + np.array([10.0, 10.0, 500.0])
    # Adjacent to the last CONFIRM (frame 19 == [11, 11, 501]), so it passes
    # both the volume test and the jump test.
    pts[20] = [11.02, 11.02, 501.02]
    assert plausibility_gate(pts, codes)[20] == True


def test_plausibility_gate_rejects_an_implausible_jump():
    """Inside the volume, but too far from the nearest recent CONFIRM.

    CONFIRM frames 0-49 travel x = 0 -> 4.9 at 0.1/frame, so v99 ~= 0.1 and the
    volume spans x in roughly [0, 5]. The candidate at frame 50 is one frame
    after the anchor at x = 4.9, giving a limit of ~0.1, but sits at x = 0.5 —
    comfortably inside the volume and 4.4 away from the anchor.
    """
    codes = np.zeros(60, dtype=np.uint8)
    codes[:50] = CONFIRM
    codes[50] = RESCUE
    pts = np.full((60, 3), np.nan)
    pts[:50] = np.c_[np.arange(50) * 0.1, np.zeros(50), np.full(50, 500.0)]
    pts[50] = [0.5, 0.0, 500.0]
    assert plausibility_gate(pts, codes, max_gap=10)[50] == False


def test_plausibility_gate_skips_jump_test_without_a_recent_confirm():
    codes = np.zeros(100, dtype=np.uint8)
    codes[:30] = CONFIRM
    codes[90] = RESCUE
    pts = np.full((100, 3), np.nan)
    pts[:30] = np.c_[np.arange(30) * 0.1, np.zeros(30), np.full(30, 500.0)]
    pts[90] = [1.5, 0.0, 500.0]              # in volume; no CONFIRM within 10
    assert plausibility_gate(pts, codes, max_gap=10)[90] == True


def test_plausibility_gate_passes_everything_without_enough_confirms():
    codes = np.array([RESCUE, RESCUE], dtype=np.uint8)
    pts = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 2.0]])
    assert list(plausibility_gate(pts, codes)) == [True, True]


def test_apply_gate_demotes_failing_rescues_only():
    codes = np.array([RESCUE, RESCUE, CONFIRM, REJECT], dtype=np.uint8)
    out = apply_gate(codes, np.array([True, False, False, False]))
    assert list(out) == [RESCUE, RESCUE_REJECTED, CONFIRM, REJECT]


def test_apply_verdicts_nans_rejects_and_raises_rescues():
    xy = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0], [9.0, 10.0]])
    lik = np.array([0.95, 0.20, 0.95, 0.30, 0.40])
    codes = np.array([REJECT, RESCUE, CONFIRM, RESCUE_REJECTED, AMBIGUOUS],
                     dtype=np.uint8)
    xy_out, lik_out = apply_verdicts(xy, lik, codes, rescue_floor=0.9)

    assert np.isnan(xy_out[0]).all() and lik_out[0] == 0.0
    assert np.allclose(xy_out[1], [3.0, 4.0]) and lik_out[1] == 0.9
    for i in (2, 3, 4):
        assert np.allclose(xy_out[i], xy[i]) and lik_out[i] == lik[i]


def test_apply_verdicts_never_lowers_a_rescued_likelihood():
    xy = np.array([[1.0, 2.0]])
    lik_out = apply_verdicts(xy, np.array([0.97]),
                             np.array([RESCUE], dtype=np.uint8),
                             rescue_floor=0.9)[1]
    assert lik_out[0] == 0.97


def test_apply_verdicts_does_not_mutate_its_inputs():
    xy = np.array([[1.0, 2.0]])
    lik = np.array([0.2])
    apply_verdicts(xy, lik, np.array([REJECT], dtype=np.uint8))
    assert np.allclose(xy, [[1.0, 2.0]]) and lik[0] == 0.2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py -v`
Expected: FAIL — `ImportError: cannot import name 'classify'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/dlc_3d_bp/epipolar_core.py`:

```python
def classify(
    d: np.ndarray,
    lik_ref: np.ndarray,
    lik_tgt: np.ndarray,
    t_ok: float,
    t_bad: float,
    gate_ref: float = 0.6,
    low_tgt: float = 0.6,
) -> np.ndarray:
    """Assign a verdict code per frame for one bodypart in the TARGET view.

    First match wins, so REJECT outranks every other outcome. RESCUE here means
    "rescue candidate"; the 3D gate confirms or demotes it in apply_gate().
    """
    d = np.asarray(d, dtype=float)
    lr = np.asarray(lik_ref, dtype=float)
    lt = np.asarray(lik_tgt, dtype=float)

    codes = np.full(d.shape, AMBIGUOUS, dtype=np.uint8)
    judged = np.isfinite(d) & (lr > gate_ref)
    codes[~judged] = UNJUDGED

    near = judged & (d <= t_ok)
    codes[judged & (d > t_bad)] = REJECT
    codes[near & (lt < low_tgt)] = RESCUE
    codes[near & (lt >= low_tgt)] = CONFIRM
    return codes


def plausibility_gate(
    pts3d: np.ndarray,
    codes: np.ndarray,
    max_gap: int = 10,
    expand: float = 0.2,
    speed_pct: float = 99.0,
    min_confirm: int = 20,
) -> np.ndarray:
    """Test rescue candidates for 3D plausibility.

    An epipolar line is a one-degree-of-freedom constraint, so a point can lie
    exactly on the correct line at a badly wrong depth. Two tests close that
    gap, both calibrated from this bodypart's own CONFIRM population:

    * working volume — the 1st-99th percentile box per axis, expanded by
      `expand`;
    * jump limit — distance from the most recent CONFIRM frame within `max_gap`
      must not exceed the 99th-percentile observed 3D speed times the gap.

    Returns a boolean array, True where a candidate passes. Entries that are not
    rescue candidates are True and meaningless. With fewer than `min_confirm`
    usable CONFIRM points there is nothing to calibrate against, so everything
    passes and the epipolar distance stands alone.
    """
    pts3d = np.asarray(pts3d, dtype=float)
    codes = np.asarray(codes)
    n = len(codes)
    out = np.ones(n, dtype=bool)

    finite = np.isfinite(pts3d).all(axis=1)
    conf = (codes == CONFIRM) & finite
    cand = (codes == RESCUE) & finite
    if not cand.any():
        return out
    out[(codes == RESCUE) & ~finite] = False
    if int(conf.sum()) < min_confirm:
        return out

    ref_pts = pts3d[conf]
    lo = np.percentile(ref_pts, 1.0, axis=0)
    hi = np.percentile(ref_pts, 99.0, axis=0)
    pad = (hi - lo) * expand
    lo, hi = lo - pad, hi + pad

    idx = np.flatnonzero(cand)
    inside = ((pts3d[idx] >= lo) & (pts3d[idx] <= hi)).all(axis=1)
    out[idx[~inside]] = False

    # v99 from frame-to-frame speed between consecutive CONFIRM frames.
    cframes = np.flatnonzero(conf)
    gaps = np.diff(cframes)
    step = np.linalg.norm(np.diff(ref_pts, axis=0), axis=1)
    usable = gaps > 0
    if not usable.any():
        return out
    v99 = float(np.percentile(step[usable] / gaps[usable], speed_pct))

    # Most recent CONFIRM at or before each candidate frame.
    prev_pos = np.searchsorted(cframes, idx, side="left") - 1
    for k, cand_frame in enumerate(idx):
        if not out[cand_frame]:
            continue
        p = prev_pos[k]
        if p < 0:
            continue
        gap = int(cand_frame - cframes[p])
        if gap <= 0 or gap > max_gap:
            continue                       # no recent anchor: volume test only
        limit = v99 * gap
        moved = float(np.linalg.norm(pts3d[cand_frame] - ref_pts[p]))
        if moved > limit:
            out[cand_frame] = False
    return out


def apply_gate(codes: np.ndarray, gate_pass: np.ndarray) -> np.ndarray:
    """Demote rescue candidates that failed the 3D gate."""
    out = np.asarray(codes).copy()
    out[(out == RESCUE) & ~np.asarray(gate_pass, dtype=bool)] = RESCUE_REJECTED
    return out


def apply_verdicts(
    xy: np.ndarray,
    lik: np.ndarray,
    codes: np.ndarray,
    rescue_floor: float = 0.9,
) -> "tuple[np.ndarray, np.ndarray]":
    """Produce corrected (xy, likelihood) for one bodypart. Inputs unchanged.

    REJECT clears the coordinates and zeroes the likelihood so every downstream
    filter drops the point. RESCUE keeps the coordinates and lifts the
    likelihood to the floor so a likelihood filter stops discarding it. Every
    other verdict is a pass-through.
    """
    xy_out = np.asarray(xy, dtype=float).copy()
    lik_out = np.asarray(lik, dtype=float).copy()
    codes = np.asarray(codes)

    rej = codes == REJECT
    xy_out[rej] = np.nan
    lik_out[rej] = 0.0

    res = codes == RESCUE
    lik_out[res] = np.maximum(lik_out[res], rescue_floor)
    return xy_out, lik_out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py -v`
Expected: PASS, 33 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/epipolar_core.py dlc-3D/tests/unit/test_epipolar_core.py
git commit -m "feat(reprojection): verdict classification, 3D plausibility gate, verdict application"
```

---

### Task 7: Calibration parsing, run orchestration, artifact writing

**Files:**
- Create: `src/dlc_3d_bp/reprojection.py`
- Test: `tests/test_reprojection_io.py`

**Interfaces:**
- Consumes: everything from `epipolar_core`.
- Produces:
  - `load_calibration(path) -> "dict[str, Cam]"` keyed by section name (`"cam_0"`, `"cam_1"`).
  - `read_pose_h5(path) -> (df, meta)` where `meta` is a dict with keys `key`, `is_table`, `scorer`, `bodyparts`, `dtypes`.
  - `write_pose_h5(df, meta, path)` — mirrors the source storage contract.
  - `run_reprojection(ref_h5, tgt_h5, calib_path, ref_cam_key, tgt_cam_key, out_dir=None, k1=3.0, k2=8.0, gate_ref=0.6, low_tgt=0.6, high_conf=0.9, rescue_floor=0.9, overrides=None) -> dict` — writes the three artifacts and returns a summary dict with keys `outputs`, `bodyparts`, `counts`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reprojection_io.py
import numpy as np
import pandas as pd
import pytest

from dlc_3d_bp.epipolar_core import Cam, project_point
from dlc_3d_bp.reprojection import (
    load_calibration,
    read_pose_h5,
    run_reprojection,
    write_pose_h5,
)

CALIB = """
[cam_0]
name = "0"
size = [ 800, 600,]
matrix = [ [ 2382.07, 0.0, 399.5,], [ 0.0, 2382.07, 299.5,], [ 0.0, 0.0, 1.0,],]
distortions = [ -0.0355, 0.0, 0.0, 0.0, 0.0,]
rotation = [ 0.0041, 0.0031, -0.0240,]
translation = [ -0.844, 1.414, -13.840,]

[cam_1]
name = "1"
size = [ 800, 600,]
matrix = [ [ 2308.44, 0.0, 399.5,], [ 0.0, 2308.44, 299.5,], [ 0.0, 0.0, 1.0,],]
distortions = [ -0.1512, 0.0, 0.0, 0.0, 0.0,]
rotation = [ 0.0370, -0.4901, -0.0016,]
translation = [ 149.34, 23.07, 104.69,]

[metadata]
adjusted = false
error = 0.0735
"""

BODYPARTS = ["Snout", "Pellet"]
SCORER = "DLC_TestNet_shuffle1_snapshot_best-180"


def _write_calib(tmp_path):
    p = tmp_path / "calibration.toml"
    p.write_text(CALIB)
    return p


def _make_df(xy, lik):
    """xy: (n_frames, n_bodyparts, 2); lik: (n_frames, n_bodyparts)."""
    cols = pd.MultiIndex.from_product(
        [[SCORER], BODYPARTS, ["x", "y", "likelihood"]],
        names=["scorer", "bodyparts", "coords"],
    )
    data = np.empty((xy.shape[0], len(BODYPARTS) * 3), dtype=np.float32)
    for j in range(len(BODYPARTS)):
        data[:, j * 3 + 0] = xy[:, j, 0]
        data[:, j * 3 + 1] = xy[:, j, 1]
        data[:, j * 3 + 2] = lik[:, j]
    return pd.DataFrame(data, columns=cols)


def _write_h5(path, df):
    df.to_hdf(str(path), key="df_with_missing", format="table", mode="w")


def test_load_calibration_builds_cams():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        cams = load_calibration(_write_calib(Path(td)))

    assert set(cams) == {"cam_0", "cam_1"}
    assert isinstance(cams["cam_0"], Cam)
    assert cams["cam_0"].K.shape == (3, 3)
    assert cams["cam_0"].K[0, 0] == pytest.approx(2382.07)
    assert cams["cam_1"].dist.shape == (5,)
    assert cams["cam_1"].size == (800, 600)
    assert cams["cam_1"].rvec[1] == pytest.approx(-0.4901)


def test_write_pose_h5_mirrors_the_source_contract(tmp_path):
    src = tmp_path / "a.h5"
    df = _make_df(np.ones((10, 2, 2), dtype=np.float32),
                  np.full((10, 2), 0.5, dtype=np.float32))
    _write_h5(src, df)

    got, meta = read_pose_h5(src)
    assert meta["key"] == "df_with_missing"
    assert meta["is_table"] is True
    assert meta["scorer"] == SCORER
    assert meta["bodyparts"] == BODYPARTS

    dst = tmp_path / "b.h5"
    write_pose_h5(got, meta, dst)
    back, meta2 = read_pose_h5(dst)
    assert meta2["key"] == meta["key"]
    assert meta2["is_table"] == meta["is_table"]
    assert list(back.columns.names) == ["scorer", "bodyparts", "coords"]
    assert set(map(str, back.dtypes)) == {"float32"}
    pd.testing.assert_frame_equal(got, back)


def test_run_reprojection_rescues_and_rejects(tmp_path):
    """Build a synthetic pair from the fixture calibration: 300 frames of a
    moving 3D point, exactly consistent in both views. Then damage the target
    view: frames 100-109 get a confident but geometrically impossible position,
    frames 200-209 keep the correct position but a low likelihood."""
    calib = _write_calib(tmp_path)
    cams = load_calibration(calib)
    ref_cam, tgt_cam = cams["cam_0"], cams["cam_1"]

    n = 300
    t = np.linspace(0.0, 1.0, n)
    xyz = np.c_[10.0 + 2.0 * t, -5.0 + 2.0 * t, 250.0 + 5.0 * t]

    ref_xy = np.stack([project_point(ref_cam, xyz)] * 2, axis=1)
    tgt_xy = np.stack([project_point(tgt_cam, xyz)] * 2, axis=1)
    ref_lik = np.full((n, 2), 0.99, dtype=np.float32)
    tgt_lik = np.full((n, 2), 0.99, dtype=np.float32)

    tgt_xy[100:110, 0] += 250.0          # far off the epipolar line
    tgt_lik[200:210, 0] = 0.10           # correct place, low confidence

    ref_h5 = tmp_path / "s_cam0_x.h5"
    tgt_h5 = tmp_path / "s_cam1_x.h5"
    _write_h5(ref_h5, _make_df(ref_xy, ref_lik))
    _write_h5(tgt_h5, _make_df(tgt_xy, tgt_lik))

    out = run_reprojection(
        ref_h5=ref_h5, tgt_h5=tgt_h5, calib_path=calib,
        ref_cam_key="cam_0", tgt_cam_key="cam_1", out_dir=tmp_path,
    )

    assert out["counts"]["REJECT"] >= 10
    assert out["counts"]["RESCUE"] >= 10

    # Both cameras get an output file, named identically apart from _cam{N}_.
    ref_out = tmp_path / "s_cam0_x_reprojected.h5"
    tgt_out = tmp_path / "s_cam1_x_reprojected.h5"
    assert ref_out.is_file() and tgt_out.is_file()
    assert ref_out.name.replace("_cam0_", "_cam1_") == tgt_out.name
    assert (tmp_path / "s_cam1_x_reprojected.json").is_file()
    assert (tmp_path / "s_cam1_x_reprojected.npz").is_file()

    # The reference file is a faithful copy.
    src_ref, _ = read_pose_h5(ref_h5)
    got_ref, _ = read_pose_h5(ref_out)
    pd.testing.assert_frame_equal(src_ref, got_ref)

    # Damaged frames are gone; low-confidence-but-correct frames are lifted.
    got_tgt, _ = read_pose_h5(tgt_out)
    snout = got_tgt[SCORER]["Snout"]
    assert snout["x"].iloc[100:110].isna().all()
    assert (snout["likelihood"].iloc[100:110] == 0).all()
    assert snout["x"].iloc[200:210].notna().all()
    assert (snout["likelihood"].iloc[200:210] >= 0.9).all()

    # Untouched frames keep their exact original coordinates.
    src_tgt, _ = read_pose_h5(tgt_h5)
    assert np.allclose(src_tgt[SCORER]["Snout"]["x"].iloc[0:50],
                       snout["x"].iloc[0:50], equal_nan=True)


def test_per_bodypart_override_corrects_the_other_file(tmp_path):
    """Flipping a bodypart means the REFERENCE camera is the one judged for it,
    so the correction must land in the reference output, not the target's."""
    calib = _write_calib(tmp_path)
    cams = load_calibration(calib)
    ref_cam, tgt_cam = cams["cam_0"], cams["cam_1"]

    n = 300
    t = np.linspace(0.0, 1.0, n)
    xyz = np.c_[10.0 + 2.0 * t, -5.0 + 2.0 * t, 250.0 + 5.0 * t]
    ref_xy = np.stack([project_point(ref_cam, xyz)] * 2, axis=1)
    tgt_xy = np.stack([project_point(tgt_cam, xyz)] * 2, axis=1)
    ref_lik = np.full((n, 2), 0.99, dtype=np.float32)
    tgt_lik = np.full((n, 2), 0.99, dtype=np.float32)

    # Damage the REFERENCE view's Snout, and flip Snout so it gets judged.
    ref_xy[100:110, 0] += 250.0

    ref_h5 = tmp_path / "s_cam0_x.h5"
    tgt_h5 = tmp_path / "s_cam1_x.h5"
    _write_h5(ref_h5, _make_df(ref_xy, ref_lik))
    _write_h5(tgt_h5, _make_df(tgt_xy, tgt_lik))

    run_reprojection(
        ref_h5=ref_h5, tgt_h5=tgt_h5, calib_path=calib,
        ref_cam_key="cam_0", tgt_cam_key="cam_1", out_dir=tmp_path,
        overrides={"Snout": "ref"},
    )

    got_ref, _ = read_pose_h5(tmp_path / "s_cam0_x_reprojected.h5")
    got_tgt, _ = read_pose_h5(tmp_path / "s_cam1_x_reprojected.h5")

    # The flipped bodypart was corrected in the reference file...
    assert got_ref[SCORER]["Snout"]["x"].iloc[100:110].isna().all()
    # ...and the target's own Snout, which was never wrong, is untouched.
    src_tgt, _ = read_pose_h5(tgt_h5)
    assert np.allclose(
        src_tgt[SCORER]["Snout"]["x"].to_numpy(),
        got_tgt[SCORER]["Snout"]["x"].to_numpy(), equal_nan=True,
    )
    # The un-flipped bodypart still leaves the reference file alone.
    src_ref, _ = read_pose_h5(ref_h5)
    assert np.allclose(
        src_ref[SCORER]["Pellet"]["x"].to_numpy(),
        got_ref[SCORER]["Pellet"]["x"].to_numpy(), equal_nan=True,
    )


def test_run_reprojection_never_writes_beside_the_source_when_out_dir_given(tmp_path):
    calib = _write_calib(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"
    out.mkdir()

    cams = load_calibration(calib)
    n = 60
    xyz = np.c_[np.full(n, 10.0), np.full(n, -5.0), np.linspace(250, 260, n)]
    xy0 = np.stack([project_point(cams["cam_0"], xyz)] * 2, axis=1)
    xy1 = np.stack([project_point(cams["cam_1"], xyz)] * 2, axis=1)
    lik = np.full((n, 2), 0.99, dtype=np.float32)

    _write_h5(src / "s_cam0_x.h5", _make_df(xy0, lik))
    _write_h5(src / "s_cam1_x.h5", _make_df(xy1, lik))

    run_reprojection(
        ref_h5=src / "s_cam0_x.h5", tgt_h5=src / "s_cam1_x.h5",
        calib_path=calib, ref_cam_key="cam_0", tgt_cam_key="cam_1",
        out_dir=out,
    )
    assert not list(src.glob("*_reprojected.*"))
    assert (out / "s_cam1_x_reprojected.h5").is_file()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_reprojection_io.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dlc_3d_bp.reprojection'`

- [ ] **Step 3: Write minimal implementation**

Note on TOML: the container has `toml`; the host has neither `toml` nor
`tomllib` (Python 3.9). Import in that order and fall back to a minimal reader
for the flat, machine-generated `calibration.toml` aniposelib writes, so host
tests pass without adding a dependency.

```python
# src/dlc_3d_bp/reprojection.py
"""I/O and orchestration for epipolar reprojection of 2D DLC markers.

epipolar_core holds the maths and stays pure; everything that touches disk is
here.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from dlc_3d_bp import epipolar_core as ec

_CAM_RE = re.compile(r"_cam(\d+)_")


def _parse_toml(text: str) -> dict:
    """Read a flat aniposelib calibration.toml.

    Prefers a real TOML parser. The fallback exists because the host test
    environment is Python 3.9 with neither `toml` nor `tomllib`; the file is
    machine-generated with one level of sections and Python-literal values.
    """
    try:
        import toml
        return toml.loads(text)
    except ImportError:
        pass
    try:
        import tomllib
        return tomllib.loads(text)
    except ImportError:
        pass

    out: "dict" = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            out[section] = {}
            continue
        if section is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().rstrip(",")
        if value in ("true", "false"):
            parsed = value == "true"
        else:
            parsed = ast.literal_eval(value)
        out[section][key.strip()] = parsed
    return out


def load_calibration(path) -> "dict":
    """Build a Cam per camera section of an aniposelib calibration.toml."""
    data = _parse_toml(Path(path).read_text())
    cams = {}
    for key, sec in data.items():
        if not key.startswith("cam") or "matrix" not in sec:
            continue
        size = sec.get("size") or [0, 0]
        cams[key] = ec.Cam(
            name=str(sec.get("name", key)),
            K=np.asarray(sec["matrix"], dtype=float).reshape(3, 3),
            dist=np.asarray(sec.get("distortions", [0] * 5), dtype=float).reshape(-1),
            rvec=np.asarray(sec["rotation"], dtype=float).reshape(3),
            tvec=np.asarray(sec["translation"], dtype=float).reshape(3),
            size=(int(size[0]), int(size[1])),
        )
    return cams


def read_pose_h5(path) -> "tuple[pd.DataFrame, dict]":
    """Read a DLC pose h5 and capture its storage contract for round-tripping."""
    path = Path(path)
    with pd.HDFStore(str(path), "r") as store:
        keys = store.keys()
        if not keys:
            raise ValueError("no datasets in {}".format(path))
        key = keys[0]
        is_table = bool(store.get_storer(key).is_table)
    df = pd.read_hdf(str(path), key=key)
    scorer = df.columns.get_level_values(0)[0]
    bodyparts = list(dict.fromkeys(df.columns.get_level_values("bodyparts")))
    meta = {
        "key": key.lstrip("/"),
        "is_table": is_table,
        "scorer": scorer,
        "bodyparts": bodyparts,
        "dtypes": {str(c): str(t) for c, t in zip(df.columns, df.dtypes)},
    }
    return df, meta


def write_pose_h5(df: pd.DataFrame, meta: dict, path) -> None:
    """Write a pose DataFrame using the source file's key and storage format."""
    df.to_hdf(
        str(path), key=meta["key"],
        format="table" if meta["is_table"] else "fixed", mode="w",
    )


def _out_path(src, out_dir, suffix) -> Path:
    src = Path(src)
    base = src.parent if out_dir is None else Path(out_dir)
    return base / (src.stem + "_reprojected" + suffix)


def run_reprojection(
    ref_h5,
    tgt_h5,
    calib_path,
    ref_cam_key: str,
    tgt_cam_key: str,
    out_dir=None,
    k1: float = 3.0,
    k2: float = 8.0,
    gate_ref: float = 0.6,
    low_tgt: float = 0.6,
    high_conf: float = 0.9,
    rescue_floor: float = 0.9,
    overrides: "dict | None" = None,
) -> dict:
    """Judge the target view against the reference view and write artifacts.

    `overrides` maps a bodypart name to "ref" or "tgt", naming which camera to
    trust for that bodypart, overriding the session-level choice. Writes
    <stem>_reprojected.h5 for BOTH cameras: the reference copy is required so
    the _cam{N}_ sibling pairing in routes.py still discovers the pair.
    """
    cams = load_calibration(calib_path)
    cam_ref, cam_tgt = cams[ref_cam_key], cams[tgt_cam_key]
    df_ref, meta_ref = read_pose_h5(ref_h5)
    df_tgt, meta_tgt = read_pose_h5(tgt_h5)

    bodyparts = [b for b in meta_tgt["bodyparts"] if b in meta_ref["bodyparts"]]
    overrides = overrides or {}

    F = {
        "tgt": ec.fundamental_matrix(cam_ref, cam_tgt),
        "ref": ec.fundamental_matrix(cam_tgt, cam_ref),
    }

    # Both sides are copied because a per-bodypart override flips which camera
    # is judged for that bodypart, and therefore which file receives the
    # correction. With no overrides, df_ref_out stays a faithful copy.
    df_tgt_out = df_tgt.copy()
    df_ref_out = df_ref.copy()
    arrays: "dict" = {}
    stats_out: "dict" = {}
    counts = {name: 0 for name in ec.VERDICT_NAMES.values()}

    for bp in bodyparts:
        a = df_ref[meta_ref["scorer"]][bp]
        b = df_tgt[meta_tgt["scorer"]][bp]
        xy_ref = a[["x", "y"]].to_numpy(dtype=float)
        xy_tgt = b[["x", "y"]].to_numpy(dtype=float)
        lik_ref = a["likelihood"].to_numpy(dtype=float)
        lik_tgt = b["likelihood"].to_numpy(dtype=float)

        u_ref = ec.undistort_to_pixels(cam_ref, xy_ref)
        u_tgt = ec.undistort_to_pixels(cam_tgt, xy_tgt)
        # Both directions cached so a reference flip needs no h5 reread.
        d_tgt = ec.epipolar_distance(F["tgt"], u_ref, u_tgt)
        d_ref = ec.epipolar_distance(F["ref"], u_tgt, u_ref)

        flipped = overrides.get(bp) == "ref"
        d = d_ref if flipped else d_tgt
        st = ec.auto_threshold(
            d, lik_tgt if flipped else lik_ref, lik_ref if flipped else lik_tgt,
            high_conf=high_conf, k1=k1, k2=k2,
        )
        codes = ec.classify(
            d,
            lik_tgt if flipped else lik_ref,
            lik_ref if flipped else lik_tgt,
            t_ok=st["t_ok"], t_bad=st["t_bad"],
            gate_ref=gate_ref, low_tgt=low_tgt,
        )

        pts3d = ec.triangulate_dlt(cam_ref, cam_tgt, xy_ref, xy_tgt)
        codes = ec.apply_gate(codes, ec.plausibility_gate(pts3d, codes))

        # The judged side is the one whose markers are being corrected: normally
        # the target, or the reference for a bodypart the caller flipped.
        if flipped:
            frame_out, meta_j, xy_j, lik_j = df_ref_out, meta_ref, xy_ref, lik_ref
        else:
            frame_out, meta_j, xy_j, lik_j = df_tgt_out, meta_tgt, xy_tgt, lik_tgt

        xy_new, lik_new = ec.apply_verdicts(
            xy_j, lik_j, codes, rescue_floor=rescue_floor
        )
        sc = meta_j["scorer"]
        dtype = frame_out[(sc, bp, "x")].dtype
        frame_out[(sc, bp, "x")] = xy_new[:, 0].astype(dtype)
        frame_out[(sc, bp, "y")] = xy_new[:, 1].astype(dtype)
        frame_out[(sc, bp, "likelihood")] = lik_new.astype(dtype)

        for code, name in ec.VERDICT_NAMES.items():
            counts[name] += int((codes == code).sum())
        st = dict(st)
        st["flipped"] = bool(flipped)
        stats_out[bp] = st
        arrays["d_tgt__" + bp] = d_tgt.astype(np.float32)
        arrays["d_ref__" + bp] = d_ref.astype(np.float32)
        arrays["codes__" + bp] = codes.astype(np.uint8)
        arrays["xyz__" + bp] = pts3d.astype(np.float32)

    ref_out = _out_path(ref_h5, out_dir, ".h5")
    tgt_out = _out_path(tgt_h5, out_dir, ".h5")
    write_pose_h5(df_ref_out, meta_ref, ref_out)
    write_pose_h5(df_tgt_out, meta_tgt, tgt_out)

    npz_path = _out_path(tgt_h5, out_dir, ".npz")
    np.savez_compressed(str(npz_path), **arrays)

    summary = {
        "config": {
            "ref_h5": str(ref_h5), "tgt_h5": str(tgt_h5),
            "calibration": str(calib_path),
            "ref_cam": ref_cam_key, "tgt_cam": tgt_cam_key,
            "k1": k1, "k2": k2, "gate_ref": gate_ref, "low_tgt": low_tgt,
            "high_conf": high_conf, "rescue_floor": rescue_floor,
            "overrides": overrides,
        },
        "bodyparts": stats_out,
        "counts": counts,
        "outputs": {
            "ref_h5": str(ref_out), "tgt_h5": str(tgt_out),
            "npz": str(npz_path), "json": str(_out_path(tgt_h5, out_dir, ".json")),
        },
        "verdict_codes": {v: k for k, v in ec.VERDICT_NAMES.items()},
    }
    Path(summary["outputs"]["json"]).write_text(json.dumps(summary, indent=2))
    return summary
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_reprojection_io.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Run the whole suite to check nothing regressed**

Run: `cd dlc-3D && python3 -m pytest -q -p no:randomly 2>&1 | tail -20`
Expected: your new tests pass, and the ONLY failures are the 10 pre-existing
host-environment failures listed in the plan's Global Constraints. If a failure
appears that is NOT on that list, it is yours — fix it. Do not attempt to fix
the 10 known ones; they are unrelated to this work.

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/reprojection.py dlc-3D/tests/test_reprojection_io.py
git commit -m "feat(reprojection): calibration parsing, run orchestration, artifact writing"
```

---

### Task 8: Flask endpoints

**Files:**
- Modify: `src/dlc_3d_bp/routes.py`
- Test: `tests/test_reprojection_routes.py`

**Interfaces:**
- Consumes: `run_reprojection`, `load_calibration`, `read_pose_h5` from Task 7; `epiline_endpoints`, `undistort_to_pixels`, `fundamental_matrix`, `auto_threshold`, `epipolar_distance` from `epipolar_core`.
- Produces: four routes on the existing `dlc_3d` blueprint (`url_prefix="/dlc-3d"`):
  - `POST /reproject/thresholds` → `{"bodyparts": {bp: {...stats}}}`
  - `POST /reproject/run` → the `run_reprojection` summary
  - `GET /reproject/audit?tgt_h5=...` → `{"summary": {...}, "arrays": {name: [...]}}`
  - `GET /reproject/epiline?...&frame=N&bodypart=X` → `{"segment": [[x1,y1],[x2,y2]]}` or `{"segment": None}`

All path parameters go through the existing `_resolve_video_path`-style guard: resolve, then require the result to start with `_USER_DATA_ROOT + "/"`. Return 403 otherwise.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reprojection_routes.py
import json

import pytest

import dlc_3d_bp.routes as routes


@pytest.fixture()
def client():
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    app.config.update(TESTING=True)
    return app.test_client()


def test_run_rejects_paths_outside_user_data(client):
    r = client.post("/dlc-3d/reproject/run", json={
        "ref_h5": "/etc/passwd", "tgt_h5": "/etc/shadow",
        "calibration": "/etc/hosts", "ref_cam": "cam_0", "tgt_cam": "cam_1",
    })
    assert r.status_code == 403


def test_run_requires_all_arguments(client):
    r = client.post("/dlc-3d/reproject/run", json={"ref_h5": "/user-data/a.h5"})
    assert r.status_code == 400


def test_thresholds_rejects_paths_outside_user_data(client):
    r = client.post("/dlc-3d/reproject/thresholds", json={
        "ref_h5": "/etc/passwd", "tgt_h5": "/etc/shadow",
        "calibration": "/etc/hosts", "ref_cam": "cam_0", "tgt_cam": "cam_1",
    })
    assert r.status_code == 403


def test_audit_rejects_paths_outside_user_data(client):
    r = client.get("/dlc-3d/reproject/audit?tgt_h5=/etc/passwd")
    assert r.status_code == 403


def test_epiline_rejects_paths_outside_user_data(client):
    r = client.get(
        "/dlc-3d/reproject/epiline?ref_h5=/etc/passwd&calibration=/etc/hosts"
        "&ref_cam=cam_0&tgt_cam=cam_1&frame=0&bodypart=Snout"
    )
    assert r.status_code == 403


def test_run_delegates_to_the_engine(client, monkeypatch):
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return {"counts": {"RESCUE": 7}, "outputs": {}, "bodyparts": {}}

    monkeypatch.setattr(routes, "_reproject_run_impl", fake_run)
    r = client.post("/dlc-3d/reproject/run", json={
        "ref_h5": "/user-data/s_cam0_x.h5", "tgt_h5": "/user-data/s_cam1_x.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_0", "tgt_cam": "cam_1", "k1": 2.5,
    })
    assert r.status_code == 200
    assert r.get_json()["counts"]["RESCUE"] == 7
    assert seen["k1"] == 2.5
    assert seen["ref_cam_key"] == "cam_0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_reprojection_routes.py -v`
Expected: FAIL — 404 responses, and `AttributeError` for `_reproject_run_impl`

- [ ] **Step 3: Write minimal implementation**

Add to the imports at the top of `src/dlc_3d_bp/routes.py`:

```python
from dlc_3d_bp import epipolar_core as ec
from dlc_3d_bp import reprojection as rp
```

Append to `src/dlc_3d_bp/routes.py`:

```python
# ── Epipolar reprojection ─────────────────────────────────────────────────────

# Indirection so tests can monkeypatch the engine without touching disk.
_reproject_run_impl = rp.run_reprojection


def _safe_user_data_path(raw: str) -> "Path | None":
    """Resolve a caller-supplied path, requiring it to live under /user-data/."""
    if not raw:
        return None
    p = Path(raw).resolve()
    if not str(p).startswith(_USER_DATA_ROOT + "/"):
        return None
    return p


def _reproject_args(body: dict, keys):
    """Resolve required path args. Returns (paths, error_response)."""
    missing = [k for k in keys if not (body.get(k) or "").strip()]
    if missing:
        return None, (jsonify({"error": "missing: " + ", ".join(missing)}), 400)
    out = {}
    for k in keys:
        p = _safe_user_data_path(str(body[k]).strip())
        if p is None:
            return None, (jsonify({"error": "path outside /user-data: " + k}), 403)
        out[k] = p
    return out, None


@bp.route("/reproject/thresholds", methods=["POST"])
def reproject_thresholds():
    """Per-bodypart residual statistics and auto-thresholds. Writes nothing."""
    body = request.get_json(force=True) or {}
    paths, err = _reproject_args(body, ("ref_h5", "tgt_h5", "calibration"))
    if err:
        return err
    for k in ("ref_cam", "tgt_cam"):
        if not (body.get(k) or "").strip():
            return jsonify({"error": "missing: " + k}), 400

    cams = rp.load_calibration(paths["calibration"])
    cam_ref = cams[body["ref_cam"]]
    cam_tgt = cams[body["tgt_cam"]]
    df_ref, meta_ref = rp.read_pose_h5(paths["ref_h5"])
    df_tgt, meta_tgt = rp.read_pose_h5(paths["tgt_h5"])
    F = ec.fundamental_matrix(cam_ref, cam_tgt)

    out = {}
    for bp_name in meta_tgt["bodyparts"]:
        if bp_name not in meta_ref["bodyparts"]:
            continue
        a = df_ref[meta_ref["scorer"]][bp_name]
        b = df_tgt[meta_tgt["scorer"]][bp_name]
        d = ec.epipolar_distance(
            F,
            ec.undistort_to_pixels(cam_ref, a[["x", "y"]].to_numpy(dtype=float)),
            ec.undistort_to_pixels(cam_tgt, b[["x", "y"]].to_numpy(dtype=float)),
        )
        out[bp_name] = ec.auto_threshold(
            d,
            a["likelihood"].to_numpy(dtype=float),
            b["likelihood"].to_numpy(dtype=float),
            high_conf=float(body.get("high_conf", 0.9)),
            k1=float(body.get("k1", 3.0)),
            k2=float(body.get("k2", 8.0)),
        )
    return jsonify({"bodyparts": out})


@bp.route("/reproject/run", methods=["POST"])
def reproject_run():
    """Full pass: verdicts, 3D gate, write the three artifacts."""
    body = request.get_json(force=True) or {}
    paths, err = _reproject_args(body, ("ref_h5", "tgt_h5", "calibration"))
    if err:
        return err
    for k in ("ref_cam", "tgt_cam"):
        if not (body.get(k) or "").strip():
            return jsonify({"error": "missing: " + k}), 400

    out_dir = None
    if (body.get("out_dir") or "").strip():
        out_dir = _safe_user_data_path(str(body["out_dir"]).strip())
        if out_dir is None:
            return jsonify({"error": "path outside /user-data: out_dir"}), 403

    summary = _reproject_run_impl(
        ref_h5=paths["ref_h5"], tgt_h5=paths["tgt_h5"],
        calib_path=paths["calibration"],
        ref_cam_key=body["ref_cam"], tgt_cam_key=body["tgt_cam"],
        out_dir=out_dir,
        k1=float(body.get("k1", 3.0)), k2=float(body.get("k2", 8.0)),
        gate_ref=float(body.get("gate_ref", 0.6)),
        low_tgt=float(body.get("low_tgt", 0.6)),
        high_conf=float(body.get("high_conf", 0.9)),
        rescue_floor=float(body.get("rescue_floor", 0.9)),
        overrides=body.get("overrides") or {},
    )
    return jsonify(summary)


@bp.route("/reproject/audit")
def reproject_audit():
    """Serve a previous run's JSON summary and npz arrays."""
    tgt = _safe_user_data_path((request.args.get("tgt_h5") or "").strip())
    if tgt is None:
        return jsonify({"error": "tgt_h5 required and must be under /user-data"}), 403

    stem = tgt.parent / (tgt.stem + "_reprojected")
    json_path = Path(str(stem) + ".json")
    npz_path = Path(str(stem) + ".npz")
    if not json_path.is_file():
        return jsonify({"error": "no audit for {}".format(tgt.name)}), 404

    summary = json.loads(json_path.read_text())
    arrays = {}
    wanted = (request.args.get("arrays") or "").strip()
    if npz_path.is_file() and wanted:
        keep = {w for w in wanted.split(",") if w}
        with np.load(str(npz_path)) as z:
            for name in z.files:
                if name in keep:
                    arrays[name] = z[name].tolist()
    return jsonify({"summary": summary, "arrays": arrays})


@bp.route("/reproject/epiline")
def reproject_epiline():
    """Epipolar line for one reference point, clipped to the target image."""
    args = request.args
    ref_h5 = _safe_user_data_path((args.get("ref_h5") or "").strip())
    calib = _safe_user_data_path((args.get("calibration") or "").strip())
    if ref_h5 is None or calib is None:
        return jsonify({"error": "ref_h5 and calibration must be under /user-data"}), 403

    frame = args.get("frame", type=int)
    bodypart = (args.get("bodypart") or "").strip()
    ref_cam_key = (args.get("ref_cam") or "").strip()
    tgt_cam_key = (args.get("tgt_cam") or "").strip()
    if frame is None or not bodypart or not ref_cam_key or not tgt_cam_key:
        return jsonify(
            {"error": "frame, bodypart, ref_cam and tgt_cam required"}
        ), 400

    cams = rp.load_calibration(calib)
    cam_ref, cam_tgt = cams[ref_cam_key], cams[tgt_cam_key]
    df_ref, meta_ref = rp.read_pose_h5(ref_h5)
    if bodypart not in meta_ref["bodyparts"]:
        return jsonify({"error": "unknown bodypart " + bodypart}), 400
    if frame < 0 or frame >= len(df_ref):
        return jsonify({"error": "frame out of range"}), 400

    row = df_ref[meta_ref["scorer"]][bodypart].iloc[frame]
    pt = ec.undistort_to_pixels(
        cam_ref, np.array([[float(row["x"]), float(row["y"])]])
    )[0]
    seg = ec.epiline_endpoints(
        ec.fundamental_matrix(cam_ref, cam_tgt), pt, *cam_tgt.size
    )
    return jsonify({
        "segment": None if seg is None else [list(seg[0]), list(seg[1])],
        "likelihood": float(row["likelihood"]),
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_reprojection_routes.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Run the whole suite**

Run: `cd dlc-3D && python3 -m pytest -q -p no:randomly 2>&1 | tail -20`
Expected: your new tests pass, and the ONLY failures are the 10 pre-existing
host-environment failures listed in the plan's Global Constraints. If a failure
appears that is NOT on that list, it is yours — fix it. Do not attempt to fix
the 10 known ones; they are unrelated to this work.

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/routes.py dlc-3D/tests/test_reprojection_routes.py
git commit -m "feat(reprojection): thresholds, run, audit and epiline endpoints"
```

---

### Task 9: Real-data verification script

**Files:**
- Create: `scripts/verify_reprojection.py`

**Interfaces:**
- Consumes: `run_reprojection`, `load_calibration`, `read_pose_h5`.
- Produces: a standalone script, run via `docker exec`, printing a per-bodypart table and totals, and asserting invariants. No pytest — the fixture h5 files are 50 MB each and cannot be committed.

**Why a script:** the engine must be proven on real data before any UI exists, and the container cannot be restarted. This runs inside the live `dlc-3d` container, reads the original session read-only, and writes only to `/tmp` inside the container.

- [ ] **Step 1: Write the script**

```python
# scripts/verify_reprojection.py
"""Verify the reprojection engine against a real two-camera session.

Reads the source session READ-ONLY and writes artifacts to --out-dir (default
/tmp/reproject-verify inside the container). Never writes beside the source.

Run:
  docker cp dlc-3D/src/dlc_3d_bp/epipolar_core.py \\
      deeplabcut-webapp-docker-dlc-3d-1:/app/dlc_3d_bp/epipolar_core.py
  docker cp dlc-3D/src/dlc_3d_bp/reprojection.py \\
      deeplabcut-webapp-docker-dlc-3d-1:/app/dlc_3d_bp/reprojection.py
  docker cp dlc-3D/scripts/verify_reprojection.py \\
      deeplabcut-webapp-docker-dlc-3d-1:/tmp/verify_reprojection.py
  docker exec deeplabcut-webapp-docker-dlc-3d-1 python3 /tmp/verify_reprojection.py

(src/dlc_3d_bp is a whole-directory bind mount, so the two module copies are
usually already present; the docker cp lines are the fallback.)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "/app")

from dlc_3d_bp import epipolar_core as ec           # noqa: E402
from dlc_3d_bp.reprojection import (                # noqa: E402
    load_calibration,
    read_pose_h5,
    run_reprojection,
)

SESSION = (
    "/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/070126"
)
STEM = (
    "eggtart-1_cam{c}_20260701_094411_10_trig1_fps200_exposure1500_gain10"
    "DLC_HrnetW48_DREADDJan7shuffle1_snapshot_best-180.h5"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=SESSION)
    ap.add_argument("--out-dir", default="/tmp/reproject-verify")
    ap.add_argument("--ref-cam", default="cam_1",
                    help="cam_1 is the better camera on eggtart-1")
    ap.add_argument("--tgt-cam", default="cam_0")
    args = ap.parse_args()

    session = Path(args.session)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ref_idx = args.ref_cam.split("_")[-1]
    tgt_idx = args.tgt_cam.split("_")[-1]
    ref_h5 = session / STEM.format(c=ref_idx)
    tgt_h5 = session / STEM.format(c=tgt_idx)
    calib = session / "calibration.toml"
    for p in (ref_h5, tgt_h5, calib):
        if not p.is_file():
            print("MISSING: {}".format(p))
            return 2

    cams = load_calibration(calib)
    print("cameras: {}".format(sorted(cams)))
    print("reference: {}  target: {}".format(args.ref_cam, args.tgt_cam))

    summary = run_reprojection(
        ref_h5=ref_h5, tgt_h5=tgt_h5, calib_path=calib,
        ref_cam_key=args.ref_cam, tgt_cam_key=args.tgt_cam,
        out_dir=out_dir,
    )

    print("\n{:12s} {:>6s} {:>6s} {:>7s} {:>7s} {:>8s} {:>8s}".format(
        "bodypart", "t_ok", "t_bad", "n_hi", "src", "med", "mad"))
    for name, st in summary["bodyparts"].items():
        print("{:12s} {:6.2f} {:6.2f} {:7d} {:>7s} {:8.3f} {:8.3f}".format(
            name, st["t_ok"], st["t_bad"], st["n_highconf"],
            st["threshold_source"], st["med"], st["mad"]))

    print("\nverdict counts")
    total = sum(summary["counts"].values())
    for name, n in sorted(summary["counts"].items(), key=lambda kv: -kv[1]):
        pct = 100.0 * n / total if total else 0.0
        print("  {:16s} {:9d}  {:5.2f}%".format(name, n, pct))

    # ── Invariants ──
    fails = []
    if summary["counts"]["RESCUE"] <= 0:
        fails.append("no rescues — the whole point of the module")
    if summary["counts"]["REJECT"] <= 0:
        fails.append("no rejects")

    ref_out = Path(summary["outputs"]["ref_h5"])
    tgt_out = Path(summary["outputs"]["tgt_h5"])
    if ref_out.name.replace("_cam{}_".format(ref_idx),
                            "_cam{}_".format(tgt_idx)) != tgt_out.name:
        fails.append("output names do not differ only by the _cam{N}_ token, "
                     "so sibling pairing will not find them")

    src_ref, meta_src = read_pose_h5(ref_h5)
    got_ref, meta_ref_out = read_pose_h5(ref_out)
    if meta_ref_out["key"] != meta_src["key"]:
        fails.append("h5 key changed: {} -> {}".format(
            meta_src["key"], meta_ref_out["key"]))
    if meta_ref_out["is_table"] != meta_src["is_table"]:
        fails.append("h5 storage format changed")
    if not src_ref.equals(got_ref):
        fails.append("reference output is not a faithful copy")

    src_tgt, meta_tgt = read_pose_h5(tgt_h5)
    got_tgt, _ = read_pose_h5(tgt_out)
    if got_tgt.shape != src_tgt.shape:
        fails.append("target shape changed: {} -> {}".format(
            src_tgt.shape, got_tgt.shape))
    if set(map(str, got_tgt.dtypes)) != set(map(str, src_tgt.dtypes)):
        fails.append("target dtypes changed")

    # Every REJECT must be NaN with likelihood 0; every RESCUE must keep its
    # coordinates and carry likelihood >= 0.9.
    with np.load(summary["outputs"]["npz"]) as z:
        sc = meta_tgt["scorer"]
        for bp_name in summary["bodyparts"]:
            codes = z["codes__" + bp_name]
            col = got_tgt[sc][bp_name]
            rej = codes == ec.REJECT
            if rej.any():
                if not col["x"].to_numpy()[rej].__class__ or not np.isnan(
                    col["x"].to_numpy()[rej]
                ).all():
                    fails.append("{}: REJECT rows not NaN".format(bp_name))
                if not (col["likelihood"].to_numpy()[rej] == 0).all():
                    fails.append("{}: REJECT likelihood not 0".format(bp_name))
            res = codes == ec.RESCUE
            if res.any():
                if np.isnan(col["x"].to_numpy()[res]).any():
                    fails.append("{}: RESCUE rows became NaN".format(bp_name))
                if (col["likelihood"].to_numpy()[res] < 0.9).any():
                    fails.append("{}: RESCUE likelihood below floor".format(bp_name))
                src_xy = src_tgt[sc][bp_name][["x", "y"]].to_numpy()[res]
                got_xy = col[["x", "y"]].to_numpy()[res]
                if not np.allclose(src_xy, got_xy, equal_nan=True):
                    fails.append("{}: RESCUE coordinates moved".format(bp_name))
            xyz = z["xyz__" + bp_name]
            if res.any() and not np.isfinite(xyz[res]).all(axis=1).all():
                fails.append("{}: rescued point has no valid 3D".format(bp_name))

    if list(session.glob("*_reprojected.*")):
        fails.append("WROTE INTO THE SOURCE SESSION — must never happen")

    print("\noutputs in {}".format(out_dir))
    if fails:
        print("\nFAILED:")
        for f in fails:
            print("  - {}".format(f))
        return 1
    print("\nAll invariants passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it against the real session**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
docker cp dlc-3D/scripts/verify_reprojection.py \
  deeplabcut-webapp-docker-dlc-3d-1:/tmp/verify_reprojection.py
docker exec deeplabcut-webapp-docker-dlc-3d-1 \
  python3 /tmp/verify_reprojection.py
```

Expected: a per-bodypart threshold table, verdict counts, and `All invariants passed.`

Sanity-check the numbers against the spec's Evidence section before accepting: `t_ok` should span roughly 3–22 px across bodyparts, `RESCUE` should be a substantial share, `UNJUDGED` roughly half. Exact counts will differ from the spec's figures because the spec measured `REJECT` with a stricter `lik_tgt > 0.9` filter and did not apply the 3D gate. If `RESCUE` is far below the spec's 133,809, investigate the gate before moving on — it may be over-rejecting.

- [ ] **Step 3: Confirm the source session is untouched**

```bash
ls "/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/tdcs/070126" \
  | grep -c reprojected
```

Expected: `0`

- [ ] **Step 4: Commit**

```bash
git add dlc-3D/scripts/verify_reprojection.py
git commit -m "test(reprojection): real-data verification script for the 070126 session"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
| --- | --- |
| Geometry (F, undistortion, distance) | 1, 2 |
| Epipolar line endpoints for overlay | 3 |
| DLT triangulation | 4 |
| Threshold estimation + fallback chain | 5 |
| Parameters table (`gate_ref`, `low_tgt`, `high_conf`, `rescue_floor`) | 5, 6, 7 |
| Decision table, precedence, verdict codes | 6 |
| 3D plausibility gate | 6 |
| Reference selection + per-bodypart overrides | 7 (`overrides`) |
| Both-camera `_reprojected.h5`, storage contract mirroring | 7 |
| JSON summary, npz arrays | 7 |
| Four API endpoints | 8 |
| Evidence numbers reproducible | 9 |

Not covered here by design: everything under the spec's "UI clone" and "Rollout" headings, which is the second plan.

**Placeholder scan:** none. Every step has runnable code or an exact command.

**Type consistency:** `Cam` field names (`K`, `dist`, `rvec`, `tvec`, `size`, `name`) are identical in Tasks 1, 4, 7, 8. Verdict constants are defined once in Task 1 and imported everywhere. `auto_threshold` returns the same key set (`med`, `mad`, `t_ok`, `t_bad`, `n_highconf`, `threshold_source`) in Tasks 5, 7, 8, 9. `read_pose_h5` meta keys (`key`, `is_table`, `scorer`, `bodyparts`, `dtypes`) are consistent in Tasks 7, 8, 9. npz array names (`d_tgt__`, `d_ref__`, `codes__`, `xyz__` + bodypart) are written in Task 7 and read in Task 9.

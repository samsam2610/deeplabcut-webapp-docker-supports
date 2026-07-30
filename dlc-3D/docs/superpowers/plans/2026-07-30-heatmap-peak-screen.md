# Heatmap Peak Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit DeepLabCut's top-K heatmap peaks as a sidecar during Analyze-for-tag, and use them as a veto-only screen that refuses epipolar rescues unsupported by image evidence.

**Architecture:** A new additive Celery task in the main webapp runs a second GPU pass after analysis and writes `<stem><scorer>_peaks.npz` beside each pose h5. The existing `_run_range` is not touched, so the production "3D Inline Analysis" card is unaffected. In dlc-3D, `run_reprojection` gains an optional screen that downgrades `RESCUE` verdicts when no single qualifying peak sits on the epipolar line. Marker positions are never modified by the screen.

**Tech Stack:** Python 3.9 (host tests) / 3.10+ (containers), numpy, scipy.ndimage, pandas, OpenCV, PyTorch, DeepLabCut 3.0.0rc14 PyTorch engine, Flask, Celery, Redis, vanilla ES modules + `node --test` for pure JS.

**Spec:** `dlc-3D/docs/superpowers/specs/2026-07-30-heatmap-peak-screen-design.md`

## Global Constraints

- **Never modify `_run_range`** in `deeplabcut-webapp-docker/src/dlc/tasks.py`. Additions to that file go at the bottom, as new functions only.
- **Never modify `peak_verdict.py`.** It is the scalar reference implementation and stays as-is.
- **The screen never changes a marker position or likelihood.** It only downgrades verdict codes so `apply_verdicts` declines to rescue.
- **The screen applies only to cells whose geometry verdict is `RESCUE`.** `CONFIRM`, `REJECT`, `RESCUE_REJECTED`, `UNJUDGED` and `AMBIGUOUS` are passed through untouched.
- **A cell with no sidecar coverage keeps its geometry verdict.** Absence of peaks is never treated as absence of evidence.
- **The inference pipeline is a verbatim port** of `dlc-3D/scripts/emit_peaks.py` lines 86–120. Do not re-derive it. The five values below are measured, not assumed, and getting any one wrong produced errors of 186–427 px:
  - native resolution padded up to a multiple of 32; **never** resized
  - `(rgb/255.0 - MEAN) / STD` with `MEAN = [0.485, 0.456, 0.406]`, `STD = [0.229, 0.224, 0.225]`
  - model output is nested: `out["bodypart"]["heatmap"]` and `out["bodypart"]["locref"]`
  - `STRIDE = 2.0` exactly
  - locref sub-pixel refinement applied with `locref_std` (default `7.2801`)
- **Sidecar path** is exactly `<pose_h5_stem>_peaks.npz` in the pose h5's directory.
- **Sidecar arrays and dtypes** are exactly: `frames` int32 `(N,)`; `xy` float32 `(N, B, K, 2)`; `score` float32 `(N, B, K)`; `bodyparts` unicode `(B,)`; `meta` a 0-d unicode array holding JSON.
- **Peak index 0 along K is DeepLabCut's argmax** — the marker already in the pose h5.
- **New verdict codes:** `NO_EVIDENCE = 6`, `CORRECTED = 7`. `AMBIGUOUS = 5` and `RESCUE = 2` already exist and keep their values.
- **UI defaults:** `Emit peaks` checkbox **checked**; `Require peak evidence` checkbox **unchecked**; `Peak score floor` number field `min=0 max=1 step=0.01 value=0.05`.
- **Extraction parameters `k=5` and `min_distance=3` are not exposed in the UI.**
- All new dlc-3D ids are namespaced `ia3dr-`, matching the reprojection card clone.
- Host test environment is Python **3.9** with numpy, scipy, pandas, h5py, cv2 — but **no torch and no deeplabcut**. Any module a host test imports must not import torch or deeplabcut at module scope.

---

### Task 1: Sidecar I/O

**Files:**
- Create: `dlc-3D/src/dlc_3d_bp/peaks_io.py`
- Test: `dlc-3D/tests/test_peaks_io.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `peaks_sidecar_path(pose_h5_path) -> pathlib.Path`
  - `write_peaks_npz(path, frames, xy, score, bodyparts, meta) -> None`
  - `read_peaks_npz(path) -> dict` with keys `frames` (int32 ndarray), `xy` (float32 ndarray), `score` (float32 ndarray), `bodyparts` (list[str]), `meta` (dict)
  - `merge_peaks(old, new) -> dict` — same dict shape; raises `ValueError` on bodypart mismatch

- [ ] **Step 1: Write the failing tests**

Create `dlc-3D/tests/test_peaks_io.py`:

```python
import json
from pathlib import Path

import numpy as np
import pytest

from dlc_3d_bp import peaks_io as pio


def _sample(frames, bodyparts=("nose", "wrist"), k=3, fill=1.0):
    n, b = len(frames), len(bodyparts)
    xy = np.full((n, b, k, 2), np.nan, np.float32)
    score = np.zeros((n, b, k), np.float32)
    xy[:, :, 0, :] = fill
    score[:, :, 0] = fill
    return {
        "frames": np.asarray(frames, np.int32),
        "xy": xy,
        "score": score,
        "bodyparts": list(bodyparts),
        "meta": {"k": k, "min_distance": 3, "snapshot": "snap.pt",
                 "stride": 2.0, "locref_std": 7.2801},
    }


def test_sidecar_path_sits_beside_the_pose_h5():
    p = pio.peaks_sidecar_path("/data/vidDLC_resnet50_x.h5")
    assert p == Path("/data/vidDLC_resnet50_x_peaks.npz")


def test_round_trip_preserves_values_dtypes_and_meta(tmp_path):
    s = _sample([0, 5, 9])
    dst = tmp_path / "a_peaks.npz"
    pio.write_peaks_npz(dst, s["frames"], s["xy"], s["score"],
                        s["bodyparts"], s["meta"])
    got = pio.read_peaks_npz(dst)
    assert got["frames"].dtype == np.int32
    assert got["xy"].dtype == np.float32
    assert got["score"].dtype == np.float32
    np.testing.assert_array_equal(got["frames"], s["frames"])
    np.testing.assert_allclose(got["xy"], s["xy"], equal_nan=True)
    assert got["bodyparts"] == ["nose", "wrist"]
    assert got["meta"]["locref_std"] == pytest.approx(7.2801)


def test_write_sorts_frames_and_reorders_the_arrays_with_them(tmp_path):
    s = _sample([7, 1, 4])
    s["xy"][:, :, 0, 0] = [70.0, 10.0, 40.0]
    dst = tmp_path / "b_peaks.npz"
    pio.write_peaks_npz(dst, s["frames"], s["xy"], s["score"],
                        s["bodyparts"], s["meta"])
    got = pio.read_peaks_npz(dst)
    np.testing.assert_array_equal(got["frames"], [1, 4, 7])
    np.testing.assert_allclose(got["xy"][:, 0, 0, 0], [10.0, 40.0, 70.0])


def test_write_rejects_duplicate_frames(tmp_path):
    s = _sample([3, 3])
    with pytest.raises(ValueError, match="duplicate"):
        pio.write_peaks_npz(tmp_path / "c_peaks.npz", s["frames"], s["xy"],
                            s["score"], s["bodyparts"], s["meta"])


def test_merge_unions_disjoint_frames_in_sorted_order():
    old, new = _sample([0, 2], fill=1.0), _sample([1, 3], fill=2.0)
    out = pio.merge_peaks(old, new)
    np.testing.assert_array_equal(out["frames"], [0, 1, 2, 3])
    np.testing.assert_allclose(out["xy"][:, 0, 0, 0], [1.0, 2.0, 1.0, 2.0])


def test_merge_prefers_the_new_run_on_overlapping_frames():
    old, new = _sample([0, 1, 2], fill=1.0), _sample([1], fill=9.0)
    out = pio.merge_peaks(old, new)
    np.testing.assert_array_equal(out["frames"], [0, 1, 2])
    np.testing.assert_allclose(out["xy"][:, 0, 0, 0], [1.0, 9.0, 1.0])


def test_merge_rejects_a_bodypart_mismatch():
    old = _sample([0], bodyparts=("nose", "wrist"))
    new = _sample([1], bodyparts=("nose", "elbow"))
    with pytest.raises(ValueError, match="bodypart"):
        pio.merge_peaks(old, new)


def test_merge_rejects_a_k_mismatch():
    old, new = _sample([0], k=3), _sample([1], k=5)
    with pytest.raises(ValueError, match="k"):
        pio.merge_peaks(old, new)


def test_merge_keeps_the_new_runs_meta():
    old, new = _sample([0]), _sample([1])
    new["meta"]["snapshot"] = "snapshot-best-999.pt"
    assert pio.merge_peaks(old, new)["meta"]["snapshot"] == "snapshot-best-999.pt"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd dlc-3D && python3 -m pytest tests/test_peaks_io.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dlc_3d_bp.peaks_io'`

- [ ] **Step 3: Implement the module**

Create `dlc-3D/src/dlc_3d_bp/peaks_io.py`:

```python
"""Read, write and merge the candidate-peak sidecar.

`<pose_h5_stem>_peaks.npz` holds DeepLabCut's top-K heatmap peaks for the frames
that were analysed. It is SPARSE — an explicit frame index — unlike the pose h5,
which is dense because downstream tools index it positionally. Tag runs touch a
few thousand of a video's 251k frames, so dense storage would be ~241 MB of
mostly-NaN against ~2 MB sparse.

numpy only: this must import on the host, where torch and DeepLabCut are absent.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def peaks_sidecar_path(pose_h5_path) -> Path:
    """`/d/vidDLC_x.h5` -> `/d/vidDLC_x_peaks.npz`."""
    p = Path(pose_h5_path)
    return p.with_name(p.stem + "_peaks.npz")


def write_peaks_npz(path, frames, xy, score, bodyparts, meta) -> None:
    """Write the sidecar, sorted by frame.

    Sorting here rather than at every read site means every consumer can rely on
    `frames` being ascending, which is what makes np.searchsorted lookups valid.
    """
    frames = np.asarray(frames, dtype=np.int32).reshape(-1)
    xy = np.asarray(xy, dtype=np.float32)
    score = np.asarray(score, dtype=np.float32)
    bodyparts = [str(b) for b in bodyparts]

    if xy.shape[:2] != (len(frames), len(bodyparts)) or xy.shape[-1] != 2:
        raise ValueError(
            "xy must be (N, B, K, 2) with N={} B={}, got {}".format(
                len(frames), len(bodyparts), xy.shape))
    if score.shape != xy.shape[:3]:
        raise ValueError(
            "score must be (N, B, K), got {} against xy {}".format(
                score.shape, xy.shape))
    if len(np.unique(frames)) != len(frames):
        raise ValueError("duplicate frame numbers in the sidecar index")

    order = np.argsort(frames, kind="stable")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        str(path),
        frames=frames[order],
        xy=xy[order],
        score=score[order],
        bodyparts=np.asarray(bodyparts, dtype=np.str_),
        meta=np.asarray(json.dumps(dict(meta)), dtype=np.str_),
    )


def read_peaks_npz(path) -> dict:
    """Load a sidecar into plain numpy arrays plus a decoded meta dict."""
    with np.load(str(path), allow_pickle=False) as z:
        return {
            "frames": np.asarray(z["frames"], dtype=np.int32),
            "xy": np.asarray(z["xy"], dtype=np.float32),
            "score": np.asarray(z["score"], dtype=np.float32),
            "bodyparts": [str(b) for b in z["bodyparts"]],
            "meta": json.loads(str(z["meta"])),
        }


def merge_peaks(old: dict, new: dict) -> dict:
    """Union the frame indices, preferring `new` where both carry a frame.

    A bodypart or k mismatch is an error rather than a merge: silently mixing
    two models' peaks in one file would corrupt every later lookup, and the
    failure would surface far from its cause.
    """
    if list(old["bodyparts"]) != list(new["bodyparts"]):
        raise ValueError(
            "bodypart mismatch: sidecar has {}, incoming run has {}".format(
                list(old["bodyparts"]), list(new["bodyparts"])))
    if old["xy"].shape[2] != new["xy"].shape[2]:
        raise ValueError(
            "k mismatch: sidecar has k={}, incoming run has k={}".format(
                old["xy"].shape[2], new["xy"].shape[2]))

    keep = ~np.isin(old["frames"], new["frames"])
    frames = np.concatenate([old["frames"][keep], new["frames"]])
    xy = np.concatenate([old["xy"][keep], new["xy"]])
    score = np.concatenate([old["score"][keep], new["score"]])
    order = np.argsort(frames, kind="stable")
    return {
        "frames": frames[order].astype(np.int32),
        "xy": xy[order].astype(np.float32),
        "score": score[order].astype(np.float32),
        "bodyparts": list(new["bodyparts"]),
        "meta": dict(new["meta"]),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd dlc-3D && python3 -m pytest tests/test_peaks_io.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/peaks_io.py dlc-3D/tests/test_peaks_io.py
git commit -m "feat(dlc-3d): candidate-peak sidecar read/write/merge"
```

---

### Task 2: The veto-only screen

**Files:**
- Create: `dlc-3D/src/dlc_3d_bp/peak_screen.py`
- Test: `dlc-3D/tests/test_peak_screen.py`

**Interfaces:**
- Consumes: verdict code constants — `RESCUE = 2`, `AMBIGUOUS = 5`, `NO_EVIDENCE = 6`, `CORRECTED = 7` — matching `dlc_3d_bp/peak_verdict.py`.
- Produces: `screen_rescues(codes, peak_dists, peak_scores, covered, t_ok, score_floor) -> (new_codes, stats)` where `new_codes` is a fresh `uint8` array and `stats` is `{"rescues": int, "covered": int, "kept": int, "refused": int, "ambiguous": int, "no_evidence": int, "corrected": int}`.

This is the vectorised twin of `peak_verdict.peak_verdict`. The scalar version stays
as the reference; Step 1 includes a randomised agreement test between the two, which
is what stops the two implementations drifting.

- [ ] **Step 1: Write the failing tests**

Create `dlc-3D/tests/test_peak_screen.py`:

```python
import numpy as np
import pytest

from dlc_3d_bp import peak_screen as ps
from dlc_3d_bp.peak_verdict import peak_verdict, RESCUE, AMBIGUOUS, NO_EVIDENCE, CORRECTED

UNJUDGED, REJECT, RESCUE_REJECTED, CONFIRM = 0, 1, 3, 4
T_OK, FLOOR = 5.0, 0.05


def _one(code, dists, scores, covered=True):
    """Screen a single cell and return its resulting code."""
    new, _ = ps.screen_rescues(
        np.array([code], np.uint8),
        np.array([dists], float),
        np.array([scores], float),
        np.array([covered], bool),
        t_ok=T_OK, score_floor=FLOOR,
    )
    return int(new[0])


def test_keeps_rescue_when_only_the_argmax_is_on_the_line():
    assert _one(RESCUE, [1.0, 40.0, 40.0], [0.4, 0.4, 0.4]) == RESCUE


def test_refuses_with_no_evidence_when_no_peak_is_on_the_line():
    assert _one(RESCUE, [40.0, 40.0, 40.0], [0.4, 0.4, 0.4]) == NO_EVIDENCE


def test_refuses_as_ambiguous_when_two_peaks_are_on_the_line():
    assert _one(RESCUE, [1.0, 2.0, 40.0], [0.4, 0.4, 0.4]) == AMBIGUOUS


def test_refuses_as_corrected_when_a_different_peak_is_the_one_on_the_line():
    assert _one(RESCUE, [40.0, 1.0, 40.0], [0.4, 0.4, 0.4]) == CORRECTED


def test_a_peak_below_the_score_floor_does_not_qualify():
    # On the line, but the detector barely responded there.
    assert _one(RESCUE, [1.0, 40.0, 40.0], [0.01, 0.0, 0.0]) == NO_EVIDENCE


def test_nan_padded_peaks_never_qualify():
    assert _one(RESCUE, [np.nan, np.nan, np.nan], [0.0, 0.0, 0.0]) == NO_EVIDENCE


@pytest.mark.parametrize("code", [UNJUDGED, REJECT, RESCUE_REJECTED, CONFIRM, AMBIGUOUS])
def test_non_rescue_verdicts_are_passed_through_untouched(code):
    # Peaks say "no evidence", but the screen has no authority over these.
    assert _one(code, [40.0, 40.0, 40.0], [0.4, 0.4, 0.4]) == code


def test_an_uncovered_frame_keeps_its_geometry_verdict():
    assert _one(RESCUE, [np.nan] * 3, [0.0] * 3, covered=False) == RESCUE


def test_stats_count_every_outcome():
    codes = np.array([RESCUE, RESCUE, RESCUE, RESCUE, CONFIRM], np.uint8)
    d = np.array([
        [1.0, 40.0, 40.0],    # keep
        [40.0, 40.0, 40.0],   # no evidence
        [1.0, 2.0, 40.0],     # ambiguous
        [40.0, 1.0, 40.0],    # corrected
        [40.0, 40.0, 40.0],   # CONFIRM, untouched
    ])
    s = np.full((5, 3), 0.4)
    covered = np.array([True, True, True, False, True])
    new, stats = ps.screen_rescues(codes, d, s, covered, T_OK, FLOOR)
    assert stats["rescues"] == 4
    assert stats["covered"] == 3
    assert stats["kept"] == 1
    assert stats["no_evidence"] == 1
    assert stats["ambiguous"] == 1
    assert stats["corrected"] == 0      # that frame was uncovered
    assert stats["refused"] == 2
    assert int(new[3]) == RESCUE        # uncovered, untouched
    assert int(new[4]) == CONFIRM


def test_input_codes_are_not_mutated():
    codes = np.array([RESCUE], np.uint8)
    ps.screen_rescues(codes, np.array([[40.0]]), np.array([[0.4]]),
                      np.array([True]), T_OK, FLOOR)
    assert int(codes[0]) == RESCUE


def test_empty_input_is_handled():
    new, stats = ps.screen_rescues(
        np.zeros(0, np.uint8), np.zeros((0, 3)), np.zeros((0, 3)),
        np.zeros(0, bool), T_OK, FLOOR)
    assert new.shape == (0,)
    assert stats["rescues"] == 0


def test_agrees_with_the_scalar_reference_implementation():
    """The vectorised screen must match peak_verdict.peak_verdict exactly.

    Two implementations of one rule drift. This is the test that catches it.
    """
    rng = np.random.default_rng(20260730)
    n, k = 500, 4
    d = rng.uniform(0, 12, size=(n, k))
    d[rng.random((n, k)) < 0.2] = np.nan
    s = rng.uniform(0, 0.5, size=(n, k))
    codes = np.full(n, RESCUE, np.uint8)
    new, _ = ps.screen_rescues(codes, d, s, np.ones(n, bool), T_OK, FLOOR)
    for i in range(n):
        want, _ = peak_verdict(d[i], s[i], T_OK, FLOOR)
        assert int(new[i]) == want, f"row {i}: {d[i]} {s[i]}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd dlc-3D && python3 -m pytest tests/test_peak_screen.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dlc_3d_bp.peak_screen'`

- [ ] **Step 3: Implement the module**

Create `dlc-3D/src/dlc_3d_bp/peak_screen.py`:

```python
"""Veto-only application of candidate-peak evidence to geometry verdicts.

The geometry engine rescues a low-confidence marker that lies on the epipolar
line. That reasoning fails under occlusion: DeepLabCut had no image evidence, so
its marker is a guess, and a one-degree-of-freedom constraint endorses any guess
landing in the band. This screen asks the better question — does the image
contain evidence for this part ON the line — and refuses the rescue when it does
not.

VETO ONLY. Marker positions are never touched. `CORRECTED` is reported so the
audit can say "a different peak was the one on the line", but the applier
refuses it rather than moving anything: measured on labelled data, moving
markers improved a badly-tracked session (23.57 -> 17.27 px) and degraded two
already-accurate ones (8.42 -> 10.33 and 4.45 -> 7.38 px).

This is the vectorised twin of peak_verdict.peak_verdict, which remains the
scalar reference. tests/test_peak_screen.py asserts they agree.

numpy only, so it imports on the host.
"""
from __future__ import annotations

import numpy as np

RESCUE = 2
AMBIGUOUS = 5
NO_EVIDENCE = 6
CORRECTED = 7


def screen_rescues(codes, peak_dists, peak_scores, covered,
                   t_ok: float, score_floor: float):
    """Downgrade RESCUE verdicts unsupported by the candidate peaks.

    codes       -- (n,) geometry verdict per frame for ONE bodypart
    peak_dists  -- (n, K) each peak's distance to the epipolar line, NaN-padded
    peak_scores -- (n, K) each peak's heatmap score, 0-padded
    covered     -- (n,) bool, whether the sidecar has a row for this frame
    Peak index 0 is DeepLabCut's argmax, i.e. the marker already in the pose h5.

    Returns (new_codes, stats). Only cells that are RESCUE *and* covered can
    change; everything else is passed through, including uncovered rescues —
    absence of peaks is not absence of evidence.
    """
    out = np.array(codes, dtype=np.uint8, copy=True)
    d = np.asarray(peak_dists, dtype=float)
    s = np.asarray(peak_scores, dtype=float)
    cov = np.asarray(covered, dtype=bool)

    is_rescue = out == RESCUE
    active = is_rescue & cov
    stats = {
        "rescues": int(is_rescue.sum()),
        "covered": int(active.sum()),
        "kept": 0, "refused": 0,
        "ambiguous": 0, "no_evidence": 0, "corrected": 0,
    }
    if not active.any():
        return out, stats

    qualifies = np.isfinite(d) & (d <= float(t_ok)) & (s >= float(score_floor))
    n_qual = qualifies.sum(axis=1)
    argmax_ok = qualifies[:, 0] if qualifies.shape[1] else np.zeros(len(out), bool)

    none_on_line = active & (n_qual == 0)
    several = active & (n_qual > 1)
    only_argmax = active & (n_qual == 1) & argmax_ok
    only_other = active & (n_qual == 1) & ~argmax_ok

    out[none_on_line] = NO_EVIDENCE
    out[several] = AMBIGUOUS
    out[only_other] = CORRECTED
    # only_argmax keeps RESCUE.

    stats["no_evidence"] = int(none_on_line.sum())
    stats["ambiguous"] = int(several.sum())
    stats["corrected"] = int(only_other.sum())
    stats["kept"] = int(only_argmax.sum())
    stats["refused"] = (stats["no_evidence"] + stats["ambiguous"]
                        + stats["corrected"])
    return out, stats
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd dlc-3D && python3 -m pytest tests/test_peak_screen.py -v`
Expected: PASS, 16 tests (the parametrised pass-through case counts as 5).

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/peak_screen.py dlc-3D/tests/test_peak_screen.py
git commit -m "feat(dlc-3d): veto-only peak screen for epipolar rescues"
```

---

### Task 3: Wire the screen into `run_reprojection`

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/epipolar_core.py:23-30` (extend `VERDICT_NAMES`)
- Modify: `dlc-3D/src/dlc_3d_bp/reprojection.py:147-290` (`run_reprojection`)
- Test: `dlc-3D/tests/test_peak_screen_integration.py`

**Interfaces:**
- Consumes: `peaks_io.read_peaks_npz`, `peaks_io.peaks_sidecar_path`, `peak_screen.screen_rescues` from Tasks 1–2; existing `ec.epipolar_distance`, `ec.undistort_to_pixels`.
- Produces:
  - `reprojection.align_peaks_to_frames(n_frames, peaks, bodypart) -> (xy, score, covered)` with shapes `(n, K, 2)`, `(n, K)`, `(n,)`
  - `run_reprojection(..., require_peaks: bool = False, peak_score_floor: float = 0.05)` — new keyword-only-in-practice arguments appended after `overrides`
  - `summary["peak_screen"]` — `None` when the screen did not run, else a dict of the aggregate `stats` keys from Task 2 plus `"bodyparts": {bp: stats}`

- [ ] **Step 1: Write the failing tests**

Create `dlc-3D/tests/test_peak_screen_integration.py`:

```python
"""The screen inside run_reprojection, driven by a synthetic sidecar.

Reuses the fixture builders already proven in tests/test_reprojection_io.py so
the geometry is real rather than mocked.
"""
import numpy as np
import pytest

from dlc_3d_bp import peaks_io as pio
from dlc_3d_bp import reprojection as rp
from dlc_3d_bp.peak_verdict import NO_EVIDENCE

from test_reprojection_io import (            # noqa: F401 — shared fixture builders
    _write_calibration, _write_pose_h5,
)


def _sidecar_for(h5_path, frames, bodyparts, xy_per_frame, k=3):
    """Write a sidecar whose peak 0 is at xy_per_frame and whose rest are NaN."""
    n, b = len(frames), len(bodyparts)
    xy = np.full((n, b, k, 2), np.nan, np.float32)
    score = np.zeros((n, b, k), np.float32)
    for i in range(n):
        for j in range(b):
            xy[i, j, 0] = xy_per_frame[i]
            score[i, j, 0] = 0.9
    pio.write_peaks_npz(
        pio.peaks_sidecar_path(h5_path), np.asarray(frames, np.int32),
        xy, score, list(bodyparts),
        {"k": k, "min_distance": 3, "snapshot": "s.pt",
         "stride": 2.0, "locref_std": 7.2801})


def test_align_maps_sparse_sidecar_rows_onto_dense_frame_positions():
    peaks = {
        "frames": np.array([0, 2], np.int32),
        "xy": np.array([[[[1.0, 2.0]]], [[[3.0, 4.0]]]], np.float32),
        "score": np.array([[[0.7]], [[0.8]]], np.float32),
        "bodyparts": ["nose"],
        "meta": {},
    }
    xy, score, covered = rp.align_peaks_to_frames(4, peaks, "nose")
    assert xy.shape == (4, 1, 2) and score.shape == (4, 1)
    np.testing.assert_array_equal(covered, [True, False, True, False])
    np.testing.assert_allclose(xy[0, 0], [1.0, 2.0])
    np.testing.assert_allclose(xy[2, 0], [3.0, 4.0])
    assert np.isnan(xy[1]).all()
    assert score[1, 0] == 0.0


def test_align_returns_all_uncovered_for_an_unknown_bodypart():
    peaks = {
        "frames": np.array([0], np.int32),
        "xy": np.zeros((1, 1, 2, 2), np.float32),
        "score": np.zeros((1, 1, 2), np.float32),
        "bodyparts": ["nose"], "meta": {},
    }
    xy, score, covered = rp.align_peaks_to_frames(3, peaks, "elbow")
    assert not covered.any()
    assert np.isnan(xy).all()


def test_summary_reports_no_screen_when_require_peaks_is_off(tmp_path):
    calib = _write_calibration(tmp_path)
    ref_h5 = _write_pose_h5(tmp_path, "cam_0")
    tgt_h5 = _write_pose_h5(tmp_path, "cam_1")
    out = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                              out_dir=tmp_path, require_peaks=False)
    assert out["peak_screen"] is None


def test_missing_sidecar_leaves_every_rescue_standing(tmp_path):
    """require_peaks with no sidecar must not silently void every rescue."""
    calib = _write_calibration(tmp_path)
    ref_h5 = _write_pose_h5(tmp_path, "cam_0")
    tgt_h5 = _write_pose_h5(tmp_path, "cam_1")
    base = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                               out_dir=tmp_path / "a", require_peaks=False)
    screened = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                                   out_dir=tmp_path / "b", require_peaks=True)
    assert screened["counts"]["RESCUE"] == base["counts"]["RESCUE"]
    assert screened["peak_screen"]["covered"] == 0


def test_a_sidecar_with_peaks_far_off_the_line_refuses_every_rescue(tmp_path):
    """Peaks parked far from any epipolar line must produce NO_EVIDENCE."""
    calib = _write_calibration(tmp_path)
    ref_h5 = _write_pose_h5(tmp_path, "cam_0")
    tgt_h5 = _write_pose_h5(tmp_path, "cam_1")
    base = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                               out_dir=tmp_path / "a", require_peaks=False)
    if base["counts"]["RESCUE"] == 0:
        pytest.skip("fixture produced no rescues to screen")

    df, meta = rp.read_pose_h5(tgt_h5)
    n = len(df)
    _sidecar_for(tgt_h5, list(range(n)), meta["bodyparts"],
                 [(9e4, 9e4)] * n)

    screened = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                                   out_dir=tmp_path / "b", require_peaks=True)
    assert screened["counts"]["RESCUE"] == 0
    assert screened["counts"]["NO_EVIDENCE"] == base["counts"]["RESCUE"]
    assert screened["peak_screen"]["refused"] == base["counts"]["RESCUE"]


def test_the_screen_never_changes_a_marker_position(tmp_path):
    """Refusing a rescue must leave x/y exactly as the geometry run left them
    minus the rescue, and must never write a peak's coordinates."""
    calib = _write_calibration(tmp_path)
    ref_h5 = _write_pose_h5(tmp_path, "cam_0")
    tgt_h5 = _write_pose_h5(tmp_path, "cam_1")
    df, meta = rp.read_pose_h5(tgt_h5)
    n = len(df)
    _sidecar_for(tgt_h5, list(range(n)), meta["bodyparts"], [(9e4, 9e4)] * n)

    screened = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                                   out_dir=tmp_path / "b", require_peaks=True)
    out_df, out_meta = rp.read_pose_h5(screened["outputs"]["tgt_h5"])
    sc = out_meta["scorer"]
    for bp in out_meta["bodyparts"]:
        x = out_df[(sc, bp, "x")].to_numpy(dtype=float)
        assert not np.isclose(x[np.isfinite(x)], 9e4).any(), bp


def test_verdict_names_cover_the_two_new_codes():
    from dlc_3d_bp import epipolar_core as ec
    assert ec.VERDICT_NAMES[6] == "NO_EVIDENCE"
    assert ec.VERDICT_NAMES[7] == "CORRECTED"
```

Before writing the implementation, open `dlc-3D/tests/test_reprojection_io.py` and
confirm the helper names `_write_calibration` and `_write_pose_h5` exist with those
signatures. If they are named differently or take different arguments, adapt the
import and the calls above to what is actually there — do not add new fixture
builders when equivalents already exist.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd dlc-3D && python3 -m pytest tests/test_peak_screen_integration.py -v`
Expected: FAIL — `AttributeError: module 'dlc_3d_bp.reprojection' has no attribute 'align_peaks_to_frames'`

- [ ] **Step 3: Extend `VERDICT_NAMES`**

In `dlc-3D/src/dlc_3d_bp/epipolar_core.py`, add the two constants beside the
existing ones and extend the mapping:

```python
NO_EVIDENCE = 6
CORRECTED = 7

VERDICT_NAMES = {
    UNJUDGED: "UNJUDGED",
    REJECT: "REJECT",
    RESCUE: "RESCUE",
    RESCUE_REJECTED: "RESCUE_REJECTED",
    CONFIRM: "CONFIRM",
    AMBIGUOUS: "AMBIGUOUS",
    # Produced only by the candidate-peak screen (peak_screen.screen_rescues).
    # A geometry-only run never emits these, so their counts stay 0.
    NO_EVIDENCE: "NO_EVIDENCE",
    CORRECTED: "CORRECTED",
}
```

Then run `cd dlc-3D && python3 -m pytest tests/test_core.py tests/test_reprojection_io.py -q`
and fix any existing assertion that hard-codes six verdict names.

- [ ] **Step 4: Add `align_peaks_to_frames` to `reprojection.py`**

Add near the other module-level helpers, above `run_reprojection`:

```python
def align_peaks_to_frames(n_frames: int, peaks: "dict | None", bodypart: str):
    """Project a sparse sidecar onto dense frame positions for one bodypart.

    Returns (xy, score, covered) with shapes (n, K, 2), (n, K) and (n,).
    Frames the sidecar does not carry — and every frame when the sidecar lacks
    this bodypart — come back uncovered, which the screen passes through
    untouched.
    """
    if not peaks or bodypart not in peaks["bodyparts"]:
        return (np.full((n_frames, 1, 2), np.nan, np.float32),
                np.zeros((n_frames, 1), np.float32),
                np.zeros(n_frames, bool))

    j = list(peaks["bodyparts"]).index(bodypart)
    k = int(peaks["xy"].shape[2])
    xy = np.full((n_frames, k, 2), np.nan, np.float32)
    score = np.zeros((n_frames, k), np.float32)
    covered = np.zeros(n_frames, bool)

    frames = np.asarray(peaks["frames"], dtype=np.int64)
    keep = (frames >= 0) & (frames < n_frames)
    rows = np.flatnonzero(keep)
    if rows.size:
        dest = frames[keep]
        xy[dest] = peaks["xy"][rows, j]
        score[dest] = peaks["score"][rows, j]
        covered[dest] = True
    return xy, score, covered
```

Add the imports at the top of `reprojection.py`, beside the existing
`from dlc_3d_bp import epipolar_core as ec`:

```python
from dlc_3d_bp import peak_screen as ps
from dlc_3d_bp import peaks_io as pio
```

- [ ] **Step 5: Thread the screen through `run_reprojection`**

Append two parameters to the signature, after `overrides`:

```python
    overrides: "dict | None" = None,
    require_peaks: bool = False,
    peak_score_floor: float = 0.05,
) -> dict:
```

After `df_ref, meta_ref = read_pose_h5(ref_h5)` / `df_tgt, meta_tgt = read_pose_h5(tgt_h5)`,
load both sidecars once:

```python
    # Load whichever sidecars exist. A missing one is not an error: analyses
    # predating this feature have none, and treating absence as "no evidence"
    # would void every rescue in them.
    peaks_by_side = {"ref": None, "tgt": None}
    screen_totals = None
    if require_peaks:
        screen_totals = {"rescues": 0, "covered": 0, "kept": 0, "refused": 0,
                         "ambiguous": 0, "no_evidence": 0, "corrected": 0,
                         "bodyparts": {}}
        for side, h5 in (("ref", ref_h5), ("tgt", tgt_h5)):
            sc_path = pio.peaks_sidecar_path(h5)
            if Path(sc_path).is_file():
                peaks_by_side[side] = pio.read_peaks_npz(sc_path)
```

Inside the per-bodypart loop, immediately **after** the `apply_gate` line and
**before** the `if flipped:` block that picks the output frame:

```python
        if require_peaks:
            # The judged side is the one being corrected, so its sidecar is the
            # one that carries evidence about the marker under test.
            judged_peaks = peaks_by_side["ref" if flipped else "tgt"]
            cam_judged = cam_ref if flipped else cam_tgt
            u_inducing = u_tgt if flipped else u_ref
            F_judged = F["ref"] if flipped else F["tgt"]

            p_xy, p_sc, covered = align_peaks_to_frames(len(codes), judged_peaks, bp)
            d_pk = np.full(p_sc.shape, np.nan)
            for kk in range(p_xy.shape[1]):
                # Peaks live in the same raw distorted pixel space as the pose
                # h5, so the existing undistort applies unchanged.
                d_pk[:, kk] = ec.epipolar_distance(
                    F_judged, u_inducing,
                    ec.undistort_to_pixels(cam_judged, p_xy[:, kk, :].astype(float)),
                )
            codes, sstats = ps.screen_rescues(
                codes, d_pk, p_sc, covered,
                t_ok=st["t_ok"], score_floor=peak_score_floor)
            screen_totals["bodyparts"][bp] = sstats
            for key in ("rescues", "covered", "kept", "refused",
                        "ambiguous", "no_evidence", "corrected"):
                screen_totals[key] += sstats[key]
```

Add `peak_score_floor` and `require_peaks` to `summary["config"]`, and add the
screen block to the summary itself:

```python
            "require_peaks": bool(require_peaks),
            "peak_score_floor": float(peak_score_floor),
```

```python
        "peak_screen": screen_totals,
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd dlc-3D && python3 -m pytest tests/test_peak_screen_integration.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full dlc-3D suite for regressions**

Run: `cd dlc-3D && python3 -m pytest tests/ -q -x --ignore=tests/e2e`
Expected: no new failures against the pre-task baseline. Record the baseline
first with `git stash && python3 -m pytest tests/ -q --ignore=tests/e2e; git stash pop`
if you are unsure which failures pre-existed.

- [ ] **Step 8: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/epipolar_core.py dlc-3D/src/dlc_3d_bp/reprojection.py \
        dlc-3D/tests/test_peak_screen_integration.py
git commit -m "feat(dlc-3d): apply the peak screen inside run_reprojection"
```

---

### Task 4: dlc-3D routes — screen parameters and sidecar discovery

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/routes.py` (the `/reproject/run` handler near line 883; append a new route at the end of the reprojection block)
- Test: `dlc-3D/tests/test_reprojection_routes.py` (append)

**Interfaces:**
- Consumes: `run_reprojection(..., require_peaks, peak_score_floor)` and `peaks_io.peaks_sidecar_path` from Task 3.
- Produces: `GET /reproject/peaks-status?ref_h5=…&tgt_h5=…` → `{"ref": {"present": bool, "frames": int|null}, "tgt": {...}}`

- [ ] **Step 1: Write the failing tests**

Append to `dlc-3D/tests/test_reprojection_routes.py`:

```python
def test_run_forwards_the_screen_parameters(client, monkeypatch, reproj_payload):
    seen = {}

    def fake_run(*a, **kw):
        seen.update(kw)
        return {"counts": {}, "bodyparts": {}, "outputs": {}, "peak_screen": None}

    monkeypatch.setattr("dlc_3d_bp.routes.rp.run_reprojection", fake_run)
    body = dict(reproj_payload, require_peaks=True, peak_score_floor=0.2)
    resp = client.post("/reproject/run", json=body)
    assert resp.status_code == 200
    assert seen["require_peaks"] is True
    assert seen["peak_score_floor"] == 0.2


def test_run_defaults_the_screen_off(client, monkeypatch, reproj_payload):
    seen = {}
    monkeypatch.setattr(
        "dlc_3d_bp.routes.rp.run_reprojection",
        lambda *a, **kw: (seen.update(kw),
                          {"counts": {}, "bodyparts": {}, "outputs": {},
                           "peak_screen": None})[1])
    assert client.post("/reproject/run", json=reproj_payload).status_code == 200
    assert seen["require_peaks"] is False
    assert seen["peak_score_floor"] == 0.05


def test_run_rejects_an_out_of_range_score_floor(client, reproj_payload):
    resp = client.post("/reproject/run",
                       json=dict(reproj_payload, peak_score_floor=1.5))
    assert resp.status_code == 400
    assert "peak_score_floor" in resp.get_json()["error"]


def test_peaks_status_reports_absent_sidecars(client, reproj_payload):
    resp = client.get("/reproject/peaks-status", query_string={
        "ref_h5": reproj_payload["ref_h5"], "tgt_h5": reproj_payload["tgt_h5"]})
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["ref"]["present"] is False and d["tgt"]["present"] is False


def test_peaks_status_reports_a_present_sidecar(client, reproj_payload):
    import numpy as np
    from dlc_3d_bp import peaks_io as pio
    dst = pio.peaks_sidecar_path(reproj_payload["tgt_h5"])
    pio.write_peaks_npz(dst, np.array([0, 1], np.int32),
                        np.zeros((2, 1, 2, 2), np.float32),
                        np.zeros((2, 1, 2), np.float32), ["nose"], {"k": 2})
    resp = client.get("/reproject/peaks-status", query_string={
        "ref_h5": reproj_payload["ref_h5"], "tgt_h5": reproj_payload["tgt_h5"]})
    d = resp.get_json()
    assert d["tgt"]["present"] is True and d["tgt"]["frames"] == 2


def test_peaks_status_refuses_a_path_outside_the_data_root(client):
    resp = client.get("/reproject/peaks-status", query_string={
        "ref_h5": "/etc/passwd", "tgt_h5": "/etc/passwd"})
    assert resp.status_code == 403
```

Open the existing `dlc-3D/tests/test_reprojection_routes.py` first and reuse its
`client` fixture and whatever it already uses to build a valid `/reproject/run`
body. If there is no `reproj_payload` fixture, add one that returns the same dict
the existing run-route tests post, so these tests share one source of truth
rather than duplicating a payload literal.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd dlc-3D && python3 -m pytest tests/test_reprojection_routes.py -v -k "screen or peaks_status or score_floor"`
Expected: FAIL — 404 on `/reproject/peaks-status`, and `KeyError: 'require_peaks'`.

- [ ] **Step 3: Forward the parameters in `/reproject/run`**

In `routes.py`, inside `reproject_run`, beside the existing `k1`/`k2` parsing:

```python
        peak_score_floor = _float_arg(body, "peak_score_floor", 0.05)
        if not (0.0 <= peak_score_floor <= 1.0):
            raise ValueError("peak_score_floor must be in 0..1")
```

and pass both through to `rp.run_reprojection`:

```python
            require_peaks=bool(body.get("require_peaks", False)),
            peak_score_floor=peak_score_floor,
```

- [ ] **Step 4: Add the status route**

Append after the `/reproject/epiline` route:

```python
@bp.route("/reproject/peaks-status", methods=["GET"])
def reproject_peaks_status():
    """Whether a candidate-peak sidecar exists for each side. Writes nothing.

    The card uses this to enable or grey out "Require peak evidence", so that a
    screen with nothing to screen with is unreachable from the UI rather than
    silently inert.
    """
    args = {k: (request.args.get(k) or "").strip() for k in ("ref_h5", "tgt_h5")}
    for k, v in args.items():
        if not v:
            return jsonify({"error": "missing: " + k}), 400

    out = {}
    for side, key in (("ref", "ref_h5"), ("tgt", "tgt_h5")):
        safe = _safe_user_data_path(args[key])
        if safe is None:
            return jsonify({"error": "path outside /user-data: " + key}), 403
        sc = pio.peaks_sidecar_path(safe)
        if not sc.is_file():
            out[side] = {"present": False, "frames": None}
            continue
        try:
            n = int(len(pio.read_peaks_npz(sc)["frames"]))
        except Exception as exc:
            out[side] = {"present": False, "frames": None, "error": str(exc)[:200]}
            continue
        out[side] = {"present": True, "frames": n}
    return jsonify(out)
```

Add the import beside the existing `from dlc_3d_bp import reprojection as rp`:

```python
from dlc_3d_bp import peaks_io as pio
```

Check the exact name and return contract of the existing path-containment helper
before using it — the plan assumes `_safe_user_data_path(str) -> Path | None`.
If it differs, use whatever `_reproject_args` uses, and keep the 403 behaviour.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd dlc-3D && python3 -m pytest tests/test_reprojection_routes.py -v`
Expected: PASS, including the pre-existing route tests.

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/routes.py dlc-3D/tests/test_reprojection_routes.py
git commit -m "feat(dlc-3d): screen params on /reproject/run plus /reproject/peaks-status"
```

---

### Task 5: Main-webapp peak emitter module

**Files:**
- Create: `deeplabcut-webapp-docker/src/dlc/peaks_emit.py`
- Test: `deeplabcut-webapp-docker/tests/test_peaks_emit.py`
- Reference (read, do not modify): `deeplabcut-webapp-docker-supports/dlc-3D/scripts/emit_peaks.py`, `deeplabcut-webapp-docker-supports/dlc-3D/src/dlc_3d_bp/peaks.py`

**Interfaces:**
- Consumes: nothing from earlier tasks. This file lives in a different repository from Tasks 1–4 and must not import `dlc_3d_bp`.
- Produces:
  - `extract_peaks(heatmap, k=5, min_distance=3) -> (xy, scores)` — verbatim copy from `dlc_3d_bp/peaks.py`
  - `heatmap_to_image(xy_cells, stride, pad_xy=(0,0), scale_xy=(1.0,1.0)) -> ndarray` — verbatim copy
  - `emit_peaks_for_video(video_path, h5_path, model_dir, snapshot_name, frames, k=5, min_distance=3, device=None) -> dict` with keys `sidecar`, `n_frames`, `bodyparts`

**On the duplication:** `extract_peaks` and `heatmap_to_image` are copied
verbatim rather than imported. The two repositories are separately built
containers; a cross-repo import would need a bind mount of dlc-3D source into
the main worker, which is more operational coupling than 60 lines of frozen,
already-tested numpy warrants. Task 9 adds a guard test that the copies stay
byte-identical. Do not "improve" either copy.

- [ ] **Step 1: Write the failing tests**

Create `deeplabcut-webapp-docker/tests/test_peaks_emit.py`:

```python
"""Host-testable parts of the peak emitter.

The inference itself needs torch + DeepLabCut and is NOT covered here; it is
verified by re-running the 0.344 px comparison against the pose h5 on the
deployed container. What is covered is everything around it.
"""
import numpy as np
import pytest

from dlc.peaks_emit import extract_peaks, heatmap_to_image


def test_extract_peaks_finds_the_single_maximum():
    hm = np.zeros((20, 20), np.float32)
    hm[7, 11] = 1.0
    xy, sc = extract_peaks(hm, k=3, min_distance=3)
    np.testing.assert_allclose(xy[0], [11.0, 7.0])   # x = column, y = row
    assert sc[0] == pytest.approx(1.0)
    assert np.isnan(xy[1]).all() and sc[1] == 0.0


def test_extract_peaks_suppresses_neighbours_of_one_blob():
    """Without NMS a plain top-k returns the peak and its neighbours, so k
    'candidates' would be one detection counted k times."""
    hm = np.zeros((20, 20), np.float32)
    hm[10, 10] = 1.0
    hm[10, 11] = 0.99
    hm[11, 10] = 0.98
    xy, sc = extract_peaks(hm, k=3, min_distance=3)
    assert np.isfinite(xy).all(axis=1).sum() == 1


def test_extract_peaks_returns_two_separated_blobs_in_score_order():
    hm = np.zeros((30, 30), np.float32)
    hm[5, 5] = 0.6
    hm[20, 20] = 0.9
    xy, sc = extract_peaks(hm, k=3, min_distance=3)
    np.testing.assert_allclose(xy[0], [20.0, 20.0])
    np.testing.assert_allclose(xy[1], [5.0, 5.0])
    assert sc[0] > sc[1]


def test_extract_peaks_on_a_flat_heatmap_returns_nothing():
    xy, sc = extract_peaks(np.zeros((10, 10), np.float32), k=3)
    assert np.isnan(xy).all() and (sc == 0).all()


def test_heatmap_to_image_maps_cell_centres_at_stride_two():
    out = heatmap_to_image(np.array([[3.0, 4.0]]), 2.0)
    np.testing.assert_allclose(out[0], [7.0, 9.0])   # (cell + 0.5) * stride


def test_heatmap_to_image_preserves_nan_padding():
    out = heatmap_to_image(np.array([[np.nan, np.nan]]), 2.0)
    assert np.isnan(out).all()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd deeplabcut-webapp-docker && python3 -m pytest tests/test_peaks_emit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dlc.peaks_emit'`

- [ ] **Step 3: Implement the module**

Create `deeplabcut-webapp-docker/src/dlc/peaks_emit.py`. Copy `extract_peaks`
and `heatmap_to_image` **verbatim** from
`../deeplabcut-webapp-docker-supports/dlc-3D/src/dlc_3d_bp/peaks.py` (including
their docstrings and comments), then add:

```python
"""Emit DeepLabCut candidate peaks for a video as a sparse .npz sidecar.

Stock single-animal inference argmaxes the heatmap away. Keeping the top-K peaks
lets the epipolar engine ask whether the IMAGE supports a part being on the line,
rather than only whether the marker is consistent with it.

torch, cv2, yaml and deeplabcut are imported INSIDE emit_peaks_for_video so that
the pure helpers above stay importable on a host with none of them.

extract_peaks and heatmap_to_image are copied verbatim from dlc-3D's
dlc_3d_bp/peaks.py. The two repositories build separate containers, so a shared
import would need a cross-repo bind mount. tests/test_peaks_emit_parity.py in
dlc-3D asserts the copies stay identical — if you change one, change both.
"""
```

Then the emitter itself:

```python
import json
from pathlib import Path

import numpy as np

# --- verbatim copies from dlc-3D/src/dlc_3d_bp/peaks.py ---------------------
# (extract_peaks and heatmap_to_image go here, unmodified)
# ---------------------------------------------------------------------------

# PIPELINE VERIFIED EMPIRICALLY against the existing pose h5 (0.344 px median,
# 0.975 px p95 on confident markers). Every constant below was measured, not
# assumed — an earlier draft was wrong on all five and produced 186-427 px error.
_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)
_STRIDE = 2.0


def _peaks_sidecar_path(pose_h5_path) -> Path:
    """Must match dlc_3d_bp.peaks_io.peaks_sidecar_path exactly."""
    p = Path(pose_h5_path)
    return p.with_name(p.stem + "_peaks.npz")


def emit_peaks_for_video(video_path, h5_path, model_dir, snapshot_name,
                         frames, k=5, min_distance=3, device=None) -> dict:
    """Run the model over `frames` and write/merge the peak sidecar.

    `frames` is a sorted list of absolute video frame numbers. Returns
    {"sidecar": str, "n_frames": int, "bodyparts": list[str]}.

    The write is atomic-by-replace: the merged array is written to a temporary
    file in the same directory and renamed, so a crash leaves the previous
    sidecar intact rather than a truncated one.
    """
    import cv2
    import torch
    import yaml
    import deeplabcut.pose_estimation_pytorch as dlcpt

    cfg_path = Path(model_dir) / "train" / "pytorch_config.yaml"
    if not cfg_path.is_file():
        raise FileNotFoundError(f"pytorch_config.yaml not found at {cfg_path}")
    cfg = yaml.safe_load(cfg_path.read_text())
    bodyparts = list(cfg["metadata"]["bodyparts"])
    locref_std = (cfg.get("model", {}).get("heads", {}).get("bodypart", {})
                     .get("predictor", {}).get("locref_std", 7.2801))

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    model = dlcpt.models.PoseModel.build(cfg["model"])
    state = torch.load(Path(model_dir) / "train" / snapshot_name,
                       map_location=device, weights_only=False)
    model.load_state_dict(state["model"] if "model" in state else state)
    model.to(device).eval()

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")

    frames = sorted({int(f) for f in frames})
    n, b = len(frames), len(bodyparts)
    XY = np.full((n, b, k, 2), np.nan, np.float32)
    SC = np.zeros((n, b, k), np.float32)
    got = []

    try:
        for i, fno in enumerate(frames):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fno)
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            H, W = ((h + 31) // 32) * 32, ((w + 31) // 32) * 32
            im = cv2.copyMakeBorder(frame, 0, H - h, 0, W - w,
                                    cv2.BORDER_CONSTANT, value=0)
            rgb = (cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.float32)
                   / 255.0 - _MEAN) / _STD
            t_in = torch.from_numpy(rgb).permute(2, 0, 1)[None].to(device)
            with torch.no_grad():
                out = model(t_in)
            hm = torch.sigmoid(out["bodypart"]["heatmap"])[0].cpu().numpy()
            lr = out["bodypart"]["locref"][0].cpu().numpy()
            for j in range(b):
                cells, sc = extract_peaks(hm[j], k=k, min_distance=min_distance)
                # Padding is bottom/right only, so the origin does not shift,
                # and there is no resize: pad_xy=(0,0), scale_xy=(1,1).
                xy = heatmap_to_image(cells, _STRIDE, (0, 0), (1.0, 1.0))
                for p_i in range(k):
                    if not np.isfinite(cells[p_i]).all():
                        continue
                    c_col, c_row = int(cells[p_i, 0]), int(cells[p_i, 1])
                    xy[p_i, 0] += lr[2 * j, c_row, c_col] * locref_std
                    xy[p_i, 1] += lr[2 * j + 1, c_row, c_col] * locref_std
                XY[i, j] = xy
                SC[i, j] = sc
            got.append(i)
    finally:
        cap.release()

    rows = np.asarray(got, dtype=int)
    new = {
        "frames": np.asarray([frames[i] for i in rows], np.int32),
        "xy": XY[rows], "score": SC[rows],
        "bodyparts": bodyparts,
        "meta": {"k": int(k), "min_distance": int(min_distance),
                 "snapshot": str(snapshot_name), "stride": _STRIDE,
                 "locref_std": float(locref_std)},
    }

    dst = _peaks_sidecar_path(h5_path)
    merged = new
    if dst.is_file():
        merged = _merge(_read(dst), new)
    _write_atomic(dst, merged)
    return {"sidecar": str(dst), "n_frames": int(len(merged["frames"])),
            "bodyparts": bodyparts}


def _read(path) -> dict:
    with np.load(str(path), allow_pickle=False) as z:
        return {
            "frames": np.asarray(z["frames"], np.int32),
            "xy": np.asarray(z["xy"], np.float32),
            "score": np.asarray(z["score"], np.float32),
            "bodyparts": [str(x) for x in z["bodyparts"]],
            "meta": json.loads(str(z["meta"])),
        }


def _merge(old: dict, new: dict) -> dict:
    if list(old["bodyparts"]) != list(new["bodyparts"]):
        raise ValueError(
            "bodypart mismatch: sidecar has {}, incoming run has {}".format(
                list(old["bodyparts"]), list(new["bodyparts"])))
    if old["xy"].shape[2] != new["xy"].shape[2]:
        raise ValueError("k mismatch: sidecar has k={}, incoming run has k={}"
                         .format(old["xy"].shape[2], new["xy"].shape[2]))
    keep = ~np.isin(old["frames"], new["frames"])
    frames = np.concatenate([old["frames"][keep], new["frames"]])
    order = np.argsort(frames, kind="stable")
    return {
        "frames": frames[order].astype(np.int32),
        "xy": np.concatenate([old["xy"][keep], new["xy"]])[order],
        "score": np.concatenate([old["score"][keep], new["score"]])[order],
        "bodyparts": list(new["bodyparts"]),
        "meta": dict(new["meta"]),
    }


def _write_atomic(dst: Path, d: dict) -> None:
    tmp = dst.with_suffix(".npz.tmp")
    np.savez_compressed(
        str(tmp), frames=d["frames"], xy=d["xy"], score=d["score"],
        bodyparts=np.asarray(d["bodyparts"], dtype=np.str_),
        meta=np.asarray(json.dumps(d["meta"]), dtype=np.str_))
    # savez appends .npz when the name lacks it; ours has it, so the file is
    # exactly `tmp`.
    Path(tmp).replace(dst)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd deeplabcut-webapp-docker && python3 -m pytest tests/test_peaks_emit.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
cd deeplabcut-webapp-docker
git add src/dlc/peaks_emit.py tests/test_peaks_emit.py
git commit -m "feat(inline): candidate-peak emitter module"
```

---

### Task 6: Main-webapp Celery task and route

**Files:**
- Modify: `deeplabcut-webapp-docker/src/dlc/tasks.py` (**append at the bottom only**)
- Modify: `deeplabcut-webapp-docker/src/dlc/inline_analysis.py` (append two routes)
- Test: `deeplabcut-webapp-docker/tests/test_inline_analysis_peaks_route.py`

**Interfaces:**
- Consumes: `dlc.peaks_emit.emit_peaks_for_video` from Task 5; the existing `_sec_check`, `_ctx.redis_client()`, `_user_id()` helpers in `inline_analysis.py`; the existing `_result_key(req_id)` / `inline:result:<req_id>` hash convention in `tasks.py`.
- Produces:
  - `POST /dlc/project/inline-analysis/peaks` → `202 {"req_id": str}`
  - `GET /dlc/project/inline-analysis/peaks/status?req_id=…` → `{"status": "pending"|"running"|"done"|"error", "n_frames": int, "error": str}`
  - `tasks.dlc_emit_peaks(video_paths, h5_paths, frames, model_dir, snapshot_name, req_id, k, min_distance)`

- [ ] **Step 1: Write the failing tests**

Create `deeplabcut-webapp-docker/tests/test_inline_analysis_peaks_route.py`:

```python
"""Route-level tests for the peak-emission endpoint.

Follows the fixture style of tests/test_inline_analysis_routes.py — open that
file and reuse its app/client fixture rather than building a second one.
"""
import json

import pytest


def test_submit_returns_a_req_id_and_queues_the_task(client, monkeypatch, tmp_video):
    sent = {}
    monkeypatch.setattr("dlc.inline_analysis._dispatch_emit_peaks",
                        lambda **kw: sent.update(kw))
    resp = client.post("/dlc/project/inline-analysis/peaks", json={
        "video_paths": [str(tmp_video)],
        "ranges": [{"start": 10, "n": 3}],
        "snapshot_path": "/models/trainset/train/snapshot-best-180.pt",
    })
    assert resp.status_code == 202
    assert resp.get_json()["req_id"]
    assert sent["frames"] == [10, 11, 12]
    assert sent["snapshot_name"] == "snapshot-best-180.pt"
    assert sent["model_dir"].endswith("/models/trainset")


def test_overlapping_ranges_are_deduped_and_sorted(client, monkeypatch, tmp_video):
    sent = {}
    monkeypatch.setattr("dlc.inline_analysis._dispatch_emit_peaks",
                        lambda **kw: sent.update(kw))
    client.post("/dlc/project/inline-analysis/peaks", json={
        "video_paths": [str(tmp_video)],
        "ranges": [{"start": 5, "n": 3}, {"start": 6, "n": 3}],
        "snapshot_path": "/models/trainset/train/snap.pt",
    })
    assert sent["frames"] == [5, 6, 7, 8]


def test_missing_video_paths_is_a_400(client):
    resp = client.post("/dlc/project/inline-analysis/peaks", json={
        "ranges": [{"start": 0, "n": 1}], "snapshot_path": "/m/train/s.pt"})
    assert resp.status_code == 400


def test_a_video_outside_the_data_root_is_a_403(client):
    resp = client.post("/dlc/project/inline-analysis/peaks", json={
        "video_paths": ["/etc/passwd"],
        "ranges": [{"start": 0, "n": 1}], "snapshot_path": "/m/train/s.pt"})
    assert resp.status_code == 403


def test_an_empty_range_list_is_a_400(client, tmp_video):
    resp = client.post("/dlc/project/inline-analysis/peaks", json={
        "video_paths": [str(tmp_video)], "ranges": [],
        "snapshot_path": "/m/train/s.pt"})
    assert resp.status_code == 400


def test_a_frame_budget_over_the_cap_is_a_400(client, tmp_video):
    resp = client.post("/dlc/project/inline-analysis/peaks", json={
        "video_paths": [str(tmp_video)],
        "ranges": [{"start": 0, "n": 50_001}],
        "snapshot_path": "/m/train/s.pt"})
    assert resp.status_code == 400
    assert "50000" in resp.get_json()["error"]


def test_status_reports_a_published_result(client, fake_redis):
    fake_redis.hset("inline:result:abc", mapping={
        "status": "done", "n_frames": "42", "error": ""})
    d = client.get("/dlc/project/inline-analysis/peaks/status?req_id=abc").get_json()
    assert d["status"] == "done" and d["n_frames"] == 42


def test_status_of_an_unknown_req_is_pending(client):
    d = client.get("/dlc/project/inline-analysis/peaks/status?req_id=nope").get_json()
    assert d["status"] == "pending"
```

Add whatever fixtures the existing inline-analysis route tests lack — a
`tmp_video` that creates a file under the configured data root, and a
`fake_redis`. Reuse the repo's existing FakeRedis rather than writing a new one.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd deeplabcut-webapp-docker && python3 -m pytest tests/test_inline_analysis_peaks_route.py -v`
Expected: FAIL — 404 on the new endpoints.

- [ ] **Step 3: Append the Celery task to `tasks.py`**

At the **very bottom** of `deeplabcut-webapp-docker/src/dlc/tasks.py`, below
`dlc_inline_session`. Do not touch anything above it:

```python
# --------------------------------------------------------------------------
# Candidate-peak emission. A SECOND, additive GPU pass fired by the "3D Inline
# Analysis - Reprojection" card after analysis completes. Deliberately separate
# from _run_range so the production inline-analysis path stays untouched.
# See deeplabcut-webapp-docker-supports/dlc-3D/docs/superpowers/specs/
#     2026-07-30-heatmap-peak-screen-design.md
# --------------------------------------------------------------------------

def _emit_peaks_inner(redis_, req_id, video_paths, h5_paths, frames,
                      model_dir, snapshot_name, k, min_distance):
    """Pure-function body, testable without Celery."""
    from .peaks_emit import emit_peaks_for_video

    _publish(redis_, req_id, status="running")
    total = 0
    for video, h5 in zip(video_paths, h5_paths):
        res = emit_peaks_for_video(
            video_path=video, h5_path=h5, model_dir=model_dir,
            snapshot_name=snapshot_name, frames=frames,
            k=k, min_distance=min_distance)
        total += int(res["n_frames"])
    _publish(redis_, req_id, status="done", n_frames=total)
    return total


@celery.task(bind=True, name="tasks.dlc_emit_peaks", acks_late=False)
def dlc_emit_peaks(self, req_id, video_paths, h5_paths, frames,
                   model_dir, snapshot_name, k=5, min_distance=3):
    redis_ = _redis_client()
    try:
        _emit_peaks_inner(redis_, req_id, video_paths, h5_paths, frames,
                          model_dir, snapshot_name, k, min_distance)
    except Exception as exc:                       # noqa: BLE001
        _publish(redis_, req_id, status="error", error=str(exc))
        raise
```

`_publish` and `_redis_client` are placeholders for whatever the file already
calls to write `inline:result:<req_id>` and obtain a client — read the existing
`_publish_result` helper near line 2925 and `dlc_inline_session` near line 3213
and use those exact names and signatures. If `_publish_result` does not accept an
`n_frames` field, extend its `mapping` with one rather than inventing a second
publisher; the field is additive and existing readers ignore unknown keys.

- [ ] **Step 4: Append the routes to `inline_analysis.py`**

```python
_PEAKS_FRAME_CAP = 50_000


def _frames_from_ranges(ranges):
    """Flatten [{start, n}, ...] into a sorted, deduped frame list."""
    out = set()
    for r in ranges:
        start, n = int(r["start"]), int(r["n"])
        if n <= 0:
            raise ValueError("each range needs n >= 1")
        out.update(range(start, start + n))
    return sorted(out)


def _dispatch_emit_peaks(**kw):
    """Seam for tests; production sends the task to the worker queue."""
    from ..tasks import dlc_emit_peaks
    dlc_emit_peaks.delay(**kw)


@bp.route("/dlc/project/inline-analysis/peaks", methods=["POST"])
def peaks_submit():
    """Queue a candidate-peak pass over frames already analysed.

    Additive: this never runs as part of an analysis and never touches the pose
    h5. A failure here leaves the analysis results exactly as they were.
    """
    body = request.get_json(silent=True) or {}
    video_paths = body.get("video_paths") or []
    ranges = body.get("ranges") or []
    snapshot_path = (body.get("snapshot_path") or "").strip()
    if not video_paths or not snapshot_path:
        return jsonify({"error": "video_paths and snapshot_path required"}), 400
    if not ranges:
        return jsonify({"error": "at least one range required"}), 400

    resolved = []
    for raw in video_paths:
        p = Path(str(raw))
        if not p.is_file():
            return jsonify({"error": f"video not found: {raw}"}), 400
        if not _sec_check(p):
            return jsonify({"error": "video path is outside the data root"}), 403
        resolved.append(p)

    try:
        frames = _frames_from_ranges(ranges)
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": f"bad ranges: {exc}"}), 400
    if len(frames) > _PEAKS_FRAME_CAP:
        return jsonify({
            "error": f"{len(frames)} frames exceeds the cap of {_PEAKS_FRAME_CAP}"
        }), 400

    snap = Path(snapshot_path)
    model_dir = str(snap.parent.parent)
    scorer = _scorer_for_snapshot(snapshot_path)
    h5_paths = [str(_resolve_h5_path(str(p), scorer)) for p in resolved]

    req_id = uuid.uuid4().hex
    _dispatch_emit_peaks(
        req_id=req_id, video_paths=[str(p) for p in resolved],
        h5_paths=h5_paths, frames=frames, model_dir=model_dir,
        snapshot_name=snap.name,
        k=int(body.get("k", 5)), min_distance=int(body.get("min_distance", 3)))
    return jsonify({"req_id": req_id}), 202


@bp.route("/dlc/project/inline-analysis/peaks/status", methods=["GET"])
def peaks_status():
    req_id = (request.args.get("req_id") or "").strip()
    if not req_id:
        return jsonify({"error": "req_id required"}), 400
    raw = _ctx.redis_client().hgetall(f"inline:result:{req_id}") or {}
    d = {(k.decode() if isinstance(k, bytes) else k):
         (v.decode() if isinstance(v, bytes) else v) for k, v in raw.items()}
    if not d:
        return jsonify({"status": "pending", "n_frames": 0, "error": ""})
    return jsonify({
        "status": d.get("status", "pending"),
        "n_frames": int(d.get("n_frames") or 0),
        "error": d.get("error", ""),
    })
```

`_scorer_for_snapshot` and `_resolve_h5_path` are the names this plan assumes for
deriving the pose h5 that the sidecar must sit beside. `_resolve_h5_path` already
exists in `tasks.py` (used by `_run_range` at line 3032) — import it rather than
reimplementing. Find how the existing code derives the scorer string from a
snapshot for `_run_range` and reuse that exact mechanism. **If the scorer cannot
be derived in the request context, do it inside the task instead and pass
`video_paths` + `snapshot_path` only** — the sidecar path must match the pose h5
the analysis actually wrote, and guessing it wrong puts the sidecar somewhere the
engine will never look.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd deeplabcut-webapp-docker && python3 -m pytest tests/test_inline_analysis_peaks_route.py -v`
Expected: PASS.

- [ ] **Step 6: Verify the production path is untouched**

Run: `cd deeplabcut-webapp-docker && git diff --stat src/dlc/tasks.py`
Expected: additions only, all at the end of the file. Then:

```bash
cd deeplabcut-webapp-docker
git diff -U0 src/dlc/tasks.py | grep '^-' | grep -v '^---'
```
Expected: **no output**. Any removed line means `_run_range` or another existing
function was edited — revert it.

Run the inline-analysis regression suite:
`python3 -m pytest tests/test_inline_analysis_routes.py tests/test_inline_analysis_session_lifecycle.py tests/test_inline_analysis_ui_isolation.py -q`
Expected: PASS, unchanged from baseline.

- [ ] **Step 7: Commit**

```bash
cd deeplabcut-webapp-docker
git add src/dlc/tasks.py src/dlc/inline_analysis.py tests/test_inline_analysis_peaks_route.py
git commit -m "feat(inline): additive peak-emission task and route"
```

---

### Task 7: Card markup and help entries

**Files:**
- Modify: `dlc-3D/src/static/card_inline_analysis_3d_reprojection.html` (~line 446 for the tag row; ~line 1005 for the params row)
- Modify: `dlc-3D/src/static/internal/reproj_help.mjs`
- Test: `dlc-3D/tests/test_reproj_panel_markup.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: element ids `ia3dr-emit-peaks`, `ia3dr-reproj-require-peaks`, `ia3dr-reproj-peak-floor`; `HELP` keys `require_peaks` and `peak_floor`.

- [ ] **Step 1: Write the failing tests**

Append to `dlc-3D/tests/test_reproj_panel_markup.py`:

```python
def test_emit_peaks_checkbox_sits_in_the_tag_row_and_defaults_on(card_html):
    i = card_html.index('id="ia3dr-emit-peaks"')
    j = card_html.index('id="ia3dr-btn-analyze-tag"')
    assert abs(i - j) < 1200, "emit-peaks must sit beside Analyze for tag"
    tag = card_html[card_html.rindex("<input", 0, i):card_html.index(">", i) + 1]
    assert "checkbox" in tag and "checked" in tag


def test_require_peaks_checkbox_defaults_off_and_carries_help(card_html):
    i = card_html.index('id="ia3dr-reproj-require-peaks"')
    tag = card_html[card_html.rindex("<input", 0, i):card_html.index(">", i) + 1]
    assert "checkbox" in tag
    assert "checked" not in tag, "the screen must be opt-in"
    assert 'data-help="require_peaks"' in tag


def test_peak_floor_field_has_the_specified_bounds_and_default(card_html):
    i = card_html.index('id="ia3dr-reproj-peak-floor"')
    tag = card_html[card_html.rindex("<input", 0, i):card_html.index(">", i) + 1]
    for want in ('type="number"', 'min="0"', 'max="1"',
                 'step="0.01"', 'value="0.05"', 'data-help="peak_floor"'):
        assert want in tag, f"{want} missing from {tag}"


def test_extraction_parameters_are_not_exposed(card_html):
    for absent in ("ia3dr-reproj-peak-k", "ia3dr-reproj-peak-min-distance"):
        assert absent not in card_html


def test_the_new_help_keys_exist():
    from pathlib import Path
    src = Path("src/static/internal/reproj_help.mjs").read_text()
    for key in ("require_peaks:", "peak_floor:"):
        assert key in src
```

Use the module's existing `card_html` fixture. If `test_reproj_panel_markup.py`
reads the file inline instead, follow that pattern rather than adding a fixture.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_markup.py -v -k "peak"`
Expected: FAIL — `ValueError: substring not found`.

- [ ] **Step 3: Add the tag-row checkbox**

In `card_inline_analysis_3d_reprojection.html`, immediately before the
`ia3dr-btn-analyze-tag` button:

```html
              <label class="ia3dr-tag-lock-label" title="After analysis, run a second GPU pass that saves DeepLabCut's candidate heatmap peaks beside each pose h5 (~50 s per 2000 frames). Required by 'Require peak evidence'.">
                <input type="checkbox" id="ia3dr-emit-peaks" checked style="accent-color:var(--accent);width:14px;height:14px"/>
                emit peaks
              </label>
```

- [ ] **Step 4: Add the params-panel controls**

In the `ia3dr-ctrl-row` that holds `ia3dr-reproj-show-lines`, after the
`min likelihood` label:

```html
          <label class="ia3dr-inline-check">
            <input type="checkbox" id="ia3dr-reproj-require-peaks"
                   data-help="require_peaks">
            Require peak evidence
          </label>
          <label class="ia3dr-inline-check">
            peak score floor
            <input type="number" id="ia3dr-reproj-peak-floor"
                   min="0" max="1" step="0.01" value="0.05"
                   data-help="peak_floor">
          </label>
```

- [ ] **Step 5: Add the two HELP entries**

In `reproj_help.mjs`, inside the exported `HELP` object:

```js
  require_peaks: {
    title: "Require peak evidence",
    body:
      "Refuses a rescue unless exactly one of DeepLabCut's candidate heatmap " +
      "peaks sits on the epipolar line. It can only REFUSE — no marker is ever " +
      "moved. Needs a peaks sidecar, which 'emit peaks' writes during " +
      "Analyze-for-tag; frames without one keep their geometry verdict rather " +
      "than being refused.",
    example:
      "On the validation run, 4,031 of 15,191 judged cells had SEVERAL peaks " +
      "on the line and 1,028 had the wrong one — 33% of refusals that geometry " +
      "alone cannot make at any threshold.",
  },
  peak_floor: {
    title: "Peak score floor",
    body:
      "A peak below this heatmap score does not count as evidence. Too high " +
      "and this degenerates into rescue_floor; too low and a hallucinated peak " +
      "passes. Same 0–1 scale as likelihood.",
    example:
      "The 0.05 default is UNVALIDATED — there is no labelled measurement " +
      "behind it. Under occlusion DeepLabCut typically scores below 0.10, so " +
      "raising it toward 0.10 refuses more and rescues less.",
  },
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_markup.py -v`
Expected: PASS. The existing cross-file guard that every `data-help` has a `HELP`
entry must also still pass — run the whole file, not just the new tests.

- [ ] **Step 7: Commit**

```bash
git add dlc-3D/src/static/card_inline_analysis_3d_reprojection.html \
        dlc-3D/src/static/internal/reproj_help.mjs \
        dlc-3D/tests/test_reproj_panel_markup.py
git commit -m "feat(dlc-3d): peak-screen controls and help entries on the reprojection card"
```

---

### Task 8: Card wiring

**Files:**
- Modify: `dlc-3D/src/static/inline_analysis_3d_reprojection.js` — `_onAnalyzeTagClick` (~2979), `_reprojEl` (~3608), `_reprojSaveParams` (~3682), `_reprojLoadParams` (~3703), the run-payload builder, and the change-listener registration (~3928)
- Test: `dlc-3D/tests/test_reproj_panel_wiring.py` (append)

**Interfaces:**
- Consumes: `POST /dlc/project/inline-analysis/peaks` and its status endpoint (Task 6); `GET /reproject/peaks-status` (Task 4); `summary.peak_screen` (Task 3).
- Produces: no new exported symbols; these are internal card functions.

- [ ] **Step 1: Write the failing tests**

Append to `dlc-3D/tests/test_reproj_panel_wiring.py`:

```python
def test_analyze_for_tag_posts_to_the_peaks_endpoint(card_js):
    assert "/dlc/project/inline-analysis/peaks" in card_js


def test_the_peaks_pass_is_gated_on_the_checkbox(card_js):
    i = card_js.index("/dlc/project/inline-analysis/peaks")
    window = card_js[max(0, i - 2500):i]
    assert "ia3dr-emit-peaks" in window, \
        "the peaks POST must be guarded by the emit-peaks checkbox"


def test_the_peaks_pass_runs_after_the_analysis_polls_resolve(card_js):
    body = card_js[card_js.index("async function _onAnalyzeTagClick"):]
    body = body[:body.index("\n}\n")]
    assert body.index("_pollReq") < body.index("_reprojEmitPeaks"), \
        "peaks must be emitted only after both cameras finish"


def test_the_run_payload_carries_the_screen_parameters(card_js):
    i = card_js.index('"/reproject/run"')
    window = card_js[i:i + 2500]
    assert "require_peaks" in window and "peak_score_floor" in window


def test_the_screen_params_round_trip_through_reproj_params(card_js):
    save = card_js[card_js.index("function _reprojSaveParams"):]
    save = save[:save.index("\n}\n")]
    assert "emit_peaks" in save and "require_peaks" in save and "peak_floor" in save
    load = card_js[card_js.index("async function _reprojLoadParams"):]
    load = load[:load.index("\n}\n")]
    assert "emit_peaks" in load and "require_peaks" in load and "peak_floor" in load


def test_the_require_peaks_checkbox_is_gated_on_sidecar_presence(card_js):
    assert "/reproject/peaks-status" in card_js
    i = card_js.index("/reproject/peaks-status")
    window = card_js[i:i + 2000]
    assert "disabled" in window, \
        "require-peaks must be disabled when no sidecar is present"


def test_the_audit_surfaces_the_screen_coverage(card_js):
    assert "peak_screen" in card_js
```

Reuse the module's existing `card_js` fixture.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_wiring.py -v -k "peak"`
Expected: FAIL — `ValueError: substring not found`.

- [ ] **Step 3: Add the emit helper and call it from `_onAnalyzeTagClick`**

Add above `_onAnalyzeTagClick`:

```js
// Fire the candidate-peak pass over the same ranges the analysis just covered.
// Additive and best-effort: the pose h5 is already written, so a failure here
// costs the screen, not the analysis. Never awaited for correctness of the run.
async function _reprojEmitPeaks(videoPaths, ranges) {
  const lastRun = _ia3drEl.lastRun();
  try {
    const r = await fetch("/dlc/project/inline-analysis/peaks", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        video_paths: videoPaths,
        ranges: ranges.map((x) => ({ start: x.start, n: x.n })),
        snapshot_path: _ia3drEl.snapSel()?.value || "",
      }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.req_id) {
      if (lastRun) lastRun.textContent += `  (peaks failed: ${d.error || r.status})`;
      return;
    }
    if (lastRun) lastRun.textContent += "  emitting peaks…";
    const res = await _pollPeaksReq(d.req_id);
    if (lastRun) {
      lastRun.textContent += res.status === "done"
        ? `  peaks: ${res.n_frames} frames.`
        : `  peaks failed: ${res.error || res.status}`;
    }
    await _reprojRefreshPeaksAvailability();
  } catch (e) {
    if (lastRun) lastRun.textContent += `  (peaks failed: ${e})`;
  }
}

// Mirrors _pollReq's setInterval + _activePolls pattern against the peaks
// status endpoint. 15 min cap: a large tag run is minutes of GPU.
function _pollPeaksReq(reqId) {
  return new Promise((resolve) => {
    let elapsedMs = 0;
    const MAX_MS = 15 * 60 * 1000;
    const t = setInterval(async () => {
      elapsedMs += 1000;
      if (elapsedMs >= MAX_MS) {
        clearInterval(t); _activePolls.delete(t);
        resolve({ status: "error", error: "timed out waiting for peaks" });
        return;
      }
      try {
        const r = await fetch(
          `/dlc/project/inline-analysis/peaks/status?req_id=${reqId}`);
        if (!r.ok) return;
        const d = await r.json();
        if (d.status === "done" || d.status === "error") {
          clearInterval(t); _activePolls.delete(t); resolve(d);
        }
      } catch (_) { /* transient; keep polling until the cap */ }
    }, 1000);
    _activePolls.add(t);
  });
}
```

In `_onAnalyzeTagClick`, after the `const results = await Promise.all(...)` line
and its error handling, before the post-analysis refresh block:

```js
  if ($("ia3dr-emit-peaks")?.checked) {
    await _reprojEmitPeaks([cam0, _siblingPath], ranges);
  }
```

Confirm `_activePolls` is the exact name used by `_pollReq` in this file before
reusing it.

- [ ] **Step 4: Add the availability refresh**

```js
// Enable "Require peak evidence" only when a sidecar actually exists. A screen
// with nothing to screen with would be silently inert, which reads as a bug.
async function _reprojRefreshPeaksAvailability() {
  const box = $("ia3dr-reproj-require-peaks");
  if (!box) return;
  const refH5 = _reprojEl.refH5?.() || null;
  const tgtH5 = _reprojEl.tgtH5?.() || null;
  if (!refH5 || !tgtH5) {
    box.disabled = true;
    box.title = "load a camera pair first";
    return;
  }
  try {
    const q = `ref_h5=${encodeURIComponent(refH5)}&tgt_h5=${encodeURIComponent(tgtH5)}`;
    const d = await (await fetch(`/reproject/peaks-status?${q}`)).json();
    const any = !!(d?.ref?.present || d?.tgt?.present);
    box.disabled = !any;
    box.title = any
      ? `peaks available (ref ${d.ref.frames || 0}, tgt ${d.tgt.frames || 0} frames)`
      : "no peaks sidecar for this pair — tick 'emit peaks' and run Analyze for tag";
    if (!any) box.checked = false;
  } catch (_) {
    box.disabled = true;
    box.title = "could not check for a peaks sidecar";
  }
}
```

Call it from wherever the card already resolves the h5 pair for `/reproject/run`
— find how `ref_h5`/`tgt_h5` are obtained for that payload and use the same
source, adding `refH5`/`tgtH5` accessors to `_reprojEl` if they do not exist.

- [ ] **Step 5: Send and persist the new parameters**

In the `/reproject/run` payload builder:

```js
    require_peaks: !!$("ia3dr-reproj-require-peaks")?.checked,
    peak_score_floor: parseFloat($("ia3dr-reproj-peak-floor")?.value) || 0.05,
```

In `_reprojEl`:

```js
  requirePeaks: () => document.getElementById("ia3dr-reproj-require-peaks"),
  peakFloor:    () => document.getElementById("ia3dr-reproj-peak-floor"),
  emitPeaks:    () => document.getElementById("ia3dr-emit-peaks"),
```

In `_reprojSaveParams`'s `prefs`:

```js
    emit_peaks: !!_reprojEl.emitPeaks()?.checked,
    require_peaks: !!_reprojEl.requirePeaks()?.checked,
    peak_floor: parseFloat(_reprojEl.peakFloor()?.value),
```

In `_reprojLoadParams`, after `setNum(_reprojEl.lineLik(), prefs.line_lik);`:

```js
    setNum(_reprojEl.peakFloor(), prefs.peak_floor);
    // Checkboxes: only apply a stored value when one was actually stored, so a
    // params blob written before this feature keeps the markup defaults.
    if (typeof prefs.emit_peaks === "boolean" && _reprojEl.emitPeaks()) {
      _reprojEl.emitPeaks().checked = prefs.emit_peaks;
    }
    if (typeof prefs.require_peaks === "boolean" && _reprojEl.requirePeaks()) {
      _reprojEl.requirePeaks().checked = prefs.require_peaks;
    }
```

Register the three controls with the existing change-listener loop near line
3928 so edits persist.

- [ ] **Step 6: Surface the coverage in the results**

Where the run summary is rendered into `ia3dr-reproj-status`, append:

```js
  // Refusing rescues makes the marker count go DOWN versus a geometry-only run.
  // That is the feature working; this line is what distinguishes it from a
  // fault, which this project has twice misdiagnosed when output got sparser.
  const scr = summary.peak_screen;
  if (scr) {
    statusEl.textContent +=
      `  peak screen: ${scr.covered}/${scr.rescues} rescues covered, ` +
      `${scr.refused} refused (${scr.ambiguous} ambiguous, ` +
      `${scr.no_evidence} no evidence, ${scr.corrected} wrong peak).`;
  }
```

Use the actual variable names the render function already uses for the summary
object and the status element.

- [ ] **Step 7: Syntax-check and run the tests**

```bash
cd dlc-3D
node --check src/static/inline_analysis_3d_reprojection.js
python3 -m pytest tests/test_reproj_panel_wiring.py tests/test_reproj_card_namespace.py \
                  tests/test_inline_analysis_3d_ui_isolation.py -v
```
Expected: PASS. `node --check` catches syntax errors but **not** a missing
import or a misspelt helper — grep for every new identifier you referenced
(`_activePolls`, `_ia3drEl.snapSel`, `_reprojEl.refH5`) and confirm each is
defined in this file.

- [ ] **Step 8: Commit**

```bash
git add dlc-3D/src/static/inline_analysis_3d_reprojection.js \
        dlc-3D/tests/test_reproj_panel_wiring.py
git commit -m "feat(dlc-3d): wire peak emission and the screen into the reprojection card"
```

---

### Task 9: Duplication guard and documentation

**Files:**
- Create: `dlc-3D/tests/test_peaks_emit_parity.py`
- Modify: `dlc-3D/docs/reprojection-parameters.md`
- Modify: `dlc-3D/docs/regression-catalog.md`

**Interfaces:**
- Consumes: `dlc_3d_bp/peaks.py` (Task 5's copy source) and `deeplabcut-webapp-docker/src/dlc/peaks_emit.py` (Task 5).
- Produces: nothing importable.

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/test_peaks_emit_parity.py`:

```python
"""The main webapp carries a verbatim copy of two peak functions.

The repositories build separate containers, so a shared import would need a
cross-repo bind mount. The copy is deliberate; this test is what stops it
drifting into two subtly different implementations of one measured pipeline.
"""
import ast
import textwrap
from pathlib import Path

import pytest

_MAIN = Path(__file__).resolve().parents[3] / \
    "deeplabcut-webapp-docker/src/dlc/peaks_emit.py"
_OURS = Path(__file__).resolve().parents[1] / "src/dlc_3d_bp/peaks.py"


def _source_of(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return textwrap.dedent(ast.get_source_segment(path.read_text(), node))
    raise AssertionError(f"{name} not found in {path}")


@pytest.mark.skipif(not _MAIN.is_file(),
                    reason="main webapp checkout not present beside this repo")
@pytest.mark.parametrize("name", ["extract_peaks", "heatmap_to_image"])
def test_the_copied_functions_are_identical(name):
    assert _source_of(_MAIN, name) == _source_of(_OURS, name), (
        f"{name} has drifted between dlc_3d_bp/peaks.py and dlc/peaks_emit.py. "
        "These are one measured pipeline in two files — change both.")


@pytest.mark.skipif(not _MAIN.is_file(), reason="main webapp checkout not present")
def test_the_five_measured_constants_survived_the_port():
    src = _MAIN.read_text()
    for want in ("0.485", "0.456", "0.406", "0.229", "0.224", "0.225",
                 "_STRIDE = 2.0", "7.2801",
                 'out["bodypart"]["heatmap"]', 'out["bodypart"]["locref"]'):
        assert want in src, f"{want} missing — the verified pipeline was altered"


@pytest.mark.skipif(not _MAIN.is_file(), reason="main webapp checkout not present")
def test_the_emitter_does_not_resize_the_frame():
    """Resizing to 448x448 produced 427 px median error. It must not reappear."""
    assert "cv2.resize" not in _MAIN.read_text()


@pytest.mark.skipif(not _MAIN.is_file(), reason="main webapp checkout not present")
def test_the_sidecar_path_rule_matches_on_both_sides():
    assert '"_peaks.npz"' in _MAIN.read_text()
    assert '"_peaks.npz"' in _OURS.parent.joinpath("peaks_io.py").read_text()
```

Verify `parents[3]` actually resolves to `/home/sam/docker-images` from
`dlc-3D/tests/`; adjust the index if the nesting differs.

- [ ] **Step 2: Run the test to verify it fails, then passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_peaks_emit_parity.py -v`

If it FAILS on the parity assertion, the Task 5 copy is not verbatim — fix the
copy, not the test. If it fails on the path resolution, fix the path. Once the
copy is genuinely verbatim: PASS.

Then prove the guard actually bites:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
sed -i 's/min_distance: int = 3/min_distance: int = 4/' src/dlc/peaks_emit.py
cd ../deeplabcut-webapp-docker-supports/dlc-3D && python3 -m pytest tests/test_peaks_emit_parity.py -q
```
Expected: FAIL. Then revert with `cd ../../deeplabcut-webapp-docker && git checkout src/dlc/peaks_emit.py`
and confirm it passes again. **A guard test that cannot fail is not a guard** —
this project has already shipped one that silently validated nothing.

- [ ] **Step 3: Document the parameters**

Append a section to `dlc-3D/docs/reprojection-parameters.md` covering
`require_peaks` and `peak_floor`, matching the file's existing per-parameter
format and repeating the same measured examples used in the `HELP` entries — the
help module's header states the two must be updated together.

State explicitly that the 0.05 default is unvalidated, and that a cell with no
sidecar coverage keeps its geometry verdict.

- [ ] **Step 4: Add the regression entries**

Append to `dlc-3D/docs/regression-catalog.md`:

```markdown
## Candidate-peak screen

- **Sidecar path must match on both sides.** `dlc/peaks_emit.py` (main webapp)
  writes it and `dlc_3d_bp/peaks_io.py` reads it. The rule is
  `<pose_h5_stem>_peaks.npz`. A mismatch is silent: the screen simply finds
  nothing and every rescue stands. Guarded by `test_peaks_emit_parity.py`.
- **Absence of peaks is not absence of evidence.** An uncovered frame keeps its
  geometry verdict. Treating absence as `NO_EVIDENCE` would void every rescue in
  every analysis predating the feature.
- **The screen only downgrades `RESCUE`.** Widening it to `CONFIRM` would let
  heatmap noise delete confident markers.
- **Refused rescues make output sparser.** That is the feature working. The audit
  coverage line is what distinguishes it from a fault — this project has twice
  diagnosed a working change as broken because output got sparser.
- **`_run_range` must never gain peak emission.** It is the production inline-3D
  card's inference path. Verify with
  `git diff -U0 src/dlc/tasks.py | grep '^-' | grep -v '^---'` returning nothing.
- **The inference pipeline's five constants are measured, not chosen.** Native
  resolution (never resized), ImageNet normalisation, nested output keys,
  `STRIDE = 2.0`, and locref refinement. Getting any one wrong gave 186–427 px.
```

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/tests/test_peaks_emit_parity.py \
        dlc-3D/docs/reprojection-parameters.md dlc-3D/docs/regression-catalog.md
git commit -m "test(dlc-3d): guard the peak-emitter copy; document the screen"
```

---

## Deployment (after all tasks pass review)

Not a task — the operational steps, recorded so they are not improvised.

1. **`docker compose up -d` is a NO-OP without a config change.** Use
   `docker compose restart dlc-3d` for dlc-3D source changes (bind-mounted), and
   `docker compose restart worker` for `src/dlc/tasks.py` and
   `src/dlc/peaks_emit.py`.
2. **`src/static/` and `src/dlc_3d_bp/` are bind mounts onto the host checkout.**
   A `docker cp` into `/app/static` or `/app/dlc_3d_bp` writes through into the
   repository. Never deploy that way.
3. **Restarting the worker mid-session leaves a stale `inline:session` hash**,
   which hangs the next inline run. Delete the session and queue keys to recover.
4. **Never use `/reproject/run` as a health probe** — it writes
   `_reprojected.h5` for both cameras and will overwrite the user's files.
   Use `/reproject/thresholds` or `/reproject/peaks-status`, which write nothing.
5. **Verify the port on the deployed container** by re-running the 0.344 px
   comparison: emit peaks for a range that already has confident markers in its
   pose h5, and confirm peak 0 agrees with the h5 marker to well under 1 px. This
   is the check that host tests cannot perform, and the one that would catch a
   preprocessing regression.

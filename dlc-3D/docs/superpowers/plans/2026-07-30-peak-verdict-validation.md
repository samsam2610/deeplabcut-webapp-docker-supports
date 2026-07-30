# Peak-Verdict Validation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure, against human labels on 13 paired sessions, whether peak-based correction beats DeepLabCut's own low-confidence markers — and whether occlusion is correctly refused.

**Architecture:** The verdict rule is a pure function, unit-tested on the host. A loader reads a labelled session (labels, calibration, image pairs) with no model involved, also host-tested. A runner executes the model over the labelled PNGs on GPU and scores the result. No production code is touched: this plan answers a question, it does not ship a feature.

**Tech Stack:** numpy, `scipy.ndimage`, DeepLabCut 3.0.0rc14, pytest.

## This plan is a gate, not a feature

Nothing here changes `epipolar_core.py`, `reprojection.py`, `routes.py`, or any
static asset. It produces two numbers that decide whether the engine change is
built at all:

- **Correction accuracy** — do corrected markers land closer to the human label
  than DeepLabCut's originals? The baseline to beat is a **22.6 px** median.
- **Occlusion recall** — where the annotator left a part unlabelled, do we return
  `NO_EVIDENCE` rather than rescuing?

**If corrections do not reduce the median distance on held-out sessions, report
that plainly. Do not tune until it passes.** A negative result here is a
successful outcome of this plan and saves building something that does not work.

## Global Constraints

- **`labeled-data/` is READ-ONLY.** It holds the human annotations the model was
  trained on — the least reproducible asset in the project. Never write, move,
  rename or reorganise anything under the DLC project: `labeled-data/**`,
  `training-datasets/**`, `dlc-models-pytorch/**`, `config.yaml`. Snapshots are
  loaded, never written. All output goes to an explicit `--out-dir`.
- **Never write into the session data** under `/user-data/Parra-Data/Cloud/Reaching-Task-Data/`.
- **Only `deeplabcut-webapp-docker-worker-1` has DeepLabCut.** Anything importing it runs there via `docker exec`.
- **Pure modules import only `numpy` and `scipy.ndimage`** so they test on the host (Python 3.9), where there is no torch and no DLC.
- Python 3.9-compatible syntax. Quote any `X | Y` annotation.
- **GPU:** use `--device cuda:1`. Inside the worker container `cuda:1` is the RTX 5090 (the project's DLC GPU); `cuda:0` is the RTX PRO 6000, reserved for LLM work. The container's CUDA order is REVERSED relative to host `nvidia-smi`.
- **Do NOT restart, rebuild or stop any container.** `docker cp` into `/tmp` only — never into `/app/dlc_3d_bp` or `/app/static`, which are bind mounts onto the host checkout.
- **Clean up:** remove everything copied into the container's `/tmp` when done, and verify the GPU is released with `nvidia-smi`.
- Ten tests fail on this host for unrelated pre-existing reasons; the two playwright e2e tests are flaky, so a run shows 9–11 failures. Compare failure NAMES, never counts.
- Run pytest from `dlc-3D/`.

## Established facts

- Inference pipeline, verified to 0.47 px: **native resolution padded to a multiple of 32** (never resized), ImageNet mean/std normalisation, model output nested at `out["bodypart"]["heatmap"]` and `["locref"]`, stride exactly **2**, `locref_std` **7.2801**. Throughput ~42 fps on the 5090.
- Snapshot: `/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07/dlc-models-pytorch/iteration-22/DREADDJan7-trainset70shuffle1/train/snapshot-best-180.pt`
- Labelled root: `/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07/labeled-data`
- 13 paired sessions, 1,104 frame-pairs, 1,072 with ≥5 labels in both cameras, 10 distinct calibrations, all images 800×600.
- Image naming: `img_cam{C}_{seq}_{videoframe}.png`. Each session folder holds `CollectedData_*.h5` and its own `calibration.toml`.
- Existing Phase 1 API: `extract_peaks(heatmap, k=5, min_distance=3) -> (xy_cells, scores)` and `heatmap_to_image(xy_cells, stride, pad_xy, scale_xy) -> xy_px`, both in `src/dlc_3d_bp/peaks.py`.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/dlc_3d_bp/peak_verdict.py` | **New.** Pure verdict rule. numpy only. |
| `tests/test_peak_verdict.py` | **New.** Host unit tests for the rule. |
| `src/dlc_3d_bp/labelled_session.py` | **New.** Reads a labelled session. numpy/pandas, no model. |
| `tests/test_labelled_session.py` | **New.** Host tests using a synthetic session. |
| `scripts/validate_peak_verdict.py` | **New.** GPU runner + scorer. |

---

### Task 1: The verdict rule

**Files:**
- Create: `src/dlc_3d_bp/peak_verdict.py`
- Test: `tests/test_peak_verdict.py`

**Interfaces:**
- Consumes: nothing.
- Produces: constants `NO_EVIDENCE = 6`, `CORRECTED = 7` (extending the existing 0–5 set), and `peak_verdict(peak_dists, peak_scores, t_ok, score_floor) -> (verdict, chosen_index)` where `chosen_index` is `None` unless the verdict is `RESCUE` or `CORRECTED`.

**The discriminability principle:** more than one qualifying peak means the
epipolar constraint identified nothing, so the honest answer is to decline. That
is what separates this from the current rule, which accepts any marker that
happens to lie in the band.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_peak_verdict.py
import numpy as np

from dlc_3d_bp.peak_verdict import CORRECTED, NO_EVIDENCE, peak_verdict

# Existing verdict codes, re-declared here so this test does not depend on
# epipolar_core (which pulls in cv2).
RESCUE = 2
AMBIGUOUS = 5


def test_no_peak_near_the_line_is_no_evidence():
    """The occlusion answer: the image supports nothing on this line."""
    d = np.array([40.0, 55.0, np.nan, np.nan, np.nan])
    s = np.array([0.8, 0.5, 0.0, 0.0, 0.0])
    assert peak_verdict(d, s, t_ok=5.0, score_floor=0.1) == (NO_EVIDENCE, None)


def test_only_the_argmax_qualifies_is_a_rescue():
    d = np.array([1.2, 40.0, np.nan, np.nan, np.nan])
    s = np.array([0.7, 0.6, 0.0, 0.0, 0.0])
    assert peak_verdict(d, s, t_ok=5.0, score_floor=0.1) == (RESCUE, 0)


def test_a_different_peak_qualifies_is_a_correction():
    """DLC's argmax is off the line but a secondary detection sits on it."""
    d = np.array([38.0, 1.1, np.nan, np.nan, np.nan])
    s = np.array([0.30, 0.22, 0.0, 0.0, 0.0])
    assert peak_verdict(d, s, t_ok=5.0, score_floor=0.1) == (CORRECTED, 1)


def test_two_qualifying_peaks_is_ambiguous():
    """The adjacent-digit case: if two candidates both satisfy the line, the
    geometry has discriminated nothing."""
    d = np.array([1.0, 2.0, np.nan, np.nan, np.nan])
    s = np.array([0.5, 0.45, 0.0, 0.0, 0.0])
    assert peak_verdict(d, s, t_ok=5.0, score_floor=0.1) == (AMBIGUOUS, None)


def test_a_peak_below_the_score_floor_does_not_qualify():
    """A near-zero-score peak is noise, not evidence, however well it lines up."""
    d = np.array([0.5, 40.0, np.nan, np.nan, np.nan])
    s = np.array([0.02, 0.6, 0.0, 0.0, 0.0])
    assert peak_verdict(d, s, t_ok=5.0, score_floor=0.1) == (NO_EVIDENCE, None)


def test_padding_never_qualifies():
    """NaN-distance / zero-score padding must not be mistaken for a candidate."""
    d = np.full(5, np.nan)
    s = np.zeros(5)
    assert peak_verdict(d, s, t_ok=5.0, score_floor=0.0) == (NO_EVIDENCE, None)


def test_correction_prefers_the_highest_scoring_qualifier_when_alone():
    d = np.array([30.0, 1.0, 31.0, np.nan, np.nan])
    s = np.array([0.9, 0.4, 0.3, 0.0, 0.0])
    assert peak_verdict(d, s, t_ok=5.0, score_floor=0.1) == (CORRECTED, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_peak_verdict.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dlc_3d_bp.peak_verdict'`

- [ ] **Step 3: Write the implementation**

```python
# src/dlc_3d_bp/peak_verdict.py
"""Verdict for one bodypart, given DeepLabCut's candidate peaks and the epipolar
line induced by the trusted camera.

The change from the geometry-only rule: instead of asking whether the marker is
CONSISTENT with the line, ask whether the image contains evidence that IDENTIFIES
this part on it. Those differ exactly when several detections satisfy the line —
the adjacent-digit case — and when none do, which is occlusion.

Imports numpy only, so this is testable on the host.
"""
from __future__ import annotations

import numpy as np

# Extends the 0-5 codes in epipolar_core. Declared here rather than imported
# because epipolar_core pulls in cv2, which the pure tests avoid.
RESCUE = 2
AMBIGUOUS = 5
NO_EVIDENCE = 6
CORRECTED = 7


def peak_verdict(peak_dists, peak_scores, t_ok: float, score_floor: float):
    """Decide from the candidate peaks alone.

    peak_dists  -- (K,) distance of each peak to the epipolar line, NaN padded
    peak_scores -- (K,) heatmap score per peak, 0 padded
    Index 0 is DeepLabCut's own argmax, i.e. the marker already in the pose h5.

    Returns (verdict, chosen_index). chosen_index is None unless the verdict is
    RESCUE (index 0) or CORRECTED (the qualifying peak).
    """
    d = np.asarray(peak_dists, dtype=float)
    s = np.asarray(peak_scores, dtype=float)
    qualifies = np.isfinite(d) & (d <= float(t_ok)) & (s >= float(score_floor))
    idx = np.flatnonzero(qualifies)

    if idx.size == 0:
        # Nothing the detector found sits on the line: the image does not
        # support this part being anywhere along it.
        return NO_EVIDENCE, None
    if idx.size > 1:
        # Several detections satisfy the line, so it has identified none of
        # them. Declining is the honest answer.
        return AMBIGUOUS, None
    only = int(idx[0])
    return (RESCUE, 0) if only == 0 else (CORRECTED, only)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_peak_verdict.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/peak_verdict.py dlc-3D/tests/test_peak_verdict.py
git commit -m "feat(peaks): verdict rule over candidate peaks"
```

---

### Task 2: Read a labelled session

**Files:**
- Create: `src/dlc_3d_bp/labelled_session.py`
- Test: `tests/test_labelled_session.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `load_labelled_session(session_dir) -> dict` with keys `bodyparts` (list of names), `calibration_path` (str), and `pairs` — a list of `{"frame": int, "cam0_image": str, "cam1_image": str, "cam0_xy": (B,2) array, "cam1_xy": (B,2) array}` where unlabelled bodyparts are `NaN`. Only frames labelled in BOTH cameras are returned.

**Why its own module:** parsing the folder is fiddly (index naming varies between
DLC versions, images are named `img_cam{C}_{seq}_{videoframe}.png`) and it must
be right or every downstream number is wrong. It needs no model, so it is fully
host-testable against a synthetic session.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_labelled_session.py
import numpy as np
import pandas as pd
import pytest

from dlc_3d_bp.labelled_session import load_labelled_session

BPS = ["Snout", "Wrist", "MCP-1"]


def _make_session(tmp_path, rows):
    """rows: list of (cam, videoframe, xy-list-or-None-per-bodypart)."""
    d = tmp_path / "sess"
    d.mkdir()
    (d / "calibration.toml").write_text("[cam_0]\n[cam_1]\n")
    index, data = [], []
    for cam, frame, coords in rows:
        name = "img_cam{}_{:04d}_{}.png".format(cam, len(index), frame)
        (d / name).write_bytes(b"")
        index.append(name)
        flat = []
        for c in coords:
            flat += [np.nan, np.nan] if c is None else [c[0], c[1]]
        data.append(flat)
    cols = pd.MultiIndex.from_product(
        [["Ali"], BPS, ["x", "y"]], names=["scorer", "bodyparts", "coords"])
    pd.DataFrame(data, columns=cols, index=index).to_hdf(
        d / "CollectedData_Ali.h5", key="df_with_missing", mode="w")
    return d


def test_returns_only_frames_labelled_in_both_cameras(tmp_path):
    d = _make_session(tmp_path, [
        (0, 100, [(1, 2), (3, 4), None]),
        (1, 100, [(5, 6), (7, 8), None]),
        (0, 200, [(1, 1), None, None]),      # cam0 only -> excluded
    ])
    s = load_labelled_session(str(d))
    assert [p["frame"] for p in s["pairs"]] == [100]
    assert s["bodyparts"] == BPS
    assert s["calibration_path"].endswith("calibration.toml")


def test_coordinates_are_per_camera_and_nan_where_unlabelled(tmp_path):
    d = _make_session(tmp_path, [
        (0, 7, [(1, 2), None, (5, 6)]),
        (1, 7, [(9, 8), (7, 6), None]),
    ])
    p = load_labelled_session(str(d))["pairs"][0]
    assert p["cam0_xy"].shape == (3, 2)
    assert np.allclose(p["cam0_xy"][0], [1, 2])
    assert np.isnan(p["cam0_xy"][1]).all(), "unlabelled must stay NaN"
    assert np.allclose(p["cam1_xy"][1], [7, 6])
    assert np.isnan(p["cam1_xy"][2]).all()


def test_image_paths_point_at_the_right_files(tmp_path):
    d = _make_session(tmp_path, [
        (0, 42, [(1, 2), (3, 4), (5, 6)]),
        (1, 42, [(1, 2), (3, 4), (5, 6)]),
    ])
    p = load_labelled_session(str(d))["pairs"][0]
    assert "img_cam0_" in p["cam0_image"] and p["cam0_image"].endswith("_42.png")
    assert "img_cam1_" in p["cam1_image"] and p["cam1_image"].endswith("_42.png")


def test_a_session_with_no_paired_frames_yields_none(tmp_path):
    d = _make_session(tmp_path, [(0, 1, [(1, 2), None, None])])
    assert load_labelled_session(str(d))["pairs"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_labelled_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dlc_3d_bp.labelled_session'`

- [ ] **Step 3: Write the implementation**

```python
# src/dlc_3d_bp/labelled_session.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_labelled_session.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Check it reads the REAL sessions (read-only)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python3 -c "
import sys; sys.path.insert(0,'src')
from dlc_3d_bp.labelled_session import load_labelled_session
import os
R='/home/sam/Parra-Lab-Data-NAS/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07/labeled-data'
tot=0
for d in sorted(os.listdir(R)):
    p=os.path.join(R,d)
    if not os.path.isdir(p) or not os.path.exists(os.path.join(p,'calibration.toml')): continue
    try: s=load_labelled_session(p)
    except Exception as e: print(f'  {d}: {type(e).__name__}'); continue
    if s['pairs']: print(f'  {d:26s} {len(s[\"pairs\"]):4d} pairs'); tot+=len(s['pairs'])
print('total pairs:',tot)
"
```

Expected: 13 sessions listed and **1,104 total pairs**. A different total means
the parser disagrees with the survey — report the number you observe.

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/labelled_session.py dlc-3D/tests/test_labelled_session.py
git commit -m "feat(peaks): read a labelled session as camera pairs"
```

---

### Task 3: Run the validation

**Files:**
- Create: `scripts/validate_peak_verdict.py`

**Interfaces:**
- Consumes: `extract_peaks`, `heatmap_to_image` (Phase 1), `peak_verdict` (Task 1), `load_labelled_session` (Task 2).
- Produces: a JSON report at `--out-dir` holding, per session and overall: correction accuracy, occlusion recall, and verdict counts.

- [ ] **Step 1: Write the script**

```python
# scripts/validate_peak_verdict.py
"""Score peak-based verdicts against human labels. READ-ONLY on the DLC project.

  docker cp dlc-3D/src/dlc_3d_bp/peaks.py            <c>:/tmp/m_peaks.py
  docker cp dlc-3D/src/dlc_3d_bp/peak_verdict.py     <c>:/tmp/m_verdict.py
  docker cp dlc-3D/src/dlc_3d_bp/labelled_session.py <c>:/tmp/m_session.py
  docker cp dlc-3D/scripts/validate_peak_verdict.py  <c>:/tmp/validate.py
  docker exec <c> python3 /tmp/validate.py --out-dir /tmp/val --device cuda:1
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import time

import numpy as np

ROOT = ("/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/"
        "DREADD-Ali-2026-01-07")
MODEL = ROOT + "/dlc-models-pytorch/iteration-22/DREADDJan7-trainset70shuffle1"
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
STRIDE, LOCREF_STD = 2.0, 7.2801


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_toml(text):
    out, sec = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            sec = line[1:-1]
            out[sec] = {}
            continue
        if sec is None or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().rstrip(",")
        out[sec][k.strip()] = (v == "true") if v in ("true", "false") else ast.literal_eval(v)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True,
                    help="explicit; never point this at the DLC project")
    ap.add_argument("--labelled-root", default=ROOT + "/labeled-data")
    ap.add_argument("--device", default="cuda:1")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--min-distance", type=int, default=3)
    ap.add_argument("--t-ok", type=float, default=8.0)
    ap.add_argument("--score-floor", type=float, default=0.10)
    ap.add_argument("--low-tgt", type=float, default=0.6)
    args = ap.parse_args()

    if os.path.abspath(args.out_dir).startswith(os.path.abspath(ROOT)):
        print("REFUSING: --out-dir is inside the DLC project")
        return 2

    import cv2
    import torch
    import yaml
    import deeplabcut.pose_estimation_pytorch as dlcpt

    pk = _load("m_peaks", "/tmp/m_peaks.py")
    pv = _load("m_verdict", "/tmp/m_verdict.py")
    ls = _load("m_session", "/tmp/m_session.py")

    cfg = yaml.safe_load(open(MODEL + "/train/pytorch_config.yaml"))
    model = dlcpt.models.PoseModel.build(cfg["model"])
    st = torch.load(MODEL + "/train/snapshot-best-180.pt",
                    map_location="cpu", weights_only=False)
    model.load_state_dict(st.get("model", st))
    model.to(args.device).eval()

    def infer(path):
        img = cv2.imread(path)
        h, w = img.shape[:2]
        H, W = ((h + 31) // 32) * 32, ((w + 31) // 32) * 32
        im = cv2.copyMakeBorder(img, 0, H - h, 0, W - w, cv2.BORDER_CONSTANT, value=0)
        rgb = (cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0 - MEAN) / STD
        with torch.no_grad():
            o = model(torch.from_numpy(rgb).permute(2, 0, 1)[None].to(args.device))
        hm = torch.sigmoid(o["bodypart"]["heatmap"])[0].cpu().numpy()
        lr = o["bodypart"]["locref"][0].cpu().numpy()
        return hm, lr

    def peaks_for(hm, lr, j):
        cells, sc = pk.extract_peaks(hm[j], k=args.k, min_distance=args.min_distance)
        xy = pk.heatmap_to_image(cells, STRIDE, (0, 0), (1.0, 1.0))
        for i in range(len(sc)):
            if np.isfinite(cells[i]).all():
                c, r = int(cells[i, 0]), int(cells[i, 1])
                xy[i, 0] += lr[2 * j, r, c] * LOCREF_STD
                xy[i, 1] += lr[2 * j + 1, r, c] * LOCREF_STD
        return xy, sc

    sessions = sorted(
        d for d in os.listdir(args.labelled_root)
        if os.path.isdir(os.path.join(args.labelled_root, d))
        and os.path.exists(os.path.join(args.labelled_root, d, "calibration.toml")))

    report, t0 = {}, time.time()
    for name in sessions:
        sdir = os.path.join(args.labelled_root, name)
        try:
            sess = ls.load_labelled_session(sdir)
        except Exception as exc:
            print("skip", name, type(exc).__name__)
            continue
        if not sess["pairs"]:
            continue
        cal = _parse_toml(open(sess["calibration_path"]).read())
        if "cam_0" not in cal or "cam_1" not in cal:
            continue

        import sys
        sys.path.insert(0, "/app")
        from dlc_3d_bp import epipolar_core as ec

        def mkcam(key):
            s = cal[key]
            return ec.Cam(name=str(s.get("name", key)),
                          K=np.asarray(s["matrix"], float).reshape(3, 3),
                          dist=np.asarray(s["distortions"], float).reshape(-1),
                          rvec=np.asarray(s["rotation"], float).reshape(3),
                          tvec=np.asarray(s["translation"], float).reshape(3),
                          size=(int(s["size"][0]), int(s["size"][1])))

        c0, c1 = mkcam("cam_0"), mkcam("cam_1")
        F = ec.fundamental_matrix(c1, c0)      # cam1 trusted, cam0 judged
        bps = sess["bodyparts"]
        orig_err, corr_err, counts, occl_total, occl_refused = [], [], {}, 0, 0

        for pair in sess["pairs"]:
            hm0, lr0 = infer(pair["cam0_image"])
            for j, _bp in enumerate(bps):
                ref = pair["cam1_xy"][j]
                if not np.isfinite(ref).all():
                    continue                     # no trusted marker: not judged
                xy, sc = peaks_for(hm0, lr0, j)
                u_ref = ec.undistort_to_pixels(c1, ref[None, :])
                u_pk = ec.undistort_to_pixels(c0, np.nan_to_num(xy, nan=1e9))
                d = ec.epipolar_distance(F, np.repeat(u_ref, len(u_pk), axis=0), u_pk)
                d[~np.isfinite(xy).all(axis=1)] = np.nan
                verdict, chosen = pv.peak_verdict(d, sc, args.t_ok, args.score_floor)
                counts[verdict] = counts.get(verdict, 0) + 1

                truth = pair["cam0_xy"][j]
                if not np.isfinite(truth).all():
                    occl_total += 1              # annotator says not visible
                    if verdict == pv.NO_EVIDENCE:
                        occl_refused += 1
                    continue
                if sc[0] >= args.low_tgt:
                    continue                     # confident already: not our population
                orig_err.append(float(np.linalg.norm(xy[0] - truth)))
                if verdict == pv.CORRECTED:
                    corr_err.append(float(np.linalg.norm(xy[chosen] - truth)))
                else:
                    corr_err.append(float(np.linalg.norm(xy[0] - truth)))

        report[name] = {
            "pairs": len(sess["pairs"]),
            "n_lowconf": len(orig_err),
            "median_original_px": float(np.median(orig_err)) if orig_err else None,
            "median_after_px": float(np.median(corr_err)) if corr_err else None,
            "occluded_cells": occl_total,
            "occluded_refused": occl_refused,
            "verdicts": {str(k): v for k, v in sorted(counts.items())},
        }
        r = report[name]
        print(f"{name:26s} pairs={r['pairs']:4d} lowconf={r['n_lowconf']:5d} "
              f"orig={r['median_original_px']} after={r['median_after_px']} "
              f"occl={occl_refused}/{occl_total}", flush=True)

    os.makedirs(args.out_dir, exist_ok=True)
    dst = os.path.join(args.out_dir, "peak_verdict_validation.json")
    with open(dst, "w") as fh:
        json.dump({"config": vars(args), "sessions": report}, fh, indent=2)
    print("\nwrote", dst, f"({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
C=deeplabcut-webapp-docker-worker-1
docker cp dlc-3D/src/dlc_3d_bp/peaks.py            $C:/tmp/m_peaks.py
docker cp dlc-3D/src/dlc_3d_bp/peak_verdict.py     $C:/tmp/m_verdict.py
docker cp dlc-3D/src/dlc_3d_bp/labelled_session.py $C:/tmp/m_session.py
docker cp dlc-3D/scripts/validate_peak_verdict.py  $C:/tmp/validate.py
docker exec $C python3 /tmp/validate.py --out-dir /tmp/val --device cuda:1
```

Expected: a per-session line for each of the 13 sessions and a JSON report.
Roughly 2,200 images at ~42 fps, so a couple of minutes. If the model fails to
build or load, STOP and report the exact error rather than improvising.

- [ ] **Step 3: Commit the script**

```bash
git add dlc-3D/scripts/validate_peak_verdict.py
git commit -m "feat(peaks): validation harness scoring verdicts against human labels"
```

---

### Task 4: Report the verdict on the approach

**Files:** none — this task decides whether Phase 2's engine change gets built.

- [ ] **Step 1: Summarise the two scores**

From the JSON, compute across all sessions and separately for a held-out split
(tune on `khoai-lang-1*`, measure on `khoai-lang-2*`, `eggtart-1*`, `OM-2*`):

- median original error vs median error after correction, on the low-confidence
  population
- occlusion recall: `occluded_refused / occluded_cells`
- the verdict mix (how often each of NO_EVIDENCE / RESCUE / CORRECTED /
  AMBIGUOUS fires)

- [ ] **Step 2: Apply the gate honestly**

The approach passes if corrections **reduce** the median distance to the human
label on the held-out sessions. If they do not, say so and stop — that is a
successful outcome of this plan. **Do not tune `--score-floor` or `--t-ok` until
the number turns green**; if you want to explore sensitivity, report the full
sweep rather than the best point.

- [ ] **Step 3: Confirm nothing was written to the project**

```bash
R=/home/sam/Parra-Lab-Data-NAS/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07
find "$R/labeled-data" -newermt '-2 hours' -type f | head
ls "$R/labeled-data" | wc -l
```

Expected: no recently modified files, and 44 directories. Report what you observe.

- [ ] **Step 4: Clean up**

```bash
C=deeplabcut-webapp-docker-worker-1
docker exec $C sh -c 'rm -f /tmp/m_peaks.py /tmp/m_verdict.py /tmp/m_session.py /tmp/validate.py; rm -rf /tmp/val'
docker exec $C ls /tmp
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
```

Report the GPU state you observe.

- [ ] **Step 5: No commit** — this task produces no repository change.

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
| --- | --- |
| `NO_EVIDENCE` when no peak qualifies | 1 |
| `CORRECTED` when a different peak qualifies | 1 |
| `AMBIGUOUS` when several qualify (discriminability) | 1 |
| Score floor rejects noise peaks | 1 |
| Read the 13 labelled sessions, both cameras | 2 |
| Per-session calibration | 3 |
| Correction accuracy vs the 22.6 px baseline | 3, 4 |
| Occlusion recall on unlabelled cells | 3, 4 |
| Held-out sessions for tuning vs measurement | 4 |
| Kill threshold applied honestly | 4 |
| `labeled-data/` read-only, explicit `--out-dir` | Global Constraints; enforced in the script and checked in 4 |

Not covered here by design: the engine change itself — new verdicts in
`epipolar_core`/`reprojection`, and any UI. That is a separate plan and is only
written if Task 4 passes.

**Placeholder scan:** none.

**Type consistency:** `peak_verdict(peak_dists, peak_scores, t_ok, score_floor) -> (verdict, chosen_index)` is defined in Task 1 and called in Task 3 with that signature. `load_labelled_session(session_dir) -> {bodyparts, calibration_path, pairs}` is defined in Task 2 and consumed in Task 3 by those key names. `extract_peaks` and `heatmap_to_image` keep their Phase 1 signatures.

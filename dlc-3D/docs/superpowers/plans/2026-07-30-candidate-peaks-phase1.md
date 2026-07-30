# Candidate Peaks — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit a `<stem>_peaks.npz` sidecar holding DeepLabCut's top-K candidate peaks per bodypart per frame, in original video pixels.

**Architecture:** Peak extraction is pure numpy and unit-tested on the host. The coordinate transform from heatmap cells back to video pixels is established empirically against DeepLabCut's own output, then reused. A runner script produces the sidecar inside the worker container, which is the only place DeepLabCut is installed.

**Tech Stack:** numpy, `scipy.ndimage`, DeepLabCut 3.0.0rc14 (PyTorch engine), pytest.

## Global Constraints

- **Only `deeplabcut-webapp-docker-worker-1` has DeepLabCut** (3.0.0rc14). The `dlc-3d` and `dlc-3d-worker` containers do not. Anything importing `deeplabcut` runs there, via `docker exec`.
- **Peak extraction itself must import only `numpy` and `scipy.ndimage`**, so it is testable on the host (Python 3.9) with no torch and no DLC.
- **Python 3.9-compatible syntax.** Host pytest runner is 3.9.23. Quote any `X | Y` annotation.
- **The GPU is in use by the user's own analysis.** Every step in this plan runs on **CPU** over short clips. Do not run a full-session pass; scheduling that is a later decision.
- **Never modify the DLC installation, the DLC project, or any model file.** Read the snapshot, never write to it.
- **Never write into the research data directories.** All output goes to a scratch path passed explicitly.
- **Do NOT restart, rebuild or stop any container.** `docker exec` and `docker cp` into `/tmp` only. Note that `/app/dlc_3d_bp` and `/app/static` are bind mounts that write through to the host checkout — never `docker cp` into those.
- Ten tests fail on this host for unrelated pre-existing reasons; the two playwright e2e tests are flaky, so a run shows 9–11 failures. **Compare failure NAMES against the known ten, never counts.**
- Run pytest from `dlc-3D/`.

## Reference facts, already established

- Model: `hrnet_w48`, `num_heatmaps: 16`. Inference runs at NATIVE resolution padded to a multiple of 32 — **not** resized to 448×448. Heatmap stride is exactly 2; `locref_std` 7.2801.
- Snapshot in use: `/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07/dlc-models-pytorch/iteration-22/DREADDJan7-trainset70shuffle1/train/snapshot-best-180.pt`
- `HeatmapPredictor.forward` receives the heatmap, but the MODEL output is nested: `out["bodypart"]["heatmap"]` and `out["bodypart"]["locref"]`, shapes `(batch, 16, 305, 401)` and `(batch, 32, 305, 401)` for a padded 800x608 frame.
- Reference session: `/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/070126`, videos `eggtart-1_cam{0,1}_...avi`, poses `..._snapshot_best-180.h5`.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/dlc_3d_bp/peaks.py` | Pure peak extraction + the coordinate transform. numpy/scipy only. |
| `tests/test_peaks.py` | Host unit tests for both. |
| `scripts/probe_dlc_heatmap.py` | Task 2 exploration: prints what DLC does to coordinates. |
| `scripts/emit_peaks.py` | Runner: video + snapshot → `<stem>_peaks.npz`. |

---

### Task 1: Pure peak extraction

**Files:**
- Create: `src/dlc_3d_bp/peaks.py`
- Test: `tests/test_peaks.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `extract_peaks(heatmap, k=5, min_distance=3) -> (xy, scores)` where `heatmap` is a 2-D `(H, W)` array for ONE bodypart, `xy` is `(k, 2)` float32 in heatmap-cell coordinates as `(x=column, y=row)` NaN-padded, and `scores` is `(k,)` float32 zero-padded, both sorted by descending score.

**Why NMS matters:** a naive top-K over a heatmap returns K adjacent cells of the same blob, so "5 peaks" would mean one detection reported five times. Peaks must be local maxima separated by `min_distance`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_peaks.py
import numpy as np
import pytest

from dlc_3d_bp.peaks import extract_peaks


def _blob(hm, cx, cy, amp, sigma=1.2):
    """Add a small Gaussian blob centred on (cx, cy)."""
    h, w = hm.shape
    ys, xs = np.mgrid[0:h, 0:w]
    hm += amp * np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sigma ** 2)))
    return hm


def test_single_blob_gives_one_peak_at_its_centre():
    hm = _blob(np.zeros((40, 40), np.float32), 12, 25, 1.0)
    xy, sc = extract_peaks(hm, k=5, min_distance=3)
    assert xy.shape == (5, 2) and sc.shape == (5,)
    assert np.allclose(xy[0], [12, 25], atol=1.0)
    assert sc[0] > 0.9
    assert np.isnan(xy[1:]).all(), "one blob must not yield five peaks"
    assert (sc[1:] == 0).all()


def test_adjacent_cells_of_one_blob_are_suppressed():
    """The regression this exists for: without NMS, top-K returns the peak cell
    and its neighbours, so K distinct candidates would be one detection."""
    hm = _blob(np.zeros((40, 40), np.float32), 20, 20, 1.0, sigma=2.5)
    xy, sc = extract_peaks(hm, k=5, min_distance=3)
    found = xy[~np.isnan(xy[:, 0])]
    assert len(found) == 1, "a single wide blob must yield exactly one peak"


def test_two_separated_blobs_give_two_peaks_ordered_by_score():
    hm = np.zeros((40, 40), np.float32)
    _blob(hm, 8, 8, 0.6)
    _blob(hm, 30, 30, 0.95)
    xy, sc = extract_peaks(hm, k=5, min_distance=3)
    assert np.allclose(xy[0], [30, 30], atol=1.0), "highest score first"
    assert np.allclose(xy[1], [8, 8], atol=1.0)
    assert sc[0] > sc[1] > 0
    assert np.isnan(xy[2:]).all()


def test_k_limits_the_number_returned():
    hm = np.zeros((60, 60), np.float32)
    for i, (cx, cy) in enumerate([(5, 5), (20, 5), (35, 5), (50, 5), (5, 25), (20, 25)]):
        _blob(hm, cx, cy, 0.9 - 0.05 * i)
    xy, sc = extract_peaks(hm, k=3, min_distance=3)
    assert xy.shape == (3, 2)
    assert not np.isnan(xy).any(), "three of six blobs must be returned"
    assert sc[0] >= sc[1] >= sc[2]


def test_flat_heatmap_yields_nothing():
    xy, sc = extract_peaks(np.zeros((20, 20), np.float32), k=5, min_distance=3)
    assert np.isnan(xy).all()
    assert (sc == 0).all()


def test_scores_are_always_descending_and_padding_is_zero():
    rng = np.random.default_rng(0)
    hm = rng.random((50, 50)).astype(np.float32) * 0.2
    _blob(hm, 10, 10, 1.0)
    _blob(hm, 40, 40, 0.8)
    xy, sc = extract_peaks(hm, k=5, min_distance=4)
    real = sc[sc > 0]
    assert np.all(np.diff(real) <= 0)
    assert np.isnan(xy[len(real):]).all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_peaks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dlc_3d_bp.peaks'`

- [ ] **Step 3: Write the implementation**

```python
# src/dlc_3d_bp/peaks.py
"""Candidate-peak extraction from DeepLabCut heatmaps.

Imports only numpy and scipy.ndimage so it is testable on the host, where
neither torch nor DeepLabCut is installed. The DLC-dependent work lives in
scripts/emit_peaks.py, which runs inside the worker container.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage


def extract_peaks(heatmap, k: int = 5, min_distance: int = 3):
    """Top-k local maxima of one bodypart's heatmap.

    Returns (xy, scores): xy is (k, 2) float32 in heatmap-cell coordinates as
    (x=column, y=row), NaN-padded; scores is (k,) float32, zero-padded. Both are
    ordered by descending score.

    Non-maximum suppression is not optional: a plain top-k returns the peak cell
    and its neighbours, so k "candidates" would be one detection counted k times.
    """
    hm = np.asarray(heatmap, dtype=np.float32)
    xy = np.full((k, 2), np.nan, dtype=np.float32)
    scores = np.zeros(k, dtype=np.float32)
    if hm.ndim != 2 or hm.size == 0:
        return xy, scores

    # A cell is a candidate when it equals the max of its neighbourhood and is
    # strictly positive, so a flat or empty heatmap yields nothing.
    size = 2 * int(min_distance) + 1
    local_max = ndimage.maximum_filter(hm, size=size, mode="nearest")
    cand = np.argwhere((hm == local_max) & (hm > 0))
    if not len(cand):
        return xy, scores

    vals = hm[cand[:, 0], cand[:, 1]]
    order = np.argsort(-vals)
    cand, vals = cand[order], vals[order]

    # Greedy suppression: keep a candidate only if it clears min_distance from
    # every candidate already kept. maximum_filter alone can still return two
    # cells of one plateau.
    kept_rc = []
    for (r, c), v in zip(cand, vals):
        if any((r - kr) ** 2 + (c - kc) ** 2 < min_distance ** 2 for kr, kc in kept_rc):
            continue
        kept_rc.append((r, c))
        idx = len(kept_rc) - 1
        xy[idx] = (float(c), float(r))   # x = column, y = row
        scores[idx] = float(v)
        if len(kept_rc) == k:
            break
    return xy, scores
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_peaks.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/peaks.py dlc-3D/tests/test_peaks.py
git commit -m "feat(peaks): NMS top-k peak extraction from a DLC heatmap"
```

---

### Task 2: Establish the coordinate transform

**Files:**
- Create: `scripts/probe_dlc_heatmap.py`
- Modify: `src/dlc_3d_bp/peaks.py`
- Test: `tests/test_peaks.py`

**Interfaces:**
- Consumes: `extract_peaks` (Task 1).
- Produces: `heatmap_to_image(xy_cells, stride, pad_xy, scale_xy) -> np.ndarray` mapping heatmap-cell coordinates to original video pixels, where `pad_xy = (pad_x, pad_y)` are the padding offsets applied before the network and `scale_xy = (sx, sy)` the resize factors from original to network input.

**Why this task exists separately:** mapping a peak back from 448×448 network space through padding and resize to an 800×600 frame is the highest-risk part of the whole phase, and it is silently wrong when mishandled. It is established empirically against DeepLabCut's own output rather than derived from documentation.

- [ ] **Step 1: Write the probe script**

```python
# scripts/probe_dlc_heatmap.py
"""Print how DeepLabCut turns a heatmap into a pose coordinate.

Runs on CPU over a handful of frames so it does not contend for the GPU.
Read the output, then implement heatmap_to_image accordingly.

  docker cp dlc-3D/scripts/probe_dlc_heatmap.py \\
      deeplabcut-webapp-docker-worker-1:/tmp/probe_dlc_heatmap.py
  docker exec deeplabcut-webapp-docker-worker-1 python3 /tmp/probe_dlc_heatmap.py
"""
from __future__ import annotations

import sys

import numpy as np
import torch

MODEL = ("/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/"
         "DREADD-Ali-2026-01-07/dlc-models-pytorch/iteration-22/"
         "DREADDJan7-trainset70shuffle1")


def main() -> int:
    import deeplabcut.pose_estimation_pytorch as dlcpt
    from deeplabcut.pose_estimation_pytorch.models.predictors import HeatmapPredictor

    cfg_path = MODEL + "/train/pytorch_config.yaml"
    print("config:", cfg_path)

    import yaml
    cfg = yaml.safe_load(open(cfg_path))

    # What the network expects, and what it emits.
    print("\n=== preprocessing config ===")
    for key in ("data", "model"):
        sub = cfg.get(key, {})
        if isinstance(sub, dict):
            for k, v in sub.items():
                s = str(v)
                if len(s) < 120:
                    print(f"  {key}.{k}: {s}")

    print("\n=== predictor ===")
    print("  ", cfg.get("predictor"))

    # A forward pass on synthetic input reveals stride: input size / heatmap size.
    print("\n=== stride, from a forward pass ===")
    try:
        model = dlcpt.models.PoseModel.build(cfg["model"])
        model.eval()
        with torch.no_grad():
            out = model(torch.zeros(1, 3, 448, 448))
        hm = out["heatmap"] if isinstance(out, dict) else out[0]["heatmap"]
        print("  heatmap shape:", tuple(hm.shape))
        print("  implied stride:", 448 / hm.shape[-1])
    except Exception as exc:
        print("  could not build model directly:", type(exc).__name__, exc)
        print("  -> fall back to reading cfg['model']['heads'] for the stride")

    print("\n=== what HeatmapPredictor does with stride ===")
    import inspect
    src = inspect.getsource(HeatmapPredictor.forward)
    for line in src.splitlines():
        if any(t in line for t in ("stride", "scale", "locref", "argmax", "poses")):
            print("   ", line.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the probe and record what it prints**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
docker cp dlc-3D/scripts/probe_dlc_heatmap.py \
  deeplabcut-webapp-docker-worker-1:/tmp/probe_dlc_heatmap.py
docker exec deeplabcut-webapp-docker-worker-1 python3 /tmp/probe_dlc_heatmap.py
```

Record the heatmap shape, the implied stride, and the lines showing how
`HeatmapPredictor.forward` scales coordinates. Write them into your report — the
next step depends on them. If the model cannot be built directly, the predictor
source printed at the end still shows the scaling, which is the part that
matters.

- [ ] **Step 3: Write the failing test**

Append to `tests/test_peaks.py`:

```python
from dlc_3d_bp.peaks import heatmap_to_image


def test_heatmap_to_image_applies_stride_then_undoes_pad_and_scale():
    """A peak at heatmap cell (10, 5) with stride 8, 20px x-pad and a 0.5
    resize maps to ((10*8 + 8/2) - 20) / 0.5 in x."""
    xy = np.array([[10.0, 5.0]], dtype=np.float32)
    got = heatmap_to_image(xy, stride=8, pad_xy=(20, 0), scale_xy=(0.5, 0.5))
    assert got.shape == (1, 2)
    assert got[0, 0] == pytest.approx(((10 * 8 + 4) - 20) / 0.5)
    assert got[0, 1] == pytest.approx(((5 * 8 + 4) - 0) / 0.5)


def test_heatmap_to_image_is_identity_for_stride_1_no_pad_no_scale():
    xy = np.array([[3.0, 7.0]], dtype=np.float32)
    got = heatmap_to_image(xy, stride=1, pad_xy=(0, 0), scale_xy=(1.0, 1.0))
    assert got[0] == pytest.approx([3.5, 7.5])


def test_heatmap_to_image_propagates_nan_padding():
    xy = np.array([[1.0, 2.0], [np.nan, np.nan]], dtype=np.float32)
    got = heatmap_to_image(xy, stride=8, pad_xy=(0, 0), scale_xy=(1.0, 1.0))
    assert np.isfinite(got[0]).all()
    assert np.isnan(got[1]).all()
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_peaks.py -k heatmap_to_image -v`
Expected: FAIL — `ImportError: cannot import name 'heatmap_to_image'`

- [ ] **Step 5: Implement it**

Append to `src/dlc_3d_bp/peaks.py`:

```python
def heatmap_to_image(xy_cells, stride, pad_xy=(0, 0), scale_xy=(1.0, 1.0)):
    """Map heatmap-cell coordinates to original video pixels.

    A cell's centre is at (cell + 0.5) * stride in network-input space. The
    network input was produced by resizing the original frame by scale_xy and
    then padding by pad_xy, so both are undone in that order.

    NaN padding is preserved: a missing peak stays missing.
    """
    xy = np.asarray(xy_cells, dtype=np.float64).reshape(-1, 2)
    out = np.full_like(xy, np.nan)
    ok = np.isfinite(xy).all(axis=1)
    if ok.any():
        net = (xy[ok] + 0.5) * float(stride)
        net[:, 0] -= float(pad_xy[0])
        net[:, 1] -= float(pad_xy[1])
        net[:, 0] /= float(scale_xy[0])
        net[:, 1] /= float(scale_xy[1])
        out[ok] = net
    return out.astype(np.float32)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_peaks.py -v`
Expected: PASS, 9 tests

- [ ] **Step 7: Commit**

```bash
git add dlc-3D/scripts/probe_dlc_heatmap.py dlc-3D/src/dlc_3d_bp/peaks.py dlc-3D/tests/test_peaks.py
git commit -m "feat(peaks): heatmap-cell to video-pixel coordinate transform"
```

---

### Task 3: Emit the sidecar

**Files:**
- Create: `scripts/emit_peaks.py`

**Interfaces:**
- Consumes: `extract_peaks`, `heatmap_to_image` (Tasks 1–2).
- Produces: `<stem>_peaks.npz` with arrays `xy` `(frames, bodyparts, K, 2)` float32, `score` `(frames, bodyparts, K)` float32, and `bodyparts` — names in the pose h5's column order. `k=0` is the argmax.

**This is a script, not a test.** It needs DeepLabCut and a video, so it runs in the worker container. Its correctness is established in Task 4.

- [ ] **Step 1: Write the script**

```python
# scripts/emit_peaks.py
"""Emit DeepLabCut candidate peaks for a video as <stem>_peaks.npz.

Runs inside deeplabcut-webapp-docker-worker-1, the only container with DLC.
Defaults to CPU and a short frame range so it does not contend for the GPU.

  docker cp dlc-3D/src/dlc_3d_bp/peaks.py \\
      deeplabcut-webapp-docker-worker-1:/tmp/peaks_mod.py
  docker cp dlc-3D/scripts/emit_peaks.py \\
      deeplabcut-webapp-docker-worker-1:/tmp/emit_peaks.py
  docker exec deeplabcut-webapp-docker-worker-1 python3 /tmp/emit_peaks.py \\
      --video "<video>" --out-dir /tmp/peaks --end 200

NOTE: copy peaks.py to /tmp, NOT into /app/dlc_3d_bp — that path is a bind mount
onto the host checkout and a docker cp there writes through to the repository.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import numpy as np
import torch

MODEL = ("/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/"
         "DREADD-Ali-2026-01-07/dlc-models-pytorch/iteration-22/"
         "DREADDJan7-trainset70shuffle1")


def _load_peaks_module(path="/tmp/peaks_mod.py"):
    spec = importlib.util.spec_from_file_location("peaks_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--snapshot", default="snapshot-best-180.pt")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--min-distance", type=int, default=3)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=200,
                    help="exclusive; keep small unless the GPU is free")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    pk = _load_peaks_module()
    import cv2
    import yaml
    import deeplabcut.pose_estimation_pytorch as dlcpt

    cfg = yaml.safe_load(open(Path(args.model) / "train" / "pytorch_config.yaml"))
    bodyparts = cfg["metadata"]["bodyparts"]
    model = dlcpt.models.PoseModel.build(cfg["model"])
    state = torch.load(Path(args.model) / "train" / args.snapshot,
                       map_location=args.device, weights_only=False)
    model.load_state_dict(state["model"] if "model" in state else state)
    model.to(args.device).eval()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print("cannot open", args.video)
        return 2
    cap.set(cv2.CAP_PROP_POS_FRAMES, args.start)

    n = args.end - args.start
    XY = np.full((n, len(bodyparts), args.k, 2), np.nan, np.float32)
    SC = np.zeros((n, len(bodyparts), args.k), np.float32)

    # PIPELINE VERIFIED EMPIRICALLY against the existing pose h5 (0.344 px median,
    # 0.975 px p95 on confident markers). Every element below was measured, not
    # assumed — an earlier draft of this script was wrong on all five:
    #   * NATIVE resolution, padded to a multiple of 32. NOT resized to 448x448
    #     (resizing gave 427 px median error).
    #   * ImageNet mean/std normalisation after /255 (plain /255 gave 186 px).
    #   * output is NESTED: out["bodypart"]["heatmap"], not out["heatmap"].
    #   * stride is exactly 2. Using net_width/heatmap_width (1.995) drifts by
    #     ~2 px at the frame edge.
    #   * locref sub-pixel refinement is REQUIRED: without it, 1.116 px median
    #     instead of 0.344 px.
    MEAN = np.array([0.485, 0.456, 0.406], np.float32)
    STD = np.array([0.229, 0.224, 0.225], np.float32)
    STRIDE = 2.0
    locref_std = (cfg.get("model", {}).get("heads", {}).get("bodypart", {})
                     .get("predictor", {}).get("locref_std", 7.2801))

    for i in range(n):
        ok, frame = cap.read()
        if not ok:
            XY, SC = XY[:i], SC[:i]
            break
        h, w = frame.shape[:2]
        H = ((h + 31) // 32) * 32
        W = ((w + 31) // 32) * 32
        im = cv2.copyMakeBorder(frame, 0, H - h, 0, W - w, cv2.BORDER_CONSTANT, value=0)
        rgb = (cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0 - MEAN) / STD
        t_in = torch.from_numpy(rgb).permute(2, 0, 1)[None].to(args.device)
        with torch.no_grad():
            out = model(t_in)
        hm = torch.sigmoid(out["bodypart"]["heatmap"])[0].cpu().numpy()
        lr = out["bodypart"]["locref"][0].cpu().numpy()
        for j in range(len(bodyparts)):
            cells, sc = pk.extract_peaks(hm[j], k=args.k,
                                         min_distance=args.min_distance)
            # Padding is bottom/right only, so it does not shift the origin, and
            # there is no resize: pad_xy=(0,0), scale_xy=(1,1).
            xy = pk.heatmap_to_image(cells, STRIDE, (0, 0), (1.0, 1.0))
            for p_i in range(args.k):
                if not np.isfinite(cells[p_i]).all():
                    continue
                c_col, c_row = int(cells[p_i, 0]), int(cells[p_i, 1])
                xy[p_i, 0] += lr[2 * j, c_row, c_col] * locref_std
                xy[p_i, 1] += lr[2 * j + 1, c_row, c_col] * locref_std
            XY[i, j] = xy
            SC[i, j] = sc
        if i % 50 == 0:
            print(f"  frame {args.start + i}", flush=True)
    cap.release()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (Path(args.video).stem + "_peaks.npz")
    np.savez_compressed(dst, xy=XY, score=SC,
                        bodyparts=np.array(bodyparts, dtype=object))
    print("wrote", dst, XY.shape, f"{dst.stat().st_size/1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it over a short clip**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
docker cp dlc-3D/src/dlc_3d_bp/peaks.py deeplabcut-webapp-docker-worker-1:/tmp/peaks_mod.py
docker cp dlc-3D/scripts/emit_peaks.py deeplabcut-webapp-docker-worker-1:/tmp/emit_peaks.py
docker exec deeplabcut-webapp-docker-worker-1 python3 /tmp/emit_peaks.py \
  --video "/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/070126/eggtart-1_cam0_20260701_094411_10_trig1_fps200_exposure1500_gain10.avi" \
  --out-dir /tmp/peaks --start 0 --end 100 --device cpu
```

Expected: a `.npz` written with shape `(100, 16, 5, 2)`. If the model will not
build or load, STOP and report the exact error — do not improvise a different
loading path. Report the wall-clock time; it is the throughput estimate the spec
says is still unknown.

- [ ] **Step 3: Commit**

```bash
git add dlc-3D/scripts/emit_peaks.py
git commit -m "feat(peaks): script emitting a candidate-peak sidecar for a video"
```

---

### Task 4: Validate `k=0` against the existing poses

**Files:** none — this task runs a check and records the result.

**Interfaces:**
- Consumes: the sidecar from Task 3.
- Produces: the go/no-go evidence for Phase 2.

**Why this is the decisive test:** the same snapshot produced the existing pose h5,
so the top peak must reproduce its coordinates. A mismatch means the coordinate
transform is wrong, and every downstream conclusion would be wrong with it.

- [ ] **Step 1: Write the check**

```python
# /tmp/check_k0.py  (not committed; a one-off verification)
import numpy as np, pandas as pd, sys
z = np.load(sys.argv[1], allow_pickle=True)
df = pd.read_hdf(sys.argv[2])
scorer = df.columns.get_level_values(0)[0]
bps = [str(b) for b in z["bodyparts"]]
xy, n = z["xy"], len(z["xy"])
d = []
for j, bp in enumerate(bps):
    got = xy[:, j, 0, :]
    want = df[scorer][bp][["x", "y"]].to_numpy(float)[:n]
    ok = np.isfinite(got).all(axis=1) & np.isfinite(want).all(axis=1)
    if ok.any():
        dist = np.linalg.norm(got[ok] - want[ok], axis=1)
        d.append((bp, len(dist), float(np.median(dist)), float(np.percentile(dist, 95))))
print(f"{'bodypart':10s} {'n':>5s} {'median px':>10s} {'p95 px':>8s}")
for bp, n_, med, p95 in d:
    print(f"{bp:10s} {n_:5d} {med:10.3f} {p95:8.3f}")
worst = max(x[2] for x in d)
print(f"\nworst median offset: {worst:.3f} px")
print("PASS - transform is correct" if worst < 2.0 else
      "FAIL - k=0 does not reproduce the pose h5; the transform is wrong")
```

- [ ] **Step 2: Run it**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
docker cp /tmp/check_k0.py deeplabcut-webapp-docker-worker-1:/tmp/check_k0.py
docker exec deeplabcut-webapp-docker-worker-1 python3 /tmp/check_k0.py \
  /tmp/peaks/eggtart-1_cam0_20260701_094411_10_trig1_fps200_exposure1500_gain10_peaks.npz \
  "/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/070126/eggtart-1_cam0_20260701_094411_10_trig1_fps200_exposure1500_gain10DLC_HrnetW48_DREADDJan7shuffle1_snapshot_best-180.h5"
```

Expected: a per-bodypart table and `PASS`. A worst median offset above 2 px means
the transform is wrong — most likely the padding or the resize is not what the
probe suggested. Report the actual numbers; do not adjust the threshold to make
it pass.

- [ ] **Step 3: Confirm nothing was written to the research data**

```bash
ls "/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/tdcs/070126" | grep -c "peaks"
```

Expected: `0`. All output went to the container's `/tmp`. Report the number you
observe.

- [ ] **Step 4: Record the finding**

Append the per-bodypart table, the worst offset, and the wall-clock time from
Task 3 to the report file. Those three numbers decide whether Phase 2 proceeds
and how the full pass gets scheduled.

- [ ] **Step 5: No commit** — this task produces no repository change.

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
| --- | --- |
| Top-K peaks with NMS | 1 |
| NMS separation so K means K detections | 1, with a dedicated regression test |
| Coordinates in original video pixels | 2 |
| Sub-pixel handling via cell centres | 2 |
| `<stem>_peaks.npz` with `xy`, `score`, `bodyparts` | 3 |
| `k=0` reproduces the pose h5 | 4 — the decisive test |
| Descending scores, NaN/zero padding | 1 |
| Throughput measurement (spec flagged as unknown) | 3 Step 2 |
| Never write to research data | 4 Step 3 |

Not covered here by design: everything under the spec's Phase 2 — the
`NO_EVIDENCE` / `CORRECTED` verdicts and validation against human labels. That is
a separate plan, and it depends on this one's Task 4 passing.

**Placeholder scan:** none. Task 2 Step 2 is an investigation, but with an exact
command and a recorded deliverable that Step 5's already-written implementation
consumes through a fixed signature.

**Type consistency:** `extract_peaks(heatmap, k, min_distance) -> (xy, scores)`
is defined in Task 1 and called in Task 3. `heatmap_to_image(xy_cells, stride,
pad_xy, scale_xy)` is defined in Task 2 and called in Task 3 with that signature.
The sidecar's `xy`/`score`/`bodyparts` arrays are written in Task 3 and read in
Task 4 under those names.

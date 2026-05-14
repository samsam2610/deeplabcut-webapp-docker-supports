# LP Two-Stage Training Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the dlc-3D pipeline so a single `Run training` click pretrains a ViT-S/DINO backbone on all labeled frames (single-view convention) then trains MVT on the multi-view project initialized from the pretrained backbone via LP's existing `cfg.model.checkpoint` weights-only fallback.

**Architecture:** `convert_dlc_to_lp` gains a nested `sv-pretrain/` sub-project containing every labeled frame flattened into one CSV (LP's canonical single-view shape). `lp_train` branches on `options.two_stage`: when set, it materialises a stage-1 config, runs `litpose train` on the SV sub-project, finds the best checkpoint, then runs the existing stage-2 (MVT) flow with `model.checkpoint` pre-set. No image rebuild; no new dependencies.

**Tech Stack:** Python, pandas/pyyaml, Celery, ffmpeg (already present), pytest. No JS framework — `lp_cards.js` gains one fieldset wiring.

**Reference spec:** `docs/superpowers/specs/2026-05-14-lp-two-stage-training-design.md`

**Test fixture:** `/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-TEST` is gone (cleaned up earlier). Use the real DLC project `/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07` as the source for the live smoke. Write to `<source>-LP-2STAGE-TEST/` to avoid colliding with the existing `<source>-LP/` from prior runs.

**Repo paths:**
- supports repo: `/home/sam/docker-images/deeplabcut-webapp-docker-supports/`
- main webapp (only restarts, no edits): `/home/sam/docker-images/deeplabcut-webapp-docker/`

---

## File Structure

**Modified:**
- `dlc-3D/src/dlc_3d_bp/lp/converter.py` — add `_build_sv_pretrain_project()` + `_walk_all_labeled_data()` + `_write_sv_config()`; call from `convert_dlc_to_lp`; extend summary return
- `dlc-3D/src/dlc_3d_bp/lp/train_runner.py` — add `find_best_checkpoint(model_dir)` and `build_stage1_config(sv_project, run_dir, options)`
- `dlc-3D/src/dlc_3d_bp/lp/tasks.py` — `lp_train` branches on `options.two_stage`
- `dlc-3D/src/templates/partials/card_lp_train.html` — add Pretraining fieldset
- `dlc-3D/src/static/lp_cards.js` — wire new controls; surface `stage` in poll output

**Created:**
- `dlc-3D/tests/test_lp_sv_pretrain.py` — converter + stage-1 config tests
- `dlc-3D/tests/test_lp_two_stage_task.py` — orchestrator tests (mock subprocess)

**Untouched:** route handler payload schema (additive options only), main webapp, docker-compose.yml, requirements-lp.txt. No image rebuild needed.

---

## Phase 0 — Baseline

- [ ] **Step 0.1: Confirm clean working tree on supports repo**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git status --short dlc-3D/
```
Expected: empty.

- [ ] **Step 0.2: Baseline test count**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q --ignore=tests/e2e 2>&1 | tail -3
```
Expected: **109 passed, 4 skipped** (or whatever the current main shows — note it for "+N" tracking).

- [ ] **Step 0.3: Confirm the existing converted LP project exists for the live smoke later**

Run:
```bash
ls /home/sam/Parra-Lab-Data-NAS/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07/config.yaml
```
Expected: file listed.

---

## Phase 1 — Converter: walk every labeled-data folder

### Task 1.1: `_walk_all_labeled_data` — generator over every labeled row across all folders

**Files:**
- Create: `dlc-3D/tests/test_lp_sv_pretrain.py`
- Modify: `dlc-3D/src/dlc_3d_bp/lp/converter.py`

- [ ] **Step 1.1.1: Write failing test**

Create `dlc-3D/tests/test_lp_sv_pretrain.py`:
```python
"""Tests for the SV-pretrain branch of convert_dlc_to_lp."""
from __future__ import annotations

import csv
from pathlib import Path
import textwrap

import pytest

from dlc_3d_bp.lp.converter import _walk_all_labeled_data


def _seed(folder: Path, csv_name: str, rows: list[list[str]], png_names: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / csv_name).open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scorer", "", "", "x"])
        w.writerow(["bodyparts", "", "", "Snout"])
        w.writerow(["coords", "", "", "x"])
        for r in rows:
            w.writerow(r)
    for n in png_names:
        (folder / n).write_bytes(b"\x89PNG\r\n\x1a\n")


def test_walk_all_labeled_data_yields_view_in_filename(tmp_path):
    """A folder whose name is a session-key (view-in-filename layout) yields
    one entry per labeled row across all cams."""
    dlc = tmp_path / "dlc"
    ld = dlc / "labeled-data" / "rat_20260101"
    _seed(
        ld, "CollectedData_x.csv",
        rows=[
            ["labeled-data", "rat_20260101", "img_cam0_0000_00100.png", "10"],
            ["labeled-data", "rat_20260101", "img_cam1_0000_00100.png", "20"],
        ],
        png_names=["img_cam0_0000_00100.png", "img_cam1_0000_00100.png"],
    )
    entries = list(_walk_all_labeled_data(dlc))
    assert len(entries) == 2
    # Each entry is (src_png: Path, dest_rel: str, normalised_row: list[str])
    rel_paths = sorted(e[1] for e in entries)
    assert rel_paths == [
        "labeled-data/rat_20260101/img_cam0_0000_00100.png",
        "labeled-data/rat_20260101/img_cam1_0000_00100.png",
    ]


def test_walk_all_labeled_data_yields_view_in_folder(tmp_path):
    """A folder whose name contains _cam<N>_ (DLC legacy) yields rows verbatim."""
    dlc = tmp_path / "dlc"
    ld = dlc / "labeled-data" / "session_cam0_20260101_run"
    _seed(
        ld, "CollectedData_x.csv",
        rows=[
            ["labeled-data/session_cam0_20260101_run/imgABC.png", "5"],
            ["labeled-data/session_cam0_20260101_run/imgDEF.png", "7"],
        ],
        png_names=["imgABC.png", "imgDEF.png"],
    )
    entries = list(_walk_all_labeled_data(dlc))
    assert len(entries) == 2


def test_walk_all_labeled_data_yields_unrecognised_folder(tmp_path):
    """A folder with no _cam<N>_ and plain img names also yields its rows."""
    dlc = tmp_path / "dlc"
    ld = dlc / "labeled-data" / "1873_DAY9_10445_11244_f1"
    _seed(
        ld, "CollectedData_x.csv",
        rows=[
            ["labeled-data/1873_DAY9_10445_11244_f1/img00001.png", "3"],
            ["labeled-data/1873_DAY9_10445_11244_f1/img00002.png", "4"],
        ],
        png_names=["img00001.png", "img00002.png"],
    )
    entries = list(_walk_all_labeled_data(dlc))
    assert len(entries) == 2


def test_walk_all_labeled_data_skips_ipynb_checkpoints(tmp_path):
    """`.ipynb_checkpoints` and hidden dot-folders must not yield rows."""
    dlc = tmp_path / "dlc"
    bad = dlc / "labeled-data" / ".ipynb_checkpoints"
    _seed(bad, "CollectedData_x.csv",
          rows=[["labeled-data/.ipynb_checkpoints/img.png", "1"]],
          png_names=["img.png"])
    assert list(_walk_all_labeled_data(dlc)) == []
```

- [ ] **Step 1.1.2: Run test to verify it fails**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_lp_sv_pretrain.py -v
```
Expected: ImportError on `_walk_all_labeled_data`.

- [ ] **Step 1.1.3: Implement `_walk_all_labeled_data`**

Append to `dlc-3D/src/dlc_3d_bp/lp/converter.py`:
```python
def _walk_all_labeled_data(dlc_dir: "Path | str") -> "Iterator[Tuple[Path, str, List[str]]]":
    """Yield ``(src_png, dest_rel, normalised_row)`` for every labeled row in
    every labeled-data folder of *dlc_dir*, view-agnostically.

    Used by the SV-pretrain converter branch: it doesn't care about pairing or
    folder classification — just every (image, row) tuple that has a backing
    PNG on disk and is referenced in the folder's CollectedData CSV.

    ``dest_rel`` is the relative path the row's first column will carry in the
    output single-view CSV (``labeled-data/<orig_folder>/<orig_filename>.png``).
    ``normalised_row`` is the row after ``_normalize_dlc_row`` flattening (the
    3-col DLC path index → 1 cell).
    """
    dlc_dir = Path(dlc_dir)
    ld = dlc_dir / "labeled-data"
    if not ld.is_dir():
        return
    for folder in sorted(ld.iterdir()):
        if not folder.is_dir():
            continue
        if folder.name.startswith(".") or folder.name.startswith("@"):
            continue
        cc = next(folder.glob("CollectedData_*.csv"), None)
        if cc is None:
            continue
        rows_by_frame = _read_dlc_collected_csv(cc)
        for frame_no, rows in rows_by_frame.items():
            if frame_no == "__header__":
                continue
            for raw_row in rows:
                row = _normalize_dlc_row(raw_row)
                # Path cell after normalisation
                path_cell = row[0]
                # Filename = last segment
                fname = Path(path_cell).name
                src_png = folder / fname
                if not src_png.is_file():
                    # Row references an image not on disk — skip it (DLC
                    # sometimes leaves stale rows after manual deletes).
                    continue
                dest_rel = f"labeled-data/{folder.name}/{fname}"
                yield src_png, dest_rel, row
```

Also add the import at the top of the file if missing:
```python
from typing import Iterator
```

- [ ] **Step 1.1.4: Run tests to verify they pass**

Run:
```bash
python -m pytest tests/test_lp_sv_pretrain.py -v
```
Expected: 4 passed.

- [ ] **Step 1.1.5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/dlc_3d_bp/lp/converter.py dlc-3D/tests/test_lp_sv_pretrain.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): _walk_all_labeled_data — view-agnostic generator"
```

---

### Task 1.2: `_write_sv_config` — single-view canonical config patched for SV pretrain

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/converter.py`
- Modify: `dlc-3D/tests/test_lp_sv_pretrain.py`

- [ ] **Step 1.2.1: Write failing test**

Append to `dlc-3D/tests/test_lp_sv_pretrain.py`:
```python
import yaml

from dlc_3d_bp.lp.converter import _write_sv_config


def test_write_sv_config_emits_singleview_canonical_shape(tmp_path, monkeypatch):
    sv_dir = tmp_path / "sv"
    sv_dir.mkdir()
    # Avoid network in tests — force the vendored fallback
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr("dlc_3d_bp.lp.converter._LP_DEFAULT_CACHE", tmp_path / "no-cache.yaml")

    _write_sv_config(
        sv_dir=sv_dir,
        dlc_dir=tmp_path / "src_dlc",
        bodyparts=["Snout", "Wrist"],
        img_h=480,
        img_w=640,
    )
    cfg = yaml.safe_load((sv_dir / "config.yaml").read_text())
    # Single-view convention: csv_file is a string, no view_names key
    assert cfg["data"]["csv_file"] == "labels.csv"
    assert "view_names" not in cfg["data"]
    # Substituted project-specific values
    assert cfg["data"]["data_dir"] == str(sv_dir)
    assert cfg["data"]["num_keypoints"] == 2
    assert cfg["data"]["keypoint_names"] == ["Snout", "Wrist"]
    assert cfg["data"]["image_orig_dims"] == {"height": 480, "width": 640}
    # ViT-required resize dims (multiple of 128, floor 256)
    assert cfg["data"]["image_resize_dims"]["height"] % 128 == 0
    assert cfg["data"]["image_resize_dims"]["height"] >= 256
    # Stage-1 model setup forces vits_dino + plain heatmap so the backbone
    # state-dict transfers cleanly into MVT in stage 2.
    assert cfg["model"]["backbone"] == "vits_dino"
    assert cfg["model"]["model_type"] == "heatmap"
    # Provenance
    assert cfg["_converter"]["sv_pretrain"] is True
```

- [ ] **Step 1.2.2: Run to verify fail**

Run:
```bash
python -m pytest tests/test_lp_sv_pretrain.py::test_write_sv_config_emits_singleview_canonical_shape -v
```
Expected: ImportError on `_write_sv_config`.

- [ ] **Step 1.2.3: Implement `_write_sv_config`**

Append to `dlc-3D/src/dlc_3d_bp/lp/converter.py`:
```python
def _write_sv_config(
    sv_dir: Path,
    dlc_dir: Path,
    bodyparts: list,
    img_h: int,
    img_w: int,
) -> None:
    """Write the single-view config.yaml for the SV-pretrain sub-project.

    Source of truth is LP's canonical ``config_default.yaml`` (single-view),
    patched with the project-specific fields. Stage-1 forces
    ``model.backbone = vits_dino`` and ``model.model_type = heatmap`` so the
    resulting checkpoint's backbone state-dict transfers cleanly into MVT's
    ``HeatmapTrackerMultiviewTransformer`` (which also uses vits_dino) via
    LP's existing ``backbone.*``-only fallback in
    ``lightning_pose/utils/scripts.py``.
    """
    cfg = _load_upstream_default_config()

    # ViT requires square image_resize_dims that's a multiple of 128.
    side = max(256, (min(img_h, img_w) // 128) * 128)

    data = cfg.setdefault("data", {})
    data["data_dir"] = str(sv_dir)
    # SV-pretrain uses the parent's videos dir (relative). Useful only if
    # unsupervised losses are later enabled; harmless to point here otherwise.
    data["video_dir"] = "../videos"
    data["csv_file"] = "labels.csv"
    data["num_keypoints"] = len(bodyparts)
    data["keypoint_names"] = bodyparts
    data["image_orig_dims"] = {"height": img_h, "width": img_w}
    data["image_resize_dims"] = {"height": side, "width": side}
    # Single-view explicitly drops view_names (LP raises if N == 1)
    data.pop("view_names", None)

    model = cfg.setdefault("model", {})
    model["backbone"] = "vits_dino"
    model["model_type"] = "heatmap"
    # Carry through canonical losses_to_use=[], heatmap_loss_type=mse, etc.

    cfg["_converter"] = {
        "source_dlc_dir": str(dlc_dir),
        "sv_pretrain": True,
        "lp_default_ref": LP_DEFAULT_CONFIG_REF,
    }

    with (sv_dir / "config.yaml").open("w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
```

- [ ] **Step 1.2.4: Run tests to verify they pass**

Run:
```bash
python -m pytest tests/test_lp_sv_pretrain.py -v
```
Expected: 5 passed.

- [ ] **Step 1.2.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/converter.py dlc-3D/tests/test_lp_sv_pretrain.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): _write_sv_config — single-view canonical for SV pretrain"
```

---

### Task 1.3: `_build_sv_pretrain_project` — orchestrate the SV sub-project build

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/converter.py`
- Modify: `dlc-3D/tests/test_lp_sv_pretrain.py`

- [ ] **Step 1.3.1: Write failing tests**

Append to `dlc-3D/tests/test_lp_sv_pretrain.py`:
```python
from dlc_3d_bp.lp.converter import _build_sv_pretrain_project


def test_build_sv_pretrain_project_writes_layout(tmp_path, monkeypatch):
    """SV pretrain dir has config.yaml + labels.csv + labeled-data/<folder>/<png>."""
    dlc = tmp_path / "dlc"
    (dlc / "config.yaml").write_text("bodyparts:\n  - Snout\n")
    # Two heterogeneous source folders
    _seed(
        dlc / "labeled-data" / "rat_view_in_filename",
        "CollectedData_x.csv",
        rows=[
            ["labeled-data", "rat_view_in_filename", "img_cam0_0000_00100.png", "10"],
            ["labeled-data", "rat_view_in_filename", "img_cam1_0000_00100.png", "20"],
        ],
        png_names=["img_cam0_0000_00100.png", "img_cam1_0000_00100.png"],
    )
    _seed(
        dlc / "labeled-data" / "session_cam0_20260101",
        "CollectedData_x.csv",
        rows=[
            ["labeled-data/session_cam0_20260101/imgZZZ.png", "5"],
        ],
        png_names=["imgZZZ.png"],
    )

    # Force vendored fallback (no network)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr("dlc_3d_bp.lp.converter._LP_DEFAULT_CACHE", tmp_path / "no-cache.yaml")

    lp_dir = tmp_path / "lp"
    lp_dir.mkdir()

    n_rows = _build_sv_pretrain_project(lp_dir=lp_dir, dlc_dir=dlc, bodyparts=["Snout"])
    assert n_rows == 3  # 2 + 1

    sv = lp_dir / "sv-pretrain"
    assert (sv / "config.yaml").is_file()
    assert (sv / "labels.csv").is_file()
    # PNGs hardlinked into sv-pretrain/labeled-data/<folder>/<png>
    assert (sv / "labeled-data" / "rat_view_in_filename" / "img_cam0_0000_00100.png").is_file()
    assert (sv / "labeled-data" / "session_cam0_20260101" / "imgZZZ.png").is_file()

    # labels.csv: 3 header rows + 3 data rows
    with (sv / "labels.csv").open() as f:
        lines = f.readlines()
    assert len(lines) == 6
    # First data row's path cell is the dest_rel (1-col, not 3-col split)
    data_rows = [l for l in lines if l.strip().startswith("labeled-data/")]
    assert len(data_rows) == 3
```

- [ ] **Step 1.3.2: Run to verify fail**

Run:
```bash
python -m pytest tests/test_lp_sv_pretrain.py::test_build_sv_pretrain_project_writes_layout -v
```
Expected: ImportError on `_build_sv_pretrain_project`.

- [ ] **Step 1.3.3: Implement**

Append to `dlc-3D/src/dlc_3d_bp/lp/converter.py`:
```python
def _build_sv_pretrain_project(
    lp_dir: Path,
    dlc_dir: Path,
    bodyparts: list,
) -> int:
    """Build ``<lp_dir>/sv-pretrain/`` from every labeled row in *dlc_dir*.

    1. Hardlinks every labeled PNG into ``sv-pretrain/labeled-data/<orig_folder>/<png>``.
    2. Writes one flat ``labels.csv`` (LP single-view convention) containing
       every labeled row, normalised to a single path column.
    3. Writes ``sv-pretrain/config.yaml`` via ``_write_sv_config``.

    Returns the number of data rows in ``labels.csv``.
    """
    sv = lp_dir / "sv-pretrain"
    sv.mkdir(parents=True, exist_ok=True)
    (sv / "labeled-data").mkdir(exist_ok=True)

    # Collect all rows + first-row image to probe dims
    header_seen: List[List[str]] = []
    data_rows: List[List[str]] = []
    first_png: Path | None = None
    for src_png, dest_rel, row in _walk_all_labeled_data(dlc_dir):
        # Hardlink PNG into the SV labeled-data tree
        dst_png = sv / dest_rel
        _link_or_copy(src_png, dst_png, mode="link")
        # Force-rewrite the row's path cell to the dest_rel (so LP resolves
        # against sv-pretrain/labeled-data/)
        row = [dest_rel] + list(row[1:])
        data_rows.append(row)
        if first_png is None:
            first_png = src_png

        # Capture one header set lazily (any folder's headers work — same schema)
        if not header_seen:
            cc = src_png.parent.glob("CollectedData_*.csv")
            cc_path = next(cc, None)
            if cc_path is not None:
                import csv as _csv
                with cc_path.open(newline="") as f:
                    for r in _csv.reader(f):
                        if r and r[0] in ("scorer", "bodyparts", "coords", "individuals"):
                            header_seen.append(_normalize_header_row(r))
                        else:
                            break

    # Probe image dims from any one labeled PNG (fallback to sv labeled-data scan)
    if first_png is None:
        img_h, img_w = _probe_image_dims(sv)
    else:
        img_h, img_w = _probe_image_dims(first_png.parent.parent)

    # Write labels.csv: headers from any source folder + every data row
    import csv as _csv
    with (sv / "labels.csv").open("w", newline="") as f:
        w = _csv.writer(f)
        for hrow in header_seen:
            w.writerow(hrow)
        for row in data_rows:
            w.writerow(row)

    _write_sv_config(sv_dir=sv, dlc_dir=dlc_dir, bodyparts=bodyparts,
                     img_h=img_h, img_w=img_w)
    return len(data_rows)
```

- [ ] **Step 1.3.4: Run tests to verify they pass**

Run:
```bash
python -m pytest tests/test_lp_sv_pretrain.py -v
```
Expected: 6 passed.

- [ ] **Step 1.3.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/converter.py dlc-3D/tests/test_lp_sv_pretrain.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): _build_sv_pretrain_project — flat SV labels for stage-1"
```

---

### Task 1.4: Wire `_build_sv_pretrain_project` into `convert_dlc_to_lp`

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/converter.py`
- Modify: `dlc-3D/tests/test_lp_sv_pretrain.py`

- [ ] **Step 1.4.1: Write failing test**

Append to `dlc-3D/tests/test_lp_sv_pretrain.py`:
```python
from dlc_3d_bp.lp.converter import convert_dlc_to_lp


def test_convert_emits_sv_pretrain_sibling(tmp_path, monkeypatch):
    """convert_dlc_to_lp summary includes sv_pretrain_dir + n_sv_rows."""
    dlc = tmp_path / "dlc"
    (dlc / "config.yaml").write_text("bodyparts:\n  - Snout\n")
    ld = dlc / "labeled-data" / "rat_20260101"
    _seed(
        ld, "CollectedData_x.csv",
        rows=[
            ["labeled-data", "rat_20260101", "img_cam0_0000_00100.png", "10"],
            ["labeled-data", "rat_20260101", "img_cam1_0000_00100.png", "20"],
        ],
        png_names=["img_cam0_0000_00100.png", "img_cam1_0000_00100.png"],
    )

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr("dlc_3d_bp.lp.converter._LP_DEFAULT_CACHE", tmp_path / "no-cache.yaml")

    lp_dir = tmp_path / "lp"
    summary = convert_dlc_to_lp(dlc, lp_dir)

    assert "sv_pretrain_dir" in summary
    assert summary["sv_pretrain_dir"].endswith("sv-pretrain")
    assert summary["n_sv_rows"] == 2
    assert (Path(summary["sv_pretrain_dir"]) / "config.yaml").is_file()
    assert (Path(summary["sv_pretrain_dir"]) / "labels.csv").is_file()
```

- [ ] **Step 1.4.2: Run to verify fail**

Run:
```bash
python -m pytest tests/test_lp_sv_pretrain.py::test_convert_emits_sv_pretrain_sibling -v
```
Expected: AssertionError — summary keys missing.

- [ ] **Step 1.4.3: Edit `convert_dlc_to_lp`**

In `dlc-3D/src/dlc_3d_bp/lp/converter.py`, locate the existing `_write_lp_config(lp_dir, dlc_dir, all_views)` call near the end of `convert_dlc_to_lp` (around line 400). Immediately after it, BEFORE `return summary.asdict()`, add:
```python
    # ── 7. Build the nested SV-pretrain sub-project ─────────────────
    try:
        n_sv = _build_sv_pretrain_project(lp_dir, dlc_dir, bodyparts)
    except Exception as e:
        summary.warnings.append(f"sv-pretrain build failed: {e}")
        n_sv = 0

    summary_dict = summary.asdict()
    summary_dict["sv_pretrain_dir"] = str(lp_dir / "sv-pretrain")
    summary_dict["n_sv_rows"] = n_sv
    return summary_dict
```

ALSO update the `bodyparts` extraction so it's accessible to that block — it's already computed early in `convert_dlc_to_lp`. Verify with:
```bash
grep -n "bodyparts = " src/dlc_3d_bp/lp/converter.py | head
```
The `bodyparts` local must be in scope at the new call site. If not, move its assignment up.

Then change the SINGLE existing `return summary.asdict()` (there should only be one at the end of the function — the early-return for "no views" also uses it; keep that one unchanged with no SV fields, since no views means an empty project anyway).

- [ ] **Step 1.4.4: Run tests**

Run:
```bash
python -m pytest tests/test_lp_sv_pretrain.py tests/test_lp_converter.py -v
```
Expected: all pass (SV tests + existing converter tests still green).

- [ ] **Step 1.4.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/converter.py dlc-3D/tests/test_lp_sv_pretrain.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): convert emits nested sv-pretrain sub-project"
```

---

## Phase 2 — Train runner: stage-1 config + checkpoint discovery

### Task 2.1: `find_best_checkpoint`

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/train_runner.py`
- Create: `dlc-3D/tests/test_lp_two_stage_task.py`

- [ ] **Step 2.1.1: Write failing test**

Create `dlc-3D/tests/test_lp_two_stage_task.py`:
```python
"""Tests for two-stage training: checkpoint discovery + task orchestration."""
from pathlib import Path

import pytest

from dlc_3d_bp.lp.train_runner import find_best_checkpoint


def test_find_best_checkpoint_returns_newest_best(tmp_path):
    """When multiple *-best.ckpt files exist, return the newest by mtime."""
    base = tmp_path / "stage1" / "tb_logs" / "test" / "version_0" / "checkpoints"
    base.mkdir(parents=True)
    a = base / "epoch=0-step=100-best.ckpt"; a.write_bytes(b"a"); import os, time
    time.sleep(0.01)
    b = base / "epoch=5-step=600-best.ckpt"; b.write_bytes(b"b")
    assert find_best_checkpoint(tmp_path / "stage1") == b


def test_find_best_checkpoint_falls_back_to_last(tmp_path):
    """No *-best.ckpt → return the only .ckpt file present."""
    base = tmp_path / "stage1" / "tb_logs" / "test" / "version_0" / "checkpoints"
    base.mkdir(parents=True)
    only = base / "epoch=10-step=1000.ckpt"; only.write_bytes(b"x")
    assert find_best_checkpoint(tmp_path / "stage1") == only


def test_find_best_checkpoint_returns_none_when_absent(tmp_path):
    (tmp_path / "stage1").mkdir()
    assert find_best_checkpoint(tmp_path / "stage1") is None
```

- [ ] **Step 2.1.2: Verify fail**

Run:
```bash
python -m pytest tests/test_lp_two_stage_task.py::test_find_best_checkpoint_returns_newest_best -v
```
Expected: ImportError.

- [ ] **Step 2.1.3: Implement**

Append to `dlc-3D/src/dlc_3d_bp/lp/train_runner.py`:
```python
def find_best_checkpoint(model_dir: Path | str) -> Path | None:
    """Return the newest ``*-best.ckpt`` under ``<model_dir>/tb_logs/.../checkpoints/``.

    Falls back to any ``*.ckpt`` if no *-best is present. Returns None when
    no checkpoint exists at all.
    """
    model_dir = Path(model_dir)
    best = list(model_dir.glob("tb_logs/*/version_*/checkpoints/*-best.ckpt"))
    if best:
        return max(best, key=lambda p: p.stat().st_mtime)
    any_ckpt = list(model_dir.glob("tb_logs/*/version_*/checkpoints/*.ckpt"))
    if any_ckpt:
        return max(any_ckpt, key=lambda p: p.stat().st_mtime)
    return None
```

- [ ] **Step 2.1.4: Run tests**

Run:
```bash
python -m pytest tests/test_lp_two_stage_task.py -v
```
Expected: 3 passed.

- [ ] **Step 2.1.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/train_runner.py dlc-3D/tests/test_lp_two_stage_task.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): find_best_checkpoint — locate stage-1 ckpt for stage-2 transfer"
```

---

### Task 2.2: `build_stage1_config` — short curriculum with early stopping

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/train_runner.py`
- Modify: `dlc-3D/tests/test_lp_two_stage_task.py`

- [ ] **Step 2.2.1: Write failing test**

Append to `dlc-3D/tests/test_lp_two_stage_task.py`:
```python
import yaml
from dlc_3d_bp.lp.train_runner import build_stage1_config


def test_build_stage1_config_emits_short_run_with_early_stopping(tmp_path):
    # Source SV config (mock — just needs to be valid YAML)
    sv = tmp_path / "sv"; sv.mkdir()
    (sv / "config.yaml").write_text(yaml.safe_dump({
        "data": {"csv_file": "labels.csv", "video_dir": "../videos"},
        "model": {"backbone": "vits_dino", "model_type": "heatmap"},
        "training": {"max_epochs": 300, "min_epochs": 300, "early_stopping": False},
    }))

    out_dir = tmp_path / "run" / "stage1"
    out_dir.mkdir(parents=True)
    build_stage1_config(sv_project=sv, out_dir=out_dir, options={
        "stage1_max_epochs": 50,
        "stage1_early_stop_patience": 4,
    })

    cfg = yaml.safe_load((out_dir / "config.yaml").read_text())
    assert cfg["training"]["max_epochs"] == 50
    assert cfg["training"]["min_epochs"] <= 50
    assert cfg["training"]["early_stopping"] is True
    assert cfg["training"]["early_stop_patience"] == 4
```

- [ ] **Step 2.2.2: Verify fail**

Run:
```bash
python -m pytest tests/test_lp_two_stage_task.py::test_build_stage1_config_emits_short_run_with_early_stopping -v
```
Expected: ImportError.

- [ ] **Step 2.2.3: Implement**

Append to `dlc-3D/src/dlc_3d_bp/lp/train_runner.py`:
```python
def build_stage1_config(
    sv_project: Path | str,
    out_dir: Path | str,
    options: dict,
) -> None:
    """Materialise stage-1's config.yaml at ``<out_dir>/config.yaml``.

    Starts from the SV-pretrain project's ``config.yaml`` and overlays
    short-run + early-stopping defaults so stage 1 finishes quickly once
    val loss plateaus.
    """
    sv_cfg_path = Path(sv_project) / "config.yaml"
    cfg = yaml.safe_load(sv_cfg_path.read_text()) or {}
    training = cfg.setdefault("training", {})
    max_epochs = int(options.get("stage1_max_epochs", 100))
    training["max_epochs"] = max_epochs
    training["min_epochs"] = min(training.get("min_epochs", 1) or 1, max_epochs)
    training["early_stopping"] = True
    training["early_stop_patience"] = int(options.get("stage1_early_stop_patience", 5))
    # No unsupervised losses, no patch masking, no reproj for stage 1.
    cfg.setdefault("losses", {})
    cfg.setdefault("callbacks", {})
    Path(out_dir, "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
```

- [ ] **Step 2.2.4: Run tests**

Run:
```bash
python -m pytest tests/test_lp_two_stage_task.py -v
```
Expected: 4 passed.

- [ ] **Step 2.2.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/train_runner.py dlc-3D/tests/test_lp_two_stage_task.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): build_stage1_config — short curriculum + early stopping"
```

---

## Phase 3 — `lp_train` task: branch on `two_stage`

### Task 3.1: Orchestrator runs both stages, propagates checkpoint

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/tasks.py`
- Modify: `dlc-3D/tests/test_lp_two_stage_task.py`

- [ ] **Step 3.1.1: Write failing test**

Append to `dlc-3D/tests/test_lp_two_stage_task.py`:
```python
import sys, types
from unittest.mock import patch, MagicMock


def _make_celery_self():
    """A stand-in for the bound `self` on a Celery task — enough surface for
    the task body to call update_state and access request.id."""
    s = MagicMock()
    s.request = MagicMock()
    s.request.id = "fake-task-id"
    return s


def test_lp_train_two_stage_runs_both_stages(tmp_path, monkeypatch):
    """When options.two_stage is True, the task invokes run_predict_subprocess-
    style litpose twice — once on sv-pretrain, once on the parent — and the
    stage-2 config gets model.checkpoint set to stage-1's best ckpt."""
    # Build a synthetic LP project layout
    lp = tmp_path / "lp"; lp.mkdir()
    (lp / "config.yaml").write_text("data:\n  view_names:\n    - cam0\n    - cam1\nmodel: {}\ntraining: {}\nlosses: {}\ncallbacks: {}\neval: {}\n")
    sv = lp / "sv-pretrain"; sv.mkdir()
    (sv / "config.yaml").write_text("data: {csv_file: labels.csv}\nmodel: {backbone: vits_dino, model_type: heatmap}\ntraining: {min_epochs: 1, max_epochs: 1}\nlosses: {}\ncallbacks: {}\neval: {}\n")

    calls = []

    def _fake_subprocess(model_dir, *, log_callback=None, **kw):
        # Record the call and synthesise the ckpt that find_best_checkpoint expects
        calls.append(("subprocess", Path(model_dir)))
        ckpt_dir = Path(model_dir) / "tb_logs" / "test" / "version_0" / "checkpoints"
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        (ckpt_dir / "epoch=0-step=10-best.ckpt").write_bytes(b"\x00")
        return 0  # success

    monkeypatch.setattr("dlc_3d_bp.lp.train_runner.run_train_subprocess", _fake_subprocess)
    monkeypatch.setattr("dlc_3d_bp.lp.predict_runner.relocate_predictions", lambda *a, **kw: {"moved":0,"skipped":[],"dest_dir":None,"dest_paths":[]})

    from dlc_3d_bp.lp.tasks import lp_train

    options = {
        "two_stage": True,
        "stage1_max_epochs": 1,
        "max_epochs": 1,
        "batch_size": 2,
    }
    # Call the task body bypassing Celery
    result = lp_train.__wrapped__(_make_celery_self(), str(lp), options)

    # Two subprocess invocations
    assert len(calls) == 2
    stage1_dir, stage2_dir = calls[0][1], calls[1][1]
    assert stage1_dir.name == "stage1"
    assert stage2_dir.name == "stage2"

    # Stage-2 config carries the stage-1 ckpt
    s2_cfg_path = stage2_dir / "config.yaml"
    cfg = yaml.safe_load(s2_cfg_path.read_text())
    assert cfg["model"]["checkpoint"].endswith("-best.ckpt")
    assert "stage1" in cfg["model"]["checkpoint"]


def test_lp_train_two_stage_skips_stage1_when_override_set(tmp_path, monkeypatch):
    """options.stage1_ckpt_override → skip stage 1, run stage 2 only with that ckpt."""
    lp = tmp_path / "lp"; lp.mkdir()
    (lp / "config.yaml").write_text("data:\n  view_names:\n    - cam0\n    - cam1\nmodel: {}\ntraining: {}\nlosses: {}\ncallbacks: {}\neval: {}\n")
    (lp / "sv-pretrain").mkdir()
    (lp / "sv-pretrain" / "config.yaml").write_text("data: {}\nmodel: {}\ntraining: {}\nlosses: {}\ncallbacks: {}\neval: {}\n")

    fake_ckpt = tmp_path / "external" / "epoch=99-best.ckpt"
    fake_ckpt.parent.mkdir(parents=True)
    fake_ckpt.write_bytes(b"x")

    calls = []
    def _fake_subprocess(model_dir, *, log_callback=None, **kw):
        calls.append(Path(model_dir))
        return 0
    monkeypatch.setattr("dlc_3d_bp.lp.train_runner.run_train_subprocess", _fake_subprocess)
    monkeypatch.setattr("dlc_3d_bp.lp.predict_runner.relocate_predictions", lambda *a, **kw: {"moved":0,"skipped":[],"dest_dir":None,"dest_paths":[]})

    from dlc_3d_bp.lp.tasks import lp_train
    lp_train.__wrapped__(_make_celery_self(), str(lp), {
        "two_stage": True,
        "stage1_ckpt_override": str(fake_ckpt),
        "max_epochs": 1, "batch_size": 2,
    })

    # Only one subprocess call (stage 2)
    assert len(calls) == 1
    assert calls[0].name == "stage2"
    # Stage 2 config has the override checkpoint
    cfg = yaml.safe_load((calls[0] / "config.yaml").read_text())
    assert cfg["model"]["checkpoint"] == str(fake_ckpt)


def test_lp_train_two_stage_fails_on_no_stage1_checkpoint(tmp_path, monkeypatch):
    """Stage 1 finishes (rc=0) but no ckpt → RuntimeError surfaces."""
    lp = tmp_path / "lp"; lp.mkdir()
    (lp / "config.yaml").write_text("data:\n  view_names:\n    - cam0\n    - cam1\nmodel: {}\ntraining: {}\nlosses: {}\ncallbacks: {}\neval: {}\n")
    (lp / "sv-pretrain").mkdir()
    (lp / "sv-pretrain" / "config.yaml").write_text("data: {}\nmodel: {}\ntraining: {}\nlosses: {}\ncallbacks: {}\neval: {}\n")

    def _fake_subprocess(model_dir, *, log_callback=None, **kw):
        # Don't write any ckpt
        return 0
    monkeypatch.setattr("dlc_3d_bp.lp.train_runner.run_train_subprocess", _fake_subprocess)

    from dlc_3d_bp.lp.tasks import lp_train
    with pytest.raises(RuntimeError, match="stage 1 produced no checkpoint"):
        lp_train.__wrapped__(_make_celery_self(), str(lp), {"two_stage": True})
```

- [ ] **Step 3.1.2: Verify fail**

Run:
```bash
python -m pytest tests/test_lp_two_stage_task.py -v
```
Expected: the three new tests fail — `lp_train` doesn't branch on `two_stage` yet.

- [ ] **Step 3.1.3: Edit `lp_predict`'s sibling — `lp_train` body**

In `dlc-3D/src/dlc_3d_bp/lp/tasks.py`, replace the existing `lp_train` function (the whole `@celery.task` decorator + body) with:
```python
@celery.task(bind=True, name="dlc_3d_lp.train")
def lp_train(self, lp_project: str, options: dict) -> dict:
    """Train an LP model. Single-stage MVT by default; two-stage curriculum
    (SV-pretrain → MVT with backbone transfer) when ``options.two_stage`` is True."""
    import os
    from pathlib import Path as _Path
    from .train_runner import (
        build_train_config,
        build_stage1_config,
        find_best_checkpoint,
        make_run_dir,
        run_train_subprocess,
    )

    proj = _Path(lp_project)
    if not (proj / "config.yaml").is_file():
        raise FileNotFoundError(f"LP project config not found at {proj}/config.yaml")

    log_key = f"dlc3d:lp:log:{self.request.id}"
    try:
        import redis
        rconn = redis.Redis.from_url(
            os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0"),
            decode_responses=True,
        )
    except Exception:
        rconn = None

    def emit(line: str, **meta) -> None:
        if rconn:
            try:
                rconn.rpush(log_key, line); rconn.ltrim(log_key, -2000, -1)
            except Exception:
                pass
        self.update_state(state="STARTED",
                          meta={"last_line": line, "lp_project": str(proj), **meta})

    # ── Two-stage branch ────────────────────────────────────────────────
    two_stage = bool(options.get("two_stage", False))
    override_ckpt = (options.get("stage1_ckpt_override") or "").strip()

    if two_stage:
        run_root = make_run_dir(proj)  # <proj>/models/<timestamp>/
        stage1_dir = run_root / "stage1"
        stage2_dir = run_root / "stage2"

        stage1_ckpt: _Path | None = None
        if override_ckpt:
            emit(f"two-stage: using override ckpt {override_ckpt} — skipping stage 1",
                 stage="stage1_override")
            stage1_ckpt = _Path(override_ckpt)
        else:
            sv_project = proj / "sv-pretrain"
            if not (sv_project / "config.yaml").is_file():
                raise FileNotFoundError(
                    f"two-stage requested but {sv_project}/config.yaml missing; "
                    "re-run convert with a current converter to emit sv-pretrain"
                )
            stage1_dir.mkdir(parents=True, exist_ok=True)
            build_stage1_config(sv_project=sv_project, out_dir=stage1_dir, options=options)
            emit("two-stage: STAGE 1 starting (sv-pretrain)", stage="stage1_training")
            rc = run_train_subprocess(stage1_dir, log_callback=lambda l: emit(l, stage="stage1_training"))
            if rc != 0:
                raise RuntimeError(f"stage 1 litpose train exited with code {rc}")
            stage1_ckpt = find_best_checkpoint(stage1_dir)
            if stage1_ckpt is None:
                raise RuntimeError(f"stage 1 produced no checkpoint under {stage1_dir}")
            emit(f"two-stage: STAGE 1 done — ckpt {stage1_ckpt}", stage="stage1_done")

        # Stage 2 (MVT)
        stage2_dir.mkdir(parents=True, exist_ok=True)
        stage2_options = dict(options)
        # Strip stage-1 keys so build_train_config doesn't see them
        for k in ("two_stage", "stage1_max_epochs", "stage1_early_stop_patience", "stage1_ckpt_override"):
            stage2_options.pop(k, None)
        build_train_config(proj / "config.yaml", stage2_dir / "config.yaml", stage2_options)

        # Inject model.checkpoint into the just-written stage-2 config
        s2_cfg_path = stage2_dir / "config.yaml"
        s2_cfg = yaml.safe_load(s2_cfg_path.read_text())
        s2_cfg.setdefault("model", {})["checkpoint"] = str(stage1_ckpt)
        s2_cfg_path.write_text(yaml.safe_dump(s2_cfg, sort_keys=False))

        emit("two-stage: STAGE 2 starting (MVT with backbone transfer)", stage="stage2_training")
        rc = run_train_subprocess(stage2_dir, log_callback=lambda l: emit(l, stage="stage2_training"))
        if rc != 0:
            raise RuntimeError(f"stage 2 litpose train exited with code {rc}")
        emit("two-stage: STAGE 2 done", stage="stage2_done")
        return {
            "status": "ok",
            "lp_project": str(proj),
            "run_dir": str(run_root),
            "stage1_ckpt": str(stage1_ckpt),
            "stage": "stage2_done",
        }

    # ── Single-stage MVT branch (existing behaviour, unchanged contract) ─
    run_dir = make_run_dir(proj)
    build_train_config(proj / "config.yaml", run_dir / "config.yaml", options)
    rc = run_train_subprocess(run_dir, log_callback=emit)
    if rc != 0:
        raise RuntimeError(f"litpose train exited with code {rc}")
    return {"status": "ok", "lp_project": str(proj), "run_dir": str(run_dir), "stage": "done"}
```

Make sure `import yaml` is at the top of `tasks.py`. Add it if absent.

- [ ] **Step 3.1.4: Run tests**

Run:
```bash
python -m pytest tests/test_lp_two_stage_task.py tests/test_lp_routes.py -v
```
Expected: all pass.

- [ ] **Step 3.1.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/tasks.py dlc-3D/tests/test_lp_two_stage_task.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): lp_train branches on two_stage — runs SV pretrain then MVT"
```

---

## Phase 4 — UI: Pretraining fieldset on Card 2

### Task 4.1: Card 2 markup + JS wiring

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_lp_train.html`
- Modify: `dlc-3D/src/static/lp_cards.js`

- [ ] **Step 4.1.1: Add Pretraining fieldset to the card**

In `dlc-3D/src/templates/partials/card_lp_train.html`, find the existing `<fieldset class="lp-group"><legend>Training</legend>` (the one with `lp-train-epochs`, `lp-train-batch`, etc.). Insert this NEW fieldset IMMEDIATELY BEFORE it:
```html
  <fieldset class="lp-group">
    <legend>Pretraining</legend>
    <div class="lp-field lp-checkbox">
      <input type="checkbox" id="lp-train-two-stage">
      <label for="lp-train-two-stage">Pretrain ViT backbone on all labels (single-view first, then MVT)</label>
    </div>
    <div class="lp-row" id="lp-train-two-stage-params" style="display:none">
      <label>Stage 1 max epochs <input type="number" id="lp-train-stage1-epochs" value="100" min="1"></label>
      <label>Stage 1 early-stop patience <input type="number" id="lp-train-stage1-patience" value="5" min="1"></label>
    </div>
    <div class="lp-field" id="lp-train-stage1-override-wrap" style="display:none">
      <label>Existing stage-1 checkpoint <span style="color:var(--text-dim);font-weight:400;text-transform:none;letter-spacing:0">(optional; skip stage 1)</span></label>
      <input type="text" id="lp-train-stage1-override" placeholder="/user-data/.../tb_logs/.../checkpoints/epoch=...-best.ckpt">
    </div>
  </fieldset>
```

- [ ] **Step 4.1.2: Wire the toggle + payload**

In `dlc-3D/src/static/lp_cards.js`, find `initTrainCard()`'s click handler. Locate the `const options = { ... };` literal. Add the new keys to it, AND add the visibility toggle. The relevant changes:

Find:
```javascript
  $("#lp-train-reproj")?.addEventListener("change", (e) => {
    $("#lp-train-reproj-params").style.display = e.target.checked ? "flex" : "none";
  });
```
And immediately AFTER it, add:
```javascript
  $("#lp-train-two-stage")?.addEventListener("change", (e) => {
    $("#lp-train-two-stage-params").style.display = e.target.checked ? "flex" : "none";
    $("#lp-train-stage1-override-wrap").style.display = e.target.checked ? "block" : "none";
  });
```

Find the `const options = {` literal that contains `mvt_enabled: $("#lp-train-mvt").checked,` etc. Add these three keys to it:
```javascript
      two_stage:                 $("#lp-train-two-stage").checked,
      stage1_max_epochs:         +$("#lp-train-stage1-epochs").value,
      stage1_early_stop_patience:+$("#lp-train-stage1-patience").value,
      stage1_ckpt_override:      $("#lp-train-stage1-override").value.trim(),
```

Find the existing `await pollJob(jobId, (j) => { ... }, 2500);` block in `initTrainCard`. Inside the callback, find:
```javascript
        resEl.textContent =
          `state: ${j.celery_state || "PENDING"}\n` +
          `run_dir: ${j.options?.lp_project || ""}\n` +
          `--- log tail ---\n${tail}`;
```
Replace with:
```javascript
        const stage = j.celery_info?.stage || "";
        resEl.textContent =
          `state: ${j.celery_state || "PENDING"}\n` +
          (stage ? `stage: ${stage}\n` : "") +
          `run_dir: ${j.celery_info?.lp_project || j.options?.lp_project || ""}\n` +
          `--- log tail ---\n${tail}`;
```

- [ ] **Step 4.1.3: Restart dlc-3d and confirm assets are served**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d
sleep 3
docker compose exec dlc-3d python3 -c "
import urllib.request
html = urllib.request.urlopen('http://localhost:5050/dlc-3d/').read().decode()
for needed in ('lp-train-two-stage', 'lp-train-stage1-epochs', 'lp-train-stage1-patience', 'lp-train-stage1-override'):
    assert f'id=\"{needed}\"' in html, needed
print('all two-stage DOM ids present')
js = urllib.request.urlopen('http://localhost:5050/dlc-3d/static/lp_cards.js').read().decode()
assert 'two_stage' in js
assert 'lp-train-two-stage' in js
print('lp_cards.js carries two_stage wiring')
"
```
Expected: both lines print.

- [ ] **Step 4.1.4: Run unit tests one more time — no regressions**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q --ignore=tests/e2e
```
Expected: all green.

- [ ] **Step 4.1.5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/partials/card_lp_train.html dlc-3D/src/static/lp_cards.js
git -c commit.gpgsign=false commit -m "feat(dlc-3d): Train card — Pretraining fieldset (two-stage toggle)"
```

---

## Phase 5 — Live smoke test

### Task 5.1: Full convert → two-stage train against DREADD-Ali

- [ ] **Step 5.1.1: Restart worker to pick up the new task code**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d-worker
sleep 5
docker compose logs --tail=30 dlc-3d-worker | grep -E "ready|error|Traceback"
```
Expected: `celery@…ready`, no traceback.

- [ ] **Step 5.1.2: Re-convert with the new converter**

```bash
docker compose exec dlc-3d python3 -c "
import urllib.request, json
req = urllib.request.Request(
    'http://localhost:5050/dlc-3d/lp/convert',
    data=json.dumps({
        'dlc_dir': '/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07',
        'lp_dir':  '/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-2STAGE-TEST',
        'force':   True,
    }).encode(),
    headers={'Content-Type':'application/json'},
)
print(json.loads(urllib.request.urlopen(req).read()))
"
```
Expected: `sv_pretrain_dir` and `n_sv_rows` in the JSON, `n_sv_rows > n_frames` (paired count).

- [ ] **Step 5.1.3: Inspect the SV sub-project**

```bash
ls /home/sam/Parra-Lab-Data-NAS/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-2STAGE-TEST/sv-pretrain/
wc -l /home/sam/Parra-Lab-Data-NAS/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-2STAGE-TEST/sv-pretrain/labels.csv
ls /home/sam/Parra-Lab-Data-NAS/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-2STAGE-TEST/sv-pretrain/labeled-data/ | head
```
Expected: `config.yaml`, `labels.csv` (many rows), `labeled-data/` with multiple session folders.

- [ ] **Step 5.1.4: Kick a tiny two-stage job (1 epoch each)**

```bash
docker compose exec dlc-3d python3 -c "
import urllib.request, json
req = urllib.request.Request(
    'http://localhost:5050/dlc-3d/lp/train',
    data=json.dumps({
        'lp_project': '/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-2STAGE-TEST',
        'options': {
            'two_stage': True,
            'stage1_max_epochs': 1,
            'stage1_early_stop_patience': 1,
            'mvt_enabled': True,
            'max_epochs': 1,
            'batch_size': 2,
        },
    }).encode(),
    headers={'Content-Type':'application/json'},
)
print(json.loads(urllib.request.urlopen(req).read()))
"
```
Note the `job_id`.

- [ ] **Step 5.1.5: Poll to terminal**

```bash
JOB=<paste job_id>
for i in $(seq 1 60); do
  sleep 30
  docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml exec dlc-3d python3 -c "
import urllib.request, json
b = json.loads(urllib.request.urlopen('http://localhost:5050/dlc-3d/lp/job/$JOB').read())
print(b.get('celery_state'), '||', (b.get('celery_info') or {}).get('stage',''), '||', (b.get('celery_info') or {}).get('last_line','')[:100])
"
  # Stop when terminal
  docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml exec dlc-3d python3 -c "
import urllib.request, json
b = json.loads(urllib.request.urlopen('http://localhost:5050/dlc-3d/lp/job/$JOB').read())
import sys; sys.exit(0 if b.get('celery_state') in ('SUCCESS','FAILURE','REVOKED') else 1)
" && break
done
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml exec dlc-3d python3 -c "
import urllib.request, json
b = json.loads(urllib.request.urlopen('http://localhost:5050/dlc-3d/lp/job/$JOB').read())
print('STATE:', b.get('celery_state'))
print('INFO:', b.get('celery_info'))
print('LAST 20:')
for line in (b.get('log_tail') or [])[-20:]: print(' ', line[:200])
"
```
Expected: `STATE: SUCCESS`, INFO mentions `stage: stage2_done`, log contains both "STAGE 1 starting" and "STAGE 2 starting" lines.

- [ ] **Step 5.1.6: Verify run dir layout**

```bash
ls /home/sam/Parra-Lab-Data-NAS/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-2STAGE-TEST/models/
ls /home/sam/Parra-Lab-Data-NAS/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-2STAGE-TEST/models/*/
```
Expected: newest `models/<timestamp>/` contains both `stage1/` and `stage2/`. Each has a `config.yaml` and `tb_logs/`. Stage 2's `config.yaml` has `model.checkpoint` pointing into `stage1/tb_logs/...`.

- [ ] **Step 5.1.7: Record outcomes in project memory**

Append to `/home/sam/.claude/projects/-home-sam-docker-images-deeplabcut-webapp-docker-supports/memory/project_lp_smoke_2026-05-13.md` (under a new heading):
```
## Two-stage training — 2026-05-14

Backend supports a curriculum: stage 1 trains heatmap+vits_dino on a flat
single-view CSV (all labels across all cams + all unrecognised folders); stage
2 trains MVT with model.checkpoint pre-set to stage 1's best ckpt, triggering
LP's existing backbone-only state-dict transfer (utils/scripts.py:584-608).
Converter now emits <lp>/sv-pretrain/ alongside the main project; Card 2 has
a "Pretrain ViT backbone on all labels" checkbox.

Live smoke (1 epoch each) on DREADD-Ali-2026-01-07-LP-2STAGE-TEST: SUCCESS,
stage1 → stage2_done, both run dirs populated, stage 2 config.model.checkpoint
points into stage1/tb_logs/.../*.ckpt.
```

- [ ] **Step 5.1.8: Final commit (only if smoke surfaced fixups)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git status --short dlc-3D/
```
If anything is dirty:
```bash
git -c commit.gpgsign=false commit -am "fix(dlc-3d): post-smoke fixups for two-stage training"
```
Otherwise: no commit needed.

---

## Self-Review Notes

**1. Spec coverage:**
- §1 SV sub-project layout → Phase 1 (Tasks 1.1–1.4)
- §1 CSV construction (view-agnostic, hardlinks) → Task 1.3
- §1 Config (single-view canonical + ViT-required dims) → Task 1.2
- §1 Converter summary fields → Task 1.4
- §2 Training orchestration (stage1 → stage2 with checkpoint propagation) → Phase 3 (Task 3.1)
- §2 find_best_checkpoint → Task 2.1
- §2 build_stage1_config (short curriculum + early stopping) → Task 2.2
- §2 Run dir layout `models/<ts>/{stage1,stage2}` → Task 3.1's `make_run_dir` + subdirs
- §2 Status reporting `stage` field → Task 3.1's `emit(..., stage=...)`
- §2 Cancellation semantics → unchanged (Celery revoke kills child subprocess)
- §2 Failure semantics → tested in `test_lp_train_two_stage_fails_on_no_stage1_checkpoint`
- §3 UI: Pretraining fieldset + override field → Task 4.1
- §3 Poll callback shows `stage` → Task 4.1.2
- §3 API contract: additive options → Task 3.1 (no route handler change needed)
- §4 Files → matches Plan File Structure
- §5 Tests → 11 unit tests across Tasks 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 3.1 + 1 live smoke

**2. Placeholder scan:** No TBD/TODO. Every code step shows full code. Commit subjects concrete.

**3. Type consistency:**
- `_walk_all_labeled_data(dlc_dir) -> Iterator[(Path, str, list)]` — consumed in Task 1.3 (`_build_sv_pretrain_project`).
- `_build_sv_pretrain_project(lp_dir, dlc_dir, bodyparts) -> int` — consumed in Task 1.4.
- `_write_sv_config(sv_dir, dlc_dir, bodyparts, img_h, img_w)` — consumed in Task 1.3.
- `find_best_checkpoint(model_dir) -> Path | None` — consumed in Task 3.1.
- `build_stage1_config(sv_project, out_dir, options)` — consumed in Task 3.1.
- `lp_train(self, lp_project, options)` — signature unchanged from previous plans.
- New summary keys: `sv_pretrain_dir`, `n_sv_rows` — used by tests in Task 1.4 + live smoke in Phase 5.
- New option keys: `two_stage`, `stage1_max_epochs`, `stage1_early_stop_patience`, `stage1_ckpt_override` — consumed in Tasks 2.2, 3.1; surfaced in UI in Task 4.1.

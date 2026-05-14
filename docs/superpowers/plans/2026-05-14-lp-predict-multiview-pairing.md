# LP Predict Multi-View Pairing + AVI Transcoding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `POST /dlc-3d/lp/predict` accept individual videos by resolving `_cam<N>_` sibling views and transcoding non-MP4 inputs to MP4 before invoking `litpose predict`, so multi-view models work without forcing the user to pick a whole folder.

**Architecture:** New pure-python helper `prepare_predict_inputs(model_dir, videos)` in `predict_runner.py` reads `<model_dir>/config.yaml` for `data.view_names`, resolves sibling files by `_<view>_` substitution in the source directory, and remuxes any non-MP4 to MP4 via `ffmpeg -c copy`. The `lp_predict` Celery task calls this helper, substitutes the resolved paths for the litpose invocation, and surfaces `transcoded`/`sibling_warnings` in the task return so the UI shows what happened.

**Tech Stack:** Python (stdlib + PyYAML already on worker), ffmpeg (already on worker), pytest.

**Reference spec:** `docs/superpowers/specs/2026-05-14-lp-predict-multiview-pairing-design.md`

**Live smoke target (user-confirmed safe to test against):**
`/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/050726/khoai-lang-1_cam0_20260507_102231_0_trig1_fps200_exposure1500_gain10.avi`
- Sibling `_cam1_` exists in the same dir; both are ~10 GB AVI.
- Host path: `/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/tdcs/050726/`
- Side effects allowed: writes `<stem>.mp4` (transcode cache), `<stem>.csv`, `<stem>_<metric>.csv`, `<stem>_labeled.mp4` next to source. **Source AVIs and CSVs must not be touched.**

---

## File Structure

**Created:**
- `dlc-3D/tests/test_lp_predict_pairing.py` — unit tests for the new helper

**Modified:**
- `dlc-3D/src/dlc_3d_bp/lp/predict_runner.py` — add `prepare_predict_inputs(model_dir, videos)` and three small private helpers; existing `list_models()`, `run_predict_subprocess()`, `relocate_predictions()` untouched
- `dlc-3D/src/dlc_3d_bp/lp/tasks.py` — `lp_predict` calls `prepare_predict_inputs` before subprocess, passes resolved paths to relocator, surfaces extra fields in return
- `dlc-3D/src/static/lp_cards.js` — Predict card's poll callback shows `transcoded` and `sibling_warnings` when present (5-line change)

**Untouched:** card markup, route handler, `relocate_predictions`, all other LP cards/files, docker-compose.yml. No image rebuild required (ffmpeg already in `Dockerfile.worker`).

---

## Phase 0 — Baseline

- [ ] **Step 0.1: Confirm clean working tree on the supports repo**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git status --short dlc-3D/
```
Expected: empty output (no unstaged changes in `dlc-3D/`).

- [ ] **Step 0.2: Baseline test count**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q --ignore=tests/e2e 2>&1 | tail -3
```
Expected: **89 passed, 1 skipped**. After this plan: expect **99 passed, 1 skipped** (+10 new tests).

- [ ] **Step 0.3: Confirm ffmpeg is on the dlc-3d-worker image**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose exec dlc-3d-worker which ffmpeg
docker compose exec dlc-3d-worker ffmpeg -version 2>&1 | head -1
```
Expected: `/usr/bin/ffmpeg` and a version line. If missing, the plan's transcode step won't work — escalate BLOCKED before proceeding.

- [ ] **Step 0.4: Confirm the user's target AVI and its sibling both exist on the host**

Run:
```bash
ls -la "/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/tdcs/050726/khoai-lang-1_cam0_20260507_102231_0_trig1_fps200_exposure1500_gain10.avi" "/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/tdcs/050726/khoai-lang-1_cam1_20260507_102231_0_trig1_fps200_exposure1500_gain10.avi"
```
Expected: both files listed, several GB each. If either is missing, escalate BLOCKED.

---

## Phase 1 — `_load_view_names` helper

### Task 1.1: Reads `data.view_names` from an LP config

**Files:**
- Create: `dlc-3D/tests/test_lp_predict_pairing.py`
- Modify: `dlc-3D/src/dlc_3d_bp/lp/predict_runner.py`

- [ ] **Step 1.1.1: Write the failing test**

Create `dlc-3D/tests/test_lp_predict_pairing.py`:
```python
"""Tests for prepare_predict_inputs and its helpers."""
from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from dlc_3d_bp.lp.predict_runner import _load_view_names


def _write_cfg(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip())
    return p


def test_load_view_names_multiview(tmp_path):
    cfg = _write_cfg(tmp_path / "config.yaml", """
        data:
          view_names:
            - cam0
            - cam1
    """)
    assert _load_view_names(cfg.parent) == ["cam0", "cam1"]


def test_load_view_names_singleview_default(tmp_path):
    cfg = _write_cfg(tmp_path / "config.yaml", """
        data:
          csv_file: labels.csv
    """)
    assert _load_view_names(cfg.parent) == []


def test_load_view_names_missing_config(tmp_path):
    assert _load_view_names(tmp_path) == []
```

- [ ] **Step 1.1.2: Run test to verify it fails**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_lp_predict_pairing.py::test_load_view_names_multiview -v
```
Expected: `ImportError: cannot import name '_load_view_names'` (or AttributeError if Python resolves to a partial import).

- [ ] **Step 1.1.3: Implement `_load_view_names`**

Append to `dlc-3D/src/dlc_3d_bp/lp/predict_runner.py`:
```python
import yaml


def _load_view_names(model_dir: Path | str) -> list[str]:
    """Return `data.view_names` from `<model_dir>/config.yaml`, or [] if missing.

    Returns [] for single-view models (where view_names is missing or has 0/1 entries).
    """
    cfg_path = Path(model_dir) / "config.yaml"
    if not cfg_path.is_file():
        return []
    try:
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
    except Exception:
        return []
    views = (cfg.get("data") or {}).get("view_names") or []
    if not isinstance(views, list):
        return []
    return [str(v) for v in views]
```

- [ ] **Step 1.1.4: Run tests to verify they pass**

Run:
```bash
python -m pytest tests/test_lp_predict_pairing.py -v
```
Expected: 3 passed.

- [ ] **Step 1.1.5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/dlc_3d_bp/lp/predict_runner.py dlc-3D/tests/test_lp_predict_pairing.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): _load_view_names — read data.view_names from LP config"
```

---

## Phase 2 — `_resolve_siblings` helper

### Task 2.1: Pair siblings by `_<view>_` substitution

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/predict_runner.py`
- Modify: `dlc-3D/tests/test_lp_predict_pairing.py`

- [ ] **Step 2.1.1: Write the failing tests**

Append to `dlc-3D/tests/test_lp_predict_pairing.py`:
```python
from dlc_3d_bp.lp.predict_runner import _resolve_siblings


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    return p


def test_resolve_siblings_pairs_camN(tmp_path):
    """One cam0 input + cam1 sibling on disk → both paths returned."""
    d = tmp_path / "vids"
    a = _touch(d / "khoai_cam0_20260507.avi")
    b = _touch(d / "khoai_cam1_20260507.avi")
    out = _resolve_siblings([a], view_names=["cam0", "cam1"])
    assert out["pairs"] == [[a, b]]
    assert out["warnings"] == []


def test_resolve_siblings_warns_on_missing(tmp_path):
    """One cam0 input but no cam1 sibling → session dropped, warning recorded."""
    d = tmp_path / "vids"
    a = _touch(d / "khoai_cam0_20260507.avi")
    out = _resolve_siblings([a], view_names=["cam0", "cam1"])
    assert out["pairs"] == []
    assert any("cam1" in w for w in out["warnings"])


def test_resolve_siblings_dedupes_when_user_supplies_both(tmp_path):
    """User supplies both views → still one pair, not two."""
    d = tmp_path / "vids"
    a = _touch(d / "khoai_cam0_20260507.avi")
    b = _touch(d / "khoai_cam1_20260507.avi")
    out = _resolve_siblings([a, b], view_names=["cam0", "cam1"])
    assert out["pairs"] == [[a, b]]
    assert out["warnings"] == []


def test_resolve_siblings_passthrough_unknown_pattern(tmp_path):
    """Filename without _camN_ → passed through alone with a warning."""
    d = tmp_path / "vids"
    a = _touch(d / "weird_filename.avi")
    out = _resolve_siblings([a], view_names=["cam0", "cam1"])
    assert out["pairs"] == [[a]]
    assert any("no view token" in w.lower() for w in out["warnings"])


def test_resolve_siblings_singleview_returns_each(tmp_path):
    """view_names == [] → each input becomes its own one-element 'pair'."""
    d = tmp_path / "vids"
    a = _touch(d / "v1.avi"); b = _touch(d / "v2.avi")
    out = _resolve_siblings([a, b], view_names=[])
    assert out["pairs"] == [[a], [b]]
```

- [ ] **Step 2.1.2: Run tests to verify they fail**

Run:
```bash
python -m pytest tests/test_lp_predict_pairing.py -v
```
Expected: ImportError on `_resolve_siblings` for the new 5 tests.

- [ ] **Step 2.1.3: Implement `_resolve_siblings`**

Append to `dlc-3D/src/dlc_3d_bp/lp/predict_runner.py`:
```python
import re


def _resolve_siblings(videos: list[Path | str], view_names: list[str]) -> dict:
    """Group video paths into per-session pairs by _<view>_ substitution.

    Multi-view (len(view_names) > 1):
      For each input, find the first ``_<view>_`` token in the stem (any
      view from ``view_names``). Resolve sibling paths for every other view
      in the same directory. Drop sessions where any view file is missing
      and record a warning.

    Single-view (len(view_names) <= 1):
      Return each input as its own one-element "pair".

    Returns: ``{"pairs": list[list[Path]], "warnings": list[str]}``.
    """
    pairs: list[list[Path]] = []
    warnings: list[str] = []

    if len(view_names) <= 1:
        for v in videos:
            pairs.append([Path(v)])
        return {"pairs": pairs, "warnings": warnings}

    # Multi-view: bucket inputs by session key
    sessions: dict[tuple[Path, str], dict[str, Path]] = {}
    for v in videos:
        v = Path(v)
        stem = v.stem
        match_view = None
        for vn in view_names:
            if re.search(rf"_{re.escape(vn)}_", stem):
                match_view = vn
                break
        if match_view is None:
            pairs.append([v])
            warnings.append(f"{v.name}: no view token from {view_names} found in stem; passing through alone")
            continue
        # Session key: directory + stem with _<view>_ removed
        session_stem = re.sub(rf"_{re.escape(match_view)}_", "_<VIEW>_", stem, count=1)
        key = (v.parent, session_stem)
        sessions.setdefault(key, {})[match_view] = v

    for (parent, session_stem), got in sessions.items():
        resolved: dict[str, Path] = {}
        for vn in view_names:
            if vn in got:
                resolved[vn] = got[vn]
                continue
            # Build the expected sibling path
            candidate_stem = session_stem.replace("_<VIEW>_", f"_{vn}_", 1)
            # Pick up the original suffix from any known view's file
            example = next(iter(got.values()))
            candidate = parent / f"{candidate_stem}{example.suffix}"
            if candidate.is_file():
                resolved[vn] = candidate
            else:
                warnings.append(
                    f"{session_stem.replace('_<VIEW>_', '_')}: "
                    f"missing sibling for view '{vn}' (looked for {candidate.name})"
                )

        if len(resolved) == len(view_names):
            pairs.append([resolved[vn] for vn in view_names])
        # else: session dropped (warning already recorded)

    return {"pairs": pairs, "warnings": warnings}
```

- [ ] **Step 2.1.4: Run tests to verify they pass**

Run:
```bash
python -m pytest tests/test_lp_predict_pairing.py -v
```
Expected: 8 passed (3 from Phase 1 + 5 from Phase 2).

- [ ] **Step 2.1.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/predict_runner.py dlc-3D/tests/test_lp_predict_pairing.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): _resolve_siblings — pair by _<view>_ substitution"
```

---

## Phase 3 — `_transcode_to_mp4` helper

### Task 3.1: Cache-aware ffmpeg remux

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/predict_runner.py`
- Modify: `dlc-3D/tests/test_lp_predict_pairing.py`

- [ ] **Step 3.1.1: Write the failing tests**

Append to `dlc-3D/tests/test_lp_predict_pairing.py`:
```python
from dlc_3d_bp.lp.predict_runner import _transcode_to_mp4


def test_transcode_skips_when_mp4_exists(tmp_path, monkeypatch):
    """If <stem>.mp4 already exists next to <stem>.avi, no ffmpeg call."""
    d = tmp_path / "vids"; d.mkdir()
    src = d / "video.avi"; src.write_bytes(b"\x00")
    cached = d / "video.mp4"; cached.write_bytes(b"\x00")

    called = []
    def _fake_run(cmd, **_kw):
        called.append(cmd)
        raise AssertionError("ffmpeg should not be invoked when mp4 cache exists")
    monkeypatch.setattr("subprocess.run", _fake_run)

    out, transcoded = _transcode_to_mp4(src)
    assert out == cached
    assert transcoded is False
    assert called == []


def test_transcode_invokes_ffmpeg_stream_copy(tmp_path, monkeypatch):
    """Non-mp4 input + no cache → ffmpeg -c copy invoked, output path returned."""
    d = tmp_path / "vids"; d.mkdir()
    src = d / "video.avi"; src.write_bytes(b"\x00")

    seen = {}
    def _fake_run(cmd, **kw):
        seen["cmd"] = cmd
        # Pretend ffmpeg succeeded and produced an mp4
        (d / "video.mp4").write_bytes(b"\x00")
        class _R:
            returncode = 0
            stderr = ""
        return _R()
    monkeypatch.setattr("subprocess.run", _fake_run)

    out, transcoded = _transcode_to_mp4(src)
    assert out == d / "video.mp4"
    assert transcoded is True
    assert "ffmpeg" in seen["cmd"][0]
    assert "-c" in seen["cmd"] and "copy" in seen["cmd"]


def test_transcode_falls_back_on_copy_failure(tmp_path, monkeypatch):
    """If -c copy fails, retry with libx264."""
    d = tmp_path / "vids"; d.mkdir()
    src = d / "video.avi"; src.write_bytes(b"\x00")

    calls = []
    def _fake_run(cmd, **kw):
        calls.append(cmd)
        class _R:
            stderr = "muxer not compatible"
        # First call (stream copy) fails; second call (re-encode) succeeds
        if "-c" in cmd and "copy" in cmd:
            _R.returncode = 1
        else:
            (d / "video.mp4").write_bytes(b"\x00")
            _R.returncode = 0
        return _R()
    monkeypatch.setattr("subprocess.run", _fake_run)

    out, transcoded = _transcode_to_mp4(src)
    assert out == d / "video.mp4"
    assert transcoded is True
    assert len(calls) == 2
    assert any("libx264" in c for c in calls[1])


def test_transcode_mp4_input_is_identity(tmp_path):
    """MP4 input → returns the same path, no transcode."""
    d = tmp_path / "vids"; d.mkdir()
    src = d / "video.mp4"; src.write_bytes(b"\x00")
    out, transcoded = _transcode_to_mp4(src)
    assert out == src
    assert transcoded is False
```

- [ ] **Step 3.1.2: Run tests to verify they fail**

Run:
```bash
python -m pytest tests/test_lp_predict_pairing.py -v
```
Expected: 4 new tests fail with ImportError on `_transcode_to_mp4`.

- [ ] **Step 3.1.3: Implement `_transcode_to_mp4`**

Append to `dlc-3D/src/dlc_3d_bp/lp/predict_runner.py`:
```python
import shutil as _shutil  # avoid shadowing existing `import shutil` if added earlier
import subprocess


def _transcode_to_mp4(src: Path | str) -> tuple[Path, bool]:
    """Remux a non-mp4 video to mp4 next to the source.

    Returns ``(out_path, did_transcode)``.

    Behaviour:
      - If src is already ``.mp4`` → returns src unchanged.
      - If ``<stem>.mp4`` already exists next to src → returns cached path; no ffmpeg.
      - Else runs ``ffmpeg -y -i src -c copy -movflags +faststart <stem>.mp4``.
      - If the stream-copy fails, falls back to ``ffmpeg -y -i src -c:v libx264 -preset veryfast -crf 18 <stem>.mp4``.
      - Raises ``FileNotFoundError`` if ffmpeg isn't on PATH.
      - Raises ``RuntimeError`` if both stream-copy and re-encode fail.
    """
    src = Path(src)
    if src.suffix.lower() == ".mp4":
        return src, False

    out = src.with_suffix(".mp4")
    if out.is_file():
        return out, False

    if _shutil.which("ffmpeg") is None:
        raise FileNotFoundError("ffmpeg required for transcoding; not found on PATH")

    copy_cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-c", "copy", "-movflags", "+faststart",
        str(out),
    ]
    r = subprocess.run(copy_cmd, capture_output=True, text=True)
    if r.returncode == 0 and out.is_file():
        return out, True

    reencode_cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        str(out),
    ]
    r2 = subprocess.run(reencode_cmd, capture_output=True, text=True)
    if r2.returncode == 0 and out.is_file():
        return out, True

    raise RuntimeError(
        f"transcode failed for {src.name}: "
        f"stream-copy stderr tail: {(r.stderr or '').splitlines()[-3:]}, "
        f"re-encode stderr tail: {(r2.stderr or '').splitlines()[-3:]}"
    )
```

- [ ] **Step 3.1.4: Run tests to verify they pass**

Run:
```bash
python -m pytest tests/test_lp_predict_pairing.py -v
```
Expected: 12 passed (3 + 5 + 4).

- [ ] **Step 3.1.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/predict_runner.py dlc-3D/tests/test_lp_predict_pairing.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): _transcode_to_mp4 — cache-aware ffmpeg remux"
```

---

## Phase 4 — `prepare_predict_inputs` orchestrator

### Task 4.1: End-to-end pairing + transcoding

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/predict_runner.py`
- Modify: `dlc-3D/tests/test_lp_predict_pairing.py`

- [ ] **Step 4.1.1: Write the failing test**

Append to `dlc-3D/tests/test_lp_predict_pairing.py`:
```python
from dlc_3d_bp.lp.predict_runner import prepare_predict_inputs


def test_prepare_predict_inputs_end_to_end_multiview(tmp_path, monkeypatch):
    """Multi-view config + one AVI input → returns two mp4 paths after pairing+transcoding."""
    # Synthetic model dir
    model = tmp_path / "model"
    _write_cfg(model / "config.yaml", """
        data:
          view_names:
            - cam0
            - cam1
    """)

    # Synthetic video dir with both cam0 and cam1 AVIs (sibling on disk)
    vids = tmp_path / "vids"; vids.mkdir()
    cam0 = vids / "khoai_cam0_x.avi"; cam0.write_bytes(b"\x00")
    cam1 = vids / "khoai_cam1_x.avi"; cam1.write_bytes(b"\x00")

    # Fake ffmpeg: writes the .mp4 next to source
    calls = []
    def _fake_run(cmd, **kw):
        calls.append(cmd)
        # find the output path (last positional after the codec args)
        out = Path(cmd[-1])
        out.write_bytes(b"\x00")
        class _R:
            returncode = 0
            stderr = ""
        return _R()
    monkeypatch.setattr("subprocess.run", _fake_run)

    result = prepare_predict_inputs(model, [cam0])

    assert result["is_multiview"] is True
    assert result["view_names"] == ["cam0", "cam1"]
    # Both mp4s are siblings in the same dir, transcoded from AVIs
    assert sorted(p.name for p in result["mp4_paths"]) == ["khoai_cam0_x.mp4", "khoai_cam1_x.mp4"]
    # Two transcodes happened (cam0 and cam1)
    assert len(result["transcoded"]) == 2
    # No warnings (both siblings present)
    assert result["sibling_warnings"] == []
    # ffmpeg was called twice
    assert len(calls) == 2


def test_prepare_predict_inputs_singleview_transcodes_only(tmp_path, monkeypatch):
    """Single-view model: no pairing, but still transcode AVI."""
    model = tmp_path / "model"
    _write_cfg(model / "config.yaml", """
        data:
          csv_file: labels.csv
    """)
    vids = tmp_path / "vids"; vids.mkdir()
    src = vids / "v.avi"; src.write_bytes(b"\x00")

    def _fake_run(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"\x00")
        class _R: returncode = 0; stderr = ""
        return _R()
    monkeypatch.setattr("subprocess.run", _fake_run)

    result = prepare_predict_inputs(model, [src])
    assert result["is_multiview"] is False
    assert result["mp4_paths"] == [vids / "v.mp4"]
    assert len(result["transcoded"]) == 1


def test_prepare_predict_inputs_raises_when_all_sessions_dropped(tmp_path):
    """Multi-view config but no siblings on disk → empty mp4_paths surfaces warnings."""
    model = tmp_path / "model"
    _write_cfg(model / "config.yaml", """
        data:
          view_names:
            - cam0
            - cam1
    """)
    vids = tmp_path / "vids"; vids.mkdir()
    a = vids / "x_cam0_y.mp4"; a.write_bytes(b"\x00")  # MP4 so no transcode
    # no x_cam1_y.mp4

    result = prepare_predict_inputs(model, [a])
    assert result["mp4_paths"] == []
    assert any("cam1" in w for w in result["sibling_warnings"])
```

- [ ] **Step 4.1.2: Run tests to verify they fail**

Run:
```bash
python -m pytest tests/test_lp_predict_pairing.py -v
```
Expected: 3 new tests fail with ImportError on `prepare_predict_inputs`.

- [ ] **Step 4.1.3: Implement `prepare_predict_inputs`**

Append to `dlc-3D/src/dlc_3d_bp/lp/predict_runner.py`:
```python
def prepare_predict_inputs(model_dir: Path | str, videos: list[Path | str]) -> dict:
    """Resolve sibling views + transcode non-mp4 inputs for litpose predict.

    1. Reads ``data.view_names`` from ``<model_dir>/config.yaml``.
    2. If multi-view: groups inputs into per-session pairs by ``_<view>_``
       substitution, dropping sessions with missing siblings (each dropped
       session adds a warning).
    3. Transcodes every non-mp4 path (via stream-copy, falling back to
       libx264 re-encode), reusing cached ``<stem>.mp4`` next to sources.

    Returns::
        {
            "mp4_paths": [Path, ...],          # what to pass to litpose
            "transcoded": [str, ...],          # source paths we transcoded this call
            "sibling_warnings": [str, ...],
            "is_multiview": bool,
            "view_names": list[str],
        }
    """
    model_dir = Path(model_dir)
    view_names = _load_view_names(model_dir)
    is_multiview = len(view_names) > 1

    siblings = _resolve_siblings([Path(v) for v in videos], view_names)
    mp4_paths: list[Path] = []
    transcoded: list[str] = []

    for group in siblings["pairs"]:
        try:
            mp4_group = []
            for v in group:
                out, did = _transcode_to_mp4(v)
                if did:
                    transcoded.append(str(v))
                mp4_group.append(out)
            mp4_paths.extend(mp4_group)
        except (FileNotFoundError, RuntimeError) as e:
            siblings["warnings"].append(f"transcode failed for {[p.name for p in group]}: {e}")

    return {
        "mp4_paths": mp4_paths,
        "transcoded": transcoded,
        "sibling_warnings": siblings["warnings"],
        "is_multiview": is_multiview,
        "view_names": view_names,
    }
```

- [ ] **Step 4.1.4: Run tests to verify they pass**

Run:
```bash
python -m pytest tests/test_lp_predict_pairing.py -v
```
Expected: 15 passed.

- [ ] **Step 4.1.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/predict_runner.py dlc-3D/tests/test_lp_predict_pairing.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): prepare_predict_inputs — orchestrate pairing + transcoding"
```

---

## Phase 5 — Wire into `lp_predict` task

### Task 5.1: Task calls the orchestrator and forwards extras

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/tasks.py`

- [ ] **Step 5.1.1: Edit `lp_predict` body**

In `dlc-3D/src/dlc_3d_bp/lp/tasks.py`, replace the entire `lp_predict` function with:
```python
@celery.task(bind=True, name="dlc_3d_lp.predict")
def lp_predict(self, model_dir: str, videos: list, skip_viz: bool = False, overwrite: bool = False, dest_dir: str = "") -> dict:
    """Run `litpose predict <model_dir> <video...>`, then relocate outputs.

    Before invoking litpose:
      - Reads model view_names from <model_dir>/config.yaml.
      - For multi-view models: resolves sibling _camN_ files in the same dir.
      - Transcodes any non-mp4 inputs to mp4 via ffmpeg (cached, stream-copy
        with libx264 fallback).

    Output relocation runs after predict — see relocate_predictions().
    """
    import os
    from .predict_runner import run_predict_subprocess, relocate_predictions, prepare_predict_inputs

    if not videos:
        raise ValueError("at least one video path required")
    md = Path(model_dir)
    if not md.is_dir():
        raise FileNotFoundError(f"model_dir does not exist: {model_dir}")

    log_key = f"dlc3d:lp:log:{self.request.id}"
    try:
        import redis
        rconn = redis.Redis.from_url(
            os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0"),
            decode_responses=True,
        )
    except Exception:
        rconn = None

    def emit(line: str) -> None:
        if rconn:
            try:
                rconn.rpush(log_key, line)
                rconn.ltrim(log_key, -2000, -1)
            except Exception:
                pass
        self.update_state(state="STARTED", meta={"last_line": line, "model_dir": str(md)})

    # ── Resolve siblings + transcode ────────────────────────────────────
    prep = prepare_predict_inputs(md, videos)
    if not prep["mp4_paths"]:
        raise RuntimeError(
            f"no usable sessions after sibling resolution: {prep['sibling_warnings']}"
        )
    emit(f"prepared {len(prep['mp4_paths'])} mp4 input(s); "
         f"transcoded {len(prep['transcoded'])}; "
         f"warnings: {len(prep['sibling_warnings'])}")
    for w in prep["sibling_warnings"]:
        emit(f"  warning: {w}")

    # ── Run litpose predict on the resolved mp4 list ────────────────────
    rc = run_predict_subprocess(md, prep["mp4_paths"], skip_viz=skip_viz, overwrite=overwrite, log_callback=emit)
    if rc != 0:
        raise RuntimeError(f"litpose predict exited with code {rc}")

    # ── Move outputs to dest_dir (or per-video parent) ─────────────────
    relocate_info = relocate_predictions(md, prep["mp4_paths"], dest_dir=(dest_dir or None), overwrite=overwrite)
    return {
        "status": "ok",
        "model_dir": str(md),
        "dest_dir": relocate_info["dest_dir"] or "<per-video parent>",
        "moved": relocate_info["moved"],
        "skipped": relocate_info["skipped"],
        "transcoded": prep["transcoded"],
        "sibling_warnings": prep["sibling_warnings"],
        "is_multiview": prep["is_multiview"],
        "view_names": prep["view_names"],
    }
```

- [ ] **Step 5.1.2: Run the full suite — no regressions**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q --ignore=tests/e2e
```
Expected: **104 passed, 1 skipped** (89 baseline + 15 new in Phase 1–4; Task 5 doesn't add tests, only wires up).

- [ ] **Step 5.1.3: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/dlc_3d_bp/lp/tasks.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): lp_predict task pairs siblings + transcodes AVI before predict"
```

---

## Phase 6 — UI: surface transcode + warning info

### Task 6.1: Predict card result panel shows transcoded / warnings

**Files:**
- Modify: `dlc-3D/src/static/lp_cards.js`

- [ ] **Step 6.1.1: Locate the predict-poll callback**

Run:
```bash
grep -n "model_dir:.*j.celery_info?.model_dir\|--- log tail ---" /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/lp_cards.js | head
```
Expected: one or more line numbers inside `initPredictCard()`'s `pollJob` callback. Read the surrounding ~10 lines to confirm you're editing the right spot.

- [ ] **Step 6.1.2: Add transcode + warnings to the displayed text**

In `dlc-3D/src/static/lp_cards.js`, inside `initPredictCard()`'s submit-click handler, find the `pollJob(jobId, (j) => { ... })` callback. Replace its body with:
```javascript
await pollJob(jobId, (j) => {
  const tail = (j.log_tail || []).slice(-30).join("\n");
  const info = j.celery_info || {};
  const transcoded = info.transcoded || [];
  const warnings   = info.sibling_warnings || [];
  const extras = [];
  if (transcoded.length) extras.push(`transcoded:\n  ` + transcoded.join("\n  "));
  if (warnings.length)   extras.push(`warnings:\n  ` + warnings.join("\n  "));
  resEl.textContent =
    `state: ${j.celery_state || "PENDING"}\n` +
    `model_dir: ${info.model_dir || j.model_dir || ""}\n` +
    `dest: ${info.dest_dir || j.dest_dir || "<per-video parent>"}\n` +
    (extras.length ? extras.join("\n") + "\n" : "") +
    `--- log tail ---\n${tail}`;
}, 2500);
```

- [ ] **Step 6.1.3: Restart dlc-3d and confirm JS reloads**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d
sleep 3
docker compose exec dlc-3d python3 -c "
import urllib.request
js = urllib.request.urlopen('http://localhost:5050/dlc-3d/static/lp_cards.js').read().decode()
assert 'transcoded:' in js, 'updated JS not reachable'
assert 'sibling_warnings' in js, 'warnings handling not present'
print('lp_cards.js update served')
"
```
Expected: `lp_cards.js update served`.

- [ ] **Step 6.1.4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/lp_cards.js
git -c commit.gpgsign=false commit -m "feat(dlc-3d): Predict card result panel shows transcoded + sibling_warnings"
```

---

## Phase 7 — Live smoke test on the user's target video

### Task 7.1: End-to-end multi-view predict

- [ ] **Step 7.1.1: Restart the worker so it picks up the new task code**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d-worker
sleep 5
docker compose logs --tail=30 dlc-3d-worker | grep -E "ready|error|Traceback"
```
Expected: `celery@…ready` line; no traceback.

- [ ] **Step 7.1.2: Confirm the target file's sibling is present**

Run:
```bash
docker compose exec dlc-3d ls -la \
  "/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/050726/khoai-lang-1_cam0_20260507_102231_0_trig1_fps200_exposure1500_gain10.avi" \
  "/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/050726/khoai-lang-1_cam1_20260507_102231_0_trig1_fps200_exposure1500_gain10.avi"
```
Expected: both files listed.

- [ ] **Step 7.1.3: Pick a usable model**

Run:
```bash
docker compose exec dlc-3d python3 -c "
import urllib.request, json
r = urllib.request.urlopen('http://localhost:5050/dlc-3d/lp/models?lp_project=/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP')
b = json.loads(r.read())
usable = [m for m in b['models'] if m['has_checkpoint']]
print('usable models:', len(usable))
print('newest:', usable[0]['path'] if usable else 'none')
"
```
Expected: at least one usable model. Note its path for step 7.1.4.

- [ ] **Step 7.1.4: Enqueue the predict job**

Run (substitute the model path from step 7.1.3 if different):
```bash
docker compose exec dlc-3d python3 -c "
import urllib.request, json
req = urllib.request.Request(
    'http://localhost:5050/dlc-3d/lp/predict',
    data=json.dumps({
        'lp_project': '/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP',
        'videos': ['/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/050726/khoai-lang-1_cam0_20260507_102231_0_trig1_fps200_exposure1500_gain10.avi'],
        'skip_viz': True,
    }).encode(),
    headers={'Content-Type':'application/json'},
)
print(json.loads(urllib.request.urlopen(req).read()))
"
```
Expected: `{'job_id': '...', 'model_dir': '...', 'dest_dir': ''}`. Note the job_id.

- [ ] **Step 7.1.5: Poll to terminal state**

Wait until the job reaches SUCCESS or FAILURE. Run (replace `<JOB>`):
```bash
JOB=<paste-job-id-here>
docker compose exec dlc-3d python3 -c "
import urllib.request, json
b = json.loads(urllib.request.urlopen('http://localhost:5050/dlc-3d/lp/job/$JOB').read())
print('STATE:', b.get('celery_state'))
print('INFO:', b.get('celery_info'))
print('LAST 20 LOG LINES:')
for line in (b.get('log_tail') or [])[-20:]: print(' ', line)
"
```
Re-run until `STATE: SUCCESS` (or `FAILURE`).

- [ ] **Step 7.1.6: Verify outputs landed beside the source AVIs**

On the host:
```bash
ls -la "/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/tdcs/050726/" | grep -E "khoai-lang-1_(cam0|cam1)_20260507_102231.*\.(mp4|csv)"
```
Expected: each of `khoai-lang-1_cam{0,1}_…mp4` (transcode cache) and `khoai-lang-1_cam{0,1}_…csv` (predictions) present. The original `.avi` and `.csv` (annotation) files must still be present and unchanged.

- [ ] **Step 7.1.7: Confirm originals untouched**

Run on the host:
```bash
ls -la "/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/tdcs/050726/khoai-lang-1_cam0_20260507_102231_0_trig1_fps200_exposure1500_gain10.avi"
ls -la "/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/tdcs/050726/khoai-lang-1_cam0_20260507_102231_0_trig1_fps200_exposure1500_gain10.csv"
```
Expected: both still 9.8 GB AVI / original CSV, mtime unchanged from before the smoke run.

- [ ] **Step 7.1.8: Record outcomes in project memory**

Append to `/home/sam/.claude/projects/-home-sam-docker-images-deeplabcut-webapp-docker-supports/memory/project_lp_smoke_2026-05-13.md` under the "Predict card analyze-style picker" section:
```
- 2026-05-14: Multi-view sibling pairing + AVI transcoding live-validated on
  user's tdcs/050726/ khoai-lang-1 pair. Cam0 .avi (9.8 GB) + auto-resolved
  cam1 .avi transcoded via ffmpeg -c copy; litpose predict succeeded; .csv
  + .mp4 outputs land beside source; source .avi untouched.
```

- [ ] **Step 7.1.9: Final commit (only if any iteration fixes were needed during smoke)**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git status --short dlc-3D/
```
If anything is dirty:
```bash
git -c commit.gpgsign=false commit -am "fix(dlc-3d): smoke-run follow-ups for predict pairing/transcode"
```
Otherwise: no commit needed.

---

## Self-Review Notes

1. **Spec coverage:**
   - §1.1 Detect view configuration → Phase 1 (`_load_view_names`)
   - §1.2 Resolve sibling views (multi-view) → Phase 2 (`_resolve_siblings`)
   - §1.3 Transcode non-MP4 inputs (cache + stream-copy + libx264 fallback + ffmpeg-missing error) → Phase 3 (`_transcode_to_mp4`)
   - §1.4 Return shape → Phase 4 (`prepare_predict_inputs` return dict matches)
   - §2.1 Task integration → Phase 5
   - §2.2 No route payload change → confirmed in Phase 5 (route untouched)
   - §3 UI surfacing → Phase 6
   - §4 Error handling rows → covered by Phase 3 + Phase 5 (`RuntimeError("no usable sessions...")` matches §4 "All sessions dropped")
   - §5 File list → matches plan File Structure
   - §6 Test plan → 10 tests in Phases 1–4 + 1 live smoke in Phase 7; spec lists 10 unit tests + live smoke, matches
   - Live smoke side-effect contract → Phase 7 explicitly verifies originals untouched (step 7.1.7)

2. **Placeholder scan:** No TBD/TODO. Every code step shows full code. Every commit subject is concrete. The ffmpeg dependency check is in Phase 0 step 0.3 with an explicit escalation branch.

3. **Type consistency:**
   - `_load_view_names(model_dir) -> list[str]` — consumed by `_resolve_siblings(..., view_names=...)` and `prepare_predict_inputs` (passes to `_resolve_siblings`).
   - `_resolve_siblings(videos, view_names) -> {pairs: list[list[Path]], warnings: list[str]}` — consumed by `prepare_predict_inputs`.
   - `_transcode_to_mp4(src) -> (Path, bool)` — consumed by `prepare_predict_inputs`.
   - `prepare_predict_inputs(model_dir, videos) -> {mp4_paths, transcoded, sibling_warnings, is_multiview, view_names}` — consumed by `lp_predict` task; the task return dict adds `status/model_dir/dest_dir/moved/skipped` from `relocate_predictions` and forwards the rest verbatim.
   - `lp_predict(self, model_dir, videos, skip_viz, overwrite, dest_dir)` — signature unchanged from previous plan; matches existing `apply_async(args=[…])` in the route handler.

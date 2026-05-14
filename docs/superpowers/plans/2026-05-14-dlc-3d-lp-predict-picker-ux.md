# DLC-3D LP Predict — Analyze-style Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Predict card's plain textarea with the main webapp Analyze card's video/folder picker UX (text input + ↑Up + Browse + inline tree + batch queue), add an optional output-folder picker that defaults to each video's parent dir.

**Architecture:** Pure additive change to the existing `card_lp_predict.html` / `lp_cards.js` / `lp_routes.py` / `lp/tasks.py` / `lp/predict_runner.py`. The tree browser uses the main webapp's `/fs/ls?path=…` endpoint (same as analyze.js) on the same origin. Outputs land where `litpose predict` writes them, then a new `relocate_predictions()` step moves them per the user's choice.

**Tech Stack:** Vanilla ES module JS, Flask, pytest. No new dependencies.

**Reference spec:** `docs/superpowers/specs/2026-05-14-dlc-3d-lp-predict-picker-ux-design.md`

**Test fixture project:** `/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-TEST-LP` (already provisioned).

**Repo paths:**
- Module root: `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/`
- Main webapp (for compose only, not touched in this plan): `/home/sam/docker-images/deeplabcut-webapp-docker/`

---

## File Structure

**Modified:**
- `src/templates/partials/card_lp_predict.html` — replace videos textarea with the analyze-style target + browser + queue block; add output-folder block
- `src/static/lp_cards.js` — replace `initPredictCard()`'s videos/output wiring with the new picker behaviour
- `src/dlc_3d_bp/lp/predict_runner.py` — add `relocate_predictions(model_dir, videos, dest_dir, overwrite)`; existing `run_predict_subprocess` unchanged
- `src/dlc_3d_bp/lp/tasks.py` — `lp_predict` task accepts `dest_dir`, calls `relocate_predictions` after the subprocess
- `src/dlc_3d_bp/lp_routes.py` — `/lp/predict` accepts and validates `dest_dir`, forwards to task
- `tests/test_lp_routes.py` — three new route tests for `dest_dir`

**Created:**
- `tests/test_lp_predict_runner.py` — three new unit tests for `relocate_predictions`

**Untouched:** all other dlc-3D code, the main webapp, docker-compose.yml. No new packages.

---

## Phase 0 — Baseline checks

- [ ] **Step 0.1: Verify clean working tree on the supports repo**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git status --short dlc-3D/
```
Expected: clean for `dlc-3D/`. The spec from this session is committed.

- [ ] **Step 0.2: Baseline test run**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q --ignore=tests/e2e
```
Expected: all green. Note the count so you can confirm we don't regress.

---

## Phase 1 — Backend: `relocate_predictions()` helper

Implement and test the post-predict file-move helper. Subprocess and route untouched in this phase.

### Task 1.1: Helper signature + first happy-path test

**Files:**
- Create: `dlc-3D/tests/test_lp_predict_runner.py`
- Modify: `dlc-3D/src/dlc_3d_bp/lp/predict_runner.py`

- [ ] **Step 1.1.1: Write the failing test**

Create `dlc-3D/tests/test_lp_predict_runner.py`:
```python
from pathlib import Path

import pytest

from dlc_3d_bp.lp.predict_runner import relocate_predictions


def _seed_model_video_preds(model_dir: Path, video_stems: list[str], with_labeled_mp4: bool = True) -> None:
    """Create the `<model_dir>/video_preds/` layout litpose produces."""
    vp = model_dir / "video_preds"
    vp.mkdir(parents=True, exist_ok=True)
    for stem in video_stems:
        (vp / f"{stem}.csv").write_text("predictions,here\n")
        (vp / f"{stem}_pixel_error.csv").write_text("metric,here\n")
        if with_labeled_mp4:
            (vp / "labeled_videos").mkdir(exist_ok=True)
            (vp / "labeled_videos" / f"{stem}_labeled.mp4").write_bytes(b"\x00")


def test_relocate_to_explicit_dest_dir(tmp_path):
    model_dir = tmp_path / "model"
    dest = tmp_path / "out"
    videos_dir = tmp_path / "vids"; videos_dir.mkdir()
    v1 = videos_dir / "clipA.mp4"; v1.write_bytes(b"")
    v2 = videos_dir / "clipB.mp4"; v2.write_bytes(b"")
    _seed_model_video_preds(model_dir, ["clipA", "clipB"])

    result = relocate_predictions(model_dir, [v1, v2], dest_dir=dest, overwrite=False)

    assert (dest / "clipA.csv").is_file()
    assert (dest / "clipA_pixel_error.csv").is_file()
    assert (dest / "clipA_labeled.mp4").is_file()
    assert (dest / "clipB.csv").is_file()
    assert (dest / "clipB_labeled.mp4").is_file()
    # Source side cleaned up
    assert not (model_dir / "video_preds" / "clipA.csv").exists()
    assert not (model_dir / "video_preds" / "labeled_videos" / "clipA_labeled.mp4").exists()
    assert result["moved"] >= 6
    assert result["skipped"] == []
```

- [ ] **Step 1.1.2: Run test to verify it fails**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_lp_predict_runner.py::test_relocate_to_explicit_dest_dir -v
```
Expected: ImportError on `relocate_predictions`.

- [ ] **Step 1.1.3: Implement `relocate_predictions` minimally**

Append to `dlc-3D/src/dlc_3d_bp/lp/predict_runner.py`:
```python
import shutil


def relocate_predictions(
    model_dir: Path | str,
    videos: Iterable[Path | str],
    dest_dir: Path | str | None = None,
    overwrite: bool = False,
) -> dict:
    """Move per-video outputs from <model_dir>/video_preds/ to their final home.

    For each input video, looks under <model_dir>/video_preds/ for:
      - <stem>.csv                            (predictions)
      - <stem>_*.csv                          (per-metric losses)
      - labeled_videos/<stem>_labeled.mp4     (only if rendered)

    If ``dest_dir`` is None (or falsy), each video's outputs land in that
    video's parent directory. Otherwise everything lands in ``dest_dir``.
    The labeled MP4 is renamed to ``<stem>_labeled.mp4`` at the destination.

    When a destination file already exists and ``overwrite`` is False, the
    move is skipped and the source path is recorded in the ``skipped`` list.

    Returns {"moved": int, "skipped": [str], "dest_dir": str | None}.
    """
    model_dir = Path(model_dir)
    vp = model_dir / "video_preds"
    labeled = vp / "labeled_videos"
    moved = 0
    skipped: list[str] = []

    explicit_dest = Path(dest_dir) if dest_dir else None

    for v in videos:
        v = Path(v)
        stem = v.stem
        target_dir = explicit_dest if explicit_dest is not None else v.parent
        target_dir.mkdir(parents=True, exist_ok=True)

        for src in sorted(vp.glob(f"{stem}.csv")) + sorted(vp.glob(f"{stem}_*.csv")):
            dst = target_dir / src.name
            if dst.exists() and not overwrite:
                skipped.append(str(src))
                continue
            shutil.move(str(src), str(dst))
            moved += 1

        mp4 = labeled / f"{stem}_labeled.mp4"
        if mp4.is_file():
            dst = target_dir / f"{stem}_labeled.mp4"
            if dst.exists() and not overwrite:
                skipped.append(str(mp4))
            else:
                shutil.move(str(mp4), str(dst))
                moved += 1

    # Tidy: drop labeled_videos/ and video_preds/ if empty after moves
    if labeled.is_dir() and not any(labeled.iterdir()):
        labeled.rmdir()
    if vp.is_dir() and not any(vp.iterdir()):
        vp.rmdir()

    return {
        "moved": moved,
        "skipped": skipped,
        "dest_dir": str(explicit_dest) if explicit_dest is not None else None,
    }
```

- [ ] **Step 1.1.4: Run test to verify it passes**

Run:
```bash
python -m pytest tests/test_lp_predict_runner.py::test_relocate_to_explicit_dest_dir -v
```
Expected: PASS.

- [ ] **Step 1.1.5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/dlc_3d_bp/lp/predict_runner.py dlc-3D/tests/test_lp_predict_runner.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): relocate_predictions — move LP outputs per request"
```

### Task 1.2: Per-video default destination

**Files:**
- Modify: `dlc-3D/tests/test_lp_predict_runner.py`

- [ ] **Step 1.2.1: Write the failing test**

Append to `dlc-3D/tests/test_lp_predict_runner.py`:
```python
def test_relocate_per_video_default(tmp_path):
    """dest_dir=None puts each video's outputs in that video's parent folder."""
    model_dir = tmp_path / "model"
    vids_a = tmp_path / "session_a"; vids_a.mkdir()
    vids_b = tmp_path / "session_b"; vids_b.mkdir()
    va = vids_a / "rat1.mp4"; va.write_bytes(b"")
    vb = vids_b / "rat2.mp4"; vb.write_bytes(b"")
    _seed_model_video_preds(model_dir, ["rat1", "rat2"], with_labeled_mp4=False)

    result = relocate_predictions(model_dir, [va, vb], dest_dir=None)

    assert (vids_a / "rat1.csv").is_file()
    assert (vids_a / "rat1_pixel_error.csv").is_file()
    assert (vids_b / "rat2.csv").is_file()
    # Don't cross-contaminate
    assert not (vids_a / "rat2.csv").exists()
    assert not (vids_b / "rat1.csv").exists()
    assert result["dest_dir"] is None
    assert result["skipped"] == []
```

- [ ] **Step 1.2.2: Run test to verify it passes**

Run:
```bash
python -m pytest tests/test_lp_predict_runner.py::test_relocate_per_video_default -v
```
Expected: PASS (the helper from Task 1.1 already handles this case).

- [ ] **Step 1.2.3: Commit**

```bash
git add dlc-3D/tests/test_lp_predict_runner.py
git -c commit.gpgsign=false commit -m "test(dlc-3d): relocate_predictions per-video parent default"
```

### Task 1.3: Skip-on-conflict semantics

**Files:**
- Modify: `dlc-3D/tests/test_lp_predict_runner.py`

- [ ] **Step 1.3.1: Write the failing test**

Append to `dlc-3D/tests/test_lp_predict_runner.py`:
```python
def test_relocate_skips_on_conflict_without_overwrite(tmp_path):
    model_dir = tmp_path / "model"
    vids = tmp_path / "v"; vids.mkdir()
    video = vids / "rat.mp4"; video.write_bytes(b"")
    _seed_model_video_preds(model_dir, ["rat"], with_labeled_mp4=False)

    # Pre-existing destination — must not be clobbered
    existing = vids / "rat.csv"
    existing.write_text("DO_NOT_TOUCH\n")

    result = relocate_predictions(model_dir, [video], dest_dir=None, overwrite=False)

    assert existing.read_text() == "DO_NOT_TOUCH\n"
    # The non-conflicting metric CSV still moves
    assert (vids / "rat_pixel_error.csv").is_file()
    assert any("rat.csv" in s for s in result["skipped"])

    # Now with overwrite=True it should replace
    _seed_model_video_preds(model_dir, ["rat"], with_labeled_mp4=False)  # re-seed (the prev run moved metric out)
    result2 = relocate_predictions(model_dir, [video], dest_dir=None, overwrite=True)
    assert existing.read_text().startswith("predictions,here")
    assert result2["skipped"] == []
```

- [ ] **Step 1.3.2: Run test to verify it passes**

Run:
```bash
python -m pytest tests/test_lp_predict_runner.py -v
```
Expected: 3 passed.

- [ ] **Step 1.3.3: Commit**

```bash
git add dlc-3D/tests/test_lp_predict_runner.py
git -c commit.gpgsign=false commit -m "test(dlc-3d): relocate_predictions honours overwrite flag"
```

---

## Phase 2 — Backend: task + route accept `dest_dir`

### Task 2.1: `lp_predict` task takes `dest_dir` and calls relocator

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/tasks.py`

- [ ] **Step 2.1.1: Edit `lp_predict` to accept and use `dest_dir`**

Replace the existing `lp_predict` task in `dlc-3D/src/dlc_3d_bp/lp/tasks.py` with:
```python
@celery.task(bind=True, name="dlc_3d_lp.predict")
def lp_predict(self, model_dir: str, videos: list, skip_viz: bool = False, overwrite: bool = False, dest_dir: str = "") -> dict:
    """Run `litpose predict <model_dir> <video...>`, then relocate outputs.

    Output lands either in ``dest_dir`` (when non-empty) or in each video's
    parent directory (when empty). Streams stdout to a Redis log list and
    updates Celery state per line for live UI polling.
    """
    import os
    from .predict_runner import run_predict_subprocess, relocate_predictions

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

    rc = run_predict_subprocess(md, videos, skip_viz=skip_viz, overwrite=overwrite, log_callback=emit)
    if rc != 0:
        raise RuntimeError(f"litpose predict exited with code {rc}")

    relocate_info = relocate_predictions(md, videos, dest_dir=(dest_dir or None), overwrite=overwrite)
    return {
        "status": "ok",
        "model_dir": str(md),
        "dest_dir": relocate_info["dest_dir"] or "<per-video parent>",
        "moved": relocate_info["moved"],
        "skipped": relocate_info["skipped"],
    }
```

- [ ] **Step 2.1.2: Run the existing test suite — no regressions**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q --ignore=tests/e2e
```
Expected: same green count as baseline + 3 new tests from Phase 1.

- [ ] **Step 2.1.3: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/tasks.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): lp_predict task forwards dest_dir to relocator"
```

### Task 2.2: Route validates and forwards `dest_dir`

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp_routes.py`
- Test: `dlc-3D/tests/test_lp_routes.py`

- [ ] **Step 2.2.1: Write the failing tests**

Append to `dlc-3D/tests/test_lp_routes.py`:
```python
def test_predict_endpoint_accepts_empty_dest_dir(lp_app, monkeypatch, tmp_path):
    class _FakeAsync:
        id = "fake-id"
    captured = {}
    def _fake_apply(args=None, **kwargs):
        captured["args"] = list(args)
        return _FakeAsync()

    md = tmp_path / "m"; md.mkdir()
    monkeypatch.setattr("dlc_3d_bp.lp_routes._under_user_data", lambda p: True)
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    monkeypatch.setattr("dlc_3d_bp.lp.tasks.lp_predict.apply_async", _fake_apply)
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/predict", json={
        "model_dir": str(md),
        "videos": ["/user-data/x/v.mp4"],
        "dest_dir": "",
    })
    assert r.status_code == 202, r.get_data(as_text=True)
    # Args order: [model_dir, videos, skip_viz, overwrite, dest_dir]
    assert captured["args"][-1] == ""


def test_predict_endpoint_forwards_dest_dir(lp_app, monkeypatch, tmp_path):
    class _FakeAsync:
        id = "fake-id"
    captured = {}
    def _fake_apply(args=None, **kwargs):
        captured["args"] = list(args)
        return _FakeAsync()

    md = tmp_path / "m"; md.mkdir()
    monkeypatch.setattr("dlc_3d_bp.lp_routes._under_user_data", lambda p: True)
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    monkeypatch.setattr("dlc_3d_bp.lp.tasks.lp_predict.apply_async", _fake_apply)
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/predict", json={
        "model_dir": str(md),
        "videos": ["/user-data/x/v.mp4"],
        "dest_dir": "/user-data/where/i/want/it",
    })
    assert r.status_code == 202, r.get_data(as_text=True)
    assert captured["args"][-1] == "/user-data/where/i/want/it"


def test_predict_endpoint_rejects_dest_dir_outside_user_data(lp_app, monkeypatch, tmp_path):
    md = tmp_path / "m"; md.mkdir()
    # Allow model_dir + videos through but NOT dest_dir
    def _under(p):
        return not str(p).startswith("/etc")
    monkeypatch.setattr("dlc_3d_bp.lp_routes._under_user_data", _under)
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/predict", json={
        "model_dir": str(md),
        "videos": ["/user-data/x/v.mp4"],
        "dest_dir": "/etc/badplace",
    })
    assert r.status_code == 403
```

- [ ] **Step 2.2.2: Run tests to verify they fail**

Run:
```bash
python -m pytest tests/test_lp_routes.py::test_predict_endpoint_accepts_empty_dest_dir tests/test_lp_routes.py::test_predict_endpoint_forwards_dest_dir tests/test_lp_routes.py::test_predict_endpoint_rejects_dest_dir_outside_user_data -v
```
Expected: the two pass-through tests fail because the route doesn't forward `dest_dir`, and the third fails because there's no validation of `dest_dir`.

- [ ] **Step 2.2.3: Edit the `/lp/predict` route**

In `dlc-3D/src/dlc_3d_bp/lp_routes.py`, locate the `predict_run()` function. Replace the body with:
```python
@lp_bp.route("/predict", methods=["POST"])
def predict_run():
    from dlc_3d_bp.lp.tasks import lp_predict
    from dlc_3d_bp.lp.predict_runner import list_models

    body = request.get_json(force=True, silent=True) or {}
    model_dir = (body.get("model_dir") or "").strip()
    videos = body.get("videos") or []
    skip_viz = bool(body.get("skip_viz", False))
    overwrite = bool(body.get("overwrite", False))
    dest_dir = (body.get("dest_dir") or "").strip()

    # Default model_dir to the newest model in <active LP project>/models/
    if not model_dir:
        lp_project = (body.get("lp_project") or "").strip() or _active_lp_project_default()
        if not lp_project:
            return jsonify({"error": "no active DLC project — load one first or pass model_dir/lp_project"}), 400
        if not _under_user_data(Path(lp_project)):
            return jsonify({"error": "lp_project must be under /user-data"}), 403
        models = list_models(lp_project)
        usable = [m for m in models if m["has_checkpoint"]]
        if not usable:
            return jsonify({"error": f"no trained models with a checkpoint found under {lp_project}/models/"}), 400
        model_dir = usable[0]["path"]  # newest first per list_models()

    if not _under_user_data(Path(model_dir)):
        return jsonify({"error": "model_dir must be under /user-data"}), 403
    if not Path(model_dir).is_dir():
        return jsonify({"error": f"model_dir does not exist: {model_dir}"}), 400

    if not videos:
        return jsonify({"error": "at least one video required"}), 400
    for v in videos:
        if not _under_user_data(Path(v)):
            return jsonify({"error": f"video path outside /user-data: {v}"}), 403

    if dest_dir and not _under_user_data(Path(dest_dir)):
        return jsonify({"error": f"dest_dir outside /user-data: {dest_dir}"}), 403

    async_result = lp_predict.apply_async(args=[model_dir, videos, skip_viz, overwrite, dest_dir])
    conn = _redis_conn()
    if conn:
        from dlc_3d_bp.lp.job_registry import register
        register(conn, async_result.id, {
            "type": "predict",
            "model_dir": model_dir,
            "videos": videos,
            "skip_viz": skip_viz,
            "overwrite": overwrite,
            "dest_dir": dest_dir,
        })
    return jsonify({"job_id": async_result.id, "model_dir": model_dir, "dest_dir": dest_dir}), 202
```

- [ ] **Step 2.2.4: Run tests to verify they pass**

Run:
```bash
python -m pytest tests/test_lp_routes.py -q
```
Expected: all green, including the three new tests.

- [ ] **Step 2.2.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp_routes.py dlc-3D/tests/test_lp_routes.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): /lp/predict accepts and validates dest_dir"
```

---

## Phase 3 — Frontend: card markup

### Task 3.1: Replace videos textarea and add output-folder block

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_lp_predict.html`

- [ ] **Step 3.1.1: Replace the videos field and append the output-folder field**

Open `dlc-3D/src/templates/partials/card_lp_predict.html`. Delete the existing block:
```html
  <div class="lp-field">
    <label>Videos to predict on <span style="color:var(--text-dim);font-weight:400;text-transform:none;letter-spacing:0">(one absolute path per line)</span></label>
    <textarea id="lp-predict-videos" rows="4" style="font-family:var(--mono);font-size:.74rem;padding:.3rem .5rem;background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text);width:100%;min-height:5rem" placeholder="/user-data/.../video1.mp4
/user-data/.../video2.mp4"></textarea>
  </div>
```

Replace it with:
```html
  <!-- ── Videos: analyze-card-style target + browser + queue ─────────── -->
  <div class="lp-field">
    <label>Videos to predict on</label>
    <div style="display:flex;gap:.4rem">
      <input type="text" id="lp-predict-target" placeholder="/path/to/video.mp4  or  /path/to/folder"
        style="flex:1;font-family:var(--mono);font-size:.78rem;padding:.35rem .55rem;background:var(--surface-2);border:1px solid var(--border);border-radius:5px;color:var(--text)" />
      <button class="btn-sm" id="lp-predict-browse-up" style="padding:.2rem .45rem;font-size:.75rem" title="Go up one level">↑ Up</button>
      <button class="btn-sm" id="lp-predict-browse-btn" title="Browse for videos and folders">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        Browse
      </button>
    </div>
    <div id="lp-predict-browser" class="hidden" style="margin-top:.5rem;max-height:240px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);padding:.4rem .5rem;font-size:.77rem"></div>
    <div style="display:flex;gap:.4rem;margin-top:.4rem;align-items:center;flex-wrap:wrap">
      <button class="btn-sm" id="lp-predict-batch-add-btn" title="Add highlighted path to the prediction queue" style="opacity:.85">+ Add to queue</button>
      <button class="btn-sm" id="lp-predict-batch-clear-btn" title="Clear all queued paths" style="opacity:.7">✕ Clear queue</button>
      <span style="font-size:.72rem;color:var(--text-dim)">Single-click to highlight · double-click to add instantly</span>
    </div>
    <div id="lp-predict-batch-list" style="margin-top:.4rem;display:none;border:1px solid var(--border);border-radius:5px;background:var(--surface-2);max-height:140px;overflow-y:auto;padding:.3rem .4rem;font-size:.74rem;font-family:var(--mono)"></div>
  </div>

  <!-- ── Output folder (optional; default: each video's parent dir) ─── -->
  <div class="lp-field">
    <label>Output folder <span style="color:var(--text-dim);font-weight:400;text-transform:none;letter-spacing:0">(optional; default: same folder as each video)</span></label>
    <div style="display:flex;gap:.4rem">
      <input type="text" id="lp-predict-destfolder" placeholder="leave empty for per-video parent folder"
        style="flex:1;font-family:var(--mono);font-size:.78rem;padding:.35rem .55rem;background:var(--surface-2);border:1px solid var(--border);border-radius:5px;color:var(--text)" />
      <button class="btn-sm" id="lp-predict-dest-up" style="padding:.2rem .45rem;font-size:.75rem" title="Go up one level">↑ Up</button>
      <button class="btn-sm" id="lp-predict-dest-browse-btn" title="Browse output folder">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        Browse
      </button>
      <button class="btn-sm" id="lp-predict-dest-clear-btn" title="Clear (use default)" style="opacity:.7">✕</button>
    </div>
    <div id="lp-predict-dest-browser" class="hidden" style="margin-top:.5rem;max-height:180px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);padding:.4rem .5rem;font-size:.77rem"></div>
  </div>
```

Keep the `skip_viz`, `overwrite`, `Run prediction` button, and result panel exactly as they are below this block.

- [ ] **Step 3.1.2: Sanity check the partial parses**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_lp_routes.py::test_index_renders_with_lp_cards -v
```
Expected: PASS (Jinja still parses the page; we didn't break the document).

- [ ] **Step 3.1.3: Commit**

```bash
git add dlc-3D/src/templates/partials/card_lp_predict.html
git -c commit.gpgsign=false commit -m "feat(dlc-3d): Predict card markup — analyze-style picker + output dir"
```

---

## Phase 4 — Frontend: JS for the new pickers

### Task 4.1: Rewrite `initPredictCard()`'s videos/output wiring

**Files:**
- Modify: `dlc-3D/src/static/lp_cards.js`

- [ ] **Step 4.1.1: Replace `initPredictCard` with the new wiring**

Open `dlc-3D/src/static/lp_cards.js`. Replace the entire `initPredictCard` function (from `function initPredictCard() {` up to but not including its `initPredictCard();` invocation) with the body below. Keep the `initPredictCard();` call line that follows it.

```javascript
function initPredictCard() {
  const card = $("#lp-predict-card");
  if (!card) return;

  const projectEl     = $("#lp-predict-project");
  const modelEl       = $("#lp-predict-model");
  const noteEl        = $("#lp-predict-model-note");

  const targetEl      = $("#lp-predict-target");
  const browseUpEl    = $("#lp-predict-browse-up");
  const browseBtnEl   = $("#lp-predict-browse-btn");
  const browserEl     = $("#lp-predict-browser");
  const batchAddEl    = $("#lp-predict-batch-add-btn");
  const batchClearEl  = $("#lp-predict-batch-clear-btn");
  const batchListEl   = $("#lp-predict-batch-list");

  const destEl        = $("#lp-predict-destfolder");
  const destUpEl      = $("#lp-predict-dest-up");
  const destBrowseEl  = $("#lp-predict-dest-browse-btn");
  const destBrowserEl = $("#lp-predict-dest-browser");
  const destClearEl   = $("#lp-predict-dest-clear-btn");

  const skipVizEl     = $("#lp-predict-skip-viz");
  const overwriteEl   = $("#lp-predict-overwrite");
  const runEl         = $("#btn-lp-predict-run");
  const resEl         = $("#lp-predict-result");

  $("#btn-close-lp-predict")?.addEventListener("click", () => card.classList.add("hidden"));

  // ── LP project + model dropdown (unchanged from previous behaviour) ──
  let lastAutoFill = "";
  const syncProjectField = () => {
    const dlc = activeDlcProjectFromDom();
    const auto = dlc ? dlc.replace(/\/+$/, "") + "-LP" : "";
    if (projectEl.value === "" || projectEl.value === lastAutoFill) {
      projectEl.value = auto;
      lastAutoFill = auto;
    }
  };

  async function reloadModels() {
    const p = projectEl.value.trim();
    modelEl.innerHTML = '<option value="">— loading… —</option>';
    noteEl.textContent = "";
    const url = "/dlc-3d/lp/models" + (p ? `?lp_project=${encodeURIComponent(p)}` : "");
    let body;
    try {
      const r = await fetch(url);
      body = await r.json();
      if (!r.ok) { modelEl.innerHTML = `<option value="">— ${body.error || "error"} —</option>`; return; }
    } catch (e) {
      modelEl.innerHTML = `<option value="">— ${e.message} —</option>`; return;
    }
    const models = body.models || [];
    if (!models.length) {
      modelEl.innerHTML = '<option value="">— no models found —</option>';
      noteEl.textContent = "Train a model first, or pick a different LP project.";
      return;
    }
    const usable = models.filter((m) => m.has_checkpoint);
    modelEl.innerHTML = models.map((m) => {
      const label = `${m.run_id}${m.has_checkpoint ? " ✓" : " (no checkpoint)"}${m.has_predictions ? " · trained" : ""}`;
      const disabled = m.has_checkpoint ? "" : " disabled";
      return `<option value="${m.path}"${disabled}>${label}</option>`;
    }).join("");
    if (usable.length) modelEl.value = usable[0].path;
    noteEl.textContent = `${usable.length} usable model${usable.length === 1 ? "" : "s"} of ${models.length} total`;
  }

  new MutationObserver(() => { syncProjectField(); reloadModels(); })
    .observe(card, { attributes: true, attributeFilter: ["class"] });
  const upstream = document.getElementById("dlc-active-path");
  if (upstream) {
    new MutationObserver(() => { syncProjectField(); reloadModels(); })
      .observe(upstream, { childList: true, characterData: true, subtree: true });
  }
  projectEl.addEventListener("change", reloadModels);
  syncProjectField();

  // ── Tree browser (mirrors analyze.js video picker) ─────────────────
  const VIDEO_EXTS  = new Set([".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v"]);
  const IMAGE_EXTS  = new Set([".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"]);
  const supportedFile = (name) => {
    const i = name.lastIndexOf(".");
    return i >= 0 && (VIDEO_EXTS.has(name.slice(i).toLowerCase()) || IMAGE_EXTS.has(name.slice(i).toLowerCase()));
  };

  /** Per-browser state. */
  function makeBrowser({ inputEl, paneEl, dirOnly }) {
    let highlightedRow = null;
    let highlightedPath = "";
    let browserLoaded = false;
    let currentDir = "";

    function setHighlight(row, path) {
      if (highlightedRow && highlightedRow !== row) {
        highlightedRow.style.background = "";
        highlightedRow.style.outline = "";
      }
      highlightedRow = row;
      highlightedPath = path;
      inputEl.value = path;
      row.style.background = "var(--accent-dim, rgba(99,179,237,.18))";
      row.style.outline = "1px solid var(--accent, #63b3ed)";
    }

    function makeEntry(name, fullPath, isDir) {
      const wrapper = document.createElement("div");
      const row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;gap:.3rem;padding:.15rem .4rem;border-radius:3px;cursor:pointer";
      const arrow = document.createElement("span");
      arrow.style.cssText = "width:.8rem;color:var(--text-dim);font-size:.7rem";
      arrow.textContent = isDir ? "▶" : "·";
      const label = document.createElement("span");
      label.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:var(--mono);font-size:.74rem";
      label.textContent = name + (isDir ? "/" : "");
      row.appendChild(arrow); row.appendChild(label);
      wrapper.appendChild(row);

      const childContainer = document.createElement("div");
      childContainer.style.cssText = "display:none;padding-left:1rem";
      wrapper.appendChild(childContainer);

      let loaded = false, expanded = false;

      if (isDir) {
        row.addEventListener("click", async () => {
          setHighlight(row, fullPath);
          if (!expanded && !loaded) {
            childContainer.innerHTML = `<span style="font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block">Loading…</span>`;
            childContainer.style.display = "block";
            try {
              const res = await fetch(`/fs/ls?path=${encodeURIComponent(fullPath)}`);
              const d = await res.json();
              childContainer.innerHTML = "";
              if (!d.error) {
                const vis = (d.entries || []).filter((e) =>
                  (e.type === "dir" && e.has_media !== false) ||
                  (!dirOnly && e.type === "file" && supportedFile(e.name)));
                vis.forEach((e) =>
                  childContainer.appendChild(makeEntry(e.name, fullPath.replace(/\/+$/, "") + "/" + e.name, e.type === "dir")));
                if (!vis.length) childContainer.innerHTML = `<span style="font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block">(no supported entries)</span>`;
              } else {
                childContainer.innerHTML = `<span style="font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block">${d.error}</span>`;
              }
            } catch (e) {
              childContainer.innerHTML = `<span style="font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block">Error loading.</span>`;
            }
            loaded = true; expanded = true; arrow.textContent = "▼";
          } else {
            expanded = !expanded;
            childContainer.style.display = expanded ? "block" : "none";
            arrow.textContent = expanded ? "▼" : "▶";
          }
        });
      } else {
        row.addEventListener("click", () => setHighlight(row, fullPath));
      }

      // Double-click: emit a custom event the parent wires to its queue handler
      row.addEventListener("dblclick", (e) => {
        e.stopPropagation();
        inputEl.value = fullPath;
        paneEl.dispatchEvent(new CustomEvent("lp-picker-dblclick", { detail: { path: fullPath }, bubbles: false }));
        paneEl.classList.add("hidden");
        browserLoaded = false;
      });

      return wrapper;
    }

    async function browseDir(dirPath) {
      browserLoaded = false;
      currentDir = dirPath;
      inputEl.value = dirPath;
      paneEl.innerHTML = `<span style="font-size:.8rem;color:var(--text-dim)">Loading…</span>`;
      try {
        const res = await fetch(`/fs/ls?path=${encodeURIComponent(dirPath)}`);
        const data = await res.json();
        if (data.error) { paneEl.textContent = data.error; return; }
        paneEl.innerHTML = "";
        const visible = (data.entries || []).filter((e) =>
          (e.type === "dir" && e.has_media !== false) ||
          (!dirOnly && e.type === "file" && supportedFile(e.name)));
        if (!visible.length) {
          const empty = document.createElement("span");
          empty.style.cssText = "font-size:.78rem;color:var(--text-dim);padding:.3rem;display:block";
          empty.textContent = dirOnly ? "(no subfolders)" : "(no supported video or image files)";
          paneEl.appendChild(empty);
        } else {
          visible.forEach((e) =>
            paneEl.appendChild(makeEntry(e.name, (data.path || dirPath).replace(/\/+$/, "") + "/" + e.name, e.type === "dir")));
        }
        browserLoaded = true;
      } catch (err) {
        paneEl.textContent = "Failed to load.";
      }
    }

    function openAt(initialPath) {
      const isHidden = paneEl.classList.contains("hidden");
      paneEl.classList.toggle("hidden");
      if (!isHidden) return; // we were open → just close
      const typed = inputEl.value.trim() || initialPath || "/user-data";
      browseDir(typed);
    }

    function up() {
      const cur = (inputEl.value.trim() || currentDir).replace(/\/+$/, "");
      if (!cur) return;
      const parent = cur.split("/").slice(0, -1).join("/") || "/";
      if (parent !== cur) { browseDir(parent); paneEl.classList.remove("hidden"); }
    }

    return { browseDir, openAt, up, getHighlighted: () => highlightedPath };
  }

  // ── Videos picker ───────────────────────────────────────────────────
  const videoBrowser = makeBrowser({ inputEl: targetEl, paneEl: browserEl, dirOnly: false });
  const queue = []; // ordered, deduped

  function renderQueue() {
    if (!queue.length) {
      batchListEl.style.display = "none";
      batchListEl.innerHTML = "";
      return;
    }
    batchListEl.style.display = "block";
    batchListEl.innerHTML = "";
    queue.forEach((p, i) => {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;gap:.3rem;padding:.1rem 0";
      const txt = document.createElement("span");
      txt.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
      txt.textContent = p;
      const rm = document.createElement("button");
      rm.className = "btn-sm"; rm.style.cssText = "padding:0 .35rem;font-size:.7rem;opacity:.6";
      rm.textContent = "×"; rm.title = "Remove";
      rm.addEventListener("click", () => { queue.splice(i, 1); renderQueue(); });
      row.appendChild(txt); row.appendChild(rm);
      batchListEl.appendChild(row);
    });
  }

  function addToQueue(p) {
    p = (p || "").trim();
    if (!p) return;
    if (!queue.includes(p)) queue.push(p);
    renderQueue();
  }

  browserEl.addEventListener("lp-picker-dblclick", (e) => addToQueue(e.detail.path));
  batchAddEl.addEventListener("click", () => addToQueue(videoBrowser.getHighlighted() || targetEl.value));
  batchClearEl.addEventListener("click", () => { queue.length = 0; renderQueue(); });

  browseBtnEl.addEventListener("click", () => {
    const fallback = (projectEl.value.trim().replace(/-LP\/?$/, "")) || "/user-data";
    videoBrowser.openAt(fallback);
  });
  browseUpEl.addEventListener("click", () => videoBrowser.up());
  targetEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); videoBrowser.browseDir(targetEl.value.trim()); browserEl.classList.remove("hidden"); }
  });

  // ── Output folder picker (dir-only) ────────────────────────────────
  const destBrowser = makeBrowser({ inputEl: destEl, paneEl: destBrowserEl, dirOnly: true });
  destBrowseEl.addEventListener("click", () => destBrowser.openAt(destEl.value.trim() || "/user-data"));
  destUpEl.addEventListener("click", () => destBrowser.up());
  destClearEl.addEventListener("click", () => { destEl.value = ""; destBrowserEl.classList.add("hidden"); });
  destEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); destBrowser.browseDir(destEl.value.trim()); destBrowserEl.classList.remove("hidden"); }
  });

  // ── Submit ─────────────────────────────────────────────────────────
  runEl.addEventListener("click", async () => {
    runEl.disabled = true;
    resEl.hidden = false;
    resEl.textContent = "Submitting…";
    const videos = queue.length ? queue.slice() : (targetEl.value.trim() ? [targetEl.value.trim()] : []);
    if (!videos.length) {
      resEl.textContent = "Error: queue at least one video (browse + double-click, or + Add to queue).";
      runEl.disabled = false;
      return;
    }
    const payload = {
      lp_project: projectEl.value.trim() || undefined,
      model_dir:  modelEl.value || undefined,
      videos,
      skip_viz:   skipVizEl.checked,
      overwrite:  overwriteEl.checked,
      dest_dir:   destEl.value.trim(),
    };
    try {
      const r = await fetch("/dlc-3d/lp/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await r.json();
      if (!r.ok) { resEl.textContent = "Error: " + JSON.stringify(body, null, 2); return; }
      const jobId = body.job_id;
      resEl.textContent = `Job ${jobId}: PENDING\nmodel_dir: ${body.model_dir || ""}\ndest: ${body.dest_dir || "<per-video parent>"}`;
      await pollJob(jobId, (j) => {
        const tail = (j.log_tail || []).slice(-30).join("\n");
        resEl.textContent =
          `state: ${j.celery_state || "PENDING"}\n` +
          `model_dir: ${j.celery_info?.model_dir || j.model_dir || ""}\n` +
          `dest: ${j.celery_info?.dest_dir || j.dest_dir || "<per-video parent>"}\n` +
          `--- log tail ---\n${tail}`;
      }, 2500);
    } finally {
      runEl.disabled = false;
    }
  });
}
```

- [ ] **Step 4.1.2: Restart dlc-3d to pick up the changes**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d
sleep 3
docker compose exec dlc-3d python3 -c "
import urllib.request
html = urllib.request.urlopen('http://localhost:5050/dlc-3d/').read().decode()
for needed in ('lp-predict-target','lp-predict-browser','lp-predict-batch-list','lp-predict-destfolder','lp-predict-dest-browser'):
    assert f'id=\"{needed}\"' in html, needed
print('all picker DOM ids present')
"
```
Expected: prints `all picker DOM ids present`.

- [ ] **Step 4.1.3: Browser smoke check (manual)**

Hard-refresh `http://localhost:5000/dlc-3d/`. Open the Lightning-Pose launcher → Predict (Inference). Verify:
- Browse next to the Videos field opens an inline tree pane.
- Single-click highlights a row; double-click adds to the queue and closes the pane.
- `↑ Up` navigates up.
- `+ Add to queue` works with both a highlighted row and a typed path.
- `✕ Clear queue` empties the list.
- The Output folder Browse opens a dir-only tree (no video files shown).
- `✕` next to output clears the field.

Note any issues; if a behaviour deviates from analyze.js, fix in place before commit.

- [ ] **Step 4.1.4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/lp_cards.js
git -c commit.gpgsign=false commit -m "feat(dlc-3d): Predict card JS — analyze-style video/output pickers"
```

---

## Phase 5 — Live integration smoke

### Task 5.1: End-to-end predict with the new picker

- [ ] **Step 5.1.1: Confirm worker has the new task signature**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d-worker
sleep 4
docker compose logs --tail=30 dlc-3d-worker | grep -E "ready|error|Traceback"
```
Expected: a `celery@…ready` line and no traceback.

- [ ] **Step 5.1.2: Predict from the UI on a fixture video**

In the browser:
1. Load the fixture DLC project `DREADD-Ali-2026-01-07-LP-TEST` via the DLC Project Manager card.
2. Open the Predict card.
3. The LP project path auto-fills to `…/DREADD-Ali-2026-01-07-LP-TEST-LP`; pick a usable model (`20260513-144824 ✓` — the one we previously trained).
4. In Videos: Browse → navigate under `/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-TEST/videos/` → double-click any non-zero-byte mp4 (if none exist in fixture, point at any video under `/user-data/` you have access to).
5. Leave Output folder empty.
6. Click `Run prediction`. Watch state move PENDING → STARTED → SUCCESS. The log tail should show "Predicting DataLoader 0:" lines.

- [ ] **Step 5.1.3: Verify outputs landed in the video's parent**

After SUCCESS:
```bash
ls -la <video_parent_dir>/<video_stem>.csv 2>&1 | head
```
Expected: predictions CSV next to the source video. If `Create labeled video` was NOT skipped, a `<stem>_labeled.mp4` is also there.

- [ ] **Step 5.1.4: Re-run with an explicit dest_dir**

Pick an absolute path under `/user-data/` in the Output folder field, run again, verify all outputs land there instead of next to the source.

- [ ] **Step 5.1.5: Record the smoke run in project memory**

Append a one-liner to `~/.claude/projects/-home-sam-docker-images-deeplabcut-webapp-docker-supports/memory/project_lp_smoke_2026-05-13.md` under "Live validated":
```
- 2026-05-14: Predict card analyze-style picker — per-video default + explicit dest_dir both verified end-to-end.
```

- [ ] **Step 5.1.6: Final commit (if any fixups landed)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git status --short dlc-3D/
# If anything is unstaged from the smoke iteration:
git -c commit.gpgsign=false commit -am "fix(dlc-3d): post-smoke fixups for analyze-style Predict picker"
```

---

## Self-Review Notes

1. **Spec coverage:**
   - §1 UX parity → Task 3.1 (markup) + Task 4.1 (tree, queue, ↑Up, Enter, double-click).
   - §2 Behaviour table → Task 4.1 (`makeBrowser`, highlight, single/double-click handlers, queue helpers).
   - §3 Output semantics → Task 1.1–1.3 (`relocate_predictions`) + Task 2.1 (task calls it) + Task 2.2 (route forwards `dest_dir`).
   - §4 Backend changes → Tasks 2.1, 2.2.
   - §5 Files touched list → matches plan's File Structure.
   - §6 Testing → six tests across Phases 1 and 2; UI smoke in Phase 5.

2. **Placeholder scan:** no TBD/TODO. Every code step shows full code. Every command shows expected output.

3. **Type consistency:**
   - `lp_predict(self, model_dir, videos, skip_viz, overwrite, dest_dir)` matches `apply_async(args=[model_dir, videos, skip_viz, overwrite, dest_dir])` in the route (Task 2.2 step 2.2.3).
   - `relocate_predictions(model_dir, videos, dest_dir, overwrite)` matches both the test calls and the task call.
   - JS `makeBrowser({ inputEl, paneEl, dirOnly })` factory consumed identically for the videos and dest pickers.
   - All `lp-predict-*` element IDs introduced in Task 3.1 are referenced in Task 4.1; the smoke check in Step 4.1.2 asserts the IDs exist post-restart.

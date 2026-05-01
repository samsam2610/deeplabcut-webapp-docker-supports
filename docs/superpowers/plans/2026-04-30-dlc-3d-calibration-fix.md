# DLC-3D Calibration Fix + Sync-Cam Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the calibration.toml source location so it copies correctly into `labeled-data/<session>/` for both in-project and out-of-project recordings (including clips nested in video-named subfolders), and add sync-cam validation that surfaces a clear error if calibration.toml is missing from the expected folder.

**Architecture:** Two tightly-related tasks, both backend + tests + frontend. Task 1 fixes the source-folder priority in `_save_single_frame` (parent → grandparent fallback) and adds two tests covering the new layouts. Task 2 enriches the `/sibling-camera` response with `calibration_exists` (using the same priority logic), threads it through `_selectVideo` → `openPlayer`, and guards the Sync Cam checkbox so it cannot be enabled when calibration is missing.

**Tech Stack:** Python 3.9 (Flask blueprint), `shutil.copy2` for the file copy, ES6 modules (`enhanced_player.js`, `dlc_3d.js`), pytest for unit tests.

---

## File Map

| File | What changes |
|------|-------------|
| `dlc-3D/src/dlc_3d_bp/routes.py` | Task 1: `_save_single_frame` calibration source priority. Task 2: `/sibling-camera` adds `calibration_exists`. |
| `dlc-3D/tests/test_core.py` | Task 1: 2 new tests for parent + grandparent layouts. Task 2: 2 new tests for sibling-camera calibration reporting. |
| `dlc-3D/src/static/dlc_3d.js` | Task 2: capture `calibration_exists` from `/sibling-camera` response, pass to `openPlayer`. |
| `dlc-3D/src/static/enhanced_player.js` | Task 2: `openPlayer` accepts `calibrationExists`; sync-cam checkbox guards against missing calibration. |

---

## Task 1: Fix calibration source location in `_save_single_frame`

The existing code reads calibration from `project_path / "videos" / "calibration.toml"`, which only works when the video lives inside the project's videos folder. With out-of-project videos now supported, calibration.toml lives in the recording folder next to the videos. For clips nested in video-named subfolders, calibration is one level up.

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/routes.py`
- Modify: `dlc-3D/tests/test_core.py`

- [ ] **Step 1: Add the first failing test (out-of-project recording)**

Append to `dlc-3D/tests/test_core.py`:

```python
# ── Calibration source location ──────────────────────────────────────────────

def test_save_frame_copies_calibration_from_video_parent_folder(tmp_path, monkeypatch):
    """Out-of-project layout: calibration.toml lives next to the videos
    in /user-data/<recording>/, not under proj/videos/."""
    import config
    from dlc_3d_bp import routes
    monkeypatch.setattr(config, "USER_DATA_ROOTS", [tmp_path])
    monkeypatch.setattr(routes, "_USER_DATA_ROOT", str(tmp_path))

    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()
    (rec_dir / "calibration.toml").write_text("[cam_0]\n")
    video = rec_dir / "surv1_cam0_20260123_121732_0.avi"
    _make_video(video, frames=10)

    proj = tmp_path / "project"
    (proj / "videos").mkdir(parents=True)

    routes._save_single_frame(proj, str(video), 3)

    assert (proj / "labeled-data" / "surv1_20260123" / "calibration.toml").is_file()
```

- [ ] **Step 2: Run the test (expect FAIL — calibration not copied because the current code only looks under `proj/videos/`)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py::test_save_frame_copies_calibration_from_video_parent_folder -v
```

Expected: FAIL with `assert False` (calibration not copied).

- [ ] **Step 3: Update the calibration-copy block in `_save_single_frame`**

In `dlc-3D/src/dlc_3d_bp/routes.py`, find this block in `_save_single_frame` (lines 241–246):

```python
    # Copy calibration.toml on first save (no existing PNGs before this one)
    if order == 0:
        calib_src  = project_path / "videos" / "calibration.toml"
        calib_dest = labeled_dir / "calibration.toml"
        if calib_src.exists() and not calib_dest.exists():
            shutil.copy2(calib_src, calib_dest)
```

Replace with:

```python
    # Copy calibration.toml on first save. Source priority:
    #   1. video's own parent folder
    #   2. grandparent folder when video is inside a clip subfolder
    if order == 0:
        calib_dest = labeled_dir / "calibration.toml"
        if not calib_dest.exists():
            calib_candidates = [video_path.parent / "calibration.toml"]
            if _session_key_from_stem(video_path.parent.name) is not None:
                calib_candidates.append(video_path.parent.parent / "calibration.toml")
            for calib_src in calib_candidates:
                if calib_src.exists():
                    shutil.copy2(calib_src, calib_dest)
                    break
```

`video_path` is already resolved earlier in the function via `_resolve_video_path`. `_session_key_from_stem` is the existing helper used elsewhere in the same function to detect clip-folder layout.

- [ ] **Step 4: Run the test (expect PASS)**

```bash
python -m pytest tests/test_core.py::test_save_frame_copies_calibration_from_video_parent_folder -v
```

Expected: PASS.

- [ ] **Step 5: Add the clip-folder grandparent test**

Append to `dlc-3D/tests/test_core.py`:

```python
def test_save_frame_copies_calibration_from_clip_grandparent(tmp_path, monkeypatch):
    """Clip layout: clip_001.avi sits inside a video-named subfolder of the
    recording dir; calibration.toml is one level up at the recording root."""
    import config
    from dlc_3d_bp import routes
    monkeypatch.setattr(config, "USER_DATA_ROOTS", [tmp_path])
    monkeypatch.setattr(routes, "_USER_DATA_ROOT", str(tmp_path))

    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()
    (rec_dir / "calibration.toml").write_text("[cam_0]\n")
    clip_dir = rec_dir / "surv1_cam0_20260123_121732_0"
    clip_dir.mkdir()
    clip = clip_dir / "clip_001.avi"
    _make_video(clip, frames=10)

    proj = tmp_path / "project"
    (proj / "videos").mkdir(parents=True)

    routes._save_single_frame(proj, str(clip), 3)

    assert (proj / "labeled-data" / "surv1_20260123" / "calibration.toml").is_file()
```

- [ ] **Step 6: Run all calibration tests + full suite**

```bash
python -m pytest tests/test_core.py -v -k calibration
```

Expected: 2 new tests pass, plus `test_save_frame_copies_calibration` (existing) still passes.

```bash
python -m pytest tests/test_core.py -v
```

Expected: 41 passed (39 prior + 2 new).

- [ ] **Step 7: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/routes.py dlc-3D/tests/test_core.py
git commit -m "fix: copy calibration.toml from video's parent folder (with clip-folder fallback)"
```

---

## Task 2: Sync-Cam validation against missing calibration

When the user toggles Sync Cam ON, throw a clear error if calibration.toml is missing from the recording folder. Implementation: `/sibling-camera` reports `calibration_exists`, the frontend stores it, and the checkbox handler refuses to enable when the flag is false.

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/routes.py` (extend `/sibling-camera` response)
- Modify: `dlc-3D/tests/test_core.py` (2 new tests)
- Modify: `dlc-3D/src/static/dlc_3d.js` (capture flag, pass to `openPlayer`)
- Modify: `dlc-3D/src/static/enhanced_player.js` (accept flag, gate sync-cam toggle)

- [ ] **Step 1: Add the first failing test (calibration present)**

Append to `dlc-3D/tests/test_core.py`:

```python
# ── /sibling-camera calibration reporting ────────────────────────────────────

def test_sibling_camera_reports_calibration_exists(tmp_path, monkeypatch):
    """When calibration.toml is present in the recording folder, the
    /sibling-camera response reports calibration_exists=True."""
    from flask import Flask
    import config
    from dlc_3d_bp import routes
    monkeypatch.setattr(config, "USER_DATA_ROOTS", [tmp_path])
    monkeypatch.setattr(routes, "_USER_DATA_ROOT", str(tmp_path))

    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()
    (rec_dir / "calibration.toml").write_text("[cam_0]\n")
    cam0 = rec_dir / "surv1_cam0_20260123_121732_0.avi"
    cam1 = rec_dir / "surv1_cam1_20260123_121732_0.avi"
    cam0.write_bytes(b"")
    cam1.write_bytes(b"")

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    client = app.test_client()

    resp = client.get(f"/dlc-3d/sibling-camera?video={cam0}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["sibling_video_path"] == str(cam1)
    assert data["calibration_exists"] is True
```

- [ ] **Step 2: Run the test (expect FAIL — `calibration_exists` key not in response)**

```bash
python -m pytest tests/test_core.py::test_sibling_camera_reports_calibration_exists -v
```

Expected: FAIL with `KeyError: 'calibration_exists'`.

- [ ] **Step 3: Refactor `/sibling-camera` to compute and return `calibration_exists`**

In `dlc-3D/src/dlc_3d_bp/routes.py`, find the existing `/sibling-camera` route (lines 388–407):

```python
@bp.route("/sibling-camera")
def get_sibling_camera():
    with _state_lock:
        proj = _active_project
    video_path = request.args.get("video", "").strip()
    if not video_path or not proj:
        return jsonify({"sibling_video_path": None})

    sibling = _find_sibling_on_filesystem(video_path)
    if sibling and str(Path(sibling).resolve()).startswith(_USER_DATA_ROOT + "/"):
        return jsonify({"sibling_video_path": sibling})

    sibling = None
    if not video_path.startswith("/"):
        vj_path = Path(proj) / "videos.json"
        if vj_path.exists():
            with open(vj_path) as f:
                videos_json = json.load(f)
            sibling = _find_sibling_video(video_path, videos_json)
    return jsonify({"sibling_video_path": sibling})
```

Replace with (refactored so the calibration check runs regardless of which sibling-lookup branch took, and the response always includes `calibration_exists`):

```python
@bp.route("/sibling-camera")
def get_sibling_camera():
    with _state_lock:
        proj = _active_project
    video_path = request.args.get("video", "").strip()
    if not video_path:
        return jsonify({"sibling_video_path": None, "calibration_exists": False})

    # ── Sibling lookup ──
    sibling = _find_sibling_on_filesystem(video_path)
    if not (sibling and str(Path(sibling).resolve()).startswith(_USER_DATA_ROOT + "/")):
        sibling = None
        if proj and not video_path.startswith("/"):
            vj_path = Path(proj) / "videos.json"
            if vj_path.exists():
                with open(vj_path) as f:
                    videos_json = json.load(f)
                sibling = _find_sibling_video(video_path, videos_json)

    # ── Calibration check (same priority as _save_single_frame) ──
    resolved = _resolve_video_path(video_path, proj or _USER_DATA_ROOT)
    calibration_exists = False
    if resolved is not None:
        candidates = [resolved.parent / "calibration.toml"]
        if _session_key_from_stem(resolved.parent.name) is not None:
            candidates.append(resolved.parent.parent / "calibration.toml")
        calibration_exists = any(p.is_file() for p in candidates)

    return jsonify({
        "sibling_video_path": sibling,
        "calibration_exists": calibration_exists,
    })
```

Note: the original code returned `{"sibling_video_path": None}` when `not proj` was true, even if the request had a valid absolute path. The refactor relaxes this so absolute paths still get a calibration check (which is correct behavior — calibration check doesn't need an active project).

- [ ] **Step 4: Run the test (expect PASS)**

```bash
python -m pytest tests/test_core.py::test_sibling_camera_reports_calibration_exists -v
```

Expected: PASS.

- [ ] **Step 5: Add the calibration-missing test**

Append to `dlc-3D/tests/test_core.py`:

```python
def test_sibling_camera_reports_calibration_missing(tmp_path, monkeypatch):
    """When calibration.toml is absent, calibration_exists=False."""
    from flask import Flask
    import config
    from dlc_3d_bp import routes
    monkeypatch.setattr(config, "USER_DATA_ROOTS", [tmp_path])
    monkeypatch.setattr(routes, "_USER_DATA_ROOT", str(tmp_path))

    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()
    cam0 = rec_dir / "surv1_cam0_20260123_121732_0.avi"
    cam1 = rec_dir / "surv1_cam1_20260123_121732_0.avi"
    cam0.write_bytes(b"")
    cam1.write_bytes(b"")

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    client = app.test_client()

    resp = client.get(f"/dlc-3d/sibling-camera?video={cam0}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["calibration_exists"] is False
```

- [ ] **Step 6: Run both calibration-reporting tests**

```bash
python -m pytest tests/test_core.py -v -k sibling_camera_reports_calibration
```

Expected: 2 passed.

- [ ] **Step 7: Run full backend suite**

```bash
python -m pytest tests/test_core.py -v
```

Expected: 43 passed (41 from Task 1 + 2 new).

- [ ] **Step 8: Capture `calibration_exists` in `_selectVideo` and pass to `openPlayer`**

In `dlc-3D/src/static/dlc_3d.js`, find this block in `_selectVideo`:

```javascript
  let siblingPath = null;
  try {
    const sr = await fetch(`/dlc-3d/sibling-camera?video=${encodeURIComponent(videoPath)}`);
    if (sr.ok) {
      const sd = await sr.json();
      siblingPath = sd.sibling_video_path || null;
    }
  } catch (e) { console.warn("[dlc_3d] sibling-camera fetch failed:", e); }
```

Replace with:

```javascript
  let siblingPath        = null;
  let calibrationExists  = false;
  try {
    const sr = await fetch(`/dlc-3d/sibling-camera?video=${encodeURIComponent(videoPath)}`);
    if (sr.ok) {
      const sd = await sr.json();
      siblingPath        = sd.sibling_video_path || null;
      calibrationExists  = !!sd.calibration_exists;
    }
  } catch (e) { console.warn("[dlc_3d] sibling-camera fetch failed:", e); }
```

Then find the `openPlayer` call lower in the same function:

```javascript
  await openPlayer(videoPath, siblingPath);
```

Replace with:

```javascript
  await openPlayer(videoPath, siblingPath, calibrationExists);
```

- [ ] **Step 9: Add `_calibrationExists` module state in `enhanced_player.js`**

In `dlc-3D/src/static/enhanced_player.js`, find the existing module state block. Locate `_siblingVideoPath` (around line 20):

```javascript
let _syncCamEnabled   = false;
let _siblingVideoPath = null;
```

Add `_calibrationExists` immediately after:

```javascript
let _syncCamEnabled    = false;
let _siblingVideoPath  = null;
let _calibrationExists = false;
```

- [ ] **Step 10: Update `openPlayer` signature and reset**

In `dlc-3D/src/static/enhanced_player.js`, find the `openPlayer` opening block:

```javascript
export async function openPlayer(videoPath, siblingPath) {
  _stop();
  _videoPath        = videoPath;
  _siblingVideoPath = siblingPath || null;
  _syncCamEnabled   = false;
```

Replace with:

```javascript
export async function openPlayer(videoPath, siblingPath, calibrationExists = false) {
  _stop();
  _videoPath         = videoPath;
  _siblingVideoPath  = siblingPath || null;
  _calibrationExists = !!calibrationExists;
  _syncCamEnabled    = false;
```

- [ ] **Step 11: Guard the Sync Cam checkbox handler**

In `dlc-3D/src/static/enhanced_player.js`, find the existing Sync Cam checkbox listener in `DOMContentLoaded`:

```javascript
  // Sync cam checkbox
  document.getElementById("ep-sync-cam")?.addEventListener("change", (e) => {
    _syncCamEnabled = e.target.checked;
    _epUpdateSyncCamUI();
    if (_syncCamEnabled) _epLoadCam2Frame(_currentFrame);
  });
```

Replace with:

```javascript
  // Sync cam checkbox
  document.getElementById("ep-sync-cam")?.addEventListener("change", (e) => {
    if (e.target.checked && !_calibrationExists) {
      e.target.checked = false;
      const status = document.getElementById("extract-status");
      if (status) {
        status.textContent = "Cannot enable Sync Cam: calibration.toml not found in recording folder.";
      }
      return;
    }
    _syncCamEnabled = e.target.checked;
    _epUpdateSyncCamUI();
    if (_syncCamEnabled) _epLoadCam2Frame(_currentFrame);
  });
```

- [ ] **Step 12: Build, restart, and manually verify**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d
docker compose up -d dlc-3d
```

Verify (using a recording folder with paired cam videos):

1. **With calibration.toml present:** load project → select primary video → click Sync Cam → checkbox stays checked, no error; extract a frame → both primary and sibling PNGs save; `labeled-data/<session>/calibration.toml` is present.

2. **Clip layout (clip inside video-named subfolder):** select a clip → extract → `labeled-data/<session>/calibration.toml` is copied (sourced from grandparent recording folder).

3. **Without calibration.toml:** temporarily move/rename calibration.toml in the recording folder → reload the video → click Sync Cam → checkbox snaps back to unchecked; status reads "Cannot enable Sync Cam: calibration.toml not found in recording folder."

- [ ] **Step 13: Run E2E + backend test suites**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py tests/e2e/ -v
```

Expected: 43 backend + 9 E2E = 52 passed.

- [ ] **Step 14: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/routes.py \
        dlc-3D/tests/test_core.py \
        dlc-3D/src/static/dlc_3d.js \
        dlc-3D/src/static/enhanced_player.js
git commit -m "feat: validate calibration.toml exists when toggling Sync Cam"
```

# DLC-3D — Calibration File Fix + Sync-Cam Validation — Design Spec

**Date:** 2026-04-30
**Status:** Approved

## Goal

Two related fixes:

1. **Bug fix**: `_save_single_frame` looks for `calibration.toml` at `project_path/videos/calibration.toml`, which only works for in-project videos. With out-of-project videos now supported, the calibration file lives next to the videos in the recording folder. Fix the source location so calibration is correctly copied into `labeled-data/<session>/` for both in-project and out-of-project recordings, including clips that live inside video-named subfolders.

2. **Validation**: When the user clicks Sync Cam, throw a clear error if `calibration.toml` is missing from the expected location. The user has guaranteed it'll always be there, so this is purely a safety net — but the error must surface immediately at toggle time, not silently fail at extract time.

---

## Section 1 — Calibration source with clip-folder fallback

### Lookup priority

1. `video_path.parent / "calibration.toml"` — the recording folder (covers in-project `proj/videos/...` and direct out-of-project `/user-data/.../<recording>/<video>.avi`).
2. `video_path.parent.parent / "calibration.toml"` — the recording folder when the video is a clip nested inside a video-named subfolder (e.g. `/user-data/.../042326/surv1_cam0_..._/clip_001.avi` → calibration is at `/user-data/.../042326/calibration.toml`).

The clip-folder case is detected via `_session_key_from_stem(parent_name) is not None`, the same predicate `_save_single_frame` already uses to determine the session key for clip videos.

### Backend change (`dlc-3D/src/dlc_3d_bp/routes.py`)

In `_save_single_frame`, replace the existing calibration-copy block:

```python
# Copy calibration.toml on first save (no existing PNGs before this one)
if order == 0:
    calib_src  = project_path / "videos" / "calibration.toml"
    calib_dest = labeled_dir / "calibration.toml"
    if calib_src.exists() and not calib_dest.exists():
        shutil.copy2(calib_src, calib_dest)
```

With:

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

`video_path` is already resolved earlier in the function (via `_resolve_video_path`), so no extra resolution is needed.

### Tests (`dlc-3D/tests/test_core.py`)

Existing tests cover the in-project layout (calibration at `proj/videos/`, video at `proj/videos/...` → `video_path.parent` matches), so they still pass.

Add two new tests:

```python
def test_save_frame_copies_calibration_from_video_parent_folder(tmp_path, monkeypatch):
    """Out-of-project layout: calibration.toml lives next to the videos
    in /user-data/<recording>/, not under proj/videos/."""
    import config
    monkeypatch.setattr(config, "USER_DATA_ROOTS", [tmp_path])
    monkeypatch.setattr(routes, "_USER_DATA_ROOT", str(tmp_path))

    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()
    (rec_dir / "calibration.toml").write_text("[cam_0]\n")
    video = rec_dir / "surv1_cam0_20260123_121732_0.avi"
    _make_video(video, frames=10)

    proj = tmp_path / "project"
    (proj / "videos").mkdir(parents=True)

    from dlc_3d_bp.routes import _save_single_frame
    _save_single_frame(proj, str(video), 3)

    assert (proj / "labeled-data" / "surv1_20260123" / "calibration.toml").is_file()


def test_save_frame_copies_calibration_from_clip_grandparent(tmp_path, monkeypatch):
    """Clip layout: clip_001.avi sits inside a video-named subfolder of the
    recording dir; calibration.toml is one level up at the recording root."""
    import config
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

    from dlc_3d_bp.routes import _save_single_frame
    _save_single_frame(proj, str(clip), 3)

    assert (proj / "labeled-data" / "surv1_20260123" / "calibration.toml").is_file()
```

---

## Section 2 — Sync-Cam validation

### Backend (`dlc-3D/src/dlc_3d_bp/routes.py`)

Augment `/sibling-camera` to also report `calibration_exists` for the primary video, using the same lookup priority as Section 1:

```python
@bp.route("/sibling-camera")
def get_sibling_camera():
    video_path = (request.args.get("video") or "").strip()
    if not video_path:
        return jsonify({"sibling_video_path": None, "calibration_exists": False})

    with _state_lock:
        proj = _active_project

    # ── existing sibling lookup unchanged ──
    sibling = _find_sibling_on_filesystem(video_path)
    if sibling and str(Path(sibling).resolve()).startswith(_USER_DATA_ROOT + "/"):
        pass  # accept
    else:
        sibling = None
        if not video_path.startswith("/") and proj:
            vj_path = Path(proj) / "videos.json"
            if vj_path.exists():
                with open(vj_path) as f:
                    videos_json = json.load(f)
                sibling = _find_sibling_video(video_path, videos_json)

    # ── calibration check (new) ──
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

(The "existing sibling lookup unchanged" comment refers to whatever the current handler body does — this design preserves it intact and only adds the calibration check + extends the response.)

### Frontend — `dlc_3d.js` (capture flag)

In `_selectVideo`, find:

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

Then change the `openPlayer` call from `await openPlayer(videoPath, siblingPath);` to:

```javascript
await openPlayer(videoPath, siblingPath, calibrationExists);
```

### Frontend — `enhanced_player.js` (gate sync-cam toggle)

Module state addition (alongside existing `_siblingVideoPath`):

```javascript
let _calibrationExists = false;
```

Update `openPlayer` signature and the early reset block:

```javascript
export async function openPlayer(videoPath, siblingPath, calibrationExists = false) {
  _stop();
  _videoPath          = videoPath;
  _siblingVideoPath   = siblingPath || null;
  _calibrationExists  = !!calibrationExists;
  // ... rest of openPlayer body unchanged ...
```

Update the sync-cam checkbox handler in `DOMContentLoaded` — find:

```javascript
document.getElementById("ep-sync-cam")?.addEventListener("change", (e) => {
  _syncCamEnabled = e.target.checked;
  _epUpdateSyncCamUI();
  if (_syncCamEnabled) _epLoadCam2Frame(_currentFrame);
});
```

Replace with:

```javascript
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

The checkbox snaps back to unchecked. Status clears on the next successful extract / video load.

### Tests (`dlc-3D/tests/test_core.py`)

Add two tests:

```python
def test_sibling_camera_reports_calibration_exists(tmp_path, monkeypatch):
    """When calibration.toml is present in the recording folder, the
    /sibling-camera response reports calibration_exists=True."""
    from flask import Flask
    import config
    monkeypatch.setattr(config, "USER_DATA_ROOTS", [tmp_path])
    monkeypatch.setattr(routes, "_USER_DATA_ROOT", str(tmp_path))

    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()
    (rec_dir / "calibration.toml").write_text("[cam_0]\n")
    cam0 = rec_dir / "surv1_cam0_20260123_121732_0.avi"
    cam1 = rec_dir / "surv1_cam1_20260123_121732_0.avi"
    cam0.write_bytes(b""); cam1.write_bytes(b"")

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    client = app.test_client()

    resp = client.get(f"/dlc-3d/sibling-camera?video={cam0}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["sibling_video_path"] == str(cam1)
    assert data["calibration_exists"] is True


def test_sibling_camera_reports_calibration_missing(tmp_path, monkeypatch):
    """When calibration.toml is absent, calibration_exists=False."""
    from flask import Flask
    import config
    monkeypatch.setattr(config, "USER_DATA_ROOTS", [tmp_path])
    monkeypatch.setattr(routes, "_USER_DATA_ROOT", str(tmp_path))

    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()
    cam0 = rec_dir / "surv1_cam0_20260123_121732_0.avi"
    cam1 = rec_dir / "surv1_cam1_20260123_121732_0.avi"
    cam0.write_bytes(b""); cam1.write_bytes(b"")

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    client = app.test_client()

    resp = client.get(f"/dlc-3d/sibling-camera?video={cam0}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["calibration_exists"] is False
```

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dlc-3D/src/dlc_3d_bp/routes.py` (`_save_single_frame` calibration source; `/sibling-camera` adds `calibration_exists`) |
| Modify | `dlc-3D/src/static/dlc_3d.js` (capture `calibration_exists` from sibling-camera response, pass to `openPlayer`) |
| Modify | `dlc-3D/src/static/enhanced_player.js` (`openPlayer` accepts `calibrationExists`; sync-cam checkbox guards against missing calibration) |
| Modify | `dlc-3D/tests/test_core.py` (4 new tests) |

No CSS or HTML template changes.

---

## Testing

Backend unit tests:
1. `test_save_frame_copies_calibration_from_video_parent_folder` — out-of-project recording, calibration next to videos.
2. `test_save_frame_copies_calibration_from_clip_grandparent` — clip inside video-named subfolder, calibration one level up.
3. `test_sibling_camera_reports_calibration_exists` — calibration present.
4. `test_sibling_camera_reports_calibration_missing` — calibration absent.

Manual:
1. Build + restart: `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose build dlc-3d && docker compose up -d dlc-3d`.
2. Load a project; browse to an out-of-project recording with calibration.toml + paired cam videos. Select primary cam, enable Sync Cam → no error; extract a frame → `labeled-data/<session>/calibration.toml` is copied.
3. Select a clip inside a video-named subfolder of a recording. Extract → calibration.toml copied (from one level up).
4. In a recording folder without calibration.toml, click Sync Cam → status shows "Cannot enable Sync Cam: calibration.toml not found in recording folder."; checkbox snaps back to unchecked.
5. Existing 48 tests still pass; total becomes 52.

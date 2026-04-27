# Folder Browser + Per-Video Template Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat video list with a hierarchical folder browser and give each video its own template stored at `<video_parent>/<video_stem>/template/template_state.json`.

**Architecture:** New `/fs/ls` endpoint for filesystem browsing. New `/select-video` endpoint sets `video_stem` + `video_parent` in `_state`; a `_template_path()` helper derives the template path from those. All template routes use `_template_path()` instead of `config.TEMPLATE_STATE_PATH`. A minimal template player (stub for later enhancement) lets users add frames after init. The folder browser replaces `#video-list` entirely in the HTML/JS.

**Tech Stack:** Flask (Python), Vanilla JS/HTML/CSS. No new Python dependencies.

---

## File Changes

| File | Change |
|------|--------|
| `clip-cutter/routes.py` | Add `/fs/ls`, `/select-video`, `/template/clear`; add `_template_path()` helper; update all `/template/*` routes; update `_run_scan`; remove `/videos`; update `load_state()` |
| `clip-cutter/app.py` | Remove `load_state()` call at startup (no video selected on boot) |
| `clip-cutter/templates/clip_cutter.html` | Replace video list with folder browser; update sidebar; add minimal player panel |
| `clip-cutter/static/clip_cutter.js` | Add folder browser state + navigation; update `selectVideo()`; update `renderTemplate()`; add sidebar wiring; add minimal player |
| `clip-cutter/tests/test_routes.py` | Add tests for `/fs/ls`, `/select-video`, `/template/clear`; update `/videos` test; update template tests |
| `clip-cutter/tests/test_ui.py` | Replace `/videos` mock with `/fs/ls` mock; add browser navigation tests |

---

### Task 1: Backend — `/fs/ls` filesystem browser endpoint

**Files:**
- Modify: `clip-cutter/routes.py`
- Modify: `clip-cutter/tests/test_routes.py`

- [ ] **Step 1: Write failing tests for `/fs/ls`**

Append to `clip-cutter/tests/test_routes.py`:

```python
def test_fs_ls_lists_dirs_and_avis(client, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path)
    (tmp_path / "subdir").mkdir()
    (tmp_path / "video.avi").touch()
    (tmp_path / "notes.txt").touch()  # should be excluded
    resp = client.get(f"/clip-cutter/fs/ls?path={tmp_path}")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["path"] == str(tmp_path)
    names = [e["name"] for e in data["entries"]]
    assert "subdir" in names
    assert "video.avi" in names
    assert "notes.txt" not in names


def test_fs_ls_dirs_first(client, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path)
    (tmp_path / "aaa.avi").touch()
    (tmp_path / "zzz_dir").mkdir()
    resp = client.get(f"/clip-cutter/fs/ls?path={tmp_path}")
    data = json.loads(resp.data)
    types = [e["type"] for e in data["entries"]]
    # dir before file even though "aaa" < "zzz"
    assert types.index("dir") < types.index("file")


def test_fs_ls_done_badge_when_video_folder_has_clips(client, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path)
    (tmp_path / "myvid.avi").touch()
    vid_dir = tmp_path / "myvid"
    vid_dir.mkdir()
    (vid_dir / "clip_success.avi").touch()
    resp = client.get(f"/clip-cutter/fs/ls?path={tmp_path}")
    data = json.loads(resp.data)
    entry = next(e for e in data["entries"] if e["name"] == "myvid.avi")
    assert entry["done"] is True


def test_fs_ls_ready_badge_when_no_video_folder(client, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path)
    (tmp_path / "myvid.avi").touch()
    resp = client.get(f"/clip-cutter/fs/ls?path={tmp_path}")
    data = json.loads(resp.data)
    entry = next(e for e in data["entries"] if e["name"] == "myvid.avi")
    assert entry["done"] is False


def test_fs_ls_default_path_is_data_root(client, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path)
    resp = client.get("/clip-cutter/fs/ls")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["path"] == str(tmp_path)


def test_fs_ls_nonexistent_path_returns_400(client):
    resp = client.get("/clip-cutter/fs/ls?path=/nonexistent/path/xyz")
    assert resp.status_code == 400
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_routes.py -v -k "fs_ls" 2>&1 | tail -15
```

Expected: all 6 FAIL with 404.

- [ ] **Step 3: Add the `/fs/ls` route to `routes.py`**

After the `list_videos()` function (around line 158), add:

```python
@bp.route("/fs/ls")
def fs_ls():
    path_str = request.args.get("path", "").strip()
    p = Path(path_str) if path_str else config._DATA_ROOT
    if not p.is_dir():
        return jsonify({"error": "not a directory"}), 400

    dirs, files = [], []
    try:
        for entry in sorted(p.iterdir(), key=lambda e: e.name.lower()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                has_avi = any(True for _ in entry.glob("*.avi"))
                dirs.append({"name": entry.name, "type": "dir", "has_avi": has_avi})
            elif entry.is_file() and entry.suffix.lower() == ".avi":
                stem = entry.stem
                video_dir = p / stem
                done = video_dir.is_dir() and any(True for _ in video_dir.glob("*.avi"))
                files.append({"name": entry.name, "type": "file", "done": done})
    except PermissionError:
        return jsonify({"error": "permission denied"}), 403

    parent = str(p.parent) if p.parent != p else None
    return jsonify({"path": str(p), "parent": parent, "entries": dirs + files})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_routes.py -v -k "fs_ls" 2>&1 | tail -10
```

Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat: add /fs/ls filesystem browser endpoint"
```

---

### Task 2: Backend — `_state` per-video fields + `_template_path()` + `/select-video`

**Files:**
- Modify: `clip-cutter/routes.py`
- Modify: `clip-cutter/tests/test_routes.py`

- [ ] **Step 1: Write failing tests**

Append to `clip-cutter/tests/test_routes.py`:

```python
def test_select_video_sets_state(client, tmp_path):
    (tmp_path / "session.avi").touch()
    resp = client.post(
        "/clip-cutter/select-video",
        json={"video_path": str(tmp_path / "session.avi")},
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "count" in data
    assert "has_template" in data


def test_select_video_missing_path_returns_400(client):
    resp = client.post(
        "/clip-cutter/select-video",
        json={},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_select_video_loads_template_if_exists(client, tmp_path, monkeypatch):
    import processor, numpy as np
    stem = "session"
    parent = str(tmp_path)
    template_dir = tmp_path / stem / "template"
    template_dir.mkdir(parents=True)
    # Write a minimal template_state.json
    fake_emb = np.ones(512, dtype=np.float32) / (512 ** 0.5)
    state = {
        "frames": [{"video_path": "/v.avi", "frame_number": 200,
                    "embedding": fake_emb, "thumbnail": "abc"}],
        "mean_embedding": fake_emb,
        "dino_mean_embedding": None,
    }
    processor.save_template_state(state, template_dir / "template_state.json")

    resp = client.post(
        "/clip-cutter/select-video",
        json={"video_path": str(tmp_path / f"{stem}.avi")},
        content_type="application/json",
    )
    data = json.loads(resp.data)
    assert data["count"] == 1
    assert data["has_template"] is True
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_routes.py -v -k "select_video" 2>&1 | tail -10
```

Expected: 3 FAIL with 404.

- [ ] **Step 3: Update `_state` and add `_template_path()` + `/select-video` in `routes.py`**

Replace line 26 (`_state: dict = ...`) with:

```python
_state: dict = {
    "frames": [],
    "mean_embedding": None,
    "dino_mean_embedding": None,
    "video_stem": None,
    "video_parent": None,
}
```

Add `_template_path()` helper right after `_state_lock = threading.Lock()` (line 27):

```python
def _template_path() -> "Path | None":
    with _state_lock:
        stem = _state.get("video_stem")
        parent = _state.get("video_parent")
    if not stem or not parent:
        return None
    return Path(parent) / stem / "template" / "template_state.json"
```

Add `/select-video` route after `fs_ls()`:

```python
@bp.route("/select-video", methods=["POST"])
def select_video():
    global _state
    body = request.get_json(force=True)
    video_path_str = (body.get("video_path") or "").strip()
    if not video_path_str:
        return jsonify({"error": "video_path required"}), 400
    p = Path(video_path_str)
    stem = p.stem
    parent = str(p.parent)
    with _state_lock:
        _state["video_stem"] = stem
        _state["video_parent"] = parent

    tpath = _template_path()
    if tpath and tpath.exists():
        new_state = processor.load_template_state(tpath)
        new_state["video_stem"] = stem
        new_state["video_parent"] = parent
        with _state_lock:
            _state.update(new_state)
        has_template = True
    else:
        with _state_lock:
            _state["frames"] = []
            _state["mean_embedding"] = None
            _state["dino_mean_embedding"] = None
        has_template = False

    with _state_lock:
        count = len(_state["frames"])
    return jsonify({"count": count, "has_template": has_template})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_routes.py -v -k "select_video" 2>&1 | tail -10
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat: add _template_path helper, _state video fields, /select-video endpoint"
```

---

### Task 3: Backend — Update template routes + `/template/clear`

**Files:**
- Modify: `clip-cutter/routes.py`
- Modify: `clip-cutter/tests/test_routes.py`

All template routes (`GET /template`, `POST /template/add`, `DELETE /template/<idx>`) currently use `config.TEMPLATE_STATE_PATH`. Update them to use `_template_path()`. Add `has_template` to the GET response. Add `/template/clear`.

- [ ] **Step 1: Write failing tests**

Append to `clip-cutter/tests/test_routes.py`:

```python
def _select(client, tmp_path, stem="session"):
    """Helper: select a video so template routes have a path."""
    (tmp_path / f"{stem}.avi").touch()
    client.post(
        "/clip-cutter/select-video",
        json={"video_path": str(tmp_path / f"{stem}.avi")},
        content_type="application/json",
    )


def test_template_get_has_template_false_when_no_file(client, tmp_path):
    _select(client, tmp_path)
    resp = client.get("/clip-cutter/template")
    data = json.loads(resp.data)
    assert data["has_template"] is False


def test_template_clear_deletes_state_and_jpgs(client, tmp_path, monkeypatch):
    import processor, numpy as np
    stem = "session"
    _select(client, tmp_path, stem)
    template_dir = tmp_path / stem / "template"
    template_dir.mkdir(parents=True)
    fake_emb = np.ones(512, dtype=np.float32)
    state = {"frames": [], "mean_embedding": None, "dino_mean_embedding": None}
    state_path = template_dir / "template_state.json"
    processor.save_template_state(state, state_path)
    (template_dir / "frame_0200.jpg").touch()

    resp = client.post("/clip-cutter/template/clear")
    assert resp.status_code == 200
    assert not state_path.exists()
    assert not (template_dir / "frame_0200.jpg").exists()
    assert template_dir.exists()  # folder kept


def test_template_clear_no_video_selected_returns_422(client):
    resp = client.post("/clip-cutter/template/clear")
    assert resp.status_code == 422
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_routes.py -v -k "template_get_has or template_clear" 2>&1 | tail -10
```

Expected: FAIL.

- [ ] **Step 3: Update `GET /template` to use `_template_path()` and return `has_template`**

Replace the `get_template()` function:

```python
@bp.route("/template")
def get_template():
    tpath = _template_path()
    with _state_lock:
        frames_out = [
            {"thumbnail": f["thumbnail"], "video_path": f["video_path"],
             "frame_number": f["frame_number"]}
            for f in _state["frames"]
        ]
        count = len(frames_out)
    has_template = tpath is not None and tpath.exists()
    return jsonify({"count": count, "frames": frames_out, "has_template": has_template})
```

- [ ] **Step 4: Update `POST /template/add` to use `_template_path()`**

Replace `add_to_template()`:

```python
@bp.route("/template/add", methods=["POST"])
def add_to_template():
    global _state
    tpath = _template_path()
    if tpath is None:
        return jsonify({"error": "no video selected"}), 422
    body = request.get_json(force=True)
    video_path = body.get("video_path")
    frame_number = body.get("frame_number")
    if not video_path or frame_number is None:
        return jsonify({"error": "video_path and frame_number required"}), 400
    tpath.parent.mkdir(parents=True, exist_ok=True)
    with _state_lock:
        try:
            _state = processor.add_frame_to_template(
                _state, video_path, int(frame_number), tpath, crop=None
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 422
        count = len(_state["frames"])
    return jsonify({"count": count})
```

- [ ] **Step 5: Update `DELETE /template/<idx>` to use `_template_path()`**

Replace `remove_from_template()`:

```python
@bp.route("/template/<int:idx>", methods=["DELETE"])
def remove_from_template(idx: int):
    global _state
    tpath = _template_path()
    if tpath is None:
        return jsonify({"error": "no video selected"}), 422
    with _state_lock:
        if idx >= len(_state["frames"]):
            return jsonify({"error": "index out of range"}), 404
        _state = processor.remove_frame_from_template(_state, idx, tpath)
        count = len(_state["frames"])
    return jsonify({"count": count})
```

- [ ] **Step 6: Add `POST /template/clear`**

Add after `remove_from_template()`:

```python
@bp.route("/template/clear", methods=["POST"])
def clear_template():
    global _state
    tpath = _template_path()
    if tpath is None:
        return jsonify({"error": "no video selected"}), 422
    template_dir = tpath.parent
    if tpath.exists():
        tpath.unlink()
    for jpg in template_dir.glob("*.jpg"):
        jpg.unlink()
    with _state_lock:
        _state["frames"] = []
        _state["mean_embedding"] = None
        _state["dino_mean_embedding"] = None
    return jsonify({"ok": True})
```

- [ ] **Step 7: Run all template tests**

```bash
python -m pytest tests/test_routes.py -v -k "template" 2>&1 | tail -15
```

Expected: all PASSED (including existing tests that still use the client fixture).

- [ ] **Step 8: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat: update template routes to use per-video path; add /template/clear"
```

---

### Task 4: Backend — Per-video `/template/init`

**Files:**
- Modify: `clip-cutter/routes.py`
- Modify: `clip-cutter/tests/test_routes.py`

`_run_init()` currently reads from `config.TRAINING_CLIPS_DIR`. Update it to read from `<video_parent>/<video_stem>/` and write to `<video_parent>/<video_stem>/template/`.

- [ ] **Step 1: Write failing tests**

Append to `clip-cutter/tests/test_routes.py`:

```python
def test_init_creates_template_folder_even_with_no_clips(client, tmp_path, monkeypatch):
    import config
    stem = "session"
    _select(client, tmp_path, stem)
    # No clips in the video folder — init should still succeed
    resp = client.post("/clip-cutter/template/init")
    assert resp.status_code == 202
    # Poll until done
    import time
    for _ in range(20):
        time.sleep(0.2)
        status_resp = client.get("/clip-cutter/template/init/status")
        data = json.loads(status_resp.data)
        if not data["running"]:
            break
    assert not data["running"]
    assert data["error"] is None
    template_dir = tmp_path / stem / "template"
    assert template_dir.exists()


def test_init_no_video_selected_returns_422(client):
    resp = client.post("/clip-cutter/template/init")
    assert resp.status_code == 422


def test_init_reads_clips_from_video_folder(client, tmp_path, monkeypatch):
    import config, cv2, numpy as np
    stem = "session"
    _select(client, tmp_path, stem)
    # Create a minimal _success AVI in the video-named folder
    vid_dir = tmp_path / stem
    vid_dir.mkdir(exist_ok=True)
    avi_path = vid_dir / "clip_success.avi"
    writer = cv2.VideoWriter(
        str(avi_path), cv2.VideoWriter_fourcc(*"XVID"), 30.0, (64, 64)
    )
    rng = np.random.default_rng(1)
    for _ in range(210):  # need at least 200 frames
        writer.write(rng.integers(0, 255, (64, 64, 3), dtype=np.uint8))
    writer.release()

    resp = client.post("/clip-cutter/template/init")
    assert resp.status_code == 202
    import time
    for _ in range(30):
        time.sleep(0.3)
        data = json.loads(client.get("/clip-cutter/template/init/status").data)
        if not data["running"]:
            break
    assert data["count"] == 1
    assert (tmp_path / stem / "template" / "template_state.json").exists()
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_routes.py -v -k "init" 2>&1 | tail -15
```

Expected: 3 FAIL (no_video_selected should already pass if we check — actually `init_template()` currently doesn't check for selected video, so it fails a different way).

- [ ] **Step 3: Update `_run_init()` and `init_template()` in `routes.py`**

Replace the existing `_run_init()` and `init_template()` functions:

```python
def _run_init(video_stem: str, video_parent: str):
    global _state
    with _init_lock:
        _init_status["running"] = True
        _init_status["error"] = None
    try:
        clips_dir = Path(video_parent) / video_stem
        template_dir = clips_dir / "template"
        template_dir.mkdir(parents=True, exist_ok=True)
        state_path = template_dir / "template_state.json"
        new_state = processor.init_template_from_clips_dir(
            clips_dir, state_path, crop=config.TRAINING_CROP
        )
        new_state["video_stem"] = video_stem
        new_state["video_parent"] = video_parent
        with _state_lock:
            _state = new_state
    except Exception as exc:
        with _init_lock:
            _init_status["error"] = str(exc)
    finally:
        with _init_lock:
            _init_status["running"] = False


@bp.route("/template/init", methods=["POST"])
def init_template():
    with _state_lock:
        stem = _state.get("video_stem")
        parent = _state.get("video_parent")
    if not stem or not parent:
        return jsonify({"error": "no video selected"}), 422
    with _init_lock:
        if _init_status["running"]:
            return jsonify({"status": "running"}), 202
    thread = threading.Thread(target=_run_init, args=(stem, parent), daemon=True)
    thread.start()
    return jsonify({"status": "started"}), 202
```

- [ ] **Step 4: Run all init tests**

```bash
python -m pytest tests/test_routes.py -v -k "init" 2>&1 | tail -15
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat: /template/init uses per-video folder structure"
```

---

### Task 5: Backend — Remove `/videos`, fix `load_state()`, update `_run_scan`

**Files:**
- Modify: `clip-cutter/routes.py`
- Modify: `clip-cutter/app.py`
- Modify: `clip-cutter/tests/test_routes.py`

`_run_scan` calls `processor.get_known_key_frames(config.TRAINING_CLIPS_DIR)`. With per-video templates, known key frames come from `<video_parent>/<video_stem>/`. Also `load_state()` at startup no longer makes sense — no video is selected on boot.

- [ ] **Step 1: Update the failing test for `/videos`**

In `test_routes.py`, find `test_videos_returns_list` and replace it:

```python
def test_videos_route_removed(client):
    resp = client.get("/clip-cutter/videos")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify the new test fails (old route still present)**

```bash
python -m pytest tests/test_routes.py::test_videos_route_removed -v 2>&1 | tail -5
```

Expected: FAIL (route still returns 200).

- [ ] **Step 3: Remove `list_videos()` and `_video_is_done()` from `routes.py`**

Delete the functions `_video_is_done()` and `list_videos()` (lines 135–158 in the original). Also remove `import pandas as pd` from the top if pandas is no longer used anywhere — check first with `grep -n "pd\." routes.py`; if no other uses, remove it.

- [ ] **Step 4: Update `_run_scan` to use per-video clips dir for known key frames**

In `_run_scan()`, find the line:

```python
known = processor.get_known_key_frames(config.TRAINING_CLIPS_DIR)
```

Replace with:

```python
with _state_lock:
    _stem = _state.get("video_stem")
    _parent = _state.get("video_parent")
clips_dir = Path(_parent) / _stem if (_stem and _parent) else config.TRAINING_CLIPS_DIR
known = processor.get_known_key_frames(clips_dir)
```

- [ ] **Step 5: Make `load_state()` a no-op and remove its call from `app.py`**

In `routes.py`, replace `load_state()`:

```python
def load_state() -> None:
    pass  # template state is now loaded per-video via /select-video
```

In `app.py`, the import `from routes import bp, load_state` and `load_state()` call can be simplified:

```python
from flask import Flask
from routes import bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.register_blueprint(bp)
    return app


if __name__ == "__main__":
    import os
    port = int(os.environ.get("CLIP_CUTTER_PORT", 5002))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    create_app().run(host="0.0.0.0", port=port, debug=debug)
```

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest tests/test_routes.py -v 2>&1 | tail -20
```

Expected: all PASSED. Fix any regressions before committing.

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/routes.py clip-cutter/app.py clip-cutter/tests/test_routes.py
git commit -m "feat: remove /videos route; per-video known keyframes; no-op load_state"
```

---

### Task 6: HTML/CSS — Folder browser + sidebar states + minimal player panel

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html`

- [ ] **Step 1: Replace `#video-list` section with folder browser**

Find the `.section` div that contains `#video-list` (lines 151–199 in the original). Replace the `<div class="section-label">Select video to scan</div>` and `<div id="video-list"></div>` block with:

```html
<div class="section" id="browser-section">
  <div class="browser-toolbar">
    <button id="browser-up" class="btn-sm" title="Parent folder">&#8593; Up</button>
    <div id="browser-breadcrumb"></div>
  </div>
  <div id="browser-list"></div>
</div>
```

Keep the scan settings and scan button `.section` div unchanged.

- [ ] **Step 2: Add minimal template player panel HTML**

After the scan settings `.section` div (before the `#progress-section` div), add:

```html
<!-- Minimal template player (hidden until init or Browse frames clicked) -->
<div id="template-player-panel" style="display:none;" class="section">
  <div class="template-player-header">
    <span id="tp-title" style="font-size:11px;color:#768390;">Browsing frames</span>
    <button class="btn-sm" id="tp-close">&#10005; Close</button>
  </div>
  <div id="tp-frame-wrap">
    <img id="tp-frame" alt="frame" style="max-width:100%;display:block;">
  </div>
  <div id="tp-controls">
    <button class="player-btn" id="tp-prev">&#9198;</button>
    <button class="player-btn" id="tp-play">&#9654;</button>
    <button class="player-btn" id="tp-next">&#9197;</button>
    <input type="range" id="tp-seek" min="0" max="1000" value="0" style="flex:1;accent-color:#1f6feb;">
    <span id="tp-frame-num" style="font-size:10px;color:#768390;font-family:monospace;white-space:nowrap;">fr 0 / 0</span>
  </div>
  <div id="tp-actions" style="margin-top:6px;">
    <button class="btn-sm btn-blue" id="tp-add-btn">+ Add this frame to template</button>
  </div>
</div>
```

- [ ] **Step 3: Update sidebar HTML**

Replace the entire `<div class="sidebar">` block with:

```html
<div class="sidebar">
  <div class="sidebar-header">
    <span class="sidebar-title">Template Bank</span>
    <button class="btn-sm btn-green" id="sidebar-init-btn" style="display:none;" title="Init template from this video">&#8635; Init</button>
  </div>
  <div id="sidebar-empty-state" style="padding:12px 10px;font-size:10px;color:#768390;">Select a video to load its template</div>
  <div id="sidebar-no-template" style="display:none;padding:12px 10px;">
    <div id="sidebar-no-template-msg" style="font-size:10px;color:#768390;margin-bottom:6px;"></div>
    <button class="btn-sm" id="sidebar-browse-btn">&#9654; Browse frames</button>
  </div>
  <div id="template-grid" style="display:none;padding:8px;display:none;flex-wrap:wrap;gap:5px;overflow-y:auto;flex:1;"></div>
  <div id="template-footer" style="display:none;padding:6px 10px;border-top:1px solid #30363d;font-size:10px;color:#768390;flex-shrink:0;">0 frames loaded</div>
  <div id="sidebar-actions" style="display:none;padding:6px 10px;border-top:1px solid #30363d;display:none;gap:6px;flex-shrink:0;">
    <button class="btn-sm" id="sidebar-browse-btn2">&#9654; Browse frames</button>
    <button class="btn-sm btn-red" id="sidebar-clear-btn">&#10005; Clear</button>
  </div>
</div>
```

Note: `#sidebar-browse-btn` (no-template state) and `#sidebar-browse-btn2` (has-template state) both open the minimal player. The clear confirmation modal is handled in JS.

- [ ] **Step 4: Add CSS for browser, breadcrumb, minimal player**

In the `<style>` block, add after the existing `.badge-pending` rule:

```css
/* Folder browser */
.browser-toolbar { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
#browser-breadcrumb { flex: 1; font-size: 10px; color: #768390; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bc-segment { cursor: pointer; color: #58a6ff; }
.bc-segment:hover { text-decoration: underline; }
.bc-sep { color: #30363d; }
.bc-current { color: #e6edf3; cursor: default; }
#browser-list { display: flex; flex-direction: column; gap: 2px; max-height: 160px; overflow-y: auto; }
.browser-row { display: flex; align-items: center; gap: 6px; padding: 4px 6px; border-radius: 4px; cursor: pointer; border: 1px solid transparent; }
.browser-row:hover { background: #1c2128; border-color: #30363d; }
.browser-row.selected { background: #1a2535; border-color: #388bfd; }
.browser-icon { font-size: 11px; flex-shrink: 0; }
.browser-name { font-family: monospace; font-size: 11px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* Minimal template player */
.template-player-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
#tp-frame-wrap { background: #1c2128; border: 1px solid #30363d; border-radius: 4px; overflow: hidden; max-height: 200px; display: flex; align-items: center; justify-content: center; margin-bottom: 6px; }
#tp-controls { display: flex; align-items: center; gap: 6px; }
/* Clear confirmation modal */
#clear-confirm-modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 100; align-items: center; justify-content: center; }
#clear-confirm-modal.open { display: flex; }
.modal-box { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; max-width: 340px; width: 100%; }
.modal-box h3 { font-size: 13px; margin-bottom: 8px; }
.modal-box p { font-size: 11px; color: #768390; margin-bottom: 12px; }
.modal-box input { width: 100%; padding: 4px 8px; background: #0d1117; border: 1px solid #30363d; border-radius: 4px; color: #cdd9e5; font-size: 12px; margin-bottom: 12px; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; }
```

- [ ] **Step 5: Add clear confirmation modal HTML**

Before the closing `</body>` tag, add:

```html
<!-- Clear template confirmation modal -->
<div id="clear-confirm-modal">
  <div class="modal-box">
    <h3>Clear template?</h3>
    <p>This deletes <code>template_state.json</code> and all frame thumbnails. Type <strong>delete</strong> to confirm.</p>
    <input type="text" id="clear-confirm-input" placeholder="type delete">
    <div class="modal-actions">
      <button class="btn-sm" id="clear-cancel-btn">Cancel</button>
      <button class="btn-sm btn-red" id="clear-confirm-btn" disabled>Clear template</button>
    </div>
  </div>
</div>
```

- [ ] **Step 6: Verify HTML renders without JS errors**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
docker compose up -d
sleep 3
curl -s http://localhost:5002/clip-cutter/ | grep -c "browser-list"
```

Expected: `1` (the element exists in the served HTML). The page should load without console errors (check browser devtools).

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/templates/clip_cutter.html
git commit -m "feat: folder browser HTML/CSS, sidebar states, minimal template player panel"
```

---

### Task 7: JS — Folder browser navigation

**Files:**
- Modify: `clip-cutter/static/clip_cutter.js`

- [ ] **Step 1: Replace `loadVideos()` / `renderVideos()` / `selectVideo()` with folder browser state + functions**

In `clip_cutter.js`, replace the entire `// ── Video list ──` section (lines 174–207) with:

```js
// ── Folder browser ────────────────────────────────────────────────────────────

let _browserCurrentPath = null;
let _selectedVideoStem = null;
let _selectedVideoParent = null;

async function loadFolder(path) {
  const url = path
    ? `/clip-cutter/fs/ls?path=${encodeURIComponent(path)}`
    : "/clip-cutter/fs/ls";
  const resp = await fetch(url);
  if (!resp.ok) { setStatus("Cannot open folder"); return; }
  const data = await resp.json();
  _browserCurrentPath = data.path;
  try { localStorage.setItem("cc-browser-path", data.path); } catch {}
  renderBrowser(data);
}

function renderBrowser(data) {
  // Breadcrumb
  const bc = document.getElementById("browser-breadcrumb");
  bc.innerHTML = "";
  const parts = data.path.split("/").filter(Boolean);
  parts.forEach((part, i) => {
    if (i > 0) {
      const sep = document.createElement("span");
      sep.className = "bc-sep";
      sep.textContent = " / ";
      bc.appendChild(sep);
    }
    const seg = document.createElement("span");
    const isLast = i === parts.length - 1;
    seg.className = isLast ? "bc-current" : "bc-segment";
    seg.textContent = part;
    if (!isLast) {
      const fullPath = "/" + parts.slice(0, i + 1).join("/");
      seg.addEventListener("click", () => loadFolder(fullPath));
    }
    bc.appendChild(seg);
  });

  // Up button
  const upBtn = document.getElementById("browser-up");
  upBtn.disabled = !data.parent;
  upBtn.onclick = () => { if (data.parent) loadFolder(data.parent); };

  // Entries
  const list = document.getElementById("browser-list");
  list.innerHTML = "";
  data.entries.forEach((entry) => {
    const row = document.createElement("div");
    row.className = "browser-row";
    const icon = document.createElement("span");
    icon.className = "browser-icon";
    const name = document.createElement("span");
    name.className = "browser-name";
    name.textContent = entry.name;
    row.appendChild(icon);
    row.appendChild(name);

    if (entry.type === "dir") {
      icon.textContent = "📁";
      row.addEventListener("click", () => loadFolder(data.path + "/" + entry.name));
    } else {
      icon.textContent = "▶";
      const badge = document.createElement("span");
      badge.className = `badge ${entry.done ? "badge-done" : "badge-pending"}`;
      badge.textContent = entry.done ? "done" : "ready";
      row.appendChild(badge);
      row.addEventListener("click", () => {
        document.querySelectorAll(".browser-row.selected").forEach((r) =>
          r.classList.remove("selected")
        );
        row.classList.add("selected");
        const videoPath = data.path + "/" + entry.name;
        const stem = entry.name.replace(/\.avi$/i, "");
        selectVideo(videoPath, stem, data.path);
      });
    }
    list.appendChild(row);
  });
}

async function selectVideo(videoPath, stem, parent) {
  selectedVideoPath = videoPath;
  _selectedVideoStem = stem;
  _selectedVideoParent = parent;

  await fetch("/clip-cutter/select-video", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_path: videoPath }),
  });

  document.getElementById("scan-btn").disabled = false;
  detections.length = 0;
  document.getElementById("results-list").innerHTML = "";
  document.getElementById("results-count").textContent = "";

  await loadTemplate();
  await loadSavedDetections(videoPath);
}
```

- [ ] **Step 2: Update `DOMContentLoaded` to call `loadFolder` instead of `loadVideos`**

In the `DOMContentLoaded` handler (line 27), replace:

```js
loadTemplate();
loadVideos();
```

with:

```js
loadTemplate();
const _savedPath = (() => { try { return localStorage.getItem("cc-browser-path"); } catch { return null; } })();
loadFolder(_savedPath || null);
```

- [ ] **Step 3: Verify browser loads in the running container**

Open `http://localhost:5002/clip-cutter/` in a browser. The folder browser should replace the video list. Clicking folders should navigate into them. Clicking `.avi` files should select them and show the scan button.

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/static/clip_cutter.js
git commit -m "feat: folder browser JS — navigation, localStorage, selectVideo"
```

---

### Task 8: JS — Sidebar state management + Init/Clear wiring

**Files:**
- Modify: `clip-cutter/static/clip_cutter.js`

- [ ] **Step 1: Replace `renderTemplate()` with version that handles 3 sidebar states**

Replace the existing `renderTemplate()` function:

```js
function renderTemplate(data) {
  const emptyState = document.getElementById("sidebar-empty-state");
  const noTemplate = document.getElementById("sidebar-no-template");
  const noTemplateMsg = document.getElementById("sidebar-no-template-msg");
  const grid = document.getElementById("template-grid");
  const footer = document.getElementById("template-footer");
  const initBtn = document.getElementById("sidebar-init-btn");
  const sidebarActions = document.getElementById("sidebar-actions");

  if (!_selectedVideoStem) {
    emptyState.style.display = "";
    noTemplate.style.display = "none";
    grid.style.display = "none";
    footer.style.display = "none";
    initBtn.style.display = "none";
    sidebarActions.style.display = "none";
    return;
  }

  emptyState.style.display = "none";
  initBtn.style.display = "";

  if (!data.has_template) {
    noTemplate.style.display = "";
    noTemplateMsg.textContent = `No template for ${_selectedVideoStem}`;
    grid.style.display = "none";
    footer.style.display = "none";
    sidebarActions.style.display = "none";
    return;
  }

  noTemplate.style.display = "none";
  grid.style.display = "flex";
  footer.style.display = "";
  sidebarActions.style.display = "flex";

  grid.innerHTML = "";
  data.frames.forEach((f, idx) => {
    const div = document.createElement("div");
    div.className = "thumb";
    div.title = `${f.video_path} frame ${f.frame_number}\nClick to remove`;
    div.innerHTML = `<img src="data:image/jpeg;base64,${f.thumbnail}"><span class="thumb-label">fr${f.frame_number}</span>`;
    div.addEventListener("click", () => removeTemplateFrame(idx));
    grid.appendChild(div);
  });
  footer.textContent = `${data.count} frame${data.count !== 1 ? "s" : ""} loaded`;
}
```

- [ ] **Step 2: Update `loadTemplate()` and `initTemplate()`**

Replace existing `loadTemplate()`:

```js
async function loadTemplate() {
  const resp = await fetch("/clip-cutter/template");
  const data = await resp.json();
  renderTemplate(data);
}
```

Replace existing `initTemplate()`:

```js
async function initTemplate() {
  if (document.getElementById("template-grid").style.display !== "none") {
    // Template already exists — confirm re-init
    if (!confirm(`Re-initialise template for ${_selectedVideoStem}? This will replace the current template.`)) return;
  }
  setStatus("Starting template build…");
  try {
    const resp = await fetch("/clip-cutter/template/init", { method: "POST" });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: resp.statusText }));
      setStatus("Init error: " + err.error);
      return;
    }
    setStatus("Building template from clips — this may take a minute…");
    pollInitStatus();
  } catch (err) {
    setStatus("Network error: " + err.message);
  }
}
```

Update `pollInitStatus()` to open the template player when done:

```js
function pollInitStatus() {
  const iv = setInterval(async () => {
    try {
      const resp = await fetch("/clip-cutter/template/init/status");
      const data = await resp.json();
      if (data.error) {
        clearInterval(iv);
        setStatus("Init error: " + data.error);
        return;
      }
      if (!data.running) {
        clearInterval(iv);
        await loadTemplate();
        setStatus(`Template initialised: ${data.count} frame${data.count !== 1 ? "s" : ""} — browse to add more`);
        openTemplatePlayer();
      } else {
        setStatus(`Building template… ${data.count} frame${data.count !== 1 ? "s" : ""} embedded`);
      }
    } catch (err) {
      clearInterval(iv);
      setStatus("Network error while polling: " + err.message);
    }
  }, 2000);
}
```

- [ ] **Step 3: Wire Init + Clear + Browse buttons in `DOMContentLoaded`**

Inside the `DOMContentLoaded` handler, add after the filter buttons wiring:

```js
// Sidebar init button
document.getElementById("sidebar-init-btn").addEventListener("click", initTemplate);

// Browse frames buttons (two: one in no-template state, one in has-template state)
document.getElementById("sidebar-browse-btn").addEventListener("click", openTemplatePlayer);
document.getElementById("sidebar-browse-btn2").addEventListener("click", openTemplatePlayer);

// Clear button — open confirmation modal
document.getElementById("sidebar-clear-btn").addEventListener("click", () => {
  document.getElementById("clear-confirm-input").value = "";
  document.getElementById("clear-confirm-btn").disabled = true;
  document.getElementById("clear-confirm-modal").classList.add("open");
});

// Clear modal — type "delete" to enable confirm button
document.getElementById("clear-confirm-input").addEventListener("input", (e) => {
  document.getElementById("clear-confirm-btn").disabled = e.target.value !== "delete";
});

// Clear modal — cancel
document.getElementById("clear-cancel-btn").addEventListener("click", () => {
  document.getElementById("clear-confirm-modal").classList.remove("open");
});

// Clear modal — confirm
document.getElementById("clear-confirm-btn").addEventListener("click", async () => {
  document.getElementById("clear-confirm-modal").classList.remove("open");
  const resp = await fetch("/clip-cutter/template/clear", { method: "POST" });
  if (resp.ok) {
    await loadTemplate();
    setStatus("Template cleared");
  } else {
    setStatus("Clear failed");
  }
});
```

- [ ] **Step 4: Remove the old `onclick="initTemplate()"` from sidebar HTML**

In `clip_cutter.html`, the `sidebar-init-btn` already has no `onclick` (we set it above) — verify the button does NOT have `onclick` in the HTML. If it does, remove it.

- [ ] **Step 5: Verify in browser**

Open `http://localhost:5002/clip-cutter/`. Without selecting a video, sidebar shows "Select a video". Select a `.avi` file — sidebar shows "No template for X" with Init and Browse buttons. Click Clear on a video that has a template — modal appears, "Clear template" button disabled until typing "delete".

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/static/clip_cutter.js clip-cutter/templates/clip_cutter.html
git commit -m "feat: sidebar state management, init/clear wiring, clear confirmation modal"
```

---

### Task 9: JS — Minimal template player

**Files:**
- Modify: `clip-cutter/static/clip_cutter.js`

- [ ] **Step 1: Add minimal template player state and functions**

Append to `clip_cutter.js` (before the `setStatus` function):

```js
// ── Minimal template player ──────────────────────────────────────────────────

let _tp = {
  videoPath: null,
  frameCount: 0,
  currentFrame: 0,
  playing: false,
  busy: false,
  timerId: null,
};

async function openTemplatePlayer() {
  if (!selectedVideoPath) { setStatus("No video selected"); return; }
  document.getElementById("template-player-panel").style.display = "";
  document.getElementById("tp-title").textContent = `Browsing: ${_selectedVideoStem}`;
  _tp.videoPath = selectedVideoPath;
  _tp.currentFrame = 0;
  _tp.playing = false;
  if (_tp.timerId) { clearTimeout(_tp.timerId); _tp.timerId = null; }

  try {
    const resp = await fetch(`/clip-cutter/video-info?video=${encodeURIComponent(selectedVideoPath)}`);
    if (!resp.ok) { setStatus("Cannot load video info"); return; }
    const info = await resp.json();
    _tp.frameCount = info.frame_count;
    await _tpLoadFrame(0);
  } catch (e) {
    setStatus("Error opening player: " + e.message);
  }
}

function closeTemplatePlayer() {
  if (_tp.timerId) { clearTimeout(_tp.timerId); _tp.timerId = null; }
  _tp.playing = false;
  document.getElementById("template-player-panel").style.display = "none";
}

async function _tpLoadFrame(n) {
  if (_tp.busy || !_tp.videoPath) return;
  _tp.busy = true;
  n = Math.max(0, Math.min(n, _tp.frameCount - 1));
  _tp.currentFrame = n;
  try {
    const url = `/clip-cutter/frame?video=${encodeURIComponent(_tp.videoPath)}&n=${n}`;
    const resp = await fetch(url);
    if (!resp.ok) return;
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const img = document.getElementById("tp-frame");
    const prev = img.src;
    await new Promise((resolve, reject) => {
      img.onload = () => { if (prev && prev.startsWith("blob:")) URL.revokeObjectURL(prev); resolve(); };
      img.onerror = reject;
      img.src = blobUrl;
    });
    _tpUpdateDisplay();
  } finally {
    _tp.busy = false;
  }
}

function _tpUpdateDisplay() {
  document.getElementById("tp-frame-num").textContent = `fr ${_tp.currentFrame} / ${_tp.frameCount}`;
  const pct = _tp.frameCount > 1 ? _tp.currentFrame / (_tp.frameCount - 1) : 0;
  document.getElementById("tp-seek").value = Math.round(pct * 1000);
  document.getElementById("tp-play").textContent = _tp.playing ? "⏸" : "▶";
}

async function _tpLoop() {
  if (!_tp.playing) return;
  if (!_tp.busy) {
    const next = _tp.currentFrame + 1 >= _tp.frameCount ? 0 : _tp.currentFrame + 1;
    await _tpLoadFrame(next);
  }
  if (_tp.playing) _tp.timerId = setTimeout(_tpLoop, Math.round(1000 / 15));
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("tp-close").addEventListener("click", closeTemplatePlayer);

  document.getElementById("tp-prev").addEventListener("click", () => {
    _tp.playing = false; _tpUpdateDisplay();
    _tpLoadFrame(_tp.currentFrame - 1);
  });

  document.getElementById("tp-next").addEventListener("click", () => {
    _tp.playing = false; _tpUpdateDisplay();
    _tpLoadFrame(_tp.currentFrame + 1);
  });

  document.getElementById("tp-play").addEventListener("click", () => {
    _tp.playing = !_tp.playing;
    _tpUpdateDisplay();
    if (_tp.playing) _tpLoop();
    else if (_tp.timerId) { clearTimeout(_tp.timerId); _tp.timerId = null; }
  });

  document.getElementById("tp-seek").addEventListener("input", (e) => {
    if (_tp.frameCount === 0) return;
    _tp.playing = false; _tpUpdateDisplay();
    const n = Math.round((e.target.value / 1000) * (_tp.frameCount - 1));
    _tpLoadFrame(n);
  });

  document.getElementById("tp-add-btn").addEventListener("click", async () => {
    if (!selectedVideoPath || _tp.frameCount === 0) return;
    const frameNumber = _tp.currentFrame + 1; // 1-based
    const resp = await fetch("/clip-cutter/template/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_path: selectedVideoPath, frame_number: frameNumber }),
    });
    if (resp.ok) {
      await loadTemplate();
      setStatus(`Frame ${frameNumber} added to template`);
    } else {
      const err = await resp.json().catch(() => ({ error: "unknown" }));
      setStatus("Error: " + err.error);
    }
  });
});
```

Note: The two `document.addEventListener("DOMContentLoaded", ...)` blocks will both fire — this is valid in JS. Alternatively, merge into one block. Either works.

- [ ] **Step 2: Verify end-to-end flow**

1. Select a video in the folder browser
2. Click "Init" in the sidebar
3. After init completes, the template player panel should appear below the scan settings
4. Navigate frames with Prev/Next and seek slider
5. Click "Add this frame to template" — thumbnail should appear in sidebar
6. Click "✕ Close" — player panel disappears

- [ ] **Step 3: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/static/clip_cutter.js
git commit -m "feat: minimal template player — frame browsing, add-to-template"
```

---

### Task 10: Playwright tests for folder browser + template management

**Files:**
- Modify: `clip-cutter/tests/test_ui.py`

- [ ] **Step 1: Read the top of `test_ui.py` to understand `setup_routes` and how to update it**

The current `setup_routes()` mocks `/clip-cutter/videos`. Replace that mock with `/clip-cutter/fs/ls` and `/clip-cutter/select-video`.

- [ ] **Step 2: Update `setup_routes()` mock data and routes**

In `test_ui.py`, replace `_MOCK_VIDEOS` with:

```python
_MOCK_FS_ROOT = {
    "path": "/user-data",
    "parent": "/",
    "entries": [
        {"name": "vid1.avi", "type": "file", "done": False},
        {"name": "vid2.avi", "type": "file", "done": True},
        {"name": "subdir", "type": "dir", "has_avi": True},
    ],
}

_MOCK_FS_SUBDIR = {
    "path": "/user-data/subdir",
    "parent": "/user-data",
    "entries": [
        {"name": "vid3.avi", "type": "file", "done": False},
    ],
}
```

In `setup_routes()`, remove the `/clip-cutter/videos` mock and add:

```python
page.route("**/clip-cutter/fs/ls**", lambda route: _json(route, _MOCK_FS_ROOT))
page.route("**/clip-cutter/select-video", lambda route: _json(route, {"count": 0, "has_template": False}))
page.route("**/clip-cutter/template/clear", lambda route: _json(route, {"ok": True}))
```

Also update `/clip-cutter/template` mock to include `has_template`:

```python
# In setup_routes(), find the route for /clip-cutter/template and update body:
page.route(
    "**/clip-cutter/template",
    lambda route: _json(route, {"count": len(state["frames"]), "frames": state["frames"], "has_template": len(state["frames"]) > 0}),
)
```

- [ ] **Step 3: Add folder browser Playwright tests**

Append to `test_ui.py`:

```python
# ── Folder browser tests ──────────────────────────────────────────────────────

def test_browser_shows_avi_entries(page, live_server):
    page.goto(f"{live_server}/clip-cutter/")
    expect(page.locator("#browser-list")).to_be_visible()
    expect(page.locator(".browser-row")).to_have_count(3)


def test_browser_shows_done_badge_for_done_video(page, live_server):
    page.goto(f"{live_server}/clip-cutter/")
    rows = page.locator(".browser-row")
    # vid2.avi is done
    done_row = rows.filter(has_text="vid2.avi")
    expect(done_row.locator(".badge-done")).to_be_visible()


def test_browser_clicking_dir_navigates_into_it(page, live_server):
    # Override fs/ls to return subdir content on second call
    call_count = {"n": 0}

    def handle_ls(route):
        call_count["n"] += 1
        if call_count["n"] == 1:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(_MOCK_FS_ROOT),
            )
        else:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(_MOCK_FS_SUBDIR),
            )

    # Playwright matches routes LIFO — this handler fires before setup_routes
    page.route("**/clip-cutter/fs/ls**", handle_ls)
    page.goto(f"{live_server}/clip-cutter/")
    page.click(".browser-row:has-text('subdir')")
    expect(page.locator("#browser-list")).to_contain_text("vid3.avi")


def test_browser_selecting_video_shows_sidebar_no_template(page, live_server):
    page.goto(f"{live_server}/clip-cutter/")
    page.click(".browser-row:has-text('vid1.avi')")
    expect(page.locator("#sidebar-no-template")).to_be_visible()
    expect(page.locator("#sidebar-init-btn")).to_be_visible()


def test_sidebar_empty_state_shown_on_load(page, live_server):
    page.goto(f"{live_server}/clip-cutter/")
    expect(page.locator("#sidebar-empty-state")).to_be_visible()
    expect(page.locator("#sidebar-init-btn")).to_be_hidden()


def test_clear_modal_requires_delete_word(page, live_server):
    # Select a video that has a template (has_template=True)
    page.route(
        "**/clip-cutter/select-video",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"count": 2, "has_template": True}),
        ),
    )
    page.goto(f"{live_server}/clip-cutter/")
    page.click(".browser-row:has-text('vid1.avi')")
    expect(page.locator("#sidebar-actions")).to_be_visible()
    page.click("#sidebar-clear-btn")
    expect(page.locator("#clear-confirm-modal")).to_have_class(re.compile(r"\bopen\b"))
    expect(page.locator("#clear-confirm-btn")).to_be_disabled()
    page.fill("#clear-confirm-input", "delete")
    expect(page.locator("#clear-confirm-btn")).to_be_enabled()


def test_clear_modal_cancel_closes_modal(page, live_server):
    page.route(
        "**/clip-cutter/select-video",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"count": 2, "has_template": True}),
        ),
    )
    page.goto(f"{live_server}/clip-cutter/")
    page.click(".browser-row:has-text('vid1.avi')")
    page.click("#sidebar-clear-btn")
    page.click("#clear-cancel-btn")
    expect(page.locator("#clear-confirm-modal")).not_to_have_class(re.compile(r"\bopen\b"))
```

- [ ] **Step 4: Run the new tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_ui.py -v -k "browser or sidebar or clear_modal" 2>&1 | tail -20
```

Expected: all PASSED.

- [ ] **Step 5: Run full UI test suite to check for regressions**

```bash
python -m pytest tests/test_ui.py -v 2>&1 | tail -20
```

Expected: all PASSED.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/tests/test_ui.py
git commit -m "test: Playwright tests for folder browser, sidebar states, clear confirmation"
```

---

### Task 11: Docker rebuild + smoke test

**Files:**
- No code changes — rebuild image and verify end-to-end

- [ ] **Step 1: Rebuild the Docker image**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
docker compose build 2>&1 | tail -5
```

Expected: build exits 0.

- [ ] **Step 2: Start and smoke test**

```bash
docker compose up -d
sleep 5
curl -s http://localhost:5002/clip-cutter/ | grep -c "browser-list"
curl -s "http://localhost:5002/clip-cutter/fs/ls" | python3 -c "import sys,json; d=json.load(sys.stdin); print('path:', d['path'])"
curl -s http://localhost:5002/clip-cutter/template | python3 -c "import sys,json; d=json.load(sys.stdin); print('has_template:', d['has_template'])"
```

Expected:
```
1
path: /user-data/Parra-Data/Cloud
has_template: False
```

- [ ] **Step 3: Manual walkthrough**

Open `http://localhost:5002/clip-cutter/` on the LAN. Verify:
1. Folder browser loads at `_DATA_ROOT` path
2. Navigate into a folder containing `.avi` files
3. Select a `.avi` file — sidebar shows "No template"
4. Click Init — template folder is created, minimal player appears
5. Browse frames and add one to template — thumbnail appears in sidebar
6. Click Clear — modal requires typing "delete"

- [ ] **Step 4: Commit any final fixes**

If any issues found during smoke test, fix them and commit. Otherwise:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add -A
git commit -m "chore: final smoke-test fixes for folder browser sub-project"
```

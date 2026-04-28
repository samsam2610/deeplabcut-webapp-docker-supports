# Sync Camera View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "sync cam" checkbox to the video player that shows the same frame number from a sibling camera recording alongside the main video.

**Architecture:** Backend discovers sibling camera files at video-selection time using filename regex (strips trailing `_N` suffix), stores the result in `_state`, and exposes it via a new read-only route. Frontend fetches the sibling path on `openPlayer()`, shows a passive second `<img>` in the horizontal space to the left of the extract panel, and mirrors every frame load to the sibling path in parallel.

**Tech Stack:** Python/Flask (routes.py), vanilla JS (enhanced_player.js), Jinja2 HTML template (clip_cutter.html), pytest.

---

## File Map

| File | Change |
|------|--------|
| `clip-cutter/routes.py` | Add `import re`; add `sibling_video_path` to `_state`; add `_find_sibling_camera()`; extend `select_video()`; add `GET /sibling-camera` |
| `clip-cutter/static/enhanced_player.js` | Add `_syncCamEnabled`, `_siblingVideoPath`; add `_epUpdateSyncCamUI()`, `_epLoadCam2Frame()`; extend `openPlayer()`, `_epLoadFrame()`, DOMContentLoaded |
| `clip-cutter/templates/clip_cutter.html` | Add CSS for `#ep-sync-cam-label`, `#ep-cam2-wrap`, `#ep-cam2-frame-wrap`; add checkbox HTML inside `#ep-frame-wrap`; add `#ep-cam2-wrap` between `#ep-left` and resize handle |
| `clip-cutter/tests/test_routes.py` | Add `_find_sibling_camera` unit tests; add `/sibling-camera` route tests; update `reset_routes_state` fixture |

---

## Task 1: Backend — sibling discovery helper, `_state` extension, `/sibling-camera` route

**Files:**
- Modify: `clip-cutter/routes.py`
- Modify: `clip-cutter/tests/test_routes.py`

- [ ] **Step 1: Write failing tests**

Append to `clip-cutter/tests/test_routes.py`:

```python
# ── Sibling camera discovery ──────────────────────────────────────────────────

def test_find_sibling_returns_sibling(tmp_path):
    cam2 = tmp_path / "m3_20250727_163450_2.avi"
    cam3 = tmp_path / "m3_20250727_163450_3.avi"
    cam2.touch()
    cam3.touch()
    assert routes._find_sibling_camera(cam3) == str(cam2)


def test_find_sibling_returns_none_when_alone(tmp_path):
    cam3 = tmp_path / "m3_20250727_163450_3.avi"
    cam3.touch()
    assert routes._find_sibling_camera(cam3) is None


def test_find_sibling_returns_none_no_trailing_number(tmp_path):
    vid = tmp_path / "no_trailing_number.avi"
    vid.touch()
    assert routes._find_sibling_camera(vid) is None


def test_sibling_camera_route_no_video_selected(client):
    resp = client.get("/clip-cutter/sibling-camera")
    assert resp.status_code == 200
    assert resp.get_json()["sibling_video_path"] is None


def test_sibling_camera_route_after_select(client, tmp_path):
    cam2 = tmp_path / "m3_20250727_163450_2.avi"
    cam3 = tmp_path / "m3_20250727_163450_3.avi"
    cam2.touch()
    cam3.touch()
    resp = client.post("/clip-cutter/select-video", json={"video_path": str(cam3)})
    assert resp.status_code == 200
    assert resp.get_json()["sibling_video_path"] == str(cam2)
    resp2 = client.get("/clip-cutter/sibling-camera")
    assert resp2.get_json()["sibling_video_path"] == str(cam2)


def test_select_video_no_sibling_returns_null(client, tmp_path):
    cam3 = tmp_path / "m3_20250727_163450_3.avi"
    cam3.touch()
    resp = client.post("/clip-cutter/select-video", json={"video_path": str(cam3)})
    assert resp.status_code == 200
    assert resp.get_json()["sibling_video_path"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_routes.py -k "sibling" -v 2>&1 | tail -20
```

Expected: all 6 new tests FAIL with `AttributeError: module 'routes' has no attribute '_find_sibling_camera'`.

- [ ] **Step 3: Update `reset_routes_state` fixture in `test_routes.py`**

Find and replace both occurrences of the state dict in `reset_routes_state` — the one before `yield` and the one after — to include `"sibling_video_path": None`:

```python
routes._state = {
    "frames": [],
    "mean_embedding": None,
    "dino_mean_embedding": None,
    "video_stem": None,
    "video_parent": None,
    "sibling_video_path": None,
}
```

- [ ] **Step 4: Add `import re` to `routes.py`**

In `clip-cutter/routes.py`, the current imports are:
```python
from __future__ import annotations

import csv
import json
import logging
import threading
import time
import uuid
from pathlib import Path
```

Add `import re` after `import csv`:
```python
from __future__ import annotations

import csv
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path
```

- [ ] **Step 5: Add `sibling_video_path` to `_state` in `routes.py`**

Find the `_state: dict = {` block (around line 30) and add the new field:

```python
_state: dict = {
    "frames": [],
    "mean_embedding": None,
    "dino_mean_embedding": None,
    "video_stem": None,
    "video_parent": None,
    "sibling_video_path": None,
}
```

- [ ] **Step 6: Add `_find_sibling_camera` helper in `routes.py`**

Add this function immediately before the `_load_libraries` function (around line 42):

```python
def _find_sibling_camera(video_path: Path) -> "str | None":
    """Return the first sibling camera AVI in the same dir, or None.

    Siblings share the same Subject_Date_Time prefix and differ only in the
    trailing _N camera-number suffix (e.g. m3_20250727_163450_2.avi vs _3.avi).
    """
    m = re.match(r'^(.+)_(\d+)$', video_path.stem)
    if not m:
        return None
    prefix = m.group(1)
    for candidate in sorted(video_path.parent.glob(f"{prefix}_*.avi")):
        tail = candidate.stem[len(prefix) + 1:]
        if candidate != video_path and re.match(r'^\d+$', tail):
            return str(candidate)
    return None
```

- [ ] **Step 7: Add `GET /sibling-camera` route in `routes.py`**

Add this route in the Filesystem browser section (after `select_video`, around line 820), before `# ── Scan`:

```python
@bp.route("/sibling-camera")
def get_sibling_camera():
    with _state_lock:
        sibling = _state.get("sibling_video_path")
    return jsonify({"sibling_video_path": sibling})
```

- [ ] **Step 8: Extend `select_video()` to compute and store sibling**

In `select_video()`, find the block that sets `_state["video_stem"]` and `_state["video_parent"]`:

```python
    with _state_lock:
        _state["video_stem"] = stem
        _state["video_parent"] = parent
```

Replace it with:

```python
    with _state_lock:
        _state["video_stem"] = stem
        _state["video_parent"] = parent
        _state["sibling_video_path"] = _find_sibling_camera(p)
```

Then find the `return jsonify(...)` at the end of `select_video` and add `sibling_video_path` to the response:

```python
    return jsonify({
        "count": count,
        "has_template": has_template,
        "sibling_video_path": _state.get("sibling_video_path"),
    })
```

- [ ] **Step 9: Run tests to verify they pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_routes.py -k "sibling" -v 2>&1 | tail -20
```

Expected: all 6 tests PASS.

- [ ] **Step 10: Run full test suite to check for regressions**

```bash
python -m pytest tests/ -v 2>&1 | tail -30
```

Expected: all tests pass (no regressions).

- [ ] **Step 11: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat: add _find_sibling_camera, /sibling-camera route, extend select_video"
```

---

## Task 2: HTML + CSS — second camera panel and sync checkbox

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html`

- [ ] **Step 1: Add CSS for sync checkbox and cam2 panel**

Find the `<style>` block in `clip_cutter.html`. Locate the `#ep-zoom-controls` rule (around line 311) and add the new rules after it:

```css
#ep-sync-cam-label {
  position: absolute; top: 28px; right: 6px;
  font-size: 8px; color: #768390;
  display: flex; align-items: center; gap: 3px;
  cursor: pointer; user-select: none;
}
#ep-sync-cam-label input { cursor: pointer; accent-color: #388bfd; }
#ep-cam2-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  padding-left: 6px;
}
#ep-cam2-frame-wrap {
  flex: 1;
  background: #1c2128;
  border: 1px solid #30363d;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  position: relative;
  min-height: 0;
}
#ep-cam2-frame { max-width: 100%; max-height: 100%; display: block; }
#ep-cam2-label {
  position: absolute; bottom: 4px; left: 6px;
  font-size: 8px; color: #768390; font-family: monospace;
}
```

- [ ] **Step 2: Add sync checkbox inside `#ep-frame-wrap`**

In the HTML body, find the `#ep-frame-wrap` div (around line 697). It currently ends with the zoom controls div:

```html
      <div id="ep-zoom-controls">
        &#128269;
        <input type="range" id="ep-zoom" min="50" max="200" value="100">
        <span id="ep-zoom-pct">100%</span>
      </div>
    </div>
```

Add the sync cam label after the zoom controls div, before `</div>` (the closing tag of `#ep-frame-wrap`):

```html
      <div id="ep-zoom-controls">
        &#128269;
        <input type="range" id="ep-zoom" min="50" max="200" value="100">
        <span id="ep-zoom-pct">100%</span>
      </div>
      <label id="ep-sync-cam-label" title="Show same frame from sibling camera" style="display:none;">
        <input type="checkbox" id="ep-sync-cam"> sync cam
      </label>
    </div>
```

- [ ] **Step 3: Add `#ep-cam2-wrap` panel between `#ep-left` and the resize handle**

Find the comment and element `<!-- Drag handle between video viewer and extract panel -->` (around line 781):

```html
  </div>

  <!-- Drag handle between video viewer and extract panel -->
  <div id="ep-panel-resize-handle"></div>
```

Insert the cam2 panel before the drag handle:

```html
  </div>

  <!-- Centre: second camera frame (sync cam view, hidden until activated) -->
  <div id="ep-cam2-wrap" style="display:none;">
    <div id="ep-cam2-frame-wrap">
      <img id="ep-cam2-frame" alt="cam 2 frame">
      <div id="ep-cam2-label">cam 2</div>
    </div>
  </div>

  <!-- Drag handle between video viewer and extract panel -->
  <div id="ep-panel-resize-handle"></div>
```

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/templates/clip_cutter.html
git commit -m "feat: add sync cam checkbox and second camera panel to player HTML"
```

---

## Task 3: JS — new state variables and helper functions

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js`

- [ ] **Step 1: Add `_syncCamEnabled` and `_siblingVideoPath` state variables**

In `enhanced_player.js`, find the state variables block near the top. After `let _unlocked = false;` (around line 33), add:

```js
let _syncCamEnabled = false;
let _siblingVideoPath = null;
```

- [ ] **Step 2: Add `_epUpdateSyncCamUI()` function**

Add this function after the `_stop()` function (around line 210):

```js
function _epUpdateSyncCamUI() {
  const label = document.getElementById("ep-sync-cam-label");
  const cb    = document.getElementById("ep-sync-cam");
  const cam2  = document.getElementById("ep-cam2-wrap");
  if (!_siblingVideoPath) {
    label.style.display = "none";
    cb.checked = false;
    _syncCamEnabled = false;
    cam2.style.display = "none";
    return;
  }
  label.style.display = "";
  cam2.style.display = _syncCamEnabled ? "flex" : "none";
}
```

- [ ] **Step 3: Add `_epLoadCam2Frame(n)` function**

Add this function immediately after `_epUpdateSyncCamUI()`:

```js
async function _epLoadCam2Frame(n) {
  if (!_syncCamEnabled || !_siblingVideoPath) return;
  try {
    const resp = await fetch(`/clip-cutter/frame?video=${encodeURIComponent(_siblingVideoPath)}&n=${n}`);
    if (!resp.ok) return;
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const img = document.getElementById("ep-cam2-frame");
    const prevSrc = img.src;
    img.onload = () => { if (prevSrc && prevSrc.startsWith("blob:")) URL.revokeObjectURL(prevSrc); };
    img.src = blobUrl;
  } catch (e) {
    console.warn("[enhanced_player] cam2 frame load error:", e.message);
  }
}
```

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/static/enhanced_player.js
git commit -m "feat: add _syncCamEnabled state, _epUpdateSyncCamUI, _epLoadCam2Frame to enhanced_player"
```

---

## Task 4: JS — hook into existing functions and wire checkbox event

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js`

- [ ] **Step 1: Extend `_epLoadFrame(n)` to mirror the frame to cam2**

In `_epLoadFrame`, find the line `const _ac = document.getElementById("ep-add-confirm");` (around line 169). After `if (_ac) _ac.style.display = "none";`, add the cam2 call:

```js
    const _ac = document.getElementById("ep-add-confirm");
    if (_ac) _ac.style.display = "none";
    _epLoadCam2Frame(n);   // non-blocking parallel fetch for second camera
    if (n < (_unlocked ? _frameCount - 1 : _clipEnd)) {
```

- [ ] **Step 2: Extend `openPlayer()` to fetch sibling and initialize sync UI**

In `openPlayer()`, find the line `_epBuildTagBars();` (around line 128). Insert the sibling fetch block before it:

```js
  // Fetch sibling camera path (computed server-side at select-video time)
  _syncCamEnabled = false;
  _siblingVideoPath = null;
  try {
    const sr = await fetch("/clip-cutter/sibling-camera");
    if (sr.ok) {
      const sd = await sr.json();
      _siblingVideoPath = sd.sibling_video_path || null;
    }
  } catch (e) { console.warn("[enhanced_player] sibling-camera fetch failed:", e); }
  _epUpdateSyncCamUI();

  _epBuildTagBars();
```

- [ ] **Step 3: Wire the sync cam checkbox `change` event in DOMContentLoaded**

In the `DOMContentLoaded` handler, find the zoom slider event listener block:

```js
  // Zoom slider
  document.getElementById("ep-zoom").addEventListener("input", (e) => {
```

Add the sync cam checkbox listener immediately after the zoom slider block:

```js
  // Sync cam checkbox
  document.getElementById("ep-sync-cam").addEventListener("change", (e) => {
    _syncCamEnabled = e.target.checked;
    _epUpdateSyncCamUI();
    if (_syncCamEnabled) _epLoadCam2Frame(_currentFrame);
  });
```

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/static/enhanced_player.js
git commit -m "feat: wire sync cam into _epLoadFrame, openPlayer, and checkbox event"
```

---

## Task 5: Verify, compose up, and smoke test

- [ ] **Step 1: Run full test suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/ -v 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 2: Compose up**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
docker compose up --build -d
```

Expected: container restarts cleanly, no errors in `docker compose logs clip-cutter`.

- [ ] **Step 3: Smoke test — single-camera video**

Open `http://localhost:PORT` (check docker-compose.yml for the host port). Select a video that has no sibling camera file. Open the player. Verify the "sync cam" checkbox is not visible.

- [ ] **Step 4: Smoke test — multi-camera video**

Select a video from a session that has two camera files (e.g. a video with `_2.avi` and `_3.avi` siblings). Open the player. Verify:
1. "sync cam" checkbox appears below the zoom slider (top-right of frame area).
2. Checkbox is unchecked by default.
3. Checking it shows a second frame panel to the right of the main video, displaying the same frame from the sibling camera.
4. Navigating frames (arrow keys, seek bar, play) keeps both frames in sync.
5. Switching to a different detection candidate keeps the checkbox state (checked/unchecked) unchanged.
6. Unchecking the box hides the second panel.

- [ ] **Step 5: Final commit (if any cleanup needed)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add -p   # review any remaining changes
git commit -m "fix: sync camera view cleanup"
```

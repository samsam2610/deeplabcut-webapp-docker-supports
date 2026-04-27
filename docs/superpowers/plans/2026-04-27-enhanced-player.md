# Enhanced Player Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two existing video players (`player.js` inline clip viewer and `_tp` template browser in `clip_cutter.js`) with a single `enhanced_player.js` bottom panel that supports clip mode and template mode, adding step-size navigation, editable frame counter, zoom, CSV status/note display, play-every-N, and a clip extract panel.

**Architecture:** A new `enhanced_player.js` exposes one public function `openPlayer(config)` called by `clip_cutter.js`; all state is module-private. The panel (`#player-panel`) lives as a fixed bottom strip (position:fixed, height 320px) always in the DOM, shown/hidden by JS. The existing `player.js` is deleted.

**Tech Stack:** Flask/Python (backend CSV route), vanilla JS (player module), plain CSS inside the existing `clip_cutter.html` `<style>` block.

---

## File Map

| File | Action |
|------|--------|
| `clip-cutter/static/enhanced_player.js` | **Create** — all player logic |
| `clip-cutter/static/player.js` | **Delete** |
| `clip-cutter/routes.py` | **Modify** — add `GET /clip-cutter/csv` route |
| `clip-cutter/tests/test_routes.py` | **Modify** — add 3 CSV tests |
| `clip-cutter/templates/clip_cutter.html` | **Modify** — remove old player markup, add `#player-panel`, update CSS, swap script tag |
| `clip-cutter/static/clip_cutter.js` | **Modify** — remove `_tp` block, update card click and Browse buttons, update Reject, delete `player.js` call sites |

---

## Codebase context (read before starting)

- All files live under `clip-cutter/`.
- Run tests from `clip-cutter/`: `python -m pytest tests/ -v`
- Flask Blueprint prefix: `/clip-cutter`
- Backend serves frames via `GET /clip-cutter/frame?video=<path>&n=<0-based>` → JPEG blob.
- Video info: `GET /clip-cutter/video-info?video=<path>` → `{ "frame_count": N }`.
- Extract endpoint: `POST /clip-cutter/extract` with `{ "video_path": "...", "key_frame": N }` (1-based).
- Overlap check: `POST /clip-cutter/check-keyframe-overlap` with `{ "video_path": "...", "key_frame": N }` → `{ "overlaps": bool, "conflicts": [{ "name": "...", "overlap_frames": N }] }`.
- `config._DATA_ROOT` — the path jail for file access.
- Cross-file globals available from `clip_cutter.js`: `detections[]` (array), `saveDetections()`, `setStatus(msg)`, `selectedVideoPath`.
- Detection object shape: `{ video_path, frame_number, status, ... }`. Status values: `"pending"`, `"kept"`, `"rejected"`.
- Card DOM ids: `#card-{idx}` (the card), `#card-clipname-{idx}` (the clip name span inside the card).

---

## Task 1: Backend — GET /clip-cutter/csv route

**Files:**
- Modify: `clip-cutter/routes.py` (add route after `check_keyframe_overlap`)
- Modify: `clip-cutter/tests/test_routes.py` (append 3 tests)

### Step 1.1: Write the three failing tests

Append to `clip-cutter/tests/test_routes.py`:

```python
def test_csv_returns_rows(client, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path)
    csv_file = tmp_path / "video.csv"
    csv_file.write_text(
        "timestamp,frame_number,frame_line_status,note\n"
        "0.0,1,14,start_reaching\n"
        "0.067,2,0,\n"
    )
    resp = client.get(f"/clip-cutter/csv?path={csv_file}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["rows"]) == 2
    assert data["rows"][0] == {"frame_number": 1, "frame_line_status": "14", "note": "start_reaching"}
    assert data["rows"][1] == {"frame_number": 2, "frame_line_status": "0", "note": ""}


def test_csv_missing_file_returns_404(client, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path)
    resp = client.get(f"/clip-cutter/csv?path={tmp_path / 'nonexistent.csv'}")
    assert resp.status_code == 404


def test_csv_path_outside_data_root_returns_403(client, tmp_path, monkeypatch):
    import config
    # data root is a subdir; request is to the parent — outside root
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path / "subdir")
    resp = client.get(f"/clip-cutter/csv?path={tmp_path / 'video.csv'}")
    assert resp.status_code == 403
```

- [ ] **Step 1.2: Run tests to confirm they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_routes.py::test_csv_returns_rows tests/test_routes.py::test_csv_missing_file_returns_404 tests/test_routes.py::test_csv_path_outside_data_root_returns_403 -v
```

Expected: 3 failures with `404 Not Found` (route doesn't exist yet).

- [ ] **Step 1.3: Add `import csv` to routes.py**

At the top of `clip-cutter/routes.py`, add `import csv` after the existing stdlib imports:

```python
import csv
import json
import logging
import threading
import time
import uuid
from pathlib import Path
```

- [ ] **Step 1.4: Add the route to routes.py**

Insert after the `check_keyframe_overlap` function (after line 447 in the current file):

```python
@bp.route("/csv")
def get_csv():
    path_str = request.args.get("path", "").strip()
    if not path_str:
        return jsonify({"error": "path required"}), 400

    try:
        csv_path = Path(path_str).resolve()
        csv_path.relative_to(config._DATA_ROOT.resolve())
    except ValueError:
        return jsonify({"error": "path outside data root"}), 403

    if not csv_path.exists():
        return jsonify({"error": "file not found"}), 404

    rows = []
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({
                    "frame_number": int(row["frame_number"]),
                    "frame_line_status": str(row.get("frame_line_status", "") or ""),
                    "note": str(row.get("note", "") or ""),
                })
    except Exception as e:
        return jsonify({"error": f"CSV parse error: {e}"}), 500

    return jsonify({"rows": rows})
```

- [ ] **Step 1.5: Run tests — expect 3 passes**

```bash
python -m pytest tests/test_routes.py::test_csv_returns_rows tests/test_routes.py::test_csv_missing_file_returns_404 tests/test_routes.py::test_csv_path_outside_data_root_returns_403 -v
```

Expected: all 3 PASS.

- [ ] **Step 1.6: Run full test suite to check for regressions**

```bash
python -m pytest tests/ -v
```

Expected: all existing tests still pass.

- [ ] **Step 1.7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat: add GET /clip-cutter/csv route with path validation and 3 tests"
```

---

## Task 2: HTML — Replace player markup with #player-panel

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html`

This task restructures the HTML and CSS only — no JS behaviour changes yet.

- [ ] **Step 2.1: Remove template-player CSS rules**

In the `<style>` block, delete these three rules (around lines 46–50):

```css
/* Minimal template player */
.template-player-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
#tp-frame-wrap { background: #1c2128; border: 1px solid #30363d; border-radius: 4px; overflow: hidden; max-height: 200px; display: flex; align-items: center; justify-content: center; margin-bottom: 6px; }
#tp-controls { display: flex; align-items: center; gap: 6px; }
```

- [ ] **Step 2.2: Remove old player pane CSS rules**

Delete these rules (around lines 138–156):

```css
/* Player pane (right 60%) */
.player-pane { flex: 1; display: flex; flex-direction: column; background: #0d1117; overflow: hidden; }
#player-placeholder { flex: 1; display: flex; align-items: center; justify-content: center; font-size: 11px; color: #768390; }
#player-container { flex: 1; display: flex; flex-direction: column; padding: 8px; gap: 6px; }
#player-frame-wrap { flex: 1; background: #1c2128; border-radius: 4px; border: 1px solid #30363d; overflow: hidden; display: flex; align-items: center; justify-content: center; min-height: 0; }
#player-frame { max-width: 100%; max-height: 100%; display: block; }
#player-controls { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
#player-seek { flex: 1; accent-color: #1f6feb; cursor: pointer; }
#player-frame-num { font-size: 10px; color: #768390; white-space: nowrap; font-family: monospace; }
#player-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
```

Also delete the `#player-overlap-warning` block (lines 152–156):

```css
#player-overlap-warning { background: #161b22; border: 1px solid #da3633; border-radius: 6px; padding: 10px 12px; margin-top: 4px; flex-shrink: 0; }
#player-overlap-warning .ow-title { color: #f85149; font-size: 11px; font-weight: 600; margin-bottom: 4px; }
#player-overlap-warning .ow-body { font-size: 10px; color: #8b949e; margin-bottom: 8px; }
#player-overlap-warning .ow-body code { color: #e6edf3; background: #21262d; padding: 1px 4px; border-radius: 3px; }
#player-overlap-warning .ow-actions { display: flex; gap: 6px; }
```

- [ ] **Step 2.3: Update results pane CSS to take full width**

Change the `.results-pane` rule from:

```css
.results-pane { width: 40%; border-right: 1px solid #30363d; display: flex; flex-direction: column; overflow: hidden; }
```

to:

```css
.results-pane { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
```

- [ ] **Step 2.4: Add enhanced player CSS**

Append before `</style>`:

```css
/* ── Enhanced player bottom panel ─────────────────────────────────────────── */
#player-panel {
  position: fixed; bottom: 0; left: 0; right: 0;
  height: 320px;
  background: #0d1117;
  border-top: 2px solid #30363d;
  z-index: 50;
  display: flex;
  gap: 8px;
  padding: 8px;
  overflow: auto;
  resize: vertical;
}
#ep-left {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}
#ep-frame-wrap {
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
#ep-frame { max-width: 100%; max-height: 100%; display: block; transform-origin: center center; }
#ep-lock-badge {
  position: absolute; top: 4px; left: 6px;
  background: #da363322; border: 1px solid #da3633; border-radius: 3px;
  padding: 1px 5px; font-size: 8px; color: #f85149;
  font-family: monospace;
}
#ep-zoom-controls {
  position: absolute; top: 4px; right: 6px;
  display: flex; align-items: center; gap: 4px;
  font-size: 8px; color: #768390;
}
#ep-zoom-controls input { width: 50px; accent-color: #388bfd; }
#ep-seek-row {
  display: flex; align-items: center; gap: 6px; flex-shrink: 0;
}
#ep-seek-track {
  flex: 1; position: relative; height: 16px;
}
#ep-seek-highlight {
  position: absolute; top: 6px; height: 4px;
  background: #1f6feb33; border-radius: 2px;
  pointer-events: none;
}
#ep-seek {
  position: absolute; top: 0; left: 0; right: 0; width: 100%;
  margin: 0; accent-color: #1f6feb; cursor: pointer;
}
#ep-frame-counter {
  font-size: 10px; color: #768390; white-space: nowrap;
  font-family: monospace; cursor: default;
}
#ep-frame-num { color: #e6edf3; text-decoration: underline; }
#ep-frame-jump {
  width: 60px; background: #21262d; border: 1px solid #388bfd;
  border-radius: 3px; color: #e6edf3; font-size: 10px; padding: 1px 3px;
  font-family: monospace;
}
#ep-controls {
  display: flex; align-items: center; gap: 4px; flex-shrink: 0;
  flex-wrap: wrap;
}
#ep-controls span { font-size: 9px; color: #768390; }
#ep-controls input[type="number"] {
  width: 32px; background: #21262d; border: 1px solid #30363d;
  border-radius: 3px; color: #e6edf3; font-size: 9px; padding: 1px 3px;
}
#ep-csv-strip {
  display: flex; align-items: center; gap: 5px; flex-shrink: 0;
  background: #161b22; border: 1px solid #30363d;
  border-radius: 4px; padding: 3px 6px;
}
.ep-strip-label { font-size: 8px; color: #768390; }
.ep-status-pill {
  background: #1f6feb22; border: 1px solid #1f6feb;
  border-radius: 3px; color: #58a6ff; padding: 1px 5px; font-size: 8px;
}
.ep-note-pill {
  background: #2ea04322; border: 1px solid #2ea043;
  border-radius: 3px; color: #3fb950; padding: 1px 5px; font-size: 8px;
}
/* Extract panel */
#ep-extract-panel {
  width: 160px; flex-shrink: 0;
  background: #161b22; border: 1px solid #30363d; border-radius: 4px;
  padding: 7px;
  display: flex; flex-direction: column; gap: 5px;
}
.ep-panel-title {
  font-size: 9px; font-weight: 600; color: #cdd9e5;
  border-bottom: 1px solid #30363d; padding-bottom: 3px;
}
#ep-extract-fields {
  display: grid; grid-template-columns: auto 1fr; gap: 3px 5px; align-items: center;
  font-size: 8px;
}
#ep-extract-fields span { color: #768390; }
#ep-extract-fields input[type="number"],
#ep-extract-fields input[type="text"] {
  background: #21262d; border: 1px solid #30363d; border-radius: 3px;
  color: #e6edf3; font-size: 8px; padding: 1px 3px; width: 100%;
}
#ep-extract-fields input[readonly] { background: #0d1117; color: #768390; border-color: #21262d; }
#ep-lock-row { display: flex; align-items: center; gap: 4px; font-size: 8px; color: #768390; }
#ep-lock-row input { accent-color: #388bfd; }
#ep-outdir {
  font-size: 8px; color: #768390;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  border: 1px solid #21262d; border-radius: 3px; padding: 2px 4px;
  background: #0d1117;
}
#ep-extract-panel .ep-spacer { flex: 1; }
#ep-warning {
  font-size: 8px; padding: 4px; background: #1a0a0a;
  border: 1px solid #da3633; border-radius: 3px;
}
.ep-btn-green { border-color: #2ea043 !important; color: #3fb950 !important; }
.ep-btn-green:hover { background: #2ea04322 !important; }
.ep-btn-blue { border-color: #388bfd !important; color: #58a6ff !important; font-weight: 600; }
.ep-btn-blue:hover { background: #388bfd22 !important; }
.ep-btn-red { border-color: #da3633 !important; color: #f85149 !important; }
.ep-btn-red:hover { background: #da363322 !important; }
#ep-extract-panel .player-btn { width: 100%; font-size: 8px; padding: 3px 5px; }
```

- [ ] **Step 2.5: Remove `#template-player-panel` HTML block**

Delete the entire `<div id="template-player-panel" ...>` section (lines 243–261 in current file):

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

- [ ] **Step 2.6: Replace `.player-pane` div with nothing (remove it)**

Delete the entire player pane from `.content-split` (lines 309–335):

```html
      <!-- Player -->
      <div class="player-pane">
        <div id="player-placeholder">Click a detection to preview</div>
        <div id="player-container" style="display:none;">
          <div id="player-frame-wrap">
            <img id="player-frame" alt="video frame">
          </div>
          <div id="player-controls">
            <button class="player-btn" id="player-prev">&#9198;</button>
            <button class="player-btn" id="player-play">&#9654;</button>
            <button class="player-btn" id="player-next">&#9197;</button>
            <input type="range" id="player-seek" min="0" max="1000" value="0">
            <span id="player-frame-num">fr 0</span>
          </div>
          <div id="player-actions">
            <button class="player-btn" id="player-keyframe">&#8982; Key frame</button>
            <button class="player-btn active" id="player-loop">&#8617; Loop</button>
            <button class="player-btn" id="player-clip-start">&#9654; From clip start</button>
            <div style="flex:1"></div>
            <span style="font-size:10px;color:#768390;font-family:monospace;white-space:nowrap;">KF: <span id="player-kf-num">&#8212;</span></span>
            <button class="player-btn player-btn-blue" id="player-set-kf">&#128204; Set KF here</button>
          </div>
          <div id="player-overlap-warning" style="display:none;"></div>
        </div>
      </div>
```

- [ ] **Step 2.7: Add `#player-panel` to the DOM**

Insert immediately before the `<!-- Clear template confirmation modal -->` comment:

```html
<!-- Enhanced player bottom panel -->
<div id="player-panel" style="display:none;">
  <!-- Left: frame + controls -->
  <div id="ep-left">
    <div id="ep-frame-wrap">
      <img id="ep-frame" alt="frame">
      <div id="ep-lock-badge" style="display:none;">&#128274; 0&#8211;0</div>
      <div id="ep-zoom-controls">
        &#128269;
        <input type="range" id="ep-zoom" min="50" max="200" value="100">
        <span id="ep-zoom-pct">100%</span>
      </div>
    </div>

    <!-- Seek bar -->
    <div id="ep-seek-row">
      <div id="ep-seek-track">
        <div id="ep-seek-highlight" style="display:none;"></div>
        <input type="range" id="ep-seek" min="0" max="1000" value="0">
      </div>
      <span id="ep-frame-counter" title="double-click to jump">fr <span id="ep-frame-num">0</span> / <span id="ep-frame-total">0</span></span>
      <input type="number" id="ep-frame-jump" style="display:none;" min="1">
    </div>

    <!-- Playback controls -->
    <div id="ep-controls">
      <button class="player-btn" id="ep-first">&#9198;</button>
      <button class="player-btn" id="ep-back">&#9664;</button>
      <button class="player-btn" id="ep-play">&#9654;</button>
      <button class="player-btn" id="ep-fwd">&#9654;</button>
      <button class="player-btn" id="ep-last">&#9197;</button>
      <span>Step</span>
      <input type="number" id="ep-step" min="1" value="10">
      <span>N=</span>
      <input type="number" id="ep-playn" min="1" value="1">
      <button class="player-btn" id="ep-loop">&#8635;</button>
      <div style="flex:1;"></div>
      <button class="player-btn" id="ep-collapse">&#10005;</button>
    </div>

    <!-- Status / note strip -->
    <div id="ep-csv-strip">
      <span class="ep-strip-label">Status:</span>
      <span id="ep-status-badge" class="ep-status-pill">&#8212;</span>
      <span class="ep-strip-label" style="margin-left:4px;">Note:</span>
      <span id="ep-note-badge" class="ep-note-pill">&#8212;</span>
      <div style="flex:1;"></div>
      <button class="player-btn" id="ep-prev-tag">&#9664;</button>
      <button class="player-btn" id="ep-next-tag">&#9654;</button>
    </div>
  </div>

  <!-- Right: extract panel -->
  <div id="ep-extract-panel">
    <div class="ep-panel-title">&#9986; Extract</div>

    <div id="ep-extract-fields">
      <span>Start</span>
      <input type="number" id="ep-start" min="1" value="1">
      <span>Frames</span>
      <input type="number" id="ep-frames" min="1" value="800">
      <span>End</span>
      <input type="number" id="ep-end" readonly>
      <span>Postfix</span>
      <input type="text" id="ep-postfix" placeholder="opt.">
    </div>

    <div id="ep-lock-row">
      <input type="checkbox" id="ep-lock-start">
      <label for="ep-lock-start">Lock start</label>
    </div>

    <div id="ep-outdir">&#8230;/</div>

    <div id="ep-warning" style="display:none;"></div>

    <div class="ep-spacer"></div>

    <button class="player-btn ep-btn-green" id="ep-add-template" style="display:none;">+ Add to template</button>
    <button class="player-btn ep-btn-green" id="ep-set-kf" style="display:none;">&#128204; Set KF</button>
    <button class="player-btn ep-btn-blue" id="ep-extract">&#9986; Extract</button>
    <button class="player-btn ep-btn-red" id="ep-reject" style="display:none;">&#10005; Reject</button>
  </div>
</div>
```

- [ ] **Step 2.8: Swap the script tag**

Change:

```html
<script src="/clip-cutter/static/player.js"></script>
<script src="/clip-cutter/static/clip_cutter.js"></script>
```

to:

```html
<script src="/clip-cutter/static/enhanced_player.js"></script>
<script src="/clip-cutter/static/clip_cutter.js"></script>
```

- [ ] **Step 2.9: Smoke-test the page loads**

Start the server (`python app.py` from `clip-cutter/`) and open `http://localhost:5001/clip-cutter/`. Verify:
- Page loads without JS errors in the console.
- No `player.js` 404 (the script tag references `enhanced_player.js` which doesn't exist yet — there WILL be a 404 for that file, that's expected for now).
- The results pane fills the full right area.
- No old player pane is visible.

- [ ] **Step 2.10: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/templates/clip_cutter.html
git commit -m "feat: replace player markup with #player-panel bottom panel, update CSS"
```

---

## Task 3: clip_cutter.js — Remove _tp block, wire openPlayer, update Reject

**Files:**
- Modify: `clip-cutter/static/clip_cutter.js`

- [ ] **Step 3.1: Remove _tp event listeners from DOMContentLoaded**

In the DOMContentLoaded handler, delete the entire template player controls block (around lines 131–172):

```javascript
  // Template player controls
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
    const frameNumber = _tp.currentFrame + 1; // convert 0-based to 1-based
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
```

- [ ] **Step 3.2: Update Browse buttons to call openPlayer**

Replace these two listeners (around lines 94–99):

```javascript
  // Browse frames buttons (no-template state and has-template state)
  document.getElementById("sidebar-browse-btn").addEventListener("click", () => {
    if (typeof openTemplatePlayer === "function") openTemplatePlayer();
  });
  document.getElementById("sidebar-browse-btn2").addEventListener("click", () => {
    if (typeof openTemplatePlayer === "function") openTemplatePlayer();
  });
```

with:

```javascript
  // Browse frames buttons
  const _openBrowse = () => {
    if (!selectedVideoPath) { setStatus("No video selected"); return; }
    openPlayer({
      mode: "template",
      videoPath: selectedVideoPath,
      csvPath: selectedVideoPath.replace(/\.avi$/i, ".csv"),
    });
  };
  document.getElementById("sidebar-browse-btn").addEventListener("click", _openBrowse);
  document.getElementById("sidebar-browse-btn2").addEventListener("click", _openBrowse);
```

- [ ] **Step 3.3: Update pollInitStatus to call openPlayer**

In `pollInitStatus`, replace `openTemplatePlayer()` (line ~265) with:

```javascript
        openPlayer({
          mode: "template",
          videoPath: selectedVideoPath,
          csvPath: selectedVideoPath.replace(/\.avi$/i, ".csv"),
        });
```

The surrounding context looks like:

```javascript
      if (!data.running) {
        clearInterval(iv);
        await loadTemplate();
        setStatus(`Template initialised: ${data.count} frame${data.count !== 1 ? "s" : ""} — browse to add more`);
        openPlayer({
          mode: "template",
          videoPath: selectedVideoPath,
          csvPath: selectedVideoPath.replace(/\.avi$/i, ".csv"),
        });
```

- [ ] **Step 3.4: Update card click handler**

In `buildResultCard`, replace the card click listener (around lines 653–658):

```javascript
  card.addEventListener("click", (e) => {
    if (e.target.closest("button")) return;
    document.querySelectorAll(".result-card").forEach((c) => c.classList.remove("active-preview"));
    card.classList.add("active-preview");
    if (typeof loadClip === "function") loadClip(d.video_path, d.frame_number, idx);
  });
```

with:

```javascript
  card.addEventListener("click", (e) => {
    if (e.target.closest("button")) return;
    document.querySelectorAll(".result-card").forEach((c) => c.classList.remove("active-preview"));
    card.classList.add("active-preview");
    openPlayer({
      mode: "clip",
      videoPath: d.video_path,
      keyFrame1Based: d.frame_number,
      detectionIdx: idx,
      csvPath: d.video_path.replace(/\.avi$/i, ".csv"),
    });
  });
```

- [ ] **Step 3.5: Update rejectDetection to splice the array**

Replace the existing `rejectDetection` function:

```javascript
async function rejectDetection(idx) {
  detections[idx].status = "rejected";
  const card = document.getElementById(`card-${idx}`);
  card.classList.add("rejected");
  card.querySelectorAll("button").forEach((b) => (b.disabled = true));
  await saveDetections();
}
```

with:

```javascript
async function rejectDetection(idx) {
  detections.splice(idx, 1);
  const card = document.getElementById(`card-${idx}`);
  if (card) card.remove();
  await saveDetections();
}
```

- [ ] **Step 3.6: Remove the _tp object and all _tp* functions**

Delete the entire "Minimal template player" section at the bottom of clip_cutter.js (lines 691–766):

```javascript
// ── Minimal template player ──────────────────────────────────────────────────

let _tp = {
  videoPath: null,
  frameCount: 0,
  currentFrame: 0,
  playing: false,
  busy: false,
  timerId: null,
};

async function openTemplatePlayer() { ... }
function closeTemplatePlayer() { ... }
async function _tpLoadFrame(n) { ... }
function _tpUpdateDisplay() { ... }
async function _tpLoop() { ... }
```

Delete all of it (approximately lines 691–766).

- [ ] **Step 3.7: Verify the page still loads**

Start the server. Open the page. Console will show a 404 for `enhanced_player.js` (not yet created). Verify no other JS errors. Click Browse frames — nothing happens yet (openPlayer is undefined). That's expected.

- [ ] **Step 3.8: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/static/clip_cutter.js
git commit -m "refactor: remove _tp player block, wire openPlayer calls, update rejectDetection to splice"
```

---

## Task 4: enhanced_player.js — Core scaffold (state, openPlayer, frame loading, playback loop)

**Files:**
- Create: `clip-cutter/static/enhanced_player.js`

This task creates the file with all state variables, the `openPlayer()` public function, `_epLoadFrame()`, `_loop()`, `_stop()`, `_epUpdateDisplay()`, `_epUpdateModeUI()`, `_epInitExtractPanel()`, and the `_epUpdateSeekHighlight()` helper. No event listeners yet.

- [ ] **Step 4.1: Create `clip-cutter/static/enhanced_player.js` with this exact content**

```javascript
// enhanced_player.js — unified video player for clip mode and template mode.
// Public API: openPlayer(config) — all other symbols are module-private.

const _EP_FPS = 15;

// ── State ──────────────────────────────────────────────────────────────────────
let _mode = null;          // "template" | "clip"
let _videoPath = null;
let _frameCount = 0;
let _currentFrame = 0;     // 0-based
let _clipStart = 0;        // 0-based
let _clipEnd = 0;          // 0-based
let _keyFrame = 0;         // 0-based
let _detectionIdx = null;
let _csvRows = [];
let _stepSize = 10;
let _playN = 1;
let _playing = false;
let _looping = true;
let _busy = false;
let _timerId = null;

// ── Public API ──────────────────────────────────────────────────────────────────

async function openPlayer({ mode, videoPath, keyFrame1Based = null, detectionIdx = null, csvPath = null }) {
  _stop();
  _mode = mode;
  _videoPath = videoPath;
  _detectionIdx = detectionIdx;
  _csvRows = [];

  let info;
  try {
    const resp = await fetch(`/clip-cutter/video-info?video=${encodeURIComponent(videoPath)}`);
    if (!resp.ok) { setStatus("Cannot load video info"); return; }
    info = await resp.json();
  } catch (e) { setStatus("Network error: " + e.message); return; }
  _frameCount = info.frame_count;

  if (mode === "clip" && keyFrame1Based !== null) {
    const kf0 = keyFrame1Based - 1;
    _keyFrame = kf0;
    _clipStart = Math.max(0, kf0 - 200);
    _clipEnd = Math.min(_frameCount - 1, kf0 + 599);
  } else {
    _keyFrame = 0;
    _clipStart = 0;
    _clipEnd = _frameCount - 1;
  }
  _currentFrame = _clipStart;

  document.getElementById("player-panel").style.display = "";

  _epUpdateModeUI();
  _epInitExtractPanel(videoPath, keyFrame1Based);

  if (csvPath) {
    try {
      const r = await fetch(`/clip-cutter/csv?path=${encodeURIComponent(csvPath)}`);
      if (r.ok) _csvRows = (await r.json()).rows;
    } catch {}
  }

  await _epLoadFrame(_clipStart);
}

// ── Frame loading ──────────────────────────────────────────────────────────────

async function _epLoadFrame(n) {
  if (_busy || !_videoPath) return;
  _busy = true;
  n = Math.max(_clipStart, Math.min(n, _clipEnd));
  const prev = _currentFrame;
  _currentFrame = n;
  try {
    const resp = await fetch(`/clip-cutter/frame?video=${encodeURIComponent(_videoPath)}&n=${n}`);
    if (!resp.ok) { _currentFrame = prev; return; }
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const img = document.getElementById("ep-frame");
    const prevSrc = img.src;
    await new Promise((resolve, reject) => {
      img.onload = () => { if (prevSrc.startsWith("blob:")) URL.revokeObjectURL(prevSrc); resolve(); };
      img.onerror = reject;
      img.src = blobUrl;
    });
    _epUpdateDisplay();
    if (n < _clipEnd) {
      new Image().src = `/clip-cutter/frame?video=${encodeURIComponent(_videoPath)}&n=${n + 1}`;
    }
  } finally {
    _busy = false;
  }
}

// ── Playback loop ──────────────────────────────────────────────────────────────

async function _epLoop() {
  if (!_playing) return;
  if (_busy) { _timerId = setTimeout(_epLoop, Math.round(1000 / _EP_FPS)); return; }

  let next = _currentFrame + _playN;
  if (next > _clipEnd) {
    if (_looping) next = _clipStart;
    else { _stop(); return; }
  }
  const t0 = performance.now();
  await _epLoadFrame(next);
  if (!_playing) return;
  const delay = Math.max(0, Math.round(1000 / _EP_FPS) - (performance.now() - t0));
  _timerId = setTimeout(_epLoop, delay);
}

function _stop() {
  if (_timerId !== null) { clearTimeout(_timerId); _timerId = null; }
  _playing = false;
  const btn = document.getElementById("ep-play");
  if (btn) btn.textContent = "▶";
}

// ── Display ────────────────────────────────────────────────────────────────────

function _epUpdateDisplay() {
  const cur1 = _currentFrame + 1;
  document.getElementById("ep-frame-num").textContent = cur1;
  document.getElementById("ep-frame-total").textContent = _frameCount;

  const seekEl = document.getElementById("ep-seek");
  seekEl.value = _currentFrame;

  _epUpdateSeekHighlight();
  _epUpdateCsvStrip();

  if (!document.getElementById("ep-lock-start").checked) {
    document.getElementById("ep-start").value = cur1;
    _epUpdateEnd();
  }
}

function _epUpdateSeekHighlight() {
  const h = document.getElementById("ep-seek-highlight");
  if (!h) return;
  if (_mode !== "clip" || _frameCount <= 1) { h.style.display = "none"; return; }
  h.style.display = "";
  const total = _frameCount - 1;
  const left = (_clipStart / total) * 100;
  const width = ((_clipEnd - _clipStart) / total) * 100;
  h.style.left = left + "%";
  h.style.width = width + "%";
}

function _epUpdateCsvStrip() {
  const cur1 = _currentFrame + 1;
  const row = _csvRows.find(r => r.frame_number === cur1);
  const statusBadge = document.getElementById("ep-status-badge");
  const noteBadge = document.getElementById("ep-note-badge");
  if (row) {
    statusBadge.textContent = row.frame_line_status || "—";
    noteBadge.textContent = row.note || "—";
  } else {
    statusBadge.textContent = "—";
    noteBadge.textContent = "—";
  }
}

function _epUpdateEnd() {
  const start = parseInt(document.getElementById("ep-start").value, 10) || 1;
  const frames = parseInt(document.getElementById("ep-frames").value, 10) || 800;
  document.getElementById("ep-end").value = start + frames - 1;
}

// ── Mode-specific UI ───────────────────────────────────────────────────────────

function _epUpdateModeUI() {
  const lockBadge = document.getElementById("ep-lock-badge");
  const setKfBtn = document.getElementById("ep-set-kf");
  const rejectBtn = document.getElementById("ep-reject");
  const addTemplateBtn = document.getElementById("ep-add-template");
  const seekEl = document.getElementById("ep-seek");

  seekEl.min = _clipStart;
  seekEl.max = _clipEnd;

  if (_mode === "clip") {
    lockBadge.style.display = "";
    lockBadge.textContent = "🔒 " + (_clipStart + 1) + "–" + (_clipEnd + 1);
    setKfBtn.style.display = "";
    rejectBtn.style.display = "";
    addTemplateBtn.style.display = "none";
    document.getElementById("ep-lock-start").checked = true;

    const isFinished = _detectionIdx !== null &&
      typeof detections !== "undefined" &&
      detections[_detectionIdx] &&
      (detections[_detectionIdx].status === "kept" || detections[_detectionIdx].status === "rejected");
    setKfBtn.disabled = isFinished;
    rejectBtn.disabled = isFinished;
    document.getElementById("ep-extract").disabled = isFinished;
  } else {
    lockBadge.style.display = "none";
    setKfBtn.style.display = "none";
    rejectBtn.style.display = "none";
    addTemplateBtn.style.display = "";
    document.getElementById("ep-lock-start").checked = false;
  }

  _epUpdateSeekHighlight();
}

// ── Extract panel init ─────────────────────────────────────────────────────────

function _epInitExtractPanel(videoPath, keyFrame1Based) {
  const start = (_mode === "clip" && keyFrame1Based !== null)
    ? Math.max(1, keyFrame1Based - 200)
    : 1;
  document.getElementById("ep-start").value = start;
  document.getElementById("ep-frames").value = 800;
  document.getElementById("ep-postfix").value = "";
  document.getElementById("ep-extract").disabled = false;
  document.getElementById("ep-warning").style.display = "none";
  _epUpdateEnd();

  const parts = videoPath.split("/");
  const filename = parts[parts.length - 1];
  const stem = filename.replace(/\.avi$/i, "");
  const parent = parts.slice(0, -1).join("/");
  const parentName = parts[parts.length - 2] || "";
  document.getElementById("ep-outdir").textContent = "…/" + parentName + "/" + stem + "/";
  document.getElementById("ep-outdir").title = parent + "/" + stem + "/";
}

// ── Apply new keyframe ─────────────────────────────────────────────────────────

function _epApplyNewKF(kf1) {
  if (_detectionIdx === null || typeof detections === "undefined") return;
  detections[_detectionIdx].frame_number = kf1;
  const kf0 = kf1 - 1;
  _keyFrame = kf0;
  _clipStart = Math.max(0, kf0 - 200);
  _clipEnd = Math.min(_frameCount - 1, kf0 + 599);

  document.getElementById("ep-lock-badge").textContent =
    "🔒 " + (_clipStart + 1) + "–" + (_clipEnd + 1);

  const seekEl = document.getElementById("ep-seek");
  seekEl.min = _clipStart;
  seekEl.max = _clipEnd;
  seekEl.value = Math.max(_clipStart, Math.min(_currentFrame, _clipEnd));

  const start = Math.max(1, kf1 - 200);
  document.getElementById("ep-start").value = start;
  _epUpdateEnd();

  const nameEl = document.getElementById("card-clipname-" + _detectionIdx);
  if (nameEl) {
    const d = detections[_detectionIdx];
    const videoName = d.video_path.split("/").pop().replace(".avi", "");
    nameEl.textContent = videoName + "_" + (kf1 - 200) + "_" + (kf1 + 599) + ".avi";
  }

  _epUpdateSeekHighlight();
  if (typeof saveDetections === "function") saveDetections();
  document.getElementById("ep-warning").style.display = "none";
}
```

- [ ] **Step 4.2: Verify the page loads with no JS errors**

Start the server. The `enhanced_player.js` file now exists. Open the browser console — there should be no errors on page load. `openPlayer` is now defined globally. Clicking a detection card opens the panel and loads a frame (seek bar and frame counter should update).

Verify:
- Panel opens and shows a frame when a detection card is clicked.
- Panel shows lock badge with correct range in clip mode.
- Seek bar min/max set to clip range.
- Extract panel Start field is pre-populated to `keyFrame - 200`.
- End field auto-computes to Start + 800 - 1.
- Browse frames opens the panel in template mode (no lock badge, full video range).

- [ ] **Step 4.3: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/static/enhanced_player.js
git commit -m "feat: add enhanced_player.js scaffold — openPlayer, frame loading, playback loop, display helpers"
```

---

## Task 5: enhanced_player.js — All event handlers (controls, keyboard, zoom, frame counter)

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js` (append a `DOMContentLoaded` block)

- [ ] **Step 5.1: Append the DOMContentLoaded event handler block**

Append to `enhanced_player.js` (after the `_epApplyNewKF` function):

```javascript
// ── Event wiring ───────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {

  // Collapse
  document.getElementById("ep-collapse").addEventListener("click", () => {
    _stop();
    document.getElementById("player-panel").style.display = "none";
  });

  // Play / pause
  document.getElementById("ep-play").addEventListener("click", () => {
    if (!_videoPath) return;
    if (_playing) {
      _stop();
    } else {
      _playing = true;
      document.getElementById("ep-play").textContent = "⏸";
      _epLoop();
    }
  });

  // ⏮ jump to clip start
  document.getElementById("ep-first").addEventListener("click", () => {
    _stop(); _epLoadFrame(_clipStart);
  });

  // ⏭ jump to clip end
  document.getElementById("ep-last").addEventListener("click", () => {
    _stop(); _epLoadFrame(_clipEnd);
  });

  // ◀ back by step size
  document.getElementById("ep-back").addEventListener("click", () => {
    _stop(); _epLoadFrame(_currentFrame - _stepSize);
  });

  // ▶ single frame forward
  document.getElementById("ep-fwd").addEventListener("click", () => {
    _stop(); _epLoadFrame(_currentFrame + 1);
  });

  // Step size input
  document.getElementById("ep-step").addEventListener("change", (e) => {
    const v = parseInt(e.target.value, 10);
    _stepSize = v > 0 ? v : 1;
    e.target.value = _stepSize;
  });

  // Play-N input
  document.getElementById("ep-playn").addEventListener("change", (e) => {
    const v = parseInt(e.target.value, 10);
    _playN = v > 0 ? v : 1;
    e.target.value = _playN;
  });

  // Loop toggle
  document.getElementById("ep-loop").addEventListener("click", () => {
    _looping = !_looping;
    document.getElementById("ep-loop").classList.toggle("active", _looping);
  });

  // Seek bar
  document.getElementById("ep-seek").addEventListener("input", (e) => {
    _stop();
    _epLoadFrame(parseInt(e.target.value, 10));
  });

  // Zoom slider
  document.getElementById("ep-zoom").addEventListener("input", (e) => {
    const pct = parseInt(e.target.value, 10);
    document.getElementById("ep-zoom-pct").textContent = pct + "%";
    const img = document.getElementById("ep-frame");
    img.style.transform = "scale(" + (pct / 100) + ")";
  });

  // Frame counter — double-click to jump
  document.getElementById("ep-frame-counter").addEventListener("dblclick", () => {
    if (!_videoPath) return;
    const jump = document.getElementById("ep-frame-jump");
    jump.value = _currentFrame + 1;
    jump.min = _clipStart + 1;
    jump.max = _clipEnd + 1;
    document.getElementById("ep-frame-counter").style.display = "none";
    jump.style.display = "";
    jump.select();
  });

  const _commitJump = () => {
    const jump = document.getElementById("ep-frame-jump");
    let n1 = parseInt(jump.value, 10);
    n1 = Math.max(_clipStart + 1, Math.min(n1, _clipEnd + 1));
    jump.style.display = "none";
    document.getElementById("ep-frame-counter").style.display = "";
    _stop();
    _epLoadFrame(n1 - 1);
  };

  const _cancelJump = () => {
    document.getElementById("ep-frame-jump").style.display = "none";
    document.getElementById("ep-frame-counter").style.display = "";
  };

  document.getElementById("ep-frame-jump").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); _commitJump(); }
    else if (e.key === "Escape") { e.preventDefault(); _cancelJump(); }
  });
  document.getElementById("ep-frame-jump").addEventListener("blur", _cancelJump);

  // Keyboard navigation (when player panel is open and no text input is focused)
  document.addEventListener("keydown", (e) => {
    if (!_videoPath) return;
    if (document.getElementById("ep-frame-jump").style.display !== "none") return;
    const tag = (e.target || {}).tagName || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

    if (e.key === "ArrowLeft" && !e.ctrlKey) {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame - 1);
    } else if (e.key === "ArrowRight" && !e.ctrlKey) {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame + 1);
    } else if (e.key === "ArrowLeft" && e.ctrlKey) {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame - _stepSize);
    } else if (e.key === "ArrowRight" && e.ctrlKey) {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame + _stepSize);
    }
  });

  // Start / Frames → recalculate End
  document.getElementById("ep-start").addEventListener("input", _epUpdateEnd);
  document.getElementById("ep-frames").addEventListener("input", _epUpdateEnd);

  // Lock start checkbox — when unchecked, sync Start to current frame
  document.getElementById("ep-lock-start").addEventListener("change", (e) => {
    if (!e.target.checked && _videoPath) {
      document.getElementById("ep-start").value = _currentFrame + 1;
      _epUpdateEnd();
    }
  });

  // CSV tag navigation
  document.getElementById("ep-prev-tag").addEventListener("click", () => {
    if (!_csvRows.length) return;
    const cur1 = _currentFrame + 1;
    const row = _csvRows.find(r => r.frame_number === cur1);
    const tagVal = row && row.note ? row.note : null;
    if (!tagVal) return;
    const prev = [..._csvRows].reverse().find(r => r.frame_number < cur1 && r.note === tagVal);
    if (prev) { _stop(); _epLoadFrame(prev.frame_number - 1); }
  });

  document.getElementById("ep-next-tag").addEventListener("click", () => {
    if (!_csvRows.length) return;
    const cur1 = _currentFrame + 1;
    const row = _csvRows.find(r => r.frame_number === cur1);
    const tagVal = row && row.note ? row.note : null;
    if (!tagVal) return;
    const next = _csvRows.find(r => r.frame_number > cur1 && r.note === tagVal);
    if (next) { _stop(); _epLoadFrame(next.frame_number - 1); }
  });

  // Add to template (template mode only)
  document.getElementById("ep-add-template").addEventListener("click", async () => {
    if (!_videoPath) return;
    const frameNumber = _currentFrame + 1;
    try {
      const resp = await fetch("/clip-cutter/template/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_path: _videoPath, frame_number: frameNumber }),
      });
      if (resp.ok) {
        if (typeof loadTemplate === "function") await loadTemplate();
        setStatus("Frame " + frameNumber + " added to template");
      } else {
        const err = await resp.json().catch(() => ({ error: "unknown" }));
        setStatus("Error: " + err.error);
      }
    } catch (e) { setStatus("Network error: " + e.message); }
  });

  // Set KF (clip mode — with overlap check)
  document.getElementById("ep-set-kf").addEventListener("click", async () => {
    if (!_videoPath || _detectionIdx === null) return;
    const kf1 = _currentFrame + 1;

    let data;
    try {
      const resp = await fetch("/clip-cutter/check-keyframe-overlap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_path: _videoPath, key_frame: kf1 }),
      });
      if (!resp.ok) { setStatus("Overlap check failed"); return; }
      data = await resp.json();
    } catch (e) { setStatus("Network error: " + e.message); return; }

    if (!data.overlaps) {
      _epApplyNewKF(kf1);
      return;
    }

    const conflict = data.conflicts[0];
    const warning = document.getElementById("ep-warning");
    warning.innerHTML = "";

    const msg = document.createElement("div");
    msg.style.cssText = "color:#f85149;margin-bottom:3px;";
    msg.textContent = "⚠ Overlaps " + conflict.name + " by " + conflict.overlap_frames + " fr";

    const btns = document.createElement("div");
    btns.style.cssText = "display:flex;gap:4px;margin-top:2px;";

    const cancelBtn = document.createElement("button");
    cancelBtn.className = "player-btn";
    cancelBtn.style.fontSize = "8px";
    cancelBtn.textContent = "Cancel";
    cancelBtn.onclick = () => { warning.style.display = "none"; };

    const keepBtn = document.createElement("button");
    keepBtn.className = "player-btn ep-btn-red";
    keepBtn.style.fontSize = "8px";
    keepBtn.textContent = "Keep anyway";
    keepBtn.onclick = () => _epApplyNewKF(kf1);

    btns.appendChild(cancelBtn);
    btns.appendChild(keepBtn);
    warning.appendChild(msg);
    warning.appendChild(btns);
    warning.style.display = "";
  });

  // Extract
  document.getElementById("ep-extract").addEventListener("click", async () => {
    if (!_videoPath) return;
    const start = parseInt(document.getElementById("ep-start").value, 10);
    const keyFrame = start + 200;
    const postfix = document.getElementById("ep-postfix").value.trim();

    const body = { video_path: _videoPath, key_frame: keyFrame };
    if (postfix) body.postfix = postfix;

    try {
      const resp = await fetch("/clip-cutter/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: resp.statusText }));
        setStatus("Extract error: " + err.error);
        return;
      }
      setStatus("Clip extracted");
      if (_detectionIdx !== null && typeof detections !== "undefined" && detections[_detectionIdx]) {
        detections[_detectionIdx].status = "kept";
        const card = document.getElementById("card-" + _detectionIdx);
        if (card) {
          card.classList.add("kept");
          card.querySelectorAll("button").forEach(b => { b.disabled = true; });
        }
        if (typeof saveDetections === "function") saveDetections();
      }
      document.getElementById("ep-extract").disabled = true;
      document.getElementById("ep-set-kf").disabled = true;
      document.getElementById("ep-reject").disabled = true;
    } catch (e) { setStatus("Network error: " + e.message); }
  });

  // Reject (clip mode)
  document.getElementById("ep-reject").addEventListener("click", async () => {
    if (_detectionIdx === null || typeof detections === "undefined") return;
    detections.splice(_detectionIdx, 1);
    const card = document.getElementById("card-" + _detectionIdx);
    if (card) card.remove();
    if (typeof saveDetections === "function") saveDetections();
    _stop();
    document.getElementById("player-panel").style.display = "none";
  });

}); // end DOMContentLoaded
```

- [ ] **Step 5.2: Manual smoke test — template mode**

Start the server. Select a video. Click "Browse frames":
- Panel opens. Full video seek bar (no lock badge, no lock highlight, no Set KF / Reject buttons).
- "Add to template" button visible.
- ← / → keys advance frames.
- Ctrl+← / Ctrl+→ skip by step-size (default 10).
- ⏮/⏭ jump to start/end of video.
- ◀/▶ (single-frame buttons) step one frame.
- Step input changes step size.
- N= input: set to 3, press play — skips 3 frames per timer tick.
- Loop toggle changes active state.
- Zoom slider scales the frame image.
- Double-click frame counter → type a frame number → Enter → jumps to it.
- Escape cancels the jump input.
- Lock checkbox unchecked → Start tracks playback.
- Lock checkbox checked → Start stays fixed.
- Collapse button hides the panel.

- [ ] **Step 5.3: Manual smoke test — clip mode**

Click a detection card:
- Panel opens. Lock badge shows clip range. Seek bar restricted to clip range.
- Set KF button visible. Reject button visible.
- Seek bar shows blue highlight over clip range.
- Nav clamped to clip range.
- Double-click frame counter → committed value clamped to clip range.
- Click Set KF → if no overlap, KF moves, lock badge updates, extract Start/End update.
- Click Set KF on a frame that overlaps an existing clip → warning appears with Cancel / Keep anyway.
- Extract: fills Start correctly, POSTs to `/clip-cutter/extract`, marks card as kept, disables buttons.
- Reject: removes detection from array, removes card from DOM, hides panel.
- Open clip mode then open template mode → no stale state (lock badge hidden, buttons correct).

- [ ] **Step 5.4: Delete player.js**

```bash
rm /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter/static/player.js
```

- [ ] **Step 5.5: Run backend tests to confirm no regressions**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 5.6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/static/enhanced_player.js
git rm clip-cutter/static/player.js
git commit -m "feat: complete enhanced_player.js — all controls, keyboard nav, zoom, tag strip, extract panel, reject; delete player.js"
```

---

## Self-Review Checklist

After all tasks are complete, verify against the spec:

- [ ] `openPlayer({mode, videoPath, keyFrame1Based, detectionIdx, csvPath})` — public API matches spec
- [ ] clip mode: lock badge, clamped seek bar, blue range highlight, Set KF, Reject visible ✓
- [ ] template mode: no lock badge, no Set KF/Reject, "Add to template" visible, full-video seek ✓
- [ ] step-size nav (◀/▶ by step, Ctrl+← / Ctrl+→) ✓
- [ ] ⏮/⏭ jump to clip start/end ✓
- [ ] editable frame counter (double-click, Enter/Escape) ✓
- [ ] zoom 50–200% ✓
- [ ] play-every-N ✓
- [ ] status/note strip from CSV ✓
- [ ] prev/next tag nav ✓
- [ ] extract panel: Start/Frames/End/Postfix/OutDir ✓
- [ ] lock start checkbox ✓
- [ ] Set KF: updates detections[], recalculates range, updates card name, saves ✓
- [ ] overlap warning with Cancel / Keep anyway ✓
- [ ] Extract: POSTs to /extract with `key_frame = start + 200`, marks card kept ✓
- [ ] Reject: splices detections[], removes card, saves, hides panel ✓
- [ ] GET /clip-cutter/csv: returns rows, 404 missing, 403 path-jail ✓
- [ ] `player.js` deleted ✓
- [ ] `_tp` block removed from clip_cutter.js ✓
- [ ] `#template-player-panel` removed from HTML ✓

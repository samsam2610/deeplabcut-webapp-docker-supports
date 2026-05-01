# DLC-3D Port Clip-Cutter Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring DLC-3D Frame Extractor's video controller to feature-parity with clip-cutter / video-annotator: CSV companion auto-load, status/note timeline strips with cursor, chip-based instance navigation, full playback controls (forward/backward, step presets, Play×, loop), and hover-gated keyboard shortcuts.

**Architecture:** Five sequential tasks. Task 1 adds a `/csv` backend endpoint that mirrors `/annotate/csv` but uses DLC-3D's existing `_resolve_video_path` security helper. Task 2 adds a client-side CSV loader plus the timeline canvas strips (data canvas + cursor canvas) that visualize the parsed rows. Task 3 wires color chips with prev/next instance navigation and canvas-click jumping. Task 4 replaces the minimal play/step controls with the full clip-cutter button row (forward/back play, ‹/›, step presets, Play×, loop). Task 5 adds hover-gated keyboard shortcuts. Each task ends with a manual visual check; final task runs the existing E2E suite.

**Tech Stack:** Python 3.9 (Flask blueprint), `csv.DictReader` for CSV parsing, ES6 modules (`enhanced_player.js`), HTML5 canvas, CSS flex layout, Docker Compose for build/test.

---

## File Map

| File | What changes |
|------|-------------|
| `dlc-3D/src/dlc_3d_bp/routes.py` | Task 1: add `csv` import + `/csv` route. |
| `dlc-3D/tests/test_core.py` | Task 1: 4 new tests for `/csv` endpoint. |
| `dlc-3D/src/templates/partials/card_3d_extract.html` | Task 2: timeline strips after seek slider. Task 4: replace `.fe-controls` row. |
| `dlc-3D/src/static/dlc_3d.css` | Task 2: chip / strip / canvas styles. Task 4: control separators + active states. |
| `dlc-3D/src/static/enhanced_player.js` | Task 2: CSV load + canvas draw. Task 3: chips + nav. Task 4: playback controls. Task 5: keyboard shortcuts. |

---

## Task 1: Backend `/csv` endpoint + tests

Add a `GET /dlc-3d/csv?video=<path>` route that finds the same-stem `.csv` next to the video, parses it with `csv.DictReader`, filters out rows where both `frame_line_status` is `"0"` (or empty) and `note` is empty, sorts by `frame_number`, and returns `{rows, csv_path, csv_exists}`. Reuses the project's existing `_resolve_video_path` helper to ensure the path stays under `/user-data/` (or the project, if the project context is set).

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/routes.py` (add `csv` import + new route)
- Modify: `dlc-3D/tests/test_core.py` (4 new tests)

- [ ] **Step 1: Write the first failing test (existing CSV with rows)**

In `dlc-3D/tests/test_core.py`, add at the end of the file:

```python
# ── /csv endpoint ─────────────────────────────────────────────────────────────

def test_csv_route_returns_rows_when_csv_exists(tmp_path, monkeypatch):
    from flask import Flask
    from dlc_3d_bp import routes
    import config

    monkeypatch.setattr(config, "USER_DATA_ROOTS", [tmp_path])
    monkeypatch.setattr(routes, "_USER_DATA_ROOT", str(tmp_path))

    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    video = videos_dir / "surv1_cam0_20260123_121732_0.avi"
    video.write_bytes(b"")
    csv_file = videos_dir / "surv1_cam0_20260123_121732_0.csv"
    csv_file.write_text(
        "timestamp,frame_number,frame_line_status,note\n"
        "0.000,1,1,start\n"
        "0.033,2,2,\n"
        "0.067,3,0,\n"
        "0.100,4,1,end\n"
    )

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    client = app.test_client()

    resp = client.get(f"/dlc-3d/csv?video={video}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["csv_exists"] is True
    assert data["csv_path"].endswith(".csv")
    fns = [r["frame_number"] for r in data["rows"]]
    assert fns == [1, 2, 4]
    assert data["rows"][0]["note"] == "start"
    assert data["rows"][0]["frame_line_status"] == "1"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py::test_csv_route_returns_rows_when_csv_exists -v
```

Expected: FAIL with `404 Not Found` (route does not exist yet).

- [ ] **Step 3: Add `csv` import and the `/csv` route to routes.py**

In `dlc-3D/src/dlc_3d_bp/routes.py`, find the imports block at the top:

```python
from __future__ import annotations

import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
```

Add `import csv` after `import json`:

```python
from __future__ import annotations

import csv
import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
```

Then add the new route at the end of the file (after the last existing route):

```python
@bp.route("/csv")
def csv_route():
    """Return CSV annotation rows for the same-stem .csv next to the given video.

    Format: {"rows": [...], "csv_path": str, "csv_exists": bool}
    Each row: {timestamp, frame_number, frame_line_status, note}.
    Skips rows where status is empty/"0" AND note is empty.
    """
    video_path = request.args.get("video", "").strip()
    if not video_path:
        return jsonify({"error": "video required"}), 400

    with _state_lock:
        proj = _active_project
    resolved = _resolve_video_path(video_path, proj or _USER_DATA_ROOT)
    if resolved is None:
        return jsonify({"error": "invalid path"}), 400

    csv_path = resolved.with_suffix(".csv")
    if not csv_path.is_file():
        return jsonify({"rows": [], "csv_path": str(csv_path), "csv_exists": False})

    rows = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, skipinitialspace=True)
            if reader.fieldnames:
                reader.fieldnames = [n.strip() for n in reader.fieldnames]
            for row in reader:
                row = {k.strip() if k else k: v for k, v in row.items()}
                status = (row.get("frame_line_status") or "").strip()
                note   = (row.get("note") or "").strip()
                if not note and (not status or status == "0"):
                    continue
                try:
                    fn = int(float(row.get("frame_number", 0)))
                except (ValueError, TypeError):
                    fn = 0
                rows.append({
                    "timestamp":         (row.get("timestamp") or "").strip(),
                    "frame_number":      fn,
                    "frame_line_status": status,
                    "note":              note,
                })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    rows.sort(key=lambda r: r["frame_number"])
    return jsonify({"rows": rows, "csv_path": str(csv_path), "csv_exists": True})
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_core.py::test_csv_route_returns_rows_when_csv_exists -v
```

Expected: PASS.

- [ ] **Step 5: Add the remaining 3 tests**

Append to `dlc-3D/tests/test_core.py`:

```python
def test_csv_route_skips_empty_rows(tmp_path, monkeypatch):
    from flask import Flask
    from dlc_3d_bp import routes
    import config

    monkeypatch.setattr(config, "USER_DATA_ROOTS", [tmp_path])
    monkeypatch.setattr(routes, "_USER_DATA_ROOT", str(tmp_path))

    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    video = videos_dir / "rec1_cam0_20260201_080000_0.avi"
    video.write_bytes(b"")
    (videos_dir / "rec1_cam0_20260201_080000_0.csv").write_text(
        "timestamp,frame_number,frame_line_status,note\n"
        "0.0,1,0,\n"
        "0.0,2,0,\n"
        "0.0,3,2,important\n"
    )

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    client = app.test_client()

    resp = client.get(f"/dlc-3d/csv?video={video}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["csv_exists"] is True
    assert len(data["rows"]) == 1
    assert data["rows"][0]["frame_number"] == 3


def test_csv_route_returns_csv_exists_false_when_missing(tmp_path, monkeypatch):
    from flask import Flask
    from dlc_3d_bp import routes
    import config

    monkeypatch.setattr(config, "USER_DATA_ROOTS", [tmp_path])
    monkeypatch.setattr(routes, "_USER_DATA_ROOT", str(tmp_path))

    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    video = videos_dir / "rec2_cam0_20260301_080000_0.avi"
    video.write_bytes(b"")

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    client = app.test_client()

    resp = client.get(f"/dlc-3d/csv?video={video}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["csv_exists"] is False
    assert data["rows"] == []
    assert data["csv_path"].endswith(".csv")


def test_csv_route_rejects_path_outside_user_data(tmp_path, monkeypatch):
    from flask import Flask
    from dlc_3d_bp import routes
    import config

    monkeypatch.setattr(config, "USER_DATA_ROOTS", [tmp_path])
    monkeypatch.setattr(routes, "_USER_DATA_ROOT", str(tmp_path))

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    client = app.test_client()

    resp = client.get("/dlc-3d/csv?video=/etc/passwd")
    assert resp.status_code == 400
```

- [ ] **Step 6: Run all CSV tests**

```bash
python -m pytest tests/test_core.py -v -k csv_route
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/routes.py dlc-3D/tests/test_core.py
git commit -m "feat: add /dlc-3d/csv endpoint serving sidecar annotation rows"
```

---

## Task 2: Frontend CSV load + timeline canvas strips

Add client-side state for parsed CSV rows + color maps. Create two timeline strips (status + note) below the seek slider — each strip is a header row (label + prev/next + chips container) plus a data canvas plus a cursor canvas. CSV is fetched in `openPlayer()`. Strips appear only if their column has any non-empty values.

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_3d_extract.html`
- Modify: `dlc-3D/src/static/dlc_3d.css`
- Modify: `dlc-3D/src/static/enhanced_player.js`

- [ ] **Step 1: Add timeline strip HTML after the seek slider**

In `dlc-3D/src/templates/partials/card_3d_extract.html`, find the seek slider:

```html
        <!-- Seek slider -->
        <input type="range" id="ep-seek" class="fe-seek" min="0" max="0" value="0">
```

Immediately below it, insert:

```html
        <!-- Status timeline -->
        <div id="ep-status-bar-wrap" style="display:none">
          <div class="ep-bar-header">
            <span class="ep-strip-label">Status</span>
            <button class="btn-sm ep-strip-nav" id="ep-status-prev" disabled title="Previous (active chip)">◀</button>
            <button class="btn-sm ep-strip-nav" id="ep-status-next" disabled title="Next (active chip)">▶</button>
            <div id="ep-status-chips" class="ep-chip-row"></div>
          </div>
          <canvas id="ep-status-canvas" height="10"></canvas>
          <canvas id="ep-status-cursor" height="6"></canvas>
        </div>

        <!-- Note timeline -->
        <div id="ep-note-bar-wrap" style="display:none">
          <div class="ep-bar-header">
            <span class="ep-strip-label">Note</span>
            <button class="btn-sm ep-strip-nav" id="ep-note-prev" disabled title="Previous (active chip)">◀</button>
            <button class="btn-sm ep-strip-nav" id="ep-note-next" disabled title="Next (active chip)">▶</button>
            <div id="ep-note-chips" class="ep-chip-row"></div>
          </div>
          <canvas id="ep-note-canvas" height="10"></canvas>
          <canvas id="ep-note-cursor" height="6"></canvas>
        </div>
```

- [ ] **Step 2: Add chip / strip / canvas styles to CSS**

In `dlc-3D/src/static/dlc_3d.css`, append at the end of the file:

```css
/* ── Timeline strips (status + note) ── */
#dlc-3d-extract-card .ep-bar-header {
  display: flex; align-items: center; gap: .35rem;
  font-size: .72rem; color: var(--text-dim);
  margin: .25rem 0 .15rem 0;
}
#dlc-3d-extract-card .ep-strip-label { flex-shrink: 0; min-width: 3rem; }
#dlc-3d-extract-card .ep-strip-nav  { padding: 1px 5px; font-size: 9px; }
#dlc-3d-extract-card .ep-chip-row {
  display: flex; flex-wrap: wrap; gap: 3px;
  flex: 1; min-width: 0;
}
#dlc-3d-extract-card .ep-chip {
  font-size: 10px; padding: 1px 6px; border-radius: 3px;
  border: 1px solid transparent; cursor: pointer;
  color: #0d1117; font-family: var(--mono);
}
#dlc-3d-extract-card .ep-chip.active {
  outline: 2px solid var(--accent); outline-offset: 1px;
}
#dlc-3d-extract-card #ep-status-canvas,
#dlc-3d-extract-card #ep-note-canvas,
#dlc-3d-extract-card #ep-status-cursor,
#dlc-3d-extract-card #ep-note-cursor {
  width: 100%; display: block;
}
```

- [ ] **Step 3: Add CSV-related module state to enhanced_player.js**

In `dlc-3D/src/static/enhanced_player.js`, find the existing module state block near the top (around line 6):

```javascript
const _EP_FPS = 15;

let _videoPath     = null;
let _frameCount    = 0;
let _currentFrame  = 0;
let _stepSize      = 10;
let _playing       = false;
let _playDir       = 1;
let _busy          = false;
let _timerId       = null;
let _syncCamEnabled   = false;
let _siblingVideoPath = null;
```

Add the CSV state after `_siblingVideoPath`:

```javascript
const _EP_FPS = 15;

let _videoPath     = null;
let _frameCount    = 0;
let _currentFrame  = 0;
let _stepSize      = 10;
let _playing       = false;
let _playDir       = 1;
let _busy          = false;
let _timerId       = null;
let _syncCamEnabled   = false;
let _siblingVideoPath = null;

let _csvRows           = [];
let _epStatusColorMap  = {};
let _epNoteColorMap    = {};
let _epActiveStatus    = new Set();
let _epActiveNote      = new Set();
let _epActiveChip      = null;       // { type: "status"|"note", val: string }

const _EP_TAG_PALETTE  = [
  "#58a6ff", "#3fb950", "#f0c040", "#f85149",
  "#d2a8ff", "#ffa657", "#79c0ff", "#56d364",
];
```

- [ ] **Step 4: Add `_epLoadCsv` helper**

In `dlc-3D/src/static/enhanced_player.js`, add this helper somewhere above `openPlayer` (e.g. just before the `// ── Public API` comment block or right after the state declarations):

```javascript
async function _epLoadCsv(videoPath) {
  _csvRows = [];
  _epStatusColorMap = {};
  _epNoteColorMap   = {};
  _epActiveStatus.clear();
  _epActiveNote.clear();
  _epActiveChip = null;
  try {
    const resp = await fetch(`/dlc-3d/csv?video=${encodeURIComponent(videoPath)}`);
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data.csv_exists) return;
    _csvRows = data.rows || [];
    const statusVals = [...new Set(_csvRows.map(r => r.frame_line_status).filter(v => v && v !== "0"))];
    const noteVals   = [...new Set(_csvRows.map(r => r.note).filter(v => v))];
    statusVals.forEach((v, i) => { _epStatusColorMap[v] = _EP_TAG_PALETTE[i % _EP_TAG_PALETTE.length]; });
    noteVals  .forEach((v, i) => { _epNoteColorMap[v]   = _EP_TAG_PALETTE[i % _EP_TAG_PALETTE.length]; });
  } catch (e) {
    console.warn("[enhanced_player] CSV load failed:", e.message);
  }
}
```

- [ ] **Step 5: Add canvas draw helpers + visibility helper**

Add these functions after `_epLoadCsv`:

```javascript
function _epDrawTagCanvas(canvas, rows, field, activeSet, colorMap) {
  if (!canvas) return;
  const total = Math.max(_frameCount, 1);
  const W = Math.round(canvas.getBoundingClientRect().width) || canvas.clientWidth || 600;
  canvas.width = W;
  const H = canvas.height || 10;
  const ctx = canvas.getContext("2d");
  const minW = Math.max(1, Math.round(W / total));
  ctx.clearRect(0, 0, W, H);
  if (!activeSet || activeSet.size === 0) return;
  rows.forEach(row => {
    const val = row[field];
    if (!val || (field === "frame_line_status" && val === "0")) return;
    if (!activeSet.has(val)) return;
    ctx.fillStyle = colorMap[val] || "#888";
    const x = Math.round(((row.frame_number - 1) / Math.max(total - 1, 1)) * W);
    ctx.fillRect(x, 0, minW, H);
  });
}

function _epDrawCursor(canvas) {
  if (!canvas) return;
  const W = Math.round(canvas.getBoundingClientRect().width) || canvas.clientWidth || 600;
  canvas.width = W;
  const H = canvas.height || 6;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, W, H);
  if (_frameCount <= 1) return;
  const x = Math.round((_currentFrame / (_frameCount - 1)) * W);
  ctx.fillStyle = "#58a6ff";
  ctx.beginPath();
  ctx.moveTo(x - 4, 0);
  ctx.lineTo(x + 4, 0);
  ctx.lineTo(x, H);
  ctx.closePath();
  ctx.fill();
}

function _epRedrawAllCanvases() {
  _epDrawTagCanvas(document.getElementById("ep-status-canvas"), _csvRows, "frame_line_status", _epActiveStatus, _epStatusColorMap);
  _epDrawTagCanvas(document.getElementById("ep-note-canvas"),   _csvRows, "note",              _epActiveNote,   _epNoteColorMap);
  _epDrawCursor(document.getElementById("ep-status-cursor"));
  _epDrawCursor(document.getElementById("ep-note-cursor"));
}

function _epUpdateBarsVisibility() {
  const hasStatus = _csvRows.some(r => r.frame_line_status && r.frame_line_status !== "0");
  const hasNote   = _csvRows.some(r => r.note);
  const sw = document.getElementById("ep-status-bar-wrap");
  const nw = document.getElementById("ep-note-bar-wrap");
  if (sw) sw.style.display = hasStatus ? "" : "none";
  if (nw) nw.style.display = hasNote   ? "" : "none";
}
```

- [ ] **Step 6: Wire `_epLoadCsv` into `openPlayer()`**

In `enhanced_player.js`, find this block in `openPlayer()` (around line 55, right before `_epUpdateSyncCamUI()`):

```javascript
  _frameCount = frameCount;

  const seekEl = document.getElementById("ep-seek");
  if (seekEl) { seekEl.min = 0; seekEl.max = frameCount - 1; seekEl.value = 0; }

  _epUpdateSyncCamUI();
```

Replace with:

```javascript
  _frameCount = frameCount;

  const seekEl = document.getElementById("ep-seek");
  if (seekEl) { seekEl.min = 0; seekEl.max = frameCount - 1; seekEl.value = 0; }

  await _epLoadCsv(videoPath);
  _epUpdateBarsVisibility();
  _epRedrawAllCanvases();

  _epUpdateSyncCamUI();
```

- [ ] **Step 7: Redraw cursor canvases after every frame load**

Find `_epUpdateDisplay()` in `enhanced_player.js`:

```javascript
function _epUpdateDisplay() {
  const numEl   = document.getElementById("ep-frame-num");
  const totalEl = document.getElementById("ep-frame-total");
  const seekEl  = document.getElementById("ep-seek");
  if (numEl)   numEl.textContent   = _currentFrame + 1;
  if (totalEl) totalEl.textContent = _frameCount;
  if (seekEl)  seekEl.value        = _currentFrame;
}
```

Replace with:

```javascript
function _epUpdateDisplay() {
  const numEl   = document.getElementById("ep-frame-num");
  const totalEl = document.getElementById("ep-frame-total");
  const seekEl  = document.getElementById("ep-seek");
  if (numEl)   numEl.textContent   = _currentFrame + 1;
  if (totalEl) totalEl.textContent = _frameCount;
  if (seekEl)  seekEl.value        = _currentFrame;
  _epDrawCursor(document.getElementById("ep-status-cursor"));
  _epDrawCursor(document.getElementById("ep-note-cursor"));
}
```

- [ ] **Step 8: Add resize listener for canvas redraws**

In `enhanced_player.js`, inside `DOMContentLoaded` (find `document.addEventListener("DOMContentLoaded", () => {` around line 187), add at the very start of the handler body:

```javascript
  let _resizeRaf = null;
  window.addEventListener("resize", () => {
    if (_resizeRaf) cancelAnimationFrame(_resizeRaf);
    _resizeRaf = requestAnimationFrame(() => {
      _epRedrawAllCanvases();
      _resizeRaf = null;
    });
  });
```

- [ ] **Step 9: Build, restart, and visually verify**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d
docker compose up -d dlc-3d
```

Open the extractor with a video that has a sidecar `.csv` containing both status and note values. Expected: two strips appear below the seek bar; canvases are blank (no chips active yet); cursor triangles render at the current frame on both strips. Open a video without a CSV: both strips stay hidden.

- [ ] **Step 10: Commit**

```bash
git add dlc-3D/src/templates/partials/card_3d_extract.html \
        dlc-3D/src/static/dlc_3d.css \
        dlc-3D/src/static/enhanced_player.js
git commit -m "feat: add CSV companion auto-load and timeline canvas strips"
```

---

## Task 3: Tag chips + instance navigation

Build chip buttons (one per unique value) with assigned palette colors. Clicking toggles the chip as active and adds/removes its value from the active set, redrawing the canvas. The strip's prev/next ◀ ▶ buttons jump to the previous/next CSV row matching the active chip. Canvas click jumps to the clicked frame.

**Files:**
- Modify: `dlc-3D/src/static/enhanced_player.js`

- [ ] **Step 1: Add chip-building helpers**

In `dlc-3D/src/static/enhanced_player.js`, add these functions after `_epUpdateBarsVisibility`:

```javascript
function _epRebuildChips() {
  const statusRow = document.getElementById("ep-status-chips");
  const noteRow   = document.getElementById("ep-note-chips");
  if (statusRow) statusRow.innerHTML = "";
  if (noteRow)   noteRow.innerHTML   = "";

  const buildChip = (type, val, color, container, activeSet) => {
    const btn = document.createElement("button");
    btn.className = "ep-chip";
    btn.dataset.type = type;
    btn.dataset.val  = val;
    btn.style.background = color;
    btn.textContent = val;
    btn.addEventListener("click", () => _epOnChipClick(type, val, btn, activeSet));
    container.appendChild(btn);
  };

  if (statusRow) {
    Object.entries(_epStatusColorMap).forEach(([val, color]) =>
      buildChip("status", val, color, statusRow, _epActiveStatus));
  }
  if (noteRow) {
    Object.entries(_epNoteColorMap).forEach(([val, color]) =>
      buildChip("note", val, color, noteRow, _epActiveNote));
  }
  _epUpdateNavButtonsEnabled();
}

function _epOnChipClick(type, val, btnEl, activeSet) {
  const wasActive = !!(_epActiveChip && _epActiveChip.type === type && _epActiveChip.val === val);
  if (wasActive) {
    _epActiveChip = null;
    activeSet.delete(val);
    btnEl.classList.remove("active");
  } else {
    if (_epActiveChip) {
      const otherSet = _epActiveChip.type === "status" ? _epActiveStatus : _epActiveNote;
      otherSet.delete(_epActiveChip.val);
      const prev = document.querySelector(`.ep-chip[data-type="${_epActiveChip.type}"][data-val="${CSS.escape(_epActiveChip.val)}"]`);
      if (prev) prev.classList.remove("active");
    }
    _epActiveChip = { type, val };
    activeSet.add(val);
    btnEl.classList.add("active");
  }
  _epUpdateNavButtonsEnabled();
  _epRedrawAllCanvases();
}

function _epUpdateNavButtonsEnabled() {
  const enabled = !!_epActiveChip;
  ["ep-status-prev", "ep-status-next", "ep-note-prev", "ep-note-next"].forEach(id => {
    const b = document.getElementById(id);
    if (b) b.disabled = !enabled;
  });
}

function _epNavByChip(dir) {
  if (!_epActiveChip || !_csvRows.length) return;
  const { type, val } = _epActiveChip;
  const field = type === "status" ? "frame_line_status" : "note";
  const cur1  = _currentFrame + 1;
  const matches = _csvRows.filter(r => r[field] === val);
  let target = null;
  if (dir < 0) {
    target = [...matches].filter(r => Number(r.frame_number) < cur1)
      .sort((a, b) => b.frame_number - a.frame_number)[0];
  } else {
    target = matches.filter(r => Number(r.frame_number) > cur1)
      .sort((a, b) => a.frame_number - b.frame_number)[0];
  }
  if (target) { _stop(); _epLoadFrame(Number(target.frame_number) - 1); }
}
```

- [ ] **Step 2: Call `_epRebuildChips` in `openPlayer()`**

In `enhanced_player.js`, find this block in `openPlayer()` (added in Task 2):

```javascript
  await _epLoadCsv(videoPath);
  _epUpdateBarsVisibility();
  _epRedrawAllCanvases();
```

Replace with:

```javascript
  await _epLoadCsv(videoPath);
  _epRebuildChips();
  _epUpdateBarsVisibility();
  _epRedrawAllCanvases();
```

- [ ] **Step 3: Wire prev/next button click handlers**

In `enhanced_player.js`, inside `DOMContentLoaded`, add (anywhere in the handler body):

```javascript
  ["ep-status-prev", "ep-note-prev"].forEach(id => {
    document.getElementById(id)?.addEventListener("click", () => _epNavByChip(-1));
  });
  ["ep-status-next", "ep-note-next"].forEach(id => {
    document.getElementById(id)?.addEventListener("click", () => _epNavByChip(+1));
  });
```

- [ ] **Step 4: Wire canvas-click → jump-to-frame**

In `enhanced_player.js`, add a helper above `DOMContentLoaded`:

```javascript
function _epWireCanvasClick(canvasId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  canvas.addEventListener("click", (e) => {
    if (_frameCount <= 1) return;
    const rect = canvas.getBoundingClientRect();
    const x    = e.clientX - rect.left;
    const frac = Math.max(0, Math.min(1, x / rect.width));
    const target = Math.round(frac * (_frameCount - 1));
    _stop(); _epLoadFrame(target);
  });
}
```

Inside `DOMContentLoaded`, register both canvases:

```javascript
  _epWireCanvasClick("ep-status-canvas");
  _epWireCanvasClick("ep-note-canvas");
```

- [ ] **Step 5: Build, restart, and visually verify**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d
docker compose up -d dlc-3d
```

Open extractor with a CSV that has multiple distinct status and note values. Expected:
- Each strip's header shows colored chip buttons (one per unique value)
- ◀ ▶ buttons disabled until a chip is clicked
- Click a chip → it gets an outline; data canvas shows colored markers only for that value; ◀ ▶ enable
- Click ◀ → jumps to the most recent frame before current with that value; cursor triangle moves
- Click ▶ → jumps to the next frame after current
- Click another chip → previous chip deactivates; new value's markers render
- Click the same chip again → deactivates; canvas clears; ◀ ▶ disable
- Click anywhere on the data canvas → jumps to that frame proportionally

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/static/enhanced_player.js
git commit -m "feat: add tag chips and instance navigation for timeline strips"
```

---

## Task 4: Playback controls (forward/backward + step + N inputs + loop)

Replace the current minimal control row (⏮ ◀◀ ▶ ▶▶ ⏭ + step input) with the full clip-cutter layout: separate play-forward / play-backward buttons that toggle pause, single-frame steppers (‹ ›), three editable step preset inputs, a Play× input controlling skip-per-tick, and a loop toggle button.

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_3d_extract.html`
- Modify: `dlc-3D/src/static/dlc_3d.css`
- Modify: `dlc-3D/src/static/enhanced_player.js`

- [ ] **Step 1: Replace `.fe-controls` HTML**

In `dlc-3D/src/templates/partials/card_3d_extract.html`, find the existing `.fe-controls` block (between the dual-camera display and the seek slider):

```html
        <!-- Controls row -->
        <div class="fe-controls">
          <button id="ep-skip-start" class="btn-sm fe-ctrl-btn" title="Jump to start">⏮</button>
          <button id="ep-step-back"  class="btn-sm fe-ctrl-btn" title="Step back N frames">◀◀</button>
          <button id="ep-play"       class="btn-sm fe-ctrl-btn" title="Play / pause">▶</button>
          <button id="ep-step-fwd"   class="btn-sm fe-ctrl-btn" title="Step forward N frames">▶▶</button>
          <button id="ep-skip-end"   class="btn-sm fe-ctrl-btn" title="Jump to end">⏭</button>
          <input type="number" id="ep-step" value="10" min="1" max="9999"
            title="Skip N frames"
            style="width:4rem;text-align:center;font-family:var(--mono);font-size:.78rem;
                   padding:.18rem .3rem;background:var(--surface-2);border:1px solid var(--border);
                   border-radius:5px;color:var(--text)">
          <span class="fe-frame-counter">Frame <span id="ep-frame-num">—</span> / <span id="ep-frame-total">—</span></span>
        </div>
```

Replace with:

```html
        <!-- Controls row -->
        <div class="fe-controls">
          <button id="ep-skip-start" class="btn-sm fe-ctrl-btn" title="Jump to start">⏮</button>
          <button id="ep-back"       class="btn-sm fe-ctrl-btn" title="Back N (Shift+←)">◀◀</button>
          <button id="ep-back1"      class="btn-sm fe-ctrl-btn" title="Back 1 (←)">‹</button>
          <button id="ep-play-back"  class="btn-sm fe-ctrl-btn" title="Play backward (Shift+Space)">◀</button>
          <button id="ep-play"       class="btn-sm fe-ctrl-btn" title="Play forward (Space)">▶</button>
          <button id="ep-fwd1"       class="btn-sm fe-ctrl-btn" title="Forward 1 (→)">›</button>
          <button id="ep-fwd"        class="btn-sm fe-ctrl-btn" title="Forward N (Shift+→)">▶▶</button>
          <button id="ep-skip-end"   class="btn-sm fe-ctrl-btn" title="Jump to end">⏭</button>
          <button id="ep-loop"       class="btn-sm fe-ctrl-btn active" title="Loop playback">↻</button>

          <span class="ep-ctrl-sep">Step</span>
          <input type="number" id="ep-step" min="1" value="10" title="Step size (frames)"
                 style="width:4rem;text-align:center;font-family:var(--mono);font-size:.78rem;
                        padding:.18rem .3rem;background:var(--surface-2);border:1px solid var(--border);
                        border-radius:5px;color:var(--text)">
          <input type="number" class="ep-step-preset" data-idx="0" value="50"  title="Step preset 1"
                 style="width:3rem;text-align:center;font-family:var(--mono);font-size:.7rem;padding:.15rem;
                        background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text-dim)">
          <input type="number" class="ep-step-preset" data-idx="1" value="100" title="Step preset 2"
                 style="width:3rem;text-align:center;font-family:var(--mono);font-size:.7rem;padding:.15rem;
                        background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text-dim)">
          <input type="number" class="ep-step-preset" data-idx="2" value="200" title="Step preset 3"
                 style="width:3rem;text-align:center;font-family:var(--mono);font-size:.7rem;padding:.15rem;
                        background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text-dim)">

          <span class="ep-ctrl-sep">Play×</span>
          <input type="number" id="ep-playn" min="1" value="1" title="Play every N frames"
                 style="width:3.5rem;text-align:center;font-family:var(--mono);font-size:.78rem;
                        padding:.18rem .3rem;background:var(--surface-2);border:1px solid var(--border);
                        border-radius:5px;color:var(--text)">

          <span class="fe-frame-counter">Frame <span id="ep-frame-num">—</span> / <span id="ep-frame-total">—</span></span>
        </div>
```

Renames in this block: `ep-step-back` → `ep-back`, `ep-step-fwd` → `ep-fwd`. New additions: `ep-back1`, `ep-fwd1`, `ep-play-back`, `ep-loop`, three `.ep-step-preset` inputs, `ep-playn`.

- [ ] **Step 2: Add control-row styles to CSS**

In `dlc-3D/src/static/dlc_3d.css`, append:

```css
/* ── Playback controls ── */
#dlc-3d-extract-card .ep-ctrl-sep {
  font-size: .72rem; color: var(--text-dim); margin-left: .4rem;
}
#dlc-3d-extract-card .ep-step-preset.active {
  outline: 2px solid var(--accent); outline-offset: -1px;
}
#dlc-3d-extract-card #ep-loop.active {
  background: var(--accent); color: #0d1117;
}
```

- [ ] **Step 3: Add new module state in enhanced_player.js**

In `dlc-3D/src/static/enhanced_player.js`, find the existing module state block (already containing `_playDir`):

```javascript
let _stepSize      = 10;
let _playing       = false;
let _playDir       = 1;
let _busy          = false;
let _timerId       = null;
```

Replace with:

```javascript
let _stepSize       = 10;
let _playing        = false;
let _playDir        = 1;
let _playN          = 1;
let _looping        = true;
let _activePresetIdx = null;
let _busy           = false;
let _timerId        = null;
```

- [ ] **Step 4: Replace `_stop` to restore both play glyphs**

Find the existing `_stop` function in `enhanced_player.js`:

```javascript
function _stop() {
  if (_timerId !== null) { clearTimeout(_timerId); _timerId = null; }
  _playing = false;
  _busy    = false;
  const playBtn = document.getElementById("ep-play");
  if (playBtn) playBtn.textContent = "▶";
}
```

Replace with:

```javascript
function _stop() {
  if (_timerId !== null) { clearTimeout(_timerId); _timerId = null; }
  _playing = false;
  _busy    = false;
  const playBtn     = document.getElementById("ep-play");
  const playBackBtn = document.getElementById("ep-play-back");
  if (playBtn)     playBtn.textContent     = "▶";
  if (playBackBtn) playBackBtn.textContent = "◀";
}
```

- [ ] **Step 5: Replace `_epLoop` to support direction + skip + loop**

Find the existing `_epLoop` function:

```javascript
async function _epLoop() {
  if (!_playing) return;
  if (_busy) { _timerId = setTimeout(_epLoop, Math.round(1000 / _EP_FPS)); return; }
  let next = _currentFrame + _playDir;
  if (next >= _frameCount) next = 0;
  if (next < 0) next = _frameCount - 1;
  const t0 = performance.now();
  await _epLoadFrame(next);
  if (!_playing) return;
  const delay = Math.max(0, Math.round(1000 / _EP_FPS) - (performance.now() - t0));
  _timerId = setTimeout(_epLoop, delay);
}
```

Replace with:

```javascript
async function _epLoop() {
  if (!_playing) return;
  if (_busy) { _timerId = setTimeout(_epLoop, Math.round(1000 / _EP_FPS)); return; }
  let next = _currentFrame + (_playN * _playDir);
  if (_playDir > 0 && next >= _frameCount) {
    if (_looping) next = 0; else { _stop(); return; }
  }
  if (_playDir < 0 && next < 0) {
    if (_looping) next = _frameCount - 1; else { _stop(); return; }
  }
  const t0 = performance.now();
  await _epLoadFrame(next);
  if (!_playing) return;
  const delay = Math.max(0, Math.round(1000 / _EP_FPS) - (performance.now() - t0));
  _timerId = setTimeout(_epLoop, delay);
}
```

- [ ] **Step 6: Add `_epPlayDir` helper**

In `enhanced_player.js`, add this function right after `_epLoop`:

```javascript
function _epPlayDir(dir) {
  if (!_videoPath) return;
  if (_playing && _playDir === dir) { _stop(); return; }
  _stop();
  _playDir = dir;
  _playing = true;
  const playBtn     = document.getElementById("ep-play");
  const playBackBtn = document.getElementById("ep-play-back");
  if (playBtn)     playBtn.textContent     = dir === 1  ? "⏸" : "▶";
  if (playBackBtn) playBackBtn.textContent = dir === -1 ? "⏸" : "◀";
  _epLoop();
}
```

- [ ] **Step 7: Replace play / step button click handlers**

In `enhanced_player.js`, find the existing handler block in `DOMContentLoaded`:

```javascript
  // Play
  document.getElementById("ep-play")?.addEventListener("click", () => {
    if (!_videoPath) return;
    if (_playing) {
      _stop();
    } else {
      _playing = true;
      document.getElementById("ep-play").textContent = "⏸";
      _epLoop();
    }
  });

  // Step back / forward
  document.getElementById("ep-step-back")?.addEventListener("click", () => {
    if (!_videoPath) return;
    _stop();
    const s = parseInt(document.getElementById("ep-step")?.value || "10", 10);
    _epLoadFrame(_currentFrame - s);
  });
  document.getElementById("ep-step-fwd")?.addEventListener("click", () => {
    if (!_videoPath) return;
    _stop();
    const s = parseInt(document.getElementById("ep-step")?.value || "10", 10);
    _epLoadFrame(_currentFrame + s);
  });
```

Replace with:

```javascript
  // Play forward / backward
  document.getElementById("ep-play")?.addEventListener("click",      () => _epPlayDir(+1));
  document.getElementById("ep-play-back")?.addEventListener("click", () => _epPlayDir(-1));

  // Step ± N
  document.getElementById("ep-back")?.addEventListener("click", () => {
    if (!_videoPath) return;
    _stop();
    _epLoadFrame(_currentFrame - _stepSize);
  });
  document.getElementById("ep-fwd")?.addEventListener("click", () => {
    if (!_videoPath) return;
    _stop();
    _epLoadFrame(_currentFrame + _stepSize);
  });

  // Step ± 1
  document.getElementById("ep-back1")?.addEventListener("click", () => {
    if (!_videoPath) return;
    _stop();
    _epLoadFrame(_currentFrame - 1);
  });
  document.getElementById("ep-fwd1")?.addEventListener("click", () => {
    if (!_videoPath) return;
    _stop();
    _epLoadFrame(_currentFrame + 1);
  });
```

- [ ] **Step 8: Add loop button + step preset + Play× wiring**

In `enhanced_player.js`, inside `DOMContentLoaded`, add after the step button wiring:

```javascript
  // Loop toggle
  const loopBtn = document.getElementById("ep-loop");
  if (loopBtn) {
    loopBtn.classList.toggle("active", _looping);
    loopBtn.addEventListener("click", () => {
      _looping = !_looping;
      loopBtn.classList.toggle("active", _looping);
    });
  }

  // Step presets (radio-style + editable)
  document.querySelectorAll(".ep-step-preset").forEach(input => {
    input.addEventListener("click", () => {
      const v = Math.max(1, parseInt(input.value, 10) || 10);
      _stepSize = v;
      const stepEl = document.getElementById("ep-step");
      if (stepEl) stepEl.value = v;
      _activePresetIdx = parseInt(input.dataset.idx, 10);
      document.querySelectorAll(".ep-step-preset").forEach(el => el.classList.remove("active"));
      input.classList.add("active");
    });
    input.addEventListener("change", () => {
      if (parseInt(input.dataset.idx, 10) === _activePresetIdx) {
        const v = Math.max(1, parseInt(input.value, 10) || 10);
        _stepSize = v;
        const stepEl = document.getElementById("ep-step");
        if (stepEl) stepEl.value = v;
      }
    });
  });

  // Play× input
  document.getElementById("ep-playn")?.addEventListener("change", (e) => {
    _playN = Math.max(1, parseInt(e.target.value, 10) || 1);
  });
```

- [ ] **Step 9: Reset playback state in `openPlayer()`**

In `enhanced_player.js`, find the start of `openPlayer()`:

```javascript
export async function openPlayer(videoPath, siblingPath) {
  _stop();
  _videoPath        = videoPath;
  _siblingVideoPath = siblingPath || null;
  _syncCamEnabled   = false;
  _currentFrame     = 0;
  _stepSize         = 10;

  const stepEl = document.getElementById("ep-step");
  if (stepEl) stepEl.value = 10;
```

Replace with:

```javascript
export async function openPlayer(videoPath, siblingPath) {
  _stop();
  _videoPath        = videoPath;
  _siblingVideoPath = siblingPath || null;
  _syncCamEnabled   = false;
  _currentFrame     = 0;
  _stepSize         = 10;
  _playDir          = 1;
  _playN            = 1;
  _looping          = true;
  _activePresetIdx  = null;

  const stepEl = document.getElementById("ep-step");
  if (stepEl) stepEl.value = 10;
  const playnEl = document.getElementById("ep-playn");
  if (playnEl) playnEl.value = 1;
  const loopBtn = document.getElementById("ep-loop");
  if (loopBtn) loopBtn.classList.toggle("active", _looping);
  document.querySelectorAll(".ep-step-preset").forEach(el => el.classList.remove("active"));
```

- [ ] **Step 10: Build, restart, and visually verify**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d
docker compose up -d dlc-3d
```

Verify:
- Control row shows: ⏮ ◀◀ ‹ ◀ ▶ › ▶▶ ⏭ ↻, then Step + step input + 3 presets, then Play× input + frame counter
- Click ▶ → plays forward; button shows ⏸; click again → pauses
- Click ◀ → plays backward; ◀ shows ⏸; click again → pauses
- Click ▶ while playing backward → switches to forward
- Click ↻ → toggles loop highlight; with loop off, playback stops at boundary
- Click `‹` → frame goes back 1; `›` → forward 1
- Click `◀◀` / `▶▶` → ± step size (default 10)
- Click step preset "100" → it gets active outline, step input becomes 100, ◀◀/▶▶ now jump 100
- Edit "100" preset to "30" while it's active → step also becomes 30 immediately
- Set Play× to 5 + click ▶ → playback advances 5 frames per tick
- Load a new video → all state resets to default (step=10, Play×=1, loop on, no preset active)

- [ ] **Step 11: Commit**

```bash
git add dlc-3D/src/templates/partials/card_3d_extract.html \
        dlc-3D/src/static/dlc_3d.css \
        dlc-3D/src/static/enhanced_player.js
git commit -m "feat: full clip-cutter playback controls (forward/back, step presets, Play×, loop)"
```

---

## Task 5: Hover-gated keyboard shortcuts

Add hover-gated keyboard shortcuts: Space toggles play forward, Shift+Space toggles play backward, ←/→ step ±1, Shift+←/→ step ±N. Shortcuts only fire when the cursor is over `#cam-displays` and no text input has focus.

**Files:**
- Modify: `dlc-3D/src/static/enhanced_player.js`

- [ ] **Step 1: Add `_cursorOverViewer` state**

In `dlc-3D/src/static/enhanced_player.js`, find the module state block. After `_activePresetIdx`:

```javascript
let _stepSize       = 10;
let _playing        = false;
let _playDir        = 1;
let _playN          = 1;
let _looping        = true;
let _activePresetIdx = null;
let _busy           = false;
let _timerId        = null;
```

Add `_cursorOverViewer`:

```javascript
let _stepSize       = 10;
let _playing        = false;
let _playDir        = 1;
let _playN          = 1;
let _looping        = true;
let _activePresetIdx = null;
let _busy           = false;
let _timerId        = null;
let _cursorOverViewer = false;
```

- [ ] **Step 2: Wire mouseenter/mouseleave on #cam-displays**

In `enhanced_player.js`, inside `DOMContentLoaded`, add (anywhere in the handler body):

```javascript
  const camDispEl = document.getElementById("cam-displays");
  if (camDispEl) {
    camDispEl.addEventListener("mouseenter", () => { _cursorOverViewer = true;  });
    camDispEl.addEventListener("mouseleave", () => { _cursorOverViewer = false; });
  }
```

- [ ] **Step 3: Replace the keyboard handler**

In `enhanced_player.js`, find the existing keydown handler:

```javascript
  // Keyboard shortcuts (hover-free — active whenever no text input focused)
  document.addEventListener("keydown", (e) => {
    if (!_videoPath) return;
    const tag = (e.target || {}).tagName || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

    if (e.key === " " && !e.shiftKey) {
      e.preventDefault();
      if (_playing) { _stop(); }
```

(The handler likely continues below — replace the entire `keydown` block.)

Replace with:

```javascript
  // Keyboard shortcuts (hover-gated)
  document.addEventListener("keydown", (e) => {
    if (!_videoPath) return;
    if (!_cursorOverViewer) return;
    const tag = (e.target || {}).tagName || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

    if (e.key === " " && !e.shiftKey) { e.preventDefault(); _epPlayDir(+1); return; }
    if (e.key === " " &&  e.shiftKey) { e.preventDefault(); _epPlayDir(-1); return; }
    if (e.key === "ArrowLeft"  && !e.shiftKey) { e.preventDefault(); _stop(); _epLoadFrame(_currentFrame - 1);          return; }
    if (e.key === "ArrowRight" && !e.shiftKey) { e.preventDefault(); _stop(); _epLoadFrame(_currentFrame + 1);          return; }
    if (e.key === "ArrowLeft"  &&  e.shiftKey) { e.preventDefault(); _stop(); _epLoadFrame(_currentFrame - _stepSize);  return; }
    if (e.key === "ArrowRight" &&  e.shiftKey) { e.preventDefault(); _stop(); _epLoadFrame(_currentFrame + _stepSize);  return; }
  });
```

- [ ] **Step 4: Build, restart, and visually verify**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d
docker compose up -d dlc-3d
```

Verify:
- Hover cursor over the video viewer:
  - Press Space → play forward
  - Press Shift+Space → switches to play backward
  - Press ← → step back 1; → step forward 1
  - Press Shift+← / Shift+→ → step ± step size
- Move cursor away from the viewer + press Space → no action
- Click into the path input + press arrows → cursor moves in the input (no frame change)

- [ ] **Step 5: Run full E2E suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/e2e/ -v
```

Expected: 9 passed, 0 failed (no E2E test changes; existing tests do not depend on shortcut behavior).

- [ ] **Step 6: Run full backend test suite**

```bash
python -m pytest tests/test_core.py -v
```

Expected: 39 passed (35 existing + 4 new CSV tests from Task 1).

- [ ] **Step 7: Commit**

```bash
git add dlc-3D/src/static/enhanced_player.js
git commit -m "feat: hover-gated keyboard shortcuts (Space, Shift+Space, ←/→, Shift+←/→)"
```

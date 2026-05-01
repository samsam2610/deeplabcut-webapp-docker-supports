# DLC-3D — Port Clip-Cutter Controller — Design Spec

**Date:** 2026-04-30
**Status:** Approved

## Goal

Bring the DLC-3D Frame Extractor's video controller to feature-parity with the clip-cutter / video-annotator controllers in the main webapp:

1. **CSV companion auto-load** — when opening a video, fetch the same-stem `.csv` (recording-session sidecar). Format: `timestamp, frame_number, frame_line_status, note` — same as video-annotator.
2. **Timeline strips** — two canvas-based bars below the seek slider showing colored markers for each `frame_line_status` value and each `note` value present in the CSV; cursor canvas shows current frame.
3. **Tag chips + instance navigation** — color-coded chips for each unique value; click to make active; ◀ / ▶ buttons jump between frames matching the active chip.
4. **Playback controls** — separate play-forward / play-backward buttons, single-frame and N-frame steppers, three editable step presets, Play× input, loop toggle.
5. **Keyboard shortcuts (hover-gated)** — Space, Shift+Space, ←, →, Shift+←, Shift+→.

Reference implementations:
- `/home/sam/docker-images/deeplabcut-webapp-docker/src/static/js/annotator.js` — CSV fetch + parse pattern
- `/home/sam/docker-images/deeplabcut-webapp-docker/src/routes/annotate.py:124-163` — CSV endpoint pattern
- `/home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter/static/enhanced_player.js` — timeline canvas + chip nav + playback logic

---

## Section 1 — CSV companion auto-load

### Backend (`dlc-3D/src/dlc_3d_bp/routes.py`)

New endpoint mirroring `annotate_csv` but using DLC-3D's existing security helper:

```python
@bp.route("/csv")
def csv_route():
    video_path = request.args.get("video", "").strip()
    if not video_path:
        return jsonify({"error": "video required"}), 400

    proj = _get_project_or_none()
    resolved = _resolve_video_path(video_path, proj or "/user-data")
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

`_resolve_video_path` already enforces that absolute paths stay under `/user-data/` and relative paths stay under the project — same security as `/frame` and `/video-info`.

`_get_project_or_none()` is a small helper that returns the current project root from `_PROJECT_PATH_FILE` if set, else None — used so the endpoint works for out-of-project videos too.

**Tests** (`tests/test_core.py`):
- `test_csv_route_returns_rows_when_csv_exists` — write a CSV next to a video, GET `/csv?video=...`, assert `csv_exists=True` and rows include status + note values.
- `test_csv_route_skips_empty_rows` — rows with status `"0"` and empty note are filtered out.
- `test_csv_route_returns_csv_exists_false_when_missing` — no CSV next to video, expect `csv_exists=False`, empty rows.
- `test_csv_route_rejects_path_outside_user_data` — absolute path outside `/user-data/` returns 400.

### Frontend (`dlc-3D/src/static/enhanced_player.js`)

New module state:
```javascript
let _csvRows           = [];
let _epStatusColorMap  = {};
let _epNoteColorMap    = {};
let _epActiveStatus    = new Set();
let _epActiveNote      = new Set();
let _epActiveChip      = null;          // { type: "status"|"note", val: string }

const _EP_TAG_PALETTE  = [
  "#58a6ff", "#3fb950", "#f0c040", "#f85149",
  "#d2a8ff", "#ffa657", "#79c0ff", "#56d364",
];
```

New helper:
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

Called from `openPlayer()` after `video-info` succeeds, before `_epLoadFrame(0)`. After loading, call `_epRebuildChips()` and `_epUpdateBarsVisibility()` (Sections 2–3).

---

## Section 2 — Timeline strips below the seek slider

### HTML (`dlc-3D/src/templates/partials/card_3d_extract.html`)

Insert immediately after the `<input type="range" id="ep-seek">` element:

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

### CSS (`dlc-3D/src/static/dlc_3d.css`)

```css
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

### JS (`enhanced_player.js`)

Port the canvas drawing functions verbatim from clip-cutter:

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
  ctx.fillStyle = "var(--accent)";
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

Wire into the existing flow:
- `_epLoadFrame()` calls `_epRedrawAllCanvases()` at the end.
- `openPlayer()` after `_epLoadCsv()` calls `_epRebuildChips()` (Section 3) then `_epUpdateBarsVisibility()` then `_epRedrawAllCanvases()`.
- Add a `window.addEventListener("resize", _epRedrawAllCanvases)` once during `DOMContentLoaded` (debounced via `requestAnimationFrame`).
- Reset on new video: arrays cleared in `_epLoadCsv()`, canvases redrawn empty, both wraps hidden.

Sync-cam interaction: strips reflect primary cam's CSV only; sibling cam frame syncs by frame number unchanged.

---

## Section 3 — Tag chips + instance navigation

### JS (`enhanced_player.js`)

Build chip rows after CSV loads:

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

  Object.entries(_epStatusColorMap).forEach(([val, color]) => buildChip("status", val, color, statusRow, _epActiveStatus));
  Object.entries(_epNoteColorMap)  .forEach(([val, color]) => buildChip("note",   val, color, noteRow,   _epActiveNote));
}

function _epOnChipClick(type, val, btnEl, activeSet) {
  const wasActive = (_epActiveChip && _epActiveChip.type === type && _epActiveChip.val === val);
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
    target = [...matches].filter(r => Number(r.frame_number) < cur1).sort((a, b) => b.frame_number - a.frame_number)[0];
  } else {
    target = matches.filter(r => Number(r.frame_number) > cur1).sort((a, b) => a.frame_number - b.frame_number)[0];
  }
  if (target) { _stop(); _epLoadFrame(Number(target.frame_number) - 1); }
}
```

Wire prev/next buttons in `DOMContentLoaded` (both strips' buttons call the same nav function — same as clip-cutter):
```javascript
["ep-status-prev", "ep-note-prev"].forEach(id =>
  document.getElementById(id)?.addEventListener("click", () => _epNavByChip(-1)));
["ep-status-next", "ep-note-next"].forEach(id =>
  document.getElementById(id)?.addEventListener("click", () => _epNavByChip(+1)));
```

Canvas-click → jump-to-frame:
```javascript
function _epWireCanvasClick(canvasId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  canvas.addEventListener("click", (e) => {
    const rect = canvas.getBoundingClientRect();
    const x    = e.clientX - rect.left;
    const frac = Math.max(0, Math.min(1, x / rect.width));
    const target = Math.round(frac * (_frameCount - 1));
    _stop(); _epLoadFrame(target);
  });
}
// In DOMContentLoaded:
_epWireCanvasClick("ep-status-canvas");
_epWireCanvasClick("ep-note-canvas");
```

---

## Section 4 — Playback controls (forward/backward + step + N inputs)

### HTML (`card_3d_extract.html`)

Replace the existing `<div class="fe-controls">` block with the full layout:

```html
<div class="fe-controls">
  <button class="btn-sm fe-ctrl-btn" id="ep-skip-start" title="Jump to start">⏮</button>
  <button class="btn-sm fe-ctrl-btn" id="ep-back"       title="Back N (Shift+←)">◀◀</button>
  <button class="btn-sm fe-ctrl-btn" id="ep-back1"      title="Back 1 (←)">‹</button>
  <button class="btn-sm fe-ctrl-btn" id="ep-play-back"  title="Play backward (Shift+Space)">◀</button>
  <button class="btn-sm fe-ctrl-btn" id="ep-play"       title="Play forward (Space)">▶</button>
  <button class="btn-sm fe-ctrl-btn" id="ep-fwd1"       title="Forward 1 (→)">›</button>
  <button class="btn-sm fe-ctrl-btn" id="ep-fwd"        title="Forward N (Shift+→)">▶▶</button>
  <button class="btn-sm fe-ctrl-btn" id="ep-skip-end"   title="Jump to end">⏭</button>
  <button class="btn-sm fe-ctrl-btn" id="ep-loop"       title="Loop playback">↻</button>

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

### CSS

```css
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

### JS (`enhanced_player.js`)

Module state (additive — `_stepSize` already exists):
```javascript
let _playN          = 1;
let _playDir        = 1;     // 1 = forward, -1 = backward
let _looping        = true;
let _activePresetIdx = null;
```

Replace the existing minimal play handler with two distinct handlers:
```javascript
function _epPlayDir(dir) {
  if (!_videoPath) return;
  if (_playing && _playDir === dir) { _stop(); return; }
  _stop();
  _playDir  = dir;
  _playing  = true;
  const playBtn     = document.getElementById("ep-play");
  const playBackBtn = document.getElementById("ep-play-back");
  if (playBtn)     playBtn.textContent     = dir === 1  ? "⏸" : "▶";
  if (playBackBtn) playBackBtn.textContent = dir === -1 ? "⏸" : "◀";
  _epLoop();
}
document.getElementById("ep-play")?.addEventListener("click",      () => _epPlayDir(+1));
document.getElementById("ep-play-back")?.addEventListener("click", () => _epPlayDir(-1));
```

Update `_stop()` to restore both glyphs:
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

Replace `_epLoop()` to support direction + skip + loop:
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

Loop button:
```javascript
const loopBtn = document.getElementById("ep-loop");
if (loopBtn) {
  loopBtn.classList.toggle("active", _looping);
  loopBtn.addEventListener("click", () => {
    _looping = !_looping;
    loopBtn.classList.toggle("active", _looping);
  });
}
```

Single-frame steppers:
```javascript
document.getElementById("ep-back1")?.addEventListener("click", () => { if (_videoPath) { _stop(); _epLoadFrame(_currentFrame - 1); } });
document.getElementById("ep-fwd1") ?.addEventListener("click", () => { if (_videoPath) { _stop(); _epLoadFrame(_currentFrame + 1); } });
```
(Existing `ep-back` / `ep-fwd` already do `± _stepSize` — leave unchanged.)

Step presets (radio-style + editable):
```javascript
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
```

Play× input:
```javascript
document.getElementById("ep-playn")?.addEventListener("change", (e) => {
  _playN = Math.max(1, parseInt(e.target.value, 10) || 1);
});
```

`openPlayer()` reset additions: `_playDir = 1; _looping = true; _playN = 1; _activePresetIdx = null;` and reset the corresponding DOM controls.

---

## Section 5 — Keyboard shortcuts (hover-gated)

### JS (`enhanced_player.js`)

New module state: `let _cursorOverViewer = false;`

In `DOMContentLoaded`:
```javascript
const camDispEl = document.getElementById("cam-displays");
if (camDispEl) {
  camDispEl.addEventListener("mouseenter", () => { _cursorOverViewer = true;  });
  camDispEl.addEventListener("mouseleave", () => { _cursorOverViewer = false; });
}
```

Replace the current minimal keydown handler with the full hover-gated map:
```javascript
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

(Replaces the existing `keydown` handler entirely — no other shortcuts in DLC-3D currently.)

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dlc-3D/src/dlc_3d_bp/routes.py` (add `/csv` endpoint + `_get_project_or_none`) |
| Modify | `dlc-3D/src/templates/partials/card_3d_extract.html` (timeline strips + control row replacement) |
| Modify | `dlc-3D/src/static/dlc_3d.css` (chip / strip / control styles) |
| Modify | `dlc-3D/src/static/enhanced_player.js` (CSV load, canvases, chips, playback, shortcuts) |
| Modify | `dlc-3D/tests/test_core.py` (4 new tests for `/csv` endpoint) |

---

## Testing

Backend unit tests (pytest):
1. `test_csv_route_returns_rows_when_csv_exists`
2. `test_csv_route_skips_empty_rows`
3. `test_csv_route_returns_csv_exists_false_when_missing`
4. `test_csv_route_rejects_path_outside_user_data`

Build + manual verification:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d && docker compose up -d dlc-3d
```
- Open extractor with a video that has a sidecar CSV → status + note strips appear with colored chips; cursor triangle tracks current frame
- Click a chip → it gets an outline; canvas shows only matching markers; ◀ ▶ buttons enable
- Click ◀ / ▶ → jumps to prev / next frame with that value; sibling cam syncs
- Click on the data canvas → jumps to that frame
- Open a video without a CSV → both strips stay hidden
- Hover over viewer + press Space → plays forward; Shift+Space → plays backward
- ← / → step ±1 frame; Shift+← / Shift+→ step ±N frames
- Click step preset → it gets active outline, step input reflects value, Shift+arrow uses that value
- Play× = 5 → playback advances 5 frames per tick
- Loop button toggle → playback wraps at boundary when on, stops when off
- E2E suite: existing 9 tests still pass

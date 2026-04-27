# Player UI Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add six UI improvements to the clip-cutter player: jump-to-keyframe button, snappier video switching via cache, canvas tag timelines (status + note), keyframe canvas overlay with navigation, collapsible sidebar and browser section, and resizable sidebar.

**Architecture:** All changes are frontend-only across three files: `clip_cutter.html` (HTML + CSS), `enhanced_player.js` (player features 1–4), `clip_cutter.js` (layout features 5–6). No backend changes. Canvas drawing follows the pattern in `/home/sam/docker-images/deeplabcut-webapp-docker/src/static/js/annotator.js`.

**Tech Stack:** Vanilla JS, HTML5 Canvas, CSS (no build step, no test framework — frontend verification is manual browser checks).

---

## File Map

- **Modify:** `clip-cutter/templates/clip_cutter.html` — HTML elements + CSS for all 6 features
- **Modify:** `clip-cutter/static/enhanced_player.js` — player logic for features 1–4
- **Modify:** `clip-cutter/static/clip_cutter.js` — collapse/resize logic for features 5–6

---

### Task 1: Jump to Keyframe Button

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html` (add button in `#ep-controls`)
- Modify: `clip-cutter/static/enhanced_player.js` (show/hide in `_epUpdateModeUI`, add event handler)

- [ ] **Step 1: Add the button HTML**

In `clip_cutter.html`, find the `#ep-controls` div. It currently starts with:
```html
<div id="ep-controls">
  <button class="player-btn" id="ep-first" title="Jump to start">&#9198;</button>
  <button class="player-btn" id="ep-back" title="Back by step size">&#9664;&#9664;</button>
```

Insert `ep-goto-kf` between `ep-first` and `ep-back`:
```html
<div id="ep-controls">
  <button class="player-btn" id="ep-first" title="Jump to start">&#9198;</button>
  <button class="player-btn" id="ep-goto-kf" title="Jump to keyframe" style="display:none;">&#8982; KF</button>
  <button class="player-btn" id="ep-back" title="Back by step size">&#9664;&#9664;</button>
```

- [ ] **Step 2: Show/hide in `_epUpdateModeUI`**

In `enhanced_player.js`, find `_epUpdateModeUI`. It currently has:
```javascript
  if (_mode === "clip") {
    lockBadge.style.display = "";
```

Add `ep-goto-kf` show/hide into the if/else:
```javascript
  const gotoKfBtn = document.getElementById("ep-goto-kf");

  if (_mode === "clip") {
    lockBadge.style.display = "";
    lockBadge.textContent = "🔒 " + (_clipStart + 1) + "–" + (_clipEnd + 1);
    setKfBtn.style.display = "";
    rejectBtn.style.display = "";
    addTemplateBtn.style.display = "none";
    gotoKfBtn.style.display = "";
    document.getElementById("ep-lock-start").checked = true;
    // ... rest of clip block unchanged ...
  } else {
    lockBadge.style.display = "none";
    setKfBtn.style.display = "none";
    rejectBtn.style.display = "none";
    addTemplateBtn.style.display = "";
    gotoKfBtn.style.display = "none";
    document.getElementById("ep-lock-start").checked = false;
  }
```

- [ ] **Step 3: Add event handler in `DOMContentLoaded`**

In `enhanced_player.js`, inside `DOMContentLoaded`, add after the `ep-first` handler:
```javascript
  // ⌖ KF — jump to current clip's keyframe
  document.getElementById("ep-goto-kf").addEventListener("click", () => {
    _stop(); _epLoadFrame(_keyFrame);
  });
```

- [ ] **Step 4: Manual verification**

Start the container: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports && docker compose up -d`
Open `http://localhost:5001` (or whatever port clip-cutter runs on), click a detection card.
Expected: `⌖ KF` button appears in controls. Clicking it jumps to the keyframe frame. Button absent in template mode.

- [ ] **Step 5: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html clip-cutter/static/enhanced_player.js
git commit -m "feat: add jump-to-keyframe button in clip mode player"
```

---

### Task 2: Snappier Video Switch (video-info cache)

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js` (add cache, show panel early)

- [ ] **Step 1: Add cache at module scope**

In `enhanced_player.js`, add after the existing state variables block (after `let _timerId = null;`):
```javascript
const _videoInfoCache = {};
```

- [ ] **Step 2: Show panel immediately and use cache in `openPlayer`**

Currently `openPlayer` shows the panel partway through. Replace the entire `openPlayer` function with this version that shows the panel first and uses the cache:

```javascript
async function openPlayer({ mode, videoPath, keyFrame1Based = null, detectionIdx = null, csvPath = null }) {
  _stop();
  _mode = mode;
  _videoPath = videoPath;
  _detectionIdx = detectionIdx;
  _csvRows = [];
  _stepSize = 10;
  _playN = 1;
  _looping = true;
  const stepEl = document.getElementById("ep-step");
  const playNEl = document.getElementById("ep-playn");
  if (stepEl) stepEl.value = 10;
  if (playNEl) playNEl.value = 1;

  // Show panel immediately so user sees it open without waiting for network
  document.getElementById("player-panel").style.display = "";

  // Fetch frame count — use cache to skip round-trip on repeated opens
  let frameCount;
  if (_videoInfoCache[videoPath]) {
    frameCount = _videoInfoCache[videoPath];
  } else {
    let info;
    try {
      const resp = await fetch(`/clip-cutter/video-info?video=${encodeURIComponent(videoPath)}`);
      if (!resp.ok) { setStatus("Cannot load video info"); return; }
      info = await resp.json();
    } catch (e) { setStatus("Network error: " + e.message); return; }
    frameCount = info.frame_count;
    _videoInfoCache[videoPath] = frameCount;
  }
  _frameCount = frameCount;

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

  _epUpdateModeUI();
  _epInitExtractPanel(videoPath, keyFrame1Based);

  if (csvPath) {
    try {
      const r = await fetch(`/clip-cutter/csv?path=${encodeURIComponent(csvPath)}`);
      if (r.ok) _csvRows = (await r.json()).rows;
    } catch (e) {
      console.warn("[enhanced_player] CSV load failed:", e);
    }
  }

  _epBuildTagBars();

  await _epLoadFrame(_clipStart);
}
```

Note: `_epBuildTagBars()` is fully defined in Task 3. For now add this stub immediately after the state variables block so `openPlayer` can call it without error:
```javascript
function _epBuildTagBars() { /* stub — replaced in Task 3 */ }
```
Task 3 will replace this stub with the real implementation.

- [ ] **Step 3: Manual verification**

Open a detection card (first open). Close the player. Click the same card again.
Expected: On the second open, the panel appears instantly (no spinner delay) and the frame loads faster.

- [ ] **Step 4: Commit**

```bash
git add clip-cutter/static/enhanced_player.js
git commit -m "feat: cache video-info and show player panel immediately on open"
```

---

### Task 3: Canvas Tag Timelines

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html` (add HTML + CSS for two timeline bars)
- Modify: `clip-cutter/static/enhanced_player.js` (replace stub, add all canvas/chip/nav functions + event handlers)

- [ ] **Step 1: Add CSS to `clip_cutter.html`**

In `clip_cutter.html`, inside `<style>`, add after the `#ep-extract-panel .player-btn` rule:
```css
/* ── Tag timeline bars ──────────────────────────────────────────────────────── */
.ep-bar-header { display:flex; align-items:center; gap:4px; margin-top:4px; margin-bottom:2px; }
.ep-chips-row { display:flex; flex-wrap:wrap; gap:3px; margin-top:2px; margin-bottom:2px; }
.ep-tag-chip {
  font-size:8px; padding:1px 5px; border-radius:3px; cursor:pointer;
  border:1px solid var(--chip-color,#555); color:var(--chip-color,#888);
  background:transparent; user-select:none;
}
.ep-tag-chip.active { background: color-mix(in srgb, var(--chip-color,#555) 20%, transparent); }
```

- [ ] **Step 2: Add HTML for the two timeline bars**

In `clip_cutter.html`, find the `#ep-csv-strip` div (the status/note strip). Insert the two bar wraps immediately after its closing `</div>`:

```html
    <!-- Status timeline bar -->
    <div id="ep-status-bar-wrap" style="display:none;">
      <div class="ep-bar-header">
        <span class="ep-strip-label">Status</span>
        <button class="player-btn" id="ep-status-prev" style="padding:1px 5px;font-size:9px;">&#9664;</button>
        <button class="player-btn" id="ep-status-next" style="padding:1px 5px;font-size:9px;">&#9654;</button>
      </div>
      <canvas id="ep-status-canvas" height="10" style="width:100%;display:block;cursor:pointer;border-radius:2px;background:#161b22;"></canvas>
      <div id="ep-status-chips" class="ep-chips-row"></div>
    </div>

    <!-- Note timeline bar -->
    <div id="ep-note-bar-wrap" style="display:none;">
      <div class="ep-bar-header">
        <span class="ep-strip-label">Note</span>
        <button class="player-btn" id="ep-note-prev" style="padding:1px 5px;font-size:9px;">&#9664;</button>
        <button class="player-btn" id="ep-note-next" style="padding:1px 5px;font-size:9px;">&#9654;</button>
      </div>
      <canvas id="ep-note-canvas" height="10" style="width:100%;display:block;cursor:pointer;border-radius:2px;background:#161b22;"></canvas>
      <div id="ep-note-chips" class="ep-chips-row"></div>
    </div>
```

- [ ] **Step 3: Add module-level state for tag canvases**

In `enhanced_player.js`, add after `const _videoInfoCache = {};`:
```javascript
const _EP_TAG_COLORS = ["#58a6ff","#3fb950","#f0c040","#f85149","#d2a8ff","#ffa657","#79c0ff","#56d364"];
let _epStatusColorMap = {};
let _epNoteColorMap   = {};
let _epActiveStatus   = new Set();
let _epActiveNote     = new Set();
```

- [ ] **Step 4: Replace the `_epBuildTagBars` stub and add all canvas drawing functions**

In `enhanced_player.js`, find and **delete** the stub added in Task 2:
```javascript
function _epBuildTagBars() { /* stub — replaced in Task 3 */ }
```

Then add all of the following functions after `_epUpdateEnd` (before `_epUpdateModeUI`):

```javascript
// ── Tag timeline canvases ──────────────────────────────────────────────────────

function _epDrawTagCanvas(canvas, rows, field, activeSet, colorMap) {
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

function _epDrawCanvasCursor(canvas) {
  if (!canvas || !_frameCount) return;
  const W = canvas.width;
  if (!W) return;
  const ctx = canvas.getContext("2d");
  const x = Math.round((_currentFrame / Math.max(_frameCount - 1, 1)) * W);
  ctx.save();
  ctx.globalAlpha = 0.8;
  ctx.fillStyle = "#fff";
  ctx.fillRect(x, 0, 1, canvas.height);
  ctx.restore();
}

function _epRedrawStatusCanvas() {
  const canvas = document.getElementById("ep-status-canvas");
  if (!canvas || document.getElementById("ep-status-bar-wrap").style.display === "none") return;
  _epDrawTagCanvas(canvas, _csvRows, "frame_line_status", _epActiveStatus, _epStatusColorMap);
  _epDrawCanvasCursor(canvas);
}

function _epRedrawNoteCanvas() {
  const canvas = document.getElementById("ep-note-canvas");
  if (!canvas || document.getElementById("ep-note-bar-wrap").style.display === "none") return;
  _epDrawTagCanvas(canvas, _csvRows, "note", _epActiveNote, _epNoteColorMap);
  _epDrawCanvasCursor(canvas);
}

function _epRedrawAllCanvases() {
  _epRedrawStatusCanvas();
  _epRedrawNoteCanvas();
}

function _epRenderStatusChips() {
  const container = document.getElementById("ep-status-chips");
  if (!container) return;
  container.innerHTML = "";
  Object.keys(_epStatusColorMap).forEach(val => {
    const chip = document.createElement("span");
    chip.className = "ep-tag-chip" + (_epActiveStatus.has(val) ? " active" : "");
    chip.textContent = val;
    chip.style.setProperty("--chip-color", _epStatusColorMap[val]);
    chip.addEventListener("click", () => {
      if (_epActiveStatus.has(val)) _epActiveStatus.delete(val);
      else _epActiveStatus.add(val);
      _epRenderStatusChips();
      _epRedrawStatusCanvas();
    });
    container.appendChild(chip);
  });
}

function _epRenderNoteChips() {
  const container = document.getElementById("ep-note-chips");
  if (!container) return;
  container.innerHTML = "";
  Object.keys(_epNoteColorMap).forEach(val => {
    const chip = document.createElement("span");
    chip.className = "ep-tag-chip" + (_epActiveNote.has(val) ? " active" : "");
    chip.textContent = val;
    chip.style.setProperty("--chip-color", _epNoteColorMap[val]);
    chip.addEventListener("click", () => {
      if (_epActiveNote.has(val)) _epActiveNote.delete(val);
      else _epActiveNote.add(val);
      _epRenderNoteChips();
      _epRedrawNoteCanvas();
    });
    container.appendChild(chip);
  });
}

function _epBuildTagBars() {
  const hasStatus = _csvRows.some(r => r.frame_line_status && r.frame_line_status !== "0");
  const hasNote   = _csvRows.some(r => r.note);

  document.getElementById("ep-status-bar-wrap").style.display = hasStatus ? "" : "none";
  document.getElementById("ep-note-bar-wrap").style.display   = hasNote   ? "" : "none";

  const statusVals = [...new Set(_csvRows.map(r => r.frame_line_status).filter(v => v && v !== "0"))];
  _epStatusColorMap = {};
  _epActiveStatus   = new Set(statusVals);
  statusVals.forEach((v, i) => { _epStatusColorMap[v] = _EP_TAG_COLORS[i % _EP_TAG_COLORS.length]; });
  _epRenderStatusChips();

  const noteVals = [...new Set(_csvRows.map(r => r.note).filter(v => v))];
  _epNoteColorMap = {};
  _epActiveNote   = new Set(noteVals);
  noteVals.forEach((v, i) => { _epNoteColorMap[v] = _EP_TAG_COLORS[i % _EP_TAG_COLORS.length]; });
  _epRenderNoteChips();

  _epRedrawAllCanvases();
}
```

- [ ] **Step 5: Call `_epRedrawAllCanvases()` from `_epUpdateDisplay`**

In `enhanced_player.js`, find `_epUpdateDisplay`. It ends with:
```javascript
  if (!_playing && !document.getElementById("ep-lock-start").checked) {
    document.getElementById("ep-start").value = cur1;
    _epUpdateEnd();
  }
}
```

Add the canvas redraw call just before the closing `}`:
```javascript
  if (!_playing && !document.getElementById("ep-lock-start").checked) {
    document.getElementById("ep-start").value = cur1;
    _epUpdateEnd();
  }
  _epRedrawAllCanvases();
}
```

- [ ] **Step 6: Add canvas click + prev/next event handlers in `DOMContentLoaded`**

In `enhanced_player.js`, inside `DOMContentLoaded`, add these handlers after the existing `ep-next-tag` handler:

```javascript
  // ── Status timeline canvas ────────────────────────────────────────────────

  document.getElementById("ep-status-canvas").addEventListener("click", e => {
    const canvas = e.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const target = Math.round((e.clientX - rect.left) / rect.width * Math.max(_frameCount - 1, 0));
    const annotated = _csvRows
      .filter(r => { const v = r.frame_line_status; return v && v !== "0" && _epActiveStatus.has(v); })
      .map(r => Number(r.frame_number) - 1);
    if (!annotated.length) return;
    const nearest = annotated.reduce((a, b) => Math.abs(b - target) < Math.abs(a - target) ? b : a);
    _stop(); _epLoadFrame(nearest);
  });

  document.getElementById("ep-status-prev").addEventListener("click", () => {
    const cur1 = _currentFrame + 1;
    const prev = [..._csvRows]
      .filter(r => { const v = r.frame_line_status; return v && v !== "0" && _epActiveStatus.has(v) && r.frame_number < cur1; })
      .sort((a, b) => b.frame_number - a.frame_number)[0];
    if (prev) { _stop(); _epLoadFrame(prev.frame_number - 1); }
  });

  document.getElementById("ep-status-next").addEventListener("click", () => {
    const cur1 = _currentFrame + 1;
    const next = _csvRows.find(r => {
      const v = r.frame_line_status;
      return v && v !== "0" && _epActiveStatus.has(v) && r.frame_number > cur1;
    });
    if (next) { _stop(); _epLoadFrame(next.frame_number - 1); }
  });

  // ── Note timeline canvas ──────────────────────────────────────────────────

  document.getElementById("ep-note-canvas").addEventListener("click", e => {
    const canvas = e.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const target = Math.round((e.clientX - rect.left) / rect.width * Math.max(_frameCount - 1, 0));
    const annotated = _csvRows
      .filter(r => { const v = r.note; return v && _epActiveNote.has(v); })
      .map(r => Number(r.frame_number) - 1);
    if (!annotated.length) return;
    const nearest = annotated.reduce((a, b) => Math.abs(b - target) < Math.abs(a - target) ? b : a);
    _stop(); _epLoadFrame(nearest);
  });

  document.getElementById("ep-note-prev").addEventListener("click", () => {
    const cur1 = _currentFrame + 1;
    const prev = [..._csvRows]
      .filter(r => { const v = r.note; return v && _epActiveNote.has(v) && r.frame_number < cur1; })
      .sort((a, b) => b.frame_number - a.frame_number)[0];
    if (prev) { _stop(); _epLoadFrame(prev.frame_number - 1); }
  });

  document.getElementById("ep-note-next").addEventListener("click", () => {
    const cur1 = _currentFrame + 1;
    const next = _csvRows.find(r => {
      const v = r.note;
      return v && _epActiveNote.has(v) && r.frame_number > cur1;
    });
    if (next) { _stop(); _epLoadFrame(next.frame_number - 1); }
  });
```

- [ ] **Step 7: Manual verification**

Open a detection card that has a CSV path (a video that has been annotated). Expected:
- Status and/or Note bars appear below the status/note strip, with a colored canvas and chip buttons.
- All chips start active (colored background).
- Clicking a chip toggles it off (removes its color from canvas).
- Clicking on the canvas jumps to the nearest annotated frame.
- ◀ / ▶ buttons cycle through annotated frames for that field.
- White cursor line moves with the current frame.
- If no CSV, bars stay hidden.

- [ ] **Step 8: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html clip-cutter/static/enhanced_player.js
git commit -m "feat: add canvas tag timelines for status and note fields"
```

---

### Task 4: Keyframe Canvas Overlay + Navigation

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html` (add KF canvas element + KF nav buttons + CSS)
- Modify: `clip-cutter/static/enhanced_player.js` (add state, `_epDrawKfCanvas`, `_epAllKfFrames`, event handlers, hook into `openPlayer` + `_epApplyNewKF`)

- [ ] **Step 1: Add CSS for KF canvas**

In `clip_cutter.html` `<style>`, add after the tag timeline CSS from Task 3:
```css
/* ── KF canvas overlay ──────────────────────────────────────────────────────── */
#ep-kf-canvas { width:100%; display:block; border-radius:2px; background:#161b22; }
```

- [ ] **Step 2: Add KF canvas element above the seek row**

In `clip_cutter.html`, find the `#ep-seek-row` div. Insert the KF canvas immediately before it:
```html
    <!-- Keyframe overlay canvas (hidden by default) -->
    <canvas id="ep-kf-canvas" height="8" style="display:none;"></canvas>

    <!-- Seek bar -->
    <div id="ep-seek-row">
```

- [ ] **Step 3: Add KF toggle and nav buttons to `#ep-controls`**

In `clip_cutter.html`, find the `#ep-controls` div. Add the three KF buttons after `ep-goto-kf` and before `ep-back`:
```html
      <button class="player-btn" id="ep-goto-kf" title="Jump to keyframe" style="display:none;">&#8982; KF</button>
      <button class="player-btn" id="ep-kf-prev" title="Previous keyframe">&#9664; KF</button>
      <button class="player-btn" id="ep-kf-toggle" title="Toggle keyframe overlay">&#8982; KFs</button>
      <button class="player-btn" id="ep-kf-next" title="Next keyframe">KF &#9654;</button>
      <button class="player-btn" id="ep-back" title="Back by step size">&#9664;&#9664;</button>
```

- [ ] **Step 4: Add module-level state for KF canvas**

In `enhanced_player.js`, add after `let _epActiveNote = new Set();`:
```javascript
let _kfCanvasVisible = false;
```

- [ ] **Step 5: Add `_epAllKfFrames` and `_epDrawKfCanvas` functions**

In `enhanced_player.js`, add after `_epBuildTagBars` (before `_epUpdateModeUI`):

```javascript
// ── Keyframe canvas overlay ────────────────────────────────────────────────────

function _epAllKfFrames() {
  if (typeof detections === "undefined") return [];
  return detections
    .filter(d => d.video_path === _videoPath && d.frame_number != null)
    .map(d => d.frame_number - 1)
    .sort((a, b) => a - b);
}

function _epDrawKfCanvas() {
  const canvas = document.getElementById("ep-kf-canvas");
  if (!canvas || !_kfCanvasVisible || !_frameCount) return;
  const W = Math.round(canvas.getBoundingClientRect().width) || canvas.clientWidth || 600;
  canvas.width = W;
  const H = canvas.height || 8;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, W, H);
  const total = Math.max(_frameCount - 1, 1);
  if (typeof detections === "undefined") return;
  detections.forEach((d, i) => {
    if (d.video_path !== _videoPath || d.frame_number == null) return;
    const kf0 = d.frame_number - 1;
    const x = Math.round((kf0 / total) * W);
    if (i === _detectionIdx) {
      ctx.fillStyle = "#56d4db"; // current clip: cyan, 2px wide
      ctx.fillRect(x, 0, 2, H);
    } else {
      ctx.fillStyle = "#f0c040"; // other clips: yellow, 1px wide
      ctx.fillRect(x, 0, 1, H);
    }
  });
}
```

- [ ] **Step 6: Hook `_epDrawKfCanvas` into `openPlayer` and `_epApplyNewKF`**

In `openPlayer`, at the very end (after `await _epLoadFrame(_clipStart);`), add:
```javascript
  document.getElementById("ep-kf-toggle").classList.toggle("active", _kfCanvasVisible);
  if (_kfCanvasVisible) {
    document.getElementById("ep-kf-canvas").style.display = "block";
    _epDrawKfCanvas();
  } else {
    document.getElementById("ep-kf-canvas").style.display = "none";
  }
```

In `_epApplyNewKF`, at the end (after `document.getElementById("ep-warning").style.display = "none";`), add:
```javascript
  _epDrawKfCanvas();
```

- [ ] **Step 7: Add event handlers in `DOMContentLoaded`**

In `enhanced_player.js`, inside `DOMContentLoaded`, add after the `ep-goto-kf` handler:

```javascript
  // KF canvas toggle
  document.getElementById("ep-kf-toggle").addEventListener("click", () => {
    _kfCanvasVisible = !_kfCanvasVisible;
    const canvas = document.getElementById("ep-kf-canvas");
    canvas.style.display = _kfCanvasVisible ? "block" : "none";
    document.getElementById("ep-kf-toggle").classList.toggle("active", _kfCanvasVisible);
    if (_kfCanvasVisible) _epDrawKfCanvas();
  });

  // KF prev/next navigation
  document.getElementById("ep-kf-prev").addEventListener("click", () => {
    const frames = _epAllKfFrames();
    const prev = [...frames].reverse().find(f => f < _currentFrame);
    if (prev !== undefined) { _stop(); _epLoadFrame(prev); }
  });

  document.getElementById("ep-kf-next").addEventListener("click", () => {
    const frames = _epAllKfFrames();
    const next = frames.find(f => f > _currentFrame);
    if (next !== undefined) { _stop(); _epLoadFrame(next); }
  });
```

- [ ] **Step 8: Manual verification**

Open two or more detection cards (close player between each to not lose state). Then open one:
- Click `⌖ KFs` → thin 8px bar appears above seek bar. Yellow ticks for other clips' KFs, cyan tick for this clip's KF.
- Click `◀ KF` / `KF ▶` → frame jumps to previous/next KF position.
- Click `⌖ KFs` again → bar hides.
- Reopen a different clip → bar state preserved (still on or off from before).

- [ ] **Step 9: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html clip-cutter/static/enhanced_player.js
git commit -m "feat: add keyframe canvas overlay and KF prev/next navigation"
```

---

### Task 5: Collapsible Sidebar and Browser Section

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html` (add toggle buttons + CSS classes)
- Modify: `clip-cutter/static/clip_cutter.js` (add toggle event handlers in DOMContentLoaded)

- [ ] **Step 1: Add CSS for collapsed states**

In `clip_cutter.html` `<style>`, add after the existing `.sidebar` rule:
```css
/* ── Collapsible sidebar ────────────────────────────────────────────────────── */
.sidebar.collapsed #template-grid,
.sidebar.collapsed #template-footer,
.sidebar.collapsed #sidebar-actions,
.sidebar.collapsed #sidebar-empty-state,
.sidebar.collapsed #sidebar-no-template { display: none !important; }

/* ── Collapsible browser section ────────────────────────────────────────────── */
#browser-section.collapsed #browser-list,
#browser-section.collapsed #scan-settings,
#browser-section.collapsed #scan-btn { display: none !important; }
```

- [ ] **Step 2: Add sidebar toggle button**

In `clip_cutter.html`, find `.sidebar-header`:
```html
    <div class="sidebar-header">
      <span class="sidebar-title">Template Bank</span>
      <button class="btn-sm btn-green" id="sidebar-init-btn" ...>&#8635; Init</button>
    </div>
```

Add the toggle button after `sidebar-init-btn`:
```html
    <div class="sidebar-header">
      <span class="sidebar-title">Template Bank</span>
      <button class="btn-sm btn-green" id="sidebar-init-btn" style="display:none;" title="Init template from this video">&#8635; Init</button>
      <button class="btn-sm" id="sidebar-toggle" title="Collapse sidebar">&#9660;</button>
    </div>
```

- [ ] **Step 3: Add browser section toggle button**

In `clip_cutter.html`, find `.browser-toolbar`:
```html
      <div class="browser-toolbar">
        <button id="browser-up" class="btn-sm" title="Parent folder">&#8593; Up</button>
        <div id="browser-breadcrumb"></div>
      </div>
```

Add the toggle button at the end of the toolbar:
```html
      <div class="browser-toolbar">
        <button id="browser-up" class="btn-sm" title="Parent folder">&#8593; Up</button>
        <div id="browser-breadcrumb"></div>
        <button id="browser-toggle" class="btn-sm" title="Collapse browser">&#9660;</button>
      </div>
```

- [ ] **Step 4: Add toggle event handlers in `clip_cutter.js`**

In `clip_cutter.js`, inside the `DOMContentLoaded` callback, add after the `settings-toggle` block:

```javascript
  // Sidebar collapse toggle
  const sidebarToggle = document.getElementById("sidebar-toggle");
  const sidebarEl = document.querySelector(".sidebar");
  if (sidebarToggle && sidebarEl) {
    sidebarToggle.addEventListener("click", () => {
      const collapsed = sidebarEl.classList.toggle("collapsed");
      sidebarToggle.textContent = collapsed ? "▶" : "▼";
    });
  }

  // Browser section collapse toggle
  const browserToggle = document.getElementById("browser-toggle");
  const browserSection = document.getElementById("browser-section");
  if (browserToggle && browserSection) {
    browserToggle.addEventListener("click", () => {
      const collapsed = browserSection.classList.toggle("collapsed");
      browserToggle.textContent = collapsed ? "▶" : "▼";
    });
  }
```

- [ ] **Step 5: Manual verification**

- Click `▼` on sidebar header → template grid and footer disappear; sidebar header stays; `▼` becomes `▶`. Click `▶` → content reappears.
- Click `▼` on browser toolbar → file list and scan settings disappear; breadcrumb toolbar stays. Click `▶` → reappears.

- [ ] **Step 6: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html clip-cutter/static/clip_cutter.js
git commit -m "feat: add collapsible sidebar and browser section toggles"
```

---

### Task 6: Resizable Sidebar

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html` (add resize handle element + CSS)
- Modify: `clip-cutter/static/clip_cutter.js` (add drag IIFE)

- [ ] **Step 1: Add CSS for resize handle**

In `clip_cutter.html` `<style>`, update the existing `.sidebar` rule to add `position: relative`:
```css
.sidebar { width: 210px; flex-shrink: 0; background: #161b22; border-right: 1px solid #30363d; display: flex; flex-direction: column; overflow: hidden; position: relative; }
```

Then add the handle CSS after it:
```css
#sidebar-resize-handle {
  position: absolute; top: 0; right: 0; bottom: 0; width: 5px;
  cursor: ew-resize; background: transparent; z-index: 10;
}
#sidebar-resize-handle:hover { background: #388bfd44; }
```

- [ ] **Step 2: Add resize handle element**

In `clip_cutter.html`, find the `.sidebar` div closing tag (after `#sidebar-actions`). Insert the handle as the last child of `.sidebar`:
```html
      <div id="sidebar-resize-handle"></div>
    </div>
    <!-- end .sidebar -->
```

The sidebar currently ends like:
```html
    <div id="sidebar-actions" style="display:none;...">
      ...
    </div>
  </div>
```

Make it:
```html
    <div id="sidebar-actions" style="display:none;...">
      ...
    </div>
    <div id="sidebar-resize-handle"></div>
  </div>
```

- [ ] **Step 3: Add drag IIFE in `clip_cutter.js`**

In `clip_cutter.js`, at the bottom of the file (after `function setStatus(msg) { ... }`), add:

```javascript
// ── Sidebar resize ─────────────────────────────────────────────────────────────

(function () {
  const handle  = document.getElementById("sidebar-resize-handle");
  const sidebar = document.querySelector(".sidebar");
  if (!handle || !sidebar) return;
  let startX = 0, startW = 0;

  handle.addEventListener("mousedown", e => {
    startX = e.clientX;
    startW = sidebar.offsetWidth;
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup",   onUp);
    e.preventDefault();
  });

  function onMove(e) {
    const w = Math.max(120, Math.min(400, startW + (e.clientX - startX)));
    sidebar.style.width = w + "px";
  }

  function onUp() {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup",   onUp);
  }
})();
```

- [ ] **Step 4: Manual verification**

Hover over the right edge of the sidebar → cursor changes to `ew-resize` and a blue highlight appears on hover. Drag right → sidebar widens (max 400px). Drag left → sidebar narrows (min 120px). Release → drag stops. Content adjusts to new width.

- [ ] **Step 5: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html clip-cutter/static/clip_cutter.js
git commit -m "feat: add draggable resize handle for sidebar"
```

---

## Self-Review Checklist

- Feature 1 (jump to KF): Button in HTML ✓, show/hide in `_epUpdateModeUI` ✓, handler in DOMContentLoaded ✓
- Feature 2 (snappier): Cache at module scope ✓, panel shown first ✓, cache used in `openPlayer` ✓
- Feature 3 (tag canvases): HTML + CSS ✓, state variables ✓, `_epDrawTagCanvas`/`_epDrawCanvasCursor`/`_epRedrawAllCanvases` ✓, `_epBuildTagBars` ✓, chip renderers ✓, called from `_epUpdateDisplay` ✓, called from `openPlayer` ✓, canvas click + prev/next handlers ✓
- Feature 4 (KF overlay): HTML canvas + buttons ✓, `_epAllKfFrames`/`_epDrawKfCanvas` ✓, hooked in `openPlayer` + `_epApplyNewKF` ✓, toggle + nav handlers ✓
- Feature 5 (collapse): CSS classes ✓, HTML buttons ✓, handlers in clip_cutter.js ✓
- Feature 6 (resize): CSS + `position:relative` on sidebar ✓, handle HTML ✓, drag IIFE ✓

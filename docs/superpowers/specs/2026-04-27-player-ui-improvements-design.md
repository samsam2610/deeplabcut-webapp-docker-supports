# Player UI Improvements Design

## Goal

Six targeted UI improvements to the clip-cutter player and layout: jump-to-keyframe button, snappier video switching, canvas tag timelines, keyframe overlay on seek bar, collapsible sidebar and browser section, and resizable sidebar.

## Architecture

All changes are isolated to three existing files: `clip_cutter.html` (HTML structure + CSS), `enhanced_player.js` (player logic for items 1–4), and `clip_cutter.js` (layout controls for items 5–6). No new files. No backend changes.

## Tech Stack

Vanilla JS, HTML5 Canvas, CSS transitions. Pattern modelled on the `_anvDrawCanvas` canvas approach in `/home/sam/docker-images/deeplabcut-webapp-docker/src/static/js/annotator.js`.

---

## Feature 1 — Jump to Keyframe Button

A `⌖ KF` button is added to `#ep-controls`, positioned between the `⏮` (first) and `◀◀` (back-step) buttons. Visible and enabled only in clip mode (`_mode === "clip"`). Clicking it stops playback and calls `_epLoadFrame(_keyFrame)`. Hidden in template mode.

`_epUpdateModeUI` handles show/hide of the button alongside the existing Set KF / Reject button logic.

---

## Feature 2 — Snappier Video Switch

**Problem:** `openPlayer` makes two sequential fetches (video-info, then CSV) before the first frame loads. Re-opening the same video repeats the video-info fetch unnecessarily.

**Solution:**
- Module-level `const _videoInfoCache = {}` maps `videoPath → frame_count`.
- On `openPlayer`, if the path is cached, skip the `/clip-cutter/video-info` fetch and use the cached value directly.
- Show `#player-panel` immediately at the start of `openPlayer` (before any fetches) so the panel appears without delay.
- CSV is not cached (it changes between sessions and is user-controlled).

No backend changes. Cache lives for the page lifetime only.

---

## Feature 3 — Canvas Tag Timelines

Two canvas-based timeline bars added below `#ep-csv-strip`, one for `frame_line_status` and one for `note`. They appear only when CSV data is loaded and the respective field has at least one non-empty value.

### HTML structure (inserted after `#ep-csv-strip`)

```html
<div id="ep-status-bar-wrap" style="display:none;">
  <div class="ep-bar-header">
    <span class="ep-strip-label">Status</span>
    <button class="player-btn" id="ep-status-prev">◀</button>
    <button class="player-btn" id="ep-status-next">▶</button>
  </div>
  <canvas id="ep-status-canvas" height="10" style="width:100%;display:block;cursor:pointer;"></canvas>
  <div id="ep-status-chips" class="ep-chips-row"></div>
</div>

<div id="ep-note-bar-wrap" style="display:none;">
  <div class="ep-bar-header">
    <span class="ep-strip-label">Note</span>
    <button class="player-btn" id="ep-note-prev">◀</button>
    <button class="player-btn" id="ep-note-next">▶</button>
  </div>
  <canvas id="ep-note-canvas" height="10" style="width:100%;display:block;cursor:pointer;"></canvas>
  <div id="ep-note-chips" class="ep-chips-row"></div>
</div>
```

### Canvas drawing (`_epDrawTagCanvas`)

Ported directly from annotator's `_anvDrawCanvas`:

```javascript
function _epDrawTagCanvas(canvas, rows, field, activeSet, colorMap) {
  const total = Math.max(_frameCount, 1);
  const W = canvas.getBoundingClientRect().width || 600;
  canvas.width = W;
  const H = canvas.height || 10;
  const ctx = canvas.getContext("2d");
  const minW = Math.max(1, Math.round(W / total));
  ctx.clearRect(0, 0, W, H);
  rows.forEach(row => {
    const val = row[field];
    if (!val || (field === "frame_line_status" && val === "0")) return;
    if (!activeSet.has(val)) return;
    ctx.fillStyle = colorMap[val] || "#888";
    const x = Math.round(((row.frame_number - 1) / (total - 1)) * W);
    ctx.fillRect(x, 0, minW, H);
  });
}
```

A current-frame cursor (1px white vertical line) is drawn on top during `_epUpdateDisplay`:

```javascript
function _epDrawCanvasCursor(canvas) {
  if (!canvas || !_frameCount) return;
  const W = canvas.width;
  const ctx = canvas.getContext("2d");
  const x = Math.round((_currentFrame / (_frameCount - 1)) * W);
  ctx.save();
  ctx.globalAlpha = 0.8;
  ctx.fillStyle = "#fff";
  ctx.fillRect(x, 0, 1, canvas.height);
  ctx.restore();
}
```

The canvas is fully redrawn (data + cursor) only when: CSV loads, a chip is toggled, or `_epUpdateDisplay` is called. `_epUpdateDisplay` calls a combined `_epRedrawAllCanvases()` which clears and redraws both canvases including the cursor — this avoids accumulating cursor artifacts.

### Color palette

```javascript
const _EP_TAG_COLORS = ["#58a6ff","#3fb950","#f0c040","#f85149","#d2a8ff","#ffa657","#79c0ff","#56d364"];
```

### Chips

Each unique value gets a `<span class="ep-tag-chip">` with `--chip-color` CSS variable. All chips start active (full activeSet). Clicking a chip toggles its value in the activeSet and redraws the canvas.

### Click to jump

Canvas click computes target frame = `Math.round(clickX / W * (frameCount - 1))`, then finds the nearest annotated frame in `_csvRows` for that field, and calls `_epLoadFrame(nearestFrame - 1)`.

### Prev/Next buttons

◀ finds the largest `frame_number` in `_csvRows` (for that field, in activeSet) less than `_currentFrame + 1`. ▶ finds the smallest greater. Calls `_epLoadFrame`.

### Visibility

`_epBuildTagBars()` is called after CSV loads. It checks `_csvRows` for the presence of each field, shows/hides the respective wrap div, builds chips, and draws the canvas.

---

## Feature 4 — Keyframe Overlay on Seek Bar + Navigation

### Canvas overlay

A `<canvas id="ep-kf-canvas">` (full-width, 8px tall) is inserted directly above `#ep-seek-track`. Hidden by default. A `[⌖ KFs]` toggle button in `#ep-controls` (after the loop button, before the spacer) shows/hides it.

When visible, `_epDrawKfCanvas()` draws:
- All keyframes from other detections for the same video: `detections.filter(d => d.video_path === _videoPath && detections.indexOf(d) !== _detectionIdx)` → yellow `#f0c040` lines, 1px wide.
- The current clip's keyframe (`_keyFrame`): cyan `#56d4db`, 2px wide.

Frame → canvas x: `Math.round((kf0 / (_frameCount - 1)) * W)`.

`_epDrawKfCanvas()` is called: when toggle is turned on, inside `openPlayer` (if already visible), and inside `_epApplyNewKF`.

### Navigation buttons

`[◀ KF]` and `[KF ▶]` buttons added to `#ep-controls` alongside the `⌖ KF` button. They collect all KF positions from `detections` for the same video (including the current one), sort them, and jump to the prev/next relative to `_currentFrame`. These buttons work regardless of whether the canvas overlay is visible.

```javascript
function _epAllKfFrames() {
  if (typeof detections === "undefined") return [];
  return detections
    .filter(d => d.video_path === _videoPath && d.frame_number != null)
    .map(d => d.frame_number - 1)
    .sort((a, b) => a - b);
}
```

Buttons are visible in both modes (useful in template mode too, to see where clip keyframes fall).

---

## Feature 5 — Collapsible Sidebar and Browser Section

### Sidebar

A `▼` / `▶` toggle button (`#sidebar-toggle`) is added to `.sidebar-header` (right side, after the init button). Clicking it toggles a `.collapsed` class on `.sidebar`.

CSS:
```css
.sidebar.collapsed #template-grid,
.sidebar.collapsed #template-footer,
.sidebar.collapsed #sidebar-actions,
.sidebar.collapsed #sidebar-empty-state,
.sidebar.collapsed #sidebar-no-template { display: none !important; }
```

The header stays visible. Width stays fixed. No animation needed (content is already hidden/shown by existing JS anyway).

### Browser section

A `▼` / `▶` toggle button (`#browser-toggle`) is added inline in the browser section header area (next to the Up button). Clicking toggles a `.collapsed` class on `#browser-section`.

CSS:
```css
#browser-section.collapsed #browser-list,
#browser-section.collapsed #scan-settings,
#browser-section.collapsed #scan-btn { display: none !important; }
```

The breadcrumb toolbar stays visible. The section shrinks to just the toolbar height.

Both toggles are wired up in `clip_cutter.js` inside the existing `DOMContentLoaded` block.

---

## Feature 6 — Resizable Sidebar

A `<div id="sidebar-resize-handle">` is added as the last child of `.sidebar`:

```css
#sidebar-resize-handle {
  position: absolute;
  top: 0; right: 0; bottom: 0;
  width: 5px;
  cursor: ew-resize;
  background: transparent;
  z-index: 10;
}
#sidebar-resize-handle:hover { background: #388bfd44; }
.sidebar { position: relative; } /* added */
```

Drag logic (in `clip_cutter.js`):

```javascript
(function() {
  const handle = document.querySelector("#sidebar-resize-handle");
  const sidebar = document.querySelector(".sidebar");
  let startX = 0, startW = 0;
  handle.addEventListener("mousedown", e => {
    startX = e.clientX;
    startW = sidebar.offsetWidth;
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    e.preventDefault();
  });
  function onMove(e) {
    const w = Math.max(120, Math.min(400, startW + (e.clientX - startX)));
    sidebar.style.width = w + "px";
  }
  function onUp() {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
  }
})();
```

Min 120px, max 400px.

---

## CSS additions summary (`clip_cutter.html`)

```css
/* Tag timeline bars */
.ep-bar-header { display:flex; align-items:center; gap:4px; margin-bottom:2px; }
.ep-chips-row { display:flex; flex-wrap:wrap; gap:3px; margin-top:2px; }
.ep-tag-chip {
  font-size:8px; padding:1px 5px; border-radius:3px; cursor:pointer;
  border:1px solid var(--chip-color,#555); color:var(--chip-color,#888);
  background:transparent; user-select:none;
}
.ep-tag-chip.active { background: color-mix(in srgb, var(--chip-color,#555) 20%, transparent); }

/* KF canvas */
#ep-kf-canvas { width:100%; display:block; }

/* Sidebar resize */
.sidebar { position: relative; }
#sidebar-resize-handle {
  position:absolute; top:0; right:0; bottom:0; width:5px;
  cursor:ew-resize; background:transparent; z-index:10;
}
#sidebar-resize-handle:hover { background:#388bfd44; }
```

---

## Testing

- Feature 1: Open clip mode, click `⌖ KF` → frame jumps to keyframe. Button hidden in template mode.
- Feature 2: Open a video, close player, reopen same video → panel appears before frame loads; frame appears faster than first open.
- Feature 3: Load a video with CSV data → canvases appear with colored ticks; chip toggle removes/adds color; click canvas → jumps to nearest frame; ◀ ▶ cycle through instances; white cursor moves with frame.
- Feature 4: Click `⌖ KFs` → thin bar appears above seek bar with yellow/cyan lines; `◀ KF` / `KF ▶` jump to prev/next KF position (nav buttons visible in both modes; return no-op in template mode since detections are filtered by video_path).
- Feature 5: Sidebar toggle collapses body, header stays; browser toggle hides list+settings, breadcrumb stays.
- Feature 6: Drag sidebar right edge → width changes between 120–400px.

# DLC-3D Viewer Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three viewer issues in the DLC-3D Frame Extractor: sync cam toggle crops the primary camera, no way to enlarge the viewer, and a ghost dropdown arrow appears near the Browse button before a project is loaded.

**Architecture:** All three fixes are pure frontend (CSS/HTML/JS) with no backend or test changes. Task 1 restructures CSS layout so `aspect-ratio` locks the total viewer height rather than each camera cell's height. Task 2 adds a zoom `<input type="range">` that applies `transform: scale()` to `#cam-displays`. Task 3 wraps the Browse button and path input in a new parent div (`dlc3d-browse-row`) that starts hidden, removing the ghost artifact.

**Tech Stack:** CSS (flexbox, aspect-ratio, transform), ES6 modules (`enhanced_player.js`, `dlc_3d.js`), Jinja2 HTML partial (`card_3d_extract.html`), Docker Compose for build/test.

---

## File Map

| File | What changes |
|------|-------------|
| `dlc-3D/src/static/dlc_3d.css` | Task 1: restructure cam layout + overflow:visible; Task 2: overflow:visible on card |
| `dlc-3D/src/templates/partials/card_3d_extract.html` | Task 1: remove inline width on imgs; Task 2: add zoom row; Task 3: wrap browse row |
| `dlc-3D/src/static/enhanced_player.js` | Task 2: zoom listener + openPlayer reset |
| `dlc-3D/src/static/dlc_3d.js` | Task 3: show/hide browse row instead of browse btn |

---

## Task 1: CSS — Sync Cam Crop Fix

The bug: `aspect-ratio: 16/9` on `.cam-frame-wrap` couples each camera cell's height to its width. When cam2 appears, cam1 shrinks to 50% width → its height also halves → `overflow:hidden` clips the frame. Fix: move `aspect-ratio: 16/9` to `#cam-displays` (the parent row) so total height is locked. Images use `object-fit: contain` to letterbox within their cell.

**Files:**
- Modify: `dlc-3D/src/static/dlc_3d.css`
- Modify: `dlc-3D/src/templates/partials/card_3d_extract.html`

- [ ] **Step 1: Update `dlc_3d.css` — restructure cam layout**

Replace the current cam-related blocks (lines 7–36) with:

```css
/* ── Dual camera display ── */
#dlc-3d-extract-card {
  overflow: visible;
}

#dlc-3d-extract-card #cam-displays {
  display: flex;
  gap: .5rem;
  margin-bottom: .5rem;
  aspect-ratio: 16 / 9;
  align-items: stretch;
}

#dlc-3d-extract-card .cam-wrap {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

#dlc-3d-extract-card .cam-label {
  font-size: .72rem;
  color: var(--text-dim);
  margin-bottom: .2rem;
}

#dlc-3d-extract-card .cam-frame-wrap {
  background: #000;
  border-radius: 4px;
  overflow: hidden;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

#dlc-3d-extract-card .cam-frame-wrap img {
  max-width: 100%;
  max-height: 100%;
  display: block;
  object-fit: contain;
}
```

The full file after this edit should be:

```css
/* dlc_3d.css — styles scoped to #dlc-3d-extract-card only */

/* ── Dual camera display ── */
#dlc-3d-extract-card {
  overflow: visible;
}

#dlc-3d-extract-card #cam-displays {
  display: flex;
  gap: .5rem;
  margin-bottom: .5rem;
  aspect-ratio: 16 / 9;
  align-items: stretch;
}

#dlc-3d-extract-card .cam-wrap {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

#dlc-3d-extract-card .cam-label {
  font-size: .72rem;
  color: var(--text-dim);
  margin-bottom: .2rem;
}

#dlc-3d-extract-card .cam-frame-wrap {
  background: #000;
  border-radius: 4px;
  overflow: hidden;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

#dlc-3d-extract-card .cam-frame-wrap img {
  max-width: 100%;
  max-height: 100%;
  display: block;
  object-fit: contain;
}

#dlc-3d-extract-card #no-video-msg {
  font-size: .8rem;
  color: var(--text-dim);
  text-align: center;
  padding: 2rem 0;
}

/* ── Sync cam row toggle ── */
#dlc-3d-extract-card label.toggle {
  display: flex;
  align-items: center;
  gap: .3rem;
  font-size: .78rem;
  cursor: pointer;
  color: var(--text-dim);
}
#dlc-3d-extract-card label.toggle input { accent-color: var(--accent); cursor: pointer; }

/* ── Seek slider ── */
#dlc-3d-extract-card .fe-seek { width: 100%; }

/* ── Labeled frame chips ── */
#dlc-3d-extract-card .frame-chip {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: .08rem .3rem;
  font-size: .7rem;
  white-space: nowrap;
}
#dlc-3d-extract-card .frame-chip.cam0 { border-color: #3fb950; color: #3fb950; }
#dlc-3d-extract-card .frame-chip.cam1 { border-color: #58a6ff; color: #58a6ff; }
```

- [ ] **Step 2: Remove inline `width:100%` from both camera `<img>` tags in `card_3d_extract.html`**

The inline `width:100%` attribute overrides the CSS `max-width:100%` rule and prevents `object-fit:contain` from letterboxing correctly. Remove `width:100%` from both img tags.

Find this in `card_3d_extract.html` (line ~41):
```html
<img id="ep-frame" src="" alt="" style="display:none;width:100%">
```
Change to:
```html
<img id="ep-frame" src="" alt="" style="display:none">
```

Find this (line ~48):
```html
<img id="ep-cam2-frame" src="" alt="" style="width:100%">
```
Change to:
```html
<img id="ep-cam2-frame" src="" alt="">
```

- [ ] **Step 3: Build and visually verify**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
docker compose build dlc-3d && docker compose up -d dlc-3d
```

Open `http://172.26.0.5:5050/dlc-3d/`. Load a project, select a video:
- Single cam: viewer renders at 16:9 ratio, image fills it fully
- Enable Sync Cam: both cameras appear side by side, **cam1 does NOT crop or shrink in height**
- Disable Sync Cam: cam1 returns to full width, no glitch
- Toggle on/off/on rapidly: no crop, height stays constant throughout

- [ ] **Step 4: Commit**

```bash
git add dlc-3D/src/static/dlc_3d.css dlc-3D/src/templates/partials/card_3d_extract.html
git commit -m "fix: move aspect-ratio to cam-displays parent to prevent sync-cam crop glitch"
```

---

## Task 2: Zoom Slider

Add a zoom range slider below the seek slider. Dragging it applies `transform: scale(v/100)` with `transform-origin: center top` to `#cam-displays`. CSS transform does not affect layout flow, so the viewer visually expands beyond the card boundary (symmetrically from center) while controls below stay in place. `openPlayer()` resets zoom to 100% on each new video load.

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_3d_extract.html`
- Modify: `dlc-3D/src/static/enhanced_player.js`

- [ ] **Step 1: Add zoom row HTML after the seek slider in `card_3d_extract.html`**

Find the seek slider (line ~69):
```html
        <!-- Seek slider -->
        <input type="range" id="ep-seek" class="fe-seek" min="0" max="0" value="0">

        <!-- Sync cam row -->
```

Insert the zoom row between seek slider and sync cam row:
```html
        <!-- Seek slider -->
        <input type="range" id="ep-seek" class="fe-seek" min="0" max="0" value="0">

        <!-- Zoom controls -->
        <div style="display:flex;align-items:center;gap:.5rem;margin:.25rem 0">
          <span style="font-size:.72rem;color:var(--text-dim);flex-shrink:0">Zoom</span>
          <input type="range" id="ep-zoom-3d" min="50" max="300" step="10" value="100"
                 style="flex:1;accent-color:var(--accent)">
          <span id="ep-zoom-3d-pct"
                style="font-family:var(--mono);font-size:.72rem;color:var(--text-dim);
                       width:3rem;text-align:right;flex-shrink:0">100%</span>
        </div>

        <!-- Sync cam row -->
```

- [ ] **Step 2: Add zoom reset in `openPlayer()` in `enhanced_player.js`**

Find the end of `openPlayer()` — the line `await _epLoadFrame(0);` at line ~62. Insert the zoom reset **before** that call:

Find:
```javascript
  const extractBtn = document.getElementById("ep-extract-btn");
  if (extractBtn) extractBtn.disabled = false;

  await _epLoadFrame(0);
```

Replace with:
```javascript
  const extractBtn = document.getElementById("ep-extract-btn");
  if (extractBtn) extractBtn.disabled = false;

  const zoomEl  = document.getElementById("ep-zoom-3d");
  const zoomPct = document.getElementById("ep-zoom-3d-pct");
  const camDisp = document.getElementById("cam-displays");
  if (zoomEl)  zoomEl.value = 100;
  if (zoomPct) zoomPct.textContent = "100%";
  if (camDisp) camDisp.style.transform = "";

  await _epLoadFrame(0);
```

- [ ] **Step 3: Add zoom event listener in `DOMContentLoaded` in `enhanced_player.js`**

Find the end of the `DOMContentLoaded` block. After the `ep-step` change listener (around line 238) and before the keyboard shortcuts block, add:

Find:
```javascript
  // Step size input — sync to module var
  document.getElementById("ep-step")?.addEventListener("change", (e) => {
    _stepSize = Math.max(1, parseInt(e.target.value, 10) || 10);
  });

  // Keyboard shortcuts
```

Replace with:
```javascript
  // Step size input — sync to module var
  document.getElementById("ep-step")?.addEventListener("change", (e) => {
    _stepSize = Math.max(1, parseInt(e.target.value, 10) || 10);
  });

  // Zoom slider
  document.getElementById("ep-zoom-3d")?.addEventListener("input", (e) => {
    const v       = parseInt(e.target.value, 10);
    const camDisp = document.getElementById("cam-displays");
    const pct     = document.getElementById("ep-zoom-3d-pct");
    if (camDisp) camDisp.style.transform       = v === 100 ? "" : `scale(${v / 100})`;
    if (camDisp) camDisp.style.transformOrigin = "center top";
    if (pct)     pct.textContent               = `${v}%`;
  });

  // Keyboard shortcuts
```

- [ ] **Step 4: Build and visually verify**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
docker compose build dlc-3d && docker compose up -d dlc-3d
```

Open `http://172.26.0.5:5050/dlc-3d/`. Load a project, select a video:
- Zoom slider is visible below the seek bar, reads "100%"
- Drag to 200%: viewer scales up symmetrically (left and right equally), extends beyond card boundary, percentage shows "200%"
- Drag to 50%: viewer shrinks, correctly contained, shows "50%"
- Load a new video: slider resets to 100%, viewer transform cleared
- Controls below the viewer (extract button, frame counter) stay in their original positions at all zoom levels

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/templates/partials/card_3d_extract.html dlc-3D/src/static/enhanced_player.js
git commit -m "feat: add zoom slider to DLC-3D viewer, resets on new video load"
```

---

## Task 3: Ghost Browse Arrow Fix

The ghost artifact appears because the flex container with Browse button and path input is rendered in the DOM even when both children are `display:none`. Some browsers render a native autocomplete indicator on a hidden `<input type="text">`. Fix: wrap the row in `id="dlc3d-browse-row"` with `display:none` by default. The Browse button no longer needs its own `display:none`. Update `_loadProject` and `_resetExtractorUI` in `dlc_3d.js` to toggle the row.

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_3d_extract.html`
- Modify: `dlc-3D/src/static/dlc_3d.js`

- [ ] **Step 1: Update the browse row HTML in `card_3d_extract.html`**

Find (lines 14–23):
```html
        <div style="display:flex;align-items:center;gap:.4rem;margin-bottom:.35rem">
          <button id="dlc3d-browse-btn" class="btn-sm btn-server-pick"
                  style="display:none;flex-shrink:0" title="Browse files">Browse</button>
          <input id="dlc3d-path-input" type="text"
                 style="display:none;flex:1;font-size:.72rem;font-family:var(--mono);
                        padding:.2rem .4rem;background:var(--surface-2);
                        border:1px solid var(--border);border-radius:4px;color:var(--text);
                        min-width:0"
                 placeholder="Type or paste a path, then press Enter">
        </div>
```

Replace with:
```html
        <div id="dlc3d-browse-row"
             style="display:none;align-items:center;gap:.4rem;margin-bottom:.35rem">
          <button id="dlc3d-browse-btn" class="btn-sm btn-server-pick"
                  style="flex-shrink:0" title="Browse files">Browse</button>
          <input id="dlc3d-path-input" type="text" autocomplete="off"
                 style="display:none;flex:1;font-size:.72rem;font-family:var(--mono);
                        padding:.2rem .4rem;background:var(--surface-2);
                        border:1px solid var(--border);border-radius:4px;color:var(--text);
                        min-width:0"
                 placeholder="Type or paste a path, then press Enter">
        </div>
```

Key changes:
- Outer div gets `id="dlc3d-browse-row"` and `display:none` (not `display:flex`)
- Browse button loses its `style="display:none;..."` (parent manages visibility)
- Path input gains `autocomplete="off"`

- [ ] **Step 2: Update `_loadProject` in `dlc_3d.js`**

Find (line ~97–98):
```javascript
  _projectPath = data.project_path;
  document.getElementById("dlc3d-browse-btn").style.display = "";
```

Replace with:
```javascript
  _projectPath = data.project_path;
  const browseRow = document.getElementById("dlc3d-browse-row");
  if (browseRow) browseRow.style.display = "flex";
```

- [ ] **Step 3: Update `_resetExtractorUI` in `dlc_3d.js`**

Find (lines ~54–57):
```javascript
  const browseBtn = document.getElementById("dlc3d-browse-btn");
  if (browseBtn) browseBtn.style.display = "none";
  const pathInput = document.getElementById("dlc3d-path-input");
  if (pathInput) { pathInput.style.display = "none"; pathInput.value = ""; }
```

Replace with:
```javascript
  const browseRow = document.getElementById("dlc3d-browse-row");
  if (browseRow) browseRow.style.display = "none";
  const pathInput = document.getElementById("dlc3d-path-input");
  if (pathInput) { pathInput.style.display = "none"; pathInput.value = ""; }
```

- [ ] **Step 4: Build and visually verify**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
docker compose build dlc-3d && docker compose up -d dlc-3d
```

Open `http://172.26.0.5:5050/dlc-3d/`. Before loading a project:
- **No ghost dropdown arrow** visible anywhere in the source section — just the empty message "Load a DLC project via Manage DLC Project"

Load a project:
- Browse button appears (no arrow artifact)
- Click Browse: path input + file list appear
- Click Browse again to close: both collapse cleanly

- [ ] **Step 5: Run full E2E test suite to confirm no regressions**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/e2e/ -v
```

Expected: 9 passed, 0 failed

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/templates/partials/card_3d_extract.html dlc-3D/src/static/dlc_3d.js
git commit -m "fix: hide entire browse-row before project loads to eliminate ghost dropdown arrow"
```

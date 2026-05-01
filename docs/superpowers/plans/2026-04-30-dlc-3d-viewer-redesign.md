# DLC-3D Viewer Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the DLC-3D Frame Extractor UI in line with existing webapp patterns — Project Manager-style file browser (SVG icons + dedicated Up button) and clip-cutter-style compact zoom overlay with width-based scaling that pushes controls down rather than covering them.

**Architecture:** Two independent frontend tasks. Task 1 swaps the inline emoji-based file browser for the Project Manager's SVG-icon `.fe-video-item` pattern with an Up button alongside the path input. Task 2 replaces the current full-width-row + `transform:scale` zoom with a compact absolute-positioned overlay that uses `width:%` + `margin-left:-%` to grow `#cam-displays` symmetrically; this is layout-affecting so controls below shift down naturally and never get covered.

**Tech Stack:** HTML (Jinja2 partial), CSS (flexbox, aspect-ratio, position:absolute), ES6 modules (`dlc_3d.js`, `enhanced_player.js`), Docker Compose for build/test (`docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml`).

---

## File Map

| File | What changes |
|------|-------------|
| `dlc-3D/src/templates/partials/card_3d_extract.html` | Task 1: Up button in browse row. Task 2: remove old zoom row, add overlay inside `#cam-displays`. |
| `dlc-3D/src/static/dlc_3d.js` | Task 1: SVG icons in `_browseDir`, remove in-list `↑ ..`, wire Up button + reset/select handlers. |
| `dlc-3D/src/static/dlc_3d.css` | Task 2: `position:relative` on `#cam-displays`, add `#ep-zoom-controls` overlay styles. |
| `dlc-3D/src/static/enhanced_player.js` | Task 2: replace transform-based zoom with width+margin-left scaling, update `openPlayer()` reset. |

---

## Task 1: File browser matches Project Manager pattern

Replace emoji icons (📁, 🎬) with SVG icons identical to the main webapp's Project Manager browser. Move the up-folder navigation from an in-list "↑ .." row to a dedicated `↑ Up` button next to the path input — matching `card_dlc_project.html`.

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_3d_extract.html`
- Modify: `dlc-3D/src/static/dlc_3d.js`

- [ ] **Step 1: Add `↑ Up` button to the browse row HTML**

In `dlc-3D/src/templates/partials/card_3d_extract.html`, find the browse row block (lines ~14–24):

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
          <button id="dlc3d-browse-up" class="btn-sm"
                  style="display:none;flex-shrink:0;font-family:var(--mono)"
                  title="Up one folder">↑ Up</button>
        </div>
```

Only addition: the `<button id="dlc3d-browse-up">` element at the end.

- [ ] **Step 2: Add `_browserParentPath` module variable in `dlc_3d.js`**

In `dlc-3D/src/static/dlc_3d.js`, find the existing module state block near the top (around line 8):

```javascript
let _projectPath        = null;
let _activeSession      = null;
let _activeVideo        = null;
let _loadToken          = 0;
let _browserCurrentPath = null;
```

Add after `_browserCurrentPath`:

```javascript
let _projectPath        = null;
let _activeSession      = null;
let _activeVideo        = null;
let _loadToken          = 0;
let _browserCurrentPath = null;
let _browserParentPath  = null;
```

- [ ] **Step 3: Replace `_browseDir` body to use SVG icons + capture parent path**

In `dlc-3D/src/static/dlc_3d.js`, replace the entire `_browseDir` function (lines ~104–175) with:

```javascript
async function _browseDir(path) {
  const browser = document.getElementById("dlc3d-file-browser");
  const empty   = document.getElementById("dlc3d-session-empty");
  browser.innerHTML = '<span style="font-size:.8rem;color:var(--text-dim)">Loading…</span>';
  browser.style.display = "";
  if (empty) empty.style.display = "none";

  let data;
  try {
    const url = path
      ? `/dlc-3d/browse?path=${encodeURIComponent(path)}`
      : "/dlc-3d/browse";
    const resp = await fetch(url);
    data = await resp.json();
    if (!resp.ok) {
      const errMsg = document.createElement("span");
      errMsg.style.cssText = "font-size:.8rem;color:var(--text-dim)";
      errMsg.textContent = data.error || "Browse error";
      browser.replaceChildren(errMsg);
      return;
    }
  } catch (e) {
    browser.innerHTML = `<span style="font-size:.8rem;color:var(--text-dim)">Network error</span>`;
    return;
  }

  _browserCurrentPath = data.path;
  _browserParentPath  = data.parent || null;
  const pathInput = document.getElementById("dlc3d-path-input");
  if (pathInput) pathInput.value = data.path;
  const upBtn = document.getElementById("dlc3d-browse-up");
  if (upBtn) upBtn.disabled = !_browserParentPath;
  browser.innerHTML = "";

  for (const entry of data.entries || []) {
    const row = document.createElement("div");
    row.className = "fe-video-item";
    row.style.cursor = "pointer";

    if (entry.type === "dir") {
      row.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
        </svg>
        <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${entry.name}/</span>`;
      row.addEventListener("click", () => _browseDir(_browserCurrentPath + "/" + entry.name));
    } else if (entry.type === "file") {
      row.dataset.videoPath = _browserCurrentPath + "/" + entry.name;
      row.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0">
          <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/>
          <line x1="7" y1="2" x2="7" y2="22"/>
          <line x1="17" y1="2" x2="17" y2="22"/>
          <line x1="2" y1="12" x2="22" y2="12"/>
          <line x1="2" y1="7" x2="7" y2="7"/>
          <line x1="2" y1="17" x2="7" y2="17"/>
          <line x1="17" y1="17" x2="22" y2="17"/>
          <line x1="17" y1="7" x2="22" y2="7"/>
        </svg>
        <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${entry.name}</span>`;
      row.addEventListener("click", () => _selectVideo(row.dataset.videoPath));
    } else {
      continue;
    }
    browser.appendChild(row);
  }

  if (browser.children.length === 0) {
    const msg = document.createElement("span");
    msg.style.cssText = "font-size:.8rem;color:var(--text-dim)";
    msg.textContent = "No files found.";
    browser.appendChild(msg);
  }
}
```

Key differences from the previous version:
- No more in-list `↑ ..` row — handled by the dedicated Up button.
- Folders use a folder SVG icon; files use a film SVG icon (no emoji).
- Captures `data.parent` into `_browserParentPath` and toggles the Up button's `disabled` state.

- [ ] **Step 4: Update Browse button toggle to also show/hide the Up button**

In `dlc-3D/src/static/dlc_3d.js`, find the Browse button click handler in `DOMContentLoaded` (around lines 308–320):

```javascript
  document.getElementById("dlc3d-browse-btn")?.addEventListener("click", () => {
    const browser   = document.getElementById("dlc3d-file-browser");
    const pathInput = document.getElementById("dlc3d-path-input");
    if (browser.style.display === "none") {
      if (pathInput) pathInput.style.display = "";
      _browseDir(_browserCurrentPath || _projectPath);
    } else {
      browser.style.display = "none";
      if (pathInput) pathInput.style.display = "none";
      const empty = document.getElementById("dlc3d-session-empty");
      if (empty) empty.style.display = "";
    }
  });
```

Replace with:

```javascript
  document.getElementById("dlc3d-browse-btn")?.addEventListener("click", () => {
    const browser   = document.getElementById("dlc3d-file-browser");
    const pathInput = document.getElementById("dlc3d-path-input");
    const upBtn     = document.getElementById("dlc3d-browse-up");
    if (browser.style.display === "none") {
      if (pathInput) pathInput.style.display = "";
      if (upBtn)     upBtn.style.display     = "";
      _browseDir(_browserCurrentPath || _projectPath);
    } else {
      browser.style.display = "none";
      if (pathInput) pathInput.style.display = "none";
      if (upBtn)     upBtn.style.display     = "none";
      const empty = document.getElementById("dlc3d-session-empty");
      if (empty) empty.style.display = "";
    }
  });
```

- [ ] **Step 5: Add Up button click handler**

In `dlc-3D/src/static/dlc_3d.js`, in `DOMContentLoaded`, immediately after the path-input keydown listener (around line 327), add:

```javascript
  document.getElementById("dlc3d-browse-up")?.addEventListener("click", () => {
    if (_browserParentPath) _browseDir(_browserParentPath);
  });
```

The full block now reads:

```javascript
  document.getElementById("dlc3d-path-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const v = e.target.value.trim();
      if (v) _browseDir(v);
    }
  });

  document.getElementById("dlc3d-browse-up")?.addEventListener("click", () => {
    if (_browserParentPath) _browseDir(_browserParentPath);
  });
```

- [ ] **Step 6: Hide Up button in `_resetExtractorUI` and `_selectVideo`**

In `dlc-3D/src/static/dlc_3d.js`, find `_resetExtractorUI` (around lines 43–61). The current body resets path input but not the Up button. Find this section:

```javascript
  const browseRow = document.getElementById("dlc3d-browse-row");
  if (browseRow) browseRow.style.display = "none";
  const pathInput = document.getElementById("dlc3d-path-input");
  if (pathInput) { pathInput.style.display = "none"; pathInput.value = ""; }
```

Replace with:

```javascript
  const browseRow = document.getElementById("dlc3d-browse-row");
  if (browseRow) browseRow.style.display = "none";
  const pathInput = document.getElementById("dlc3d-path-input");
  if (pathInput) { pathInput.style.display = "none"; pathInput.value = ""; }
  const upBtn = document.getElementById("dlc3d-browse-up");
  if (upBtn) upBtn.style.display = "none";
  _browserParentPath = null;
```

Then find `_selectVideo` (around lines 179–218). Find this section:

```javascript
  const pathInput = document.getElementById("dlc3d-path-input");
  if (pathInput) pathInput.style.display = "none";
```

Replace with:

```javascript
  const pathInput = document.getElementById("dlc3d-path-input");
  if (pathInput) pathInput.style.display = "none";
  const upBtn = document.getElementById("dlc3d-browse-up");
  if (upBtn) upBtn.style.display = "none";
```

- [ ] **Step 7: Build, restart container, and visually verify**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d
docker compose up -d dlc-3d
```

Open the webapp, navigate to the 3D Frame Extractor:
- Load a project → Browse button appears, no Up button visible yet
- Click Browse → path input AND `↑ Up` button both appear
- Folder rows show a folder SVG icon (not 📁); video file rows show a film SVG icon (not 🎬)
- No `↑  ..` row inside the file list
- Click `↑ Up` → navigates one folder up; button is disabled at filesystem root
- Type a path + Enter → still works
- Click a video file → player opens, Up button hides
- Click Browse again → path input + Up button reappear at the previously-visited directory

- [ ] **Step 8: Commit**

```bash
git add dlc-3D/src/templates/partials/card_3d_extract.html dlc-3D/src/static/dlc_3d.js
git commit -m "feat: match DLC-3D file browser to Project Manager (SVG icons + Up button)"
```

---

## Task 2: Compact zoom overlay + width-based scaling

Replace the full-width zoom row (which uses `transform:scale` and overflows onto controls below) with a compact overlay anchored top-right inside `#cam-displays`. The zoom value sets `#cam-displays` `width:%` and `margin-left:-%/2` so the viewer grows symmetrically and pushes the controls below downward — never covering them.

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_3d_extract.html`
- Modify: `dlc-3D/src/static/dlc_3d.css`
- Modify: `dlc-3D/src/static/enhanced_player.js`

- [ ] **Step 1: Remove the old zoom row from HTML**

In `dlc-3D/src/templates/partials/card_3d_extract.html`, find the existing zoom row (after the seek slider, around lines 71–80):

```html
        <!-- Zoom controls -->
        <div style="display:flex;align-items:center;gap:.5rem;margin:.25rem 0">
          <span style="font-size:.72rem;color:var(--text-dim);flex-shrink:0">Zoom</span>
          <input type="range" id="ep-zoom-3d" min="50" max="300" step="10" value="100"
                 style="flex:1;accent-color:var(--accent)">
          <span id="ep-zoom-3d-pct"
                style="font-family:var(--mono);font-size:.72rem;color:var(--text-dim);
                       width:3rem;text-align:right;flex-shrink:0">100%</span>
        </div>
```

Delete the entire `<!-- Zoom controls -->` block. The seek slider line above and the `<!-- Sync cam row -->` block below should now be adjacent, separated by a blank line.

- [ ] **Step 2: Add the zoom overlay inside `#cam-displays`**

In the same file, find the `#cam-displays` opening tag (around line 37):

```html
        <div id="cam-displays">
          <div class="cam-wrap" id="cam1-wrap">
```

Insert the zoom overlay as the first child of `#cam-displays`:

```html
        <div id="cam-displays">
          <div id="ep-zoom-controls">
            <span style="font-size:10px">🔍</span>
            <input type="range" id="ep-zoom-3d" min="50" max="200" step="10" value="100">
            <span id="ep-zoom-3d-pct">100%</span>
          </div>
          <div class="cam-wrap" id="cam1-wrap">
```

(Note: range max changed from 300 to 200 to match clip-cutter.)

- [ ] **Step 3: Add `position:relative` to `#cam-displays` and overlay styles in CSS**

In `dlc-3D/src/static/dlc_3d.css`, find the `#cam-displays` rule (around lines 7–13):

```css
#dlc-3d-extract-card #cam-displays {
  display: flex;
  gap: .5rem;
  margin-bottom: .5rem;
  aspect-ratio: 16 / 9;
  align-items: stretch;
}
```

Replace with:

```css
#dlc-3d-extract-card #cam-displays {
  display: flex;
  gap: .5rem;
  margin-bottom: .5rem;
  aspect-ratio: 16 / 9;
  align-items: stretch;
  position: relative;
}

#dlc-3d-extract-card #ep-zoom-controls {
  position: absolute;
  top: 4px;
  right: 6px;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: var(--text-dim);
  background: rgba(0, 0, 0, 0.5);
  padding: 2px 6px;
  border-radius: 4px;
}

#dlc-3d-extract-card #ep-zoom-controls input {
  width: 60px;
  accent-color: var(--accent);
}

#dlc-3d-extract-card #ep-zoom-controls #ep-zoom-3d-pct {
  font-family: var(--mono);
  min-width: 2.5rem;
  text-align: right;
}
```

- [ ] **Step 4: Replace the zoom listener in `enhanced_player.js`**

In `dlc-3D/src/static/enhanced_player.js`, find the existing zoom block in `DOMContentLoaded` (around lines 249–257):

```javascript
  // Zoom slider
  const _zoomCamDisp = document.getElementById("cam-displays");
  if (_zoomCamDisp) _zoomCamDisp.style.transformOrigin = "center top";
  document.getElementById("ep-zoom-3d")?.addEventListener("input", (e) => {
    const v   = parseInt(e.target.value, 10);
    const pct = document.getElementById("ep-zoom-3d-pct");
    if (_zoomCamDisp) _zoomCamDisp.style.transform = v === 100 ? "" : `scale(${v / 100})`;
    if (pct)          pct.textContent               = `${v}%`;
  });
```

Replace with:

```javascript
  // Zoom slider
  document.getElementById("ep-zoom-3d")?.addEventListener("input", (e) => {
    const v       = parseInt(e.target.value, 10);
    const camDisp = document.getElementById("cam-displays");
    const pct     = document.getElementById("ep-zoom-3d-pct");
    if (camDisp) {
      camDisp.style.width      = v === 100 ? "" : `${v}%`;
      camDisp.style.marginLeft = v === 100 ? "" : `${(100 - v) / 2}%`;
    }
    if (pct) pct.textContent = `${v}%`;
  });
```

The `transformOrigin` line and the `_zoomCamDisp` cached reference are removed entirely — width/margin scaling does not need them.

- [ ] **Step 5: Update the `openPlayer()` zoom reset**

In `dlc-3D/src/static/enhanced_player.js`, find the zoom reset block in `openPlayer()` (around lines 62–67):

```javascript
  const zoomEl  = document.getElementById("ep-zoom-3d");
  const zoomPct = document.getElementById("ep-zoom-3d-pct");
  const camDisp = document.getElementById("cam-displays");
  if (zoomEl)  zoomEl.value = 100;
  if (zoomPct) zoomPct.textContent = "100%";
  if (camDisp) camDisp.style.transform = "";
```

Replace with:

```javascript
  const zoomEl  = document.getElementById("ep-zoom-3d");
  const zoomPct = document.getElementById("ep-zoom-3d-pct");
  const camDisp = document.getElementById("cam-displays");
  if (zoomEl)  zoomEl.value = 100;
  if (zoomPct) zoomPct.textContent = "100%";
  if (camDisp) { camDisp.style.width = ""; camDisp.style.marginLeft = ""; }
```

- [ ] **Step 6: Build, restart container, and visually verify**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d
docker compose up -d dlc-3d
```

Load a project, select a video, then:
- Compact zoom slider visible top-right of the viewer (semitransparent dark background, 🔍 icon, ~60px slider, "100%" readout)
- The OLD full-width zoom row below the seek bar is gone
- Drag to 200%: viewer becomes 2× wide and 2× tall, **centered** (so it overflows equally left and right beyond the card width), and the seek bar / sync cam row / extract button below all **shift down** with it — every control still clickable, page scrolls if needed
- Drag to 50%: viewer shrinks centered, controls move up
- Drag back to 100%: viewer returns to natural position, controls return to original positions
- Toggle Sync Cam at any zoom level: cam1 does NOT crop or change height (Task 1 fix from previous spec preserved)
- Load a new video: zoom resets to 100%

- [ ] **Step 7: Run E2E test suite to confirm no regressions**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/e2e/ -v
```

Expected: 9 passed, 0 failed.

- [ ] **Step 8: Commit**

```bash
git add dlc-3D/src/templates/partials/card_3d_extract.html \
        dlc-3D/src/static/dlc_3d.css \
        dlc-3D/src/static/enhanced_player.js
git commit -m "feat: replace zoom row with compact overlay using width-based scaling"
```

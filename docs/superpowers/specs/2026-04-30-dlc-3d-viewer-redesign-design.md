# DLC-3D Viewer Redesign — Design Spec

**Date:** 2026-04-30
**Status:** Approved

## Goal

Bring the DLC-3D Frame Extractor's UI into line with existing patterns from the main webapp:
1. File browser should match the Project Manager's "Browse User Data" GUI (SVG icons, Up button next to path input)
2. Zoom should not cover controls — when zoomed in, controls shift downward and stay accessible (clip-cutter overlay pattern, adapted)
3. Zoom slider should be compact (clip-cutter style: small overlay top-right, ~50px wide), not a full-width row
4. Zoom range: 50–200% (matches clip-cutter)

---

## Section 1: File browser matches Project Manager pattern

### Reference files

- `/home/sam/docker-images/deeplabcut-webapp-docker/src/templates/partials/card_dlc_project.html` (lines 5–36)
- `/home/sam/docker-images/deeplabcut-webapp-docker/src/static/js/dlc_project.js` (lines 79–138)

### HTML changes (`card_3d_extract.html`)

Add an `↑ Up` button to the right of the path input in the existing browse row:

```html
<div id="dlc3d-browse-row"
     style="display:none;align-items:center;gap:.4rem;margin-bottom:.35rem">
  <button id="dlc3d-browse-btn" class="btn-sm btn-server-pick"
          style="flex-shrink:0" title="Browse files">Browse</button>
  <input id="dlc3d-path-input" type="text" autocomplete="off"
         style="flex:1;display:none;font-size:.72rem;font-family:var(--mono);
                padding:.2rem .4rem;background:var(--surface-2);
                border:1px solid var(--border);border-radius:4px;color:var(--text);
                min-width:0"
         placeholder="Type or paste a path, then press Enter">
  <button id="dlc3d-browse-up" class="btn-sm"
          style="display:none;flex-shrink:0;font-family:var(--mono)"
          title="Up one folder">↑ Up</button>
</div>
```

The Up button's `display:none` is toggled by the same code that toggles the path input — both appear together when Browse is open, both hide when closed.

### JS changes (`dlc_3d.js`)

**`_browseDir`**: replace emoji-based row creation with SVG icons matching Project Manager.

Remove the in-list `↑ ..` row (now handled by the dedicated Up button). Replace the file/folder row creation with:

```javascript
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
```

**Up button wiring** (in `DOMContentLoaded`): when clicked, navigate to `data.parent` (most recently fetched). The `_browseDir` function already stores `data.parent` implicitly — capture the parent path on each fetch in a module-level `_browserParentPath` variable, then have the Up button click handler call `_browseDir(_browserParentPath)` if it's truthy.

```javascript
// Module-level state addition:
let _browserParentPath = null;

// In _browseDir, after `_browserCurrentPath = data.path;`:
_browserParentPath = data.parent || null;
const upBtn = document.getElementById("dlc3d-browse-up");
if (upBtn) upBtn.disabled = !_browserParentPath;

// In DOMContentLoaded:
document.getElementById("dlc3d-browse-up")?.addEventListener("click", () => {
  if (_browserParentPath) _browseDir(_browserParentPath);
});
```

**Browse button toggle**: also show/hide the Up button alongside the path input:
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

**`_selectVideo`** and **`_resetExtractorUI`**: also hide the Up button when collapsing/resetting (mirror the existing path-input hiding logic).

---

## Section 2: Compact zoom overlay + width-based scaling

### Reference files

- `/home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter/templates/clip_cutter.html` (lines 895–899) — zoom overlay HTML
- `/home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter/static/enhanced_player.js` (lines 1356–1361) — zoom listener

### Behavior

- Zoom slider is a compact overlay anchored top-right of `#cam-displays` (50px wide range input + magnifier emoji + percentage).
- Slider value sets `#cam-displays` width as a percentage. `aspect-ratio: 16/9` makes the height grow proportionally.
- Negative `margin-left` keeps the growing block centered horizontally.
- This is a layout-affecting change (not `transform: scale`) — controls below the viewer **shift down** with it; nothing gets covered.
- Range: 50 to 200, default 100, step 10.

### HTML changes (`card_3d_extract.html`)

**Remove** the existing zoom row below the seek slider (the `<!-- Zoom controls -->` block added in the previous task).

**Add** a compact overlay inside `#cam-displays` as the first child:
```html
<div id="cam-displays">
  <div id="ep-zoom-controls">
    <span style="font-size:10px">🔍</span>
    <input type="range" id="ep-zoom-3d" min="50" max="200" step="10" value="100">
    <span id="ep-zoom-3d-pct">100%</span>
  </div>
  <div class="cam-wrap" id="cam1-wrap">...</div>
  <div class="cam-wrap" id="ep-cam2-wrap" style="display:none">...</div>
</div>
```

### CSS changes (`dlc_3d.css`)

`#cam-displays` already has `aspect-ratio: 16/9`, `align-items: stretch`, `display: flex`, `gap: .5rem`, `margin-bottom: .5rem` from Task 1. Add `position: relative` so the zoom overlay anchors correctly:

```css
#dlc-3d-extract-card #cam-displays {
  display: flex;
  gap: .5rem;
  margin-bottom: .5rem;
  aspect-ratio: 16 / 9;
  align-items: stretch;
  position: relative;       /* ADD */
}
```

`#dlc-3d-extract-card { overflow: visible }` from Task 1 stays as-is — width-based zoom needs the card to allow horizontal overflow when the viewer grows past its natural width.

Add overlay styles:

```css
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

(60px slider is slightly wider than clip-cutter's 50px to give 10% step granularity; semitransparent background ensures readability over dark video frames.)

### JS changes (`enhanced_player.js`)

**Remove** the existing zoom listener that uses `transform: scale` and the old `transformOrigin` initialization.

**Add** new listener using width + margin-left:

```javascript
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

**`openPlayer()` reset** — replace the `transform`/`transformOrigin` reset with width/marginLeft reset:

```javascript
const zoomEl  = document.getElementById("ep-zoom-3d");
const zoomPct = document.getElementById("ep-zoom-3d-pct");
const camDisp = document.getElementById("cam-displays");
if (zoomEl)  zoomEl.value = 100;
if (zoomPct) zoomPct.textContent = "100%";
if (camDisp) { camDisp.style.width = ""; camDisp.style.marginLeft = ""; }
```

### Behavior table

| Slider value | `#cam-displays` width | margin-left | Effect |
|--------------|----------------------|-------------|--------|
| 50  | 50%  | +25%  | viewer half-size, centered, controls move up |
| 100 | (cleared) | (cleared) | natural size and position |
| 150 | 150% | -25% | viewer 1.5× wider/taller, centered, controls shift down |
| 200 | 200% | -50% | viewer 2× wider/taller, centered, all controls still accessible (page may scroll) |

---

## Section 3: No additional card-level changes

`#dlc-3d-extract-card { overflow: visible }` from Task 1 is retained — it allows the growing cam-displays to extend past the card's natural width without clipping.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dlc-3D/src/templates/partials/card_3d_extract.html` |
| Modify | `dlc-3D/src/static/dlc_3d.css` |
| Modify | `dlc-3D/src/static/dlc_3d.js` |
| Modify | `dlc-3D/src/static/enhanced_player.js` |

---

## Testing

1. `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose build dlc-3d && docker compose up -d dlc-3d`
2. Open `http://localhost:5000/dlc-3d/` (or the user-facing URL)
3. **File browser**:
   - Load a project, click Browse — path input + Up button appear together
   - Folders show with a folder SVG icon, video files show with a film SVG icon (no emoji)
   - Up button navigates one folder up; disabled at filesystem root
   - Path input Enter still works
4. **Zoom slider**:
   - Compact slider appears top-right of viewer with translucent background
   - Drag to 200%: cam-displays grows wider AND taller, **stays centered**, controls below shift down — all clickable
   - Drag to 50%: viewer shrinks centered, controls move up
   - Drag back to 100%: viewer returns to natural size
   - Load a new video: zoom resets to 100%
5. **Sync cam still works** (Task 1 fix preserved): toggle on/off — no crop, height stays locked at the displayed scale factor
6. `python -m pytest tests/e2e/ -v` → existing 9 tests still pass (no new tests; pure UI redesign)

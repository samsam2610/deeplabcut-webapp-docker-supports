# DLC-3D Viewer Fixes — Design Spec

**Date:** 2026-04-30
**Status:** Approved

## Goal

Fix three issues in the DLC-3D Frame Extractor viewer:
1. Toggling Sync Cam on/off/on crops and glitches the primary camera viewer
2. No way to enlarge the viewer — add a zoom slider that allows the dual-camera display to grow beyond the card boundary
3. A ghost dropdown arrow appears near the Browse button area before a project is loaded

---

## Section 1: Sync Cam toggle crop fix

### Root cause

`.cam-frame-wrap` has `aspect-ratio: 16/9`. This couples the element's **height to its width**. When cam2 appears, the flex row splits from 1 to 2 children: cam1 goes from 100% to 50% of the row's width. The `aspect-ratio` constraint then halves cam1's height proportionally. `overflow: hidden` clips the image during the layout reflow. Toggling on/off/on repeats this three times and makes the glitch obvious.

### Fix

Move `aspect-ratio: 16/9` from `.cam-frame-wrap` to `#cam-displays` (the parent flex row). This locks the **total viewer height** regardless of how many cameras are shown. Each `.cam-frame-wrap` fills its flex cell at `height: 100%` with `display: flex; align-items: center; justify-content: center`. Images switch from `width: 100%; height: auto` to `max-width: 100%; max-height: 100%; object-fit: contain` — they letterbox within their cell rather than cropping.

**Single cam:** `#cam-displays` is full card width × 9/16 height (e.g., 560×315). cam1 image fills the full cell at 16:9 — no letterboxing.

**Dual cam:** `#cam-displays` stays at the same 315px height. cam1 and cam2 each get 50% width (280px). Images letterbox to 280×157 within their 280×315 cells — smaller but never cropped, height never changes.

### CSS changes (`dlc_3d.css`)

```css
#dlc-3d-extract-card #cam-displays {
  display: flex;
  gap: .5rem;
  margin-bottom: .5rem;
  aspect-ratio: 16 / 9;          /* ADD — locks total height */
  align-items: stretch;           /* ADD — children fill height */
}

#dlc-3d-extract-card .cam-wrap {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  display: flex;                  /* ADD */
  flex-direction: column;         /* ADD */
}

#dlc-3d-extract-card .cam-frame-wrap {
  background: #000;
  border-radius: 4px;
  overflow: hidden;
  flex: 1;                        /* ADD — fills .cam-wrap height */
  display: flex;                  /* ADD */
  align-items: center;            /* ADD */
  justify-content: center;        /* ADD */
  /* REMOVE: aspect-ratio: 16 / 9 */
}

#dlc-3d-extract-card .cam-frame-wrap img {
  max-width: 100%;                /* was: width: 100% */
  max-height: 100%;               /* ADD */
  display: block;
  object-fit: contain;            /* ADD */
  /* REMOVE: height: auto */
}
```

---

## Section 2: Viewer zoom slider

### Behavior

A zoom row is added below the seek slider (before the sync-cam row). It contains:
- A label "Zoom"
- A range slider `#ep-zoom-3d` (min 50, max 300, step 10, default 100)
- A percentage readout `#ep-zoom-3d-pct`

Dragging the slider applies `transform: scale(v/100)` to `#cam-displays` with `transform-origin: center top`. Because CSS transform does not affect layout flow, the controls below the viewer remain in place; the cam-displays visually expands outward (symmetrically left/right from center) beyond the card boundary.

`openPlayer()` resets the slider to 100% and resets the transform whenever a new video is loaded.

### HTML changes (`card_3d_extract.html`)

Add after the seek slider (`<input type="range" id="ep-seek" ...>`):

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

### CSS changes (`dlc_3d.css`)

Allow the scaled cam-displays to visually overflow the card:

```css
#dlc-3d-extract-card {
  overflow: visible;
}
```

### JS changes (`enhanced_player.js`)

**In `openPlayer()`**, reset zoom after the frame-count fetch succeeds (before `_epLoadFrame(0)`):

```javascript
const zoomEl  = document.getElementById("ep-zoom-3d");
const zoomPct = document.getElementById("ep-zoom-3d-pct");
const camDisp = document.getElementById("cam-displays");
if (zoomEl)  zoomEl.value = 100;
if (zoomPct) zoomPct.textContent = "100%";
if (camDisp) camDisp.style.transform = "";
```

**In `DOMContentLoaded`**, add the zoom listener:

```javascript
document.getElementById("ep-zoom-3d")?.addEventListener("input", (e) => {
  const v      = parseInt(e.target.value, 10);
  const camDisp = document.getElementById("cam-displays");
  const pct     = document.getElementById("ep-zoom-3d-pct");
  if (camDisp) camDisp.style.transform = v === 100 ? "" : `scale(${v / 100})`;
  if (camDisp) camDisp.style.transformOrigin = "center top";
  if (pct)     pct.textContent = `${v}%`;
});
```

---

## Section 3: Ghost dropdown arrow fix

### Root cause

The flex container holding the Browse button and path input renders in the DOM before a project loads, even though both children are `display: none`. Some browsers render a small native autocomplete indicator on a hidden `<input type="text">` that has previously stored suggestions. The container also adds an unwanted `margin-bottom: .35rem` gap when empty.

### Fix

Give the flex container `id="dlc3d-browse-row"` and set it to `display: none` by default. Show it as `display: flex` from `_loadProject`; hide it in `_resetExtractorUI`. The Browse button no longer needs its own `display` toggling — the parent row handles visibility. Also add `autocomplete="off"` to the path input.

### HTML changes (`card_3d_extract.html`)

Replace the source-section flex row:

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

Key changes vs. current HTML:
- Outer div gets `id="dlc3d-browse-row"` and `display:none` (not `display:flex`)
- Browse button loses its `display:none` inline style (parent manages visibility)
- Path input gains `autocomplete="off"`

### JS changes (`dlc_3d.js`)

**`_loadProject`**: replace `document.getElementById("dlc3d-browse-btn").style.display = ""` with:

```javascript
const browseRow = document.getElementById("dlc3d-browse-row");
if (browseRow) browseRow.style.display = "flex";
```

**`_resetExtractorUI`**: replace the Browse button block:

```javascript
// OLD:
const browseBtn = document.getElementById("dlc3d-browse-btn");
if (browseBtn) browseBtn.style.display = "none";

// NEW:
const browseRow = document.getElementById("dlc3d-browse-row");
if (browseRow) browseRow.style.display = "none";
```

The path input hide (`pathInput.style.display = "none"`) in `_resetExtractorUI` stays unchanged — it still needs its own control for the Browse toggle.

Also update the null-check in the Browse button click handler: the `if (pathInput) pathInput.style.display = "none/flex"` lines stay as-is since they control the input separately from the row.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dlc-3D/src/static/dlc_3d.css` |
| Modify | `dlc-3D/src/templates/partials/card_3d_extract.html` |
| Modify | `dlc-3D/src/static/enhanced_player.js` |
| Modify | `dlc-3D/src/static/dlc_3d.js` |

---

## Testing

1. `docker compose build dlc-3d && docker compose up -d dlc-3d`
2. Open extractor — no ghost arrow visible in the source section
3. Load project — Browse button appears, no arrow artifact
4. Select a video — player loads at correct size
5. Toggle Sync Cam on → both cams appear side by side, cam1 does NOT crop or glitch, viewer height stays constant
6. Toggle Sync Cam off → cam1 returns to full width, no glitch
7. Toggle on/off/on repeatedly — no crop, smooth
8. Drag zoom slider to 200% → both cams scale up symmetrically, extend beyond card boundary
9. Drag to 50% → cams shrink, still correctly laid out
10. Load a new video → zoom resets to 100%
11. `python -m pytest tests/e2e/ -v` → 9 passed (no backend changes, no new E2E tests needed)

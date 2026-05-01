# DLC-3D Frame Labeler — Per-Tile Viewer Size in Sync Mode

**Date:** 2026-05-01
**Module:** `dlc-3D/`
**Touches:** `src/templates/partials/card_frame_labeler.html`, `src/static/frame_labeler_3d.js`, `src/static/dlc_3d.css`

## Problem

In sync mode, all camera tiles share the row width equally (`flex: 1 1 0`). The global "Viewer size" slider (50–300%) scales the whole row uniformly. Two limitations:

1. The 300% cap is too small when users want to inspect one camera's frame closely.
2. There's no way to enlarge a single camera's tile without enlarging all of them. Users want to focus on one viewer (e.g., the one being actively labeled) while keeping the others visible but smaller.

## Goals

- Raise the global "Viewer size" max to **500%** (sync mode only).
- Give each tile its own size slider next to its `cam` label that grows that tile within the existing row width — other tiles shrink to compensate.
- Provide a one-click **Equalize** button to reset all per-tile weights to equal.
- Keep single-tile mode unchanged (range stays 50–300%, no per-tile sliders).

## Design

### Mechanism: flex-grow weights

Tiles already use `flex: 1 1 0`. Per-tile size becomes a **flex-grow weight** in the range **50–300, step 25, default 100**. With weights `[w₁, w₂, …, wₙ]` and row width `W`, tile `i` gets `W · wᵢ / Σw`. The row width itself is set by the global slider (capped at 500% in sync mode).

This means dragging one tile's slider grows that tile and shrinks the others proportionally, with no other slider physically moving. Equalize resets every weight to 100.

State lives on each tile element as `tile.dataset.weight` and is applied as inline `style.flexGrow`. Weights are **reset to 100** every time sync mode is turned on (matches the existing pattern where sibling tiles are torn down and rebuilt on sync toggle).

### UI changes — `card_frame_labeler.html`

**1. Global slider max in sync mode.** The slider's `max` attribute starts at `300` (single-tile default). When sync turns on, JS sets `max="500"`; when it turns off, JS sets `max="300"` and clamps the current value back into range.

**2. Equalize button** added inline in the controls bar, immediately after the global "Viewer size" label, hidden by default. Shown only when sync is on.

```html
<button id="fl3d-equalize-btn" class="btn-sm hidden"
        title="Reset all per-camera viewer sizes to equal">
  <svg width="12" height="12" viewBox="0 0 24 24" …>…</svg>
  Equalize
</button>
```

**3. Per-tile slider** added inside each tile's header. The header changes from a plain `<div class="fl3d-tile-label">cam0</div>` to a small flex row:

```html
<div class="fl3d-tile-header">
  <span class="fl3d-tile-label">cam0</span>
  <input type="range" class="fl3d-tile-size" min="50" max="300" step="25" value="100">
  <span class="fl3d-tile-size-val">100%</span>
</div>
```

The primary tile's header (which exists in static HTML) is updated to this structure. Sibling tiles already get their header generated in `_fl3dSyncRenderRow`; the template literal there is updated to include the slider markup.

The per-tile slider is **only visible when sync is on**. CSS rule: `.fl3d-tile-size, .fl3d-tile-size-val { display: none; }` by default; a `.fl3d-canvas-row.sync-on .fl3d-tile-size, …-val { display: inline-block; }` override flips them on. The row gets a `sync-on` class when sync is enabled, removed when disabled.

### JS changes — `frame_labeler_3d.js`

**1. Global slider clamp on sync toggle.** In the existing `fl3d-sync-frame` change handler:

- On **sync ON**: `flZoomInput.max = "500"`; `equalizeBtn.classList.remove("hidden")`; `row.classList.add("sync-on")`.
- On **sync OFF**: `flZoomInput.max = "300"`; if `flZoomInput.value > 300`, set value to 300, update `_flZoom` and label, refit; `equalizeBtn.classList.add("hidden")`; `row.classList.remove("sync-on")`.

**2. Per-tile slider wiring.** A single helper attaches the slider listener to each tile (primary and siblings). For the primary tile, called once at startup. For sibling tiles, called from `_fl3dRenderTile` after the tile is built (only when `tile.classList.contains("fl3d-tile-sibling")`, matching the existing once-per-startup vs. per-render pattern).

```js
function _fl3dWireTileSizeSlider(tile) {
  const slider = tile.querySelector(".fl3d-tile-size");
  const val    = tile.querySelector(".fl3d-tile-size-val");
  if (!slider) return;
  slider.addEventListener("input", () => {
    const w = parseInt(slider.value, 10);
    tile.dataset.weight = String(w);
    tile.style.flexGrow = String(w);
    val.textContent = w + "%";
    // Per-tile redraw — canvas display width changes, hit-test scaling
    // re-derives from getBoundingClientRect() so no recompute needed.
    if (tile.dataset.fname) _fl3dDrawTileMarkers(tile, tile.dataset.fname);
  });
}
```

On each new sibling tile created in `_fl3dSyncRenderRow`, set `tile.style.flexGrow = "100"` and `tile.dataset.weight = "100"` before calling `_fl3dWireTileSizeSlider(tile)`. The primary tile is initialized to weight 100 once at startup.

**3. Equalize button.** Click handler iterates `#fl3d-canvas-row .fl3d-tile`, sets each tile's weight back to 100 (slider value, label, dataset, `style.flexGrow`), then redraws each tile.

**4. Sync OFF cleanup.** When sync turns off, the existing code removes sibling tiles (`.fl3d-tile-sibling`). Add: reset the primary tile's weight to 100 (`flexGrow = "100"`, slider/label updated). This guarantees a clean state on the next sync ON.

### CSS — `dlc_3d.css`

```css
.fl3d-tile-header {
  display: flex;
  align-items: center;
  gap: .35rem;
  margin-bottom: 2px;
}
.fl3d-tile-label { font-size: .7rem; color: var(--text-dim); font-family: var(--mono); }
.fl3d-tile-size { width: 70px; accent-color: var(--accent); }
.fl3d-tile-size-val { font-size: .7rem; color: var(--text); min-width: 2.5rem; text-align: right; }
.fl3d-tile-size, .fl3d-tile-size-val { display: none; }
.fl3d-canvas-row.sync-on .fl3d-tile-size,
.fl3d-canvas-row.sync-on .fl3d-tile-size-val { display: inline-block; }
```

Existing `.fl3d-tile-label` rule is moved inside the new header structure (the wrapper takes over `margin-bottom: 2px`).

### Hit-test compatibility

The existing per-tile click/hover hit-test uses `canvas.getBoundingClientRect()` to derive the click→buffer scale (see `_fl3dCanvasClickToImage`). Because each tile's canvas is `width: 100%` of its tile, growing/shrinking the tile via flex-grow changes only the displayed size — buffer dimensions and the rect-based scale handle this for free. No hit-test code changes needed.

### Out of scope

- Persisting per-tile weights across sync toggles or page reloads.
- Per-tile sliders in single-tile mode.
- Drag-to-resize between tiles (could be a future enhancement; the slider is simpler and matches existing controls).

## Test plan

- Toggle sync ON: global slider max becomes 500, Equalize button appears, per-tile sliders appear next to each `cam` label.
- Drag the primary tile's slider to 300%: that tile grows; siblings shrink; row width unchanged.
- Drag a sibling's slider: same behavior, in the opposite direction.
- Click Equalize: all sliders snap back to 100%, tiles equal width.
- Set global slider to 500%: row spans wider than at 300% (reaches up to viewport-32px cap from `_fl3dFitRow`).
- Toggle sync OFF: per-tile sliders hidden, Equalize hidden, global slider max back to 300, value clamped if it was above 300.
- Toggle sync OFF then ON: all weights reset to 100 (no leftover state).
- Click and place markers on a sibling tile that has been resized to 50% / 300%: marker lands at the correct image coordinate.

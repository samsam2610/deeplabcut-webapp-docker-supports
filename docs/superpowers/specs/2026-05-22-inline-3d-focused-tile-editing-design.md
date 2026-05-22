# Inline 3D Focused-Tile Marker Editing — Design

**Date:** 2026-05-22
**Status:** Approved (pending implementation plan)
**Repo:** `deeplabcut-webapp-docker-supports/dlc-3D`, branch `feat/3d-inline-analysis`

## Context

This is **Spec 2 of a 3-part decomposition** (Spec 1 = 2D Finalize-analysis, done; Spec 3
= 3D Finalize-analysis, next). Today the inline 3D card (`src/static/inline_analysis_3d.js`,
`src/templates/partials/card_inline_analysis_3d.html`) can hand-edit markers on **cam0
(tile-0) only**. The edit-input handlers (`inline_analysis_3d.js:1418+`) are hardwired to
tile-0's overlay canvas (`#ia3d-overlay-canvas-0`), the global pose buffer
`_iaCurrentPoses`, and `_iaLocalEdits`. Sibling tiles already **display** markers (via
`Controller._renderTileMarkers`) and the `Tile`/`Controller` architecture already provides
per-tile `canvasEl`/`imgEl`/`pendingEdits`/layer `posesCache`, `focusTile(cam)` (click a
tile or press 1/2), and focus styling. What is missing is **edit input on the focused
non-tile-0 camera**.

Goal: generalize editing so the **focused** camera tile (any cam) is hand-editable,
modeled on `src/static/frame_labeler_3d.js`'s focused-cam tile-input pattern.

## Decision: mirror the frame labeler's intrinsic-canvas coordinate model

Per the brainstorm, we adopt the frame labeler's exact approach (not the inline card's
current display-pixel approach):

- Each tile's overlay canvas is sized to the **video's intrinsic resolution**:
  `canvas.width = img.naturalWidth; canvas.height = img.naturalHeight` (CSS keeps
  `width:100%`/`height:100%` so it visually scales). Markers and the frame image are then
  drawn in **image/video coordinates** directly.
- Pointer events map display→image coords via the bounding-rect ratio (frame labeler's
  `_fl3dCanvasClickToImage`):

  ```js
  function _ia3dCanvasToImage(canvas, e) {
    const rect = canvas.getBoundingClientRect();
    const sx = rect.width  > 0 ? canvas.width  / rect.width  : 1;
    const sy = rect.height > 0 ? canvas.height / rect.height : 1;
    return { x: (e.clientX - rect.left) * sx, y: (e.clientY - rect.top) * sy,
             scale: Math.max(sx, sy) };
  }
  ```

**Implication / risk (explicit):** the inline card currently sizes overlay canvases to
**display pixels** and scales marker draw by `canvasEl.width / naturalWidth` in
`_renderTileMarkers` (sibling path) and the tile-0 global render path. Switching to
intrinsic sizing means BOTH render paths must draw in image coords (drop the `sx/sy`
marker scaling; use `scale` only for the hit-test radius / on-screen marker px). This is a
coordinated rendering change with regression risk to the working cam0 display — the plan
sequences it carefully and the tests guard it.

## Architecture (all in `inline_analysis_3d.js`)

### 1. Intrinsic canvas sizing in the render paths
- `_renderTileMarkers(tile)`: set `tile.canvasEl.width = tile.imgEl.naturalWidth` (and
  height) instead of `offsetWidth`; draw markers at image coords (radius scaled for
  on-screen consistency by the display ratio). Applies to every tile including tile-0 so
  both paths share one coordinate model.
- The tile-0 global overlay render path (the `iaOverlayCanvas`/`iaFrameImg` block ~1081-1143)
  is migrated to the same intrinsic model (or routed through `_renderTileMarkers`) so cam0
  and cam1 are pixel-consistent.

### 2. Per-tile editing wiring — `Controller._wireTileEditing(tile)`
Wire each tile's `canvasEl` once (called from `init()` for tile-0 and `_addSibling()` for
siblings) with: `click` (select-or-place), `mousemove` (hover + drag), `mousedown` (drag
start), `mouseup` (drag flush), `contextmenu` (delete), `dblclick` (clear frame). Every
handler early-returns unless the tile is focused:

```js
if (tile.cam !== Controller.focusedCam) return;   // only focused tile accepts input
```

(except the render/hover-display parts, which run whenever the overlay is on — mirroring
Spec 1's gating discipline: display is never gated by focus, only mutation is).

### 3. Per-tile coord + hit-test + writes
- Coords via `_ia3dCanvasToImage(tile.canvasEl, e)` (above).
- Hit-test `_ia3dTileHitTest(tile, ix, iy, scale)` against the tile's **primary layer's
  `posesCache.get(currentFrame)`** plus the tile's `pendingEdits` for the current frame
  (image coords; radius = `(markerSize + 8) * scale`).
- Mutations write to **`tile.pendingEdits`** (tile-0 stays aliased to `_iaLocalEdits` via
  the existing `_iaBindTile0PendingEdits`) and flush to **`tile.layers[0].path`** (the
  tile's primary layer) via `POST /dlc/viewer/marker-edit` (`{h5, frame, bp, x, y}`; null
  x/y = delete). Selected bodypart `_iaSelectedBp` stays global (the chip list is shared).
- After a mutation, redraw via `_renderTileMarkers(tile)` so the edit shows immediately.

### 4. Remove the cam0-only handler block
The existing tile-0-only handlers (`inline_analysis_3d.js:1418+`) and the "Per-cam editing
scope note" comment (`1403-1417`) are replaced by `_wireTileEditing` (tile-0 flows through
the same generalized path). `_iaCanvasToVideo`/`_iaHitTestWithEdits` are replaced by the
per-tile equivalents.

### 5. Save Adjustments — persist both cameras
Generalize the 3D Save Adjustments handler to loop `Controller.tiles`, and for each tile
with non-empty `pendingEdits`, `POST /dlc/viewer/save-marker-edits` (`{h5: tile.layers[0].path}`)
so cam0 and cam1 both persist to their own h5/csv. Discard clears all tiles' pendingEdits.
The edit banner already shows per-cam counts (`cam0: N · cam1: M`).

## Out of scope
- The 3D **finalize** toggle / minicard / copy-to-`_analyzed` (that is **Spec 3**, which
  adds the finalize gate on top of this editing).
- Any backend change — `/dlc/viewer/marker-edit` and `/dlc/viewer/save-marker-edits`
  already exist and are per-h5; this spec only changes which h5 (per focused tile) they
  target.
- The 2D card (`inline_analysis_player.js`) — untouched.

## Testing

Static source-assertions in `tests/test_inline_analysis_3d_ui_isolation.py`:
- `Controller` wires editing per-tile (`_wireTileEditing` exists and is called for siblings,
  not just tile-0); the cam0-only scope-note comment is gone.
- Editing handlers gate on `Controller.focusedCam` (or `tile.cam === ...focused`).
- Intrinsic canvas sizing present (`naturalWidth` assigned to `canvasEl.width` in the
  render path); the per-tile coord helper (`_ia3dCanvasToImage`/rect-ratio) exists.
- Save Adjustments loops tiles (saves each tile's `layers[0].path`).
- Existing guard tests stay green (analyze button, init button states, dual-tile markup,
  no `va3d-` leaks, etc.).

The e2e test `tests/e2e/test_analyzed_viewer.py` is **not** required to pass for this spec
(it needs a live stack); rely on the static guards + manual verification in the app.

## Manual verification (after implement)
Open inline 3D, run analysis on a stereo pair, focus cam1 (click its tile or press 2), drag
a marker on cam1 — it should move and persist via Save Adjustments to cam1's h5; cam0
editing still works; marker display unchanged on both when not editing.

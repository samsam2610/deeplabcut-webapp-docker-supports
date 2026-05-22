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

## Decision: minimal-change per-tile generalization

We adopt the frame labeler's **focused-cam input-gate pattern** (only the focused tile's
canvas accepts edit input) but keep the inline card's **existing, proven coordinate model
and render pipeline unchanged**. The intrinsic-canvas approach was rejected: it would
require rewriting ~20+ call sites that assume display-pixel canvas sizing
(`_iaSyncCanvas`, every `sx = iaOverlayCanvas.width / natW` draw site, `_iaDrawCurrentFrame`,
`_iaDrawPoseMarkers`, `_iaDrawHoverLabel`, `_renderTileMarkers`, …) — a large
regression-risk rewrite of a working pipeline for zero user-facing benefit.

Instead, **parameterize the existing `_iaCanvasToVideo` / hit-test math per-tile** (each
tile already has its own `canvasEl` + `imgEl`, both sized in display pixels by the existing
render paths):

```js
function _ia3dTileCanvasToVideo(tile, cx, cy) {
  const natW = tile.imgEl.naturalWidth  || 1;
  const natH = tile.imgEl.naturalHeight || 1;
  const sx   = tile.canvasEl.width  / natW;   // canvas already display-sized by render
  const sy   = tile.canvasEl.height / natH;
  return { x: cx / sx, y: cy / sy };
}
```

This is the same formula the working cam0 path (`_iaCanvasToVideo`, line ~1331) already
uses — just reading the focused tile's elements instead of the tile-0 globals. **No change
to `_iaSyncCanvas`, canvas sizing, or any draw function.**

## Architecture (all in `inline_analysis_3d.js`)

### 1. No render-pipeline change
Canvas sizing and all marker-draw functions are left exactly as they are. Sibling-tile
marker DISPLAY already works via `_renderTileMarkers`; tile-0 DISPLAY via the existing
global path. This spec only adds **edit INPUT** on the focused tile and the per-tile
coordinate/hit-test helpers above.

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
- Coords via `_ia3dTileCanvasToVideo(tile, cx, cy)` (above) — the existing display-pixel
  formula, per-tile.
- Hit-test `_ia3dTileHitTest(tile, cx, cy)` against the tile's **primary layer's
  `posesCache.get(currentFrame)`** plus the tile's `pendingEdits` for the current frame
  (mirrors the existing `_iaHitTestWithEdits`, using the tile's `canvasEl`/`imgEl` scale
  and `_iaMarkerSize`).
- Mutations write to **`tile.pendingEdits`** (tile-0 stays aliased to `_iaLocalEdits` via
  the existing `_iaBindTile0PendingEdits`) and flush to **`tile.layers[0].path`** (the
  tile's primary layer) via `POST /dlc/viewer/marker-edit` (`{h5, frame, bp, x, y}`; null
  x/y = delete). Selected bodypart `_iaSelectedBp` stays global (the chip list is shared).
- After a mutation, redraw via `_renderTileMarkers(tile)` so the edit shows immediately.

### 4. Replace the cam0-only handler block
The existing tile-0-only handlers (`inline_analysis_3d.js:1418+`) and the "Per-cam editing
scope note" comment (`1403-1417`) are replaced by `_wireTileEditing(tile)` so tile-0 flows
through the same generalized, focus-gated path. The old globals `_iaCanvasToVideo` /
`_iaHitTestWithEdits` are superseded by the per-tile `_ia3dTileCanvasToVideo` /
`_ia3dTileHitTest` (which are the same math reading `tile.canvasEl`/`tile.imgEl`). The
sibling marker DISPLAY in `_renderTileMarkers` is extended so the **focused** tile's
primary layer also overlays `pendingEdits` + the selected-bp ring (today it draws the
sibling primary read-only) — display-only change, no canvas-sizing change.

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
- The per-tile coord/hit-test helpers exist (`_ia3dTileCanvasToVideo` / `_ia3dTileHitTest`)
  and read `tile.canvasEl`/`tile.imgEl` (NOT the tile-0 globals).
- NO change to `_iaSyncCanvas` or the display-pixel render math — assert the render
  pipeline's canvas-sizing call sites are untouched (the diff for `_iaSyncCanvas` and the
  `sx = iaOverlayCanvas.width / natW` draw functions is empty).
- Save Adjustments loops tiles (saves each tile's `layers[0].path`).
- Existing guard tests stay green (analyze button, init button states, dual-tile markup,
  no `va3d-` leaks, etc.).

The e2e test `tests/e2e/test_analyzed_viewer.py` is **not** required to pass for this spec
(it needs a live stack); rely on the static guards + manual verification in the app.

## Manual verification (after implement)
Open inline 3D, run analysis on a stereo pair, focus cam1 (click its tile or press 2), drag
a marker on cam1 — it should move and persist via Save Adjustments to cam1's h5; cam0
editing still works; marker display unchanged on both when not editing.

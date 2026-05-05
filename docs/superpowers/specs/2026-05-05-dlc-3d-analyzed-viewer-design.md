# dlc-3D — Analyzed Frame/Video Viewer with Sync-Cam Markers

**Date:** 2026-05-05
**Module:** `deeplabcut-webapp-docker-supports/dlc-3D`
**Status:** Spec — pending implementation plan

## Goal

Bring the main webapp's "View Analyzed Videos / Frames" card (kinematic
overlay + dataset curation) into the dlc-3D module as a dlc-3D-aware viewer
that handles paired sync-cam videos. When a video has a discoverable sibling
cam, two tiles appear side-by-side (mirroring the 3D Frame Extractor and
Frame Labeler layouts), frame-locked, with one shared overlay-layer
selection auto-paired per cam, per-cam editing, and one-click "Both cams"
extract/add-to-dataset operations.

## Non-goals

- Modifying the main webapp's `card_viewer.html` or `static/js/viewer.js`.
- Independent per-tile scrub/playback (always frame-locked).
- Per-cam companion CSVs — the companion CSV is primary-cam-only.
- Three-or-more-cam layouts.

## Files added / changed

**dlc-3D module (new):**

- `dlc-3D/src/templates/partials/card_viewer_3d.html` — fork of upstream
  `card_viewer.html`; ids prefixed `va3d-*`; player section restructured
  into a tile row.
- `dlc-3D/src/static/viewer_3d.js` — fork of upstream `static/js/viewer.js`;
  same module shape, sync-cam aware.
- `dlc-3D/src/static/viewer_3d.css` — additional sync-cam / per-tile styles.
  Reuse existing `fl3d-tile` rules where possible.

**dlc-3D module (edited):**

- `dlc-3D/src/templates/dlc_3d.html` — replace
  `{% include "partials/card_viewer.html" %}` with
  `{% include "partials/card_viewer_3d.html" %}`; load `viewer_3d.js`.
- `dlc-3D/src/dlc_3d_bp/routes.py` — add three endpoints (Section 4).

**Main webapp:** untouched.

## Player section layout

Header, source picker (Project Content / Browse Folders), and global
metadata strip remain identical to upstream `card_viewer.html`. Below the
source picker the player section is restructured:

```
[ va3d-selected-name ] [ Back ]
[ Equalize ] [ Marker size … ] [ Sync Cam ☑ (auto-on if sibling) ]
[ Metadata strip — primary cam only — global ]
[ Kinematic Overlay panel — SHARED (one primary picker + one comparison list) ]
[ Marker Adjustment Banner — combined: "cam0: N · cam1: M frames — unsaved" ]

┌──────────── va3d-tile-row (flex) ────────────┐
│ ┌─ tile primary (cam0) ─┐ ┌─ tile sib (cam1)┐│
│ │ header: label · size  │ │ header: label · ││
│ │         slider · %    │ │         slider %││
│ │ <img> + <canvas>      │ │ <img> + <canvas>││
│ │ spinner               │ │ spinner         ││
│ └───────────────────────┘ └─────────────────┘│
└──────────────────────────────────────────────┘

[ seek slider — global ]
[ play/pause · prev · next · fps · step · skip · frame counter · time ] — global
[ Body-part chips — global ]
[ Status timeline — primary cam CSV — global ]
[ Note timeline   — primary cam CSV — global ]
[ Annotation panel (Status / Note / Add Tag) — primary cam CSV — global ]
[ Dataset Curation panel — Both cams ☑ default; gates Extract / Add / Batch ]
```

Single-cam mode (no sibling): sibling tile hidden; marker-edit banner shows
just the primary count; "Both cams" checkbox not shown.

## Frontend architecture (`viewer_3d.js`)

**Tile (per-cam state):**

- `cam` (0 or 1), `videoRel`, `imgEl`, `canvasEl`, `wrapEl`, `weight` (size
  slider value).
- `primaryH5Path`, `comparisonLayers[]` — *resolved* paths for this cam,
  derived from the shared layer selection.
- `pendingEdits` map (frame → bodypart → xy), `markersByFrame` cache.
- Methods: `loadFrame(n)`, `loadH5()`, `renderOverlay()`, `applyEdit()`,
  `clearFrame()`, `serializeEdits()`.

**ViewerController (singleton):**

- `tiles[]` (1 or 2 long), `currentFrame`, `syncOn`, `extractBoth`.
- Owns: source picker, seek/play loop, fps/step, body-part chip selection,
  threshold/marker-size sliders, layer-pair resolver, mirrored-write
  helpers, focus state.
- `setVideo(rel)`: probe sibling via `/dlc-3d/sibling-camera`; create or
  destroy tile #1 accordingly; set `syncOn` auto-on when sibling found.
- `setPrimaryLayer(layerKey)`: resolve cam-specific h5 for each tile via
  the layer-pair resolver, then `tile.loadH5()`.
- `seek(n)`: `tile.loadFrame(n)` for each tile (always frame-locked).
- `saveAdjustments()`: collects pending edits from each tile, posts one
  batch per tile's h5/csv pair in parallel.

**Layer-pair resolver:**

- Input: a layer "key" (scorer + shuffle + snapshot) plus a cam index.
- Logic: substitute `_cam{N}_` segment in the file stem (and any folder
  fragment matching `_cam\d+_`); if the resulting file exists in the same
  directory, use it; otherwise fall back to the original (and surface a
  per-tile "no sibling h5" status pill).
- Used identically for the primary picker and each comparison entry.

**Marker-edit banner:**

- Single banner; text becomes `cam0: 3 frames · cam1: 2 frames — unsaved`.
- Save Adjustments writes per-cam h5/csv files in parallel; status is
  collated.
- The "Edit disabled while comparing layers" banner stays per-tile (each
  tile decides locally based on its own comparison count — same rule as
  upstream).

**Per-tile size sliders + Equalize:**

- Reuse the fl3d-tile flex-grow weight pattern (`data-weight`,
  `flex-grow:N`); persist weights across frame navigation; Equalize resets
  both to 100. Global "Marker size" slider and chip selection remain shared.

## Backend (`dlc_3d_bp/routes.py`)

Existing endpoints (frame fetch, h5 marker fetch, save-adjustments to a
single h5/csv pair) are reused per tile. Three new endpoints add the
sync-cam pairing layer.

1. **`GET /dlc-3d/analyzed/sibling-h5?primary_h5=<rel>&cam=<n>`**
   Resolve the sibling cam's matching h5 by substituting `_cam{N}_` in the
   basename and searching the same directory. Returns
   `{path, exists}` or `{path: null}`. Used by the layer-pair resolver
   for both primary and comparison layers.

2. **`POST /dlc-3d/analyzed/extract-pair`**
   Body: `{video_rel, frame_number, mode: "extract" | "add_to_dataset" |
   "batch", batch?: {count, step}, both_cams: bool}`.
   When `both_cams: true`, performs the operation on the primary cam frame
   **and** the sibling cam frame at the same frame number, returning a
   per-cam result `{cam0: {...}, cam1: {...}}` so the UI can surface
   partial-failure cleanly. Internally delegates to the existing
   single-cam handlers.

3. **`POST /dlc-3d/analyzed/save-edits-pair`**
   Optional convenience wrapper for parallel per-cam edit-save calls;
   returns aggregated `{cam0, cam1}` result. May be implemented as two
   client-side parallel calls instead — decision deferred to the
   implementation plan.

**Path security:** all new handlers route through the existing
`_resolve_video_path` helper before any filesystem touch.

## Behavior details

**Sync-cam entry / exit.**
On `setVideo(rel)`: probe `/dlc-3d/sibling-camera`. If found, instantiate
the sibling tile, set `Sync Cam` checkbox checked. If not, sibling tile
hidden, checkbox shown but disabled with tooltip "no sibling cam detected".
User can uncheck to collapse to single-cam at any time (sibling tile hides;
sibling pending edits are kept in memory until video changes).

**Frame-locked seek/play.**
Single seek slider drives `controller.seek(n)` → `tile.loadFrame(n)` for
each tile. Play loop ticks once per fps and dispatches to all tiles.
fps / step / skip-N controls are global. Body-part chip selection is global.

**Overlay scope (shared, auto-paired).**
Single primary picker + single comparison list. On every layer change, the
controller calls the layer-pair resolver per tile and triggers
`tile.loadH5()`. If the sibling h5 doesn't exist, that tile shows a small
"no sibling h5 — overlay off" pill in its tile header but the primary tile
keeps rendering. Threshold slider, marker-size slider, and per-layer
threshold customization are global and apply to every tile's render.

**Editing.**
Per-cam editing on each tile (matches existing single-cam edit behavior on
each tile independently). Each tile's pending-edits map is cam-scoped. The
single banner shows `cam0: N · cam1: M frames — unsaved`. Save Adjustments
writes both cams' h5/csv files in parallel; status reports per-cam success
or partial failure. Discard clears both. Clear Frame clears the focused
tile only (the tile whose canvas was last interacted with, indicated by a
thin focus ring — same `focused` class the frame labeler uses).

**Dataset curation — Both cams.**
"Both cams" checkbox lives in the curation panel header, only visible when
sync-cam is on, **checked by default**. Gates Extract Frame, +Add to
Dataset, and Batch Add. All three call `/dlc-3d/analyzed/extract-pair`
with `both_cams` from the checkbox. Extract count chip shows combined
count when checkbox is checked, e.g. "5 + 5 frames saved".

**Companion CSV (primary cam only, global).**
There is one companion CSV — the primary cam's. One global metadata strip
and one global status/note timeline pair below the tile row (as in
upstream). The annotation panel (Save Status / Save Note / Add Tag) writes
only to the primary cam's CSV. The sibling tile shows no separate
metadata strip, no separate timelines, no separate annotation panel.

**Per-tile size & Equalize.**
Each tile has a header with label + range slider (50–500%, step 25) +
percent readout. The slider drives `data-weight` → `flex-grow`. Weights
persist across `loadFrame` / `setVideo` until explicitly reset by Equalize
(both → 100). Global Viewer-size slider stays as a multiplier on top.

**Keyboard.**
Inherits upstream bindings: Space play/pause, ←/→ frame, Ctrl+←/→
skip-N. New: number keys `1` / `2` focus tile 0 / 1 (sets the `focused`
ring; controls Clear-Frame target and indicates which tile receives
hover-label rendering). Marker-edit keys (drag/click/right-click delete)
act on the focused tile only.

## Edge cases

- **No sibling found** → sibling tile hidden, Sync Cam checkbox shown but
  disabled with tooltip.
- **Sibling exists, sibling h5 missing** → primary renders normally;
  sibling tile shows "no sibling h5 — overlay off" pill in tile header;
  layer-pair resolver returns `{path: null}`. Editing still allowed on the
  primary tile.
- **Sibling exists, sibling video unreadable** → sibling tile shows error
  placeholder; Sync Cam stays on so user can retry; primary tile remains
  functional.
- **Layer-pair resolver fails for a comparison layer** → that one
  comparison entry is skipped on the failing tile but kept on the other;
  per-tile pill notes it.
- **Mixed-success extract-pair** (primary saved, sibling failed or
  vice-versa) → curation status shows e.g. "cam0 ✓ · cam1 ✗ <reason>";
  counter increments only for successes; Batch Add stops on first
  sibling-side failure (configurable later).
- **Toggle Sync Cam off mid-edit** → sibling pending edits stay in memory;
  re-enabling restores them; switching video discards them with
  confirm-prompt if non-empty.
- **Frame number out of range on sibling** (rare; mismatched lengths) →
  sibling tile shows "frame N/A on sibling" overlay; primary continues to
  play.

## Testing

Manual smoke checklist (matches the rest of the dlc-3D module's
predominantly UI-test posture):

1. Single-cam video → card behaves identically to upstream
   `card_viewer.html`.
2. Sync video → both tiles load; seek stays locked; layer pair
   auto-resolves; threshold / marker-size apply to both.
3. Extract / Add / Batch with Both cams checked → pair counter increments
   correctly; both labeled-data folders populate.
4. Annotate writes only to primary cam CSV; sibling labeled-data
   unaffected.
5. Edit on tile 0 then tile 1 → banner shows split count; Save writes both
   files; Discard clears both.
6. Missing sibling h5 → primary works; sibling pill appears.
7. Toggle Sync off and on → state preserved; pending edits survive.

Backend additive tests in `dlc-3D/tests/` cover the new endpoints; existing
`_find_sibling_video` tests remain authoritative.

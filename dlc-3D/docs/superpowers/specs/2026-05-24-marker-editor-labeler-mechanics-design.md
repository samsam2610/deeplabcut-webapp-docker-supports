# Frame-Labeler Editing Mechanics in the Shared `markerEditor` — Design Spec

**Date:** 2026-05-24
**Module:** `dlc-3D` (frontend only)
**Status:** Approved (brainstormed + decisions captured below).
**Branch:** `feat/marker-editor-labeler-mechanics` (off `fix/inline-3d-marker-edit-overlay`, which carries the prerequisite "enable editing when Finalize is checked" fix `2a4818b`).

## Goal

Make marker labeling/adjusting + view-switching on the inline-3D analysis card feel like the
well-tested `frame_labeler_3d.js` ("label-frame 3d"), by porting that proven **interaction model**
into the shared `markerEditor` feature — not by forking the labeler.

## Why enhance the shared feature (not fork)

The dlc-3D policy (`docs/policies/video-viewer-component.md`, enforced by
`tests/test_video_viewer_policy.py`) forbids re-forking the player; the whole video-viewer library
extraction existed to delete exactly that duplication. `frame_labeler_3d.js` is a 1,895-line
monolith that owns its own player and edits a **different data model** — DeepLabCut **training
labels** (`/dlc/project/labels/...`), not the **analysis-h5 predicted poses** the inline card edits
(edit-cache → h5/csv, consumed by Finalize). So we copy the *interaction feel*, keep markerEditor's
pose/edit-cache data layer, and both curation cards (inline + View Analyzed) inherit the polish.

## Decisions (from brainstorming)

- **View switching:** polish the existing click-to-focus dual-cam model (NOT a single-view switch).
- **Edit gate:** decouple editing from the overlay toggle — edit-mode always renders + edits.
- **Lock-BP is a checkbox, NOT the `L` key** — `L` is already the keyframe range-lock in the inline card (`keyframe_window_ui.js`). Avoid the collision.
- **Save model unchanged:** keep markerEditor's per-edit auto-flush + the existing "Save Adjustments" button + edit-count banner. Do NOT adopt the labeler's training-label save path.

## Scope

Frontend only. Enhance the shared `markerEditor` feature + wire the inline-card consumer; verify
View Analyzed for regressions. No new HTTP routes, no backend change, no player fork, no data-model
change. Out of scope: single-view/maximize mode, the labeler's training-label workflow, TAPNet/ML
propagation, any change to View Analyzed behavior beyond inheriting the feature.

## Files

- Modify: `src/static/components/viewer/features/marker_editor.js` — the interaction enhancements (see Behaviors).
- Create: `src/static/components/viewer/internal/bodypart_cycle.mjs` — DOM-free reducers: `nextUnlabeledBodypart(bodyparts, posedSet, current, lock)` and `cycleBodypart(bodyparts, current, dir)`; reuse `posedBodyparts` from `marker_overlay.mjs` for "labeled-in-frame".
- Create: `tests/unit/test_bodypart_cycle.mjs` — node:test for the reducers.
- Modify: `tests/test_marker_editor_feature.py` — extend the feature contract for the new API/behaviors.
- Modify: `src/static/inline_analysis_3d.js` — consumer wiring (Lock-BP checkbox, `autoAdvance`, simplified `_applyOverlayPrimary`, focus-persistence config).
- Modify: `src/templates/partials/card_inline_analysis_3d.html` — Lock-BP checkbox in the overlay/marker-edit controls.
- Modify: `src/static/inline_analysis_3d.css` — focused-tile highlight emphasis + Lock-BP control style (reuse existing tokens).
- Modify: `tests/test_inline_analysis_3d_ui_isolation.py` — assertions for the Lock-BP control + edit-mode decoupling wiring.

## Behaviors (markerEditor enhancements)

### B1 — Decouple editing from the overlay gate
Today every edit handler and `renderTile` gate on `overlayEnabled` (`marker_editor.js:170,381,396,410,427`).
Change the gate to `overlayEnabled || editingAllowed`. Effects:
- `setEditable(true)` ⇒ markers render and click/drag/keyboard are live, with no `setOverlayEnabled(true)` required.
- Read-only consumers (View Analyzed when not editing) keep `editingAllowed === false`, so their rendering stays keyed on `overlayEnabled` — **no behavior change**.
- The inline overlay toggle becomes a show/hide-markers convenience; the consumer no longer force-enables it for editing.

### B2 — Auto-advance bodypart after placing (config `autoAdvance`, default off; inline sets `true`)
After a successful click-place, advance `selectedBp` to the next bodypart with NO finite pose in the
current frame (using `posedBodyparts(curPoses)`), wrapping once; if all are placed, stay put. Skipped
when Lock-BP is on. Pure logic in `nextUnlabeledBodypart`.

### B3 — Lock-BP mode (`setLockBp(bool)` + state; UI = checkbox)
When locked, placing does NOT auto-advance — repeated clicks re-place the SAME bodypart (correct a
marker). No keyboard shortcut (checkbox only; `L` is taken). Default off.

### B4 — Click-near-marker selects its bodypart
On mousedown, hit-test existing markers (already present at `marker_editor.js:383`): if the cursor is
on/near a marker, select that bp and begin a drag; otherwise a click on empty space places the
selected bp. Ensure this works the instant edit-mode is on (no overlay precondition, per B1).

### B5 — Cursor feedback tracks state on hover
Update the focused tile's canvas cursor on mousemove: `pointer` when hovering an existing marker,
`crosshair` when a bp is selected + edit-mode on, else default. (Today the cursor is set only in
`selectBp`/`setFocusedCam`/`setEditable`.)

### B6 — Keyboard set (focused tile, edit-mode on)
Tab / Shift-Tab cycle bodyparts (exists); WASD nudge ±1 (Shift ±10) (exists); Backspace/Delete
remove (exists); **Space toggles the selected bp's per-frame visibility** (NEW) — hide it from render
+ reflect the `.vv-bp-chip.vis-hidden` chip state already in the inline CSS. Arrows remain
VideoViewer frame-nav. Keep the existing keyboardTarget scoping (shortcuts only when the card owns focus).

### B7 — View-switching polish (click-to-focus, both cams)
- Prominent focused-tile highlight (`.vv-tile-focused`).
- Crosshair only on the focused tile; non-focused tiles render read-only; first click on a non-focused tile focuses it, subsequent clicks edit (exists — verify).
- **Focus persistence:** do NOT reset `focusedCam` to 0 on `videoLoad` (`marker_editor.js:469`). Preserve the last focused cam across frame steps and video switches; clamp to a valid tile index if the new video has fewer cams.

### B8 — Save model (unchanged)
Per-edit auto-flush to edit-cache → h5/csv (both cams) stays. Surface confidence via the existing
edit-count banner + "Save Adjustments" button. No new save path.

## Consumer wiring (inline_analysis_3d.js)

- Edit-mode is driven by the Finalize toggle → `setEditable(on)` (exists).
- Pass `autoAdvance: true` in the markerEditor config.
- Add a **Lock-BP** checkbox (markup + CSS) near the marker-edit controls; wire it to `setLockBp`.
- Simplify `_applyOverlayPrimary`: after `setPrimary` + sibling resolve, when Finalize is checked just `setEditable(true)` — drop the forced `setOverlayEnabled`/overlay-toggle dispatch (B1 makes editing render without it). Keep the existing primary-resolution + bp auto-select.
- Keep both cams + click-to-focus; rely on B7 for focus persistence.

## View Analyzed (`viewer_3d.js`) — regression guard

Inherits the markerEditor changes but does not enable editing by default, so B1 keeps its rendering
keyed on `overlayEnabled` (unchanged), and B2/B3/B6-Space are inert unless editing. The only shared
path that could shift is focus persistence (B7) — verify View Analyzed still focuses sanely. Explicit
acceptance criterion: View Analyzed overlay + (if it supports edit) editing behave as before.

## Data flow (unchanged)

Marker edits → markerEditor `editsByCam` → `endpoints.saveMarker()` per cam → edit-cache → h5/csv.
Finalize "Add range to _analyzed" reads the edited h5. No new endpoints.

## Error handling

- `nextUnlabeledBodypart` tolerates an empty/!array bodypart list and an all-placed frame (returns current).
- Focus-persistence clamps a stale `focusedCam` to the available tile count on `videoLoad`.
- Visibility toggle is per-(frame,bp) in-memory state; never blocks rendering of other bodyparts.

## Testing

- **node:test** `tests/unit/test_bodypart_cycle.mjs`: `nextUnlabeledBodypart` (skip placed, wrap, lock=stay, all-placed=stay, empty list) + `cycleBodypart` (wrap both directions).
- **pytest** `tests/test_marker_editor_feature.py`: extend the contract — `setLockBp` exists; `autoAdvance` config honored; render/edit gated on `overlayEnabled || editingAllowed`; `focusedCam` not reset on videoLoad.
- **pytest** `tests/test_inline_analysis_3d_ui_isolation.py`: Lock-BP control present + wired; `_applyOverlayPrimary` no longer force-enables the overlay (just setEditable); `autoAdvance:true` passed.
- **pytest** `tests/test_video_viewer_policy.py`: must stay green (no player fork).
- **Live verification (read-only)** against a posed fixture video (e.g. DREADD-Ali / khoai-lang-1 cam0 with an h5), NO destructive saves: edit-mode on (Finalize checked) renders markers with no overlay toggle; place → auto-advances; Lock-BP on → re-places same bp; click-near-marker selects + drags; crosshair/pointer cursor tracks hover; Tab/WASD/Backspace/Space work on the focused tile; focus persists across frame steps; clicking cam1 focuses + edits cam1. Do NOT click Save Adjustments / Add range / Extract / Finalize / Delete.

## Out of scope

- Single-view/maximize mode; the labeler's training-label save; TAPNet/ML propagation; removing the overlay toggle entirely (kept as a show/hide convenience); any View Analyzed behavior change beyond inheriting the feature.

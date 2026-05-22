# Finalize Analysis (3D inline, both cameras) — Design

**Date:** 2026-05-22
**Status:** Approved (pending implementation plan)
**Repo:** `deeplabcut-webapp-docker-supports/dlc-3D`, branch `feat/3d-inline-analysis`

## Context

**Spec 3 of the 3-part decomposition** (Spec 1 = 2D Finalize, done; Spec 2 = inline 3D
sibling-tile editing, done). This is the 3D mirror of Spec 1: a "Finalize analysis"
minicard in the inline 3D card that gates marker editing, and copies a chosen frame range
from each camera's working layer into that camera's canonical `<stem>_analyzed.h5`.

**Reuses, no new backend:** the `POST /dlc/project/inline-analysis/finalize-range`
endpoint (Spec 1, in the main webapp) is called once per camera. Spec 2 made cam1
hand-editable. All work here is in the dlc-3D card.

Files: `src/templates/partials/card_inline_analysis_3d.html`,
`src/static/inline_analysis_3d.js`, `tests/test_inline_analysis_3d_ui_isolation.py`.

## Feature 1 — Finalize minicard

A panel below `#ia3d-curation-panel` (after the `<!-- end Dataset Curation Panel -->`
comment ~line 420, before the `</div>` closing `#ia3d-player-section`), mirroring the
curation panel's toggle+controls structure:
- toggle `#ia3d-finalize-toggle` (unchecked by default),
- hidden `#ia3d-finalize-controls`,
- `#ia3d-finalize-start` / `#ia3d-finalize-count` number inputs,
- `#ia3d-finalize-add-btn` (`btn-sm btn-create`, label "Add range to _analyzed"),
- `#ia3d-finalize-status` (`fe-extract-status`).

## Feature 2 — Edit-gating via `_iaIsEditable`

Add a module flag `_ia3dFinalizeEnabled` (default false), set by `#ia3d-finalize-toggle`'s
`change` handler. Change `_iaIsEditable()` (`inline_analysis_3d.js:723`) from:
```js
function _iaIsEditable()  { return _iaLayers.length === 1; }
```
to:
```js
function _iaIsEditable()  { return _iaLayers.length === 1 && _ia3dFinalizeEnabled; }
```
Both the tile-0 handlers and the Spec-2 `_wireSiblingEditing` handlers gate mutation
(place/drag/delete + flush) on `_iaIsEditable()`, so this single change gates editing on
**every** camera tile behind the finalize toggle. Select-on-hit (`_iaSelectBp`) runs before
the `_iaIsEditable()` check, so selecting a bodypart still works when finalize is off.

The toggle `change` handler also:
- toggles `#ia3d-finalize-controls` `hidden`;
- auto-enables the overlay if off (`iaOverlayToggle.checked = true` + dispatch `change`);
- populates the finalize fields (Feature 5) when enabling;
- calls `_iaUpdateEditBanner()` to show/hide the relocated controls.

## Feature 3 — Relocate marker-edit controls

Mirror Spec 1: **remove** the top `#ia3d-marker-edit-banner` (~lines 182-198); add a
`#ia3d-marker-edit-controls` row directly below `#ia3d-bp-list-wrap` (after line ~281,
before `#ia3d-status`), holding the count `#ia3d-marker-edit-count` + `#ia3d-save-adjustments-btn`
+ `#ia3d-discard-adjustments-btn` + `#ia3d-clear-frame-btn` (ids preserved). Retarget the JS
const (`inline_analysis_3d.js:1383`) to `getElementById("ia3d-marker-edit-controls")` and
make `_iaUpdateEditBanner` (1413) finalize-driven: `classList.toggle("hidden", !_ia3dFinalizeEnabled)`
then update the per-cam count text (the existing `cam0: N · cam1: M` formatting stays).
Update the existing `test_card_*`/guard that asserts `ia3d-marker-edit-banner` to the new id.

## Feature 4 — "Add range to `_analyzed`" (both cameras)

On `#ia3d-finalize-add-btn` click:
1. Guard: tile-0 must have a primary layer (`_iaPrimary()`); else error to status.
2. **Commit edits to both cameras** — run the same per-tile save the Save-Adjustments
   button does (tile-0 via `/dlc/viewer/save-marker-edits` `{h5: _iaPrimary().path}`, plus
   the sibling loop saving each `tile.primaryH5Path`).
3. **Copy each camera's range** — read `start`/`n` from the fields, then:
   - cam0: `POST finalize-range` `{video_path: _iaCurrentVideoPath, source_h5: _iaPrimary().path, start_frame, n_frames}`.
   - cam1 (only if `_siblingPath` resolved): `POST finalize-range`
     `{video_path: _siblingPath, source_h5: Controller.tiles[1].primaryH5Path, start_frame, n_frames}`.
4. Status: `cam0 ✓ N · cam1 ✓ M` (or per-cam error). Re-enable the button in `finally`.

The endpoint computes the canonical scorer + `<stem>_analyzed.h5` per `video_path`, so cam0
and cam1 each write their own `_analyzed` file. Curated-range-wins semantics come from
`write_to_canonical` (unchanged).

## Feature 5 — Autopopulate from the last 3D run

In the 3D analyze-submit handler (~line 3424, where `startFrame = _iaCurrentFrame` and
`nFrames = parseInt(framesEl.value)` are computed), store `_ia3dLastRunStart` /
`_ia3dLastRunN`. Populate the finalize fields from those when the minicard is opened and on
run-complete; before any run, default start = `_iaCurrentFrame`, count = the
`#ia3d-frames-per-click` value.

## Out of scope
- The `finalize-range` backend endpoint (exists from Spec 1; reused, called per camera).
- `canonical.py` (unchanged).
- The 2D card (`inline_analysis_player.js`).

## Testing

Static source-assertions in `tests/test_inline_analysis_3d_ui_isolation.py`:
- minicard ids present (`ia3d-finalize-toggle/controls/start/count/add-btn/status`); panel
  after `#ia3d-curation-panel`.
- `_iaIsEditable` includes `_ia3dFinalizeEnabled`.
- relocated controls below `#ia3d-bp-list-wrap`; old `#ia3d-marker-edit-banner` id gone;
  JS retargeted to `ia3d-marker-edit-controls`.
- finalize add-btn handler references `/dlc/project/inline-analysis/finalize-range`,
  `_siblingPath`, and `_iaCurrentVideoPath` (both-cams copy) + `/dlc/viewer/save-marker-edits`.
- autopopulate (`_ia3dLastRunStart` / `_ia3dLastRunN`).
- existing 3D guard tests stay green (now 19 + new).

## Manual verification (after implement)
Open inline 3D, run analysis on a stereo pair, check Finalize analysis (editing enables on
both tiles; controls appear below the bodypart list; fields auto-fill from the run). Edit a
marker on cam0 and one on cam1, click "Add range to _analyzed" → both cams' `<stem>_analyzed.h5`
get the curated range; status shows cam0 ✓ · cam1 ✓.

# Inline 3D — Finalize-and-Extract Clip (+ Rename / Delete with _analyzed un-finalize) — Design

**Date:** 2026-05-24
**Status:** Approved (pre-approved through implementation)
**Repos:** `deeplabcut-webapp-docker-supports/dlc-3D` (frontend) + `deeplabcut-webapp-docker` (main webapp backend).

## Context

The inline-3D Finalize sub-card has a keyframe window (keyframe/before/after/length) and an **Add range to _analyzed** button (`_onFinalizeAddClick`: overwrite-confirm → save marker edits to both cams' layers → `finalize-range` into each cam's `_analyzed`). Add clip creation that reuses the SAME keyframe-window range (no separate start/length/end), plus a postfix field, and Rename/Delete of the created clip. **Delete must also un-finalize** (remove) the just-added range from `_analyzed`.

**User decisions:** add a second button "Finalize and extract clip" (keep Add-range); both-cams checkbox default on; new optional postfix; add Rename + Delete; Delete removes the clip AND the recently-added `_analyzed` entry; test the un-finalize carefully.

## Components

### A. Backend — un-finalize (main webapp)
- **`dlc/canonical.py`** `unfinalize_range(video_path, start_frame, n_frames) -> int`:
  - `h5 = canonical_h5_path(video_path)`. If it doesn't exist → return 0 (no-op).
  - Read the df (`pd.read_hdf`). For rows whose index is in `[start_frame, start_frame+n_frames)` AND present in the index, set ALL columns to `NaN`. Rows outside the range are untouched.
  - Atomically rewrite both the `.h5` (`_atomic_write_h5`) and the `.csv` (`_atomic_write_csv`) so they stay consistent.
  - Return the count of rows cleared.
- **`dlc/inline_analysis.py`** `POST /dlc/project/inline-analysis/unfinalize-range` body `{video_path, start_frame, n_frames}` → resolve active project (400 if none), call `canonical.unfinalize_range(...)`, return `{"n_frames_cleared": <int>}`. Mirrors `finalize-range`'s shape/guards.

### B. Frontend — finalize clip controls (dlc-3D)
- **Markup** (`card_inline_analysis_3d.html`, in `#ia3d-finalize-controls`, after the Add-range row): a row with `#ia3d-finalize-clip-postfix` (text, optional) + `#ia3d-finalize-clip-sibling` (checkbox, checked, "both cams"); a button row keeping `#ia3d-finalize-add-btn` and adding `#ia3d-finalize-clip-btn` ("Finalize and extract clip"), `#ia3d-finalize-clip-rename-btn` ("Rename clip"), `#ia3d-finalize-clip-delete-btn` ("Delete clip"). Rename/Delete start `disabled`.
- **Glue** (`inline_analysis_3d.js`):
  - Refactor: extract the finalize core into `async function _doFinalizeAdd() -> { ok, start, n }` (the existing overwrite-confirm + save + both-cams `finalize-range`; returns the range and success). `_onFinalizeAddClick` becomes: disable its button → `await _doFinalizeAdd()` → re-enable. (Behavior unchanged for the existing button.)
  - Module state `let _lastFinalizeClip = null;` = `{ start, n, cams: [{ video, avi }, …] }`.
  - `_finalizeClipBtns()` helper to enable/disable rename+delete based on `_lastFinalizeClip`.
  - **`_onFinalizeAndExtractClick`:** disable button → `const r = await _doFinalizeAdd()`; if `!r.ok` return. Then for cam0 (video `_cam0Path()`) and, if both-cams + `_siblingPath`, cam1: `POST /dlc-3d/extract-clip {video_path, start_frame: r.start, n_frames: r.n, postfix}`; collect `avi_path`s. Set `_lastFinalizeClip = { start:r.start, n:r.n, cams:[…] }`; enable rename/delete; status "finalized ✓ · clip ✓ (+sibling)".
  - **`_onFinalizeClipRename`:** for each tracked cam with an avi, `POST /dlc-3d/extract-clip/rename {avi_path, postfix}`; update the tracked `avi` to the returned path. `_analyzed` untouched. Status.
  - **`_onFinalizeClipDelete`:** `window.confirm` (names the range + that it removes the clip AND un-finalizes those frames). Then per tracked cam: `POST /dlc-3d/extract-clip/delete {avi_path}` (if avi) AND `POST /dlc/project/inline-analysis/unfinalize-range {video_path, start_frame: _lastFinalizeClip.start, n_frames: _lastFinalizeClip.n}`. Then `_refreshFinalizeCoverage()`, clear `_lastFinalizeClip`, disable rename/delete. Status.
  - Reset `_lastFinalizeClip = null` + disable rename/delete in `_resetForOpen`.

## Data flow / error handling
- The clip + un-finalize use the SAME range tracked at extract time (`_lastFinalizeClip`), not the live keyframe window (which the user may have moved). So Rename/Delete always act on the actual created clip.
- Each network step is independent; a failure on one cam reports in status but doesn't abort the other (best-effort, like the existing finalize). Delete attempts both the file delete and the un-finalize per cam.
- Un-finalize on a missing `_analyzed` is a no-op (0). NaN-ing a range that overlaps a separately-finalized range also clears the overlap — correct for "remove the recently added entry" (its exact range); noted as an accepted edge.
- Rename/Delete are inert (disabled) until a clip has been created this session.

## Testing
- **backend** (`tests/test_canonical_unfinalize.py`, main repo): build a dense canonical with a known finalized range (via `write_to_canonical` or `build_empty_dense_df` + set values), `unfinalize_range` the range → those rows all-NaN, rows OUTSIDE unchanged; `.csv` regenerated to match `.h5`; missing-file → 0; partial/sub-range leaves the rest intact; return count correct.
- **endpoint** (extend `tests/test_inline_analysis*` or a focused test): `unfinalize-range` resolves active project + returns `n_frames_cleared`; 400 with no project.
- **inline contract** (`test_inline_analysis_3d_ui_isolation.py`): the postfix/both-cams ids + four buttons present; rename/delete `disabled` by default; the handlers wired (`/dlc-3d/extract-clip`, `/extract-clip/rename`, `/extract-clip/delete`, `/dlc/project/inline-analysis/unfinalize-range`); `_doFinalizeAdd` shared by both finalize buttons; `_lastFinalizeClip` tracked.
- **live verify (limited):** controls render; Rename/Delete disabled until a clip exists. Will NOT click Finalize-and-extract / Delete (write `_analyzed` + create/delete files). The risky un-finalize correctness is proven by the backend round-trip unit tests on a tmp fixture.

## Out of scope (YAGNI)
- Redo/history stack (single last-op undo only).
- Persisting `_lastFinalizeClip` across reloads (in-session only).
- Rename/Delete of clips created from the separate create-clip sub-card (that card has its own).

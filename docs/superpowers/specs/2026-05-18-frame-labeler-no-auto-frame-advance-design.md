# Frame Labeler: drop auto-frame-advance when last BP is labeled

**Date:** 2026-05-18
**Scope:** main webapp (`deeplabcut-webapp-docker`) and 3D module (`deeplabcut-webapp-docker-supports/dlc-3D`)

## Problem

When a user places the final missing body-part label on a frame, the Frame Labeler card auto-advances to the next frame. The user wants to own frame navigation: a click that completes the current frame should not silently move them off it. Selecting the next missing BP **within** the current frame after a click remains desirable.

## Behavior change

In `_flAutoAdvanceBp()`, drop the fall-through that calls `_flShowFrame(...)` when every BP on the current frame is already labeled. The function's responsibility narrows to a single thing: cyclically walk the BP chip list and select the next missing BP on the current frame. If none is missing, do nothing.

Frame index and `_flSelectedBp` are never mutated as a side-effect of frame navigation or of the "all labeled" case. The user advances frames explicitly via the Next/Prev buttons, arrow keys, or (3D only) the frame-number tape.

This is purely a deletion — no new flag, no new branch.

## Files touched (code)

1. `deeplabcut-webapp-docker/src/static/js/frame_labeler.js`
   - Inside `_flAutoAdvanceBp()` (declared at line 1116), delete the two trailing lines that advance the frame:
     ```js
     // All body parts labeled on this frame → move to next frame
     if (_flFrameIdx < _flFrames.length - 1) _flShowFrame(_flFrameIdx + 1);
     ```

2. `deeplabcut-webapp-docker-supports/dlc-3D/src/static/frame_labeler_3d.js`
   - Inside `_flAutoAdvanceBp()` (declared at line 1629), delete the comment + `curIdx`/`total` block that picks the right axis and calls `_flShowFrame(curIdx + 1)`:
     ```js
     // All body parts labeled on this frame → move to next frame.
     // (sync-axis selection block …)
     const curIdx = _fl3dSyncOn ? _fl3dFrameNumIdx     : _flFrameIdx;
     const total  = _fl3dSyncOn ? _fl3dFrameNumbers.length : _flFrames.length;
     if (curIdx < total - 1) _flShowFrame(curIdx + 1);
     ```

Both files retain the BP-walk loop above the deleted block — that loop is the desired same-frame behavior and must be preserved verbatim.

## Tests

### Playwright e2e (3D module)

New file: `deeplabcut-webapp-docker-supports/dlc-3D/tests/e2e/test_labeler_no_auto_frame_advance.py`

The 3D module already has playwright infrastructure (see `tests/e2e/conftest.py` and `test_sync_frame.py`):
- `conftest.py` handles auth, activates the `OM-2_20260424` DLC project, and skips the module if the fixture is unreachable.
- `window.__fl3d` exposes `labels`, `selectedBp`, `syncOn`, `frameNumberIdx`, etc.
- Existing helpers in `test_sync_frame.py` (e.g., `_select_unlabeled_chip`, `_click_canvas_center`) model the same DOM interactions.

Two tests, one per sync mode:

1. `test_no_auto_advance_when_last_bp_labeled_sync_off`
   - Snapshot the focused tile's `data-fname`.
   - Wipe `window.__fl3d.labels[fname]` to force fresh placements (mirrors the `_select_unlabeled_chip` pattern — necessary because the OM-2 fixture pre-labels most BPs and click-near-existing-marker takes a select-only path).
   - For every BP chip in DOM order: click the chip, wait for `selectedBp`, click the canvas at a unique offset, wait for the label to appear in `window.__fl3d.labels`.
   - After all BPs are placed, assert the focused tile's `data-fname` equals the snapshot.

2. `test_no_auto_advance_when_last_bp_labeled_sync_on`
   - Check `#fl3d-sync-frame`, wait for `window.__fl3d.syncOn === true`.
   - Snapshot `window.__fl3d.frameNumberIdx` and the focused tile's `data-fname`.
   - Same placement loop as above.
   - Assert `frameNumberIdx` and `data-fname` are unchanged.

Both tests cover the fall-through branch the deletion targets. Sync-off exercises the `_flFrameIdx / _flFrames` path; sync-on exercises the `_fl3dFrameNumIdx / _fl3dFrameNumbers` path — both of which were combined in the deleted block.

### Source-text regression (both codebases)

Two thin, fast tests that re-read each JS file and assert the function body no longer calls `_flShowFrame`. These guard against the deleted block being reintroduced and run in the standard unit-test job (no Playwright required).

1. `deeplabcut-webapp-docker/tests/test_frame_labeler_no_auto_frame_advance.py`
   - Read `src/static/js/frame_labeler.js`.
   - Extract the `_flAutoAdvanceBp` body by locating `function _flAutoAdvanceBp(` then walking braces to the matching close.
   - Assert `_flShowFrame` does not appear in the body.

2. `deeplabcut-webapp-docker-supports/dlc-3D/tests/test_frame_labeler_3d_no_auto_frame_advance.py`
   - Same approach against `src/static/frame_labeler_3d.js`.

Why both layers: the Playwright test proves runtime behavior on the 3D side; the source-text tests are cheap regression guards that fire even without the browser/fixture stack up, and provide the same guard for the main webapp (which currently has no Playwright infra for the labeler — adding it is out of scope for this change).

## Out of scope

- No new Playwright infrastructure for the main webapp (no `window.__fl` debug proxy, no e2e conftest, no fixture wiring). The source-text test is the agreed regression guard there.
- No UI affordance, setting, or feature flag for the behavior — it is changed unconditionally.
- No other refactoring inside `_flAutoAdvanceBp` or its callers.
- Same-frame BP selector walk (the loop above the deleted block) is preserved.

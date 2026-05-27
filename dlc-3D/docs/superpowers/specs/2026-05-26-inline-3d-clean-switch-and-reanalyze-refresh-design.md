# Inline-3D: Clean Video-Switch + Refresh-After-Re-Analyze — Design Spec

**Date:** 2026-05-26
**Module:** `dlc-3D` (frontend only)
**Status:** Approved (brainstormed + systematic-debugging root cause; decisions below).
**Branch:** `feat/marker-editor-labeler-mechanics` (continues this session's markerEditor/inline work; not yet merged).

## Goal

Fix two video-switch bugs on the inline-3D analysis card:
- **Bug 1:** switching videos with the kinematics view on auto-snaps to the latest h5 + paints markers (box reads unchecked while markers show). Make switching a **clean** reset; markers appear only when the user turns the kinematics view on.
- **Bug 2:** after switching + re-running analysis, new markers + the coverage timeline don't refresh until a manual h5 re-select. Invalidate the stale client caches after analysis.

## Root cause (from systematic-debugging)

- **Bug 1:** `_resetForOpen` unchecks the overlay box but keeps Finalize checked + `setEditable(true)`; `videoLoad → _refreshOverlayH5Variants` auto-picks the single h5 variant → `_applyOverlayPrimary` renders, because `renderActive = overlayEnabled || editingAllowed` (editing armed). The earlier marker-edit fix also had `_applyOverlayPrimary` force-check the overlay box. Net: markers paint on switch with the auto-picked latest h5 while the box reads unchecked.
- **Bug 2:** inline analysis OVERWRITES the same h5 in place, but `markerEditor.posesCache` (key `(h5,threshold)`) and `_coverageCache` (key `${h5}:${thr}:${w}`) have no mtime/version and are never invalidated after analysis; `posesCache` only rebuilds when `setPrimary` makes a fresh layer (which the post-analysis path does only for a single variant). `_resetForOpen` also never clears the markerEditor layer, so a switch can leave the previous video's layer live.

## Decisions

- **Clean switch:** on switch/open the kinematics view is OFF, nothing auto-loaded, no markers drawn (Finalize stays checked = armed). The user turns the view on to see/edit.
- **On turning the view ON: auto-pick the LATEST h5 variant** (regardless of variant count) and render; editing works (Finalize checked).

## Scope

Frontend only, inline-3D card + the shared markerEditor cache invalidation. Bug 1 behavior changes are inline-only (`inline_analysis_3d.js`); the markerEditor invalidation method is shared (additive — View Analyzed is unaffected, it runs no analysis). No backend change, no new routes, no player fork. Out of scope: changing View Analyzed's switch behavior; the data/save layer.

## Files

- Modify: `src/static/inline_analysis_3d.js` — `_resetForOpen` (clear markerEditor layer + reset overlay state); `_refreshOverlayH5Variants` (populate dropdown only, NO auto-pick on switch); overlay-toggle handler (on ON: enable + auto-pick latest + render); `_applyOverlayPrimary` (drop force-enable-overlay; keep setEditable arming); post-analysis done handlers (`_onAnalyzeClick`, `_onAnalyzeRangeConfinedClick`) — invalidate caches + refresh.
- Modify: `src/static/components/viewer/features/marker_editor.js` — add a pose-cache invalidation method (e.g. `invalidatePoses()` / `refreshPoses()`): clears the layers' `posesCache` and re-fetches + re-renders the current frame.
- Modify: `tests/test_inline_analysis_3d_ui_isolation.py` — clean-switch + refresh-after-analyze source assertions.
- Modify: `tests/test_marker_editor_feature.py` — contract for the new invalidation method.
- (Possibly) `tests/unit/*.mjs` — if any pure logic is extracted (e.g. "pick latest variant").

## Behaviors

### B1 — Clean switch (no auto-show)
`_resetForOpen` (on every video open/switch):
- `#ia3d-overlay-toggle` unchecked + `setOverlayEnabled(false)` (already).
- **NEW:** clear the markerEditor's layers/poses for the previous video — `_markerEditor?.setPrimary(null)` (setPrimary(null) already nulls the primary + sibling); reset `_overlayPrimaryH5 = null` (already) and the primary `<select>` to its placeholder.
- Finalize stays checked (armed); `_coverageCache.clear()` (already).
- Result: overlay off + no primary ⇒ nothing renders even though editing is armed (no cached poses to draw, no chips).

`_refreshOverlayH5Variants` (on `videoLoad`): populate the primary `<select>` options for the new video, but **do NOT auto-pick / call `_applyOverlayPrimary`**. Leave the selection on the placeholder.

### B2 — Turn view ON → show + auto-pick latest
The overlay-toggle ("Show Kinematic Markers") `change` handler:
- ON: `setOverlayEnabled(true)`; if no primary is selected yet, **auto-pick the LATEST variant** (determine "latest" from the `/dlc/viewer/h5-variants` ordering / mtime — confirm in code) → set the `<select>` + `_applyOverlayPrimary(latest)`; reveal controls + chips; refresh coverage. Editing works (Finalize checked).
- OFF: `setOverlayEnabled(false)` (markers hide); controls/chips hidden.

`_applyOverlayPrimary`: **remove** the block that force-checks `#ia3d-overlay-toggle` / dispatches its change (the overlay is now driven explicitly by the toggle handler). **Keep** `setEditable(true)` when Finalize is checked (arms editing the moment a primary is set — preserves the first-open edit-arming).

### B3 — Refresh after re-analyze (cache invalidation)
`markerEditor.invalidatePoses()` (new): clear every layer's `posesCache` and re-fetch + re-render the current frame (so an in-place-overwritten h5 repaints). Add to the public API; does not change the save path.

Post-analysis done handlers (`_onAnalyzeClick`, `_onAnalyzeRangeConfinedClick`), after the run completes and the viewer reloads:
- **Invalidate `_coverageCache`** for the analyzed h5 (delete keys prefixed with the h5 path, or clear the cache) so the main timeline re-fetches.
- Call `_markerEditor.invalidatePoses()` so the overlay repaints the new poses.
- Re-run the coverage refresh (now cache-busted) so the newly-labeled frame shows.
- This must work whether the video has one or multiple h5 variants (don't gate on variant count).

## View Analyzed (`viewer_3d.js`) regression guard

Bug 1 changes are inline-only. The shared markerEditor gains `invalidatePoses()` (additive; View Analyzed never calls it). Verify View Analyzed still: renders on overlay-on, edits, switches videos as before. No behavior change expected.

## Error handling

- `setPrimary(null)` on switch must be safe (it already early-returns/clears when h5 is null).
- `invalidatePoses()` no-ops if there are no layers / no current frame.
- "Latest variant" pick tolerates an empty variant list (no-op; overlay-on shows nothing until analysis exists).

## Testing

- **pytest `test_inline_analysis_3d_ui_isolation.py`:** `_resetForOpen` clears the markerEditor primary (`setPrimary(null)`); `_refreshOverlayH5Variants` no longer auto-picks on videoLoad (no `_applyOverlayPrimary` call in its single-variant branch); the overlay-toggle ON handler auto-picks the latest variant + enables; `_applyOverlayPrimary` no longer dispatches the overlay toggle; the post-analysis handlers invalidate `_coverageCache` + call `invalidatePoses`.
- **pytest `test_marker_editor_feature.py`:** `invalidatePoses` exists + clears `posesCache` + re-renders (source assertion).
- **pytest `test_video_viewer_policy.py`:** stays green.
- **Live verify (read-only)** on a posed video: switching videos lands clean (view off, no markers, dropdown on placeholder); turning the view on shows the latest h5's markers + editing works; View Analyzed unchanged. Bug-2 (post-analysis refresh) is verified by code + unit/contract tests (NOT by running analysis against protected fixtures); if a safe re-analyze path exists it may be exercised, otherwise documented as covered by tests.

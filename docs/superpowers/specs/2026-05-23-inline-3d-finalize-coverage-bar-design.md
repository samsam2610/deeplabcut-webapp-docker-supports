# Inline 3D — `_analyzed` Coverage Bar in the Finalize Panel — Design

**Date:** 2026-05-23
**Status:** Approved (pending implementation plan)
**Repos:** `deeplabcut-webapp-docker-supports/dlc-3D` (frontend) + `deeplabcut-webapp-docker` (one backend param), branch `feat/viewer-3d-onto-library` (dlc-3D) / `feat/3d-inline-analysis` (main webapp)

## Context

The inline 3D card already paints a likelihood-filtered marker-coverage layer on the main seek timeline from the WORKING analyzed h5 (`/dlc/viewer/pose-coverage?…&threshold=`). This adds the same idea for the FINALIZE workflow: a separate "FINALIZED" coverage bar inside the Finalize panel showing which frames exist in the canonical `_analyzed` file. Because `_analyzed` is finalized/curated, coverage is **presence-only (no threshold)**.

Findings:
- The Finalize panel (`#ia3d-finalize-controls`, revealed by the `#ia3d-finalize-toggle`) finalizes a frame range into the canonical `_analyzed` file via `POST /dlc/project/inline-analysis/finalize-range` (handler `_ia3dFinalizeOne` in `inline_analysis_3d.js`; written by `_onFinalizeAddClick`). Cam0's working h5 = `_overlayPrimaryH5`, cam1's = `_siblingPrimaryH5`.
- `GET /dlc/project/analysis-file/status?video_path=<v>` already returns `{initialized, h5_path, csv_path}` — `h5_path` is the canonical `<stem>_analyzed.h5` (`dlc/canonical.py: canonical_h5_path`). The `_analyzed` file has the canonical DLC structure (per-bodypart x/y/likelihood); `write_empty` makes it dense (all-NaN) and finalize fills frames, so a frame "has a finalized label" iff ≥1 bodypart has a **finite x**.
- The main-timeline coverage uses the `coverage_timeline.mjs` reducer (`coverageRects(buckets,width)`, `xToFrame(px,width,frameCount)`) + a draw routine (`_drawSeekTimeline`) + `/dlc/viewer/pose-coverage` returning `{buckets,n_frames,n_buckets}` computed from the LRU-cached `poses_np` and downsampled.

## Components

### 1. Backend — `mode=presence` on `/dlc/viewer/pose-coverage` (main webapp)
Add an optional `mode` **keyword** arg to the EXISTING `_coverage_buckets(poses_np, threshold, n_buckets, mode="likelihood")` — keep its current positional signature so the existing test (`_coverage_buckets(poses, threshold=0.6, n_buckets=3)`) is unchanged. Only the per-frame mask differs:
```python
def _coverage_buckets(poses_np, threshold, n_buckets, mode="likelihood"):
    n = int(poses_np.shape[0]) if poses_np is not None else 0
    if n == 0:
        return []
    if mode == "presence":
        covered = ~_np.isnan(poses_np[:, :, 0])              # finite-x → has a finalized label
    else:
        covered = poses_np[:, :, 2] >= float(threshold)      # existing likelihood filter
    covered = covered.any(axis=1)
    # … unchanged downsample (idx = arange(n)*b//n; logical_or.at) …
```
The route passes `mode = request.args.get("mode", "likelihood")` into the call. Backward-compatible (default unchanged).

### 2. Finalize coverage bar (inline card)
Add `<canvas id="ia3d-finalize-coverage" height="14" …>` inside `#ia3d-finalize-controls` (with a small "Finalized" label), styled like the main timeline (`var(--bg)` track + border). It draws marker-coverage in a **distinct amber color** (vs the main timeline's accent) so "finalized" reads differently from "detected", plus a playhead, plus click/drag seek — same UX as the main timeline.

### 3. Shared draw helper (inline)
Factor the main-timeline draw into a small parameterized helper so both bars reuse it:
```
_drawCoverageBar(canvas, buckets, markColor)  // clear track → coverageRects fills → playhead
```
`_drawSeekTimeline` becomes `_drawCoverageBar(seekCanvas, _coverageBuckets, accent)`; the finalize bar uses `_drawCoverageBar(finalizeCanvas, _finalizeCoverageBuckets, amber)`. Click/drag seek wiring is shared/mirrored (both call `xToFrame` → `viewer.seek`). Redraw both on `frameChange` (playhead).

### 4. Data flow
- On Finalize-toggle ON (with a cam0 video loaded): `_refreshFinalizeCoverage()` → `GET /dlc/project/analysis-file/status?video_path=<cam0 video>`; if `initialized`, fetch `/dlc/viewer/pose-coverage?h5=<status.h5_path>&mode=presence&buckets=W`, store `_finalizeCoverageBuckets`, redraw. If not initialized → empty buckets (track only).
- **After every successful Finalize-Add** (`_onFinalizeAddClick`, once the range is written): invalidate the cached `_analyzed` coverage and call `_refreshFinalizeCoverage()` so the bar grows. (The backend `viewer_load_h5` cache is mtime-keyed → it reloads the just-written `_analyzed` file automatically; the frontend just refetches.)
- Cache: keyed by the `_analyzed` h5 path (presence-mode → no threshold dependency); cleared on finalize-add and in `_resetForOpen`.
- Threshold changes do NOT affect this bar (presence-only).

## Error handling
- `analysis-file/status` not initialized / fetch fails → empty finalize bar (track only); never block.
- Finalize bar only visible/fetched when the Finalize toggle is on.
- cam0 video path = `_iaCurrentVideoPath || _iaBrowseVideoPath` (the same value the finalize-add uses as `cam0Video`); reuse that resolution.

## Testing
- **backend** (`deeplabcut-webapp-docker/tests/test_pose_coverage.py`): `mode=presence` → a frame with a finite x (any bodypart) is covered regardless of likelihood; an all-NaN-x frame is not; `mode` absent → unchanged likelihood behavior.
- **inline contract** (`tests/test_inline_analysis_3d_ui_isolation.py`): `#ia3d-finalize-coverage` canvas present in the card; JS wires `analysis-file/status` + `pose-coverage?…mode=presence`; `_refreshFinalizeCoverage` invoked from the finalize toggle handler AND after finalize-add.
- **live verify** (OM-2 fixture, scratch — do NOT write to protected dirs): if a real finalize can't be run without writing `_analyzed` into `/user-data`, verify the bar renders + the status/coverage fetch fire on toggle, and rely on the backend test for the presence compute. (Finalize-add itself writes `_analyzed`; only exercise it if a scratch project/video is available.)

## Out of scope
- A separate cam1 `_analyzed` bar (cam0's represents the finalized ranges; both cams finalize together over the same range).
- The main timeline (unchanged).

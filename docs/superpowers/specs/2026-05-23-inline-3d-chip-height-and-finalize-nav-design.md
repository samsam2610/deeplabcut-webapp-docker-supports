# Inline 3D — Stable Chip-List Height + Finalize-Bar Region Nav — Design

**Date:** 2026-05-23
**Status:** Approved (pending implementation plan)
**Repo:** `deeplabcut-webapp-docker-supports/dlc-3D`, branch `feat/viewer-3d-onto-library`. Frontend-only (no backend changes).

## Context

Two refinements to the inline 3D card:

1. **Chip-list height jump.** The body-part chips (`#ia3d-bp-chips`, `flex-wrap`) toggle a per-chip checkmark via the `.labeled` class as you move between frames (`markerEditor.updateBpChips` sets `.labeled` for body parts posed at the current frame). The checkmark changes chip width, so the list re-wraps to a different row count and its height changes — making the timeline and everything below it jump up/down between frames with many vs. no markers.
2. **No region nav on the FINALIZED bar.** The status/note timeline has ◀ ▶ buttons that jump to the next/prev annotated frame (`findMatchingFrame` reducer); the new finalize coverage bar has none.

**User decision:** keep BOTH parts inside the inline card (Part 1 is NOT a shared-markerEditor change).

## Components

### 1. Reserve the chip list's max height (inline-only)
Reserve the list's tallest layout once per body-part set so per-frame checkmark toggles can't reflow it.
- **CSS** (`inline_analysis_3d.css`): a measuring class that force-shows every checkmark (so measurement reflects the widest chips), without touching `.labeled`:
  ```css
  #inline-analysis-3d-card #ia3d-bp-chips.ia3d-measuring .vv-bp-check { display: block; }
  ```
- **JS** (`inline_analysis_3d.js`): `_reserveBpChipHeight()` —
  ```
  c = $("ia3d-bp-chips"); if (!c) return;
  c.style.minHeight = "";            // reset so we measure natural max
  c.classList.add("ia3d-measuring"); // all checkmarks shown → widest wrap
  const h = c.offsetHeight;
  c.classList.remove("ia3d-measuring");
  if (h > 0) c.style.minHeight = h + "px";
  ```
  Call it right after `await _markerEditor.setPrimary(h5)` in `_applyOverlayPrimary` (chips are in the DOM by then; this is once per project's chosen h5 = per project's body-part set). Reset `#ia3d-bp-chips` `minHeight` to `""` in `_resetForOpen`.
- This reserves max height without interfering with markerEditor's class management (the measuring class only flips `display`, never `.labeled`). markerEditor is untouched. Stabilizing the chip list keeps every element below it fixed.

### 2. Finalize-bar region nav (inline-only)
Add ◀ ▶ buttons beside the FINALIZED coverage bar; jump to the previous/next finalized region.
- **Reducer** (`internal/coverage_timeline.mjs`, node-tested): `nextCoveredBucket(buckets, fromBucket, dir)` → the start bucket of the next (`dir=1`) or previous (`dir=-1`) covered RUN relative to `fromBucket` (skipping the run `fromBucket` is inside), or `null` if none. Plus a small `bucketToFrame(bucket, nBuckets, frameCount)` (or reuse inline math) to map the result to a frame.
- **Markup** (`card_inline_analysis_3d.html`): a label + ◀ ▶ buttons (`#ia3d-finalize-prev`, `#ia3d-finalize-next`) on the same row as the "Finalized frames" label, mirroring the status/note bar's nav row styling.
- **JS** (`inline_analysis_3d.js`): on click, compute the current frame's bucket = `floor(currentFrame / frameCount · nBuckets)`, call `nextCoveredBucket(_finalizeCoverageBuckets, curBucket, dir)`, map to a frame, `_viewer.pause()` + `_viewer.seek(frame)`. Disable both buttons when `_finalizeCoverageBuckets` is empty/absent (mirror the status/note `updateNavDisabled` pattern); re-enable in `_redrawFinalizeCoverage`/after a coverage fetch.
- "Marked instance" = the start of a finalized region, at bucket granularity — consistent with what the bucketed bar displays (frame-exact nav would need frame-level coverage; out of scope).

## Data flow / error handling
- Part 1: `setPrimary` → chips built → `_reserveBpChipHeight()` measures + pins min-height. If the chips container is empty/absent, no-op (no min-height). Width changes (rare card resize) won't shrink below the reserved max — they could leave extra space, acceptable; recompute happens on the next `setPrimary`.
- Part 2: nav no-ops when no coverage; seeks are clamped by `_viewer.seek`. Buckets come from the existing `_finalizeCoverageBuckets` (presence coverage already fetched in the finalize feature).

## Testing
- **node** (`tests/unit/test_viewer_coverage_timeline.mjs`): `nextCoveredBucket` — next run start forward, prev run start backward, skips the current run, returns null when none ahead/behind; `[1,1,0,0,1,1,0,1]` style fixtures.
- **inline contract** (`tests/test_inline_analysis_3d_ui_isolation.py`): `_reserveBpChipHeight` defined + called after `setPrimary`; `.ia3d-measuring` CSS present; `#ia3d-finalize-prev`/`#ia3d-finalize-next` in the card + wired (`nextCoveredBucket`).
- **live verify** (OM-2 fixture): chip-list height stays constant while stepping across frames with many vs. zero markers (measure `#ia3d-bp-chips` offsetHeight at two frames → equal); finalize nav buttons disabled when `_analyzed` not initialized; (region jump exercised against bucket fixtures in the node test, since OM-2 has no `_analyzed`).

## Out of scope
- Sharing Part 1 with View Analyzed (kept inline per the user).
- Frame-exact finalize nav (region/bucket granularity only).

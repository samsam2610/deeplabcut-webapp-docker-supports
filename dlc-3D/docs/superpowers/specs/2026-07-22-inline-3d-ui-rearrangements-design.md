# Inline 3D Analysis — UI Rearrangements

**Date:** 2026-07-22
**Status:** Approved
**Scope:** Four independent UI/GUI changes in the "3D Inline Analysis" card. No new
backend routes; one one-line allow-list addition in the main repo.

---

## 1. 3D coverage nav arrows

The `3D coverage` bar (`#ia3d-triangulate-coverage`) currently supports click/drag-seek
but has **no ◀ ▶ navigation buttons**, unlike the `Finalized frames` bar directly above
it (`#ia3d-finalize-prev` / `#ia3d-finalize-next` → `_finalizeNav()`).

**Markup** — in `card_inline_analysis_3d.html`, inside the `#ia3d-triangulate-coverage-wrap`
bar-header, add two buttons mirroring the finalize pair exactly (same classes, inline
style, `disabled` default):

- `#ia3d-triangulate-prev` — title "Previous triangulated region", label `◀`
- `#ia3d-triangulate-next` — title "Next triangulated region", label `▶`

**JS** — in `inline_analysis_3d.js`:

- Add `_triangulateNav(dir)` mirroring `_finalizeNav(dir)`:
  `nextCoveredBucket(_triCoverageBuckets, frameToBucket(_viewer.currentFrame(), fc, nB), dir)`,
  then `_viewer.pause()` + `_viewer.seek(f)`. Because the 3D coverage endpoint returns
  buckets only (no per-bucket frames), seek to `bucketToFrame(b, nB, fc)` — the **same**
  target the bar's existing click-seek already lands on.
- In `_redrawTriangulateCoverage`, enable/disable `#ia3d-triangulate-prev/next` on
  `_triCoverageBuckets` presence — exactly as `_redrawFinalizeCoverage` gates its buttons.
- Wire the two click handlers next to the existing finalize-nav wiring.

Behaviour: identical to the Finalized-frames nav — jump the playhead to the previous/next
triangulated region.

## 2. "Triangulate all for tag" button

Mirror *Analyze for tag* (`_onAnalyzeTagClick`) but run triangulation instead of 2D
analysis, over the **same before/after windows** of the locked note tag.

**Markup** — inside `.ia3d-tag-batch`, add `#ia3d-btn-triangulate-tag`
("▲ Triangulate all for tag"), positioned **above** the `#ia3d-tag-hint` line (i.e. after
`#ia3d-btn-analyze-tag`, before the hint span). Gated identically to *Analyze for tag*:
finalize on + `#ia3d-tag-lock` checked + sibling present. It **shares the same Lock-tag
checkbox** as *Analyze for tag* — no separate lock.

**JS** — `_onTriangulateTagClick()`:

- Same guards + range collection as `_onAnalyzeTagClick`: `activeNotes.length === 1`,
  `tagKeyframes(rows, tagValue)`, before/after from `#ia3d-finalize-before/after`,
  `mergeWindows(frames, before, after, frameCount)`.
- Confirm dialog worded for triangulation (N tagged frames → M ranges → total frames).
- For each merged range, `POST /dlc/project/triangulate/range`
  `{ cam0_video, start_frame: r.start, n_frames: r.n }` (the route handles the sibling
  cam server-side — **one call per range, cam0 only**, unlike analyze's per-cam submits),
  polling each `req_id` with `_pollTriangulateReq`.
- Progress/status reported in the **Triangulate panel's `#ia3d-triangulate-range-status`**
  line (the natural home for triangulation progress), not the tag last-run line.
- On completion: `await _refreshTriangulateCoverage()`; if `_pose3d && _pose3dLoaded`,
  `await _loadPose3d()`.
- Add `#ia3d-btn-triangulate-tag` to `_refreshAnalyzeEnablement` so it follows the same
  enable/disable rules as `#ia3d-btn-analyze-tag`.

**No new backend route** — reuses the existing `POST /dlc/project/triangulate/range`.

## 3. Two separator lines in Finalize Analysis

Add a thin divider `.ia3d-group-sep` (`border-top:1px solid var(--border); margin:.5rem 0`)
in `inline_analysis_3d.css`, and two instances in the card:

- one **below `#ia3d-start-hint`** — separates the *Start from current / Start for range*
  group from the *tag-batch* group.
- one **below `#ia3d-tag-hint`** (end of `.ia3d-tag-batch`) — separates the *tag-batch*
  group from the *Add current frame to labeled-data* button.

## 4. Editable 3D background color (persisted per project)

Currently hard-coded: `scene.background = new THREE.Color(0x12141a)` in `pose3d_viewer.js`.

- **pose3d_viewer.js:** add `setBackground(hex)` to the returned viewer object —
  `scene.background.set(hex)` + a re-render — and keep `#12141a` as the default. Include
  it in the returned API object.
- **Markup:** `<input type="color" id="ia3d-pose3d-bg" value="#12141a">` with a small
  label, inside `#ia3d-pose3d-controls`, near the marker-size slider.
- **JS:** on `input`, `_pose3d.setBackground(el.value)` + debounced save to
  `POST /dlc/project/ui-setting` `{ key: "pose3d_bg_color", value: <hex> }`. On pose3d
  load, `GET /dlc/project/ui-setting?key=pose3d_bg_color`; if present, apply it and set the
  input value.
- **Main repo (one line):** add `"pose3d_bg_color"` to `_UI_SETTING_KEYS` in
  `src/dlc/inline_analysis.py` (currently
  `{"finalize_window", "clip_window", "postfix_tags", "status_tags", "note_tags"}`).

---

## Files & restarts

- **dlc-3D:** `src/templates/partials/card_inline_analysis_3d.html`,
  `src/static/inline_analysis_3d.js`, `src/static/inline_analysis_3d.css`,
  `src/static/pose3d_viewer.js` → **dlc-3d restart** (html/template is a bind-mount; JS is
  hot but restart is harmless and covers the template).
- **main repo:** `src/dlc/inline_analysis.py` (allow-list key) → **flask restart**.

## Tests

Following the existing `test_inline_3d_*` / static-guard patterns:

- Markup guards: `#ia3d-triangulate-prev/next` in the 3D-coverage header;
  `#ia3d-btn-triangulate-tag` present and above `#ia3d-tag-hint`; two `.ia3d-group-sep`
  dividers after the two hints; `#ia3d-pose3d-bg` color input in the pose3d controls.
- JS-source guards: `_onTriangulateTagClick` defined, POSTs `/dlc/project/triangulate/range`,
  reuses `mergeWindows`; `_triangulateNav` defined and wired to the two nav buttons;
  `#ia3d-btn-triangulate-tag` referenced in `_refreshAnalyzeEnablement`.
- pose3d_viewer.js guard: `setBackground` exported.
- **main repo:** assert `"pose3d_bg_color"` is in `_UI_SETTING_KEYS`.

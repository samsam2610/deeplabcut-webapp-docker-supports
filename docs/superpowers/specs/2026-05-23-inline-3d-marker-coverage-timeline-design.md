# Inline 3D — Marker-Coverage Timeline + Frame-Labeler Chips — Design

**Date:** 2026-05-23
**Status:** Approved (pending implementation plan)
**Repos:** `deeplabcut-webapp-docker-supports/dlc-3D` (frontend + chip lib) and `deeplabcut-webapp-docker` (one additive backend route), branch `feat/viewer-3d-onto-library`

## Context

Three refinements to the inline 3D analysis card's viewer:

1. **Main timeline styling** — the seek control should match the status/note bars (dark recessed track).
2. **Marker-coverage timeline (new)** — when "Show kinematic markers" is on, the main timeline should paint *where in the video* markers exist, so the user sees which frames were detected. Must be efficient.
3. **Body-part marker chips** — still don't match the frame labeler's chips.

Investigation findings:
- Pose data + h5 reading live in the main webapp `deeplabcut-webapp-docker/src/dlc/viewer.py`; `viewer_load_h5(h5_path)` loads the full DataFrame **once and caches it (LRU, max 5)**. So once the overlay is on, per-frame marker presence is a cheap vectorized op on the in-memory df.
- The status/note bars are drawn by `statusNoteTimeline` (`features/status_notes.js`) via `drawBar` (one `fillRect` per annotated frame) + `drawCursor` + click-to-seek (`timelineSeek`). The main timeline is currently an `<input type=range #ia3d-seek>`.
- markerEditor's `rebuildBpChips` renders only the bare bodypart name (`chip.textContent = bp`). The frame labeler's `fl-bp-chip` (frame_labeler_3d.js ~930) renders `<span fl-bp-dot>` + `<span fl-bp-name>` + a checkmark `<svg fl-bp-check>` (shown when `.labeled`) + an eye-slash `<svg fl-bp-eye-slash>` (shown when `.vis-hidden`), colored via `--fl-color`. That check/eye structure is the gap.

**User decision:** marker coverage is painted ON the main timeline (the seek bar becomes a status/note-style canvas), not a separate bar. Coverage is **likelihood-filtered** and **recomputes when the threshold changes**.

## Components

### 1. Main timeline as a canvas bar (inline card) — covers #1 + #2 display
Replace `<input type=range #ia3d-seek>` with `<canvas id="ia3d-seek-canvas">` styled like the status/note bars (dark `var(--bg)` track, border, ~12px tall). Drawn by inline consumer glue mirroring `statusNoteTimeline`'s draw helpers:
- **Track**: clear to the recessed bg each redraw.
- **Coverage marks**: when overlay is on and a primary h5 is chosen, `fillRect` (accent color) per covered bucket from the fetched coverage (see §2). When overlay is off / no h5, no marks (plain seek bar).
- **Playhead**: a 1–2px cursor at `currentFrame / (frameCount-1) * width`, redrawn on the viewer's `frameChange`.
- **Seek**: `mousedown` + `mousemove` (while pressed) + `click` → map x → frame → `viewer.seek(n)` (drag-scrub + click-jump). On `frameChange` the playhead follows.
Redraw triggers: `videoLoad`, `frameChange` (playhead), coverage-loaded, overlay toggle, threshold change.

### 2. Marker-coverage data — efficient, likelihood-filtered, threshold-reactive
New `GET /dlc/viewer/pose-coverage?h5=<abs>&threshold=<T>&buckets=<N>` in `deeplabcut-webapp-docker/src/dlc/viewer.py` (beside frame-poses). Logic:
- Load the DataFrame via the existing `viewer_load_h5` cache (no extra read).
- Select the likelihood sub-columns (DLC MultiIndex `(scorer, bodypart, "likelihood")`).
- `covered_per_frame = (likelihood_df >= T).any(axis=1)` → boolean per frame (vectorized).
- **Downsample to N buckets** (N ≈ canvas width, default ~600, capped): `bucket[i] = covered_per_frame[bucket_slice_i].any()`.
- Return `{ "buckets": [0/1, …], "n_frames": <int>, "n_buckets": <int> }`. Tiny payload.
- Validation: missing/invalid h5 → 404/422 with `{error}`; threshold defaults to the overlay default if absent.

Frontend (inline consumer):
- Fetch coverage when the overlay turns on / the primary h5 is set, and (debounced ~200 ms) whenever the likelihood threshold slider (`#ia3d-overlay-threshold`) changes.
- **Cache keyed by `(h5, threshold.toFixed(2))`** — repeated toggles/redraws don't refetch; only a new h5 or threshold triggers a fetch.
- On fetch resolve, store the buckets for the active h5 and redraw the main timeline.
- A node-tested pure reducer in `internal/*.mjs` (e.g. `coverageRects(buckets, width, height)` → list of `{x,w}` rects to fill, and `xToFrame(px, width, frameCount)` for seek mapping) keeps the downsample/scale math testable; the canvas draw + pointer wiring is the inline DOM glue that calls it.

### 3. Body-part marker chips → exact `fl-bp-chip` (shared markerEditor) — #3
Change markerEditor `rebuildBpChips` (`features/marker_editor.js`) to render the labeler's sub-structure instead of bare text:
```
<span class="vv-bp-dot"></span>
<span class="vv-bp-name">${bp}</span>
<svg class="vv-bp-check" …>✓</svg>
<svg class="vv-bp-eye-slash" …>⦰</svg>
```
keep `class="vv-bp-chip"`, `--bp-color`, the click (select) + dblclick (visibility) handlers. `updateBpChips` already toggles `.active`/`.labeled`/`.vis-hidden`. Add CSS (consumer card scope, both inline + view-analyzed) mirroring `.fl-bp-chip`: the `.vv-bp-dot` uses `--bp-color`; `.vv-bp-check` shown only on `.labeled`; `.vv-bp-eye-slash` shown only on `.vis-hidden`; `.vis-hidden` dims the chip. This makes the chips structurally + visually identical to the frame labeler's. Library change → View Analyzed inherits the richer chips (cam editing behavior unchanged).

## Data flow
- Coverage: overlay-on / primary-set / threshold-change → (debounced) fetch `/dlc/viewer/pose-coverage` → cache by `(h5,thr)` → redraw main timeline canvas.
- Playhead: `frameChange` → redraw cursor.
- Seek: canvas pointer → `viewer.seek`.
- Chips: markerEditor renders structure; `updateBpChips` toggles state classes; CSS shows check/eye.

## Error handling
- Coverage fetch failure / no h5 → draw the timeline with no coverage marks (plain seek bar); never block seeking.
- Threshold dragging → debounce so only the settled value is fetched; in-flight fetch superseded by the latest (guard by comparing the resolved key to the current `(h5,thr)`).
- Backend: bad h5 → error JSON; non-DLC h5 (no likelihood columns) → empty buckets (no coverage), not a 500.

## Testing
- **node** (`tests/unit/`): the bucket/scale reducer (downsample correctness; covered bucket iff any frame in range covered; x→frame mapping for seek).
- **backend** (`deeplabcut-webapp-docker` tests, or a dlc-3D-side request test): `/pose-coverage` returns N buckets; a frame above threshold → its bucket covered; below → not; non-finite likelihood treated as not-covered.
- **markerEditor contract** (`tests/test_marker_editor_feature.py`): `rebuildBpChips` emits `vv-bp-dot`/`vv-bp-name`/`vv-bp-check`/`vv-bp-eye-slash`.
- **inline contract** (`tests/test_inline_analysis_3d_ui_isolation.py`): `#ia3d-seek-canvas` present (range input gone); `/dlc/viewer/pose-coverage` wired; threshold change triggers coverage refetch.
- **live verify** (OM-2 fixture): coverage marks appear when overlay on; dragging the likelihood slider visibly changes coverage; click + drag seek works; chips show the check on labeled parts + eye-slash when a part is double-clicked off.

## Out of scope
- Other cards' main-timeline conversion (View Analyzed keeps its current seek; it only inherits the chip change).
- Per-bodypart coverage (coverage is "any bodypart ≥ threshold", matching "≥1 non-NaN/over-threshold marker").

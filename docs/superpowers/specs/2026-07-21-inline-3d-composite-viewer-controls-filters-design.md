# Inline 3D — composite 3D view (synced mini-cams) + on-screen controls + filters

**Date:** 2026-07-21
**Repos:** support module (`dlc-3D`, UI) + main repo (`deeplabcut-webapp-docker`, 2 backend changes)
**Depends on:** the three.js pose-viewer spike (poses-3d route, `pose3d_viewer.js`, vendored three.js).

## Goal

Turn the "3D View" panel into an anipose-style **composite** the user opens after triangulation:
a smaller duplicate of the multi-cam view (cam0 + cam1 frames) with the 3D skeleton below it,
**fully synced to the MAIN viewer** (frame position + playback). The user navigates with the
original viewer; the composite mirrors it. Plus on-screen 3D controls, live quality-threshold
sliders, and an on-the-go median re-filter.

## Concept / sync model

- The main `VideoViewer` (`#ia3d-viewer-mount`) stays the driver. Nothing relocates.
- The composite panel (revealed by the existing `#ia3d-pose3d-toggle`) contains:
  - **Top:** two mini `<img>` (cam0, cam1) mirroring the main viewer's current-frame tiles.
  - **Below:** the three.js 3D skeleton canvas (`#ia3d-pose3d-canvas`).
- **Sync:** on the main viewer's `frameChange(n)` → set each mini `<img>.src` from
  `_viewer.getTile(0/1).imgEl.src` (already decoded → instant), and call `pose3d.showFrame(n)`.
  Playback/seek/step are driven ONLY by the main viewer; the composite is a read-only mirror.
  (The 3D-specific controls below act on the 3D sub-view only.)
- Mirroring is a no-op when the panel is closed or a tile is absent (single-cam).

## Part 1 — Composite layout (support)

Template `dlc-3D/src/templates/partials/card_inline_analysis_3d.html`, inside
`#ia3d-pose3d-controls`:
- A mini multi-cam row: `#ia3d-pose3d-cam0` + `#ia3d-pose3d-cam1` (`<img>`, ~200px wide each,
  side by side, object-fit:contain). Hidden individually when the corresponding tile is absent.
- Below it, the existing `#ia3d-pose3d-canvas` container (~360px), now with an overlaid control
  cluster (Part 2).

## Part 2 — On-screen 3D controls (support + viewer module)

Overlay (absolutely positioned in the canvas container):
- **Home** button top-right → `resetView()` (fit to bounds).
- **Zoom + / −** → `zoomBy(1/1.2)` / `zoomBy(1.2)` (dolly camera along its view direction).
- **Orbit ← → ↑ ↓** d-pad → `orbit(±dAz, 0)` / `orbit(0, ±dPol)` (rotate camera around the
  controls target by a fixed increment, e.g. 15°).
Mouse `OrbitControls` still works. `pose3d_viewer.js` gains:
- `zoomBy(factor)` — scale the camera→target offset length (clamped to near/far), `controls.update()`.
- `orbit(dAzimuthRad, dPolarRad)` — via `THREE.Spherical` on the offset; clamp polar to
  `(epsilon, PI-epsilon)`; `controls.update()`.
- `resetView()` already exists (`_fitToBounds`).
Button ids: `#ia3d-pose3d-home`, `#ia3d-pose3d-zoom-in`, `#ia3d-pose3d-zoom-out`,
`#ia3d-pose3d-orbit-left/right/up/down`.

## Part 3 — Quality-threshold sliders (support + backend)

**Backend** (`src/dlc/canonical_3d.py::read_poses_3d`): add, parallel to `points`:
- `scores`: per frame, per bodypart → the `<bp>_score` value (or null when the point is null).
- `errors`: per frame, per bodypart → the `<bp>_error` value (or null).
- `error_max`: max finite error across populated points (for the slider's upper bound; null if none).
Contract additions only — existing keys unchanged. Route `poses-3d` returns them verbatim.

**Frontend**: two sliders in the panel — `#ia3d-pose3d-score-thr` (0..1, default e.g. 0.0 = show
all) and `#ia3d-pose3d-error-thr` (0..`error_max`, default = `error_max` = show all), with value
labels. `pose3d_viewer.js`:
- `load(data)` stores `scores`/`errors`.
- `setThresholds({score, error})` stores the thresholds and re-applies to the current frame.
- `showFrame(n)`: a joint is shown only if its point is finite AND `score >= scoreThr` AND
  `error <= errThr`; a bone is shown only if BOTH endpoints are shown. Instant, no server call.

## Part 4 — On-the-go median re-filter (support + backend)

**Backend** — new route `POST /dlc/project/triangulate/refilter` in `src/dlc/inline_analysis.py`:
- Body `{cam0_video, medfilt, offset_threshold}`. Validate (`_sec_check` → 403; missing cam0 →
  400; `medfilt` odd int in ~[1,199]; `offset_threshold` >= 0).
- Runs **synchronously in flask** (scipy present): determine the populated raw-3d span
  (min..max populated frame in `pose-3d/<pair>_3d.csv`), then call
  `canonical_3d.medfilt_range_and_splice(session_dir, pair_name, start, n,
  {"filter3d": {"medfilt": M, "offset_threshold": O}})` to rewrite `pose-3d-filtered/`.
- Absent raw canonical → 400 ("triangulate first"). Return `{ok, start, n, medfilt, offset_threshold}`.
- Add a small helper `canonical_3d.populated_span(session_dir, pair_name, source="raw")` →
  `(start, n)` or `None`, used by the route (and unit-testable).

**Frontend**: `#ia3d-pose3d-medfilt` (number, odd) + `#ia3d-pose3d-offset` (number) + `#ia3d-pose3d-apply`
button + `#ia3d-pose3d-refilter-status`. On Apply → POST `/dlc/project/triangulate/refilter`;
on success, refetch `poses-3d?source=filtered` and `load()` it, then `showFrame(current)`.
Prefill medfilt/offset defaults from the config-driven filtered values if easily available, else
sensible defaults (medfilt 17, offset 15).

## Wiring (support, `inline_analysis_3d.js`)

- Extend the pose3d wire fn: mirror mini-cams + `showFrame` on the main `frameChange` (add the
  mini-cam mirroring next to the existing `_pose3d.showFrame(n)` call). Guarded by `_pose3dLoaded`.
- Wire the on-screen control buttons → viewer methods; the two threshold sliders →
  `setThresholds`; Apply → refilter fetch + reload.
- Keep the existing toggle/open/fetch/reset behaviour.

## Tests

**Main repo** (`tests/`):
- `read_poses_3d` now returns `scores`, `errors`, `error_max` aligned to `points` (null where
  point is null); values match the CSV.
- `populated_span` returns the min..max populated span; None when empty.
- `refilter` route: rewrites the filtered canonical using the passed medfilt/offset (assert the
  smoothing differs from a different medfilt, or that a spike is removed); absent raw → 400;
  missing cam0 → 400; oob → 403. (Sync route — mirror the coverage-route test style.)

**Support repo** (`dlc-3D/tests/`):
- Markup guards: mini-cam imgs, the control buttons (home/zoom/orbit ids), both threshold
  sliders, medfilt/offset/apply present in the pose3d panel.
- Wiring guards: `pose3d_viewer.js` exports/handles `zoomBy`, `orbit`, `resetView`,
  `setThresholds`, and stores scores/errors; `inline_analysis_3d.js` mirrors
  `getTile(…).imgEl.src` into the mini-cams on frameChange, wires the buttons/sliders, and
  POSTs `/dlc/project/triangulate/refilter` on Apply.

## Deploy

Sync flask route + backend change → restart flask. Template change → restart dlc-3d container.
JS/vendor hot. Browser hard-refresh.

## Out of scope

Independent playback in the composite (it's a mirror), per-camera 2D marker overlay in the
mini-cams, trajectory trails, saving camera presets.

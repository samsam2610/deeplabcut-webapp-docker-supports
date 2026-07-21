# Inline 3D — mini-cam marker mirroring + 3D erase-by-raw-quality

**Date:** 2026-07-21
**Repos:** support (`dlc-3D`, mini-cam composite) + main (`deeplabcut-webapp-docker`, raw-quality in poses-3d)
**Depends on:** the composite 3D viewer (mini-cams + threshold sliders + `pose3d_viewer.js`).

## Goal

1. The mini cam0/cam1 frames in the 3D view show the **labeled markers exactly as the original
   viewer**, mirroring every original adjustment (threshold, marker-size slider, overlay on/off,
   bodypart visibility), scaled proportionally.
2. In the 3D skeleton, joints **below the quality threshold are erased**, not shown at their last /
   interpolated position — gated by the RAW triangulation quality even when displaying filtered
   (smoothed) coordinates.

## Part 1 — Mini-cam marker mirroring (support module)

**Fact:** each original tile is a stacked `tile.imgEl` (`.vv-frame-img`) + `tile.canvasEl`
(`.vv-overlay-canvas`); the overlay canvas is redrawn each frame by the marker editor and already
reflects the threshold / marker-size / overlay-toggle / bodypart-visibility state. So mirroring the
composite of img+overlay reproduces the original exactly and mirrors all adjustments for free.

### Template `card_inline_analysis_3d.html`
Change `#ia3d-pose3d-cam0` / `#ia3d-pose3d-cam1` from `<img>` to `<canvas>` (keep the `-wrap` divs,
each `flex:1 1 0`, so they fill width side-by-side). The wrappers still hide when the tile is absent.

### JS `inline_analysis_3d.js`
Replace `_mirrorPose3dCams()` (currently sets `<img>.src`) with a **composite** per cam:
- Get `tile = _viewer.getTile(i)`; require `tile.imgEl.naturalWidth > 0` (frame loaded), else skip.
- Size the mini `<canvas>` backing store to its CSS width and height = width × (imgEl aspect); set
  once / on change.
- `ctx.clearRect(...)`; `ctx.drawImage(tile.imgEl, 0,0, w,h)`; then `ctx.drawImage(tile.canvasEl,
  0,0, w,h)` — the overlay canvas represents the same frame rectangle, so scaling both to the mini
  rect aligns the markers. Hide the wrapper when the tile / imgEl is absent (single-cam).
- Run it on a **lightweight rAF loop while the 3D panel is open** (start on panel-open, stop on
  close/dispose), throttled to ~30fps — the main frame image and overlay both update async, so
  continuous mirroring avoids compositing a stale frame/overlay. Guard: no-op when
  `!_pose3dLoaded` or the panel is closed. Keep the existing `frameChange` hook harmless (the rAF
  loop is the source of truth; the frameChange call can simply request an immediate mirror).

Everything else (three.js viewer, sliders, refilter, params panel) untouched.

## Part 2 — 3D erase by raw quality (main repo)

### `src/dlc/canonical_3d.py::read_poses_3d`
When `source != "raw"` (i.e. filtered display): keep **positions/points from the filtered** canonical
but source **`scores`/`errors` from the RAW canonical**, aligned by frame number (`fnum`) + bodypart,
and compute `error_max` from the raw errors. `source == "raw"` is unchanged (both from raw).
- Alignment: for each populated filtered frame `f` and bodypart `bp`, `score = raw[f, bp_score]` if
  `f` exists in raw and the value is finite, else `null`; same for error. A filtered point whose raw
  frame has no triangulation (pure gap-fill) → `null` score/error (stays "no-gate" / shown).
- Implementation: read the raw canonical once (via `_read_csv`), build a `fnum → row` lookup, and
  fill score/error per emitted point from it. Absent raw canonical → score/error all `null`
  (positions still returned; behaves like today).
- Keep the payload shape identical (`scores`/`errors`/`error_max` keys unchanged) — only their SOURCE
  changes for the filtered case.

The frontend `showFrame` already erases gated joints (`m.visible = false`) — no change needed there;
it now receives real raw quality so the threshold actually erases low-quality joints in the filtered
view.

## Tests

**Main** (`tests/test_canonical_3d.py` / route test):
- `read_poses_3d(source="filtered")`: write a RAW canonical with a **low score** at some frame/bodypart
  and a FILTERED canonical that has a (smoothed/interpolated) point there; assert the returned `score`
  for that point equals the RAW low score (not the filtered file's value / not null), so a threshold
  above it would gate the joint. `error_max` comes from raw.
- A filtered frame absent from raw → that point's score/error is `null`.
- `source="raw"` unchanged (regression).

**Support** (`dlc-3D/tests/`):
- Markup guard: `#ia3d-pose3d-cam0`/`cam1` are `<canvas>` (not `<img>`).
- Wiring guard: `_mirrorPose3dCams` (or the composite fn) draws BOTH `imgEl` and `canvasEl`
  (`getTile(` + `.imgEl` + `.canvasEl` + `drawImage`), and a rAF mirror loop runs while the panel is
  open. Update the existing composite wiring guard that asserted `.imgEl.src` into an `<img>`.

## Deploy

Restart flask (poses-3d change) + dlc-3d (template). JS hot. Hard-refresh.

## Out of scope

Drawing 2D markers on the mini-cams when the ORIGINAL overlay is off (mirror reflects the original's
state); erasing pure gap-fill points (only genuinely below-threshold joints are erased, per decision).

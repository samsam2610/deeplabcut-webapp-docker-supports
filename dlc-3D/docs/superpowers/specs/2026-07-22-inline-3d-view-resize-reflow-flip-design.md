# Inline 3D View — resize, reflow, axis-flip

**Date:** 2026-07-22
**Status:** Approved
**Scope:** Restructure the `#ia3d-pose3d-panel` (3D View) internals; add persisted
width/height + flip-X/Y/Z controls. No new backend routes; one allow-list key in the
main repo.

Builds on `2026-07-22-inline-3d-ui-rearrangements-design.md` (background-colour picker
+ its ui-setting flow), which this mirrors.

---

## 1. Panel reflow

Restructure the inside of `#ia3d-pose3d-controls` (within `#ia3d-pose3d-panel`) to this
top→bottom order:

1. **Reset view** button + `#ia3d-pose3d-status` — unchanged, stays first.
2. **2D frame viewer** — the mini-cams row `#ia3d-pose3d-cams` (cam0/cam1) — unchanged,
   stays second.
3. **New flex row** (`display:flex; align-items:flex-start; gap`), tops aligned:
   - **Left column** = all the controls, stacked: the score / error / marker-size /
     background sliders (existing `#ia3d-pose3d-*-thr`, `-marker-size`, `-bg`), the NEW
     width / height inputs, the NEW flip X/Y/Z checkboxes, and the median re-filter row
     (`#ia3d-pose3d-medfilt` / `-offset` / `-apply` / `-refilter-status`). Give it a
     sensible fixed-ish width (e.g. a `.ia3d-pose3d-ctl-col` class, ~200–220px).
   - **Right** = the existing 3D-canvas viewport (the `position:relative` container
     holding `#ia3d-pose3d-canvas` + the zoom / orbit / home overlay buttons). Keep the
     zoom/orbit/home buttons as on-canvas overlays (do NOT move them into the left
     column). Drop the container's `margin:0 auto` centering; its size now comes from
     the width/height inputs (see §2).

Panel keeps its current position in the card (below the Triangulate / params panels).
The change is purely the internal reflow — the slider/refilter groups move up from below
the canvas to a left column beside it.

## 2. Width / Height controls (number inputs, px, persisted)

Two numeric inputs in the left column near Background:

- `#ia3d-pose3d-view-w` — default `460` (the current `max-width`).
- `#ia3d-pose3d-view-h` — default `520` (the current `height`).

On `input`/`change`, set the canvas-container's inline `width`/`height` to the px values.
The container's canvas is `width:100%;height:100%`, and `pose3d_viewer` already observes
the canvas via `ResizeObserver` → `_resize()`, so the renderer repaints automatically —
**no viewer method needed** for resize. Clamp to sane bounds (e.g. 200–1600 w, 200–1200 h).

## 3. Flip X / Y / Z (checkboxes, persisted)

Three checkboxes `#ia3d-pose3d-flip-x` / `-y` / `-z` in the left column.

- **pose3d_viewer.js:** add `setFlip(fx, fy, fz)` → `group.scale.set(fx?-1:1, fy?-1:1, fz?-1:1)`
  followed by a re-render (`renderer.render(scene, camera)` if present). `group` is the
  existing `THREE.Group` holding the pose spheres + skeleton (created in `init()`), so the
  grid/axes helpers (on the scene, not the group) stay world-oriented. Export `setFlip` in
  the returned viewer API object.
- On checkbox change → `_pose3d.setFlip(x,y,z)` + persist (see §4).

## 4. Persistence (one consolidated key)

Reuse the `pose3d_bg_color` ui-setting flow with ONE new key `pose3d_view_prefs` whose
value is JSON `{ w, h, flipX, flipY, flipZ }`:

- **Save:** on width/height input (debounced, like the bg save) and on any flip toggle,
  serialize the current `{w,h,flipX,flipY,flipZ}` and `POST /dlc/project/ui-setting`
  `{ key:"pose3d_view_prefs", value: JSON.stringify(prefs) }`.
- **Load:** `_loadPose3dViewPrefs()` — `GET /dlc/project/ui-setting?key=pose3d_view_prefs`,
  parse JSON; if present, apply width/height to the container + sync the number inputs,
  apply flips via `setFlip` + sync the checkboxes. Called once when the viewer is first
  created (right beside the existing `_loadPose3dBgColor()` call). Best-effort: a failed
  or absent/invalid setting leaves the 460×520 / no-flip defaults.
- **Main repo:** add `"pose3d_view_prefs"` to `_UI_SETTING_KEYS` in
  `src/dlc/inline_analysis.py`.

## 5. Files & restarts

- **dlc-3D:** `src/templates/partials/card_inline_analysis_3d.html` (reflow + new
  controls), `src/static/inline_analysis_3d.js` (wiring + `_loadPose3dViewPrefs` +
  save), `src/static/pose3d_viewer.js` (`setFlip`), `src/static/inline_analysis_3d.css`
  (`.ia3d-pose3d-ctl-col` + row helper) → **dlc-3d restart**.
- **main repo:** `src/dlc/inline_analysis.py` (allow-list key) → **flask restart**.

## 6. Tests

Following the existing `test_inline_3d_*` static-guard patterns:

- Markup: the reflow row exists with a left controls column and the canvas on the right,
  tops aligned; `#ia3d-pose3d-view-w`/`-h` number inputs (defaults 460/520) present;
  `#ia3d-pose3d-flip-x/y/z` checkboxes present; the reset row + mini-cams still precede
  the reflow row.
- JS-source: `setFlip` exported in pose3d_viewer's API and calls `group.scale.set`;
  `_loadPose3dViewPrefs` defined; width/height + flip inputs wired to setBackground-style
  live-apply + debounced save under `pose3d_view_prefs`.
- **Main repo:** assert `"pose3d_view_prefs"` in `_UI_SETTING_KEYS`.

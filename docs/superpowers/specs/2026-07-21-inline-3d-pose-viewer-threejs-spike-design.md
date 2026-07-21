# Inline 3D — three.js 3D pose viewer (spike)

**Date:** 2026-07-21
**Repos:** support module (`dlc-3D`, UI + vendored three.js) + main repo (`deeplabcut-webapp-docker`, one data route)
**Depends on:** the incremental anipose triangulation (pose-3d canonical CSVs already produced).

## Goal

Validate three.js as the renderer for triangulated 3D pose: a rotatable 3D view of the
reconstructed joints + skeleton for a stereo pair, **driven by the existing 2D player** so
it plays/seeks in lock-step with the camera videos. This is a **spike** — prove the
approach on real data (`khoai-lang` / `050626`) before polishing or considering a custom
renderer.

## Scope (spike)

- three.js scene: 16 joints as spheres (color per bodypart) + **skeleton bones** for the
  finger chains `Wrist→MCP-k→PIP-k→DIP-k` (k=1–4). Snout / Left-Paw / Pellet are lone dots.
- Ground grid + axes helper; `OrbitControls` (drag-rotate, scroll-zoom, right-drag-pan);
  auto-fit camera to the data bounding box; "Reset view" button.
- Playback = the existing player's `frameChange(n)` → update joint/bone positions to frame
  `n`. No separate play engine. Frames with no 3D (outside the triangulated range) → pose
  hidden.
- Default data source: **filtered** (`pose-3d-filtered/`).

**Deferred** (after the spike proves out): score-threshold hiding, raw/filtered toggle,
trails, exact 2D-overlay palette match, measurement tools.

## three.js sourcing / vendoring

- Vendor locally (module is offline/self-hosted; no CDN at runtime). Fetch at build time
  from unpkg (reachable; `npm`/`yarn` also present):
  - `three@0.160.0/build/three.module.js` → `dlc-3D/src/static/vendor/three/three.module.js`
  - `three@0.160.0/examples/jsm/controls/OrbitControls.js`
    → `dlc-3D/src/static/vendor/three/OrbitControls.js`
- **Bare-specifier fix (no bundler / no import map):** `OrbitControls.js` imports
  `from 'three'`. Rewrite that import to the relative path `from './three.module.js'` so it
  resolves without an import map. (Avoids editing the page `<head>`, which is a shared
  template.) Document the one-line edit in the vendored file's header comment.
- Pin the version in a short `vendor/three/VERSION` note for provenance.

## Data route (main repo)

`GET /dlc/project/triangulate/poses-3d?cam0_video=<path>&source=filtered|raw`
(in `src/dlc/inline_analysis.py`; reuse `_sec_check`, `pair_name_from_cam0`). Reads the
canonical (`pose-3d-filtered/` default, `pose-3d/` when `source=raw`) via `canonical_3d`.
Returns **populated frames only** (rows with any x/y/z), compact:

```json
{ "bodyparts": ["Snout","Wrist","MCP-1", ...],
  "skeleton":  [["Wrist","MCP-1"],["MCP-1","PIP-1"],["PIP-1","DIP-1"], ...],
  "frames":    [23110, 23111, ...],
  "points":    [ [[x,y,z]|null, ... per bodypart], ... per frame ],
  "bounds":    { "center":[cx,cy,cz], "size": s } }
```

- **Skeleton derivation** (server, from bodypart names, in a small pure helper e.g.
  `canonical_3d.derive_skeleton(bodyparts)`): for each finger k, connect
  `Wrist→MCP-k`, `MCP-k→PIP-k`, `PIP-k→DIP-k` when those names are present. Names not on a
  chain (Snout, Left-Paw, Pellet) get no bones. Generic/robust to missing joints.
- `bounds` = center + max extent across all populated points (for camera auto-fit).
- Absent canonical / no populated frames → `{bodyparts, skeleton, frames:[], points:[],
  bounds:null}` (200, not an error). Missing cam0/oob → 400/403 like the coverage route.

Contract is frozen here; both repos build to it.

## Support module — UI

### Template `dlc-3D/src/templates/partials/card_inline_analysis_3d.html`
A new collapsible panel **after** the Triangulate panel, same toggle-reveal pattern:
- `#ia3d-pose3d-toggle` (checkbox) reveals `#ia3d-pose3d-controls` (`.hidden`).
- Inside: `<canvas id="ia3d-pose3d-canvas">` in a fixed-height (~360px) container, a
  `#ia3d-pose3d-reset` button, and a `#ia3d-pose3d-status` span.

### New viewer module `dlc-3D/src/static/pose3d_viewer.js` (isolated)
A small factory `makePose3dViewer({ canvas, statusEl })` returning
`{ init(), load(data), showFrame(n), resetView(), dispose() }`:
- `init()` — lazily create the three.js `Scene`/`PerspectiveCamera`/`WebGLRenderer`
  (imported from `./vendor/three/three.module.js`) + `OrbitControls`, grid, axes, a render
  loop. Idempotent.
- `load(data)` — build sphere meshes per bodypart + `LineSegments` for the skeleton; store
  `frames`→index map + `points`; auto-fit camera to `bounds`.
- `showFrame(n)` — set sphere/bone positions from the row for frame `n`; hide the group if
  `n` has no 3D. Cheap (position updates only).
- `resetView()` — recenter camera on `bounds`.
Keep three.js entirely inside this module (isolation): the card controller only calls the
returned handle.

### Wiring in `inline_analysis_3d.js`
- On `#ia3d-pose3d-toggle` check: reveal controls, `viewer3d.init()`, fetch
  `/dlc/project/triangulate/poses-3d?cam0_video=<_cam0Path()>&source=filtered`, `load()` it,
  then `showFrame(currentFrame)`.
- Subscribe once: `_viewer.on("frameChange", (n) => pose3d.showFrame(n))` (guarded so it
  no-ops until the 3D panel has loaded data). Reset button → `resetView()`. Refetch after a
  successful triangulation run (so newly-added 3D shows).

## Tests

**Main repo** (`tests/`): route + skeleton tests —
- `derive_skeleton`: builds Wrist→MCP→PIP→DIP chains; omits absent joints; leaves
  Snout/Pellet unconnected.
- route: populated-only frames returned; `source=raw` vs `filtered` reads the right file;
  bounds computed; absent canonical → empty frames (200); missing cam0 → 400; oob → 403.

**Support repo** (`dlc-3D/tests/`):
- Markup guard: `#ia3d-pose3d-toggle` + `#ia3d-pose3d-canvas` present, controls hidden by
  default, panel after the Triangulate panel.
- Vendor guard: `vendor/three/three.module.js` + `OrbitControls.js` exist and OrbitControls
  imports from the relative `./three.module.js` (not bare `'three'`).
- JS wiring guard: `inline_analysis_3d.js` imports `pose3d_viewer.js`, fetches
  `/dlc/project/triangulate/poses-3d`, and wires `showFrame` to `frameChange`.
- (WebGL rendering itself isn't unit-tested headless; keep frame-indexing logic as a small
  pure function if practical.)

## Deployment

- `npm`/unpkg reachable → vendor step runs at build. No runtime CDN.
- Restart flask (new route) + dlc-3D container (template); JS/vendor served hot from
  `src/static`. Browser hard-refresh.

## Out of scope

Threshold/raw-filtered toggles, trails, palette parity, cross-session camera sync,
measurements — all follow once three.js is validated.

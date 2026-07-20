# Inline 3D — "Triangulate" panel: initialize anipose folder (Phase 1)

**Date:** 2026-07-20
**Module:** `dlc-3D` (support module, git root `deeplabcut-webapp-docker-supports`)
**Scope:** Phase 1 only — scaffold the on-disk anipose folder layout for a stereo pair.
The actual anipose triangulation run is a later phase.

## Goal

Add a **Triangulate** checkbox to the 3D Inline Analysis card, directly **above** the
Dataset Curation panel. Unchecked by default. Checking it reveals a controls block whose
only Phase-1 action is a button that initializes the currently-selected stereo video pair
into the anipose folder format inside their current folder.

## UI

Template: `dlc-3D/src/templates/partials/card_inline_analysis_3d.html`
Inserted immediately **before** `#ia3d-curation-panel` (currently line ~480), as its own
toggle-reveal section mirroring the Dataset Curation pattern (NOT nested inside curation).

```
☐ Triangulate                                  (#ia3d-triangulate-toggle, unchecked default)
  └─ #ia3d-triangulate-controls (.hidden) ──
     [ ⚙ Initialize into anipose format ]      (#ia3d-anipose-init-btn)
     <status line>                             (#ia3d-anipose-init-status)
```

- Toggle reveals/hides `#ia3d-triangulate-controls` via the `.hidden` class — same wiring
  style as `#ia3d-curation-toggle` → `#ia3d-curation-controls`.
- Button enabled only when a cam0/cam1 pair is resolvable for the current selection
  (mirror existing pair-dependent gating).

## JS

Controller: `dlc-3D/src/static/inline_analysis_3d.js` (hot-reloads; no restart needed).

- Wire the toggle to reveal/hide controls (copy the `_curationChromeWired` idempotent-wire pattern).
- On button click: `POST /dlc-3d/anipose/init` with `{ cam0_video: <selected cam0 path> }`.
  Disable button while running; render the JSON result into `#ia3d-anipose-init-status`
  (e.g. `calibration/ ✓ · pose-2d: cam0 ✓, cam1 ✓`, warnings appended).

## Backend

New route in `dlc-3D/src/dlc_3d_bp/routes.py`, served under `/dlc-3d/*`.
Reuse existing helpers: `_resolve_video_path`, `_find_sibling_on_filesystem`, the
`/user-data` sandbox guard, and cam-naming regex.

`POST /dlc-3d/anipose/init` — steps, all confined to the selected video's current folder:

1. Resolve `cam0` video path; resolve sibling `cam1` via `_find_sibling_on_filesystem`.
   No sibling → `400 {"error": "no paired camera found"}`.
2. `current_folder = cam0.parent`. Create `current_folder/calibration/` and
   `current_folder/pose-2d/` (idempotent, `mkdir(parents=True, exist_ok=True)`).
3. **Copy (not move)** into `calibration/`, overwriting existing:
   - `current_folder/calibration.toml` → `calibration/calibration.toml`
   - `current_folder/detection.pickle` (fallback source `detections.pickle`)
     → `calibration/detections.pickle`  *(normalized to the plural anipose name)*
   - Either source missing → `400` with a clear message (user guarantees these exist).
4. For **each cam** (cam0, cam1): locate the canonical analyzed files next to that cam's
   video — `<videostem>_analyzed.h5` and `<videostem>_analyzed.csv` — and **copy as-is**
   (unchanged filename) into `pose-2d/`, overwriting existing. Missing analyzed files for a
   cam → recorded as a per-cam warning, NOT a hard failure.
5. Return JSON:
   `{ "calibration": {"calibration.toml": "...", "detections.pickle": "..."},
      "pose_2d": {"cam0": [...copied names...], "cam1": [...]},
      "warnings": [...] }`

Resulting layout:

```
<current folder>/
  calibration/  calibration.toml   detections.pickle
  pose-2d/      <cam0stem>_analyzed.h5  .csv   <cam1stem>_analyzed.h5  .csv
```

### Behavior defaults (approved)

- **Overwrite/refresh** on every run (idempotent — re-running picks up newer analysis).
- Missing `_analyzed` files → **warn, not fail**.
- **Hard-fail** only on: missing sibling, or missing calibration.toml / detection.pickle.

## Tests

Module `dlc-3D/tests/` — follow existing conventions (pytest source-guards + route tests).

1. **Markup guard** (new `test_inline_3d_triangulate_markup.py` style):
   - `#ia3d-triangulate-toggle` present and unchecked by default.
   - Triangulate panel appears **before** `#ia3d-curation-panel` in the template.
   - `#ia3d-triangulate-controls` has `hidden` class by default.
   - `#ia3d-anipose-init-btn` present.
2. **Route test** (`test_anipose_init_route.py` style): build a temp folder with two cam
   videos + `calibration.toml` + `detection.pickle` + `<stem>_analyzed.h5/.csv` for each
   cam. Assert:
   - `calibration/` and `pose-2d/` created.
   - `calibration/calibration.toml` and `calibration/detections.pickle` exist (pickle
     renamed from `detection.pickle`).
   - both cams' `_analyzed.h5/.csv` copied into `pose-2d/` with unchanged names.
   - missing sibling → 400; missing calibration input → 400.
   - missing `_analyzed` for one cam → 200 with a warning, other cam still copied.

## Notes

- HTML template edits require `docker restart deeplabcut-webapp-docker-dlc-3d-1` to go live
  (single-file bind mount); JS/CSS under `src/static/` are hot.
- Canonical analyzed-file naming comes from the main repo `src/dlc/canonical.py`
  (`<videostem>_analyzed.h5` / `.csv`) — replicated here as a simple `.with_name(stem + "_analyzed.ext")`.

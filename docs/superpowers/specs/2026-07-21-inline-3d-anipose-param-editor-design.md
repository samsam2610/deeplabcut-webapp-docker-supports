# Inline 3D — Anipose parameter editor + real 2D-filter step

**Date:** 2026-07-21
**Repos:** main (`deeplabcut-webapp-docker`, config read/write + 2D-filter step) + support (`dlc-3D`, editor UI)
**Depends on:** the triangulation + 3D viewer feature line (config.toml at `parent(session_folder)`).

## Goal

Expose all numeric/toggle parameters of `[triangulation]`, `[filter]` (2D), and `[filter3d]` as
editable UI fields, persist edits to `config.toml`, and ensure they're actually applied in
filter-2d, triangulation, and filter-3d.

## Current state (verified)

- `triangulate()` already reads every `[triangulation]` param from config.toml → applies on next run.
- `[filter3d]` (medfilt/offset) is applied by `canonical_3d.medfilt_range_and_splice`.
- **`[filter]` (2D) is NOT applied** — `run_triangulate_range` triangulates raw pose-2d; no 2D-filter
  step. anipose `anipose_src.filter_2d_funcs` exists (`filter_pose_medfilt`, `filter_pose_viterbi`,
  `process_session_filter_2d`, `write_pose_2d`).
- Flask has the `toml` lib (read); no tomlkit/tomli_w → **write via targeted line edits**.

## Decisions (locked)

- **Config editor → config.toml** (persist, targeted writes preserving scheme/constraints/comments).
- Add a **real 2D-filter step** gated on `config['filter']['enabled']` (default false → off by default).

## Fields (numeric + toggles only; skip list params constraints/scheme/axes)

- **[triangulation]**: `cam_regex` (text), `ransac`·`optim`·`optim_chunking` (bool), `scale_smooth`,
  `scale_length`, `scale_length_weak`, `reproj_error_threshold`, `score_threshold`,
  `n_deriv_smooth`, `optim_chunking_size`.
- **[filter]**: `enabled`·`spline`·`multiprocessing` (bool), `type` (select: medfilt|viterbi),
  `medfilt`, `offset_threshold`, `score_threshold`, `n_back`.
- **[filter3d]**: `enabled` (bool), `medfilt`, `offset_threshold`.

## Backend (main repo)

### `src/dlc/anipose_config.py` (new)
- `read_params(config_path) -> {"triangulation":{...}, "filter":{...}, "filter3d":{...}}` — parse
  config.toml (via `toml`), return ONLY the fields above (missing → omit). Numbers as int/float,
  bools as bool, `cam_regex`/`type` as str.
- `write_params(config_path, params) -> None` — for each `(section, key, value)` present in `params`,
  **targeted replace** the `key = <value>` line within the correct `[section]` block, preserving
  every other line/comment/formatting byte-for-byte. Add the key under the section header if the
  section exists but the key is missing; error if a target section is absent. TOML-encode values
  (bools → `true`/`false`, strings → quoted, numbers bare). Atomic write.
- Validation helper `validate_params(params)` → raise/return errors: `medfilt` odd int in [1,199];
  `*_threshold`/`scale_*`/`n_*` numeric ≥ 0; bools actually bool; `type` in {medfilt,viterbi}.

### Routes in `src/dlc/inline_analysis.py`
Mirror the `triangulate_coverage` style (`_sec_check`, cam0 validation). config path =
`Path(cam0_video).parent.parent / "config.toml"`.
- `GET /dlc/project/triangulate/config?cam0_video=…` → `read_params(config_path)`; missing config
  → 400 `{"error":"config.toml not found …"}`; missing cam0 → 400; oob → 403.
- `POST /dlc/project/triangulate/config` `{cam0_video, params:{triangulation,filter,filter3d}}` →
  `validate_params` (400 on bad) → `write_params` → return `{ok, params: read_params(...)}` (echo
  the persisted result). Same 400/403 guards.

### 2D-filter step — `src/dlc/triangulate_range.py`
In `run_triangulate_range`, after slicing pose-2d and BEFORE triangulation:
```
if config.get('filter', {}).get('enabled'):
    _filter_pose2d(config, sliced_h5, filtered_h5)   # per cam; triangulate from filtered
```
- `_filter_pose2d(config, in_h5, out_h5)` — a patchable worker-only seam: load points (anipose
  `load_pose_2d`), run `filter_pose_medfilt` or `filter_pose_viterbi` per `config['filter']['type']`,
  `write_pose_2d` to `out_h5`. On failure → fall back to the unfiltered h5 (log) so triangulation
  still runs. Emit a progress line.
- Thread the chosen h5 (filtered when enabled, else the raw slice) into `fname_dict`.

## Support module — UI

### Template `card_inline_analysis_3d.html`
New collapsible **"Anipose Parameters"** panel AFTER `#ia3d-triangulate-panel`
(`#ia3d-params-toggle` reveals `#ia3d-params-controls`), three labelled sub-groups with inputs
per the field list (ids like `#ia3d-param-tri-optim`, `#ia3d-param-filter-medfilt`,
`#ia3d-param-f3d-medfilt`, …), a `#ia3d-params-save` button, `#ia3d-params-status` span, and a
one-line note "triangulation/2D-filter changes apply on next Triangulate; filter3d on next
re-filter."

### Wiring `inline_analysis_3d.js`
- On panel open (toggle) OR after a cam0 selection: `GET …/triangulate/config?cam0_video=…` and
  populate the fields (checkboxes for bools, number inputs, selects). Guard when config absent
  (disable Save, show the error in status).
- Save → gather field values into `{triangulation,filter,filter3d}` (numbers as numbers, bools as
  bools), `POST …/triangulate/config`; on success show "saved", on 400 show the validation error.
- Isolated, mirrors the existing `_wire*Chrome` idempotent pattern.

## Tests

**Main** (`tests/`):
- `anipose_config`: `read_params` returns the fields with correct types; `write_params` targeted-edit
  round-trips values AND leaves other lines/comments byte-identical (write a config with a comment +
  `[labeling] scheme` list, change one number, assert the rest unchanged); adds a missing key under an
  existing section; `validate_params` rejects even medfilt / negative thresholds / bad type.
- config routes: GET returns params; POST persists + echoes; absent config → 400; missing cam0 → 400;
  oob → 403; invalid params → 400.
- 2D-filter step: `run_triangulate_range` calls `_filter_pose2d` when `filter.enabled` (mock the seam +
  `_triangulate`), and does NOT when disabled; triangulation still runs if `_filter_pose2d` raises.

**Support** (`dlc-3D/tests/`):
- Markup guards: the param panel + a representative field id per section + Save present; controls
  hidden by default; panel after the Triangulate panel.
- Wiring guards: `inline_analysis_3d.js` GETs `/dlc/project/triangulate/config` to prefill and POSTs it
  on Save.

## Deploy

Restart flask (routes + 2D-filter step reachable) + worker (2D-filter step) + dlc-3d (template). JS hot.

## Out of scope

Editing list params (constraints/scheme/axes/reference_point), a full free-form TOML editor, applying
params retroactively to already-triangulated ranges (user re-runs Triangulate / re-filter).

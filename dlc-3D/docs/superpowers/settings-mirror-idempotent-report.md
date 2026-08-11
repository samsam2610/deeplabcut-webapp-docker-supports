# Settings whitelist, snapshot-picker mirror, idempotent reprojection

## Status

All three tasks complete, committed separately, on `fix/marker-save-race` in
both repos (no new branches/worktrees created, per instructions).

## Commits

**Main webapp** (`deeplabcut-webapp-docker`):
- `08c41a8` — fix(inline): whitelist the reprojection card's 8 ui-setting keys

**Support module** (`deeplabcut-webapp-docker-supports`, `dlc-3D/`):
- `8f0b9c6` — test(inline-3d): guard the reprojection card's ui-setting keys against the whitelist
- `4e6b87a` — feat(inline-3d): mirror the pinnable snapshot picker onto the original card
- `1882780` — fix(inline-3d): make reprojection idempotent — no more _reprojected_reprojected

## Task 1 — ui-setting whitelist

Added the 8 missing keys to `_UI_SETTING_KEYS` in
`deeplabcut-webapp-docker/src/dlc/inline_analysis.py`: `reproj_params`,
`clip_window_reproj`, `finalize_window_reproj`, `note_tags_reproj`,
`postfix_tags_reproj`, `status_tags_reproj`, `pose3d_bg_color_reproj`,
`pose3d_view_prefs_reproj`.

Guard test: `dlc-3D/tests/test_reproj_ui_setting_whitelist.py`. It parses
`inline_analysis_3d_reprojection.js` for every ui-setting key literal actually
sent (`key: "literal"`, `key: CONST_NAME` resolved via `const CONST_NAME =
"...";`, `?key=literal`, `?key=${CONST_NAME}`, `settingKey: "literal"`),
scoped to the `JSON.stringify({ key: ... })` POST-body shape and `?key=`
GET shape so it can't false-positive on unrelated object literals that also
have a `key` property (the anipose-params field descriptors do — first
extraction attempt caught 18 false positives from that; fixed by scoping to
the JSON.stringify(...) call shape). Asserts the extracted set is non-empty,
then asserts it's a subset of `_UI_SETTING_KEYS`. `skipif`s when the sibling
main-webapp checkout is absent.

**Mutation proof** (removed `"reproj_params"` from the whitelist, ran the
test, restored, ran again):

```
$ python3 -m pytest tests/test_reproj_ui_setting_whitelist.py -v   # after removing "reproj_params"
FAILED tests/test_reproj_ui_setting_whitelist.py::test_every_reprojection_ui_setting_key_is_whitelisted
AssertionError: reprojection card sends ui-setting key(s) not in _UI_SETTING_KEYS: ['reproj_params'] — ...

$ python3 -m pytest tests/test_reproj_ui_setting_whitelist.py -v   # after restoring
tests/test_reproj_ui_setting_whitelist.py::test_every_reprojection_ui_setting_key_is_whitelisted PASSED
1 passed in 0.01s
```

**Original card's settings keys** — ran the same extraction logic against
`inline_analysis_3d.js` (ad hoc, not committed as a test since the task asked
only to report):

```
['clip_window', 'finalize_window', 'note_tags', 'pinned_snapshot',
 'pose3d_bg_color', 'pose3d_view_prefs', 'postfix_tags', 'status_tags']
```

All 8 are already present in `_UI_SETTING_KEYS`. **No fix needed for the
original card** — its settings have always persisted correctly.

## Task 2 — mirror the pinnable snapshot picker

Ported the pin-list markup (`ia3d-snapshot-pin-list`, same bounded/scrollable
styling) into `card_inline_analysis_3d.html` directly under the existing
`ia3d-snapshot` dropdown (dropdown itself untouched). Ported the wiring into
`inline_analysis_3d.js`: `_ia3dEl.snapPinList`, `IA3D_PINNED_SNAPSHOT_KEY =
"pinned_snapshot"` (same shared key as the reprojection card, by design —
pinning in one card is honoured by the other), `_ia3dRenderPinList`,
`_ia3dOnPinToggle`, `_ia3dSavePinnedSnapshot`, `_ia3dApplyPinnedSnapshot`, and
wired `_loadSnapshots` to build the `items` list and call
`_ia3dRenderPinList`/`_ia3dApplyPinnedSnapshot` on every (re)build — same
behaviour as the reprojection source, `ia3dr-` → `ia3d-` id/name prefix
throughout. Missing-pinned-snapshot case: dropdown left untouched, nothing
checked, a note surfaced via `lastRun` — no silent fallback.

Test home: `test_inline_analysis_3d_ui_isolation.py` (the file that already
guards this card's general markup+wiring — `test_inline_3d_params_markup.py`
/ `_wiring.py` turned out to cover the *unrelated* "Anipose Parameters"
config.toml editor panel, not the Analysis-Parameters snapshot picker, so
those were not the right home). Added 9 tests mirroring
`test_reproj_panel_markup.py` + `test_reproj_panel_wiring.py`'s "Pinnable
snapshot picker" section 1:1 with names/ids swapped.

**Mutation proof 1** (dropped single-selection enforcement — removed
`boxes.forEach((b) => { if (b !== changedCb) b.checked = false; });`):

```
FAILED test_pin_toggle_enforces_single_selection
AssertionError: no code path unchecks the other rows — single-selection is not enforced
```
Restored → passed again.

**Mutation proof 2** (dropped dropdown-sync on check — removed
`const snapSel = ...; if (snapSel) snapSel.value = changedCb.value;`):

```
FAILED test_checking_a_row_writes_the_dropdown_value
AssertionError: checking a row does not sync the dropdown's value
```
Restored → passed again; full file re-verified at 80/80 passing after restore.

## Task 3 — idempotent reprojection

`reprojection.py`: added a pure helper `_source_layer_for(h5_path) -> Path |
None` (path arithmetic only, no filesystem access — returns None when the
stem doesn't end in `_reprojected`, else the stripped source path) and
`_normalize_reproject_input(h5_path) -> Path` (calls the pure helper, then
does the existence check: returns the path unchanged if not a reprojection
output; returns the resolved source if it exists; raises `FileNotFoundError`
naming both paths if the source is missing — no chaining fallback).
`run_reprojection` calls this on both `ref_h5`/`tgt_h5` before reading
anything, so `_out_path` naturally regenerates the *same* `_reprojected` name
from the source and replaces the existing output — input (source `.h5`) and
output (`_reprojected.h5`) are always distinct files, so a crash mid-write
can't destroy the source. `summary["config"]` now records both
`ref_h5`/`tgt_h5` (path actually read) and `ref_h5_requested`/`tgt_h5_requested`
(what the caller asked for).

`routes.py`: `/reproject/run` now catches `FileNotFoundError` and maps it to
a 400 (mirroring the existing `ValueError` handling), rather than letting it
surface as an uncaught 500.

`inline_analysis_3d_reprojection.js`: `_reprojRun` now compares
`data.config.ref_h5_requested`/`tgt_h5_requested` against
`data.config.ref_h5`/`tgt_h5`; if they differ, appends a status-line note that
the run re-read the source and replaced the output rather than reprojecting
the selected (already-reprojected) layer.

New tests in `tests/test_reprojection_io.py`:
- `_source_layer_for`: plain path → None; already-reprojected → stripped
  source path; pure (no existence check — verified against a path that
  doesn't exist on disk); only strips a *trailing* `_reprojected`, not one
  merely appearing mid-stem.
- `_normalize_reproject_input`: plain path passes through; existing source
  redirects correctly; missing source raises `FileNotFoundError` naming both
  the reprojected path and the missing source path.
- `test_reprojecting_an_already_reprojected_layer_yields_exactly_one_output`:
  runs reprojection once, then feeds the `_reprojected.h5` output back in as
  input — asserts exactly one `*_reprojected.h5` per camera afterward (no
  `_reprojected_reprojected`), that `config` records the resolved source vs.
  requested reprojected path, and that the rescued-frame likelihoods on the
  second pass match the first pass exactly (proves corrections are NOT
  compounded — the second pass re-derives from the untouched source, not from
  the already-corrected output).
- `test_reprojecting_an_already_reprojected_layer_with_missing_source_raises`:
  deletes the source after a first run, re-runs on the `_reprojected.h5`
  output, asserts `FileNotFoundError`.

New test in `tests/test_reprojection_routes.py`:
`test_run_maps_missing_source_layer_to_400_not_500`.

New test in `tests/test_reproj_panel_wiring.py`:
`test_reprojecting_a_reprojected_layer_surfaces_a_note`.

No pre-existing `*_reprojected_reprojected.h5` files were touched or migrated.

**Regression check** — the full pre-existing reprojection test suite
(`test_reprojection_io.py` + `test_reprojection_routes.py`, including exact
numeric assertions on verdict counts, per-camera rescue floors, and byte-level
`assert_frame_equal` checks on unaffected frames) passes unchanged: 43/43
before adding new tests, all still green after.

## Test summary (dlc-3D full suite)

```
python3 -m pytest tests/ -q --ignore=tests/e2e
8 failed, 845 passed, 3 skipped in ~10s
```

8 failures are the pre-existing baseline, unchanged (`test_finalize3d_confirms_before_overwrite`,
2× `test_lp_csv_to_h5.py`, 4× `test_lp_predict_pairing.py` — all confirmed via
`git stash` to fail identically before this session's changes). 845 = 824
baseline + 21 new tests added across the three tasks (1 + 9 + 11). No
pre-existing assertion was deleted or weakened anywhere.

Main-webapp side: did **not** run the main-webapp pytest suite (disk-fill
hazard; the one file touched, `test_ui_setting_tag_keys.py`, requires the
forbidden `flask_test_client`/`dlc_sandbox_project` fixtures). Verified the
whitelist change instead via a static AST parse of `_UI_SETTING_KEYS`
(16 keys: the original 8 + the 8 new ones, no duplicates, nothing dropped).

## Concerns / notes

- The `/reproject/thresholds` (estimate) and `/reproject/peaks-status`
  endpoints read `ref_h5`/`tgt_h5` directly via `rp.read_pose_h5` without
  going through `run_reprojection`/normalization. If a user previews
  thresholds against an already-reprojected layer, that preview still reads
  the reprojected (corrected) file as-is — out of scope per the task (which
  scoped the fix to `run_reprojection`), flagging in case that's surprising
  later.
- `_UI_SETTING_KEYS` values are stored as `str(value)` regardless of key —
  pre-existing behavior, unrelated to this change, not touched.

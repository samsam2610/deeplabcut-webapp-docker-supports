# Snapshot iteration naming + pinnable snapshot picker — report

## Status
Both features implemented and committed, each in a separate commit per repo. All targeted tests pass; no regressions against either repo's baseline.

## Commits

- Main webapp (`deeplabcut-webapp-docker`), branch `fix/marker-save-race`:
  - `01bb7d7` — fix(inline): fold training iteration into analysis scorer name (Feature 1)
  - `e3f284d` — feat(inline-3d): whitelist pinned_snapshot as a per-project ui-setting key (Feature 2, backend half)
- Support module (`deeplabcut-webapp-docker-supports`), branch `fix/marker-save-race`:
  - `676dc3c` — feat(inline-3d): pinnable snapshot picker on the reprojection card (Feature 2, dlc-3D half)

## Feature 1 — training iteration in output filenames

Added a pure module-level helper `_scorer_with_iteration(scorer, snapshot_path)` in `src/dlc/tasks.py`, called once at the single site `scorer = loader.scorer(snapshot_path)` inside `_dlc_inline_session_inner` (was line 3133). It inserts `_iter<N>_` immediately before the `snapshot` token, is idempotent (no-ops if `_iter\d+_` already present), and leaves the scorer untouched if `iteration-(\d+)` isn't found in the snapshot path or if the scorer has no `snapshot` token to anchor on.

Verified by reading (not separately edited) that everything downstream flows from this one variable:
- `_resolve_h5_path(video, scorer)` (line ~2858) builds `stem + scorer + ".h5"` — picks up the new name automatically.
- `_run_range`'s DataFrame is built via `_make_df(..., dlc_scorer=scorer, ...)` — the MultiIndex column level comes from the same variable.
- `_publish_result(..., scorer=scorer)` at both call sites in the task loop sends the same value to the browser.
- The peaks sidecar rule (`dlc/peaks_emit.py::_peaks_sidecar_path`) derives from `h5_path.stem + "_peaks.npz"`, so it inherits the new name via the h5 path.
- The snapshot-index recovery regex at `tasks.py:1464` (`re.search(r'snapshot[_-](.+)$', ...)`) still captures the same tail (e.g. `"200"`) because the iteration is inserted *before* `snapshot`, not after — confirmed by a dedicated regression test.

Existing analysis files are untouched; no migration/rename was performed.

### Diff-scope check
```
git diff -U0 01bb7d7^ 01bb7d7 -- src/dlc/tasks.py | grep '^-' | grep -v '^---'
```
Output:
```
-        scorer       = loader.scorer(snapshot_path)
```
Only the single scorer line is removed/replaced — the helper function is purely additive.

### Tests (main webapp)
New file `tests/test_scorer_iteration.py` (5 tests, stubs `deeplabcut` via `sys.modules` patching like `test_inline_analysis_worker.py` — no torch/deeplabcut import, no heavy fixtures):
- inserts `_iter23_` before `_snapshot_` for a realistic path
- idempotent when already present
- unchanged when no `iteration-N` in the snapshot path
- unchanged when the scorer has no `snapshot` token
- regression guard: `re.search(r'snapshot[_-](.+)$', ..., re.I).group(1)` is identical before and after transformation

```
tests/test_scorer_iteration.py .....                                     [100%]
5 passed in 0.24s
```

Also ran (targeted, no heavy fixtures):
- `tests/test_inline_analysis_worker.py` — 27 passed. One test, `TestRangeVideoIterator::test_non_contiguous_skip_list_preserves_order`, fails only when the file is run as a whole batch; confirmed via `git stash` that this failure is **pre-existing test-order pollution unrelated to this change** (identical failure on unmodified `tasks.py`; passes standalone with or without the change).
- `tests/test_inline_analysis_ui_isolation.py` + `tests/test_inline_analysis_finalize.py` — 28 passed.

No `dlc_sandbox_project` / `flask_test_client` / `ia_client` fixtures were used; no `pytest tests/` was run in the main webapp repo (disk-fill hazard).

## Feature 2 — pinnable snapshot picker

### Backend (main webapp)
Added `"pinned_snapshot"` to `_UI_SETTING_KEYS` in `src/dlc/inline_analysis.py:421`. No other backend change needed — `/dlc/project/ui-setting` GET/POST already generically stores/reads any whitelisted key via `_project_settings`.

### Frontend (dlc-3D)
- `src/static/card_inline_analysis_3d_reprojection.html`: added `<div id="ia3dr-snapshot-pin-list" style="max-height:7.5rem;overflow-y:auto;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);padding:.3rem .5rem;margin-bottom:.4rem;font-size:.77rem"></div>` directly after the existing `<select id="ia3dr-snapshot">` row. The dropdown itself (`<select id="ia3dr-snapshot" style="flex:1;min-width:0"></select>`) is byte-for-byte unchanged.
- `src/static/inline_analysis_3d_reprojection.js`:
  - `_loadSnapshots` now also builds a parallel `items` array (value/label pairs matching the dropdown's options, including "Latest"), and at the end calls `_ia3drRenderPinList(items)` then `await _ia3drApplyPinnedSnapshot(items)`. Because card-open, the ↺ refresh button, and a shuffle change all already call `_loadSnapshots`, the pin is re-applied on every one of those triggers with no extra wiring.
  - `_ia3drRenderPinList(items)` — builds one checkbox row per snapshot (`name="ia3dr-snap-pin"`), each wired to `_ia3drOnPinToggle`.
  - `_ia3drOnPinToggle(changedCb)` — on check: unchecks every other box (radio behaviour), sets `snapSel.value = changedCb.value`, persists the pin. On uncheck: persists an empty pin and leaves the dropdown alone.
  - `_ia3drSavePinnedSnapshot(value)` — `POST /dlc/project/ui-setting` with `key: "pinned_snapshot"`.
  - `_ia3drApplyPinnedSnapshot(items)` — `GET`s the persisted pin; if it matches a current snapshot, checks that row and sets the dropdown; if it does not match anything currently listed, leaves the dropdown and checkboxes untouched and writes a note into the existing `#ia3dr-last-run-status` area ("Pinned snapshot is no longer available — showing the default instead.") — deliberately no silent fallback.

`node --check --input-type=module < dlc-3D/src/static/inline_analysis_3d_reprojection.js` → passes. Every new identifier (`_ia3drRenderPinList`, `_ia3drOnPinToggle`, `_ia3drSavePinnedSnapshot`, `_ia3drApplyPinnedSnapshot`, `_ia3drEl.snapPinList`, `IA3DR_PINNED_SNAPSHOT_KEY`) was grepped and confirmed defined and consistently referenced.

### Tests
`dlc-3D/tests/test_reproj_panel_markup.py` (fixture `card`), added:
- `test_snapshot_dropdown_still_present_and_unchanged`
- `test_snapshot_pin_list_exists_scrollable_and_bounded`
- `test_snapshot_pin_list_sits_after_the_dropdown`

`dlc-3D/tests/test_reproj_panel_wiring.py` (fixture `js`), added:
- `test_pin_toggle_enforces_single_selection`
- `test_checking_a_row_writes_the_dropdown_value`
- `test_pin_round_trips_through_the_ui_setting_key`
- `test_unchecking_the_pinned_row_clears_the_pin_without_touching_the_dropdown`
- `test_missing_pinned_snapshot_does_not_silently_change_the_dropdown`
- `test_snapshot_refresh_applies_the_pin`

Main webapp, `tests/test_ui_setting_tag_keys.py`, added:
- `test_pinned_snapshot_key_allowed` (`"pinned_snapshot" in _UI_SETTING_KEYS`; no fixtures) — ran, passes
- `test_pinned_snapshot_round_trip` (uses `tag_client`, which pulls in `dlc_sandbox_project`/`flask_test_client` — mirrors the existing `pose3d_bg_color`/`pose3d_view_prefs` round-trip tests in the same file exactly; **not executed** in this session per the disk-fill hazard instruction, since it needs the heavy fixture)

No pre-existing assertion in either markup/wiring test file was deleted or weakened; the only file where I touched existing tests was `tests/test_ui_setting_tag_keys.py`, and only by appending two new tests after the existing `pose3d_view_prefs` tests — nothing existing was modified.

### Test run
```
dlc-3D: tests/test_reproj_panel_markup.py + test_reproj_panel_wiring.py
........................................................................ [ 64%]
........................................                                 [100%]
112 passed in 0.15s
```
```
dlc-3D full suite: python3 -m pytest tests/ -q --ignore=tests/e2e
8 failed, 824 passed, 3 skipped
```
The 8 failures match the stated baseline exactly (`test_finalize3d_confirms_before_overwrite`, 2× `test_lp_csv_to_h5.py`, 5× `test_lp_predict_pairing.py` — all pre-existing, unrelated to this change: ffprobe/`_R` mock plumbing and an unrelated confirm-dialog test).

### Mutation testing (proving the wiring tests bite)
Two mutations applied to `inline_analysis_3d_reprojection.js`, one at a time, then reverted:

**(a) Dropped single-selection enforcement** (removed `boxes.forEach((b) => { if (b !== changedCb) b.checked = false; });`):
```
FAILED tests/test_reproj_panel_wiring.py::test_pin_toggle_enforces_single_selection
AssertionError: no code path unchecks the other rows — single-selection is not enforced
1 failed, 68 deselected in 0.06s
```

**(b) Dropped dropdown-sync on check** (removed `const snapSel = _ia3drEl.snapSel(); if (snapSel) snapSel.value = changedCb.value;`):
```
FAILED tests/test_reproj_panel_wiring.py::test_checking_a_row_writes_the_dropdown_value
AssertionError: checking a row does not sync the dropdown's value
1 failed, 68 deselected in 0.06s
```

Both mutations were reverted afterward; `node --check` and the full markup+wiring suite (112 passed) were re-confirmed green post-revert.

## Concerns

1. **`tests/test_inline_analysis_worker.py::TestRangeVideoIterator::test_non_contiguous_skip_list_preserves_order`** fails when the file runs as a full batch (test-order pollution — some earlier test in the file leaves shared state that empties the `seeks` list). Confirmed pre-existing via `git stash` (identical failure on unmodified code), so out of scope for this task, but worth a separate fix.
2. **Pre-existing, unrelated gap noticed while reading `inline_analysis.py`**: `_UI_SETTING_KEYS` does not include `pose3d_view_prefs_reproj`, `pose3d_bg_color_reproj`, or `reproj_params` — all three keys are used by `inline_analysis_3d_reprojection.js` (view-prefs/background-colour/panel-params persistence) but aren't in the whitelist, so those specific POSTs would 400. Did not touch this — out of scope for the task as given, flagging since it looks like a live bug adjacent to where I was working.
3. Feature 2's "missing pinned snapshot" note is written to the shared `#ia3dr-last-run-status` area, which is also used for run-status/error messages elsewhere on the card. This matches the spec's "existing status area" instruction, but a message shown at card-open could be overwritten by an unrelated status update shortly after; no dedicated area exists for this specific case.

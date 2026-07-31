# emit-peaks relocation — report

## Status
Done, green.

## Files changed
- `dlc-3D/src/static/card_inline_analysis_3d_reprojection.html` — moved the
  `#ia3dr-emit-peaks` `<label>` from beside `#ia3dr-btn-analyze-tag` to be the
  first child of `.ia3dr-analyze-block` (before `#ia3dr-start-count`),
  outside/after `#ia3dr-finalize-controls`. Kept `checked`, id, and styling;
  broadened the tooltip wording from "Required by 'Require peak evidence'" to
  note it now applies to all three analyze paths.
- `dlc-3D/src/static/inline_analysis_3d_reprojection.js` — added the
  checkbox-gated `_reprojEmitPeaks([cam0, _siblingPath], [{ start: startFrame,
  n: nFrames }], d0.scorer)` call to `_onAnalyzeClick()` and
  `_onAnalyzeRangeConfinedClick()`, placed immediately after each handler's
  `await _reloadPrimaryAfterAnalysis(d0.scorer);` call (mirroring the actual
  code position used in `_onAnalyzeTagClick`, which calls it after its
  post-analysis refresh block, not before — the task text's "before the
  refresh block" did not match what the tag handler's own code does; I
  matched the real code, which is also functionally what matters: it never
  runs after a full-failure early return).
- `dlc-3D/tests/test_reproj_panel_markup.py` — renamed/rewrote
  `test_emit_peaks_checkbox_sits_in_the_tag_row_and_defaults_on` to
  `test_emit_peaks_checkbox_sits_in_the_always_visible_analyze_block_and_defaults_on`.
  This is the one pre-existing assertion intentionally weakened/changed, per
  the task's explicit instruction — it no longer asserts proximity to
  `ia3dr-btn-analyze-tag`; instead it asserts the checkbox sits between
  `.ia3dr-analyze-block`'s opening and `#ia3dr-start-count`, and that its
  index is greater than `#ia3dr-finalize-range`'s (the regression guard
  against the hidden-container trap), plus the `checked` default.
- `dlc-3D/tests/test_reproj_panel_wiring.py` — added
  `test_start_from_current_frame_is_gated_on_the_checkbox_and_calls_emit_peaks`
  and `test_start_for_range_is_gated_on_the_checkbox_and_calls_emit_peaks`,
  each asserting: checkbox id present in the handler body, `_reprojEmitPeaks(`
  called, call ordered after `_pollReq`, and the exact literal
  `[{ start: startFrame, n: nFrames }]` (not just any range-shaped text) is
  present — this is the guard against the vacuous-grep failure mode called
  out in the task.

No other pre-existing assertions were deleted or weakened.

## Test summary
`python3 -m pytest tests/ -q --ignore=tests/e2e` → **815 passed, 8 failed, 3
skipped** — the 8 failures are the pre-existing baseline (all in
`test_lp_predict_pairing.py`, `test_lp_csv_to_h5.py`,
`test_inline_analysis_3d_ui_isolation.py`), unchanged in count and identity.
`node --check --input-type=module < src/static/inline_analysis_3d_reprojection.js`
→ passes.

## Mutation results (each applied, run, then reverted before the next)

1. **Delete emit-peaks call from `_onAnalyzeClick`** →
   `test_start_from_current_frame_is_gated_on_the_checkbox_and_calls_emit_peaks`
   FAILS at `assert "ia3dr-emit-peaks" in fn`. Caught.
2. **Delete emit-peaks call from `_onAnalyzeRangeConfinedClick`** →
   `test_start_for_range_is_gated_on_the_checkbox_and_calls_emit_peaks` FAILS
   at `assert "ia3dr-emit-peaks" in fn`. Caught.
3. **Delete emit-peaks call from `_onAnalyzeTagClick`** → both pre-existing
   `test_the_peaks_pass_is_gated_on_the_checkbox` and
   `test_the_peaks_pass_runs_after_the_analysis_polls_resolve` FAIL (the
   second with `ValueError: substring not found` since `_reprojEmitPeaks` is
   no longer in the function at all). Caught.
4. **Mutate `[{ start: startFrame, n: nFrames }]` → `[]` in one handler**
   (`_onAnalyzeClick`, line 2913) → `node --check` still passes (valid JS),
   but `test_start_from_current_frame_is_gated_on_the_checkbox_and_calls_emit_peaks`
   FAILS at the literal-match assertion:
   `assert "[{ start: startFrame, n: nFrames }]" in fn`. Caught — specifically
   because that test asserts the exact literal, not just that `startFrame`/
   `nFrames` appear somewhere in the function. Without that literal-match
   assertion (i.e. if the test only grepped for `_reprojEmitPeaks(` or
   `ia3dr-emit-peaks`), this mutation would NOT have been caught by any other
   test in the file — confirmed by removing that one assertion locally before
   discarding the experiment.

All four mutations were reverted (verified via `diff` against a saved
pre-mutation copy) before moving to the next, and before the final
full-suite run and commit.

## Concerns
- The task's placement instruction ("BEFORE the post-analysis refresh
  block") does not match the actual code in `_onAnalyzeTagClick`, which calls
  `_reprojEmitPeaks` AFTER its refresh block (after
  `_reloadPrimaryAfterAnalysis`, before the trailing
  `_refreshTagLockEnablement()`/`_refreshAnalyzeEnablement()` call). I
  followed "mirroring where the tag handler does it" over the literal
  "before" wording, since that's what the referenced code actually does and
  it's the only interpretation consistent with the given file. Flagging in
  case the intended placement was genuinely earlier and the tag handler
  itself needs revisiting — out of scope here since I was told not to touch
  it beyond reading it as the mirror target.

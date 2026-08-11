# Stranded-queue visibility fix — report

## Status
DONE. Committed to `fix/marker-save-race`.

## Commit
`750b18b` — fix(jobs): surface stranded inline queues with no session on /dlc/jobs/all

Files changed:
- `src/dlc/monitoring.py` — `_inline_session_rows` now unions `inline:session:*` and `inline:queue:*`, new `_parse_inline_suffix` helper
- `src/static/js/jobs.js` — stranded-state glyph/color, `_isStranded` helper, distinct confirm copy and detail-pane warning
- `src/static/css/jobs.css` — `.jobs-row-stranded` visual treatment
- `tests/test_dlc_jobs_unified.py` — 5 new tests (purely additive)

## Fix summary
`_inline_session_rows` previously scanned only `inline:session:*`, so a queue whose session hash was already gone produced no row — the exact stranded state the endpoint exists to expose. It now scans the union of `inline:session:*` and `inline:queue:*`, dedupes on the `(user_id, snap_key)` suffix (parsed by stripping the known `inline:<prefix>:` prefix, not a naive `split(":")` count — malformed keys are skipped, never raised), and produces one of three row states per suffix:

1. session + queue → normal row, `state` = session status.
2. session, no/empty queue → normal idle row.
3. queue, no session → `state: "stranded"`, `detail.stranded: true`, `detail.project`/`detail.snapshot` left empty (no metadata to show), still `cancellable: true`.

Cancel path (`/dlc/jobs/cancel`, type `inline` → `_inline_analysis._explicit_session_stop`) was already session-hash-agnostic (only touches the control key and queue key) — verified working with no session hash present, no changes needed there.

`jobs.js`: added `_isStranded(job)`, a `⛔` glyph + red color for `state: "stranded"`, a distinct confirm string ("Discard stranded inline-analysis queue? … No worker is draining this queue — N pending ranges will be discarded."), a `.jobs-row-stranded` CSS treatment (red-tinted row, red left border) so it doesn't read as a running job in the rail, and a prominent warning + "Discard" button label in the detail pane.

## Test summary
`tests/test_dlc_jobs_unified.py`: **23 passed** (18 pre-existing + 5 new), 0 failed.

New tests:
- `test_queue_with_no_session_produces_a_stranded_row`
- `test_session_with_no_queue_is_not_stranded`
- `test_session_plus_nonempty_queue_is_one_row_not_two`
- `test_malformed_inline_queue_key_is_skipped_without_raising`
- `test_cancel_stranded_row_with_no_session_hash_still_succeeds`

No pre-existing assertion was touched, removed, or weakened — `git diff tests/test_dlc_jobs_unified.py | grep '^-' | grep -v '^---'` returns nothing (purely additive diff).

Also re-ran (unmodified, sanity-only) `tests/test_inline_analysis_peaks_route.py` (25 passed), `tests/test_inline_analysis_session_stop_guard.py` (5 passed), `tests/test_inline_player_close_preserves_queue.py` (2 passed) — none of the disk-fill fixtures (`dlc_sandbox_project`, `flask_test_client`, `ia_client`) were used anywhere.

## Mutation-proof
Reverted `_inline_session_rows` to session-only scanning (in-place edit, no commit), ran the suite:

```
tests/test_dlc_jobs_unified.py ......FFF.........                        [100%]

FAILED tests/test_dlc_jobs_unified.py::TestJobsAll::test_queue_with_no_session_produces_a_stranded_row
FAILED tests/test_dlc_jobs_unified.py::TestJobsAll::test_session_with_no_queue_is_not_stranded
FAILED tests/test_dlc_jobs_unified.py::TestJobsAll::test_session_plus_nonempty_queue_is_one_row_not_two
3 failed, 15 passed in 0.35s
```

The three failures are exactly the new tests asserting stranded-row behavior and the `detail.stranded` field (the two non-stranded-but-new tests fail because the old code never set `detail.stranded` at all — `KeyError: 'stranded'`). `test_malformed_inline_queue_key_is_skipped_without_raising` and the cancel test still passed under the mutation (expected — they don't depend on the union logic). Restored the file from a pre-edit backup; confirmed no `MUTATED FOR MUTATION-PROOF` / `_parse_inline_suffix` markers left dangling, then re-ran the full file: 18/18 passed clean.

## tasks.py grep (constraint check)
```
$ git diff -U0 f7fd5ee -- src/dlc/tasks.py | grep '^-' | grep -v '^---'
(no output)
```
`src/dlc/tasks.py` was not touched, confirmed empty diff since `f7fd5ee`.

## JS syntax / identifier check
```
$ node --check --input-type=module < src/static/js/jobs.js
(no output — syntax OK)
```
New identifiers grepped and confirmed defined: `_isStranded` (defined once, used at 3 call sites), `pendingTxt` (defined once, used in the two places it's referenced), `jobs-row-stranded` (CSS class defined in `jobs.css`, applied in `jobs.js`).

## Concerns / notes
- `/dlc/training/jobs` and `/dlc/training/queue/cancel` were not touched, per constraint.
- The stranded-row `state` literal is `"stranded"` — added to the row-shape docstring's enumerated state list in `monitoring.py` for discoverability.
- Left `detail.project`/`detail.snapshot` as empty strings (not `null`/omitted) for a stranded row to match the existing detail dict shape the frontend already indexes into (`d.project`, `d.snapshot`) — avoids adding a null-check in `jobs.js` for a field that's simply "we don't know."
- Did not add a dedicated frontend test file; `jobs.js`'s existing pure-function test seam (`window.__jobsTestHooks`) already exports `_cancelConfirmText`/`_isCancellable` for `tests/test_jobs_js_cancel_ui.mjs` — did not modify that seam's exported set (no request to do so), so that file's existing tests are unaffected. If frontend coverage for the stranded confirm-copy branch is wanted, `_isStranded` could be added to `window.__jobsTestHooks` in a follow-up.

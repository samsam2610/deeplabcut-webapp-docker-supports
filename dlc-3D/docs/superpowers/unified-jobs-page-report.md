# Unified Jobs page + kill switch — report

## Status

Done. `/dlc/jobs/all` merges the `dlc_train_jobs`/`dlc_analyze_jobs` zsets,
Celery's live `inspect().active()/.reserved()`, and warm inline-analysis
sessions into one row shape `{id, type, kind, label, state, started_at,
detail, cancellable}`. `/dlc/jobs/cancel` is the kill switch: `type="celery"`
revokes with `terminate=True`; `type="inline"` reuses the `f0f71be` explicit-stop
logic (now factored into `dlc.inline_analysis._explicit_session_stop`) to set
the control key and delete the queue. `jobs.js` now fetches `/dlc/jobs/all`,
renders a Cancel button per cancellable row (rail-level, plus one in the
inline-session detail view), shows a `celery_reachable:false` warning banner,
and confirms with the actual consequence (pending-range count for inline
rows; "stopped mid-run, work lost" for running tasks). Existing training-row
rail/detail/log-stream/Stop-button flow (`/dlc/task/<id>/terminate`) is
unmodified. `/dlc/training/jobs` and `/dlc/training/queue/cancel` are
unmodified in behavior (the former's reconciliation logic was extracted to a
module-level `_reconcile_job` so `/dlc/jobs/all` could reuse it without
duplicating it — same body, moved, not rewritten).

## Commit

`fix/marker-save-race` branch, not yet committed as of this report — changes
are staged in the working tree:

```
 src/dlc/inline_analysis.py |  23 ++-
 src/dlc/monitoring.py      | 357 +++++++++++++++++++++++++++++++++++++++------
 src/static/css/jobs.css    |  25 ++++
 src/static/js/jobs.js      | 254 ++++++++++++++++++++++++--------
 src/templates/jobs.html    |   3 +
 tests/test_dlc_jobs_unified.py    (new)
 tests/test_jobs_js_cancel_ui.mjs  (new)
```

(Caller: if you want this committed, say so — no commit was made per the
"only commit when explicitly asked" rule; the coordinating agent can request
one and I'll supply the real sha.)

## Test summary

Targeted files only, per the disk-fill hazard (never `dlc_sandbox_project` /
`flask_test_client` / `ia_client`):

```
tests/test_dlc_jobs_unified.py ............. (13 passed)
tests/test_inline_analysis_session_stop_guard.py ..... (5 passed)
tests/test_inline_analysis_peaks_route.py ......................... (25 passed)
= 43 passed in 0.45s =

node --input-type=module --check < src/static/js/jobs.js   -> OK (loaded as
  <script type="module"> per jobs.html; classic-script parsing was NOT used)
node tests/test_jobs_js_cancel_ui.mjs                        -> all assertions passed
```

New route tests cover: three-source merge, de-dup-by-id preferring the
richer zset record, `celery_reachable:false` on both an inspector exception
and a timed-out/unreachable inspector (`active()`/`reserved()` both `None`)
while still returning the other sources, inline pending count from `LLEN`,
inline rows surviving after the session itself is no longer running (the
"stranded queue" case), celery-cancel `terminate=True`, inline-cancel
control-key+queue-delete, and 400s for missing/unknown type, missing id, and
malformed inline id.

`test_inline_analysis_session_stop_guard.py` and
`test_inline_analysis_peaks_route.py` were re-run unmodified (only
`inline_analysis.py`'s `session_stop` body changed, delegating its explicit
branch to the new `_explicit_session_stop` helper) to confirm the refactor
didn't regress `f0f71be`'s behavior — no existing assertion was weakened or
deleted.

## Mutation-proof output

**(a) `terminate=True` → `terminate=False`** in `dlc_jobs_cancel`:

```
FAILED tests/test_dlc_jobs_unified.py::TestJobsCancel::test_celery_type_revokes_with_terminate_true
AssertionError: assert [('t-1', False)] == [('t-1', True)]
```
Reverted; full suite green again.

**(b) inline cancel skips the queue delete** (commented out `redis_.delete(queue_key)`
in `_explicit_session_stop`):

```
FAILED tests/test_dlc_jobs_unified.py::TestJobsCancel::test_inline_type_sets_control_key_and_deletes_queue
AssertionError: assert 3 == 0
FAILED tests/test_inline_analysis_session_stop_guard.py::test_explicit_stop_sets_control_key_and_deletes_the_queue
AssertionError: assert 2 == 0
FAILED tests/test_inline_analysis_session_stop_guard.py::test_explicit_stop_default_false_matches_absent_flag
AssertionError: assert 1 == 0
3 failed, 3 passed
```
This mutation also broke two of the **pre-existing** `f0f71be` tests, confirming
the shared helper is genuinely load-bearing for both call sites (the Jobs-page
cancel and the original `/session/stop` explicit path), not just for the new
test. Reverted; full suite green again (43 passed).

## tasks.py grep (constraint check)

```
$ git diff -U0 f0f71be -- src/dlc/tasks.py | grep '^-' | grep -v '^---'
(no output)
```
`src/dlc/tasks.py` — including `_run_range` — is untouched since `f0f71be`.

## Concerns / notes for review

- **No commit was made.** Per the git-safety rule ("never commit unless
  explicitly asked"), all changes are in the working tree only. Ask if you
  want a commit; I'll report the real sha then instead of the placeholder above.
- **Old `/dlc/task/<id>/terminate` Stop button is left reachable for every
  `type="celery"` row**, not just train/analyze. It already degrades
  gracefully (404 JSON + `alert()`) for a row that has no `dlc_train_job:`/
  `dlc_analyze_job:` hash (e.g. a bare Celery-inspector-only row like
  `tasks.dlc_emit_peaks`), so nothing crashes, but clicking Stop on such a
  row is a slightly confusing no-op-with-error rather than being hidden
  outright. The new rail-level Cancel button is the intended kill switch for
  those rows; I left the old Stop button's gating exactly as it was
  pre-existing (`state === "running" || "paused"`, no kind check) rather than
  inventing new gating logic that wasn't requested.
- **Detail pane for `type="inline"` rows has no log stream** (there is no
  `dlc_task:<id>:log` for a warm session) — shows a small summary (project,
  snapshot, pending count, state) with its own Cancel button instead. This
  matches the spec's "keep the log view working for the training rows that
  have logs" — it was never claimed for inline rows.
- **`inline_analysis.py`'s `_explicit_session_stop`** is a new, small,
  behavior-preserving extraction (the exact 4 lines that used to live inline
  in `session_stop`, now shared). No existing test's assertions were
  weakened; `test_inline_analysis_session_stop_guard.py` passed unmodified
  before and after.
- **`monitoring.py`'s `_reconcile_job`** is the same treatment: `dlc_training_jobs`'s
  nested `_reconcile` closure was moved to module scope, unchanged body, and
  `dlc_training_jobs` now calls it. I could not re-run
  `tests/test_jobs_page_endpoints.py` (it depends on the forbidden
  `flask_test_client` fixture) to double-confirm `/dlc/training/jobs` byte-for-byte,
  so this rests on the diff being a pure move + the new tests exercising the
  same reconciliation path indirectly via `/dlc/jobs/all`. Recommend running
  that file yourself if you want it re-verified (it's a modest-size fixture,
  not `dlc_sandbox_project`, but I stayed within the letter of the hazard note).
- **Celery-inspector "unreachable" detection** treats `active() is None and
  reserved() is None` as unreachable (in addition to any exception). Real
  Celery can return `{}` (empty dict) rather than `None` when workers respond
  but have nothing running — that's correctly treated as reachable-but-idle,
  not unreachable. Only a genuine no-reply/timeout (which surfaces as `None`
  in the Celery/Kombu inspect API) or an exception trips `celery_reachable: false`.

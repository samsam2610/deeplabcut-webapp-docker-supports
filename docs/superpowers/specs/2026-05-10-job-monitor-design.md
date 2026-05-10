# Job Monitor Page (`/jobs`) — Design

**Date:** 2026-05-10
**Repo:** `deeplabcut-webapp-docker` (main webapp; not dlc-3D module)
**Status:** Spec — pending implementation plan

## Goal

A standalone, session-independent page at `/jobs` that lists every running
DLC train/analyze task and streams its terminal output in real time, with
a Stop button that works from any browser session — not just the one that
started the task.

## Why

The existing per-card UIs stash the active task_id in JS state from the
"Run Training" / "Run Analyze" click. Closing that tab loses the task_id;
a fresh tab has no way to find or stop the running task. Symptoms the user
reported on the existing UI:

- "Can't be seen if I open a new tab and close the old one."
- "Stop function doesn't work if I switched to a different session."
- "GPU monitor and job killer didn't work; only Stop in the original
  session works."

The Redis tracking already exists and IS global — `dlc_train_jobs` /
`dlc_analyze_jobs` zsets, per-task hashes, and the `dlc_task:<id>:log`
list populated by emit_loop in the worker. The new page reads from those
keys directly, so it is correct regardless of who created the task.

## Non-goals

- ML inference (`dlc_machine_label_frames`) job tracking. Activating it
  requires extending the ML task to write the same Redis pattern as
  train/analyze, which needs a worker restart. Deferred to a follow-up.
- Pause/resume controls (the underlying endpoints exist but are not
  exposed on this page).
- Clear-finished button.
- Multi-job simultaneous log viewing.
- Downloadable log archive.

## Components

| New file | Purpose |
|---|---|
| `src/templates/jobs.html` | Standalone page extending `base.html`; rail + detail-pane layout |
| `src/static/css/jobs.css` | Page styling (terminal pane, status badges, focus rail) |
| `src/static/js/jobs.js` | List polling, SSE lifecycle, visibility/timeout, stop wiring |
| `tests/test_jobs_page_endpoints.py` | Backend unit/integration tests |
| `tests/test_jobs_page_render.py` | Page render + nav button tests |
| `tests/e2e_jobs_cross_session.py` | Playwright cross-session E2E |

| Edited file | Change |
|---|---|
| `src/dlc/task_control.py` | Add `GET /dlc/task/<id>/log-tail?n=2000` |
| `src/dlc/monitoring.py` | One extra reconciliation line: force `status="running"` when Celery state is live but Redis says dead/stopped |
| `src/app.py` | Add `GET /jobs` route → render `jobs.html` |
| `src/templates/base.html` | Add "Jobs" nav button next to "3D Extractor" |

**Worker changes: zero.** Page lives entirely on the flask side — ships
with a flask restart only. No worker restart needed; the running training
is unaffected.

## Page layout

```
┌────────────── /jobs ────────────────────────────────────────────────────────┐
│  Jobs                                            ⏸ paused (tab hidden)      │
├──────────────────────────┬──────────────────────────────────────────────────┤
│  ▸ train  5acf20dd  ●     │  train  5acf20dd-…   project: DREADD-Ali …      │
│    DREADD-Ali  GPU0  3h12m│  engine: pytorch  GPU0  started: 20:16:42       │
│    pytorch                │  status: running          [ Stop ]              │
│  ─────────────────────────│ ────────────────────────────────────────────── │
│    analyze  ghi34   ●     │  Last 2000 log lines + live tail:               │
│    Project-X  GPU0  18s   │  ┌───────────────────────────────────────────┐  │
│    pytorch                │  │ Epoch 12/150 (lr=0.0006) train loss …    │  │
│  ─────────────────────────│  │ Epoch 13/150 …                            │  │
│    train  abcd56   ✓ done │  │ Epoch 14/150 …                            │  │
│    DREADD-Ali  GPU0       │  │ Epoch 15/150 …                            │  │
│    13m runtime            │  │ Epoch 16/150 …                            │  │
│                           │  │ ▍                                          │  │
│                           │  └───────────────────────────────────────────┘  │
│                           │  [ Reconnect ]  (shown only when stream closed) │
└──────────────────────────┴──────────────────────────────────────────────────┘
```

**Job-row contents:** task_id (last 8 chars), op (train/analyze), project
name, GPU id, runtime, status indicator: ● running, ⏸ paused, ✓ done,
✗ failed, ⚠ dead.

**Stop button:** shown only for `running` and `paused` statuses. Click →
single confirmation dialog ("Stop training task 5acf20dd? This cannot be
undone.") → POST `/dlc/task/<id>/terminate`.

**Header status pill** reflects the SSE state for the currently-selected
job: `live · streaming` / `paused (tab hidden)` /
`closed (idle 20m — Reconnect)` / `disconnected (server unreachable)`.

**Empty states:**
- No jobs at all: "No jobs running. Start a training or analyze task from
  the project card."
- Jobs present, none selected: "Select a job from the list to see its
  log."

## Frontend behavior (`jobs.js`)

**Per-page-load state:**
- `selectedTaskId` — currently-focused job (null on first load)
- `eventSource` — open EventSource for the selected job, or null
- `listPollTimer` — setInterval handle for `/dlc/training/jobs`
- `idleTimer` — setTimeout handle for the 20-min hard cap

**Lifecycle:**

1. **Page load:** fetch `/dlc/training/jobs` once → render rail.
   Auto-select the most recent running job if any. Start `listPollTimer`
   (3000 ms).
2. **Row click:** `selectedTaskId = id`; close any existing
   `eventSource`; fetch `/dlc/task/<id>/log-tail?n=2000`; paint into
   terminal pane; open `new EventSource('/dlc/task/<id>/log-stream')`;
   append each `data:` frame to the pane. Auto-scroll only when the user
   is already at the bottom (otherwise hold position).
3. **`visibilitychange` → hidden:** close `eventSource`, clear
   `listPollTimer`. Header pill: `paused (tab hidden)`. Start
   `idleTimer = setTimeout(20*60*1000)`.
4. **`visibilitychange` → visible BEFORE `idleTimer` fires:** clear
   `idleTimer`, reopen the EventSource (re-tail backfill), restart
   `listPollTimer`. Header pill: `live · streaming`.
5. **`idleTimer` fires (20 min hidden):** explicitly close everything,
   header pill `closed (idle 20m — Reconnect)`, show **Reconnect**
   button below the terminal. Click reconnects (same flow as row click).
6. **Stop click:** POST `/dlc/task/<id>/terminate`. On 200, the next
   list-poll tick surfaces the new `stopping`/`stopped` status; the SSE
   stream continues until the task actually exits and closes its log key.
7. **EventSource error (server-side close, network glitch):** auto-
   reconnect once after 2 s; second failure → header pill `disconnected`
   + show Reconnect button.

**Why explicitly close on row click:** EventSource keeps the connection
open even when not displayed; not closing leaks one connection per click.

## Server-side endpoints

### New: `GET /dlc/task/<id>/log-tail?n=2000`

Five-line wrapper in `src/dlc/task_control.py`:

```python
@bp.route("/dlc/task/<task_id>/log-tail")
def task_log_tail(task_id: str):
    n = max(1, min(int(request.args.get("n", 2000)), 10000))
    r = _ctx.redis_client()
    log_key = f"dlc_task:{task_id}:log"
    lines = r.lrange(log_key, -n, -1)
    return jsonify({"lines": lines, "total": r.llen(log_key)})
```

Read-only, idempotent, no session state.

### Edited: `/dlc/training/jobs` (one reconciliation line)

Currently in `src/dlc/monitoring.py:_reconcile`:

```python
if job.get("status") == "running":
    celery_state = AsyncResult(jid, app=_ctx.celery()).state
    if celery_state not in _LIVE_CELERY_STATES:
        redis.hset(redis_key, "status", "dead")
```

Add the inverse: when Redis says `dead` or `stopped` but Celery is live,
flip to `running`. Fixes the user-visible misreport for the currently-
running training (`5acf20dd-...`) and any future Reaper false-positive:

```python
elif celery_state in _LIVE_CELERY_STATES and job.get("status") in ("dead", "stopped"):
    redis.hset(redis_key, "status", "running")
    job["status"] = "running"
```

### New: `GET /jobs`

In `src/app.py`:

```python
@app.route("/jobs")
def jobs_page():
    return render_template("jobs.html")
```

Subject to the existing `_require_auth` `before_request` handler.

### Reused (no changes): `POST /dlc/task/<id>/terminate`

Already accepts a task_id with no session/uid lookup. Cross-session safe
by construction.

## Cross-session correctness — the explicit guarantees

| Risk | Mitigation |
|---|---|
| Page only shows tasks created in the current session | All listing comes from the global `dlc_train_jobs` / `dlc_analyze_jobs` Redis zsets — no `_user_id()` anywhere in the request path. |
| Stop button silently fails from a fresh tab | `/dlc/task/<id>/terminate` takes only the task_id from the URL, no session/uid lookup. |
| SSE returns nothing in a fresh tab | Log lines live in `dlc_task:<id>:log` (global Redis list, populated by emit_loop in the worker — independent of any browser session). |
| Page loads in a tab that hasn't auth'd (e.g., fresh incognito) | Existing `before_request` redirects to login; user enters token once, page works. |

## Edge cases

| Case | Behavior |
|---|---|
| User opens `/jobs` with no tasks ever run | Empty list; "No jobs running." |
| Job finishes while user is viewing its log | SSE generator hits the existing terminal-status close condition. Header pill switches to `closed`. List poll updates the badge to ✓ done. |
| Flask restart mid-view | EventSource auto-reconnect (built into spec) reopens. Backfill via tail picks up any lines added during the gap. |
| Worker restart mid-view | Subprocess ends → log key stops growing → SSE closes cleanly with terminal status. PID-cleanup Reaper marks job dead, page badge updates within one poll. |
| Two browsers stop the same task simultaneously | Idempotent: second call sees no PID, returns the dead/orphaned cleanup path (still 200, status `stopped`). |
| Tab hidden right when a job finishes | `idleTimer` keeps running; on visible again, list poll fires, badge shows `done`, terminal pane re-tails with final lines. |
| Long log file (>10000 lines) | `log-tail` capped at 10000 server-side. Live tail picks up from there. |

## Tests

Three test files. The user explicitly asked for cross-session coverage —
the spec is built around proving that, not just functional correctness.

### `tests/test_jobs_page_endpoints.py`

| Test | Asserts |
|---|---|
| `test_log_tail_returns_last_n_lines` | RPUSH 5 lines → GET `?n=3` → returns the last 3 in order, plus `total: 5`. |
| `test_log_tail_n_capped_at_10000` | n=99999 → server clamps to 10000, no error. |
| `test_log_tail_unknown_task_returns_empty_list` | GET on a never-seen task_id → `{"lines": [], "total": 0}`, status 200. |
| `test_jobs_endpoint_no_uid_in_payload` | Response JSON has no key matching `uid`/`user`/`session`/`webapp:` — confirms the wire format isn't session-coupled. |
| `test_jobs_endpoint_lists_jobs_from_any_session` | Session A: HSET + ZADD a job. Session B (fresh test client, fresh cookie): GET `/dlc/training/jobs` → job appears. |
| `test_terminate_endpoint_works_without_session_state` | POST from a fresh test client → returns 200 OR 404 (with body matching "not found" because no PID), but never raises 500. Stub `_resolve_task` to drive the no-PID path. |
| `test_jobs_endpoint_force_running_when_celery_live` | HSET status=`dead`. Stub `AsyncResult(jid).state` → `PROGRESS`. GET → reported as `running`. |

### `tests/test_jobs_page_render.py`

| Test | Asserts |
|---|---|
| `test_jobs_page_renders` | GET `/jobs` (auth'd) → 200, body contains `id="jobs-rail"` and `id="jobs-detail"` and the script tag for `jobs.js`. |
| `test_jobs_page_redirects_to_login_when_unauth` | Fresh client, no cookie, no token → 302 to `/login`. |
| `test_jobs_page_loads_when_redis_empty` | Wipe `dlc_train_jobs` + `dlc_analyze_jobs` → GET → 200, no JS-error tag in body. |
| `test_nav_button_appears_on_base_template` | GET `/` → body contains `href="/jobs"` and visible label "Jobs". |

### `tests/e2e_jobs_cross_session.py` (Playwright — the headline test)

Two completely independent browser contexts simulate "a different session
entirely." Tests don't touch the real worker — they seed Redis directly
through a small `seed_test_job(redis, task_id, …)` helper that mimics
what the real task writes.

Tests:

- `test_stop_works_from_a_session_that_did_not_start_the_task` — Session
  B clicks Stop on a job seeded by Session A; status updates within one
  list-poll tick.
- `test_log_visible_from_session_that_did_not_start_the_task` — Session
  B selects the job → terminal pane shows the seeded log lines.
- `test_visibility_change_pauses_and_resumes_sse` — mock visibilitychange
  events; verify EventSource opens/closes accordingly; verify lines
  pushed while hidden are picked up after the resume tail.
- `test_idle_timeout_closes_after_simulated_20m` — override the 20-min
  cap via `?_test_idle_ms=500` (only honored when `FLASK_DEBUG`;
  production ignores it). Verify the Reconnect button appears.

## Run order

```bash
pytest tests/test_jobs_page_endpoints.py tests/test_jobs_page_render.py -v
pytest tests/e2e_jobs_cross_session.py -v   # requires playwright + live stack
```

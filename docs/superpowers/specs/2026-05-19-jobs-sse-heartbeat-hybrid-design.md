# Jobs log-stream SSE — heartbeat + 1-SSE-per-tab hybrid

Date: 2026-05-19
Repo: `deeplabcut-webapp-docker` (main webapp)
Branch: whatever is currently checked out (`feat/posture-match-refiner` at
time of writing).

## Problem

The `/jobs` page hung and the public site returned 502 because all four
gunicorn sync workers were pinned by long-lived SSE connections to
`/dlc/task/<id>/log-stream`. Two consumers (`jobs.js` and `gpu_monitor.js`)
each open their own `EventSource`, so a couple of viewers exhaust the pool.

The server-side generator (`task_control.py::task_log_stream`) loops forever
polling Redis at 1Hz and only exits when the task hits a terminal state plus
two idle polls. There is no inter-line keep-alive, so an intermediate proxy
(nginx) that closes idle connections will sever the stream even though it
holds a worker server-side.

## Goals

- Eliminate worker starvation on `/jobs` without bumping gunicorn worker
  count or switching worker classes.
- Keep real-time log streaming for the **one task the user is currently
  watching**.
- Let any number of additional log consumers exist on the page, fetching
  data via short polling (`/dlc/task/<id>/log-tail`) instead of holding
  their own SSE.
- Add a server-side heartbeat so the SSE survives proxy idle timeouts and
  so the client can distinguish "server still alive" from "connection dropped"
  during quiet periods (e.g. between training epochs).
- Do **not** add any inactivity/idle timeout — server or client. A user can
  leave the page open indefinitely.

## Non-goals

- Refactoring the dlc-3D module's job stream or the clip-cutter `queue_stream`.
  Those have their own patterns and aren't on fire today.
- Switching gunicorn from sync to gevent/gthread. Worth doing later, but
  out of scope here.
- Persisting log streams across a flask restart. Today's behavior
  (clients re-subscribe automatically via `EventSource` auto-reconnect)
  is fine.

## Architecture

### One shared client module: `src/static/js/log_stream.js` (NEW)

A small module that owns the single `EventSource` per browser tab and
exposes two operations to callers:

```js
// Returns an unsubscribe() function. Multiple subscribers for the SAME
// taskId share a single EventSource. A new subscribe() for a DIFFERENT
// taskId takes over the SSE; previous subscribers get onDemoted() and
// must arrange their own pollTail() if they still want updates.
logStream.subscribe(taskId, {
  onLine:    (line) => {},   // new log line
  onDone:    ()     => {},   // task hit terminal state, stream closed
  onDemoted: ()     => {},   // another caller took the SSE for a different task
});

// Returns a stop() function. Polls /dlc/task/<id>/log-tail every
// intervalMs and emits only NEW lines (uses the `total` field as a
// cursor). Use this when subscribe() demoted you.
logStream.pollTail(taskId, {
  intervalMs: 60_000,
  onLines:    (newLines) => {},
});
```

Internal invariants:

- At most ONE `EventSource` is open in the tab at any moment.
- The active `EventSource` is associated with exactly one `taskId`. Every
  subscriber registered against that `taskId` receives every `onLine`.
- Closing the last subscriber for the active task closes the
  `EventSource`. If no subscribers remain, the module is idle.
- `pollTail` is independent — many `pollTail` loops can run in parallel
  for different tasks; each is a one-shot fetch on a `setInterval`, so
  none of them holds a worker.

### Server side: heartbeat in `task_log_stream`

`src/dlc/task_control.py::task_log_stream` adds a heartbeat. Concretely:

- Track `last_send_at` (monotonic). Each yielded SSE frame updates it.
- On every loop iteration where `time.monotonic() - last_send_at >= 60`
  AND no new lines were just yielded, yield an SSE comment line:
  `: heartbeat\n\n` and update `last_send_at`. (Lines starting with `:`
  are SSE comments — the spec ignores them client-side and they keep the
  connection warm.)
- Terminal-state auto-close (today's behavior, lines 217–229) is kept.
- The 1-second `time.sleep(1)` between polls stays. The heartbeat does
  not change polling frequency, only ensures something is written
  periodically.

The constant `60` is sourced from a module-level `HEARTBEAT_SECONDS` so
tests can monkeypatch it down to ~0.2s.

### Client refactors

**`jobs.js`** — Replace the inline `new EventSource(...)` in `_openStream`
with `logStream.subscribe(taskId, { onLine, onDone, onDemoted })`. Drop the
20-min idle timer (referenced in the file header comment block — search for
"20-min idle timeout"). Drop the bespoke retry/reconnect logic; the shared
module handles those concerns. On `onDemoted`, transparently fall back to
`pollTail` so the user keeps seeing log updates (just at 60s cadence) when
some other consumer took the SSE for a different task.

**`gpu_monitor.js`** — Same refactor. Replace `_gmLogEventSource` with a
`subscribe()` call; on `onDemoted`, switch to `pollTail`.

### What we do NOT do

- No idle timeout — client or server. The heartbeat lives forever, the
  EventSource stays open as long as a subscriber wants it.
- No throttling of `pollTail` to per-tab quotas — it's just HTTP GETs to a
  cheap endpoint that already exists.

## Data flow

```
   jobs.js     gpu_monitor.js     (future consumer)
      \             |                   /
       \            |                  /
        +---- log_stream.js (shared) --+
                    |
              (1 EventSource max)
                    |
       GET /dlc/task/<id>/log-stream   <-- has heartbeat now
                    |
              flask worker
                    |
              Redis BRPOP/LRANGE
                    |
              celery worker (RPUSH log lines)
```

Polling path (for demoted / non-focused consumers):

```
pollTail loop --setInterval(60s)--> GET /dlc/task/<id>/log-tail
                                          |
                                    flask worker (cheap,
                                    one-shot, no hold)
```

## Files touched

- `src/dlc/task_control.py` — add `HEARTBEAT_SECONDS` constant + heartbeat
  emission in `_generate()`.
- `src/static/js/log_stream.js` — NEW shared module.
- `src/static/js/jobs.js` — use shared module; drop idle timer + retry
  bespoke logic.
- `src/static/js/gpu_monitor.js` — use shared module.
- `tests/test_task_log_stream_heartbeat.py` — NEW pytest.
- `tests/test_log_stream_module.py` — NEW static-source guards for the JS
  module's API surface and consumer usage.

No template changes. No backend route additions. `/dlc/task/<id>/log-tail`
already exists and is reused as-is.

## Testing

### Server unit test (`tests/test_task_log_stream_heartbeat.py`)

Direct unit test of the generator. Monkeypatch `HEARTBEAT_SECONDS` to a
small value (e.g. 0.2s) and `time.sleep` to a fast version, drive the
generator with a fake redis_client whose `lrange` returns no new lines and
whose `hget` returns a non-terminal status. Collect a few iterations of
yielded frames and assert at least one matches `b": heartbeat"` (or string
prefix `: heartbeat`).

A second test runs the generator with new lines arriving on every poll and
asserts NO heartbeat is emitted while real data is flowing (because real
data frames reset `last_send_at`).

### Client static-source guards (`tests/test_log_stream_module.py`)

Mirroring the existing `test_frame_labeler_*` pattern:

1. Assert `src/static/js/log_stream.js` exports both `subscribe` and
   `pollTail` (grep for the function names and an `export` / global
   attachment pattern).
2. Assert `src/static/js/jobs.js` no longer constructs `new EventSource(`
   for `/dlc/task/`. It must go through `log_stream`.
3. Assert `src/static/js/gpu_monitor.js` no longer constructs
   `new EventSource(`.
4. Assert the string `20-min idle` (or its surrounding 20-minute idle
   timer logic) is gone from `jobs.js` — guards against the timer being
   reintroduced.

### Live integration test against the running training

There is currently a training job running with task_id
`7f977f80-7774-417f-b28e-f47bfaa80cd3` (181% CPU on the worker container,
150+ log lines already in Redis, status `running`). After implementation
and `docker compose restart flask`, run these smoke checks:

1. **Heartbeat shows up**: from the host, `curl --no-buffer -N
   http://localhost:5000/dlc/task/7f977f80-7774-417f-b28e-f47bfaa80cd3/log-stream`
   and confirm within ~70s either (a) actual `data:` log frames, or
   (b) at least one `: heartbeat` line. Interrupt the curl after the
   evidence is captured (Ctrl-C / kill the curl pid). Do this with a
   short read timeout so the connection closes cleanly.
2. **No starvation**: open six parallel SSE connections to the same
   task in background with `curl --max-time 30`, and simultaneously
   `curl http://localhost:5000/dlc/training/jobs` — the second curl must
   return 200 in <2s. This proves consumers sharing the SAME task no
   longer scales workers linearly. (In the *old* code, six SSEs would
   block all four gunicorn workers; here the server still has 4 workers
   pinned for 30s on the six parallel curls because each curl is a
   separate `EventSource`. The client-side dedup is browser-side. So this
   step is the LIMIT of the server fix; it confirms heartbeat works,
   not dedup. Dedup is verified by the static guards instead.)
3. **Training survives**: `docker stats --no-stream` shows
   `deeplabcut-webapp-docker-worker-1` still at >100% CPU and status
   still `running` in Redis (`HGET dlc_train_job:<id> status`). This is
   the most important check — proves the flask restart did not disturb
   training.

All three checks must succeed before sign-off.

## Hard constraints during implementation

- **Do NOT restart** `worker`, `worker-tf`, `dlc-3d-worker`, or `redis`.
  Training in `worker` must keep running uninterrupted.
- `flask` restart IS allowed (and necessary, to pick up the
  `task_control.py` change). Flask restart does not touch celery.
- `dlc-3d` rebuild is NOT needed — no dlc-3d files change.
- The job's live logs and Redis state must survive across flask restarts
  (they already do; just don't accidentally `docker compose down`).

## Risks and mitigations

- **Risk**: heartbeat comment frames confuse a client that's strict about
  `data:` events. Mitigation: SSE comment frames (`: foo`) are part of the
  W3C SSE spec; `EventSource` ignores them and doesn't fire `message`
  events for them. Verified by spec, no special-casing needed in clients.
- **Risk**: subscribe→demoted→pollTail dance has a race where a line
  arrives between SSE close and the first poll. Mitigation: `pollTail`
  uses `total` as a cursor; the first poll reads everything since the
  consumer last saw, so no gap.
- **Risk**: a flask restart drops the active SSE, training keeps running,
  but the user sees a brief gap. Mitigation: `EventSource` auto-reconnects;
  the next poll picks up logs from the cursor.

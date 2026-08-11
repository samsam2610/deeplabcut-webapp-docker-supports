# Session-stop guard fix — report

## Status

Done. Both repos on `fix/marker-save-race` (no new branches/worktrees created).

## Commits

- Main webapp (`/home/sam/docker-images/deeplabcut-webapp-docker`):
  `f0f71be` — fix(inline-analysis): server-side only_if_idle guard on session/stop
- Support module (`/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D`):
  `cb68576` — fix(inline-3d): send only_if_idle:true on tab/card close for session/stop

## What changed

**`src/dlc/inline_analysis.py`** (`session_stop` route): added a boolean
`only_if_idle` body field (default `false`, preserving prior behaviour for
any existing caller):
- `only_if_idle: true` → if `LLEN inline:queue:<user>:<snap_key> > 0`, do
  NOT set the control key; return `{"stopped": false, "pending": N}`. If
  empty, set the stop key and return `{"stopped": true, "pending": 0}`.
- `only_if_idle` absent/false → explicit cancel: set the stop key AND
  `DELETE` the queue key; return `{"stopped": true, "cleared": N}`.
- Missing `snap_key` still 400.
- Route now returns JSON, not `("", 204)`.

**`dlc-3D/src/static/inline_analysis_3d.js`**: both the card-close handler
(`btn-close-inline-analysis-3d` click listener that calls `session/stop`)
and the `beforeunload` handler now send `only_if_idle: true`. `beforeunload`
prefers `navigator.sendBeacon` with a JSON-typed `Blob`, falling back to
`fetch(..., {keepalive: true})` when `sendBeacon` is unavailable; the
card-close `fetch` call also now passes `keepalive: true`. The reprojection
card's `beforeunload` no-op (`inline_analysis_3d_reprojection.js`) was left
untouched — verified by a dedicated test.

## sendBeacon JSON body — did it parse server-side?

Yes, verified directly (not assumed). Simulated exactly what
`navigator.sendBeacon(url, new Blob([json], {type: "application/json"}))`
puts on the wire — a raw-bytes body plus a `Content-Type: application/json`
request header — against the real route via Flask's test client:

```
status: 200
body: {'pending': 0, 'stopped': True}
control key present: stop
```

`request.get_json(silent=True)` parses it fine because Flask's JSON
detection is based on the request's `Content-Type` header, and the Beacon
spec sets that header from the `Blob`'s `type`. No change was needed to make
the beacon path work — it already worked, which is *why* the original bug
existed (the stop command reliably reached and was honored by the server on
tab close). I kept the `fetch(..., {keepalive: true})` fallback anyway for
browsers/paths without `sendBeacon`.

## Test summary

**Main webapp** — new file `tests/test_inline_analysis_session_stop_guard.py`
(mirrors `tests/test_inline_analysis_peaks_route.py`'s minimal-Flask-app +
`fake_redis` style; no `dlc_sandbox_project` / `flask_test_client` /
`ia_client`):

```
tests/test_inline_analysis_session_stop_guard.py .....   [100%]   5 passed
```
Covers: `only_if_idle=true` + non-empty queue → declined, pending count
correct, queue untouched; `only_if_idle=true` + empty queue → stopped;
explicit stop (flag absent) → stopped AND queue deleted; `only_if_idle=false`
explicit matches absent; missing `snap_key` → 400 (both flag variants).

Touched one **pre-existing** test: `tests/test_inline_analysis_routes.py::TestSessionStop::test_sets_control_key_to_stop`
— its `resp.status_code == 204` assertion was updated to `200` (the route's
response-contract change from `("", 204)` to JSON). Its original assertion
(`redis.get("inline:control:u1:k1") == "stop"`) was kept, not weakened.

Also re-ran `tests/test_inline_analysis_peaks_route.py` (25 passed) to make
sure nothing in the shared blueprint module broke.

**dlc-3D** — new file `tests/test_session_stop_guard_wiring.py` (static
regex guards over the JS source, same pattern as
`tests/test_inline_3d_lock_wiring.py` / `test_reproj_card_namespace.py`):

```
tests/test_session_stop_guard_wiring.py ....   [100%]   4 passed
```
Covers: card-close handler sends `only_if_idle: true`; `beforeunload`
handler sends `only_if_idle: true`; `beforeunload` prefers `sendBeacon`
with a `application/json`-typed `Blob` and falls back to a `keepalive`
`fetch`; the reprojection card's `beforeunload` still sends no stop at all
(and stays a documented no-op).

Full-suite runs (post-fix):
- `python3 -m pytest tests/ -q --ignore=tests/e2e` → **8 failed, 866
  passed, 3 skipped** — same 8 pre-existing failures as the stated baseline
  (`test_inline_analysis_3d_ui_isolation.py::test_finalize3d_confirms_before_overwrite`,
  2× `test_lp_csv_to_h5.py`, 5× `test_lp_predict_pairing.py`, all unrelated
  to this change — ffmpeg/ffprobe environment issues), plus the 862-baseline
  passing count now 866 (+4 new wiring tests).
- `node --test tests/unit/*.mjs` → **28/28 pass**, matching baseline.

## Mutation-proof drills (main webapp)

**Mutation 1** — made the route ignore `only_if_idle` (always set the stop
key unconditionally):
```
tests/test_inline_analysis_session_stop_guard.py F....   [100%]
FAILED test_only_if_idle_with_nonempty_queue_declines_the_stop
  assert body["stopped"] is False
  AssertionError: assert True is False
1 failed, 4 passed
```
Reverted; confirmed back to 5/5 passing (byte-for-byte diff against the
pre-mutation backup was empty).

**Mutation 2** — made the explicit-stop path skip the queue delete:
```
tests/test_inline_analysis_session_stop_guard.py ..FF.   [100%]
FAILED test_explicit_stop_sets_control_key_and_deletes_the_queue
  assert fake_redis.llen(queue_key) == 0
  AssertionError: assert 2 == 0
FAILED test_explicit_stop_default_false_matches_absent_flag
  assert fake_redis.llen(queue_key) == 0
  AssertionError: assert 1 == 0
2 failed, 3 passed
```
Reverted; confirmed back to 5/5 passing (and 25/25 on
`test_inline_analysis_peaks_route.py`, byte-for-byte diff empty).

## Mutation-proof drills (dlc-3D JS wiring)

Stripped `only_if_idle: true` from both handlers (regex substitution):
```
tests/test_session_stop_guard_wiring.py FF..
FAILED test_card_close_handler_sends_only_if_idle_true
FAILED test_beforeunload_handler_sends_only_if_idle_true
2 failed, 2 passed
```
Reverted; confirmed back to 4/4 passing, `node --check --input-type=module`
clean, and byte-for-byte diff against the pre-mutation backup empty.

## tasks.py constraint check

```
$ git diff -U0 HEAD -- src/dlc/tasks.py | grep '^-' | grep -v '^---'
(no output — exit code 1, i.e. no removed lines)
```
`src/dlc/tasks.py` was never opened for editing; `_run_range` and every
other function in that file are untouched. (Diffing against `main` instead
of `HEAD` shows one unrelated pre-existing line change already on this
branch from an earlier commit — `HEAD` is the correct base for "did *this*
change touch tasks.py.")

## Concerns / notes

- `src/static/js/inline_analysis_player.js` (main webapp's own inline-
  analysis card, a different surface from dlc-3D's) has the identical
  unconditional-stop pattern on `beforeunload`/card-close and is exposed to
  the same race. It was explicitly out of scope per the task (which scoped
  the client fix to `dlc-3D/src/static/inline_analysis_3d.js` only), and the
  server-side route change protects it too now for the *explicit*-stop path
  (queue no longer orphaned), but that caller still does an unconditional
  stop rather than `only_if_idle: true`, so it can still kill a session fed
  by another tab. Flagging as a candidate follow-up, not fixed here.
- The route's response contract changed from `("", 204)` to JSON `200`.
  Grepped both repos for `session/stop` callers; the only caller that
  asserted the old status code was `tests/test_inline_analysis_routes.py`,
  which was updated (assertion widened only on status code, kept the
  control-key assertion). No production JS caller inspects the response
  status or body.

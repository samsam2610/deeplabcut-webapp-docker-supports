# Job Monitor Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a session-independent `/jobs` page on the main webapp that lists every running DLC train/analyze task, streams their terminal output in real time, and exposes a Stop button that works from ANY browser session — fixing the user-reported issues where the existing card UIs lose track of the task_id when the originating tab closes.

**Architecture:** Page lives entirely on the flask side (no worker changes). Reads from the existing global Redis state (`dlc_train_jobs` zset, per-task `dlc_train_job:<id>` hash, `dlc_task:<id>:log` list populated by the worker's emit_loop). Reuses existing SSE log-stream + terminate endpoints. Adds one new endpoint (`/dlc/task/<id>/log-tail`) for backfill, one reconciliation tweak in `/dlc/training/jobs`, and the page+nav.

**Tech Stack:** Flask + Jinja templates, vanilla ES module JS, EventSource (SSE), pytest with FakeRedis fixture, Playwright pytest for E2E. Bind-mount layout in `docker-compose.yml` means flask source edits go live with `docker compose restart flask` (no image rebuild). Worker container is NOT touched.

**Reference spec:** `docs/superpowers/specs/2026-05-10-job-monitor-design.md` (in the dlc-3D-supports repo at `/home/sam/docker-images/deeplabcut-webapp-docker-supports`)

**Constraints:**
- A real DLC training task is running on the worker right now (`5acf20dd-...`). Do NOT restart the worker container, send new Celery tasks that compete for the GPU, or modify worker-side code (`src/dlc/tasks.py`, `celery_app.py`).
- Flask container restart IS allowed (`docker compose restart flask`).

---

## File Structure

**Main webapp (`/home/sam/docker-images/deeplabcut-webapp-docker`) — new:**

| Path | Purpose |
|---|---|
| `src/templates/jobs.html` | Standalone page; rail + detail-pane layout |
| `src/static/css/jobs.css` | Page styling (terminal pane, rail, status badges) |
| `src/static/js/jobs.js` | List poll, SSE lifecycle, visibility+idle, Stop wiring |
| `tests/test_jobs_page_endpoints.py` | log-tail + reconciliation + cross-session unit tests |
| `tests/test_jobs_page_render.py` | Page render + nav button + auth tests |
| `tests/e2e_jobs_cross_session.py` | Playwright cross-session E2E |

**Main webapp — edited:**

| Path | Change |
|---|---|
| `src/dlc/task_control.py` | Add `GET /dlc/task/<id>/log-tail` endpoint |
| `src/dlc/monitoring.py` | One reconciliation line in `_reconcile()` |
| `src/app.py` | Add `GET /jobs` route |
| `src/templates/base.html` | Add "Jobs" nav anchor next to "3D Extractor" |
| `tests/conftest.py` | Add `lrange` to the FakeRedis fixture |

**Worker (`src/dlc/tasks.py`, `src/celery_app.py`):** untouched.

---

## Conventions

- Run pytest from the main webapp repo root: `cd /home/sam/docker-images/deeplabcut-webapp-docker && pytest tests/test_<file>.py -v`.
- After flask-side edits, the running container picks them up with: `docker compose restart flask`. Wait ~5 s before re-running tests against the live stack.
- Commit messages use the existing style (`feat: …` / `fix: …` / `test: …`). Trail every commit with `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`.
- All Python imports go at the top of files unless they need to be lazy for an obvious reason (Celery import order, etc.).
- HTML/CSS uses the existing app's design tokens (`var(--surface)`, `var(--border)`, `var(--text)`, `var(--text-dim)`, `var(--accent)`, `var(--mono)`); look at any existing card_*.html for conventions.

---

## Task 1: Extend FakeRedis with `lrange`

The log-tail endpoint uses `redis.lrange(key, -n, -1)` to return the last N entries of a list. The existing FakeRedis in `tests/conftest.py` implements `llen`, `rpush`, `lpop` but not `lrange`. Tests that use FakeRedis can't assert log-tail behavior without it.

**Files:**
- Modify: `tests/conftest.py` — extend the `FakeRedis` class

- [ ] **Step 1: Write the failing test**

Add to a new file `tests/test_fake_redis_lrange.py`:

```python
"""Verifies the FakeRedis fixture supports lrange — required by log-tail tests."""
def test_fake_redis_lrange_basic(fake_redis):
    fake_redis.rpush("mylist", "a", "b", "c", "d", "e")
    assert fake_redis.lrange("mylist", 0, -1) == ["a", "b", "c", "d", "e"]
    assert fake_redis.lrange("mylist", -2, -1) == ["d", "e"]
    assert fake_redis.lrange("mylist", -10, -1) == ["a", "b", "c", "d", "e"]


def test_fake_redis_lrange_unknown_key(fake_redis):
    assert fake_redis.lrange("never-pushed", 0, -1) == []


def test_fake_redis_lrange_positive_range(fake_redis):
    fake_redis.rpush("mylist", "a", "b", "c", "d", "e")
    assert fake_redis.lrange("mylist", 1, 3) == ["b", "c", "d"]
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
pytest tests/test_fake_redis_lrange.py -v
```

Expected: FAIL — `AttributeError: 'FakeRedis' object has no attribute 'lrange'`

- [ ] **Step 3: Implement `lrange` on FakeRedis**

Edit `tests/conftest.py`. Find the FakeRedis class section labeled `# ── lists (broker queues) ──` (around line 186) and add `lrange` next to `llen`/`rpush`/`lpop`:

```python
        def lrange(self, name, start, end):
            """Mirror Redis LRANGE semantics: end is INCLUSIVE; -1 means last."""
            lst = self._lists.get(name, [])
            n = len(lst)
            if not lst:
                return []
            # Normalise negative indices
            s = start if start >= 0 else max(0, n + start)
            e = end if end >= 0 else n + end
            # Redis end is inclusive; clamp e to n-1
            e = min(e, n - 1)
            if s > e:
                return []
            return list(lst[s:e + 1])
```

- [ ] **Step 4: Run to verify passing**

```bash
pytest tests/test_fake_redis_lrange.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add tests/conftest.py tests/test_fake_redis_lrange.py
git commit -m "$(cat <<'EOF'
test(infra): add lrange to FakeRedis for log-tail tests

The job-monitor page's log-tail endpoint uses redis.lrange to return
the last N entries of dlc_task:<id>:log. The existing FakeRedis in
the conftest fixture only implemented llen/rpush/lpop; without
lrange, tests for the new endpoint would 500 on attribute error.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add `GET /dlc/task/<id>/log-tail?n=N` endpoint

Read-only Redis-backed endpoint that returns the last N log lines plus the total list length. Used by `jobs.js` to backfill the terminal pane before opening the SSE stream.

**Files:**
- Modify: `src/dlc/task_control.py` — append the new route after the existing `task_log_stream` handler
- Test: `tests/test_jobs_page_endpoints.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_jobs_page_endpoints.py`:

```python
"""Backend tests for the /jobs page endpoints.

Covers:
  GET /dlc/task/<id>/log-tail?n=N — log backfill
  GET /dlc/training/jobs           — cross-session listing + reconciliation
  POST /dlc/task/<id>/terminate    — cross-session stop
"""
from __future__ import annotations

import json
from unittest.mock import patch


# ── log-tail ─────────────────────────────────────────────────────────────────

def test_log_tail_returns_last_n_lines(flask_test_client):
    client, app_module, redis, _, _ = flask_test_client
    redis.rpush("dlc_task:t1:log", "line 1", "line 2", "line 3", "line 4", "line 5")
    res = client.get("/dlc/task/t1/log-tail?n=3")
    assert res.status_code == 200
    data = res.get_json()
    assert data["lines"] == ["line 3", "line 4", "line 5"]
    assert data["total"] == 5


def test_log_tail_default_n_is_2000(flask_test_client):
    client, _, redis, _, _ = flask_test_client
    redis.rpush("dlc_task:t2:log", *[f"l{i}" for i in range(10)])
    res = client.get("/dlc/task/t2/log-tail")
    assert res.status_code == 200
    assert len(res.get_json()["lines"]) == 10  # well under the default cap


def test_log_tail_n_capped_at_10000(flask_test_client):
    client, _, redis, _, _ = flask_test_client
    redis.rpush("dlc_task:t3:log", "x")
    # n=99999 must clamp without raising; behavioral check via no-error.
    res = client.get("/dlc/task/t3/log-tail?n=99999")
    assert res.status_code == 200
    assert res.get_json()["lines"] == ["x"]


def test_log_tail_unknown_task_returns_empty_list(flask_test_client):
    client, _, _, _, _ = flask_test_client
    res = client.get("/dlc/task/never-existed/log-tail")
    assert res.status_code == 200
    data = res.get_json()
    assert data["lines"] == []
    assert data["total"] == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_jobs_page_endpoints.py::test_log_tail_returns_last_n_lines -v
```

Expected: FAIL with 404 (route not registered).

- [ ] **Step 3: Implement the endpoint**

Edit `src/dlc/task_control.py`. After the existing `task_log_stream` handler (look at the end of the file — there's a final `# end SSE` or just the last route), append:

```python
@bp.route("/dlc/task/<task_id>/log-tail")
def task_log_tail(task_id: str):
    """Return the last N log lines for a task — backfill for the /jobs page.

    Read-only, idempotent, no session state. Used by jobs.js to populate the
    terminal pane before opening the SSE stream.
    """
    try:
        n = int(_request.args.get("n", 2000))
    except (TypeError, ValueError):
        n = 2000
    n = max(1, min(n, 10000))
    r = _ctx.redis_client()
    log_key = f"dlc_task:{task_id}:log"
    lines = r.lrange(log_key, -n, -1)
    return jsonify({"lines": lines, "total": r.llen(log_key)})
```

The existing file imports `Response`, `jsonify`, `stream_with_context` from flask — add `request as _request` to the import line at the top, OR (if that import line is `from flask import Blueprint, Response, jsonify, stream_with_context`) change it to `from flask import Blueprint, Response, jsonify, request as _request, stream_with_context`. Read the existing import line first to choose.

- [ ] **Step 4: Run to verify passing**

```bash
docker compose restart flask
sleep 5
pytest tests/test_jobs_page_endpoints.py -v -k log_tail
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/task_control.py tests/test_jobs_page_endpoints.py
git commit -m "$(cat <<'EOF'
feat(jobs): add GET /dlc/task/<id>/log-tail for backfill

Reads the last N entries (default 2000, capped at 10000) of
dlc_task:<id>:log via redis.lrange. Powers the terminal-pane
backfill on the new /jobs page before the SSE stream opens.
Read-only, idempotent, no session state.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Force-running reconciliation in `/dlc/training/jobs`

Currently `_reconcile()` flips `running → dead` if Celery says the task is gone, but never flips `dead → running` when Celery says the task is alive. The user's running training is mis-displayed because of this. One added line.

**Files:**
- Modify: `src/dlc/monitoring.py` — extend `_reconcile()`
- Test: append to `tests/test_jobs_page_endpoints.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_jobs_page_endpoints.py`:

```python
# ── /dlc/training/jobs reconciliation ────────────────────────────────────────

def test_jobs_endpoint_force_running_when_celery_live(flask_test_client):
    """If Redis says 'dead' but Celery state is live, the response must show 'running'."""
    client, app_module, redis, _, _ = flask_test_client
    redis.zadd("dlc_train_jobs", {"tL": 12345.0})
    redis.hset("dlc_train_job:tL", mapping={
        "task_id": "tL", "status": "dead", "engine": "pytorch",
        "project": "TestProj", "gpu_id": "0", "started_at": "12345.0",
    })
    fake_async = type("FA", (), {"state": "PROGRESS"})
    with patch("dlc.monitoring.AsyncResult", return_value=fake_async):
        res = client.get("/dlc/training/jobs")
    assert res.status_code == 200
    jobs = res.get_json()["jobs"]
    target = next((j for j in jobs if j.get("task_id") == "tL"), None)
    assert target is not None, jobs
    assert target["status"] == "running"


def test_jobs_endpoint_running_when_celery_terminal_marks_dead(flask_test_client):
    """The pre-existing direction is preserved: running → dead when Celery is gone."""
    client, _, redis, _, _ = flask_test_client
    redis.zadd("dlc_train_jobs", {"tD": 99999.0})
    redis.hset("dlc_train_job:tD", mapping={
        "task_id": "tD", "status": "running", "engine": "pytorch",
        "project": "TestProj", "gpu_id": "0", "started_at": "99999.0",
    })
    fake_async = type("FA", (), {"state": "SUCCESS"})  # not in _LIVE_CELERY_STATES
    with patch("dlc.monitoring.AsyncResult", return_value=fake_async):
        res = client.get("/dlc/training/jobs")
    target = next((j for j in res.get_json()["jobs"] if j.get("task_id") == "tD"), None)
    assert target is not None
    assert target["status"] == "dead"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_jobs_page_endpoints.py::test_jobs_endpoint_force_running_when_celery_live -v
```

Expected: FAIL — assertion `target["status"] == "running"` fails because the function still returns `dead`.

- [ ] **Step 3: Patch `_reconcile()`**

Edit `src/dlc/monitoring.py`. Find `_reconcile()` (around line 239) and add the inverse branch. The before:

```python
    def _reconcile(redis_key: str, jid: str) -> dict | None:
        job = _ctx.redis_client().hgetall(redis_key)
        if not job:
            return None
        if job.get("status") == "running":
            celery_state = AsyncResult(jid, app=_ctx.celery()).state
            if celery_state not in _LIVE_CELERY_STATES:
                _ctx.redis_client().hset(redis_key, "status", "dead")
                job["status"] = "dead"
        return job
```

After:

```python
    def _reconcile(redis_key: str, jid: str) -> dict | None:
        job = _ctx.redis_client().hgetall(redis_key)
        if not job:
            return None
        celery_state = AsyncResult(jid, app=_ctx.celery()).state
        if job.get("status") == "running" and celery_state not in _LIVE_CELERY_STATES:
            _ctx.redis_client().hset(redis_key, "status", "dead")
            job["status"] = "dead"
        elif (
            job.get("status") in ("dead", "stopped")
            and celery_state in _LIVE_CELERY_STATES
        ):
            # Reaper false-positive: Celery still considers the task running.
            # Trust the live Celery state and flip the Redis flag back.
            _ctx.redis_client().hset(redis_key, "status", "running")
            job["status"] = "running"
        return job
```

- [ ] **Step 4: Run tests**

```bash
docker compose restart flask
sleep 5
pytest tests/test_jobs_page_endpoints.py -v -k "reconciliation or running"
```

Expected: 2 passed (the new force-running test + the preserved running-to-dead test).

- [ ] **Step 5: Commit**

```bash
git add src/dlc/monitoring.py tests/test_jobs_page_endpoints.py
git commit -m "$(cat <<'EOF'
fix(jobs): reconcile dead→running when Celery state is live

The Reaper occasionally marks a still-running task 'dead' (e.g.
when its PID lookup races with the worker_process_init cleanup,
or when the PID happens to be unreachable from the polling thread).
The /dlc/training/jobs endpoint already flips 'running'→'dead' when
Celery says the task is gone; mirror the inverse so a Reaper
false-positive doesn't permanently mis-display a live task.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Cross-session listing + terminate tests

Prove the existing list/stop endpoints don't leak any session/uid state. These tests don't change behavior — they pin it.

**Files:**
- Test: append to `tests/test_jobs_page_endpoints.py`

- [ ] **Step 1: Write the tests**

Append to `tests/test_jobs_page_endpoints.py`:

```python
# ── Cross-session correctness pins ───────────────────────────────────────────

def test_jobs_endpoint_no_uid_in_payload(flask_test_client):
    """The wire format must not leak any session/uid identifiers."""
    client, _, redis, _, _ = flask_test_client
    redis.zadd("dlc_train_jobs", {"tA": 1.0})
    redis.hset("dlc_train_job:tA", mapping={
        "task_id": "tA", "status": "running", "engine": "pytorch",
        "project": "P", "gpu_id": "0", "started_at": "1.0",
    })
    fake_async = type("FA", (), {"state": "PROGRESS"})
    with patch("dlc.monitoring.AsyncResult", return_value=fake_async):
        res = client.get("/dlc/training/jobs")
    body = res.get_data(as_text=True)
    for forbidden in ("uid", '"user"', '"session"', "webapp:"):
        assert forbidden not in body, f"{forbidden!r} leaked into response: {body[:300]}"


def test_jobs_endpoint_lists_jobs_across_sessions(flask_test_client):
    """A task seeded in 'session A's redis must appear when 'session B' fetches the list.

    Sessions are simulated by clearing Flask cookies between requests; the underlying
    Redis state is shared (which is the whole point of the design)."""
    client, _, redis, _, _ = flask_test_client
    redis.zadd("dlc_train_jobs", {"tCross": 1.0})
    redis.hset("dlc_train_job:tCross", mapping={
        "task_id": "tCross", "status": "running", "engine": "pytorch",
        "project": "Pcross", "gpu_id": "0", "started_at": "1.0",
    })
    fake_async = type("FA", (), {"state": "PROGRESS"})

    # Simulate 'session B' by clearing all cookies on the test client.
    client.delete_cookie("session")
    with patch("dlc.monitoring.AsyncResult", return_value=fake_async):
        res = client.get("/dlc/training/jobs")
    assert res.status_code == 200
    ids = [j.get("task_id") for j in res.get_json()["jobs"]]
    assert "tCross" in ids


def test_terminate_endpoint_works_without_session_state(flask_test_client):
    """POST /dlc/task/<id>/terminate must not 500 on a missing PID — should return 404
    or 200 with a plain 'task not found' / 'stopped' body."""
    client, _, redis, _, _ = flask_test_client
    # Seed a finished job (no PID key) — drives the "Path B" cleanup
    redis.zadd("dlc_train_jobs", {"tNoPid": 1.0})
    redis.hset("dlc_train_job:tNoPid", mapping={
        "task_id": "tNoPid", "status": "running", "engine": "pytorch",
        "project": "P", "gpu_id": "0", "started_at": "1.0",
    })
    res = client.post("/dlc/task/tNoPid/terminate")
    assert res.status_code in (200, 404), res.get_data(as_text=True)
    assert res.get_json() is not None  # JSON body, not HTML traceback
```

- [ ] **Step 2: Run them**

```bash
pytest tests/test_jobs_page_endpoints.py -v -k "cross or no_uid or without_session"
```

Expected: 3 passed (these test existing behavior; should pass without code changes).

If a test fails, the existing endpoint has a session leak that must be fixed BEFORE marking this task done — that fix becomes a sub-step here, not a follow-up.

- [ ] **Step 3: Commit**

```bash
git add tests/test_jobs_page_endpoints.py
git commit -m "$(cat <<'EOF'
test(jobs): pin cross-session listing/stop correctness

These tests don't add behavior — they assert the existing
/dlc/training/jobs and /dlc/task/<id>/terminate endpoints don't
leak any session/uid state. Future regressions that introduce a
session check would now break the test suite loudly.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `/jobs` route + minimal `jobs.html`

Renders an empty-but-valid page so the next task (Jobs nav button) has a destination. JS/CSS files are wired in but their contents land in later tasks.

**Files:**
- Create: `src/templates/jobs.html`
- Modify: `src/app.py` — add the route
- Test: `tests/test_jobs_page_render.py` (new)

- [ ] **Step 1: Write the render test**

Create `tests/test_jobs_page_render.py`:

```python
"""Tests for the /jobs page render + nav button + auth gate."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_jobs_page_renders_when_authenticated(flask_test_client):
    client, _, _, _, _ = flask_test_client
    # Authenticate by token (mirrors the existing _require_auth handler)
    client.get("/?token=" + _get_token())
    res = client.get("/jobs")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert 'id="jobs-rail"' in body
    assert 'id="jobs-detail"' in body
    assert "/static/js/jobs.js" in body


def test_jobs_page_redirects_to_login_when_unauth(flask_test_client):
    client, _, _, _, _ = flask_test_client
    res = client.get("/jobs")
    assert res.status_code in (302, 401)


def _get_token():
    """The conftest fixture sets the app token via env var or generates one;
    check the running app instance for it."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    import app as flask_app_module
    return flask_app_module._APP_TOKEN
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_jobs_page_render.py::test_jobs_page_renders_when_authenticated -v
```

Expected: FAIL — `404 NOT FOUND` (route not registered).

- [ ] **Step 3: Implement the route**

Edit `src/app.py`. Find the section near line 198-200 where blueprints are registered, then look for an existing `@app.route` (e.g. the index `/`) — there are several. After all the existing top-level routes (use grep `grep -n "@app.route" src/app.py` to find the right cluster), add:

```python
@app.route("/jobs")
def jobs_page():
    """Session-independent monitor for DLC train/analyze tasks.

    Reads from global Redis state (dlc_train_jobs zset, dlc_task:<id>:log
    list). Works in any browser session — JS does not retain task_ids
    across page loads.
    """
    return render_template("jobs.html")
```

- [ ] **Step 4: Implement the template**

Create `src/templates/jobs.html`:

```html
{% extends "base.html" %}

{% block title %}Jobs{% endblock %}

{% block extra_head %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/jobs.css') }}">
{% endblock %}

{% block content %}
  <main class="jobs-page">
    <header class="jobs-header">
      <h2>Jobs</h2>
      <span id="jobs-status-pill" class="jobs-status-pill"></span>
    </header>
    <div class="jobs-layout">
      <aside id="jobs-rail" class="jobs-rail">
        <p class="jobs-empty">Loading…</p>
      </aside>
      <section id="jobs-detail" class="jobs-detail">
        <p class="jobs-empty">Select a job to see its log.</p>
      </section>
    </div>
  </main>
{% endblock %}

{% block scripts %}
{{ super() }}
<script type="module" src="{{ url_for('static', filename='js/jobs.js') }}"></script>
{% endblock %}
```

- [ ] **Step 5: Run tests**

```bash
docker compose restart flask
sleep 5
pytest tests/test_jobs_page_render.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/app.py src/templates/jobs.html tests/test_jobs_page_render.py
git commit -m "$(cat <<'EOF'
feat(jobs): /jobs route and skeleton template

Renders an empty page with rail (#jobs-rail) and detail
(#jobs-detail) containers, plus the script tag for jobs.js.
Subject to the existing _require_auth handler, so unauth'd
requests redirect to login.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: "Jobs" nav button in `base.html`

Adds the entry point users will actually click. Sits next to the existing "3D Extractor" anchor.

**Files:**
- Modify: `src/templates/base.html` — one new `<a>` element
- Test: append to `tests/test_jobs_page_render.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_jobs_page_render.py`:

```python
def test_nav_button_appears_on_base_template(flask_test_client):
    client, _, _, _, _ = flask_test_client
    client.get("/?token=" + _get_token())  # auth
    res = client.get("/")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert 'href="/jobs"' in body
    assert ">Jobs<" in body  # visible label text
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_jobs_page_render.py::test_nav_button_appears_on_base_template -v
```

Expected: FAIL.

- [ ] **Step 3: Edit `src/templates/base.html`**

Find the existing `3D Extractor` anchor (use `grep -n "3D Extractor" src/templates/base.html` — it's around line 44). The full existing line:

```html
<a href="/dlc-3d/" style="font-size:.78rem;color:var(--text-dim);text-decoration:none;padding:.2rem .55rem;border-radius:5px;border:1px solid transparent;transition:all .15s" onmouseover="this.style.borderColor='var(--border)';this.style.color='var(--text)'" onmouseout="this.style.borderColor='transparent';this.style.color='var(--text-dim)'">3D Extractor</a>
```

Insert immediately AFTER it (same line styling so they look consistent):

```html
<a href="/jobs" style="font-size:.78rem;color:var(--text-dim);text-decoration:none;padding:.2rem .55rem;border-radius:5px;border:1px solid transparent;transition:all .15s" onmouseover="this.style.borderColor='var(--border)';this.style.color='var(--text)'" onmouseout="this.style.borderColor='transparent';this.style.color='var(--text-dim)'">Jobs</a>
```

- [ ] **Step 4: Run test**

```bash
docker compose restart flask
sleep 5
pytest tests/test_jobs_page_render.py::test_nav_button_appears_on_base_template -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/templates/base.html tests/test_jobs_page_render.py
git commit -m "$(cat <<'EOF'
feat(jobs): add 'Jobs' nav button next to '3D Extractor'

Same hover/text-color/border styling as the 3D Extractor anchor
already uses, so the two read as a consistent pair in the header.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `jobs.css` — page styling

Static styling, no JS interactions yet. Keeps the page legible while the JS lands incrementally.

**Files:**
- Create: `src/static/css/jobs.css`

- [ ] **Step 1: Create the file**

Create `src/static/css/jobs.css`:

```css
/* /jobs — list rail + detail pane + terminal log viewer */

.jobs-page {
  padding: 1.2rem 1.4rem;
  max-width: 1400px;
  width: 100%;
  margin: 0 auto;
  height: calc(100vh - 5rem);
  display: flex;
  flex-direction: column;
}

.jobs-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 0.8rem;
}

.jobs-header h2 {
  margin: 0;
  font-size: 1.1rem;
}

.jobs-status-pill {
  font-size: .72rem;
  color: var(--text-dim);
  padding: .15rem .55rem;
  border-radius: 999px;
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.jobs-status-pill.live  { color: #3fb950; border-color: #3fb950; }
.jobs-status-pill.paused { color: #d29922; border-color: #d29922; }
.jobs-status-pill.closed { color: var(--text-dim); }
.jobs-status-pill.error  { color: #f85149; border-color: #f85149; }

.jobs-layout {
  display: flex;
  gap: 1rem;
  flex: 1;
  min-height: 0;
}

.jobs-rail {
  width: 18rem;
  flex-shrink: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 7px;
  overflow-y: auto;
}

.jobs-row {
  padding: .55rem .75rem;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: .15rem;
  transition: background .12s;
}
.jobs-row:hover    { background: var(--surface-2); }
.jobs-row.selected { background: var(--surface-2); border-left: 2px solid var(--accent); padding-left: calc(.75rem - 2px); }

.jobs-row-top {
  display: flex;
  align-items: center;
  gap: .35rem;
  font-family: var(--mono);
  font-size: .76rem;
}
.jobs-row-id        { color: var(--text); }
.jobs-row-op        { color: var(--text-dim); }
.jobs-row-status    { margin-left: auto; font-size: .8rem; }

.jobs-row-meta {
  font-size: .68rem;
  color: var(--text-dim);
  display: flex;
  gap: .55rem;
  flex-wrap: wrap;
}

.jobs-empty {
  padding: 1rem .9rem;
  font-size: .78rem;
  color: var(--text-dim);
  text-align: center;
}

.jobs-detail {
  flex: 1;
  min-width: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 7px;
  padding: .9rem 1rem;
  display: flex;
  flex-direction: column;
}

.jobs-detail-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: .8rem;
  flex-wrap: wrap;
}
.jobs-detail-header h3 {
  margin: 0;
  font-family: var(--mono);
  font-size: .9rem;
}
.jobs-detail-meta {
  font-size: .73rem;
  color: var(--text-dim);
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
}
.jobs-detail-meta span { white-space: nowrap; }

.jobs-stop-btn {
  margin-left: auto;
  padding: .35rem .9rem;
  font-size: .78rem;
  background: #f85149;
  color: #fff;
  border: 1px solid #f85149;
  border-radius: 5px;
  cursor: pointer;
}
.jobs-stop-btn:hover    { background: #da3633; }
.jobs-stop-btn:disabled { opacity: .5; cursor: not-allowed; }

.jobs-terminal {
  flex: 1;
  min-height: 0;
  font-family: var(--mono);
  font-size: .76rem;
  background: #0d1117;
  color: #c9d1d9;
  padding: .65rem .8rem;
  border: 1px solid var(--border);
  border-radius: 5px;
  overflow-y: auto;
  white-space: pre-wrap;
  line-height: 1.45;
}

.jobs-reconnect-btn {
  align-self: flex-start;
  margin-top: .55rem;
  padding: .3rem .8rem;
  font-size: .78rem;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 5px;
  cursor: pointer;
}
```

- [ ] **Step 2: Verify CSS loads**

```bash
docker compose restart flask
sleep 5
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:5000/static/css/jobs.css"
```

Expected: `200`.

- [ ] **Step 3: Commit**

```bash
git add src/static/css/jobs.css
git commit -m "$(cat <<'EOF'
feat(jobs): jobs.css — rail + detail + terminal styling

List rail on the left (18rem fixed), detail pane fills remaining
width, terminal-style log viewer (#0d1117 / #c9d1d9, monospace)
inside the detail pane. Status pill colors green/yellow/red
following the existing app palette.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `jobs.js` — list polling + rail rendering

The first slice of the JS module: render the rail from `/dlc/training/jobs` and re-poll every 3 seconds. No log streaming yet (Task 9).

**Files:**
- Create: `src/static/js/jobs.js`

- [ ] **Step 1: Implement the file**

Create `src/static/js/jobs.js`:

```javascript
"use strict";

// ─── jobs.js — session-independent monitor for DLC train/analyze tasks ───
//
// Reads list state from /dlc/training/jobs (global Redis-backed) every 3s
// when the tab is visible. Selecting a job opens a backfill+SSE stream to
// /dlc/task/<id>/log-stream (added in Task 9). Stop button calls
// /dlc/task/<id>/terminate (added in Task 11). Visibility + 20-min
// idle timeout govern the SSE lifecycle (added in Task 10).

const State = {
  selectedTaskId: null,
  eventSource:    null,
  listPollTimer:  null,
  idleTimer:      null,
  jobs:           [],   // last-rendered list (for Stop confirmation)
};

const POLL_MS = 3000;

// ─── Rail rendering ──────────────────────────────────────────────────────
function _statusGlyph(status) {
  return ({
    running:  "●",
    paused:   "⏸",
    complete: "✓",
    failed:   "✗",
    dead:     "⚠",
    stopped:  "■",
    stopping: "■",
  })[status] || "·";
}

function _statusColor(status) {
  return ({
    running:  "var(--accent)",
    paused:   "#d29922",
    complete: "#3fb950",
    failed:   "#f85149",
    dead:     "#f85149",
    stopped:  "var(--text-dim)",
    stopping: "var(--text-dim)",
  })[status] || "var(--text-dim)";
}

function _formatRuntime(startedAt) {
  if (!startedAt) return "";
  const elapsed = Date.now() / 1000 - parseFloat(startedAt);
  if (elapsed < 60)   return `${Math.round(elapsed)}s`;
  if (elapsed < 3600) return `${Math.floor(elapsed / 60)}m`;
  const h = Math.floor(elapsed / 3600);
  const m = Math.floor((elapsed - h * 3600) / 60);
  return `${h}h ${m}m`;
}

function _renderRail(jobs) {
  const rail = document.getElementById("jobs-rail");
  if (!rail) return;
  if (!jobs.length) {
    rail.innerHTML = '<p class="jobs-empty">No jobs running.</p>';
    return;
  }
  rail.innerHTML = jobs.map(j => {
    const id = j.task_id || "";
    const op = j.operation || "train";
    const status = j.status || "";
    const isSel = id === State.selectedTaskId ? "selected" : "";
    return `
      <div class="jobs-row ${isSel}" data-task-id="${id}" data-status="${status}">
        <div class="jobs-row-top">
          <span class="jobs-row-op">${op}</span>
          <span class="jobs-row-id">${id.slice(0, 8)}</span>
          <span class="jobs-row-status" style="color:${_statusColor(status)}">${_statusGlyph(status)} ${status}</span>
        </div>
        <div class="jobs-row-meta">
          <span>${j.project || ""}</span>
          <span>GPU${j.gpu_id || "?"}</span>
          <span>${_formatRuntime(j.started_at)}</span>
        </div>
      </div>`;
  }).join("");
  rail.querySelectorAll(".jobs-row").forEach(row => {
    row.addEventListener("click", () => _onRowClick(row.dataset.taskId));
  });
}

async function _fetchJobs() {
  try {
    const res = await fetch("/dlc/training/jobs");
    if (!res.ok) return;
    const data = await res.json();
    State.jobs = data.jobs || [];
    _renderRail(State.jobs);
  } catch (err) {
    console.error("[jobs] _fetchJobs failed:", err);
  }
}

function _startListPoll() {
  if (State.listPollTimer) clearInterval(State.listPollTimer);
  _fetchJobs();
  State.listPollTimer = setInterval(_fetchJobs, POLL_MS);
}

function _stopListPoll() {
  if (State.listPollTimer) {
    clearInterval(State.listPollTimer);
    State.listPollTimer = null;
  }
}

// ─── Row click — placeholder; real impl lands in Task 9 ─────────────────
function _onRowClick(taskId) {
  State.selectedTaskId = taskId;
  _renderRail(State.jobs);
  // Detail pane wiring lands in Task 9
  const detail = document.getElementById("jobs-detail");
  if (detail) detail.innerHTML = `<p class="jobs-empty">Selected ${taskId} — log streaming lands in Task 9.</p>`;
}

// ─── Bootstrap ──────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  _startListPoll();
});

// Test seam — exposed for cross-session E2E tests to wait on the first poll.
window.__jobsState = State;
```

- [ ] **Step 2: Smoke-test by hand (no automated test for the visual list yet — Task 13's Playwright test will cover it)**

```bash
docker compose restart flask
sleep 5
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:5000/static/js/jobs.js"
```

Expected: `200`.

Then visit `http://localhost:5000/jobs` in a browser (after authenticating once via `?token=<APP_TOKEN>`). The list rail should populate within 3 s with whatever's in `dlc_train_jobs` / `dlc_analyze_jobs` (currently includes the running training).

- [ ] **Step 3: Commit**

```bash
git add src/static/js/jobs.js
git commit -m "$(cat <<'EOF'
feat(jobs): jobs.js list polling + rail render

Polls /dlc/training/jobs every 3 s, renders one row per job in
the left rail with task-id, operation, project, GPU, runtime,
and a colored status glyph. Click handler is a placeholder; real
SSE log streaming lands in the next task.

window.__jobsState exposed as a test seam for the Playwright
cross-session E2E.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `jobs.js` — row click → log-tail backfill + SSE stream

Wires the detail pane: click a job → fetch the last 2000 log lines via the new `log-tail` endpoint, paint into the terminal, then open an EventSource to `/dlc/task/<id>/log-stream` and append each frame.

**Files:**
- Modify: `src/static/js/jobs.js` — replace `_onRowClick` and add detail-render helpers

- [ ] **Step 1: Replace `_onRowClick` and add the log-detail helpers**

Open `src/static/js/jobs.js`. Replace the placeholder `_onRowClick` plus the section it lives in. Specifically, BEFORE the `// ─── Bootstrap ───` line, ensure the file has:

```javascript
// ─── Detail pane: backfill + SSE stream ─────────────────────────────────
function _setStatusPill(text, cls) {
  const pill = document.getElementById("jobs-status-pill");
  if (!pill) return;
  pill.textContent = text;
  pill.className = "jobs-status-pill " + (cls || "");
}

function _renderDetailHeader(job) {
  const status = job.status || "";
  const showStop = status === "running" || status === "paused";
  const startedTxt = job.started_at
    ? new Date(parseFloat(job.started_at) * 1000).toLocaleTimeString()
    : "?";
  return `
    <div class="jobs-detail-header">
      <h3>${(job.operation || "train")} ${job.task_id || ""}</h3>
      <div class="jobs-detail-meta">
        <span>project: ${job.project || "?"}</span>
        <span>engine: ${job.engine || "?"}</span>
        <span>GPU${job.gpu_id || "?"}</span>
        <span>started: ${startedTxt}</span>
        <span>status: ${status}</span>
      </div>
      ${showStop ? `<button class="jobs-stop-btn" data-action="stop">Stop</button>` : ""}
    </div>
    <pre id="jobs-terminal" class="jobs-terminal"></pre>
  `;
}

async function _backfillLog(taskId, terminalEl) {
  try {
    const res = await fetch(`/dlc/task/${taskId}/log-tail?n=2000`);
    if (!res.ok) return;
    const data = await res.json();
    const lines = (data.lines || []).join("\n");
    terminalEl.textContent = lines + (lines ? "\n" : "");
    terminalEl.scrollTop = terminalEl.scrollHeight;
  } catch (err) {
    console.error("[jobs] backfill failed:", err);
  }
}

function _isAtBottom(el) {
  return Math.abs(el.scrollHeight - el.clientHeight - el.scrollTop) < 6;
}

function _openStream(taskId, terminalEl) {
  if (State.eventSource) { State.eventSource.close(); State.eventSource = null; }
  const es = new EventSource(`/dlc/task/${taskId}/log-stream`);
  es.addEventListener("message", (ev) => {
    if (taskId !== State.selectedTaskId) return;  // raced past selection change
    const wasBottom = _isAtBottom(terminalEl);
    terminalEl.textContent += ev.data + "\n";
    if (wasBottom) terminalEl.scrollTop = terminalEl.scrollHeight;
  });
  es.addEventListener("error", () => {
    _setStatusPill("disconnected (server unreachable)", "error");
  });
  State.eventSource = es;
  _setStatusPill("live · streaming", "live");
}

async function _showJob(taskId) {
  State.selectedTaskId = taskId;
  _renderRail(State.jobs);
  const detail = document.getElementById("jobs-detail");
  if (!detail) return;
  const job = State.jobs.find(j => j.task_id === taskId) || { task_id: taskId };
  detail.innerHTML = _renderDetailHeader(job);
  const terminal = detail.querySelector("#jobs-terminal");
  await _backfillLog(taskId, terminal);
  _openStream(taskId, terminal);
}

// Replace the placeholder _onRowClick with one that wires _showJob:
function _onRowClick(taskId) {
  if (!taskId || taskId === State.selectedTaskId) return;
  _showJob(taskId).catch(err => console.error("[jobs] _showJob:", err));
}
```

Make sure to remove the old placeholder `_onRowClick` definition above the `Bootstrap` section so there's only one.

- [ ] **Step 2: Manual smoke**

```bash
docker compose restart flask
sleep 5
```

In a browser at `/jobs`: click the running training row. The terminal pane should populate with the recent epochs (backfill) and continue streaming live as new epochs land.

- [ ] **Step 3: Commit**

```bash
git add src/static/js/jobs.js
git commit -m "$(cat <<'EOF'
feat(jobs): row-click → log-tail backfill + SSE stream

Click a job row → fetch last 2000 lines from /dlc/task/<id>/log-tail,
paint into the terminal, then open EventSource to /log-stream and
append each frame. Auto-scroll only when already at bottom (so the
user can read history without being yanked back). Detail pane shows
the standard meta + a Stop button when status is running/paused
(button wiring lands in Task 11).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `jobs.js` — visibility + 20-min idle timeout

Pause SSE + list-poll on `visibilitychange=hidden`; resume on visible if within 20 min; close + show Reconnect button if 20 min elapses. Tests for this go through the Playwright E2E in Task 15.

**Files:**
- Modify: `src/static/js/jobs.js`

- [ ] **Step 1: Add the visibility lifecycle**

Append to `src/static/js/jobs.js`, BEFORE the bootstrap block (`document.addEventListener("DOMContentLoaded", …)`):

```javascript
// ─── Visibility + 20-min idle timeout ───────────────────────────────────
const IDLE_MS_DEFAULT = 20 * 60 * 1000;

function _idleMs() {
  // Test seam: ?_test_idle_ms=500 lets E2E tests force a fast timeout.
  // Honored only when the URL is on localhost (defensive against accidental
  // exposure in production).
  if (location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
    return IDLE_MS_DEFAULT;
  }
  const v = parseInt(new URLSearchParams(location.search).get("_test_idle_ms"), 10);
  return Number.isFinite(v) && v > 0 ? v : IDLE_MS_DEFAULT;
}

function _showReconnectButton() {
  const detail = document.getElementById("jobs-detail");
  if (!detail) return;
  if (detail.querySelector(".jobs-reconnect-btn")) return;  // already shown
  const btn = document.createElement("button");
  btn.className = "jobs-reconnect-btn";
  btn.textContent = "Reconnect";
  btn.addEventListener("click", () => {
    btn.remove();
    if (State.selectedTaskId) _showJob(State.selectedTaskId);
    _startListPoll();
  });
  detail.appendChild(btn);
}

function _onHidden() {
  if (State.eventSource) { State.eventSource.close(); State.eventSource = null; }
  _stopListPoll();
  _setStatusPill("paused (tab hidden)", "paused");
  if (State.idleTimer) clearTimeout(State.idleTimer);
  State.idleTimer = setTimeout(() => {
    State.idleTimer = null;
    _setStatusPill("closed (idle 20m — Reconnect)", "closed");
    _showReconnectButton();
  }, _idleMs());
}

function _onVisible() {
  if (State.idleTimer) { clearTimeout(State.idleTimer); State.idleTimer = null; }
  // Don't auto-resume if the idle timer already fired and the user hasn't clicked Reconnect.
  const detail = document.getElementById("jobs-detail");
  if (detail && detail.querySelector(".jobs-reconnect-btn")) return;
  _startListPoll();
  if (State.selectedTaskId) {
    const term = document.querySelector("#jobs-terminal");
    if (term) {
      _backfillLog(State.selectedTaskId, term).then(() => {
        _openStream(State.selectedTaskId, term);
      });
    }
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) _onHidden();
  else                  _onVisible();
});
```

- [ ] **Step 2: Manual smoke**

```bash
docker compose restart flask
sleep 5
```

In a browser at `/jobs`:
1. Select a running job, see live streaming.
2. Switch to another tab — return after a few seconds — verify the stream continues without losing history.
3. Open `/jobs?_test_idle_ms=2000`, switch tabs, wait 3 seconds, return — header pill shows `closed (idle 20m — Reconnect)` and a Reconnect button appears below the terminal. Click it — stream resumes.

- [ ] **Step 3: Commit**

```bash
git add src/static/js/jobs.js
git commit -m "$(cat <<'EOF'
feat(jobs): visibility + 20-min idle timeout

Tab hidden → close EventSource, stop list poll, header pill
'paused (tab hidden)'. Visible again within 20 min → reopen and
re-tail. 20 min hidden → close everything, show Reconnect button.
Test seam: ?_test_idle_ms=N (localhost only) overrides the timeout
for the Playwright E2E.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: `jobs.js` — Stop button + confirmation

The Stop button HTML already renders in Task 9 (when `status` is running/paused). This task wires its click handler.

**Files:**
- Modify: `src/static/js/jobs.js` — add the click handler in `_renderDetailHeader` chain

- [ ] **Step 1: Add the handler**

In `src/static/js/jobs.js`, find the `_showJob` function. After `_openStream(taskId, terminal);` add:

```javascript
  const stopBtn = detail.querySelector('button[data-action="stop"]');
  if (stopBtn) {
    stopBtn.addEventListener("click", async () => {
      const ok = window.confirm(`Stop ${job.operation || "task"} ${taskId}?\n\nThis cannot be undone.`);
      if (!ok) return;
      stopBtn.disabled = true;
      try {
        const res = await fetch(`/dlc/task/${taskId}/terminate`, { method: "POST" });
        if (!res.ok) {
          const errText = await res.text();
          alert(`Stop failed: ${errText}`);
          stopBtn.disabled = false;
          return;
        }
        // Status flip surfaces on the next list poll (within ~3s).
      } catch (err) {
        alert(`Stop failed: ${err.message}`);
        stopBtn.disabled = false;
      }
    });
  }
```

- [ ] **Step 2: Manual smoke**

DO NOT actually click Stop on the currently-running training. Smoke is by visual inspection only at this point — confirm the Stop button appears and is clickable on a running job. Real validation comes from the Playwright tests in Task 13.

- [ ] **Step 3: Commit**

```bash
git add src/static/js/jobs.js
git commit -m "$(cat <<'EOF'
feat(jobs): Stop button confirmation + terminate POST

Single-confirm dialog ("Stop … This cannot be undone.") then POST
to /dlc/task/<id>/terminate. Disables the button on click; on
non-2xx response, surfaces the server error text and re-enables.
Status flip surfaces on the next list poll.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Playwright cross-session test infrastructure

Add a Redis-seeded helper + the bare-bones test file. Tests themselves come in Task 13. Skipping if the Playwright stack isn't available in the test environment.

**Files:**
- Create: `tests/e2e_jobs_cross_session.py`
- Modify: `tests/conftest.py` — add a `live_redis` fixture (real connection, scoped per-test)

- [ ] **Step 1: Create the e2e test file with the helper + skeleton**

Create `tests/e2e_jobs_cross_session.py`:

```python
"""Playwright cross-session E2E tests for the /jobs page.

These tests use TWO independent browser contexts to simulate "a different
browser session entirely" and assert that a job seeded in Redis from the
test process is visible / stoppable from any context.

Skipped if Playwright isn't installed or the live stack isn't reachable.
"""
from __future__ import annotations

import os
import time

import pytest
import redis as _redis_mod

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:5000")
APP_TOKEN = os.environ.get("APP_TOKEN", "deeplabcut")


@pytest.fixture(scope="session")
def live_redis():
    """A real Redis connection — required because the SSE log-stream and
    /dlc/training/jobs both read live Redis state in the running flask
    container. Skips the test session if Redis isn't reachable."""
    url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    r = _redis_mod.Redis.from_url(url, decode_responses=True)
    try:
        r.ping()
    except _redis_mod.ConnectionError:
        pytest.skip(f"Redis not reachable at {url}")
    yield r


def seed_test_job(r, task_id: str, *, op: str = "train",
                  status: str = "running", project: str = "test-project",
                  gpu_id: str = "0") -> None:
    """Mirror the shape that worker emit_loop writes for train/analyze."""
    zset = "dlc_train_jobs" if op == "train" else "dlc_analyze_jobs"
    job_pfx = "dlc_train_job:" if op == "train" else "dlc_analyze_job:"
    r.zadd(zset, {task_id: time.time()})
    r.hset(job_pfx + task_id, mapping={
        "task_id":    task_id,
        "operation":  op,
        "status":     status,
        "engine":     "pytorch",
        "project":    project,
        "gpu_id":     gpu_id,
        "started_at": str(time.time()),
        "config_path": "/test/config.yaml",
        "log_path":    "/tmp/e2e_test.log",
    })


def cleanup_test_job(r, task_id: str, op: str = "train") -> None:
    zset = "dlc_train_jobs" if op == "train" else "dlc_analyze_jobs"
    job_pfx = "dlc_train_job:" if op == "train" else "dlc_analyze_job:"
    r.zrem(zset, task_id)
    r.delete(job_pfx + task_id)
    r.delete(f"dlc_task:{task_id}:log")


def _new_authenticated_context(p, base_url: str, token: str):
    browser = p.chromium.launch()
    ctx = browser.new_context()
    page = ctx.new_page()
    # Authenticate once; cookie persists in this context only.
    page.goto(f"{base_url}/?token={token}", wait_until="domcontentloaded")
    return browser, ctx, page
```

- [ ] **Step 2: Run the file (no real tests yet, but ensures the helper imports)**

```bash
pytest tests/e2e_jobs_cross_session.py -v
```

Expected: `no tests ran` or `collected 0 items`. Should not error.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e_jobs_cross_session.py
git commit -m "$(cat <<'EOF'
test(jobs): scaffold for Playwright cross-session E2E

Adds the seed_test_job / cleanup_test_job helpers and a
live_redis fixture (skips if Redis unreachable). Real test cases
land in the next task.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Playwright cross-session tests — listing + stop + log

The headline tests. Each uses two independent browser contexts to prove the page works regardless of which session created the task.

**Files:**
- Modify: `tests/e2e_jobs_cross_session.py` — append the test functions

- [ ] **Step 1: Append the cross-session tests**

Append to `tests/e2e_jobs_cross_session.py`:

```python
def test_job_visible_from_session_that_did_not_start_it(live_redis):
    seed_test_job(live_redis, "tCROSS-1", project="cross-test-1")
    try:
        with sync_playwright() as p:
            # Session A — the "originating" session. Authenticates but never visits /jobs.
            br_a, ctx_a, page_a = _new_authenticated_context(p, BASE_URL, APP_TOKEN)
            # Session B — completely separate context. Visits /jobs.
            br_b, ctx_b, page_b = _new_authenticated_context(p, BASE_URL, APP_TOKEN)
            page_b.goto(f"{BASE_URL}/jobs")
            page_b.wait_for_selector('[data-task-id="tCROSS-1"]', timeout=10000)
            br_a.close(); br_b.close()
    finally:
        cleanup_test_job(live_redis, "tCROSS-1")


def test_log_visible_from_session_that_did_not_start_it(live_redis):
    seed_test_job(live_redis, "tCROSS-2", project="cross-test-2")
    live_redis.rpush("dlc_task:tCROSS-2:log", "Epoch 1/3 ...", "Epoch 2/3 ...", "Epoch 3/3 ...")
    try:
        with sync_playwright() as p:
            br, _, page = _new_authenticated_context(p, BASE_URL, APP_TOKEN)
            page.goto(f"{BASE_URL}/jobs")
            page.wait_for_selector('[data-task-id="tCROSS-2"]', timeout=10000)
            page.click('[data-task-id="tCROSS-2"]')
            page.wait_for_function(
                """() => {
                    const t = document.querySelector('#jobs-terminal');
                    return t && t.textContent.includes('Epoch 3/3');
                }""",
                timeout=10000,
            )
            term_text = page.text_content("#jobs-terminal")
            assert "Epoch 1/3" in term_text
            assert "Epoch 2/3" in term_text
            assert "Epoch 3/3" in term_text
            br.close()
    finally:
        cleanup_test_job(live_redis, "tCROSS-2")
        live_redis.delete("dlc_task:tCROSS-2:log")


def test_stop_works_from_session_that_did_not_start_it(live_redis):
    """Note: terminate on a job with no PID enters Path B (direct cleanup) —
    so it's safe to run against a seeded test job, no real subprocess involved."""
    seed_test_job(live_redis, "tCROSS-3", project="cross-test-3")
    try:
        with sync_playwright() as p:
            br, _, page = _new_authenticated_context(p, BASE_URL, APP_TOKEN)
            page.goto(f"{BASE_URL}/jobs")
            page.wait_for_selector('[data-task-id="tCROSS-3"]', timeout=10000)
            page.click('[data-task-id="tCROSS-3"]')
            page.wait_for_selector('button[data-action="stop"]', timeout=5000)
            # Auto-confirm the dialog
            page.on("dialog", lambda d: d.accept())
            page.click('button[data-action="stop"]')
            # Status flips to 'stopped' on the next list poll cycle
            page.wait_for_function(
                """() => {
                    const row = document.querySelector('[data-task-id="tCROSS-3"]');
                    return row && row.dataset.status === 'stopped';
                }""",
                timeout=10000,
            )
            br.close()
    finally:
        cleanup_test_job(live_redis, "tCROSS-3")
```

- [ ] **Step 2: Run the tests against the live stack**

```bash
docker compose restart flask
sleep 5
cd /home/sam/docker-images/deeplabcut-webapp-docker
APP_TOKEN=deeplabcut pytest tests/e2e_jobs_cross_session.py -v
```

Expected: 3 passed.

If the tests can't reach the live stack, they SKIP gracefully (per the `live_redis` fixture). If they reach Redis but fail, the fixtures also auto-cleanup the seeded keys via the `try/finally` blocks.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e_jobs_cross_session.py
git commit -m "$(cat <<'EOF'
test(jobs): cross-session Playwright E2E

Three headline tests, each using two independent browser
contexts:
  1. Job seeded by 'session A' is visible from 'session B'.
  2. Log lines for that job render in the terminal of session B.
  3. Stop button in session B successfully terminates the seeded
     job (Path B cleanup — no real subprocess involved).

These prove the page is genuinely session-independent — exactly
the user complaint that motivated the redesign.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Playwright visibility + idle-timeout test

Drive the visibility lifecycle and the (forced) 20-min timeout.

**Files:**
- Modify: `tests/e2e_jobs_cross_session.py` — append visibility + idle tests

- [ ] **Step 1: Append the tests**

Append to `tests/e2e_jobs_cross_session.py`:

```python
def test_visibility_pause_resume(live_redis):
    seed_test_job(live_redis, "tVIS", project="visibility-test")
    live_redis.rpush("dlc_task:tVIS:log", "initial line")
    try:
        with sync_playwright() as p:
            br, _, page = _new_authenticated_context(p, BASE_URL, APP_TOKEN)
            page.goto(f"{BASE_URL}/jobs")
            page.wait_for_selector('[data-task-id="tVIS"]', timeout=10000)
            page.click('[data-task-id="tVIS"]')
            page.wait_for_function(
                "() => document.getElementById('jobs-status-pill').textContent.includes('live')",
                timeout=5000,
            )
            # Simulate tab hide → pill flips to paused
            page.evaluate("Object.defineProperty(document, 'hidden', {value: true, configurable: true}); document.dispatchEvent(new Event('visibilitychange'));")
            page.wait_for_function(
                "() => document.getElementById('jobs-status-pill').textContent.includes('paused')",
                timeout=2000,
            )
            # New log line lands while hidden
            live_redis.rpush("dlc_task:tVIS:log", "lined while hidden")
            # Show again → pill back to live, terminal contains the new line
            page.evaluate("Object.defineProperty(document, 'hidden', {value: false, configurable: true}); document.dispatchEvent(new Event('visibilitychange'));")
            page.wait_for_function(
                "() => document.getElementById('jobs-status-pill').textContent.includes('live')",
                timeout=5000,
            )
            page.wait_for_function(
                "() => document.getElementById('jobs-terminal').textContent.includes('lined while hidden')",
                timeout=5000,
            )
            br.close()
    finally:
        cleanup_test_job(live_redis, "tVIS")
        live_redis.delete("dlc_task:tVIS:log")


def test_idle_timeout_shows_reconnect(live_redis):
    seed_test_job(live_redis, "tIDLE", project="idle-test")
    try:
        with sync_playwright() as p:
            br, _, page = _new_authenticated_context(p, BASE_URL, APP_TOKEN)
            # Force a 500ms idle timeout via the test seam
            page.goto(f"{BASE_URL}/jobs?_test_idle_ms=500")
            page.wait_for_selector('[data-task-id="tIDLE"]', timeout=10000)
            page.click('[data-task-id="tIDLE"]')
            # Hide and wait > 500 ms
            page.evaluate("Object.defineProperty(document, 'hidden', {value: true, configurable: true}); document.dispatchEvent(new Event('visibilitychange'));")
            page.wait_for_timeout(900)  # comfortably past the 500ms timeout
            # Reconnect button must appear
            page.wait_for_selector(".jobs-reconnect-btn", timeout=2000)
            # Pill should say 'closed'
            assert "closed" in page.text_content("#jobs-status-pill")
            # Click reconnect → button removed, pill back to 'live'
            page.evaluate("Object.defineProperty(document, 'hidden', {value: false, configurable: true}); document.dispatchEvent(new Event('visibilitychange'));")
            page.click(".jobs-reconnect-btn")
            page.wait_for_function(
                "() => !document.querySelector('.jobs-reconnect-btn')",
                timeout=2000,
            )
            br.close()
    finally:
        cleanup_test_job(live_redis, "tIDLE")
```

- [ ] **Step 2: Run them**

```bash
docker compose restart flask
sleep 5
APP_TOKEN=deeplabcut pytest tests/e2e_jobs_cross_session.py::test_visibility_pause_resume tests/e2e_jobs_cross_session.py::test_idle_timeout_shows_reconnect -v
```

Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e_jobs_cross_session.py
git commit -m "$(cat <<'EOF'
test(jobs): visibility + idle-timeout E2E

Two more Playwright tests:
  - Tab hidden → SSE pauses, pill 'paused'. Visible again →
    re-tail picks up lines pushed while hidden.
  - With ?_test_idle_ms=500, 500ms of hidden time → Reconnect
    button appears and pill says 'closed'. Reconnect click
    re-opens the stream.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Final smoke + spec checklist

End-to-end verification against the live stack. No new code unless something is broken.

**Files:** none new

- [ ] **Step 1: All tests green**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart flask
sleep 5
pytest tests/test_jobs_page_endpoints.py tests/test_jobs_page_render.py tests/test_fake_redis_lrange.py -v
APP_TOKEN=deeplabcut pytest tests/e2e_jobs_cross_session.py -v
```

Expected: all passed (the live-Redis E2E tests skip if Redis is unreachable).

- [ ] **Step 2: Spec checklist walkthrough (manual)**

In a browser at `http://localhost:5000/jobs`:

1. **Page renders.** Title "Jobs", header pill, rail on the left, detail pane on the right.
2. **Currently-running training appears.** It's `5acf20dd-…`. Status now reads `running` (the reconciliation fix flipped it from `dead`). Project: `DREADD-Ali-2026-01-07`. Runtime ticks up every 3 s.
3. **Click the row → terminal pane populates with the latest ~2000 epochs and continues streaming.** Auto-scroll to bottom; manual scroll up holds position.
4. **Cross-session check:** open `/jobs` in a fresh incognito window. Authenticate via `?token=…` once. Same list, same logs.
5. **Tab hide / restore:** switch tabs, return — terminal continues to fill seamlessly. Header pill toggles `live`/`paused`.
6. **Idle timeout (using the test seam):** `/jobs?_test_idle_ms=500`, hide for 1 s — Reconnect button appears.
7. **Stop:** DO NOT actually stop the running real training. Use one of the seeded tests' job IDs OR wait for a different real task. Stop confirmation dialog appears; OK → status flips to `stopped` within 3 s.
8. **Empty state:** If no jobs exist (rare), rail shows `No jobs running`.

- [ ] **Step 3: (Optional) cleanup commit**

If anything cosmetic surfaced during smoke (typo, off-by-one in styling), fix in a single `fix(jobs): …` commit. Otherwise no-op.

- [ ] **Step 4: Final commit (smoke checklist record)**

```bash
git commit --allow-empty -m "$(cat <<'EOF'
chore(jobs): final smoke pass for the /jobs monitor page

All automated tests green (FakeRedis lrange, log-tail, jobs
endpoint + reconciliation, page render + nav button). Playwright
cross-session E2E suite passes against the live stack.

Manual smoke confirmed on the running stack:
  - Currently-running training (5acf20dd-...) shows on the page
    with correct status (running), runtime ticks up.
  - Click row → backfill paints recent epochs; live tail continues.
  - Cross-session: fresh incognito sees the same list / logs / Stop.
  - Visibility lifecycle: pause/resume/idle-timeout all work.

Worker container was NOT restarted at any point during this work.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

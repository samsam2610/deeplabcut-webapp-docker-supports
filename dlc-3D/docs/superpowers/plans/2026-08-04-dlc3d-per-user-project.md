# Per-User Project State in dlc-3D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let several people use `/dlc-3d/` at once without overwriting each other's active project, then raise the module's worker count so they are not serialised behind a single process.

**Architecture:** Delete the `_active_project` module global. The main webapp's proxy stamps `X-DLC-User` on every forwarded request; dlc-3D reads the main webapp's own `webapp:dlc_project:{uid}` Redis key per request. No second store, no sync. Then `-w 1` → `-w 4`, with the per-process video-capture cache divided to match.

**Tech Stack:** Flask, redis-py 5.3.1 (already installed in the container), gunicorn, pytest.

**Spec:** `dlc-3D/docs/superpowers/specs/2026-08-04-dlc3d-per-user-project-design.md`

## Global Constraints

- No `requirements.txt` change and **no image rebuild**. `redis` 5.3.1 is already installed in the `dlc-3d` container; deployment is `docker compose restart dlc-3d`.
- Redis is reached through the module's existing proven pattern — copy `lp_routes.py:78` `_redis_conn()`: `CELERY_RESULT_BACKEND`, default `redis://redis:6379/0`, `socket_timeout=1.0`, returns `None` on any failure.
- The key is the main webapp's own: `webapp:dlc_project:{uid}`. Its value is JSON; the field this module needs is `project_path`. Confirmed live shape: `{"project_path": ..., "project_name": ..., "has_config": true, "config_path": ..., "engine": "pytorch"}`.
- The header is exactly `X-DLC-User`.
- Every failure mode — no header, Redis down, key missing, malformed JSON, missing `project_path` — resolves to "no active project". Never a 500.
- `_active_project` must not survive anywhere as a module global. A test enforces this.
- This change never writes a label and never modifies `labeled-data`.
- dlc-3D must remain unreachable except through the proxy. Do not add a `ports:` mapping for the `dlc-3d` service.

**Running the tests.** `cd dlc-3D && python3 -m pytest tests/<file> -q`.

**Baseline:** `cd dlc-3D && python3 -m pytest tests/ -q --ignore=tests/e2e` has **8 known pre-existing failures** (5 `test_lp_predict_pairing.py`, 2 `test_lp_csv_to_h5.py`, 1 `test_inline_analysis_3d_ui_isolation.py::test_finalize3d_confirms_before_overwrite`). A 9th means you broke something. The run takes about 10 seconds.

---

### Task 1: The proxy names the user

**Files:**
- Modify: `/home/sam/docker-images/deeplabcut-webapp-docker/src/app.py` — `proxy_dlc_3d`, at line 612
- Test: `/home/sam/docker-images/deeplabcut-webapp-docker/tests/test_dlc3d_proxy_user_header.py`

**Interfaces:**
- Consumes: `_user_id()` (`app.py:76`) — the same function backing `_dlc_key()` at `app.py:83`.
- Produces: every request forwarded to dlc-3D carries header `X-DLC-User: <uid>`.

Note this task is in the **main webapp repo**, not the supports repo. Commit there.

- [ ] **Step 1: Write the failing test**

```python
"""The dlc-3d proxy must name the user, or dlc-3D cannot tell two users apart.

dlc-3D has no session of its own: the browser's cookie is for the main webapp.
The uid stamped here is the same one keying webapp:dlc_project:{uid}, so the
header and the key cannot drift.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _captured_headers(monkeypatch, app_module):
    """Call the proxy and return the headers it forwarded."""
    seen = {}

    class _Resp:
        status_code = 200
        headers = {}
        def iter_content(self, chunk_size=8192):
            return iter([b""])

    def _fake_request(**kw):
        seen.update(kw.get("headers") or {})
        return _Resp()

    fake_requests = MagicMock()
    fake_requests.request = _fake_request
    fake_requests.exceptions.ConnectionError = Exception
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    return seen


def test_proxy_stamps_the_user_id(monkeypatch):
    import app as app_module
    seen = _captured_headers(monkeypatch, app_module)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["uid"] = "user-abc"
    client.get("/dlc-3d/labeled-frames?session=s1")
    assert seen.get("X-DLC-User") == "user-abc", (
        "without this header dlc-3D cannot distinguish two users"
    )


def test_two_sessions_get_different_ids(monkeypatch):
    """The whole point: two browsers must not look like one user."""
    import app as app_module
    seen = _captured_headers(monkeypatch, app_module)

    ids = []
    for uid in ("user-one", "user-two"):
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess["uid"] = uid
        client.get("/dlc-3d/")
        ids.append(seen.get("X-DLC-User"))
    assert ids == ["user-one", "user-two"]


def test_header_survives_the_hop_by_hop_filter(monkeypatch):
    """The proxy strips host/content-length/transfer-encoding. X-DLC-User must
    not be caught by that filter."""
    import app as app_module
    seen = _captured_headers(monkeypatch, app_module)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["uid"] = "survivor"
    client.post("/dlc-3d/project", json={"path": "/tmp/x"})
    assert seen.get("X-DLC-User") == "survivor"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python3 -m pytest tests/test_dlc3d_proxy_user_header.py -q`
Expected: FAIL — `assert None == 'user-abc'`

- [ ] **Step 3: Write the implementation**

In `src/app.py`, inside `proxy_dlc_3d`, replace the inline `headers=` argument
with a named dict so the uid can be added:

```python
    url = f"http://dlc-3d:5050/dlc-3d/{path}"
    # dlc-3D has no session of its own — the browser's cookie belongs to this
    # app. Name the user explicitly so dlc-3D can look up THEIR active project
    # instead of keeping one global that users overwrite for each other.
    # Same _user_id() that keys webapp:dlc_project:{uid}, so the two agree.
    fwd_headers = {
        k: v for k, v in request.headers
        if k.lower() not in ("host", "content-length", "transfer-encoding")
    }
    fwd_headers["X-DLC-User"] = _user_id()
    try:
        resp = _req.request(
            method=request.method,
            url=url,
            headers=fwd_headers,
            data=request.get_data(),
            params=request.args,
            stream=True,
            timeout=60,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python3 -m pytest tests/test_dlc3d_proxy_user_header.py -q`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit** (in the main webapp repo)

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/app.py tests/test_dlc3d_proxy_user_header.py
git commit -m "feat(dlc-3d): stamp X-DLC-User on proxied requests"
```

---

### Task 2: dlc-3D resolves the project per user

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/routes.py` — remove the global at :30, add two helpers, replace 13 sites
- Modify: `dlc-3D/src/dlc_3d_bp/lp_routes.py` — 3 sites at :60, :276, :300
- Test: `dlc-3D/tests/test_dlc3d_per_user_project.py`

**Interfaces:**
- Consumes: `X-DLC-User` (Task 1); the main webapp's `webapp:dlc_project:{uid}` key.
- Produces: `_user_id() -> str` and `_active_project_for_user() -> str | None` in `routes.py`. `lp_routes.py` calls `routes_mod._active_project_for_user()` where it previously read `routes_mod._active_project`.

- [ ] **Step 1: Write the failing test**

```python
"""Two users must not overwrite each other's active project.

The bug this locks down: routes.py kept the project in a module global, so
whoever POSTed last won for everybody. Because _save_single_frame writes PNGs
into labeled-data/, the loser's saves landed in the winner's project.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dlc_3d_bp import routes as R  # noqa: E402


class FakeRedis:
    """Minimal stand-in. `fail` makes every call raise, for the Redis-down path."""
    def __init__(self, fail=False):
        self.store = {}
        self.fail = fail

    def get(self, key):
        if self.fail:
            raise ConnectionError("redis is down")
        return self.store.get(key)

    def ping(self):
        if self.fail:
            raise ConnectionError("redis is down")
        return True


@pytest.fixture
def projects(tmp_path):
    made = {}
    for name in ("alpha", "beta"):
        p = tmp_path / name
        p.mkdir()
        (p / "config.yaml").write_text("bodyparts: []\n")
        made[name] = p
    return made


@pytest.fixture
def redis_with(monkeypatch, projects):
    fake = FakeRedis()
    for uid, name in (("user-a", "alpha"), ("user-b", "beta")):
        fake.store[f"webapp:dlc_project:{uid}"] = json.dumps({
            "project_path": str(projects[name]),
            "project_name": name,
            "has_config": True,
            "config_path": str(projects[name] / "config.yaml"),
            "engine": "pytorch",
        })
    monkeypatch.setattr(R, "_redis_conn", lambda: fake)
    return fake


@pytest.fixture
def app():
    from flask import Flask
    a = Flask(__name__)
    a.register_blueprint(R.bp)
    a.config.update(TESTING=True)
    return a


def _resolve(app, uid):
    """Whatever _active_project_for_user returns for this uid, in request scope."""
    headers = {"X-DLC-User": uid} if uid is not None else {}
    with app.test_request_context("/dlc-3d/", headers=headers):
        return R._active_project_for_user()


def test_two_users_each_see_their_own_project(app, redis_with, projects):
    """The regression test for the original bug."""
    assert _resolve(app, "user-a") == str(projects["alpha"])
    assert _resolve(app, "user-b") == str(projects["beta"])
    # And A is unchanged after B resolved — no shared state was written.
    assert _resolve(app, "user-a") == str(projects["alpha"])


def test_the_global_is_gone(app):
    """A later merge must not quietly reintroduce it."""
    assert not hasattr(R, "_active_project"), (
        "_active_project is back; two users will overwrite each other again"
    )


def test_no_header_means_no_project(app, redis_with):
    assert _resolve(app, None) is None


def test_unknown_user_means_no_project(app, redis_with):
    assert _resolve(app, "never-seen") is None


def test_redis_down_means_no_project_not_a_crash(app, monkeypatch):
    monkeypatch.setattr(R, "_redis_conn", lambda: None)
    assert _resolve(app, "user-a") is None


def test_redis_raising_means_no_project_not_a_crash(app, monkeypatch):
    monkeypatch.setattr(R, "_redis_conn", lambda: FakeRedis(fail=True))
    assert _resolve(app, "user-a") is None


def test_malformed_payload_means_no_project(app, monkeypatch):
    fake = FakeRedis()
    fake.store["webapp:dlc_project:user-a"] = "{not json"
    monkeypatch.setattr(R, "_redis_conn", lambda: fake)
    assert _resolve(app, "user-a") is None


def test_payload_without_project_path_means_no_project(app, monkeypatch):
    fake = FakeRedis()
    fake.store["webapp:dlc_project:user-a"] = json.dumps({"engine": "pytorch"})
    monkeypatch.setattr(R, "_redis_conn", lambda: fake)
    assert _resolve(app, "user-a") is None


def test_set_project_writes_no_server_state(app, redis_with, projects):
    """It still validates and still returns sessions, but the selection itself
    now lives in the main webapp — this endpoint must not shadow it."""
    client = app.test_client()
    r = client.post("/dlc-3d/project",
                    json={"path": str(projects["beta"])},
                    headers={"X-DLC-User": "user-a"})
    assert r.status_code == 200
    assert "sessions" in r.get_json()
    # user-a's project is unchanged: the POST did not write anything.
    assert _resolve(app, "user-a") == str(projects["alpha"])


def test_set_project_still_404s_on_a_bad_path(app, redis_with, tmp_path):
    client = app.test_client()
    r = client.post("/dlc-3d/project",
                    json={"path": str(tmp_path / "nope")},
                    headers={"X-DLC-User": "user-a"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_dlc3d_per_user_project.py -q`
Expected: FAIL — `AttributeError: module 'dlc_3d_bp.routes' has no attribute '_active_project_for_user'`

- [ ] **Step 3: Write the implementation**

In `routes.py`, delete BOTH `_active_project` and `_state_lock` at lines 30-31,
along with the `# ── Server state (single-user) ──` banner above them. Verified:
every one of the 15 `_state_lock` uses guards only a read or write of
`_active_project`, so the lock has nothing left to protect once the global is
gone. Leaving it would be dead code that implies a shared-state discipline the
module no longer has. Remove `import threading` at line 7 if nothing else uses
it — check before deleting.

Then add:

```python
def _redis_conn():
    """Redis client, or None when it is unreachable.

    Same pattern as lp_routes._redis_conn, which has been writing
    dlc3d:lp:job:* keys in production; kept local so routes.py does not import
    the LP module.
    """
    try:
        import redis
        url = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0")
        c = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1.0)
        c.ping()
        return c
    except Exception:
        return None


def _user_id() -> str:
    """The uid the main webapp's proxy stamped on this request.

    dlc-3D has no session of its own — the browser's cookie belongs to the main
    webapp. Empty when absent, which resolves to "no project" downstream.
    """
    return (request.headers.get("X-DLC-User") or "").strip()


def _active_project_for_user() -> "str | None":
    """This request's user's active project path, or None.

    Reads the main webapp's own webapp:dlc_project:{uid} key rather than a
    mirror. dlc-3D used to keep a module global synced by POST /project, which
    meant two users silently overwrote each other's selection — and, since
    _save_single_frame writes into labeled-data/, corrupted each other's work.

    Every failure resolves to None ("no project selected"), which every caller
    already handles. Nothing here may raise.
    """
    uid = _user_id()
    if not uid:
        return None
    conn = _redis_conn()
    if conn is None:
        return None
    try:
        raw = conn.get(f"webapp:dlc_project:{uid}")
        if not raw:
            return None
        return json.loads(raw).get("project_path") or None
    except Exception:
        return None
```

Verified: `routes.py` already imports `json` (line 4) and `request` (line 13),
but **not** `os`. Add `import os` to the stdlib import block at the top, and use
plain `os.environ` in `_redis_conn` (drop the `_os` alias used above).

Then replace each of the 13 read sites. They share one shape:

```python
    with _state_lock:
        proj = _active_project
```

becomes:

```python
    proj = _active_project_for_user()
```

The `with` block goes away every time — the lock guarded nothing else. The
sites are at lines 351, 361, 373, 409, 426, 485, 553, 632, 670, 742 plus the
`rescan_project` read; verify each against the file before editing, since line
numbers shift as you go.

In `set_project` (line 327): delete `global _active_project` and the
`with _state_lock: _active_project = str(p)` assignment. Keep everything
else — the validation, the 404, and the `_load_or_scan_videos` response.

In `lp_routes.py`, three sites at lines 60, 276 and 300:

```python
            dlc = routes_mod._active_project or ""
```

becomes:

```python
            dlc = routes_mod._active_project_for_user() or ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_dlc3d_per_user_project.py -q`
Expected: PASS, 10 tests

- [ ] **Step 5: Update the three test files that set the old global**

`test_frame_route_no_project.py:18`, `test_lp_routes.py:90,103,232` and
`test_labeled_epilines_route.py:52` do
`monkeypatch.setattr(R, "_active_project", ...)`, which now targets an
attribute that no longer exists. Replace each with a patched
`_active_project_for_user`:

```python
    monkeypatch.setattr(R, "_active_project_for_user", lambda: str(proj))
```

and for the "no project" cases:

```python
    monkeypatch.setattr(R, "_active_project_for_user", lambda: None)
```

`test_labeled_epilines_route.py` also has a docstring at line 5 mentioning
`_active_project set directly` — update it to match.

- [ ] **Step 6: Run the whole suite**

Run: `cd dlc-3D && python3 -m pytest tests/ -q --ignore=tests/e2e`
Expected: exactly 8 pre-existing failures, no more.

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/dlc_3d_bp/routes.py dlc-3D/src/dlc_3d_bp/lp_routes.py dlc-3D/tests/
git commit -m "fix(dlc-3d): resolve the active project per user, not per process"
```

---

### Task 3: Raise the worker count

**Files:**
- Modify: `dlc-3D/Dockerfile:19`
- Modify: `dlc-3D/src/viewer.py:8`
- Modify: `dlc-3D/README.md`
- Test: `dlc-3D/tests/test_dlc3d_concurrency_config.py`

**Interfaces:**
- Consumes: Task 2 (no request may depend on process state).
- Produces: nothing downstream.

- [ ] **Step 1: Write the failing test**

```python
"""Configuration guards for running dlc-3D multi-worker.

-w 1 was not a performance choice: it was the only thing keeping the
_active_project global self-consistent, because each gunicorn worker holds its
own copy. Now that no request depends on process state, the module can serve
several users at once — but the per-process video-capture cache multiplies with
the worker count, so the two numbers are coupled and must move together.
"""
import re
from pathlib import Path

SRC = Path(__file__).parent.parent
DOCKERFILE = SRC / "Dockerfile"
VIEWER = SRC / "src" / "viewer.py"


def _worker_count():
    m = re.search(r'"-w",\s*"(\d+)"', DOCKERFILE.read_text())
    assert m, "could not find the gunicorn -w flag in the Dockerfile"
    return int(m.group(1))


def _vcap_max():
    m = re.search(r"^_VCAP_MAX\s*=\s*(\d+)", VIEWER.read_text(), re.M)
    assert m, "could not find _VCAP_MAX in viewer.py"
    return int(m.group(1))


def test_serves_more_than_one_request_at_a_time():
    assert _worker_count() >= 4, (
        "one worker serialises every /dlc-3d/ request behind the slowest one; "
        "get_frame_jpeg decodes a video frame per request, so one user "
        "scrubbing a timeline blocks everyone else's saves"
    )


def test_the_frame_cache_is_divided_across_workers():
    """_VCAP_MAX is per PROCESS. N workers hold N caches, so the open-handle
    count against NAS-mounted video is workers x _VCAP_MAX."""
    total = _worker_count() * _vcap_max()
    assert total <= 8, (
        f"{_worker_count()} workers x {_vcap_max()} cached captures = {total} "
        "open video handles; divide _VCAP_MAX when raising the worker count"
    )


def test_the_module_is_not_directly_reachable():
    """dlc-3D trusts the X-DLC-User header, which is only sound because the
    proxy is the sole route in. A ports: mapping would make user identity
    spoofable from the LAN."""
    compose = (SRC.parent.parent / "deeplabcut-webapp-docker"
               / "docker-compose.yml").read_text()
    block = compose.split("\n  dlc-3d:")[1].split("\n  ")[0]
    assert "ports:" not in block, (
        "dlc-3d must stay internal — see the trust boundary in the design doc"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_dlc3d_concurrency_config.py -q`
Expected: FAIL — `assert 1 >= 4`

- [ ] **Step 3: Write the implementation**

`Dockerfile` line 19:

```dockerfile
# -w 4: several people label at once. Safe only because no request depends on
# process state any more (see docs/superpowers/specs/
# 2026-08-04-dlc3d-per-user-project-design.md) — the active project is resolved
# per request from Redis. Do not raise without dividing _VCAP_MAX in viewer.py:
# that cache is per process.
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5050", "--timeout", "300", "app:app"]
```

`src/viewer.py` line 8:

```python
# Per PROCESS, and gunicorn runs 4 workers, so the real ceiling on open video
# handles is 4 x this. Kept at 2 so the total stays where it was at -w 1.
_VCAP_MAX = 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_dlc3d_concurrency_config.py -q`
Expected: PASS, 3 tests

- [ ] **Step 5: Record the trust boundary in the README**

Append to `dlc-3D/README.md`:

```markdown
## Multi-user

The active DLC project is resolved **per request**, from the main webapp's
`webapp:dlc_project:{uid}` Redis key, using the `X-DLC-User` header its proxy
stamps on every forwarded request. There is no server-side "current project" —
several people can use `/dlc-3d/` at once on different projects.

**Do not add a `ports:` mapping to the `dlc-3d` service.** This module trusts
`X-DLC-User`, which is sound only because the main webapp's proxy is the only
route in. Exposing a host port would make user identity spoofable from the LAN.

Gunicorn runs 4 workers. `viewer._VCAP_MAX` is a per-process cache, so the
open-video-handle ceiling is `workers x _VCAP_MAX` — move the two together.
```

- [ ] **Step 6: Run the whole suite**

Run: `cd dlc-3D && python3 -m pytest tests/ -q --ignore=tests/e2e`
Expected: exactly 8 pre-existing failures.

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/Dockerfile dlc-3D/src/viewer.py dlc-3D/README.md dlc-3D/tests/test_dlc3d_concurrency_config.py
git commit -m "feat(dlc-3d): serve 4 workers now that no request holds process state"
```

---

## Deployment

The `-w 4` change is in the **Dockerfile**, so unlike the source-only changes
this one does need a rebuild of the dlc-3d image:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d && docker compose up -d dlc-3d
```

`src/app.py` in the main webapp is a **single-file bind mount**, which goes
stale on `restart` because of inode rebinding. It needs:

```bash
docker compose up -d --force-recreate flask
```

Then verify, inside the containers rather than by inference:

```bash
docker compose exec -T dlc-3d ps -eo args | grep gunicorn        # expect -w 4
docker compose exec -T dlc-3d grep -c "_active_project_for_user" /app/dlc_3d_bp/routes.py
docker compose exec -T dlc-3d grep -c "^_active_project" /app/dlc_3d_bp/routes.py   # expect 0
docker compose exec -T flask grep -c "X-DLC-User" /app/app.py
```

End-to-end check: open `/dlc-3d/` in two different browsers (or one normal and
one private window — they get different uids), select a different project in
each, and confirm each keeps its own.

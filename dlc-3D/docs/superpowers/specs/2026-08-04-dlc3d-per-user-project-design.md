# Per-User Project State in dlc-3D — Design

**Date:** 2026-08-04
**Status:** approved (design decision delegated by the user), ready for planning

## The problem

`src/dlc_3d_bp/routes.py:30` holds the active project in a module-level global:

```python
# ── Server state (single-user) ──────────
_active_project: str | None = None
```

Sixteen call sites read it (13 in `routes.py`, 3 in `lp_routes.py`). If user A
opens project X in `/dlc-3d/` and user B opens project Y, **B's selection
silently replaces A's**. A's next frame save, label write or triangulation then
runs against B's project. No error is raised. Because `_save_single_frame`
writes PNGs into `labeled-data/`, this corrupts work rather than merely
confusing the display.

The module is pinned at `gunicorn -w 1` (`Dockerfile:19`), which is the only
thing keeping the global self-consistent today: each gunicorn worker process
would otherwise hold its own copy, so requests would land on workers holding
different projects at random. That single worker is also a throughput ceiling —
`viewer.get_frame_jpeg` decodes a video frame per request, so one person
scrubbing a timeline blocks every other `/dlc-3d/` request, including saves.

## The decision

**dlc-3D stops keeping its own copy of the active project and reads the main
webapp's per-user key directly.**

The alternative — dlc-3D keeping its own `dlc3d:active_project:{uid}`, synced
by the existing POST — was rejected. dlc-3D's global is *already* a mirror:
`dlc_3d.js:235` reads `#dlc-active-path` from the DOM (which the main webapp
fills per user), and `dlc_3d.js:251` POSTs it to `/dlc-3d/project`. A second
per-user copy would preserve exactly the class of bug being removed — two
stores that can disagree — and would need sync code to keep them honest.
Reading the source of truth needs none.

Three facts make this cheap, all verified rather than assumed:

1. **`redis` 5.3.1 is already installed** in the running `dlc-3d` container.
   There is no `requirements.txt` in the module at all, so no dependency
   change and **no image rebuild** — a restart suffices.
2. **A working Redis-connection pattern already exists** in the module:
   `lp_routes.py:78` `_redis_conn()`, which returns a client or `None`, using
   `CELERY_RESULT_BACKEND` with a `redis://redis:6379/0` default. It is proven
   in production — 4,720 `dlc3d:lp:job:*` keys were written through it.
3. **The proxy already forwards every header.** `deeplabcut-webapp-docker/src/app.py:616`
   copies all request headers except `host`, `content-length` and
   `transfer-encoding`, so one added header reaches dlc-3D untouched.

## Architecture

### 1. The main webapp names the user

`proxy_dlc_3d` (`app.py:612`) injects the uid it already computes:

```python
headers["X-DLC-User"] = _user_id()
```

`_user_id()` (`app.py:76`) is the same function backing
`webapp:dlc_project:{uid}` (`app.py:83`), so the header and the key cannot
drift apart.

### 2. dlc-3D resolves the project per request

Two new helpers in `routes.py`, replacing the global:

```python
def _user_id() -> str:
    """The uid the main webapp's proxy stamped on this request."""
    return (request.headers.get("X-DLC-User") or "").strip()


def _active_project_for_user() -> "str | None":
    """This user's active project path, or None.

    Reads the main webapp's own key rather than a mirror: dlc-3D used to keep
    a module global synced by a POST, which two users could silently
    overwrite for each other. Defensive throughout — an unreachable Redis, a
    missing key or an unexpected payload all mean "no project selected",
    never a 500.
    """
```

It reads `webapp:dlc_project:{uid}` and returns `project_path`. The live
payload shape, confirmed against production:

```json
{"project_path": "...", "project_name": "...", "has_config": true,
 "config_path": ".../config.yaml", "engine": "pytorch"}
```

Every one of the 16 sites becomes `proj = _active_project_for_user()`. The 13
in `routes.py` are near-identical (`with _state_lock: proj = _active_project`),
so the bulk is mechanical, and most of the 15 `_state_lock` uses disappear
with the global.

### 3. `POST /dlc-3d/project` becomes validation-only

It currently sets the global. It keeps its path validation and its
`_load_or_scan_videos` response — `dlc_3d.js` depends on the `sessions` payload
— but no longer writes any server state. The main webapp already owns the
selection; this endpoint acknowledges it.

### 4. Raise the worker count

`Dockerfile:19` `-w 1` → `-w 4`, safe once no request depends on process state.

**One consequence to handle in the same change:** `viewer.py` keeps a per-path
`VideoCapture` LRU cache **per process**, so four workers means four copies —
four times the open handles against NAS-mounted video. `_VCAP_MAX` must be
divided accordingly, or the module will hold four times the file descriptors it
does now.

## Failure behaviour

No header, unreachable Redis, missing key, or malformed JSON all resolve to
"no active project" — the same state as a fresh session, which every route
already handles. Nothing new can 500.

## The trust boundary

dlc-3D will trust `X-DLC-User`. That is sound **only because the proxy is the
only route in**: the service declares no host port mapping, so it is reachable
only on the internal Docker network. Anyone adding a `ports:` entry for
debugging would turn user identity into a spoofable header.

This constraint is recorded in the module README as part of this change.

## Testing

**Route level** (extending the three files that currently
`monkeypatch.setattr(R, "_active_project", ...)` — 11 lines across
`test_frame_route_no_project.py`, `test_lp_routes.py`,
`test_labeled_epilines_route.py`):

- two users with different projects, interleaved requests, each sees its own —
  the test that would have caught the original bug
- no `X-DLC-User` header → behaves as "no project", not a 500
- Redis unreachable → same
- key present but malformed JSON → same
- `POST /dlc-3d/project` still returns `sessions` and still 404s on a bad path,
  while writing no server state

**Guard:** an assertion that `_active_project` no longer exists as a module
global, so it cannot be reintroduced by a later merge.

## Scope boundaries

- Container-per-project is **not** built. It was considered and rejected for
  this problem: users on the *same* project would share a container and still
  serialise behind its workers, so it does not address the stated need (four
  people on one project), while adding dynamic proxy routing and container
  lifecycle management. This change is a prerequisite for it in any case.
- GPU throughput is unchanged. All users still share GPU 0 and one Celery pool
  (`--concurrency=2`). Four people can browse and label concurrently; they
  cannot train or analyse concurrently.
- The main webapp's own `gunicorn -w 4` ceiling is site-wide and out of scope.
- The `#dlc-active-path` MutationObserver and the POST it drives stay as they
  are. Removing that path is follow-up work, not part of this change.

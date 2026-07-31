# Tracked Files Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user mark a video as "tracked" and reopen it later from a new **Tracked Files** tab in the 3D Inline Analysis card, without re-navigating to its folder.

**Architecture:** Three independent layers. A pure SQLite store (`<project>/tracked_files.sqlite`) in the main webapp, a thin Flask blueprint over it at `/dlc/project/tracked-files`, and a self-contained client factory in dlc-3D that owns the new tab plus a track checkbox in the player header. `inline_analysis_3d.js` gains wiring only.

**Tech Stack:** Python 3 + Flask + sqlite3 (stdlib) in `deeplabcut-webapp-docker`; vanilla ES modules in `deeplabcut-webapp-docker-supports/dlc-3D`. Tests: pytest (both repos) and `node --test` for pure `.mjs`.

**Spec:** `docs/superpowers/specs/2026-07-31-tracked-files-design.md`

## Global Constraints

- Two repos are involved. `MAIN` = `/home/sam/docker-images/deeplabcut-webapp-docker`. `SUP` = `/home/sam/docker-images/deeplabcut-webapp-docker-supports`. They are separate git checkouts — commit in the repo you touched.
- Video extension whitelist, used identically on both sides: `.mp4 .avi .mov .mkv .mpg .mpeg` (matches `_IA_VIDEO_EXTS` at `SUP/dlc-3D/src/static/inline_analysis_3d.js:91`).
- Timestamps are `time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())` — the same shape as `MAIN/src/dlc/marks_store.py:70`.
- The store module imports **no** Flask, DLC or Redis, and **never** touches the filesystem beyond its own DB file.
- No route stats a tracked path. Missing files are discovered at open time only.
- Known-failure baselines — do **not** attribute these to this work: **8** failures in dlc-3D, **2 + 14** in the main webapp.
- Run pytest only from a repo root so its `pytest.ini` disk-fill guards apply. Never run the multi-GB e2e suites for this work.
- Client code renders every server-provided string with `textContent`, never `innerHTML` — paths are user data.

---

### Task 1: SQLite store

**Files:**
- Create: `MAIN/src/dlc/tracked_files.py`
- Test: `MAIN/src/tests/test_tracked_files_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `list_tracked(project_path) -> list[dict]` with keys `path`, `tracked_at`, `last_opened_at`; `track(project_path, video_path) -> None`; `untrack(project_path, video_path) -> None`; `touch_opened(project_path, video_path) -> None`; module constant `DB_FILENAME = "tracked_files.sqlite"`; internal `_now() -> str` (tests monkeypatch it).

- [ ] **Step 1: Write the failing test**

Create `MAIN/src/tests/test_tracked_files_store.py`:

```python
"""Tests for src/dlc/tracked_files.py — pure SQLite layer for tracked videos."""
from __future__ import annotations
from pathlib import Path

import pytest

from dlc import tracked_files as tf


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A bare DLC project root — only what tracked_files cares about."""
    p = tmp_path / "Proj-2026-07-31"
    p.mkdir()
    return p


@pytest.fixture
def clock(monkeypatch):
    """Deterministic _now() — tracked_at resolution is 1 s, so tests must control it."""
    ticks = iter([
        "2026-07-31T10:00:00Z", "2026-07-31T10:00:01Z", "2026-07-31T10:00:02Z",
        "2026-07-31T10:00:03Z", "2026-07-31T10:00:04Z", "2026-07-31T10:00:05Z",
    ])
    monkeypatch.setattr(tf, "_now", lambda: next(ticks))


def test_fresh_project_lists_nothing_and_creates_no_db(project):
    assert tf.list_tracked(project) == []
    assert not (project / tf.DB_FILENAME).exists()


def test_track_then_list(project, clock):
    tf.track(project, "/data/eggtart-1_cam0.avi")
    assert tf.list_tracked(project) == [
        {"path": "/data/eggtart-1_cam0.avi",
         "tracked_at": "2026-07-31T10:00:00Z",
         "last_opened_at": None},
    ]


def test_track_is_idempotent_and_preserves_tracked_at(project, clock):
    tf.track(project, "/data/a.avi")
    tf.touch_opened(project, "/data/a.avi")     # 10:00:01
    tf.track(project, "/data/a.avi")            # re-track must not reset anything
    rows = tf.list_tracked(project)
    assert len(rows) == 1
    assert rows[0]["tracked_at"] == "2026-07-31T10:00:00Z"
    assert rows[0]["last_opened_at"] == "2026-07-31T10:00:01Z"


def test_untrack_removes_row_and_is_a_noop_when_absent(project, clock):
    tf.track(project, "/data/a.avi")
    tf.untrack(project, "/data/a.avi")
    assert tf.list_tracked(project) == []
    tf.untrack(project, "/data/a.avi")          # must not raise
    assert tf.list_tracked(project) == []


def test_touch_opened_never_creates_a_row(project, clock):
    tf.touch_opened(project, "/data/never-tracked.avi")
    assert tf.list_tracked(project) == []


def test_ordering_recently_opened_first_never_opened_last(project, clock):
    tf.track(project, "/data/a.avi")            # tracked 10:00:00
    tf.track(project, "/data/b.avi")            # tracked 10:00:01
    tf.track(project, "/data/c.avi")            # tracked 10:00:02
    tf.touch_opened(project, "/data/a.avi")     # opened  10:00:03
    tf.touch_opened(project, "/data/c.avi")     # opened  10:00:04
    assert [r["path"] for r in tf.list_tracked(project)] == [
        "/data/c.avi",   # opened most recently
        "/data/a.avi",   # opened earlier
        "/data/b.avi",   # never opened -> last
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_store.py -v`
Expected: FAIL — `ImportError: cannot import name 'tracked_files' from 'dlc'`

- [ ] **Step 3: Write minimal implementation**

Create `MAIN/src/dlc/tracked_files.py`:

```python
"""
Tracked video files, persisted in <project>/tracked_files.sqlite.

The user marks a video as "tracked" so it can be reopened later without
re-navigating to its folder. Identity is the absolute video path, stored
verbatim — no realpath/symlink resolution, so the stored path always matches
what the UI shows in its breadcrumb.

This module imports no Flask, no DLC, no Redis, and never touches the
filesystem beyond its own DB file — it can be unit-tested against tmp_path.
Existence of a tracked path is deliberately NOT checked here; a missing file
is discovered when the user tries to open it.

Schema (v1):
    tracked(video_path TEXT PRIMARY KEY, tracked_at TEXT NOT NULL,
            last_opened_at TEXT)
    meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)
        meta keys: schema_version="1"
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_FILENAME = "tracked_files.sqlite"
SCHEMA_VERSION = "1"


def _db_path(project_path) -> Path:
    return Path(project_path) / DB_FILENAME


@contextmanager
def _connect(project_path):
    """Open the SQLite DB, applying schema on first use. Per-call connection."""
    conn = sqlite3.connect(str(_db_path(project_path)), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        _ensure_schema(conn)
        yield conn
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tracked (
            video_path     TEXT PRIMARY KEY,
            tracked_at     TEXT NOT NULL,
            last_opened_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
    if cur.fetchone() is None:
        conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)",
                     ("schema_version", SCHEMA_VERSION))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def list_tracked(project_path) -> list[dict]:
    """Every tracked video, most recently opened first, never-opened last.

    SQLite has no NULLS LAST, hence the explicit `(last_opened_at IS NULL)`
    leading sort key.
    """
    if not _db_path(project_path).is_file():
        return []
    with _connect(project_path) as conn:
        rows = conn.execute(
            "SELECT video_path, tracked_at, last_opened_at FROM tracked "
            "ORDER BY (last_opened_at IS NULL), last_opened_at DESC, tracked_at DESC"
        ).fetchall()
    return [{"path": p, "tracked_at": t, "last_opened_at": o} for (p, t, o) in rows]


def track(project_path, video_path: str) -> None:
    """Start tracking `video_path`. Idempotent: re-tracking preserves the
    existing tracked_at and last_opened_at."""
    with _connect(project_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT OR IGNORE INTO tracked(video_path, tracked_at, last_opened_at) "
                "VALUES (?, ?, NULL)",
                (video_path, _now()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def untrack(project_path, video_path: str) -> None:
    """Stop tracking `video_path`. No-op when it was never tracked."""
    if not _db_path(project_path).is_file():
        return
    with _connect(project_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM tracked WHERE video_path=?", (video_path,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def touch_opened(project_path, video_path: str) -> None:
    """Stamp last_opened_at=now, but ONLY if the row already exists — opening
    an untracked video must never create a tracked row."""
    if not _db_path(project_path).is_file():
        return
    with _connect(project_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "UPDATE tracked SET last_opened_at=? WHERE video_path=?",
                (_now(), video_path),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_store.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/tracked_files.py src/tests/test_tracked_files_store.py
git commit -m "feat(tracked-files): per-project SQLite store for tracked videos"
```

---

### Task 2: Flask blueprint

**Files:**
- Create: `MAIN/src/dlc/tracked_files_routes.py`
- Modify: `MAIN/src/app.py` (blueprint import block ~line 190, registration block ~line 206)
- Test: `MAIN/src/tests/test_tracked_files_routes.py`

**Interfaces:**
- Consumes: Task 1's `list_tracked` / `track` / `untrack` / `touch_opened`.
- Produces: `bp = Blueprint("dlc_tracked_files", __name__)` serving `GET|POST|DELETE /dlc/project/tracked-files` and `POST /dlc/project/tracked-files/opened`. GET returns `{"files": [{path, name, dir, tracked_at, last_opened_at}]}`. Task 5 consumes these URLs.

- [ ] **Step 1: Write the failing test**

Create `MAIN/src/tests/test_tracked_files_routes.py`:

```python
"""Tests for the dlc_tracked_files blueprint."""
from __future__ import annotations
import json
from pathlib import Path

import pytest


def _activate_project(client, fake_redis, project_path: Path):
    """Seed the Redis project key the way dlc_project would."""
    with client.session_transaction() as sess:
        sess["uid"] = "test-uid"
    fake_redis.set(
        "webapp:dlc_project:test-uid",
        json.dumps({
            "project_path": str(project_path),
            "config_path": str(project_path / "config.yaml"),
            "engine": "pytorch",
        }),
    )


@pytest.fixture
def tracked_project(flask_test_client):
    """A project INSIDE data_dir — _sec_check rejects anything outside it."""
    client, _app, fake_redis, data_dir, _udd = flask_test_client
    proj = data_dir / "TrackedTest-2026-07-31"
    proj.mkdir()
    (proj / "config.yaml").write_text("scorer: TestScorer\n")
    _activate_project(client, fake_redis, proj)
    return client, proj


def test_list_requires_active_project(flask_test_client):
    client = flask_test_client[0]
    rv = client.get("/dlc/project/tracked-files")
    assert rv.status_code == 400
    assert "error" in rv.get_json()


def test_list_is_empty_on_fresh_project(tracked_project):
    client, _proj = tracked_project
    rv = client.get("/dlc/project/tracked-files")
    assert rv.status_code == 200
    assert rv.get_json()["files"] == []


def test_post_then_list_returns_derived_name_and_dir(tracked_project):
    client, _proj = tracked_project
    rv = client.post("/dlc/project/tracked-files",
                     json={"path": "/data/eggtart/day1/eggtart-1_cam0.avi"})
    assert rv.status_code == 200
    assert rv.get_json()["tracked"] is True

    files = client.get("/dlc/project/tracked-files").get_json()["files"]
    assert len(files) == 1
    assert files[0]["path"] == "/data/eggtart/day1/eggtart-1_cam0.avi"
    assert files[0]["name"] == "eggtart-1_cam0.avi"
    assert files[0]["dir"] == "/data/eggtart/day1"
    assert files[0]["last_opened_at"] is None


def test_list_does_not_require_the_file_to_exist(tracked_project):
    """No stat at list time — a path on an unmounted disk still lists."""
    client, _proj = tracked_project
    client.post("/dlc/project/tracked-files", json={"path": "/nowhere/gone.avi"})
    files = client.get("/dlc/project/tracked-files").get_json()["files"]
    assert [f["path"] for f in files] == ["/nowhere/gone.avi"]


def test_delete_removes_the_row(tracked_project):
    client, _proj = tracked_project
    client.post("/dlc/project/tracked-files", json={"path": "/data/a.avi"})
    rv = client.delete("/dlc/project/tracked-files", json={"path": "/data/a.avi"})
    assert rv.status_code == 200
    assert rv.get_json()["tracked"] is False
    assert client.get("/dlc/project/tracked-files").get_json()["files"] == []


def test_rejects_relative_path(tracked_project):
    client, _proj = tracked_project
    rv = client.post("/dlc/project/tracked-files", json={"path": "data/a.avi"})
    assert rv.status_code == 400
    assert client.get("/dlc/project/tracked-files").get_json()["files"] == []


def test_rejects_non_video_extension(tracked_project):
    client, _proj = tracked_project
    rv = client.post("/dlc/project/tracked-files", json={"path": "/data/a.csv"})
    assert rv.status_code == 400
    assert client.get("/dlc/project/tracked-files").get_json()["files"] == []


def test_accepts_every_whitelisted_extension(tracked_project):
    client, _proj = tracked_project
    for ext in (".mp4", ".avi", ".mov", ".mkv", ".mpg", ".mpeg"):
        rv = client.post("/dlc/project/tracked-files", json={"path": f"/data/v{ext}"})
        assert rv.status_code == 200, ext
    assert len(client.get("/dlc/project/tracked-files").get_json()["files"]) == 6


def test_opened_stamps_only_an_existing_row(tracked_project):
    client, _proj = tracked_project
    client.post("/dlc/project/tracked-files", json={"path": "/data/a.avi"})

    rv = client.post("/dlc/project/tracked-files/opened", json={"path": "/data/a.avi"})
    assert rv.status_code == 200
    files = client.get("/dlc/project/tracked-files").get_json()["files"]
    assert files[0]["last_opened_at"] is not None

    # An untracked path must not be created by 'opened'.
    client.post("/dlc/project/tracked-files/opened", json={"path": "/data/other.avi"})
    paths = [f["path"] for f in client.get("/dlc/project/tracked-files").get_json()["files"]]
    assert paths == ["/data/a.avi"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_routes.py -v`
Expected: FAIL — every route returns 404 (blueprint not registered)

- [ ] **Step 3: Write minimal implementation**

Create `MAIN/src/dlc/tracked_files_routes.py`:

```python
"""
Tracked video files — Flask Blueprint.

Routes
------
GET    /dlc/project/tracked-files          List tracked videos for the active project.
POST   /dlc/project/tracked-files          Track one absolute video path.
DELETE /dlc/project/tracked-files          Untrack one absolute video path.
POST   /dlc/project/tracked-files/opened   Stamp last_opened_at on an existing row.

Lives in its own module rather than in inline_analysis.py (already 1000+ lines).
No route stats a tracked path: a vanished file is discovered when the user
tries to open it, not while listing. A bulk "verify these still exist" sweep
belongs to the planned file-management module.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from flask import Blueprint, jsonify, request

from . import ctx as _ctx
from . import tracked_files as _store
from .labeling import _dlc_key, _sec_check

bp = Blueprint("dlc_tracked_files", __name__)

_ROUTE = "/dlc/project/tracked-files"

# Same set as _IA_VIDEO_EXTS in dlc-3D's inline_analysis_3d.js, so the server
# never rejects something the browse list offered.
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".mpg", ".mpeg"}


def _project_path_checked() -> tuple[Path | None, str | None]:
    raw = _ctx.redis_client().get(_dlc_key())
    if not raw:
        return None, "No active DLC project."
    try:
        project = json.loads(raw)
    except (TypeError, ValueError):
        return None, "Active project state is unreadable."
    pp = Path(project.get("project_path", ""))
    if not pp.is_dir():
        return None, "Project directory not found."
    if not _sec_check(pp):
        return None, "Access denied."
    return pp, None


def _video_path_checked() -> tuple[str | None, str | None]:
    body = request.get_json(silent=True) or {}
    raw = body.get("path", "")
    if not isinstance(raw, str) or not raw.strip():
        return None, "path required"
    path = raw.strip()
    if not path.startswith("/"):
        return None, "path must be absolute"
    if Path(path).suffix.lower() not in VIDEO_EXTS:
        return None, "not a video file"
    return path, None


@bp.route(_ROUTE, methods=["GET"])
def list_tracked_files():
    pp, err = _project_path_checked()
    if err:
        return jsonify({"error": err}), 400
    try:
        rows = _store.list_tracked(pp)
    except sqlite3.Error as exc:
        return jsonify({"error": f"tracked-files DB error: {exc}"}), 500
    files = [
        {
            "path": r["path"],
            "name": Path(r["path"]).name,
            "dir": str(Path(r["path"]).parent),
            "tracked_at": r["tracked_at"],
            "last_opened_at": r["last_opened_at"],
        }
        for r in rows
    ]
    return jsonify({"files": files})


@bp.route(_ROUTE, methods=["POST"])
def track_file():
    pp, err = _project_path_checked()
    if err:
        return jsonify({"error": err}), 400
    path, perr = _video_path_checked()
    if perr:
        return jsonify({"error": perr}), 400
    try:
        _store.track(pp, path)
    except sqlite3.Error as exc:
        return jsonify({"error": f"tracked-files DB error: {exc}"}), 500
    return jsonify({"ok": True, "tracked": True})


@bp.route(_ROUTE, methods=["DELETE"])
def untrack_file():
    pp, err = _project_path_checked()
    if err:
        return jsonify({"error": err}), 400
    path, perr = _video_path_checked()
    if perr:
        return jsonify({"error": perr}), 400
    try:
        _store.untrack(pp, path)
    except sqlite3.Error as exc:
        return jsonify({"error": f"tracked-files DB error: {exc}"}), 500
    return jsonify({"ok": True, "tracked": False})


@bp.route(_ROUTE + "/opened", methods=["POST"])
def mark_opened():
    pp, err = _project_path_checked()
    if err:
        return jsonify({"error": err}), 400
    path, perr = _video_path_checked()
    if perr:
        return jsonify({"error": perr}), 400
    try:
        _store.touch_opened(pp, path)
    except sqlite3.Error as exc:
        return jsonify({"error": f"tracked-files DB error: {exc}"}), 500
    return jsonify({"ok": True})
```

Then register it in `MAIN/src/app.py`. Add the import immediately after the `_dlc_posture_bp` import line:

```python
from dlc.posture_routes import bp as _dlc_posture_bp
from dlc.tracked_files_routes import bp as _dlc_tracked_files_bp
```

and the registration immediately after the `_dlc_posture_bp` registration line:

```python
app.register_blueprint(_dlc_posture_bp)
app.register_blueprint(_dlc_tracked_files_bp)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_routes.py -v`
Expected: 9 passed

- [ ] **Step 5: Verify nothing else broke**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/ -q --ignore=src/tests/tests -p no:randomly`
Expected: the pre-existing **2 + 14** failures and no others. Compare against `git stash` baseline if any new failure appears.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/tracked_files_routes.py src/tests/test_tracked_files_routes.py src/app.py
git commit -m "feat(tracked-files): blueprint for listing/tracking/untracking videos"
```

---

### Task 3: Relative-time helper

**Files:**
- Create: `SUP/dlc-3D/src/static/internal/relative_time.mjs`
- Test: `SUP/dlc-3D/tests/unit/test_relative_time.mjs`

**Interfaces:**
- Consumes: nothing.
- Produces: `export function formatRelative(iso, nowMs) -> string`. `iso` is an ISO-8601 string or `null`; `nowMs` is `Date.now()`-style epoch ms, passed in so the function is testable. Task 5 imports it.

- [ ] **Step 1: Write the failing test**

Create `SUP/dlc-3D/tests/unit/test_relative_time.mjs`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { formatRelative } from "../../src/static/internal/relative_time.mjs";

const NOW = Date.parse("2026-07-31T12:00:00Z");

test("formatRelative: null/empty/garbage timestamps read as never opened", () => {
  assert.equal(formatRelative(null, NOW), "never opened");
  assert.equal(formatRelative("", NOW), "never opened");
  assert.equal(formatRelative("not-a-date", NOW), "never opened");
});

test("formatRelative: under a minute is 'just now'", () => {
  assert.equal(formatRelative("2026-07-31T12:00:00Z", NOW), "just now");
  assert.equal(formatRelative("2026-07-31T11:59:31Z", NOW), "just now");
});

test("formatRelative: minutes, hours, days", () => {
  assert.equal(formatRelative("2026-07-31T11:58:00Z", NOW), "2 min ago");
  assert.equal(formatRelative("2026-07-31T10:00:00Z", NOW), "2 h ago");
  assert.equal(formatRelative("2026-07-28T12:00:00Z", NOW), "3 d ago");
});

test("formatRelative: months and years", () => {
  assert.equal(formatRelative("2026-05-31T12:00:00Z", NOW), "2 mo ago");
  assert.equal(formatRelative("2024-07-31T12:00:00Z", NOW), "2 y ago");
});

test("formatRelative: a future timestamp clamps to 'just now', never negative", () => {
  assert.equal(formatRelative("2026-07-31T12:05:00Z", NOW), "just now");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_relative_time.mjs`
Expected: FAIL — `Cannot find module .../internal/relative_time.mjs`

- [ ] **Step 3: Write minimal implementation**

Create `SUP/dlc-3D/src/static/internal/relative_time.mjs`:

```javascript
// relative_time.mjs — pure "how long ago" formatting for the Tracked Files list.
//
// `nowMs` is a parameter rather than a Date.now() call so the function is
// directly unit-testable. No DOM, no fetch.

export function formatRelative(iso, nowMs) {
  if (!iso) return "never opened";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "never opened";
  // Clamp: a clock skew between server and browser must never print "-3 min ago".
  const sec = Math.max(0, Math.round((nowMs - t) / 1000));
  if (sec < 60) return "just now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} d ago`;
  const mon = Math.floor(day / 30);
  if (mon < 12) return `${mon} mo ago`;
  return `${Math.floor(day / 365)} y ago`;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_relative_time.mjs`
Expected: 5 pass, 0 fail

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/internal/relative_time.mjs dlc-3D/tests/unit/test_relative_time.mjs
git commit -m "feat(tracked-files): pure relative-time formatter for the tracked list"
```

---

### Task 4: Card markup

**Files:**
- Modify: `SUP/dlc-3D/src/templates/partials/card_inline_analysis_3d.html:11-15` (tab row), `:44` (after the browse panel), `:92-95` (player header)
- Test: `SUP/dlc-3D/tests/test_tracked_files_markup.py`

**Interfaces:**
- Consumes: nothing.
- Produces: DOM ids `ia3d-tab-tracked`, `ia3d-tab-tracked-panel`, `ia3d-tracked-list`, `ia3d-launcher-error`, `ia3d-track-checkbox`. Tasks 5 and 6 look these up by id.

- [ ] **Step 1: Write the failing test**

Create `SUP/dlc-3D/tests/test_tracked_files_markup.py`:

```python
"""Static guards for the Tracked Files markup in the 3D Inline Analysis card.

See docs/superpowers/specs/2026-07-31-tracked-files-design.md.
"""
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1]
        / "src" / "templates" / "partials" / "card_inline_analysis_3d.html")


def _src():
    assert HTML.is_file(), f"missing {HTML}"
    return HTML.read_text()


def test_third_source_tab_exists_after_browse_folders():
    s = _src()
    assert 'id="ia3d-tab-tracked"' in s
    assert "Tracked Files" in s
    # Order matters: Project Content, Browse Folders, Tracked Files.
    assert s.index('id="ia3d-tab-project"') < s.index('id="ia3d-tab-browse"') < s.index('id="ia3d-tab-tracked"')


def test_tracked_panel_and_list_container_exist_and_start_hidden():
    s = _src()
    m = re.search(r'<div id="ia3d-tab-tracked-panel"[^>]*class="([^"]*)"', s)
    assert m, "missing #ia3d-tab-tracked-panel"
    assert "hidden" in m.group(1), "tracked panel must start hidden"
    assert 'id="ia3d-tracked-list"' in s


def test_launcher_error_line_exists_outside_the_player_section():
    """The open-failure message must live in the launcher — the player section
    is never shown when an open aborts."""
    s = _src()
    assert 'id="ia3d-launcher-error"' in s
    assert s.index('id="ia3d-launcher-error"') < s.index('id="ia3d-player-section"')


def test_track_checkbox_precedes_the_selected_name_in_the_player_header():
    s = _src()
    assert 'id="ia3d-track-checkbox"' in s
    assert s.index('id="ia3d-track-checkbox"') < s.index('id="ia3d-selected-name"')


def test_track_checkbox_starts_hidden():
    """Visible only in browse-video mode; JS reveals it via setCurrent()."""
    s = _src()
    m = re.search(r'<label id="ia3d-track-label"[^>]*class="([^"]*)"', s)
    assert m, "missing #ia3d-track-label wrapper"
    assert "hidden" in m.group(1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_tracked_files_markup.py -v`
Expected: 5 failed

- [ ] **Step 3: Write minimal implementation**

In `card_inline_analysis_3d.html`, replace the tab row (lines 11-15):

```html
      <!-- Source tabs -->
      <div style="display:flex;gap:.4rem;margin-bottom:.6rem">
        <button id="ia3d-tab-project" class="btn-sm active" style="padding:.2rem .65rem;font-size:.75rem">Project Content</button>
        <button id="ia3d-tab-browse" class="btn-sm" style="padding:.2rem .65rem;font-size:.75rem">Browse Folders</button>
        <button id="ia3d-tab-tracked" class="btn-sm" style="padding:.2rem .65rem;font-size:.75rem">Tracked Files</button>
      </div>

      <!-- Launcher-level error line. Lives OUTSIDE #ia3d-player-section because an
           aborted open (missing file) never reveals the player. -->
      <div id="ia3d-launcher-error" class="fe-extract-status" style="margin-bottom:.4rem"></div>
```

Then insert the tracked panel immediately after the closing `</div>` of `#ia3d-tab-browse-panel` (after line 44):

```html
      <!-- Tab: Tracked Files -->
      <div id="ia3d-tab-tracked-panel" class="hidden">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.3rem">
          <label style="font-size:.78rem;color:var(--text-dim)">Tracked videos</label>
          <button class="btn-sm" id="ia3d-tracked-refresh" style="padding:.2rem .45rem;font-size:.75rem">↺ Refresh</button>
        </div>
        <div id="ia3d-tracked-list" style="max-height:220px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);padding:.4rem .5rem;font-size:.77rem">
          <p class="explorer-empty">Loading…</p>
        </div>
      </div>
```

Then in the player header, replace the `#ia3d-selected-name` line (line 93) so the checkbox precedes it:

```html
          <label id="ia3d-track-label" class="hidden" title="Track this file — it will appear in the Tracked Files tab"
                 style="display:flex;align-items:center;gap:.35rem;flex-shrink:0;cursor:pointer">
            <input type="checkbox" id="ia3d-track-checkbox" style="accent-color:var(--accent);width:14px;height:14px">
          </label>
          <span id="ia3d-selected-name" style="font-family:var(--mono);font-size:.78rem;color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0"></span>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_tracked_files_markup.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/partials/card_inline_analysis_3d.html dlc-3D/tests/test_tracked_files_markup.py
git commit -m "feat(tracked-files): third source tab + player-header track checkbox markup"
```

---

### Task 5: Tracked-files client factory

**Files:**
- Create: `SUP/dlc-3D/src/static/tracked_files_tab.js`
- Test: `SUP/dlc-3D/tests/test_tracked_files_tab_source.py`

**Interfaces:**
- Consumes: Task 3's `formatRelative(iso, nowMs)`; Task 2's four routes; Task 4's DOM ids.
- Produces: `export function makeTrackedFiles({ tabBtn, refreshBtn, panelEl, listEl, headerCheckbox, headerLabel, onOpen, onError }) -> { refresh(), setCurrent(pathOrNull), destroy() }`. Task 6 constructs it.

There is no DOM test runner in this repo, so this task is guarded by source assertions (the established `*_wiring.py` pattern) plus the manual check in Task 7.

- [ ] **Step 1: Write the failing test**

Create `SUP/dlc-3D/tests/test_tracked_files_tab_source.py`:

```python
"""Static guards for static/tracked_files_tab.js.

There is no DOM test runner here, so the invariants that actually bite —
XSS-safe rendering, checkbox revert on failure, stopPropagation on the row
checkbox — are guarded at the source level.

See docs/superpowers/specs/2026-07-31-tracked-files-design.md.
"""
import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "src" / "static" / "tracked_files_tab.js"


def _src():
    assert JS.is_file(), f"missing {JS}"
    return JS.read_text()


def test_exports_the_factory_with_the_documented_surface():
    s = _src()
    assert "export function makeTrackedFiles" in s
    for fn in ("refresh", "setCurrent", "destroy"):
        assert re.search(rf"\b{fn}\b", s), f"factory must expose {fn}"


def test_hits_all_four_routes():
    s = _src()
    assert '"/dlc/project/tracked-files"' in s
    assert '"DELETE"' in s and '"POST"' in s
    assert "/opened" in s


def test_paths_are_rendered_with_textContent_never_innerHTML():
    """Tracked paths are user data — innerHTML on them would be an injection."""
    s = _src()
    # innerHTML is allowed ONLY to clear the list ("" assignment), never to interpolate.
    for m in re.finditer(r"innerHTML\s*=\s*(.+)", s):
        assert m.group(1).strip().startswith('""'), f"unsafe innerHTML: {m.group(0)}"


def test_row_checkbox_stops_propagation_so_untracking_never_opens_the_video():
    s = _src()
    assert "stopPropagation" in s


def test_failed_mutations_revert_the_checkbox():
    s = _src()
    # Both the untrack and track failure paths must restore checkbox state.
    assert re.search(r"catch[\s\S]{0,400}?checked\s*=\s*true", s), "untrack failure must re-check"
    assert re.search(r"catch[\s\S]{0,400}?checked\s*=\s*false", s), "track failure must un-check"


def test_uses_the_shared_relative_time_helper():
    s = _src()
    assert 'from "./internal/relative_time.mjs"' in s
    assert "formatRelative(" in s


def test_listeners_are_abortable_for_destroy():
    """Header checkbox and tab button are persistent nodes — listeners must be
    removable or they accumulate across re-wiring."""
    s = _src()
    assert "AbortController" in s
    assert "signal" in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_tracked_files_tab_source.py -v`
Expected: 7 failed — `missing .../tracked_files_tab.js`

- [ ] **Step 3: Write minimal implementation**

Create `SUP/dlc-3D/src/static/tracked_files_tab.js`:

```javascript
// tracked_files_tab.js — "Tracked Files" source tab for the 3D Inline Analysis card.
//
// Owns the tab panel's list, the in-memory set of tracked paths, and the
// track checkbox in the player header. The consumer (inline_analysis_3d.js)
// only constructs it and calls setCurrent() — no tracking logic lives there.
//
// Persistence is per DLC project, served by the main webapp's
// /dlc/project/tracked-files blueprint. The list is a pure DB read: a tracked
// file that has since moved still lists, and only fails when opened.
"use strict";

import { formatRelative } from "./internal/relative_time.mjs";

const API = "/dlc/project/tracked-files";
const JSON_HEADERS = { "Content-Type": "application/json" };

export function makeTrackedFiles({
  tabBtn, refreshBtn, panelEl, listEl, headerCheckbox, headerLabel, onOpen, onError,
}) {
  let _rows = new Map();     // path -> {path, name, dir, tracked_at, last_opened_at}
  let _current = null;       // the path currently open in the player, or null
  const _ac = new AbortController();
  const _sig = { signal: _ac.signal };

  // ── Transport ─────────────────────────────────────────────────────────────

  async function _fetchJson(url, opts) {
    const res = await fetch(url, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.error || `status ${res.status}`);
    return data;
  }

  const _body = (path) => ({ headers: JSON_HEADERS, body: JSON.stringify({ path }) });

  // ── Rendering ─────────────────────────────────────────────────────────────

  function _empty(text) {
    listEl.innerHTML = "";
    const p = document.createElement("p");
    p.className = "explorer-empty";
    p.textContent = text;
    listEl.appendChild(p);
  }

  function _render() {
    if (_rows.size === 0) {
      _empty("No tracked files. Open a video from Browse Folders and tick the box next to its name.");
      return;
    }
    listEl.innerHTML = "";
    const now = Date.now();
    for (const row of _rows.values()) listEl.appendChild(_makeRow(row, now));
  }

  function _makeRow(f, now) {
    const row = document.createElement("div");
    row.className = "fe-video-item";
    row.style.cursor = "pointer";
    row.dataset.path = f.path;

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = true;
    cb.title = "Untrack this file";
    cb.style.cssText = "accent-color:var(--accent);width:13px;height:13px;flex-shrink:0";
    // The row opens the video; the checkbox must not.
    cb.addEventListener("click", (e) => e.stopPropagation(), _sig);
    cb.addEventListener("change", () => _untrack(f.path, cb), _sig);

    const col = document.createElement("div");
    col.style.cssText = "display:flex;flex-direction:column;min-width:0;flex:1";
    const nameEl = document.createElement("span");
    nameEl.textContent = f.name;
    nameEl.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
    const dirEl = document.createElement("span");
    dirEl.textContent = f.dir;
    dirEl.style.cssText = "font-size:.7rem;color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
    col.appendChild(nameEl);
    col.appendChild(dirEl);

    const when = document.createElement("span");
    when.textContent = formatRelative(f.last_opened_at, now);
    when.style.cssText = "font-size:.68rem;color:var(--text-dim);margin-left:auto;flex-shrink:0;padding-left:.4rem";

    row.appendChild(cb);
    row.appendChild(col);
    row.appendChild(when);
    row.addEventListener("click", () => onOpen?.(f.path, f.name), _sig);
    return row;
  }

  function _syncHeader() {
    if (!headerCheckbox) return;
    const wrap = headerLabel || headerCheckbox;
    if (!_current) {
      wrap.classList.add("hidden");
      headerCheckbox.checked = false;
      return;
    }
    wrap.classList.remove("hidden");
    headerCheckbox.checked = _rows.has(_current);
  }

  // ── Mutations ─────────────────────────────────────────────────────────────

  async function _track(path) {
    try {
      await _fetchJson(API, { method: "POST", ..._body(path) });
      await refresh();
    } catch (err) {
      if (headerCheckbox) headerCheckbox.checked = false;   // revert
      onError?.(`Could not track ${path} — ${err.message}`);
    }
  }

  async function _untrack(path, cb) {
    try {
      await _fetchJson(API, { method: "DELETE", ..._body(path) });
      _rows.delete(path);
      _render();
      _syncHeader();
    } catch (err) {
      if (cb) cb.checked = true;                            // revert
      onError?.(`Could not untrack ${path} — ${err.message}`);
    }
  }

  // Ordering is cosmetic, so a failure here never disturbs the open.
  function _noteOpened(path) {
    _fetchJson(API + "/opened", { method: "POST", ..._body(path) }).catch(() => {});
  }

  // ── Public surface ────────────────────────────────────────────────────────

  async function refresh() {
    try {
      const data = await _fetchJson(API);
      _rows = new Map((data.files || []).map((f) => [f.path, f]));
      _render();
    } catch (err) {
      _rows = new Map();
      _empty(err.message);
    }
    _syncHeader();
  }

  // Called with the open video's absolute path, or null when nothing is open /
  // the open thing is not a browse video (project content, frame folders).
  function setCurrent(path) {
    _current = path || null;
    _syncHeader();
    if (_current && _rows.has(_current)) _noteOpened(_current);
  }

  function destroy() {
    _ac.abort();
    _rows = new Map();
    _current = null;
  }

  // ── Wiring ────────────────────────────────────────────────────────────────

  tabBtn?.addEventListener("click", () => refresh(), _sig);
  refreshBtn?.addEventListener("click", (e) => { e.stopPropagation(); refresh(); }, _sig);
  headerCheckbox?.addEventListener("change", () => {
    if (!_current) return;
    if (headerCheckbox.checked) _track(_current);
    else _untrack(_current, headerCheckbox);
  }, _sig);

  return { refresh, setCurrent, destroy };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_tracked_files_tab_source.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/tracked_files_tab.js dlc-3D/tests/test_tracked_files_tab_source.py
git commit -m "feat(tracked-files): tracked-files tab factory (list, checkboxes, header sync)"
```

---

### Task 6: Wire into the card + fix the silent-open bug

**Files:**
- Modify: `SUP/dlc-3D/src/static/inline_analysis_3d.js` — import block (~line 28), `_iaOpenBrowseVideo` (2300-2319), `_resetForOpen` (2322-2394), `_wireLauncher` (2573-2600)
- Test: `SUP/dlc-3D/tests/test_tracked_files_wiring.py`

**Interfaces:**
- Consumes: Task 5's `makeTrackedFiles(...)` and its `refresh` / `setCurrent` / `destroy`; Task 4's DOM ids.
- Produces: module-level `_trackedFiles` handle and `_iaLauncherError(msg)`. Nothing later depends on these.

- [ ] **Step 1: Write the failing test**

Create `SUP/dlc-3D/tests/test_tracked_files_wiring.py`:

```python
"""Static guards for the Tracked Files wiring in inline_analysis_3d.js.

Also guards the bug this feature depends on fixing: _iaOpenBrowseVideo used to
swallow a video-info error and open an EMPTY viewer at fps 30 / 0 frames, so a
tracked file that had moved looked like a broken player instead of an error.

See docs/superpowers/specs/2026-07-31-tracked-files-design.md.
"""
import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "src" / "static" / "inline_analysis_3d.js"


def _src():
    assert JS.is_file(), f"missing {JS}"
    return JS.read_text()


def _fn(name):
    """Return the source of a top-level `async function name(...)` body."""
    s = _src()
    m = re.search(rf"^(?:async )?function {name}\(", s, re.M)
    assert m, f"missing function {name}"
    nxt = re.search(r"^(?:async )?function ", s[m.end():], re.M)
    return s[m.start(): m.end() + (nxt.start() if nxt else len(s))]


def test_imports_and_constructs_the_tracked_files_factory():
    s = _src()
    assert 'from "./tracked_files_tab.js"' in s
    assert "makeTrackedFiles(" in s


def test_factory_is_constructed_in_the_launcher_wiring():
    assert "makeTrackedFiles(" in _fn("_wireLauncher")


def test_open_browse_video_reports_current_path_to_the_tracker():
    body = _fn("_iaOpenBrowseVideo")
    assert re.search(r"_trackedFiles\??\.?setCurrent\(\s*absPath\s*\)", body) or \
           re.search(r"_trackedFiles\?\.setCurrent\(absPath\)", body), \
        "_iaOpenBrowseVideo must call _trackedFiles?.setCurrent(absPath)"


def test_reset_clears_the_tracker_so_the_checkbox_hides_in_other_modes():
    body = _fn("_resetForOpen")
    assert re.search(r"_trackedFiles\?\.setCurrent\(\s*null\s*\)", body), \
        "_resetForOpen must call _trackedFiles?.setCurrent(null)"


def test_open_browse_video_aborts_on_a_video_info_error():
    """Regression: the old bare `catch { _fps = 30; _frameCount = 0; }` fallback
    silently opened an empty viewer for a missing file. Do not re-introduce it."""
    body = _fn("_iaOpenBrowseVideo")
    assert "res.ok" in body or "response.ok" in body, "must check the HTTP status"
    assert re.search(r"info\.error|data\.error", body), "must check the JSON error field"
    assert "return" in body, "must abort the open"
    assert not re.search(r"catch\s*\([^)]*\)\s*\{\s*_fps\s*=\s*30", body), \
        "the silent fps-30 fallback must be gone"


def test_open_browse_video_reveals_the_player_only_after_info_resolves():
    body = _fn("_iaOpenBrowseVideo")
    assert body.index("annotate/video-info") < body.index("ia3d-player-section"), \
        "video-info must resolve before the player section is revealed"


def test_launcher_error_helper_targets_the_launcher_error_element():
    s = _src()
    assert "_iaLauncherError" in s
    assert "ia3d-launcher-error" in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_tracked_files_wiring.py -v`
Expected: 7 failed

- [ ] **Step 3: Write minimal implementation**

**3a.** Add the import after the `makePose3dViewer` import (~line 28):

```javascript
import { makeTrackedFiles } from "./tracked_files_tab.js";
```

**3b.** Add the module-level handle next to the other module state (near `let _markerEditor = null;`):

```javascript
let _trackedFiles = null; // Tracked Files tab controller (composed in _wireLauncher)
```

**3c.** Add the launcher error helper directly above `_iaOpenBrowseVideo`:

```javascript
// Launcher-level error line. Used when an open ABORTS — the player section is
// never revealed in that case, so #ia3d-status (which lives inside it) would
// be invisible. Pass "" to clear.
function _iaLauncherError(msg) {
  const el = $("ia3d-launcher-error");
  if (!el) return;
  el.textContent = msg || "";
  el.style.color = msg ? "var(--danger, #e66)" : "";
}
```

**3d.** Replace the whole of `_iaOpenBrowseVideo` (lines 2300-2319) with:

```javascript
async function _iaOpenBrowseVideo(absPath, name) {
  // Resolve video info BEFORE mutating any state: a missing or unreadable file
  // must abort the open instead of silently loading an empty viewer. This is
  // the path a tracked file takes after its video has moved.
  let info;
  try {
    const res = await fetch(`/annotate/video-info?path=${encodeURIComponent(absPath)}`);
    info = await res.json().catch(() => ({}));
    if (!res.ok || info.error) throw new Error(info.error || `status ${res.status}`);
  } catch (err) {
    _iaLauncherError(`Cannot open ${absPath} — ${err.message}. Fix the path or untrack this entry.`);
    return;
  }
  _iaLauncherError("");
  _resetForOpen();
  _iaMode = "browse-video";
  _browsePath = absPath;
  _primaryRel = absPath;
  const nameEl = $("ia3d-selected-name");
  if (nameEl) nameEl.textContent = name;
  _fps = info.fps || 30;
  _frameCount = info.frame_count || 0;
  $("ia3d-player-section")?.classList.remove("hidden");
  const v = _ensureViewer();
  if (!v) return;
  _loadAllQuickTags();
  await v.load({ videoPath: _primaryRel, frameCount: _frameCount, framesMode: false, siblingPath: undefined });
  // Reveal the track checkbox for this path and stamp last-opened if tracked.
  _trackedFiles?.setCurrent(absPath);
}
```

**3e.** In `_resetForOpen`, add this immediately after `_siblingAvailable = false;`:

```javascript
  _trackedFiles?.setCurrent(null);   // hide the track checkbox until a browse video opens
```

**3f.** In `_wireLauncher`, add the third tab. Replace the two existing tab handlers with an array-driven switcher (three hand-written copies of the same block is where it rots):

```javascript
  // Tab switching — one table, three tabs.
  const TABS = [
    { btn: "ia3d-tab-project", panel: "ia3d-tab-project-panel" },
    { btn: "ia3d-tab-browse",  panel: "ia3d-tab-browse-panel"  },
    { btn: "ia3d-tab-tracked", panel: "ia3d-tab-tracked-panel" },
  ];
  function _showTab(id) {
    TABS.forEach((t) => {
      const on = t.btn === id;
      $(t.btn)?.classList.toggle("active", on);
      $(t.panel)?.classList.toggle("hidden", !on);
    });
  }
  TABS.forEach((t) => $(t.btn)?.addEventListener("click", () => _showTab(t.btn)));
  $("ia3d-tab-browse")?.addEventListener("click", () => {
    if (!_iaBrowsePath) {
      const startPath = state.userDataDir || state.dataDir || "/";
      _iaRefreshBrowse(startPath);
    }
  });

  // Tracked Files tab controller. Owns its list, its checkboxes and the
  // player-header track checkbox; this module only reports the current path.
  _trackedFiles = makeTrackedFiles({
    tabBtn: $("ia3d-tab-tracked"),
    refreshBtn: $("ia3d-tracked-refresh"),
    panelEl: $("ia3d-tab-tracked-panel"),
    listEl: $("ia3d-tracked-list"),
    headerCheckbox: $("ia3d-track-checkbox"),
    headerLabel: $("ia3d-track-label"),
    onOpen: (path, name) => _iaOpenBrowseVideo(path, name),
    onError: (msg) => _iaLauncherError(msg),
  });
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_tracked_files_wiring.py -v`
Expected: 7 passed

- [ ] **Step 5: Verify nothing else broke**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/ -q --ignore=tests/e2e`
Expected: the pre-existing **8** failures and no others. The inline-3D markup/wiring guards (`test_inline_3d_*.py`, `test_inline_analysis_3d_ui_isolation.py`) must all still pass — they assert on the same file and the same card.

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/inline_analysis_3d.js dlc-3D/tests/test_tracked_files_wiring.py
git commit -m "feat(tracked-files): wire the tab into the 3D card; abort open on missing video"
```

---

### Task 7: Deploy and verify in the running app

**Files:** none — deployment and verification only.

**Interfaces:**
- Consumes: everything above.
- Produces: a running app serving the feature.

Dispatch this task to a **subagent** (the user asked for deployment to be handled by one). Give it this brief verbatim:

> Deploy and verify the tracked-files feature.
>
> 1. `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart flask dlc-3d`. The flask service must restart to register the new `dlc_tracked_files` blueprint; dlc-3d must restart to re-read the bind-mounted `card_inline_analysis_3d.html` partial. Do NOT rebuild images and do NOT touch `worker` or `worker-tf`.
> 2. Wait for both to report healthy (`docker compose ps`), then check logs for import errors: `docker compose logs --tail=50 flask dlc-3d`. A traceback mentioning `tracked_files` is a hard failure — report it and stop.
> 3. Verify the route is registered and correctly refuses an unauthenticated/no-project request: `curl -si http://localhost:5000/dlc/project/tracked-files | head -20`. Expect HTTP 200 with a JSON body, or a 400 whose body is `{"error": "No active DLC project."}` — both prove the blueprint is live. A **404** means registration failed.
> 4. Verify the card's assets load: `curl -sI http://localhost:5000/dlc-3d/static/tracked_files_tab.js` and `.../static/internal/relative_time.mjs` — both must be HTTP 200, not 404.
> 5. Confirm the markup is being served: `curl -s http://localhost:5000/dlc-3d/ | grep -c 'ia3d-tab-tracked'` must be ≥ 1.
>
> Report: the restart result, any log errors, and the HTTP status of each of the four checks. Do not fix anything — report findings only.

- [ ] **Step 1: Dispatch the deployment subagent with the brief above**

- [ ] **Step 2: Act on the report**

If any check failed, fix it in this session, re-run the affected task's tests, and re-dispatch the subagent. If all four checks passed, continue.

- [ ] **Step 3: Manual smoke test in the browser**

At `http://localhost:5000/dlc-3d/`, with a DLC project active in the main webapp:

1. Open the 3D Inline Analysis card → a third **Tracked Files** tab is visible.
2. Click it → *"No tracked files. Open a video from Browse Folders and tick the box next to its name."*
3. **Browse Folders** → navigate to a stereo session → click a `cam0` video → it opens as before, and a checkbox appears in front of the filename in the player header, unticked.
4. Tick it → **Tracked Files** now lists the file with its folder and "just now".
5. **← Back** → the header checkbox disappears.
6. **Tracked Files** → click the row → the video reopens with the companion CSV, sibling camera, kinematic layers and calibration all resolving exactly as the Browse path does.
7. Untick the row's checkbox → it disappears from the list.
8. Track a file, then rename it on disk, then click its row → the open **aborts** with "Cannot open … Fix the path or untrack this entry." and the player does not appear. Rename it back.
9. **Project Content** → open a labeled video → the track checkbox stays hidden (browse videos only).

- [ ] **Step 4: Commit any fixes**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git status   # commit only if step 2 or 3 required changes
```

---

## Self-Review

**Spec coverage** — every spec section maps to a task: store → Task 1; API → Task 2; `relative_time.mjs` → Task 3; DOM changes → Task 4; `tracked_files_tab.js` + behaviour → Task 5; `inline_analysis_3d.js` wiring + the video-info abort → Task 6; the four test suites → Tasks 1-6; deployment → Task 7.

**Deviation from the spec, deliberate:** the spec did not name a place to show the open-failure message. `#ia3d-status` lives inside `#ia3d-player-section`, which an aborted open never reveals, so Task 4 adds `#ia3d-launcher-error` above the player section and Task 6 adds `_iaLauncherError()`. Same behaviour the spec describes, with a visible home.

**Type consistency:** the store returns `path` / `tracked_at` / `last_opened_at`; the routes add `name` / `dir` and preserve those key names; the client reads exactly `f.path`, `f.name`, `f.dir`, `f.last_opened_at`. `formatRelative(iso, nowMs)` is defined in Task 3 and called with that signature in Task 5. `makeTrackedFiles` options in Task 5 match the object built in Task 6 key-for-key (`tabBtn`, `refreshBtn`, `panelEl`, `listEl`, `headerCheckbox`, `headerLabel`, `onOpen`, `onError`).

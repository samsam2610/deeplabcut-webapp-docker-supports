# Progress Arrow Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each DLC project one configurable progress arrow bar, and render it — editable in place — next to every tracked file, on both the 2D and 3D pages.

**Architecture:** Three new tables in the existing `<project>/tracked_files.sqlite`, a pure store + blueprint over them, and a shared DOM component. The client modules that render a tracked-file row are promoted out of dlc-3D into the main webapp so one implementation serves the new card, the 3D tab and the 2D tab.

**Tech Stack:** Python 3.9 + Flask + sqlite3 (stdlib); vanilla ES modules. Tests: pytest both repos, `node` for pure `.mjs`.

**Spec:** `docs/superpowers/specs/2026-08-01-progress-arrow-bar-design.md`

## Global Constraints

- `MAIN` = `/home/sam/docker-images/deeplabcut-webapp-docker`. `SUP` = `/home/sam/docker-images/deeplabcut-webapp-docker-supports`. Separate git checkouts — commit in the repo you touched.
- Python is **3.9**: every module needs `from __future__ import annotations` before `X | None` annotations.
- Segment count is **0–10**, enforced in the store (`ValueError`), not only in the UI.
- IDs: `seg_` / `opt_` + 12 hex chars from `secrets.token_hex(6)`. **Never reused**, never regenerated on rename or recolour.
- Colours are `#rrggbb`, validated on **every** write and before **every** `style` write. They reach `style.setProperty()`, so an unvalidated value is a CSS-injection vector.
- **No delete cascade** anywhere: dropping a segment or option never deletes a `progress_value` row.
- All client rendering of server strings uses `textContent`, never `innerHTML`.
- Known-failure baselines — do **not** attribute these to this work: **8** in dlc-3D, **16** in the main webapp (all `test_dlc_celery_tasks.py`, `KeyError: 'n_machine'`).
- Run pytest from a repo root so `pytest.ini` disk-fill guards apply. In dlc-3D always pass `--ignore=tests/e2e`. Never run the e2e suites.
- Node is **v16**: `node --test <dir>` finds nothing and collapses per-file output. Run each `.mjs` file directly (`node path/to/test.mjs`).

---

### Task 1: Progress-bar store

**Files:**
- Create: `MAIN/src/dlc/progress_bar.py`
- Test: `MAIN/src/tests/test_progress_bar_store.py`

**Interfaces:**
- Consumes: `MAIN/src/dlc/tracked_files.py` — reuses its DB file `<project>/tracked_files.sqlite` (constant `tracked_files.DB_FILENAME`).
- Produces: `get_definition(project_path) -> dict`; `save_definition(project_path, segments) -> dict`; `get_values(project_path, video_paths) -> dict`; `set_value(project_path, video_path, segment_id, option_id) -> None`; `MAX_SEGMENTS = 10`.

- [ ] **Step 1: Write the failing test**

Create `MAIN/src/tests/test_progress_bar_store.py`:

```python
"""Tests for src/dlc/progress_bar.py — definition + per-file values."""
from __future__ import annotations
from pathlib import Path

import pytest

from dlc import progress_bar as pb
from dlc import tracked_files as tf


@pytest.fixture
def project(tmp_path: Path) -> Path:
    p = tmp_path / "Proj-2026-08-01"
    p.mkdir()
    return p


def _seg(name, options):
    return {"name": name, "options": options}


def test_fresh_project_has_no_segments(project):
    assert pb.get_definition(project) == {"segments": []}


def test_save_then_get_assigns_ids_and_preserves_order(project):
    pb.save_definition(project, [
        _seg("Label", [{"label": "Todo", "color": "#888888"},
                       {"label": "Done", "color": "#2ea043"}]),
        _seg("QC", [{"label": "Pending", "color": "#e0a800"}]),
    ])
    got = pb.get_definition(project)["segments"]
    assert [s["name"] for s in got] == ["Label", "QC"]
    assert [o["label"] for o in got[0]["options"]] == ["Todo", "Done"]
    assert got[0]["segment_id"].startswith("seg_")
    assert got[0]["options"][0]["option_id"].startswith("opt_")


def test_rename_and_recolour_keep_ids(project):
    pb.save_definition(project, [_seg("Label", [{"label": "Todo", "color": "#888888"}])])
    before = pb.get_definition(project)["segments"][0]
    sid, oid = before["segment_id"], before["options"][0]["option_id"]

    pb.save_definition(project, [{
        "segment_id": sid, "name": "Labelling",
        "options": [{"option_id": oid, "label": "Not started", "color": "#111111"}],
    }])
    after = pb.get_definition(project)["segments"][0]
    assert after["segment_id"] == sid
    assert after["name"] == "Labelling"
    assert after["options"][0]["option_id"] == oid
    assert after["options"][0]["color"] == "#111111"


def test_values_round_trip_and_clear(project):
    pb.save_definition(project, [_seg("Label", [{"label": "Done", "color": "#2ea043"}])])
    seg = pb.get_definition(project)["segments"][0]
    sid, oid = seg["segment_id"], seg["options"][0]["option_id"]

    pb.set_value(project, "/data/a.avi", sid, oid)
    assert pb.get_values(project, ["/data/a.avi"]) == {"/data/a.avi": {sid: oid}}

    pb.set_value(project, "/data/a.avi", sid, None)
    assert pb.get_values(project, ["/data/a.avi"]) == {}


def test_get_values_batches_and_omits_files_without_values(project):
    pb.save_definition(project, [_seg("Label", [{"label": "Done", "color": "#2ea043"}])])
    seg = pb.get_definition(project)["segments"][0]
    sid, oid = seg["segment_id"], seg["options"][0]["option_id"]
    pb.set_value(project, "/data/a.avi", sid, oid)

    out = pb.get_values(project, ["/data/a.avi", "/data/b.avi"])
    assert set(out) == {"/data/a.avi"}


def test_deleting_a_segment_leaves_its_values_in_the_db(project):
    """No cascade: the value survives so re-adding the ID restores it."""
    pb.save_definition(project, [_seg("Label", [{"label": "Done", "color": "#2ea043"}])])
    seg = pb.get_definition(project)["segments"][0]
    sid, oid = seg["segment_id"], seg["options"][0]["option_id"]
    pb.set_value(project, "/data/a.avi", sid, oid)

    pb.save_definition(project, [])                       # drop every segment
    assert pb.get_definition(project) == {"segments": []}
    assert pb.get_values(project, ["/data/a.avi"]) == {"/data/a.avi": {sid: oid}}

    pb.save_definition(project, [{                        # re-add under the SAME id
        "segment_id": sid, "name": "Label",
        "options": [{"option_id": oid, "label": "Done", "color": "#2ea043"}],
    }])
    assert pb.get_values(project, ["/data/a.avi"]) == {"/data/a.avi": {sid: oid}}


def test_rejects_more_than_ten_segments(project):
    too_many = [_seg(f"S{i}", []) for i in range(11)]
    with pytest.raises(ValueError):
        pb.save_definition(project, too_many)
    assert pb.get_definition(project) == {"segments": []}


def test_accepts_exactly_ten_segments(project):
    pb.save_definition(project, [_seg(f"S{i}", []) for i in range(10)])
    assert len(pb.get_definition(project)["segments"]) == 10


def test_rejects_malformed_colour(project):
    with pytest.raises(ValueError):
        pb.save_definition(project, [_seg("Label", [{"label": "X", "color": "red"}])])
    with pytest.raises(ValueError):
        pb.save_definition(project, [
            _seg("Label", [{"label": "X", "color": "#fff; background:url(x)"}])
        ])


def test_duplicate_colours_are_allowed(project):
    """No uniqueness constraint — same colour twice in one segment is fine."""
    pb.save_definition(project, [_seg("Label", [
        {"label": "A", "color": "#2ea043"},
        {"label": "B", "color": "#2ea043"},
    ])])
    assert len(pb.get_definition(project)["segments"][0]["options"]) == 2


def test_upgrades_a_v1_db_in_place_without_losing_tracked_rows(project):
    """tracked_files.py created this DB at schema v1; adding the progress
    tables must not disturb it."""
    tf.track(project, "/data/a.avi")
    pb.save_definition(project, [_seg("Label", [])])
    assert [r["path"] for r in tf.list_tracked(project)] == ["/data/a.avi"]
    assert len(pb.get_definition(project)["segments"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_progress_bar_store.py -q`
Expected: collection error — `cannot import name 'progress_bar' from 'dlc'`

- [ ] **Step 3: Write minimal implementation**

Create `MAIN/src/dlc/progress_bar.py`:

```python
"""
Per-project progress arrow bar: one ordered set of segments, each offering
options that carry a user-chosen colour, plus one value per (file, segment).

Stored in the SAME DB file as tracked_files.py — <project>/tracked_files.sqlite
— because the values belong to tracked files. Schema version moves 1 -> 2;
CREATE TABLE IF NOT EXISTS means existing v1 DBs upgrade on first touch with no
migration script.

Segment and option IDs are stable and never reused: renaming or recolouring
must not disturb stored values. Deleting a segment or option does NOT delete
the values referencing it — orphaned values stay in the DB, render as unset,
and come back if the same ID is restored.

Imports no Flask, no DLC, no Redis, and never touches the filesystem beyond
its own DB file.

Schema (v2 additions):
    progress_segment(segment_id TEXT PRIMARY KEY, position INTEGER NOT NULL,
                     name TEXT NOT NULL)
    progress_option(option_id TEXT PRIMARY KEY, segment_id TEXT NOT NULL,
                    position INTEGER NOT NULL, label TEXT NOT NULL,
                    color TEXT NOT NULL)
    progress_value(video_path TEXT NOT NULL, segment_id TEXT NOT NULL,
                   option_id TEXT NOT NULL, set_at TEXT NOT NULL,
                   PRIMARY KEY (video_path, segment_id))
"""
from __future__ import annotations

import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .tracked_files import DB_FILENAME

MAX_SEGMENTS = 10
SCHEMA_VERSION = "2"

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _db_path(project_path) -> Path:
    return Path(project_path) / DB_FILENAME


@contextmanager
def _connect(project_path):
    conn = sqlite3.connect(str(_db_path(project_path)), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        _ensure_schema(conn)
        yield conn
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress_segment (
            segment_id TEXT PRIMARY KEY,
            position   INTEGER NOT NULL,
            name       TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress_option (
            option_id  TEXT PRIMARY KEY,
            segment_id TEXT NOT NULL,
            position   INTEGER NOT NULL,
            label      TEXT NOT NULL,
            color      TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress_value (
            video_path TEXT NOT NULL,
            segment_id TEXT NOT NULL,
            option_id  TEXT NOT NULL,
            set_at     TEXT NOT NULL,
            PRIMARY KEY (video_path, segment_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                 ("schema_version", SCHEMA_VERSION))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def is_valid_color(value) -> bool:
    return isinstance(value, str) and bool(_HEX_COLOR_RE.match(value))


def get_definition(project_path) -> dict:
    """The ordered segments, each with its ordered options."""
    if not _db_path(project_path).is_file():
        return {"segments": []}
    with _connect(project_path) as conn:
        segs = conn.execute(
            "SELECT segment_id, name FROM progress_segment ORDER BY position"
        ).fetchall()
        opts = conn.execute(
            "SELECT option_id, segment_id, label, color FROM progress_option "
            "ORDER BY position"
        ).fetchall()
    by_seg: dict = {}
    for oid, sid, label, color in opts:
        by_seg.setdefault(sid, []).append(
            {"option_id": oid, "label": label, "color": color})
    return {"segments": [
        {"segment_id": sid, "name": name, "options": by_seg.get(sid, [])}
        for sid, name in segs
    ]}


def save_definition(project_path, segments) -> dict:
    """Replace the definition. Entries carrying an id keep it; entries without
    one get a fresh id. Segments/options absent from `segments` are removed
    from the definition but their progress_value rows are left untouched.

    Raises ValueError on >MAX_SEGMENTS or a colour that is not '#rrggbb'.
    """
    segments = list(segments or [])
    if len(segments) > MAX_SEGMENTS:
        raise ValueError(f"at most {MAX_SEGMENTS} segments (got {len(segments)})")
    # Validate everything BEFORE opening a write transaction, so a bad payload
    # never leaves a half-applied definition behind.
    for seg in segments:
        for opt in seg.get("options") or []:
            if not is_valid_color(opt.get("color")):
                raise ValueError(f"invalid colour: {opt.get('color')!r}")

    rows_seg = []
    rows_opt = []
    for s_pos, seg in enumerate(segments):
        sid = seg.get("segment_id") or _new_id("seg")
        rows_seg.append((sid, s_pos, str(seg.get("name", ""))))
        for o_pos, opt in enumerate(seg.get("options") or []):
            oid = opt.get("option_id") or _new_id("opt")
            rows_opt.append((oid, sid, o_pos, str(opt.get("label", "")), opt["color"]))

    with _connect(project_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Full replace of the DEFINITION only. progress_value is never touched.
            conn.execute("DELETE FROM progress_option")
            conn.execute("DELETE FROM progress_segment")
            conn.executemany(
                "INSERT INTO progress_segment(segment_id, position, name) VALUES (?,?,?)",
                rows_seg)
            conn.executemany(
                "INSERT INTO progress_option(option_id, segment_id, position, label, color) "
                "VALUES (?,?,?,?,?)", rows_opt)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return get_definition(project_path)


def get_values(project_path, video_paths) -> dict:
    """{video_path: {segment_id: option_id}} for the given paths, batched into
    one query. Paths with no stored value are omitted entirely."""
    paths = [p for p in (video_paths or []) if p]
    if not paths or not _db_path(project_path).is_file():
        return {}
    out: dict = {}
    with _connect(project_path) as conn:
        # Chunked so a huge tracked list cannot exceed SQLite's variable limit.
        for i in range(0, len(paths), 400):
            chunk = paths[i:i + 400]
            marks = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT video_path, segment_id, option_id FROM progress_value "
                f"WHERE video_path IN ({marks})", chunk
            ).fetchall()
            for path, sid, oid in rows:
                out.setdefault(path, {})[sid] = oid
    return out


def set_value(project_path, video_path: str, segment_id: str, option_id) -> None:
    """Set one segment's option for one file. option_id=None clears it."""
    with _connect(project_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if option_id is None:
                conn.execute(
                    "DELETE FROM progress_value WHERE video_path=? AND segment_id=?",
                    (video_path, segment_id))
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO progress_value"
                    "(video_path, segment_id, option_id, set_at) VALUES (?,?,?,?)",
                    (video_path, segment_id, option_id, _now()))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_progress_bar_store.py -q`
Expected: 11 passed

- [ ] **Step 5: Confirm the tracked-files store still passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_store.py src/tests/test_tracked_files_routes.py -q`
Expected: 15 passed

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/progress_bar.py src/tests/test_progress_bar_store.py
git commit -m "feat(progress-bar): per-project segment/option definition + per-file values"
```

---

### Task 2: Progress-bar blueprint

**Files:**
- Create: `MAIN/src/dlc/progress_bar_routes.py`
- Modify: `MAIN/src/app.py` (import block ~line 191, registration ~line 208), `MAIN/src/dlc/tracked_files_routes.py` (the `list_tracked_files` view)
- Test: `MAIN/src/tests/test_progress_bar_routes.py`

**Interfaces:**
- Consumes: Task 1's `get_definition` / `save_definition` / `get_values` / `set_value` / `MAX_SEGMENTS`.
- Produces: `GET|PUT /dlc/project/progress-bar`, `PUT /dlc/project/progress-bar/value`, and a `progress` key on every file in `GET /dlc/project/tracked-files`. Task 4 and Task 5 consume these.

- [ ] **Step 1: Write the failing test**

Create `MAIN/src/tests/test_progress_bar_routes.py`:

```python
"""Tests for the dlc_progress_bar blueprint."""
from __future__ import annotations
import json
from pathlib import Path

import pytest


def _activate_project(client, fake_redis, project_path: Path):
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
def bar_project(flask_test_client):
    """A project INSIDE data_dir — _sec_check rejects anything outside it."""
    client, _app, fake_redis, data_dir, _udd = flask_test_client
    proj = data_dir / "BarTest-2026-08-01"
    proj.mkdir()
    (proj / "config.yaml").write_text("scorer: TestScorer\n")
    _activate_project(client, fake_redis, proj)
    return client, proj


def _save(client, segments):
    return client.put("/dlc/project/progress-bar", json={"segments": segments})


def test_requires_active_project(flask_test_client):
    client = flask_test_client[0]
    assert client.get("/dlc/project/progress-bar").status_code == 400


def test_definition_starts_empty(bar_project):
    client, _ = bar_project
    rv = client.get("/dlc/project/progress-bar")
    assert rv.status_code == 200
    assert rv.get_json()["segments"] == []


def test_put_then_get_round_trip_with_server_ids(bar_project):
    client, _ = bar_project
    rv = _save(client, [{"name": "Label", "options": [
        {"label": "Todo", "color": "#888888"}]}])
    assert rv.status_code == 200
    seg = rv.get_json()["segments"][0]
    assert seg["segment_id"].startswith("seg_")
    assert seg["options"][0]["option_id"].startswith("opt_")

    again = client.get("/dlc/project/progress-bar").get_json()["segments"][0]
    assert again["segment_id"] == seg["segment_id"]


def test_rejects_more_than_ten_segments(bar_project):
    client, _ = bar_project
    rv = _save(client, [{"name": f"S{i}", "options": []} for i in range(11)])
    assert rv.status_code == 400
    assert client.get("/dlc/project/progress-bar").get_json()["segments"] == []


def test_rejects_malformed_colour(bar_project):
    client, _ = bar_project
    rv = _save(client, [{"name": "L", "options": [
        {"label": "X", "color": "#fff; background:url(x)"}]}])
    assert rv.status_code == 400


def test_set_and_clear_a_value(bar_project):
    client, _ = bar_project
    seg = _save(client, [{"name": "Label", "options": [
        {"label": "Done", "color": "#2ea043"}]}]).get_json()["segments"][0]
    sid, oid = seg["segment_id"], seg["options"][0]["option_id"]
    client.post("/dlc/project/tracked-files", json={"path": "/data/a.avi"})

    rv = client.put("/dlc/project/progress-bar/value",
                    json={"path": "/data/a.avi", "segment_id": sid, "option_id": oid})
    assert rv.status_code == 200
    files = client.get("/dlc/project/tracked-files").get_json()["files"]
    assert files[0]["progress"] == {sid: oid}

    client.put("/dlc/project/progress-bar/value",
               json={"path": "/data/a.avi", "segment_id": sid, "option_id": None})
    files = client.get("/dlc/project/tracked-files").get_json()["files"]
    assert files[0]["progress"] == {}


def test_tracked_files_always_carries_a_progress_object(bar_project):
    """Even with no bar defined, the key exists so the client never branches."""
    client, _ = bar_project
    client.post("/dlc/project/tracked-files", json={"path": "/data/a.avi"})
    files = client.get("/dlc/project/tracked-files").get_json()["files"]
    assert files[0]["progress"] == {}


def test_value_write_requires_a_path_and_segment(bar_project):
    client, _ = bar_project
    assert client.put("/dlc/project/progress-bar/value",
                      json={"segment_id": "seg_x", "option_id": None}).status_code == 400
    assert client.put("/dlc/project/progress-bar/value",
                      json={"path": "/data/a.avi", "option_id": None}).status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_progress_bar_routes.py -q`
Expected: failures — 404 on every `/dlc/project/progress-bar` call

- [ ] **Step 3: Write minimal implementation**

Create `MAIN/src/dlc/progress_bar_routes.py`:

```python
"""
Progress arrow bar — Flask Blueprint.

Routes
------
GET /dlc/project/progress-bar         The project's segment/option definition.
PUT /dlc/project/progress-bar         Replace the definition (ids preserved).
PUT /dlc/project/progress-bar/value   Set/clear one segment for one file.

Per-file values are READ through GET /dlc/project/tracked-files, which carries
a `progress` object per file — one batched query instead of an N+1.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from flask import Blueprint, jsonify, request

from . import ctx as _ctx
from . import progress_bar as _store
from .labeling import _dlc_key, _sec_check

bp = Blueprint("dlc_progress_bar", __name__)

_ROUTE = "/dlc/project/progress-bar"


def _project_path_checked() -> tuple:
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


@bp.route(_ROUTE, methods=["GET"])
def get_progress_bar():
    pp, err = _project_path_checked()
    if err:
        return jsonify({"error": err}), 400
    try:
        return jsonify(_store.get_definition(pp))
    except sqlite3.Error as exc:
        return jsonify({"error": f"progress-bar DB error: {exc}"}), 500


@bp.route(_ROUTE, methods=["PUT"])
def put_progress_bar():
    pp, err = _project_path_checked()
    if err:
        return jsonify({"error": err}), 400
    body = request.get_json(silent=True) or {}
    segments = body.get("segments")
    if not isinstance(segments, list):
        return jsonify({"error": "segments must be a list"}), 400
    try:
        definition = _store.save_definition(pp, segments)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except sqlite3.Error as exc:
        return jsonify({"error": f"progress-bar DB error: {exc}"}), 500
    return jsonify({"ok": True, **definition})


@bp.route(_ROUTE + "/value", methods=["PUT"])
def put_progress_value():
    pp, err = _project_path_checked()
    if err:
        return jsonify({"error": err}), 400
    body = request.get_json(silent=True) or {}
    path = body.get("path", "")
    segment_id = body.get("segment_id", "")
    if not isinstance(path, str) or not path.strip():
        return jsonify({"error": "path required"}), 400
    if not isinstance(segment_id, str) or not segment_id.strip():
        return jsonify({"error": "segment_id required"}), 400
    option_id = body.get("option_id")
    if option_id is not None and not isinstance(option_id, str):
        return jsonify({"error": "option_id must be a string or null"}), 400
    try:
        _store.set_value(pp, path.strip(), segment_id.strip(), option_id)
    except sqlite3.Error as exc:
        return jsonify({"error": f"progress-bar DB error: {exc}"}), 500
    return jsonify({"ok": True})
```

Register it in `MAIN/src/app.py` — import next to the tracked-files one:

```python
from dlc.tracked_files_routes import bp as _dlc_tracked_files_bp
from dlc.progress_bar_routes import bp as _dlc_progress_bar_bp
```

and register it directly after:

```python
app.register_blueprint(_dlc_tracked_files_bp)
app.register_blueprint(_dlc_progress_bar_bp)
```

Then add `progress` to the tracked-files listing. In
`MAIN/src/dlc/tracked_files_routes.py`, add the import at the top:

```python
from . import progress_bar as _progress
```

and replace the body of `list_tracked_files`'s `files = [...]` construction with:

```python
    paths = [r["path"] for r in rows]
    try:
        values = _progress.get_values(pp, paths)
    except sqlite3.Error:
        values = {}          # progress is decorative here; never fail the listing
    files = [
        {
            "path": r["path"],
            "name": Path(r["path"]).name,
            "dir": str(Path(r["path"]).parent),
            "tracked_at": r["tracked_at"],
            "last_opened_at": r["last_opened_at"],
            "progress": values.get(r["path"], {}),
        }
        for r in rows
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_progress_bar_routes.py src/tests/test_tracked_files_routes.py -q`
Expected: 8 + 9 = 17 passed

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/progress_bar_routes.py src/tests/test_progress_bar_routes.py \
        src/app.py src/dlc/tracked_files_routes.py
git commit -m "feat(progress-bar): blueprint + progress on the tracked-files listing"
```

---

### Task 3: Promote the shared client modules

Moves `relative_time.mjs` and `tracked_files_tab.js` out of dlc-3D into the main
webapp so the new card, the 3D tab and the 2D tab share one implementation.
Adds `hex_color.mjs`. Behaviour must not change in this task.

**Files:**
- Create: `MAIN/src/static/js/components/hex_color.mjs`, `MAIN/src/static/js/components/relative_time.mjs`, `MAIN/src/static/js/components/tracked_files_tab.js`, `MAIN/src/tests/unit/test_relative_time.mjs`, `MAIN/src/tests/unit/test_hex_color.mjs`, `MAIN/src/tests/README-unit-mjs.md`
- Delete: `SUP/dlc-3D/src/static/internal/relative_time.mjs`, `SUP/dlc-3D/src/static/tracked_files_tab.js`, `SUP/dlc-3D/tests/unit/test_relative_time.mjs`, `SUP/dlc-3D/tests/test_tracked_files_tab_source.py`
- Modify: `SUP/dlc-3D/src/static/inline_analysis_3d.js` (import line), `SUP/dlc-3D/tests/test_tracked_files_wiring.py` (import assertion)
- Test: `MAIN/src/tests/test_tracked_files_tab_source.py` (moved from dlc-3D, paths updated)

**Interfaces:**
- Consumes: nothing new.
- Produces: `/static/js/components/tracked_files_tab.js` exporting `makeTrackedFiles({tabBtn, refreshBtn, panelEl, listEl, headerCheckbox, headerLabel, onOpen, onError}) -> {refresh, setCurrent, destroy}`; `/static/js/components/relative_time.mjs` exporting `formatRelative(iso, nowMs)`; `/static/js/components/hex_color.mjs` exporting `isValidHexColor(value)`. Tasks 4–6 import these by absolute URL.

- [ ] **Step 1: Write the failing test**

Create `MAIN/src/tests/unit/test_hex_color.mjs`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { isValidHexColor } from "../../static/js/components/hex_color.mjs";

test("isValidHexColor: accepts #rrggbb in either case", () => {
  assert.equal(isValidHexColor("#2ea043"), true);
  assert.equal(isValidHexColor("#2EA043"), true);
});

test("isValidHexColor: rejects anything that is not exactly #rrggbb", () => {
  assert.equal(isValidHexColor("#fff"), false);       // shorthand
  assert.equal(isValidHexColor("red"), false);        // named
  assert.equal(isValidHexColor("2ea043"), false);     // no hash
  assert.equal(isValidHexColor("#2ea0433"), false);   // too long
});

test("isValidHexColor: rejects CSS-injection payloads", () => {
  assert.equal(isValidHexColor("#fff; background:url(evil)"), false);
  assert.equal(isValidHexColor("}body{display:none}"), false);
});

test("isValidHexColor: rejects non-strings", () => {
  assert.equal(isValidHexColor(null), false);
  assert.equal(isValidHexColor(undefined), false);
  assert.equal(isValidHexColor(0x2ea043), false);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && node src/tests/unit/test_hex_color.mjs`
Expected: FAIL — cannot find module `hex_color.mjs`

- [ ] **Step 3: Write minimal implementation**

Create `MAIN/src/static/js/components/hex_color.mjs`:

```javascript
// hex_color.mjs — the one guard for user-chosen colours.
//
// Progress-bar option colours are user input and end up in
// style.setProperty(), where an unvalidated value is a CSS-injection vector.
// Every colour passes through here before it is stored or applied.

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;

export function isValidHexColor(value) {
  return typeof value === "string" && HEX_COLOR_RE.test(value);
}
```

Now move the two dlc-3D modules. Use `git mv` across repos is not possible, so
copy then delete:

```bash
cd /home/sam/docker-images
mkdir -p deeplabcut-webapp-docker/src/static/js/components
cp deeplabcut-webapp-docker-supports/dlc-3D/src/static/internal/relative_time.mjs \
   deeplabcut-webapp-docker/src/static/js/components/relative_time.mjs
cp deeplabcut-webapp-docker-supports/dlc-3D/src/static/tracked_files_tab.js \
   deeplabcut-webapp-docker/src/static/js/components/tracked_files_tab.js
cp deeplabcut-webapp-docker-supports/dlc-3D/tests/unit/test_relative_time.mjs \
   deeplabcut-webapp-docker/src/tests/unit/test_relative_time.mjs
cp deeplabcut-webapp-docker-supports/dlc-3D/tests/test_tracked_files_tab_source.py \
   deeplabcut-webapp-docker/src/tests/test_tracked_files_tab_source.py
rm deeplabcut-webapp-docker-supports/dlc-3D/src/static/internal/relative_time.mjs \
   deeplabcut-webapp-docker-supports/dlc-3D/src/static/tracked_files_tab.js \
   deeplabcut-webapp-docker-supports/dlc-3D/tests/unit/test_relative_time.mjs \
   deeplabcut-webapp-docker-supports/dlc-3D/tests/test_tracked_files_tab_source.py
```

Fix the moved files' paths.

In `MAIN/src/static/js/components/tracked_files_tab.js` the import becomes:

```javascript
import { formatRelative } from "./relative_time.mjs";
```

In `MAIN/src/tests/unit/test_relative_time.mjs` the import becomes:

```javascript
import { formatRelative } from "../../static/js/components/relative_time.mjs";
```

In `MAIN/src/tests/test_tracked_files_tab_source.py` the path constant becomes:

```python
JS = (Path(__file__).resolve().parents[1]
      / "static" / "js" / "components" / "tracked_files_tab.js")
```

and its `test_uses_the_shared_relative_time_helper` assertion becomes:

```python
    assert 'from "./relative_time.mjs"' in s
```

In `SUP/dlc-3D/src/static/inline_analysis_3d.js` the import becomes:

```javascript
import { makeTrackedFiles } from "/static/js/components/tracked_files_tab.js";
```

In `SUP/dlc-3D/tests/test_tracked_files_wiring.py` the first assertion becomes:

```python
    assert 'from "/static/js/components/tracked_files_tab.js"' in s
```

Create `MAIN/src/tests/README-unit-mjs.md`:

```markdown
# Pure-JS unit tests (.mjs)

Node here is **v16**, whose test runner finds nothing when pointed at a
directory (`node --test tests/unit/` reports `# tests 0`) and collapses a named
file into a single TAP line. Run each file directly instead — that prints one
`ok N - <name>` per assertion:

    cd deeplabcut-webapp-docker/src
    for f in tests/unit/*.mjs; do printf "%-38s " "$(basename $f)"; \
      node "$f" 2>&1 | grep -E "^# (pass|fail)" | tr '\n' ' '; echo; done

These cover pure, DOM-free modules under `static/js/components/`. Anything
needing a DOM is guarded by a source-assertion test in `tests/test_*_source.py`
instead — there is no DOM test runner in this project.
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
node tests/unit/test_hex_color.mjs | grep -E "^# (pass|fail)"
node tests/unit/test_relative_time.mjs | grep -E "^# (pass|fail)"
cd /home/sam/docker-images/deeplabcut-webapp-docker
python -m pytest src/tests/test_tracked_files_tab_source.py -q
```
Expected: `# pass 4` / `# fail 0`, `# pass 5` / `# fail 0`, and 8 passed.

- [ ] **Step 5: Verify dlc-3D still passes with the new import**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/ -q --ignore=tests/e2e`
Expected: **8 failed** (the known baseline) and no new failures. `test_tracked_files_wiring.py` must be green.

- [ ] **Step 6: Commit (two repos)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/static/js/components src/tests/unit src/tests/README-unit-mjs.md \
        src/tests/test_tracked_files_tab_source.py
git commit -m "refactor(tracked-files): promote the shared row component into the main webapp"

cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add -A dlc-3D/src/static dlc-3D/tests
git commit -m "refactor(tracked-files): import the shared component from /static/js/components"
```

---

### Task 4: The progress-bar component

**Files:**
- Create: `MAIN/src/static/js/components/progress_bar.js`
- Test: `MAIN/src/tests/test_progress_bar_component_source.py`

**Interfaces:**
- Consumes: Task 3's `isValidHexColor` from `./hex_color.mjs`.
- Produces: `makeProgressBar({definition, values, onChange, readOnly}) -> HTMLElement`. `definition` is Task 2's `{segments:[...]}`; `values` is `{segment_id: option_id}`; `onChange(segmentId, optionId|null)` returns a promise. Tasks 5 and 6 use it via `tracked_files_tab.js`.

- [ ] **Step 1: Write the failing test**

Create `MAIN/src/tests/test_progress_bar_component_source.py`:

```python
"""Static guards for static/js/components/progress_bar.js.

There is no DOM test runner in this project, so the invariants that actually
bite — CSS injection via a user-chosen colour, XSS via an option label, and
reverting an optimistic paint when the write fails — are guarded at the source.

See docs/superpowers/specs/2026-08-01-progress-arrow-bar-design.md.
"""
import re
from pathlib import Path

JS = (Path(__file__).resolve().parents[1]
      / "static" / "js" / "components" / "progress_bar.js")


def _src():
    assert JS.is_file(), f"missing {JS}"
    return JS.read_text()


def test_exports_the_factory():
    assert "export function makeProgressBar" in _src()


def test_every_colour_is_validated_before_it_reaches_style():
    """A colour is user input and lands in style.setProperty / style.background."""
    s = _src()
    assert 'from "./hex_color.mjs"' in s
    assert "isValidHexColor(" in s


def test_labels_are_rendered_with_textContent_never_innerHTML():
    s = _src()
    for m in re.finditer(r"innerHTML\s*=\s*(.+)", s):
        assert m.group(1).strip().startswith('""'), f"unsafe innerHTML: {m.group(0)}"


def test_a_failed_write_reverts_the_optimistic_paint():
    s = _src()
    assert re.search(r"catch[\s\S]{0,300}?(_paint|render|revert)", s), \
        "onChange rejection must restore the previous value"


def test_zero_segments_renders_nothing():
    s = _src()
    assert re.search(r"segments[\s\S]{0,200}?length[\s\S]{0,120}?return", s), \
        "an empty definition must produce no chevrons"


def test_dropdown_offers_clear_and_survives_a_segment_with_no_options():
    s = _src()
    assert "Clear" in s
    assert "No options defined" in s


def test_segments_are_buttons_and_the_dropdown_closes_on_escape():
    s = _src()
    assert 'createElement("button")' in s
    assert "Escape" in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_progress_bar_component_source.py -q`
Expected: 7 failed — `missing .../progress_bar.js`

- [ ] **Step 3: Write minimal implementation**

Create `MAIN/src/static/js/components/progress_bar.js`:

```javascript
// progress_bar.js — one file's progress arrow bar: a row of chevron segments,
// each editable by clicking it and picking from that segment's options.
//
// Pure DOM. It does no fetching: the caller supplies the project definition and
// this file's values, and persists through onChange. That is what makes it
// droppable next to any filename — the new panel, the 2D tab and the 3D tab all
// render the same component.
"use strict";

import { isValidHexColor } from "./hex_color.mjs";

const UNSET_OUTLINE = "transparent";

export function makeProgressBar({ definition, values, onChange, readOnly } = {}) {
  const segments = (definition && definition.segments) || [];
  const wrap = document.createElement("span");
  wrap.className = "pb-bar";
  wrap.style.cssText = "display:inline-flex;align-items:center;gap:2px;flex-shrink:0";
  // An empty definition renders nothing at all — no container, no layout shift.
  if (!segments.length) return wrap;

  const current = Object.assign({}, values || {});
  let openMenu = null;

  function _optionOf(seg, optionId) {
    return (seg.options || []).find((o) => o.option_id === optionId) || null;
  }

  // A value referencing a deleted segment/option simply does not resolve, so
  // the chevron paints as unset. No error, no cleanup.
  function _paint(btn, seg) {
    const opt = _optionOf(seg, current[seg.segment_id]);
    const color = opt && isValidHexColor(opt.color) ? opt.color : null;
    btn.style.background = color || UNSET_OUTLINE;
    btn.style.borderColor = color || "var(--border)";
    btn.style.color = color ? "#fff" : "var(--text-dim)";
    btn.title = `${seg.name}: ${opt ? opt.label : "unset"}`;
    btn.textContent = seg.name;
  }

  function _closeMenu() {
    if (openMenu) { openMenu.remove(); openMenu = null; }
  }

  function _openMenu(btn, seg) {
    _closeMenu();
    const menu = document.createElement("div");
    menu.className = "pb-menu";
    menu.style.cssText =
      "position:absolute;z-index:40;min-width:9rem;background:var(--surface-2);" +
      "border:1px solid var(--border);border-radius:6px;padding:.2rem;" +
      "box-shadow:0 4px 16px rgba(0,0,0,.4);font-size:.75rem";

    const opts = seg.options || [];
    if (!opts.length) {
      const none = document.createElement("div");
      none.textContent = "No options defined";
      none.style.cssText = "padding:.25rem .45rem;color:var(--text-dim);font-style:italic";
      menu.appendChild(none);
    }
    opts.forEach((opt) => {
      const row = document.createElement("button");
      row.type = "button";
      row.style.cssText =
        "display:flex;align-items:center;gap:.4rem;width:100%;text-align:left;" +
        "background:none;border:none;color:var(--text);padding:.25rem .45rem;" +
        "border-radius:4px;cursor:pointer";
      const dot = document.createElement("span");
      dot.style.cssText = "width:10px;height:10px;border-radius:2px;flex-shrink:0";
      dot.style.background = isValidHexColor(opt.color) ? opt.color : UNSET_OUTLINE;
      const label = document.createElement("span");
      label.textContent = opt.label;
      row.appendChild(dot);
      row.appendChild(label);
      row.addEventListener("click", (e) => {
        e.stopPropagation();
        _choose(btn, seg, opt.option_id);
      });
      menu.appendChild(row);
    });

    const clear = document.createElement("button");
    clear.type = "button";
    clear.textContent = "Clear";
    clear.style.cssText =
      "display:block;width:100%;text-align:left;background:none;border:none;" +
      "border-top:1px solid var(--border);margin-top:.15rem;color:var(--text-dim);" +
      "padding:.25rem .45rem;cursor:pointer";
    clear.addEventListener("click", (e) => {
      e.stopPropagation();
      _choose(btn, seg, null);
    });
    menu.appendChild(clear);

    btn.parentNode.style.position = "relative";
    btn.parentNode.appendChild(menu);
    openMenu = menu;
  }

  async function _choose(btn, seg, optionId) {
    _closeMenu();
    const previous = current[seg.segment_id];
    // Optimistic: paint first so the bar feels instant.
    if (optionId === null) delete current[seg.segment_id];
    else current[seg.segment_id] = optionId;
    _paint(btn, seg);
    try {
      if (onChange) await onChange(seg.segment_id, optionId);
    } catch (_err) {
      // Write failed — restore what was there and repaint, so the bar never
      // shows a value the server does not have.
      if (previous === undefined) delete current[seg.segment_id];
      else current[seg.segment_id] = previous;
      _paint(btn, seg);
    }
  }

  segments.forEach((seg, i) => {
    const cell = document.createElement("span");
    cell.style.cssText = "display:inline-flex;align-items:center";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.segmentId = seg.segment_id;
    btn.style.cssText =
      "font-size:.66rem;line-height:1;padding:.2rem .4rem;border:1px solid;" +
      "border-radius:3px;cursor:" + (readOnly ? "default" : "pointer") +
      ";max-width:6rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
    _paint(btn, seg);
    if (!readOnly) {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();     // the row opens the video; the bar must not
        if (openMenu) _closeMenu();
        else _openMenu(btn, seg);
      });
    }
    cell.appendChild(btn);
    wrap.appendChild(cell);
    if (i < segments.length - 1) {
      const sep = document.createElement("span");
      sep.textContent = "›";
      sep.style.cssText = "color:var(--text-dim);font-size:.7rem";
      wrap.appendChild(sep);
    }
  });

  document.addEventListener("click", _closeMenu);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") _closeMenu(); });
  return wrap;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_progress_bar_component_source.py -q`
Expected: 7 passed

- [ ] **Step 5: Syntax-check the module**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
cp src/static/js/components/progress_bar.js /tmp/pb_check.mjs && node --check /tmp/pb_check.mjs && echo "SYNTAX OK"
```
Expected: `SYNTAX OK`

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/static/js/components/progress_bar.js src/tests/test_progress_bar_component_source.py
git commit -m "feat(progress-bar): editable chevron component"
```

---

### Task 5: Render the bar in tracked-file rows

**Files:**
- Modify: `MAIN/src/static/js/components/tracked_files_tab.js`
- Test: `MAIN/src/tests/test_tracked_files_tab_source.py` (add cases)

**Interfaces:**
- Consumes: Task 4's `makeProgressBar`; Task 2's `progress` key and `PUT /dlc/project/progress-bar/value`.
- Produces: rows that carry the bar. The 3D tab picks this up with no dlc-3D change at all.

- [ ] **Step 1: Write the failing test**

Append to `MAIN/src/tests/test_tracked_files_tab_source.py`:

```python
def test_rows_render_the_shared_progress_bar():
    s = _src()
    assert 'from "./progress_bar.js"' in s
    assert "makeProgressBar(" in s


def test_bar_is_built_from_the_listing_progress_and_the_fetched_definition():
    s = _src()
    assert "/dlc/project/progress-bar" in s
    assert re.search(r"values\s*:\s*f\.progress", s), \
        "each row's bar must be seeded from that file's progress object"


def test_segment_edits_persist_through_the_value_route():
    s = _src()
    assert "/dlc/project/progress-bar/value" in s
    assert '"PUT"' in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_tab_source.py -q`
Expected: 3 failed, 8 passed

- [ ] **Step 3: Write minimal implementation**

In `MAIN/src/static/js/components/tracked_files_tab.js`:

Add the import beside the existing one:

```javascript
import { formatRelative } from "./relative_time.mjs";
import { makeProgressBar } from "./progress_bar.js";
```

Add the definition constant and state next to `API`:

```javascript
const API = "/dlc/project/tracked-files";
const BAR_API = "/dlc/project/progress-bar";
```

Inside the factory, beside `let _loaded = false;`:

```javascript
  let _definition = { segments: [] };   // project's bar definition, fetched with the list
```

In `refresh()`, fetch the definition alongside the list. Replace the body of the
`try` block with:

```javascript
      const [data, def] = await Promise.all([
        _fetchJson(API),
        // The bar is decorative next to the list: if it fails, still show files.
        _fetchJson(BAR_API).catch(() => ({ segments: [] })),
      ]);
      _definition = def && Array.isArray(def.segments) ? def : { segments: [] };
      _rows = new Map((data.files || []).map((f) => [f.path, f]));
      _loaded = true;
      _render();
```

Add the persistence helper next to `_noteOpened`:

```javascript
  // Persist one segment of one file. Rejecting lets the component revert its
  // optimistic paint, so the bar never shows a value the server does not have.
  async function _setSegment(path, segmentId, optionId) {
    await _fetchJson(BAR_API + "/value", {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ path, segment_id: segmentId, option_id: optionId }),
    });
    const row = _rows.get(path);
    if (row) {
      row.progress = row.progress || {};
      if (optionId === null) delete row.progress[segmentId];
      else row.progress[segmentId] = optionId;
    }
  }
```

In `_makeRow`, insert the bar between the checkbox and the text column — add
this immediately after the `cb.addEventListener("change", …)` line:

```javascript
    const bar = makeProgressBar({
      definition: _definition,
      values: f.progress || {},
      onChange: (segmentId, optionId) => _setSegment(f.path, segmentId, optionId),
    });
```

and change the append order at the end of `_makeRow` from
`row.appendChild(cb); row.appendChild(col); row.appendChild(when);` to:

```javascript
    row.appendChild(cb);
    row.appendChild(bar);
    row.appendChild(col);
    row.appendChild(when);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_tab_source.py -q`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/static/js/components/tracked_files_tab.js src/tests/test_tracked_files_tab_source.py
git commit -m "feat(progress-bar): render the editable bar on every tracked-file row"
```

---

### Task 6: The management card

**Files:**
- Create: `MAIN/src/templates/partials/card_tracked_files.html`, `MAIN/src/static/js/tracked_files_panel.js`
- Modify: `MAIN/src/templates/partials/card_dlc_project.html:150` (button), `MAIN/src/templates/index.html:20` (include), `MAIN/src/static/js/main.js:19` (import), `SUP/dlc-3D/src/templates/dlc_3d.html:36` (include), `deeplabcut-webapp-docker/docker-compose.yml` (two dlc-3d mounts)
- Test: `MAIN/src/tests/test_tracked_files_panel_markup.py`

**Interfaces:**
- Consumes: Task 3's `makeTrackedFiles`, Task 2's routes.
- Produces: the card. Nothing later depends on it.

- [ ] **Step 1: Write the failing test**

Create `MAIN/src/tests/test_tracked_files_panel_markup.py`:

```python
"""Static guards for the Tracked Files management card (2D + 3D).

See docs/superpowers/specs/2026-08-01-progress-arrow-bar-design.md.
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
CARD = SRC / "templates" / "partials" / "card_tracked_files.html"
PROJECT_CARD = SRC / "templates" / "partials" / "card_dlc_project.html"
INDEX = SRC / "templates" / "index.html"
PANEL_JS = SRC / "static" / "js" / "tracked_files_panel.js"
MAIN_JS = SRC / "static" / "js" / "main.js"
DLC3D = (SRC.parents[2] / "deeplabcut-webapp-docker-supports" / "dlc-3D"
         / "src" / "templates" / "dlc_3d.html")


def test_the_open_button_sits_directly_after_annotate_video():
    s = PROJECT_CARD.read_text()
    assert 'id="btn-open-progress-tracking"' in s
    assert s.index('id="btn-open-annotate-video"') < s.index('id="btn-open-progress-tracking"')
    between = s[s.index('id="btn-open-annotate-video"'):s.index('id="btn-open-progress-tracking"')]
    assert between.count("<button") == 1, "no other button may sit between the two"


def test_card_has_the_definition_editor_and_the_file_list():
    s = CARD.read_text()
    for el in ("tracked-files-card", "tf-add-bar-btn", "tf-segment-count",
               "tf-segments", "tf-save-bar-btn", "tf-list", "tf-status"):
        assert f'id="{el}"' in s, f"missing #{el}"


def test_segment_count_input_is_clamped_zero_to_ten():
    s = CARD.read_text()
    m = re.search(r'<input[^>]*id="tf-segment-count"[^>]*>', s)
    assert m, "missing #tf-segment-count"
    assert 'min="0"' in m.group(0)
    assert 'max="10"' in m.group(0)


def test_card_is_included_by_both_page_templates():
    assert 'partials/card_tracked_files.html' in INDEX.read_text()
    assert DLC3D.is_file(), f"missing {DLC3D}"
    assert 'partials/card_tracked_files.html' in DLC3D.read_text()


def test_panel_controller_is_loaded_by_main_js():
    assert PANEL_JS.is_file(), f"missing {PANEL_JS}"
    assert "tracked_files_panel.js" in MAIN_JS.read_text()


def test_panel_reuses_the_shared_row_component_rather_than_its_own_list():
    s = PANEL_JS.read_text()
    assert 'from "./components/tracked_files_tab.js"' in s
    assert "makeTrackedFiles(" in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_panel_markup.py -q`
Expected: 6 failed

- [ ] **Step 3: Write minimal implementation**

**3a.** In `MAIN/src/templates/partials/card_dlc_project.html`, insert directly
after the `btn-open-annotate-video` button's closing `</button>` (line 150):

```html
        <button id="btn-open-progress-tracking" class="inspect-btn" style="width:100%;gap:.55rem">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 9 6 12 9 9 12 3 12"/><polyline points="12 12 18 12 21 15 18 18 12 18"/>
          </svg>
          <span>Tracked Files &amp; Progress</span>
        </button>
```

**3b.** Create `MAIN/src/templates/partials/card_tracked_files.html`:

```html
    <section class="card dlc-theme hidden" id="tracked-files-card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.3rem">
        <h2>Tracked Files &amp; Progress</h2>
        <button class="btn-sm" id="btn-close-tracked-files" title="Close">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          Close
        </button>
      </div>
      <p class="subtitle">Define this project's progress bar, then set each tracked file's progress by clicking a segment.</p>

      <!-- ── Bar definition ─────────────────────────────────────── -->
      <div style="margin-bottom:.7rem;padding:.5rem .65rem;border:1px solid var(--border);border-radius:7px;background:var(--surface-2)">
        <div style="font-size:.72rem;font-weight:600;color:var(--text-dim);text-transform:uppercase;letter-spacing:.05em;margin-bottom:.5rem">Progress bar</div>
        <button class="btn-sm btn-create" id="tf-add-bar-btn">＋ Add progress bar</button>
        <div id="tf-bar-editor" class="hidden">
          <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.5rem">
            <label style="font-size:.78rem;color:var(--text-dim)">Segments</label>
            <input type="number" id="tf-segment-count" min="0" max="10" step="1" value="0"
                   style="width:4.5rem;font-family:var(--mono);font-size:.78rem;background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.2rem .35rem"/>
            <span style="font-size:.7rem;color:var(--text-dim)">0–10</span>
            <button class="btn-sm btn-create" id="tf-save-bar-btn" style="margin-left:auto">Save bar</button>
          </div>
          <div id="tf-segments"></div>
        </div>
      </div>

      <!-- ── Tracked files ──────────────────────────────────────── -->
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.3rem">
        <label style="font-size:.78rem;color:var(--text-dim)">Tracked files</label>
        <button class="btn-sm" id="tf-refresh" style="padding:.2rem .45rem;font-size:.75rem">↺ Refresh</button>
      </div>
      <div id="tf-list" style="max-height:320px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);padding:.4rem .5rem;font-size:.77rem">
        <p class="explorer-empty">Loading…</p>
      </div>
      <div id="tf-status" class="fe-extract-status" style="margin-top:.35rem"></div>
    </section>
```

**3c.** Create `MAIN/src/static/js/tracked_files_panel.js`:

```javascript
// tracked_files_panel.js — the "Tracked Files & Progress" card.
//
// Two jobs: edit the project's progress-bar definition, and list every tracked
// file with its checkbox and its editable bar. The list itself is the shared
// makeTrackedFiles component — this file owns only the definition editor.
"use strict";

import { makeTrackedFiles } from "./components/tracked_files_tab.js";
import { isValidHexColor } from "./components/hex_color.mjs";

const BAR_API = "/dlc/project/progress-bar";
const DEFAULT_COLOR = "#888888";

const $ = (id) => document.getElementById(id);

let _definition = { segments: [] };
let _tracked = null;

function _status(msg, isError) {
  const el = $("tf-status");
  if (!el) return;
  el.textContent = msg || "";
  el.style.color = isError ? "var(--danger, #e66)" : "";
}

async function _fetchJson(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `status ${res.status}`);
  return data;
}

// ── Definition editor ───────────────────────────────────────────────────────

function _renderSegments() {
  const host = $("tf-segments");
  if (!host) return;
  host.innerHTML = "";
  _definition.segments.forEach((seg, idx) => {
    const box = document.createElement("div");
    box.style.cssText =
      "border:1px solid var(--border);border-radius:6px;padding:.4rem .5rem;margin-bottom:.4rem;background:var(--surface)";

    const head = document.createElement("div");
    head.style.cssText = "display:flex;align-items:center;gap:.4rem;margin-bottom:.35rem";
    const num = document.createElement("span");
    num.textContent = `${idx + 1}.`;
    num.style.cssText = "font-size:.72rem;color:var(--text-dim);flex-shrink:0";
    const name = document.createElement("input");
    name.type = "text";
    name.value = seg.name || "";
    name.placeholder = "segment name";
    name.style.cssText =
      "flex:1;min-width:0;font-size:.76rem;background:var(--surface-2);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.2rem .4rem";
    name.addEventListener("input", () => { seg.name = name.value; });
    const addOpt = document.createElement("button");
    addOpt.className = "btn-sm";
    addOpt.textContent = "＋ Option";
    addOpt.style.cssText = "padding:.15rem .45rem;font-size:.72rem;flex-shrink:0";
    addOpt.addEventListener("click", () => {
      seg.options = seg.options || [];
      seg.options.push({ label: "", color: DEFAULT_COLOR });
      _renderSegments();
    });
    head.appendChild(num); head.appendChild(name); head.appendChild(addOpt);
    box.appendChild(head);

    (seg.options || []).forEach((opt, oIdx) => {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;gap:.4rem;margin-bottom:.25rem";
      const color = document.createElement("input");
      color.type = "color";
      color.value = isValidHexColor(opt.color) ? opt.color : DEFAULT_COLOR;
      color.style.cssText = "width:2rem;height:1.5rem;padding:0;border:1px solid var(--border);border-radius:4px;background:none;flex-shrink:0";
      color.addEventListener("input", () => { opt.color = color.value; });
      const label = document.createElement("input");
      label.type = "text";
      label.value = opt.label || "";
      label.placeholder = "option label";
      label.style.cssText =
        "flex:1;min-width:0;font-size:.75rem;background:var(--surface-2);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.18rem .4rem";
      label.addEventListener("input", () => { opt.label = label.value; });
      const del = document.createElement("button");
      del.className = "btn-sm";
      del.textContent = "✕";
      del.title = "Remove this option";
      del.style.cssText = "padding:.1rem .4rem;font-size:.7rem;opacity:.7;flex-shrink:0";
      del.addEventListener("click", () => {
        seg.options.splice(oIdx, 1);
        _renderSegments();
      });
      row.appendChild(color); row.appendChild(label); row.appendChild(del);
      box.appendChild(row);
    });

    host.appendChild(box);
  });
}

// Removed segments are kept here so lowering the count and raising it again
// BEFORE saving restores the same ids — and therefore the same file values.
// Once saved, those ids are gone for good.
let _dropped = [];

function _applyCount(n) {
  const count = Math.max(0, Math.min(10, Number(n) || 0));
  const segs = _definition.segments;
  while (segs.length > count) _dropped.unshift(segs.pop());
  while (segs.length < count) {
    segs.push(_dropped.length ? _dropped.shift()
                              : { name: `Stage ${segs.length + 1}`, options: [] });
  }
  _renderSegments();
}

async function _loadDefinition() {
  try {
    const def = await _fetchJson(BAR_API);
    _definition = def && Array.isArray(def.segments) ? def : { segments: [] };
  } catch (err) {
    _definition = { segments: [] };
    _status(err.message, true);
  }
  _dropped = [];
  const hasBar = _definition.segments.length > 0;
  $("tf-bar-editor")?.classList.toggle("hidden", !hasBar);
  $("tf-add-bar-btn")?.classList.toggle("hidden", hasBar);
  const countEl = $("tf-segment-count");
  if (countEl) countEl.value = String(_definition.segments.length);
  _renderSegments();
}

async function _saveDefinition() {
  try {
    const saved = await _fetchJson(BAR_API, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ segments: _definition.segments }),
    });
    _definition = { segments: saved.segments || [] };
    _dropped = [];
    _renderSegments();
    _status("Progress bar saved.");
    await _tracked?.refresh();     // rows must repaint against the new definition
  } catch (err) {
    _status(`Could not save: ${err.message}`, true);
  }
}

// ── Wiring ──────────────────────────────────────────────────────────────────

const card = $("tracked-files-card");
if (card) {
  _tracked = makeTrackedFiles({
    refreshBtn: $("tf-refresh"),
    panelEl: card,
    listEl: $("tf-list"),
    onOpen: () => {},          // this card manages files; it does not open videos
    onError: (msg) => _status(msg, true),
  });

  $("btn-open-progress-tracking")?.addEventListener("click", async () => {
    card.classList.remove("hidden");
    card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    _status("");
    await _loadDefinition();
    await _tracked.refresh();
  });
  $("btn-close-tracked-files")?.addEventListener("click", () => card.classList.add("hidden"));
  $("tf-add-bar-btn")?.addEventListener("click", async () => {
    _definition = { segments: [{ name: "Stage 1", options: [] }] };
    await _saveDefinition();
    await _loadDefinition();
  });
  $("tf-segment-count")?.addEventListener("change", (e) => _applyCount(e.target.value));
  $("tf-save-bar-btn")?.addEventListener("click", _saveDefinition);
}
```

**3d.** In `MAIN/src/templates/index.html`, add after the `card_annotator.html`
include:

```html
    {% include "partials/card_tracked_files.html" %}
```

**3e.** In `MAIN/src/static/js/main.js`, add after `import './custom_script.js';`:

```javascript
import './tracked_files_panel.js';
```

**3f.** In `SUP/dlc-3D/src/templates/dlc_3d.html`, add after the
`card_annotator.html` include:

```html
    {% include "partials/card_tracked_files.html" %}
```

**3g.** In `deeplabcut-webapp-docker/docker-compose.yml`, add two mounts to the
`dlc-3d` service's `volumes:` list. Without these the 3D page keeps serving the
image's baked copies and neither the button nor the card appears there:

```yaml
      - ../deeplabcut-webapp-docker/src/templates/partials/card_dlc_project.html:/app/templates/partials/card_dlc_project.html
      - ../deeplabcut-webapp-docker/src/templates/partials/card_tracked_files.html:/app/templates/partials/card_tracked_files.html
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_panel_markup.py -q`
Expected: 6 passed

- [ ] **Step 5: Syntax-check and commit (two repos)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
cp src/static/js/tracked_files_panel.js /tmp/panel_check.mjs && node --check /tmp/panel_check.mjs && echo "SYNTAX OK"
git add src/templates/partials/card_tracked_files.html src/templates/partials/card_dlc_project.html \
        src/templates/index.html src/static/js/tracked_files_panel.js src/static/js/main.js \
        src/tests/test_tracked_files_panel_markup.py docker-compose.yml
git commit -m "feat(progress-bar): Tracked Files & Progress card, reachable from 2D and 3D"

cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/dlc_3d.html
git commit -m "feat(progress-bar): include the shared tracked-files card on the 3D page"
```

---

### Task 7: 2D Tracked Files tab

**Files:**
- Modify: `MAIN/src/templates/partials/card_inline_analysis.html:10-14` (tabs), `:44` (after browse panel), `:90` (header), `MAIN/src/static/js/inline_analysis_player.js:372-388` (open), `:151` (reset), `:467-478` (tabs)
- Test: `MAIN/src/tests/test_inline_analysis_2d_tracked_tab.py`

**Interfaces:**
- Consumes: Task 3's `makeTrackedFiles`.
- Produces: nothing later depends on it.

- [ ] **Step 1: Write the failing test**

Create `MAIN/src/tests/test_inline_analysis_2d_tracked_tab.py`:

```python
"""Static guards for the 2D Inline Analysis card's Tracked Files tab.

Mirrors the 3D card's guards, including the open-abort regression: a tracked
file whose video has moved must not open an empty viewer at fps 30 / 0 frames.
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
HTML = SRC / "templates" / "partials" / "card_inline_analysis.html"
JS = SRC / "static" / "js" / "inline_analysis_player.js"


def test_third_tab_and_panel_exist():
    s = HTML.read_text()
    assert 'id="ia-tab-tracked"' in s
    assert s.index('id="ia-tab-browse"') < s.index('id="ia-tab-tracked"')
    m = re.search(r'<div id="ia-tab-tracked-panel"[^>]*class="([^"]*)"', s)
    assert m and "hidden" in m.group(1)
    assert 'id="ia-tracked-list"' in s


def test_launcher_error_line_precedes_the_player_section():
    s = HTML.read_text()
    assert 'id="ia-launcher-error"' in s
    assert s.index('id="ia-launcher-error"') < s.index('id="ia-player-section"')


def test_track_checkbox_precedes_the_selected_name():
    s = HTML.read_text()
    assert 'id="ia-track-checkbox"' in s
    assert s.index('id="ia-track-checkbox"') < s.index('id="ia-selected-name"')


def test_js_constructs_the_shared_component():
    s = JS.read_text()
    assert 'from "./components/tracked_files_tab.js"' in s
    assert "makeTrackedFiles(" in s


def test_open_browse_video_aborts_instead_of_falling_back_to_fps_30():
    s = JS.read_text()
    m = re.search(r"async function _iaOpenBrowseVideo\([\s\S]*?\n    \}", s)
    assert m, "missing _iaOpenBrowseVideo"
    body = m.group(0)
    assert "res.ok" in body
    assert re.search(r"info\.error", body)
    assert not re.search(r"catch\s*\([^)]*\)\s*\{\s*_iaFps\s*=\s*30", body), \
        "the silent fps-30 fallback must be gone"


def test_reset_hides_the_track_checkbox():
    s = JS.read_text()
    assert re.search(r"_trackedFiles\?\.setCurrent\(\s*null\s*\)", s)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_inline_analysis_2d_tracked_tab.py -q`
Expected: 6 failed

- [ ] **Step 3: Write minimal implementation**

**3a.** In `card_inline_analysis.html`, add the third tab button after
`ia-tab-browse` and the error line after the tab row:

```html
        <button id="ia-tab-tracked" class="btn-sm" style="padding:.2rem .65rem;font-size:.75rem">Tracked Files</button>
      </div>

      <!-- Launcher-level error line: an aborted open never reveals the player. -->
      <div id="ia-launcher-error" class="fe-extract-status" style="margin-bottom:.4rem"></div>
```

**3b.** Add the tracked panel immediately after the `#ia-tab-browse-panel`
closing `</div>`:

```html
      <!-- Tab: Tracked Files -->
      <div id="ia-tab-tracked-panel" class="hidden">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.3rem">
          <label style="font-size:.78rem;color:var(--text-dim)">Tracked videos</label>
          <button class="btn-sm" id="ia-tracked-refresh" style="padding:.2rem .45rem;font-size:.75rem">↺ Refresh</button>
        </div>
        <div id="ia-tracked-list" style="max-height:220px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);padding:.4rem .5rem;font-size:.77rem">
          <p class="explorer-empty">Loading…</p>
        </div>
      </div>
```

**3c.** In the player header, put the checkbox before `#ia-selected-name`:

```html
          <label id="ia-track-label" class="hidden" title="Track this file — it will appear in the Tracked Files tab"
                 style="display:flex;align-items:center;gap:.35rem;flex-shrink:0;cursor:pointer">
            <input type="checkbox" id="ia-track-checkbox" style="accent-color:var(--accent);width:14px;height:14px">
          </label>
```

**3d.** In `inline_analysis_player.js`, add the import at the top of the file
beside the existing imports:

```javascript
import { makeTrackedFiles } from "./components/tracked_files_tab.js";
```

**3e.** Add the module-level handle and the error helper near the other
`const ia…` declarations (after line 34):

```javascript
    let _trackedFiles = null;

    function _iaLauncherError(msg) {
      const el = document.getElementById("ia-launcher-error");
      if (!el) return;
      el.textContent = msg || "";
      el.style.color = msg ? "var(--danger, #e66)" : "";
    }
```

**3f.** Replace `_iaOpenBrowseVideo` (lines 372-388) with:

```javascript
    async function _iaOpenBrowseVideo(absPath, name) {
      // Resolve video info BEFORE mutating state: a missing or unreadable file
      // must abort instead of silently loading an empty viewer. A tracked file
      // whose video has moved takes exactly this path.
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
      _iaReset();
      _iaMode             = "browse-video";
      _iaBrowseVideoPath  = absPath;
      _iaCurrentVideoPath = absPath;
      iaSelectedName.textContent = name;
      _iaFps        = info.fps || 30;
      _iaFrameCount = info.frame_count || 0;
      iaPlayerSec.classList.remove("hidden");
      _iaLoadFrame(0);
      _iaDiscoverVariants(absPath);
      _trackedFiles?.setCurrent(absPath);
    }
```

**3g.** In `_iaReset()` (line 151), add as its first statement:

```javascript
      _trackedFiles?.setCurrent(null);
```

**3h.** Replace the two tab handlers (lines 467-478) with the three-tab table
and construct the component:

```javascript
    const IA_TABS = [
      { btn: "ia-tab-project", panel: "ia-tab-project-panel" },
      { btn: "ia-tab-browse",  panel: "ia-tab-browse-panel"  },
      { btn: "ia-tab-tracked", panel: "ia-tab-tracked-panel" },
    ];
    function _iaShowTab(id) {
      IA_TABS.forEach((t) => {
        const on = t.btn === id;
        document.getElementById(t.btn)?.classList.toggle("active", on);
        document.getElementById(t.panel)?.classList.toggle("hidden", !on);
      });
    }
    IA_TABS.forEach((t) =>
      document.getElementById(t.btn)?.addEventListener("click", () => _iaShowTab(t.btn)));

    _trackedFiles = makeTrackedFiles({
      tabBtn: document.getElementById("ia-tab-tracked"),
      refreshBtn: document.getElementById("ia-tracked-refresh"),
      panelEl: document.getElementById("ia-tab-tracked-panel"),
      listEl: document.getElementById("ia-tracked-list"),
      headerCheckbox: document.getElementById("ia-track-checkbox"),
      headerLabel: document.getElementById("ia-track-label"),
      onOpen: (path, name) => _iaOpenBrowseVideo(path, name),
      onError: (msg) => _iaLauncherError(msg),
    });
```

Keep whatever the old `iaTabBrowse` handler did beyond switching panels (the
first-visit `_iaRefreshBrowse(...)` call) by re-attaching it as a second
listener on `ia-tab-browse`, exactly as the 3D card does.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_inline_analysis_2d_tracked_tab.py -q`
Expected: 6 passed

- [ ] **Step 5: Full verification, both repos**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
cp src/static/js/inline_analysis_player.js /tmp/ia2d.mjs && node --check /tmp/ia2d.mjs && echo "SYNTAX OK"
python -m pytest src/tests/ -q -p no:randomly 2>&1 | tail -5
cd src && for f in tests/unit/*.mjs; do printf "%-38s " "$(basename $f)"; \
  node "$f" 2>&1 | grep -E "^# (pass|fail)" | tr '\n' ' '; echo; done
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q --ignore=tests/e2e 2>&1 | tail -3
```
Expected: `SYNTAX OK`; main webapp at the **16** known failures and no others;
every `.mjs` file `# fail 0`; dlc-3D at the **8** known failures.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/templates/partials/card_inline_analysis.html src/static/js/inline_analysis_player.js \
        src/tests/test_inline_analysis_2d_tracked_tab.py
git commit -m "feat(tracked-files): Tracked Files tab on the 2D card; abort open on missing video"
```

---

### Task 8: Deploy and verify

**Files:** none — deployment and verification only.

Dispatch to a **subagent** with this brief verbatim:

> Deploy and verify the progress-arrow-bar feature. Report findings only — do NOT edit, fix, or commit anything.
>
> 1. `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose up -d flask dlc-3d`. Use `up -d`, NOT `restart`: `docker-compose.yml` gained two new bind mounts for the `dlc-3d` service, and `restart` does not apply mount changes — the container must be recreated. Do NOT rebuild images. Do NOT touch `worker` or `worker-tf`.
> 2. `docker compose ps` to confirm both are Up, then `docker compose logs --tail=50 flask dlc-3d`. A traceback mentioning `progress_bar` or `tracked_files` is a hard failure — quote it and stop.
> 3. The app is behind session auth: unauthenticated requests 302 to /login, which is a FALSE NEGATIVE, not a routing failure. Seed a cookie jar first: `curl -sc /tmp/cj.txt "http://localhost:5000/?token=deeplabcut" -o /dev/null`, then pass `-b /tmp/cj.txt` on every check below.
> 4. `curl -sb /tmp/cj.txt -o /dev/null -w '%{http_code}\n' http://localhost:5000/dlc/project/progress-bar` — expect 200 or 400 (400 body should be `{"error":"No active DLC project."}`). A **404 means blueprint registration failed**.
> 5. Assets, each must be 200 not 404: `/static/js/components/progress_bar.js`, `/static/js/components/tracked_files_tab.js`, `/static/js/components/relative_time.mjs`, `/static/js/components/hex_color.mjs`, `/static/js/tracked_files_panel.js`.
> 6. Confirm the OLD dlc-3D asset path is gone (it was moved): `/dlc-3d/static/tracked_files_tab.js` should now 404. Report what it returns.
> 7. Markup on BOTH pages — each count must be >= 1: `curl -sb /tmp/cj.txt http://localhost:5000/ | grep -c 'btn-open-progress-tracking'` and the same for `tracked-files-card`; then repeat both greps against `http://localhost:5000/dlc-3d/`.
>
> Report the restart result, any log errors quoted, and the status code or count for every check in steps 4–7, with a one-line PASS/FAIL per check.

- [ ] **Step 1: Dispatch the deployment subagent with the brief above**

- [ ] **Step 2: Act on the report** — fix anything that failed, re-run the affected task's tests, re-dispatch.

- [ ] **Step 3: Manual smoke test** at `http://localhost:5000/` with a project active:

1. **Tracked Files & Progress** button appears directly under **Annotate Video**; clicking opens the card.
2. **Add progress bar** → one segment `Stage 1` appears; set count to 3, name them, add two coloured options to the first.
3. **Save bar** → status says saved.
4. A tracked file's row shows three chevrons; click the first → dropdown lists both options plus **Clear**; pick one → it paints in that colour.
5. Reload the page, reopen the card → the value persisted.
6. Rename that option and recolour it → **Save bar** → the file's chevron keeps its value in the new colour (stable IDs).
7. Lower the segment count to 1 and **Save**, then raise it back to 3 → the two new segments are blank (their IDs were not recoverable after save — expected).
8. Repeat 4 on `/dlc-3d/` in the 3D card's Tracked Files tab and on the 2D Inline Analysis card's tab — the same bar renders in all three places.

---

## Self-Review

**Spec coverage:** store → Task 1; API + `progress` on the listing → Task 2; module promotion + `hex_color.mjs` + the new `.mjs` test dir → Task 3; the component → Task 4; rendering in rows (which is what makes the 3D tab get it for free) → Task 5; card, button, both includes, compose mounts → Task 6; 2D tab + the open-abort fix → Task 7; deployment → Task 8.

**Placeholder scan:** no TBDs; every code step carries the actual code. Task 7 step 3h contains one judgement instruction ("keep whatever the old handler did beyond switching panels") rather than literal code, because the surrounding lines are not quoted in full anywhere in this plan — the implementer must read `inline_analysis_player.js:473-478` and preserve its `_iaRefreshBrowse` call.

**Type consistency:** `makeTrackedFiles` options match Task 3's produced signature everywhere it is constructed (Tasks 6 and 7) — note Task 6 omits `tabBtn`, `headerCheckbox` and `headerLabel`, which the component already treats as optional via `?.`. `makeProgressBar({definition, values, onChange, readOnly})` in Task 4 matches its call in Task 5. Store keys `segment_id` / `option_id` / `label` / `color` / `name` / `options` are identical across Tasks 1, 2, 4, 5 and 6. The value route takes `{path, segment_id, option_id}` in both Task 2 and Task 5.

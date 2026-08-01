# Video Identity & Audit Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Key every tracked file and progress value to a surrogate `video_id` that survives renaming and moving, and log every database change atomically with the change.

**Architecture:** A new `dlc/tracked_db.py` owns the connection, the v3 schema, the v2→v3 migration, video identity and the audit helper. `tracked_files.py` and `progress_bar.py` become thin stores over it, keyed by `video_id`. Routes probe video metadata and supply the actor.

**Tech Stack:** Python 3.9 + Flask + sqlite3 + hashlib.blake2b (stdlib); cv2 for probing, already used by `/annotate/video-info`.

**Spec:** `docs/superpowers/specs/2026-08-01-video-identity-and-audit-log-design.md`

## Global Constraints

- `MAIN` = `/home/sam/docker-images/deeplabcut-webapp-docker`. `SUP` = `/home/sam/docker-images/deeplabcut-webapp-docker-supports`.
- Python is **3.9**: `from __future__ import annotations` before any `X | None` annotation.
- `tracked_db.py`, `tracked_files.py`, `progress_bar.py` import **no** Flask, **no** DLC, **no** Redis, and **never** touch the filesystem beyond their own DB file. Probing lives in the route layer.
- Fingerprint is exactly `blake2b(f"{size_bytes}|{frame_count}", digest_size=16).hexdigest()`. **No mtime** — it is not intrinsic and `cp` without `-p` changes it.
- `video.path` is UNIQUE; `video.fingerprint` is deliberately **NOT** unique (two copies of one recording share it).
- Every mutating store function writes its audit row **inside the same `BEGIN IMMEDIATE` transaction as the change**.
- The migration **never probes the filesystem** — files may be on unmounted disks.
- IDs: `vid_` + 16 hex from `secrets.token_hex(8)`. Never reused.
- Known-failure baselines — do NOT attribute these to this work: **16** in the main webapp (all `test_dlc_celery_tasks.py`, `KeyError: 'n_machine'`), **8** in dlc-3D.
- Run pytest from a repo root. In dlc-3D pass `--ignore=tests/e2e`. Never run e2e suites.
- Deployment needs `docker compose up -d --force-recreate flask` — `src/app.py` is a single-file bind mount and Docker binds the inode, so a restart serves stale code.

---

### Task 1: Shared DB layer — schema, migration, identity, audit

**Files:**
- Create: `MAIN/src/dlc/tracked_db.py`
- Test: `MAIN/src/tests/test_tracked_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DB_FILENAME`; `db_path(project_path)`; `connect(project_path)` context manager; `now()`; `fingerprint(size_bytes, frame_count)`; `audit(conn, actor, entity, entity_id, action, before=None, after=None)`; `ensure_video(conn, path, actor=None, size_bytes=None, frame_count=None) -> str`; `video_id_for_path(conn, path) -> str | None`; `video_row(conn, video_id) -> dict | None`; `relink_path(conn, video_id, new_path, actor=None) -> bool`. Tasks 2–4 consume all of these.

- [ ] **Step 1: Write the failing test**

Create `MAIN/src/tests/test_tracked_db.py`:

```python
"""Tests for src/dlc/tracked_db.py — schema, v2->v3 migration, identity, audit."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

import pytest

from dlc import tracked_db as db


@pytest.fixture
def project(tmp_path: Path) -> Path:
    p = tmp_path / "Proj-2026-08-01"
    p.mkdir()
    return p


def _v2_database(project: Path):
    """Build a database in the OLD path-keyed shape, as shipped before v3."""
    conn = sqlite3.connect(str(project / db.DB_FILENAME), isolation_level=None)
    conn.executescript("""
        CREATE TABLE tracked (video_path TEXT PRIMARY KEY, tracked_at TEXT NOT NULL,
                              last_opened_at TEXT);
        CREATE TABLE progress_value (video_path TEXT NOT NULL, segment_id TEXT NOT NULL,
                                     option_id TEXT NOT NULL, set_at TEXT NOT NULL,
                                     PRIMARY KEY (video_path, segment_id));
        CREATE TABLE progress_segment (segment_id TEXT PRIMARY KEY, position INTEGER NOT NULL,
                                       name TEXT NOT NULL);
        CREATE TABLE progress_option (option_id TEXT PRIMARY KEY, segment_id TEXT NOT NULL,
                                      position INTEGER NOT NULL, label TEXT NOT NULL,
                                      color TEXT NOT NULL);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta VALUES ('schema_version', '2');
        INSERT INTO tracked VALUES ('/data/a.avi', '2026-07-01T10:00:00Z', '2026-07-02T10:00:00Z');
        INSERT INTO tracked VALUES ('/data/b.avi', '2026-07-01T11:00:00Z', NULL);
        INSERT INTO progress_value VALUES ('/data/a.avi', 'seg_1', 'opt_1', '2026-07-03T10:00:00Z');
        INSERT INTO progress_value VALUES ('/data/c.avi', 'seg_1', 'opt_2', '2026-07-03T11:00:00Z');
    """)
    conn.close()


# ── Fresh database ──────────────────────────────────────────────────────────

def test_fresh_database_is_created_at_v3(project):
    with db.connect(project) as conn:
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    assert version[0] == "3"


def test_fresh_database_has_every_v3_table(project):
    with db.connect(project) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"video", "tracked", "progress_value", "progress_segment",
            "progress_option", "audit_log", "meta"} <= names


def test_tracked_is_keyed_by_video_id_not_path(project):
    with db.connect(project) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tracked)")}
    assert "video_id" in cols
    assert "video_path" not in cols


# ── Migration ───────────────────────────────────────────────────────────────

def test_migration_creates_one_video_row_per_distinct_path(project):
    _v2_database(project)
    with db.connect(project) as conn:
        paths = {r[0] for r in conn.execute("SELECT path FROM video")}
    assert paths == {"/data/a.avi", "/data/b.avi", "/data/c.avi"}


def test_migration_preserves_tracked_rows(project):
    _v2_database(project)
    with db.connect(project) as conn:
        rows = conn.execute(
            "SELECT v.path, t.tracked_at, t.last_opened_at FROM tracked t "
            "JOIN video v ON v.video_id = t.video_id ORDER BY v.path").fetchall()
    assert rows == [
        ("/data/a.avi", "2026-07-01T10:00:00Z", "2026-07-02T10:00:00Z"),
        ("/data/b.avi", "2026-07-01T11:00:00Z", None),
    ]


def test_migration_preserves_progress_values_including_untracked_paths(project):
    """/data/c.avi has a value but was never tracked — it must still migrate."""
    _v2_database(project)
    with db.connect(project) as conn:
        rows = conn.execute(
            "SELECT v.path, p.segment_id, p.option_id FROM progress_value p "
            "JOIN video v ON v.video_id = p.video_id ORDER BY v.path").fetchall()
    assert rows == [("/data/a.avi", "seg_1", "opt_1"),
                    ("/data/c.avi", "seg_1", "opt_2")]


def test_migration_carries_tracked_at_into_first_seen_at(project):
    _v2_database(project)
    with db.connect(project) as conn:
        seen = conn.execute(
            "SELECT first_seen_at FROM video WHERE path='/data/a.avi'").fetchone()[0]
    assert seen == "2026-07-01T10:00:00Z"


def test_migration_leaves_metrics_null_because_it_never_probes(project):
    _v2_database(project)
    with db.connect(project) as conn:
        row = conn.execute(
            "SELECT size_bytes, frame_count, fingerprint FROM video "
            "WHERE path='/data/a.avi'").fetchone()
    assert row == (None, None, None)


def test_migration_is_recorded_in_the_audit_log(project):
    _v2_database(project)
    with db.connect(project) as conn:
        rows = conn.execute(
            "SELECT action, after FROM audit_log WHERE action='migrate_v2_v3'").fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0][1])["videos"] == 3


def test_migration_runs_once_and_is_a_noop_on_reconnect(project):
    _v2_database(project)
    with db.connect(project) as conn:
        first = conn.execute("SELECT video_id, path FROM video ORDER BY path").fetchall()
    with db.connect(project) as conn:
        second = conn.execute("SELECT video_id, path FROM video ORDER BY path").fetchall()
        migrations = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action='migrate_v2_v3'").fetchone()[0]
    assert first == second, "video ids must be stable across reconnects"
    assert migrations == 1


# ── Identity ────────────────────────────────────────────────────────────────

def test_ensure_video_creates_once_and_reuses_thereafter(project):
    with db.connect(project) as conn:
        a = db.ensure_video(conn, "/data/a.avi")
        b = db.ensure_video(conn, "/data/a.avi")
        count = conn.execute("SELECT COUNT(*) FROM video").fetchone()[0]
    assert a == b
    assert a.startswith("vid_")
    assert count == 1


def test_ensure_video_backfills_metrics_on_a_later_call(project):
    with db.connect(project) as conn:
        vid = db.ensure_video(conn, "/data/a.avi")
        assert db.video_row(conn, vid)["fingerprint"] is None
        db.ensure_video(conn, "/data/a.avi", size_bytes=100, frame_count=10)
        row = db.video_row(conn, vid)
    assert row["size_bytes"] == 100
    assert row["frame_count"] == 10
    assert row["fingerprint"] == db.fingerprint(100, 10)


def test_relink_path_keeps_the_id_and_moves_the_data_with_it(project):
    with db.connect(project) as conn:
        vid = db.ensure_video(conn, "/old/a.avi")
        conn.execute("INSERT INTO tracked(video_id, tracked_at) VALUES (?, ?)",
                     (vid, db.now()))
        conn.execute("INSERT INTO progress_value VALUES (?,?,?,?)",
                     (vid, "seg_1", "opt_1", db.now()))
        assert db.relink_path(conn, vid, "/new/renamed.avi") is True
        row = db.video_row(conn, vid)
        still_tracked = conn.execute(
            "SELECT COUNT(*) FROM tracked WHERE video_id=?", (vid,)).fetchone()[0]
        still_valued = conn.execute(
            "SELECT COUNT(*) FROM progress_value WHERE video_id=?", (vid,)).fetchone()[0]
    assert row["path"] == "/new/renamed.avi"
    assert still_tracked == 1, "rename must not orphan the tracked flag"
    assert still_valued == 1, "rename must not orphan progress values"


def test_video_id_for_path_returns_none_when_unknown(project):
    with db.connect(project) as conn:
        assert db.video_id_for_path(conn, "/nope.avi") is None


# ── Fingerprint ─────────────────────────────────────────────────────────────

def test_fingerprint_is_stable_and_depends_on_both_inputs(project):
    assert db.fingerprint(100, 10) == db.fingerprint(100, 10)
    assert db.fingerprint(100, 10) != db.fingerprint(101, 10)
    assert db.fingerprint(100, 10) != db.fingerprint(100, 11)
    assert len(db.fingerprint(100, 10)) == 32          # blake2b digest_size=16


def test_fingerprint_is_none_without_both_metrics():
    assert db.fingerprint(None, 10) is None
    assert db.fingerprint(100, None) is None


def test_two_copies_of_one_recording_share_a_fingerprint_but_not_an_id(project):
    """Expected: a copy IS that recording. Hence the non-unique index."""
    with db.connect(project) as conn:
        a = db.ensure_video(conn, "/data/a.avi", size_bytes=999, frame_count=42)
        b = db.ensure_video(conn, "/backup/a.avi", size_bytes=999, frame_count=42)
        rows = conn.execute(
            "SELECT fingerprint FROM video ORDER BY path").fetchall()
    assert a != b
    assert rows[0][0] == rows[1][0]


# ── Audit ───────────────────────────────────────────────────────────────────

def test_audit_records_actor_action_and_payloads(project):
    with db.connect(project) as conn:
        db.audit(conn, "uid-123", "tracked", "vid_x", "track",
                 before=None, after={"tracked_at": "now"})
        row = conn.execute(
            "SELECT actor, entity, entity_id, action, before, after FROM audit_log"
        ).fetchone()
    assert row[0] == "uid-123"
    assert row[1] == "tracked"
    assert row[2] == "vid_x"
    assert row[3] == "track"
    assert row[4] is None
    assert json.loads(row[5]) == {"tracked_at": "now"}


def test_ensure_video_logs_creation_and_the_later_probe(project):
    with db.connect(project) as conn:
        db.ensure_video(conn, "/data/a.avi", actor="uid-1")
        db.ensure_video(conn, "/data/a.avi", actor="uid-1", size_bytes=5, frame_count=2)
        actions = [r[0] for r in conn.execute(
            "SELECT action FROM audit_log ORDER BY id")]
    assert actions == ["create_video", "probe_metadata"]


def test_relink_is_audited_with_before_and_after_paths(project):
    with db.connect(project) as conn:
        vid = db.ensure_video(conn, "/old/a.avi")
        db.relink_path(conn, vid, "/new/a.avi", actor="uid-9")
        row = conn.execute(
            "SELECT before, after FROM audit_log WHERE action='relink_path'").fetchone()
    assert json.loads(row[0]) == {"path": "/old/a.avi"}
    assert json.loads(row[1]) == {"path": "/new/a.avi"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_db.py -q`
Expected: collection error — `cannot import name 'tracked_db' from 'dlc'`

- [ ] **Step 3: Write minimal implementation**

Create `MAIN/src/dlc/tracked_db.py`:

```python
"""
Shared SQLite layer for the project's tracked-files database.

Owns the connection, the v3 schema, the v2->v3 migration, video identity and
the audit log. tracked_files.py and progress_bar.py are thin stores on top of
this; the schema lives here because both of them open the same file and a
migration written twice will eventually disagree with itself.

Identity: every video gets a surrogate `video_id`, assigned once and never
reused. `path` is a mutable attribute, NOT identity — renaming or moving a file
is an UPDATE of video.path, and every tracked flag and progress value follows
automatically because none of them ever stored a path.

Re-identification: `fingerprint` is blake2b over "<size_bytes>|<frame_count>",
both intrinsic to the recording, so it survives rename, move and copy. It is
NOT unique — two copies of one recording share it — so it is only ever a hint
for a future re-link sweep. mtime is deliberately excluded: `cp` without -p,
rsync and restores all change it.

Auditing: every mutation writes an audit_log row inside the SAME transaction as
the change, so a change cannot commit without its log entry.

This module imports no Flask, no DLC, no Redis, and never touches the
filesystem beyond its own DB file — probing is the route layer's job.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_FILENAME = "tracked_files.sqlite"
SCHEMA_VERSION = "3"


def db_path(project_path) -> Path:
    return Path(project_path) / DB_FILENAME


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_video_id() -> str:
    return f"vid_{secrets.token_hex(8)}"


def fingerprint(size_bytes, frame_count):
    """Stable id-hint for a recording. None unless BOTH metrics are known."""
    if size_bytes is None or frame_count is None:
        return None
    raw = f"{int(size_bytes)}|{int(frame_count)}".encode("utf-8")
    return hashlib.blake2b(raw, digest_size=16).hexdigest()


@contextmanager
def connect(project_path):
    conn = sqlite3.connect(str(db_path(project_path)), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        ensure_schema(conn)
        yield conn
    finally:
        conn.close()


# ── Schema ──────────────────────────────────────────────────────────────────

def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS video (
            video_id      TEXT PRIMARY KEY,
            path          TEXT NOT NULL,
            size_bytes    INTEGER,
            frame_count   INTEGER,
            fingerprint   TEXT,
            first_seen_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS video_path_idx ON video(path)")
    # NOT unique: two copies of one recording legitimately share a fingerprint.
    conn.execute("CREATE INDEX IF NOT EXISTS video_fingerprint_idx ON video(fingerprint)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            at        TEXT NOT NULL,
            actor     TEXT,
            entity    TEXT NOT NULL,
            entity_id TEXT,
            action    TEXT NOT NULL,
            before    TEXT,
            after     TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress_segment (
            segment_id TEXT PRIMARY KEY, position INTEGER NOT NULL, name TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress_option (
            option_id TEXT PRIMARY KEY, segment_id TEXT NOT NULL, position INTEGER NOT NULL,
            label TEXT NOT NULL, color TEXT NOT NULL
        )
    """)
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    _ensure_id_keyed_tables(conn)
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                 ("schema_version", SCHEMA_VERSION))


def _columns(conn, table) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _ensure_id_keyed_tables(conn: sqlite3.Connection) -> None:
    """Create tracked/progress_value in their v3 shape, migrating v2 if present."""
    tracked_cols = _columns(conn, "tracked")
    value_cols = _columns(conn, "progress_value")
    legacy = "video_path" in tracked_cols or "video_path" in value_cols

    if not legacy:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tracked (
                video_id       TEXT PRIMARY KEY,
                tracked_at     TEXT NOT NULL,
                last_opened_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS progress_value (
                video_id   TEXT NOT NULL,
                segment_id TEXT NOT NULL,
                option_id  TEXT NOT NULL,
                set_at     TEXT NOT NULL,
                PRIMARY KEY (video_id, segment_id)
            )
        """)
        return

    _migrate_v2_to_v3(conn, tracked_cols, value_cols)


def _migrate_v2_to_v3(conn: sqlite3.Connection, tracked_cols, value_cols) -> None:
    """One transaction: mint a video row per distinct path, re-key both tables.

    Never touches the filesystem — files may live on unmounted disks, and a
    schema upgrade must not depend on I/O it cannot guarantee. Metrics stay
    NULL and are backfilled on the next successful open.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        paths = {}          # path -> first_seen_at
        if "video_path" in tracked_cols:
            for path, tracked_at in conn.execute(
                    "SELECT video_path, tracked_at FROM tracked"):
                paths.setdefault(path, tracked_at)
        if "video_path" in value_cols:
            for (path,) in conn.execute("SELECT DISTINCT video_path FROM progress_value"):
                paths.setdefault(path, None)

        stamp = now()
        for path, first_seen in paths.items():
            conn.execute(
                "INSERT OR IGNORE INTO video(video_id, path, first_seen_at) VALUES (?,?,?)",
                (new_video_id(), path, first_seen or stamp))

        if "video_path" in tracked_cols:
            conn.execute("""
                CREATE TABLE tracked_v3 (
                    video_id TEXT PRIMARY KEY, tracked_at TEXT NOT NULL, last_opened_at TEXT)
            """)
            conn.execute("""
                INSERT INTO tracked_v3(video_id, tracked_at, last_opened_at)
                SELECT v.video_id, t.tracked_at, t.last_opened_at
                FROM tracked t JOIN video v ON v.path = t.video_path
            """)
            conn.execute("DROP TABLE tracked")
            conn.execute("ALTER TABLE tracked_v3 RENAME TO tracked")

        if "video_path" in value_cols:
            conn.execute("""
                CREATE TABLE progress_value_v3 (
                    video_id TEXT NOT NULL, segment_id TEXT NOT NULL,
                    option_id TEXT NOT NULL, set_at TEXT NOT NULL,
                    PRIMARY KEY (video_id, segment_id))
            """)
            conn.execute("""
                INSERT INTO progress_value_v3(video_id, segment_id, option_id, set_at)
                SELECT v.video_id, p.segment_id, p.option_id, p.set_at
                FROM progress_value p JOIN video v ON v.path = p.video_path
            """)
            conn.execute("DROP TABLE progress_value")
            conn.execute("ALTER TABLE progress_value_v3 RENAME TO progress_value")

        _audit_row(conn, None, "video", None, "migrate_v2_v3",
                   None, {"videos": len(paths)})
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ── Audit ───────────────────────────────────────────────────────────────────

def _audit_row(conn, actor, entity, entity_id, action, before, after) -> None:
    conn.execute(
        "INSERT INTO audit_log(at, actor, entity, entity_id, action, before, after) "
        "VALUES (?,?,?,?,?,?,?)",
        (now(), actor, entity, entity_id, action,
         json.dumps(before) if before is not None else None,
         json.dumps(after) if after is not None else None))


def audit(conn, actor, entity, entity_id, action, before=None, after=None) -> None:
    """Append one audit row. Callers MUST be inside the transaction that makes
    the change, so the two commit or roll back together."""
    _audit_row(conn, actor, entity, entity_id, action, before, after)


# ── Video identity ──────────────────────────────────────────────────────────

def video_id_for_path(conn, path: str):
    row = conn.execute("SELECT video_id FROM video WHERE path=?", (path,)).fetchone()
    return row[0] if row else None


def video_row(conn, video_id: str):
    row = conn.execute(
        "SELECT video_id, path, size_bytes, frame_count, fingerprint, first_seen_at "
        "FROM video WHERE video_id=?", (video_id,)).fetchone()
    if not row:
        return None
    return {"video_id": row[0], "path": row[1], "size_bytes": row[2],
            "frame_count": row[3], "fingerprint": row[4], "first_seen_at": row[5]}


def ensure_video(conn, path: str, actor=None, size_bytes=None, frame_count=None) -> str:
    """Return the video_id for `path`, creating the row on first sight.

    Metrics are optional and best-effort: a path that could not be probed still
    gets a row, and the metrics are backfilled by a later call that has them.
    Caller owns the transaction.
    """
    row = conn.execute(
        "SELECT video_id, size_bytes, frame_count FROM video WHERE path=?", (path,)
    ).fetchone()
    if row:
        vid, have_size, have_frames = row
        if (size_bytes is not None and frame_count is not None
                and (have_size is None or have_frames is None)):
            fp = fingerprint(size_bytes, frame_count)
            conn.execute(
                "UPDATE video SET size_bytes=?, frame_count=?, fingerprint=? WHERE video_id=?",
                (size_bytes, frame_count, fp, vid))
            audit(conn, actor, "video", vid, "probe_metadata", None,
                  {"size_bytes": size_bytes, "frame_count": frame_count, "fingerprint": fp})
        return vid

    vid = new_video_id()
    fp = fingerprint(size_bytes, frame_count)
    conn.execute(
        "INSERT INTO video(video_id, path, size_bytes, frame_count, fingerprint, first_seen_at) "
        "VALUES (?,?,?,?,?,?)",
        (vid, path, size_bytes, frame_count, fp, now()))
    audit(conn, actor, "video", vid, "create_video", None,
          {"path": path, "size_bytes": size_bytes, "frame_count": frame_count,
           "fingerprint": fp})
    return vid


def relink_path(conn, video_id: str, new_path: str, actor=None) -> bool:
    """Point an existing video at a new location. Identity is unchanged, so all
    tracked state and progress values follow. False when the id is unknown."""
    row = conn.execute("SELECT path FROM video WHERE video_id=?", (video_id,)).fetchone()
    if not row:
        return False
    old_path = row[0]
    conn.execute("UPDATE video SET path=? WHERE video_id=?", (new_path, video_id))
    audit(conn, actor, "video", video_id, "relink_path",
          {"path": old_path}, {"path": new_path})
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_db.py -q`
Expected: 20 passed

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/tracked_db.py src/tests/test_tracked_db.py
git commit -m "feat(db): shared tracked-files DB layer with video identity and audit log"
```

---

### Task 2: Re-key the tracked-files store

**Files:**
- Modify: `MAIN/src/dlc/tracked_files.py` (full rewrite over `tracked_db`)
- Modify: `MAIN/src/tests/test_tracked_files_store.py`

**Interfaces:**
- Consumes: Task 1's `connect`, `db_path`, `ensure_video`, `video_id_for_path`, `audit`, `now`.
- Produces: `list_tracked(project_path) -> list[dict]` with keys `video_id`, `path`, `tracked_at`, `last_opened_at`; `track(project_path, path, actor=None, size_bytes=None, frame_count=None) -> str` (the video_id); `untrack(project_path, video_id, actor=None) -> None`; `touch_opened(project_path, video_id, actor=None, size_bytes=None, frame_count=None) -> None`; `resolve(project_path, video_id=None, path=None) -> str | None`. Task 4 consumes these.

- [ ] **Step 1: Write the failing test**

Replace `MAIN/src/tests/test_tracked_files_store.py` entirely:

```python
"""Tests for src/dlc/tracked_files.py — now keyed by video_id."""
from __future__ import annotations
from pathlib import Path

import pytest

from dlc import tracked_db as db
from dlc import tracked_files as tf


@pytest.fixture
def project(tmp_path: Path) -> Path:
    p = tmp_path / "Proj-2026-08-01"
    p.mkdir()
    return p


def test_fresh_project_lists_nothing(project):
    assert tf.list_tracked(project) == []


def test_track_returns_a_video_id_and_lists_the_path(project):
    vid = tf.track(project, "/data/a.avi")
    assert vid.startswith("vid_")
    rows = tf.list_tracked(project)
    assert len(rows) == 1
    assert rows[0]["video_id"] == vid
    assert rows[0]["path"] == "/data/a.avi"
    assert rows[0]["last_opened_at"] is None


def test_track_is_idempotent_and_keeps_the_same_id(project):
    first = tf.track(project, "/data/a.avi")
    second = tf.track(project, "/data/a.avi")
    assert first == second
    assert len(tf.list_tracked(project)) == 1


def test_untrack_removes_the_row_but_keeps_the_video_identity(project):
    """Untracking must not destroy the id — re-tracking restores its history."""
    vid = tf.track(project, "/data/a.avi")
    tf.untrack(project, vid)
    assert tf.list_tracked(project) == []
    assert tf.track(project, "/data/a.avi") == vid


def test_touch_opened_only_stamps_an_existing_row(project):
    vid = tf.track(project, "/data/a.avi")
    tf.touch_opened(project, vid)
    assert tf.list_tracked(project)[0]["last_opened_at"] is not None

    other = db_only_video(project, "/data/other.avi")
    tf.touch_opened(project, other)
    assert [r["path"] for r in tf.list_tracked(project)] == ["/data/a.avi"]


def db_only_video(project, path):
    """A video row with no tracked row — used to prove touch_opened won't create one."""
    with db.connect(project) as conn:
        conn.execute("BEGIN IMMEDIATE")
        vid = db.ensure_video(conn, path)
        conn.execute("COMMIT")
    return vid


def test_renaming_via_relink_keeps_the_file_tracked(project):
    vid = tf.track(project, "/data/a.avi")
    with db.connect(project) as conn:
        conn.execute("BEGIN IMMEDIATE")
        db.relink_path(conn, vid, "/moved/renamed.avi")
        conn.execute("COMMIT")
    rows = tf.list_tracked(project)
    assert len(rows) == 1
    assert rows[0]["video_id"] == vid
    assert rows[0]["path"] == "/moved/renamed.avi"


def test_ordering_recently_opened_first_never_opened_last(project):
    a = tf.track(project, "/data/a.avi")
    b = tf.track(project, "/data/b.avi")
    c = tf.track(project, "/data/c.avi")
    tf.touch_opened(project, a)
    tf.touch_opened(project, c)
    order = [r["path"] for r in tf.list_tracked(project)]
    assert order[-1] == "/data/b.avi", "never-opened sorts last"
    assert set(order[:2]) == {"/data/a.avi", "/data/c.avi"}


def test_resolve_accepts_either_key(project):
    vid = tf.track(project, "/data/a.avi")
    assert tf.resolve(project, video_id=vid) == vid
    assert tf.resolve(project, path="/data/a.avi") == vid
    assert tf.resolve(project, video_id="vid_nope") is None
    assert tf.resolve(project, path="/nope.avi") is None


def test_every_mutation_is_audited(project):
    vid = tf.track(project, "/data/a.avi", actor="uid-7")
    tf.touch_opened(project, vid, actor="uid-7")
    tf.untrack(project, vid, actor="uid-7")
    with db.connect(project) as conn:
        rows = conn.execute(
            "SELECT action, actor FROM audit_log ORDER BY id").fetchall()
    actions = [r[0] for r in rows]
    assert "create_video" in actions
    assert actions.count("track") == 1
    assert actions.count("mark_opened") == 1
    assert actions.count("untrack") == 1
    assert {r[1] for r in rows} == {"uid-7"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_store.py -q`
Expected: failures — `track()` returns None / unexpected keyword `actor`

- [ ] **Step 3: Write minimal implementation**

Replace `MAIN/src/dlc/tracked_files.py` entirely:

```python
"""
Tracked video files, keyed by the surrogate video_id from tracked_db.

Tracking marks a video for quick reopening. Identity is the video_id, never the
path, so renaming or moving a file (an UPDATE of video.path) leaves the tracked
flag and its timestamps untouched.

Untracking deletes the tracked row but NEVER the video row: the identity — and
therefore the file's progress values and history — survives, so re-tracking the
same path returns the same id.

Imports no Flask, no DLC, no Redis, and never touches the filesystem.
"""
from __future__ import annotations

from .tracked_db import (  # noqa: F401  (DB_FILENAME re-exported for callers)
    DB_FILENAME, audit, connect, db_path, ensure_video, now, video_id_for_path,
)


def list_tracked(project_path) -> list:
    """Tracked videos, most recently opened first, never-opened last.

    SQLite has no NULLS LAST, hence the explicit leading sort key.
    """
    if not db_path(project_path).is_file():
        return []
    with connect(project_path) as conn:
        rows = conn.execute("""
            SELECT t.video_id, v.path, t.tracked_at, t.last_opened_at
            FROM tracked t JOIN video v ON v.video_id = t.video_id
            ORDER BY (t.last_opened_at IS NULL), t.last_opened_at DESC, t.tracked_at DESC
        """).fetchall()
    return [{"video_id": r[0], "path": r[1], "tracked_at": r[2], "last_opened_at": r[3]}
            for r in rows]


def track(project_path, path: str, actor=None, size_bytes=None, frame_count=None) -> str:
    """Start tracking `path`; returns its video_id. Idempotent: re-tracking
    preserves tracked_at, last_opened_at and the id."""
    with connect(project_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            vid = ensure_video(conn, path, actor=actor,
                               size_bytes=size_bytes, frame_count=frame_count)
            existing = conn.execute(
                "SELECT 1 FROM tracked WHERE video_id=?", (vid,)).fetchone()
            if not existing:
                stamp = now()
                conn.execute(
                    "INSERT INTO tracked(video_id, tracked_at, last_opened_at) "
                    "VALUES (?,?,NULL)", (vid, stamp))
                audit(conn, actor, "tracked", vid, "track", None,
                      {"path": path, "tracked_at": stamp})
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return vid


def untrack(project_path, video_id: str, actor=None) -> None:
    """Stop tracking. The video row (identity, fingerprint, progress values)
    is deliberately left in place."""
    if not db_path(project_path).is_file():
        return
    with connect(project_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT tracked_at, last_opened_at FROM tracked WHERE video_id=?",
                (video_id,)).fetchone()
            if row:
                conn.execute("DELETE FROM tracked WHERE video_id=?", (video_id,))
                audit(conn, actor, "tracked", video_id, "untrack",
                      {"tracked_at": row[0], "last_opened_at": row[1]}, None)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def touch_opened(project_path, video_id: str, actor=None,
                 size_bytes=None, frame_count=None) -> None:
    """Stamp last_opened_at, and backfill the video's metrics if supplied.

    Only stamps an EXISTING tracked row — opening an untracked video must never
    start tracking it.
    """
    if not db_path(project_path).is_file():
        return
    with connect(project_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT last_opened_at, (SELECT path FROM video WHERE video_id=?) "
                "FROM tracked WHERE video_id=?", (video_id, video_id)).fetchone()
            if row:
                stamp = now()
                conn.execute("UPDATE tracked SET last_opened_at=? WHERE video_id=?",
                             (stamp, video_id))
                audit(conn, actor, "tracked", video_id, "mark_opened",
                      {"last_opened_at": row[0]}, {"last_opened_at": stamp})
                if size_bytes is not None and frame_count is not None:
                    ensure_video(conn, row[1], actor=actor,
                                 size_bytes=size_bytes, frame_count=frame_count)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def resolve(project_path, video_id=None, path=None):
    """Return an existing video_id from either key, or None. Never creates."""
    if not db_path(project_path).is_file():
        return None
    with connect(project_path) as conn:
        if video_id:
            row = conn.execute(
                "SELECT video_id FROM video WHERE video_id=?", (video_id,)).fetchone()
            return row[0] if row else None
        if path:
            return video_id_for_path(conn, path)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_store.py src/tests/test_tracked_db.py -q`
Expected: 30 passed

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/tracked_files.py src/tests/test_tracked_files_store.py
git commit -m "refactor(tracked-files): key the store by video_id and audit every mutation"
```

---

### Task 3: Re-key the progress store

**Files:**
- Modify: `MAIN/src/dlc/progress_bar.py`
- Modify: `MAIN/src/tests/test_progress_bar_store.py`

**Interfaces:**
- Consumes: Task 1's `connect`, `db_path`, `audit`, `now`; Task 2 is independent of this task.
- Produces: `get_definition(project_path) -> dict` (unchanged shape); `save_definition(project_path, segments, actor=None) -> dict`; `get_values(project_path, video_ids) -> {video_id: {segment_id: option_id}}`; `set_value(project_path, video_id, segment_id, option_id, actor=None) -> None`; `MAX_SEGMENTS = 10`. Task 4 consumes these.

- [ ] **Step 1: Write the failing test**

In `MAIN/src/tests/test_progress_bar_store.py`, replace the two value-related
tests and add audit coverage. Replace `test_values_round_trip_and_clear`,
`test_get_values_batches_and_omits_files_without_values` and
`test_deleting_a_segment_leaves_its_values_in_the_db` with:

```python
def _video(project, path):
    """Mint a video_id the way the routes will."""
    from dlc import tracked_db as db
    with db.connect(project) as conn:
        conn.execute("BEGIN IMMEDIATE")
        vid = db.ensure_video(conn, path)
        conn.execute("COMMIT")
    return vid


def test_values_round_trip_and_clear(project):
    pb.save_definition(project, [_seg("Label", [{"label": "Done", "color": "#2ea043"}])])
    seg = pb.get_definition(project)["segments"][0]
    sid, oid = seg["segment_id"], seg["options"][0]["option_id"]
    vid = _video(project, "/data/a.avi")

    pb.set_value(project, vid, sid, oid)
    assert pb.get_values(project, [vid]) == {vid: {sid: oid}}

    pb.set_value(project, vid, sid, None)
    assert pb.get_values(project, [vid]) == {}


def test_get_values_batches_and_omits_videos_without_values(project):
    pb.save_definition(project, [_seg("Label", [{"label": "Done", "color": "#2ea043"}])])
    seg = pb.get_definition(project)["segments"][0]
    sid, oid = seg["segment_id"], seg["options"][0]["option_id"]
    a, b = _video(project, "/data/a.avi"), _video(project, "/data/b.avi")
    pb.set_value(project, a, sid, oid)
    assert set(pb.get_values(project, [a, b])) == {a}


def test_deleting_a_segment_leaves_its_values_in_the_db(project):
    """No cascade: the value survives so re-adding the ID restores it."""
    pb.save_definition(project, [_seg("Label", [{"label": "Done", "color": "#2ea043"}])])
    seg = pb.get_definition(project)["segments"][0]
    sid, oid = seg["segment_id"], seg["options"][0]["option_id"]
    vid = _video(project, "/data/a.avi")
    pb.set_value(project, vid, sid, oid)

    pb.save_definition(project, [])
    assert pb.get_definition(project) == {"segments": []}
    assert pb.get_values(project, [vid]) == {vid: {sid: oid}}


def test_values_survive_a_rename(project):
    """The whole point of video_id: moving the file keeps its progress."""
    from dlc import tracked_db as db
    pb.save_definition(project, [_seg("Label", [{"label": "Done", "color": "#2ea043"}])])
    seg = pb.get_definition(project)["segments"][0]
    sid, oid = seg["segment_id"], seg["options"][0]["option_id"]
    vid = _video(project, "/data/a.avi")
    pb.set_value(project, vid, sid, oid)

    with db.connect(project) as conn:
        conn.execute("BEGIN IMMEDIATE")
        db.relink_path(conn, vid, "/elsewhere/renamed.avi")
        conn.execute("COMMIT")

    assert pb.get_values(project, [vid]) == {vid: {sid: oid}}


def test_definition_and_value_writes_are_audited(project):
    from dlc import tracked_db as db
    pb.save_definition(project, [_seg("L", [{"label": "D", "color": "#2ea043"}])],
                       actor="uid-3")
    seg = pb.get_definition(project)["segments"][0]
    vid = _video(project, "/data/a.avi")
    pb.set_value(project, vid, seg["segment_id"], seg["options"][0]["option_id"],
                 actor="uid-3")
    pb.set_value(project, vid, seg["segment_id"], None, actor="uid-3")

    with db.connect(project) as conn:
        actions = [r[0] for r in conn.execute(
            "SELECT action FROM audit_log ORDER BY id")]
    assert actions.count("save_definition") == 1
    assert actions.count("set_value") == 1
    assert actions.count("clear_value") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_progress_bar_store.py -q`
Expected: failures — `set_value` still expects a path, no audit rows

- [ ] **Step 3: Write minimal implementation**

In `MAIN/src/dlc/progress_bar.py`, replace the module docstring's schema block,
delete its private `_db_path`/`_connect`/`_ensure_schema`/`_now` (they now live
in `tracked_db`), and import from the shared layer instead. Replace the imports
and helpers at the top with:

```python
from __future__ import annotations

import re
import secrets

from .tracked_db import audit, connect, db_path, now

MAX_SEGMENTS = 10

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def is_valid_color(value) -> bool:
    return isinstance(value, str) and bool(_HEX_COLOR_RE.match(value))
```

Change `get_definition` to use `db_path`/`connect` (replace `_db_path` with
`db_path` and `_connect` with `connect`; the body is otherwise unchanged).

Replace `save_definition`'s signature and transaction body with:

```python
def save_definition(project_path, segments, actor=None) -> dict:
    """Replace the definition. Entries carrying an id keep it; entries without
    one get a fresh id. Segments/options absent from `segments` are removed
    from the definition but their progress_value rows are left untouched.

    Raises ValueError on >MAX_SEGMENTS or a colour that is not '#rrggbb'.
    """
    segments = list(segments or [])
    if len(segments) > MAX_SEGMENTS:
        raise ValueError(f"at most {MAX_SEGMENTS} segments (got {len(segments)})")
    for seg in segments:
        for opt in seg.get("options") or []:
            if not is_valid_color(opt.get("color")):
                raise ValueError(f"invalid colour: {opt.get('color')!r}")

    rows_seg, rows_opt = [], []
    for s_pos, seg in enumerate(segments):
        sid = seg.get("segment_id") or _new_id("seg")
        rows_seg.append((sid, s_pos, str(seg.get("name", ""))))
        for o_pos, opt in enumerate(seg.get("options") or []):
            oid = opt.get("option_id") or _new_id("opt")
            rows_opt.append((oid, sid, o_pos, str(opt.get("label", "")), opt["color"]))

    with connect(project_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            before = {
                "segments": conn.execute(
                    "SELECT COUNT(*) FROM progress_segment").fetchone()[0],
                "options": conn.execute(
                    "SELECT COUNT(*) FROM progress_option").fetchone()[0],
            }
            conn.execute("DELETE FROM progress_option")
            conn.execute("DELETE FROM progress_segment")
            conn.executemany(
                "INSERT INTO progress_segment(segment_id, position, name) VALUES (?,?,?)",
                rows_seg)
            conn.executemany(
                "INSERT INTO progress_option(option_id, segment_id, position, label, color) "
                "VALUES (?,?,?,?,?)", rows_opt)
            # Counts, not the whole definition — the log stays readable.
            audit(conn, actor, "progress_definition", None, "save_definition",
                  before, {"segments": len(rows_seg), "options": len(rows_opt)})
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return get_definition(project_path)
```

Replace `get_values` and `set_value` with:

```python
def get_values(project_path, video_ids) -> dict:
    """{video_id: {segment_id: option_id}} for the given ids, batched into one
    query. Videos with no stored value are omitted entirely."""
    ids = [v for v in (video_ids or []) if v]
    if not ids or not db_path(project_path).is_file():
        return {}
    out: dict = {}
    with connect(project_path) as conn:
        # Chunked so a huge tracked list cannot exceed SQLite's variable limit.
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            marks = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT video_id, segment_id, option_id FROM progress_value "
                f"WHERE video_id IN ({marks})", chunk).fetchall()
            for vid, sid, oid in rows:
                out.setdefault(vid, {})[sid] = oid
    return out


def set_value(project_path, video_id: str, segment_id: str, option_id, actor=None) -> None:
    """Set one segment's option for one video. option_id=None clears it."""
    with connect(project_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            prev = conn.execute(
                "SELECT option_id FROM progress_value WHERE video_id=? AND segment_id=?",
                (video_id, segment_id)).fetchone()
            before = {"option_id": prev[0]} if prev else None
            if option_id is None:
                conn.execute(
                    "DELETE FROM progress_value WHERE video_id=? AND segment_id=?",
                    (video_id, segment_id))
                audit(conn, actor, "progress_value", video_id, "clear_value",
                      before, None)
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO progress_value"
                    "(video_id, segment_id, option_id, set_at) VALUES (?,?,?,?)",
                    (video_id, segment_id, option_id, now()))
                audit(conn, actor, "progress_value", video_id, "set_value",
                      before, {"segment_id": segment_id, "option_id": option_id})
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_progress_bar_store.py src/tests/test_tracked_files_store.py src/tests/test_tracked_db.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/progress_bar.py src/tests/test_progress_bar_store.py
git commit -m "refactor(progress-bar): key values by video_id and audit every write"
```

---

### Task 4: Routes — probe metadata, supply the actor, accept video_id

**Files:**
- Modify: `MAIN/src/dlc/tracked_files_routes.py`, `MAIN/src/dlc/progress_bar_routes.py`
- Modify: `MAIN/src/tests/test_tracked_files_routes.py`, `MAIN/src/tests/test_progress_bar_routes.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: `GET /dlc/project/tracked-files` files gain `video_id`; `DELETE`/`opened`/`progress-bar/value` accept `{video_id}` or `{path}`. Task 5 consumes `video_id` from the listing.

- [ ] **Step 1: Write the failing test**

Add to `MAIN/src/tests/test_tracked_files_routes.py`:

```python
def test_listing_carries_a_video_id(tracked_project):
    client, _ = tracked_project
    client.post("/dlc/project/tracked-files", json={"path": "/data/a.avi"})
    files = client.get("/dlc/project/tracked-files").get_json()["files"]
    assert files[0]["video_id"].startswith("vid_")


def test_delete_accepts_a_video_id(tracked_project):
    client, _ = tracked_project
    client.post("/dlc/project/tracked-files", json={"path": "/data/a.avi"})
    vid = client.get("/dlc/project/tracked-files").get_json()["files"][0]["video_id"]
    rv = client.delete("/dlc/project/tracked-files", json={"video_id": vid})
    assert rv.status_code == 200
    assert client.get("/dlc/project/tracked-files").get_json()["files"] == []


def test_unknown_video_id_is_rejected(tracked_project):
    client, _ = tracked_project
    rv = client.delete("/dlc/project/tracked-files", json={"video_id": "vid_nope"})
    assert rv.status_code == 400


def test_tracking_an_unopenable_path_still_succeeds_with_null_metrics(tracked_project):
    """Probing is best effort — a path we cannot open must still be trackable."""
    from dlc import tracked_db as db
    client, proj = tracked_project
    assert client.post("/dlc/project/tracked-files",
                       json={"path": "/nowhere/gone.avi"}).status_code == 200
    with db.connect(proj) as conn:
        row = conn.execute(
            "SELECT size_bytes, frame_count, fingerprint FROM video "
            "WHERE path='/nowhere/gone.avi'").fetchone()
    assert row == (None, None, None)


def test_writes_are_attributed_to_the_session_uid(tracked_project):
    from dlc import tracked_db as db
    client, proj = tracked_project
    client.post("/dlc/project/tracked-files", json={"path": "/data/a.avi"})
    with db.connect(proj) as conn:
        actors = {r[0] for r in conn.execute(
            "SELECT actor FROM audit_log WHERE action='track'")}
    assert actors == {"test-uid"}
```

Add to `MAIN/src/tests/test_progress_bar_routes.py`:

```python
def test_value_route_accepts_a_video_id(bar_project):
    client, _ = bar_project
    seg = _save(client, [{"name": "Label", "options": [
        {"label": "Done", "color": "#2ea043"}]}]).get_json()["segments"][0]
    sid, oid = seg["segment_id"], seg["options"][0]["option_id"]
    client.post("/dlc/project/tracked-files", json={"path": "/data/a.avi"})
    vid = client.get("/dlc/project/tracked-files").get_json()["files"][0]["video_id"]

    rv = client.put("/dlc/project/progress-bar/value",
                    json={"video_id": vid, "segment_id": sid, "option_id": oid})
    assert rv.status_code == 200
    files = client.get("/dlc/project/tracked-files").get_json()["files"]
    assert files[0]["progress"] == {sid: oid}


def test_value_route_rejects_an_unknown_video_id(bar_project):
    client, _ = bar_project
    rv = client.put("/dlc/project/progress-bar/value",
                    json={"video_id": "vid_nope", "segment_id": "seg_1",
                          "option_id": None})
    assert rv.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_routes.py src/tests/test_progress_bar_routes.py -q`
Expected: failures — no `video_id` key, `video_id` body ignored

- [ ] **Step 3: Write minimal implementation**

In `MAIN/src/dlc/tracked_files_routes.py`, add these imports and helpers below
the existing imports:

```python
from flask import session as flask_session

from . import tracked_db as _db


def _actor():
    """The Flask session uid. Identifies a browser session, not a person."""
    return flask_session.get("uid")


def _probe(path: str):
    """(size_bytes, frame_count), best effort — (None, None) on any failure.

    Reads only the container header, never the 12-16 GB payload.
    """
    try:
        p = Path(path)
        if not p.is_file():
            return None, None
        size = p.stat().st_size
        import cv2
        cap = cv2.VideoCapture(str(p))
        if not cap.isOpened():
            return None, None
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        return (size, frames) if frames > 0 else (None, None)
    except Exception:
        return None, None


def _resolve_video(pp, body):
    """video_id from {video_id} (preferred) or {path}. None when unresolvable."""
    vid = body.get("video_id")
    if isinstance(vid, str) and vid.strip():
        return _store.resolve(pp, video_id=vid.strip())
    path = body.get("path")
    if isinstance(path, str) and path.strip():
        return _store.resolve(pp, path=path.strip())
    return None
```

Replace `list_tracked_files`'s `files` construction with:

```python
    ids = [r["video_id"] for r in rows]
    try:
        values = _progress.get_values(pp, ids)
    except sqlite3.Error:
        values = {}          # progress is decorative here; never fail the listing
    files = [
        {
            "video_id": r["video_id"],
            "path": r["path"],
            "name": Path(r["path"]).name,
            "dir": str(Path(r["path"]).parent),
            "tracked_at": r["tracked_at"],
            "last_opened_at": r["last_opened_at"],
            "progress": values.get(r["video_id"], {}),
        }
        for r in rows
    ]
```

Replace `track_file`'s store call with:

```python
    size_bytes, frame_count = _probe(path)
    try:
        video_id = _store.track(pp, path, actor=_actor(),
                                size_bytes=size_bytes, frame_count=frame_count)
    except sqlite3.Error as exc:
        return jsonify({"error": f"tracked-files DB error: {exc}"}), 500
    return jsonify({"ok": True, "tracked": True, "video_id": video_id})
```

Replace `untrack_file`'s body after the project check with:

```python
    body = request.get_json(silent=True) or {}
    video_id = _resolve_video(pp, body)
    if not video_id:
        return jsonify({"error": "unknown video"}), 400
    try:
        _store.untrack(pp, video_id, actor=_actor())
    except sqlite3.Error as exc:
        return jsonify({"error": f"tracked-files DB error: {exc}"}), 500
    return jsonify({"ok": True, "tracked": False})
```

Replace `mark_opened`'s body after the project check with:

```python
    body = request.get_json(silent=True) or {}
    video_id = _resolve_video(pp, body)
    if not video_id:
        return jsonify({"error": "unknown video"}), 400
    row = None
    try:
        with _db.connect(pp) as conn:
            row = _db.video_row(conn, video_id)
        size_bytes, frame_count = _probe(row["path"]) if row else (None, None)
        _store.touch_opened(pp, video_id, actor=_actor(),
                            size_bytes=size_bytes, frame_count=frame_count)
    except sqlite3.Error as exc:
        return jsonify({"error": f"tracked-files DB error: {exc}"}), 500
    return jsonify({"ok": True})
```

In `MAIN/src/dlc/progress_bar_routes.py`, add below the existing imports:

```python
from flask import session as flask_session

from . import tracked_files as _tracked


def _actor():
    return flask_session.get("uid")
```

Replace `put_progress_bar`'s store call with:

```python
        definition = _store.save_definition(pp, segments, actor=_actor())
```

Replace `put_progress_value`'s body after the project check with:

```python
    body = request.get_json(silent=True) or {}
    segment_id = body.get("segment_id", "")
    if not isinstance(segment_id, str) or not segment_id.strip():
        return jsonify({"error": "segment_id required"}), 400
    option_id = body.get("option_id")
    if option_id is not None and not isinstance(option_id, str):
        return jsonify({"error": "option_id must be a string or null"}), 400

    vid = body.get("video_id")
    video_id = (_tracked.resolve(pp, video_id=vid.strip())
                if isinstance(vid, str) and vid.strip() else None)
    if not video_id:
        path = body.get("path")
        video_id = (_tracked.resolve(pp, path=path.strip())
                    if isinstance(path, str) and path.strip() else None)
    if not video_id:
        return jsonify({"error": "unknown video"}), 400

    try:
        _store.set_value(pp, video_id, segment_id.strip(), option_id, actor=_actor())
    except sqlite3.Error as exc:
        return jsonify({"error": f"progress-bar DB error: {exc}"}), 500
    return jsonify({"ok": True})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_routes.py src/tests/test_progress_bar_routes.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/tracked_files_routes.py src/dlc/progress_bar_routes.py \
        src/tests/test_tracked_files_routes.py src/tests/test_progress_bar_routes.py
git commit -m "feat(routes): probe video metadata, attribute writes, accept video_id"
```

---

### Task 5: Client sends video_id

**Files:**
- Modify: `MAIN/src/static/js/components/tracked_files_tab.js`
- Modify: `MAIN/src/tests/test_tracked_files_tab_source.py`

**Interfaces:**
- Consumes: Task 4's `video_id` on each listed file.
- Produces: nothing later depends on it.

- [ ] **Step 1: Write the failing test**

Append to `MAIN/src/tests/test_tracked_files_tab_source.py`:

```python
def test_writes_are_keyed_by_video_id_not_path():
    """A rename mid-session must not misdirect an untrack or a segment write."""
    s = _src()
    assert re.search(r"video_id:\s*f\.video_id", s), \
        "untrack must send the row's video_id"
    assert re.search(r"video_id:\s*videoId", s), \
        "segment writes must send the video_id"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_tab_source.py -q`
Expected: 1 failed

- [ ] **Step 3: Write minimal implementation**

In `MAIN/src/static/js/components/tracked_files_tab.js`:

Change `_body` so it can carry either key:

```javascript
  const _body = (payload) => ({ headers: JSON_HEADERS, body: JSON.stringify(payload) });
```

Update `_untrack` to take the row and send its id:

```javascript
  async function _untrack(f, cb) {
    try {
      await _fetchJson(API, { method: "DELETE", ..._body({ video_id: f.video_id }) });
      _rows.delete(f.path);
      _render();
      _syncHeader();
    } catch (err) {
      if (cb) cb.checked = true;                            // revert
      onError?.(`Could not untrack ${f.path} — ${err.message}`);
    }
  }
```

Update `_setSegment` to take the video id:

```javascript
  async function _setSegment(path, videoId, segmentId, optionId) {
    await _fetchJson(BAR_API + "/value", {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ video_id: videoId, segment_id: segmentId, option_id: optionId }),
    });
    const row = _rows.get(path);
    if (row) {
      row.progress = row.progress || {};
      if (optionId === null) delete row.progress[segmentId];
      else row.progress[segmentId] = optionId;
    }
  }
```

In `_makeRow`, update both call sites:

```javascript
    cb.addEventListener("change", () => _untrack(f, cb), _sig);
```

```javascript
    const bar = makeProgressBar({
      definition: _definition,
      values: f.progress || {},
      onChange: (segmentId, optionId) =>
        _setSegment(f.path, f.video_id, segmentId, optionId),
    });
```

The header checkbox still tracks by path (you track a location), so leave
`_track` sending `{ path }`, and change its untrack branch to look the row up:

```javascript
  headerCheckbox?.addEventListener("change", () => {
    if (!_current) return;
    if (headerCheckbox.checked) _track(_current);
    else {
      const row = _rows.get(_current);
      if (row) _untrack(row, headerCheckbox);
    }
  }, _sig);
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
python -m pytest src/tests/test_tracked_files_tab_source.py -q
cp src/static/js/components/tracked_files_tab.js /tmp/tft.mjs && node --check /tmp/tft.mjs && echo "SYNTAX OK"
```
Expected: all pass, `SYNTAX OK`

- [ ] **Step 5: Full verification, both repos**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
python -m pytest -q -p no:randomly 2>&1 | tail -4
for f in tests/unit/*.mjs; do printf "%-32s " "$(basename $f)"; \
  node "$f" 2>&1 | grep -E "^# (pass|fail)" | tr '\n' ' '; echo; done
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q --ignore=tests/e2e 2>&1 | tail -3
```
Expected: main webapp at the **16** known failures and no others; every `.mjs`
file `# fail 0`; dlc-3D at the **8** known failures.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/static/js/components/tracked_files_tab.js src/tests/test_tracked_files_tab_source.py
git commit -m "feat(tracked-files): send video_id on writes so renames cannot misdirect them"
```

---

### Task 6: Deploy and verify

**Files:** none — deployment and verification only.

Dispatch to a **subagent** with this brief verbatim:

> Deploy and verify the video-identity + audit-log change. Report findings only — do NOT edit, fix, or commit anything.
>
> 1. `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose up -d --force-recreate flask && docker compose up -d dlc-3d`. `--force-recreate` on flask is REQUIRED: `src/app.py` and several modules are single-file bind mounts and Docker binds the inode, so an edited file never reaches a merely-restarted container. Do NOT rebuild images. Do NOT touch `worker` or `worker-tf`.
> 2. `docker compose ps`, then `docker compose logs --tail=60 flask dlc-3d`. Any traceback mentioning `tracked_db`, `tracked_files` or `progress_bar` is a hard failure — quote it and stop.
> 3. The app is behind session auth; unauthenticated requests 302 to /login, which is a FALSE NEGATIVE. Seed a cookie jar: `curl -sc /tmp/cj.txt "http://localhost:5000/?token=deeplabcut" -o /dev/null`, then pass `-b /tmp/cj.txt` on every check.
> 4. `curl -sb /tmp/cj.txt -w ' [%{http_code}]\n' http://localhost:5000/dlc/project/tracked-files` — expect 200, or 400 with body `{"error":"No active DLC project."}`. A 404 means the blueprint did not register.
> 5. Same for `http://localhost:5000/dlc/project/progress-bar`.
> 6. Confirm the client asset is the new one: `curl -sb /tmp/cj.txt http://localhost:5000/static/js/components/tracked_files_tab.js | grep -c video_id` must be >= 2.
> 7. Report whether any project database on disk has already migrated. Find candidates with `ls /home/sam/data-disk/Parra-Data/**/tracked_files.sqlite 2>/dev/null | head -5`; for each, run `python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(sys.argv[1], c.execute(\"SELECT value FROM meta WHERE key='schema_version'\").fetchone(), [r[1] for r in c.execute('PRAGMA table_info(tracked)')])" <path>`. Report the schema_version and column list for each. A DB still at "2" is EXPECTED if nobody has opened that project since the deploy — migration runs on first connect, not at startup. Do not open the UI to force it.
>
> Report: recreate result, any log errors quoted, the status code for steps 4–6, and the per-database schema versions from step 7, with one-line PASS/FAIL per check.

- [ ] **Step 1: Dispatch the deployment subagent with the brief above**

- [ ] **Step 2: Act on the report** — fix anything that failed, re-run that task's tests, re-dispatch.

- [ ] **Step 3: Manual smoke test** at `http://localhost:5000/` with a project active:

1. Open **Tracked Files & Progress**. The existing tracked files still list, with their folders, last-opened times and progress bars intact — this proves the v2→v3 migration preserved everything.
2. Set a progress segment on a file, reload, confirm it persisted.
3. Rename that video on disk, then in a Python shell update its row:
   `UPDATE video SET path='<new path>' WHERE video_id='<its id>'` — reopen the card and confirm the file still appears **with its progress intact** under the new name. This is the whole point of the change.
4. Inspect the audit trail:
   `sqlite3 <project>/tracked_files.sqlite "SELECT at, actor, action, entity_id FROM audit_log ORDER BY id DESC LIMIT 10;"`
   Every action from steps 1–3 should be present with a session uid.

---

## Self-Review

**Spec coverage:** schema v3 + migration + identity + audit helper → Task 1; tracked store re-key → Task 2; progress store re-key → Task 3; probing, actor, `video_id` API → Task 4; client → Task 5; deployment → Task 6. The spec's "fingerprint is a hint, not a key" is enforced by Task 1's non-unique index and its two-copies test; "migration never probes" by Task 1's NULL-metrics test.

**Placeholder scan:** none — every step carries its code. Task 3 step 3 gives edits rather than the whole file because `progress_bar.py`'s `get_definition` body is unchanged; the instruction names the exact substitutions (`_db_path`→`db_path`, `_connect`→`connect`).

**Type consistency:** `list_tracked` returns `video_id`/`path`/`tracked_at`/`last_opened_at` in Task 2 and is consumed with exactly those keys in Task 4. `get_values(project_path, video_ids)` in Task 3 is called with `ids` (a list of `video_id`) in Task 4. `ensure_video(conn, path, actor, size_bytes, frame_count)` in Task 1 is called with those keywords in Tasks 2 and 4. `resolve(project_path, video_id=, path=)` in Task 2 is used by both route modules in Task 4. `_setSegment(path, videoId, segmentId, optionId)` in Task 5 matches its only call site.

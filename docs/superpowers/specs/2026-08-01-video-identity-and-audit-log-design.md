# Video Identity & Audit Log — design

Date: 2026-08-01
Status: approved, ready for planning

Builds on [2026-07-31-tracked-files-design.md](2026-07-31-tracked-files-design.md)
and [2026-08-01-progress-arrow-bar-design.md](2026-08-01-progress-arrow-bar-design.md).

## Problem

Both existing tables key on the video's absolute path. Renaming a file, or
moving it to another folder, orphans everything attached to it: its tracked
flag, its last-opened time, and every progress value. The data is not wrong —
it is simply unreachable, and re-tracking the file starts from zero.

Separately, nothing records who changed what. A cleared progress segment or an
untracked file leaves no trace.

## Goals

1. Give every video a surrogate identity that survives renaming and moving.
2. Record enough intrinsic metadata to re-link a moved file later.
3. Log every change to the project database, atomically with the change.

## Scope

In scope: the shared DB layer, the schema migration, video identity, the audit
log, and the route changes needed to populate them.

Out of scope: detecting and repairing moved files. This change records the
fingerprint that a future "verify tracked files" sweep will match on; the sweep
itself belongs to the planned file-management module.

Nothing changes visually. The one client-side change is that
`tracked_files_tab.js` sends `video_id` instead of `path` on writes — no markup,
no styling, no new controls.

## Decisions taken

| Question | Decision |
| --- | --- |
| Identity | Surrogate `video_id`, assigned once, never reused |
| Re-identification data | `frame_count` + `size_bytes` only |
| When to re-link | Not now — store the fingerprint, repair later |
| Logging | Audit table in the same project DB |
| Actor | Flask session uid, passed in from the route layer |

## Architecture

The schema is now shared by two store modules, so it moves into one place
rather than being created twice:

```
dlc/tracked_db.py        NEW — connection, schema v3, migration, audit, video identity
dlc/tracked_files.py     uses tracked_db; keyed by video_id
dlc/progress_bar.py      uses tracked_db; keyed by video_id
dlc/tracked_files_routes.py   probes metadata, supplies the actor
dlc/progress_bar_routes.py    same
```

Extracting `tracked_db.py` is required, not cosmetic: both modules run
`_ensure_schema` on every connect, and a migration executed from two
independent definitions will eventually disagree. One owner, one migration.

### 1. Schema (v3)

```
video(video_id      TEXT PRIMARY KEY,   -- 'vid_' + 16 hex; assigned once, never reused
      path          TEXT NOT NULL,      -- current location; mutable, NOT identity
      size_bytes    INTEGER,            -- NULL until first successful probe
      frame_count   INTEGER,            -- NULL until first successful probe
      fingerprint   TEXT,               -- blake2b_16("<size>|<frames>"); NULL until probed
      first_seen_at TEXT NOT NULL)
  CREATE UNIQUE INDEX video_path_idx ON video(path)
  CREATE INDEX video_fingerprint_idx ON video(fingerprint)   -- deliberately NOT unique

tracked(video_id TEXT PRIMARY KEY, tracked_at TEXT NOT NULL, last_opened_at TEXT)

progress_value(video_id TEXT NOT NULL, segment_id TEXT NOT NULL,
               option_id TEXT NOT NULL, set_at TEXT NOT NULL,
               PRIMARY KEY (video_id, segment_id))

audit_log(id        INTEGER PRIMARY KEY AUTOINCREMENT,
          at        TEXT NOT NULL,      -- "%Y-%m-%dT%H:%M:%SZ" UTC
          actor     TEXT,               -- Flask session uid; NULL when unknown
          entity    TEXT NOT NULL,      -- video | tracked | progress_value | progress_definition
          entity_id TEXT,               -- video_id, segment_id, or NULL
          action    TEXT NOT NULL,
          before    TEXT,               -- JSON or NULL
          after     TEXT)               -- JSON or NULL

progress_segment / progress_option    unchanged
meta                                  schema_version = "3"
```

`path` is unique because one location is one video. `fingerprint` is **not**
unique: two copies of the same recording fingerprint identically, which is
correct — they are that recording — but it means the fingerprint can only ever
be a re-link *hint*. `video_id` stays the sole identity.

Renaming or moving becomes `UPDATE video SET path=?`. Nothing else changes,
because nothing else ever stored a path.

### 2. Fingerprint

`fingerprint = blake2b(f"{size_bytes}|{frame_count}", digest_size=16).hexdigest()`

Byte size alone is close to unique for a 12–16 GB recording; combined with
frame count a false match is not a practical concern. Both fields are intrinsic
to the recording, so the fingerprint survives rename, move, and copy to another
disk. It does **not** survive re-encoding or truncation — such a file is a
different recording and should get a new identity.

`mtime` is deliberately excluded: it is not intrinsic, and `cp` without `-p`,
rsync, or a restore from backup all change it — breaking re-linking exactly
when it is needed.

### 3. Purity and where probing happens

`tracked_db.py`, `tracked_files.py` and `progress_bar.py` still import no
Flask, no DLC, no Redis, and still never touch the filesystem. The **route**
probes the video (`cv2.VideoCapture`, as `/annotate/video-info` already does)
and passes `size_bytes` and `frame_count` in.

Probing is **best effort**. Tracking a path that cannot be opened still
succeeds, creating a `video` row with NULL metrics — this preserves today's
behaviour, where tracking never stats. The metrics are backfilled on the next
`POST /dlc/project/tracked-files/opened`, which the client only sends after an
open has succeeded, so the file is known to exist and its header was just read.

The **migration never probes**: files may be on unmounted disks, and a schema
upgrade must not depend on I/O it cannot guarantee.

### 4. Migration (v2 → v3)

Runs inside one transaction, guarded by `meta.schema_version`, so it executes
once and is a no-op on every subsequent connect.

1. Create `video`, `audit_log` and the new-shaped `tracked` / `progress_value`
   under temporary names.
2. Insert one `video` row per distinct path found in the old `tracked` and
   `progress_value` tables — a fresh `video_id`, `path` carried over, metrics
   NULL, `first_seen_at` = the old `tracked_at` where known, else now.
3. Copy the old rows across, joining on path to pick up `video_id`.
4. Drop the old tables, rename the new ones into place.
5. Write one `audit_log` row: `entity="video"`, `action="migrate_v2_v3"`,
   `after` = `{"videos": N}`.
6. Set `schema_version = "3"`.

A project DB that does not exist yet is created directly at v3 with no
migration path executed.

### 5. Audit log

Every mutating store function calls one helper:

```python
_audit(conn, actor, entity, entity_id, action, before=None, after=None)
```

It is called **inside the same `BEGIN IMMEDIATE` transaction as the change it
describes**, so a change cannot commit without its log entry and a rollback
discards both.

Actions recorded: `create_video`, `relink_path`, `probe_metadata`, `track`,
`untrack`, `mark_opened`, `set_value`, `clear_value`, `save_definition`,
`migrate_v2_v3`.

`before`/`after` hold JSON of the affected fields only — for `set_value`, the
previous and new `option_id`; for `save_definition`, segment and option counts
rather than the whole definition, so the log stays readable.

**Why not SQLite triggers.** Triggers would guarantee capture even for writes
from outside the app, which is genuinely attractive. They are rejected because
a trigger cannot see the Flask session uid, so every row would lose its actor —
which is most of the value here. Completeness is enforced instead by a test
that enumerates the public mutating functions and asserts each one writes an
audit row.

**Two honest limits.** `actor` is a Flask session uid (`uuid4().hex` per
browser), so it distinguishes sessions, not people. And the log is unbounded;
at roughly one row per user action this is negligible for SQLite, and no
pruning is added.

### 6. API

The HTTP surface stays path-friendly so existing clients keep working, and
gains `video_id` so future ones can be immune to path drift.

| Route | Change |
| --- | --- |
| `GET /dlc/project/tracked-files` | each file gains `video_id` |
| `POST /dlc/project/tracked-files` | `{path}` unchanged; probes and creates/reuses the `video` row |
| `DELETE /dlc/project/tracked-files` | accepts `{video_id}` (preferred) or `{path}` |
| `POST /dlc/project/tracked-files/opened` | accepts either; backfills metrics when absent |
| `PUT /dlc/project/progress-bar/value` | accepts `{video_id}` (preferred) or `{path}` |

Where both are supplied, `video_id` wins. A `path` that matches no `video` row
resolves by creating one, exactly as tracking does.

The client is updated to send `video_id` from the listing, so a rename that
happens mid-session cannot misdirect a write.

## Error handling

| Case | Behaviour |
| --- | --- |
| Probe fails (missing/unreadable file) | Track still succeeds; metrics stay NULL; retried on next successful open |
| Two paths, same fingerprint | Both keep distinct `video_id`s. Expected for copies; no merge, no warning |
| Path already in `video` | Reuse that `video_id`; never create a second row for one location |
| `video_id` not found on a write | `400`, nothing written |
| Migration fails mid-way | Whole transaction rolls back; DB stays at v2 and the route returns `500` |
| Audit insert fails | The enclosing transaction rolls back, so the data change is discarded too |

## Testing

1. `test_tracked_db_migration.py` — build a **v2** DB with the current schema,
   populate tracked rows and progress values, open it with the new code, and
   assert: every path became one `video` row; tracked flags and progress values
   survive with identical content; `schema_version` is `"3"`; a second connect
   changes nothing; a migration audit row exists.
2. `test_tracked_db_identity.py` — `video_id` is stable across a path change;
   `UPDATE path` carries tracked state and progress values with it; two paths
   with equal size and frame count get equal fingerprints but distinct ids;
   fingerprint is NULL until metrics are supplied.
3. `test_audit_log.py` — each public mutating function writes **at least one**
   audit row carrying the expected action, actor and before/after. "At least"
   because a single call can legitimately log twice: tracking a path never seen
   before logs `create_video` and then `track`. Also: a failed write leaves
   neither the change nor the log row; and a completeness test enumerates the
   store modules' public mutating functions so a new one cannot be added
   without an audit row.
4. Route tests extended — listing carries `video_id`; writes accept `video_id`;
   a write with an unknown `video_id` is `400`; tracking an unopenable path
   still succeeds with NULL metrics.

Baselines before attributing failures: **16** in the main webapp
(`test_dlc_celery_tasks.py`), **8** in dlc-3D.

## Deployment

`src/dlc/` is a directory mount, so new modules appear without a rebuild. The
flask container must be **recreated**, not restarted — `src/app.py` is a
single-file bind mount and Docker binds the inode, so an edited `app.py` never
reaches a merely-restarted container:

```
docker compose up -d --force-recreate flask
docker compose up -d dlc-3d
```

The migration runs on the first connect to each project DB, i.e. the first time
the card is opened for that project after deploy.

# Tracked Files — design

Date: 2026-07-31
Status: approved, ready for planning

## Problem

To open a stereo session in the 3D Inline Analysis card you must go to **Browse
Folders** and navigate, every time, to the directory holding the video, its
companion CSV, the kinematic `.h5` files and `calibration.toml`. The path is
deep and the navigation is repeated many times a day against the same handful of
recordings.

## Goal

Let the user mark a video as **tracked**. Tracked videos are listed in a new
third tab in the card; clicking a row is exactly equivalent to clicking that
video in its original folder — same open path, so the companion CSV, sibling
camera, kinematic layers and calibration all resolve as they do today.

The tracked list is persisted per DLC project in SQLite.

## Scope

In scope: the persistence layer, its HTTP API, and the 3D Inline Analysis card
as the first consumer.

Out of scope, deliberately:

- The `file-management/` module directory (currently empty). A full file
  management module is planned separately; this design is the store it will
  build on, not that module.
- A bulk "verify tracked paths still exist" sweep. That belongs to the future
  module and needs no schema change to add.
- Other cards (2D Inline Analysis, View Analyzed). The API is project-scoped and
  card-agnostic, so they can adopt it later without a migration.

## Decisions taken

| Question | Decision |
| --- | --- |
| Where the store lives | Main webapp (`deeplabcut-webapp-docker`), new table, no new container |
| Persistence scope | Per DLC project |
| Where the checkbox appears | Player header (in front of the open file's name) **and** on each row of the Tracked tab |
| What a track stores | One row per opened video path; the sibling camera is resolved on open as today |
| What is trackable | Browse-Folders videos only |
| Row content | Filename, parent folder, last-opened time; most recently opened first |
| Missing files | Not detected at list time. The open attempt fails loudly and asks the user to fix it manually |

## Architecture

Three layers, each independently testable:

```
dlc/tracked_files.py          pure SQLite, no Flask/DLC/Redis      <project>/tracked_files.sqlite
        ▲
dlc/tracked_files_routes.py   Flask blueprint, project resolution  /dlc/project/tracked-files
        ▲
static/tracked_files_tab.js   DOM + fetch, in dlc-3D               #ia3d-tab-tracked
```

`inline_analysis_3d.js` (3763 lines) gains only wiring — the feature does not
live inside it.

### 1. Store — `deeplabcut-webapp-docker/src/dlc/tracked_files.py`

New module, mirroring the established `marks_store.py` pattern: per-call
connection, `PRAGMA journal_mode=WAL`, `_ensure_schema` on connect, writes
wrapped in `BEGIN IMMEDIATE`, and no Flask / DLC / Redis imports so it is
unit-testable against `tmp_path`.

DB file `<project>/tracked_files.sqlite`, created on first write.

```
Schema (v1):
  tracked(video_path     TEXT PRIMARY KEY,   -- absolute path, the identity
          tracked_at     TEXT NOT NULL,      -- "%Y-%m-%dT%H:%M:%SZ" UTC
          last_opened_at TEXT)               -- same format, NULL until first open
  meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)   -- schema_version = "1"
```

Timestamps use `time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())`, the same
helper shape `marks_store.py:70` uses, so the two stores stay comparable.

Public functions:

- `list_tracked(project_path)` — returns a list of dicts. SQLite has no
  `NULLS LAST`, so the ordering is written explicitly as
  `ORDER BY (last_opened_at IS NULL), last_opened_at DESC, tracked_at DESC`:
  most recently opened first, never-opened rows last, ties broken by newest
  tracked. Returns `[]` for a project with no DB file.
- `track(project_path, video_path)` — idempotent insert. Re-tracking an existing
  path does **not** reset `tracked_at` and does **not** clear `last_opened_at`.
- `untrack(project_path, video_path)` — delete; no-op when absent.
- `touch_opened(project_path, video_path)` — set `last_opened_at` to now **only
  if the row already exists**. Opening an untracked video never creates a row.

Two deliberate constraints:

- `video_path` is the primary key and is stored **verbatim** as the browse tab
  produced it (already absolute, already normalised by the server's
  `dir + "/" + name` join). No realpath or symlink resolution — resolving would
  make the stored path stop matching what the UI displays in its breadcrumb.
- The store **never touches the filesystem**. Anything needing a `stat` belongs
  to a caller, which keeps this module testable with no fixture videos.

### 2. API — `deeplabcut-webapp-docker/src/dlc/tracked_files_routes.py`

New blueprint, registered in `app.py` alongside `_dlc_posture_bp`. Routes go
here rather than into `inline_analysis.py` (already 1033 lines).

Project resolution follows `posture_routes.py`'s `_project_path_checked()`:
read the active project from Redis, confirm the directory exists, run
`_dlc_project_security_check`. All four routes return `{"error": …}, 400` when
there is no active project.

| Route | Body / params | Returns |
| --- | --- | --- |
| `GET /dlc/project/tracked-files` | — | `{"files": [{path, name, dir, tracked_at, last_opened_at}, …]}` |
| `POST /dlc/project/tracked-files` | `{path}` | `{"ok": true, "tracked": true}` |
| `DELETE /dlc/project/tracked-files` | `{path}` | `{"ok": true, "tracked": false}` |
| `POST /dlc/project/tracked-files/opened` | `{path}` | `{"ok": true}` |

- `name` and `dir` are derived server-side (`Path.name`, `Path.parent`) so the
  client does no path arithmetic.
- `GET` is a pure DB read. **No `stat` per row**, no `exists` field. Rows render
  identically whether or not the file is still on disk.
- Write validation: the path must be absolute and its lowercased suffix must be
  in `{.mp4, .avi, .mov, .mkv, .mpg, .mpeg}` — the same set as
  `_IA_VIDEO_EXTS` (`inline_analysis_3d.js:91`), so the server never rejects
  something the browse list offered. Otherwise `400`. No root sandbox is added — `/fs/ls` and
  `/annotate/video-info` already accept any absolute server path, and
  restricting only this route would let the user browse to a video they then
  could not track. This matches the existing posture rather than silently
  diverging from it.
- There is no per-video "is this tracked?" probe. The card fetches the list once
  and answers from an in-memory `Set`.

### 3. Client — `dlc-3D/src/static/`

`src/static` is bind-mounted as a whole directory and
`card_inline_analysis_3d.html` is already mounted individually, so no
`docker-compose.yml` change is needed.

**`static/internal/relative_time.mjs`** — pure, no DOM.
`formatRelative(iso, nowMs)` → `"never opened"` / `"just now"` / `"2 h ago"` /
`"3 d ago"`. `nowMs` is a parameter, so it is directly unit-testable. Sits with
the other `internal/*.mjs` pure helpers.

**`static/tracked_files_tab.js`** — a factory in the style of
`makeKeyframeWindow` / `makeFileBrowser`:

```js
makeTrackedFiles({ tabBtn, panelEl, listEl, headerCheckbox, onOpen, onError })
  → { refresh(), setCurrent(pathOrNull), destroy() }
```

It owns the list fetch, the in-memory `Set` of tracked paths, row rendering and
every checkbox handler.

`inline_analysis_3d.js` changes are wiring only:

- construct `makeTrackedFiles` in `_wireLauncher`, passing `_iaOpenBrowseVideo`
  as `onOpen`;
- `setCurrent(absPath)` at the end of a successful `_iaOpenBrowseVideo`;
- `setCurrent(null)` in `_resetForOpen`;
- abort the open when video-info reports an error (see Error handling).

### DOM changes — `templates/partials/card_inline_analysis_3d.html`

1. Third tab button `#ia3d-tab-tracked` ("Tracked Files") after **Browse
   Folders** (line 14), plus `#ia3d-tab-tracked-panel` containing
   `#ia3d-tracked-list`, styled like the existing browse panel.
   Tab switching becomes a small array-driven helper instead of the two
   hand-written handlers in `_wireLauncher` — three hand-written copies of that
   block is where it starts to rot.
2. `#ia3d-track-checkbox` inserted before `#ia3d-selected-name` in the player
   header (line 93), wrapped in a `<label title="Track this file">`, `hidden`
   by default.

### Behaviour

- The header checkbox is visible **only** when `_iaMode === "browse-video"`.
  Project-content videos and labeled frame folders are not trackable.
- Row layout: checkbox (always checked) · filename · dimmed parent directory ·
  dimmed right-aligned last-opened text.
- The whole row is clickable to open, except the checkbox, which
  `stopPropagation`s so unticking never also opens the video.
- Unticking a row removes it optimistically and re-renders on the `DELETE`
  response.
- Empty state: *"No tracked files. Open a video from Browse Folders and tick the
  box next to its name."*
- The tab refreshes on tab click and after any track/untrack. No polling.

## Data flow

**Tracking** — user opens a video from Browse Folders → header checkbox appears
unchecked → user ticks it → `POST /dlc/project/tracked-files {path}` → row
inserted → in-memory set updated → tracked list re-rendered.

**Opening a tracked file** — user clicks a row → `onOpen(path, name)` calls
`_iaOpenBrowseVideo(path, name)`, the identical function the Browse tab uses →
`/annotate/video-info` resolves fps and frame count → the viewer loads and the
existing downstream logic resolves the sibling camera, companion CSV, kinematic
layers and `calibration.toml` → on success, `POST
/dlc/project/tracked-files/opened {path}` moves the row to the top of the list.

## Error handling

| Case | Behaviour |
| --- | --- |
| No active DLC project | All four routes `400`. Tab renders *"Activate a DLC project in the main webapp to track files."*; header checkbox stays hidden. |
| Tracked file gone at open | Open **aborts** — the player section never appears — and the message names the path and says to fix or untrack it. `last_opened_at` is untouched. |
| Track/untrack request fails | The checkbox **reverts** to its previous state and the error is shown. No optimistic state is left standing on failure. |
| Re-tracking an already-tracked path | Idempotent `200`; `tracked_at` and `last_opened_at` preserved. |
| Untracking an absent row | No-op `200`. |
| Relative path or non-video extension on write | `400`, nothing stored. |
| Project directory read-only / DB unwritable | `sqlite3.OperationalError` → `500`, message surfaced in the tab. Reads against a project with no DB return `[]`, never an error. |

`/annotate/video-info` already returns `{"error": "File not found."}, 404`
(`routes/annotate.py:42`). Today `_iaOpenBrowseVideo` swallows that in a bare
`catch` and falls back to `fps 30 / frameCount 0`, so a dead path silently opens
an empty viewer. Honouring that error is therefore a real bug fix for the
existing Browse tab as well as the precondition for the tracked-files error
path.

## Testing

Four suites, each following a pattern already present in these repos.

1. **`deeplabcut-webapp-docker/src/tests/test_tracked_files_store.py`** — pure
   store against `tmp_path`, mirroring `test_marks_store.py`: fresh project
   returns `[]`; track → list; re-track preserves `tracked_at`; untrack;
   `touch_opened` on an untracked path creates nothing; ordering is
   `last_opened_at DESC` with never-opened rows last, tie-broken by
   `tracked_at DESC`.
2. **`deeplabcut-webapp-docker/src/tests/test_tracked_files_routes.py`** —
   blueprint tests using the `_activate_project(client, fake_redis,
   project_path)` helper from `test_test_set_picker_routes.py`: `400` with no
   active project; POST → GET round-trip returning derived `name`/`dir`;
   DELETE; rejection of relative and non-video paths; `opened` touching only an
   existing row.
3. **`dlc-3D/tests/unit/test_relative_time.mjs`** — `node --test`, alongside the
   existing `.mjs` unit tests.
4. **`dlc-3D/tests/test_tracked_files_markup.py`** and
   **`test_tracked_files_wiring.py`** — the static source-guard pattern this
   card already uses (`test_inline_3d_lock_wiring.py` et al.): the third tab
   button, panel and list container exist; the checkbox precedes
   `#ia3d-selected-name`; `inline_analysis_3d.js` constructs `makeTrackedFiles`
   and calls `setCurrent` in both `_iaOpenBrowseVideo` and `_resetForOpen`; and
   a regression guard that `_iaOpenBrowseVideo` aborts on a video-info error
   instead of falling back to `fps 30 / frameCount 0`.

Known-failure baselines to check before attributing a failure to this work:
**8** in dlc-3D, **2 + 14** in the main webapp. Run pytest only with the
existing `pytest.ini` disk-fill guards in place.

## Files touched

New:

- `deeplabcut-webapp-docker/src/dlc/tracked_files.py`
- `deeplabcut-webapp-docker/src/dlc/tracked_files_routes.py`
- `deeplabcut-webapp-docker/src/tests/test_tracked_files_store.py`
- `deeplabcut-webapp-docker/src/tests/test_tracked_files_routes.py`
- `deeplabcut-webapp-docker-supports/dlc-3D/src/static/tracked_files_tab.js`
- `deeplabcut-webapp-docker-supports/dlc-3D/src/static/internal/relative_time.mjs`
- `deeplabcut-webapp-docker-supports/dlc-3D/tests/unit/test_relative_time.mjs`
- `deeplabcut-webapp-docker-supports/dlc-3D/tests/test_tracked_files_markup.py`
- `deeplabcut-webapp-docker-supports/dlc-3D/tests/test_tracked_files_wiring.py`

Modified:

- `deeplabcut-webapp-docker/src/app.py` — register the blueprint
- `deeplabcut-webapp-docker-supports/dlc-3D/src/static/inline_analysis_3d.js` —
  wiring plus the video-info error fix
- `deeplabcut-webapp-docker-supports/dlc-3D/src/templates/partials/card_inline_analysis_3d.html`
  — third tab and header checkbox

No `docker-compose.yml` change. The main webapp needs a `flask` service restart
to pick up the new blueprint; dlc-3D static assets are live-reloaded.

# Progress Arrow Bar — design

Date: 2026-08-01
Status: approved, ready for planning

Builds on [2026-07-31-tracked-files-design.md](2026-07-31-tracked-files-design.md).

## Problem

Tracked files are a flat list. There is no way to record where each recording
sits in the lab's workflow — labelled? trained? analysed? QC'd? — so progress
lives in people's heads and in filenames.

## Goal

A per-project **progress arrow bar**: an ordered row of chevron segments, each
segment offering a fixed set of options, each option carrying a user-chosen
colour. Every tracked file gets its own value per segment. The bar renders next
to the filename anywhere a track/untrack row is shown, and each segment is
editable in place by clicking it and picking from a dropdown.

A new card, reachable from a button under **Annotate Video** on both the 2D and
3D pages, is where the bar is defined and where all tracked files are managed.

## Scope

In scope: the definition + values store, its API, a reusable client component,
the new management card, and the 2D Tracked Files tab (so both inline-analysis
cards match).

Out of scope: the `file-management/` module directory, which stays empty; a
bulk "verify tracked paths still exist" sweep; any per-user or cross-project
progress view.

## Decisions taken

| Question | Decision |
| --- | --- |
| Bars per project | Exactly one |
| Colour lives on | Each option, so the bar reads as progress at a glance |
| Segment count | 0–10, enforced in the store, not just the UI |
| Identity | Segments **and** options carry stable server-generated IDs; renaming or recolouring never disturbs stored values |
| Deleting a segment/option | No cascade — referencing values stay in the DB and render blank |
| Colour uniqueness | No constraint; `#rrggbb` format still validated |
| Where the bar renders | The new panel, and — via a shared component — anywhere a track/untrack row appears |
| 2D Tracked Files tab | Yes, added by this work |

## Architecture

Shared client code is promoted into the main webapp so all three consumers use
one implementation:

```
deeplabcut-webapp-docker/src/
  dlc/progress_bar.py            pure SQLite (new tables in tracked_files.sqlite)
  dlc/progress_bar_routes.py     blueprint: definition + single-value writes
  static/js/components/
    hex_color.mjs                pure #rrggbb guard
    relative_time.mjs            MOVED from dlc-3D
    tracked_files_tab.js         MOVED from dlc-3D
    progress_bar.js              NEW — renders + edits one file's bar
  static/js/tracked_files_panel.js   the new card's controller
  templates/partials/card_tracked_files.html
```

dlc-3D imports these by absolute URL (`/static/js/components/…`), exactly as
`inline_analysis_3d.js` already imports `/static/js/state.js`.

**Note on the move.** Standing guidance in this project is "don't refactor
working code — copy into a new shared module and defer migrating the working
consumer". This design deliberately *moves* rather than copies, because there is
exactly one consumer, the migration is one import line, the code is a day old,
and duplicating a renderer of user-chosen colours and dropdown state guarantees
silent divergence between the 2D and 3D bars.

### 1. Store — `dlc/progress_bar.py`

Pure SQLite, same conventions as `tracked_files.py` (per-call connection, WAL,
`_ensure_schema`, `BEGIN IMMEDIATE` writes, no Flask/DLC/Redis, no filesystem
access). Writes three new tables into the **existing**
`<project>/tracked_files.sqlite`. `schema_version` in `meta` moves `1` → `2`;
because `_ensure_schema` issues `CREATE TABLE IF NOT EXISTS`, existing project
DBs upgrade on first touch with no migration script.

```
progress_segment(segment_id  TEXT PRIMARY KEY,   -- stable, never reused
                 position    INTEGER NOT NULL,   -- 0..9, display order
                 name        TEXT NOT NULL)

progress_option(option_id    TEXT PRIMARY KEY,   -- stable, never reused
                segment_id   TEXT NOT NULL,
                position     INTEGER NOT NULL,
                label        TEXT NOT NULL,
                color        TEXT NOT NULL)      -- '#rrggbb', validated

progress_value(video_path    TEXT NOT NULL,
               segment_id    TEXT NOT NULL,
               option_id     TEXT NOT NULL,
               set_at        TEXT NOT NULL,
               PRIMARY KEY (video_path, segment_id))
```

Public surface:

- `get_definition(project_path)` → `{"segments": [{segment_id, name, options:
  [{option_id, label, color}]}]}`, ordered by `position`.
- `save_definition(project_path, segments)` — full replace of the definition,
  **diffed by ID** so existing IDs survive. Entries arriving without an ID are
  new and get one (`seg_`/`opt_` + 12 hex chars, from `secrets.token_hex(6)`).
  Segments and options **absent** from the payload are deleted from
  `progress_segment` / `progress_option` — but never from `progress_value`
  (see below). Raises `ValueError` for more than 10 segments or a `color`
  failing `#rrggbb`.
- `get_values(project_path, video_paths)` → `{video_path: {segment_id:
  option_id}}` — batched, so listing N files costs one query, not N.
- `set_value(project_path, video_path, segment_id, option_id)` — `option_id=None`
  clears that segment for that file.

Two consequences of the no-cascade decision, stated so they are not surprises:

- **Orphans are inert.** `get_values` returns whatever is stored; the client
  renders a segment only if its `segment_id` and `option_id` are still in the
  definition. Re-adding a segment under its original ID restores its values —
  but note that IDs are only recoverable before a save (see §4), so this is a
  within-session undo, not a way back after the fact.
- **Values outlive tracking.** `progress_value` is keyed by `video_path` alone,
  with no foreign key to `tracked`. Untracking then re-tracking a file restores
  its progress.

`color` is validated on write because it reaches `style.setProperty()` in the
browser, where an unvalidated value is a CSS-injection vector. That guard is
correctness, not policy — it stands despite there being no uniqueness rule.

### 2. API — `dlc/progress_bar_routes.py`

New blueprint registered in `app.py`, reusing the `_project_path_checked()`
pattern from `tracked_files_routes.py`. All routes return `{"error": …}, 400`
without an active project.

| Route | Body | Returns |
| --- | --- | --- |
| `GET /dlc/project/progress-bar` | — | `{"segments": [...]}` |
| `PUT /dlc/project/progress-bar` | `{segments: [...]}` | `{"ok": true, "segments": [...]}` with server-assigned IDs |
| `PUT /dlc/project/progress-bar/value` | `{path, segment_id, option_id}` | `{"ok": true}`; `option_id: null` clears |

One change to an existing route: `GET /dlc/project/tracked-files` gains a
`progress` object per file (`{segment_id: option_id}`), populated by one batched
`get_values` call. This keeps row rendering to a single fetch instead of an
N+1. It is the only coupling introduced between the two stores, and it is a
read.

### 3. Shared component — `static/js/components/progress_bar.js`

```js
makeProgressBar({ definition, values, onChange, readOnly }) -> HTMLElement
```

Pure DOM, no fetching — the caller supplies the definition and that file's
values and handles persistence in `onChange(segmentId, optionId)`. This is what
makes it droppable next to any filename.

- Renders one chevron per segment, filled with the selected option's colour, or
  an empty outline when unset or orphaned.
- Clicking a segment opens a dropdown listing that segment's options plus
  **Clear**. Choosing one repaints optimistically and calls `onChange`; if the
  caller's promise rejects, the previous value is restored. A segment with no
  options yet opens a dropdown containing only **Clear** and the dimmed text
  "No options defined" — it is never a dead click with no feedback.
- A definition with zero segments renders nothing at all (no empty container,
  no layout shift).
- Every label is written with `textContent`; every colour passes
  `isValidHexColor` before reaching `style`, falling back to the unset outline.
- Keyboard reachable: each segment is a `<button>`, the dropdown closes on
  `Escape` and on outside click.

`tracked_files_tab.js` composes it into each row between the checkbox and the
filename column, passing `f.progress` from the list response.

### 4. The card — `card_tracked_files.html` + `tracked_files_panel.js`

A new button `#btn-open-progress-tracking` goes into
`templates/partials/card_dlc_project.html` immediately after
`#btn-open-annotate-video`. Because `dlc_3d.html` includes that same partial,
**one edit covers both pages**.

The card partial is included by `templates/index.html` and by
`dlc-3D/src/templates/dlc_3d.html`. Its controller
`static/js/tracked_files_panel.js` is imported by `static/js/main.js`, which
`base.html` loads on both pages — so the JS needs no dlc-3D change at all.

The card has two sections:

1. **Bar definition.** When no bar exists (`segments` is empty): a single
   **Add progress bar** button. Clicking it creates one segment named
   `Stage 1` with no options and saves immediately, so the editor below has
   something to show. Once a bar exists: a segment-count number input clamped
   0–10, and per segment a name field plus its option rows (label +
   `<input type="color">` + remove), with **Add option**. Raising the count
   appends segments named `Stage N`; lowering it removes trailing segments from
   the editor. **Save** PUTs the whole definition.

   Undo has a precise boundary, worth stating because it is easy to assume more
   than is true. The editor holds removed segments in memory until you save, so
   lowering the count and raising it again **before saving** restores the same
   IDs and therefore the same values. Once you save, those segments are gone
   from `progress_segment` and their IDs are not recoverable — their
   `progress_value` rows remain in the DB but nothing references them again.
   Saving a reduced count is the one action here that is effectively permanent
   for the dropped segments, even though no row is deleted.
2. **Tracked files.** The same `makeTrackedFiles` list used by both inline cards
   — checkbox, filename, folder, last-opened, and now the bar.

### 5. The 2D Tracked Files tab

`card_inline_analysis.html` gains the third tab, panel, list container and
launcher error line, mirroring the 3D card. `inline_analysis_player.js`
(2518 lines) gains wiring only: construct `makeTrackedFiles`, `setCurrent` on
open and reset, and a track checkbox before `#ia-selected-name`.

It also gets the same open-abort fix already applied to the 3D card:
`_iaOpenBrowseVideo` at `inline_analysis_player.js:383` currently swallows a
video-info error into `_iaFps = 30; _iaFrameCount = 0`, silently opening an
empty viewer. A tracked file whose video has moved hits exactly that path, so
the fix is required by this feature, not incidental cleanup.

## Deployment

The `dlc-3d` service bind-mounts only its **own** partials; main-webapp
templates come from the baked image (`dlc-3d` builds `FROM`
`deeplabcut-webapp-docker-flask`). So the edited `card_dlc_project.html` and the
new `card_tracked_files.html` will **not** appear on the 3D page without action.
Add two bind mounts to the `dlc-3d` service in `docker-compose.yml`, matching
the existing per-file pattern:

```yaml
- ../deeplabcut-webapp-docker/src/templates/partials/card_dlc_project.html:/app/templates/partials/card_dlc_project.html
- ../deeplabcut-webapp-docker/src/templates/partials/card_tracked_files.html:/app/templates/partials/card_tracked_files.html
```

This also means future edits to `card_dlc_project.html` reach the 3D page live,
which they do not today. JS and CSS need no mounts: the browser fetches
`/static/js/…` from the main webapp on port 5000 regardless of which page it is
on. Both `flask` and `dlc-3d` need a restart; neither needs a rebuild.

## Error handling

| Case | Behaviour |
| --- | --- |
| No active DLC project | Routes `400`; the card shows "Activate a DLC project in the main webapp." |
| No bar defined yet | Rows render no bar; the card shows only **Add progress bar**. |
| Segment count > 10 | Rejected client-side by the input's `max`, and by the store with `ValueError` → `400`. |
| Malformed colour | `400`; the client falls back to the unset outline rather than styling with it. |
| Value references a deleted segment/option | Renders unset. No error, no cleanup. |
| Setting a value fails | The chevron reverts to its previous colour and the error surfaces in the card's status line. |
| Tracked file gone at open | Unchanged from the tracked-files spec: the open aborts with a message naming the path — now in the 2D card too. |

## Testing

1. `src/tests/test_progress_bar_store.py` — pure store against `tmp_path`:
   round-trip a definition; IDs survive rename and recolour; new entries get
   fresh IDs; >10 segments raises; bad colour raises; values survive deleting a
   segment; `get_values` batches correctly; `set_value(None)` clears; upgrading
   a v1 `tracked_files.sqlite` in place preserves its `tracked` rows.
2. `src/tests/test_progress_bar_routes.py` — blueprint tests via the
   `flask_test_client` + `_activate_project` pattern: 400 without a project,
   definition round-trip, value set/clear, 400 on >10 segments and bad colour,
   and `GET /dlc/project/tracked-files` carrying `progress`.
3. `src/tests/unit/*.mjs` — a **new** node-test directory in the main webapp
   (none exists today), holding the moved `test_relative_time.mjs` and a new
   `test_hex_color.mjs`. Node here is v16, whose `--test` finds nothing in
   directory mode, so the documented command runs each file directly.
4. `src/tests/test_progress_bar_component_source.py` and
   `test_tracked_files_panel_markup.py` — the static source-guard pattern:
   `textContent`-only rendering, `isValidHexColor` before any `style` write,
   zero-segment renders nothing, the new button sits after
   `#btn-open-annotate-video`, the card is included by both page templates.
5. `dlc-3D/tests/` — update the existing tracked-files guards to the new import
   URL, and delete the two moved files' tests from that repo.

Baselines to check before blaming this work: **8** known failures in dlc-3D,
**16** in the main webapp (all `test_dlc_celery_tasks.py`, `KeyError:
'n_machine'`). Run pytest only from a repo root, and pass `--ignore=tests/e2e`
in dlc-3D.

## Suggested cut point

If this needs to ship in stages, sections 1–4 (store, API, component, card) form
a complete, useful feature on their own. Section 5 (the 2D tab) is independent
of the bar and can follow.

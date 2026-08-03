# Tracked-list Sorting & Header Progress Bar — design

Date: 2026-08-03
Status: approved, ready for planning

Builds on [2026-08-01-progress-arrow-bar-design.md](2026-08-01-progress-arrow-bar-design.md).

## Problem

The tracked list has one fixed order — most recently opened first — so finding a
session by name, or reading sessions in the order they were recorded, means
scanning the whole list by eye.

Separately, the progress bar is only reachable from a list row. While a video is
open in the player there is no way to see or change its progress without going
back to the list.

## Goals

1. Sort the tracked list by name, recording date, or last opened, in either
   direction, with the choice remembered per project.
2. Render the same editable progress bar beside the filename in both
   inline-analysis player headers.

## Scope

In scope: the shared `tracked_files_tab.js` component, one new pure module, the
three list-header templates, the two player-header templates, and one new
`ui-setting` whitelist key.

Out of scope: server-side sorting (the listing already returns every row in one
response), sorting the Project Content or Browse Folders lists, and any change
to how progress values are stored.

## Decisions taken

| Question | Decision |
| --- | --- |
| "Date" means | Recording timestamp parsed from the filename |
| Header bar when untracked | Hidden entirely |
| Where the sort buttons appear | All three lists — both tabs and the management card |
| Persistence | Per project, via the existing `ui-setting` mechanism |

## 1. Sorting

Client-side, over rows already fetched. The server's ordering is unchanged and
remains the initial state.

New pure module `static/js/components/tracked_sort.mjs`, DOM-free and
directly unit-testable:

```js
parseRecordedAt(name) -> epochMs | null
sortTrackedFiles(rows, field, direction) -> newly sorted array
```

`field` is `"name" | "recorded" | "opened"`; `direction` is `"asc" | "desc"`.
`sortTrackedFiles` returns a new array and never mutates its input.

**Timestamp parsing.** `/_(\d{8})_(\d{6})(?=_|\.|$)/` against the filename:

```
khoai-lang-2_cam0_20260507_105538_1_trig1_fps200_exposure1500_gain10.avi
                  └──────┬──────┘
                  2026-05-07 10:55:38
```

Parsed with `Date.UTC` so daylight-saving transitions cannot reorder a list.
The 8-then-6 digit shape cannot be matched by `fps200`, `exposure1500` or
`gain10`. A name with no match yields `null`.

**Missing values sort last in BOTH directions.** A never-opened file
(`last_opened_at === null`) and a file whose name carries no timestamp always
sink to the bottom, ascending or descending. This generalises the existing
"never-opened last" rule; flipping direction to surface the rows that have no
value would be actively unhelpful.

**Tie-break** is filename, case-insensitive, so equal keys produce a stable and
predictable order rather than depending on the server's row order.

## 2. Buttons

The component renders three buttons — `Name`, `Recorded`, `Opened` — into a
`<span id="…-sort">` mount in each header. Rendering them from the component
rather than the templates keeps each template to one line and makes it
impossible for the three lists to drift apart.

- Clicking the **active** field flips its direction.
- Clicking a **different** field switches to it at its natural default:
  `Name → asc`, `Recorded → desc`, `Opened → desc`. Newest-first is the useful
  default for both dates; alphabetical is the useful default for a name.
- The active button shows ▲ or ▼; the others show none.

The tab panels' header is narrow, so labels stay compact and the row is allowed
to wrap rather than shrinking the buttons below a comfortable click target.

## 3. Persistence

`GET`/`POST /dlc/project/ui-setting` with a new key **`tracked_sort`**, whose
value is `"<field>:<direction>"`, e.g. `"recorded:desc"`. The key must be added
to `_UI_SETTING_KEYS` in `dlc/inline_analysis.py:466`.

This is load-bearing: on 2026-07-31 eight reprojection keys were missing from
that whitelist, so every save silently returned `400 unknown key` and nothing
persisted. `dlc-3D/tests/test_reproj_ui_setting_whitelist.py` was written to
guard exactly that. This design adds the equivalent guard for
`tracked_files_tab.js` in the main webapp.

Reading it adds a **third parallel fetch** to the `Promise.all` in `refresh()`,
which today already issues two (the listing and the definition). It is
concurrent with those, so it adds no serial latency — worth stating explicitly
given that per-request database cost on the NAS mount is already under scrutiny.
Like the definition fetch, a failure degrades rather than propagates: a
malformed, unknown, or unreachable value falls back to the default order.

## 4. Header progress bar

`makeTrackedFiles` gains one option, `headerBarMount` — an element.

On `setCurrent(path)`:

- If `path` resolves to a **tracked** row, render `makeProgressBar` into the
  mount with that row's `progress`, wired to the same `onChange` the list rows
  use, so an edit made in the header persists identically and updates the
  in-memory row.
- Otherwise clear the mount. An untracked video has no identity to attach
  values to, so there is nothing to show — the same reasoning that already
  hides the track checkbox.

Ticking or unticking the track checkbox re-runs this, so the bar appears and
disappears with the checkbox.

Markup: one `<span id="ia3d-track-bar">` / `<span id="ia-track-bar">` placed
**after** the filename span, preserving the checkbox → name → bar order used in
list rows.

## Error handling

| Case | Behaviour |
| --- | --- |
| Filename has no parseable timestamp | Sorts last under "Recorded"; no error, no warning |
| Stored `tracked_sort` is malformed or unknown | Falls back to the default order |
| Saving the sort preference fails | Order still changes on screen; the failure is silent, since a lost preference is not worth interrupting the user |
| No bar defined for the project | `makeProgressBar` already renders nothing for zero segments, so the header mount stays empty |
| Header bar edit fails | The chevron reverts, exactly as in list rows |

## Testing

1. `src/tests/unit/test_tracked_sort.mjs` — `parseRecordedAt` on a real
   filename, on one with no timestamp, and on near-misses (`fps200`,
   `exposure1500`); `sortTrackedFiles` for each field in both directions;
   missing values last in both directions; input array not mutated; ties broken
   by filename.
2. `src/tests/test_tracked_files_tab_source.py` — the component renders three
   sort buttons, persists via `ui-setting`, and clears the header mount when the
   current path is not tracked.
3. `src/tests/test_tracked_sort_ui_setting_whitelist.py` — every `ui-setting`
   key `tracked_files_tab.js` sends is present in `_UI_SETTING_KEYS`, extracted
   from both sources rather than hand-copied.
4. Markup tests — the three `…-sort` mounts exist in their headers, and each
   player header has its `…-track-bar` mount positioned after the filename.

Baselines: **16** known failures in the main webapp, **8** in dlc-3D.

## Deployment

Templates and JS are directory-mounted, so both live-reload. `inline_analysis.py`
lives under the directory-mounted `src/dlc`, so it needs only a flask restart —
not a recreate, since no single-file mount is involved. `dlc-3d` needs a restart
to re-read its own edited partial.

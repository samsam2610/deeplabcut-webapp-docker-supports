# Reorderable Panels, SAM Panel Toggle, and Per-Camera Box Controls — Design

**Date:** 2026-08-14
**Status:** approved, ready for planning

## Goal

Three independent changes to the 3D inline-analysis cards, smallest first:

1. **Per-camera clear box.** Each camera card gets its own `clear box` control
   next to its `show box` checkbox; the `re-place [cam▾] [Clear box]` row is
   deleted.
2. **Re-aim, left-aligned and explained.** The `Re-aim box from clicks + rerun`
   button moves to the left of its row and gains a note that says what it
   rebuilds — including the cost it currently hides.
3. **Reorderable panels.** The stack of checkbox-gated panels
   (Triangulate · Anipose Parameters · 3D View · Dataset Curation · Create
   Clip · SAM 3 + DINOv3) can be reordered by dragging a panel's header row,
   and the order is saved per project. To take part, the SAM panel gains a
   checkbox toggle like its five neighbours, unchecked by default.

Parts 1 and 2 touch only the SAM card. Part 3 touches all three cards.

## Verified facts

Checked in the working tree, not assumed.

1. **Three near-clone cards**, distinguished only by an id prefix:

   | card | markup | JS | prefix |
   |---|---|---|---|
   | Inline Analysis 3D | `templates/partials/card_inline_analysis_3d.html` | `static/inline_analysis_3d.js` | `ia3d-` |
   | …Reprojection | `static/card_inline_analysis_3d_reprojection.html` | `static/inline_analysis_3d_reprojection.js` | `ia3dr-` |
   | …SAM Model | `static/card_inline_analysis_3d_sam.html` | `static/inline_analysis_3d_sam.js` | `ia3ds-` |

   All three JS files are ES modules (`templates/dlc_3d.html:58-60`), so a
   shared `internal/*.mjs` import works in every one.

2. **The panels are already siblings**, in a contiguous run at the end of each
   card's `<prefix>player-section`:

   | card | container | panels |
   |---|---|---|
   | `ia3d-` | `player-section` (108–961) | 522, 557, 676, 841, 931 — the last five children |
   | `ia3dr-` | `player-section` (91–1049) | 504, 539, 658, 823, 913, then `ia3dr-reproj-panel` (944) |
   | `ia3ds-` | `player-section` (108–961) | 522, 557, 676, 841, 931 — the last five children |

   Reordering is therefore a sibling-shuffle, not a layout rewrite.

3. **The SAM panel is not one of them.** `ia3ds-sam-panel`
   (`card_inline_analysis_3d_sam.html:967`) is a sibling *of*
   `ia3ds-player-section`, which closes at line 961. It is also the only one of
   the six with no checkbox gate, and nothing ever hides it — no code
   references it except at injection.

4. **The Re-aim button sits right because of one CSS rule.**
   `.ia3ds-sam-status { margin-left: auto }`
   (`inline_analysis_3d_sam.css:329-332`) pushes everything after the status
   span to the right edge. The button follows the span in the markup
   (`card_inline_analysis_3d_sam.html:1016-1019`).

5. **Re-aim invalidates every cached sweep in the project.** This is currently
   invisible in the UI and is the reason part 2 is worth doing:

   - `store.model_signature` includes `len(cam.exemplars)` per camera
     (`sam-training/src/store.py:63-65`);
   - `api_pellet_retrain` sets `cam.exemplars = []` and re-cuts one patch per
     click (`sam-training/src/api_sam.py:1064-1079`), so the count tracks the
     number of clicks;
   - `sweep_cache.signature` is `model_signature` plus the calibration name
     (`sam-training/src/sweep_cache.py:38-46`), and that string is the cache
     key.

   So adding or deleting a click changes the key **for every video in the
   project**, not just the clicked pair. Pressing Re-aim again without changing
   the clicks yields the same count and costs nothing.

6. **The toggle pattern to copy**: a checkbox followed by a
   `<div id="…-controls" class="hidden">`, toggled on `change`
   (`inline_analysis_3d_sam.js:1427-1432`). None of the five persists its
   checked state — every page load starts collapsed.

7. **dlc-3D can host a project-scoped store.** `_active_project_for_user()`
   (`src/dlc_3d_bp/routes.py:81-121`) resolves the active project per user from
   Redis and returns `None` on every failure. No `Thread(` exists anywhere in
   `src/dlc_3d_bp/*.py`, so restarting the `dlc-3d` container kills no work —
   LP jobs run in `dlc-3d-worker`, triangulate/analyze on the main `worker`.

## Part 1 — per-camera clear box

`_pelletRenderCams` (`inline_analysis_3d_sam.js:4737-4771`) builds one card per
camera. Its `<h4>` gains a clear-box control beside the existing `show box`
checkbox:

```
[thumb]  cam0   ☐ show box   ⟲ clear box            12 samples
```

The button carries `data-clearcam="${name}"` and reuses the handler currently
bound to `ia3ds-pellet-replace` (`inline_analysis_3d_sam.js:5108`), with the
camera read from the dataset instead of from a dropdown.

**Deleted:** the whole `re-place` row (`card_inline_analysis_3d_sam.html:1006-1014`),
including `ia3ds-pellet-replace` and `ia3ds-pellet-replace-cam`.
`ia3ds-bind-status` lives in that row and is kept — it moves to its own line
under the camera grid rather than joining the Re-aim row, where it would be a
second right-aligned status competing with `ia3ds-pellet-status`.

**Testability.** The header is built by string concatenation inside a 5000-line
non-exported function, which is why it has no test today. Extract it as a pure
`camCardHead(name, cam, visible)` in `static/internal/pellet_box.mjs` (where the
rest of this card's pure logic already lives) and unit-test it: the clear button
carries the camera's own name, and the show-box checkbox reflects the passed
visibility.

`tests/unit/test_sam_panel_ids.mjs:85` pins both deleted ids and must be
updated in the same commit.

## Part 2 — Re-aim left-aligned and explained

Swap the two children of the row at `card_inline_analysis_3d_sam.html:1016-1019`
so the button precedes the status span. `margin-left: auto` on the span then
does the rest: button hard left, status hanging right. No CSS change.

Below the row, a `<p class="ia3ds-sam-note">` (the class already exists, used at
line 991):

> **Re-aim** rebuilds each camera's template pool from the DLC seed plus every
> pellet click on this pair, recentres that camera's search box on the median
> click, re-derives the fallback 3D reference from frames clicked in **both**
> cameras, saves all of it to the project model, then reruns this pair.
> Deleting a click removes its influence — the pool is re-cut from scratch every
> time. **Adding or removing a click invalidates cached sweeps for every video
> in the project**, because the pool is part of the sweep's cache key. Pressing
> it again without changing the clicks costs nothing.

Wording is normative: it is the only place the user can learn fact 5.

## Part 3 — reorderable panels

### 3.1 The SAM panel becomes the sixth uniform panel

Restructure `ia3ds-sam-panel` to match its neighbours:

```html
<div id="ia3ds-sam-panel" style="…same as the other five…">
  <div style="display:flex;align-items:center;gap:.6rem;flex-wrap:wrap">
    <label …>
      <input type="checkbox" id="ia3ds-sam-toggle" …/>
      SAM 3 + DINOv3
    </label>
  </div>
  <div id="ia3ds-sam-controls" class="hidden" style="margin-top:.5rem">
    …the entire existing body, unchanged…
  </div>
</div>
```

and **move the element inside `ia3ds-player-section`** as its last child.

Every id, listener, canvas and `<details>` inside is untouched — the body is
wrapped, not rewritten.

Two visible consequences, both intended:

- The panel starts collapsed on every page load, like the other five. Checked
  state is not persisted (fact 6).
- It hides when no video is open, where today it stays on screen with stale
  contents. That is the same failure the video-switch reset fixed in `eca8164`.

Wiring follows fact 6's pattern exactly. The existing `_samWirePanel`,
`_samWatchVideo` and `_samResetPanel` continue to run regardless of the
checkbox — visibility must not gate data flow, or switching video while
collapsed would leave the panel stale when expanded.

### 3.2 What is movable

Per card, an explicit id list — never "all children", because
`player-section` also holds the viewer split, the metadata strip and the
overlay panel.

| card | movable ids (in default order) |
|---|---|
| `ia3d-` | `triangulate-panel`, `params-panel`, `pose3d-panel`, `curation-panel`, `clip-panel-wrap` |
| `ia3dr-` | same five with the `ia3dr-` prefix |
| `ia3ds-` | those five plus `ia3ds-sam-panel` |

`ia3dr-reproj-panel` is **out of scope**: it is not checkbox-gated, and gating
it to make it uniform is a behaviour change nobody asked for. It stays the last
child of its container, below the movable block.

Panels reorder only among the DOM positions the movable set already occupies,
so nothing can be dragged above the viewer.

### 3.3 Drag mechanics

No new chrome. The panel's header row is the drag source, styled
`cursor: grab` (shared rule in `inline_analysis_3d.css`, which is the only one
of the three stylesheets loaded page-wide — `templates/dlc_3d.html:8`).

`draggable` is set on `mousedown` and cleared on `dragend`, and is **not** set
when the mousedown target is an `<input>` — so ticking a checkbox never starts
a drag. HTML5 drag-and-drop is used rather than pointer maths: it is ~30 lines,
and the browser draws the drag image.

On `dragover`, the hovered panel gets a 2px accent border on the edge the drop
would land against. On `drop`, the moved element is re-inserted with
`insertBefore` — **moved, never rebuilt**, which is the entire safety argument:
every element identity, event listener and canvas context inside survives.

### 3.4 Ordering logic — `static/internal/panel_order.mjs`

Pure, no DOM:

```js
export function applyOrder(domIds, savedOrder)      // -> ids in render order
export function reorder(ids, movedId, beforeId)     // beforeId null = to the end
export function sameOrder(a, b)                     // skip a pointless PUT
```

`applyOrder` rules, in priority order:

1. ids present in both `savedOrder` and `domIds`, in saved order;
2. ids in `domIds` but not in `savedOrder`, appended in their DOM order — a
   panel added in a later release appears last rather than vanishing;
3. ids in `savedOrder` but not in `domIds` are dropped.

### 3.5 Persistence — `GET/PUT /dlc-3d/card-layout`

New routes on the existing blueprint (`url_prefix="/dlc-3d"`,
`src/dlc_3d_bp/routes.py:23`), resolving the project with
`_active_project_for_user()`.

```
GET  /dlc-3d/card-layout
     -> 200 {"layout": {"ia3d": [...], "ia3dr": [...], "ia3ds": [...]}}
     -> 200 {"layout": {}}            no project selected, or file absent

PUT  /dlc-3d/card-layout
     <- {"card": "ia3ds", "order": ["ia3ds-sam-panel", ...]}
     -> 200 {"ok": true}
     -> 400 unknown card key, or order not a list of strings
     -> 400 {"error": "no active project"}   — the wording and status every
        other project-scoped route on this blueprint already uses
        (`rescan_project`, `routes.py:452-453`)
```

Stored as `dlc3d_card_layout.json` in the project directory, one key per card,
written atomically via the tempfile-then-rename pattern already used for
`videos.json` (`routes.py:231-232`). PUT merges one card's key and leaves the
others alone, so two cards open in two tabs cannot erase each other.

`card` is validated against the three known prefixes; ids are stored verbatim
but only ever applied through `applyOrder`, which intersects them with the DOM,
so a junk id can never inject an element.

**Client behaviour.** One `GET` per page load, shared by the three cards. The
order is applied after the card's markup exists — for the SAM card that means
after `_samInjectCard()` (`inline_analysis_3d_sam.js:5242`). A drop triggers a
debounced `PUT` (400 ms) for that card only.

**Failure mode:** if the `GET` fails, returns nothing, or no project is
selected, the markup order stands. A layout store must never be able to blank
or reorder a card into nonsense — the fallback is always the shipped order.

## Testing

`.mjs` unit tests run per-file under Node 16 (`node --test <file>`).

| test | pins |
|---|---|
| `test_panel_order.mjs` | saved order applies; an id no longer in the DOM is ignored; a panel absent from the saved order still appears; `reorder` to the end; `sameOrder` |
| `test_pellet_box_placement.mjs` (extend) | `camCardHead` emits a clear button carrying its own camera name; show-box reflects visibility |
| `test_sam_panel_ids.mjs` (update) | `ia3ds-pellet-replace{,-cam}` gone; `ia3ds-sam-toggle` and `ia3ds-sam-controls` present |
| `test_sam_card_loads.mjs` (extend) | under jsdom, `ia3ds-sam-panel` is a child of `ia3ds-player-section` and its controls start hidden |
| Python | `card-layout` GET/PUT round-trip; PUT of one card preserves the others; no active project → 409; unknown card → 400; malformed stored JSON reads as `{}` rather than raising |

A DOM-level check that reordering preserves element identity — the same node
object, with whatever was attached to it still attached — belongs with the drag
glue, in a jsdom test of its own (`test_panel_layout.mjs`). It is the one
assertion that separates "moved" from "re-rendered"; an order-only assertion
passes either way.

## Deployment

Parts 1 and 2, and all client-side work in part 3, are under `src/static/`,
which is a whole-directory mount — a browser reload suffices.

The `card-layout` routes need `docker compose restart dlc-3d`. Fact 7 says that
container holds no background work, but **confirm at deploy time rather than
trusting the note**: check `docker ps` and the jobs card before restarting, and
never touch `worker`, `worker-tf` or `dlc-3d-worker`. Deployment runs through a
subagent, as usual for this project.

## Out of scope

- Making `ia3dr-reproj-panel` draggable or checkbox-gated.
- Persisting which panels are expanded — the five don't, so the sixth doesn't.
- Any change to what a panel *does*. Every behaviour change in this spec is a
  consequence of moving or gating a panel, and all of them are listed in 3.1.

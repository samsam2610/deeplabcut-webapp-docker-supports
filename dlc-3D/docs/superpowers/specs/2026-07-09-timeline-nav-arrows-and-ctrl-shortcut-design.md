# Timeline nav — arrows beside labels + Ctrl+Arrow keyboard nav

**Date:** 2026-07-09
**Branch:** `feat/timeline-nav-arrows-and-ctrl-shortcut` (repo: `deeplabcut-webapp-docker-supports`)
**Module:** `dlc-3D`

## Goals

1. **UI:** move the status/note ◀▶ navigation arrows next to the "Status" / "Notes"
   label text (currently pushed to the far right of the header row).
2. **Feature:** `Ctrl+Arrow` (physical Ctrl on both macOS and Windows) navigates to the
   next/previous instance on the **last-used** timeline. After the user clicks a
   timeline's ◀▶ button (which requires an active tag chip), `Ctrl+ArrowRight` /
   `Ctrl+ArrowLeft` repeat that jump on the same timeline. Clicking the other
   timeline's button switches which timeline `Ctrl+Arrow` drives.

## Context / constraints

- The status/note timelines live in the shared `statusNoteTimeline` feature
  (`src/static/components/viewer/features/status_notes.js`), used by three cards.
  Decision: the shortcut applies to **all three** (shared component). The UI move
  applies to the two templates that render the arrows:
  `card_inline_analysis_3d.html` and `card_viewer_3d.html`.
- `nav(field, activeSet, dir)` seeks to the next/prev frame whose value is in the
  **active tag set** for that field. The ◀▶ buttons are disabled until a chip is
  active, so "next instance" == "next frame matching the active filter".
- **Conflict:** `Ctrl+Arrow` is already bound to skip-N-frames in the shared viewer
  (`components/viewer/internal/controls.mjs`: `(ctrlKey || shiftKey) → stepSkip`).
  It is **redundant** — `Shift+Arrow` performs the identical skip. So `Ctrl+Arrow`
  can be repurposed for timeline nav with no loss: skip stays on `Shift+Arrow`.
  Decision: **conditional** override — `Ctrl+Arrow` navigates only when a timeline is
  active; otherwise it falls through to the viewer's skip. `controls.mjs` is untouched.

## Design

### Part 1 — arrows beside the labels

`card_inline_analysis_3d.html`, `card_viewer_3d.html`

Each Status/Notes header row is a flex row: `<span class="fe-csv-bar-label"
style="flex:1;margin:0">Status</span>` followed by the ◀▶ buttons. The `flex:1`
stretches the label so the buttons sit at the far right. Remove `flex:1` (keep
`margin:0`) from the four label spans (2 per template) so the buttons sit immediately
after the label text.

### Part 2 — Ctrl+Arrow nav

`src/static/components/viewer/features/status_notes.js`

- Add feature state `let lastNav = null;` — `{ field, activeSet }` for the last-used
  timeline.
- Route the four ◀▶ button clicks through a helper that records `lastNav` before
  navigating:

  ```js
  function doNav(field, activeSet, dir) {
    lastNav = { field, activeSet };
    nav(field, activeSet, dir);
  }
  ```

  (status buttons → `doNav("frame_line_status", activeStatus, ±1)`;
  note buttons → `doNav("note", activeNote, ±1)`.)

- Add a **capture-phase** `document` keydown handler (registered in `attach` with the
  feature's `AbortController` signal so it tears down on viewer teardown):

  ```js
  function onCtrlArrowKey(e) {
    if (!e.ctrlKey || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
    if (!lastNav || lastNav.activeSet.size === 0) return;            // no active timeline → skip
    const wrap = lastNav.field === "note" ? els.noteWrap : els.statusWrap;
    if (!wrap || wrap.offsetParent === null) return;                // bar hidden / card not visible → skip
    e.preventDefault();
    e.stopImmediatePropagation();                                   // suppress the viewer's Ctrl+Arrow skip
    nav(lastNav.field, lastNav.activeSet, e.key === "ArrowRight" ? 1 : -1);
  }
  document.addEventListener("keydown", onCtrlArrowKey, { capture: true, signal: ac.signal });
  ```

Rationale:
- **Capture phase** runs before the viewer's (target/bubble) keydown handler
  regardless of whether the viewer's `keyboardTarget` is the mount or `document`, so
  `stopImmediatePropagation()` reliably prevents the skip when we handle the key.
- **`offsetParent === null` gate** on the last-nav timeline's wrap scopes the handler
  to the single visible card and to a rendered timeline bar — so hidden cards' feature
  instances stay inert (mirrors the viewer's own `mount.offsetParent === null` gate).
- Keying off the stable `activeStatus`/`activeNote` Set references + the `size === 0`
  and visibility guards means an emptied filter or a video switch (which clears the
  sets in `loadCsv`) automatically falls back to skip — no explicit `lastNav` reset.
- **`ctrlKey`** (not `metaKey`) matches the "Ctrl on both Mac and Windows" requirement.

## Testing

Source-pattern pytest + Playwright e2e (auto-skips without the OM-2 fixture).

- **`tests/test_status_notes_ctrl_arrow_nav.py`** (new):
  - `lastNav` recorded via a `doNav` helper wired to the ◀▶ button clicks.
  - a capture-phase (`capture: true`) keydown handler gated on `ctrlKey` +
    `ArrowLeft/Right`, `activeSet.size`, and `offsetParent` visibility, that calls
    `nav` and uses `stopImmediatePropagation`.
  - handler registered with the abort `signal` (torn down on teardown).
- **`tests/test_timeline_arrows_beside_labels.py`** (new): the four
  `fe-csv-bar-label` spans in the two card templates no longer carry `flex:1`.
- Run `pytest` for the module.
- Manual: activate an "s" status chip → click status ▶ (jumps to next "s") → then
  `Ctrl+→` repeats the jump; activate a note chip and click a note arrow → `Ctrl+→`
  now drives the note timeline; with no active timeline, `Ctrl+→` still skips frames;
  `Shift+→` always skips.

## Non-goals

- No change to `controls.mjs` or the viewer's skip behavior (`Shift+Arrow` unchanged;
  `Ctrl+Arrow` skip still works when no timeline is active).
- No `metaKey` (Cmd) binding — the request is Ctrl on both platforms.
- macOS note: `Ctrl+←/→` is an OS Spaces shortcut; `preventDefault` suppresses it in
  the page, but a user with it bound at the OS level may need to free it. Out of scope.

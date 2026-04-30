# DLC-3D Project Sync — Design Spec

**Date:** 2026-04-30
**Status:** Approved

## Goal

When the user loads or changes the DLC project in the "Manage DLC Project" card, the 3D Frame Extractor card resets its state and auto-loads the new project. No manual re-load required in the extractor.

---

## Mechanism

`dlc_project.js` (main webapp) sets `#dlc-active-path` text content whenever a project is loaded or cleared, via `applyDlcProjectState(data)`. `dlc_3d.js` attaches a `MutationObserver` to that span. No changes to `dlc_project.js` or the backend are needed.

---

## Reset Behavior

When `#dlc-active-path` text content changes:

1. Clear state variables: `_projectPath = null`, `_sessions = {}`, `_activeVideo = null`, `_activeSession = null`
2. Hide `#dlc3d-player-section`
3. Clear `#dlc3d-video-list` innerHTML, show `#dlc3d-session-empty`
4. Reset `#dlc3d-project-path` display to `"No project loaded"`, hide the Rescan button
5. Clear `#extract-status`, hide `#labeled-wrap`
6. If new path is non-empty → call `_loadProject(newPath)` (auto-loads sessions)
7. If path is empty (project cleared) → leave in empty state

`_openCard()` also auto-loads on first open: if `#dlc-active-path` has a value and `_projectPath` is null, call `_loadProject(path)`.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dlc-3D/src/static/dlc_3d.js` |

`card_3d_extract.html`, `dlc_3d.css`, `routes.py` — no changes.

---

## Implementation Notes

- Add `_resetExtractorUI()` helper: encapsulates all the state-clear + DOM-reset steps
- `MutationObserver` config: `{ childList: true, characterData: true, subtree: true }` on `#dlc-active-path`
- Observer callback reads `el.textContent.trim()` as the new path
- `_openCard()` change: one `if (!_projectPath && activePath)` guard at top, calls `_loadProject(activePath)`

---

## Testing

1. `docker compose restart dlc-3d`
2. Load a DLC project in "Manage DLC Project" → click "Extract Frames" → extractor opens with sessions already loaded (no Browse Server needed)
3. With extractor open, load a different project in "Manage DLC Project" → extractor resets and loads new project's sessions
4. Clear project in "Manage DLC Project" → extractor resets to empty state
5. All 26 existing pytest tests pass: `python -m pytest tests/ -q`

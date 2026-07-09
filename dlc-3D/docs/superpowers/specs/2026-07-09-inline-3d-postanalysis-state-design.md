# Inline-3D — preserve view state after an analysis run

**Date:** 2026-07-09
**Branch:** `fix/inline-3d-postanalysis-state` (repo: `deeplabcut-webapp-docker-supports`)
**Module:** `dlc-3D`

## Problem

When "analyze current" / "analyze range" finishes in the inline-3D card, two pieces
of the user's view state are wrongly disturbed:

1. **Active status/note tag filters reset.** Any status/note chips the user had
   activated (to highlight/navigate) are cleared.
2. **The "show kinematic markers" primary layer jumps to the wrong model** — not the
   model that was just used to analyze the frames.

## Root cause

Both analyze handlers (`_onAnalyzeClick`, `_onAnalyzeRangeConfinedClick`) end with a
frame-preserving `_viewer.load()` followed by `_reloadPrimaryAfterAnalysis()`.

- **Bug (a):** `_viewer.load()` emits `videoLoad`, which the shared
  `statusNoteTimeline` feature handles by calling `loadCsv()`. `loadCsv()`
  unconditionally `activeStatus.clear()` / `activeNote.clear()` (status_notes.js
  lines 53–54) on every load — including a reload of the *same* video — so the active
  filters are discarded.
- **Bug (b):** the inline analysis writes its output as a **raw companion** h5
  (`<stem><scorer>.h5`, `ts = null`). `_reloadPrimaryAfterAnalysis` picks the primary
  via `_pickLatestKinematic` → `pickLatestVariant`, which prefers the variant with the
  max `ts`. Any pre-existing **postproc** run (which carries a `ts`) therefore
  outranks the freshly-written companion, so the primary jumps to an unrelated run.
  The analysis done-payload already returns `scorer`, which uniquely names the output
  file (`_resolve_h5_path` = `<stem><scorer>.h5`, main app).

## Design

Decision (from brainstorming): fix bug (a) **narrow / inline-only** — do not change the
shared component's default clear-on-load behavior; snapshot + restore around the
inline analyze flow instead.

### Bug (b) — select the model just used

`src/static/inline_analysis_3d.js`

- Change `_reloadPrimaryAfterAnalysis()` → `_reloadPrimaryAfterAnalysis(scorer)`.
- Both handlers pass the cam0 done-payload scorer: `_reloadPrimaryAfterAnalysis(d0.scorer)`.
- Selection: prefer the variant whose `path` ends with `scorer + ".h5"`; fall back to
  `_pickLatestKinematic(variants)` when `scorer` is empty or unmatched.

```js
async function _reloadPrimaryAfterAnalysis(scorer) {
  _coverageCache.clear();
  const variants = await _fetchOverlayH5Variants();
  let target = null;
  if (scorer) target = variants.find((v) => (v.path || "").endsWith(scorer + ".h5")) || null;
  if (!target) target = _pickLatestKinematic(variants);
  const sel = $("ia3d-overlay-primary-select");
  if (target && sel) {
    sel.value = target.path;
    await _applyOverlayPrimary(target.path);
  } else {
    _markerEditor?.invalidatePoses();
    _refreshCoverage();
  }
}
```

### Bug (a) — preserve active tag filters across the post-analysis reload

`src/static/components/viewer/features/status_notes.js` (inert plumbing only)

- Add `getActiveTags()` → `{ status: [...activeStatus], note: [...activeNote] }`.
- Add `setActiveTags({ status, note })` → repopulate the active sets, keeping only
  values that still exist in the current color maps (prune stale), then `rebuildChips()`
  + `redraw(curFrame())`.

No consumer's behavior changes unless it calls these — viewer-3D / dlc-3D unaffected.

`src/static/inline_analysis_3d.js`

- Add module state `let _pendingTagRestore = null;`.
- Add an `onCsv` callback to the inline `_snTimeline` config. `onCsv` fires at the END
  of `loadCsv` (status_notes.js line 73), after clear+rebuild, so it is the correct
  restore point. When `_pendingTagRestore` is set, call
  `_snTimeline.setActiveTags(_pendingTagRestore)` and clear the flag. (Preserve any
  existing onCsv responsibilities — currently none in this card.)
- In both analyze handlers, immediately before `_viewer.load()`:
  `_pendingTagRestore = _snTimeline?.getActiveTags() || null;`
  The single `videoLoad` → `loadCsv` → `onCsv` cycle consumes it once.

## Testing

Source-pattern pytest (repo convention) + Playwright e2e (auto-skips without the OM-2
fixture).

- **`tests/test_inline_3d_postanalysis_state.py`** (new):
  - `_reloadPrimaryAfterAnalysis` accepts a scorer arg and matches on `scorer + ".h5"`
    with a `_pickLatestKinematic` fallback.
  - both analyze handlers call `_reloadPrimaryAfterAnalysis(d0.scorer)`.
  - inline wires `_pendingTagRestore` (set before `_viewer.load`, restored via `onCsv`).
- **`tests/test_status_notes_active_tags.py`** (new): `statusNoteTimeline` exposes
  `getActiveTags` and `setActiveTags`, and `setActiveTags` prunes to existing values.
- Run `pytest` for the module.
- Manual: activate a status/note chip, run analyze range → chips stay active and the
  primary shows the just-analyzed model.

## Non-goals

- No change to the shared `loadCsv` clear-on-switch behavior (narrow fix, per decision).
- No change to `pickLatestVariant` or the backend analysis/output naming.

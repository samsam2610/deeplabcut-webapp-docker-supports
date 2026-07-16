# Inline 3D Analysis: "Analyze for tag" batch — Design

**Date:** 2026-07-16
**Repo:** `deeplabcut-webapp-docker-supports` (module: `dlc-3D`)
**Status:** Approved design, ready for implementation plan

## Goal

Add a batch-analysis path to the 3D inline-analysis **Finalize** panel that runs
the model over every frame carrying a single locked note tag — reusing the
existing "Start analysis for range" machinery, but fed by tag positions on the
note timeline instead of one manually-locked keyframe.

Two new controls sit in the finalize panel's `.ia3d-analyze-block`, directly
**below** the existing hint *"lock the finalize keyframe to enable 'for range'"*
(`#ia3d-start-hint`):

1. A **`Lock tag`** checkbox that locks in the single active note tag.
2. An **`Analyze for tag`** button that batch-analyzes all frames carrying that tag.

## Background — current implementation (verified on disk)

- **Finalize panel:** `src/templates/partials/card_inline_analysis_3d.html`,
  `#ia3d-finalize-panel` (lines ~377–450). Contains the `#ia3d-finalize-toggle`
  checkbox, the KeyframeLock controls (`#ia3d-finalize-keyframe`,
  `#ia3d-finalize-lock`, and `before`/`after`/`length` inputs
  `#ia3d-finalize-before` = 200, `#ia3d-finalize-after` = 599,
  `#ia3d-finalize-length`), and the always-visible `.ia3d-analyze-block`
  (lines ~412–421) holding both analyze buttons and `#ia3d-start-hint`.
- **Keyframe lock controller:** `src/static/keyframe_window_ui.js`
  (`makeKeyframeWindow`), pure math in
  `src/static/components/viewer/internal/keyframe_window.mjs`
  (`finalizeRange(keyframe, before, after, frameCount)` → `{start, end, n}`,
  clamped to `[0, frameCount-1]`). Instantiated as `_finalizeKW` in
  `src/static/inline_analysis_3d.js` (lines ~494–515).
- **Analyze submit:** `_submitRange(sk, videoPath, startFrame, nFrames)`
  (`inline_analysis_3d.js` ~1887–1904) POSTs `/dlc/project/inline-analysis/range`
  (single camera). Dual-cam is two calls in `Promise.all`. Polled by `_pollReq`.
  The `for range` handler `_onAnalyzeRangeConfinedClick` (~2011–2056) reads
  `_finalizeKW.getRange()` and submits `{start, n}` for cam0 + `_siblingPath`.
- **Analyze gating:** `_refreshAnalyzeEnablement()` (~2061–2084). `for range`
  button `#ia3d-btn-analyze-range-confined` is enabled iff
  `finalizeToggle ON && keyframeLock checked && sibling exists`, and it sets
  `#ia3d-start-hint` to *"lock the finalize keyframe to enable 'for range'"*.
- **Note timeline + tags:** shared module
  `src/static/components/viewer/features/status_notes.js`
  (`statusNoteTimeline`), instantiated as `_snTimeline`
  (`inline_analysis_3d.js` ~184–223). Holds `activeNote` / `activeStatus`
  `Set`s. `renderChips` wires a click handler per chip that toggles the value in
  the active set. `getActiveTags()` → `{status:[…], note:[…]}`. Frame lookup uses
  `findMatchingFrame` / `uniqueValues` in
  `src/static/components/viewer/internal/csv_annotations.mjs`; rows carry
  `frame_number`, `frame_line_status`, `note`.
- **Tag vocabulary:** `note_tags` persists per-project via
  `/dlc/project/ui-setting` (`_makeQuickTags`, `inline_analysis_3d.js`
  ~1301–1361).

## Behavior

### `Lock tag` checkbox (`#ia3d-tag-lock`)

- **Enabled only when exactly one note tag is active** (`activeNote.size === 1`).
  Zero or ≥2 active → **disabled and unchecked**.
- **Checked** → the note timeline's **note** chips freeze: clicking a note chip
  does nothing, so the user cannot activate/deactivate note tags while locked.
  The single active tag is held. Status chips are unaffected.
- **Unchecked** → note chips interactive again.
- If the active-note set stops being exactly 1 (e.g., a video switch reloads the
  CSV and clears active tags) → auto-uncheck, unfreeze, and disable.

### `Analyze for tag` button (`#ia3d-btn-analyze-tag`)

- **Gated identically to "for range," but on the tag-lock:** enabled iff
  `finalizeToggle ON && tagLock checked && sibling exists`.
- On click:
  1. Resolve the locked tag value = the single member of `activeNote`.
  2. `tagKeyframes(rows, tagValue)` → sorted, deduped list of tagged
     `frame_number`s.
  3. `mergeWindows(frames, before, after, frameCount)` — expand each frame to
     `finalizeRange(frame, before, after, frameCount)` and union
     overlapping/adjacent intervals into a minimal sorted list of
     `{start, end, n}`. `before`/`after` come from `_finalizeKW`'s inputs;
     `frameCount` from the viewer. This is the "precompute per-tag ranges →
     union → remove duplicate frames" step.
  4. `window.confirm` a summary: *K tagged frames → J ranges → T total frames ×
     2 cameras*. Abort if the user cancels or T === 0.
  5. `_ensureSession()`; then for each merged range, dual-cam
     `Promise.all([_submitRange(sk, cam0, start, n),
     _submitRange(sk, _siblingPath, start, n)])`, ranges processed
     sequentially. Collect all `req_id`s.
  6. Poll all `req_id`s to done (reuse `_pollReq`).
  7. Run the **existing post-analysis refresh block once** at the end
     (`_ia3dPopulateFinalizeFields`, `_iaDiscoverVariants`, overlay re-enable,
     frame-preserving `_viewer.load`, `_reloadPrimaryAfterAnalysis`).

### Hint line (`#ia3d-tag-hint`)

Mirrors `#ia3d-start-hint`: e.g.
*"activate exactly one note tag to enable"* when disabled;
*"1 note tag locked → analyzes N tagged frames. Unlock to disable."* when armed.

The manual keyframe + keyframe-lock are untouched. The tag-lock is an independent
second locking mechanism that only borrows the `before`/`after` window size.

## Architecture & changes

All changes are in the `dlc-3D` module. **No new HTTP routes.**

### 1. Pure logic — new `.mjs` helper (DOM-free, unit-tested)

`src/static/components/viewer/internal/tag_batch.mjs`:

- `tagKeyframes(rows, tagValue)` → sorted, deduped `frame_number`s where
  `row.note === tagValue`. Ignores empty/other notes and non-numeric frames.
- `mergeWindows(frames, before, after, frameCount)` → import `finalizeRange`
  from `keyframe_window.mjs`; compute a `{start, end}` per frame; merge
  overlapping/adjacent intervals; return sorted `[{start, end, n}]` with
  `n === end - start + 1`.

### 2. Template — `src/templates/partials/card_inline_analysis_3d.html`

Insert after `#ia3d-start-hint` inside `.ia3d-analyze-block`:
- `#ia3d-tag-lock` checkbox + label ("Lock tag").
- `#ia3d-btn-analyze-tag` button (`btn-sm btn-create`, `disabled` by default,
  label "▶ Analyze for tag").
- `#ia3d-tag-hint` status span.

### 3. Shared timeline module — `status_notes.js` (additive, default-off)

- `config.onActiveTagsChange` callback, fired whenever a chip is toggled.
- `setNoteChipsLocked(bool)` public method: when locked, `renderChips` for the
  **note** container skips wiring click handlers and adds a `.locked` visual;
  status chips unaffected. Default unlocked, so other `statusNoteTimeline`
  consumers are unchanged.

### 4. Controller glue — `src/static/inline_analysis_3d.js`

- Pass `onActiveTagsChange: () => _refreshTagLockEnablement()` when building
  `_snTimeline`.
- `_refreshTagLockEnablement()`: read `_snTimeline.getActiveTags().note`; enable
  `#ia3d-tag-lock` iff length === 1; if it drops off 1, uncheck +
  `setNoteChipsLocked(false)` + disable.
- `#ia3d-tag-lock` change handler → `setNoteChipsLocked(checked)`, update
  `#ia3d-tag-hint`, call `_refreshAnalyzeEnablement()`.
- Extend `_refreshAnalyzeEnablement()` to also set `#ia3d-btn-analyze-tag`
  disabled state = `!(finOn && tagLockChecked && hasSibling)`.
- New `_onAnalyzeTagClick()` implementing the batch flow above.
- Reset tag-lock state in the video-switch / `iaBack` teardown paths alongside
  existing lock resets.

### 5. CSS — `src/static/inline_analysis_3d.css`

`.vv-tag-chip.locked` (or a `.locked` container state): `cursor:default`, dimmed,
no hover — signals frozen chips.

## Testing

Follows the repo's three tiers.

### `node:test` unit — `tests/unit/test_tag_batch.mjs`

- `tagKeyframes`: filters by `note` value, dedupes, sorts; ignores empty/other
  notes and non-numeric `frame_number`.
- `mergeWindows`: single frame → one clamped range; two far-apart frames → two
  ranges; two close frames → merged; adjacent/touching windows merge; clamps at
  `0` and `frameCount-1`; `n === end-start+1`.

### pytest static (HTML + JS source)

- `#ia3d-tag-lock` and `#ia3d-btn-analyze-tag` exist inside `#ia3d-finalize-panel`
  `.ia3d-analyze-block`, after `#ia3d-start-hint`; button ships `disabled`.
- `inline_analysis_3d.js` wires `onActiveTagsChange`,
  `_refreshTagLockEnablement`, the tag-lock change handler, and adds the tag gate
  to `_refreshAnalyzeEnablement`.
- `status_notes.js` exposes `setNoteChipsLocked` and fires `onActiveTagsChange`.

### Playwright e2e (`tests/e2e/`) — UI-state only

**Never dispatches real analysis** (honors the repo rule against running analysis
on protected `/user-data`).

- Tag-lock disabled with 0 and with 2 active note tags; enabled with exactly 1.
- Checking tag-lock freezes note chips (a chip click no longer toggles);
  unchecking restores.
- `#ia3d-btn-analyze-tag` gating flips with Finalize toggle + tag-lock + sibling
  presence.

## Edge cases

- **No matching frames** → confirm summary shows 0 and aborts (no-op).
- **Video switch while locked** → CSV reload clears `activeNote` →
  `onActiveTagsChange` → auto-uncheck + unfreeze + re-disable.
- **Windows clamped** to `[0, frameCount-1]`; oversized before/after simply clamp.
- **Shared-module safety** — both `status_notes.js` additions are opt-in
  (default off).

## Out of scope (YAGNI)

- No new backend route; no frame-list submission API (merged contiguous ranges
  cover it).
- No persistence of tag-lock state across reloads.
- No change to the existing keyframe-lock or "for range" behavior.

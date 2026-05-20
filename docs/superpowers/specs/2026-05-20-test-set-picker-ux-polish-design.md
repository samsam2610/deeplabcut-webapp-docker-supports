# Test-set Picker — UX polish

**Date:** 2026-05-20
**Status:** approved, ready for implementation plan
**Scope:** three small UX improvements to the Test-set Picker card shipped in
`feat/test-set-picker`. Follow-up to
`2026-05-19-test-set-picker-design.md`.

---

## 1. Goal

Three independent UX improvements:

1. Replace the "type iteration + shuffle, then click Inspect" dialog with a
   dropdown auto-populated from the splits actually on disk (mirrors the
   labeler's snapshot picker). The current dialog was reported as "doesn't
   work" because users guess values and hit empty-result alerts.
2. Make the bodypart-dot colors in the picker identical to the Frame Labeler's
   so the same bodypart looks the same in both views.
3. In the picker's labeled-frames folder dropdown, show each folder's
   `marked/total` counter next to its name so users can see at a glance which
   folders have any test-set marks.

## 2. Inspect-splits dropdown

### Backend

New route in the existing `dlc_test_set_picker` blueprint:

```
GET /dlc/project/training-dataset/splits
    → { "splits": [
          {
            "iteration": 4,
            "shuffle": 1,
            "train_fraction": 0.8,
            "pickle": "Documentation_data-DREADD_80shuffle1.pickle",
            "label": "iteration-4 • shuffle-1 • trainset 80%"
          },
          …
       ] }
```

Implementation:

- Globs every `<project>/training-datasets/iteration-*/UnaugmentedDataSet_*/Documentation_data-*.pickle` under the active DLC project's root.
- Iteration number is parsed from the parent folder name (`iteration-N`) with a regex; the existing `_DOC_PICKLE_RE` already parses shuffle and train-percent from the pickle filename.
- Results sorted by `(iteration DESC, shuffle ASC)` so the newest iteration appears first.
- Skips files whose name doesn't match `_DOC_PICKLE_RE`; never throws on a single bad pickle (logs and continues).
- Returns `{"splits": []}` on a missing or empty `training-datasets/` folder; never 404.
- Reuses `_active_project()` for the active-project guard.

### Frontend

Edit `templates/partials/card_test_set_picker.html` — replace the two
`<input type="number">` (`ts-inspect-iter`, `ts-inspect-shuffle`) inside
`ts-inspect-dialog` with:

```html
<div class="scorer-row" style="margin-bottom:.85rem">
  <label for="ts-inspect-select">Split</label>
  <select id="ts-inspect-select" style="flex:1">
    <option value="">— loading… —</option>
  </select>
  <button class="btn-sm" id="ts-inspect-refresh" title="Refresh splits list">↻</button>
</div>
```

Edit `static/js/test_set_picker.js`:

- New helper `async function _loadInspectSplits()` calls `GET /dlc/project/training-dataset/splits`, populates `<select>` options. Each option's `value` is `JSON.stringify({iteration, shuffle})`; its text is the server-provided `label`.
- `_openInspectDialog()` calls `_loadInspectSplits()` before showing the dialog.
- The refresh button calls `_loadInspectSplits()` again.
- `_runInspect()` reads the selected option's JSON-encoded value (parses to `{iteration, shuffle}`), then issues the existing `GET /dlc/project/training-dataset/inspect?iteration=…&shuffle=…` call.
- The "Inspect" button is disabled while the select shows the loading placeholder or is empty.
- If the splits list comes back empty, the select shows a single disabled `— no splits found —` option and the Inspect button stays disabled.

The two old number-input IDs are removed entirely (presence tests get updated accordingly).

## 3. Color palette parity

Move the labeler's `FL_COLORS` palette into the shared
`static/js/frame_overlay.js` as an exported constant:

```js
export const DEFAULT_PALETTE = [
  "#f87171","#fb923c","#fbbf24","#a3e635","#34d399",
  "#22d3ee","#818cf8","#e879f9","#f43f5e","#10b981",
  "#3b82f6","#ec4899","#f59e0b","#84cc16","#06b6d4",
];
```

Picker JS replaces its local `TS_DEFAULT_PALETTE` with this import. The labeler keeps its own private `FL_COLORS` array unchanged (touching it risks regressing the lock-BP work that just landed); the value is identical to `DEFAULT_PALETTE`. If it ever drifts, the picker's bodypart palette is the canonical one to keep using `frame_overlay`'s export.

## 4. Folder dropdown counter

Edit `_loadStems()` and `_loadMarks()` in `test_set_picker.js` so marks are
loaded **before** stems are rendered:

- `_openPicker()` already does `Promise.all([_loadBodyparts(), _loadStems(), _loadMarks()])`. Change to `await _loadMarks()` first, then `await _loadStems()` — so `_loadStems` can read `_tsMarks` when rendering.
- In `_loadStems`, each `<option>` text becomes:
  ```js
  const marked = (_tsMarks[stem] || new Set()).size;
  const total  = (s.frames || []).length;
  opt.textContent = `${stem} — ${marked}/${total}`;
  ```
- After every `_toggleCurrentMark`, refresh the **single** option whose value matches `_tsStem` (don't re-fetch stems; just rewrite that one `.textContent`). Add a small helper `_refreshStemOptionLabel(stem)` for this.

No backend change; the existing `/dlc/project/test-set/marks` already
returns per-folder counts.

## 5. Tests

- New `tests/test_test_set_picker_splits_route.py` — 4 cases:
  - empty project (no `training-datasets/`) → `{splits: []}`
  - one iteration with one shuffle → 1 entry, correct fields
  - multiple iterations × multiple shuffles → sorted iteration-DESC, shuffle-ASC
  - malformed pickle filename in the glob → silently skipped, valid ones still returned
- Extend `tests/test_test_set_picker_ui_presence.py`:
  - `test_inspect_dialog_uses_dropdown`: assert `ts-inspect-select` and `ts-inspect-refresh` are in the partial; assert `ts-inspect-iter` and `ts-inspect-shuffle` are gone.
  - `test_frame_overlay_exports_default_palette`: assert `frame_overlay.js` exports `DEFAULT_PALETTE`.
  - `test_picker_js_imports_default_palette`: assert `test_set_picker.js` imports `DEFAULT_PALETTE` from `frame_overlay.js`.
- Existing inspect tests (`tests/test_test_set_picker_inspect.py`) cover the
  actual frame-mapping endpoint; they pass `iteration=&shuffle=` query args
  just like the new dropdown does, so they remain valid without changes.

## 6. Preserving existing behavior

- The existing `GET /dlc/project/training-dataset/inspect` endpoint is unchanged.
- The Frame Labeler card is byte-identical (no shared imports, no touched lines).
- The Test-set Picker card's structure outside the inspect dialog is unchanged.
- No backend change for the folder-counter feature.

## 7. Out of scope

- Showing per-shuffle metrics (loss, eval results) in the inspect dropdown.
- Persisting the last-inspected split per project.
- Inspecting splits from other DLC engines (TF vs PyTorch); the dropdown lists what's on disk, regardless of engine.
- Re-running CTD from inside the inspect view.

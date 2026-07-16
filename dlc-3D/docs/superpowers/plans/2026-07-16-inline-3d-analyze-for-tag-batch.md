# Inline 3D "Analyze for tag" Batch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `Lock tag` checkbox + `Analyze for tag` button to the inline-3D Finalize panel that batch-runs the model over every frame carrying a single locked note tag, reusing the existing keyframe-window + analyze-range machinery.

**Architecture:** Frontend-only change in the `dlc-3D` module. Pure range math goes in a new DOM-free `.mjs` helper (`tag_batch.mjs`, node-tested). The shared `statusNoteTimeline` module gains two additive, default-off hooks (`getRows`, `setNoteChipsLocked`, `onActiveTagsChange`). `inline_analysis_3d.js` wires a tag-lock that gates a new dual-cam batch dispatch built from tagged-frame windows. No new HTTP routes — reuses `/dlc/project/inline-analysis/range`, `_submitRange`, `_pollReq`, `_ensureSession`.

**Tech Stack:** Vanilla ES modules (browser), Jinja partial HTML, CSS. Tests: `node:test` (`.mjs` helpers), `pytest` (static HTML/JS/CSS string guards), `pytest`+Playwright (e2e, read-only).

## Global Constraints

- Repo: `deeplabcut-webapp-docker-supports`, module dir `dlc-3D/`. All paths below are relative to `dlc-3D/`.
- Branch: `feat/inline-3d-analyze-for-tag` (already created; the design spec is committed there).
- **No new backend HTTP routes.** Reuse existing inline-analysis endpoints only.
- **Additive, default-off** changes to the shared `status_notes.js` — other `statusNoteTimeline` consumers must behave identically unless they opt in.
- The `_snTimeline` in this card is instantiated with `frameBase: 0`, so CSV `frame_number` equals viewer seek-frame. The new helper works in `frame_number` space; the host passes `viewer.frameCount()`.
- e2e tests are **read-only**: never dispatch real analysis/finalize/extract against protected `/user-data`.
- Run node unit tests with: `node --test tests/unit/` (from `dlc-3D/`). Run pytest with: `python -m pytest tests/<file> -q`.

---

### Task 1: Pure range helper `tag_batch.mjs`

**Files:**
- Create: `src/static/components/viewer/internal/tag_batch.mjs`
- Test: `tests/unit/test_tag_batch.mjs`

**Interfaces:**
- Consumes: `finalizeRange(keyframe, before, after, frameCount)` from `./keyframe_window.mjs` (returns `{start, end, n}`, clamped to `[0, frameCount-1]`).
- Produces:
  - `tagKeyframes(rows, tagValue)` → `number[]` — sorted, deduped, non-negative integer `frame_number`s where `row.note === tagValue`.
  - `mergeWindows(frames, before, after, frameCount)` → `Array<{start, end, n}>` — each frame expanded via `finalizeRange` then overlapping/adjacent spans merged; sorted by `start`; `n === end - start + 1`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tag_batch.mjs`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { tagKeyframes, mergeWindows } from "../../src/static/components/viewer/internal/tag_batch.mjs";

test("tagKeyframes: filters by note value, dedupes, sorts, drops non-numeric/negative", () => {
  const rows = [
    { frame_number: "30", note: "grab" },
    { frame_number: "10", note: "grab" },
    { frame_number: "10", note: "grab" },   // dup
    { frame_number: "20", note: "rest" },    // other note
    { frame_number: "50", note: "" },        // empty note
    { frame_number: "x", note: "grab" },     // non-numeric
    { frame_number: "-5", note: "grab" },    // negative
  ];
  assert.deepEqual(tagKeyframes(rows, "grab"), [10, 30]);
  assert.deepEqual(tagKeyframes([], "grab"), []);
  assert.deepEqual(tagKeyframes(null, "grab"), []);
});

test("mergeWindows: single frame → one clamped range with correct n", () => {
  assert.deepEqual(mergeWindows([1234], 200, 200, 3000), [{ start: 1034, end: 1434, n: 401 }]);
  assert.deepEqual(mergeWindows([50], 0, 0, 3000), [{ start: 50, end: 50, n: 1 }]);
});

test("mergeWindows: far-apart frames → two ranges; close/overlapping → merged", () => {
  // 10 → [0,609] (clamp low, before 200), 5000 → [4800,5599]; far apart → 2 ranges
  assert.deepEqual(mergeWindows([10, 5000], 200, 599, 6000),
    [{ start: 0, end: 609, n: 610 }, { start: 4800, end: 5599, n: 800 }]);
  // 100 → [0,300], 300 → [100,500]; overlap → merged [0,500]
  assert.deepEqual(mergeWindows([100, 300], 200, 200, 3000), [{ start: 0, end: 500, n: 501 }]);
});

test("mergeWindows: adjacent (touching) windows merge", () => {
  // 200 → [0,400], 601 → [401,801]; touch at 400/401 → merged [0,801]
  assert.deepEqual(mergeWindows([200, 601], 200, 200, 3000), [{ start: 0, end: 801, n: 802 }]);
});

test("mergeWindows: empty input → empty list", () => {
  assert.deepEqual(mergeWindows([], 200, 200, 3000), []);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/unit/test_tag_batch.mjs`
Expected: FAIL — cannot find module `tag_batch.mjs`.

- [ ] **Step 3: Write minimal implementation**

Create `src/static/components/viewer/internal/tag_batch.mjs`:

```javascript
// Pure range math for the inline-3D "Analyze for tag" batch. Turns tagged frames
// into the minimal set of contiguous analyze ranges. No DOM. Works in CSV
// frame_number space (the inline-3D timeline uses frameBase 0, so frame_number ==
// viewer seek-frame).
import { finalizeRange } from "./keyframe_window.mjs";

// Sorted, deduped, non-negative integer frame_numbers whose note === tagValue.
export function tagKeyframes(rows, tagValue) {
  const out = new Set();
  for (const r of rows || []) {
    if (!r || r.note !== tagValue) continue;
    const n = Math.floor(Number(r.frame_number));
    if (Number.isFinite(n) && n >= 0) out.add(n);
  }
  return [...out].sort((a, b) => a - b);
}

// Expand each frame to [frame-before, frame+after] (clamped via finalizeRange),
// then union overlapping/adjacent spans into a minimal sorted list of {start,end,n}.
export function mergeWindows(frames, before, after, frameCount) {
  const spans = (frames || []).map((f) => {
    const { start, end } = finalizeRange(f, before, after, frameCount);
    return { start, end };
  });
  spans.sort((a, b) => a.start - b.start || a.end - b.end);
  const merged = [];
  for (const s of spans) {
    const last = merged[merged.length - 1];
    if (last && s.start <= last.end + 1) {
      if (s.end > last.end) last.end = s.end;
    } else {
      merged.push({ start: s.start, end: s.end });
    }
  }
  return merged.map((r) => ({ start: r.start, end: r.end, n: r.end - r.start + 1 }));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/unit/test_tag_batch.mjs`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/static/components/viewer/internal/tag_batch.mjs tests/unit/test_tag_batch.mjs
git commit -m "feat(inline-3d): tag_batch.mjs — tagged frames → merged analyze ranges

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `statusNoteTimeline` hooks — getRows, setNoteChipsLocked, onActiveTagsChange

**Files:**
- Modify: `src/static/components/viewer/features/status_notes.js`
- Test: `tests/test_status_notes_tag_lock.py` (create)

**Interfaces:**
- Consumes: existing `rows`, `activeNote`, `renderChips`, `rebuildChips`, `config` in the module.
- Produces (new public API on the returned object + config hook):
  - `getRows()` → array of shallow-copied row objects (inert accessor).
  - `setNoteChipsLocked(on)` → when `on`, note chips render without click handlers and carry a `.locked` class; status chips unaffected. Re-renders chips.
  - `config.onActiveTagsChange()` — optional callback fired after a chip toggle changes an active set.

- [ ] **Step 1: Write the failing test**

Create `tests/test_status_notes_tag_lock.py`:

```python
"""Guards for the statusNoteTimeline tag-lock hooks used by the inline-3D
"Analyze for tag" batch. All additive + default-off — other consumers unaffected
unless they pass onActiveTagsChange / call setNoteChipsLocked.

See docs/superpowers/specs/2026-07-16-inline-3d-analyze-for-tag-batch-design.md.
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "static" / "components" / "viewer" / "features" / "status_notes.js"


def _src():
    assert SRC.is_file(), f"missing {SRC}"
    return SRC.read_text()


def test_exposes_get_rows_and_set_note_chips_locked():
    s = _src()
    assert re.search(r"\bgetRows\s*\(", s), "must expose getRows()"
    assert re.search(r"\bsetNoteChipsLocked\s*\(", s), "must expose setNoteChipsLocked()"


def test_note_chips_lock_skips_click_and_adds_class():
    s = _src()
    # renderChips must accept a locked flag, add a "locked" class, and only wire the
    # click listener when not locked.
    assert "noteChipsLocked" in s, "must track a note-chips-locked flag"
    assert re.search(r'"\s*locked\s*"', s) or "locked" in s, "locked chips need a class"
    assert re.search(r"if\s*\(\s*!locked\s*\)", s), "click listener must be gated on !locked"


def test_chip_toggle_fires_on_active_tags_change():
    s = _src()
    assert "onActiveTagsChange" in s, "chip toggle must fire config.onActiveTagsChange"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_status_notes_tag_lock.py -q`
Expected: FAIL — `getRows` / `setNoteChipsLocked` / `noteChipsLocked` / `onActiveTagsChange` absent.

- [ ] **Step 3: Write minimal implementation**

In `src/static/components/viewer/features/status_notes.js`:

(a) Add the lock flag next to the other `let` state (after `const activeNote = new Set();`, line ~42):

```javascript
  const activeNote = new Set();
  // When true, the NOTE chips render inert (no click handler, .locked class) so the
  // consumer can freeze the active-note selection. Status chips unaffected.
  let noteChipsLocked = false;
```

(b) Update `rebuildChips()` to pass the locked flag for the note container:

```javascript
  function rebuildChips() {
    renderChips(els.statusChips, statusColors, activeStatus, false);
    renderChips(els.noteChips, noteColors, activeNote, noteChipsLocked);
    updateNavDisabled();
  }
```

(c) Replace `renderChips` (currently `function renderChips(container, colorMap, activeSet) {...}`) with a version taking a `locked` param:

```javascript
  function renderChips(container, colorMap, activeSet, locked) {
    if (!container) return;
    container.innerHTML = "";
    for (const val of Object.keys(colorMap)) {
      const chip = container.ownerDocument.createElement("span");
      chip.className = "vv-tag-chip" + (activeSet.has(val) ? " active" : "") + (locked ? " locked" : "");
      chip.textContent = val;
      chip.style.setProperty("--chip-color", colorMap[val]);
      if (!locked) {
        chip.addEventListener("click", () => {
          if (activeSet.has(val)) activeSet.delete(val);
          else activeSet.add(val);
          rebuildChips();
          redraw(curFrame());
          if (config.onActiveTagsChange) config.onActiveTagsChange();
        });
      }
      container.appendChild(chip);
    }
  }
```

(d) Add two accessors to the returned object (after `setActiveTags(tags) {...}`, before the closing `};`):

```javascript
    // Shallow-copied rows for consumers that compute over the companion CSV (e.g.
    // the inline-3D "Analyze for tag" batch). Inert — does not mutate module state.
    getRows() {
      return rows.map((r) => ({ ...r }));
    },
    // Freeze/unfreeze the NOTE chips: locked chips render without click handlers so
    // the active-note selection can't change. Repaints chips. Default unlocked.
    setNoteChipsLocked(on) {
      noteChipsLocked = !!on;
      rebuildChips();
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_status_notes_tag_lock.py -q`
Expected: PASS (3 tests).

Also run the existing timeline guards to confirm no regression:

Run: `python -m pytest tests/test_status_notes_active_tags.py tests/test_status_notes_feature.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/static/components/viewer/features/status_notes.js tests/test_status_notes_tag_lock.py
git commit -m "feat(inline-3d): statusNoteTimeline getRows/setNoteChipsLocked/onActiveTagsChange

Additive, default-off hooks for the Analyze-for-tag batch: freeze note chips and
read rows without mutating state.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Template — tag-lock checkbox + Analyze-for-tag button + hint

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html` (inside `.ia3d-analyze-block`, lines ~412–421)
- Test: `tests/test_inline_3d_analyze_for_tag_markup.py` (create)

**Interfaces:**
- Produces DOM ids consumed by Task 5: `#ia3d-tag-lock` (checkbox), `#ia3d-btn-analyze-tag` (button), `#ia3d-tag-hint` (span).

- [ ] **Step 1: Write the failing test**

Create `tests/test_inline_3d_analyze_for_tag_markup.py`:

```python
"""Static guards for the inline-3D "Analyze for tag" controls: a Lock-tag checkbox
and an Analyze-for-tag button live in the analyze block, below the for-range hint.

See docs/superpowers/specs/2026-07-16-inline-3d-analyze-for-tag-batch-design.md.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"


def _idx(hay, needle):
    i = hay.find(needle)
    assert i >= 0, f"not found: {needle}"
    return i


def test_tag_lock_and_button_in_analyze_block_after_hint():
    html = CARD.read_text()
    block = _idx(html, 'class="ia3d-analyze-block"')
    hint = _idx(html, 'id="ia3d-start-hint"')
    outputs = _idx(html, 'id="ia3d-finalize-outputs"')
    lock = _idx(html, 'id="ia3d-tag-lock"')
    btn = _idx(html, 'id="ia3d-btn-analyze-tag"')
    tag_hint = _idx(html, 'id="ia3d-tag-hint"')
    # new controls sit inside the analyze block, after the for-range hint, before outputs
    for i in (lock, btn, tag_hint):
        assert block < hint < i < outputs, "tag-lock controls must sit after #ia3d-start-hint in the analyze block"


def test_analyze_for_tag_button_disabled_by_default():
    html = CARD.read_text()
    i = _idx(html, 'id="ia3d-btn-analyze-tag"')
    # the button element (up to its closing '>') must ship the disabled attribute
    tag = html[i:html.index(">", i)]
    assert "disabled" in tag, "Analyze-for-tag button must ship disabled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_inline_3d_analyze_for_tag_markup.py -q`
Expected: FAIL — `id="ia3d-tag-lock"` not found.

- [ ] **Step 3: Write minimal implementation**

In `src/templates/partials/card_inline_analysis_3d.html`, insert the new controls immediately after the `#ia3d-start-hint` span (line 416), still inside `.ia3d-analyze-block`:

```html
            <span id="ia3d-start-hint" class="ia3d-start-hint"></span>
            <!-- Analyze for tag: batch the model over every frame carrying one locked
                 note tag. Lock-tag is enabled only when exactly one note tag is active;
                 checking it freezes the note chips. Button gated like "for range". -->
            <div class="ia3d-tag-batch">
              <label class="ia3d-tag-lock-label" title="Lock the single active note tag (freezes note chips)">
                <input type="checkbox" id="ia3d-tag-lock" disabled style="accent-color:var(--accent);width:14px;height:14px"/>
                Lock tag
              </label>
              <button id="ia3d-btn-analyze-tag" class="btn-sm btn-create" disabled
                title="Run analysis on every frame carrying the locked note tag (both cameras)">
                ▶ Analyze for tag
              </button>
              <span id="ia3d-tag-hint" class="ia3d-start-hint"></span>
            </div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_inline_3d_analyze_for_tag_markup.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/templates/partials/card_inline_analysis_3d.html tests/test_inline_3d_analyze_for_tag_markup.py
git commit -m "feat(inline-3d): Lock-tag checkbox + Analyze-for-tag button markup

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: CSS — frozen note-chip style

**Files:**
- Modify: `src/static/inline_analysis_3d.css` (after the `.vv-tag-chip.active` rule, line ~124)
- Test: `tests/test_inline_3d_analyze_for_tag_css.py` (create)

**Interfaces:**
- Produces: a `.vv-tag-chip.locked` style scoped to `#inline-analysis-3d-card`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_inline_3d_analyze_for_tag_css.py`:

```python
"""Frozen note chips need a non-interactive visual. See design spec 2026-07-16."""
import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "src" / "static" / "inline_analysis_3d.css"


def test_locked_chip_rule_present():
    css = CSS.read_text()
    m = re.search(r"#inline-analysis-3d-card\s+\.vv-tag-chip\.locked\s*\{([^}]*)\}", css)
    assert m, "missing .vv-tag-chip.locked rule"
    body = m.group(1)
    assert "cursor" in body and "default" in body, "locked chips must not show a pointer cursor"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_inline_3d_analyze_for_tag_css.py -q`
Expected: FAIL — no `.vv-tag-chip.locked` rule.

- [ ] **Step 3: Write minimal implementation**

In `src/static/inline_analysis_3d.css`, after the `.vv-tag-chip.active` block (ends line 124), add:

```css
/* Frozen note chips while a tag is locked for "Analyze for tag": inert, dimmed. */
#inline-analysis-3d-card .vv-tag-chip.locked {
  cursor: default;
  opacity: .5;
}
#inline-analysis-3d-card .vv-tag-chip.locked:hover {
  border-color: var(--border);
  color: var(--text-dim);
}
#inline-analysis-3d-card .vv-tag-chip.locked.active {
  opacity: 1;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_inline_3d_analyze_for_tag_css.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/static/inline_analysis_3d.css tests/test_inline_3d_analyze_for_tag_css.py
git commit -m "feat(inline-3d): .vv-tag-chip.locked frozen-chip style

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Controller glue — wire the tag-lock + Analyze-for-tag batch

**Files:**
- Modify: `src/static/inline_analysis_3d.js`
  - import (line ~27), `_snTimeline` config (lines ~184–222), `_refreshAnalyzeEnablement` (lines ~2061–2084), `_wireStereoDispatch` (lines ~2362–2365), `_iaBack` (lines ~1508–1516).
  - Add new module functions near the analyze handlers (~line 2057).
- Test: `tests/test_inline_3d_analyze_for_tag_wiring.py` (create)

**Interfaces:**
- Consumes: `tagKeyframes`, `mergeWindows` (Task 1); `_snTimeline.getActiveTags()`, `.getRows()`, `.setNoteChipsLocked()` (Task 2); DOM ids `#ia3d-tag-lock`, `#ia3d-btn-analyze-tag`, `#ia3d-tag-hint` (Task 3); existing `_ensureSession`, `_submitRange`, `_pollReq`, `_cam0Path`, `_siblingPath`, `_iaDiscoverVariants`, `_reloadPrimaryAfterAnalysis`, `_ia3dPopulateFinalizeFields`, finalize before/after inputs `#ia3d-finalize-before`/`#ia3d-finalize-after`.
- Produces: `_refreshTagLockEnablement()`, `_updateTagHint()`, `_onAnalyzeTagClick()`; extends `_refreshAnalyzeEnablement()` to gate `#ia3d-btn-analyze-tag`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_inline_3d_analyze_for_tag_wiring.py`:

```python
"""Static guards for the inline-3D Analyze-for-tag controller wiring.

See docs/superpowers/specs/2026-07-16-inline-3d-analyze-for-tag-batch-design.md.
"""
import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "src" / "static" / "inline_analysis_3d.js"


def _js():
    return JS.read_text()


def test_imports_tag_batch_helpers():
    s = _js()
    assert re.search(r'import\s*\{[^}]*tagKeyframes[^}]*mergeWindows[^}]*\}\s*from\s*"[^"]*tag_batch\.mjs"', s), \
        "must import tagKeyframes + mergeWindows from tag_batch.mjs"


def test_snTimeline_wires_on_active_tags_change():
    s = _js()
    assert "onActiveTagsChange" in s and "_refreshTagLockEnablement" in s, \
        "statusNoteTimeline must call _refreshTagLockEnablement on tag change"


def test_tag_lock_enablement_requires_exactly_one_note():
    s = _js()
    # enable iff exactly one active note tag
    assert re.search(r"getActiveTags\(\)\.note", s), "must read active note tags"
    assert re.search(r"\.length\s*===\s*1", s), "tag-lock enabled only when exactly one note tag active"


def test_tag_lock_change_freezes_chips():
    s = _js()
    assert re.search(r'ia3d-tag-lock"\)\?\.addEventListener\("change"', s), "tag-lock change must be wired"
    assert "setNoteChipsLocked" in s, "tag-lock change must freeze/unfreeze note chips"


def test_analyze_for_tag_button_wired_and_gated():
    s = _js()
    assert re.search(r'ia3d-btn-analyze-tag"\)\?\.addEventListener\("click",\s*_onAnalyzeTagClick', s), \
        "Analyze-for-tag button must be wired to _onAnalyzeTagClick"
    # gate mirrors for-range: finalize on && tag-lock checked && sibling
    assert re.search(r'ia3d-btn-analyze-tag"\)[\s\S]{0,200}finOn\s*&&\s*tagLocked\s*&&\s*hasSibling', s) or \
           re.search(r'tagLocked\s*&&\s*hasSibling', s), "tag button gated on finalize+tagLock+sibling"


def test_analyze_for_tag_builds_and_submits_merged_ranges():
    s = _js()
    assert "_onAnalyzeTagClick" in s, "must define _onAnalyzeTagClick"
    assert re.search(r"tagKeyframes\(", s) and re.search(r"mergeWindows\(", s), \
        "batch must build ranges via tagKeyframes + mergeWindows"
    assert "window.confirm" in s, "batch must confirm before dispatching"
    # dual-cam submit per range reusing _submitRange
    assert s.count("_submitRange(") >= 4, "batch must submit both cams (in addition to the two existing callers)"


def test_iaback_resets_tag_lock():
    s = _js()
    back = s[s.index("function _iaBack()"): s.index("function _iaBack()") + 800]
    assert "ia3d-tag-lock" in back, "_iaBack must reset the tag-lock checkbox"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_inline_3d_analyze_for_tag_wiring.py -q`
Expected: FAIL — none of the wiring exists yet.

- [ ] **Step 3a: Add the import**

In `src/static/inline_analysis_3d.js`, after line 27 (`import { addTag, removeTag } from "./internal/tag_list.mjs";`):

```javascript
import { tagKeyframes, mergeWindows } from "./components/viewer/internal/tag_batch.mjs";
```

- [ ] **Step 3b: Wire `onActiveTagsChange` + refresh in the `_snTimeline` config**

In the `statusNoteTimeline({...})` call, add `onActiveTagsChange` and extend the `onCsv` hook (replace the existing `onCsv: () => {...}` block, lines ~216–221):

```javascript
    // Recompute tag-lock enablement whenever the user toggles a note/status chip.
    onActiveTagsChange: () => _refreshTagLockEnablement(),
    onCsv: () => {
      if (_pendingTagRestore) {
        _snTimeline?.setActiveTags(_pendingTagRestore);
        _pendingTagRestore = null;
      }
      // A CSV (re)load clears the active-note set (or restores it above); refresh the
      // tag-lock so a video switch drops the lock and a same-video reload keeps it.
      _refreshTagLockEnablement();
    },
```

- [ ] **Step 3c: Add the enablement + hint helpers**

Insert directly above `function _refreshAnalyzeEnablement()` (line ~2061):

```javascript
// Enable the Lock-tag checkbox only when exactly one note tag is active. If the
// active-note count drifts off 1 (e.g. a video switch clears it), drop the lock and
// unfreeze the chips. Called on chip toggles (onActiveTagsChange) and CSV reloads.
function _refreshTagLockEnablement() {
  const lock = $("ia3d-tag-lock");
  if (!lock) return;
  const activeNotes = _snTimeline ? _snTimeline.getActiveTags().note : [];
  const exactlyOne = activeNotes.length === 1;
  lock.disabled = !exactlyOne;
  if (!exactlyOne && lock.checked) {
    lock.checked = false;
    _snTimeline?.setNoteChipsLocked(false);
  }
  _updateTagHint();
  _refreshAnalyzeEnablement();
}

// Mirror #ia3d-start-hint's wording for the tag path.
function _updateTagHint() {
  const hint = $("ia3d-tag-hint");
  if (!hint) return;
  const activeNotes = _snTimeline ? _snTimeline.getActiveTags().note : [];
  const locked = !!$("ia3d-tag-lock")?.checked;
  if (locked && activeNotes.length === 1) {
    const n = tagKeyframes(_snTimeline.getRows(), activeNotes[0]).length;
    hint.textContent = `1 note tag locked → analyzes ${n} tagged frame${n === 1 ? "" : "s"}. Unlock to disable.`;
  } else if (activeNotes.length === 1) {
    hint.textContent = 'check "Lock tag" to enable "Analyze for tag".';
  } else {
    hint.textContent = 'activate exactly one note tag to enable "Analyze for tag".';
  }
}
```

- [ ] **Step 3d: Gate the button inside `_refreshAnalyzeEnablement`**

Inside `_refreshAnalyzeEnablement()`, after the `if (rng) rng.disabled = !rangeOk;` line (line 2072), add:

```javascript
  // Analyze-for-tag mirrors the for-range gate but keys on the tag-lock.
  const tagBtn = $("ia3d-btn-analyze-tag");
  const tagLocked = !!$("ia3d-tag-lock")?.checked;
  if (tagBtn) tagBtn.disabled = !(finOn && tagLocked && hasSibling);
```

- [ ] **Step 3e: Add the batch handler**

Insert after `_onAnalyzeRangeConfinedClick` (after line 2056, before the `_refreshAnalyzeEnablement` comment block):

```javascript
// Analyze BOTH cameras over every frame carrying the single locked note tag.
// Each tagged frame expands to the finalize before/after window; overlapping windows
// are merged (deduped) into minimal ranges. Gated by the UI (finalize on && tag-lock
// && sibling). Reuses the same session + dual-cam submit/poll as the for-range path.
async function _onAnalyzeTagClick() {
  const lastRun = _ia3dEl.lastRun();
  const cam0 = _cam0Path();
  if (!cam0) { if (lastRun) lastRun.textContent = "Pick a cam0 video first."; return; }
  if (!_siblingPath) { if (lastRun) lastRun.textContent = "No sibling camera — cannot run 3D analysis."; return; }
  const activeNotes = _snTimeline ? _snTimeline.getActiveTags().note : [];
  if (activeNotes.length !== 1) { if (lastRun) lastRun.textContent = "Activate exactly one note tag first."; return; }
  const tagValue = activeNotes[0];
  const frames = tagKeyframes(_snTimeline.getRows(), tagValue);
  const before = parseInt($("ia3d-finalize-before")?.value, 10) || 0;
  const after  = parseInt($("ia3d-finalize-after")?.value, 10) || 0;
  const frameCount = _viewer ? _viewer.frameCount() : 0;
  const ranges = mergeWindows(frames, before, after, frameCount);
  const totalFrames = ranges.reduce((s, r) => s + r.n, 0);
  if (!frames.length || !ranges.length || totalFrames < 1) {
    if (lastRun) lastRun.textContent = `Note tag "${tagValue}" has no frames to analyze.`;
    return;
  }
  const ok = window.confirm(
    `Analyze note tag "${tagValue}":\n` +
    `${frames.length} tagged frame(s) → ${ranges.length} range(s) → ${totalFrames} frames × 2 cameras.\n\nProceed?`
  );
  if (!ok) return;
  const sk = await _ensureSession();
  if (!sk) return;
  const btn = $("ia3d-btn-analyze-tag");
  if (btn) btn.disabled = true;
  if (lastRun) { lastRun.textContent = `Analyzing note tag "${tagValue}" (${ranges.length} ranges)…`; lastRun.className = "fe-extract-status"; }
  const reqIds = [];
  let submitFailed = false;
  for (const r of ranges) {
    const [q0, q1] = await Promise.all([
      _submitRange(sk, cam0, r.start, r.n),
      _submitRange(sk, _siblingPath, r.start, r.n),
    ]);
    if (!q0 || !q1) { submitFailed = true; break; }
    reqIds.push(q0, q1);
  }
  if (submitFailed) { _refreshAnalyzeEnablement(); return; }
  const results = await Promise.all(reqIds.map((id) => _pollReq(id)));
  const errs = results.filter((d) => d.status === "error");
  const lastDone = results.find((d) => d.status === "done");
  if (lastRun) {
    lastRun.textContent = errs.length === results.length
      ? `All ranges failed: ${errs[0]?.error || "unknown"}`
      : `Note tag "${tagValue}" done: ${results.length - errs.length}/${results.length} submits ok.`;
    if (errs.length === results.length) { lastRun.className = "fe-extract-status err"; _refreshAnalyzeEnablement(); return; }
  }
  // Post-analysis refresh — run ONCE (mirrors _onAnalyzeRangeConfinedClick).
  _ia3dPopulateFinalizeFields();
  await _iaDiscoverVariants(cam0);
  const ov = $("ia3d-overlay-toggle");
  if (ov && !ov.checked) { ov.checked = true; ov.dispatchEvent(new Event("change", { bubbles: true })); }
  else { _markerEditor?.setOverlayEnabled(true); }
  if (_viewer && _primaryRel) {
    _pendingTagRestore = _snTimeline?.getActiveTags() || null;
    const keepFrame = _viewer.currentFrame();
    const framesMode = _iaMode === "frames";
    const sync = $("ia3d-sync-cam");
    await _viewer.load({ videoPath: _primaryRel, frameCount: _frameCount, framesMode, siblingPath: sync?.checked && !framesMode ? undefined : null });
    if (keepFrame > 0) _viewer.seek(keepFrame);
    _applyCamLabels();
  }
  if (lastDone) await _reloadPrimaryAfterAnalysis(lastDone.scorer);
  _refreshTagLockEnablement();
}
```

- [ ] **Step 3f: Wire the checkbox + button in `_wireStereoDispatch`**

In `_wireStereoDispatch()`, after the existing left-region wiring (after line 2365, `$("ia3d-finalize-lock")?.addEventListener("change", _refreshAnalyzeEnablement);`):

```javascript
  // Analyze-for-tag: Lock-tag freezes the note chips + gates the batch button.
  $("ia3d-tag-lock")?.addEventListener("change", () => {
    const on = !!$("ia3d-tag-lock").checked;
    _snTimeline?.setNoteChipsLocked(on);
    _updateTagHint();
    _refreshAnalyzeEnablement();
  });
  $("ia3d-btn-analyze-tag")?.addEventListener("click", _onAnalyzeTagClick);
```

- [ ] **Step 3g: Reset the tag-lock in `_iaBack`**

In `_iaBack()`, after `_finalizeKW = null;` (line 1513), add:

```javascript
  const _tagLock = $("ia3d-tag-lock");
  if (_tagLock) { _tagLock.checked = false; _tagLock.disabled = true; }
  _snTimeline?.setNoteChipsLocked(false);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_inline_3d_analyze_for_tag_wiring.py -q`
Expected: PASS (7 tests).

Run the broader inline-3D static + node suites to confirm no regression:

Run: `python -m pytest tests/test_inline_3d_panel_consolidation.py tests/test_inline_analysis_3d_ui_isolation.py tests/test_inline_3d_lock_wiring.py -q && node --test tests/unit/*.mjs`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/static/inline_analysis_3d.js tests/test_inline_3d_analyze_for_tag_wiring.py
git commit -m "feat(inline-3d): wire Lock-tag + Analyze-for-tag batch dispatch

Tag-lock enables only with exactly one active note tag and freezes the note chips;
Analyze-for-tag builds merged ranges from tagged frames and dual-cam submits them
via the existing range machinery, gated on finalize+tag-lock+sibling.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: e2e — presence + default-disabled gating (read-only)

**Files:**
- Test: `tests/e2e/test_inline_3d_analyze_for_tag.py` (create)

**Interfaces:**
- Consumes: the running card at `/dlc-3d/` via the shared e2e conftest `page`/`base_url` fixtures (same pattern as `tests/e2e/test_inline_3d_reorg.py`).

**Note on scope:** The e2e fixture opens the OM-2 video through the Browse tab; that path has no companion CSV note chips and no resolvable sibling (documented in `test_inline_3d_reorg.py`). So e2e covers what's frame/CSV-independent: both controls present, and both disabled by default (0 active note tags, no sibling). The exactly-one-active gating, chip-freeze, and range building are covered by Tasks 1–5 (unit + static). Do **not** trigger analysis.

- [ ] **Step 1: Write the test**

Create `tests/e2e/test_inline_3d_analyze_for_tag.py`:

```python
"""Live read-only checks for the inline-3D "Analyze for tag" controls.

Reuses the reorg suite's card-open fixture pattern. READ-ONLY: asserts the Lock-tag
checkbox + Analyze-for-tag button are present and disabled by default (no active
note tag, no sibling in this fixture). NEVER triggers analysis. Richer gating +
chip-freeze are covered by unit/static tests (see design spec 2026-07-16).
"""
import pytest
from playwright.sync_api import Page, expect

SESSION = "OM-2_20260424"
PROJECT_PATH_IN_CONTAINER = (
    "/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07"
)
BROWSE_VIDEO = f"{PROJECT_PATH_IN_CONTAINER}/videos/{SESSION}.mp4"


@pytest.fixture(autouse=True)
def _open_inline_card(page: Page, base_url):
    page.goto(base_url)
    page.locator("#btn-open-inline-analysis-3d").click()
    page.locator("#inline-analysis-3d-card").wait_for(state="visible")
    page.locator("#ia3d-tab-browse").click()
    page.locator("#ia3d-browse-breadcrumb").fill(BROWSE_VIDEO)
    page.locator("#ia3d-browse-breadcrumb").press("Enter")
    page.locator("#ia3d-player-section").wait_for(state="visible", timeout=15000)
    page.wait_for_function(
        "() => window.__iaViewer && document.querySelector('#ia3d-viewer-mount .vv-tile')"
    )


def test_tag_controls_present(page: Page):
    expect(page.locator("#ia3d-tag-lock")).to_be_visible()
    expect(page.locator("#ia3d-btn-analyze-tag")).to_be_visible()


def test_tag_lock_disabled_without_active_note(page: Page):
    # No companion-CSV note chips in this fixture → zero active note tags → lock off.
    expect(page.locator("#ia3d-tag-lock")).to_be_disabled()


def test_analyze_for_tag_disabled_by_default(page: Page):
    expect(page.locator("#ia3d-btn-analyze-tag")).to_be_disabled()
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/e2e/test_inline_3d_analyze_for_tag.py -q`
Expected: PASS (3 tests). If the e2e stack is not running in this environment, note that these tests require the live card (same precondition as the existing `tests/e2e/` suite) and run them where the stack is available.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_inline_3d_analyze_for_tag.py
git commit -m "test(inline-3d): e2e presence + default-disabled gating for Analyze-for-tag

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Run the full relevant suite:

```bash
node --test tests/unit/*.mjs
python -m pytest tests/test_status_notes_tag_lock.py \
  tests/test_inline_3d_analyze_for_tag_markup.py tests/test_inline_3d_analyze_for_tag_css.py \
  tests/test_inline_3d_analyze_for_tag_wiring.py tests/test_inline_3d_panel_consolidation.py \
  tests/test_status_notes_active_tags.py -q
```

Expected: all PASS.

- [ ] Manual smoke (in the running app, on a labeled video with a cam1 sibling and companion-CSV note tags): open the inline-3D card → activate one note tag on the Notes timeline → confirm `Lock tag` enables → check it → confirm note chips freeze and clicking them does nothing → confirm `Analyze for tag` enables only when Finalize is on → click it, confirm the confirm-dialog summary matches the tagged-frame count, then let it dispatch and verify markers repaint after completion. (Reminder: only against a non-protected project.)
```

## Self-Review notes

- **Spec coverage:** Lock-tag behavior → Tasks 3/5; Analyze-for-tag batch → Tasks 1/5; window from finalize before/after → Task 5 (Step 3e); merge/dedup → Task 1; shared-module additive hooks → Task 2; CSS freeze → Task 4; all three test tiers → Tasks 1/2/3/4/5/6; edge cases (no frames, video switch, clamp, shared-module safety) → Tasks 1 (clamp/empty), 5 (no-frames abort, `_refreshTagLockEnablement` reset via onCsv + `_iaBack`), 2 (default-off).
- **Type consistency:** `mergeWindows` returns `{start,end,n}`; `_submitRange(sk, videoPath, startFrame, nFrames)` consumes `r.start`/`r.n`. `tagKeyframes(rows, tagValue)` consumes `_snTimeline.getRows()`. `getActiveTags().note` is a string array. Names match across tasks.

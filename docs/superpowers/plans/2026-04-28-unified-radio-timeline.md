# Unified Radio-Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the tag-bar chip/timeline interaction so every timeline (main canvas + sub-rows) has a radio button; the selected radio determines which timeline responds to chip clicks; each timeline independently tracks its own active-chip Set.

**Architecture:** The HTML gains a `.ep-main-row` wrapper around each main canvas so the main timeline is visually and functionally identical to sub-rows (radio + canvas, no `×`). JS replaces per-sub-row `dataset.chipVal` (single string) with `row._activeChips` (Set). `_epDrawSubCanvas` is updated to accept a Set. All chip-click routing checks which radio is currently checked.

**Tech Stack:** Vanilla JS (ES2020), HTML/CSS, Playwright (pytest) for UI tests. Flask serves static files — no backend changes needed.

---

## File Map

| File | Change |
|---|---|
| `clip-cutter/templates/clip_cutter.html` | Add `.ep-main-row` + main radio for both bars; add `.ep-main-row` CSS |
| `clip-cutter/static/enhanced_player.js` | Init empty Sets; main radio listeners; `_epDrawSubCanvas` accepts Set; `_epRenderStatusChips`/`_epRenderNoteChips` routing; `_epAddSubRow` uses `_activeChips`; remove-button falls back to main radio |
| `clip-cutter/tests/test_ui.py` | Replace current chip-toggle tests with tests matching new model |

---

## Task 1: Add main-row radio to HTML + CSS

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui.py` (after existing chip tests):

```python
def test_status_main_radio_exists_and_is_checked(page: Page):
    """On load, the status bar has a main-row radio that is checked by default."""
    _setup_player_with_csv(page)
    radio = page.locator("#ep-status-main-radio")
    expect(radio).to_have_count(1)
    assert page.evaluate("document.getElementById('ep-status-main-radio').checked") is True

def test_note_main_radio_exists_and_is_checked(page: Page):
    """On load, the note bar has a main-row radio that is checked by default."""
    _setup_player_with_csv(page)
    radio = page.locator("#ep-note-main-radio")
    expect(radio).to_have_count(1)
    assert page.evaluate("document.getElementById('ep-note-main-radio').checked") is True

def test_main_row_radio_in_same_group_as_sub_rows(page: Page):
    """Main radio and sub-row radio share the same radio group (mutual exclusion)."""
    _setup_player_with_csv(page)
    # Add a sub-row — its radio auto-selects, main should deselect
    page.locator("#ep-status-add-sub").click()
    assert page.evaluate("document.getElementById('ep-status-main-radio').checked") is False
    expect(page.locator("#ep-status-sub-rows .ep-sub-radio:checked")).to_have_count(1)
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd clip-cutter && python -m pytest tests/test_ui.py::test_status_main_radio_exists_and_is_checked tests/test_ui.py::test_note_main_radio_exists_and_is_checked tests/test_ui.py::test_main_row_radio_in_same_group_as_sub_rows -v
```

Expected: 3 FAILED (elements not found)

- [ ] **Step 3: Add CSS for `.ep-main-row`**

In `clip_cutter.html`, locate the `.ep-sub-rows` CSS block (around line 497) and add after it:

```css
.ep-main-row { display:flex; align-items:center; gap:3px; }
.ep-main-row canvas { flex:1; min-width:0; display:block; cursor:pointer; border-radius:2px; background:#161b22; }
.ep-main-radio { accent-color:#388bfd; cursor:pointer; flex-shrink:0; }
```

- [ ] **Step 4: Wrap status main canvas in `.ep-main-row`**

Find in `clip_cutter.html`:
```html
      <canvas id="ep-status-cursor" height="6" style="width:100%;display:block;"></canvas>
      <canvas id="ep-status-canvas" height="10" style="width:100%;display:block;cursor:pointer;border-radius:2px;background:#161b22;"></canvas>
```

Replace with:
```html
      <canvas id="ep-status-cursor" height="6" style="width:100%;display:block;"></canvas>
      <div class="ep-main-row" id="ep-status-main-row">
        <input type="radio" name="ep-status-sub-radio" id="ep-status-main-radio" class="ep-main-radio" checked>
        <canvas id="ep-status-canvas" height="10"></canvas>
      </div>
```

- [ ] **Step 5: Wrap note main canvas in `.ep-main-row`**

Find in `clip_cutter.html`:
```html
      <canvas id="ep-note-cursor" height="6" style="width:100%;display:block;"></canvas>
      <canvas id="ep-note-canvas" height="10" style="width:100%;display:block;cursor:pointer;border-radius:2px;background:#161b22;"></canvas>
```

Replace with:
```html
      <canvas id="ep-note-cursor" height="6" style="width:100%;display:block;"></canvas>
      <div class="ep-main-row" id="ep-note-main-row">
        <input type="radio" name="ep-note-sub-radio" id="ep-note-main-radio" class="ep-main-radio" checked>
        <canvas id="ep-note-canvas" height="10"></canvas>
      </div>
```

- [ ] **Step 6: Run tests to confirm pass**

```bash
python -m pytest tests/test_ui.py::test_status_main_radio_exists_and_is_checked tests/test_ui.py::test_note_main_radio_exists_and_is_checked tests/test_ui.py::test_main_row_radio_in_same_group_as_sub_rows -v
```

Expected: 3 PASSED

- [ ] **Step 7: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html clip-cutter/tests/test_ui.py
git commit -m "feat: add main-row radio button to status and note bar canvases"
```

---

## Task 2: Init empty Sets and re-check main radio in `_epBuildTagBars`

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui.py`:

```python
def test_main_canvas_starts_blank(page: Page):
    """After _epBuildTagBars, both main canvases start blank (no chip events drawn)."""
    _setup_player_with_csv(page)
    # If activeStatus is empty, _epDrawTagCanvas returns immediately without drawing.
    # Verify by checking the module-level Set sizes.
    status_size = page.evaluate("_epActiveStatus.size")
    note_size   = page.evaluate("_epActiveNote.size")
    assert status_size == 0, f"_epActiveStatus should be empty, got size {status_size}"
    assert note_size   == 0, f"_epActiveNote should be empty, got size {note_size}"
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_ui.py::test_main_canvas_starts_blank -v
```

Expected: FAILED (sizes are non-zero — currently initialized with all vals)

- [ ] **Step 3: Fix `_epBuildTagBars` to init empty Sets and check main radio**

In `enhanced_player.js`, find `_epBuildTagBars` and change:

```js
  _epActiveStatus   = new Set(statusVals);
```
to:
```js
  _epActiveStatus   = new Set();
```

And:
```js
  _epActiveNote   = new Set(noteVals);
```
to:
```js
  _epActiveNote   = new Set();
```

Also add right before `_epActiveChip = null;`:
```js
  const srMain = document.getElementById("ep-status-main-radio");
  if (srMain) srMain.checked = true;
  const nrMain = document.getElementById("ep-note-main-radio");
  if (nrMain) nrMain.checked = true;
```

- [ ] **Step 4: Run test to confirm pass**

```bash
python -m pytest tests/test_ui.py::test_main_canvas_starts_blank -v
```

Expected: PASSED

- [ ] **Step 5: Run full suite to catch regressions**

```bash
python -m pytest tests/test_ui.py -v -q
```

Expected: all pass (the old auto-create and chipVal tests will still run — they'll be replaced in Task 5)

- [ ] **Step 6: Commit**

```bash
git add clip-cutter/static/enhanced_player.js clip-cutter/tests/test_ui.py
git commit -m "feat: init tag-bar Sets empty on load, re-check main radio in _epBuildTagBars"
```

---

## Task 3: Upgrade sub-rows from `chipVal` string to `_activeChips` Set

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js`

This replaces `row.dataset.chipVal` (single chip) with `row._activeChips` (Set) on each sub-row DOM element. Also updates `_epDrawSubCanvas` to accept a Set, and `_epRedrawSubRows` to pass the Set.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui.py`:

```python
def test_sub_row_has_active_chips_set(page: Page):
    """After adding a sub-row, the DOM element has an _activeChips Set (not chipVal string)."""
    _setup_player_with_csv(page)
    page.locator("#ep-status-add-sub").click()
    result = page.evaluate("""() => {
        const row = document.querySelector('#ep-status-sub-rows .ep-sub-row');
        return row && row._activeChips instanceof Set ? row._activeChips.size : -1;
    }""")
    assert result == 0, f"Expected _activeChips Set with size 0, got {result}"
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_ui.py::test_sub_row_has_active_chips_set -v
```

Expected: FAILED (`_activeChips` is not a Set)

- [ ] **Step 3: Init `row._activeChips` in `_epAddSubRow`**

In `enhanced_player.js`, find in `_epAddSubRow`:
```js
  const row = document.createElement("div");
  row.className = "ep-sub-row";
```

Add after those two lines:
```js
  row._activeChips = new Set();
```

- [ ] **Step 4: Update sub-row canvas click to use `_activeChips`**

In `_epAddSubRow`, find the canvas click listener:
```js
  canvas.addEventListener("click", e => {
    const chipVal = row.dataset.chipVal;
    if (!chipVal) return;
    const rect = canvas.getBoundingClientRect();
    const target = Math.round((e.clientX - rect.left) / rect.width * Math.max(_frameCount - 1, 0));
    const annotated = _csvRows
      .filter(r => { const v = r[field]; return v && v === chipVal && (field !== "frame_line_status" || v !== "0"); })
      .map(r => Number(r.frame_number) - 1);
    if (!annotated.length) return;
    const nearest = annotated.reduce((a, b) => Math.abs(b - target) < Math.abs(a - target) ? b : a);
    _stop(); _epLoadFrame(nearest);
  });
```

Replace with:
```js
  canvas.addEventListener("click", e => {
    if (!row._activeChips.size) return;
    const rect = canvas.getBoundingClientRect();
    const target = Math.round((e.clientX - rect.left) / rect.width * Math.max(_frameCount - 1, 0));
    const annotated = _csvRows
      .filter(r => { const v = r[field]; return v && row._activeChips.has(v) && (field !== "frame_line_status" || v !== "0"); })
      .map(r => Number(r.frame_number) - 1);
    if (!annotated.length) return;
    const nearest = annotated.reduce((a, b) => Math.abs(b - target) < Math.abs(a - target) ? b : a);
    _stop(); _epLoadFrame(nearest);
  });
```

- [ ] **Step 5: Update `_epDrawSubCanvas` to accept a Set**

Find:
```js
function _epDrawSubCanvas(canvas, rows, field, chipVal, colorMap) {
  if (!canvas) return;
  const W = Math.round(canvas.getBoundingClientRect().width) || canvas.clientWidth || 600;
  canvas.width = W;
  const H = canvas.height || 8;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, W, H);
  if (!chipVal) return;
  const total = Math.max(_frameCount, 1);
  const minW = Math.max(1, Math.round(W / total));
  const color = colorMap[chipVal] || "#888";
  rows.forEach(row => {
    const v = row[field];
    if (!v || v !== chipVal) return;
    if (field === "frame_line_status" && v === "0") return;
    ctx.fillStyle = color;
    const x = Math.round(((row.frame_number - 1) / Math.max(total - 1, 1)) * W);
    ctx.fillRect(x, 0, minW, H);
  });
  _epDrawCanvasCursor(canvas);
}
```

Replace entirely with:
```js
function _epDrawSubCanvas(canvas, rows, field, chipSet, colorMap) {
  if (!canvas) return;
  const W = Math.round(canvas.getBoundingClientRect().width) || canvas.clientWidth || 600;
  canvas.width = W;
  const H = canvas.height || 8;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, W, H);
  if (!chipSet || chipSet.size === 0) return;
  const total = Math.max(_frameCount, 1);
  const minW = Math.max(1, Math.round(W / total));
  rows.forEach(row => {
    const v = row[field];
    if (!v || !chipSet.has(v)) return;
    if (field === "frame_line_status" && v === "0") return;
    ctx.fillStyle = colorMap[v] || "#888";
    const x = Math.round(((row.frame_number - 1) / Math.max(total - 1, 1)) * W);
    ctx.fillRect(x, 0, minW, H);
  });
  _epDrawCanvasCursor(canvas);
}
```

- [ ] **Step 6: Update `_epRedrawSubRows` to pass `row._activeChips`**

Find:
```js
function _epRedrawSubRows(containerId, field, colorMap) {
  document.querySelectorAll(`#${containerId} .ep-sub-row`).forEach(row => {
    const canvas = row.querySelector("canvas");
    if (canvas) _epDrawSubCanvas(canvas, _csvRows, field, row.dataset.chipVal || null, colorMap);
  });
}
```

Replace with:
```js
function _epRedrawSubRows(containerId, field, colorMap) {
  document.querySelectorAll(`#${containerId} .ep-sub-row`).forEach(row => {
    const canvas = row.querySelector("canvas");
    if (canvas) _epDrawSubCanvas(canvas, _csvRows, field, row._activeChips || new Set(), colorMap);
  });
}
```

- [ ] **Step 7: Run test to confirm pass**

```bash
python -m pytest tests/test_ui.py::test_sub_row_has_active_chips_set -v
```

Expected: PASSED

- [ ] **Step 8: Commit**

```bash
git add clip-cutter/static/enhanced_player.js clip-cutter/tests/test_ui.py
git commit -m "feat: replace sub-row chipVal string with _activeChips Set; update _epDrawSubCanvas"
```

---

## Task 4: Chip-click routing — main radio vs sub-row radio

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js`

Chip clicks now check which radio is selected and toggle in that timeline's Set.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui.py` (replacing the existing chip-toggle tests — delete the 6 tests added earlier: `test_chip_click_auto_creates_sub_row`, `test_chip_toggle_clears_sub_row`, `test_chip_switch_replaces_sub_row_assignment`, `test_manual_plus_then_chip_assigns_to_that_row`, `test_two_sub_rows_independent_chip_assignment`, `test_note_chip_click_auto_creates_sub_row`):

```python
def test_chip_click_on_main_radio_toggles_main_canvas(page: Page):
    """With main radio selected, clicking a chip adds it to _epActiveStatus."""
    _setup_player_with_csv(page)
    # Main radio is selected by default
    assert page.evaluate("document.getElementById('ep-status-main-radio').checked") is True
    page.locator("#ep-status-chips .ep-tag-chip", has_text="success").click()
    assert page.evaluate("_epActiveStatus.has('success')") is True
    expect(page.locator("#ep-status-chips .ep-tag-chip", has_text="success")).to_have_class(
        re.compile(r"\bactive\b")
    )

def test_chip_toggle_off_on_main_canvas(page: Page):
    """Clicking the same chip twice removes it from _epActiveStatus."""
    _setup_player_with_csv(page)
    chip = page.locator("#ep-status-chips .ep-tag-chip", has_text="success")
    chip.click()
    assert page.evaluate("_epActiveStatus.has('success')") is True
    chip.click()
    assert page.evaluate("_epActiveStatus.has('success')") is False
    expect(chip).not_to_have_class(re.compile(r"\bactive\b"))

def test_chip_click_on_sub_row_does_not_affect_main_canvas(page: Page):
    """With sub-row radio selected, chip click goes to sub-row only, not main canvas."""
    _setup_player_with_csv(page)
    page.locator("#ep-status-add-sub").click()  # sub-row radio auto-selects
    page.locator("#ep-status-chips .ep-tag-chip", has_text="success").click()
    assert page.evaluate("_epActiveStatus.has('success')") is False, \
        "Main canvas should not be affected when sub-row radio is selected"
    result = page.evaluate("""() => {
        const row = document.querySelector('#ep-status-sub-rows .ep-sub-row');
        return row._activeChips.has('success');
    }""")
    assert result is True, "Sub-row should have 'success' in its _activeChips"

def test_chip_highlight_reflects_selected_radio_timeline(page: Page):
    """Switching radio updates chip highlights to reflect that timeline's active chips."""
    _setup_player_with_csv(page)
    # Toggle 'success' on main canvas
    page.locator("#ep-status-chips .ep-tag-chip", has_text="success").click()
    # Add sub-row (auto-selects its radio) — main canvas 'success' no longer highlighted
    page.locator("#ep-status-add-sub").click()
    expect(page.locator("#ep-status-chips .ep-tag-chip", has_text="success")).not_to_have_class(
        re.compile(r"\bactive\b")
    )
    # Select main radio again — 'success' should re-appear as active
    page.evaluate("document.getElementById('ep-status-main-radio').click()")
    page.wait_for_timeout(100)
    expect(page.locator("#ep-status-chips .ep-tag-chip", has_text="success")).to_have_class(
        re.compile(r"\bactive\b")
    )

def test_two_sub_rows_hold_independent_chip_sets(page: Page):
    """Two sub-rows independently track their own active-chip Sets."""
    _setup_player_with_csv(page)
    # Sub-row 1: assign 'success'
    page.locator("#ep-status-add-sub").click()
    page.locator("#ep-status-chips .ep-tag-chip", has_text="success").click()
    # Sub-row 2: assign 'fail'
    page.locator("#ep-status-add-sub").click()
    page.locator("#ep-status-chips .ep-tag-chip", has_text="fail").click()

    result = page.evaluate("""() => {
        const rows = document.querySelectorAll('#ep-status-sub-rows .ep-sub-row');
        return {
            row0_success: rows[0]._activeChips.has('success'),
            row0_fail:    rows[0]._activeChips.has('fail'),
            row1_fail:    rows[1]._activeChips.has('fail'),
            row1_success: rows[1]._activeChips.has('success'),
        };
    }""")
    assert result["row0_success"] is True,  "Row 0 should have 'success'"
    assert result["row0_fail"]    is False, "Row 0 should NOT have 'fail'"
    assert result["row1_fail"]    is True,  "Row 1 should have 'fail'"
    assert result["row1_success"] is False, "Row 1 should NOT have 'success'"
```

- [ ] **Step 2: Run to confirm failures**

```bash
python -m pytest tests/test_ui.py::test_chip_click_on_main_radio_toggles_main_canvas tests/test_ui.py::test_chip_toggle_off_on_main_canvas tests/test_ui.py::test_chip_click_on_sub_row_does_not_affect_main_canvas tests/test_ui.py::test_chip_highlight_reflects_selected_radio_timeline tests/test_ui.py::test_two_sub_rows_hold_independent_chip_sets -v
```

Expected: all FAILED

- [ ] **Step 3: Add helper `_epGetActiveSetForBar` to `enhanced_player.js`**

Add this function immediately before `_epRenderStatusChips`:

```js
function _epGetActiveSetForBar(barType) {
  const mainRadio = document.getElementById(`ep-${barType}-main-radio`);
  if (mainRadio?.checked) return barType === "status" ? _epActiveStatus : _epActiveNote;
  const subRow = document.querySelector(`#ep-${barType}-sub-rows .ep-sub-radio:checked`)?.closest(".ep-sub-row");
  return subRow?._activeChips || new Set();
}
```

- [ ] **Step 4: Rewrite `_epRenderStatusChips`**

Replace the entire function:

```js
function _epRenderStatusChips() {
  const container = document.getElementById("ep-status-chips");
  if (!container) return;
  container.innerHTML = "";
  const activeSet = _epGetActiveSetForBar("status");
  Object.keys(_epStatusColorMap).forEach(val => {
    const chip = document.createElement("span");
    chip.className = "ep-tag-chip" + (activeSet.has(val) ? " active" : "");
    chip.textContent = val;
    chip.style.setProperty("--chip-color", _epStatusColorMap[val]);
    chip.addEventListener("click", () => {
      const mainRadio = document.getElementById("ep-status-main-radio");
      if (mainRadio?.checked) {
        if (_epActiveStatus.has(val)) {
          _epActiveStatus.delete(val);
          if (_epActiveChip?.type === "status" && _epActiveChip.val === val) _epActiveChip = null;
        } else {
          _epActiveStatus.add(val);
          _epActiveChip = { type: "status", val };
        }
        _epRedrawStatusCanvas();
      } else {
        const subRow = document.querySelector("#ep-status-sub-rows .ep-sub-radio:checked")?.closest(".ep-sub-row");
        if (!subRow) return;
        if (subRow._activeChips.has(val)) {
          subRow._activeChips.delete(val);
          if (_epActiveChip?.type === "status" && _epActiveChip.val === val) _epActiveChip = null;
        } else {
          subRow._activeChips.add(val);
          _epActiveChip = { type: "status", val };
        }
        const canvas = subRow.querySelector("canvas");
        if (canvas) _epDrawSubCanvas(canvas, _csvRows, "frame_line_status", subRow._activeChips, _epStatusColorMap);
      }
      _epRenderStatusChips();
      _epUpdateNavButtons();
    });
    container.appendChild(chip);
  });
}
```

- [ ] **Step 5: Rewrite `_epRenderNoteChips`**

Replace the entire function:

```js
function _epRenderNoteChips() {
  const container = document.getElementById("ep-note-chips");
  if (!container) return;
  container.innerHTML = "";
  const activeSet = _epGetActiveSetForBar("note");
  Object.keys(_epNoteColorMap).forEach(val => {
    const chip = document.createElement("span");
    chip.className = "ep-tag-chip" + (activeSet.has(val) ? " active" : "");
    chip.textContent = val;
    chip.style.setProperty("--chip-color", _epNoteColorMap[val]);
    chip.addEventListener("click", () => {
      const mainRadio = document.getElementById("ep-note-main-radio");
      if (mainRadio?.checked) {
        if (_epActiveNote.has(val)) {
          _epActiveNote.delete(val);
          if (_epActiveChip?.type === "note" && _epActiveChip.val === val) _epActiveChip = null;
        } else {
          _epActiveNote.add(val);
          _epActiveChip = { type: "note", val };
        }
        _epRedrawNoteCanvas();
      } else {
        const subRow = document.querySelector("#ep-note-sub-rows .ep-sub-radio:checked")?.closest(".ep-sub-row");
        if (!subRow) return;
        if (subRow._activeChips.has(val)) {
          subRow._activeChips.delete(val);
          if (_epActiveChip?.type === "note" && _epActiveChip.val === val) _epActiveChip = null;
        } else {
          subRow._activeChips.add(val);
          _epActiveChip = { type: "note", val };
        }
        const canvas = subRow.querySelector("canvas");
        if (canvas) _epDrawSubCanvas(canvas, _csvRows, "note", subRow._activeChips, _epNoteColorMap);
      }
      _epRenderNoteChips();
      _epUpdateNavButtons();
    });
    container.appendChild(chip);
  });
}
```

- [ ] **Step 6: Update sub-row `change` listener in `_epAddSubRow` to use `_activeChips`**

In `_epAddSubRow`, find the radio `change` listener:
```js
  radio.addEventListener("change", () => {
    const chipVal = row.dataset.chipVal || null;
    _epActiveChip = chipVal ? { type: barType, val: chipVal } : null;
    if (barType === "status") _epRenderStatusChips(); else _epRenderNoteChips();
    _epUpdateNavButtons();
  });
```

Replace with:
```js
  radio.addEventListener("change", () => {
    const chips = row._activeChips;
    _epActiveChip = chips.size > 0 ? { type: barType, val: [...chips][0] } : null;
    if (barType === "status") _epRenderStatusChips(); else _epRenderNoteChips();
    _epUpdateNavButtons();
  });
```

- [ ] **Step 7: Add main radio `change` listeners in `DOMContentLoaded`**

In `enhanced_player.js`, find the DOMContentLoaded handler. After the existing `ep-status-add-sub` and `ep-note-add-sub` click listeners, add:

```js
  document.getElementById("ep-status-main-radio").addEventListener("change", () => {
    _epActiveChip = _epActiveStatus.size > 0 ? { type: "status", val: [..._epActiveStatus][0] } : null;
    _epRenderStatusChips();
    _epUpdateNavButtons();
  });
  document.getElementById("ep-note-main-radio").addEventListener("change", () => {
    _epActiveChip = _epActiveNote.size > 0 ? { type: "note", val: [..._epActiveNote][0] } : null;
    _epRenderNoteChips();
    _epUpdateNavButtons();
  });
```

- [ ] **Step 8: Run new tests to confirm pass**

```bash
python -m pytest tests/test_ui.py::test_chip_click_on_main_radio_toggles_main_canvas tests/test_ui.py::test_chip_toggle_off_on_main_canvas tests/test_ui.py::test_chip_click_on_sub_row_does_not_affect_main_canvas tests/test_ui.py::test_chip_highlight_reflects_selected_radio_timeline tests/test_ui.py::test_two_sub_rows_hold_independent_chip_sets -v
```

Expected: 5 PASSED

- [ ] **Step 9: Commit**

```bash
git add clip-cutter/static/enhanced_player.js clip-cutter/tests/test_ui.py
git commit -m "feat: chip click routes to selected radio's timeline; main canvas starts blank"
```

---

## Task 5: Remove-button falls back to main radio; remove stale tests

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js`
- Modify: `clip-cutter/tests/test_ui.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui.py`:

```python
def test_remove_selected_sub_row_falls_back_to_main_radio(page: Page):
    """Removing the selected sub-row checks the main radio automatically."""
    _setup_player_with_csv(page)
    page.locator("#ep-status-add-sub").click()
    assert page.evaluate("document.getElementById('ep-status-main-radio').checked") is False
    page.locator("#ep-status-sub-rows .ep-sub-remove").click()
    assert page.evaluate("document.getElementById('ep-status-main-radio').checked") is True
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_ui.py::test_remove_selected_sub_row_falls_back_to_main_radio -v
```

Expected: FAILED

- [ ] **Step 3: Update remove button in `_epAddSubRow`**

Find the `removeBtn` click listener:
```js
  removeBtn.addEventListener("click", () => {
    row.remove();
    if (!document.querySelector(`#${containerId} .ep-sub-radio:checked`)) {
      _epActiveChip = null;
      if (barType === "status") _epRenderStatusChips(); else _epRenderNoteChips();
      _epUpdateNavButtons();
    }
  });
```

Replace with:
```js
  removeBtn.addEventListener("click", () => {
    const wasChecked = radio.checked;
    row.remove();
    if (wasChecked) {
      const mainRadio = document.getElementById(`ep-${barType}-main-radio`);
      if (mainRadio) {
        mainRadio.checked = true;
        _epActiveChip = barType === "status"
          ? (_epActiveStatus.size > 0 ? { type: "status", val: [..._epActiveStatus][0] } : null)
          : (_epActiveNote.size > 0   ? { type: "note",   val: [..._epActiveNote][0]   } : null);
        if (barType === "status") _epRenderStatusChips(); else _epRenderNoteChips();
        _epUpdateNavButtons();
      }
    }
  });
```

- [ ] **Step 4: Delete the 6 stale chip-toggle tests from `test_ui.py`**

Remove these test functions entirely (they used the old auto-create / chipVal model):
- `test_chip_click_auto_creates_sub_row`
- `test_chip_toggle_clears_sub_row`
- `test_chip_switch_replaces_sub_row_assignment`
- `test_manual_plus_then_chip_assigns_to_that_row`
- `test_two_sub_rows_independent_chip_assignment`
- `test_note_chip_click_auto_creates_sub_row`

- [ ] **Step 5: Run the new test plus the full suite**

```bash
python -m pytest tests/test_ui.py -v -q
```

Expected: all pass, no stale test failures

- [ ] **Step 6: Commit**

```bash
git add clip-cutter/static/enhanced_player.js clip-cutter/tests/test_ui.py
git commit -m "feat: remove sub-row falls back to main radio; remove stale chipVal tests"
```

---

## Task 6: Compose down/up + smoke test

- [ ] **Step 1: Restart container**

```bash
docker compose down && docker compose up -d
```

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest tests/test_ui.py -v
```

Expected: all pass

- [ ] **Step 3: Manual smoke check**

Open `http://localhost:5002/clip-cutter/` in browser. Open a clip with annotated CSV. Verify:
1. Status/Note bars visible, both main canvases blank
2. Main radio is checked; clicking a chip draws events on main canvas; clicking again clears it
3. Clicking `+` adds a sub-row, its radio auto-selects; clicking a chip draws on sub-row only
4. Switching back to main radio shows main canvas's active chips highlighted
5. `×` removes sub-row and main radio re-checks

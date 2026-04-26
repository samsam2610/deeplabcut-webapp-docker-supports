# Source Filter UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a three-button filter bar above the detection results list so the user can show only `sensor+CLIP`, only `CLIP only`, or all detections; default after each scan is `sensor+CLIP`.

**Architecture:** Pure frontend change — a `currentFilter` JS variable drives `applyFilter()` which iterates `.result-card` elements and toggles `display:none` based on `card.dataset.source`. The filter bar is HTML with three pill buttons. No backend changes.

**Tech Stack:** Vanilla JS, HTML/CSS in `clip_cutter.html` and `clip_cutter.js`.

---

## File Changes

| File | Change |
|------|--------|
| `clip-cutter/templates/clip_cutter.html` | Add `#source-filter` HTML above `#results-list`; add CSS for `.filter-btn` |
| `clip-cutter/static/clip_cutter.js` | Add `currentFilter` state, `applyFilter()`, `data-source` on cards, button wiring in DOMContentLoaded, reset after scan, apply after load |
| `clip-cutter/tests/test_ui.py` | Add Playwright tests for filter behaviour |

---

### Task 1: HTML + CSS — filter bar

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html`

The results section currently looks like this (around line 229–236):

```html
<div class="results-pane">
  <div class="results-pane-header">
    <span class="section-label">Detections</span>
    <span id="results-count"></span>
  </div>
  <div id="results-list"></div>
</div>
```

- [ ] **Step 1: Add CSS for the filter bar**

In the `<style>` block (search for `#results-count` around line 90), add after that rule:

```css
#source-filter { display: flex; gap: 6px; padding: 6px 10px 2px; }
.filter-btn { padding: 3px 10px; border-radius: 12px; border: 1px solid #30363d;
              background: #1c2128; color: #768390; font-size: 11px; cursor: pointer; }
.filter-btn.active { background: #1f6feb; border-color: #1f6feb; color: #fff; }
```

- [ ] **Step 2: Add filter bar HTML**

Insert `<div id="source-filter">` between `</div>` (closing `.results-pane-header`) and `<div id="results-list">`:

```html
<div class="results-pane-header">
  <span class="section-label">Detections</span>
  <span id="results-count"></span>
</div>
<div id="source-filter">
  <button class="filter-btn active" data-filter="sensor+clip">✓ sensor+CLIP</button>
  <button class="filter-btn" data-filter="clip_only">CLIP only</button>
  <button class="filter-btn" data-filter="all">All</button>
</div>
<div id="results-list"></div>
```

- [ ] **Step 3: Open the app and verify the bar renders**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
docker compose up -d
```

Navigate to `http://localhost:5002/clip-cutter/`. The three pill buttons should appear between the "Detections" header and the (empty) results list. The `✓ sensor+CLIP` button should be blue (active). No JS wiring yet — buttons don't do anything.

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/templates/clip_cutter.html
git commit -m "feat: add source filter bar HTML and CSS"
```

---

### Task 2: JS — filter state, applyFilter, data-source, wiring

**Files:**
- Modify: `clip-cutter/static/clip_cutter.js`

- [ ] **Step 1: Add `currentFilter` state variable**

After the existing state variables at the top of the file (after `const detections = [];`), add:

```js
let currentFilter = "sensor+clip";
```

- [ ] **Step 2: Add `applyFilter()` function**

Add this function after the `esc()` helper (before the `DOMContentLoaded` block):

```js
function applyFilter() {
  document.querySelectorAll(".result-card").forEach((card) => {
    const src = card.dataset.source || "";
    const visible =
      currentFilter === "all" ||
      (currentFilter === "sensor+clip" && src === "sensor+clip") ||
      (currentFilter === "clip_only" && src === "clip_only");
    card.style.display = visible ? "" : "none";
  });
}
```

- [ ] **Step 3: Add `data-source` to each card in `buildResultCard()`**

In `buildResultCard()`, after `card.id = \`card-${idx}\`;` (line ~378), add:

```js
card.dataset.source = d.source || "";
```

- [ ] **Step 4: Wire filter buttons in DOMContentLoaded**

Inside the `DOMContentLoaded` handler (the block starting at line 15), add after the existing threshold-slider wiring:

```js
// Source filter buttons
document.querySelectorAll(".filter-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    currentFilter = btn.dataset.filter;
    document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    applyFilter();
  });
});
```

- [ ] **Step 5: Reset filter to `sensor+clip` after scan completes**

In `listenToScan()`, find the block after `renderDetections(job.detections);` (line ~279). Add immediately after:

```js
renderDetections(job.detections);
// Reset filter to default after each scan
currentFilter = "sensor+clip";
document.querySelectorAll(".filter-btn").forEach((b) => {
  b.classList.toggle("active", b.dataset.filter === "sensor+clip");
});
applyFilter();
```

- [ ] **Step 6: Apply current filter after loading saved detections**

In `loadSavedDetections()`, find `renderDetections(data.detections);` (line ~212). Add immediately after:

```js
renderDetections(data.detections);
applyFilter();
```

- [ ] **Step 7: Verify manually**

With the container running (`docker compose up -d`), open `http://localhost:5002/clip-cutter/`. Select a video that has saved detections. The filter should apply on load — only `sensor+CLIP` cards visible by default. Clicking `All` shows all cards. Clicking `CLIP only` shows only clip-only cards.

- [ ] **Step 8: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/static/clip_cutter.js
git commit -m "feat: JS source filter — currentFilter state, applyFilter, data-source on cards"
```

---

### Task 3: Playwright tests

**Files:**
- Modify: `clip-cutter/tests/test_ui.py`

Read `tests/test_ui.py` to understand the existing fixtures (`page`, `live_server`, `setup_routes`, `_MOCK_DETECTIONS`) before adding tests.

- [ ] **Step 1: Understand the mock detection fixture**

The existing `_MOCK_DETECTIONS` list (search for it in `test_ui.py`) contains detection dicts. To test the filter, you need detections with different `source` values. Check whether `_MOCK_DETECTIONS` already has `source` fields. If not, add them — or create a local list inside the tests.

For these tests, create a module-level list at the top of the new test section:

```python
_FILTER_DETECTIONS = [
    {"frame_number": 100, "similarity": 0.90, "source": "sensor+clip",
     "known_match": None, "status": "pending"},
    {"frame_number": 200, "similarity": 0.80, "source": "clip_only",
     "known_match": None, "status": "pending"},
    {"frame_number": 300, "similarity": 0.75, "source": "sensor_only",
     "known_match": None, "status": "pending"},
]
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_ui.py`:

```python
# ── Source filter tests ───────────────────────────────────────────────────────

_FILTER_DETECTIONS = [
    {"frame_number": 100, "similarity": 0.90, "source": "sensor+clip",
     "known_match": None, "status": "pending"},
    {"frame_number": 200, "similarity": 0.80, "source": "clip_only",
     "known_match": None, "status": "pending"},
    {"frame_number": 300, "similarity": 0.75, "source": "sensor_only",
     "known_match": None, "status": "pending"},
]


def _inject_detections(page, dets):
    page.wait_for_function("typeof renderDetections === 'function'")
    page.evaluate(f"renderDetections({json.dumps(dets)})")


def test_filter_bar_visible(page, live_server):
    page.goto(f"{live_server}/clip-cutter/")
    expect(page.locator("#source-filter")).to_be_visible()


def test_filter_default_active_is_sensor_clip(page, live_server):
    page.goto(f"{live_server}/clip-cutter/")
    active = page.locator(".filter-btn.active")
    expect(active).to_have_attribute("data-filter", "sensor+clip")


def test_filter_default_hides_clip_only_cards(page, live_server):
    page.goto(f"{live_server}/clip-cutter/")
    _inject_detections(page, _FILTER_DETECTIONS)
    # sensor+clip card should be visible
    expect(page.locator(".result-card[data-source='sensor+clip']")).to_be_visible()
    # clip_only card should be hidden
    expect(page.locator(".result-card[data-source='clip_only']")).to_be_hidden()


def test_filter_all_shows_every_card(page, live_server):
    page.goto(f"{live_server}/clip-cutter/")
    _inject_detections(page, _FILTER_DETECTIONS)
    page.click(".filter-btn[data-filter='all']")
    expect(page.locator(".result-card[data-source='sensor+clip']")).to_be_visible()
    expect(page.locator(".result-card[data-source='clip_only']")).to_be_visible()
    expect(page.locator(".result-card[data-source='sensor_only']")).to_be_visible()


def test_filter_clip_only_shows_only_clip_cards(page, live_server):
    page.goto(f"{live_server}/clip-cutter/")
    _inject_detections(page, _FILTER_DETECTIONS)
    page.click(".filter-btn[data-filter='clip_only']")
    expect(page.locator(".result-card[data-source='sensor+clip']")).to_be_hidden()
    expect(page.locator(".result-card[data-source='clip_only']")).to_be_visible()
    expect(page.locator(".result-card[data-source='sensor_only']")).to_be_hidden()


def test_filter_sensor_only_cards_visible_only_in_all(page, live_server):
    page.goto(f"{live_server}/clip-cutter/")
    _inject_detections(page, _FILTER_DETECTIONS)
    # Default (sensor+clip): sensor_only hidden
    expect(page.locator(".result-card[data-source='sensor_only']")).to_be_hidden()
    # clip_only filter: sensor_only still hidden
    page.click(".filter-btn[data-filter='clip_only']")
    expect(page.locator(".result-card[data-source='sensor_only']")).to_be_hidden()
    # All: sensor_only visible
    page.click(".filter-btn[data-filter='all']")
    expect(page.locator(".result-card[data-source='sensor_only']")).to_be_visible()


def test_filter_active_button_updates_on_click(page, live_server):
    page.goto(f"{live_server}/clip-cutter/")
    page.click(".filter-btn[data-filter='all']")
    expect(page.locator(".filter-btn[data-filter='all']")).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator(".filter-btn[data-filter='sensor\\+clip']")).not_to_have_class(
        re.compile(r"\bactive\b")
    )
```

Note: `json` and `re` must be imported at the top of `test_ui.py`. Check if they're already imported; if not, add `import json` and `import re`.

- [ ] **Step 3: Run the tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_ui.py -v -k "filter" 2>&1 | tail -20
```

Expected: tests fail because `#source-filter` doesn't exist yet in the served HTML (or `applyFilter` isn't wired yet). If the container is running with live-mount, the tests should exercise the new code.

- [ ] **Step 4: Verify all filter tests pass**

After Task 1 and Task 2 are complete, re-run:

```bash
python -m pytest tests/test_ui.py -v -k "filter" 2>&1 | tail -20
```

Expected: 7 tests PASSED.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/tests/test_ui.py
git commit -m "test: Playwright tests for source filter bar"
```

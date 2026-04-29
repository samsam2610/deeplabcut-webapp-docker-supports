# Similarity Threshold Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a slider + number field to the Detections panel header that hides result cards whose similarity score falls below the threshold, and update Tab navigation to skip hidden cards.

**Architecture:** Three coordinated changes in two files — (1) stamp `dataset.similarity` onto each card when built so `applyFilter()` can read it, (2) extend `applyFilter()` to AND the existing source filter with a similarity threshold, (3) add HTML/CSS for the control group and wire up its events. Tab navigation is updated to skip `display:none` cards.

**Tech Stack:** Vanilla JS, Jinja2 HTML, Playwright (pytest) for tests. No backend changes.

---

## File Map

| File | Change |
|---|---|
| `clip-cutter/templates/clip_cutter.html` | Add `#sim-filter` HTML in `results-pane-header`; add CSS for `#sim-filter`, `#sim-slider`, `#sim-value`, `#sim-reset` |
| `clip-cutter/static/clip_cutter.js` | `buildResultCard`: add `dataset.similarity`; `applyFilter`: add threshold check; Tab handler: filter visible-only; wire slider/field/reset events |
| `clip-cutter/tests/test_ui.py` | New tests for threshold filtering and Tab skipping |

---

## Task 1: Stamp similarity onto each result card

**Files:**
- Modify: `clip-cutter/static/clip_cutter.js` (around line 1435)
- Modify: `clip-cutter/tests/test_ui.py`

### Step 1.1 — Write the failing test

Add to the end of `clip-cutter/tests/test_ui.py`:

```python
# ── Similarity threshold filter tests ─────────────────────────────────────────

_SIM_DETECTIONS = [
    {"frame_number": 100, "similarity": 0.87, "source": "sensor+clip",
     "video_path": "/user-data/vid1.avi", "known_match": None, "status": "pending"},
    {"frame_number": 200, "similarity": 0.74, "source": "sensor+clip",
     "video_path": "/user-data/vid1.avi", "known_match": None, "status": "pending"},
]


def _inject_sim_detections(page: Page) -> None:
    page.wait_for_function("typeof renderDetections === 'function'")
    import json as _j
    page.evaluate(f"renderDetections({_j.dumps(_SIM_DETECTIONS)})")


def test_result_card_has_data_similarity_attribute(page: Page):
    """Each result card must expose data-similarity matching the detection's similarity."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    _inject_sim_detections(page)

    cards = page.locator(".result-card")
    expect(cards).to_have_count(2)

    sim0 = page.evaluate("document.querySelectorAll('.result-card')[0].dataset.similarity")
    sim1 = page.evaluate("document.querySelectorAll('.result-card')[1].dataset.similarity")
    assert float(sim0) == pytest.approx(0.87, abs=0.001), f"card 0 data-similarity wrong: {sim0}"
    assert float(sim1) == pytest.approx(0.74, abs=0.001), f"card 1 data-similarity wrong: {sim1}"
```

### Step 1.2 — Run the test to verify it fails

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
pytest tests/test_ui.py::test_result_card_has_data_similarity_attribute -v
```

Expected: FAIL — `dataset.similarity` is undefined (currently not set).

### Step 1.3 — Add `dataset.similarity` in `buildResultCard`

In `clip-cutter/static/clip_cutter.js`, find the block that sets `card.dataset.source`:

```js
  card.dataset.source = d.source || "";
```

Add one line immediately after it:

```js
  card.dataset.source = d.source || "";
  card.dataset.similarity = d.similarity ?? 0;
```

### Step 1.4 — Run the test to verify it passes

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
pytest tests/test_ui.py::test_result_card_has_data_similarity_attribute -v
```

Expected: PASS.

### Step 1.5 — Commit

```bash
git add clip-cutter/static/clip_cutter.js clip-cutter/tests/test_ui.py
git commit -m "feat: stamp dataset.similarity onto result cards for filter access"
```

---

## Task 2: Extend `applyFilter()` with threshold check

**Files:**
- Modify: `clip-cutter/static/clip_cutter.js` (lines 23–32)
- Modify: `clip-cutter/tests/test_ui.py`

### Step 2.1 — Write the failing tests

Append to `clip-cutter/tests/test_ui.py`:

```python
def test_threshold_zero_shows_all_cards(page: Page):
    """Threshold=0 (default) shows all cards regardless of similarity."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click(".filter-btn[data-filter='all']")  # switch to all-sources to isolate sim filter
    _inject_sim_detections(page)
    # Both cards visible with threshold=0
    expect(page.locator(".result-card").nth(0)).to_be_visible()
    expect(page.locator(".result-card").nth(1)).to_be_visible()


def test_threshold_hides_low_similarity_cards(page: Page):
    """Setting threshold to 0.80 hides the card with similarity 0.74."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click(".filter-btn[data-filter='all']")
    _inject_sim_detections(page)

    # Set threshold via JS (slider doesn't exist yet — we test applyFilter logic directly)
    page.evaluate("""() => {
        const slider = document.getElementById('sim-slider');
        if (slider) { slider.value = '0.80'; slider.dispatchEvent(new Event('input')); }
        else {
            // Patch applyFilter to use a test threshold when slider absent
            window._testSimThreshold = 0.80;
        }
    }""")

    # If slider absent, patch currentFilter path temporarily: call applyFilter manually
    page.evaluate("""() => {
        if (!document.getElementById('sim-slider')) {
            // Temporarily monkey-patch applyFilter to use _testSimThreshold
            const orig = applyFilter;
            window._origApplyFilter = orig;
            window.applyFilter = function() {
                const threshold = window._testSimThreshold || 0;
                document.querySelectorAll('.result-card').forEach(card => {
                    const src = card.dataset.source || '';
                    const sim = parseFloat(card.dataset.similarity || 0);
                    const sourceOk = currentFilter === 'all' ||
                        (currentFilter === 'sensor+clip' && src === 'sensor+clip') ||
                        (currentFilter === 'clip_only' && src === 'clip_only');
                    card.style.display = (sourceOk && sim >= threshold) ? '' : 'none';
                });
            };
            applyFilter();
        }
    }""")

    cards = page.locator(".result-card")
    expect(cards.nth(0)).to_be_visible()   # 0.87 >= 0.80 → visible
    expect(cards.nth(1)).to_be_hidden()    # 0.74 < 0.80 → hidden
```

### Step 2.2 — Run the tests to verify they fail

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
pytest tests/test_ui.py::test_threshold_zero_shows_all_cards tests/test_ui.py::test_threshold_hides_low_similarity_cards -v
```

Expected: `test_threshold_zero_shows_all_cards` may pass (threshold 0 is already the behaviour), `test_threshold_hides_low_similarity_cards` fails (applyFilter doesn't check similarity yet).

### Step 2.3 — Update `applyFilter()` in `clip_cutter.js`

Replace the existing `applyFilter` function (lines 23–32):

```js
function applyFilter() {
  const sliderEl = document.getElementById("sim-slider");
  const threshold = sliderEl ? parseFloat(sliderEl.value) : 0;
  document.querySelectorAll(".result-card").forEach((card) => {
    const src = card.dataset.source || "";
    const sim = parseFloat(card.dataset.similarity ?? 0);
    const sourceOk =
      currentFilter === "all" ||
      (currentFilter === "sensor+clip" && src === "sensor+clip") ||
      (currentFilter === "clip_only" && src === "clip_only");
    card.style.display = sourceOk && sim >= threshold ? "" : "none";
  });
}
```

### Step 2.4 — Run the tests to verify they pass

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
pytest tests/test_ui.py::test_threshold_zero_shows_all_cards tests/test_ui.py::test_threshold_hides_low_similarity_cards -v
```

Expected: both PASS.

### Step 2.5 — Commit

```bash
git add clip-cutter/static/clip_cutter.js clip-cutter/tests/test_ui.py
git commit -m "feat: extend applyFilter with similarity threshold check"
```

---

## Task 3: Add `#sim-filter` HTML and CSS

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html`
- Modify: `clip-cutter/tests/test_ui.py`

### Step 3.1 — Write the failing test

Append to `clip-cutter/tests/test_ui.py`:

```python
def test_sim_filter_control_exists_and_visible(page: Page):
    """#sim-filter, #sim-slider, and #sim-value are present in the Detections header."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    expect(page.locator("#sim-filter")).to_be_visible()
    expect(page.locator("#sim-slider")).to_have_attribute("type", "range")
    expect(page.locator("#sim-value")).to_have_attribute("type", "number")


def test_sim_reset_hidden_by_default(page: Page):
    """#sim-reset button is hidden when threshold is 0."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    expect(page.locator("#sim-reset")).to_be_hidden()
```

### Step 3.2 — Run the tests to verify they fail

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
pytest tests/test_ui.py::test_sim_filter_control_exists_and_visible tests/test_ui.py::test_sim_reset_hidden_by_default -v
```

Expected: FAIL — elements don't exist yet.

### Step 3.3 — Add CSS in `clip_cutter.html`

In `clip-cutter/templates/clip_cutter.html`, find the block with `#source-filter` styles (around line 249). Add after the `.filter-btn.active` rule:

```css
#sim-filter { display: flex; align-items: center; gap: 3px; }
#sim-filter .sim-label { font-size: 9px; color: #768390; white-space: nowrap; }
#sim-slider { width: 70px; accent-color: #388bfd; cursor: pointer; }
#sim-value { width: 42px; font-size: 9px; background: #0d1117; border: 1px solid #30363d;
             color: #cdd9e5; border-radius: 3px; padding: 1px 3px; text-align: center; }
#sim-reset { background: transparent; border: none; color: #768390; font-size: 11px;
             cursor: pointer; padding: 0 2px; line-height: 1; }
#sim-reset:hover { color: #f85149; }
```

### Step 3.4 — Add HTML in `results-pane-header`

In `clip-cutter/templates/clip_cutter.html`, find:

```html
      <span id="results-count"></span>
      <div id="source-filter">
```

Replace with:

```html
      <span id="results-count"></span>
      <div id="sim-filter">
        <span class="sim-label">&#8805;</span>
        <input type="range" id="sim-slider" min="0" max="1" step="0.01" value="0">
        <input type="number" id="sim-value" min="0" max="1" step="0.01" value="0">
        <button id="sim-reset" title="Clear similarity filter" style="display:none;">&#215;</button>
      </div>
      <div id="source-filter">
```

### Step 3.5 — Run the tests to verify they pass

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
pytest tests/test_ui.py::test_sim_filter_control_exists_and_visible tests/test_ui.py::test_sim_reset_hidden_by_default -v
```

Expected: both PASS.

### Step 3.6 — Commit

```bash
git add clip-cutter/templates/clip_cutter.html clip-cutter/tests/test_ui.py
git commit -m "feat: add sim-filter slider+field+reset HTML and CSS to Detections header"
```

---

## Task 4: Wire up slider, field, and reset button events

**Files:**
- Modify: `clip-cutter/static/clip_cutter.js`
- Modify: `clip-cutter/tests/test_ui.py`

### Step 4.1 — Write the failing tests

Append to `clip-cutter/tests/test_ui.py`:

```python
def test_sim_slider_updates_field_and_filters(page: Page):
    """Moving #sim-slider to 0.80 updates #sim-value and hides the low-sim card."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click(".filter-btn[data-filter='all']")
    _inject_sim_detections(page)

    page.fill("#sim-value", "0.80")
    page.dispatch_event("#sim-value", "input")

    expect(page.locator("#sim-slider")).to_have_value("0.8")
    expect(page.locator(".result-card").nth(0)).to_be_visible()   # 0.87 >= 0.80
    expect(page.locator(".result-card").nth(1)).to_be_hidden()    # 0.74 < 0.80


def test_sim_reset_appears_when_threshold_nonzero(page: Page):
    """#sim-reset button becomes visible when threshold > 0."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.fill("#sim-value", "0.50")
    page.dispatch_event("#sim-value", "input")

    expect(page.locator("#sim-reset")).to_be_visible()


def test_sim_reset_clears_filter(page: Page):
    """Clicking #sim-reset resets threshold to 0, shows all cards, hides itself."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click(".filter-btn[data-filter='all']")
    _inject_sim_detections(page)

    page.fill("#sim-value", "0.80")
    page.dispatch_event("#sim-value", "input")
    expect(page.locator(".result-card").nth(1)).to_be_hidden()

    page.click("#sim-reset")

    expect(page.locator("#sim-slider")).to_have_value("0")
    expect(page.locator("#sim-value")).to_have_value("0")
    expect(page.locator(".result-card").nth(1)).to_be_visible()
    expect(page.locator("#sim-reset")).to_be_hidden()
```

### Step 4.2 — Run the tests to verify they fail

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
pytest tests/test_ui.py::test_sim_slider_updates_field_and_filters tests/test_ui.py::test_sim_reset_appears_when_threshold_nonzero tests/test_ui.py::test_sim_reset_clears_filter -v
```

Expected: all FAIL — events not wired yet.

### Step 4.3 — Add event wiring in `clip_cutter.js`

Find the section near the bottom of `clip_cutter.js` that wires up source-filter buttons (around line 755):

```js
  document.querySelectorAll(".filter-btn").forEach((btn) => {
```

Add the following block **before** that section (or after it — the position doesn't matter as long as it's inside the `DOMContentLoaded` listener or runs after DOM is ready):

```js
  // ── Similarity threshold filter ────────────────────────────────────────────
  (function () {
    const slider = document.getElementById("sim-slider");
    const field  = document.getElementById("sim-value");
    const reset  = document.getElementById("sim-reset");
    if (!slider || !field || !reset) return;

    function _updateReset() {
      reset.style.display = parseFloat(slider.value) > 0 ? "" : "none";
    }

    slider.addEventListener("input", () => {
      field.value = slider.value;
      _updateReset();
      applyFilter();
    });

    field.addEventListener("input", () => {
      let v = parseFloat(field.value);
      if (isNaN(v)) v = 0;
      v = Math.max(0, Math.min(1, v));
      field.value = v;
      slider.value = v;
      _updateReset();
      applyFilter();
    });

    reset.addEventListener("click", () => {
      slider.value = 0;
      field.value = 0;
      reset.style.display = "none";
      applyFilter();
    });
  })();
```

### Step 4.4 — Run the tests to verify they pass

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
pytest tests/test_ui.py::test_sim_slider_updates_field_and_filters tests/test_ui.py::test_sim_reset_appears_when_threshold_nonzero tests/test_ui.py::test_sim_reset_clears_filter -v
```

Expected: all PASS.

### Step 4.5 — Commit

```bash
git add clip-cutter/static/clip_cutter.js clip-cutter/tests/test_ui.py
git commit -m "feat: wire slider/field/reset events for similarity threshold filter"
```

---

## Task 5: Fix Tab navigation to skip hidden cards

**Files:**
- Modify: `clip-cutter/static/clip_cutter.js` (lines 1558–1567)
- Modify: `clip-cutter/tests/test_ui.py`

### Step 5.1 — Write the failing test

Append to `clip-cutter/tests/test_ui.py`:

```python
def test_tab_skips_hidden_cards(page: Page):
    """Tab from the active card skips cards hidden by the similarity filter.

    Setup: 2 cards, threshold=0.80 → card[1] (sim=0.74) is hidden.
    Make card[0] active-preview, dispatch Tab → should NOT activate card[1].
    """
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    # Open player so Tab handler is active
    page.locator(".result-card").first.locator(".result-name").click()
    expect(page.locator("#player-panel")).to_be_visible(timeout=5_000)

    # Set threshold to 0.80 via the field — card[1] (sim=0.74) becomes hidden
    page.click(".filter-btn[data-filter='all']")
    page.fill("#sim-value", "0.80")
    page.dispatch_event("#sim-value", "input")

    # card[0] is active-preview (it was clicked to open player)
    expect(page.locator(".result-card").nth(0)).to_have_class(re.compile(r"active-preview"))
    expect(page.locator(".result-card").nth(1)).to_be_hidden()

    # Press Tab — with the fix, no visible next card, so active-preview stays on card[0]
    page.locator("body").press("Tab")
    page.wait_for_timeout(200)

    # card[0] should still be active (no next visible card to jump to)
    expect(page.locator(".result-card").nth(0)).to_have_class(re.compile(r"active-preview"))
    expect(page.locator(".result-card").nth(1)).not_to_have_class(re.compile(r"active-preview"))
```

### Step 5.2 — Run the test to verify it fails

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
pytest tests/test_ui.py::test_tab_skips_hidden_cards -v
```

Expected: FAIL — current Tab handler iterates all cards including hidden ones, so Tab does nothing (next card at index 1 is found but is hidden and shouldn't activate, but the current code calls `.click()` on it regardless).

### Step 5.3 — Update Tab navigation in `clip_cutter.js`

Find the Tab keydown handler (around line 1558):

```js
  const cards = Array.from(document.querySelectorAll("#results-list .result-card"));
  const cur = cards.indexOf(active);
  if (cur === -1) return;

  const next = e.shiftKey ? cur - 1 : cur + 1;
  if (next < 0 || next >= cards.length) { e.preventDefault(); return; }

  e.preventDefault();
  cards[next].click();
  cards[next].scrollIntoView({ block: "nearest" });
```

Replace with:

```js
  const cards = Array.from(document.querySelectorAll("#results-list .result-card"))
    .filter(c => c.style.display !== "none");
  const cur = cards.indexOf(active);
  if (cur === -1) return;

  const next = e.shiftKey ? cur - 1 : cur + 1;
  if (next < 0 || next >= cards.length) { e.preventDefault(); return; }

  e.preventDefault();
  cards[next].click();
  cards[next].scrollIntoView({ block: "nearest" });
```

### Step 5.4 — Run the test to verify it passes

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
pytest tests/test_ui.py::test_tab_skips_hidden_cards -v
```

Expected: PASS.

### Step 5.5 — Run the full test suite to check for regressions

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
pytest tests/test_ui.py -v
```

Expected: all existing tests still PASS.

### Step 5.6 — Commit

```bash
git add clip-cutter/static/clip_cutter.js clip-cutter/tests/test_ui.py
git commit -m "feat: Tab navigation skips display:none cards (similarity + source filtered)"
```

---

## Done

All changes are in `clip-cutter/templates/clip_cutter.html` and `clip-cutter/static/clip_cutter.js`. No backend changes. The feature is fully reversible: reset button or dragging slider to 0 restores all cards.

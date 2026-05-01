# DLC-3D Per-Tile Viewer Size Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-tile size sliders next to each cam label in the Frame Labeler's sync mode, plus an Equalize button that resets all weights, plus raise the global "Viewer size" max to 500% (sync mode only).

**Architecture:** Tiles already use `flex: 1 1 0` in a flex row. We replace the "equal share" assumption with explicit `flex-grow` weights (50–300, default 100) per tile, set by per-tile range sliders. The row width is still controlled by the global slider — per-tile sliders only redistribute width *within* the row. State lives on each tile's `dataset.weight`/`style.flexGrow`; weights reset to 100 on every sync ON.

**Tech Stack:** Vanilla JS + Jinja templates + CSS (no build step). E2E tests via Playwright against the live stack at `http://localhost:5000/dlc-3d/`.

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_frame_labeler.html` — add Equalize button; restructure primary tile header
- Modify: `dlc-3D/src/static/dlc_3d.css` — header flex layout; show/hide rules for per-tile slider
- Modify: `dlc-3D/src/static/frame_labeler_3d.js` — slider wiring, Equalize handler, sync toggle changes, sibling tile markup
- Create: `dlc-3D/tests/e2e/test_per_tile_size.py` — e2e tests for the new feature

**Reference spec:** `docs/superpowers/specs/2026-05-01-dlc-3d-per-tile-viewer-size-design.md`

---

## Pre-flight

The dev stack must be running for e2e tests. The main webapp serves `http://localhost:5000/dlc-3d/` which reverse-proxies to the dlc-3d container. Rebuilding the dlc-3d module after code changes:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d && docker compose up -d dlc-3d
```

Static assets (`dlc_3d.css`, `frame_labeler_3d.js`) and templates (`card_frame_labeler.html`) are served from the dlc-3d container, so they require a rebuild. Run e2e tests from the dlc-3D module directory:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/e2e/test_per_tile_size.py -v
```

---

### Task 1: Add e2e tests (will fail until implementation lands)

**Files:**
- Create: `dlc-3D/tests/e2e/test_per_tile_size.py`

- [ ] **Step 1: Write the e2e test file**

Create `dlc-3D/tests/e2e/test_per_tile_size.py`:

```python
"""e2e tests for per-tile viewer size sliders + Equalize button + sync-mode 500% global max.

Mirrors the conftest pattern from test_sync_frame.py (autouse session activation,
om2_fixture_present skip).
"""
import re
import pytest
from playwright.sync_api import Page, expect

SESSION = "OM-2_20260424"


@pytest.fixture(autouse=True)
def _open_labeler(page: Page, base_url):
    page.goto(base_url)
    page.locator("#btn-open-frame-labeler").click()
    page.locator("#frame-labeler-card").wait_for(state="visible")
    page.wait_for_function(
        f"() => Array.from(document.getElementById('fl3d-stem-select').options)"
        f".some(o => o.value === '{SESSION}')",
        timeout=10000,
    )
    page.locator("#fl3d-stem-select").select_option(SESSION)
    page.wait_for_function(
        '() => document.querySelector("#fl3d-canvas-row .fl3d-tile")?.dataset?.fname'
    )


def _enable_sync(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")


# ---------- Group A: Visibility gating ----------

def test_a1_per_tile_sliders_hidden_when_sync_off(page: Page):
    sliders = page.locator("#fl3d-canvas-row .fl3d-tile-size")
    assert sliders.count() >= 1
    for i in range(sliders.count()):
        expect(sliders.nth(i)).to_be_hidden()


def test_a2_equalize_hidden_when_sync_off(page: Page):
    expect(page.locator("#fl3d-equalize-btn")).to_be_hidden()


def test_a3_per_tile_sliders_visible_when_sync_on(page: Page):
    _enable_sync(page)
    sliders = page.locator("#fl3d-canvas-row .fl3d-tile-size")
    cam_count = page.evaluate("window.__fl3d.camSet.length")
    assert sliders.count() == cam_count
    for i in range(sliders.count()):
        expect(sliders.nth(i)).to_be_visible()


def test_a4_equalize_visible_when_sync_on(page: Page):
    _enable_sync(page)
    expect(page.locator("#fl3d-equalize-btn")).to_be_visible()


# ---------- Group B: Global slider max ----------

def test_b1_global_max_300_when_sync_off(page: Page):
    assert page.eval_on_selector("#fl3d-zoom", "el => el.max") == "300"


def test_b2_global_max_500_when_sync_on(page: Page):
    _enable_sync(page)
    assert page.eval_on_selector("#fl3d-zoom", "el => el.max") == "500"


def test_b3_global_value_clamped_when_sync_off(page: Page):
    _enable_sync(page)
    page.locator("#fl3d-zoom").evaluate(
        "(el) => { el.value = '450'; el.dispatchEvent(new Event('input')); }"
    )
    page.locator("#fl3d-sync-frame").uncheck()
    page.wait_for_function("window.__fl3d.syncOn === false")
    assert page.eval_on_selector("#fl3d-zoom", "el => el.max") == "300"
    assert int(page.eval_on_selector("#fl3d-zoom", "el => el.value")) <= 300


# ---------- Group C: Per-tile weight redistribution ----------

def test_c1_default_weights_equal(page: Page):
    _enable_sync(page)
    weights = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile",
        "tiles => tiles.map(t => parseInt(t.style.flexGrow || t.dataset.weight || '100', 10))",
    )
    assert all(w == 100 for w in weights), f"expected all 100, got {weights}"


def test_c2_drag_one_slider_grows_that_tile(page: Page):
    _enable_sync(page)
    tiles = page.locator("#fl3d-canvas-row .fl3d-tile")
    n = tiles.count()
    assert n >= 2

    widths_before = [
        tiles.nth(i).evaluate("el => el.getBoundingClientRect().width") for i in range(n)
    ]

    # Drag tile 0's slider to 300
    tiles.nth(0).locator(".fl3d-tile-size").evaluate(
        "(el) => { el.value = '300'; el.dispatchEvent(new Event('input')); }"
    )

    widths_after = [
        tiles.nth(i).evaluate("el => el.getBoundingClientRect().width") for i in range(n)
    ]
    assert widths_after[0] > widths_before[0], "tile 0 should grow"
    for i in range(1, n):
        assert widths_after[i] < widths_before[i], f"tile {i} should shrink"


def test_c3_row_width_unchanged_when_redistributing(page: Page):
    _enable_sync(page)
    row = page.locator("#fl3d-canvas-row")
    row_w_before = row.evaluate("el => el.getBoundingClientRect().width")
    page.locator("#fl3d-canvas-row .fl3d-tile").first.locator(".fl3d-tile-size").evaluate(
        "(el) => { el.value = '250'; el.dispatchEvent(new Event('input')); }"
    )
    row_w_after = row.evaluate("el => el.getBoundingClientRect().width")
    # Row width may shift by sub-pixel rounding; assert within 2px.
    assert abs(row_w_after - row_w_before) <= 2


def test_c4_slider_label_updates(page: Page):
    _enable_sync(page)
    tile = page.locator("#fl3d-canvas-row .fl3d-tile").first
    tile.locator(".fl3d-tile-size").evaluate(
        "(el) => { el.value = '175'; el.dispatchEvent(new Event('input')); }"
    )
    label_text = tile.locator(".fl3d-tile-size-val").inner_text()
    assert label_text.strip() == "175%"


# ---------- Group D: Equalize ----------

def test_d1_equalize_resets_all_weights(page: Page):
    _enable_sync(page)
    tiles = page.locator("#fl3d-canvas-row .fl3d-tile")
    # Skew weights
    tiles.nth(0).locator(".fl3d-tile-size").evaluate(
        "(el) => { el.value = '300'; el.dispatchEvent(new Event('input')); }"
    )
    page.locator("#fl3d-equalize-btn").click()
    weights = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile",
        "tiles => tiles.map(t => parseInt(t.style.flexGrow, 10))",
    )
    assert all(w == 100 for w in weights), f"expected all 100, got {weights}"
    sliders_vals = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile-size",
        "els => els.map(e => parseInt(e.value, 10))",
    )
    assert all(v == 100 for v in sliders_vals)


# ---------- Group E: Sync toggle resets weights ----------

def test_e1_sync_off_then_on_resets_weights(page: Page):
    _enable_sync(page)
    page.locator("#fl3d-canvas-row .fl3d-tile").first.locator(".fl3d-tile-size").evaluate(
        "(el) => { el.value = '275'; el.dispatchEvent(new Event('input')); }"
    )
    page.locator("#fl3d-sync-frame").uncheck()
    page.wait_for_function("window.__fl3d.syncOn === false")
    _enable_sync(page)
    weights = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile",
        "tiles => tiles.map(t => parseInt(t.style.flexGrow || '100', 10))",
    )
    assert all(w == 100 for w in weights), f"expected all 100 after sync re-enable, got {weights}"


# ---------- Group F: Marker placement still works after resize ----------

def test_f1_click_focused_tile_at_300pct_places_marker(page: Page):
    _enable_sync(page)
    # Pick first body part chip
    page.wait_for_function("document.querySelectorAll('#fl3d-bodypart-list .fl-bp-chip').length > 0")
    page.locator("#fl3d-bodypart-list .fl-bp-chip").first.click()
    bp = page.evaluate("window.__fl3d.selectedBp")
    assert bp

    # Resize the focused (primary) tile to 300%
    primary = page.locator("#fl3d-canvas-row .fl3d-tile.focused")
    primary.locator(".fl3d-tile-size").evaluate(
        "(el) => { el.value = '300'; el.dispatchEvent(new Event('input')); }"
    )

    # Click center of focused canvas
    canvas = primary.locator("canvas.fl3d-tile-canvas")
    box = canvas.bounding_box()
    assert box
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    primary_fname = primary.evaluate("t => t.dataset.fname")
    page.wait_for_function(
        f"window.__fl3d.dirtyFrames.includes('{primary_fname}')"
    )
```

- [ ] **Step 2: Verify the test file collects (without running)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/e2e/test_per_tile_size.py --collect-only -q
```

Expected: 12 tests collected, no errors.

- [ ] **Step 3: Run the tests against current code**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/e2e/test_per_tile_size.py -v
```

Expected: most tests **fail** (per-tile sliders, equalize button, and 500% max don't exist yet). `test_b1_global_max_300_when_sync_off` may pass (existing slider already has max=300). This is the failing-test baseline.

- [ ] **Step 4: Commit the failing tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/tests/e2e/test_per_tile_size.py
git commit -m "test(dlc-3d): e2e tests for per-tile viewer size + equalize"
```

---

### Task 2: HTML — Equalize button + primary tile header restructure

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_frame_labeler.html` (lines 224–253 — controls bar and canvas row)

- [ ] **Step 1: Add the Equalize button to the controls bar**

In `card_frame_labeler.html`, find the existing `Viewer size` label block (around line 225-229):

```html
          <label style="display:flex;align-items:center;gap:.45rem;font-size:.78rem;color:var(--text-dim);white-space:nowrap">
            Viewer size
            <input type="range" id="fl3d-zoom" min="50" max="300" value="100" step="25" style="width:80px;accent-color:var(--accent)">
            <span id="fl3d-zoom-val" style="min-width:2.5rem;text-align:right;color:var(--text)">100 %</span>
          </label>
```

Insert this button **immediately after** the closing `</label>` of that block:

```html
          <button id="fl3d-equalize-btn" class="btn-sm hidden" title="Reset all per-camera viewer sizes to equal" style="font-size:.75rem;padding:.2rem .55rem">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
            Equalize
          </button>
```

- [ ] **Step 2: Replace the primary tile's `tile-label` div with a header**

Find (around line 247-252):

```html
          <div class="fl3d-tile focused" data-cam="" data-fname="">
            <div class="fl3d-tile-label" id="fl3d-tile-label-primary"></div>
            <canvas id="fl3d-canvas" class="fl3d-tile-canvas" data-cam="" data-fname=""></canvas>
            <div class="fl3d-tile-empty hidden" id="fl3d-tile-empty-primary"></div>
            <p class="fl-canvas-empty hidden" id="fl3d-canvas-loading">Loading frame…</p>
          </div>
```

Replace with:

```html
          <div class="fl3d-tile focused" data-cam="" data-fname="" data-weight="100" style="flex-grow:100">
            <div class="fl3d-tile-header">
              <span class="fl3d-tile-label" id="fl3d-tile-label-primary"></span>
              <input type="range" class="fl3d-tile-size" min="50" max="300" step="25" value="100">
              <span class="fl3d-tile-size-val">100%</span>
            </div>
            <canvas id="fl3d-canvas" class="fl3d-tile-canvas" data-cam="" data-fname=""></canvas>
            <div class="fl3d-tile-empty hidden" id="fl3d-tile-empty-primary"></div>
            <p class="fl-canvas-empty hidden" id="fl3d-canvas-loading">Loading frame…</p>
          </div>
```

- [ ] **Step 3: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/partials/card_frame_labeler.html
git commit -m "feat(dlc-3d): add equalize button + primary tile header markup"
```

---

### Task 3: CSS — header flex layout + show/hide rules

**Files:**
- Modify: `dlc-3D/src/static/dlc_3d.css` (around lines 144–186, the frame-labeler tile section)

- [ ] **Step 1: Edit the tile-label rule and add header + slider styles**

Find:

```css
.fl3d-tile-label {
  font-size: .7rem;
  color: var(--text-dim);
  margin-bottom: 2px;
  font-family: var(--mono);
}
```

Replace with:

```css
.fl3d-tile-header {
  display: flex;
  align-items: center;
  gap: .35rem;
  margin-bottom: 2px;
}
.fl3d-tile-label {
  font-size: .7rem;
  color: var(--text-dim);
  font-family: var(--mono);
}
.fl3d-tile-size {
  width: 70px;
  accent-color: var(--accent);
}
.fl3d-tile-size-val {
  font-size: .7rem;
  color: var(--text);
  min-width: 2.6rem;
  text-align: right;
}
.fl3d-tile-size,
.fl3d-tile-size-val {
  display: none;
}
.fl3d-canvas-row.sync-on .fl3d-tile-size,
.fl3d-canvas-row.sync-on .fl3d-tile-size-val {
  display: inline-block;
}
```

- [ ] **Step 2: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/dlc_3d.css
git commit -m "style(dlc-3d): tile header flex layout + per-tile slider show/hide"
```

---

### Task 4: JS — primary tile slider wiring + Equalize handler

**Files:**
- Modify: `dlc-3D/src/static/frame_labeler_3d.js` (insert after the existing `flZoomInput` block around line 646)

- [ ] **Step 1: Add a helper that wires a per-tile slider**

Insert this function near the other `_fl3d…` helpers — a good spot is just below the `_fl3dRenderTile` function (around line 1054, before its `if (tile.classList.contains("fl3d-tile-sibling"))` block exits scope). Place the helper at the **module level** of the IIFE (alongside the other functions like `_fl3dDrawTileMarkers`). For concreteness, insert immediately after the `_fl3dFitRow` function (around line 1248):

```js
function _fl3dWireTileSizeSlider(tile) {
  const slider = tile.querySelector(".fl3d-tile-size");
  const val    = tile.querySelector(".fl3d-tile-size-val");
  if (!slider || slider.dataset.wired === "1") return;
  slider.dataset.wired = "1";
  slider.addEventListener("input", () => {
    const w = parseInt(slider.value, 10);
    tile.dataset.weight = String(w);
    tile.style.flexGrow = String(w);
    val.textContent = w + "%";
    if (tile.dataset.fname) _fl3dDrawTileMarkers(tile, tile.dataset.fname);
  });
}

function _fl3dResetTileWeight(tile) {
  const slider = tile.querySelector(".fl3d-tile-size");
  const val    = tile.querySelector(".fl3d-tile-size-val");
  tile.dataset.weight = "100";
  tile.style.flexGrow = "100";
  if (slider) slider.value = "100";
  if (val) val.textContent = "100%";
}
```

- [ ] **Step 2: Wire the primary tile's slider once at startup**

Find the existing `flZoomInput.addEventListener` block (line 642-646):

```js
    flZoomInput.addEventListener("input", () => {
      _flZoom = parseInt(flZoomInput.value, 10);
      flZoomVal.textContent = _flZoom + " %";
      if (_flImgLoaded) { _flFitCanvas(); _flDraw(); }
    });
```

**Immediately after** this block, add:

```js
    // Wire primary tile's size slider once. Sibling-tile sliders are wired in _fl3dRenderTile.
    const _flPrimaryTile = document.querySelector("#fl3d-canvas-row .fl3d-tile:not(.fl3d-tile-sibling)");
    if (_flPrimaryTile) _fl3dWireTileSizeSlider(_flPrimaryTile);

    // Equalize button: reset all per-tile weights to 100.
    const flEqualizeBtn = document.getElementById("fl3d-equalize-btn");
    flEqualizeBtn.addEventListener("click", () => {
      document.querySelectorAll("#fl3d-canvas-row .fl3d-tile").forEach(t => {
        _fl3dResetTileWeight(t);
        if (t.dataset.fname) _fl3dDrawTileMarkers(t, t.dataset.fname);
      });
    });
```

- [ ] **Step 3: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/frame_labeler_3d.js
git commit -m "feat(dlc-3d): wire primary tile size slider + equalize handler"
```

---

### Task 5: JS — sibling tile slider markup + sync toggle (max + show/hide + reset)

**Files:**
- Modify: `dlc-3D/src/static/frame_labeler_3d.js` — sibling tile innerHTML in `_fl3dSyncRenderRow` (around line 1005), `_fl3dRenderTile` post-init (around line 1054), and the `fl3d-sync-frame` change handler (around line 674-701)

- [ ] **Step 1: Update sibling tile innerHTML to include header + slider**

Find (around line 1002-1009):

```js
        const tile = document.createElement("div");
        tile.className = "fl3d-tile fl3d-tile-sibling";
        tile.dataset.cam = String(cam);
        tile.innerHTML = `
          <div class="fl3d-tile-label">cam${cam}</div>
          <canvas class="fl3d-tile-canvas" data-cam="${cam}"></canvas>
          <div class="fl3d-tile-empty hidden"></div>
        `;
        row.appendChild(tile);
        _fl3dRenderTile(tile, cam, byCam.get(cam) || null, currentFrameNum);
```

Replace with:

```js
        const tile = document.createElement("div");
        tile.className = "fl3d-tile fl3d-tile-sibling";
        tile.dataset.cam = String(cam);
        tile.dataset.weight = "100";
        tile.style.flexGrow = "100";
        tile.innerHTML = `
          <div class="fl3d-tile-header">
            <span class="fl3d-tile-label">cam${cam}</span>
            <input type="range" class="fl3d-tile-size" min="50" max="300" step="25" value="100">
            <span class="fl3d-tile-size-val">100%</span>
          </div>
          <canvas class="fl3d-tile-canvas" data-cam="${cam}"></canvas>
          <div class="fl3d-tile-empty hidden"></div>
        `;
        row.appendChild(tile);
        _fl3dRenderTile(tile, cam, byCam.get(cam) || null, currentFrameNum);
```

- [ ] **Step 2: Wire sibling tile slider in `_fl3dRenderTile`**

Find the start of the sibling-only branch in `_fl3dRenderTile` (around line 1057):

```js
      // ── Sibling-tile input listeners ──────────────────────────────
      // Only attach to sibling tiles; the primary tile's listeners are attached
      // once at startup above to prevent accumulation across re-renders.
      if (tile.classList.contains("fl3d-tile-sibling")) {
```

**Inside this `if` block**, immediately after the opening brace, add:

```js
        // Per-tile size slider — sibling header was just (re)built, wire its input listener
        _fl3dWireTileSizeSlider(tile);
```

- [ ] **Step 3: Update sync toggle handler — slider max + show/hide + primary weight reset**

Find the `fl3d-sync-frame` change handler (lines 674-701):

```js
    document.getElementById("fl3d-sync-frame").addEventListener("change", (e) => {
      if (e.target.checked) {
        if (_fl3dCamSet.length < 2) {
          e.target.checked = false;
          flStemStatus.textContent = "Sync Frame needs at least 2 cams in this folder.";
          return;
        }
        // Determine current cam + frame from current fname
        const fname = _flFrames[_flFrameIdx];
        const m = FL3D_FRAME_RE.exec(fname || "");
        if (!m) { e.target.checked = false; return; }
        _fl3dPrimaryCam = +m[1];
        _fl3dFocusedCam = _fl3dPrimaryCam;
        const currentFrameNum = +m[3];
        _fl3dFrameNumIdx = _fl3dFrameNumbers.indexOf(currentFrameNum);
        if (_fl3dFrameNumIdx < 0) _fl3dFrameNumIdx = 0;
        _fl3dSyncOn = true;
        _flShowFrame(_fl3dFrameNumIdx);
      } else {
        // Capture focused fname while sync is still on
        const focusedFname = _fl3dActiveFname();
        _fl3dSyncOn = false;
        document.querySelectorAll("#fl3d-canvas-row .fl3d-tile-sibling").forEach(t => t.remove());
        const idx = _flFrames.indexOf(focusedFname);
        if (idx >= 0) _flFrameIdx = idx;
        _flShowFrame(_flFrameIdx);
      }
    });
```

Replace with:

```js
    document.getElementById("fl3d-sync-frame").addEventListener("change", (e) => {
      const row = document.getElementById("fl3d-canvas-row");
      if (e.target.checked) {
        if (_fl3dCamSet.length < 2) {
          e.target.checked = false;
          flStemStatus.textContent = "Sync Frame needs at least 2 cams in this folder.";
          return;
        }
        // Determine current cam + frame from current fname
        const fname = _flFrames[_flFrameIdx];
        const m = FL3D_FRAME_RE.exec(fname || "");
        if (!m) { e.target.checked = false; return; }
        _fl3dPrimaryCam = +m[1];
        _fl3dFocusedCam = _fl3dPrimaryCam;
        const currentFrameNum = +m[3];
        _fl3dFrameNumIdx = _fl3dFrameNumbers.indexOf(currentFrameNum);
        if (_fl3dFrameNumIdx < 0) _fl3dFrameNumIdx = 0;
        _fl3dSyncOn = true;
        // Sync ON: bump global slider max to 500, reveal per-tile sliders + equalize.
        flZoomInput.max = "500";
        row.classList.add("sync-on");
        flEqualizeBtn.classList.remove("hidden");
        // Reset primary tile's weight for a clean state on each sync ON.
        const primaryTile = row.querySelector(".fl3d-tile:not(.fl3d-tile-sibling)");
        if (primaryTile) _fl3dResetTileWeight(primaryTile);
        _flShowFrame(_fl3dFrameNumIdx);
      } else {
        // Capture focused fname while sync is still on
        const focusedFname = _fl3dActiveFname();
        _fl3dSyncOn = false;
        row.querySelectorAll(".fl3d-tile-sibling").forEach(t => t.remove());
        // Sync OFF: cap global slider at 300, hide per-tile sliders + equalize, clamp value.
        flZoomInput.max = "300";
        if (parseInt(flZoomInput.value, 10) > 300) {
          flZoomInput.value = "300";
          _flZoom = 300;
          flZoomVal.textContent = "300 %";
        }
        row.classList.remove("sync-on");
        flEqualizeBtn.classList.add("hidden");
        // Reset primary tile's weight so single-tile mode is unaffected.
        const primaryTile = row.querySelector(".fl3d-tile:not(.fl3d-tile-sibling)");
        if (primaryTile) _fl3dResetTileWeight(primaryTile);
        const idx = _flFrames.indexOf(focusedFname);
        if (idx >= 0) _flFrameIdx = idx;
        _flShowFrame(_flFrameIdx);
      }
    });
```

Note: this handler now references `flEqualizeBtn` (declared in Task 4 Step 2) and `flZoomVal` (declared at line 640). Both are in the same IIFE scope. Ordering note — the const `flEqualizeBtn` is declared just below this handler in the source order from Task 4. JavaScript's `let`/`const` are not hoisted, **but** this is fine because the handler body only runs on user interaction (well after IIFE init completes), at which point `flEqualizeBtn` is defined. If you want belt-and-suspenders, move the `const flEqualizeBtn = …` line to be declared **above** this `addEventListener("change", …)` block — both work.

- [ ] **Step 4: Rebuild + run e2e tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d && docker compose up -d dlc-3d
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/e2e/test_per_tile_size.py -v
```

Expected: all 12 tests **pass**.

If `test_c3_row_width_unchanged_when_redistributing` fails by more than 2px, the row width is being recomputed somewhere — most likely a stray `_flFitCanvas`/`_fl3dFitRow` call inside the slider input handler. There shouldn't be one (the helper from Task 4 only redraws markers).

If `test_f1_click_focused_tile_at_300pct_places_marker` fails, the click→image scale is being miscomputed at non-uniform tile widths. The existing `_fl3dCanvasClickToImage` uses `getBoundingClientRect()` which already accounts for the displayed canvas width — re-check it wasn't accidentally changed.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/frame_labeler_3d.js
git commit -m "feat(dlc-3d): per-tile size sliders + 500% sync zoom + equalize"
```

---

### Task 6: Verification — full sync-frame test suite + smoke

**Files:** none

- [ ] **Step 1: Run the existing sync-frame test suite to confirm no regressions**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/e2e/test_sync_frame.py -v
```

Expected: all previously-passing tests still pass. Pay attention to:
- Group G (zoom 200% breakout, marker size, show names) — these touch the same controls bar
- Group H (save round-trip) — only runs with `FL3D_E2E_WRITE=1`; skip OK
- Group J (sync OFF transition) — confirms the cleanup we extended works

- [ ] **Step 2: Manual smoke in the browser**

Open `http://localhost:5000/dlc-3d/` in a browser. With Frame Labeler open and a multi-cam stem selected:

1. Toggle **Sync Frame** ON → per-tile sliders appear next to each `cam` label, Equalize button visible, global slider's max moves up (drag past 300%).
2. Drag global to 500% → row spans wider than 300%; tiles still equal-width.
3. Drag tile 0's per-tile slider to 300% → that tile grows, other tile(s) shrink, row width unchanged.
4. Click **Equalize** → all tiles back to equal.
5. Skew weights again; toggle Sync Frame OFF → single tile shown; toggle ON → weights back to 100 (verify by inspecting `tile.style.flexGrow` in devtools).
6. With sync OFF, drag global slider — max is 300% again. With sync ON at 500%, then sync OFF: global slider value snaps to 300%.
7. Click on the focused tile after resizing it to 300% → marker lands at the right pixel.

- [ ] **Step 3: Commit nothing (verification only)**

If both Step 1 and Step 2 are clean, the feature is done.

---

## Self-Review Notes

- **Spec coverage:** Each spec section maps to a task. UI changes (Task 2, 3); JS state and slider wiring (Task 4, 5); 500% sync max (Task 5 step 3); reset on sync ON (Task 5 step 3); sync OFF cleanup including value clamping (Task 5 step 3); hit-test (no change needed — verified in Task 1 group F + manual smoke).
- **Out of scope (per spec):** persistence across reloads, per-tile sliders in single-tile mode, drag-to-resize between tiles. None added.
- **Type/signature consistency:** `_fl3dWireTileSizeSlider` and `_fl3dResetTileWeight` are referenced from three places (primary init, sibling render, equalize, sync toggle); definitions and call sites match.
- **Names sanity:** `fl3d-equalize-btn`, `fl3d-tile-header`, `fl3d-tile-size`, `fl3d-tile-size-val`, `sync-on` (row class) used consistently across HTML, CSS, JS, and tests.

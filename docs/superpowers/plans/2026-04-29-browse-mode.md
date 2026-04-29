# Browse Mode + KF Row Refactor + Note Palette Scroll — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Browse" button to the Detections header that lets users extract manual clips from a selected video without scanning; also split the Propagate KF checkbox into two, and cap the note palette height.

**Architecture:** Three independent UI changes touching `clip_cutter.html`, `clip_cutter.js`, and `enhanced_player.js`. The browse feature adds an `unlocked` parameter to `openPlayer()` and a `_browseMode` flag that routes every extract call to create a new detection entry instead of updating an existing one.

**Tech Stack:** Vanilla JS, Jinja2 HTML templates, Playwright (pytest) for UI tests.

---

## File Map

| File | Changes |
|---|---|
| `clip-cutter/templates/clip_cutter.html` | Add `#detections-browse-btn` button + CSS; refactor `#ep-propagate-row` HTML; add `#ep-note-palette` scroll CSS |
| `clip-cutter/static/clip_cutter.js` | Enable/disable browse button on video select; wire browse button click → `openPlayer` with `unlocked:true` |
| `clip-cutter/static/enhanced_player.js` | `openPlayer()` `unlocked` param; `_browseMode` flag; Set KF free-mode path; Extract free-mode path; `_epUpdateModeUI()` propagate-row always-visible |
| `clip-cutter/tests/test_ui.py` | New tests for browse button state, propagate row always-visible, note palette scroll, set-kf free-mode, extract free-mode |

---

## Task 1: Note Palette Scroll (CSS only)

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html` (line ~997 — `#ep-note-palette` div)

**Context:** `#ep-note-palette` currently has `display:flex;gap:4px;flex-wrap:wrap;min-height:18px;` with no max-height. We need `max-height:72px;overflow-y:auto;` added inline.

- [ ] **Step 1: Write the failing test**

Add this test to `clip-cutter/tests/test_ui.py`, after the last `test_tab_skips_hidden_cards` test:

```python
def test_note_palette_has_scroll_limit(page: Page):
    """#ep-note-palette must have max-height: 72px and overflow-y: auto."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    max_h = page.evaluate(
        "getComputedStyle(document.getElementById('ep-note-palette')).maxHeight"
    )
    overflow = page.evaluate(
        "getComputedStyle(document.getElementById('ep-note-palette')).overflowY"
    )
    assert max_h == "72px", f"max-height wrong: {max_h}"
    assert overflow == "auto", f"overflow-y wrong: {overflow}"
```

- [ ] **Step 2: Run to confirm it fails**

```
cd clip-cutter
pytest tests/test_ui.py::test_note_palette_has_scroll_limit -v
```

Expected: FAIL — `max-height wrong: none`

- [ ] **Step 3: Apply the CSS**

In `clip-cutter/templates/clip_cutter.html`, find line ~997:

```html
        <div id="ep-note-palette" style="display:flex;gap:4px;flex-wrap:wrap;min-height:18px;"></div>
```

Change to:

```html
        <div id="ep-note-palette" style="display:flex;gap:4px;flex-wrap:wrap;min-height:18px;max-height:72px;overflow-y:auto;"></div>
```

- [ ] **Step 4: Run to confirm it passes**

```
cd clip-cutter
pytest tests/test_ui.py::test_note_palette_has_scroll_limit -v
```

Expected: PASS

- [ ] **Step 5: Run full suite to check for regressions**

```
cd clip-cutter
pytest tests/test_ui.py -v
```

Expected: all tests pass (was 86 + 1 new = 87)

- [ ] **Step 6: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html clip-cutter/tests/test_ui.py
git commit -m "feat: cap note palette height at 72px with scroll"
```

---

## Task 2: Propagate KF Row Refactor

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html` (lines ~1010–1014 — `#ep-propagate-row`)
- Modify: `clip-cutter/static/enhanced_player.js` (lines ~963–975 — `_epUpdateModeUI()` propagate-row mode-gating; line ~1053 — `_epApplyNewKF` propagate check)

**Context:**
- Current propagate-row HTML (lines 1010–1014): single `ep-propagate-kf` checkbox (checked by default), hidden in non-clip modes via `_epUpdateModeUI()`.
- `_epUpdateModeUI()` clip-mode branch (line 964): `propagateRow.style.display = "flex"`. Non-clip branch (line 975): `propagateRow.style.display = "none"`.
- `_epApplyNewKF()` line 1053: `if (document.getElementById("ep-propagate-kf")?.checked)` — this stays unchanged but the element ID changes to `ep-propagate-kf` (same name, no change needed here).
- New: `ep-add-kf-to-template` (checked by default). When Set KF is pressed with `_detectionIdx !== null` and `ep-add-kf-to-template` is checked, call `addToTemplate(_videoPath, kf1)` after `_epApplyNewKF`.

- [ ] **Step 1: Write the failing tests**

Add these tests to `clip-cutter/tests/test_ui.py` after `test_note_palette_has_scroll_limit`:

```python
def test_propagate_row_always_visible_in_clip_mode(page: Page):
    """#ep-propagate-row must be flex in clip mode (player opened via detection card)."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    # Trigger a scan so detection cards appear
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.wait_for_selector("#scan-btn:not([disabled])")
    page.click("#scan-btn")
    page.wait_for_selector(".result-card", timeout=5000)
    # Open player via keep button (simulated via JS to avoid real video endpoint)
    page.evaluate("""() => {
        openPlayer({ mode: 'clip', videoPath: '/user-data/vid1.avi',
                     keyFrame1Based: 201, detectionIdx: 0 });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    display = page.evaluate(
        "document.getElementById('ep-propagate-row').style.display"
    )
    assert display == "flex", f"propagate-row display in clip mode: {display}"


def test_propagate_row_visible_in_template_mode(page: Page):
    """#ep-propagate-row must NOT be hidden in template/non-clip mode."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.wait_for_selector("#sidebar-browse-btn:not([disabled])", timeout=3000)
    # Open template browse mode
    page.evaluate("""() => {
        openPlayer({ mode: 'template', videoPath: '/user-data/vid1.avi' });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    display = page.evaluate(
        "document.getElementById('ep-propagate-row').style.display"
    )
    assert display != "none", f"propagate-row hidden in template mode: {display}"


def test_propagate_row_has_two_checkboxes(page: Page):
    """#ep-propagate-row must contain ep-add-kf-to-template (checked) and ep-propagate-kf (unchecked)."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    add_kf_checked = page.evaluate(
        "document.getElementById('ep-add-kf-to-template').checked"
    )
    propagate_checked = page.evaluate(
        "document.getElementById('ep-propagate-kf').checked"
    )
    assert add_kf_checked is True, "ep-add-kf-to-template should be checked by default"
    assert propagate_checked is False, "ep-propagate-kf should be unchecked by default"
```

- [ ] **Step 2: Run to confirm they fail**

```
cd clip-cutter
pytest tests/test_ui.py::test_propagate_row_has_two_checkboxes -v
```

Expected: FAIL — `ep-add-kf-to-template` element not found

- [ ] **Step 3: Rewrite `#ep-propagate-row` HTML**

In `clip-cutter/templates/clip_cutter.html`, replace the propagate-row block (lines ~1010–1014):

```html
    <!-- Propagate KF — shown in clip mode only -->
    <div id="ep-propagate-row" style="display:none;align-items:center;gap:6px;padding:3px 4px;margin-bottom:2px;">
      <input type="checkbox" id="ep-propagate-kf" checked style="accent-color:#388bfd;cursor:pointer;flex-shrink:0;">
      <label for="ep-propagate-kf" style="font-size:10px;color:#adbac7;cursor:pointer;flex:1;">↻ Propagate KF</label>
    </div>
```

With:

```html
    <!-- KF options — always visible -->
    <div id="ep-propagate-row" style="display:flex;align-items:center;gap:10px;padding:3px 4px;margin-bottom:2px;">
      <label style="display:flex;align-items:center;gap:4px;font-size:10px;color:#adbac7;cursor:pointer;">
        <input type="checkbox" id="ep-add-kf-to-template" checked style="accent-color:#388bfd;cursor:pointer;">
        add KF to template
      </label>
      <label style="display:flex;align-items:center;gap:4px;font-size:10px;color:#adbac7;cursor:pointer;">
        <input type="checkbox" id="ep-propagate-kf" style="accent-color:#388bfd;cursor:pointer;">
        propagate
      </label>
    </div>
```

- [ ] **Step 4: Remove propagate-row mode-gating from `_epUpdateModeUI()`**

In `clip-cutter/static/enhanced_player.js`, find the clip-mode branch in `_epUpdateModeUI()` (around line 963):

```js
    const propagateRow = document.getElementById("ep-propagate-row");
    if (propagateRow) propagateRow.style.display = "flex";
```

Delete those two lines (they're inside the `if (_mode === "clip")` block).

Then find the non-clip branch (around line 974):

```js
    const propagateRow = document.getElementById("ep-propagate-row");
    if (propagateRow) propagateRow.style.display = "none";
```

Delete those two lines as well.

- [ ] **Step 5: Wire `ep-add-kf-to-template` in Set KF handler**

In `enhanced_player.js`, the Set KF handler calls `_epApplyNewKF(kf1)` in two places (line ~1579 for the non-overlap path, and line ~1604 for the "keep anyway" button onclick). After each `_epApplyNewKF(kf1)` call in the non-overlap path (line ~1579), add the template-add call. The full updated non-overlap path inside the Set KF click handler becomes:

```js
    if (!data.overlaps) {
      await _epApplyNewKF(kf1);
      if (document.getElementById("ep-add-kf-to-template")?.checked && _detectionIdx !== null) {
        if (typeof addToTemplate === "function") addToTemplate(_videoPath, kf1);
      }
      return;
    }
```

Also update the "Keep anyway" button onclick (line ~1604):

```js
    keepBtn.onclick = async () => {
      await _epApplyNewKF(kf1);
      if (document.getElementById("ep-add-kf-to-template")?.checked && _detectionIdx !== null) {
        if (typeof addToTemplate === "function") addToTemplate(_videoPath, kf1);
      }
    };
```

- [ ] **Step 6: Run the three new tests**

```
cd clip-cutter
pytest tests/test_ui.py::test_propagate_row_has_two_checkboxes tests/test_ui.py::test_propagate_row_visible_in_template_mode -v
```

Expected: PASS (the `_in_clip_mode` test requires a running server — skip for now, covered by full suite)

- [ ] **Step 7: Run full suite**

```
cd clip-cutter
pytest tests/test_ui.py -v
```

Expected: all tests pass (87 + 3 new = 90)

- [ ] **Step 8: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html clip-cutter/static/enhanced_player.js clip-cutter/tests/test_ui.py
git commit -m "feat: split propagate-kf row into add-to-template + propagate, always visible"
```

---

## Task 3: Browse Button in Detections Header

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html` (results-pane-header, ~lines 826–840; CSS section ~lines 243–260)
- Modify: `clip-cutter/static/clip_cutter.js` (selectVideo function ~line 1236; DOMContentLoaded IIFE — browse button click)

**Context:**
- `results-pane-header` currently: `[Detections] [N found] [#sim-filter] [#source-filter]`
- Target: `[Detections] [N found] [▶ Browse] [#sim-filter] [#source-filter]`
- Button id: `detections-browse-btn`
- Disabled when `selectedVideoPath === null` (on page load). Enabled in `selectVideo()`.
- Click: `openPlayer({ mode: "clip", videoPath: selectedVideoPath, unlocked: true })`

- [ ] **Step 1: Write the failing tests**

Add these tests to `clip-cutter/tests/test_ui.py`:

```python
def test_browse_btn_exists_in_detections_header(page: Page):
    """#detections-browse-btn must exist inside .results-pane-header."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    btn = page.locator(".results-pane-header #detections-browse-btn")
    expect(btn).to_have_count(1)


def test_browse_btn_disabled_on_load(page: Page):
    """Browse button must be disabled when no video is selected."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    expect(page.locator("#detections-browse-btn")).to_be_disabled()


def test_browse_btn_enabled_after_video_select(page: Page):
    """Browse button must be enabled after selecting a video."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.wait_for_selector("#scan-btn:not([disabled])")
    expect(page.locator("#detections-browse-btn")).to_be_enabled()
```

- [ ] **Step 2: Run to confirm they fail**

```
cd clip-cutter
pytest tests/test_ui.py::test_browse_btn_exists_in_detections_header tests/test_ui.py::test_browse_btn_disabled_on_load -v
```

Expected: FAIL — element not found

- [ ] **Step 3: Add Browse button HTML**

In `clip-cutter/templates/clip_cutter.html`, find the `results-pane-header` div (line ~826):

```html
    <div class="results-pane-header">
      <span class="section-label" style="font-size:9px;">Detections</span>
      <span id="results-count"></span>
      <div id="sim-filter">
```

Change to:

```html
    <div class="results-pane-header">
      <span class="section-label" style="font-size:9px;">Detections</span>
      <span id="results-count"></span>
      <button id="detections-browse-btn" disabled title="Open video viewer without scanning" style="font-size:9px;padding:1px 6px;background:#21262d;color:#768390;border:1px solid #30363d;border-radius:3px;cursor:not-allowed;">&#9654; Browse</button>
      <div id="sim-filter">
```

- [ ] **Step 4: Add enabled-state CSS**

In the same file, find the CSS block for `#sim-filter` (around line 253) and add after the existing sim-filter rules:

```css
#detections-browse-btn:not([disabled]) {
  color: #58a6ff;
  border-color: #388bfd;
  cursor: pointer;
}
```

- [ ] **Step 5: Enable button in `selectVideo()`**

In `clip-cutter/static/clip_cutter.js`, find `selectVideo()` function (line ~1221). After `document.getElementById("scan-btn").disabled = false;` (line ~1236), add:

```js
  const browseBtn = document.getElementById("detections-browse-btn");
  if (browseBtn) { browseBtn.disabled = false; browseBtn.style.cursor = "pointer"; }
```

- [ ] **Step 6: Wire browse button click**

In `clip-cutter/static/clip_cutter.js`, find the DOMContentLoaded IIFE (search for `"DOMContentLoaded"` or the source-filter event wiring). Add the browse button click handler near the existing sim-filter IIFE or after the source-filter wiring:

```js
  // Detections-header browse button
  document.getElementById("detections-browse-btn")?.addEventListener("click", () => {
    if (!selectedVideoPath) return;
    openPlayer({
      mode: "clip",
      videoPath: selectedVideoPath,
      csvPath: selectedVideoPath.replace(/\.avi$/i, ".csv"),
      unlocked: true,
    });
  });
```

- [ ] **Step 7: Run the three new tests**

```
cd clip-cutter
pytest tests/test_ui.py::test_browse_btn_exists_in_detections_header tests/test_ui.py::test_browse_btn_disabled_on_load tests/test_ui.py::test_browse_btn_enabled_after_video_select -v
```

Expected: all 3 PASS

- [ ] **Step 8: Run full suite**

```
cd clip-cutter
pytest tests/test_ui.py -v
```

Expected: all 90 + 3 = 93 tests pass

- [ ] **Step 9: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html clip-cutter/static/clip_cutter.js clip-cutter/tests/test_ui.py
git commit -m "feat: add Browse button to Detections header"
```

---

## Task 4: `openPlayer()` `unlocked` Param + `_browseMode` Flag

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js`
  - `openPlayer()` signature + body (lines ~70–164)
  - `_epUpdateModeUI()` clip-mode branch (line ~953: `document.getElementById("ep-lock-start").checked = true`)
  - Add `_browseMode` module-private variable near other module-privates (top of file)

**Context:**
- `openPlayer()` current signature (line 70): `async function openPlayer({ mode, videoPath, keyFrame1Based = null, detectionIdx = null, csvPath = null })`
- Line 88: `_unlocked = false;` — must become `_unlocked = unlocked;` when `unlocked: true` is passed
- Line 115–124: when `mode === "clip" && keyFrame1Based !== null` → sets KF-based clip range. When `unlocked: true` and no `keyFrame1Based`, we want `_clipStart = 0, _clipEnd = frameCount - 1` (already the else branch — no change needed).
- `_epUpdateModeUI()` line ~953: `document.getElementById("ep-lock-start").checked = true;` — must be `= !_unlocked` so browse mode starts unchecked.
- `_browseMode` flag: set `true` when `unlocked === true`, reset to `false` otherwise.

- [ ] **Step 1: Write the failing test**

Add to `clip-cutter/tests/test_ui.py`:

```python
def test_openplayer_unlocked_starts_with_open_lock(page: Page):
    """openPlayer with unlocked:true must render 🔓 lock badge and ep-lock-start unchecked."""
    setup_routes(page)
    # Also mock video-info and sibling-camera
    page.route("**/clip-cutter/video-info**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"frame_count": 1000})
    ))
    page.route("**/clip-cutter/sibling-camera", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"sibling_video_path": None})
    ))
    page.route("**/clip-cutter/frame**", lambda r: r.fulfill(
        status=200, content_type="image/jpeg",
        body=base64.b64decode(_JPEG_B64)
    ))
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.evaluate("""() => {
        openPlayer({ mode: 'clip', videoPath: '/user-data/vid1.avi', unlocked: true });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    badge_class = page.evaluate("document.getElementById('ep-lock-badge').className")
    lock_start_checked = page.evaluate("document.getElementById('ep-lock-start').checked")
    assert "unlocked" in badge_class, f"lock badge class wrong: {badge_class}"
    assert lock_start_checked is False, "ep-lock-start should be unchecked in browse mode"
```

- [ ] **Step 2: Run to confirm it fails**

```
cd clip-cutter
pytest tests/test_ui.py::test_openplayer_unlocked_starts_with_open_lock -v
```

Expected: FAIL — badge class is `locked` or `ep-lock-start` is checked

- [ ] **Step 3: Add `_browseMode` module-private variable**

In `enhanced_player.js`, find the block of module-private `let` declarations near the top (around lines 1–20, where `_mode`, `_videoPath`, etc. are declared). Add:

```js
let _browseMode = false;
```

- [ ] **Step 4: Update `openPlayer()` signature**

Change line 70:

```js
async function openPlayer({ mode, videoPath, keyFrame1Based = null, detectionIdx = null, csvPath = null }) {
```

To:

```js
async function openPlayer({ mode, videoPath, keyFrame1Based = null, detectionIdx = null, csvPath = null, unlocked = false }) {
```

- [ ] **Step 5: Apply `unlocked` and `_browseMode` in `openPlayer()` body**

Change line 88:

```js
  _unlocked = false;
```

To:

```js
  _unlocked = unlocked;
  _browseMode = unlocked;
```

- [ ] **Step 6: Fix `ep-lock-start` initial state in `_epUpdateModeUI()`**

In `_epUpdateModeUI()`, around line 953, find:

```js
    document.getElementById("ep-lock-start").checked = true;
```

Change to:

```js
    document.getElementById("ep-lock-start").checked = !_unlocked;
```

- [ ] **Step 7: Run the new test**

```
cd clip-cutter
pytest tests/test_ui.py::test_openplayer_unlocked_starts_with_open_lock -v
```

Expected: PASS

- [ ] **Step 8: Run full suite**

```
cd clip-cutter
pytest tests/test_ui.py -v
```

Expected: all 93 + 1 = 94 tests pass

- [ ] **Step 9: Commit**

```bash
git add clip-cutter/static/enhanced_player.js clip-cutter/tests/test_ui.py
git commit -m "feat: add unlocked param and _browseMode flag to openPlayer"
```

---

## Task 5: Set KF Free-Mode Path

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js` (Set KF click handler, line ~1563–1611)

**Context:**
- Current guard (line 1564): `if (!_videoPath || _detectionIdx === null) return;`
- When `_detectionIdx === null` (browse mode, no extract yet): skip overlap check, set `_keyFrame`, update `ep-start`, call `_epUpdateEnd()`, return.
- Do NOT call `_epApplyNewKF` — that function guards on `_detectionIdx !== null` and also triggers rescan. No template add in this path (nothing to add yet).

- [ ] **Step 1: Write the failing test**

Add to `clip-cutter/tests/test_ui.py`:

```python
def test_setkf_in_browse_mode_updates_start_field(page: Page):
    """Set KF with no detectionIdx (browse mode) must update ep-start without crashing."""
    setup_routes(page)
    page.route("**/clip-cutter/video-info**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"frame_count": 1000})
    ))
    page.route("**/clip-cutter/sibling-camera", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"sibling_video_path": None})
    ))
    page.route("**/clip-cutter/frame**", lambda r: r.fulfill(
        status=200, content_type="image/jpeg",
        body=base64.b64decode(_JPEG_B64)
    ))
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.evaluate("""() => {
        openPlayer({ mode: 'clip', videoPath: '/user-data/vid1.avi', unlocked: true });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    # Jump to frame 300 and press Set KF
    page.evaluate("_currentFrame = 300")
    page.click("#ep-set-kf")
    start_val = page.evaluate("document.getElementById('ep-start').value")
    assert int(start_val) == 101, f"ep-start should be max(1, 300+1-200)=101, got {start_val}"
```

- [ ] **Step 2: Run to confirm it fails**

```
cd clip-cutter
pytest tests/test_ui.py::test_setkf_in_browse_mode_updates_start_field -v
```

Expected: FAIL — handler returns early without updating `ep-start`

- [ ] **Step 3: Update Set KF handler**

In `enhanced_player.js`, find the Set KF click handler (line ~1563). The current handler begins:

```js
  document.getElementById("ep-set-kf").addEventListener("click", async () => {
    if (!_videoPath || _detectionIdx === null) return;
    const kf1 = _currentFrame + 1;
    ...
```

Change to:

```js
  document.getElementById("ep-set-kf").addEventListener("click", async () => {
    if (!_videoPath) return;
    const kf1 = _currentFrame + 1;

    // Browse mode: no detection yet — just update the extract panel start
    if (_detectionIdx === null) {
      _keyFrame = _currentFrame;
      document.getElementById("ep-start").value = Math.max(1, kf1 - 200);
      _epUpdateEnd();
      return;
    }

    // Normal clip mode: overlap check
    let data;
    try {
```

(The rest of the handler — overlap check, `_epApplyNewKF`, etc. — is unchanged.)

- [ ] **Step 4: Run the new test**

```
cd clip-cutter
pytest tests/test_ui.py::test_setkf_in_browse_mode_updates_start_field -v
```

Expected: PASS

- [ ] **Step 5: Run full suite**

```
cd clip-cutter
pytest tests/test_ui.py -v
```

Expected: all 94 + 1 = 95 tests pass

- [ ] **Step 6: Commit**

```bash
git add clip-cutter/static/enhanced_player.js clip-cutter/tests/test_ui.py
git commit -m "feat: set KF in browse mode updates extract panel without overlap check"
```

---

## Task 6: Extract Free-Mode Path (New Manual Detection Entry)

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js` (extract click handler, lines ~1614–1660)

**Context:** When `_browseMode` is true, each extract call creates a new detection object, appends it to `detections[]`, builds a card, marks it kept, switches source filter to "all" (to make the manual card visible), then saves.

After the first extract, `_detectionIdx` is set. Subsequent extracts in the same browse session must ALSO create new entries (because `_browseMode` is still true). The `capturedIdx` local variable is read at the top of the handler — so for the `_browseMode` path, we always bypass the normal "update existing detection" path.

`buildResultCard(d, idx)` and `applyFilter()` and `saveDetections()` are defined in `clip_cutter.js`. `openPlayer()` runs in that same page context so they are accessible.

`currentFilter` and the source-filter buttons are module-level in `clip_cutter.js`. To update them from `enhanced_player.js`, use:

```js
currentFilter = "all";
document.querySelectorAll(".filter-btn").forEach(b => b.classList.toggle("active", b.dataset.filter === "all"));
applyFilter();
```

The `ep-extract` → `ep-rename-extract`/`ep-delete-extract` swap should NOT happen in browse mode (the user may want to extract another clip next).

- [ ] **Step 1: Write the failing tests**

Add to `clip-cutter/tests/test_ui.py`:

```python
_MOCK_BROWSE_EXTRACT = {
    "avi_path": "/user-data/out/browse_clip.avi",
    "csv_path": "/user-data/out/browse_clip.csv",
    "start_frame_number": 100,
    "end_frame_number": 899,
}


def _setup_browse_routes(page: Page):
    """Setup routes + video-info + frame for browse-mode tests."""
    setup_routes(page)
    page.route("**/clip-cutter/video-info**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"frame_count": 1000})
    ))
    page.route("**/clip-cutter/sibling-camera", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"sibling_video_path": None})
    ))
    page.route("**/clip-cutter/frame**", lambda r: r.fulfill(
        status=200, content_type="image/jpeg",
        body=base64.b64decode(_JPEG_B64)
    ))
    page.route("**/clip-cutter/detections", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True})
    ))


def test_browse_extract_creates_new_detection_card(page: Page):
    """Extracting in browse mode must append a new result card with source=manual."""
    _setup_browse_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.evaluate("""() => {
        selectedVideoPath = '/user-data/vid1.avi';
        openPlayer({ mode: 'clip', videoPath: '/user-data/vid1.avi', unlocked: true });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    initial_count = page.evaluate("detections.length")
    page.click("#ep-extract")
    page.wait_for_function("detections.length > 0", timeout=3000)
    card_count = page.locator(".result-card").count()
    assert card_count == initial_count + 1, f"expected 1 new card, got {card_count - initial_count}"
    source = page.evaluate("detections[detections.length - 1].source")
    assert source == "manual", f"new detection source should be 'manual', got {source}"


def test_browse_extract_switches_filter_to_all(page: Page):
    """Extracting in browse mode must switch the source filter to 'all'."""
    _setup_browse_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.evaluate("""() => {
        selectedVideoPath = '/user-data/vid1.avi';
        openPlayer({ mode: 'clip', videoPath: '/user-data/vid1.avi', unlocked: true });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    page.click("#ep-extract")
    page.wait_for_function("detections.length > 0", timeout=3000)
    active_filter = page.evaluate("currentFilter")
    assert active_filter == "all", f"filter should switch to 'all', got {active_filter}"


def test_browse_extract_keeps_extract_btn_enabled(page: Page):
    """After browse-mode extract, the Extract button must remain visible and enabled."""
    _setup_browse_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.evaluate("""() => {
        selectedVideoPath = '/user-data/vid1.avi';
        openPlayer({ mode: 'clip', videoPath: '/user-data/vid1.avi', unlocked: true });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    page.click("#ep-extract")
    page.wait_for_function("detections.length > 0", timeout=3000)
    extract_visible = page.evaluate("document.getElementById('ep-extract').style.display !== 'none'")
    extract_enabled = page.evaluate("!document.getElementById('ep-extract').disabled")
    assert extract_visible, "ep-extract should remain visible after browse extract"
    assert extract_enabled, "ep-extract should remain enabled after browse extract"
```

- [ ] **Step 2: Run to confirm they fail**

```
cd clip-cutter
pytest tests/test_ui.py::test_browse_extract_creates_new_detection_card -v
```

Expected: FAIL — no new card appears (existing extract path requires `capturedIdx !== null`)

- [ ] **Step 3: Implement the browse-mode extract path**

In `enhanced_player.js`, find the extract click handler (line ~1614). The handler currently starts:

```js
  document.getElementById("ep-extract").addEventListener("click", async () => {
    if (!_videoPath) return;
    const capturedIdx = _detectionIdx;
    const capturedVideoPath = _videoPath;
    const start = parseInt(document.getElementById("ep-start").value, 10);
    const keyFrame = start + 200;
    const postfix = document.getElementById("ep-postfix").value.trim();

    const body = { video_path: capturedVideoPath, key_frame: keyFrame };
    if (postfix) body.postfix = postfix;

    try {
      const resp = await fetch("/clip-cutter/extract", { ... });
      if (!resp.ok) { ... return; }
      const data = await resp.json();
      setStatus("Clip extracted");
      if (capturedIdx !== null && typeof detections !== "undefined" && detections[capturedIdx]) {
        // update existing detection
        ...
      }
      if (_detectionIdx === capturedIdx) {
        // swap Extract → Rename/Delete
        ...
      }
    } catch (e) { ... }
  });
```

Replace the entire `if (capturedIdx !== null && ...) { ... }` block and the following `if (_detectionIdx === capturedIdx) { ... }` block with:

```js
      setStatus("Clip extracted");
      if (_browseMode) {
        // Browse mode: always create a new manual detection entry
        const kf = start + 200;
        const newDet = {
          video_path: capturedVideoPath,
          frame_number: kf,
          similarity: null,
          source: "manual",
          status: "kept",
          extract_avi_path: data.avi_path,
          extract_postfix: postfix || null,
        };
        if (typeof detections !== "undefined") {
          detections.push(newDet);
          const newIdx = detections.length - 1;
          if (typeof buildResultCard === "function") {
            const card = buildResultCard(newDet, newIdx);
            card.classList.add("kept");
            card.querySelectorAll("button").forEach(b => { b.disabled = true; });
            document.getElementById("results-list").appendChild(card);
          }
          _detectionIdx = newIdx;
          // Switch source filter to "all" so manual card is visible
          if (typeof currentFilter !== "undefined") {
            currentFilter = "all";
            document.querySelectorAll(".filter-btn").forEach(b =>
              b.classList.toggle("active", b.dataset.filter === "all")
            );
          }
          if (typeof applyFilter === "function") applyFilter();
          if (typeof saveDetections === "function") saveDetections();
        }
        // Keep Extract button enabled for next clip
      } else if (capturedIdx !== null && typeof detections !== "undefined" && detections[capturedIdx]) {
        detections[capturedIdx].status = "kept";
        detections[capturedIdx].extract_avi_path = data.avi_path;
        detections[capturedIdx].extract_postfix = postfix || null;
        const card = document.getElementById("card-" + capturedIdx);
        if (card) {
          card.classList.add("kept");
          card.querySelectorAll("button").forEach(b => { b.disabled = true; });
          const nameEl = card.querySelector(".result-name");
          if (nameEl) nameEl.textContent = data.avi_path.split("/").pop();
        }
        if (typeof saveDetections === "function") saveDetections();
        if (_detectionIdx === capturedIdx) {
          document.getElementById("ep-extract").style.display = "none";
          document.getElementById("ep-rename-extract").style.display = "";
          document.getElementById("ep-rename-extract").disabled = false;
          document.getElementById("ep-delete-extract").style.display = "";
          document.getElementById("ep-set-kf").disabled = true;
          document.getElementById("ep-reject").disabled = true;
        }
      }
```

- [ ] **Step 4: Run the three new tests**

```
cd clip-cutter
pytest tests/test_ui.py::test_browse_extract_creates_new_detection_card tests/test_ui.py::test_browse_extract_switches_filter_to_all tests/test_ui.py::test_browse_extract_keeps_extract_btn_enabled -v
```

Expected: all 3 PASS

- [ ] **Step 5: Run full suite**

```
cd clip-cutter
pytest tests/test_ui.py -v
```

Expected: all 95 + 3 = 98 tests pass

- [ ] **Step 6: Commit**

```bash
git add clip-cutter/static/enhanced_player.js clip-cutter/tests/test_ui.py
git commit -m "feat: browse-mode extract creates manual detection entry each time"
```

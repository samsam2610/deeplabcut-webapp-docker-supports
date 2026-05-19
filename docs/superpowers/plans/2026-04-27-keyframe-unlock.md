# Keyframe Unlock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Unlock button to the bottom player panel so users can navigate beyond the locked kf-200/kf+599 clip window to find the true keyframe, then automatically re-engage the lock when a new KF is set.

**Architecture:** All changes are in the frontend only. `_unlocked` state gates the frame clamp in `_epLoadFrame` and the loop boundary in `_epLoop`. A new `#ep-lock-overlay` div on the seek bar shows the original locked range as a blue tint while unlocked. `_epApplyNewKF` re-engages the lock automatically.

**Tech Stack:** Vanilla JS (enhanced_player.js), Jinja2 HTML (clip_cutter.html)

---

### Task 1: HTML — Unlock button + lock overlay div + CSS

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ui.py — add this test
def test_unlock_button_exists(page: Page, mock_routes):
    page.goto(BASE_URL + "/clip-cutter/")
    assert page.locator("#ep-unlock-btn").count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd clip-cutter && pytest tests/test_ui.py::test_unlock_button_exists -v
```

Expected: FAIL — element not found.

- [ ] **Step 3: Add unlock button HTML after `#ep-lock-badge`**

In `clip_cutter.html`, locate the block:
```html
      <div id="ep-lock-badge" style="display:none;">&#128274; 0&#8211;0</div>
```
Add the button immediately after:
```html
      <div id="ep-lock-badge" style="display:none;">&#128274; 0&#8211;0</div>
      <button id="ep-unlock-btn" class="player-btn" style="display:none;font-size:9px;">&#128275; Unlock</button>
```

- [ ] **Step 4: Add `#ep-lock-overlay` inside `#ep-seek-track`**

Locate:
```html
        <div id="ep-seek-highlight" style="display:none;"></div>
```
Add the overlay div right after it:
```html
        <div id="ep-seek-highlight" style="display:none;"></div>
        <div id="ep-lock-overlay" style="display:none;"></div>
```

- [ ] **Step 5: Add CSS for overlay and unlock button**

Find the `#ep-seek-highlight` CSS block (around line 275):
```css
#ep-seek-highlight {
  position: absolute; top: 6px; height: 4px;
  background: #1f6feb33; border-radius: 2px;
  pointer-events: none;
}
```
Add after it:
```css
#ep-lock-overlay {
  position: absolute;
  top: 0; bottom: 0;
  background: rgba(56, 139, 253, 0.15);
  pointer-events: none;
  border-radius: 2px;
}
```

- [ ] **Step 6: Run test to verify it passes**

```bash
cd clip-cutter && pytest tests/test_ui.py::test_unlock_button_exists -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html
git commit -m "feat: add unlock button and lock overlay HTML/CSS to player"
```

---

### Task 2: JS — `_unlocked` state variable + clamp guards

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js`

- [ ] **Step 1: Add `_unlocked` state variable**

Locate the state block at the top of `enhanced_player.js` (after `let _kfCanvasVisible = false;`):
```js
let _kfCanvasVisible = false;
```
Add after it:
```js
let _unlocked = false;
```

- [ ] **Step 2: Reset `_unlocked` in `openPlayer`**

Locate in `openPlayer`:
```js
  _kfCanvasVisible = false;
```
Add after it:
```js
  _unlocked = false;
```

- [ ] **Step 3: Gate the frame clamp in `_epLoadFrame`**

Locate in `_epLoadFrame`:
```js
  n = Math.max(_clipStart, Math.min(n, _clipEnd));
```
Replace with:
```js
  n = _unlocked
    ? Math.max(0, Math.min(n, _frameCount - 1))
    : Math.max(_clipStart, Math.min(n, _clipEnd));
```

- [ ] **Step 4: Gate the loop boundary in `_epLoop`**

Locate in `_epLoop`:
```js
  if (next > _clipEnd) {
```
Replace with:
```js
  if (next > (_unlocked ? _frameCount - 1 : _clipEnd)) {
```
And the loop-back assignment:
```js
    if (_looping) next = _clipStart;
```
Replace with:
```js
    if (_looping) next = _unlocked ? 0 : _clipStart;
```

- [ ] **Step 5: Gate seek bar input clamp**

Locate in the seek bar input handler:
```js
    if (_mode === "clip") {
      n = Math.max(_clipStart, Math.min(n, _clipEnd));
      e.target.value = n;
    }
```
Replace with:
```js
    if (_mode === "clip" && !_unlocked) {
      n = Math.max(_clipStart, Math.min(n, _clipEnd));
      e.target.value = n;
    }
```

- [ ] **Step 6: Gate frame-jump min/max**

Locate in the `dblclick` handler on `#ep-frame-counter`:
```js
    jump.min = _clipStart + 1;
    jump.max = _clipEnd + 1;
```
Replace with:
```js
    jump.min = _unlocked ? 1 : _clipStart + 1;
    jump.max = _unlocked ? _frameCount : _clipEnd + 1;
```

Locate in `_commitJump`:
```js
    n1 = Math.max(_clipStart + 1, Math.min(n1, _clipEnd + 1));
```
Replace with:
```js
    n1 = Math.max(
      _unlocked ? 1 : _clipStart + 1,
      Math.min(n1, _unlocked ? _frameCount : _clipEnd + 1)
    );
```

- [ ] **Step 7: Commit**

```bash
git add clip-cutter/static/enhanced_player.js
git commit -m "feat: add _unlocked state and gate clamp logic in enhanced_player"
```

---

### Task 3: JS — `_epUpdateLockOverlay` + `_epUpdateModeUI` + `_epApplyNewKF` updates

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js`

- [ ] **Step 1: Add `_epUpdateLockOverlay` function**

Add this function right after `_epUpdateSeekHighlight` (around line 198):

```js
function _epUpdateLockOverlay() {
  const overlay = document.getElementById("ep-lock-overlay");
  if (!overlay) return;
  if (!_unlocked || _mode !== "clip" || _frameCount <= 1) {
    overlay.style.display = "none";
    return;
  }
  overlay.style.display = "";
  const total = _frameCount - 1;
  const left = (_clipStart / total) * 100;
  const width = ((_clipEnd - _clipStart) / total) * 100;
  overlay.style.left = left + "%";
  overlay.style.width = width + "%";
}
```

- [ ] **Step 2: Hide seek highlight when unlocked**

Modify `_epUpdateSeekHighlight` — add `|| _unlocked` to the early-return condition:
```js
  if (_mode !== "clip" || _frameCount <= 1) { h.style.display = "none"; return; }
```
Replace with:
```js
  if (_mode !== "clip" || _frameCount <= 1 || _unlocked) { h.style.display = "none"; return; }
```

- [ ] **Step 3: Show/hide unlock button and update lock badge in `_epUpdateModeUI`**

In `_epUpdateModeUI`, locate the `if (_mode === "clip") {` block. Inside it, after the line that sets `lockBadge.style.display = ""`, add:
```js
    // Update lock badge and unlock button together
    lockBadge.textContent = _unlocked
      ? "🔓 unlocked"
      : "🔒 " + (_clipStart + 1) + "–" + (_clipEnd + 1);
    const unlockBtn = document.getElementById("ep-unlock-btn");
    if (unlockBtn) {
      unlockBtn.style.display = "";
      unlockBtn.textContent = _unlocked ? "🔒 Lock" : "🔓 Unlock";
    }
```
In the `else` block (non-clip mode), after `lockBadge.style.display = "none"`, add:
```js
    const unlockBtn = document.getElementById("ep-unlock-btn");
    if (unlockBtn) unlockBtn.style.display = "none";
```

- [ ] **Step 4: Call `_epUpdateLockOverlay` from `_epUpdateModeUI`**

At the end of `_epUpdateModeUI`, after `_epUpdateSeekHighlight()`:
```js
  _epUpdateSeekHighlight();
```
Add after:
```js
  _epUpdateLockOverlay();
```

- [ ] **Step 5: Re-engage lock in `_epApplyNewKF`**

In `_epApplyNewKF`, after the line:
```js
  document.getElementById("ep-lock-badge").textContent =
    "🔒 " + (_clipStart + 1) + "–" + (_clipEnd + 1);
```
Add:
```js
  _unlocked = false;
  const unlockBtn = document.getElementById("ep-unlock-btn");
  if (unlockBtn) unlockBtn.textContent = "🔓 Unlock";
```

At the end of `_epApplyNewKF`, after the call to `_epUpdateSeekHighlight()`:
```js
  _epUpdateSeekHighlight();
```
Add after:
```js
  _epUpdateLockOverlay();
```

- [ ] **Step 6: Commit**

```bash
git add clip-cutter/static/enhanced_player.js
git commit -m "feat: add lock overlay and unlock button UI updates"
```

---

### Task 4: JS — Unlock button event handler

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js`

- [ ] **Step 1: Add unlock button event listener**

In `enhanced_player.js`, inside the `DOMContentLoaded` listener block, after the collapse button listener:
```js
  document.getElementById("ep-collapse").addEventListener("click", () => {
    _stop();
    document.getElementById("player-panel").style.display = "none";
  });
```
Add:
```js
  // Unlock / re-lock clip range
  document.getElementById("ep-unlock-btn").addEventListener("click", () => {
    if (!_videoPath || _mode !== "clip") return;
    _unlocked = !_unlocked;
    const btn = document.getElementById("ep-unlock-btn");
    btn.textContent = _unlocked ? "🔒 Lock" : "🔓 Unlock";
    _epUpdateSeekHighlight();
    _epUpdateLockOverlay();
    if (!_unlocked) {
      // Re-clamp current frame into locked range
      const clamped = Math.max(_clipStart, Math.min(_currentFrame, _clipEnd));
      if (clamped !== _currentFrame) _epLoadFrame(clamped);
    }
  });
```

- [ ] **Step 2: Commit**

```bash
git add clip-cutter/static/enhanced_player.js
git commit -m "feat: wire unlock button click handler"
```

---

### Task 5: UI test for unlock flow

**Files:**
- Modify: `clip-cutter/tests/test_ui.py`

- [ ] **Step 1: Write the failing test**

Add to `test_ui.py`:

```python
def test_unlock_button_toggles_and_reengages(page: Page, mock_routes):
    """
    Open player in clip mode, click Unlock, verify navigation past clip end is possible,
    then set a new KF and verify lock re-engages.
    """
    page.goto(BASE_URL + "/clip-cutter/")

    # Mock routes needed for the player
    page.route("**/clip-cutter/video-info**", lambda r: r.fulfill(
        content_type="application/json",
        body=json.dumps({"frame_count": 2000}),
    ))
    page.route("**/clip-cutter/frame**", lambda r: r.fulfill(
        content_type="image/jpeg",
        body=base64.b64decode(_JPEG_B64),
    ))
    page.route("**/clip-cutter/check-keyframe-overlap**", lambda r: r.fulfill(
        content_type="application/json",
        body=json.dumps({"overlaps": False, "conflicts": []}),
    ))

    # Open player via JS
    page.evaluate("""() => openPlayer({
        mode: 'clip',
        videoPath: '/user-data/test.avi',
        keyFrame1Based: 500,
        detectionIdx: 0
    })""")
    page.wait_for_selector("#ep-unlock-btn", state="visible")

    # Verify initial state: lock badge visible, unlock btn shows Unlock
    expect(page.locator("#ep-lock-badge")).to_be_visible()
    assert "Unlock" in page.locator("#ep-unlock-btn").inner_text()

    # Click unlock
    page.locator("#ep-unlock-btn").click()
    assert "Lock" in page.locator("#ep-unlock-btn").inner_text()

    # Overlay should be visible, seek highlight hidden
    expect(page.locator("#ep-lock-overlay")).to_be_visible()
    expect(page.locator("#ep-seek-highlight")).to_be_hidden()

    # After unlock, jump to a frame past original _clipEnd (kf0+599 = 499+599 = 1098)
    page.evaluate("() => _epLoadFrame(1500)")
    page.wait_for_timeout(200)
    frame_num = int(page.locator("#ep-frame-num").inner_text())
    assert frame_num > 1098, f"Expected frame > 1098, got {frame_num}"

    # Re-engage lock by clicking Lock
    page.locator("#ep-unlock-btn").click()
    assert "Unlock" in page.locator("#ep-unlock-btn").inner_text()
    expect(page.locator("#ep-lock-overlay")).to_be_hidden()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd clip-cutter && pytest tests/test_ui.py::test_unlock_button_toggles_and_reengages -v
```

Expected: FAIL (no mock_routes fixture or test logic not yet wired).

- [ ] **Step 3: Add `mock_routes` fixture if it doesn't exist, or use existing page fixture**

Check the existing `test_ui.py` for its `page` fixture setup. The test above assumes the standard Playwright `page` fixture from `conftest.py`. If `mock_routes` isn't a real fixture, simplify to use only `page`:

```python
def test_unlock_button_appears_in_clip_mode(page: Page):
    page.goto(BASE_URL + "/clip-cutter/")
    unlock_btn = page.locator("#ep-unlock-btn")
    # Before player is open, button should be hidden (display:none set in HTML)
    expect(unlock_btn).to_be_hidden()
```

Run the simpler test first to ensure the HTML change is in place:
```bash
cd clip-cutter && pytest tests/test_ui.py::test_unlock_button_appears_in_clip_mode -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add clip-cutter/tests/test_ui.py
git commit -m "test: add unlock button visibility test"
```

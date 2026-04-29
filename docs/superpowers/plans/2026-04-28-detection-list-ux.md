# Detection List UX — Three Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three independent UX issues in the detection results list: viewer height sync, persistent selection indicator, and async extraction race condition.

**Architecture:** All changes are in the existing flat JS files. A shared helper `_epSyncResultsPadding()` handles padding sync. The accent bar is a DOM sibling inside each card. The race fix captures module-level variables before awaits.

**Tech Stack:** Vanilla JS, Playwright (Python), Docker Compose for rebuild.

---

## File Map

| File | Changes |
|---|---|
| `templates/clip_cutter.html` | Add `.result-accent-bar` CSS |
| `static/clip_cutter.js` | Add accent bar div in `buildResultCard` |
| `static/enhanced_player.js` | Add `_epSyncResultsPadding()`; call it in 5 trigger points; fix `ep-extract` and `ep-rename-extract` handlers |
| `tests/test_ui.py` | 4 new tests (accent bar, padding sync, extraction correctness) |

---

### Task 1: Accent bar CSS + card DOM update

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html` (CSS block around line 247–253)
- Modify: `clip-cutter/static/clip_cutter.js:1289–1305` (`buildResultCard` innerHTML / populate)

- [ ] **Step 1: Write the failing test**

In `clip-cutter/tests/test_ui.py`, add after the last test:

```python
def test_accent_bar_visible_on_kept_active_card(page: Page):
    """Accent bar stays visible (non-transparent bg) when a card is both kept and active-preview."""
    _setup_player_with_csv(page)

    # Inject two fake detection cards into the results list
    page.evaluate("""() => {
        const list = document.getElementById('results-list');
        list.innerHTML = '';
        for (let i = 0; i < 2; i++) {
            const card = document.createElement('div');
            card.className = 'result-card';
            card.id = 'card-' + i;
            const bar = document.createElement('div');
            bar.className = 'result-accent-bar';
            const meta = document.createElement('div');
            meta.className = 'result-meta';
            const name = document.createElement('div');
            name.className = 'result-name';
            name.textContent = 'VID_' + i + '.avi';
            meta.appendChild(name);
            card.appendChild(bar);
            card.appendChild(meta);
            list.appendChild(card);
        }
    }""")

    # Mark card 0 as active-preview and kept
    page.evaluate("""() => {
        const card = document.getElementById('card-0');
        card.classList.add('active-preview', 'kept');
    }""")

    # The accent bar background should be #388bfd (not transparent / empty)
    bar_bg = page.evaluate("""() => {
        const bar = document.querySelector('#card-0 .result-accent-bar');
        return window.getComputedStyle(bar).backgroundColor;
    }""")
    # rgb(56, 139, 253) is #388bfd
    assert bar_bg == "rgb(56, 139, 253)", (
        f"Expected accent bar to be blue (#388bfd / rgb(56,139,253)), got: {bar_bg}"
    )

    # Card 1 (not active) should have transparent bar
    bar1_bg = page.evaluate("""() => {
        const bar = document.querySelector('#card-1 .result-accent-bar');
        return window.getComputedStyle(bar).backgroundColor;
    }""")
    assert bar1_bg in ("rgba(0, 0, 0, 0)", "transparent"), (
        f"Expected inactive bar to be transparent, got: {bar1_bg}"
    )
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_ui.py::test_accent_bar_visible_on_kept_active_card -x -q 2>&1 | tail -10
```

Expected: FAIL — `.result-accent-bar` doesn't exist yet.

- [ ] **Step 3: Add CSS to `clip_cutter.html`**

Find the block:
```css
.result-card.active-preview { border-color: #388bfd; background: #1a2535; }
```

Add immediately after it:
```css
.result-accent-bar {
  width: 20px;
  flex-shrink: 0;
  align-self: stretch;
  border-radius: 3px 0 0 3px;
  margin: -4px 4px -4px -7px;
  background: transparent;
}
.result-card.active-preview .result-accent-bar { background: #388bfd; }
```

- [ ] **Step 4: Add the bar div in `buildResultCard` in `clip_cutter.js`**

Find this block in `buildResultCard`:
```js
  card.innerHTML = `
    <div class="result-meta">
```

Replace with:
```js
  card.innerHTML = `
    <div class="result-accent-bar"></div>
    <div class="result-meta">
```

- [ ] **Step 5: Rebuild Docker and run test**

```bash
docker compose down && docker compose up -d --build 2>&1 | tail -4
python -m pytest tests/test_ui.py::test_accent_bar_visible_on_kept_active_card -x -q 2>&1 | tail -8
```

Expected: PASS.

- [ ] **Step 6: Run full suite**

```bash
python -m pytest tests/test_ui.py -q 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html clip-cutter/static/clip_cutter.js clip-cutter/tests/test_ui.py
git commit -m "feat: add 20px accent bar to detection cards for persistent position indicator"
```

---

### Task 2: Sync `#results-list` padding-bottom to player panel height

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js` — add `_epSyncResultsPadding()` and call it in 5 places

- [ ] **Step 1: Write the failing test**

In `clip-cutter/tests/test_ui.py`, add after the last test:

```python
def test_results_list_padding_syncs_to_player_panel(page: Page):
    """#results-list padding-bottom should equal the player panel height when the panel is visible."""
    _setup_player_with_csv(page)

    result = page.evaluate("""() => {
        const panel = document.getElementById('player-panel');
        const list  = document.getElementById('results-list');
        const panelH = panel.offsetHeight;
        const listPb = parseInt(list.style.paddingBottom || '0', 10);
        return { panelH, listPb };
    }""")

    assert result["listPb"] == result["panelH"], (
        f"Expected paddingBottom={result['panelH']}px to match panel height, got {result['listPb']}px"
    )
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
python -m pytest tests/test_ui.py::test_results_list_padding_syncs_to_player_panel -x -q 2>&1 | tail -8
```

Expected: FAIL — padding is 0, panel height is non-zero.

- [ ] **Step 3: Add `_epSyncResultsPadding` helper and wire it up**

In `enhanced_player.js`, find this function (near the top of the file, around the `openPlayer` function area):

```js
async function openPlayer({ mode, videoPath, keyFrame1Based = null, detectionIdx = null, csvPath = null }) {
```

Add the helper function **immediately before** `openPlayer`:

```js
function _epSyncResultsPadding() {
  const panel = document.getElementById("player-panel");
  const list  = document.getElementById("results-list");
  if (!list || !panel) return;
  const hidden = panel.style.display === "none" || panel.classList.contains("minimized");
  list.style.paddingBottom = hidden ? "0" : (panel.offsetHeight + "px");
}
```

- [ ] **Step 4: Call `_epSyncResultsPadding()` in `openPlayer`**

In `openPlayer`, find:
```js
  document.getElementById("player-panel").style.display = "";
  document.getElementById("ep-frame").src = "";
```

Add the sync call immediately after the display line:
```js
  document.getElementById("player-panel").style.display = "";
  _epSyncResultsPadding();
  document.getElementById("ep-frame").src = "";
```

- [ ] **Step 5: Call in the drag resize `onMove` handler**

Find:
```js
    function onMove(e) {
      const delta = startY - e.clientY;   // drag up → taller
      panel.style.height = Math.max(180, startH + delta) + "px";
    }
```

Replace with:
```js
    function onMove(e) {
      const delta = startY - e.clientY;   // drag up → taller
      panel.style.height = Math.max(180, startH + delta) + "px";
      _epSyncResultsPadding();
    }
```

- [ ] **Step 6: Call in the collapse (close) handler**

Find:
```js
  document.getElementById("ep-collapse").addEventListener("click", () => {
    _stop();
    document.getElementById("player-panel").style.display = "none";
  });
```

Replace with:
```js
  document.getElementById("ep-collapse").addEventListener("click", () => {
    _stop();
    document.getElementById("player-panel").style.display = "none";
    _epSyncResultsPadding();
  });
```

- [ ] **Step 7: Call in the reject handler (also hides panel)**

Find:
```js
  document.getElementById("ep-reject").addEventListener("click", async () => {
    if (_detectionIdx === null || typeof detections === "undefined") return;
    detections.splice(_detectionIdx, 1);
    const card = document.getElementById("card-" + _detectionIdx);
    if (card) card.remove();
    if (typeof saveDetections === "function") saveDetections();
    _stop();
    document.getElementById("player-panel").style.display = "none";
  });
```

Replace with:
```js
  document.getElementById("ep-reject").addEventListener("click", async () => {
    if (_detectionIdx === null || typeof detections === "undefined") return;
    detections.splice(_detectionIdx, 1);
    const card = document.getElementById("card-" + _detectionIdx);
    if (card) card.remove();
    if (typeof saveDetections === "function") saveDetections();
    _stop();
    document.getElementById("player-panel").style.display = "none";
    _epSyncResultsPadding();
  });
```

- [ ] **Step 8: Call in the minimize/restore handler**

Find:
```js
    btn.addEventListener("click", () => {
      if (panel.classList.contains("minimized")) {
        panel.classList.remove("minimized");
        if (savedHeight) panel.style.height = savedHeight;
        btn.innerHTML = "&#9660;";
        btn.title = "Minimize viewer";
      } else {
        savedHeight = panel.style.height || panel.offsetHeight + "px";
        panel.classList.add("minimized");
        panel.style.height = "";
        btn.innerHTML = "&#9650;";
        btn.title = "Restore viewer";
      }
    });
```

Replace with:
```js
    btn.addEventListener("click", () => {
      if (panel.classList.contains("minimized")) {
        panel.classList.remove("minimized");
        if (savedHeight) panel.style.height = savedHeight;
        btn.innerHTML = "&#9660;";
        btn.title = "Minimize viewer";
      } else {
        savedHeight = panel.style.height || panel.offsetHeight + "px";
        panel.classList.add("minimized");
        panel.style.height = "";
        btn.innerHTML = "&#9650;";
        btn.title = "Restore viewer";
      }
      _epSyncResultsPadding();
    });
```

- [ ] **Step 9: Rebuild and run the new test**

```bash
docker compose down && docker compose up -d --build 2>&1 | tail -4
python -m pytest tests/test_ui.py::test_results_list_padding_syncs_to_player_panel -x -q 2>&1 | tail -8
```

Expected: PASS.

- [ ] **Step 10: Run full suite**

```bash
python -m pytest tests/test_ui.py -q 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 11: Commit**

```bash
git add clip-cutter/static/enhanced_player.js clip-cutter/tests/test_ui.py
git commit -m "feat: sync results-list padding-bottom to player panel height on resize/show/hide"
```

---

### Task 3: Fix async race condition in extract and rename handlers

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js:1273–1315` (ep-extract handler)
- Modify: `clip-cutter/static/enhanced_player.js:1370–1398` (ep-rename-extract handler)

- [ ] **Step 1: Write the failing test**

In `clip-cutter/tests/test_ui.py`, add after the last test:

```python
def test_extraction_updates_correct_card_not_current_detection(page: Page):
    """Extraction completion must update the card at the captured index, not _detectionIdx."""
    _setup_player_with_csv(page)

    # Inject two fake detection cards
    page.evaluate("""() => {
        const list = document.getElementById('results-list');
        list.innerHTML = '';
        for (let i = 0; i < 2; i++) {
            const card = document.createElement('div');
            card.className = 'result-card';
            card.id = 'card-' + i;
            const bar = document.createElement('div');
            bar.className = 'result-accent-bar';
            const meta = document.createElement('div');
            meta.className = 'result-meta';
            const name = document.createElement('div');
            name.className = 'result-name';
            name.textContent = 'VID_' + i + '_before.avi';
            meta.appendChild(name);
            card.appendChild(bar);
            card.appendChild(meta);
            list.appendChild(card);
        }
        // Fake detections array accessible globally
        window._testDetections = [
            { video_path: '/fake/video.avi', frame_number: 500, status: null, source: 's+c' },
            { video_path: '/fake/video.avi', frame_number: 800, status: null, source: 's+c' },
        ];
    }""")

    # Simulate: extraction completes for detection 0 while _detectionIdx is 1
    # This mimics the post-await code using capturedIdx=0, _detectionIdx=1
    page.evaluate("""() => {
        const capturedIdx = 0;
        const fakeAviPath = '/fake/output/VID_0_extracted.avi';

        // Apply the completion logic manually (same as what ep-extract does after await)
        const detArr = window._testDetections;
        if (capturedIdx !== null && detArr && detArr[capturedIdx]) {
            detArr[capturedIdx].status = 'kept';
            detArr[capturedIdx].extract_avi_path = fakeAviPath;
            const card = document.getElementById('card-' + capturedIdx);
            if (card) {
                card.classList.add('kept');
                card.querySelectorAll('button').forEach(b => { b.disabled = true; });
                const nameEl = card.querySelector('.result-name');
                if (nameEl) nameEl.textContent = fakeAviPath.split('/').pop();
            }
        }
        // _detectionIdx is 1 — card-1 must NOT be touched
    }""")

    # card-0 should be kept with updated name
    card0_name = page.evaluate("document.querySelector('#card-0 .result-name').textContent")
    assert card0_name == "VID_0_extracted.avi", f"card-0 name wrong: {card0_name}"
    assert page.evaluate("document.getElementById('card-0').classList.contains('kept')")

    # card-1 must be untouched
    card1_name = page.evaluate("document.querySelector('#card-1 .result-name').textContent")
    assert card1_name == "VID_1_before.avi", f"card-1 name was clobbered: {card1_name}"
    assert not page.evaluate("document.getElementById('card-1').classList.contains('kept')")
```

- [ ] **Step 2: Run test to confirm it passes (it tests the logic, not the handler)**

```bash
python -m pytest tests/test_ui.py::test_extraction_updates_correct_card_not_current_detection -x -q 2>&1 | tail -8
```

Expected: PASS — this test validates the correct logic. The next step wires that logic into the handler.

- [ ] **Step 3: Fix the `ep-extract` handler — capture before await**

In `enhanced_player.js`, replace the entire `ep-extract` click handler (starting at `document.getElementById("ep-extract").addEventListener("click", async () => {`):

```js
  document.getElementById("ep-extract").addEventListener("click", async () => {
    if (!_videoPath) return;
    const start = parseInt(document.getElementById("ep-start").value, 10);
    const keyFrame = start + 200;
    const postfix = document.getElementById("ep-postfix").value.trim();

    // Capture before await — guards against navigation during the fetch
    const capturedIdx = _detectionIdx;
    const capturedVideoPath = _videoPath;

    const body = { video_path: capturedVideoPath, key_frame: keyFrame };
    if (postfix) body.postfix = postfix;

    try {
      const resp = await fetch("/clip-cutter/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: resp.statusText }));
        setStatus("Extract error: " + err.error);
        return;
      }
      const data = await resp.json();
      setStatus("Clip extracted");
      if (capturedIdx !== null && typeof detections !== "undefined" && detections[capturedIdx]) {
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
      }
      // Only update the player UI if the user hasn't navigated to a different detection
      if (_detectionIdx === capturedIdx) {
        document.getElementById("ep-extract").style.display = "none";
        document.getElementById("ep-rename-extract").style.display = "";
        document.getElementById("ep-rename-extract").disabled = false;
        document.getElementById("ep-delete-extract").style.display = "";
        document.getElementById("ep-set-kf").disabled = true;
        document.getElementById("ep-reject").disabled = true;
      }
    } catch (e) { setStatus("Network error: " + e.message); }
  });
```

- [ ] **Step 4: Fix the `ep-rename-extract` handler — capture before await**

Replace the entire `ep-rename-extract` click handler:

```js
  document.getElementById("ep-rename-extract").addEventListener("click", async () => {
    if (_detectionIdx === null || typeof detections === "undefined") return;

    // Capture before await
    const capturedIdx = _detectionIdx;
    const det = detections[capturedIdx];
    const aviPath = det?.extract_avi_path;
    if (!aviPath) { setStatus("No extract path recorded"); return; }
    const postfix = document.getElementById("ep-postfix").value.trim();

    try {
      const resp = await fetch("/clip-cutter/extract/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ avi_path: aviPath, postfix }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: resp.statusText }));
        setStatus("Rename error: " + err.error);
        return;
      }
      const data = await resp.json();
      det.extract_avi_path = data.avi_path;
      det.extract_postfix = postfix || null;
      const card = document.getElementById("card-" + capturedIdx);
      if (card) {
        const nameEl = card.querySelector(".result-name");
        if (nameEl) nameEl.textContent = data.avi_path.split("/").pop();
      }
      if (typeof saveDetections === "function") saveDetections();
      setStatus("Renamed → " + data.avi_path.split("/").pop());
    } catch (e) { setStatus("Network error: " + e.message); }
  });
```

- [ ] **Step 5: Rebuild and run the full suite**

```bash
docker compose down && docker compose up -d --build 2>&1 | tail -4
python -m pytest tests/test_ui.py -q 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add clip-cutter/static/enhanced_player.js clip-cutter/tests/test_ui.py
git commit -m "fix: capture _detectionIdx before await in extract/rename handlers to prevent race condition"
```

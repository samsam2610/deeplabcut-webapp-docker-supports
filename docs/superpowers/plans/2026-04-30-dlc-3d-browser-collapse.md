# DLC-3D Browser Collapse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop auto-browsing to `videos/` on project load; add a Browse toggle button that expands/collapses the inline file browser and auto-collapses when a video is selected.

**Architecture:** Two file changes only — `card_3d_extract.html` gets a Browse button alongside the project display, and `dlc_3d.js` gets four targeted edits: remove the auto-browse call from `_loadProject`, show/hide the button in `_loadProject`/`_resetExtractorUI`, collapse the browser in `_selectVideo`, and wire a new toggle listener in `DOMContentLoaded`. An E2E test is written first to drive the HTML change.

**Tech Stack:** Vanilla JS ES6 module, Jinja2 HTML partial, pytest-playwright E2E tests (live server at container IP).

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dlc-3D/src/templates/partials/card_3d_extract.html` |
| Modify | `dlc-3D/src/static/dlc_3d.js` |
| Modify | `dlc-3D/tests/e2e/test_ui.py` |

---

### Task 1: Add Browse button to HTML (TDD)

**Files:**
- Modify: `dlc-3D/tests/e2e/test_ui.py`
- Modify: `dlc-3D/src/templates/partials/card_3d_extract.html`

**Context:** The extractor card lives at `dlc-3D/src/templates/partials/card_3d_extract.html`. The current project display (lines 13–16) is a single `<div>` with a span. We're replacing it with a flex row that also holds a Browse button. The button must start `display:none` (no project loaded yet).

The E2E tests live at `dlc-3D/tests/e2e/test_ui.py`. They connect to the live dlc-3d container at `http://172.26.0.5:5050/dlc-3d/` (via the `base_url` fixture in `conftest.py`). No project data is needed — we're just checking DOM structure.

- [ ] **Step 1: Write the failing E2E test**

Append this test to `dlc-3D/tests/e2e/test_ui.py`:

```python
def test_browse_btn_hidden_without_project(page, base_url):
    page.goto(base_url)
    page.locator("#btn-open-frame-extractor").click()
    display = page.evaluate("document.getElementById('dlc3d-browse-btn')?.style.display ?? 'missing'")
    assert display == "none"
```

- [ ] **Step 2: Run test to confirm it fails (button not in DOM yet)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/e2e/test_ui.py::test_browse_btn_hidden_without_project -v
```

Expected: FAIL — `display` is `'missing'` (element doesn't exist), assertion fails.

- [ ] **Step 3: Replace the project display div with a flex row + Browse button**

In `dlc-3D/src/templates/partials/card_3d_extract.html`, replace lines 13–16:

```html
      <div id="dlc3d-source-section">
        <div style="font-size:.75rem;color:var(--text-dim);margin-bottom:.35rem">
          Project: <span id="dlc3d-project-display" style="color:var(--text)">—</span>
        </div>
```

With:

```html
      <div id="dlc3d-source-section">
        <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.35rem">
          <div style="font-size:.75rem;color:var(--text-dim);flex:1">
            Project: <span id="dlc3d-project-display" style="color:var(--text)">—</span>
          </div>
          <button id="dlc3d-browse-btn" class="btn-sm btn-server-pick"
                  style="display:none" title="Browse project files">Browse</button>
        </div>
```

Also update the comment on line 17 from `<!-- Inline file browser (auto-opens when project loads) -->` to `<!-- Inline file browser (opened/closed by Browse button) -->`.

- [ ] **Step 4: Rebuild and run the test — confirm it passes**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose build dlc-3d && docker compose up -d dlc-3d
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/e2e/test_ui.py::test_browse_btn_hidden_without_project -v
```

Expected: PASS — `display` is `'none'`.

- [ ] **Step 5: Run full E2E suite to confirm no regressions**

```bash
python -m pytest tests/e2e/ -v
```

Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/partials/card_3d_extract.html dlc-3D/tests/e2e/test_ui.py
git commit -m "feat: add Browse button to extractor source section (hidden until project loads)"
```

---

### Task 2: Wire Browse button behavior in JS

**Files:**
- Modify: `dlc-3D/src/static/dlc_3d.js`

**Context:** Four edits to `dlc_3d.js`. Read the current file at `dlc-3D/src/static/dlc_3d.js` before starting.

1. **`_loadProject` (line 97):** Remove `_browseDir(_projectPath + "/videos");` and replace with showing the Browse button.

2. **`_resetExtractorUI` (after line 55 where `display` is reset):** Hide the Browse button.

3. **`_selectVideo` (after line 187 where player section is shown):** Collapse the file browser.

4. **`DOMContentLoaded` (after line 296):** Add Browse button toggle listener.

- [ ] **Step 1: Edit `_loadProject` — remove auto-browse, show Browse button**

Current lines 94–97:
```javascript
  _projectPath = data.project_path;
  document.getElementById("dlc3d-project-display").textContent = _projectPath;
  _setStatus("");
  _browseDir(_projectPath + "/videos");
```

Replace with:
```javascript
  _projectPath = data.project_path;
  document.getElementById("dlc3d-project-display").textContent = _projectPath;
  document.getElementById("dlc3d-browse-btn").style.display = "";
  _setStatus("");
```

- [ ] **Step 2: Edit `_resetExtractorUI` — hide Browse button**

Current lines 54–55:
```javascript
  const display = document.getElementById("dlc3d-project-display");
  if (display) display.textContent = "—";
```

Replace with:
```javascript
  const display = document.getElementById("dlc3d-project-display");
  if (display) display.textContent = "—";
  const browseBtn = document.getElementById("dlc3d-browse-btn");
  if (browseBtn) browseBtn.style.display = "none";
```

- [ ] **Step 3: Edit `_selectVideo` — collapse browser after video selection**

Current lines 184–187:
```javascript
  const empty = document.getElementById("dlc3d-session-empty");
  if (empty) empty.style.display = "none";

  document.getElementById("dlc3d-player-section").style.display = "";
```

Replace with:
```javascript
  const empty = document.getElementById("dlc3d-session-empty");
  if (empty) empty.style.display = "none";

  const browser = document.getElementById("dlc3d-file-browser");
  if (browser) browser.style.display = "none";

  document.getElementById("dlc3d-player-section").style.display = "";
```

- [ ] **Step 4: Edit `DOMContentLoaded` — add Browse button listener**

Current lines 293–296:
```javascript
  document.getElementById("btn-open-frame-extractor")?.addEventListener("click", _openCard);
  document.getElementById("btn-close-3d-extract")?.addEventListener("click", _closeCard);
  document.getElementById("ep-extract-btn")?.addEventListener("click", _extractFrame);
```

Replace with:
```javascript
  document.getElementById("btn-open-frame-extractor")?.addEventListener("click", _openCard);
  document.getElementById("btn-close-3d-extract")?.addEventListener("click", _closeCard);
  document.getElementById("ep-extract-btn")?.addEventListener("click", _extractFrame);

  document.getElementById("dlc3d-browse-btn")?.addEventListener("click", () => {
    const browser = document.getElementById("dlc3d-file-browser");
    if (browser.style.display === "none") {
      _browseDir(_projectPath);
    } else {
      browser.style.display = "none";
      const empty = document.getElementById("dlc3d-session-empty");
      if (empty) empty.style.display = "";
    }
  });
```

- [ ] **Step 5: Run backend tests to confirm nothing is broken**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py -q
```

Expected: `27 passed`

- [ ] **Step 6: Rebuild container and run full E2E suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose build dlc-3d && docker compose up -d dlc-3d
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/e2e/ -v
```

Expected: 9 passed.

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/dlc_3d.js
git commit -m "feat: Browse button toggles file browser, collapses on video select, no auto-browse on load"
```

# DLC-3D Extractor Overhaul — Design Spec

**Date:** 2026-04-30
**Status:** Approved

## Goal

Fix the extractor card's broken open/close behavior, replace the DLC-project-browser source section with a plain inline file browser, and add Playwright E2E tests.

---

## Section 1: Card Open/Close Fix

Remove the full-page-takeover pattern. Follow the annotator card pattern exactly.

- `_openCard()`: removes `hidden` from `#dlc-3d-extract-card` and scrolls to it. No other cards are touched.
- `_closeCard()`: adds `hidden` to `#dlc-3d-extract-card` only. No other cards are touched.

The extractor card starts with `class="card dlc-theme hidden"` (already the case) and is toggled independently like every other card.

---

## Section 2: Inline File Browser (replaces DLC project source section)

### HTML changes — `card_3d_extract.html`

**Remove:**
- The entire `#dlc3d-source-section` block (Browse Server button, `#dlc3d-project-path`, Rescan button, `#dlc3d-video-list`, `#dlc3d-session-empty`)
- The entire `#dlc3d-browser-modal` block

**Replace `#dlc3d-source-section` with:**

```html
<div id="dlc3d-source-section">
  <div style="font-size:.75rem;color:var(--text-dim);margin-bottom:.35rem">
    Project: <span id="dlc3d-project-display" style="color:var(--text)">—</span>
  </div>
  <div id="dlc3d-file-browser" class="fe-video-list"
    style="display:none;max-height:220px;overflow-y:auto;margin-bottom:.5rem">
    <!-- populated by dlc_3d.js _browseDir() -->
  </div>
  <p id="dlc3d-session-empty" class="explorer-empty">
    Load a DLC project via "Manage DLC Project".
  </p>
</div>
```

### JS changes — `dlc_3d.js`

**Remove:**
- `_renderSessions()` and `_makeVideoItem()` (session-list logic)
- `_browserNavigate()`, `_openBrowser()`, `_closeBrowser()`, `_browserCurrentPath` (modal browser logic)
- DOMContentLoaded listeners for: `dlc3d-btn-open-project`, `dlc3d-browser-close`, `dlc3d-browser-modal` click-outside, `dlc3d-btn-rescan`

**Update `_selectVideo(videoRel)`** — remove the `sessionKey` parameter; derive `_activeSession` from the video path stem using the same `{subject}_{date}` regex pattern the backend uses (`/^(.+?)_cam\d+_(\d{8})/`). Update the active-item highlight to use `#dlc3d-file-browser` rows instead of the deleted `#dlc3d-video-list`. Signature becomes `_selectVideo(videoRel)`.

```javascript
async function _selectVideo(videoRel) {
  _activeVideo = videoRel;
  // Derive session key from stem (mirrors backend _session_key_from_stem)
  const stem = videoRel.split("/").pop().replace(/\.[^.]+$/, "");
  const m = stem.match(/^(.+?)_cam\d+_(\d{8})/);
  _activeSession = m ? `${m[1]}_${m[2]}` : null;

  // Highlight active row
  document.querySelectorAll("#dlc3d-file-browser .fe-video-item").forEach(el => {
    el.classList.toggle("active", el.dataset.videoRel === videoRel);
  });
  // ... rest unchanged (show player section, fetch sibling, openPlayer, refreshLabeledFrames)
}
```

File rows in `_browseDir` should set `row.dataset.videoRel = rel` so the highlight works.

**Replace `_loadProject(path)`:**
```javascript
async function _loadProject(path) {
  const token = ++_loadToken;
  _setStatus("Loading project…");
  let data;
  try {
    const resp = await fetch("/dlc-3d/project", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    data = await resp.json();
    if (!resp.ok) { _setStatus(data.error || "Failed to load project"); return; }
  } catch (e) { _setStatus("Network error: " + e.message); return; }
  if (token !== _loadToken) return;

  _projectPath = data.project_path;
  document.getElementById("dlc3d-project-display").textContent = _projectPath;
  _setStatus("");
  _browseDir(_projectPath + "/videos");
}
```

**Add `_browseDir(path)`:**
```javascript
let _browserCurrentPath = null;

async function _browseDir(path) {
  const browser = document.getElementById("dlc3d-file-browser");
  const empty   = document.getElementById("dlc3d-session-empty");
  browser.innerHTML = '<span style="font-size:.8rem;color:var(--text-dim)">Loading…</span>';
  browser.style.display = "";
  if (empty) empty.style.display = "none";

  let data;
  try {
    const url = path
      ? `/dlc-3d/browse?path=${encodeURIComponent(path)}`
      : "/dlc-3d/browse";
    const resp = await fetch(url);
    data = await resp.json();
    if (!resp.ok) { browser.innerHTML = `<span style="font-size:.8rem;color:var(--text-dim)">${data.error || "Browse error"}</span>`; return; }
  } catch (e) { browser.innerHTML = `<span style="font-size:.8rem;color:var(--text-dim)">Network error</span>`; return; }

  _browserCurrentPath = data.path;
  browser.innerHTML = "";

  // "↑ .." row
  if (data.parent) {
    const upRow = document.createElement("div");
    upRow.className = "fe-video-item";
    const upSpan = document.createElement("span");
    upSpan.textContent = "↑  ..";
    upSpan.style.cssText = "color:var(--text-dim);font-style:italic";
    upRow.appendChild(upSpan);
    upRow.addEventListener("click", () => _browseDir(data.parent));
    browser.appendChild(upRow);
  }

  for (const entry of data.entries || []) {
    const row = document.createElement("div");
    row.className = "fe-video-item";

    const icon = document.createElement("span");
    const name = document.createElement("span");
    name.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
    name.textContent = entry.name;

    if (entry.type === "dir") {
      icon.textContent = "📁 ";
      row.append(icon, name);
      row.addEventListener("click", () => _browseDir(_browserCurrentPath + "/" + entry.name));
    } else if (entry.type === "file") {
      icon.textContent = "🎬 ";
      row.append(icon, name);
      row.addEventListener("click", () => {
        // Compute path relative to project root for API calls
        const rel = (_browserCurrentPath + "/" + entry.name).slice(_projectPath.length + 1);
        _selectVideo(rel);
      });
    } else {
      continue;
    }
    browser.appendChild(row);
  }

  if (browser.children.length === 0) {
    const msg = document.createElement("span");
    msg.style.cssText = "font-size:.8rem;color:var(--text-dim)";
    msg.textContent = "No files found.";
    browser.appendChild(msg);
  }
}
```

**Update `_resetExtractorUI()`:**
- Replace references to `dlc3d-video-list` / `dlc3d-project-path` / `dlc3d-btn-rescan` with `dlc3d-file-browser` / `dlc3d-project-display`
- Reset: clear `#dlc3d-file-browser` innerHTML, hide it, show `#dlc3d-session-empty`

### Backend — `routes.py`

The existing `/dlc-3d/browse` endpoint already returns `entries` with `type: "dir"` for directories. Add `type: "file"` for `.avi` and `.mp4` files (currently it only returns dirs and `config.yaml`). Specifically, in the `browse()` route, add a clause:

```python
elif entry.is_file() and entry.suffix.lower() in (".avi", ".mp4"):
    entries.append({"name": entry.name, "type": "file"})
```

### CSS — `dlc_3d.css`

Remove rules referencing deleted elements:
- `.dlc3d-session-header`, `.dlc3d-cam-badge`, `.dlc3d-clip-item` (session list classes, no longer used)

---

## Section 3: Playwright E2E Tests

### Setup

- `dlc-3D/tests/e2e/conftest.py` — `base_url` fixture pointing at `http://localhost:5050/dlc-3d/`; `page` fixture from `pytest-playwright`
- `dlc-3D/tests/e2e/test_ui.py` — test cases
- `dlc-3D/tests/e2e/__init__.py` — empty

Install: `pip install pytest-playwright` (Playwright 1.58 already installed). Run `playwright install chromium` once.

### Test cases (`test_ui.py`)

All tests connect to the live running dlc-3d service. No video data required — tests check page structure and card behavior.

1. `test_page_loads` — page returns 200, `<main class="cards">` visible
2. `test_dlc_project_card_visible` — `#dlc-project-card` present in DOM (not hidden initially — it's shown after project loads; we check it exists)
3. `test_extractor_card_hidden_by_default` — `#dlc-3d-extract-card` has class `hidden` on load
4. `test_open_extractor_card` — click `#btn-open-frame-extractor` → `#dlc-3d-extract-card` does NOT have class `hidden`
5. `test_close_extractor_card` — open extractor, click `#btn-close-3d-extract` → `#dlc-3d-extract-card` has class `hidden`; other cards unaffected
6. `test_other_cards_unaffected_by_open` — after clicking "Extract Frames", `#dlc-project-card` does NOT have class `hidden`
7. `test_empty_state_message` — with no project loaded, `#dlc3d-session-empty` is visible inside extractor card
8. `test_file_browser_hidden_without_project` — `#dlc3d-file-browser` has `display:none` when no project loaded

Run: `cd dlc-3D && python -m pytest tests/e2e/ -v` (headless by default with pytest-playwright)

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dlc-3D/src/templates/partials/card_3d_extract.html` |
| Modify | `dlc-3D/src/static/dlc_3d.js` |
| Modify | `dlc-3D/src/static/dlc_3d.css` |
| Modify | `dlc-3D/src/dlc_3d_bp/routes.py` |
| Create | `dlc-3D/tests/e2e/__init__.py` |
| Create | `dlc-3D/tests/e2e/conftest.py` |
| Create | `dlc-3D/tests/e2e/test_ui.py` |

---

## Testing

1. `docker compose restart dlc-3d`
2. Navigate to `http://localhost:5000/dlc-3d/` — DLC Project card visible, extractor card not visible
3. Click "Extract Frames" — extractor appears below, other cards stay visible
4. Close extractor — only extractor hides, grid intact
5. Load project via "Manage DLC Project" → open extractor → file browser auto-navigates to `videos/` folder
6. Click a folder → navigates in; click `↑ ..` → goes up; click a `.avi` → player loads
7. `cd dlc-3D && python -m pytest tests/e2e/ -v` — 8 tests pass
8. `python -m pytest tests/ -q` — 26 existing tests still pass

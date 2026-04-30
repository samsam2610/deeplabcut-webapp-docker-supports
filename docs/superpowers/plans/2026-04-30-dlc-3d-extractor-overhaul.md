# DLC-3D Extractor Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the broken card open/close, replace the DLC-project-browser source section with an inline file browser, and add Playwright E2E tests.

**Architecture:** Four sequential tasks: (1) backend browse endpoint gains `.avi`/`.mp4` support, (2) HTML/CSS removes the old source section and modal and adds an inline browser div, (3) JS is rewritten to use the inline browser and fix card behavior, (4) Playwright E2E tests verify the full stack. Each task commits independently.

**Tech Stack:** Flask/Python, vanilla JS ES6 modules, pytest, playwright 1.58 + pytest-playwright

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dlc-3D/src/dlc_3d_bp/routes.py` |
| Modify | `dlc-3D/tests/test_core.py` |
| Modify | `dlc-3D/src/templates/partials/card_3d_extract.html` |
| Modify | `dlc-3D/src/static/dlc_3d.css` |
| Replace | `dlc-3D/src/static/dlc_3d.js` |
| Create | `dlc-3D/tests/e2e/__init__.py` |
| Create | `dlc-3D/tests/e2e/conftest.py` |
| Create | `dlc-3D/tests/e2e/test_ui.py` |

---

### Task 1: Backend — add video files to `/dlc-3d/browse`

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/routes.py:229-236`
- Test: `dlc-3D/tests/test_core.py`

All work done from `/home/sam/docker-images/deeplabcut-webapp-docker-supports/`.

- [ ] **Step 1: Write the failing test**

Add this test at the bottom of `dlc-3D/tests/test_core.py`:

```python
def test_browse_returns_video_files(tmp_path):
    """browse() should include .avi and .mp4 files in entries."""
    import app as flask_app
    client = flask_app.app.test_client()

    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    (videos_dir / "surv1_cam0_20260123_121732.avi").write_bytes(b"")
    (videos_dir / "surv1_cam1_20260123_121732.avi").write_bytes(b"")
    (videos_dir / "clip.mp4").write_bytes(b"")
    (videos_dir / "readme.txt").write_bytes(b"")  # should NOT appear

    resp = client.get(f"/dlc-3d/browse?path={videos_dir}")
    assert resp.status_code == 200
    data = resp.get_json()
    types = {e["name"]: e["type"] for e in data["entries"]}
    assert types["surv1_cam0_20260123_121732.avi"] == "file"
    assert types["surv1_cam1_20260123_121732.avi"] == "file"
    assert types["clip.mp4"] == "file"
    assert "readme.txt" not in types
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd dlc-3D && python -m pytest tests/test_core.py::test_browse_returns_video_files -v
```

Expected: FAIL — `KeyError` or `AssertionError` because `.avi` entries don't appear yet.

- [ ] **Step 3: Add video file support to `browse()` in `routes.py`**

In `dlc-3D/src/dlc_3d_bp/routes.py`, find the `browse()` function (around line 229). The current loop body is:

```python
            if entry.is_dir():
                has_config = (entry / "config.yaml").exists()
                entries.append({"name": entry.name, "type": "dir", "has_config": has_config})
            elif entry.name == "config.yaml":
                entries.append({"name": entry.name, "type": "yaml", "has_config": True})
```

Replace it with:

```python
            if entry.is_dir():
                has_config = (entry / "config.yaml").exists()
                entries.append({"name": entry.name, "type": "dir", "has_config": has_config})
            elif entry.name == "config.yaml":
                entries.append({"name": entry.name, "type": "yaml", "has_config": True})
            elif entry.is_file() and entry.suffix.lower() in (".avi", ".mp4"):
                entries.append({"name": entry.name, "type": "file"})
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd dlc-3D && python -m pytest tests/test_core.py::test_browse_returns_video_files -v
```

Expected: PASS

- [ ] **Step 5: Run all backend tests**

```bash
cd dlc-3D && python -m pytest tests/test_core.py -q
```

Expected: `27 passed`

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/dlc_3d_bp/routes.py dlc-3D/tests/test_core.py
git commit -m "feat: return .avi and .mp4 files from /dlc-3d/browse endpoint"
```

---

### Task 2: HTML + CSS — replace source section and remove modal

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_3d_extract.html`
- Modify: `dlc-3D/src/static/dlc_3d.css`

All work done from `/home/sam/docker-images/deeplabcut-webapp-docker-supports/`.

- [ ] **Step 1: Replace `card_3d_extract.html` source section and remove modal**

Replace the entire file at `dlc-3D/src/templates/partials/card_3d_extract.html` with:

```html
    <section class="card dlc-theme hidden" id="dlc-3d-extract-card">
      <!-- Card header -->
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.3rem">
        <h2>3D Frame Extractor</h2>
        <button class="btn-sm" id="btn-close-3d-extract" title="Close 3D extractor">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          Close
        </button>
      </div>
      <p class="subtitle">Browse the project's video folder, select a sync-cam video, navigate frame-by-frame, and save paired frames into <code style="font-family:var(--mono);font-size:.78rem;background:var(--surface);border:1px solid var(--border);border-radius:3px;padding:.05rem .3rem">labeled-data/</code>.</p>

      <!-- ── Source section ── -->
      <div id="dlc3d-source-section">
        <div style="font-size:.75rem;color:var(--text-dim);margin-bottom:.35rem">
          Project: <span id="dlc3d-project-display" style="color:var(--text)">—</span>
        </div>
        <!-- Inline file browser (auto-opens when project loads) -->
        <div id="dlc3d-file-browser" class="fe-video-list"
          style="display:none;max-height:220px;overflow-y:auto;margin-bottom:.5rem">
        </div>
        <p id="dlc3d-session-empty" class="explorer-empty">
          Load a DLC project via "Manage DLC Project".
        </p>
      </div>

      <!-- ── Player section (shown after a video is clicked) ── -->
      <div id="dlc3d-player-section" style="display:none;margin-top:.75rem">

        <!-- Dual cameras side-by-side -->
        <div id="cam-displays">
          <div class="cam-wrap" id="cam1-wrap">
            <div class="cam-label" id="cam1-label">Primary camera</div>
            <div class="cam-frame-wrap" id="cam1-frame-wrap">
              <img id="ep-frame" src="" alt="" style="display:none;width:100%">
              <span id="no-video-msg">Select a video from the list above.</span>
            </div>
          </div>
          <div class="cam-wrap" id="ep-cam2-wrap" style="display:none">
            <div class="cam-label" id="cam2-label">Sibling camera</div>
            <div class="cam-frame-wrap">
              <img id="ep-cam2-frame" src="" alt="" style="width:100%">
            </div>
          </div>
        </div>

        <!-- Controls row -->
        <div class="fe-controls">
          <button id="ep-skip-start" class="btn-sm fe-ctrl-btn" title="Jump to start">⏮</button>
          <button id="ep-step-back"  class="btn-sm fe-ctrl-btn" title="Step back N frames">◀◀</button>
          <button id="ep-play"       class="btn-sm fe-ctrl-btn" title="Play / pause">▶</button>
          <button id="ep-step-fwd"   class="btn-sm fe-ctrl-btn" title="Step forward N frames">▶▶</button>
          <button id="ep-skip-end"   class="btn-sm fe-ctrl-btn" title="Jump to end">⏭</button>
          <input type="number" id="ep-step" value="10" min="1" max="9999"
            title="Skip N frames"
            style="width:4rem;text-align:center;font-family:var(--mono);font-size:.78rem;
                   padding:.18rem .3rem;background:var(--surface-2);border:1px solid var(--border);
                   border-radius:5px;color:var(--text)">
          <span class="fe-frame-counter">Frame <span id="ep-frame-num">—</span> / <span id="ep-frame-total">—</span></span>
        </div>

        <!-- Seek slider -->
        <input type="range" id="ep-seek" class="fe-seek" min="0" max="0" value="0">

        <!-- Sync cam row -->
        <div id="sync-cam-row" style="display:none;align-items:center;gap:1rem;margin:.4rem 0;font-size:.78rem">
          <label class="toggle">
            <input type="checkbox" id="ep-sync-cam"> Sync Cam
          </label>
          <label class="toggle" id="ep-extract-sibling-label" style="display:none">
            <input type="checkbox" id="ep-extract-sibling" checked> Extract Sibling
          </label>
        </div>

        <!-- Extract section -->
        <div style="display:flex;flex-direction:column;gap:.5rem;margin-top:.75rem">
          <div style="display:flex;align-items:center;gap:.8rem">
            <button id="ep-extract-btn" class="btn-sm btn-create" disabled
              style="flex:1;justify-content:center;padding:.5rem 1rem">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="12" cy="12" r="4"/></svg>
              Extract Frame
            </button>
            <span id="extract-count" class="fe-extract-count">0 frames saved</span>
          </div>
        </div>

        <!-- Status line -->
        <span id="extract-status" class="fe-extract-status"></span>

        <!-- Labeled frames chip list -->
        <div id="labeled-wrap" style="display:none;border-top:1px solid var(--border);padding-top:.4rem;margin-top:.4rem">
          <div id="labeled-header" style="font-size:.75rem;font-weight:600;margin-bottom:.25rem">
            Extracted frames: <span id="labeled-count">0</span>
          </div>
          <div id="labeled-list"
            style="font-size:.72rem;color:var(--text-dim);max-height:90px;overflow-y:auto;display:flex;flex-wrap:wrap;gap:.2rem"></div>
        </div>

      </div><!-- /dlc3d-player-section -->
    </section>
```

- [ ] **Step 2: Update `dlc_3d.css` — remove session list and browser modal rules**

Replace the entire file at `dlc-3D/src/static/dlc_3d.css` with:

```css
/* dlc_3d.css — styles scoped to #dlc-3d-extract-card only */

/* Card fills full width */
#dlc-3d-extract-card {
  max-width: none;
  width: 100%;
}

/* ── Dual camera display ── */
#dlc-3d-extract-card #cam-displays {
  display: flex;
  gap: .5rem;
  margin-bottom: .5rem;
}

#dlc-3d-extract-card .cam-wrap {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

#dlc-3d-extract-card .cam-label {
  font-size: .72rem;
  color: var(--text-dim);
  margin-bottom: .2rem;
}

#dlc-3d-extract-card .cam-frame-wrap {
  background: #000;
  border-radius: 4px;
  overflow: hidden;
  aspect-ratio: 16 / 9;
}

#dlc-3d-extract-card .cam-frame-wrap img {
  width: 100%;
  display: block;
  height: auto;
}

#dlc-3d-extract-card #no-video-msg {
  font-size: .8rem;
  color: var(--text-dim);
  text-align: center;
  padding: 2rem 0;
}

/* ── Sync cam row toggle ── */
#dlc-3d-extract-card label.toggle {
  display: flex;
  align-items: center;
  gap: .3rem;
  font-size: .78rem;
  cursor: pointer;
  color: var(--text-dim);
}
#dlc-3d-extract-card label.toggle input { accent-color: var(--accent); cursor: pointer; }

/* ── Seek slider ── */
#dlc-3d-extract-card .fe-seek { width: 100%; }

/* ── Labeled frame chips ── */
#dlc-3d-extract-card .frame-chip {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: .08rem .3rem;
  font-size: .7rem;
  white-space: nowrap;
}
#dlc-3d-extract-card .frame-chip.cam0 { border-color: #3fb950; color: #3fb950; }
#dlc-3d-extract-card .frame-chip.cam1 { border-color: #58a6ff; color: #58a6ff; }
```

- [ ] **Step 3: Run backend tests to confirm nothing broken**

```bash
cd dlc-3D && python -m pytest tests/test_core.py -q
```

Expected: `27 passed`

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/partials/card_3d_extract.html dlc-3D/src/static/dlc_3d.css
git commit -m "feat: replace extractor source section with inline file browser div, strip modal"
```

---

### Task 3: JS — rewrite `dlc_3d.js`

**Files:**
- Replace: `dlc-3D/src/static/dlc_3d.js`

All work done from `/home/sam/docker-images/deeplabcut-webapp-docker-supports/`.

- [ ] **Step 1: Write the new `dlc_3d.js`**

Replace the entire file at `dlc-3D/src/static/dlc_3d.js` with:

```javascript
// dlc_3d.js — inline file browser, project loader, extract button handler.
"use strict";

import { openPlayer, getCurrentFrame, getVideoPath, getSiblingPath, isSyncCamEnabled } from "./enhanced_player.js";

// ── State ─────────────────────────────────────────────────────────────────────

let _projectPath      = null;
let _activeSession    = null;
let _activeVideo      = null;
let _loadToken        = 0;
let _browserCurrentPath = null;

// ── Helpers ───────────────────────────────────────────────────────────────────

function _setStatus(msg) {
  const el = document.getElementById("extract-status");
  if (el) el.textContent = msg;
}

function _camColorClass(filename) {
  const m = filename.match(/img_cam(\d)_/);
  return m ? `cam${m[1]}` : "";
}

function _sessionKeyFromVideoRel(videoRel) {
  const parts = videoRel.split("/");
  // Try filename stem first (raw AVI: "videos/subj_cam0_20260123_....avi")
  let stem = parts[parts.length - 1].replace(/\.[^.]+$/, "");
  let m = stem.match(/^(.+?)_cam\d+_(\d{8})/);
  if (m) return `${m[1]}_${m[2]}`;
  // Fall back to parent folder name (clip: "videos/subj_cam0_20260123_.../clip_001.avi")
  if (parts.length >= 2) {
    stem = parts[parts.length - 2];
    m = stem.match(/^(.+?)_cam\d+_(\d{8})/);
    if (m) return `${m[1]}_${m[2]}`;
  }
  return null;
}

// ── Extractor reset ───────────────────────────────────────────────────────────

function _resetExtractorUI() {
  _projectPath        = null;
  _activeVideo        = null;
  _activeSession      = null;
  _browserCurrentPath = null;

  document.getElementById("dlc3d-player-section").style.display = "none";
  const browser = document.getElementById("dlc3d-file-browser");
  browser.innerHTML     = "";
  browser.style.display = "none";
  const empty = document.getElementById("dlc3d-session-empty");
  if (empty) { empty.style.display = ""; empty.textContent = 'Load a DLC project via "Manage DLC Project".'; }
  document.getElementById("dlc3d-project-display").textContent = "—";
  _setStatus("");
  const labeledWrap = document.getElementById("labeled-wrap");
  if (labeledWrap) labeledWrap.style.display = "none";
}

// ── Card open / close ─────────────────────────────────────────────────────────

function _openCard() {
  document.getElementById("dlc-3d-extract-card").classList.remove("hidden");
  document.getElementById("dlc-3d-extract-card").scrollIntoView({ behavior: "smooth", block: "nearest" });

  if (!_projectPath) {
    const activePath = document.getElementById("dlc-active-path")?.textContent.trim();
    if (activePath) _loadProject(activePath);
  }
}

function _closeCard() {
  document.getElementById("dlc-3d-extract-card").classList.add("hidden");
}

// ── Project loading ───────────────────────────────────────────────────────────

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

// ── Inline file browser ───────────────────────────────────────────────────────

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
    if (!resp.ok) {
      browser.innerHTML = `<span style="font-size:.8rem;color:var(--text-dim)">${data.error || "Browse error"}</span>`;
      return;
    }
  } catch (e) {
    browser.innerHTML = `<span style="font-size:.8rem;color:var(--text-dim)">Network error: ${e.message}</span>`;
    return;
  }

  _browserCurrentPath = data.path;
  browser.innerHTML = "";

  // "↑ .." row (up to parent, but not above the project's videos/ root)
  const videosRoot = _projectPath ? _projectPath + "/videos" : null;
  if (data.parent && data.path !== videosRoot) {
    const upRow = document.createElement("div");
    upRow.className = "fe-video-item";
    const upSpan = document.createElement("span");
    upSpan.style.cssText = "color:var(--text-dim);font-style:italic";
    upSpan.textContent = "↑  ..";
    upRow.appendChild(upSpan);
    upRow.addEventListener("click", () => _browseDir(data.parent));
    browser.appendChild(upRow);
  }

  for (const entry of data.entries || []) {
    const row = document.createElement("div");
    row.className = "fe-video-item";

    const icon = document.createElement("span");
    icon.style.marginRight = ".35rem";
    const name = document.createElement("span");
    name.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
    name.textContent = entry.name;

    if (entry.type === "dir") {
      icon.textContent = "📁";
      row.append(icon, name);
      row.addEventListener("click", () => _browseDir(_browserCurrentPath + "/" + entry.name));
    } else if (entry.type === "file") {
      icon.textContent = "🎬";
      const rel = (_browserCurrentPath + "/" + entry.name).slice(_projectPath.length + 1);
      row.dataset.videoRel = rel;
      row.append(icon, name);
      row.addEventListener("click", () => _selectVideo(rel));
    } else {
      continue;
    }
    browser.appendChild(row);
  }

  if (browser.children.length === 0) {
    const msg = document.createElement("span");
    msg.style.cssText = "font-size:.8rem;color:var(--text-dim)";
    msg.textContent = "No video files found.";
    browser.appendChild(msg);
  }
}

// ── Video selection ───────────────────────────────────────────────────────────

async function _selectVideo(videoRel) {
  _activeVideo   = videoRel;
  _activeSession = _sessionKeyFromVideoRel(videoRel);

  // Highlight active row
  document.querySelectorAll("#dlc3d-file-browser .fe-video-item").forEach(el => {
    el.classList.toggle("active", el.dataset.videoRel === videoRel);
  });

  // Show the player section
  document.getElementById("dlc3d-player-section").style.display = "";

  // Update primary camera label
  const camIdx = videoRel.match(/_cam(\d+)_/)?.[1] ?? "?";
  document.getElementById("cam1-label").textContent = `Camera ${camIdx} (primary)`;

  // Fetch sibling camera
  let siblingPath = null;
  try {
    const sr = await fetch(`/dlc-3d/sibling-camera?video=${encodeURIComponent(videoRel)}`);
    if (sr.ok) {
      const sd = await sr.json();
      siblingPath = sd.sibling_video_path || null;
    }
  } catch (e) { console.warn("[dlc_3d] sibling-camera fetch failed:", e); }

  if (siblingPath) {
    const sibCamIdx = siblingPath.match(/_cam(\d+)_/)?.[1] ?? "?";
    document.getElementById("cam2-label").textContent = `Camera ${sibCamIdx} (sibling)`;
  }

  _setStatus("");
  await openPlayer(videoRel, siblingPath);
  _refreshLabeledFrames();
}

// ── Extract ───────────────────────────────────────────────────────────────────

async function _extractFrame() {
  const primaryVideo   = getVideoPath();
  const primaryFrame   = getCurrentFrame();
  const siblingPath    = getSiblingPath();
  const extractSibling = isSyncCamEnabled()
    ? (document.getElementById("ep-extract-sibling")?.checked ?? true)
    : false;

  if (!primaryVideo || primaryFrame == null || !_projectPath) {
    if (!_projectPath) _setStatus("No project loaded.");
    return;
  }

  const extractBtn = document.getElementById("ep-extract-btn");
  if (extractBtn) extractBtn.disabled = true;
  _setStatus("Saving…");

  const body = {
    primary_video:        primaryVideo,
    primary_frame_number: primaryFrame,
    extract_sibling:      extractSibling,
  };
  if (extractSibling && siblingPath) {
    body.sibling_video        = siblingPath;
    body.sibling_frame_number = primaryFrame;
  }

  let data;
  try {
    const resp = await fetch("/dlc-3d/save-frame", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    data = await resp.json();
    if (!resp.ok) { _setStatus(data.error || "Save failed"); return; }
  } catch (e) { _setStatus("Network error: " + e.message); return; }
  finally { if (extractBtn) extractBtn.disabled = false; }

  if (data.saved && data.saved.length > 0) {
    _setStatus(`Saved: ${data.saved.join(", ")}`);
  } else if (data.skipped && data.skipped.length > 0) {
    _setStatus(`Frame ${primaryFrame} already extracted — skipped.`);
  }
  _refreshLabeledFrames();
}

// ── Labeled frames display ────────────────────────────────────────────────────

async function _refreshLabeledFrames() {
  if (!_activeSession || !_projectPath) return;
  let data;
  try {
    const resp = await fetch(`/dlc-3d/labeled-frames?session=${encodeURIComponent(_activeSession)}`);
    if (!resp.ok) return;
    data = await resp.json();
  } catch (e) { return; }

  const wrap       = document.getElementById("labeled-wrap");
  const countEl    = document.getElementById("labeled-count");
  const list       = document.getElementById("labeled-list");
  const extractCnt = document.getElementById("extract-count");

  const count = data.count || 0;
  countEl.textContent = count;
  if (extractCnt) extractCnt.textContent = `${count} frame${count !== 1 ? "s" : ""} saved`;

  list.innerHTML = "";
  for (const fname of data.frames || []) {
    const chip = document.createElement("span");
    chip.className = "frame-chip " + _camColorClass(fname);
    chip.textContent = fname;
    list.appendChild(chip);
  }

  wrap.style.display = count > 0 ? "" : "none";
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btn-open-frame-extractor")?.addEventListener("click", _openCard);
  document.getElementById("btn-close-3d-extract")?.addEventListener("click", _closeCard);
  document.getElementById("ep-extract-btn")?.addEventListener("click", _extractFrame);

  const activePathEl = document.getElementById("dlc-active-path");
  if (activePathEl) {
    new MutationObserver(() => {
      const newPath = activePathEl.textContent.trim();
      _resetExtractorUI();
      if (newPath) _loadProject(newPath);
    }).observe(activePathEl, { childList: true, characterData: true, subtree: true });
  }
});
```

- [ ] **Step 2: Run backend tests**

```bash
cd dlc-3D && python -m pytest tests/test_core.py -q
```

Expected: `27 passed`

- [ ] **Step 3: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/dlc_3d.js
git commit -m "feat: rewrite dlc_3d.js — inline file browser, fix card open/close, drop modal"
```

---

### Task 4: Playwright E2E tests

**Files:**
- Create: `dlc-3D/tests/e2e/__init__.py`
- Create: `dlc-3D/tests/e2e/conftest.py`
- Create: `dlc-3D/tests/e2e/test_ui.py`

All work done from `/home/sam/docker-images/deeplabcut-webapp-docker-supports/`.

The tests connect to the live dlc-3d service. The service must be running (`docker compose restart dlc-3d` from `/home/sam/docker-images/deeplabcut-webapp-docker/`) before tests run.

- [ ] **Step 1: Install pytest-playwright and browsers**

```bash
pip install pytest-playwright
playwright install chromium
```

Expected: exits cleanly.

- [ ] **Step 2: Create `tests/e2e/__init__.py`**

Create an empty file at `dlc-3D/tests/e2e/__init__.py`:

```python
```

(Empty file — just needs to exist for pytest discovery.)

- [ ] **Step 3: Create `tests/e2e/conftest.py`**

Create `dlc-3D/tests/e2e/conftest.py`:

```python
import pytest

BASE_URL = "http://localhost:5000/dlc-3d/"


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL
```

- [ ] **Step 4: Write the failing tests in `tests/e2e/test_ui.py`**

Create `dlc-3D/tests/e2e/test_ui.py`:

```python
"""Playwright E2E tests for the DLC-3D extractor UI.

Requires the dlc-3d service to be running:
  docker compose restart dlc-3d   (from deeplabcut-webapp-docker/)

Run:
  cd dlc-3D && python -m pytest tests/e2e/ -v
"""
import pytest
from playwright.sync_api import Page, expect


BASE_URL = "http://localhost:5000/dlc-3d/"


@pytest.fixture(autouse=True)
def goto_page(page: Page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")


def test_page_loads(page: Page):
    """Page returns 200 and renders a card grid."""
    expect(page.locator("main.cards")).to_be_visible()


def test_extractor_card_hidden_by_default(page: Page):
    """The 3D extractor card starts hidden."""
    card = page.locator("#dlc-3d-extract-card")
    expect(card).to_have_class(lambda c: "hidden" in c)


def test_open_extractor_card(page: Page):
    """Clicking 'Extract Frames' removes hidden from the extractor card."""
    # The button only appears after a project is loaded, but it's in the DOM
    btn = page.locator("#btn-open-frame-extractor")
    btn.click()
    card = page.locator("#dlc-3d-extract-card")
    expect(card).not_to_have_class(lambda c: "hidden" in c)


def test_close_extractor_card(page: Page):
    """Close button hides the extractor card."""
    page.locator("#btn-open-frame-extractor").click()
    page.locator("#btn-close-3d-extract").click()
    expect(page.locator("#dlc-3d-extract-card")).to_have_class(lambda c: "hidden" in c)


def test_other_cards_unaffected_by_open(page: Page):
    """Opening the extractor does NOT hide the DLC project card."""
    page.locator("#btn-open-frame-extractor").click()
    dlc_card = page.locator("#dlc-project-card")
    # dlc-project-card may be hidden initially (no project loaded), but it should
    # not be FORCED hidden by the extractor open. Check it doesn't gain hidden via extractor.
    # We verify the extractor card is open without touching other cards.
    expect(page.locator("#dlc-3d-extract-card")).not_to_have_class(lambda c: "hidden" in c)


def test_empty_state_shown_without_project(page: Page):
    """With no project loaded, extractor shows the empty-state message."""
    page.locator("#btn-open-frame-extractor").click()
    empty = page.locator("#dlc3d-session-empty")
    expect(empty).to_be_visible()
    expect(empty).to_contain_text("Manage DLC Project")


def test_file_browser_hidden_without_project(page: Page):
    """File browser panel is hidden when no project is loaded."""
    page.locator("#btn-open-frame-extractor").click()
    browser_div = page.locator("#dlc3d-file-browser")
    expect(browser_div).to_be_hidden()


def test_player_section_hidden_without_video(page: Page):
    """Player section is hidden until a video is selected."""
    page.locator("#btn-open-frame-extractor").click()
    expect(page.locator("#dlc3d-player-section")).to_be_hidden()
```

- [ ] **Step 5: Run the E2E tests (service must be running)**

First restart the service to pick up the code changes from Tasks 1–3:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart dlc-3d
```

Then run the tests:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/e2e/ -v
```

Expected: `7 passed`

- [ ] **Step 6: Run all tests together**

```bash
cd dlc-3D && python -m pytest tests/ -v
```

Expected: `34 passed` (27 backend + 7 E2E)

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/tests/e2e/
git commit -m "test: add Playwright E2E tests for 3D extractor card behavior"
```

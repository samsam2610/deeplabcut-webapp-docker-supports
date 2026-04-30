# DLC-3D Extract Card Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the 3D Frame Extractor card to match the main webapp's frame extractor style — top source section with session/camera list, full-width dual-camera player below, extract controls at the bottom — wired to open from the DLC Project card's "Extract Frames" button.

**Architecture:** Three files change: `card_3d_extract.html` is fully rewritten to a single-column layout reusing main webapp CSS classes (`fe-video-list`, `fe-controls`, `fe-seek`, `fe-extract-count`). `dlc_3d.js` replaces the sidebar tree renderer with a flat list renderer and swaps the card trigger from a session-bar button to `btn-open-frame-extractor`. `dlc_3d.css` drops all sidebar rules and adds scoped styles only for the dual-camera display, session headers, and chip colors. `enhanced_player.js`, `routes.py`, `dlc_3d.html`, and `docker-compose.yml` are unchanged.

**Tech Stack:** Vanilla JS ES modules, Jinja2 HTML partials, CSS custom properties (`var(--accent)`, `var(--border)`, `var(--surface-2)`, etc.) from the main webapp's `style.css`.

---

## File Map

| Action | Path |
|--------|------|
| Replace | `dlc-3D/src/templates/partials/card_3d_extract.html` |
| Replace | `dlc-3D/src/static/dlc_3d.js` |
| Replace | `dlc-3D/src/static/dlc_3d.css` |

---

## Context for all tasks

The dlc-3D module runs inside a Docker container (`dlc-3d` service) that is live-mounted — editing files in `dlc-3D/src/` takes effect immediately after `docker compose restart dlc-3d`. No rebuild needed.

The main webapp's `style.css` (loaded globally via `base.html`) already defines `.fe-video-list`, `.fe-video-item`, `.fe-controls`, `.fe-ctrl-btn`, `.fe-seek`, `.fe-frame-counter`, `.fe-extract-count`, `.fe-extract-status`, and `.explorer-empty`. The 3D card can use all of these classes without defining them in `dlc_3d.css`.

`enhanced_player.js` (unchanged) requires these exact element IDs in the DOM:
`ep-frame`, `ep-cam2-frame`, `ep-cam2-wrap`, `cam1-label`, `cam2-label`, `cam1-frame-wrap`, `ep-seek`, `ep-play`, `ep-step-back`, `ep-step-fwd`, `ep-skip-start`, `ep-skip-end`, `ep-frame-num`, `ep-frame-total`, `ep-step`, `ep-extract-btn`, `ep-sync-cam`, `ep-extract-sibling`, `ep-extract-sibling-label`, `extract-status`, `no-video-msg`, `sync-cam-row`.

---

## Task 1: Replace `card_3d_extract.html`

**Files:**
- Replace: `dlc-3D/src/templates/partials/card_3d_extract.html`

There are no pytest tests for HTML. Verification is manual (listed at the end of this task).

- [ ] **Step 1: Write the new card HTML**

Replace the entire contents of `dlc-3D/src/templates/partials/card_3d_extract.html` with:

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
      <p class="subtitle">Select a sync-cam video pair, navigate frame-by-frame, and save paired frames into <code style="font-family:var(--mono);font-size:.78rem;background:var(--surface);border:1px solid var(--border);border-radius:3px;padding:.05rem .3rem">labeled-data/</code>.</p>

      <!-- ── Source section ── -->
      <div id="dlc3d-source-section">
        <label style="display:block;font-size:.82rem;font-weight:500;margin-bottom:.5rem">DLC Project</label>
        <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.8rem">
          <button class="btn-sm" id="dlc3d-btn-open-project">Browse Server</button>
          <span id="dlc3d-project-path"
            style="flex:1;font-size:.78rem;color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
            No project loaded
          </span>
          <button class="btn-sm" id="dlc3d-btn-rescan" style="display:none">↺ Rescan</button>
        </div>

        <!-- Session / camera list — uses main webapp fe-video-list styles -->
        <div id="dlc3d-video-list" class="fe-video-list" style="display:none"></div>
        <p id="dlc3d-session-empty" class="explorer-empty">Load a project to see sessions.</p>
      </div>

      <!-- ── Player section (shown after a camera row is clicked) ── -->
      <div id="dlc3d-player-section" style="display:none;margin-top:.75rem">

        <!-- Dual cameras side-by-side -->
        <div id="cam-displays" style="display:flex;gap:.6rem;margin-bottom:.5rem">
          <div class="cam-wrap" id="cam1-wrap" style="flex:1;min-width:0">
            <div class="cam-label" id="cam1-label">Primary camera</div>
            <div class="cam-frame-wrap" id="cam1-frame-wrap">
              <img id="ep-frame" src="" alt="" style="display:none;width:100%">
              <span id="no-video-msg">Select a camera from the list above.</span>
            </div>
          </div>
          <div class="cam-wrap" id="ep-cam2-wrap" style="flex:1;min-width:0;display:none">
            <div class="cam-label" id="cam2-label">Sibling camera</div>
            <div class="cam-frame-wrap">
              <img id="ep-cam2-frame" src="" alt="" style="width:100%">
            </div>
          </div>
        </div>

        <!-- Controls row — uses main webapp fe-controls / fe-ctrl-btn styles -->
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

        <!-- Seek slider — uses main webapp fe-seek style -->
        <input type="range" id="ep-seek" class="fe-seek" min="0" max="0" value="0">

        <!-- Sync cam row — display managed by enhanced_player.js via id="sync-cam-row" -->
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

      <!-- Filesystem browser modal (fixed overlay) -->
      <div id="dlc3d-browser-modal">
        <div id="dlc3d-browser-box">
          <div id="dlc3d-browser-box-header">
            <span>Open DLC Project</span>
            <button class="btn-sm" id="dlc3d-browser-close">✕</button>
          </div>
          <div id="dlc3d-browser-path-bar">/</div>
          <div id="dlc3d-browser-list"></div>
        </div>
      </div>
    </section>
```

- [ ] **Step 2: Restart the dlc-3d container**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d
```

Expected: `Container deeplabcut-webapp-docker-dlc-3d-1  Started`

- [ ] **Step 3: Manually verify the HTML renders**

Navigate to `http://localhost:5000/dlc-3d/`. Open the DLC Project card if needed. Click **Extract Frames**. Confirm:
- 3D Frame Extractor card opens (may not work yet — JS not updated)
- Source section shows "DLC Project" label + Browse Server button + path + session-empty paragraph
- Player section is not yet visible

(The card trigger from btn-open-frame-extractor is wired in Task 2.)

- [ ] **Step 4: Run pytest to confirm no backend regression**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q
```

Expected: `26 passed` (all green, no failures)

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/partials/card_3d_extract.html
git commit -m "feat: rewrite card_3d_extract with fe-style single-column layout"
```

---

## Task 2: Replace `dlc_3d.js`

**Files:**
- Replace: `dlc-3D/src/static/dlc_3d.js`

- [ ] **Step 1: Write the new `dlc_3d.js`**

Replace the entire contents of `dlc-3D/src/static/dlc_3d.js` with:

```javascript
// dlc_3d.js — session browser, project loader, extract button handler.
"use strict";

import { openPlayer, getCurrentFrame, getVideoPath, getSiblingPath, isSyncCamEnabled } from "./enhanced_player.js";

// ── State ─────────────────────────────────────────────────────────────────────

let _projectPath   = null;
let _sessions      = {};
let _activeSession = null;
let _activeVideo   = null;

// ── Helpers ───────────────────────────────────────────────────────────────────

function _setStatus(msg) {
  const el = document.getElementById("extract-status");
  if (el) el.textContent = msg;
}

function _camColorClass(filename) {
  const m = filename.match(/img_cam(\d)_/);
  return m ? `cam${m[1]}` : "";
}

// ── Card open / close ─────────────────────────────────────────────────────────

function _openCard() {
  document.querySelectorAll(".card:not(#dlc-3d-extract-card)").forEach(c => c.classList.add("hidden"));
  document.getElementById("dlc-3d-extract-card").classList.remove("hidden");
  document.getElementById("dlc-3d-extract-card").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function _closeCard() {
  document.getElementById("dlc-3d-extract-card").classList.add("hidden");
}

// ── Project loading ───────────────────────────────────────────────────────────

async function _loadProject(path) {
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

  _projectPath = data.project_path;
  _sessions    = data.sessions || {};

  document.getElementById("dlc3d-project-path").textContent = _projectPath;
  document.getElementById("dlc3d-btn-rescan").style.display = "";
  _setStatus("");
  _renderSessions();
  // Player section stays hidden until a camera row is clicked
}

// ── Session / camera list rendering ──────────────────────────────────────────

function _renderSessions() {
  const list  = document.getElementById("dlc3d-video-list");
  const empty = document.getElementById("dlc3d-session-empty");

  if (!_sessions || Object.keys(_sessions).length === 0) {
    list.innerHTML = "";
    list.style.display = "none";
    if (empty) { empty.style.display = ""; empty.textContent = "No multi-camera videos found."; }
    return;
  }

  if (empty) empty.style.display = "none";
  list.innerHTML = "";
  list.style.display = "";

  for (const [sessionKey, cams] of Object.entries(_sessions).sort()) {
    // Session header (non-clickable label)
    const header = document.createElement("div");
    header.className = "dlc3d-session-header";
    header.textContent = sessionKey;
    list.appendChild(header);

    const camCount = Object.keys(cams).length;

    for (const [camKey, camData] of Object.entries(cams).sort()) {
      // Raw AVI row
      list.appendChild(_makeVideoItem(camData.avi, sessionKey, camCount > 1 ? camKey : null, false));

      // Clip rows (indented)
      for (const clipPath of (camData.clips || [])) {
        list.appendChild(_makeVideoItem(clipPath, sessionKey, null, true));
      }
    }
  }
}

function _makeVideoItem(videoRel, sessionKey, camBadgeText, isClip) {
  const item = document.createElement("div");
  item.className = "fe-video-item" + (isClip ? " dlc3d-clip-item" : "");
  item.dataset.videoRel  = videoRel;
  item.dataset.sessionKey = sessionKey;

  const videoSvg = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>`;
  const clipSvg  = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><polyline points="14 2 14 8 20 8"/></svg>`;

  const badgeHtml = camBadgeText
    ? `<span class="dlc3d-cam-badge">${camBadgeText}</span>`
    : "";
  const nameHtml = `<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${videoRel.split("/").pop()}</span>`;

  item.innerHTML = (isClip ? clipSvg : videoSvg) + badgeHtml + nameHtml;
  item.addEventListener("click", () => _selectVideo(videoRel, sessionKey));
  return item;
}

// ── Video selection ───────────────────────────────────────────────────────────

async function _selectVideo(videoRel, sessionKey) {
  _activeVideo   = videoRel;
  _activeSession = sessionKey;

  // Mark the clicked item active, clear others
  document.querySelectorAll("#dlc3d-video-list .fe-video-item").forEach(el => {
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

// ── Filesystem browser ────────────────────────────────────────────────────────

let _browserCurrentPath = null;

async function _browserNavigate(path) {
  let data;
  try {
    const url = path ? `/dlc-3d/browse?path=${encodeURIComponent(path)}` : "/dlc-3d/browse";
    const resp = await fetch(url);
    data = await resp.json();
    if (!resp.ok) { alert(data.error || "Browse error"); return; }
  } catch (e) { alert("Network error: " + e.message); return; }

  _browserCurrentPath = data.path;
  document.getElementById("dlc3d-browser-path-bar").textContent = data.path;

  const list = document.getElementById("dlc3d-browser-list");
  list.innerHTML = "";

  if (data.parent) {
    const upRow = document.createElement("div");
    upRow.className = "browser-entry browser-up";
    upRow.innerHTML = '<span class="entry-icon">↑</span> ..';
    upRow.addEventListener("click", () => _browserNavigate(data.parent));
    list.appendChild(upRow);
  }

  for (const entry of data.entries || []) {
    const row = document.createElement("div");
    if (entry.type === "dir") {
      row.className = "browser-entry" + (entry.has_config ? " has-config" : "");
      const iconEl = document.createElement("span");
      iconEl.className = "entry-icon";
      iconEl.textContent = entry.has_config ? "📂" : "📁";
      const nameEl = document.createElement("span");
      nameEl.textContent = entry.name;
      row.append(iconEl, nameEl);
      row.addEventListener("click", () => _browserNavigate(_browserCurrentPath + "/" + entry.name));
      if (entry.has_config) {
        const selectBtn = document.createElement("button");
        selectBtn.className = "btn-sm";
        selectBtn.style.cssText = "margin-left:auto;font-size:.7rem;padding:.15rem .4rem";
        selectBtn.textContent = "Select";
        selectBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          _closeBrowser();
          _loadProject(_browserCurrentPath + "/" + entry.name);
        });
        row.appendChild(selectBtn);
      }
    } else if (entry.type === "yaml") {
      row.className = "browser-entry yaml";
      const iconEl2 = document.createElement("span");
      iconEl2.className = "entry-icon";
      iconEl2.textContent = "✓";
      const nameEl2 = document.createElement("span");
      nameEl2.textContent = entry.name;
      row.append(iconEl2, nameEl2);
      row.addEventListener("click", () => {
        _closeBrowser();
        _loadProject(_browserCurrentPath);
      });
    }
    list.appendChild(row);
  }
}

function _openBrowser() {
  document.getElementById("dlc3d-browser-modal").classList.add("open");
  _browserNavigate(null);
}

function _closeBrowser() {
  document.getElementById("dlc3d-browser-modal").classList.remove("open");
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  // Open 3D extractor card via the DLC Project card's "Extract Frames" button
  document.getElementById("btn-open-frame-extractor")?.addEventListener("click", _openCard);

  document.getElementById("btn-close-3d-extract")?.addEventListener("click", _closeCard);
  document.getElementById("dlc3d-btn-open-project")?.addEventListener("click", _openBrowser);
  document.getElementById("dlc3d-browser-close")?.addEventListener("click", _closeBrowser);
  document.getElementById("dlc3d-browser-modal")?.addEventListener("click", (e) => {
    if (e.target === document.getElementById("dlc3d-browser-modal")) _closeBrowser();
  });

  document.getElementById("dlc3d-btn-rescan")?.addEventListener("click", async () => {
    _setStatus("Rescanning…");
    try {
      const resp = await fetch("/dlc-3d/project/rescan", { method: "POST" });
      const data = await resp.json();
      if (!resp.ok) { _setStatus(data.error || "Rescan failed"); return; }
      _sessions = data.sessions || {};
      _renderSessions();
      _setStatus("Rescan complete.");
    } catch (e) { _setStatus("Rescan failed: " + e.message); }
  });

  document.getElementById("ep-extract-btn")?.addEventListener("click", _extractFrame);
});
```

- [ ] **Step 2: Verify JS loads without errors**

After saving, open browser DevTools → Console on `/dlc-3d/`. There should be no errors on page load. The existing 14 cards' buttons should all still work.

- [ ] **Step 3: Run pytest**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q
```

Expected: `26 passed`

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/dlc_3d.js
git commit -m "feat: rewrite dlc_3d.js — flat session list, wire btn-open-frame-extractor"
```

---

## Task 3: Replace `dlc_3d.css`

**Files:**
- Replace: `dlc-3D/src/static/dlc_3d.css`

- [ ] **Step 1: Write the new CSS**

Replace the entire contents of `dlc-3D/src/static/dlc_3d.css` with:

```css
/* dlc_3d.css — styles scoped to #dlc-3d-extract-card only.
   Main webapp style.css already provides: fe-video-list, fe-video-item,
   fe-controls, fe-ctrl-btn, fe-seek, fe-frame-counter, fe-extract-count,
   fe-extract-status, explorer-empty, btn-sm, btn-create, toggle. */

/* Card width override */
#dlc-3d-extract-card {
  max-width: none;
  width: 100%;
}

/* ── Session list overrides ── */

/* Allow taller list than the default 220px */
#dlc-3d-extract-card #dlc3d-video-list {
  max-height: 260px;
}

/* Non-clickable session group header inside fe-video-list */
#dlc-3d-extract-card .dlc3d-session-header {
  font-size: .72rem;
  font-weight: 600;
  color: var(--text-dim);
  padding: .45rem .65rem .2rem;
  text-transform: uppercase;
  letter-spacing: .04em;
  cursor: default;
  user-select: none;
}

/* Camera badge pill (cam0 / cam1 label) */
#dlc-3d-extract-card .dlc3d-cam-badge {
  font-size: .68rem;
  background: var(--surface-3, #222330);
  border-radius: 3px;
  padding: .05rem .3rem;
  color: var(--text-dim);
  flex-shrink: 0;
}

/* Clip items — indented under their parent camera row */
#dlc-3d-extract-card .dlc3d-clip-item {
  padding-left: 2rem;
  font-size: .78rem;
}

/* ── Dual cameras ── */

#dlc-3d-extract-card #cam-displays {
  min-height: 180px;
}

#dlc-3d-extract-card .cam-wrap {
  display: flex;
  flex-direction: column;
  gap: .2rem;
  min-width: 0;
}

#dlc-3d-extract-card .cam-label {
  font-size: .72rem;
  color: var(--text-dim);
}

#dlc-3d-extract-card .cam-frame-wrap {
  flex: 1;
  background: #000;
  border-radius: 6px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 120px;
  border: 1px solid var(--border);
}

#dlc-3d-extract-card .cam-frame-wrap img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  display: block;
}

#dlc-3d-extract-card #no-video-msg {
  font-size: .8rem;
  color: var(--text-dim);
  text-align: center;
  padding: 1rem;
}

/* ── Sync cam / extract sibling toggles ── */

#dlc-3d-extract-card label.toggle {
  display: flex;
  align-items: center;
  gap: .3rem;
  font-size: .78rem;
  cursor: pointer;
  color: var(--text-dim);
}
#dlc-3d-extract-card label.toggle input { accent-color: var(--accent); cursor: pointer; }

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

/* ── Filesystem browser modal (fixed overlay) ── */

#dlc-3d-extract-card #dlc3d-browser-modal {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.65);
  z-index: 200;
  align-items: center;
  justify-content: center;
}
#dlc-3d-extract-card #dlc3d-browser-modal.open { display: flex; }
#dlc-3d-extract-card #dlc3d-browser-box {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  width: 560px;
  max-height: 70vh;
  display: flex;
  flex-direction: column;
}
#dlc-3d-extract-card #dlc3d-browser-box-header {
  padding: .55rem 1rem;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
#dlc-3d-extract-card #dlc3d-browser-box-header span { font-weight: 600; font-size: .85rem; }
#dlc-3d-extract-card #dlc3d-browser-path-bar {
  font-size: .72rem;
  color: var(--text-dim);
  padding: .25rem .75rem;
  border-bottom: 1px solid var(--border);
}
#dlc-3d-extract-card #dlc3d-browser-list { flex: 1; overflow-y: auto; }
#dlc-3d-extract-card .browser-entry {
  padding: .32rem .75rem;
  font-size: .8rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: .4rem;
}
#dlc-3d-extract-card .browser-entry:hover { background: var(--surface-3, #222330); }
#dlc-3d-extract-card .browser-entry .entry-icon { font-size: .85rem; }
#dlc-3d-extract-card .browser-entry.has-config .entry-icon { color: #3fb950; }
#dlc-3d-extract-card .browser-entry.yaml { color: #3fb950; font-weight: 600; }
#dlc-3d-extract-card .browser-up { color: var(--text-dim); font-style: italic; }
```

- [ ] **Step 2: Restart the dlc-3d container to pick up the new CSS**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d
```

Expected: `Container deeplabcut-webapp-docker-dlc-3d-1  Started`

- [ ] **Step 3: Full end-to-end manual verification**

1. Navigate to `http://localhost:5000/dlc-3d/`
2. Open the DLC Project card — click "Extract Frames" → 3D Frame Extractor card opens, other cards hide
3. Click "Browse Server" → filesystem browser modal opens, navigate to a DLC project → click "Select"
4. Session/camera list appears in the source section (scrollable, styled like the main webapp video list)
5. Click a camera row → player section appears, primary camera frame loads, camera label updates
6. Enable "Sync Cam" checkbox → sibling camera appears side-by-side at equal width
7. Use seek slider, step buttons, skip-start/end — frames navigate correctly
8. Click "Extract Frame" → extract-count updates ("1 frame saved"), chip appears in labeled-list below
9. Click "Close" → 3D extractor card hides
10. All other cards (Frame Labeler, Training Dataset, etc.) still work normally

- [ ] **Step 4: Run pytest**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q
```

Expected: `26 passed`

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/dlc_3d.css
git commit -m "feat: rewrite dlc_3d.css — single-column layout, drop sidebar rules"
```

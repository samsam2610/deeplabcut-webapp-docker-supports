# DLC-3D Card Layout Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dlc-3D module's custom full-page split-panel layout with the main webapp's card-based layout, so `/dlc-3d/` looks identical to the main webapp — same session bars, same 15-card grid — with `card_frame_extractor` swapped for a new `card_3d_extract` partial containing the sync-cam player.

**Architecture:** `dlc_3d.html` mirrors `index.html` (includes same session bars + 15 cards, replacing `card_frame_extractor` with `card_3d_extract.html`). `dlc_3d.js` injects a "3D Frame Extractor" button into the DLC session bar and handles card open/close. `dlc_3d.css` drops all full-page rules and re-scopes card-interior styles under `#dlc-3d-extract-card`. The 14 unchanged cards and all main webapp JS run normally — only the 3D extract card is dlc-3D-specific.

**Tech Stack:** Jinja2 template inheritance, vanilla JS ES modules, Docker volume mounts, pytest (backend only — frontend tested via curl + visual inspection).

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dlc-3D/src/templates/dlc_3d.html` |
| Create | `dlc-3D/src/templates/partials/card_3d_extract.html` |
| Replace | `dlc-3D/src/static/dlc_3d.css` |
| Replace | `dlc-3D/src/static/dlc_3d.js` |
| Modify | `deeplabcut-webapp-docker/docker-compose.yml` |

---

### Task 1: Create `card_3d_extract.html`

**Files:**
- Create: `dlc-3D/src/templates/partials/card_3d_extract.html`

The card follows the exact main webapp card pattern (`class="card dlc-theme hidden"`). Element IDs used by `enhanced_player.js` are preserved verbatim (those are marked with `← ep` in the comments below). IDs used only by `dlc_3d.js` get a `dlc3d-` prefix to avoid collisions with the main webapp's own elements.

- [ ] **Step 1: Create the partials directory**

Working directory: `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D`

```bash
mkdir -p src/templates/partials
```

- [ ] **Step 2: Create `card_3d_extract.html`**

Create `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/templates/partials/card_3d_extract.html` with this exact content:

```html
    <section class="card dlc-theme hidden" id="dlc-3d-extract-card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.3rem">
        <h2>3D Frame Extractor</h2>
        <button class="btn-sm" id="btn-close-3d-extract" title="Close 3D extractor">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          Close
        </button>
      </div>
      <p class="subtitle">Select a sync-cam video pair, navigate frame-by-frame, and save paired frames into <code style="font-family:var(--mono);font-size:.78rem;background:var(--surface);border:1px solid var(--border);border-radius:3px;padding:.05rem .3rem">labeled-data/</code>.</p>

      <!-- Project picker row — always visible inside card -->
      <div id="dlc3d-project-row" style="display:flex;align-items:center;gap:.5rem;margin:.6rem 0">
        <button class="btn-sm" id="dlc3d-btn-open-project">Browse Server</button>
        <span id="dlc3d-project-path"
          style="flex:1;font-size:.78rem;color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
          No project loaded
        </span>
        <button class="btn-sm" id="dlc3d-btn-rescan" style="display:none">↺ Rescan</button>
      </div>

      <!-- Player section — hidden until project loaded -->
      <div id="dlc3d-player-section" style="display:none">
        <div class="dlc3d-layout">

          <!-- Left: session browser -->
          <div id="dlc3d-session-panel">
            <div id="dlc3d-session-empty">Open a DLC project to begin.</div>
          </div>

          <!-- Right: sync-cam player -->
          <div id="dlc3d-player-area">
            <div id="cam-displays"><!-- ← ep -->
              <div class="cam-wrap" id="cam1-wrap">
                <div class="cam-label" id="cam1-label">Primary camera</div><!-- ← ep -->
                <div class="cam-frame-wrap" id="cam1-frame-wrap">
                  <img id="ep-frame" src="" alt="" style="display:none"><!-- ← ep -->
                  <span id="no-video-msg">Select a video or clip from the left panel.</span><!-- ← ep -->
                </div>
              </div>
              <div class="cam-wrap" id="ep-cam2-wrap" style="display:none"><!-- ← ep -->
                <div class="cam-label" id="cam2-label">Sibling camera</div><!-- ← ep -->
                <div class="cam-frame-wrap">
                  <img id="ep-cam2-frame" src="" alt=""><!-- ← ep -->
                </div>
              </div>
            </div>

            <div id="controls">
              <!-- Seek row -->
              <div class="ctrl-row">
                <input type="range" id="ep-seek" value="0" min="0" max="0"><!-- ← ep -->
                <span class="frame-info">
                  Frame <span id="ep-frame-num">—</span> / <span id="ep-frame-total">—</span><!-- ← ep -->
                </span>
              </div>
              <!-- Playback row -->
              <div class="ctrl-row">
                <button class="btn-sm" id="ep-skip-start" title="Jump to start">⏮</button><!-- ← ep -->
                <button class="btn-sm" id="ep-step-back" title="Step back">◀</button><!-- ← ep -->
                <button class="btn-sm" id="ep-play" title="Play / pause">▶</button><!-- ← ep -->
                <button class="btn-sm" id="ep-step-fwd" title="Step forward">▶</button><!-- ← ep -->
                <button class="btn-sm" id="ep-skip-end" title="Jump to end">⏭</button><!-- ← ep -->
                <label style="font-size:.75rem;color:var(--text-dim)">
                  Skip <input type="number" id="ep-step" value="10" min="1" max="9999"<!-- ← ep -->
                    style="width:3.2rem;background:var(--surface);border:1px solid var(--border);
                           color:var(--text);padding:.18rem .28rem;border-radius:3px;font-size:.78rem">
                </label>
                <button class="btn-sm btn-create" id="ep-extract-btn" disabled>Extract Frame</button><!-- ← ep -->
              </div>
              <!-- Sync cam row -->
              <div class="ctrl-row" id="sync-cam-row"><!-- ← ep -->
                <label class="toggle">
                  <input type="checkbox" id="ep-sync-cam"> Sync Cam<!-- ← ep -->
                </label>
                <label class="toggle" id="ep-extract-sibling-label" style="display:none"><!-- ← ep -->
                  <input type="checkbox" id="ep-extract-sibling" checked> Extract Sibling<!-- ← ep -->
                </label>
              </div>
            </div>

            <div id="extract-status" style="font-size:.75rem;color:var(--text-dim);min-height:1.1em"></div><!-- ← ep -->

            <!-- Labeled frames for current session -->
            <div id="labeled-wrap" style="display:none;border-top:1px solid var(--border);padding-top:.4rem;margin-top:.3rem">
              <div id="labeled-header" style="font-size:.75rem;font-weight:600;margin-bottom:.25rem">
                Extracted frames: <span id="labeled-count">0</span>
              </div>
              <div id="labeled-list" style="font-size:.72rem;color:var(--text-dim);max-height:90px;overflow-y:auto;display:flex;flex-wrap:wrap;gap:.2rem"></div>
            </div>
          </div><!-- /dlc3d-player-area -->

        </div><!-- /dlc3d-layout -->
      </div><!-- /dlc3d-player-section -->

      <!-- Filesystem browser modal -->
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

- [ ] **Step 3: Verify file was created**

```bash
wc -l /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/templates/partials/card_3d_extract.html
```

Expected: at least 60 lines.

- [ ] **Step 4: Run existing tests to confirm no regressions**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q
```

Expected: `26 passed`

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/partials/card_3d_extract.html
git commit -m "feat(dlc-3d): add card_3d_extract.html partial"
```

---

### Task 2: Rewrite `dlc_3d.html` to mirror `index.html`

**Files:**
- Modify: `dlc-3D/src/templates/dlc_3d.html`

Replace the current content (which has a custom header + split-panel layout) with a structure identical to the main webapp's `index.html` — same session bars, same card grid — substituting `card_3d_extract.html` where `card_frame_extractor.html` was. The `{% include %}` paths for all 14 unchanged cards resolve from the base image's `/app/templates/partials/` without any copies needed.

- [ ] **Step 1: Replace `dlc_3d.html` entirely**

Write `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/templates/dlc_3d.html` with:

```html
{% extends "base.html" %}

{% block title %}DLC-3D Extractor{% endblock %}

{% block extra_head %}
<link rel="stylesheet" href="{{ url_for('dlc_3d.static', filename='dlc_3d.css') }}">
{% endblock %}

{% block content %}
  {% include "partials/session_dlc_bar.html" %}
  {% include "partials/session_anipose_bar.html" %}

  <!-- ─── Main card grid ──────────────────────────────────────── -->
  <main class="cards">
    {% include "partials/card_dlc_project.html" %}
    {% include "partials/card_3d_extract.html" %}
    {% include "partials/card_frame_labeler.html" %}
    {% include "partials/card_training_dataset.html" %}
    {% include "partials/card_train_network.html" %}
    {% include "partials/card_analyze.html" %}
    {% include "partials/card_viewer.html" %}
    {% include "partials/card_annotator.html" %}
    {% include "partials/card_gpu_monitor.html" %}
    {% include "partials/card_dlc_config.html" %}
    {% include "partials/card_custom_script.html" %}
    {% include "partials/card_project_explorer.html" %}
    {% include "partials/card_session_actions.html" %}
    {% include "partials/card_config_editor.html" %}
    {% include "partials/card_admin.html" %}
  </main>
{% endblock %}

{% block scripts %}
{{ super() }}
<script type="module" src="{{ url_for('dlc_3d.static', filename='enhanced_player.js') }}"></script>
<script type="module" src="{{ url_for('dlc_3d.static', filename='dlc_3d.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: Verify the old header and main-layout divs are gone**

```bash
grep -c "main-layout\|btn-open-project\|dlc3d-root" \
  /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/templates/dlc_3d.html
```

Expected: `0`

- [ ] **Step 3: Run existing tests to confirm no regressions**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q
```

Expected: `26 passed`

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/dlc_3d.html
git commit -m "feat(dlc-3d): rewrite dlc_3d.html to mirror index.html card layout"
```

---

### Task 3: Rewrite `dlc_3d.css`

**Files:**
- Replace: `dlc-3D/src/static/dlc_3d.css`

Drop all full-page rules (`:root` / `body` / `header` / `.main-layout` / `.btn` / `.btn-primary` — the main webapp owns those). Re-scope everything under `#dlc-3d-extract-card`. Rename IDs to match the new card HTML. Add `--bg` and `--panel` aliases on the card root so the player's inline styles continue to resolve correctly.

- [ ] **Step 1: Replace `dlc_3d.css` entirely**

Write `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/dlc_3d.css` with:

```css
/* dlc_3d.css — styles scoped to #dlc-3d-extract-card only */

/* Alias old var names used in player inline styles */
#dlc-3d-extract-card {
  --bg: var(--surface);
  --panel: var(--surface-2);
}

/* ── Inner two-column layout ── */
#dlc-3d-extract-card .dlc3d-layout {
  display: flex;
  gap: .5rem;
  height: 420px;
  overflow: hidden;
  margin-top: .4rem;
}

/* ── Session panel (left) ── */
#dlc-3d-extract-card #dlc3d-session-panel {
  width: 210px;
  min-width: 140px;
  border-right: 1px solid var(--border);
  overflow-y: auto;
  padding: .4rem;
  display: flex;
  flex-direction: column;
  gap: .25rem;
}
#dlc-3d-extract-card #dlc3d-session-empty {
  font-size: .75rem;
  color: var(--text-dim);
  padding: .5rem;
}
#dlc-3d-extract-card .session-group {
  border: 1px solid var(--border);
  border-radius: 5px;
  overflow: hidden;
}
#dlc-3d-extract-card .session-header {
  font-size: .8rem;
  font-weight: 600;
  padding: .3rem .55rem;
  background: var(--surface-2);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: .35rem;
}
#dlc-3d-extract-card .session-header:hover { background: var(--surface-3, #21262d); }
#dlc-3d-extract-card .session-body { display: none; }
#dlc-3d-extract-card .session-body.open { display: block; }
#dlc-3d-extract-card .cam-row {
  padding: .22rem .55rem .22rem 1.1rem;
  font-size: .78rem;
  color: var(--text-dim);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: .4rem;
}
#dlc-3d-extract-card .cam-row:hover { background: var(--surface-3, #21262d); color: var(--text); }
#dlc-3d-extract-card .cam-row.active { background: #1f3a5c; color: var(--accent); }
#dlc-3d-extract-card .clip-section { padding-left: 1.6rem; }
#dlc-3d-extract-card .clip-header {
  font-size: .72rem;
  color: var(--text-dim);
  padding: .15rem .4rem;
  font-style: italic;
}
#dlc-3d-extract-card .clip-row {
  padding: .18rem .4rem;
  font-size: .75rem;
  color: var(--text-dim);
  cursor: pointer;
  border-radius: 3px;
}
#dlc-3d-extract-card .clip-row:hover { background: var(--surface-3, #21262d); color: var(--text); }
#dlc-3d-extract-card .clip-row.active { background: #1f3a5c; color: var(--accent); }
#dlc-3d-extract-card .cam-badge {
  font-size: .68rem;
  background: var(--surface-3, #21262d);
  border-radius: 3px;
  padding: .05rem .3rem;
  color: var(--text-dim);
}

/* ── Player area (right) ── */
#dlc-3d-extract-card #dlc3d-player-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  gap: .35rem;
  min-width: 0;
}
#dlc-3d-extract-card #cam-displays {
  display: flex;
  gap: .6rem;
  flex: 1;
  min-height: 0;
}
#dlc-3d-extract-card .cam-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: .2rem;
  min-width: 0;
  min-height: 0;
}
#dlc-3d-extract-card .cam-label { font-size: .72rem; color: var(--text-dim); }
#dlc-3d-extract-card .cam-frame-wrap {
  flex: 1;
  background: #000;
  border-radius: 4px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
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
  width: 100%;
}

/* ── Controls ── */
#dlc-3d-extract-card #controls {
  display: flex;
  flex-direction: column;
  gap: .3rem;
  flex-shrink: 0;
}
#dlc-3d-extract-card .ctrl-row {
  display: flex;
  align-items: center;
  gap: .35rem;
  flex-wrap: wrap;
}
#dlc-3d-extract-card #ep-seek {
  flex: 1;
  min-width: 80px;
  accent-color: var(--accent);
}
#dlc-3d-extract-card .frame-info {
  font-size: .75rem;
  color: var(--text-dim);
  white-space: nowrap;
}

/* ── Sync cam row ── */
#dlc-3d-extract-card #sync-cam-row {
  display: none;
  align-items: center;
  gap: .75rem;
}
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

/* ── Browser modal ── */
#dlc3d-browser-modal {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.65);
  z-index: 200;
  align-items: center;
  justify-content: center;
}
#dlc3d-browser-modal.open { display: flex; }
#dlc3d-browser-box {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  width: 560px;
  max-height: 70vh;
  display: flex;
  flex-direction: column;
}
#dlc3d-browser-box-header {
  padding: .55rem 1rem;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
#dlc3d-browser-box-header span { font-weight: 600; font-size: .85rem; }
#dlc3d-browser-path-bar {
  font-size: .72rem;
  color: var(--text-dim);
  padding: .25rem .75rem;
  border-bottom: 1px solid var(--border);
}
#dlc3d-browser-list { flex: 1; overflow-y: auto; }
#dlc-3d-extract-card .browser-entry {
  padding: .32rem .75rem;
  font-size: .8rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: .4rem;
}
#dlc-3d-extract-card .browser-entry:hover { background: var(--surface-3, #21262d); }
#dlc-3d-extract-card .browser-entry .entry-icon { font-size: .85rem; }
#dlc-3d-extract-card .browser-entry.has-config .entry-icon { color: #3fb950; }
#dlc-3d-extract-card .browser-entry.yaml { color: #3fb950; font-weight: 600; }
#dlc-3d-extract-card .browser-up { color: var(--text-dim); font-style: italic; }
```

- [ ] **Step 2: Verify no `#dlc3d-root` references remain**

```bash
grep -c "dlc3d-root" /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/dlc_3d.css
```

Expected: `0`

- [ ] **Step 3: Run existing tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q
```

Expected: `26 passed`

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/dlc_3d.css
git commit -m "feat(dlc-3d): re-scope CSS under #dlc-3d-extract-card, drop full-page rules"
```

---

### Task 4: Rewrite `dlc_3d.js`

**Files:**
- Replace: `dlc-3D/src/static/dlc_3d.js`

Rename all element IDs that changed (`session-panel` → `dlc3d-session-panel`, `session-empty` → `dlc3d-session-empty`, `project-path-display` → `dlc3d-project-path`, `btn-rescan` → `dlc3d-btn-rescan`, `btn-open-project` → `dlc3d-btn-open-project`, `browser-modal` → `dlc3d-browser-modal`, `browser-close` → `dlc3d-browser-close`, `browser-path-bar` → `dlc3d-browser-path-bar`, `browser-list` → `dlc3d-browser-list`). Add `_openCard`/`_closeCard` helpers and inject "3D Frame Extractor" button into the DLC session bar at init. Show `#dlc3d-player-section` once a project loads.

- [ ] **Step 1: Replace `dlc_3d.js` entirely**

Write `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/dlc_3d.js` with:

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
  document.getElementById("extract-status").textContent = msg;
}

function _camColorClass(filename) {
  const m = filename.match(/img_cam(\d)_/);
  return m ? `cam${m[1]}` : "";
}

// ── Card open / close ─────────────────────────────────────────────────────────

function _openCard() {
  document.querySelectorAll(".card:not(#dlc-3d-extract-card)").forEach(c => c.classList.add("hidden"));
  document.getElementById("dlc-3d-extract-card").classList.remove("hidden");
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
  document.getElementById("dlc3d-player-section").style.display = "";
  _setStatus("");
  _renderSessions();
}

// ── Session browser rendering ─────────────────────────────────────────────────

function _renderSessions() {
  const panel = document.getElementById("dlc3d-session-panel");
  const empty = document.getElementById("dlc3d-session-empty");

  if (!_sessions || Object.keys(_sessions).length === 0) {
    panel.innerHTML = "";
    if (empty) { empty.textContent = "No multi-camera videos found."; panel.appendChild(empty); }
    return;
  }
  if (empty) empty.remove();

  panel.innerHTML = "";
  for (const [sessionKey, cams] of Object.entries(_sessions).sort()) {
    const group  = document.createElement("div");
    group.className = "session-group";

    const header = document.createElement("div");
    header.className = "session-header";
    header.textContent = "▶ " + sessionKey;
    group.appendChild(header);

    const body = document.createElement("div");
    body.className = "session-body";

    for (const [camKey, camData] of Object.entries(cams).sort()) {
      const camRow = document.createElement("div");
      camRow.className = "cam-row";
      camRow.dataset.videoRel = camData.avi;
      camRow.innerHTML = `<span class="cam-badge">${camKey}</span><span>${camData.avi.split("/").pop()}</span>`;
      camRow.addEventListener("click", () => _selectVideo(camData.avi, sessionKey));
      body.appendChild(camRow);

      if (camData.clips && camData.clips.length > 0) {
        const clipSection = document.createElement("div");
        clipSection.className = "clip-section";
        const clipHeader = document.createElement("div");
        clipHeader.className = "clip-header";
        clipHeader.textContent = `${camData.clips.length} clip(s)`;
        clipSection.appendChild(clipHeader);
        for (const clipPath of camData.clips) {
          const clipRow = document.createElement("div");
          clipRow.className = "clip-row";
          clipRow.dataset.videoRel = clipPath;
          clipRow.textContent = clipPath.split("/").pop();
          clipRow.addEventListener("click", () => _selectVideo(clipPath, sessionKey));
          clipSection.appendChild(clipRow);
        }
        body.appendChild(clipSection);
      }
    }

    header.addEventListener("click", () => {
      body.classList.toggle("open");
      header.textContent = (body.classList.contains("open") ? "▼ " : "▶ ") + sessionKey;
    });

    group.appendChild(body);
    panel.appendChild(group);
  }
}

// ── Video selection ───────────────────────────────────────────────────────────

async function _selectVideo(videoRel, sessionKey) {
  _activeVideo   = videoRel;
  _activeSession = sessionKey;

  document.querySelectorAll(".cam-row, .clip-row").forEach(el => {
    el.classList.toggle("active", el.dataset.videoRel === videoRel);
  });

  const camIdx = videoRel.match(/_cam(\d+)_/)?.[1] ?? "?";
  document.getElementById("cam1-label").textContent = `Camera ${camIdx} (primary)`;

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

  const wrap    = document.getElementById("labeled-wrap");
  const countEl = document.getElementById("labeled-count");
  const list    = document.getElementById("labeled-list");

  countEl.textContent = data.count || 0;
  list.innerHTML = "";

  for (const fname of data.frames || []) {
    const chip = document.createElement("span");
    chip.className = "frame-chip " + _camColorClass(fname);
    chip.textContent = fname;
    list.appendChild(chip);
  }

  wrap.style.display = data.count > 0 ? "" : "none";
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
  // Inject "3D Frame Extractor" button into DLC session bar
  const dlcBarBtns = document.querySelector("#dlc-bar .session-btns");
  if (dlcBarBtns) {
    const btn = document.createElement("button");
    btn.className = "btn-sm btn-create";
    btn.id = "btn-open-3d-extract";
    btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="12" cy="12" r="4"/></svg> 3D Frame Extractor`;
    dlcBarBtns.appendChild(btn);
    btn.addEventListener("click", _openCard);
  }

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
      _sessions = data.sessions || {};
      _renderSessions();
      _setStatus("Rescan complete.");
    } catch (e) { _setStatus("Rescan failed: " + e.message); }
  });

  document.getElementById("ep-extract-btn")?.addEventListener("click", _extractFrame);
});
```

- [ ] **Step 2: Verify no old ID references remain**

```bash
grep -c "session-panel\b\|session-empty\b\|project-path-display\|btn-rescan\b\|btn-open-project\b\|browser-modal\b\|browser-close\b\|browser-path-bar\b\|browser-list\b" \
  /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/dlc_3d.js
```

Expected: `0`

- [ ] **Step 3: Run existing tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q
```

Expected: `26 passed`

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/dlc_3d.js
git commit -m "feat(dlc-3d): rewrite dlc_3d.js for card layout, inject session bar button"
```

---

### Task 5: Update docker-compose and smoke-test

**Files:**
- Modify: `deeplabcut-webapp-docker/docker-compose.yml`

Add a volume mount for the new card partial. The existing `dlc_3d.html` mount (single file) stays. Restart the container and verify the page renders correctly.

- [ ] **Step 1: Add the card partial volume mount**

In `/home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml`, find the `dlc-3d` service's `volumes:` block. It currently ends with:

```yaml
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/static:/app/static
```

Add this line immediately after it:

```yaml
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/templates/partials/card_3d_extract.html:/app/templates/partials/card_3d_extract.html
```

The full `dlc-3d` service block should look like:

```yaml
  dlc-3d:
    build:
      context: ../
      dockerfile: deeplabcut-webapp-docker-supports/dlc-3D/Dockerfile
    image: dlc-3d:latest
    volumes:
      - /home/sam/data-disk/Parra-Data:/user-data/Parra-Data/Disk
      - /home/sam/synology/Parra-Lab-Data:/user-data/Parra-Data/Cloud
      - /home/sam/data-mount-dir:/user-data/Martin-Data/USB
      - /home/sam/Parra-Lab-Data-NAS:/user-data/NAS-Data-Share
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/app.py:/app/app.py
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/dlc_3d_bp:/app/dlc_3d_bp
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/config.py:/app/config.py
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/viewer.py:/app/viewer.py
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/templates/dlc_3d.html:/app/templates/dlc_3d.html
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/static:/app/static
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/templates/partials/card_3d_extract.html:/app/templates/partials/card_3d_extract.html
    environment:
      - AUTH_DISABLED=true
      - DLC_3D_PORT=5050
    networks:
      - default
    restart: unless-stopped
```

- [ ] **Step 2: Validate the YAML**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose config --quiet
```

Expected: exits 0 with no output.

- [ ] **Step 3: Restart the dlc-3d container (live mounts — no rebuild needed)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d
docker compose logs dlc-3d --tail 20
```

Expected in logs: `[INFO] Listening at: http://0.0.0.0:5050` (gunicorn startup). No errors.

- [ ] **Step 4: Smoke-test the page returns 200**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5050/dlc-3d/
```

Expected: `200`

- [ ] **Step 5: Smoke-test the static CSS and JS assets load**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5050/dlc-3d/static/dlc_3d.css && echo
curl -s -o /dev/null -w "%{http_code}" http://localhost:5050/dlc-3d/static/dlc_3d.js && echo
curl -s -o /dev/null -w "%{http_code}" http://localhost:5050/dlc-3d/static/enhanced_player.js && echo
```

Expected: `200` for all three.

- [ ] **Step 6: Smoke-test the card partial is rendered in the page HTML**

```bash
curl -s http://localhost:5050/dlc-3d/ | grep -c "dlc-3d-extract-card"
```

Expected: at least `1` (the card section element is present in the HTML).

- [ ] **Step 7: Smoke-test the session bar and grid are rendered**

```bash
curl -s http://localhost:5050/dlc-3d/ | grep -c "session-bar dlc-theme"
curl -s http://localhost:5050/dlc-3d/ | grep -c "class=\"cards\""
```

Expected: `1` for both.

- [ ] **Step 8: Run full test suite one final time**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q
```

Expected: `26 passed`

- [ ] **Step 9: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add docker-compose.yml
git commit -m "feat(dlc-3d): add card_3d_extract.html volume mount to docker-compose"
```

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add docs/superpowers/plans/2026-04-30-dlc-3d-card-layout.md
git commit -m "docs(dlc-3d): add card layout implementation plan"
```

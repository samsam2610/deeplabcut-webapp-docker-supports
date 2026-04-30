# DLC-3D Project Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the active DLC project changes in "Manage DLC Project", the 3D Frame Extractor card resets and auto-loads the new project.

**Architecture:** `dlc_3d.js` watches `#dlc-active-path` via `MutationObserver` — this span is already set by `applyDlcProjectState()` in `dlc_project.js` on every project load/clear. On change, a `_resetExtractorUI()` helper clears all extractor state and DOM, then auto-calls `_loadProject()` if a new path is present. `_openCard()` also auto-loads on first open.

**Tech Stack:** Vanilla JS ES6 module, MutationObserver API, Flask (backend unchanged)

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dlc-3D/src/static/dlc_3d.js` |

No other files change.

---

### Task 1: Add `_resetExtractorUI`, wire MutationObserver, auto-load in `_openCard`

**Files:**
- Modify: `dlc-3D/src/static/dlc_3d.js`

There are no JS unit tests in this project — testing is manual (see Step 4). The 26 existing backend pytest tests remain unaffected and must still pass.

- [ ] **Step 1: Read the current file**

```bash
cat /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/dlc_3d.js
```

Confirm the file starts with:
```javascript
// dlc_3d.js — session browser, project loader, extract button handler.
"use strict";
import { openPlayer, getCurrentFrame, getVideoPath, getSiblingPath, isSyncCamEnabled } from "./enhanced_player.js";
```

- [ ] **Step 2: Add `_resetExtractorUI()` after the `_camColorClass` helper**

Insert this function after the existing `_camColorClass` helper (currently around line 23) and before `_openCard`:

```javascript
// ── Extractor reset ───────────────────────────────────────────────────────────

function _resetExtractorUI() {
  _projectPath   = null;
  _sessions      = {};
  _activeVideo   = null;
  _activeSession = null;

  document.getElementById("dlc3d-player-section").style.display = "none";
  const list = document.getElementById("dlc3d-video-list");
  list.innerHTML     = "";
  list.style.display = "none";
  const empty = document.getElementById("dlc3d-session-empty");
  if (empty) { empty.style.display = ""; empty.textContent = "Load a project to see sessions."; }
  document.getElementById("dlc3d-project-path").textContent = "No project loaded";
  document.getElementById("dlc3d-btn-rescan").style.display = "none";
  _setStatus("");
  const labeledWrap = document.getElementById("labeled-wrap");
  if (labeledWrap) labeledWrap.style.display = "none";
}
```

- [ ] **Step 3: Modify `_openCard()` to auto-load on first open**

Replace the current `_openCard`:

```javascript
function _openCard() {
  document.querySelectorAll(".card:not(#dlc-3d-extract-card)").forEach(c => c.classList.add("hidden"));
  document.getElementById("dlc-3d-extract-card").classList.remove("hidden");
  document.getElementById("dlc-3d-extract-card").scrollIntoView({ behavior: "smooth", block: "nearest" });

  if (!_projectPath) {
    const activePath = document.getElementById("dlc-active-path")?.textContent.trim();
    if (activePath) _loadProject(activePath);
  }
}
```

- [ ] **Step 4: Add MutationObserver in `DOMContentLoaded`**

Inside the existing `document.addEventListener("DOMContentLoaded", () => { ... })` block, add these lines at the end (just before the closing `}`):

```javascript
  const activePathEl = document.getElementById("dlc-active-path");
  if (activePathEl) {
    new MutationObserver(() => {
      const newPath = activePathEl.textContent.trim();
      _resetExtractorUI();
      if (newPath) _loadProject(newPath);
    }).observe(activePathEl, { childList: true, characterData: true, subtree: true });
  }
```

- [ ] **Step 5: Run backend tests to confirm nothing is broken**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q
```

Expected: `26 passed`

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/dlc_3d.js
git commit -m "feat: auto-load and reset 3D extractor when DLC project changes"
```

- [ ] **Step 7: Manual smoke test**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d
```

Then in the browser at `http://localhost:5000/dlc-3d/`:

1. Load a DLC project via "Manage DLC Project" → click "Extract Frames" → extractor card opens with sessions already listed (no "Browse Server" step needed)
2. While the extractor is open, load a **different** project via "Manage DLC Project" → extractor resets and loads the new project's sessions automatically
3. Click "Clear" (×) on the DLC project → extractor resets to empty "Load a project to see sessions." state
4. Load a project again → extractor populates again

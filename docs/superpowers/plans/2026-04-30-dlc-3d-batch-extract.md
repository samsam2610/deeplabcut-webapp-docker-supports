# DLC-3D Batch Frame Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Extract Batch" feature to the DLC-3D Frame Extractor mirroring the main webapp's batch extract layout — Count + Step inputs, Extract Batch button, Stop button — that extracts `count` frames starting at the current position, advancing by `step` per iteration, with sibling cam in lock-step (so total saved = `count × 2` when sync sibling is enabled).

**Architecture:** Three small additive tasks. Task 1 adds the new HTML control row directly below the existing Extract Frame row. Task 2 adds an `epLoadFrameAt(n)` export to `enhanced_player.js` and updates `openPlayer()` to enable both extract buttons. Task 3 adds the batch loop logic to `dlc_3d.js` (`_extractBatch`, `_setBatchUIRunning`, listener wiring, reset). The existing `/dlc-3d/save-frame` endpoint already handles `extract_sibling` and de-duplicates by `(cam, frame_number)` — no backend changes needed.

**Tech Stack:** ES6 modules (`enhanced_player.js`, `dlc_3d.js`), HTML + inline styles (Jinja2 partial), Docker Compose for build/test. Existing endpoints `POST /dlc-3d/save-frame`, `GET /dlc-3d/video-info`, `GET /dlc-3d/labeled-frames` are unchanged.

---

## File Map

| File | What changes |
|------|-------------|
| `dlc-3D/src/templates/partials/card_3d_extract.html` | Task 1: insert new batch-extract row below existing Extract Frame row. |
| `dlc-3D/src/static/enhanced_player.js` | Task 2: add `epLoadFrameAt(n)` export; update `openPlayer()` to enable both extract buttons. |
| `dlc-3D/src/static/dlc_3d.js` | Task 3: add `_extractBatch`, `_setBatchUIRunning`, `_batchStopRequested` state, reset logic, listeners, import update. |

No backend, CSS, or test changes.

---

## Task 1: Add batch-extract HTML row

Insert a new row directly below the existing Extract Frame row containing Count input, Step input, Extract Batch button, and Stop button.

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_3d_extract.html`

- [ ] **Step 1: Insert the new batch row HTML**

Find the existing extract section (around lines 82–91):

```html
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
```

Replace with:

```html
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
          <div style="display:flex;align-items:center;gap:.6rem">
            <label style="display:flex;flex-direction:column;gap:.2rem;font-size:.78rem;color:var(--text-dim);flex-shrink:0">
              Count
              <input type="number" id="ep-batch-count" min="2" value="10"
                     style="width:4rem;text-align:center;font-family:var(--mono);font-size:.78rem;
                            padding:.18rem .3rem;background:var(--surface-2);border:1px solid var(--border);
                            border-radius:5px;color:var(--text)">
            </label>
            <label style="display:flex;flex-direction:column;gap:.2rem;font-size:.78rem;color:var(--text-dim);flex-shrink:0">
              Step
              <input type="number" id="ep-batch-step" min="1" value="1"
                     style="width:4rem;text-align:center;font-family:var(--mono);font-size:.78rem;
                            padding:.18rem .3rem;background:var(--surface-2);border:1px solid var(--border);
                            border-radius:5px;color:var(--text)">
            </label>
            <button id="ep-batch-extract-btn" class="btn-sm btn-create" disabled
                    style="flex:1;justify-content:center;padding:.5rem 1rem;align-self:flex-end">
              Extract Batch
            </button>
            <button id="ep-batch-stop-btn" class="btn-sm btn-danger hidden"
                    style="flex-shrink:0;padding:.5rem .9rem;align-self:flex-end">
              Stop
            </button>
          </div>
        </div>
```

The new row sits inside the same outer `flex-direction:column;gap:.5rem` wrapper, so it will render with consistent vertical spacing below the existing extract row.

- [ ] **Step 2: Visually verify before continuing**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d
docker compose up -d dlc-3d
```

Open the extractor (no project, no video selected). Expected: the new row is visible inside `#dlc3d-player-section` (which is itself hidden until a video loads, so visually no change yet). Inspect HTML: the new IDs (`ep-batch-count`, `ep-batch-step`, `ep-batch-extract-btn`, `ep-batch-stop-btn`) are present.

Load a project and select a video. Expected: the player section appears; under the existing Extract Frame button, the new row shows Count (10), Step (1), Extract Batch (disabled until Task 2 lands), Stop (hidden via `.hidden`).

- [ ] **Step 3: Commit**

```bash
git add dlc-3D/src/templates/partials/card_3d_extract.html
git commit -m "feat: add HTML row for batch frame extraction (count + step + buttons)"
```

---

## Task 2: Export `epLoadFrameAt` and enable batch button on video load

Expose the player's frame-load function so `dlc_3d.js` can advance the player from outside the module. Update `openPlayer()` to enable both Extract Frame and Extract Batch when a video loads.

**Files:**
- Modify: `dlc-3D/src/static/enhanced_player.js`

- [ ] **Step 1: Add `epLoadFrameAt` export**

In `dlc-3D/src/static/enhanced_player.js`, find the public API block:

```javascript
// ── Public API ────────────────────────────────────────────────────────────────

export function getVideoPath()     { return _videoPath; }
export function getCurrentFrame()  { return _currentFrame; }
export function getSiblingPath()   { return _siblingVideoPath; }
export function isSyncCamEnabled() { return _syncCamEnabled; }

export async function openPlayer(videoPath, siblingPath) {
```

Add a new export immediately after `isSyncCamEnabled` and before `openPlayer`:

```javascript
// ── Public API ────────────────────────────────────────────────────────────────

export function getVideoPath()     { return _videoPath; }
export function getCurrentFrame()  { return _currentFrame; }
export function getSiblingPath()   { return _siblingVideoPath; }
export function isSyncCamEnabled() { return _syncCamEnabled; }

export async function epLoadFrameAt(n) {
  await _epLoadFrame(n);
}

export async function openPlayer(videoPath, siblingPath) {
```

- [ ] **Step 2: Enable batch button in `openPlayer()`**

Find this block inside `openPlayer()`:

```javascript
  const extractBtn = document.getElementById("ep-extract-btn");
  if (extractBtn) extractBtn.disabled = false;
```

Replace with:

```javascript
  const extractBtn      = document.getElementById("ep-extract-btn");
  const batchExtractBtn = document.getElementById("ep-batch-extract-btn");
  if (extractBtn)      extractBtn.disabled      = false;
  if (batchExtractBtn) batchExtractBtn.disabled = false;
```

- [ ] **Step 3: Build, restart, and verify both buttons enable on video load**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d
docker compose up -d dlc-3d
```

Open the extractor, load a project, select a video. Expected: both Extract Frame AND Extract Batch buttons are enabled (clickable). Extract Batch click does nothing yet — wiring lands in Task 3.

- [ ] **Step 4: Commit**

```bash
git add dlc-3D/src/static/enhanced_player.js
git commit -m "feat: export epLoadFrameAt and enable batch extract button on video load"
```

---

## Task 3: Batch extract loop, stop button, reset

Implement the JS loop, status updates, stop logic, and reset hook in `dlc_3d.js`.

**Files:**
- Modify: `dlc-3D/src/static/dlc_3d.js`

- [ ] **Step 1: Update import to include `epLoadFrameAt`**

In `dlc-3D/src/static/dlc_3d.js`, find the existing import line at the top:

```javascript
import { openPlayer, getCurrentFrame, getVideoPath, getSiblingPath, isSyncCamEnabled } from "./enhanced_player.js";
```

Replace with:

```javascript
import { openPlayer, getCurrentFrame, getVideoPath, getSiblingPath, isSyncCamEnabled, epLoadFrameAt } from "./enhanced_player.js";
```

- [ ] **Step 2: Add `_batchStopRequested` module state**

Find the existing module state block near the top:

```javascript
let _projectPath        = null;
let _activeSession      = null;
let _activeVideo        = null;
let _loadToken          = 0;
let _browserCurrentPath = null;
let _browserParentPath  = null;
```

Add `_batchStopRequested` at the end:

```javascript
let _projectPath        = null;
let _activeSession      = null;
let _activeVideo        = null;
let _loadToken          = 0;
let _browserCurrentPath = null;
let _browserParentPath  = null;
let _batchStopRequested = false;
```

- [ ] **Step 3: Add `_setBatchUIRunning` helper**

In `dlc_3d.js`, add this function immediately above the existing `async function _extractFrame()` declaration (in the `// ── Extract ──` section):

```javascript
function _setBatchUIRunning(running) {
  const single = document.getElementById("ep-extract-btn");
  const batch  = document.getElementById("ep-batch-extract-btn");
  const stop   = document.getElementById("ep-batch-stop-btn");
  if (single) single.disabled = running;
  if (batch)  batch.disabled  = running;
  if (stop)   stop.classList.toggle("hidden", !running);
}
```

- [ ] **Step 4: Add `_extractBatch` function**

In `dlc_3d.js`, add this function immediately after `_setBatchUIRunning` (still in the `// ── Extract ──` section):

```javascript
async function _extractBatch() {
  const primaryVideo = getVideoPath();
  const siblingPath  = getSiblingPath();
  if (!primaryVideo || !_projectPath) {
    if (!_projectPath) _setStatus("No project loaded.");
    return;
  }

  let frameCount;
  try {
    const resp = await fetch(`/dlc-3d/video-info?video=${encodeURIComponent(primaryVideo)}`);
    const info = await resp.json();
    frameCount = info.frame_count;
  } catch (e) { _setStatus("Network error: " + e.message); return; }

  const startFrame = getCurrentFrame();
  const requested  = Math.max(2, parseInt(document.getElementById("ep-batch-count").value, 10) || 10);
  const step       = Math.max(1, parseInt(document.getElementById("ep-batch-step").value,  10) || 1);
  const maxCount   = Math.floor((frameCount - 1 - startFrame) / step) + 1;
  const count      = Math.min(requested, maxCount);
  if (count < 1) { _setStatus("No frames available from this position."); return; }

  const extractSibling = isSyncCamEnabled()
    ? (document.getElementById("ep-extract-sibling")?.checked ?? true)
    : false;

  _batchStopRequested = false;
  _setBatchUIRunning(true);
  if (count < requested) {
    _setStatus(`Near end — extracting ${count} frame${count !== 1 ? "s" : ""} (clamped from ${requested})`);
  }

  let saved = 0, skipped = 0, aborted = false;
  for (let i = 0; i < count; i++) {
    if (_batchStopRequested) { aborted = true; break; }
    const targetFrame = startFrame + i * step;
    _setStatus(`Saving… ${i + 1}/${count}`);
    const body = {
      primary_video:        primaryVideo,
      primary_frame_number: targetFrame,
      extract_sibling:      extractSibling,
    };
    if (extractSibling && siblingPath) {
      body.sibling_video        = siblingPath;
      body.sibling_frame_number = targetFrame;
    }
    try {
      const resp = await fetch("/dlc-3d/save-frame", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (resp.ok) {
        saved   += (data.saved   || []).length;
        skipped += (data.skipped || []).length;
      }
    } catch (e) {
      _setStatus(`Network error at frame ${targetFrame}: ${e.message}`);
      aborted = true;
      break;
    }
    if (i < count - 1) await epLoadFrameAt(targetFrame + step);
    _refreshLabeledFrames();
  }

  _setBatchUIRunning(false);
  const totalDesc = extractSibling ? `${saved} (×2 sibling)` : `${saved}`;
  _setStatus(aborted
    ? `Stopped — saved ${totalDesc}, skipped ${skipped}`
    : `Done — saved ${totalDesc}, skipped ${skipped}`);
  _refreshLabeledFrames();
}
```

- [ ] **Step 5: Wire button click handlers**

In `dlc_3d.js`, find the existing `DOMContentLoaded` handler. Locate the existing `ep-extract-btn` listener (around line 305):

```javascript
  document.getElementById("ep-extract-btn")?.addEventListener("click", _extractFrame);
```

Add immediately after it:

```javascript
  document.getElementById("ep-extract-btn")?.addEventListener("click", _extractFrame);
  document.getElementById("ep-batch-extract-btn")?.addEventListener("click", _extractBatch);
  document.getElementById("ep-batch-stop-btn")?.addEventListener("click", () => { _batchStopRequested = true; });
```

- [ ] **Step 6: Reset batch state in `_resetExtractorUI`**

In `dlc_3d.js`, find `_resetExtractorUI` (around lines 43–65). At the end of its body (right after the existing `if (labeledWrap) labeledWrap.style.display = "none";` line), add:

```javascript
  const labeledWrap = document.getElementById("labeled-wrap");
  if (labeledWrap) labeledWrap.style.display = "none";
  const batchBtn  = document.getElementById("ep-batch-extract-btn");
  const batchStop = document.getElementById("ep-batch-stop-btn");
  if (batchBtn)  batchBtn.disabled = true;
  if (batchStop) batchStop.classList.add("hidden");
  _batchStopRequested = false;
}
```

(The trailing `}` is the existing closing brace of `_resetExtractorUI`. Insert the four new lines right before it.)

- [ ] **Step 7: Build and restart**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d
docker compose up -d dlc-3d
```

- [ ] **Step 8: Manually verify Step=1 batch**

In the browser:
- Open extractor, load a project, select a video without sibling cam.
- Set Count=5, Step=1. Click Extract Batch.
- Expected: Stop button appears; status updates "Saving… 1/5" through "Saving… 5/5"; player advances frame-by-frame; final status "Done — saved 5, skipped 0"; chip count = 5; Stop button hides.

- [ ] **Step 9: Manually verify de-duplication**

- Click Extract Batch a second time at the same starting frame.
- Expected: status "Done — saved 0, skipped 5".

- [ ] **Step 10: Manually verify Step>1**

- Reload the video (or seek back to frame 0). Set Count=10, Step=3. Click Extract Batch.
- Expected: player advances by 3 each iteration (you should see frame numbers 0, 3, 6, 9, …); 10 unique frames saved.

- [ ] **Step 11: Manually verify boundary clamp**

- Seek near the end of the video (within last 20 frames). Set Count=100. Click Extract Batch.
- Expected: status shows "Near end — extracting N frame(s) (clamped from 100)"; loop runs N iterations; final status "Done — saved N (clamped)".

- [ ] **Step 12: Manually verify Stop**

- Seek to frame 0. Set Count=20. Click Extract Batch. After ~3 iterations click Stop.
- Expected: loop halts; status "Stopped — saved 3, skipped 0" (or similar); Stop button hides.

- [ ] **Step 13: Manually verify sibling × 2**

- Select a video with a sibling cam. Enable Sync Cam + Extract Sibling. Set Count=5, Step=1. Click Extract Batch.
- Expected: status "Done — saved 10 (×2 sibling), skipped 0"; the chip count display reads 10.

- [ ] **Step 14: Run E2E + backend test suites**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py tests/e2e/ -v
```

Expected: 39 + 9 = 48 passed (no test changes).

- [ ] **Step 15: Commit**

```bash
git add dlc-3D/src/static/dlc_3d.js
git commit -m "feat: add batch frame extraction with stop button and sibling lock-step"
```

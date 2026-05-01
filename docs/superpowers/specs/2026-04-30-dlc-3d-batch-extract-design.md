# DLC-3D — Batch Frame Extraction — Design Spec

**Date:** 2026-04-30
**Status:** Approved

## Goal

Add an "Extract Batch" feature to the DLC-3D Frame Extractor matching the main webapp's frame extractor card layout. The user enters a Count and Step, clicks Extract Batch, and the player extracts `count` frames starting at the current position, advancing by `step` per iteration. When Sync Cam + Extract Sibling are on, each iteration also saves the sibling frame, so total saved = `count × 2`. A Stop button can abort mid-loop.

Reference: `/home/sam/docker-images/deeplabcut-webapp-docker/src/templates/partials/card_frame_extractor.html` (lines 149–174) and `/home/sam/docker-images/deeplabcut-webapp-docker/src/static/js/frame_extractor.js` (lines 714–727 for batch handler, 495–552 for save flow).

---

## Section 1 — Layout (matches main webapp)

The existing single Extract row stays unchanged. A new row goes immediately below it.

### HTML changes (`card_3d_extract.html`)

Find the existing extract row:

```html
<div style="display:flex;align-items:center;gap:.8rem">
  <button id="ep-extract-btn" class="btn-sm btn-create" disabled
    style="flex:1;justify-content:center;padding:.5rem 1rem">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="12" cy="12" r="4"/></svg>
    Extract Frame
  </button>
  <span id="extract-count" class="fe-extract-count">0 frames saved</span>
</div>
```

Insert immediately below:

```html
<div style="display:flex;align-items:center;gap:.6rem;margin-top:.4rem">
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
```

Defaults match the main webapp: Count=10 (min 2), Step=1 (min 1).

The `.hidden` class is already used elsewhere in the codebase to set `display:none`. The Stop button's existing `btn-danger` class is reused for visual consistency with main-webapp Stop button styling.

---

## Section 2 — Behavior + sibling × 2

### Algorithm

Click Extract Batch → loop `count` iterations starting at the current frame, advancing by `step` per iteration. Each iteration calls the existing `/dlc-3d/save-frame` endpoint, which already handles `extract_sibling` (saves both primary and sibling when Sync Cam is on). Total saved = `count × 2` when sync sibling is enabled.

### Boundary clamping

Before starting, compute:
```
maxCount = floor((frameCount - 1 - currentFrame) / step) + 1
count    = min(requested, maxCount)
```
If `count < requested`, show: `"Near end — extracting {count} frame(s) (clamped from {requested})"` (same wording as main webapp).

If `count < 1`, abort with status `"No frames available from this position."`.

### Per-iteration flow

1. Check `_batchStopRequested` → if true, break.
2. `targetFrame = startFrame + i * step`.
3. Update status: `"Saving… i/N"`.
4. POST to `/dlc-3d/save-frame` with body:
   ```json
   {
     "primary_video":        "<absolute or relative video path>",
     "primary_frame_number": targetFrame,
     "extract_sibling":      true|false,
     "sibling_video":        "<sibling path>",        // only if extract_sibling
     "sibling_frame_number": targetFrame              // only if extract_sibling
   }
   ```
5. Parse response, accumulate `saved` and `skipped` counts (each `data.saved` / `data.skipped` is an array of filenames).
6. Call `epLoadFrameAt(targetFrame + step)` (new export from `enhanced_player.js`) to advance the player view, so the user sees progress live.
7. Call `_refreshLabeledFrames()` so the chip list updates incrementally.

### After loop

- `_setBatchUIRunning(false)` re-enables Extract Frame + Extract Batch buttons, hides Stop.
- Final status: `"Done — saved {n} (×2 sibling), skipped {m}"` (or without "(×2 sibling)" when sibling not extracted).
- If aborted: `"Stopped — saved {n} (×2 sibling), skipped {m}"`.
- One last `_refreshLabeledFrames()`.

### JS additions to `dlc-3D/src/static/dlc_3d.js`

Module-level state:
```javascript
let _batchStopRequested = false;
```

New `_extractBatch()` function:
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

function _setBatchUIRunning(running) {
  const single = document.getElementById("ep-extract-btn");
  const batch  = document.getElementById("ep-batch-extract-btn");
  const stop   = document.getElementById("ep-batch-stop-btn");
  if (single) single.disabled = running;
  if (batch)  batch.disabled  = running;
  if (stop)   stop.classList.toggle("hidden", !running);
}
```

Wire in `DOMContentLoaded`:
```javascript
document.getElementById("ep-batch-extract-btn")?.addEventListener("click", _extractBatch);
document.getElementById("ep-batch-stop-btn")?.addEventListener("click", () => { _batchStopRequested = true; });
```

Add `epLoadFrameAt` to the imports at the top of `dlc_3d.js`:
```javascript
import { openPlayer, getCurrentFrame, getVideoPath, getSiblingPath, isSyncCamEnabled, epLoadFrameAt } from "./enhanced_player.js";
```

### JS addition to `dlc-3D/src/static/enhanced_player.js`

Export a thin wrapper that drives the existing internal `_epLoadFrame`:
```javascript
export async function epLoadFrameAt(n) {
  await _epLoadFrame(n);
}
```

Add it next to the other public exports near the top of the file (after `isSyncCamEnabled`).

---

## Section 3 — Enable / disable + button states

### Initial state

Both `ep-extract-btn` (existing) and `ep-batch-extract-btn` (new) are `disabled` in HTML. `ep-batch-stop-btn` has `class="hidden"` (shown only during batch).

### Enable on video load

In `enhanced_player.js` `openPlayer()`, find:
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

### Reset on extractor reset

In `dlc_3d.js` `_resetExtractorUI`, add at the end of the body:
```javascript
const batchBtn  = document.getElementById("ep-batch-extract-btn");
const batchStop = document.getElementById("ep-batch-stop-btn");
if (batchBtn)  batchBtn.disabled = true;
if (batchStop) batchStop.classList.add("hidden");
_batchStopRequested = false;
```

### During batch

`_setBatchUIRunning(true)` disables both Extract Frame and Extract Batch (so the user can't trigger an overlapping single save mid-loop) and shows the Stop button. `_setBatchUIRunning(false)` reverses both.

### Player controls during batch

The batch loop calls `epLoadFrameAt(target + step)` per iteration, which internally calls the same `_epLoadFrame` used by all other navigation. That function calls `_stop()` first, so any active playback is paused before each frame loads. User can still interact with player controls, but the loop runs to completion or until Stop is pressed — same as main webapp.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dlc-3D/src/templates/partials/card_3d_extract.html` (insert new batch row) |
| Modify | `dlc-3D/src/static/dlc_3d.js` (`_extractBatch`, `_setBatchUIRunning`, `_resetExtractorUI` reset, listener wiring, import update) |
| Modify | `dlc-3D/src/static/enhanced_player.js` (`epLoadFrameAt` export, `openPlayer` enables both buttons) |

No backend, CSS, or test changes required. The existing `/dlc-3d/save-frame` already supports the request shape and de-duplicates by (cam, frame_number).

---

## Testing

1. `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose build dlc-3d && docker compose up -d dlc-3d`
2. Load a project; select a video without sibling cam; both Extract Frame and Extract Batch buttons enabled.
3. Set Count=5, Step=1. Click Extract Batch. Status updates "Saving… 1/5" through "5/5"; player advances through frames; frame counter shows 5 saved.
4. Click Extract Batch again at the same starting frame: status shows "Done — saved 0, skipped 5" (de-dupe).
5. Set Count=10, Step=3. Player advances by 3 each iteration; 10 frames saved.
6. Move to near end of video. Set Count=100. Click Extract Batch. Status shows "Near end — extracting N frames (clamped from 100)".
7. Click Extract Batch with Count=20. While running, click Stop. Status shows "Stopped — saved {n}, skipped {m}".
8. Enable Sync Cam + Extract Sibling. Click Extract Batch with Count=5. Status shows "Done — saved 10 (×2 sibling), skipped 0".
9. Load a different video while a batch is mid-loop (open extractor with new path). Verify reset clears state.
10. `python -m pytest tests/test_core.py tests/e2e/ -v` → existing 39 + 9 tests pass (no test changes).

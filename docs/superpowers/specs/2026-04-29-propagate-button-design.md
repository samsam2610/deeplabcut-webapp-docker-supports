# Propagate Button — Design Spec

**Date:** 2026-04-29
**Module:** clip-cutter
**Status:** Approved

---

## Overview

Replace the `ep-propagate-kf` checkbox with an explicit `↻ Propagate` button. Propagation is no longer automatic after Set KF — the user triggers it manually. The button rescans all unprocessed detections on the current video in **both directions** from the active detection.

---

## 1. HTML (`clip_cutter.html`)

In `#ep-propagate-row`, replace:

```html
<label style="display:flex;align-items:center;gap:4px;font-size:10px;color:#adbac7;cursor:pointer;">
  <input type="checkbox" id="ep-propagate-kf" style="accent-color:#388bfd;cursor:pointer;">
  propagate
</label>
```

With:

```html
<button class="player-btn" id="ep-propagate-btn" disabled
  style="font-size:9px;padding:2px 7px;"
  title="Rescan all unprocessed detections in both directions">↻ Propagate</button>
```

The row then contains the "add KF to template" checkbox on the left and the Propagate button on the right, both always visible.

---

## 2. `_epApplyNewKF` (`enhanced_player.js`)

Remove the block at the end of the function:

```js
// REMOVE this entire block:
if (document.getElementById("ep-propagate-kf")?.checked) {
  try {
    await fetch("/clip-cutter/template/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_path: _videoPath, frame_number: kf1 }),
    });
  } catch { /* non-fatal */ }
}
_epStartRescan(_detectionIdx);
```

Template enrichment is now handled entirely by the `ep-add-kf-to-template` checkbox in the Set KF handler (already present). Auto-propagation is removed.

---

## 3. `_epStartRescan` — new signature

Change from `(detectionIdx)` to `(candidates)`, where `candidates` is `{idx, frame_number}[]`.

Remove the early-return guard:
```js
// REMOVE:
if (!document.getElementById("ep-propagate-kf")?.checked) return;
// REMOVE the forward-only candidate collection loop
```

Update the in-progress label from `"↻ Rescanning N ahead…"` to `"↻ Rescanning N candidates…"`.

New signature used only by `_epPropagateAll`. Everything else in `_epStartRescan` (cancel-in-flight, SSE stream, `_epApplyRescanKF`) is unchanged.

---

## 4. New `_epPropagateAll()`

```js
function _epPropagateAll() {
  if (_detectionIdx === null || typeof detections === "undefined") return;
  const videoPath = _videoPath;
  const candidates = [];
  for (let i = 0; i < detections.length; i++) {
    if (i === _detectionIdx) continue;
    const d = detections[i];
    if (!d || d.video_path !== videoPath) continue;
    if (d.status === "kept" || d.status === "rejected") continue;
    candidates.push({ idx: i, frame_number: d.frame_number });
  }
  if (!candidates.length) return;
  _epStartRescan(candidates);
}
```

Collects every detection on the current video that is not the active detection, not kept, and not rejected — regardless of whether it is before or after `_detectionIdx`.

---

## 5. `_epUpdateModeUI`

Add after the existing mode-gating logic:

```js
const propagateBtn = document.getElementById("ep-propagate-btn");
if (propagateBtn) propagateBtn.disabled = (_detectionIdx === null);
```

Button is enabled whenever a detection is active; disabled in browse mode and when no video is selected.

---

## 6. Event wiring

Wire button click → `_epPropagateAll()`. Place with other player button wires in the init block:

```js
document.getElementById("ep-propagate-btn")
  .addEventListener("click", () => _epPropagateAll());
```

---

## Backend

No changes. `/clip-cutter/rescan-forward` already accepts any `{idx, frame_number}[]` candidate list and uses whatever template state is currently loaded on the server.

---

## Files Changed

| File | Change |
|---|---|
| `clip-cutter/templates/clip_cutter.html` | Replace `ep-propagate-kf` checkbox with `ep-propagate-btn` button |
| `clip-cutter/static/enhanced_player.js` | Remove auto-propagate from `_epApplyNewKF`; refactor `_epStartRescan` to accept candidates array; add `_epPropagateAll()`; update `_epUpdateModeUI`; wire button |

---

## Non-Goals

- No change to the rescan backend or SSE stream
- No change to cancel behaviour (cancel button still works)
- No change to the "add KF to template" checkbox behaviour
- No directional filtering — all unprocessed detections are included

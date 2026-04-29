# Browse Mode + KF Row Refactor + Note Palette Scroll — Design Spec

**Date:** 2026-04-29
**Module:** clip-cutter
**Status:** Approved

---

## Overview

Three related changes to the clip-cutter video player:

1. **Browse button** — open the video viewer directly from the Detections header without scanning, starting with the frame lock unlocked.
2. **Propagate KF row refactor** — split the single "Propagate KF" checkbox into two: "add KF to template" (checked by default) and "propagate" (unchecked by default), both always visible.
3. **Note palette scroll** — cap the height of the unique-note chip list so it doesn't overflow the extract panel.

---

## 1. Browse Button

### Placement

A small `▶ Browse` button added to `results-pane-header`, to the left of `#sim-filter`. It is only enabled when a video is selected (`selectedVideoPath !== null`). It is disabled (greyed) when no video is selected.

```
[Detections] [N found] [▶ Browse] [≥ ——●—— 0.00 ×] [✓ sensor+CLIP] [CLIP only] [All]
```

### Trigger

```js
openPlayer({ mode: "clip", videoPath: selectedVideoPath, unlocked: true });
```

---

## 2. `openPlayer()` — `unlocked` parameter

Add `unlocked = false` to the signature:

```js
async function openPlayer({ mode, videoPath, keyFrame1Based = null, detectionIdx = null, csvPath = null, unlocked = false })
```

When `unlocked: true`:
- `_unlocked = true` (instead of the default `false`)
- `document.getElementById("ep-lock-start").checked = false`
- `_detectionIdx = null`, `keyFrame1Based = null` → clip range defaults to full video (0 to frameCount−1)
- Everything else (extract panel, tag bars, sibling cam, CSV load) is unchanged
- `_epUpdateModeUI()` runs as usual — in `mode: "clip"` the lock badge is shown; since `_unlocked` is now `true` at call time, it renders as 🔓

The lock badge remains toggleable by the user. `ep-lock-start` starts unchecked.

---

## 3. Set KF in Free Mode (`_detectionIdx === null`)

Current guard in `ep-set-kf` click handler:

```js
if (!_videoPath || _detectionIdx === null) return;
```

**Change:** when `_detectionIdx === null` (browse mode, no detection yet), instead of returning:
- Skip the overlap check
- Set `_keyFrame = _currentFrame`
- Update `ep-start` to `Math.max(1, _currentFrame + 1 - 200)`
- Call `_epUpdateEnd()`
- Return (do not call `_epApplyNewKF` — that requires a detectionIdx)

Once a detection entry exists (after first extract), subsequent Set KF calls proceed normally.

---

## 4. Extract in Free Mode (`capturedIdx === null`)

When `capturedIdx === null` in the `ep-extract` click handler:

**On success from `/clip-cutter/extract`:**

1. Compute `keyFrame` from extract panel: `parseInt(ep-start.value) + 200`
2. Create a new detection object:
   ```js
   {
     video_path: capturedVideoPath,
     frame_number: keyFrame,
     similarity: null,
     source: "manual",
     status: "kept",
     extract_avi_path: data.avi_path,
     extract_postfix: postfix || null,
   }
   ```
3. Push to `detections[]`
4. Build card: `buildResultCard(d, detections.length - 1)` → append to `#results-list`
5. Mark card as kept immediately (add `.kept` class, disable buttons)
6. Set `_detectionIdx = detections.length - 1`
7. Auto-switch source filter to `"all"` so the manual card is visible (update `currentFilter`, update `.filter-btn` active class, call `applyFilter()`)
8. Swap Extract → Rename/Delete buttons in the player UI
9. Call `saveDetections()`

Subsequent extracts in the same browse session (after `_detectionIdx` is set) follow the normal kept-detection path and create additional manual entries each time (a new detection per extract call, same pattern as above, but with `capturedIdx` now being the previous `_detectionIdx`).

**Wait — on subsequent extract calls:** once `_detectionIdx` is set, the normal extract handler path runs (`capturedIdx !== null`). This marks the existing detection as kept (already is), updates its name. For a truly "new clip each time" experience, browse mode should always create a new entry. Handle this by: if `detections[capturedIdx].status === "kept"` and `_mode === "clip"` and the detection was created as `source: "manual"`, treat the next extract as a new entry.

**Simpler resolution:** In browse mode, each extract always creates a new detection. Track this with a module-private flag `_browseMode` (set `true` when `openPlayer` is called with `unlocked: true`, reset to `false` on any other `openPlayer` call). The extract handler checks: if `_browseMode`, always create a new entry regardless of `_detectionIdx`.

---

## 5. Propagate KF Row Refactor

Replace the single `#ep-propagate-row` checkbox with two checkboxes on the same line. **Always visible (no mode gating).**

### HTML

```html
<div id="ep-propagate-row" style="display:flex; align-items:center; gap:10px; padding:3px 4px; margin-bottom:2px;">
  <label style="display:flex; align-items:center; gap:4px; font-size:10px; color:#adbac7; cursor:pointer;">
    <input type="checkbox" id="ep-add-kf-to-template" checked style="accent-color:#388bfd; cursor:pointer;">
    add KF to template
  </label>
  <label style="display:flex; align-items:center; gap:4px; font-size:10px; color:#adbac7; cursor:pointer;">
    <input type="checkbox" id="ep-propagate-kf" style="accent-color:#388bfd; cursor:pointer;">
    propagate
  </label>
</div>
```

Note: `ep-propagate-kf` loses its `checked` default (was checked, now unchecked). `ep-add-kf-to-template` is new, checked by default.

### Behavior — `ep-add-kf-to-template`

When Set KF is pressed (and `_detectionIdx !== null`) and `ep-add-kf-to-template` is checked: after `_epApplyNewKF(kf1)` completes successfully, also call `addToTemplate(_videoPath, kf1)`.

In browse mode (`_detectionIdx === null`), the "add KF to template" checkbox is checked and Set KF just updates the panel — no template add call (there's no confirmed keyframe to add yet; it's added after extract if desired).

### Behavior — `ep-propagate-kf`

Unchanged from current "Propagate KF" behavior. The only difference: `ep-propagate-row` is no longer hidden in non-clip modes (`_epUpdateModeUI` removes the `display:none` toggling for this row).

---

## 6. Note Palette Scroll

`#ep-note-palette` gets a max-height and scroll:

```css
#ep-note-palette {
  max-height: 72px;   /* ~3 rows of chips */
  overflow-y: auto;
}
```

The `#ep-note-mapping-section` header ("Note → tag — drag chip onto quicktag to map") stays fixed above the scrollable palette.

---

## Files Changed

| File | Change |
|---|---|
| `clip-cutter/templates/clip_cutter.html` | Add Browse button HTML+CSS; refactor `#ep-propagate-row` HTML; add `#ep-note-palette` scroll CSS |
| `clip-cutter/static/clip_cutter.js` | Enable/disable Browse button on video select; wire Browse button click |
| `clip-cutter/static/enhanced_player.js` | `openPlayer()`: add `unlocked` param; Set KF: free-mode path; Extract: free-mode path + `_browseMode` flag; `_epUpdateModeUI()`: remove propagate-row mode-gating; wire `ep-add-kf-to-template` |

---

## Non-Goals

- No new backend endpoints
- No persistence of "browse mode" across page reloads
- No change to the overlap-check logic for clip-mode Set KF
- No change to how the source filter works (manual entries visible only under "All")

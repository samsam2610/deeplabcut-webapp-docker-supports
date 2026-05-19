# Mark Current Frame as Keyframe — Design Spec

**Date:** 2026-04-26

## Goal

Allow the user to reposition the keyframe of a detection while previewing it in the clip player. Clicking "📌 Set KF here" updates `detections[idx].frame_number` in-place so that subsequent Extract/Keep operations use the new keyframe. An overlap check warns when the new clip range conflicts with clips already on disk.

## Background

The clip player reads frames directly from the original `.avi` via `/clip-cutter/frame?video=...&n=...` — no clip is pre-extracted at preview time. The player window is `[keyframe−200, keyframe+599]` around the detected keyframe. `detections[idx].frame_number` is the single source of truth; `keepDetection(idx)` reads it directly, so updating it in-place is sufficient.

---

## Section 1: Scope

**In scope:**
- "📌 Set KF here" button in the player action row marks the current frame as the new keyframe
- Live "KF: N" counter shows the active keyframe at all times
- "▶ From clip start" button (optional, manual) seeks to `keyframe−200` and starts playing
- On "Set KF here": backend overlap check against clips on disk; if clear, update immediately; if conflict, show card-style warning with conflict details
- `detections[idx].frame_number` updated in-place; result card clip-name label updated to reflect new range
- Player clip bounds (`_playerClipStart`, `_playerClipEnd`) recalculated after update

**Out of scope:**
- Persisting keyframe changes to the CSV/scan results on disk
- Changing the extraction pipeline or scan logic
- Automatic playback on keyframe change (user must click "▶ From clip start" manually)

---

## Section 2: API

```
POST /clip-cutter/check-keyframe-overlap
Content-Type: application/json
Body: { "key_frame": N, "video_path": "/absolute/path/to/video.avi" }   ← key_frame is 1-based

Response (no overlap):
{ "overlaps": false }

Response (overlap):
{
  "overlaps": true,
  "conflicts": [
    { "name": "MAP2_4650_5249_success.avi", "overlap_frames": 427 }
  ]
}

Error: 422 if `video_path` is missing or the derived clips directory does not exist
```

**Backend logic:**
- Derives `clips_dir` from `video_path` in the request body (`<parent>/<stem>/`)
- Calls existing `get_known_key_frames(clips_dir)` to get `{kf_1based: clip_stem}` from filenames on disk
- New clip range: `[key_frame−200, key_frame+599]`
- For each known clip: compute its range `[kf−200, kf+599]` and check if ranges intersect
- Overlap frame count = length of intersection

---

## Section 3: UI Components

### HTML changes (`clip_cutter.html`)

**Updated `#player-actions` row:**
```html
<div id="player-actions">
  <button class="player-btn" id="player-keyframe">⤢ Key frame</button>
  <button class="player-btn active" id="player-loop">↺ Loop</button>
  <button class="player-btn" id="player-clip-start">▶ From clip start</button>
  <div style="flex:1"></div>
  <span id="player-kf-label" style="font-size:10px;color:#768390;font-family:monospace">
    KF: <span id="player-kf-num">—</span>
  </span>
  <button class="player-btn player-btn-blue" id="player-set-kf">📌 Set KF here</button>
</div>

<!-- shown only when overlap detected -->
<div id="player-overlap-warning" style="display:none;"></div>
```

New CSS rule: `.player-btn-blue { border-color: #388bfd; color: #388bfd; }`

### JS state (`player.js`)

```js
let _playerDetectionIdx = null;   // which detections[] entry is loaded
let _pendingKF = null;            // proposed new keyframe (1-based), awaiting confirm
```

`loadClip(videoPath, kf1, detectionIdx)` gains a third argument, stores `_playerDetectionIdx`, and sets `#player-kf-num` on load.

### Interaction flow

1. User clicks "📌 Set KF here" → reads current frame (1-based), stores in `_pendingKF`, POSTs `{ key_frame, video_path: _playerVideoPath }` to `/clip-cutter/check-keyframe-overlap`
2. **No overlap** → `applyNewKF(_pendingKF)`: updates `detections[_playerDetectionIdx].frame_number`, recalculates `_playerClipStart/_End`, refreshes `#player-kf-num`, updates card clip-name label
3. **Overlap** → populates `#player-overlap-warning` with conflict name + frame count; buttons:
   - "Keep anyway" → calls `applyNewKF`, hides warning
   - "Cancel" → hides warning, clears `_pendingKF`
4. "▶ From clip start" → seeks to `_playerClipStart`, calls play

**Card label update:** `buildResultCard` gives the clip-name span `id="card-clipname-{idx}"` so `applyNewKF` can update it when the KF changes.

---

## Section 4: File Changes

| File | Change |
|------|--------|
| `clip-cutter/templates/clip_cutter.html` | Add new buttons, KF counter, overlap warning container, `.player-btn-blue` CSS |
| `clip-cutter/static/player.js` | Add `_playerDetectionIdx`, `_pendingKF` state; update `loadClip` signature; add Set KF Here, From Clip Start, and overlap warning handlers; add `applyNewKF()` |
| `clip-cutter/static/clip_cutter.js` | Pass `idx` to `loadClip` call sites; add `id="card-clipname-{idx}"` to clip-name span in `buildResultCard` |
| `clip-cutter/routes.py` | Add `POST /clip-cutter/check-keyframe-overlap` endpoint |

No new files. No changes to `processor.py`, the extraction pipeline, or scan logic.

---

## Section 5: Testing

Manual smoke tests:

1. Open a video with existing clips on disk. Click "📌 Set KF here" at an overlapping frame → overlap warning card appears with correct clip name and overlap count.
2. Click "Cancel" → `detections[idx].frame_number` unchanged, card label unchanged, warning hidden.
3. Click "📌 Set KF here" again at the same frame, then "Keep anyway" → detection updated, card label reflects new range, warning hidden.
4. Click "📌 Set KF here" at a non-overlapping frame → no warning, detection updates immediately.
5. Click "▶ From clip start" → player seeks to `kf−200` and begins playing.
6. After updating KF, click Extract → extracted clip uses the new keyframe, not the original.

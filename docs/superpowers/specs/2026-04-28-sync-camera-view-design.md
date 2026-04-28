# Sync Camera View — Design Spec

**Date:** 2026-04-28
**Module:** clip-cutter
**Status:** Approved

---

## Overview

Multi-camera recording sessions produce sibling video files in the same directory with identical subject/date/time stems and differing trailing camera-number suffixes (e.g. `m3_20250727_163450_2.avi` and `m3_20250727_163450_3.avi`). This feature adds a passive second-camera view to the video player: a single checkbox ("sync cam") causes the player to display the same frame number from the sibling camera alongside the main video, using available horizontal space. All controls, CSV data, notes, and extraction actions remain bound to the main video.

---

## Naming Convention

Files follow: `<Subject>_<Date>_<Time>_<CamNum>.avi`

Example: `m3_20250727_163450_3.avi` → subject `m3`, date `20250727`, time `163450`, cam `3`.

Siblings share the same `<Subject>_<Date>_<Time>` prefix and differ only in `<CamNum>`. Two cameras are assumed.

---

## Backend

### `_state` extension

`_state` (in `routes.py`) gains one new field:

```python
_state: dict = {
    ...
    "sibling_video_path": None,  # str | None — set once per video selection
}
```

### Sibling discovery helper

```python
def _find_sibling_camera(video_path: Path) -> str | None:
    m = re.match(r'^(.+)_(\d+)$', video_path.stem)
    if not m:
        return None
    prefix = m.group(1)
    for candidate in sorted(video_path.parent.glob(f"{prefix}_*.avi")):
        tail = candidate.stem[len(prefix) + 1:]
        if candidate != video_path and re.match(r'^\d+$', tail):
            return str(candidate)
    return None
```

### `POST /select-video` change

After resolving the video path, compute and store the sibling once:

```python
_state["sibling_video_path"] = _find_sibling_camera(p)
```

Returned in the response:

```json
{ "count": 3, "has_template": true, "sibling_video_path": "/user-data/.../m3_..._2.avi" }
```

No filesystem re-scan on subsequent requests — the value lives in `_state` until the next `select_video` call.

### `GET /clip-cutter/sibling-camera`

Thin read route for the frontend to retrieve the stored sibling path:

```json
{ "sibling_video_path": "<path>" }   // or null
```

---

## Frontend

### New state variables (`enhanced_player.js`)

```js
let _syncCamEnabled = false;   // persists across epSwitchDetection(), reset on openPlayer()
let _siblingVideoPath = null;  // set once per openPlayer() call
```

### Checkbox UI

Placed inside `#ep-frame-wrap`, positioned absolute below the existing `#ep-zoom-controls` (top-right corner). Markup:

```html
<label id="ep-sync-cam-label">
  <input type="checkbox" id="ep-sync-cam"> sync cam
</label>
```

Style: `position: absolute; top: 28px; right: 6px; font-size: 8px; color: #768390;`

If `_siblingVideoPath` is null, the label is hidden and the checkbox is unchecked and disabled.

### Second camera panel (`#ep-cam2-wrap`)

Inserted into `#ep-inner` between `#ep-left` and `#ep-panel-resize-handle`. Starts hidden.

```html
<div id="ep-cam2-wrap">
  <img id="ep-cam2-frame" alt="">
  <div id="ep-cam2-label">cam 2</div>
</div>
```

Styles mirror `#ep-frame-wrap`: dark background, border, flex-centered, `flex: 1`, `display: none` by default. When sync is active, `display: flex` — both `#ep-left` and `#ep-cam2-wrap` share the middle zone equally (`flex: 1` each), with the extract panel unchanged on the right.

### `openPlayer()` changes

After fetching video info, call `GET /clip-cutter/sibling-camera`:

```js
_siblingVideoPath = null;
_syncCamEnabled = false;   // reset for new video
// update checkbox UI: hidden if no sibling, visible if sibling found
const r = await fetch("/clip-cutter/sibling-camera");
if (r.ok) _siblingVideoPath = (await r.json()).sibling_video_path || null;
_epUpdateSyncCamUI();
```

### `epSwitchDetection()` changes

Do NOT reset `_syncCamEnabled` — the checkbox state persists across candidate switches on the same video.

Call `_epLoadCam2Frame(_keyFrame)` if sync is active, so the second camera jumps to the new detection's frame immediately.

### `_epLoadFrame()` changes

After the main frame is loaded, if `_syncCamEnabled && _siblingVideoPath`:

```js
_epLoadCam2Frame(n);
```

`_epLoadCam2Frame(n)` fetches `/clip-cutter/frame?video=<sibling>&n=${n}` in parallel (does not block main frame display), updates `ep-cam2-frame.src` via blob URL (same pattern as main frame).

### Checkbox event

```js
document.getElementById("ep-sync-cam").addEventListener("change", (e) => {
  _syncCamEnabled = e.target.checked;
  _epUpdateSyncCamUI();
  if (_syncCamEnabled) _epLoadCam2Frame(_currentFrame);
});
```

`_epUpdateSyncCamUI()` shows/hides `#ep-cam2-wrap`, enables/disables the checkbox.

---

## Data Flow

```
User checks "sync cam"
  → _syncCamEnabled = true
  → #ep-cam2-wrap shown
  → _epLoadCam2Frame(_currentFrame) called immediately

User navigates / plays
  → _epLoadFrame(n) fires
  → main frame fetch completes → ep-frame.src updated
  → _epLoadCam2Frame(n) fires in parallel → ep-cam2-frame.src updated

User switches detection (epSwitchDetection)
  → _syncCamEnabled unchanged
  → _epLoadCam2Frame(new keyframe) called

User selects new video (openPlayer)
  → _syncCamEnabled = false
  → _siblingVideoPath refetched from /sibling-camera
  → if null: checkbox hidden, auto-unchecked
```

---

## What Does NOT Change

- All controls (seek, play, step, loop, zoom, lock) remain on the main video only.
- CSV data, status/note badges, tag bars, extraction panel — all main video only.
- Template mode behavior — unchanged.
- The horizontal resize handle between video and extract panel — unchanged.
- The `#ep-extract-panel` width and behavior — unchanged.

---

## Error Handling

- If `_epLoadCam2Frame` fetch fails (sibling file missing or corrupt), the `#ep-cam2-frame` img simply retains its previous src (or shows broken image). No error is surfaced to the user — the passive view degrades silently.
- If `GET /sibling-camera` fails on `openPlayer`, `_siblingVideoPath` stays null, checkbox hidden.

---

## Scope

- Assumes exactly 2 cameras. If more than one sibling is found, the first alphabetically is used.
- No extraction, renaming, or template actions on the second camera view.
- No independent seek or controls on the second camera view.

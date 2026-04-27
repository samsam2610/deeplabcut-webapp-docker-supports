# Folder Browser + Per-Video Template Management — Design Spec

## Goal

Replace the flat video list with a hierarchical folder browser. Each video gets its own template stored alongside its extracted clips. A minimal template frame player lets users manually add frames to the template after init.

## Architecture

Pure frontend + backend change within `clip-cutter`. No changes to `processor.py` logic — only how paths are derived and passed. The server remains stateless with respect to template path: every request carries `video_stem` + `video_parent`, and the backend constructs the path dynamically. `_state` in `routes.py` tracks the currently selected video so scan operations can derive the template path without the frontend re-sending it every time.

**Tech Stack:** Vanilla JS, HTML/CSS in `clip_cutter.html` / `clip_cutter.js`; Flask routes in `routes.py`.

---

## Folder Structure

```
<video_parent>/
  <video_stem>/
    template/
      template_state.json     ← CLIP + DINOv2 embeddings and mean
      frame_0100.jpg          ← thumbnail copies of template frames
      frame_0200.jpg
      …
    <clip1>_success.avi       ← extracted clips live here (not in template/)
    <clip2>_failure.avi
    …
```

- Init reads `_success` / `_failure` `.avi` files from `<video_parent>/<video_stem>/` (direct children only, not recursive).
- If no clips exist when Init is clicked, the empty `template/` folder and an empty `template_state.json` are created without error.
- Template frame thumbnails (`.jpg`) are written into `template/` alongside `template_state.json`.
- The `template/` folder is never deleted by Clear — only its contents are.

---

## Folder Browser

### Behavior

- Replaces the current flat `.avi` list entirely.
- **Breadcrumb** at top: shows full current path; each segment is clickable to navigate there.
- **Up button (↑)**: navigates to parent directory. No upper bound — fully unrestricted filesystem access.
- **Entries**: directories first (📁), then `.avi` files (▶), each group sorted case-insensitively.
- **`.avi` status badge**:
  - `done` — `<video_parent>/<video_stem>/` folder exists and contains at least one `.avi` clip
  - `ready` — no such folder yet
  - Done videos remain clickable (unlike current greyed-out behavior).
- **Clicking a folder**: navigates into it, updates breadcrumb.
- **Clicking a `.avi`**: selects it, loads its per-video template into the sidebar, enables Scan button.
- **Starting path**: `_DATA_ROOT` on first load. Last-visited path persisted in `localStorage` so page refresh returns the user to their last location.

### New Backend Endpoint

```
GET /clip-cutter/fs/ls?path=<absolute_path>
```

Response:
```json
{
  "path": "/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos",
  "parent": "/user-data/Parra-Data/Cloud/Reaching-Task-Data",
  "entries": [
    {"name": "MAP-1", "type": "dir", "has_avi": true},
    {"name": "MAP-2", "type": "dir", "has_avi": true},
    {"name": "session_20250515.avi", "type": "file"}
  ]
}
```

- `has_avi` is `true` if the directory contains at least one `.avi` file (shallow check only).
- Dotfiles and non-directory / non-`.avi` entries are excluded.
- `GET /clip-cutter/videos` is removed.

---

## Template Sidebar

The sidebar adapts to the current selection state:

| State | Display |
|-------|---------|
| No video selected | "Select a video to load its template" — Init and Clear hidden |
| Video selected, no `template_state.json` | "No template for `<video_stem>`" — Init button only |
| Video selected, template exists (even 0 frames) | Thumbnail grid + frame count + Init button + Clear button (red) |

### Init Button

- If a template already exists: shows confirmation prompt — "Re-init will replace the current template. Continue?" — before proceeding.
- Spawns background task (existing polling pattern via `/template/init/status`).
- On completion: sidebar thumbnails refresh; minimal template player opens in the main area.

### Clear Button

- Red button, visible only when `template_state.json` exists.
- Shows a modal confirmation: user must type `delete` (exact string, case-sensitive) and click Confirm.
- On confirm: calls `POST /clip-cutter/template/clear`.
- Backend deletes `template_state.json` and all `.jpg` files inside `template/`. The `template/` folder itself is kept.
- Sidebar returns to "no template" state.

---

## Init Flow + Minimal Template Player

### Init Steps (backend)

1. Create `<video_parent>/<video_stem>/template/` (mkdir -p, no error if exists).
2. Scan `<video_parent>/<video_stem>/` for direct-child `.avi` files whose stem ends in `_success` or `_failure`.
3. For each clip: extract frame 200, embed with CLIP + DINOv2, save thumbnail JPEG to `template/frame_<N>.jpg`.
4. Compute `mean_embedding` and `dino_mean_embedding`.
5. Write `template_state.json`.
6. Return progress via existing SSE / polling mechanism.

### Minimal Template Player

Opens in the main area (slides in, replacing the folder browser) after init completes — or at any time via a **"Browse frames"** button in the sidebar when a video is selected.

Controls:
- Prev / Next frame buttons
- Seek slider (0–1000 normalized)
- Frame counter: `fr N / Total` (read-only in this version — editable in the full enhanced player)
- **"Add this frame to template"** button: calls `POST /clip-cutter/template/add`; sidebar thumbnail updates immediately
- **"Close"** button: dismisses player, returns to folder browser

The minimal player reuses the existing `/clip-cutter/frame` and `/clip-cutter/video-info` endpoints unchanged.

This player is a stub. A later sub-project replaces it with the full enhanced player (skip-N field, double-click frame jump, nth-frame playback, adjustable size, CSV status/note bars).

---

## API Changes

| Method | Endpoint | Change |
|--------|----------|--------|
| GET | `/clip-cutter/fs/ls` | **New** — filesystem browser |
| GET | `/clip-cutter/videos` | **Removed** — replaced by `/fs/ls` |
| GET | `/clip-cutter/template` | Updated — accepts `video_stem` + `video_parent` query params |
| POST | `/clip-cutter/template/init` | Updated — body includes `video_stem` + `video_parent`; creates folder structure |
| GET | `/clip-cutter/template/init/status` | Unchanged |
| POST | `/clip-cutter/template/add` | Updated — body includes `video_stem` + `video_parent` |
| DELETE | `/clip-cutter/template/<idx>` | Updated — query params `video_stem` + `video_parent` |
| POST | `/clip-cutter/template/clear` | **New** — deletes `template_state.json` + `.jpg` files in `template/` |

### `_state` in `routes.py`

Two new keys added to the module-level `_state` dict:

```python
_state: dict = {
    "frames": [],
    "mean_embedding": None,
    "dino_mean_embedding": None,
    "video_stem": None,       # set when frontend selects a video
    "video_parent": None,     # set when frontend selects a video
}
```

A new endpoint `POST /clip-cutter/select-video` sets these two keys under `_state_lock`. All template operations derive the template path from `_state["video_parent"] / _state["video_stem"] / "template" / "template_state.json"`.

---

## File Changes

| File | Change |
|------|--------|
| `clip-cutter/routes.py` | Add `/fs/ls`, `/template/clear`, `/select-video`; update all `/template/*` routes; remove `/videos` |
| `clip-cutter/templates/clip_cutter.html` | Replace video list with folder browser; add minimal player panel; update sidebar states |
| `clip-cutter/static/clip_cutter.js` | Folder browser state + navigation; updated template calls; minimal player logic; `localStorage` path persistence |
| `clip-cutter/config.py` | `TRAINING_CLIPS_DIR` no longer used by UI (kept for backward compat); `_DATA_ROOT` used as browser starting point |
| `clip-cutter/tests/test_routes.py` | Update existing video-list tests; add tests for `/fs/ls`, `/template/clear`, `/select-video` |
| `clip-cutter/tests/test_ui.py` | Add Playwright tests for folder navigation, per-video template init, clear confirmation dialog |

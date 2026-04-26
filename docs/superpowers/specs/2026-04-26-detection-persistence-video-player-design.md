# Detection Persistence & Video Player — Design Spec

## Goal

Save scan results to disk per video so they survive restarts and cross-device sessions. Add a frame-by-frame video player (side-by-side with the results list) so detections can be visually reviewed before Keep/Reject decisions.

## Architecture

Two independent subsystems that share a workflow: persistence makes results durable; the player makes them reviewable. The player reads detection data already in the frontend — no new coupling between the two backend features.

**Tech stack additions:** OpenCV VideoCapture LRU cache (same pattern as `/home/sam/docker-images/deeplabcut-webapp-docker/src/routes/annotate.py`), ETag-cached JPEG frame serving, `setTimeout`-based playback loop (same as `viewer.js` in the main webapp).

---

## Subsystem 1 — Persistence

### File layout

A new `DETECTIONS_DIR` config var (env: `CLIP_CUTTER_DETECTIONS_DIR`) defaults to:

```
<CLIP_CUTTER_DATA_ROOT>/Reaching-Task-Data/clip-cutter/detections/
```

One JSON file per video, named by stem: `MAP2_20250515_103618_0.json`.

### JSON schema

```json
{
  "video_path": "/user-data/Parra-Data/Cloud/.../MAP2_20250515_103618_0.avi",
  "scan_timestamp": "2026-04-26T12:05:00",
  "template_frame_count": 19,
  "detections": [
    {
      "cv2_pos": 20967,
      "frame_number": 20968,
      "similarity": 0.8734,
      "known_match": "MAP2_0_20768_21567_success",
      "status": "pending"
    }
  ]
}
```

`status` is one of `"pending"`, `"kept"`, `"rejected"`.

### New routes

| Method | Path | Body / Query | Response |
|--------|------|--------------|----------|
| `GET` | `/clip-cutter/detections` | `?video=<path>` | saved JSON or 404 |
| `PUT` | `/clip-cutter/detections` | `{video_path, detections}` | `{ok: true}` |

### Data flow

1. Scan completes → `_run_scan` auto-saves all detections with `status: "pending"` via `PUT /detections`.
2. User selects a video → frontend calls `GET /detections?video=<path>`:
   - **200**: populate cards with saved statuses, skip scan. Scan button stays enabled for re-scan.
   - **404**: normal state (no prior scan). Show empty results.
3. User clicks Keep → `/extract` succeeds → `PUT /detections` with updated status `"kept"`.
4. User clicks Reject → `PUT /detections` with status `"rejected"` (currently client-only; now persisted).
5. Re-scan → overwrites the JSON with fresh detections, all `status: "pending"`. Write is atomic: write to `<stem>.json.tmp` then `os.replace()` to avoid partial reads.

### New processor function

```python
# processor.py
def save_detections(video_path: str, detections: list[dict],
                    template_frame_count: int, detections_dir: Path) -> None: ...

def load_detections(video_path: str, detections_dir: Path) -> dict | None: ...
```

---

## Subsystem 2 — Video Player

### New module: `viewer.py`

Holds the VideoCapture LRU cache, isolated from `routes.py`.

```python
_VCAP_MAX = 4          # max simultaneously open VideoCapture handles
_vcap_cache: OrderedDict  # keyed by video_path
_vcap_lock: threading.Lock

def get_frame_jpeg(video_path: str, frame_number: int, quality: int = 80) -> bytes:
    """Return JPEG bytes for the given 0-based frame. Raises ValueError on bad input."""

def get_video_info(video_path: str) -> dict:
    """Return {frame_count: int, fps: float}."""
```

Sequential-read optimisation: if `frame_number == last_pos + 1`, skip `CAP_PROP_POS_FRAMES` seek (same as annotate.py).

**Frame number convention:** `viewer.py` and the `/frame` route use **0-based** frame numbers (OpenCV `CAP_PROP_POS_FRAMES` convention). Detection `frame_number` fields are **1-based**. The frontend converts: `cv2_frame = frame_number - 1` before calling `/frame`.

### New routes (in `routes.py`)

| Method | Path | Query params | Response |
|--------|------|--------------|----------|
| `GET` | `/clip-cutter/frame` | `video=<path>&n=<int>` | JPEG, ETag, Cache-Control: private max-age=3600 |
| `GET` | `/clip-cutter/video-info` | `video=<path>` | `{frame_count, fps}` |

### Layout — side by side

Once detections are loaded (from scan or from saved JSON), the main panel splits:

```
┌─────────────┬──────────────────────────────┐
│ Results 40% │ Player 60%                   │
│             │ ┌──────────────────────────┐ │
│ [card 1] ◀  │ │      frame image         │ │
│ [card 2]    │ │                          │ │
│ [card 3]    │ └──────────────────────────┘ │
│             │  ⏮  ▶  ⏭  ══════════  fr N  │
│             │  [⌖ Key frame]  [↩ Loop]     │
└─────────────┴──────────────────────────────┘
```

Before any card is clicked, the player shows a placeholder: *"Click a detection to preview"*.

### Player behaviour

- Clicking a card loads `{videoPath, clipStart: max(0, frame_number - 200), clipEnd: min(frame_count - 1, frame_number + 599), keyFrame: frame_number}` into the player, seeks to `clipStart`, starts looping immediately. `frame_count` comes from `GET /video-info`.
- **Scrub bar** spans the full video (not just the clip window) so the user can explore context.
- **⌖ Key frame** button: seeks to `keyFrame` instantly.
- **Loop** toggle (on by default): at `clipEnd`, wraps back to `clipStart`.
- **⏮ / ⏭**: step ±1 frame (stop playback).
- **▶/⏸**: play/pause. Playback is `setTimeout`-based — each tick awaits `_loadFrame()` before scheduling the next, so slow frames never desync.
- Default playback speed: 15 fps (configurable JS constant `PLAYER_FPS = 15`).

### New JS structure

Split `clip_cutter.js` into two files to keep file sizes manageable:

- `clip_cutter.js` — existing logic (template bank, video list, scan, results) + persistence calls
- `player.js` — all player state and functions (`initPlayer`, `loadClip`, `_playerLoop`, `_loadFrame`, seek bar, controls)

`player.js` exposes one function: `loadClip(videoPath, clipStart, clipEnd, keyFrame)`. Result cards call this on click.

---

## File Changes

| File | Action |
|------|--------|
| `config.py` | Add `DETECTIONS_DIR` |
| `processor.py` | Add `save_detections`, `load_detections` |
| `viewer.py` | **New** — VideoCapture LRU cache, `get_frame_jpeg`, `get_video_info` |
| `routes.py` | Add `/frame`, `/video-info`, `/detections` (GET + PUT); wire auto-save into `_run_scan` |
| `templates/clip_cutter.html` | Add player panel CSS + HTML; split-column layout |
| `static/clip_cutter.js` | Add persistence calls (load on video select, save on keep/reject); wire card click → `loadClip` |
| `static/player.js` | **New** — all player logic |
| `tests/test_frame_routes.py` | **New** — backend pytest for `/frame`, `/video-info`, `/detections` |
| `tests/test_ui.py` | Extend mock routes + add 6 new Playwright tests |

---

## Testing

### Backend (`test_frame_routes.py`)

Uses a synthetic 30-frame AVI generated with OpenCV (no real video data needed).

- `GET /frame` returns JPEG for valid path + frame
- `GET /frame` returns 404 for missing file
- `GET /frame` returns 304 on ETag match (no re-encode)
- `GET /video-info` returns correct `frame_count` and `fps`
- `GET /detections` returns 404 when no file exists
- `PUT /detections` writes JSON; `GET /detections` round-trips it
- `PUT /detections` then keep + reject → status fields persisted correctly

### Frontend (`test_ui.py` additions)

Mock routes added: `/frame` → 1×1 JPEG, `/video-info` → `{frame_count: 26492, fps: 30}`, `GET /detections` → saved fixture or 404, `PUT /detections` → captures body.

New tests:
1. Selecting a video with saved detections auto-loads cards (no scan needed)
2. Scan button remains enabled when saved results are loaded
3. Player panel placeholder visible before any card clicked
4. Clicking a card makes the player panel show a frame image
5. Next-frame button increments the frame counter display
6. Key-frame button sets the frame counter to `frame_number`
7. Reject calls `PUT /detections` with status `"rejected"`
8. Re-scan with existing saved results overwrites and resets all statuses to `"pending"`

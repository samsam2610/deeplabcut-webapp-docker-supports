---
name: DLC-3D Extract Frames
description: Design spec for the dlc-3D support module — standalone Flask app for extract-frames workflow on multi-camera 3D DLC projects
type: project
---

# DLC-3D Extract Frames — Design Spec

**Date:** 2026-04-30  
**Scope:** Extract-frames feature only. The full 3D module workflow (label frames, analyze, annotate) is future work.

---

## 1. Architecture

### Module structure

```
dlc-3D/
  app.py                  ← Flask factory, registers blueprint, sets port 5050
  config.py               ← DATA_DIR, allowed roots, port constant
  routes.py               ← all routes under /dlc-3d/*
  viewer.py               ← single-frame video cache (copied from clip-cutter)
  Dockerfile
  requirements.txt
  docker-compose.yml
  templates/
    dlc_3d.html           ← full-page shell
  static/
    dlc_3d.js             ← session browser + extract logic
    enhanced_player.js    ← sync-cam, sibling detection (ported from clip-cutter)
```

The module is fully self-contained. It reads and writes to the same data disk mounts the main webapp uses. It does not import or call any code from the main webapp.

### Main webapp changes (exactly 3)

1. **`docker-compose.yml`** — add `dlc-3d` service on the internal Docker network, no exposed host port, port 5050 internally.
2. **`base.html`** — add one nav link: `3D Extractor` → `/dlc-3d/`.
3. **`app.py`** — one catch-all proxy route forwarding `GET|POST /dlc-3d/<path>` → `http://dlc-3d:5050/dlc-3d/<path>`.

No nginx changes required. The existing `ppp.conf` has a `location /` catch-all that forwards everything to `localhost:5000` (the Flask container), which then proxies to the module.

---

## 2. 3D Project Model

### Opening a project

User browses the server filesystem to a DLC `config.yaml` using the same server-file-browser widget pattern as the main webapp. The selected project path is stored in a server-side module-level variable (no Redis; this is a single-user tool).

### `videos.json` — persistent video registry

Stored at `<dlc-project>/videos.json` alongside `config.yaml`. Written on first scan; reloaded on every subsequent page load without re-crawling. A **Rescan** button on the UI overwrites it.

Paths are stored relative to `project_path` so the file is portable if the mount point changes.

**Structure:**
```json
{
  "project_path": "/user-data/Parra-Data/Disk/DLC-Projects/DREADD-Ali-2026-01-07",
  "scanned_at": "2026-04-30T12:00:00",
  "sessions": {
    "surv1_20260123": {
      "cam0": {
        "avi": "videos/surv1_cam0_20260123_121732_0_trig1_fps200_exposure1500_gain10.avi",
        "csv": "videos/surv1_cam0_20260123_121732_0_trig1_fps200_exposure1500_gain10.csv",
        "clip_folder": "videos/surv1_cam0_20260123_121732_0_trig1_fps200_exposure1500_gain10/",
        "clips": [
          "videos/surv1_cam0_20260123_121732_0_trig1_fps200_exposure1500_gain10/clip_001.avi"
        ]
      },
      "cam1": {
        "avi": "videos/surv1_cam1_20260123_121743_0_trig2_fps200_exposure1500_gain10.avi",
        "csv": "videos/surv1_cam1_20260123_121743_0_trig2_fps200_exposure1500_gain10.csv",
        "clip_folder": "videos/surv1_cam1_20260123_121743_0_trig2_fps200_exposure1500_gain10/",
        "clips": [
          "videos/surv1_cam1_20260123_121743_0_trig2_fps200_exposure1500_gain10/clip_001.avi"
        ]
      }
    }
  }
}
```

`clip_folder` and `clips` are `null` if no pre-processed folder exists.

### Session key derivation

Video stem: `surv1_cam0_20260123_121732_0_trig1_fps200_exposure1500_gain10`

Regex: `^(.+?)_cam\d+_(\d{8})`
- Group 1 (subject): `surv1`
- Group 2 (date): `20260123`
- Session key: `surv1_20260123`

### Calibration

On the **first frame save** into a session folder, the server auto-detects and copies `calibration.toml` into `labeled-data/{session}/calibration.toml`. Search order (first match wins):

1. `<project>/calibration.toml`
2. `<project>/calibration/calibration.toml`
3. `<project>/videos/calibration.toml`

If none found, the copy is skipped silently — the extract still succeeds and the user can place the file manually later. Subsequent saves into the same session folder skip the copy (file already present).

---

## 3. Video Player + Sync-Cam UI

### Layout

- **Left panel:** session/video browser — lists sessions, expands to show cameras and clip folders, click a clip or raw video to load it in the player.
- **Right:** one or two video panels depending on sync-cam state.
- Primary camera panel is always visible.
- Secondary (sibling) panel appears only when sync-cam is enabled AND a sibling was found.
- Below panels: frame counter, seek bar, skip controls (±1, ±N), **Extract Frame** button.
- Extract status bar shows `img_cam{N}_...` filenames as each camera saves.

### Sync-cam behaviour (identical to clip-cutter)

- When user selects a clip, server resolves the sibling camera path from `videos.json` and returns it in the select response.
- `Sync Cam` checkbox appears only if a sibling was found; hidden otherwise.
- Checking it opens the cam2 panel and loads the same frame number from the sibling video.
- Both panels scrub in lockstep — seeking primary also fetches sibling frame.
- `Extract Sibling` checkbox (shown below Sync Cam when sibling exists) defaults to checked.
- Unchecking it saves only the primary camera frame on extract.

### Sibling resolution

Server-side: given primary video path, look up `videos.json` for the same session key and return all other camera paths. For the initial implementation (2-camera sessions), return the first other camera. The client receives `sibling_video_path` in the select-video response.

---

## 4. Frame Extraction Logic

### Route

`POST /dlc-3d/save-frame`

### Request body

```json
{
  "project_path": "/user-data/.../DREADD-Ali-2026-01-07",
  "primary_video": "videos/surv1_cam0_20260123_121732_0_...",
  "primary_frame_data": "<base64 JPEG>",
  "primary_frame_number": 847,
  "sibling_video": "videos/surv1_cam1_20260123_121743_0_...",
  "sibling_frame_data": "<base64 JPEG>",
  "extract_sibling": true
}
```

`sibling_video` and `sibling_frame_data` may be omitted or null when `extract_sibling` is false.

### Server logic

1. Derive session key `{subject}_{date}` from primary video stem using the regex above.
2. Resolve `labeled_dir = <project>/labeled-data/{session_key}/`; create if absent.
3. Parse camera index `N` from `_cam{N}_` in the video stem (single digit).
4. Count existing `img_cam{N}_*.png` files in `labeled_dir` → `order` (per-camera, independent).
5. Duplicate check: if any file matches `img_cam{N}_????_{frame_number:05d}.png`, return `{"skipped": true}`.
6. Decode base64 JPEG → PNG via OpenCV → write `img_cam{N}_{order:04d}_{frame_number:05d}.png`.
7. If `extract_sibling=true`: repeat steps 3–6 for sibling video + sibling frame data.
8. On first save into `labeled_dir` (no existing PNGs): auto-detect `calibration.toml` by searching `<project>/calibration.toml`, then `<project>/calibration/calibration.toml`, then `<project>/videos/calibration.toml`; copy first match to `labeled_dir/calibration.toml`. Skip silently if none found.
9. Return saved filenames and session folder path.

### Frame naming

Format: `img_cam{N}_{order:04d}_{frame:05d}.png`

Regex to parse: `img_cam(\d)_(\d{4})_(\d+)\.png`
- Group 1: camera index
- Group 2: insertion order (per-camera)
- Group 3: source video frame number

**Examples** — session `surv1_20260123`, cam0 has 5 existing frames, cam1 has 3:
- cam0, video frame 847 → `img_cam0_0005_00847.png`
- cam1, video frame 847 → `img_cam1_0003_00847.png`

### Response

```json
{
  "saved": ["img_cam0_0005_00847.png", "img_cam1_0003_00847.png"],
  "session_folder": "labeled-data/surv1_20260123",
  "frame_counts": {"cam0": 6, "cam1": 4}
}
```

---

## 5. Routes Summary

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/dlc-3d/` | Serve main page (`dlc_3d.html`) |
| `GET` | `/dlc-3d/browse` | Filesystem browser (find `config.yaml`) |
| `POST` | `/dlc-3d/project` | Set active project; load or create `videos.json` |
| `POST` | `/dlc-3d/project/rescan` | Re-crawl videos, overwrite `videos.json` |
| `GET` | `/dlc-3d/project/sessions` | Return sessions from `videos.json` |
| `GET` | `/dlc-3d/frame` | Stream a single video frame as JPEG (`?video=...&n=...`) |
| `GET` | `/dlc-3d/video-info` | Return fps/frame-count for a video |
| `GET` | `/dlc-3d/sibling-camera` | Return sibling camera path for loaded video |
| `POST` | `/dlc-3d/save-frame` | Extract and save frames (primary + optional sibling) |
| `GET` | `/dlc-3d/labeled-frames` | List already-extracted frames for a session |

---

## 6. Out of Scope (this session)

- Label frames (CollectedData CSV editing)
- Analyze video / view analyzed output
- Annotate video
- Support for >2 cameras (sibling returns first other camera only)
- Uploading videos to the project

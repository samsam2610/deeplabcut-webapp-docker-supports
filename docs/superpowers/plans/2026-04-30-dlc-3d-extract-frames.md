# DLC-3D Extract Frames — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Flask support module (`dlc-3D/`) that lets users browse a DLC project, view multi-camera video pairs with a sync-cam player, and extract frames that are saved with per-camera naming (`img_cam{N}_{order:04d}_{frame:05d}.png`) into a shared session folder under `labeled-data/`.

**Architecture:** Standalone Flask app (port 5050) behind the main webapp's catch-all proxy — no shared code with the main app. Ports the clip-cutter sync-cam player pattern directly, removing scan/template/detection logic and replacing the extract queue with a direct save-frame route. The main webapp gets exactly three changes: docker-compose service, nav button, proxy route.

**Tech Stack:** Python 3.11, Flask ≥3.0, OpenCV (headless), pytest; vanilla JS ES modules (no build step).

**Spec:** `docs/superpowers/specs/2026-04-30-dlc-3d-extract-frames-design.md`

---

## File Map

| Path | Action | Purpose |
|------|--------|---------|
| `dlc-3D/config.py` | Create | Port, data roots |
| `dlc-3D/app.py` | Create | Flask factory |
| `dlc-3D/viewer.py` | Create | LRU video frame cache (verbatim copy from clip-cutter) |
| `dlc-3D/routes.py` | Create | All routes + helper functions |
| `dlc-3D/Dockerfile` | Create | Lightweight image (no ML models) |
| `dlc-3D/requirements.txt` | Create | Flask, OpenCV, pytest |
| `dlc-3D/docker-compose.yml` | Create | Dev compose with live-reload mounts |
| `dlc-3D/templates/dlc_3d.html` | Create | Full-page shell |
| `dlc-3D/static/enhanced_player.js` | Create | Sync-cam video player (ported, stripped of scan/template logic) |
| `dlc-3D/static/dlc_3d.js` | Create | Session browser + extract UI |
| `dlc-3D/tests/__init__.py` | Create | Empty |
| `dlc-3D/tests/conftest.py` | Create | sys.path fixture |
| `dlc-3D/tests/test_core.py` | Create | Unit tests for pure Python helpers |
| `../deeplabcut-webapp-docker/docker-compose.yml` | Modify | Add dlc-3d service |
| `../deeplabcut-webapp-docker/src/templates/base.html` | Modify | Add nav button |
| `../deeplabcut-webapp-docker/src/app.py` | Modify | Add proxy route |

---

## Task 1: Module scaffold

**Files:**
- Create: `dlc-3D/config.py`
- Create: `dlc-3D/app.py`
- Create: `dlc-3D/viewer.py`
- Create: `dlc-3D/Dockerfile`
- Create: `dlc-3D/requirements.txt`
- Create: `dlc-3D/docker-compose.yml`
- Create: `dlc-3D/tests/__init__.py`
- Create: `dlc-3D/tests/conftest.py`

- [ ] **Step 1: Write `config.py`**

```python
# dlc-3D/config.py
from pathlib import Path
import os

PORT = int(os.environ.get("DLC_3D_PORT", 5050))

USER_DATA_ROOTS = [
    Path("/user-data/Parra-Data/Disk"),
    Path("/user-data/Parra-Data/Cloud"),
    Path("/user-data/Martin-Data/USB"),
    Path("/user-data/NAS-Data-Share"),
]
```

- [ ] **Step 2: Write `app.py`**

```python
# dlc-3D/app.py
from flask import Flask
from routes import bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.register_blueprint(bp)
    return app


if __name__ == "__main__":
    from config import PORT
    import os
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    create_app().run(host="0.0.0.0", port=PORT, debug=debug, threaded=True)
```

- [ ] **Step 3: Write `viewer.py`** (verbatim copy from clip-cutter — already tested)

```python
# dlc-3D/viewer.py
from __future__ import annotations

import threading
from collections import OrderedDict

import cv2

_VCAP_MAX = 4
_vcap_cache: OrderedDict = OrderedDict()
_vcap_lock = threading.Lock()


def get_video_info(video_path: str) -> dict:
    """Return {frame_count: int, fps: float}. Raises FileNotFoundError if unopenable."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {video_path}")
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()
    return {"frame_count": frame_count, "fps": fps}


def get_frame_jpeg(video_path: str, frame_number: int, quality: int = 80) -> bytes:
    """
    Return JPEG bytes for the given 0-based frame_number.
    Keeps a per-path VideoCapture open (LRU cache, max _VCAP_MAX entries).
    Sequential reads skip the seek for faster playback.
    Raises FileNotFoundError or ValueError on failure.
    """
    vpath = str(video_path)

    with _vcap_lock:
        if vpath not in _vcap_cache:
            if len(_vcap_cache) >= _VCAP_MAX:
                _, evicted = _vcap_cache.popitem(last=False)
                with evicted["lock"]:
                    if evicted["vcap"] is not None:
                        evicted["vcap"].release()
                        evicted["vcap"] = None
            _vcap_cache[vpath] = {
                "vcap": None,
                "pos": -1,
                "lock": threading.Lock(),
            }
        _vcap_cache.move_to_end(vpath)
        entry = _vcap_cache[vpath]

    with entry["lock"]:
        if entry["vcap"] is None or not entry["vcap"].isOpened():
            entry["vcap"] = cv2.VideoCapture(vpath)
            entry["pos"] = -1
            if not entry["vcap"].isOpened():
                raise FileNotFoundError(f"Cannot open video: {vpath}")

        if frame_number != entry["pos"] + 1:
            entry["vcap"].set(cv2.CAP_PROP_POS_FRAMES, frame_number)

        ok, frame = entry["vcap"].read()
        entry["pos"] = frame_number if ok else -1

    if not ok:
        raise ValueError(f"Cannot read frame {frame_number} from {vpath}")

    ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok2:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()
```

- [ ] **Step 4: Write `requirements.txt`**

```
flask>=3.0
opencv-python-headless>=4.8
numpy>=1.24
pytest>=8.0
```

- [ ] **Step 5: Write `Dockerfile`**

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5050

CMD ["python", "app.py"]
```

- [ ] **Step 6: Write `docker-compose.yml`** (standalone dev compose for this module)

```yaml
services:
  dlc-3d:
    build:
      context: .
      dockerfile: Dockerfile
    image: dlc-3d:latest
    ports:
      - "5050:5050"
    volumes:
      - /home/sam/data-disk/Parra-Data:/user-data/Parra-Data/Disk
      - /home/sam/synology/Parra-Lab-Data:/user-data/Parra-Data/Cloud
      - /home/sam/data-mount-dir:/user-data/Martin-Data/USB
      - /home/sam/Parra-Lab-Data-NAS:/user-data/NAS-Data-Share
      - ./app.py:/app/app.py
      - ./config.py:/app/config.py
      - ./routes.py:/app/routes.py
      - ./viewer.py:/app/viewer.py
      - ./templates:/app/templates
      - ./static:/app/static
    environment:
      - DLC_3D_PORT=5050
      - FLASK_DEBUG=0
    restart: unless-stopped
```

- [ ] **Step 7: Write `tests/__init__.py`** (empty file)

- [ ] **Step 8: Write `tests/conftest.py`**

```python
# dlc-3D/tests/conftest.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
```

- [ ] **Step 9: Commit**

```bash
git add dlc-3D/
git commit -m "feat(dlc-3d): add module scaffold — config, app, viewer, Dockerfile, docker-compose"
```

---

## Task 2: Core Python helpers + tests

**Files:**
- Create: `dlc-3D/tests/test_core.py`
- Create: `dlc-3D/routes.py` (initial — helpers only, no routes yet)

The helpers live at module level in `routes.py` so tests can import them directly.

- [ ] **Step 1: Write the failing tests in `tests/test_core.py`**

```python
# dlc-3D/tests/test_core.py
import json
import re
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from routes import (
    _cam_index_from_stem,
    _find_sibling_video,
    _save_single_frame,
    _scan_videos,
    _session_key_from_stem,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_video(path: Path, frames: int = 10, w: int = 32, h: int = 32) -> None:
    out = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"XVID"), 30.0, (w, h)
    )
    for i in range(frames):
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:] = (i * 25 % 256, 100, 50)
        out.write(frame)
    out.release()


def _fake_project(tmp_path: Path, cams=("cam0", "cam1"), clips=False) -> Path:
    """Create a minimal project layout with AVI files for each cam."""
    proj = tmp_path / "project"
    videos = proj / "videos"
    videos.mkdir(parents=True)
    (videos / "calibration.toml").write_text("[cam_0]\nname = '0'\n")
    for cam in cams:
        stem = f"surv1_{cam}_20260123_121732_0_trig1"
        avi = videos / f"{stem}.avi"
        _make_video(avi, frames=20)
        (videos / f"{stem}.csv").touch()
        if clips:
            clip_dir = videos / stem
            clip_dir.mkdir()
            _make_video(clip_dir / "clip_001.avi", frames=15)
    return proj


# ── _session_key_from_stem ───────────────────────────────────────────────────

def test_session_key_standard():
    assert _session_key_from_stem(
        "surv1_cam0_20260123_121732_0_trig1_fps200_exposure1500_gain10"
    ) == "surv1_20260123"


def test_session_key_hyphenated_subject():
    assert _session_key_from_stem("my-rat_cam1_20260205_090000_0") == "my-rat_20260205"


def test_session_key_no_cam_pattern_returns_none():
    assert _session_key_from_stem("MAP2_20250715_120050_0") is None


def test_session_key_no_date_returns_none():
    assert _session_key_from_stem("surv1_cam0_nodate") is None


# ── _cam_index_from_stem ─────────────────────────────────────────────────────

def test_cam_index_cam0():
    assert _cam_index_from_stem("surv1_cam0_20260123_121732_0") == 0


def test_cam_index_cam1():
    assert _cam_index_from_stem("surv1_cam1_20260123_121743_0") == 1


def test_cam_index_no_pattern_returns_none():
    assert _cam_index_from_stem("MAP2_20250715_120050_0") is None


# ── _scan_videos ─────────────────────────────────────────────────────────────

def test_scan_videos_groups_by_session(tmp_path):
    proj = _fake_project(tmp_path)
    sessions = _scan_videos(proj)
    assert "surv1_20260123" in sessions
    assert "cam0" in sessions["surv1_20260123"]
    assert "cam1" in sessions["surv1_20260123"]


def test_scan_videos_relative_paths(tmp_path):
    proj = _fake_project(tmp_path)
    sessions = _scan_videos(proj)
    cam0 = sessions["surv1_20260123"]["cam0"]
    assert cam0["avi"].startswith("videos/")
    assert not cam0["avi"].startswith("/")


def test_scan_videos_csv_included(tmp_path):
    proj = _fake_project(tmp_path)
    sessions = _scan_videos(proj)
    assert sessions["surv1_20260123"]["cam0"]["csv"] is not None


def test_scan_videos_no_clips_when_no_folder(tmp_path):
    proj = _fake_project(tmp_path, clips=False)
    cam0 = _scan_videos(proj)["surv1_20260123"]["cam0"]
    assert cam0["clip_folder"] is None
    assert cam0["clips"] is None


def test_scan_videos_detects_clip_folder(tmp_path):
    proj = _fake_project(tmp_path, clips=True)
    cam0 = _scan_videos(proj)["surv1_20260123"]["cam0"]
    assert cam0["clip_folder"] is not None
    assert len(cam0["clips"]) == 1
    assert cam0["clips"][0].endswith("clip_001.avi")


def test_scan_videos_skips_unmatched_avi(tmp_path):
    proj = _fake_project(tmp_path, cams=())
    (proj / "videos" / "unrelated.avi").touch()
    sessions = _scan_videos(proj)
    assert sessions == {}


# ── _find_sibling_video ───────────────────────────────────────────────────────

def test_find_sibling_raw_video(tmp_path):
    proj = _fake_project(tmp_path)
    sessions = _scan_videos(proj)
    videos_json = {"sessions": sessions}
    sibling = _find_sibling_video("videos/surv1_cam0_20260123_121732_0_trig1.avi", videos_json)
    assert sibling is not None
    assert "cam1" in sibling


def test_find_sibling_clip(tmp_path):
    proj = _fake_project(tmp_path, clips=True)
    sessions = _scan_videos(proj)
    videos_json = {"sessions": sessions}
    primary_clip = sessions["surv1_20260123"]["cam0"]["clips"][0]
    sibling = _find_sibling_video(primary_clip, videos_json)
    assert sibling is not None
    assert "cam1" in sibling
    assert sibling.endswith("clip_001.avi")


def test_find_sibling_returns_none_for_single_cam(tmp_path):
    proj = _fake_project(tmp_path, cams=("cam0",))
    sessions = _scan_videos(proj)
    videos_json = {"sessions": sessions}
    sibling = _find_sibling_video("videos/surv1_cam0_20260123_121732_0_trig1.avi", videos_json)
    assert sibling is None


# ── _save_single_frame ────────────────────────────────────────────────────────

def test_save_frame_creates_png(tmp_path):
    proj = _fake_project(tmp_path)
    result = _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 5)
    assert "saved" in result
    assert result["saved"] == "img_cam0_0000_00005.png"
    labeled_dir = proj / "labeled-data" / "surv1_20260123"
    assert (labeled_dir / "img_cam0_0000_00005.png").exists()


def test_save_frame_png_is_valid_image(tmp_path):
    proj = _fake_project(tmp_path)
    _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 3)
    labeled_dir = proj / "labeled-data" / "surv1_20260123"
    img = cv2.imread(str(labeled_dir / "img_cam0_0000_00003.png"))
    assert img is not None
    assert img.shape[:2] == (32, 32)


def test_save_frame_copies_calibration(tmp_path):
    proj = _fake_project(tmp_path)
    _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 3)
    calib_dest = proj / "labeled-data" / "surv1_20260123" / "calibration.toml"
    assert calib_dest.exists()


def test_save_frame_skips_calibration_copy_on_second_save(tmp_path):
    proj = _fake_project(tmp_path)
    _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 3)
    # Modify destination to detect if it gets overwritten
    dest = proj / "labeled-data" / "surv1_20260123" / "calibration.toml"
    dest.write_text("modified")
    _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 7)
    assert dest.read_text() == "modified"


def test_save_frame_duplicate_skipped(tmp_path):
    proj = _fake_project(tmp_path)
    r1 = _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 5)
    r2 = _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 5)
    assert "saved" in r1
    assert r2.get("skipped") is True


def test_save_frame_order_increments(tmp_path):
    proj = _fake_project(tmp_path)
    r1 = _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 3)
    r2 = _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 7)
    assert r1["saved"] == "img_cam0_0000_00003.png"
    assert r2["saved"] == "img_cam0_0001_00007.png"


def test_save_frame_cam_order_independent(tmp_path):
    """cam0 and cam1 orders are counted separately."""
    proj = _fake_project(tmp_path)
    _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 3)
    _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 7)
    r_cam1 = _save_single_frame(proj, "videos/surv1_cam1_20260123_121732_0_trig1.avi", 3)
    # cam1 order starts at 0, not 2
    assert r_cam1["saved"] == "img_cam1_0000_00003.png"
```

- [ ] **Step 2: Run tests — expect ImportError (routes.py not yet written)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name '_session_key_from_stem' from 'routes'`

- [ ] **Step 3: Write `routes.py` with helpers only (no routes yet)**

```python
# dlc-3D/routes.py
from __future__ import annotations

import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from flask import Blueprint, Response, jsonify, render_template, request

import config
import viewer

bp = Blueprint(
    "dlc_3d", __name__, url_prefix="/dlc-3d",
    template_folder="templates",
    static_folder="static", static_url_path="/static",
)

# ── Server state (single-user) ───────────────────────────────────────────────

_active_project: str | None = None
_state_lock = threading.Lock()

# ── Regex helpers ─────────────────────────────────────────────────────────────

_SESSION_RE = re.compile(r'^(.+?)_cam\d+_(\d{8})')
_CAM_RE     = re.compile(r'_cam(\d+)_')
_FRAME_RE   = re.compile(r'^img_cam(\d)_(\d{4})_(\d+)\.png$')


def _session_key_from_stem(stem: str) -> "str | None":
    """'surv1_cam0_20260123_...' → 'surv1_20260123'. None if no match."""
    m = _SESSION_RE.match(stem)
    if not m:
        return None
    return f"{m.group(1)}_{m.group(2)}"


def _cam_index_from_stem(stem: str) -> "int | None":
    """'surv1_cam0_20260123_...' → 0. None if no match."""
    m = _CAM_RE.search(stem)
    return int(m.group(1)) if m else None


# ── Video scanning ────────────────────────────────────────────────────────────

def _scan_videos(project_path: Path) -> dict:
    """
    Crawl <project>/videos/ for *_cam<N>_*.avi files.
    Returns sessions dict keyed by '{subject}_{date}'.
    All paths are relative to project_path.
    """
    videos_dir = project_path / "videos"
    sessions: dict = {}
    if not videos_dir.is_dir():
        return sessions

    for avi in sorted(videos_dir.glob("*.avi")):
        stem = avi.stem
        session_key = _session_key_from_stem(stem)
        cam_idx = _cam_index_from_stem(stem)
        if session_key is None or cam_idx is None:
            continue

        csv_path = avi.with_suffix(".csv")
        clip_dir = videos_dir / stem
        if clip_dir.is_dir():
            clips = sorted(
                str(f.relative_to(project_path))
                for f in sorted(clip_dir.glob("*.avi"))
            )
            clip_folder = str(clip_dir.relative_to(project_path)) + "/"
        else:
            clips = None
            clip_folder = None

        cam_key = f"cam{cam_idx}"
        sessions.setdefault(session_key, {})[cam_key] = {
            "avi":         str(avi.relative_to(project_path)),
            "csv":         str(csv_path.relative_to(project_path)) if csv_path.exists() else None,
            "clip_folder": clip_folder,
            "clips":       clips,
        }

    return sessions


def _load_or_scan_videos(project_path: Path) -> dict:
    """Load videos.json if present, otherwise scan and write it."""
    vj = project_path / "videos.json"
    if vj.exists():
        with open(vj) as f:
            return json.load(f)
    return _rescan_and_save(project_path)


def _rescan_and_save(project_path: Path) -> dict:
    sessions = _scan_videos(project_path)
    data = {
        "project_path": str(project_path),
        "scanned_at":   datetime.now(timezone.utc).isoformat(),
        "sessions":     sessions,
    }
    (project_path / "videos.json").write_text(json.dumps(data, indent=2))
    return data


# ── Sibling resolution ────────────────────────────────────────────────────────

def _find_sibling_video(video_rel: str, videos_json: dict) -> "str | None":
    """
    Return the sibling camera's video path (relative) for a given video.
    Handles both raw videos and clips inside clip folders.
    """
    vp = Path(video_rel)
    parent_name = vp.parent.name  # "videos" or a clip-folder stem

    is_clip = _session_key_from_stem(parent_name) is not None
    if is_clip:
        folder_stem = parent_name           # e.g. surv1_cam0_20260123_...
        clip_name   = vp.name               # e.g. clip_001.avi
        session_key = _session_key_from_stem(folder_stem)
        cam_idx     = _cam_index_from_stem(folder_stem)
    else:
        session_key = _session_key_from_stem(vp.stem)
        cam_idx     = _cam_index_from_stem(vp.stem)
        clip_name   = None

    if session_key is None or cam_idx is None:
        return None

    session = videos_json.get("sessions", {}).get(session_key, {})
    for cam_key, cam_data in sorted(session.items()):
        if cam_key == f"cam{cam_idx}":
            continue
        if is_clip:
            for clip_path in (cam_data.get("clips") or []):
                if Path(clip_path).name == clip_name:
                    return clip_path
            return None
        else:
            return cam_data.get("avi")

    return None


# ── Frame saving ──────────────────────────────────────────────────────────────

def _save_single_frame(project_path: Path, video_rel: str, frame_number: int) -> dict:
    """
    Save one frame from video_rel at frame_number into labeled-data/{session_key}/.
    Returns {"saved": filename} or {"skipped": True, "frame_number": N}.
    Also copies calibration.toml on first save into the session folder.
    """
    stem = Path(video_rel).stem
    # If video is inside a clip folder, use the clip folder's stem for session/cam
    parent_name = Path(video_rel).parent.name
    if _session_key_from_stem(parent_name) is not None:
        stem = parent_name  # resolve session/cam from the clip-folder stem

    session_key = _session_key_from_stem(stem)
    cam_idx     = _cam_index_from_stem(stem)
    if session_key is None or cam_idx is None:
        raise ValueError(f"Cannot derive session/cam from {video_rel!r}")

    labeled_dir = project_path / "labeled-data" / session_key
    labeled_dir.mkdir(parents=True, exist_ok=True)

    # Duplicate check
    existing = sorted(labeled_dir.glob(f"img_cam{cam_idx}_*.png"))
    for f in existing:
        m = _FRAME_RE.match(f.name)
        if m and int(m.group(3)) == frame_number:
            return {"skipped": True, "frame_number": frame_number}

    # Read frame from video → PNG
    video_path = project_path / video_rel
    frame_jpeg = viewer.get_frame_jpeg(str(video_path), frame_number)
    nparr = np.frombuffer(frame_jpeg, np.uint8)
    img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"Could not decode frame {frame_number} from {video_rel}")
    ok, png_buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encoding failed")

    order = len(existing)
    fname = f"img_cam{cam_idx}_{order:04d}_{frame_number:05d}.png"
    (labeled_dir / fname).write_bytes(png_buf.tobytes())

    # Copy calibration.toml on first save (no existing PNGs before this one)
    if order == 0:
        calib_src  = project_path / "videos" / "calibration.toml"
        calib_dest = labeled_dir / "calibration.toml"
        if calib_src.exists() and not calib_dest.exists():
            shutil.copy2(calib_src, calib_dest)

    return {"saved": fname, "order": order + 1}
```

- [ ] **Step 4: Run tests — all should pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py -v
```

Expected: all tests pass. If a test fails, fix the helper before continuing.

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/tests/ dlc-3D/routes.py
git commit -m "feat(dlc-3d): add core Python helpers with full test coverage"
```

---

## Task 3: Flask routes

**Files:**
- Modify: `dlc-3D/routes.py` (append all route handlers)

- [ ] **Step 1: Append route handlers to `routes.py`**

Add after the helpers (after `_save_single_frame`):

```python
# ── UI ────────────────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    return render_template("dlc_3d.html")


# ── Filesystem browser ────────────────────────────────────────────────────────

@bp.route("/browse")
def browse():
    path_str = request.args.get("path", "").strip()
    if path_str:
        p = Path(path_str)
    else:
        p = next((r for r in config.USER_DATA_ROOTS if r.is_dir()), Path("/"))

    if not p.is_dir():
        return jsonify({"error": "not a directory"}), 400

    entries = []
    try:
        for entry in sorted(p.iterdir(), key=lambda e: e.name.lower()):
            if entry.name.startswith(".") or entry.name.startswith("@"):
                continue
            if entry.is_dir():
                has_config = (entry / "config.yaml").exists()
                entries.append({"name": entry.name, "type": "dir", "has_config": has_config})
            elif entry.name == "config.yaml":
                entries.append({"name": entry.name, "type": "yaml"})
    except PermissionError:
        return jsonify({"error": "permission denied"}), 403

    parent = str(p.parent) if str(p.parent) != str(p) else None
    return jsonify({"path": str(p), "parent": parent, "entries": entries})


# ── Project ───────────────────────────────────────────────────────────────────

@bp.route("/project", methods=["POST"])
def set_project():
    """Set active project by config.yaml path or project directory path."""
    global _active_project
    body = request.get_json(force=True) or {}
    path_str = (body.get("path") or "").strip()
    if not path_str:
        return jsonify({"error": "path required"}), 400

    p = Path(path_str)
    # Accept either config.yaml path or the directory itself
    if p.name == "config.yaml":
        p = p.parent
    if not (p / "config.yaml").exists():
        return jsonify({"error": "config.yaml not found at that path"}), 404

    with _state_lock:
        _active_project = str(p)

    data = _load_or_scan_videos(p)
    return jsonify({"project_path": str(p), "sessions": data.get("sessions", {})})


@bp.route("/project/rescan", methods=["POST"])
def rescan_project():
    with _state_lock:
        proj = _active_project
    if not proj:
        return jsonify({"error": "no active project"}), 400
    data = _rescan_and_save(Path(proj))
    return jsonify({"sessions": data.get("sessions", {})})


@bp.route("/project/sessions")
def get_sessions():
    with _state_lock:
        proj = _active_project
    if not proj:
        return jsonify({"sessions": {}})
    data = _load_or_scan_videos(Path(proj))
    return jsonify({"sessions": data.get("sessions", {})})


# ── Video / frame serving ─────────────────────────────────────────────────────

@bp.route("/frame")
def get_frame():
    with _state_lock:
        proj = _active_project
    video_path = request.args.get("video", "").strip()
    n_str      = request.args.get("n", "").strip()
    if not video_path or not n_str or not proj:
        return jsonify({"error": "video, n, and active project required"}), 400
    try:
        n = int(n_str)
    except ValueError:
        return jsonify({"error": "n must be an integer"}), 400

    etag = f'"dlc3d-{video_path}-{n}"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304)

    full_path = Path(proj) / video_path
    try:
        data = viewer.get_frame_jpeg(str(full_path), n)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except (ValueError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 400

    resp = Response(data, mimetype="image/jpeg")
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@bp.route("/video-info")
def get_video_info():
    with _state_lock:
        proj = _active_project
    video_path = request.args.get("video", "").strip()
    if not video_path or not proj:
        return jsonify({"error": "video and active project required"}), 400
    full_path = Path(proj) / video_path
    try:
        info = viewer.get_video_info(str(full_path))
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify(info)


@bp.route("/sibling-camera")
def get_sibling_camera():
    with _state_lock:
        proj = _active_project
    video_rel = request.args.get("video", "").strip()
    if not video_rel or not proj:
        return jsonify({"sibling_video_path": None})

    vj_path = Path(proj) / "videos.json"
    if not vj_path.exists():
        return jsonify({"sibling_video_path": None})
    with open(vj_path) as f:
        videos_json = json.load(f)

    sibling = _find_sibling_video(video_rel, videos_json)
    return jsonify({"sibling_video_path": sibling})


# ── Frame extraction ──────────────────────────────────────────────────────────

@bp.route("/save-frame", methods=["POST"])
def save_frame():
    with _state_lock:
        proj = _active_project
    if not proj:
        return jsonify({"error": "no active project"}), 400

    body             = request.get_json(force=True) or {}
    primary_video    = (body.get("primary_video")    or "").strip()
    primary_frame    = body.get("primary_frame_number")
    extract_sibling  = bool(body.get("extract_sibling", False))
    sibling_video    = (body.get("sibling_video")    or "").strip()
    sibling_frame    = body.get("sibling_frame_number")

    if not primary_video or primary_frame is None:
        return jsonify({"error": "primary_video and primary_frame_number required"}), 400

    project_path = Path(proj)
    saved = []
    skipped = []

    try:
        r = _save_single_frame(project_path, primary_video, int(primary_frame))
        if r.get("skipped"):
            skipped.append(r)
        else:
            saved.append(r["saved"])
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return jsonify({"error": str(e)}), 400

    if extract_sibling and sibling_video and sibling_frame is not None:
        try:
            r2 = _save_single_frame(project_path, sibling_video, int(sibling_frame))
            if r2.get("skipped"):
                skipped.append(r2)
            else:
                saved.append(r2["saved"])
        except (ValueError, RuntimeError, FileNotFoundError) as e:
            return jsonify({"error": f"sibling save failed: {e}"}), 400

    # Derive session folder for display
    stem = Path(primary_video).stem
    parent_name = Path(primary_video).parent.name
    if _session_key_from_stem(parent_name) is not None:
        stem = parent_name
    session_key = _session_key_from_stem(stem) or stem

    return jsonify({
        "saved":          saved,
        "skipped":        skipped,
        "session_folder": f"labeled-data/{session_key}",
    }), 201 if saved else 200


# ── Labeled frames ────────────────────────────────────────────────────────────

@bp.route("/labeled-frames")
def labeled_frames():
    with _state_lock:
        proj = _active_project
    session_key = request.args.get("session", "").strip()
    if not session_key or not proj:
        return jsonify({"frames": [], "count": 0})

    labeled_dir = Path(proj) / "labeled-data" / session_key
    if not labeled_dir.is_dir():
        return jsonify({"frames": [], "count": 0, "session_folder": f"labeled-data/{session_key}"})

    frames = sorted(f.name for f in labeled_dir.glob("img_cam*.png"))
    return jsonify({
        "frames":         frames,
        "count":          len(frames),
        "session_folder": f"labeled-data/{session_key}",
    })
```

- [ ] **Step 2: Verify tests still pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py -v
```

Expected: all tests pass (adding routes to routes.py shouldn't break the helpers).

- [ ] **Step 3: Commit**

```bash
git add dlc-3D/routes.py
git commit -m "feat(dlc-3d): add all Flask routes (browse, project, frame, save-frame, labeled-frames)"
```

---

## Task 4: Main webapp integration

**Files:**
- Modify: `../deeplabcut-webapp-docker/docker-compose.yml`
- Modify: `../deeplabcut-webapp-docker/src/templates/base.html`
- Modify: `../deeplabcut-webapp-docker/src/app.py`

- [ ] **Step 1: Add `dlc-3d` service to `docker-compose.yml`**

Find the `networks:` block at the bottom of `/home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml`.
Insert the new service **before** the `volumes:` block:

```yaml
  # ── DLC-3D Support Module ───────────────────────────────────────
  dlc-3d:
    build:
      context: ../deeplabcut-webapp-docker-supports/dlc-3D
      dockerfile: Dockerfile
    image: dlc-3d:latest
    volumes:
      - /home/sam/data-disk/Parra-Data:/user-data/Parra-Data/Disk
      - /home/sam/synology/Parra-Lab-Data:/user-data/Parra-Data/Cloud
      - /home/sam/data-mount-dir:/user-data/Martin-Data/USB
      - /home/sam/Parra-Lab-Data-NAS:/user-data/NAS-Data-Share
      - ../deeplabcut-webapp-docker-supports/dlc-3D/routes.py:/app/routes.py
      - ../deeplabcut-webapp-docker-supports/dlc-3D/config.py:/app/config.py
      - ../deeplabcut-webapp-docker-supports/dlc-3D/viewer.py:/app/viewer.py
      - ../deeplabcut-webapp-docker-supports/dlc-3D/templates:/app/templates
      - ../deeplabcut-webapp-docker-supports/dlc-3D/static:/app/static
    environment:
      - DLC_3D_PORT=5050
    networks:
      - default
    restart: unless-stopped
```

- [ ] **Step 2: Add nav button to `base.html`**

In `/home/sam/docker-images/deeplabcut-webapp-docker/src/templates/base.html`, find the `<nav>` block and add a link after the existing `VLM Refiner` link:

```html
      <a href="/dlc-3d/" style="font-size:.78rem;color:var(--text-dim);text-decoration:none;padding:.2rem .55rem;border-radius:5px;border:1px solid transparent;transition:all .15s" onmouseover="this.style.borderColor='var(--border)';this.style.color='var(--text)'" onmouseout="this.style.borderColor='transparent';this.style.color='var(--text-dim)'">3D Extractor</a>
```

- [ ] **Step 3: Add proxy route to `app.py`**

In `/home/sam/docker-images/deeplabcut-webapp-docker/src/app.py`, add these two routes after the `static_files` route (before the `if __name__ == "__main__":` line):

```python
@app.route("/dlc-3d/", defaults={"path": ""})
@app.route("/dlc-3d/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def proxy_dlc_3d(path):
    import requests as _req
    url = f"http://dlc-3d:5050/dlc-3d/{path}"
    try:
        resp = _req.request(
            method=request.method,
            url=url,
            headers={k: v for k, v in request.headers if k.lower() not in ("host", "content-length", "transfer-encoding")},
            data=request.get_data(),
            params=request.args,
            stream=True,
            timeout=60,
        )
    except _req.exceptions.ConnectionError:
        return jsonify({"error": "dlc-3d module is not running"}), 502
    excluded = {"content-encoding", "transfer-encoding", "connection"}
    headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded}
    return Response(resp.iter_content(chunk_size=8192), status=resp.status_code, headers=headers)
```

- [ ] **Step 4: Commit both repos**

```bash
# Main webapp
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add docker-compose.yml src/templates/base.html src/app.py
git commit -m "feat: integrate dlc-3d support module — docker service, nav link, proxy route"

# Support modules
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/
git commit -m "feat(dlc-3d): complete Python backend (scaffold, helpers, routes)"
```

---

## Task 5: HTML template

**Files:**
- Create: `dlc-3D/templates/dlc_3d.html`

- [ ] **Step 1: Write `dlc_3d.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DLC 3D Extractor</title>
  <style>
    :root {
      --bg: #0d1117; --panel: #161b22; --border: #30363d;
      --text: #e6edf3; --text-dim: #8b949e; --accent: #58a6ff;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: var(--bg); color: var(--text); font-family: system-ui, sans-serif;
           height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

    /* ── Header ── */
    header { background: var(--panel); border-bottom: 1px solid var(--border);
             padding: .45rem 1rem; display: flex; align-items: center; gap: .75rem; flex-shrink: 0; }
    header h1 { font-size: .92rem; font-weight: 600; white-space: nowrap; }
    #project-path-display { font-size: .75rem; color: var(--text-dim); flex: 1;
                             white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

    /* ── Buttons ── */
    .btn { background: var(--panel); border: 1px solid var(--border); color: var(--text);
           padding: .28rem .65rem; border-radius: 5px; cursor: pointer; font-size: .8rem;
           white-space: nowrap; }
    .btn:hover { border-color: var(--accent); }
    .btn-primary { background: var(--accent); border-color: var(--accent); color: #000; font-weight: 600; }
    .btn:disabled { opacity: .45; cursor: default; }

    /* ── Main layout ── */
    .main-layout { display: flex; flex: 1; overflow: hidden; }

    /* ── Session panel (left) ── */
    #session-panel { width: 260px; min-width: 180px; border-right: 1px solid var(--border);
                     overflow-y: auto; padding: .4rem; display: flex; flex-direction: column; gap: .25rem; }
    #session-empty { font-size: .75rem; color: var(--text-dim); padding: .5rem; }
    .session-group { border: 1px solid var(--border); border-radius: 5px; overflow: hidden; }
    .session-header { font-size: .8rem; font-weight: 600; padding: .3rem .55rem;
                      background: var(--panel); cursor: pointer; display: flex; align-items: center; gap: .35rem; }
    .session-header:hover { background: #21262d; }
    .session-body { display: none; }
    .session-body.open { display: block; }
    .cam-row { padding: .22rem .55rem .22rem 1.1rem; font-size: .78rem; color: var(--text-dim);
               cursor: pointer; display: flex; align-items: center; gap: .4rem; }
    .cam-row:hover { background: #21262d; color: var(--text); }
    .cam-row.active { background: #1f3a5c; color: var(--accent); }
    .clip-section { padding-left: 1.6rem; }
    .clip-header { font-size: .72rem; color: var(--text-dim); padding: .15rem .4rem; font-style: italic; }
    .clip-row { padding: .18rem .4rem; font-size: .75rem; color: var(--text-dim); cursor: pointer; border-radius: 3px; }
    .clip-row:hover { background: #21262d; color: var(--text); }
    .clip-row.active { background: #1f3a5c; color: var(--accent); }
    .cam-badge { font-size: .68rem; background: #21262d; border-radius: 3px;
                 padding: .05rem .3rem; color: var(--text-dim); }

    /* ── Player area (right) ── */
    #player-area { flex: 1; display: flex; flex-direction: column; overflow: hidden;
                   padding: .6rem; gap: .45rem; min-width: 0; }
    #cam-displays { display: flex; gap: .6rem; flex: 1; min-height: 0; }
    .cam-wrap { flex: 1; display: flex; flex-direction: column; gap: .2rem; min-width: 0; min-height: 0; }
    .cam-label { font-size: .72rem; color: var(--text-dim); }
    .cam-frame-wrap { flex: 1; background: #000; border-radius: 4px; overflow: hidden;
                      display: flex; align-items: center; justify-content: center; min-height: 0; }
    .cam-frame-wrap img { max-width: 100%; max-height: 100%; object-fit: contain; display: block; }
    #no-video-msg { font-size: .8rem; color: var(--text-dim); text-align: center; width: 100%; }

    /* ── Controls ── */
    #controls { display: flex; flex-direction: column; gap: .3rem; flex-shrink: 0; }
    .ctrl-row { display: flex; align-items: center; gap: .35rem; flex-wrap: wrap; }
    #ep-seek { flex: 1; min-width: 100px; accent-color: var(--accent); }
    .frame-info { font-size: .75rem; color: var(--text-dim); white-space: nowrap; }

    /* ── Sync cam row ── */
    #sync-cam-row { display: none; align-items: center; gap: .75rem; }
    label.toggle { display: flex; align-items: center; gap: .3rem; font-size: .78rem;
                   cursor: pointer; color: var(--text-dim); }
    label.toggle input { accent-color: var(--accent); cursor: pointer; }

    /* ── Extract status ── */
    #extract-status { font-size: .75rem; color: var(--text-dim); min-height: 1.1em; flex-shrink: 0; }

    /* ── Labeled frames ── */
    #labeled-wrap { border-top: 1px solid var(--border); padding-top: .4rem; flex-shrink: 0; display: none; }
    #labeled-header { font-size: .75rem; font-weight: 600; margin-bottom: .25rem; }
    #labeled-list { font-size: .72rem; color: var(--text-dim); max-height: 90px;
                    overflow-y: auto; display: flex; flex-wrap: wrap; gap: .2rem; }
    .frame-chip { background: var(--panel); border: 1px solid var(--border); border-radius: 3px;
                  padding: .08rem .3rem; font-size: .7rem; white-space: nowrap; }
    .frame-chip.cam0 { border-color: #3fb950; color: #3fb950; }
    .frame-chip.cam1 { border-color: #58a6ff; color: #58a6ff; }

    /* ── Browser modal ── */
    #browser-modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.65);
                     z-index: 200; align-items: center; justify-content: center; }
    #browser-modal.open { display: flex; }
    #browser-box { background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
                   width: 560px; max-height: 70vh; display: flex; flex-direction: column; }
    #browser-box-header { padding: .55rem 1rem; border-bottom: 1px solid var(--border);
                          display: flex; justify-content: space-between; align-items: center; }
    #browser-box-header span { font-weight: 600; font-size: .85rem; }
    #browser-path-bar { font-size: .72rem; color: var(--text-dim); padding: .25rem .75rem;
                        border-bottom: 1px solid var(--border); }
    #browser-list { flex: 1; overflow-y: auto; }
    .browser-entry { padding: .32rem .75rem; font-size: .8rem; cursor: pointer;
                     display: flex; align-items: center; gap: .4rem; }
    .browser-entry:hover { background: #21262d; }
    .browser-entry .entry-icon { font-size: .85rem; }
    .browser-entry.has-config .entry-icon { color: #3fb950; }
    .browser-entry.yaml { color: #3fb950; font-weight: 600; }
    .browser-up { color: var(--text-dim); font-style: italic; }
  </style>
</head>
<body>
  <!-- Header -->
  <header>
    <h1>DLC 3D Extractor</h1>
    <button class="btn" id="btn-open-project">Open Project</button>
    <span id="project-path-display">No project loaded</span>
    <button class="btn" id="btn-rescan" style="display:none">↺ Rescan</button>
  </header>

  <div class="main-layout">
    <!-- Left: session browser -->
    <div id="session-panel">
      <div id="session-empty">Open a DLC project to begin.</div>
    </div>

    <!-- Right: player area -->
    <div id="player-area">
      <div id="cam-displays">
        <div class="cam-wrap" id="cam1-wrap">
          <div class="cam-label" id="cam1-label">Primary camera</div>
          <div class="cam-frame-wrap" id="cam1-frame-wrap">
            <img id="ep-frame" src="" alt="" style="display:none">
            <span id="no-video-msg">Select a video or clip from the left panel.</span>
          </div>
        </div>
        <div class="cam-wrap" id="ep-cam2-wrap" style="display:none">
          <div class="cam-label" id="cam2-label">Sibling camera</div>
          <div class="cam-frame-wrap">
            <img id="ep-cam2-frame" src="" alt="">
          </div>
        </div>
      </div>

      <div id="controls">
        <!-- Seek row -->
        <div class="ctrl-row">
          <input type="range" id="ep-seek" value="0" min="0" max="0">
          <span class="frame-info">
            Frame <span id="ep-frame-num">—</span> / <span id="ep-frame-total">—</span>
          </span>
        </div>
        <!-- Playback row -->
        <div class="ctrl-row">
          <button class="btn" id="ep-skip-start" title="Jump to start">⏮</button>
          <button class="btn" id="ep-step-back" title="Step back">◀</button>
          <button class="btn" id="ep-play" title="Play / pause">▶</button>
          <button class="btn" id="ep-step-fwd" title="Step forward">▶</button>
          <button class="btn" id="ep-skip-end" title="Jump to end">⏭</button>
          <label style="font-size:.75rem;color:var(--text-dim)">
            Skip <input type="number" id="ep-step" value="10" min="1" max="9999"
              style="width:3.2rem;background:var(--bg);border:1px solid var(--border);
                     color:var(--text);padding:.18rem .28rem;border-radius:3px;font-size:.78rem">
          </label>
          <button class="btn btn-primary" id="ep-extract-btn" disabled>Extract Frame</button>
        </div>
        <!-- Sync cam row -->
        <div class="ctrl-row" id="sync-cam-row">
          <label class="toggle">
            <input type="checkbox" id="ep-sync-cam"> Sync Cam
          </label>
          <label class="toggle" id="ep-extract-sibling-label" style="display:none">
            <input type="checkbox" id="ep-extract-sibling" checked> Extract Sibling
          </label>
        </div>
      </div>

      <div id="extract-status"></div>

      <!-- Labeled frames for current session -->
      <div id="labeled-wrap">
        <div id="labeled-header">Extracted frames: <span id="labeled-count">0</span></div>
        <div id="labeled-list"></div>
      </div>
    </div>
  </div>

  <!-- Filesystem browser modal -->
  <div id="browser-modal">
    <div id="browser-box">
      <div id="browser-box-header">
        <span>Open DLC Project</span>
        <button class="btn" id="browser-close">✕</button>
      </div>
      <div id="browser-path-bar" id="browser-path-display">/</div>
      <div id="browser-list"></div>
    </div>
  </div>

  <script type="module" src="/dlc-3d/static/enhanced_player.js"></script>
  <script type="module" src="/dlc-3d/static/dlc_3d.js"></script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add dlc-3D/templates/dlc_3d.html
git commit -m "feat(dlc-3d): add HTML template shell"
```

---

## Task 6: enhanced_player.js

**Files:**
- Create: `dlc-3D/static/enhanced_player.js`

This is a stripped-down port of clip-cutter's `enhanced_player.js`. Removed: template/scan/detection/postfix/note/CSV/KF-canvas logic. Kept: playback, seek, sync-cam, cam2 loading. Changed: all `/clip-cutter/` URLs → `/dlc-3d/`.

- [ ] **Step 1: Write `dlc-3D/static/enhanced_player.js`**

```javascript
// enhanced_player.js — simplified video player for dlc-3D module.
// Public API: openPlayer(videoPath, siblingPath), getCurrentFrame(), getVideoPath(), getSiblingPath(), isSyncCamEnabled()

"use strict";

const _EP_FPS = 15;

let _videoPath     = null;
let _frameCount    = 0;
let _currentFrame  = 0;
let _stepSize      = 10;
let _playing       = false;
let _playDir       = 1;
let _busy          = false;
let _timerId       = null;
let _syncCamEnabled   = false;
let _siblingVideoPath = null;

// ── Public API ────────────────────────────────────────────────────────────────

export function getVideoPath()     { return _videoPath; }
export function getCurrentFrame()  { return _currentFrame; }
export function getSiblingPath()   { return _siblingVideoPath; }
export function isSyncCamEnabled() { return _syncCamEnabled; }

export async function openPlayer(videoPath, siblingPath) {
  _stop();
  _videoPath        = videoPath;
  _siblingVideoPath = siblingPath || null;
  _syncCamEnabled   = false;
  _currentFrame     = 0;
  _stepSize         = 10;

  const stepEl = document.getElementById("ep-step");
  if (stepEl) stepEl.value = 10;

  // Show primary frame area
  const noMsg = document.getElementById("no-video-msg");
  const epFrame = document.getElementById("ep-frame");
  if (noMsg)    noMsg.style.display = "none";
  if (epFrame)  epFrame.style.display = "";

  // Fetch frame count
  let frameCount = 0;
  try {
    const resp = await fetch(`/dlc-3d/video-info?video=${encodeURIComponent(videoPath)}`);
    if (!resp.ok) { _setStatus("Cannot load video info"); return; }
    const info = await resp.json();
    frameCount = info.frame_count;
  } catch (e) { _setStatus("Network error: " + e.message); return; }

  _frameCount = frameCount;

  const seekEl = document.getElementById("ep-seek");
  if (seekEl) { seekEl.min = 0; seekEl.max = frameCount - 1; seekEl.value = 0; }

  _epUpdateSyncCamUI();

  const extractBtn = document.getElementById("ep-extract-btn");
  if (extractBtn) extractBtn.disabled = false;

  await _epLoadFrame(0);
}

// ── Frame loading ─────────────────────────────────────────────────────────────

async function _epLoadFrame(n) {
  if (_busy || !_videoPath) return;
  _busy = true;
  n = Math.max(0, Math.min(n, _frameCount - 1));
  const prev = _currentFrame;
  _currentFrame = n;
  try {
    const resp = await fetch(`/dlc-3d/frame?video=${encodeURIComponent(_videoPath)}&n=${n}`);
    if (!resp.ok) { _currentFrame = prev; return; }
    const blob   = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const img    = document.getElementById("ep-frame");
    const prevSrc = img.src;
    await new Promise((resolve, reject) => {
      img.onload  = () => { if (prevSrc.startsWith("blob:")) URL.revokeObjectURL(prevSrc); resolve(); };
      img.onerror = () => reject(new Error("frame load failed"));
      img.src = blobUrl;
    });
    _epUpdateDisplay();
    _epLoadCam2Frame(n);
    // Prefetch next frame
    if (n < _frameCount - 1) {
      new Image().src = `/dlc-3d/frame?video=${encodeURIComponent(_videoPath)}&n=${n + 1}`;
    }
  } catch (e) {
    console.warn("[enhanced_player] frame load error:", e.message);
  } finally {
    _busy = false;
  }
}

// ── Cam2 (sibling) ────────────────────────────────────────────────────────────

async function _epLoadCam2Frame(n) {
  if (!_syncCamEnabled || !_siblingVideoPath) return;
  try {
    const resp = await fetch(`/dlc-3d/frame?video=${encodeURIComponent(_siblingVideoPath)}&n=${n}`);
    if (!resp.ok) return;
    const blob    = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const img     = document.getElementById("ep-cam2-frame");
    const prevSrc = img.src;
    img.onload  = () => { if (prevSrc && prevSrc.startsWith("blob:")) URL.revokeObjectURL(prevSrc); };
    img.onerror = () => URL.revokeObjectURL(blobUrl);
    img.src = blobUrl;
  } catch (e) {
    console.warn("[enhanced_player] cam2 load error:", e.message);
  }
}

// ── Sync cam UI ───────────────────────────────────────────────────────────────

function _epUpdateSyncCamUI() {
  const syncRow    = document.getElementById("sync-cam-row");
  const syncCb     = document.getElementById("ep-sync-cam");
  const cam2Wrap   = document.getElementById("ep-cam2-wrap");
  const siblingLbl = document.getElementById("ep-extract-sibling-label");

  if (!_siblingVideoPath) {
    if (syncRow)  syncRow.style.display = "none";
    if (syncCb)   syncCb.checked = false;
    if (cam2Wrap) cam2Wrap.style.display = "none";
    if (siblingLbl) siblingLbl.style.display = "none";
    _syncCamEnabled = false;
    return;
  }

  if (syncRow) syncRow.style.display = "flex";
  if (syncCb)  syncCb.checked = _syncCamEnabled;
  if (cam2Wrap) cam2Wrap.style.display = _syncCamEnabled ? "flex" : "none";
  if (siblingLbl) {
    siblingLbl.style.display = _syncCamEnabled ? "flex" : "none";
    if (_syncCamEnabled) {
      const cb = document.getElementById("ep-extract-sibling");
      if (cb) cb.checked = true;
    }
  }
}

// ── Display ───────────────────────────────────────────────────────────────────

function _epUpdateDisplay() {
  const numEl   = document.getElementById("ep-frame-num");
  const totalEl = document.getElementById("ep-frame-total");
  const seekEl  = document.getElementById("ep-seek");
  if (numEl)   numEl.textContent   = _currentFrame + 1;
  if (totalEl) totalEl.textContent = _frameCount;
  if (seekEl)  seekEl.value        = _currentFrame;
}

// ── Playback ──────────────────────────────────────────────────────────────────

async function _epLoop() {
  if (!_playing) return;
  if (_busy) { _timerId = setTimeout(_epLoop, Math.round(1000 / _EP_FPS)); return; }
  let next = _currentFrame + _playDir;
  if (next >= _frameCount) next = 0;
  if (next < 0) next = _frameCount - 1;
  const t0 = performance.now();
  await _epLoadFrame(next);
  if (!_playing) return;
  const delay = Math.max(0, Math.round(1000 / _EP_FPS) - (performance.now() - t0));
  _timerId = setTimeout(_epLoop, delay);
}

function _stop() {
  if (_timerId !== null) { clearTimeout(_timerId); _timerId = null; }
  _playing = false;
  _busy    = false;
  const playBtn = document.getElementById("ep-play");
  if (playBtn) playBtn.textContent = "▶";
}

function _setStatus(msg) {
  const el = document.getElementById("extract-status");
  if (el) el.textContent = msg;
}

// ── Event wiring (runs once DOM is ready) ─────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  // Seek bar
  document.getElementById("ep-seek")?.addEventListener("input", (e) => {
    _stop();
    _epLoadFrame(parseInt(e.target.value, 10));
  });

  // Play
  document.getElementById("ep-play")?.addEventListener("click", () => {
    if (!_videoPath) return;
    if (_playing) {
      _stop();
    } else {
      _playing = true;
      document.getElementById("ep-play").textContent = "⏸";
      _epLoop();
    }
  });

  // Step back / forward
  document.getElementById("ep-step-back")?.addEventListener("click", () => {
    if (!_videoPath) return;
    _stop();
    const s = parseInt(document.getElementById("ep-step")?.value || "10", 10);
    _epLoadFrame(_currentFrame - s);
  });
  document.getElementById("ep-step-fwd")?.addEventListener("click", () => {
    if (!_videoPath) return;
    _stop();
    const s = parseInt(document.getElementById("ep-step")?.value || "10", 10);
    _epLoadFrame(_currentFrame + s);
  });

  // Skip to start / end
  document.getElementById("ep-skip-start")?.addEventListener("click", () => {
    if (!_videoPath) return;
    _stop(); _epLoadFrame(0);
  });
  document.getElementById("ep-skip-end")?.addEventListener("click", () => {
    if (!_videoPath) return;
    _stop(); _epLoadFrame(_frameCount - 1);
  });

  // Sync cam checkbox
  document.getElementById("ep-sync-cam")?.addEventListener("change", (e) => {
    _syncCamEnabled = e.target.checked;
    _epUpdateSyncCamUI();
    if (_syncCamEnabled) _epLoadCam2Frame(_currentFrame);
  });

  // Step size input — sync to module var
  document.getElementById("ep-step")?.addEventListener("change", (e) => {
    _stepSize = Math.max(1, parseInt(e.target.value, 10) || 10);
  });

  // Keyboard shortcuts (hover-free — active whenever no text input focused)
  document.addEventListener("keydown", (e) => {
    if (!_videoPath) return;
    const tag = (e.target || {}).tagName || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

    if (e.key === " " && !e.shiftKey) {
      e.preventDefault();
      if (_playing) { _stop(); }
      else { _playing = true; document.getElementById("ep-play").textContent = "⏸"; _epLoop(); }
    } else if (e.key === "ArrowRight") {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame + _stepSize);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame - _stepSize);
    } else if (e.key === "ArrowRight" && e.shiftKey) {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame + 1);
    } else if (e.key === "ArrowLeft" && e.shiftKey) {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame - 1);
    }
  });
});
```

- [ ] **Step 2: Commit**

```bash
git add dlc-3D/static/enhanced_player.js
git commit -m "feat(dlc-3d): add simplified sync-cam video player (ported from clip-cutter)"
```

---

## Task 7: dlc_3d.js

**Files:**
- Create: `dlc-3D/static/dlc_3d.js`

- [ ] **Step 1: Write `dlc-3D/static/dlc_3d.js`**

```javascript
// dlc_3d.js — session browser, project loader, extract button handler.
"use strict";

import { openPlayer, getCurrentFrame, getVideoPath, getSiblingPath, isSyncCamEnabled } from "./enhanced_player.js";

// ── State ─────────────────────────────────────────────────────────────────────

let _projectPath   = null;
let _sessions      = {};
let _activeSession = null;  // session key e.g. "surv1_20260123"
let _activeVideo   = null;  // relative path of currently loaded video

// ── Helpers ───────────────────────────────────────────────────────────────────

function _setStatus(msg) {
  document.getElementById("extract-status").textContent = msg;
}

function _camColorClass(filename) {
  const m = filename.match(/img_cam(\d)_/);
  return m ? `cam${m[1]}` : "";
}

// ── Project loading ───────────────────────────────────────────────────────────

async function _loadProject(path) {
  _setStatus("Loading project…");
  let data;
  try {
    const resp = await fetch("/dlc-3d/project", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    data = await resp.json();
    if (!resp.ok) { _setStatus(data.error || "Failed to load project"); return; }
  } catch (e) { _setStatus("Network error: " + e.message); return; }

  _projectPath = data.project_path;
  _sessions    = data.sessions || {};

  document.getElementById("project-path-display").textContent = _projectPath;
  document.getElementById("btn-rescan").style.display = "";
  _setStatus("");
  _renderSessions();
}

// ── Session browser rendering ─────────────────────────────────────────────────

function _renderSessions() {
  const panel = document.getElementById("session-panel");
  const empty = document.getElementById("session-empty");

  if (!_sessions || Object.keys(_sessions).length === 0) {
    panel.innerHTML = "";
    if (empty) { empty.textContent = "No multi-camera videos found."; panel.appendChild(empty); }
    return;
  }
  if (empty) empty.remove();

  panel.innerHTML = "";
  for (const [sessionKey, cams] of Object.entries(_sessions).sort()) {
    const group  = document.createElement("div");
    group.className = "session-group";

    const header = document.createElement("div");
    header.className = "session-header";
    header.textContent = "▶ " + sessionKey;
    group.appendChild(header);

    const body = document.createElement("div");
    body.className = "session-body";

    for (const [camKey, camData] of Object.entries(cams).sort()) {
      // Raw video row
      const camRow = document.createElement("div");
      camRow.className = "cam-row";
      camRow.innerHTML = `<span class="cam-badge">${camKey}</span><span>${camData.avi.split("/").pop()}</span>`;
      camRow.addEventListener("click", () => _selectVideo(camData.avi, sessionKey));
      body.appendChild(camRow);

      // Clips section
      if (camData.clips && camData.clips.length > 0) {
        const clipSection = document.createElement("div");
        clipSection.className = "clip-section";
        const clipHeader = document.createElement("div");
        clipHeader.className = "clip-header";
        clipHeader.textContent = `${camData.clips.length} clip(s)`;
        clipSection.appendChild(clipHeader);
        for (const clipPath of camData.clips) {
          const clipRow = document.createElement("div");
          clipRow.className = "clip-row";
          clipRow.textContent = clipPath.split("/").pop();
          clipRow.addEventListener("click", () => _selectVideo(clipPath, sessionKey));
          clipSection.appendChild(clipRow);
        }
        body.appendChild(clipSection);
      }
    }

    header.addEventListener("click", () => {
      body.classList.toggle("open");
      header.textContent = (body.classList.contains("open") ? "▼ " : "▶ ") + sessionKey;
    });

    group.appendChild(body);
    panel.appendChild(group);
  }
}

// ── Video selection ───────────────────────────────────────────────────────────

async function _selectVideo(videoRel, sessionKey) {
  _activeVideo   = videoRel;
  _activeSession = sessionKey;

  // Highlight active row
  document.querySelectorAll(".cam-row, .clip-row").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".cam-row, .clip-row").forEach(el => {
    if (el.textContent.trim().includes(videoRel.split("/").pop())) el.classList.add("active");
  });

  // Update cam label
  const camIdx = videoRel.match(/_cam(\d+)_/)?.[1] ?? "?";
  document.getElementById("cam1-label").textContent = `Camera ${camIdx} (primary)`;

  // Fetch sibling path
  let siblingPath = null;
  try {
    const sr = await fetch(`/dlc-3d/sibling-camera?video=${encodeURIComponent(videoRel)}`);
    if (sr.ok) {
      const sd = await sr.json();
      siblingPath = sd.sibling_video_path || null;
    }
  } catch (e) { console.warn("[dlc_3d] sibling-camera fetch failed:", e); }

  // Update sibling cam label
  if (siblingPath) {
    const sibCamIdx = siblingPath.match(/_cam(\d+)_/)?.[1] ?? "?";
    document.getElementById("cam2-label").textContent = `Camera ${sibCamIdx} (sibling)`;
  }

  _setStatus("");
  await openPlayer(videoRel, siblingPath);
  _refreshLabeledFrames();
}

// ── Extract ───────────────────────────────────────────────────────────────────

async function _extractFrame() {
  const primaryVideo  = getVideoPath();
  const primaryFrame  = getCurrentFrame();
  const siblingPath   = getSiblingPath();
  const extractSibling = isSyncCamEnabled()
    ? (document.getElementById("ep-extract-sibling")?.checked ?? true)
    : false;

  if (!primaryVideo || primaryFrame === null || !_projectPath) return;

  const extractBtn = document.getElementById("ep-extract-btn");
  if (extractBtn) extractBtn.disabled = true;
  _setStatus("Saving…");

  const body = {
    primary_video:        primaryVideo,
    primary_frame_number: primaryFrame,
    extract_sibling:      extractSibling,
  };
  if (extractSibling && siblingPath) {
    body.sibling_video        = siblingPath;
    body.sibling_frame_number = primaryFrame;  // same frame number
  }

  let data;
  try {
    const resp = await fetch("/dlc-3d/save-frame", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    data = await resp.json();
    if (!resp.ok) { _setStatus(data.error || "Save failed"); return; }
  } catch (e) { _setStatus("Network error: " + e.message); return; }
  finally { if (extractBtn) extractBtn.disabled = false; }

  if (data.saved && data.saved.length > 0) {
    _setStatus(`Saved: ${data.saved.join(", ")}`);
  } else if (data.skipped && data.skipped.length > 0) {
    _setStatus(`Frame ${primaryFrame} already extracted — skipped.`);
  }
  _refreshLabeledFrames();
}

// ── Labeled frames display ────────────────────────────────────────────────────

async function _refreshLabeledFrames() {
  if (!_activeSession || !_projectPath) return;
  let data;
  try {
    const resp = await fetch(`/dlc-3d/labeled-frames?session=${encodeURIComponent(_activeSession)}`);
    if (!resp.ok) return;
    data = await resp.json();
  } catch (e) { return; }

  const wrap    = document.getElementById("labeled-wrap");
  const countEl = document.getElementById("labeled-count");
  const list    = document.getElementById("labeled-list");

  countEl.textContent = data.count || 0;
  list.innerHTML = "";

  for (const fname of data.frames || []) {
    const chip = document.createElement("span");
    chip.className = "frame-chip " + _camColorClass(fname);
    chip.textContent = fname;
    list.appendChild(chip);
  }

  wrap.style.display = data.count > 0 ? "" : "none";
}

// ── Filesystem browser ────────────────────────────────────────────────────────

let _browserCurrentPath = null;

async function _browserNavigate(path) {
  let data;
  try {
    const url = path ? `/dlc-3d/browse?path=${encodeURIComponent(path)}` : "/dlc-3d/browse";
    const resp = await fetch(url);
    data = await resp.json();
    if (!resp.ok) { alert(data.error || "Browse error"); return; }
  } catch (e) { alert("Network error: " + e.message); return; }

  _browserCurrentPath = data.path;
  document.getElementById("browser-path-bar").textContent = data.path;

  const list = document.getElementById("browser-list");
  list.innerHTML = "";

  if (data.parent) {
    const upRow = document.createElement("div");
    upRow.className = "browser-entry browser-up";
    upRow.innerHTML = '<span class="entry-icon">↑</span> ..';
    upRow.addEventListener("click", () => _browserNavigate(data.parent));
    list.appendChild(upRow);
  }

  for (const entry of data.entries || []) {
    const row = document.createElement("div");
    if (entry.type === "dir") {
      row.className = "browser-entry" + (entry.has_config ? " has-config" : "");
      row.innerHTML = `<span class="entry-icon">${entry.has_config ? "📂" : "📁"}</span>${entry.name}`;
      row.addEventListener("click", () => _browserNavigate(_browserCurrentPath + "/" + entry.name));
      if (entry.has_config) {
        const selectBtn = document.createElement("button");
        selectBtn.className = "btn";
        selectBtn.style.cssText = "margin-left:auto;font-size:.7rem;padding:.15rem .4rem";
        selectBtn.textContent = "Select";
        selectBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          _closeBrowser();
          _loadProject(_browserCurrentPath + "/" + entry.name);
        });
        row.appendChild(selectBtn);
      }
    } else if (entry.type === "yaml") {
      row.className = "browser-entry yaml";
      row.innerHTML = `<span class="entry-icon">✓</span>${entry.name}`;
      row.addEventListener("click", () => {
        _closeBrowser();
        _loadProject(_browserCurrentPath);
      });
    }
    list.appendChild(row);
  }
}

function _openBrowser() {
  document.getElementById("browser-modal").classList.add("open");
  _browserNavigate(null);
}

function _closeBrowser() {
  document.getElementById("browser-modal").classList.remove("open");
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btn-open-project").addEventListener("click", _openBrowser);
  document.getElementById("browser-close").addEventListener("click", _closeBrowser);
  document.getElementById("browser-modal").addEventListener("click", (e) => {
    if (e.target === document.getElementById("browser-modal")) _closeBrowser();
  });

  document.getElementById("btn-rescan")?.addEventListener("click", async () => {
    _setStatus("Rescanning…");
    try {
      const resp = await fetch("/dlc-3d/project/rescan", { method: "POST" });
      const data = await resp.json();
      _sessions = data.sessions || {};
      _renderSessions();
      _setStatus("Rescan complete.");
    } catch (e) { _setStatus("Rescan failed: " + e.message); }
  });

  document.getElementById("ep-extract-btn").addEventListener("click", _extractFrame);
});
```

- [ ] **Step 2: Commit**

```bash
git add dlc-3D/static/dlc_3d.js
git commit -m "feat(dlc-3d): add session browser and extract UI (dlc_3d.js)"
```

---

## Task 8: Smoke test

- [ ] **Step 1: Build the module image**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
docker build -t dlc-3d:latest .
```

Expected: build completes without error.

- [ ] **Step 2: Run all Python tests inside the image**

```bash
docker run --rm dlc-3d:latest python -m pytest tests/test_core.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Start the module standalone and open the UI**

```bash
docker compose up
```

Open `http://localhost:5050/dlc-3d/` — verify the page loads, the browser modal opens, and you can navigate to a DLC project.

- [ ] **Step 4: End-to-end extract test**

1. Open the project at `/user-data/Parra-Data/Disk/Motion-Tracking/MAPS-Inhibitory-DREADSS-Clipped-Sam-2025-10-20` (has `surv1_cam0_20260123_121732_0_trig1_fps200_exposure1500_gain10.avi`)
2. Session `surv1_20260123` should appear in the left panel
3. Click the cam0 raw video — player opens. Sibling (cam1) should be detected if a cam1 AVI exists in the same folder.
4. Enable Sync Cam — cam2 panel appears with same frame
5. Scrub to any frame, click Extract Frame
6. Verify in terminal:
   ```bash
   ls /home/sam/data-disk/Parra-Data/Motion-Tracking/MAPS-Inhibitory-DREADSS-Clipped-Sam-2025-10-20/labeled-data/surv1_20260123/
   ```
   Expected: `img_cam0_0000_NNNNN.png` (and `img_cam1_0000_NNNNN.png` if sibling extracted), `calibration.toml`

- [ ] **Step 5: Final commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/
git commit -m "feat(dlc-3d): smoke test pass — module complete for extract-frames"
```

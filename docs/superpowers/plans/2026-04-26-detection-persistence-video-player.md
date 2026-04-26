# Detection Persistence & Video Player — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save scan results per video to JSON so they survive restarts, and add a side-by-side frame-by-frame video player so detections can be visually reviewed before Keep/Reject.

**Architecture:** Persistence uses two new `processor.py` functions (`save_detections` / `load_detections`) and two routes (`GET/PUT /clip-cutter/detections`). The player lives in a new `static/player.js` module with a VideoCapture LRU cache in `viewer.py` serving JPEG frames via `GET /clip-cutter/frame`. The main panel splits into a 40/60 results-list / player column layout.

**Tech Stack:** OpenCV VideoCapture LRU cache, ETag JPEG caching, setTimeout-based playback loop (same pattern as `/home/sam/docker-images/deeplabcut-webapp-docker/src/routes/annotate.py` and `viewer.js`), Flask test client for backend tests, Playwright for frontend tests.

---

## Codebase context

Working directory for all paths: `clip-cutter/` inside `/home/sam/docker-images/deeplabcut-webapp-docker-supports/`.

Key facts:
- `frame_number` in detection dicts is **1-based** (human-readable). OpenCV `CAP_PROP_POS_FRAMES` is **0-based**. Convert with `cv2_frame = frame_number - 1`.
- `CLIP_PRE_FRAMES = 200`, `CLIP_POST_FRAMES = 600` in `config.py` — a clip window spans `[frame_number - 200, frame_number + 599]` (1-based), i.e., `[frame_number - 201, frame_number + 598]` in 0-based.
- The `/extract` route already calls `processor.extract_clip` and `processor.update_parent_csv_note`. Do not change that flow.
- `rejectDetection` in `clip_cutter.js` is currently client-only (no server call). This plan adds persistence to it.
- Run all tests from inside `clip-cutter/`: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter && pytest tests/ -v`

---

## File map

| File | Action | Responsibility |
|------|--------|----------------|
| `config.py` | Modify | Add `DETECTIONS_DIR` |
| `processor.py` | Modify | Add `save_detections`, `load_detections` |
| `viewer.py` | **Create** | VideoCapture LRU cache; `get_frame_jpeg`, `get_video_info` |
| `routes.py` | Modify | Add `/frame`, `/video-info`, `/detections` (GET+PUT); auto-save in `_run_scan` |
| `templates/clip_cutter.html` | Modify | Split layout CSS + player panel HTML |
| `static/clip_cutter.js` | Modify | Persistence calls; card click → `loadClip`; restore statuses |
| `static/player.js` | **Create** | All player state and playback logic |
| `tests/test_frame_routes.py` | **Create** | Backend pytest: persistence, frame serving |
| `tests/test_ui.py` | Modify | Extend mock routes; add persistence + player Playwright tests |

---

## Task 1: Persistence data layer

**Files:**
- Modify: `config.py`
- Modify: `processor.py`
- Create: `tests/test_frame_routes.py`

- [ ] **Step 1: Write failing persistence tests**

Create `tests/test_frame_routes.py`:

```python
import json
import pytest
from pathlib import Path
from app import create_app
import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DETECTIONS_DIR", tmp_path / "detections")
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_get_detections_404_when_missing(client):
    resp = client.get("/clip-cutter/detections?video=/some/video.avi")
    assert resp.status_code == 404


def test_put_detections_saves_and_get_returns_it(client):
    dets = [{"cv2_pos": 100, "frame_number": 101, "similarity": 0.85,
              "known_match": None, "status": "pending"}]
    resp = client.put(
        "/clip-cutter/detections",
        json={"video_path": "/some/video.avi", "detections": dets},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    resp2 = client.get("/clip-cutter/detections?video=/some/video.avi")
    assert resp2.status_code == 200
    data = resp2.get_json()
    assert data["video_path"] == "/some/video.avi"
    assert len(data["detections"]) == 1
    assert data["detections"][0]["status"] == "pending"


def test_put_detections_overwrites_previous(client):
    dets1 = [{"cv2_pos": 100, "frame_number": 101, "similarity": 0.85,
               "known_match": None, "status": "pending"}]
    dets2 = [{"cv2_pos": 200, "frame_number": 201, "similarity": 0.90,
               "known_match": "clip_name", "status": "kept"}]
    client.put("/clip-cutter/detections",
               json={"video_path": "/v.avi", "detections": dets1})
    client.put("/clip-cutter/detections",
               json={"video_path": "/v.avi", "detections": dets2})
    resp = client.get("/clip-cutter/detections?video=/v.avi")
    data = resp.get_json()
    assert len(data["detections"]) == 1
    assert data["detections"][0]["status"] == "kept"


def test_get_detections_missing_video_param(client):
    resp = client.get("/clip-cutter/detections")
    assert resp.status_code == 400


def test_put_detections_missing_body_fields(client):
    resp = client.put("/clip-cutter/detections", json={"video_path": "/v.avi"})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
pytest tests/test_frame_routes.py -v
```

Expected: all 5 tests FAIL (ImportError or 404 from missing route).

- [ ] **Step 3: Add `DETECTIONS_DIR` to `config.py`**

Add after `TEMPLATE_STATE_PATH` block:

```python
DETECTIONS_DIR = Path(
    os.environ.get(
        "CLIP_CUTTER_DETECTIONS_DIR",
        str(_DATA_ROOT / "Reaching-Task-Data/clip-cutter/detections"),
    )
)
```

- [ ] **Step 4: Add `save_detections` and `load_detections` to `processor.py`**

Add at the top with existing imports:
```python
import datetime
import os
```

Add at the bottom of `processor.py`:

```python
def save_detections(
    video_path: str,
    detections: list[dict],
    template_frame_count: int,
    detections_dir: Path,
) -> None:
    """Save detection results atomically. Write to .tmp then os.replace."""
    detections_dir = Path(detections_dir)
    detections_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video_path).stem
    out = detections_dir / f"{stem}.json"
    tmp = out.with_suffix(".json.tmp")
    payload = {
        "video_path": str(video_path),
        "scan_timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "template_frame_count": template_frame_count,
        "detections": detections,
    }
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, out)


def load_detections(video_path: str, detections_dir: Path) -> dict | None:
    """Return saved detection dict or None if no file exists."""
    stem = Path(video_path).stem
    path = Path(detections_dir) / f"{stem}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None
```

- [ ] **Step 5: Add `/detections` routes to `routes.py`**

Add after the `/extract` route at the bottom of `routes.py`:

```python
# ── Detection persistence ──────────────────────────────────────────────────────

@bp.route("/detections")
def get_detections():
    video_path = request.args.get("video", "").strip()
    if not video_path:
        return jsonify({"error": "video required"}), 400
    data = processor.load_detections(video_path, config.DETECTIONS_DIR)
    if data is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(data)


@bp.route("/detections", methods=["PUT"])
def put_detections():
    body = request.get_json(force=True)
    video_path = body.get("video_path")
    detections = body.get("detections")
    if not video_path or detections is None:
        return jsonify({"error": "video_path and detections required"}), 400
    with _state_lock:
        template_frame_count = len(_state["frames"])
    processor.save_detections(
        video_path, detections, template_frame_count, config.DETECTIONS_DIR
    )
    return jsonify({"ok": True})
```

- [ ] **Step 6: Run tests — verify they pass**

```bash
pytest tests/test_frame_routes.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add config.py processor.py routes.py tests/test_frame_routes.py
git commit -m "feat(clip-cutter): detection persistence — save/load JSON per video"
```

---

## Task 2: Frame serving backend

**Files:**
- Create: `viewer.py`
- Modify: `routes.py`
- Modify: `tests/test_frame_routes.py`

- [ ] **Step 1: Write failing frame-serving tests**

Append to `tests/test_frame_routes.py`:

```python
import cv2
import numpy as np


@pytest.fixture
def synthetic_avi(tmp_path):
    """30-frame 64×64 MJPEG AVI with varying blue channel so frames differ."""
    path = tmp_path / "test.avi"
    out = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        30.0,
        (64, 64),
    )
    for i in range(30):
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        frame[:, :, 0] = i * 8
        out.write(frame)
    out.release()
    return path


def test_frame_returns_jpeg(client, synthetic_avi):
    resp = client.get(f"/clip-cutter/frame?video={synthetic_avi}&n=0")
    assert resp.status_code == 200
    assert resp.content_type == "image/jpeg"
    assert len(resp.data) > 100


def test_frame_404_for_missing_file(client):
    resp = client.get("/clip-cutter/frame?video=/nonexistent.avi&n=0")
    assert resp.status_code == 404


def test_frame_304_on_etag_match(client, synthetic_avi):
    resp1 = client.get(f"/clip-cutter/frame?video={synthetic_avi}&n=0")
    etag = resp1.headers.get("ETag")
    assert etag is not None
    resp2 = client.get(
        f"/clip-cutter/frame?video={synthetic_avi}&n=0",
        headers={"If-None-Match": etag},
    )
    assert resp2.status_code == 304


def test_frame_missing_params(client):
    assert client.get("/clip-cutter/frame?video=/v.avi").status_code == 400
    assert client.get("/clip-cutter/frame?n=0").status_code == 400


def test_video_info_returns_frame_count_and_fps(client, synthetic_avi):
    resp = client.get(f"/clip-cutter/video-info?video={synthetic_avi}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["frame_count"] == 30
    assert abs(data["fps"] - 30.0) < 1.0


def test_video_info_404_for_missing_file(client):
    resp = client.get("/clip-cutter/video-info?video=/nonexistent.avi")
    assert resp.status_code == 404


def test_video_info_missing_param(client):
    assert client.get("/clip-cutter/video-info").status_code == 400
```

- [ ] **Step 2: Run tests — verify new ones fail**

```bash
pytest tests/test_frame_routes.py -v
```

Expected: 5 original tests PASS, 7 new tests FAIL (ImportError / 404).

- [ ] **Step 3: Create `viewer.py`**

```python
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
                evicted["vcap"].release()
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

- [ ] **Step 4: Add `/frame` and `/video-info` routes to `routes.py`**

Add `import viewer` at the top of `routes.py` with the other imports.

Add these routes after the detection persistence routes:

```python
# ── Frame serving ──────────────────────────────────────────────────────────────

@bp.route("/frame")
def get_frame():
    video_path = request.args.get("video", "").strip()
    n = request.args.get("n", "").strip()
    if not video_path or not n:
        return jsonify({"error": "video and n required"}), 400
    try:
        n = int(n)
    except ValueError:
        return jsonify({"error": "n must be an integer"}), 400

    etag = f"cc-frame-{video_path}-{n}"
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304)

    try:
        data = viewer.get_frame_jpeg(video_path, n)
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
    video_path = request.args.get("video", "").strip()
    if not video_path:
        return jsonify({"error": "video required"}), 400
    try:
        info = viewer.get_video_info(video_path)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify(info)
```

- [ ] **Step 5: Run all backend tests**

```bash
pytest tests/test_frame_routes.py -v
```

Expected: all 12 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add viewer.py routes.py tests/test_frame_routes.py
git commit -m "feat(clip-cutter): frame serving — /frame and /video-info routes with LRU cache"
```

---

## Task 3: Auto-save scan results

**Files:**
- Modify: `routes.py` (`_run_scan` function)

- [ ] **Step 1: Update `_run_scan` to auto-save after scan**

In `routes.py`, find the `_run_scan` function. After the loop that adds `known_match`, add `status` field to each detection and then save. Replace the block that sets `status = "done"`:

Current code (lines ~186–196):
```python
        for d in detections:
            kf = d["frame_number"]
            match = next(
                (name for kf_known, name in known.items() if abs(kf - kf_known) <= 5),
                None,
            )
            d["known_match"] = match

        with _jobs_lock:
            _scan_jobs[job_id]["status"] = "done"
            _scan_jobs[job_id]["detections"] = detections
```

Replace with:
```python
        for d in detections:
            kf = d["frame_number"]
            match = next(
                (name for kf_known, name in known.items() if abs(kf - kf_known) <= 5),
                None,
            )
            d["known_match"] = match
            d["status"] = "pending"

        with _state_lock:
            template_frame_count = len(_state["frames"])
        processor.save_detections(
            video_path, detections, template_frame_count, config.DETECTIONS_DIR
        )

        with _jobs_lock:
            _scan_jobs[job_id]["status"] = "done"
            _scan_jobs[job_id]["detections"] = detections
```

- [ ] **Step 2: Run all backend tests to confirm nothing broke**

```bash
pytest tests/test_frame_routes.py -v
```

Expected: all 12 tests PASS (auto-save doesn't affect these tests since they don't trigger a scan).

- [ ] **Step 3: Commit**

```bash
git add routes.py
git commit -m "feat(clip-cutter): auto-save detections JSON when scan completes"
```

---

## Task 4: HTML layout split

**Files:**
- Modify: `templates/clip_cutter.html`

- [ ] **Step 1: Replace results section with split layout**

In `clip_cutter.html`, replace the entire `/* Results */` CSS block and the `<!-- Results -->` HTML block.

**CSS — replace the `/* Results */` section** (currently lines 70–86):

```css
/* Results + Player split */
.content-split { display: flex; flex: 1; overflow: hidden; }

/* Results pane (left 40%) */
.results-pane { width: 40%; border-right: 1px solid #30363d; display: flex; flex-direction: column; overflow: hidden; }
.results-pane-header { padding: 8px 12px 4px; flex-shrink: 0; display: flex; align-items: center; justify-content: space-between; }
#results-count { font-size: 11px; color: #2ea043; }
#results-list { flex: 1; overflow-y: auto; padding: 6px 10px; display: flex; flex-direction: column; gap: 6px; }
.result-card { display: flex; align-items: center; gap: 10px; padding: 8px 10px; background: #1c2128; border-radius: 5px; border: 1px solid #30363d; cursor: pointer; }
.result-card:hover { border-color: #388bfd44; }
.result-card.active-preview { border-color: #388bfd; background: #1a2535; }
.result-card.new { border-color: #388bfd55; }
.result-card.kept { opacity: 0.4; }
.result-card.rejected { opacity: 0.4; }
.result-meta { flex: 1; min-width: 0; }
.result-name { font-family: monospace; font-size: 11px; color: #cdd9e5; margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.result-info { font-size: 10px; color: #768390; margin-bottom: 5px; }
.result-actions { display: flex; gap: 5px; flex-wrap: wrap; }
.sim-pill { font-size: 10px; padding: 2px 7px; border-radius: 10px; background: #1a3a1a; color: #2ea043; flex-shrink: 0; }
.match-pill { font-size: 9px; padding: 1px 5px; border-radius: 3px; }
.match-known { background: #1a3a1a; color: #2ea043; }
.match-new { background: #1a2535; color: #388bfd; }

/* Player pane (right 60%) */
.player-pane { flex: 1; display: flex; flex-direction: column; background: #0d1117; overflow: hidden; }
#player-placeholder { flex: 1; display: flex; align-items: center; justify-content: center; font-size: 11px; color: #768390; }
#player-container { flex: 1; display: flex; flex-direction: column; padding: 8px; gap: 6px; }
#player-frame-wrap { flex: 1; background: #1c2128; border-radius: 4px; border: 1px solid #30363d; overflow: hidden; display: flex; align-items: center; justify-content: center; min-height: 0; }
#player-frame { max-width: 100%; max-height: 100%; display: block; }
#player-controls { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
#player-seek { flex: 1; accent-color: #1f6feb; cursor: pointer; }
#player-frame-num { font-size: 10px; color: #768390; white-space: nowrap; font-family: monospace; }
#player-actions { display: flex; gap: 6px; flex-shrink: 0; }
.player-btn { font-size: 11px; padding: 3px 10px; border-radius: 4px; cursor: pointer; border: 1px solid #30363d; background: transparent; color: #cdd9e5; }
.player-btn:hover { background: #30363d; }
.player-btn.active { border-color: #388bfd; color: #388bfd; }
#player-loop.active { border-color: #388bfd; color: #388bfd; }
```

**HTML — replace the `<!-- Results -->` div** (currently the `<div class="results-section">` block):

```html
    <!-- Results + Player split -->
    <div class="content-split">
      <!-- Results list -->
      <div class="results-pane">
        <div class="results-pane-header">
          <span class="section-label">Detections</span>
          <span id="results-count"></span>
        </div>
        <div id="results-list"></div>
      </div>

      <!-- Player -->
      <div class="player-pane">
        <div id="player-placeholder">Click a detection to preview</div>
        <div id="player-container" style="display:none;">
          <div id="player-frame-wrap">
            <img id="player-frame" alt="video frame">
          </div>
          <div id="player-controls">
            <button class="player-btn" id="player-prev">&#9198;</button>
            <button class="player-btn" id="player-play">&#9654;</button>
            <button class="player-btn" id="player-next">&#9197;</button>
            <input type="range" id="player-seek" min="0" max="1000" value="0">
            <span id="player-frame-num">fr 0</span>
          </div>
          <div id="player-actions">
            <button class="player-btn" id="player-keyframe">&#8982; Key frame</button>
            <button class="player-btn active" id="player-loop">&#8617; Loop</button>
          </div>
        </div>
      </div>
    </div>
```

- [ ] **Step 2: Verify page still loads and passes existing Playwright tests**

```bash
pytest tests/test_ui.py -v
```

Expected: all 14 existing tests PASS (layout change doesn't break any existing selectors).

- [ ] **Step 3: Commit**

```bash
git add templates/clip_cutter.html
git commit -m "feat(clip-cutter): split main panel — results left 40%, player right 60%"
```

---

## Task 5: Frontend persistence

**Files:**
- Modify: `static/clip_cutter.js`
- Modify: `tests/test_ui.py`

- [ ] **Step 1: Write failing Playwright persistence tests**

Append to `tests/test_ui.py`:

```python
# ── Persistence mock data ──────────────────────────────────────────────────────

_MOCK_SAVED_DETECTIONS = {
    "video_path": "/user-data/vid1.avi",
    "scan_timestamp": "2026-04-26T12:00:00",
    "template_frame_count": 19,
    "detections": [
        {
            "cv2_pos": 20967,
            "frame_number": 20968,
            "similarity": 0.8734,
            "known_match": "MAP2_0_20768_21567_success",
            "status": "kept",
        },
        {
            "cv2_pos": 51399,
            "frame_number": 51400,
            "similarity": 0.7412,
            "known_match": None,
            "status": "rejected",
        },
    ],
}


def setup_routes_with_persistence(
    page: Page,
    *,
    template_frames=None,
    saved_detections=None,
    put_detections_calls=None,
) -> None:
    """
    Like setup_routes but also mocks /detections GET and PUT.
    saved_detections: dict to return from GET, or None to return 404.
    put_detections_calls: list to append captured PUT bodies to (for assertions).
    """
    setup_routes(page, template_frames=template_frames)

    def on_detections_get(route: Route):
        if saved_detections is None:
            _json(route, {"error": "not found"}, status=404)
        else:
            _json(route, saved_detections)

    def on_detections_put(route: Route):
        if put_detections_calls is not None:
            put_detections_calls.append(json.loads(route.request.post_data))
        _json(route, {"ok": True})

    def on_video_info(route: Route):
        _json(route, {"frame_count": 26492, "fps": 30.0})

    def on_frame(route: Route):
        route.fulfill(
            status=200,
            content_type="image/jpeg",
            body=base64.b64decode(_JPEG_B64),
        )

    page.route("**/clip-cutter/detections", on_detections_put,
               method="PUT" if hasattr(route, "method") else None)
    page.route("**/clip-cutter/video-info*", on_video_info)
    page.route("**/clip-cutter/frame*", on_frame)
    # GET detections must come after PUT route registration
    page.route("**/clip-cutter/detections*", lambda r: (
        on_detections_put(r) if r.request.method == "PUT" else on_detections_get(r)
    ))


def test_saved_detections_load_on_video_select(page: Page):
    """Selecting a video with saved results auto-populates cards without scanning."""
    setup_routes_with_persistence(
        page,
        template_frames=_MOCK_FRAMES,
        saved_detections=_MOCK_SAVED_DETECTIONS,
    )
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.locator(".video-row:not(.done)").first.click()

    cards = page.locator(".result-card")
    expect(cards).to_have_count(2, timeout=5_000)
    expect(page.locator("#results-count")).to_have_text("2 found")


def test_saved_statuses_restored_on_load(page: Page):
    """Cards restored from saved JSON show kept/rejected classes."""
    setup_routes_with_persistence(
        page,
        template_frames=_MOCK_FRAMES,
        saved_detections=_MOCK_SAVED_DETECTIONS,
    )
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".video-row:not(.done)").first.click()

    cards = page.locator(".result-card")
    expect(cards).to_have_count(2, timeout=5_000)
    expect(cards.nth(0)).to_have_class(re.compile(r"\bkept\b"))
    expect(cards.nth(1)).to_have_class(re.compile(r"\brejected\b"))


def test_scan_button_still_enabled_with_saved_results(page: Page):
    """Scan button is enabled even when saved results are loaded."""
    setup_routes_with_persistence(
        page,
        template_frames=_MOCK_FRAMES,
        saved_detections=_MOCK_SAVED_DETECTIONS,
    )
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".video-row:not(.done)").first.click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=5_000)
    expect(page.locator("#scan-btn")).to_be_enabled()


def test_reject_persists_via_put_detections(page: Page):
    """Clicking Reject calls PUT /detections with status rejected."""
    put_calls = []
    setup_routes_with_persistence(
        page,
        template_frames=_MOCK_FRAMES,
        saved_detections=None,
        put_detections_calls=put_calls,
    )
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".video-row:not(.done)").first.click()
    page.locator("#scan-btn").click()

    cards = page.locator(".result-card")
    expect(cards).to_have_count(2, timeout=8_000)
    cards.nth(1).locator("button", has_text="Reject").click()

    page.wait_for_timeout(500)
    assert any(
        any(d.get("status") == "rejected" for d in call.get("detections", []))
        for call in put_calls
    )


def test_rescan_overwrites_saved_results(page: Page):
    """Re-scanning clears previous cards and shows fresh detections."""
    setup_routes_with_persistence(
        page,
        template_frames=_MOCK_FRAMES,
        saved_detections=_MOCK_SAVED_DETECTIONS,
    )
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".video-row:not(.done)").first.click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=5_000)

    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)
    # After rescan neither card should be kept/rejected
    for i in range(2):
        expect(page.locator(".result-card").nth(i)).not_to_have_class(re.compile(r"\bkept\b"))
```

Note: the `setup_routes_with_persistence` above has a routing issue — Playwright route matching works by URL pattern, not HTTP method. Fix `setup_routes_with_persistence` to use a request handler that checks `r.request.method`:

```python
def setup_routes_with_persistence(
    page: Page,
    *,
    template_frames=None,
    saved_detections=None,
    put_detections_calls=None,
) -> None:
    setup_routes(page, template_frames=template_frames)

    def on_detections(route: Route):
        if route.request.method == "PUT":
            if put_detections_calls is not None:
                put_detections_calls.append(json.loads(route.request.post_data))
            _json(route, {"ok": True})
        else:
            if saved_detections is None:
                _json(route, {"error": "not found"}, status=404)
            else:
                _json(route, saved_detections)

    def on_video_info(route: Route):
        _json(route, {"frame_count": 26492, "fps": 30.0})

    def on_frame(route: Route):
        import base64
        route.fulfill(
            status=200,
            content_type="image/jpeg",
            body=base64.b64decode(_JPEG_B64),
        )

    page.route("**/clip-cutter/detections*", on_detections)
    page.route("**/clip-cutter/video-info*", on_video_info)
    page.route("**/clip-cutter/frame*", on_frame)
```

- [ ] **Step 2: Run new Playwright tests — verify they fail**

```bash
pytest tests/test_ui.py::test_saved_detections_load_on_video_select -v
```

Expected: FAIL (no persistence logic in JS yet).

- [ ] **Step 3: Update `static/clip_cutter.js`**

**Add `saveDetections` and `loadSavedDetections` functions** (add after the `loadVideos` / `renderVideos` section):

```javascript
// ── Persistence ───────────────────────────────────────────────────────────────

async function saveDetections() {
  if (!selectedVideoPath || detections.length === 0) return;
  await fetch("/clip-cutter/detections", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_path: selectedVideoPath, detections }),
  });
}

async function loadSavedDetections(videoPath) {
  try {
    const resp = await fetch(
      `/clip-cutter/detections?video=${encodeURIComponent(videoPath)}`
    );
    if (!resp.ok) return false;
    const data = await resp.json();
    detections.length = 0;
    renderDetections(data.detections);
    return true;
  } catch {
    return false;
  }
}
```

**Update `selectVideo`** to load saved detections after selecting:

```javascript
async function selectVideo(path, rowEl) {
  document.querySelectorAll(".video-row").forEach((r) => r.classList.remove("selected"));
  rowEl.classList.add("selected");
  selectedVideoPath = path;
  document.getElementById("scan-btn").disabled = false;
  await loadSavedDetections(path);
}
```

**Update `renderDetections`** to preserve existing status and apply CSS classes:

```javascript
function renderDetections(dets) {
  const list = document.getElementById("results-list");
  const count = document.getElementById("results-count");
  list.innerHTML = "";
  count.textContent = `${dets.length} found`;

  dets.forEach((d) => {
    if (!d.video_path) d.video_path = selectedVideoPath;
    if (!d.status) d.status = "pending";
    detections.push(d);
    const card = buildResultCard(d, detections.length - 1);
    if (d.status === "kept") {
      card.classList.add("kept");
      card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    } else if (d.status === "rejected") {
      card.classList.add("rejected");
      card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    }
    list.appendChild(card);
  });
}
```

**Update `startScan`** to clear detections array before scanning:

Find the line `detections.length = 0;` — it already exists. Confirm it's present in `startScan`.

**Update `listenToScan`** to call `saveDetections` after scan completes. In the `job.status === "done"` handler, after `renderDetections(job.detections)`, add:

```javascript
      await saveDetections();
```

**Update `keepDetection`** to call `saveDetections` after success:

```javascript
async function keepDetection(idx) {
  const d = detections[idx];
  const resp = await fetch("/clip-cutter/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_path: d.video_path, key_frame: d.frame_number }),
  });
  if (resp.ok) {
    detections[idx].status = "kept";
    const card = document.getElementById(`card-${idx}`);
    card.classList.add("kept");
    card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    setStatus(`Clip extracted for frame ${d.frame_number}`);
    await saveDetections();
  } else {
    const err = await resp.json();
    setStatus("Error: " + err.error);
  }
}
```

**Update `rejectDetection`** to async and call `saveDetections`:

```javascript
async function rejectDetection(idx) {
  detections[idx].status = "rejected";
  const card = document.getElementById(`card-${idx}`);
  card.classList.add("rejected");
  card.querySelectorAll("button").forEach((b) => (b.disabled = true));
  await saveDetections();
}
```

**Wire card click to player** (add to `buildResultCard` after existing event listeners):

```javascript
  card.addEventListener("click", (e) => {
    if (e.target.closest("button")) return; // don't trigger on button clicks
    document.querySelectorAll(".result-card").forEach((c) => c.classList.remove("active-preview"));
    card.classList.add("active-preview");
    loadClip(d.video_path, d.frame_number);
  });
```

- [ ] **Step 4: Run Playwright persistence tests**

```bash
pytest tests/test_ui.py -k "persist or saved or rescan" -v
```

Expected: all 5 new persistence tests PASS.

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
pytest tests/test_ui.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add static/clip_cutter.js tests/test_ui.py
git commit -m "feat(clip-cutter): frontend persistence — auto-load/save detections, restore card statuses"
```

---

## Task 6: Player

**Files:**
- Create: `static/player.js`
- Modify: `templates/clip_cutter.html` (add script tag)
- Modify: `tests/test_ui.py` (add player Playwright tests)

- [ ] **Step 1: Write failing Playwright player tests**

Append to `tests/test_ui.py`:

```python
def test_player_placeholder_visible_before_card_click(page: Page):
    """Player placeholder is shown before any detection card is clicked."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".video-row:not(.done)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    expect(page.locator("#player-placeholder")).to_be_visible()
    expect(page.locator("#player-container")).to_be_hidden()


def test_clicking_card_shows_player(page: Page):
    """Clicking a detection card hides the placeholder and shows the player."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".video-row:not(.done)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    page.locator(".result-card").first.click()

    expect(page.locator("#player-container")).to_be_visible(timeout=5_000)
    expect(page.locator("#player-placeholder")).to_be_hidden()


def test_player_next_frame_advances_counter(page: Page):
    """Clicking next-frame button increments the frame counter."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".video-row:not(.done)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    page.locator(".result-card").first.click()
    expect(page.locator("#player-container")).to_be_visible(timeout=5_000)

    frame_text_before = page.locator("#player-frame-num").inner_text()
    page.locator("#player-next").click()
    page.wait_for_timeout(800)
    frame_text_after = page.locator("#player-frame-num").inner_text()
    assert frame_text_before != frame_text_after


def test_player_keyframe_button_jumps_to_keyframe(page: Page):
    """Key frame button seeks to the detection's frame_number (0-based display)."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".video-row:not(.done)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    page.locator(".result-card").first.click()
    expect(page.locator("#player-container")).to_be_visible(timeout=5_000)

    page.locator("#player-prev").click()
    page.wait_for_timeout(400)
    page.locator("#player-keyframe").click()
    page.wait_for_timeout(400)

    # frame_number=20968, 0-based=20967
    expect(page.locator("#player-frame-num")).to_have_text("fr 20967")
```

- [ ] **Step 2: Run new player tests — verify they fail**

```bash
pytest tests/test_ui.py -k "player" -v
```

Expected: all 4 tests FAIL (player.js not created yet).

- [ ] **Step 3: Create `static/player.js`**

```javascript
// player.js — video frame player for clip-cutter

const PLAYER_FPS = 15;

let _playerVideoPath = null;
let _playerFrameCount = 0;
let _playerCurrentFrame = 0;
let _playerClipStart = 0;
let _playerClipEnd = 0;
let _playerKeyFrame = 0;   // 0-based
let _playerLooping = true;
let _playerPlaying = false;
let _playerBusy = false;
let _playerTimeoutId = null;

async function loadClip(videoPath, keyFrame1Based) {
  const resp = await fetch(
    `/clip-cutter/video-info?video=${encodeURIComponent(videoPath)}`
  );
  if (!resp.ok) { setStatus("Cannot load video info"); return; }
  const info = await resp.json();

  _playerVideoPath = videoPath;
  _playerFrameCount = info.frame_count;
  // Convert 1-based frame_number to 0-based for OpenCV
  const kf0 = keyFrame1Based - 1;
  _playerKeyFrame = kf0;
  _playerClipStart = Math.max(0, kf0 - 200);
  _playerClipEnd = Math.min(info.frame_count - 1, kf0 + 599);

  _playerStop();
  document.getElementById("player-placeholder").style.display = "none";
  document.getElementById("player-container").style.display = "flex";

  await _playerLoadFrame(_playerClipStart);
}

async function _playerLoadFrame(n) {
  if (_playerBusy || _playerVideoPath === null) return;
  _playerBusy = true;
  n = Math.max(0, Math.min(n, _playerFrameCount - 1));
  _playerCurrentFrame = n;

  try {
    const url = `/clip-cutter/frame?video=${encodeURIComponent(_playerVideoPath)}&n=${n}`;
    const resp = await fetch(url);
    if (!resp.ok) return;
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const img = document.getElementById("player-frame");
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = reject;
      const prev = img.src;
      img.src = blobUrl;
      if (prev && prev.startsWith("blob:")) URL.revokeObjectURL(prev);
    });
    _playerUpdateDisplay();
    // Prefetch next frame
    new Image().src = `/clip-cutter/frame?video=${encodeURIComponent(_playerVideoPath)}&n=${n + 1}`;
  } finally {
    _playerBusy = false;
  }
}

async function _playerLoop() {
  if (!_playerPlaying) return;

  let next = _playerCurrentFrame + 1;
  if (next > _playerClipEnd) {
    if (_playerLooping) {
      next = _playerClipStart;
    } else {
      _playerStop();
      return;
    }
  }

  const t0 = performance.now();
  await _playerLoadFrame(next);
  if (!_playerPlaying) return;

  const elapsed = performance.now() - t0;
  const delay = Math.max(0, Math.round(1000 / PLAYER_FPS) - elapsed);
  _playerTimeoutId = setTimeout(_playerLoop, delay);
}

function _playerStop() {
  if (_playerTimeoutId !== null) { clearTimeout(_playerTimeoutId); _playerTimeoutId = null; }
  _playerPlaying = false;
  const btn = document.getElementById("player-play");
  if (btn) btn.textContent = "▶";
}

function _playerUpdateDisplay() {
  document.getElementById("player-frame-num").textContent = `fr ${_playerCurrentFrame}`;
  const seek = document.getElementById("player-seek");
  const pct = _playerFrameCount > 1 ? _playerCurrentFrame / (_playerFrameCount - 1) : 0;
  seek.value = Math.round(pct * 1000);
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("player-play").addEventListener("click", () => {
    if (_playerVideoPath === null) return;
    if (_playerPlaying) {
      _playerStop();
    } else {
      _playerPlaying = true;
      document.getElementById("player-play").textContent = "⏸";
      _playerLoop();
    }
  });

  document.getElementById("player-prev").addEventListener("click", () => {
    _playerStop();
    _playerLoadFrame(_playerCurrentFrame - 1);
  });

  document.getElementById("player-next").addEventListener("click", () => {
    _playerStop();
    _playerLoadFrame(_playerCurrentFrame + 1);
  });

  document.getElementById("player-keyframe").addEventListener("click", () => {
    _playerStop();
    _playerLoadFrame(_playerKeyFrame);
  });

  document.getElementById("player-loop").addEventListener("click", () => {
    _playerLooping = !_playerLooping;
    document.getElementById("player-loop").classList.toggle("active", _playerLooping);
  });

  document.getElementById("player-seek").addEventListener("input", (e) => {
    if (_playerFrameCount === 0) return;
    _playerStop();
    const n = Math.round((e.target.value / 1000) * (_playerFrameCount - 1));
    _playerLoadFrame(n);
  });
});
```

- [ ] **Step 4: Add `player.js` script tag to `clip_cutter.html`**

Find the line:
```html
<script src="/clip-cutter/static/clip_cutter.js"></script>
```

Replace with:
```html
<script src="/clip-cutter/static/player.js"></script>
<script src="/clip-cutter/static/clip_cutter.js"></script>
```

(`player.js` must load first so `loadClip` is defined when `clip_cutter.js` wires the card click handler.)

- [ ] **Step 5: Run player Playwright tests**

```bash
pytest tests/test_ui.py -k "player" -v
```

Expected: all 4 player tests PASS.

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all backend and Playwright tests PASS.

- [ ] **Step 7: Commit**

```bash
git add static/player.js templates/clip_cutter.html tests/test_ui.py
git commit -m "feat(clip-cutter): video player — frame-by-frame preview with loop and key-frame jump"
```

---

## Post-implementation checklist

- [ ] Restart container to pick up `routes.py` and `viewer.py` changes: `docker compose restart clip-cutter`
- [ ] Open `http://192.168.1.13:5002/clip-cutter/` from another machine and verify:
  1. Select a video with a prior scan → cards load immediately without re-scanning
  2. Click a card → player shows, starts at clip start
  3. ⌖ Key frame jumps to correct frame
  4. Keep/Reject → status persists after page refresh
  5. Re-scan → old results replaced, new statuses all pending
- [ ] Add `CLIP_CUTTER_DETECTIONS_DIR` to `docker-compose.yml` environment section if a custom path is needed

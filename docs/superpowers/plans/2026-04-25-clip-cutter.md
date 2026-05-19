# Clip Cutter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Flask web app that uses CLIP ViT-B-32 template matching to auto-detect reaching-onset frames in long rat behavioural videos, extract 800-frame clips, and write results to CSVs.

**Architecture:** A CLIP-based similarity scan (coarse stride-10 pass → Gaussian smooth → peak detection → fine stride-1 pass) produces candidate key frames. A Flask UI lets the user review detections, confirm/reject each, and grow the template bank with frames from new videos. All heavy processing runs in a background thread streamed via SSE.

**Tech Stack:** Python 3.10+, Flask, sentence-transformers (clip-ViT-B-32), OpenCV, pandas, scipy, PIL

---

## File Map

```
clip-cutter/
  config.py                   ← all paths + tunables (single source of truth)
  processor.py                ← CLIP logic: embed, template state, scan, extract
  app.py                      ← Flask factory; registers blueprint at /clip-cutter
  routes.py                   ← all HTTP routes + SSE job management
  requirements.txt
  templates/
    clip_cutter.html          ← full UI (layout B: left sidebar + main panel)
  static/
    clip_cutter.js            ← all frontend JS
  tests/
    __init__.py
    conftest.py               ← shared fixtures: tiny_video, tiny_csv, mock_model
    test_processor.py         ← unit tests for processor functions
    test_routes.py            ← Flask test client tests
```

**Indexing contract (read this first):**
- `frame_number` in CSVs is **1-based** (first frame = 1).
- OpenCV `CAP_PROP_POS_FRAMES` is **0-based**.
- Conversion: `cv2_pos = frame_number - 1`.
- A clip named `…_{start}_{end}_…` contains `frame_number` values `start` through `end` inclusive (800 frames). Key frame `K = start + 200` (1-based frame_number in parent video).

---

## Task 1: Project scaffold

**Files:**
- Create: `clip-cutter/config.py`
- Create: `clip-cutter/requirements.txt`
- Create: `clip-cutter/tests/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter/{templates,static,tests}
touch /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter/tests/__init__.py
```

- [ ] **Step 2: Write `config.py`**

```python
from pathlib import Path

# --- Paths ---
VIDEO_DIR = Path("/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/MAP-2")
TRAINING_CLIPS_DIR = VIDEO_DIR / "MAP2_20250515_103618_0"
TEMPLATE_STATE_PATH = Path(__file__).parent / "template_state.json"

# --- Template ---
TRAINING_CROP = (401, 268, 581, 632)   # (x, y, w, h) in original 1376×900 frame

# --- Scanning ---
SCAN_STRIDE = 10           # extract every Nth frame for coarse pass
SCAN_BATCH_SIZE = 64       # CLIP batch size
SIMILARITY_THRESHOLD = 0.70
MIN_PEAK_SPACING = 900     # minimum frames between two detections (original frame units)
FINE_SCAN_WINDOW = 50      # ± frames around coarse peak for fine pass

# --- Clip extraction ---
CLIP_PRE_FRAMES = 200      # frames before key frame
CLIP_POST_FRAMES = 600     # frames after key frame (inclusive end = key + 599)

# --- "Done" detection ---
# A video is considered done if its _test_clips/ dir exists OR its CSV has any start_reaching note
TEST_CLIPS_SUFFIX = "_test_clips"
```

- [ ] **Step 3: Write `requirements.txt`**

```
flask>=3.0
sentence-transformers>=3.0
opencv-python>=4.8
pandas>=2.0
scipy>=1.12
Pillow>=10.0
pytest>=8.0
```

- [ ] **Step 4: Install dependencies**

```bash
pip install -r /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter/requirements.txt
```

Expected: packages install without error. `sentence-transformers` will download the CLIP model on first use (~350 MB, cached in `~/.cache`).

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git init  # only if not already a git repo
git add clip-cutter/config.py clip-cutter/requirements.txt clip-cutter/tests/__init__.py
git commit -m "feat(clip-cutter): project scaffold and config"
```

---

## Task 2: CLIP model + frame embedding utilities

**Files:**
- Create: `clip-cutter/processor.py`
- Create: `clip-cutter/tests/conftest.py`
- Create: `clip-cutter/tests/test_processor.py` (partial — embedding tests)

- [ ] **Step 1: Write the failing tests for embedding utilities**

`clip-cutter/tests/conftest.py`:
```python
import pytest
import numpy as np
import cv2
import pandas as pd
from pathlib import Path


@pytest.fixture
def mock_model(monkeypatch):
    """Replace the CLIP model singleton with a deterministic fake."""
    import processor
    rng = np.random.default_rng(42)

    class FakeModel:
        def encode(self, images, convert_to_numpy=True, batch_size=64, show_progress_bar=False):
            if isinstance(images, list):
                return rng.random((len(images), 512)).astype(np.float32)
            return rng.random(512).astype(np.float32)

    monkeypatch.setattr(processor, "_model", FakeModel())
    return FakeModel()


@pytest.fixture
def tiny_video(tmp_path):
    """50-frame 64×48 MJPEG AVI for I/O tests."""
    path = tmp_path / "test.avi"
    out = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 48)
    )
    for i in range(50):
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        frame[:, :] = (i * 5 % 256, 100, (200 - i * 4) % 256)
        out.write(frame)
    out.release()
    return path


@pytest.fixture
def tiny_csv(tmp_path):
    """Matching 50-row CSV for tiny_video (frame_number 1-based)."""
    path = tmp_path / "test.csv"
    df = pd.DataFrame({
        "timestamp": range(50),
        "frame_number": range(1, 51),
        "frame_line_status": [10] * 50,
        "note": [""] * 50,
    })
    df.to_csv(path, index=False)
    return path
```

`clip-cutter/tests/test_processor.py` (embedding section):
```python
import numpy as np
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import processor


def test_embed_frame_returns_unit_vector(mock_model, tiny_video):
    import cv2
    cap = cv2.VideoCapture(str(tiny_video))
    ret, frame = cap.read()
    cap.release()
    assert ret
    emb = processor.embed_frame(frame)
    assert emb.shape == (512,)
    assert abs(np.linalg.norm(emb) - 1.0) < 1e-5


def test_embed_frame_with_crop(mock_model, tiny_video):
    import cv2
    cap = cv2.VideoCapture(str(tiny_video))
    ret, frame = cap.read()
    cap.release()
    crop = (5, 5, 20, 20)
    emb = processor.embed_frame(frame, crop=crop)
    assert emb.shape == (512,)


def test_embed_frames_batch_shape(mock_model, tiny_video):
    import cv2
    cap = cv2.VideoCapture(str(tiny_video))
    frames = []
    for _ in range(5):
        ret, f = cap.read()
        if ret:
            frames.append(f)
    cap.release()
    embs = processor.embed_frames_batch(frames)
    assert embs.shape == (len(frames), 512)
    norms = np.linalg.norm(embs, axis=1)
    np.testing.assert_allclose(norms, np.ones(len(frames)), atol=1e-5)


def test_read_frame_valid_index(tiny_video):
    frame = processor.read_frame(tiny_video, 0)
    assert frame is not None
    assert frame.shape == (48, 64, 3)


def test_read_frame_out_of_range_returns_none(tiny_video):
    frame = processor.read_frame(tiny_video, 9999)
    assert frame is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_processor.py::test_embed_frame_returns_unit_vector -v
```

Expected: `ModuleNotFoundError: No module named 'processor'`

- [ ] **Step 3: Write `processor.py` — embedding section**

```python
from __future__ import annotations

import json
import base64
import io
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from PIL import Image

# Lazy-loaded CLIP model singleton
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("clip-ViT-B-32")
    return _model


def read_frame(video_path: Path | str, cv2_pos: int) -> np.ndarray | None:
    """Read a single frame at 0-based cv2_pos. Returns None if out of range."""
    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, cv2_pos)
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None


def _to_pil(frame_bgr: np.ndarray, crop: tuple | None = None) -> Image.Image:
    if crop is not None:
        x, y, w, h = crop
        frame_bgr = frame_bgr[y : y + h, x : x + w]
    return Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))


def embed_frame(frame_bgr: np.ndarray, crop: tuple | None = None) -> np.ndarray:
    """Embed a single BGR frame. Returns L2-normalised float32 vector."""
    img = _to_pil(frame_bgr, crop)
    emb = _get_model().encode(img, convert_to_numpy=True, show_progress_bar=False)
    emb = emb.astype(np.float32)
    return emb / np.linalg.norm(emb)


def embed_frames_batch(
    frames: list[np.ndarray], crop: tuple | None = None
) -> np.ndarray:
    """Embed a list of BGR frames in one CLIP batch. Returns (N, D) float32."""
    pil_images = [_to_pil(f, crop) for f in frames]
    embs = _get_model().encode(
        pil_images, convert_to_numpy=True, batch_size=64, show_progress_bar=False
    )
    embs = embs.astype(np.float32)
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    return embs / norms
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_processor.py -k "embed or read_frame" -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add clip-cutter/processor.py clip-cutter/tests/conftest.py clip-cutter/tests/test_processor.py
git commit -m "feat(clip-cutter): CLIP model singleton + frame embedding utilities"
```

---

## Task 3: Template state management

**Files:**
- Modify: `clip-cutter/processor.py` (add template functions)
- Modify: `clip-cutter/tests/test_processor.py` (add template tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_processor.py`:
```python
def test_load_template_state_missing_file(tmp_path):
    state = processor.load_template_state(tmp_path / "missing.json")
    assert state["frames"] == []
    assert state["mean_embedding"] is None


def test_save_and_reload_template_state(mock_model, tiny_video, tmp_path):
    path = tmp_path / "state.json"
    state = processor.load_template_state(path)
    from config import TRAINING_CROP
    import cv2
    cap = cv2.VideoCapture(str(tiny_video))
    ret, frame = cap.read()
    cap.release()
    state = processor.add_frame_to_template(state, str(tiny_video), 1, path, crop=TRAINING_CROP)
    assert len(state["frames"]) == 1
    assert state["mean_embedding"] is not None
    assert state["mean_embedding"].shape == (512,)
    # Reload from disk
    reloaded = processor.load_template_state(path)
    assert len(reloaded["frames"]) == 1
    np.testing.assert_allclose(
        reloaded["mean_embedding"], state["mean_embedding"], atol=1e-5
    )


def test_remove_frame_from_template(mock_model, tiny_video, tmp_path):
    path = tmp_path / "state.json"
    state = processor.load_template_state(path)
    from config import TRAINING_CROP
    state = processor.add_frame_to_template(state, str(tiny_video), 1, path, crop=TRAINING_CROP)
    state = processor.add_frame_to_template(state, str(tiny_video), 2, path, crop=TRAINING_CROP)
    assert len(state["frames"]) == 2
    state = processor.remove_frame_from_template(state, 0, path)
    assert len(state["frames"]) == 1


def test_compute_mean_embedding_is_unit_vector():
    rng = np.random.default_rng(0)
    embs = rng.random((5, 512)).astype(np.float32)
    mean = processor.compute_mean_embedding(embs)
    assert mean.shape == (512,)
    assert abs(np.linalg.norm(mean) - 1.0) < 1e-5


def test_frame_to_thumbnail_is_base64_string(tiny_video):
    frame = processor.read_frame(tiny_video, 0)
    thumb = processor.frame_to_thumbnail(frame)
    assert isinstance(thumb, str)
    # valid base64 JPEG
    data = base64.b64decode(thumb)
    assert data[:2] == b"\xff\xd8"  # JPEG magic bytes
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_processor.py -k "template or thumbnail or mean_embedding" -v
```

Expected: `AttributeError: module 'processor' has no attribute 'load_template_state'`

- [ ] **Step 3: Append template functions to `processor.py`**

```python
def frame_to_thumbnail(frame_bgr: np.ndarray, max_width: int = 120) -> str:
    """Return a base64-encoded JPEG thumbnail string."""
    h, w = frame_bgr.shape[:2]
    scale = max_width / w
    small = cv2.resize(frame_bgr, (max_width, int(h * scale)))
    _, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return base64.b64encode(buf).decode()


def compute_mean_embedding(embeddings: np.ndarray) -> np.ndarray:
    """L2-normalised mean of a (N, D) embedding matrix."""
    mean = embeddings.mean(axis=0).astype(np.float32)
    return mean / np.linalg.norm(mean)


def load_template_state(path: Path | str) -> dict:
    """Load template state from JSON. Returns empty state if file absent."""
    path = Path(path)
    if not path.exists():
        return {"frames": [], "mean_embedding": None}
    with open(path) as f:
        raw = json.load(f)
    for frame in raw["frames"]:
        frame["embedding"] = np.array(frame["embedding"], dtype=np.float32)
    if raw.get("mean_embedding") is not None:
        raw["mean_embedding"] = np.array(raw["mean_embedding"], dtype=np.float32)
    return raw


def save_template_state(state: dict, path: Path | str) -> None:
    path = Path(path)
    serializable = {
        "frames": [
            {**f, "embedding": f["embedding"].tolist()}
            for f in state["frames"]
        ],
        "mean_embedding": (
            state["mean_embedding"].tolist()
            if state["mean_embedding"] is not None
            else None
        ),
    }
    with open(path, "w") as f:
        json.dump(serializable, f)


def add_frame_to_template(
    state: dict,
    video_path: Path | str,
    frame_number: int,
    state_path: Path | str,
    crop: tuple | None = None,
) -> dict:
    """
    Extract frame at frame_number (1-based), embed it, add to state, persist.
    crop applies only during embedding (training frames use TRAINING_CROP;
    frames from new videos use no crop).
    """
    frame = read_frame(video_path, frame_number - 1)
    if frame is None:
        raise ValueError(f"Frame {frame_number} not found in {video_path}")
    emb = embed_frame(frame, crop=crop)
    thumb = frame_to_thumbnail(frame)
    state["frames"].append(
        {
            "video_path": str(video_path),
            "frame_number": frame_number,
            "embedding": emb,
            "thumbnail": thumb,
        }
    )
    all_embs = np.stack([f["embedding"] for f in state["frames"]])
    state["mean_embedding"] = compute_mean_embedding(all_embs)
    save_template_state(state, state_path)
    return state


def remove_frame_from_template(
    state: dict, idx: int, state_path: Path | str
) -> dict:
    state["frames"].pop(idx)
    if state["frames"]:
        all_embs = np.stack([f["embedding"] for f in state["frames"]])
        state["mean_embedding"] = compute_mean_embedding(all_embs)
    else:
        state["mean_embedding"] = None
    save_template_state(state, state_path)
    return state


def init_template_from_clips_dir(
    clips_dir: Path | str,
    state_path: Path | str,
    crop: tuple | None = None,
) -> dict:
    """Build a fresh template state from all .avi clips in clips_dir."""
    clips_dir = Path(clips_dir)
    # Only base clips (success/failure suffix, not DLC result files)
    clip_files = sorted(
        p for p in clips_dir.glob("*.avi")
        if "_success" in p.stem or "_failure" in p.stem
    )
    state = {"frames": [], "mean_embedding": None}
    for clip_path in clip_files:
        # Frame 200 of clip = 0-based index 199
        frame = read_frame(clip_path, 199)
        if frame is None:
            continue
        emb = embed_frame(frame, crop=crop)
        thumb = frame_to_thumbnail(frame)
        state["frames"].append(
            {
                "video_path": str(clip_path),
                "frame_number": 200,
                "embedding": emb,
                "thumbnail": thumb,
            }
        )
    if state["frames"]:
        all_embs = np.stack([f["embedding"] for f in state["frames"]])
        state["mean_embedding"] = compute_mean_embedding(all_embs)
    save_template_state(state, state_path)
    return state
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_processor.py -k "template or thumbnail or mean_embedding" -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add clip-cutter/processor.py clip-cutter/tests/test_processor.py
git commit -m "feat(clip-cutter): template state management (add/remove/persist/init)"
```

---

## Task 4: Video scanning — coarse + fine pass

**Files:**
- Modify: `clip-cutter/processor.py` (add scan functions)
- Modify: `clip-cutter/tests/test_processor.py` (add scan tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_processor.py`:
```python
def test_smooth_curve_reduces_noise():
    values = np.array([0.0, 0.5, 1.0, 0.5, 0.0, 0.0, 0.0, 0.5, 1.0, 0.5, 0.0],
                      dtype=np.float32)
    smoothed = processor.smooth_curve(values, sigma=1.0)
    assert smoothed.shape == values.shape
    # Peak should still be near index 2 and 8
    assert smoothed[2] == smoothed.max() or smoothed[8] == smoothed.max()


def test_find_peaks_basic():
    # Two clear peaks at indices 10 and 50, above threshold 0.7
    values = np.zeros(100, dtype=np.float32)
    values[10] = 0.9
    values[50] = 0.8
    frame_indices = np.arange(0, 1000, 10)  # coarse: every 10th frame
    peaks = processor.find_peaks_in_curve(
        values, frame_indices, threshold=0.7, min_spacing=200
    )
    assert len(peaks) == 2
    assert 100 in peaks   # frame_indices[10] = 100
    assert 500 in peaks   # frame_indices[50] = 500


def test_find_peaks_respects_min_spacing():
    values = np.zeros(100, dtype=np.float32)
    values[10] = 0.9
    values[12] = 0.85   # too close to index 10
    frame_indices = np.arange(0, 1000, 10)
    peaks = processor.find_peaks_in_curve(
        values, frame_indices, threshold=0.7, min_spacing=200
    )
    assert len(peaks) == 1


def test_get_known_key_frames_parses_clip_names(tmp_path):
    # Create fake clip filenames
    for name in [
        "MAP2_0_20768_21567_success.avi",
        "MAP2_0_22148_22947_failure.avi",
    ]:
        (tmp_path / name).touch()
    known = processor.get_known_key_frames(tmp_path)
    # key_frame = start + 200
    assert 20968 in known
    assert 22348 in known


def test_get_known_key_frames_ignores_dlc_files(tmp_path):
    (tmp_path / "MAP2_0_20768_21567_successDLC_something.avi").touch()
    (tmp_path / "MAP2_0_20768_21567_success.avi").touch()
    known = processor.get_known_key_frames(tmp_path)
    assert len(known) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_processor.py -k "smooth or peaks or known_key" -v
```

Expected: `AttributeError: module 'processor' has no attribute 'smooth_curve'`

- [ ] **Step 3: Append scanning functions to `processor.py`**

```python
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks


def smooth_curve(values: np.ndarray, sigma: float = 3.0) -> np.ndarray:
    return gaussian_filter1d(values.astype(np.float64), sigma=sigma).astype(np.float32)


def find_peaks_in_curve(
    smoothed: np.ndarray,
    frame_indices: np.ndarray,
    threshold: float,
    min_spacing: int,
) -> list[int]:
    """
    Return list of original frame indices (0-based cv2_pos) at detected peaks.
    min_spacing is in original frame units; convert to curve-index units by
    dividing by the stride implied by frame_indices.
    """
    stride = int(frame_indices[1] - frame_indices[0]) if len(frame_indices) > 1 else 1
    min_distance_idx = max(1, min_spacing // stride)
    peak_idxs, _ = find_peaks(smoothed, height=threshold, distance=min_distance_idx)
    return [int(frame_indices[i]) for i in peak_idxs]


def get_similarity_curve(
    video_path: Path | str,
    template_emb: np.ndarray,
    stride: int = 10,
    batch_size: int = 64,
    progress_cb=None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Coarse scan: extract every `stride`th frame, embed, compute cosine similarity.
    Returns (frame_indices, similarities) as 1D numpy arrays (0-based cv2_pos).
    progress_cb(current, total) is called after each batch if provided.
    """
    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    all_positions = np.arange(0, total_frames, stride)
    similarities = np.zeros(len(all_positions), dtype=np.float32)

    for batch_start in range(0, len(all_positions), batch_size):
        batch_pos = all_positions[batch_start : batch_start + batch_size]
        frames = []
        cap = cv2.VideoCapture(str(video_path))
        for pos in batch_pos:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(pos))
            ret, frame = cap.read()
            frames.append(frame if ret else np.zeros((64, 64, 3), dtype=np.uint8))
        cap.release()

        embs = embed_frames_batch(frames)
        sims = embs @ template_emb  # cosine similarity (both unit vectors)
        similarities[batch_start : batch_start + len(batch_pos)] = sims

        if progress_cb:
            progress_cb(batch_start + len(batch_pos), len(all_positions))

    return all_positions, similarities


def fine_scan(
    video_path: Path | str,
    template_emb: np.ndarray,
    coarse_cv2_pos: int,
    window: int = 50,
) -> int:
    """
    Scan ±window frames around coarse_cv2_pos at stride 1.
    Returns the cv2_pos of the best-matching frame.
    """
    cap = cv2.VideoCapture(str(video_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    start = max(0, coarse_cv2_pos - window)
    end = min(total - 1, coarse_cv2_pos + window)
    frames = []
    positions = list(range(start, end + 1))

    cap = cv2.VideoCapture(str(video_path))
    for pos in positions:
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        frames.append(frame if ret else np.zeros((64, 64, 3), dtype=np.uint8))
    cap.release()

    embs = embed_frames_batch(frames)
    sims = embs @ template_emb
    best_local = int(np.argmax(sims))
    return positions[best_local]


def scan_video(
    video_path: Path | str,
    template_emb: np.ndarray,
    stride: int = 10,
    threshold: float = 0.70,
    min_spacing: int = 900,
    fine_window: int = 50,
    batch_size: int = 64,
    progress_cb=None,
) -> list[dict]:
    """
    Full scan pipeline. Returns list of dicts:
      {cv2_pos, frame_number (1-based), similarity}
    """
    frame_indices, raw_sims = get_similarity_curve(
        video_path, template_emb, stride=stride,
        batch_size=batch_size, progress_cb=progress_cb
    )
    smoothed = smooth_curve(raw_sims, sigma=3.0)
    coarse_peaks = find_peaks_in_curve(smoothed, frame_indices, threshold, min_spacing)

    results = []
    for coarse_pos in coarse_peaks:
        exact_pos = fine_scan(video_path, template_emb, coarse_pos, window=fine_window)
        sim = float(raw_sims[np.searchsorted(frame_indices, coarse_pos)])
        results.append(
            {
                "cv2_pos": exact_pos,
                "frame_number": exact_pos + 1,  # 1-based
                "similarity": round(sim, 4),
            }
        )
    return results


def get_known_key_frames(clips_dir: Path | str) -> dict[int, str]:
    """
    Parse existing clip filenames to extract known key frames.
    Returns {key_frame_number (1-based): clip_stem}.
    Ignores DLC result files (those with 'DLC' anywhere after the label).
    """
    clips_dir = Path(clips_dir)
    known = {}
    for p in clips_dir.glob("*.avi"):
        stem = p.stem
        # Valid clip: ends with _success or _failure (no DLC suffix)
        if "DLC" in stem:
            continue
        for label in ("_success", "_failure"):
            if stem.endswith(label):
                core = stem[: -len(label)]
                parts = core.rsplit("_", 2)
                if len(parts) >= 3:
                    try:
                        start = int(parts[-2])
                        known[start + 200] = stem
                    except ValueError:
                        pass
                break
    return known
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_processor.py -k "smooth or peaks or known_key" -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add clip-cutter/processor.py clip-cutter/tests/test_processor.py
git commit -m "feat(clip-cutter): coarse+fine CLIP scan pipeline"
```

---

## Task 5: Clip extraction + CSV writing

**Files:**
- Modify: `clip-cutter/processor.py` (add extraction functions)
- Modify: `clip-cutter/tests/test_processor.py` (add extraction tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_processor.py`:
```python
def test_extract_clip_video_creates_file(tiny_video, tmp_path):
    out = tmp_path / "clip.avi"
    processor.extract_clip_video(tiny_video, cv2_start=5, cv2_end=14, output_path=out)
    assert out.exists()
    import cv2 as _cv2
    cap = _cv2.VideoCapture(str(out))
    count = int(cap.get(_cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    assert count == 10  # frames 5..14 inclusive


def test_build_clip_csv_row_count(tiny_video, tiny_csv):
    df = processor.build_clip_csv(tiny_csv, start_frame_number=5, end_frame_number=14)
    assert len(df) == 10
    assert list(df.columns) == [
        "timestamp", "frame_number", "frame_line_status", "note", "clip_frame"
    ]
    assert df["clip_frame"].tolist() == list(range(1, 11))
    assert df["frame_number"].iloc[0] == 5


def test_update_parent_csv_note_writes_correctly(tiny_csv):
    processor.update_parent_csv_note(tiny_csv, frame_number=10, note="start_reaching")
    df = pd.read_csv(tiny_csv)
    row = df[df["frame_number"] == 10]
    assert row["note"].values[0] == "start_reaching"
    # All other rows untouched
    assert (df[df["frame_number"] != 10]["note"] == "").all()


def test_update_parent_csv_preserves_row_count(tiny_csv):
    original_count = len(pd.read_csv(tiny_csv))
    processor.update_parent_csv_note(tiny_csv, frame_number=5, note="start_reaching")
    assert len(pd.read_csv(tiny_csv)) == original_count
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_processor.py -k "extract_clip or build_clip_csv or update_parent" -v
```

Expected: `AttributeError: module 'processor' has no attribute 'extract_clip_video'`

- [ ] **Step 3: Append extraction functions to `processor.py`**

```python
def extract_clip_video(
    video_path: Path | str,
    cv2_start: int,
    cv2_end: int,
    output_path: Path | str,
) -> None:
    """
    Write frames [cv2_start, cv2_end] inclusive from video_path to output_path.
    Codec: MJPEG (matches source). cv2_start and cv2_end are 0-based.
    """
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, cv2_start)

    out = cv2.VideoWriter(
        str(output_path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h)
    )
    for _ in range(cv2_end - cv2_start + 1):
        ret, frame = cap.read()
        if not ret:
            break
        out.write(frame)
    cap.release()
    out.release()


def build_clip_csv(
    parent_csv_path: Path | str,
    start_frame_number: int,
    end_frame_number: int,
) -> pd.DataFrame:
    """
    Slice rows from parent CSV where frame_number is in [start, end] inclusive.
    Appends a 1-based clip_frame column.
    frame_number values are 1-based as stored in the CSV.
    """
    df = pd.read_csv(parent_csv_path)
    mask = (df["frame_number"] >= start_frame_number) & (
        df["frame_number"] <= end_frame_number
    )
    clip_df = df[mask].copy().reset_index(drop=True)
    clip_df["clip_frame"] = range(1, len(clip_df) + 1)
    return clip_df


def update_parent_csv_note(
    parent_csv_path: Path | str, frame_number: int, note: str
) -> None:
    """
    Write `note` into the note column of the row matching frame_number.
    All other rows and columns are unchanged.
    """
    df = pd.read_csv(parent_csv_path)
    df.loc[df["frame_number"] == frame_number, "note"] = note
    df.to_csv(parent_csv_path, index=False)


def extract_clip(
    video_path: Path | str,
    parent_csv_path: Path | str,
    key_frame_number: int,
    output_dir: Path | str,
) -> dict:
    """
    Extract the 800-frame clip for a confirmed detection.
    Writes: {output_dir}/{stem}_{start}_{end}.avi and matching .csv
    Returns dict with output paths and start/end frame numbers.
    key_frame_number is 1-based (matches CSV frame_number).
    """
    from config import CLIP_PRE_FRAMES, CLIP_POST_FRAMES

    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    start_fn = key_frame_number - CLIP_PRE_FRAMES   # 1-based
    end_fn = key_frame_number + CLIP_POST_FRAMES - 1  # 1-based, inclusive

    stem = video_path.stem
    clip_stem = f"{stem}_{start_fn}_{end_fn}"
    avi_path = output_dir / f"{clip_stem}.avi"
    csv_path = output_dir / f"{clip_stem}.csv"

    extract_clip_video(video_path, cv2_start=start_fn - 1, cv2_end=end_fn - 1, output_path=avi_path)

    clip_df = build_clip_csv(parent_csv_path, start_fn, end_fn)
    clip_df.to_csv(csv_path, index=False)

    return {"avi_path": str(avi_path), "csv_path": str(csv_path),
            "start_frame_number": start_fn, "end_frame_number": end_fn}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_processor.py -k "extract_clip or build_clip_csv or update_parent" -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Run the full test suite to make sure nothing regressed**

```bash
python -m pytest tests/test_processor.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add clip-cutter/processor.py clip-cutter/tests/test_processor.py
git commit -m "feat(clip-cutter): clip video extraction and CSV writing"
```

---

## Task 6: Flask app + all routes

**Files:**
- Create: `clip-cutter/app.py`
- Create: `clip-cutter/routes.py`
- Create: `clip-cutter/tests/test_routes.py`

- [ ] **Step 1: Write the failing route tests**

`clip-cutter/tests/test_routes.py`:
```python
import sys
import json
import pytest
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask test client with patched paths and mocked CLIP model."""
    import config
    import processor

    monkeypatch.setattr(config, "TEMPLATE_STATE_PATH", tmp_path / "state.json")

    rng = np.random.default_rng(42)
    class FakeModel:
        def encode(self, images, convert_to_numpy=True, batch_size=64, show_progress_bar=False):
            n = len(images) if isinstance(images, list) else 1
            return rng.random((n, 512)).astype(np.float32) if n > 1 else rng.random(512).astype(np.float32)
    monkeypatch.setattr(processor, "_model", FakeModel())

    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_index_returns_200(client):
    resp = client.get("/clip-cutter/")
    assert resp.status_code == 200
    assert b"Clip Cutter" in resp.data


def test_template_get_empty(client):
    resp = client.get("/clip-cutter/template")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["count"] == 0
    assert data["frames"] == []


def test_template_delete_out_of_range(client):
    resp = client.delete("/clip-cutter/template/0")
    assert resp.status_code == 404


def test_videos_returns_list(client, monkeypatch, tmp_path):
    import config
    (tmp_path / "vid1.avi").touch()
    (tmp_path / "vid2.avi").touch()
    monkeypatch.setattr(config, "VIDEO_DIR", tmp_path)
    resp = client.get("/clip-cutter/videos")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert len(data["videos"]) == 2


def test_extract_route_missing_params(client):
    resp = client.post(
        "/clip-cutter/extract",
        json={},
        content_type="application/json",
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_routes.py -v
```

Expected: `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Write `app.py`**

```python
from flask import Flask
from routes import bp, load_state


def create_app() -> Flask:
    # No template_folder/static_folder here — the blueprint owns them.
    app = Flask(__name__)
    app.register_blueprint(bp)
    load_state()   # populate _state after monkeypatching is possible in tests
    return app


if __name__ == "__main__":
    create_app().run(debug=True, port=5001)
```

- [ ] **Step 4: Write `routes.py`**

```python
from __future__ import annotations

import threading
import uuid
from pathlib import Path

from flask import Blueprint, Response, jsonify, render_template, request, stream_with_context

import config
import processor

bp = Blueprint(
    "clip_cutter", __name__, url_prefix="/clip-cutter",
    template_folder="templates",
    static_folder="static", static_url_path="/clip-cutter/static",
)

# In-memory job registry: job_id → {status, phase, current, total, detections, error}
_scan_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

# Template state — initialized empty; loaded by load_state() called from create_app()
_state: dict = {"frames": [], "mean_embedding": None}


def load_state() -> None:
    """Load template state from disk. Called once by create_app()."""
    global _state
    _state = processor.load_template_state(config.TEMPLATE_STATE_PATH)


# ── UI ──────────────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    return render_template("clip_cutter.html")


# ── Template bank ────────────────────────────────────────────────────────────

@bp.route("/template")
def get_template():
    global _state
    frames_out = [
        {"thumbnail": f["thumbnail"], "video_path": f["video_path"],
         "frame_number": f["frame_number"]}
        for f in _state["frames"]
    ]
    return jsonify({"count": len(frames_out), "frames": frames_out})


@bp.route("/template/add", methods=["POST"])
def add_to_template():
    global _state
    body = request.get_json(force=True)
    video_path = body.get("video_path")
    frame_number = body.get("frame_number")
    if not video_path or frame_number is None:
        return jsonify({"error": "video_path and frame_number required"}), 400
    try:
        _state = processor.add_frame_to_template(
            _state, video_path, int(frame_number),
            config.TEMPLATE_STATE_PATH, crop=None  # no crop for new-video frames
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    return jsonify({"count": len(_state["frames"])})


@bp.route("/template/<int:idx>", methods=["DELETE"])
def remove_from_template(idx: int):
    global _state
    if idx >= len(_state["frames"]):
        return jsonify({"error": "index out of range"}), 404
    _state = processor.remove_frame_from_template(_state, idx, config.TEMPLATE_STATE_PATH)
    return jsonify({"count": len(_state["frames"])})


@bp.route("/template/init", methods=["POST"])
def init_template():
    """Rebuild template from all clips in TRAINING_CLIPS_DIR."""
    global _state
    _state = processor.init_template_from_clips_dir(
        config.TRAINING_CLIPS_DIR, config.TEMPLATE_STATE_PATH, crop=config.TRAINING_CROP
    )
    return jsonify({"count": len(_state["frames"])})


# ── Video list ────────────────────────────────────────────────────────────────

def _video_is_done(avi_path: Path) -> bool:
    test_clips_dir = avi_path.parent / (avi_path.stem + config.TEST_CLIPS_SUFFIX)
    if test_clips_dir.exists():
        return True
    csv_path = avi_path.with_suffix(".csv")
    if csv_path.exists():
        import pandas as pd
        df = pd.read_csv(csv_path, usecols=["note"])
        return df["note"].eq("start_reaching").any()
    return False


@bp.route("/videos")
def list_videos():
    videos = []
    for p in sorted(config.VIDEO_DIR.glob("*.avi")):
        videos.append({
            "name": p.name,
            "path": str(p),
            "done": _video_is_done(p),
        })
    return jsonify({"videos": videos})


# ── Scan ──────────────────────────────────────────────────────────────────────

def _run_scan(job_id: str, video_path: str, template_emb):
    def progress_cb(current, total):
        with _jobs_lock:
            _scan_jobs[job_id]["current"] = current
            _scan_jobs[job_id]["total"] = total

    with _jobs_lock:
        _scan_jobs[job_id]["phase"] = "coarse"

    try:
        detections = processor.scan_video(
            video_path,
            template_emb,
            stride=config.SCAN_STRIDE,
            threshold=config.SIMILARITY_THRESHOLD,
            min_spacing=config.MIN_PEAK_SPACING,
            fine_window=config.FINE_SCAN_WINDOW,
            batch_size=config.SCAN_BATCH_SIZE,
            progress_cb=progress_cb,
        )
        # Annotate with known key frame match
        known = processor.get_known_key_frames(config.TRAINING_CLIPS_DIR)
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
    except Exception as exc:
        with _jobs_lock:
            _scan_jobs[job_id]["status"] = "error"
            _scan_jobs[job_id]["error"] = str(exc)


@bp.route("/scan", methods=["POST"])
def start_scan():
    body = request.get_json(force=True)
    video_path = body.get("video_path")
    if not video_path:
        return jsonify({"error": "video_path required"}), 400
    if _state["mean_embedding"] is None:
        return jsonify({"error": "template is empty — run /template/init first"}), 422

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _scan_jobs[job_id] = {"status": "running", "phase": "starting",
                               "current": 0, "total": 1, "detections": [], "error": None}

    import numpy as np
    template_emb = _state["mean_embedding"].copy()
    thread = threading.Thread(target=_run_scan, args=(job_id, video_path, template_emb), daemon=True)
    thread.start()
    return jsonify({"job_id": job_id})


@bp.route("/scan/stream")
def scan_stream():
    job_id = request.args.get("job_id")
    if not job_id or job_id not in _scan_jobs:
        return jsonify({"error": "unknown job_id"}), 404

    def generate():
        import time, json
        while True:
            with _jobs_lock:
                job = dict(_scan_jobs[job_id])
            yield f"data: {json.dumps(job)}\n\n"
            if job["status"] in ("done", "error"):
                break
            time.sleep(0.5)

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Extract confirmed detection ───────────────────────────────────────────────

@bp.route("/extract", methods=["POST"])
def extract():
    body = request.get_json(force=True)
    video_path = body.get("video_path")
    key_frame = body.get("key_frame")
    if not video_path or key_frame is None:
        return jsonify({"error": "video_path and key_frame required"}), 400

    video_path = Path(video_path)
    parent_csv = video_path.with_suffix(".csv")
    output_dir = video_path.parent / (video_path.stem + config.TEST_CLIPS_SUFFIX)

    result = processor.extract_clip(video_path, parent_csv, int(key_frame), output_dir)
    processor.update_parent_csv_note(parent_csv, int(key_frame), "start_reaching")
    return jsonify(result)
```

- [ ] **Step 5: Run route tests to verify they pass**

```bash
python -m pytest tests/test_routes.py -v
```

Expected: 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add clip-cutter/app.py clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat(clip-cutter): Flask routes, SSE scan streaming, clip extraction endpoint"
```

---

## Task 7: HTML template

**Files:**
- Create: `clip-cutter/templates/clip_cutter.html`

- [ ] **Step 1: Write `clip_cutter.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Clip Cutter</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d1117; color: #cdd9e5; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 13px; height: 100vh; display: flex; flex-direction: column; }
header { padding: 10px 16px; border-bottom: 1px solid #30363d; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
header h1 { font-size: 15px; font-weight: 600; }
#status-msg { font-size: 11px; color: #768390; }
.app { display: flex; flex: 1; overflow: hidden; }

/* SIDEBAR */
.sidebar { width: 210px; flex-shrink: 0; background: #161b22; border-right: 1px solid #30363d; display: flex; flex-direction: column; overflow: hidden; }
.sidebar-header { padding: 10px 10px 6px; border-bottom: 1px solid #30363d; display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
.sidebar-title { font-size: 10px; color: #768390; text-transform: uppercase; letter-spacing: 0.5px; }
.btn-sm { font-size: 10px; padding: 3px 8px; border-radius: 4px; cursor: pointer; border: 1px solid; background: transparent; }
.btn-green { border-color: #2ea043; color: #2ea043; }
.btn-green:hover { background: #2ea04322; }
.btn-blue { border-color: #388bfd; color: #388bfd; }
.btn-blue:hover { background: #388bfd22; }
.btn-red { border-color: #f85149; color: #f85149; }
.btn-red:hover { background: #f8514922; }
#template-grid { padding: 8px; display: flex; flex-wrap: wrap; gap: 5px; overflow-y: auto; flex: 1; }
.thumb { width: 58px; height: 44px; background: #1c2128; border-radius: 3px; border: 1px solid #30363d; cursor: pointer; position: relative; overflow: hidden; title: "Click to remove"; }
.thumb:hover { border-color: #f85149; }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb-label { position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.65); font-size: 7px; color: #ccc; text-align: center; padding: 1px; }
#template-footer { padding: 6px 10px; border-top: 1px solid #30363d; font-size: 10px; color: #768390; flex-shrink: 0; }

/* MAIN */
.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

/* Video section */
.section { padding: 10px 14px; border-bottom: 1px solid #30363d; flex-shrink: 0; }
.section-label { font-size: 10px; color: #768390; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
#video-list { display: flex; flex-direction: column; gap: 3px; max-height: 110px; overflow-y: auto; }
.video-row { display: flex; align-items: center; justify-content: space-between; padding: 5px 8px; background: #1c2128; border-radius: 4px; border: 1px solid transparent; cursor: pointer; }
.video-row:hover { border-color: #388bfd44; }
.video-row.selected { border-color: #388bfd; background: #1a2535; }
.video-row.done { opacity: 0.45; cursor: default; }
.video-name { font-family: monospace; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 320px; }
.badge { font-size: 9px; padding: 1px 6px; border-radius: 3px; flex-shrink: 0; }
.badge-done { background: #1a3a1a; color: #2ea043; }
.badge-pending { background: #1a2535; color: #388bfd; }
#scan-btn { margin-top: 8px; padding: 6px 18px; background: #1f6feb; color: #fff; border: none; border-radius: 5px; cursor: pointer; font-size: 12px; }
#scan-btn:disabled { opacity: 0.4; cursor: not-allowed; }
#scan-btn:not(:disabled):hover { background: #388bfd; }

/* Progress */
#progress-section { padding: 8px 14px; border-bottom: 1px solid #30363d; background: #161b22; display: none; flex-shrink: 0; }
#progress-label { font-size: 10px; color: #768390; margin-bottom: 4px; display: flex; justify-content: space-between; }
#progress-bar { height: 4px; background: #30363d; border-radius: 2px; }
#progress-fill { height: 100%; width: 0; background: linear-gradient(90deg, #1f6feb, #7ec8e3); border-radius: 2px; transition: width 0.3s; }

/* Results */
.results-section { flex: 1; overflow-y: auto; padding: 10px 14px; }
#results-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
#results-count { font-size: 11px; color: #2ea043; }
#results-list { display: flex; flex-direction: column; gap: 6px; }
.result-card { display: flex; align-items: center; gap: 10px; padding: 8px 10px; background: #1c2128; border-radius: 5px; border: 1px solid #30363d; }
.result-card.new { border-color: #388bfd55; }
.result-card.kept { opacity: 0.4; }
.result-card.rejected { opacity: 0.4; }
.result-meta { flex: 1; }
.result-name { font-family: monospace; font-size: 11px; color: #cdd9e5; margin-bottom: 2px; }
.result-info { font-size: 10px; color: #768390; margin-bottom: 5px; }
.result-actions { display: flex; gap: 5px; }
.sim-pill { font-size: 10px; padding: 2px 7px; border-radius: 10px; background: #1a3a1a; color: #2ea043; flex-shrink: 0; }
.match-pill { font-size: 9px; padding: 1px 5px; border-radius: 3px; flex-shrink: 0; }
.match-known { background: #1a3a1a; color: #2ea043; }
.match-new { background: #1a2535; color: #388bfd; }
</style>
</head>
<body>

<header>
  <h1>Clip Cutter</h1>
  <span id="status-msg">Ready</span>
</header>

<div class="app">
  <!-- Sidebar -->
  <div class="sidebar">
    <div class="sidebar-header">
      <span class="sidebar-title">Template Bank</span>
      <button class="btn-sm btn-green" onclick="initTemplate()">↺ Init</button>
    </div>
    <div id="template-grid"></div>
    <div id="template-footer">0 frames loaded</div>
  </div>

  <!-- Main panel -->
  <div class="main">
    <!-- Video list -->
    <div class="section">
      <div class="section-label">Select video to scan</div>
      <div id="video-list"></div>
      <button id="scan-btn" disabled onclick="startScan()">▶ Scan selected video</button>
    </div>

    <!-- Progress -->
    <div id="progress-section">
      <div id="progress-label">
        <span id="progress-text">Scanning…</span>
        <span id="progress-pct">0%</span>
      </div>
      <div id="progress-bar"><div id="progress-fill"></div></div>
    </div>

    <!-- Results -->
    <div class="results-section">
      <div id="results-header">
        <span class="section-label">Detections</span>
        <span id="results-count"></span>
      </div>
      <div id="results-list"></div>
    </div>
  </div>
</div>

<script src="/clip-cutter/static/clip_cutter.js"></script>
</body>
</html>
```

- [ ] **Step 2: Verify the app renders**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python app.py &
curl -s http://localhost:5001/clip-cutter/ | grep -c "Clip Cutter"
kill %1
```

Expected: `2` (title appears in `<title>` and `<h1>`).

- [ ] **Step 3: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html
git commit -m "feat(clip-cutter): HTML layout B (sidebar + main panel)"
```

---

## Task 8: JavaScript frontend

**Files:**
- Create: `clip-cutter/static/clip_cutter.js`

- [ ] **Step 1: Write `clip_cutter.js`**

```javascript
// State
let selectedVideoPath = null;
let currentJobId = null;
let eventSource = null;
const detections = [];   // {frame_number, similarity, known_match, video_path, status}

// ── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  loadTemplate();
  loadVideos();
});

// ── Template bank ─────────────────────────────────────────────────────────────

async function loadTemplate() {
  const resp = await fetch("/clip-cutter/template");
  const data = await resp.json();
  renderTemplate(data);
}

function renderTemplate(data) {
  const grid = document.getElementById("template-grid");
  const footer = document.getElementById("template-footer");
  grid.innerHTML = "";
  data.frames.forEach((f, idx) => {
    const div = document.createElement("div");
    div.className = "thumb";
    div.title = `${f.video_path} frame ${f.frame_number}\nClick to remove`;
    div.innerHTML = `<img src="data:image/jpeg;base64,${f.thumbnail}"><span class="thumb-label">fr${f.frame_number}</span>`;
    div.addEventListener("click", () => removeTemplateFrame(idx));
    grid.appendChild(div);
  });
  footer.textContent = `${data.count} frame${data.count !== 1 ? "s" : ""} loaded`;
}

async function initTemplate() {
  setStatus("Building template from training clips…");
  const resp = await fetch("/clip-cutter/template/init", { method: "POST" });
  const data = await resp.json();
  await loadTemplate();
  setStatus(`Template initialised: ${data.count} frames`);
}

async function removeTemplateFrame(idx) {
  if (!confirm("Remove this frame from the template?")) return;
  await fetch(`/clip-cutter/template/${idx}`, { method: "DELETE" });
  await loadTemplate();
}

async function addToTemplate(videoPath, frameNumber) {
  const resp = await fetch("/clip-cutter/template/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_path: videoPath, frame_number: frameNumber }),
  });
  if (resp.ok) {
    await loadTemplate();
    setStatus(`Frame ${frameNumber} added to template`);
  }
}

// ── Video list ────────────────────────────────────────────────────────────────

async function loadVideos() {
  const resp = await fetch("/clip-cutter/videos");
  const data = await resp.json();
  renderVideos(data.videos);
}

function renderVideos(videos) {
  const list = document.getElementById("video-list");
  list.innerHTML = "";
  videos.forEach((v) => {
    const row = document.createElement("div");
    row.className = "video-row" + (v.done ? " done" : "");
    row.innerHTML = `
      <span class="video-name" title="${v.path}">${v.name}</span>
      <span class="badge ${v.done ? "badge-done" : "badge-pending"}">${v.done ? "done" : "ready"}</span>`;
    if (!v.done) {
      row.addEventListener("click", () => selectVideo(v.path, row));
    }
    list.appendChild(row);
  });
}

function selectVideo(path, rowEl) {
  document.querySelectorAll(".video-row").forEach((r) => r.classList.remove("selected"));
  rowEl.classList.add("selected");
  selectedVideoPath = path;
  document.getElementById("scan-btn").disabled = false;
}

// ── Scan ──────────────────────────────────────────────────────────────────────

async function startScan() {
  if (!selectedVideoPath) return;
  document.getElementById("scan-btn").disabled = true;
  document.getElementById("results-list").innerHTML = "";
  document.getElementById("results-count").textContent = "";
  detections.length = 0;

  const resp = await fetch("/clip-cutter/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_path: selectedVideoPath }),
  });
  if (!resp.ok) {
    const err = await resp.json();
    setStatus("Error: " + err.error);
    document.getElementById("scan-btn").disabled = false;
    return;
  }
  const { job_id } = await resp.json();
  currentJobId = job_id;
  listenToScan(job_id);
}

function listenToScan(jobId) {
  const progressSection = document.getElementById("progress-section");
  progressSection.style.display = "block";
  setStatus("Scanning…");

  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/clip-cutter/scan/stream?job_id=${jobId}`);

  eventSource.onmessage = (e) => {
    const job = JSON.parse(e.data);
    updateProgress(job);
    if (job.status === "done") {
      eventSource.close();
      progressSection.style.display = "none";
      renderDetections(job.detections);
      document.getElementById("scan-btn").disabled = false;
      setStatus(`Scan complete — ${job.detections.length} detection${job.detections.length !== 1 ? "s" : ""}`);
    } else if (job.status === "error") {
      eventSource.close();
      progressSection.style.display = "none";
      setStatus("Scan error: " + job.error);
      document.getElementById("scan-btn").disabled = false;
    }
  };
}

function updateProgress(job) {
  const pct = job.total > 0 ? Math.round((job.current / job.total) * 100) : 0;
  document.getElementById("progress-fill").style.width = pct + "%";
  document.getElementById("progress-pct").textContent = pct + "%";
  document.getElementById("progress-text").textContent =
    `${job.phase} pass — frame ${job.current.toLocaleString()} / ${job.total.toLocaleString()}`;
}

// ── Results ───────────────────────────────────────────────────────────────────

function renderDetections(dets) {
  const list = document.getElementById("results-list");
  const count = document.getElementById("results-count");
  list.innerHTML = "";
  count.textContent = `${dets.length} found`;

  dets.forEach((d) => {
    d.video_path = selectedVideoPath;
    d.status = "pending";
    detections.push(d);
    const card = buildResultCard(d, detections.length - 1);
    list.appendChild(card);
  });
}

function buildResultCard(d, idx) {
  const videoName = d.video_path.split("/").pop().replace(".avi", "");
  const pre = 200, post = 600;
  const clipName = `${videoName}_${d.frame_number - pre}_${d.frame_number + post - 1}`;
  const isKnown = !!d.known_match;

  const card = document.createElement("div");
  card.className = "result-card" + (isKnown ? "" : " new");
  card.id = `card-${idx}`;
  card.innerHTML = `
    <div class="result-meta">
      <div class="result-name">${clipName}.avi</div>
      <div class="result-info">
        Key frame ${d.frame_number.toLocaleString()} ·
        <span class="match-pill ${isKnown ? "match-known" : "match-new"}">
          ${isKnown ? "✓ matches " + d.known_match : "new detection"}
        </span>
      </div>
      <div class="result-actions">
        <button class="btn-sm btn-green" onclick="keepDetection(${idx})">✓ Keep</button>
        <button class="btn-sm btn-red" onclick="rejectDetection(${idx})">✗ Reject</button>
        <button class="btn-sm btn-blue" onclick="addToTemplate('${d.video_path}', ${d.frame_number})">+ Add to template</button>
      </div>
    </div>
    <span class="sim-pill">${d.similarity.toFixed(2)}</span>`;
  return card;
}

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
  } else {
    const err = await resp.json();
    setStatus("Error: " + err.error);
  }
}

function rejectDetection(idx) {
  detections[idx].status = "rejected";
  const card = document.getElementById(`card-${idx}`);
  card.classList.add("rejected");
  card.querySelectorAll("button").forEach((b) => (b.disabled = true));
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function setStatus(msg) {
  document.getElementById("status-msg").textContent = msg;
}
```

- [ ] **Step 2: Smoke test in browser**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python app.py
```

Open `http://localhost:5001/clip-cutter/` in a browser. Verify:
- Sidebar renders with "0 frames loaded"
- "↺ Init" button is visible
- Video list shows (may be empty if VIDEO_DIR doesn't exist yet — that's fine)
- No JS console errors

- [ ] **Step 3: Commit**

```bash
git add clip-cutter/static/clip_cutter.js
git commit -m "feat(clip-cutter): frontend JS (template bank, video list, scan + SSE, result actions)"
```

---

## Task 9: End-to-end smoke test with real data

No new files — run the real pipeline manually to validate accuracy.

- [ ] **Step 1: Start the app**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python app.py
```

- [ ] **Step 2: Initialise the template**

Open `http://localhost:5001/clip-cutter/`. Click **↺ Init**. Wait for the sidebar to populate with 19 thumbnails. Confirm the footer shows "19 frames loaded".

- [ ] **Step 3: Scan the training video**

Select `MAP2_20250515_103618_0.avi` from the video list. Click **▶ Scan selected video**. Watch the progress bar. After completion check:
- Number of detections ≥ 15 (expect ~19)
- Detections with "matches known clip ✓" should align with the 19 existing clips (key frame within ±5 frames)

- [ ] **Step 4: Verify accuracy**

For each "matches known clip ✓" detection, check that the detected frame_number is within ±5 of `start_frame + 200` from the known clip name. Any mismatch > 5 frames indicates the threshold or fine-scan window may need tuning in `config.py`.

- [ ] **Step 5: Extract one clip and inspect output**

Click **✓ Keep** on one detection. Verify:
```bash
ls "/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/MAP-2/MAP2_20250515_103618_0_test_clips/"
```
Expected: one `.avi` and one `.csv` file named `MAP2_20250515_103618_0_{start}_{end}.avi`.

Verify the parent CSV was updated:
```bash
python3 -c "
import pandas as pd
df = pd.read_csv('/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/MAP-2/MAP2_20250515_103618_0.csv')
print(df[df.note == 'start_reaching'][['frame_number','note']].head())
"
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(clip-cutter): complete clip-cutter module (CLIP scan + Flask UI)"
```

---

## Tuning Reference

If accuracy is low after Task 9 Step 4, adjust these constants in `config.py`:

| Issue | Fix |
|-------|-----|
| Too few detections | Lower `SIMILARITY_THRESHOLD` (try 0.60) |
| Too many false positives | Raise `SIMILARITY_THRESHOLD` (try 0.78) |
| Detected frame off by > 10 | Increase `FINE_SCAN_WINDOW` (try 100) |
| Double-counting adjacent events | Increase `MIN_PEAK_SPACING` (try 1200) |

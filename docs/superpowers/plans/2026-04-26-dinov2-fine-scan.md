# DINOv2 Fine Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace CLIP ViT-B/32 with DINOv2 ViT-L/14 in `fine_scan()` to eliminate the ±20-30 frame random keyframe error caused by CLIP's flat cosine-similarity curve within the fine-scan window.

**Architecture:** Two models run independently. CLIP ViT-B/32 stays for the coarse scan (full-video retrieval). DINOv2 ViT-L/14 handles `fine_scan()` only (±50 frame window). The template stores two mean embeddings: `mean_embedding` (CLIP, 512-dim) and `dino_mean_embedding` (DINOv2, 1024-dim). Existing template JSON files without `dino_mean_embedding` gracefully fall back to CLIP with a logged warning until the user re-runs init.

**Tech Stack:** `torch.hub` (DINOv2), `torchvision.transforms` (image preprocessing), existing `processor.py` / `routes.py` pattern, Docker build-time model download.

---

## File Changes

| File | Change |
|------|--------|
| `clip-cutter/requirements.txt` | Add `torchvision>=0.17` |
| `clip-cutter/config.py` | Add `DINO_MODEL_NAME` |
| `clip-cutter/processor.py` | Add `_dino_model`/`_get_dino_model()`, `embed_frames_dino_batch()`, `compute_dino_mean_embedding()`; update `fine_scan()`, `save_template_state()`, `load_template_state()`, `add_frame_to_template()`, `remove_frame_from_template()`, `init_template_from_clips_dir()`, `scan_video()`, `scan_video_sensor_guided()` |
| `clip-cutter/routes.py` | Add `dino_mean_embedding` to `_state` default; read from `_state` in `start_scan()`; pass to `_run_scan()` |
| `clip-cutter/Dockerfile` | Pre-download DINOv2 weights at build time |
| `clip-cutter/tests/test_dino.py` | New test file for DINOv2 functions |

---

### Task 1: Config + requirements

**Files:**
- Modify: `clip-cutter/config.py`
- Modify: `clip-cutter/requirements.txt`

- [ ] **Step 1: Add `DINO_MODEL_NAME` to `config.py`**

Open `config.py`. After the `SCAN_BATCH_SIZE` line, add a new section:

```python
# ── DINOv2 fine scan ──────────────────────────────────────────────────────────
DINO_MODEL_NAME = "dinov2_vitl14"   # swap to dinov2_vitb14 for faster/smaller
```

- [ ] **Step 2: Add torchvision to `requirements.txt`**

`torchvision` provides the image transform pipeline needed for DINOv2 preprocessing. Add to `requirements.txt`:

```
torchvision>=0.17
```

- [ ] **Step 3: Verify torchvision imports inside the container**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
docker compose run --rm clip-cutter python -c "import torchvision; print(torchvision.__version__)"
```

Expected: a version string like `0.17.x`. If the image is stale, rebuild first: `docker compose build`.

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/config.py clip-cutter/requirements.txt
git commit -m "feat: add DINO_MODEL_NAME config and torchvision dep"
```

---

### Task 2: DINOv2 model functions — TDD

**Files:**
- Create: `clip-cutter/tests/test_dino.py`
- Modify: `clip-cutter/processor.py`

The goal of this task is: `_get_dino_model()`, `embed_frames_dino_batch()`, and `compute_dino_mean_embedding()` exist in `processor.py` and pass tests.

DINOv2 ViT-L/14 produces 1024-dimensional CLS token embeddings. Images must be resized to 224×224 and normalized with ImageNet mean/std.

- [ ] **Step 1: Write the failing tests**

Create `clip-cutter/tests/test_dino.py`:

```python
import numpy as np
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import processor


def _make_random_bgr_frames(n=4, h=480, w=640):
    rng = np.random.default_rng(42)
    return [rng.integers(0, 255, (h, w, 3), dtype=np.uint8) for _ in range(n)]


def test_embed_frames_dino_batch_shape():
    frames = _make_random_bgr_frames(4)
    embs = processor.embed_frames_dino_batch(frames)
    assert embs.shape == (4, 1024), f"expected (4, 1024), got {embs.shape}"


def test_embed_frames_dino_batch_l2_normalised():
    frames = _make_random_bgr_frames(3)
    embs = processor.embed_frames_dino_batch(frames)
    norms = np.linalg.norm(embs, axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-5)


def test_embed_frames_dino_batch_single_frame():
    frames = _make_random_bgr_frames(1)
    embs = processor.embed_frames_dino_batch(frames)
    assert embs.shape == (1, 1024)


def test_embed_frames_dino_batch_respects_batch_size():
    # Batch size smaller than number of frames — should still produce correct output
    frames = _make_random_bgr_frames(6)
    embs = processor.embed_frames_dino_batch(frames, batch_size=2)
    assert embs.shape == (6, 1024)
    norms = np.linalg.norm(embs, axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-5)


def test_compute_dino_mean_embedding_shape():
    frames = _make_random_bgr_frames(5)
    mean_emb = processor.compute_dino_mean_embedding(frames)
    assert mean_emb.shape == (1024,)


def test_compute_dino_mean_embedding_normalised():
    frames = _make_random_bgr_frames(5)
    mean_emb = processor.compute_dino_mean_embedding(frames)
    norm = np.linalg.norm(mean_emb)
    np.testing.assert_allclose(norm, 1.0, atol=1e-5)


def test_compute_dino_mean_embedding_empty_returns_none():
    result = processor.compute_dino_mean_embedding([])
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_dino.py -v 2>&1 | tail -15
```

Expected: `AttributeError: module 'processor' has no attribute 'embed_frames_dino_batch'`

- [ ] **Step 3: Add DINOv2 singleton and embedding functions to `processor.py`**

In `processor.py`, after the existing CLIP singleton block (lines 15–24), add:

```python
# Lazy-loaded DINOv2 model singleton
_dino_model = None
_dino_transform = None


def _get_dino_model():
    global _dino_model, _dino_transform
    if _dino_model is None:
        import torch
        import torchvision.transforms as T
        _dino_model = torch.hub.load(
            "facebookresearch/dinov2", config.DINO_MODEL_NAME, pretrained=True
        )
        _dino_model.eval()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _dino_model = _dino_model.to(device)
        _dino_transform = T.Compose([
            T.Resize(224, interpolation=T.InterpolationMode.BICUBIC),
            T.CenterCrop(224),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
    return _dino_model, _dino_transform


def embed_frames_dino_batch(frames: list, batch_size: int = 64) -> np.ndarray:
    """Embed BGR numpy frames with DINOv2 ViT-L/14.

    Returns L2-normalised float32 array of shape (N, 1024).
    """
    import torch
    model, transform = _get_dino_model()
    device = next(model.parameters()).device
    all_embs: list[np.ndarray] = []
    for i in range(0, len(frames), batch_size):
        batch = frames[i:i + batch_size]
        tensors = torch.stack([
            transform(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)))
            for f in batch
        ]).to(device)
        with torch.no_grad():
            feats = model(tensors)          # CLS token, shape (B, 1024)
        feats = feats.cpu().float().numpy()
        norms = np.linalg.norm(feats, axis=1, keepdims=True).clip(min=1e-8)
        all_embs.append(feats / norms)
    return np.concatenate(all_embs, axis=0)


def compute_dino_mean_embedding(frames: list) -> np.ndarray | None:
    """L2-normalised mean DINOv2 embedding over a list of BGR frames.

    Returns None when frames is empty.
    """
    if not frames:
        return None
    embs = embed_frames_dino_batch(frames)
    mean = embs.mean(axis=0).astype(np.float32)
    norm = np.linalg.norm(mean)
    if norm == 0.0:
        return None
    return mean / norm
```

`config` is already imported at the top of `processor.py`. `Image`, `cv2`, and `np` are already imported.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_dino.py -v 2>&1 | tail -15
```

Expected: 7 tests PASSED. DINOv2 model loads on first run (downloads from hub if not cached).

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/processor.py clip-cutter/tests/test_dino.py
git commit -m "feat: DINOv2 model singleton, embed_frames_dino_batch, compute_dino_mean_embedding"
```

---

### Task 3: Update `fine_scan()` to use DINOv2

**Files:**
- Modify: `clip-cutter/processor.py` (lines 343–370)
- Modify: `clip-cutter/tests/test_dino.py`

Current `fine_scan()` signature (line 343):
```python
def fine_scan(
    video_path: Path | str,
    template_emb: np.ndarray,
    coarse_cv2_pos: int,
    window: int = 50,
) -> tuple[int, float]:
```

- [ ] **Step 1: Write failing test for DINOv2 fine_scan path**

Append to `tests/test_dino.py`:

```python
def test_fine_scan_uses_dino_when_emb_provided(tmp_path):
    import cv2 as _cv2
    # Create a minimal 3-second synthetic AVI (90 frames at 30fps)
    out_path = tmp_path / "test.avi"
    writer = _cv2.VideoWriter(
        str(out_path),
        _cv2.VideoWriter_fourcc(*"XVID"),
        30.0,
        (64, 64),
    )
    rng = np.random.default_rng(7)
    for _ in range(90):
        frame = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
        writer.write(frame)
    writer.release()

    # Build a random dino_template_emb
    rng2 = np.random.default_rng(99)
    dino_emb = rng2.random(1024).astype(np.float32)
    dino_emb /= np.linalg.norm(dino_emb)

    # fine_scan with dino_template_emb should return a position within the window
    coarse = 45
    pos, sim = processor.fine_scan(
        str(out_path), template_emb=None, coarse_cv2_pos=coarse,
        window=20, dino_template_emb=dino_emb
    )
    assert 0 <= pos <= 89, f"position {pos} out of video range"
    assert -1.0 <= sim <= 1.0, f"similarity {sim} out of [-1, 1]"


def test_fine_scan_falls_back_to_clip_when_no_dino_emb(tmp_path):
    import cv2 as _cv2
    out_path = tmp_path / "test2.avi"
    writer = _cv2.VideoWriter(
        str(out_path), _cv2.VideoWriter_fourcc(*"XVID"), 30.0, (64, 64)
    )
    rng = np.random.default_rng(13)
    for _ in range(60):
        writer.write(rng.integers(0, 255, (64, 64, 3), dtype=np.uint8))
    writer.release()

    clip_emb = np.zeros(512, dtype=np.float32)
    clip_emb[0] = 1.0   # unit vector
    pos, sim = processor.fine_scan(
        str(out_path), template_emb=clip_emb, coarse_cv2_pos=30,
        window=10, dino_template_emb=None
    )
    assert 0 <= pos <= 59
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_dino.py::test_fine_scan_uses_dino_when_emb_provided tests/test_dino.py::test_fine_scan_falls_back_to_clip_when_no_dino_emb -v 2>&1 | tail -15
```

Expected: `TypeError: fine_scan() got an unexpected keyword argument 'dino_template_emb'`

- [ ] **Step 3: Update `fine_scan()` in `processor.py`**

Replace the entire `fine_scan()` function (lines 343–370) with:

```python
def fine_scan(
    video_path: Path | str,
    template_emb: np.ndarray | None,
    coarse_cv2_pos: int,
    window: int = 50,
    dino_template_emb: np.ndarray | None = None,
) -> tuple[int, float]:
    """
    Scan ±window frames around coarse_cv2_pos at stride 1.
    Uses DINOv2 embeddings if dino_template_emb is provided, else CLIP.
    Returns (cv2_pos, similarity) of the best-matching frame.
    """
    cap = cv2.VideoCapture(str(video_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    start = max(0, coarse_cv2_pos - window)
    end = min(total - 1, coarse_cv2_pos + window)
    frames = []
    positions = list(range(start, end + 1))

    for pos in positions:
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        frames.append(frame if ret else np.zeros((64, 64, 3), dtype=np.uint8))
    cap.release()

    if dino_template_emb is not None:
        embs = embed_frames_dino_batch(frames)
        sims = embs @ dino_template_emb
    else:
        embs = embed_frames_batch(frames)
        sims = embs @ template_emb

    best_local = int(np.argmax(sims))
    return positions[best_local], float(sims[best_local])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_dino.py -v 2>&1 | tail -15
```

Expected: all 9 tests PASSED.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/processor.py clip-cutter/tests/test_dino.py
git commit -m "feat: fine_scan() accepts dino_template_emb, uses DINOv2 when provided"
```

---

### Task 4: Template state — store and load DINOv2 embeddings

**Files:**
- Modify: `clip-cutter/processor.py` (functions: `load_template_state`, `save_template_state`, `add_frame_to_template`, `remove_frame_from_template`, `init_template_from_clips_dir`)
- Modify: `clip-cutter/tests/test_dino.py`

The template state dict gains a new key `dino_mean_embedding` (numpy array or None). Per-frame dicts gain `dino_embedding` (numpy array). Both are serialised as lists in JSON.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_dino.py`:

```python
def test_template_state_roundtrip_preserves_dino_embedding(tmp_path):
    state_path = tmp_path / "state.json"
    dino_emb = np.random.default_rng(1).random(1024).astype(np.float32)
    dino_emb /= np.linalg.norm(dino_emb)
    clip_emb = np.random.default_rng(2).random(512).astype(np.float32)
    clip_emb /= np.linalg.norm(clip_emb)
    dino_frame_emb = np.random.default_rng(3).random(1024).astype(np.float32)
    dino_frame_emb /= np.linalg.norm(dino_frame_emb)

    state = {
        "frames": [{
            "video_path": "/fake/v.avi",
            "frame_number": 100,
            "embedding": clip_emb,
            "dino_embedding": dino_frame_emb,
            "thumbnail": "abc",
        }],
        "mean_embedding": clip_emb,
        "dino_mean_embedding": dino_emb,
    }
    processor.save_template_state(state, state_path)
    loaded = processor.load_template_state(state_path)

    assert loaded["dino_mean_embedding"] is not None
    np.testing.assert_allclose(loaded["dino_mean_embedding"], dino_emb, atol=1e-5)
    np.testing.assert_allclose(
        loaded["frames"][0]["dino_embedding"], dino_frame_emb, atol=1e-5
    )


def test_load_template_state_old_json_returns_none_dino(tmp_path):
    """Old JSON without dino_mean_embedding must load without error."""
    import json as _json
    state_path = tmp_path / "old_state.json"
    old_state = {
        "frames": [],
        "mean_embedding": None,
    }
    state_path.write_text(_json.dumps(old_state))
    loaded = processor.load_template_state(state_path)
    assert loaded.get("dino_mean_embedding") is None


def test_load_template_state_missing_file_returns_none_dino():
    loaded = processor.load_template_state("/nonexistent/path.json")
    assert loaded.get("dino_mean_embedding") is None


def test_compute_dino_mean_from_embeddings_shape():
    embs = np.random.default_rng(77).random((5, 1024)).astype(np.float32)
    result = processor._compute_dino_mean_from_embeddings(embs)
    assert result.shape == (1024,)
    np.testing.assert_allclose(np.linalg.norm(result), 1.0, atol=1e-5)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_dino.py::test_template_state_roundtrip_preserves_dino_embedding tests/test_dino.py::test_load_template_state_old_json_returns_none_dino tests/test_dino.py::test_load_template_state_missing_file_returns_none_dino -v 2>&1 | tail -15
```

Expected: failures because `save_template_state` doesn't serialise `dino_mean_embedding` yet.

- [ ] **Step 3: Update `load_template_state()` in `processor.py`**

Replace lines 86–97 with:

```python
def load_template_state(path: Path | str) -> dict:
    """Load template state from JSON. Returns empty state if file absent."""
    path = Path(path)
    if not path.exists():
        return {"frames": [], "mean_embedding": None, "dino_mean_embedding": None}
    with open(path) as f:
        raw = json.load(f)
    for frame in raw.get("frames", []):
        frame["embedding"] = np.array(frame["embedding"], dtype=np.float32)
        if frame.get("dino_embedding") is not None:
            frame["dino_embedding"] = np.array(frame["dino_embedding"], dtype=np.float32)
    if raw.get("mean_embedding") is not None:
        raw["mean_embedding"] = np.array(raw["mean_embedding"], dtype=np.float32)
    if raw.get("dino_mean_embedding") is not None:
        raw["dino_mean_embedding"] = np.array(raw["dino_mean_embedding"], dtype=np.float32)
    else:
        raw["dino_mean_embedding"] = None
    return raw
```

- [ ] **Step 4: Update `save_template_state()` in `processor.py`**

Replace lines 100–115 with:

```python
def save_template_state(state: dict, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {
        "frames": [
            {
                **{k: v for k, v in f.items() if k not in ("embedding", "dino_embedding")},
                "embedding": f["embedding"].tolist(),
                **({"dino_embedding": f["dino_embedding"].tolist()}
                   if f.get("dino_embedding") is not None else {}),
            }
            for f in state["frames"]
        ],
        "mean_embedding": (
            state["mean_embedding"].tolist()
            if state.get("mean_embedding") is not None else None
        ),
        "dino_mean_embedding": (
            state["dino_mean_embedding"].tolist()
            if state.get("dino_mean_embedding") is not None else None
        ),
    }
    with open(path, "w") as f:
        json.dump(serializable, f)
```

- [ ] **Step 5: Update `add_frame_to_template()` in `processor.py`**

Replace lines 118–146 with:

```python
def add_frame_to_template(
    state: dict,
    video_path: Path | str,
    frame_number: int,
    state_path: Path | str,
    crop: tuple | None = None,
) -> dict:
    """
    Extract frame at frame_number (1-based), embed with CLIP and DINOv2, add to state, persist.
    """
    frame = read_frame(video_path, frame_number - 1)
    if frame is None:
        raise ValueError(f"Frame {frame_number} not found in {video_path}")
    emb = embed_frame(frame, crop=crop)
    dino_emb = embed_frames_dino_batch([frame])[0]
    thumb = frame_to_thumbnail(frame)
    state["frames"].append(
        {
            "video_path": str(video_path),
            "frame_number": frame_number,
            "embedding": emb,
            "dino_embedding": dino_emb,
            "thumbnail": thumb,
        }
    )
    all_embs = np.stack([f["embedding"] for f in state["frames"]])
    state["mean_embedding"] = compute_mean_embedding(all_embs)
    all_dino_embs = np.stack([f["dino_embedding"] for f in state["frames"]])
    state["dino_mean_embedding"] = compute_dino_mean_embedding(
        []  # recompute from stored per-frame embeddings, not from raw frames
    ) or _compute_dino_mean_from_embeddings(all_dino_embs)
    save_template_state(state, state_path)
    return state
```

Add the helper `_compute_dino_mean_from_embeddings` just before `add_frame_to_template`:

```python
def _compute_dino_mean_from_embeddings(embs: np.ndarray) -> np.ndarray:
    """L2-normalised mean of a (N, 1024) DINOv2 embedding matrix."""
    mean = embs.mean(axis=0).astype(np.float32)
    norm = np.linalg.norm(mean)
    return mean / norm if norm > 0 else mean
```

And simplify `add_frame_to_template` to use it directly:

```python
def add_frame_to_template(
    state: dict,
    video_path: Path | str,
    frame_number: int,
    state_path: Path | str,
    crop: tuple | None = None,
) -> dict:
    frame = read_frame(video_path, frame_number - 1)
    if frame is None:
        raise ValueError(f"Frame {frame_number} not found in {video_path}")
    emb = embed_frame(frame, crop=crop)
    dino_emb = embed_frames_dino_batch([frame])[0]
    thumb = frame_to_thumbnail(frame)
    state["frames"].append({
        "video_path": str(video_path),
        "frame_number": frame_number,
        "embedding": emb,
        "dino_embedding": dino_emb,
        "thumbnail": thumb,
    })
    all_embs = np.stack([f["embedding"] for f in state["frames"]])
    state["mean_embedding"] = compute_mean_embedding(all_embs)
    all_dino = np.stack([f["dino_embedding"] for f in state["frames"]])
    state["dino_mean_embedding"] = _compute_dino_mean_from_embeddings(all_dino)
    save_template_state(state, state_path)
    return state
```

- [ ] **Step 6: Update `remove_frame_from_template()` in `processor.py`**

Replace lines 149–159 with:

```python
def remove_frame_from_template(
    state: dict, idx: int, state_path: Path | str
) -> dict:
    state["frames"].pop(idx)
    if state["frames"]:
        all_embs = np.stack([f["embedding"] for f in state["frames"]])
        state["mean_embedding"] = compute_mean_embedding(all_embs)
        all_dino = np.stack([f["dino_embedding"] for f in state["frames"]])
        state["dino_mean_embedding"] = _compute_dino_mean_from_embeddings(all_dino)
    else:
        state["mean_embedding"] = None
        state["dino_mean_embedding"] = None
    save_template_state(state, state_path)
    return state
```

- [ ] **Step 7: Update `init_template_from_clips_dir()` in `processor.py`**

Replace lines 162–194 with:

```python
def init_template_from_clips_dir(
    clips_dir: Path | str,
    state_path: Path | str,
    crop: tuple | None = None,
) -> dict:
    """Build a fresh template state from all .avi clips in clips_dir."""
    clips_dir = Path(clips_dir)
    clip_files = sorted(
        p for p in clips_dir.glob("*.avi")
        if p.stem.endswith("_success") or p.stem.endswith("_failure")
    )
    state: dict = {"frames": [], "mean_embedding": None, "dino_mean_embedding": None}
    raw_frames = []
    for clip_path in clip_files:
        frame = read_frame(clip_path, 199)
        if frame is None:
            continue
        raw_frames.append((clip_path, frame))

    if raw_frames:
        # Batch-embed all frames with CLIP then DINOv2
        all_bgr = [f for _, f in raw_frames]
        clip_embs = [embed_frame(f, crop=crop) for f in all_bgr]
        dino_embs = embed_frames_dino_batch(all_bgr)
        for (clip_path, frame), clip_emb, dino_emb in zip(raw_frames, clip_embs, dino_embs):
            thumb = frame_to_thumbnail(frame)
            state["frames"].append({
                "video_path": str(clip_path),
                "frame_number": 200,
                "embedding": clip_emb,
                "dino_embedding": dino_emb,
                "thumbnail": thumb,
            })
        all_embs = np.stack([f["embedding"] for f in state["frames"]])
        state["mean_embedding"] = compute_mean_embedding(all_embs)
        all_dino = np.stack([f["dino_embedding"] for f in state["frames"]])
        state["dino_mean_embedding"] = _compute_dino_mean_from_embeddings(all_dino)
    save_template_state(state, state_path)
    return state
```

- [ ] **Step 8: Run all dino tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_dino.py -v 2>&1 | tail -20
```

Expected: 12 tests PASSED.

- [ ] **Step 9: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/processor.py clip-cutter/tests/test_dino.py
git commit -m "feat: template state stores dino_embedding per frame and dino_mean_embedding"
```

---

### Task 5: Wire DINOv2 into `scan_video()` and `scan_video_sensor_guided()`

**Files:**
- Modify: `clip-cutter/processor.py` (lines 373–416 and 419–529)
- Modify: `clip-cutter/tests/test_dino.py`

Both scan functions call `fine_scan()`. They need to accept and forward `dino_template_emb`.

- [ ] **Step 1: Write a failing integration test**

Append to `tests/test_dino.py`:

```python
def test_scan_video_sensor_guided_uses_dino_fine_scan(tmp_path, monkeypatch):
    """Verify dino_template_emb is forwarded to fine_scan."""
    calls = []
    original_fine_scan = processor.fine_scan

    def mock_fine_scan(*args, **kwargs):
        calls.append(kwargs.get("dino_template_emb"))
        return original_fine_scan(*args, **kwargs)

    monkeypatch.setattr(processor, "fine_scan", mock_fine_scan)

    import csv as _csv, cv2 as _cv2
    avi_path = tmp_path / "test.avi"
    writer = _cv2.VideoWriter(
        str(avi_path), _cv2.VideoWriter_fourcc(*"XVID"), 30.0, (64, 64)
    )
    rng = np.random.default_rng(55)
    for _ in range(300):
        writer.write(rng.integers(0, 255, (64, 64, 3), dtype=np.uint8))
    writer.release()

    csv_path = tmp_path / "test.csv"
    with open(csv_path, "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["frame_number", "frame_line_status"])
        for i in range(1, 301):
            w.writerow([i, 14 if 100 <= i <= 110 else 0])

    clip_emb = np.ones(512, dtype=np.float32) / (512 ** 0.5)
    dino_emb = np.ones(1024, dtype=np.float32) / (1024 ** 0.5)

    processor.scan_video_sensor_guided(
        str(avi_path), str(csv_path), clip_emb,
        dino_template_emb=dino_emb,
        fine_window=5,
    )
    assert len(calls) > 0, "fine_scan was never called"
    assert all(c is not None for c in calls), "dino_template_emb was not forwarded"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_dino.py::test_scan_video_sensor_guided_uses_dino_fine_scan -v 2>&1 | tail -10
```

Expected: `TypeError: scan_video_sensor_guided() got an unexpected keyword argument 'dino_template_emb'`

- [ ] **Step 3: Update `scan_video()` signature and `fine_scan` call**

In `processor.py`, update `scan_video()` (starts around line 373):

Add `dino_template_emb: np.ndarray | None = None` to the signature:

```python
def scan_video(
    video_path: Path | str,
    template_emb: np.ndarray,
    stride: int = 10,
    threshold: float = 0.70,
    min_spacing: int = 900,
    fine_window: int = 50,
    batch_size: int = 64,
    smooth_sigma: float = 3.0,
    progress_cb=None,
    phase_cb=None,
    dino_template_emb: np.ndarray | None = None,
) -> list[dict]:
```

Update the `fine_scan` call inside `scan_video` from:

```python
exact_pos, fine_sim = fine_scan(video_path, template_emb, coarse_pos, window=fine_window)
```

to:

```python
exact_pos, fine_sim = fine_scan(
    video_path, template_emb, coarse_pos,
    window=fine_window, dino_template_emb=dino_template_emb
)
```

- [ ] **Step 4: Update `scan_video_sensor_guided()` signature and `fine_scan` call**

Add `dino_template_emb: np.ndarray | None = None` to the signature of `scan_video_sensor_guided()` (around line 419). Then update its `fine_scan` call from:

```python
exact_pos, fine_sim = fine_scan(video_path, template_emb, coarse_pos, window=fine_window)
```

to:

```python
exact_pos, fine_sim = fine_scan(
    video_path, template_emb, coarse_pos,
    window=fine_window, dino_template_emb=dino_template_emb
)
```

- [ ] **Step 5: Run all dino tests**

```bash
python -m pytest tests/test_dino.py -v 2>&1 | tail -20
```

Expected: 13 tests PASSED.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/processor.py clip-cutter/tests/test_dino.py
git commit -m "feat: scan_video and scan_video_sensor_guided forward dino_template_emb to fine_scan"
```

---

### Task 6: Routes — wire `dino_mean_embedding` through the scan pipeline

**Files:**
- Modify: `clip-cutter/routes.py`

- [ ] **Step 1: Update default `_state` to include `dino_mean_embedding`**

In `routes.py` line 25, change:

```python
_state: dict = {"frames": [], "mean_embedding": None}
```

to:

```python
_state: dict = {"frames": [], "mean_embedding": None, "dino_mean_embedding": None}
```

- [ ] **Step 2: Update `_run_scan()` to read and forward `dino_mean_embedding`**

`_run_scan()` currently reads `template_emb` as a parameter. It needs to also read `dino_template_emb`. Change the signature of `_run_scan` from:

```python
def _run_scan(job_id: str, video_path: str, template_emb, params: dict):
```

to:

```python
def _run_scan(job_id: str, video_path: str, template_emb, dino_template_emb, params: dict):
```

Inside `_run_scan`, add `dino_template_emb=dino_template_emb` to both scan function calls:

```python
detections = processor.scan_video_sensor_guided(
    video_path, csv_path, template_emb,
    trigger_value=trigger_value,
    sensor_margin=sensor_margin,
    stride=stride,
    threshold=threshold,
    min_spacing=min_spacing,
    fine_window=fine_window,
    batch_size=config.SCAN_BATCH_SIZE,
    dino_template_emb=dino_template_emb,
    progress_cb=progress_cb,
    phase_cb=phase_cb,
)
```

and:

```python
detections = processor.scan_video(
    video_path, template_emb,
    stride=stride,
    threshold=threshold,
    min_spacing=min_spacing,
    fine_window=fine_window,
    batch_size=config.SCAN_BATCH_SIZE,
    dino_template_emb=dino_template_emb,
    progress_cb=progress_cb,
    phase_cb=phase_cb,
)
```

- [ ] **Step 3: Update `start_scan()` to read and pass `dino_mean_embedding`**

In `start_scan()`, after:

```python
with _state_lock:
    mean_embedding = _state["mean_embedding"]
```

add:

```python
with _state_lock:
    mean_embedding = _state["mean_embedding"]
    dino_mean_embedding = _state.get("dino_mean_embedding")
```

(Combine into one `with` block — do not take the lock twice.)

Then change the `thread = threading.Thread(...)` call from:

```python
thread = threading.Thread(
    target=_run_scan, args=(job_id, video_path, template_emb, params), daemon=True
)
```

to:

```python
dino_emb_copy = dino_mean_embedding.copy() if dino_mean_embedding is not None else None
thread = threading.Thread(
    target=_run_scan,
    args=(job_id, video_path, template_emb, dino_emb_copy, params),
    daemon=True,
)
```

If `dino_mean_embedding` is None (old template file), `fine_scan()` falls back to CLIP automatically.

- [ ] **Step 4: Verify the app starts and responds correctly**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
docker compose up -d
sleep 3
curl -s http://localhost:5002/clip-cutter/template | python3 -c "import sys,json; d=json.load(sys.stdin); print('count:', d['count'])"
```

Expected: `count: N` where N is the current template frame count. No crash.

- [ ] **Step 5: Log warning when DINOv2 embedding is absent**

In `routes.py`, in `start_scan()`, after reading `dino_mean_embedding`, add:

```python
if dino_mean_embedding is None:
    import logging
    logging.getLogger(__name__).warning(
        "dino_mean_embedding is None — fine scan will use CLIP fallback. "
        "Re-run /template/init to enable DINOv2 fine scan."
    )
```

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/routes.py
git commit -m "feat: routes wire dino_mean_embedding through _run_scan to scan functions"
```

---

### Task 7: Dockerfile — pre-download DINOv2 weights

**Files:**
- Modify: `clip-cutter/Dockerfile`

DINOv2 ViT-L/14 is ~1.1 GB. Pre-downloading at build time means the first scan doesn't stall waiting for a download.

- [ ] **Step 1: Add DINOv2 download line to Dockerfile**

After the existing CLIP pre-download line:

```dockerfile
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('clip-ViT-B-32')"
```

add:

```dockerfile
RUN python -c "import torch; torch.hub.load('facebookresearch/dinov2', 'dinov2_vitl14', pretrained=True)"
```

- [ ] **Step 2: Rebuild the image**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
docker compose build 2>&1 | tail -10
```

Expected: build succeeds. The download step will take a few minutes on first run (model is ~1.1 GB).

- [ ] **Step 3: Verify DINOv2 loads from cache inside the container**

```bash
docker compose run --rm clip-cutter python -c "
import torch
m = torch.hub.load('facebookresearch/dinov2', 'dinov2_vitl14', pretrained=True)
print('DINOv2 loaded, param count:', sum(p.numel() for p in m.parameters()))
"
```

Expected: prints param count (~307M). Should complete in a few seconds (no download).

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/Dockerfile
git commit -m "feat: pre-download DINOv2 ViT-L/14 weights in Docker image"
```

---

### Task 8: End-to-end smoke test + re-init template

**Files:** None (manual verification)

After rebuilding the image with DINOv2 pre-downloaded, the template needs to be re-initialised to compute `dino_mean_embedding`. Existing `template_state.json` files lack `dino_embedding` per frame, so the DINOv2 mean embedding is None until re-init.

- [ ] **Step 1: Start the container and navigate to the UI**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
docker compose up -d
```

Open `http://localhost:5002/clip-cutter/`.

- [ ] **Step 2: Re-init the template**

Click "Init from training clips". Wait for completion. The status message should show the frame count. Check the server log for any errors:

```bash
docker compose logs --tail=30 clip-cutter
```

Expected: no errors. Log should show DINOv2 model loaded (first call triggers `_get_dino_model()`).

- [ ] **Step 3: Run a scan and verify keyframe accuracy**

Select a video that has a known ground-truth keyframe. Run a scan. For 5 detections, compare the reported `frame_number` against the known ground truth. Record the absolute frame error for each. The median error should be noticeably lower than the previous ±20-30 frames.

- [ ] **Step 4: Run the full test suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/ -v 2>&1 | tail -30
```

Expected: all existing tests plus all new dino tests pass.

# DINOv2 Fine Scan — Design Spec

## Goal

Replace CLIP ViT-B/32 with DINOv2 ViT-L/14 in the fine-scan step to eliminate the ±20-30 frame random keyframe error caused by CLIP's flat cosine-similarity curve within the fine-scan window. Coarse scan stays CLIP. Fine scan switches to DINOv2, which produces 1024-dim spatially-aware CLS features with much sharper temporal peaks.

## Architecture

Two models run in parallel:

- **CLIP ViT-B/32** — coarse scan only (full-video retrieval, semantic breadth). Unchanged.
- **DINOv2 ViT-L/14** — fine scan only (±`FINE_SCAN_WINDOW` frames, precise temporal discrimination). New.

The template stores two mean embeddings: `mean_embedding` (CLIP, 512-dim) and `dino_mean_embedding` (DINOv2, 1024-dim). Both are computed at template init time and persisted in `template_state.json`.

Backward compatibility: template JSON files without `dino_mean_embedding` load fine — the key is `None`, `fine_scan()` falls back to CLIP, and a warning is logged. The user re-runs "Init from training clips" to enable DINOv2 fine scan.

---

## Changes

### `config.py`

```python
DINO_MODEL_NAME = "dinov2_vitl14"  # swap to dinov2_vitb14 for smaller/faster
```

### `processor.py`

#### DINOv2 model singleton

```python
_dino_model = None
_dino_transform = None

def _get_dino_model():
    global _dino_model, _dino_transform
    if _dino_model is None:
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
```

#### `embed_frames_dino_batch(frames, batch_size=64)`

```python
def embed_frames_dino_batch(frames: list, batch_size: int = 64) -> np.ndarray:
    """
    Embed BGR numpy frames with DINOv2. Returns L2-normalised (N, 1024) float32 array.
    """
    model, transform = _get_dino_model()
    device = next(model.parameters()).device
    all_embs = []
    for i in range(0, len(frames), batch_size):
        batch = frames[i:i + batch_size]
        tensors = torch.stack([
            transform(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)))
            for f in batch
        ]).to(device)
        with torch.no_grad():
            feats = model(tensors)  # CLS token, shape (B, 1024)
        feats = feats.cpu().float().numpy()
        feats /= np.linalg.norm(feats, axis=1, keepdims=True).clip(min=1e-8)
        all_embs.append(feats)
    return np.concatenate(all_embs, axis=0)
```

#### `compute_dino_mean_embedding(frames)`

Returns `None` when `frames` is empty (mirrors the CLIP path).

```python
def compute_dino_mean_embedding(frames: list) -> np.ndarray | None:
    if not frames:
        return None
    embs = embed_frames_dino_batch(frames)
    mean = embs.mean(axis=0)
    mean /= np.linalg.norm(mean).clip(min=1e-8)
    return mean
```

#### `fine_scan()` — add `dino_template_emb` kwarg

Current signature:
```python
def fine_scan(video_path, coarse_pos, template_emb, window=50, batch_size=64):
```

New signature:
```python
def fine_scan(video_path, coarse_pos, template_emb, window=50, batch_size=64,
              dino_template_emb=None):
    ...
    frames = read_window_frames(video_path, coarse_pos, window)  # existing logic
    if dino_template_emb is not None:
        embs = embed_frames_dino_batch(frames, batch_size=batch_size)
        sims = embs @ dino_template_emb
    else:
        embs = embed_frames_batch(frames)
        sims = embs @ template_emb
    best_idx = int(np.argmax(sims))
    best_sim = float(sims[best_idx])
    ...
```

#### Template functions — compute DINOv2 embedding alongside CLIP

`add_frame_to_template()`: after computing the CLIP embedding for the new frame, also compute its DINOv2 embedding. Recompute `dino_mean_embedding` from all stored DINOv2 frame embeddings (same pattern as CLIP).

`init_template_from_clips_dir()`: after building CLIP embeddings, compute DINOv2 embeddings for all template frames in one batch pass and store `dino_mean_embedding`.

`load_template_state()`: read `dino_mean_embedding` from JSON if present; default to `None`. Log a warning when `None` so the user knows fine scan is using CLIP fallback.

`save_template_state()`: serialize `dino_mean_embedding` alongside `mean_embedding` (same base64 numpy encoding).

The per-frame DINOv2 embeddings are stored in each frame dict as `"dino_embedding"` (base64 numpy, same as existing `"embedding"`). This allows `dino_mean_embedding` to be recomputed incrementally when frames are added/removed.

#### `scan_video_sensor_guided()` and `scan_video()`

Both already forward `template_emb` to `fine_scan()`. Add `dino_template_emb=dino_template_emb` to those calls. Their signatures gain `dino_template_emb=None`.

### `routes.py`

`_state` gains `"dino_mean_embedding": None` as a default key.

`_run_scan()` reads `dino_template_emb = _state["dino_mean_embedding"]` and passes it to the scan functions.

`add_frame_to_template()` route: no change needed — `processor.add_frame_to_template()` handles DINOv2 internally.

### `Dockerfile`

Pre-download DINOv2 weights at build time:

```dockerfile
RUN python -c "import torch; torch.hub.load('facebookresearch/dinov2', 'dinov2_vitl14', pretrained=True)"
```

Add after the existing CLIP pre-download line.

---

## File Changes

| File | Action |
|------|--------|
| `config.py` | Add `DINO_MODEL_NAME` |
| `processor.py` | Add `_get_dino_model()`, `embed_frames_dino_batch()`, `compute_dino_mean_embedding()`; update `fine_scan()`, `add_frame_to_template()`, `init_template_from_clips_dir()`, `load_template_state()`, `save_template_state()`, `scan_video()`, `scan_video_sensor_guided()` |
| `routes.py` | Add `dino_mean_embedding` to default `_state`; pass to `_run_scan()` |
| `Dockerfile` | Pre-download DINOv2 weights |

---

## Testing

### Backend unit tests (`tests/test_dino.py`)

- `embed_frames_dino_batch` returns shape `(N, 1024)`, L2-normalised (norm ≈ 1.0)
- `compute_dino_mean_embedding` returns shape `(1024,)`, L2-normalised
- `fine_scan()` with `dino_template_emb=None` → uses CLIP path (existing tests pass)
- `fine_scan()` with a real `dino_template_emb` → returns position within the window
- Template state round-trip: save/load preserves `dino_mean_embedding`
- `load_template_state()` on old JSON (no `dino_mean_embedding`) → returns `None` without error

### Integration

- After `init_template_from_clips_dir()`, `_state["dino_mean_embedding"]` is not `None`
- Scan on a video with a CSV uses DINOv2 in fine scan (verify by mocking `embed_frames_dino_batch` and checking it was called)

### Performance (manual)

Record fine-scan keyframe error before and after on 5 known videos. Target: median error < 5 frames.

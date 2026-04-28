from __future__ import annotations

import base64
import datetime
import json
import os
import threading
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, gaussian_filter1d
from scipy.signal import find_peaks

import config

# Lazy-loaded CLIP model singleton
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("clip-ViT-B-32")
    return _model


# Lazy-loaded DINOv2 model singleton
_dino_model = None
_dino_transform = None
_dino_model_lock = threading.Lock()


def _get_dino_model():
    global _dino_model, _dino_transform
    if _dino_model is None:
        with _dino_model_lock:
            if _dino_model is None:  # double-checked locking
                import torch
                import torchvision.transforms as T
                model = torch.hub.load(
                    "facebookresearch/dinov2", config.DINO_MODEL_NAME, pretrained=True
                )
                model.eval()
                device = "cuda" if torch.cuda.is_available() else "cpu"
                model = model.to(device)
                # Assign transform before model so the outer None check stays correct
                _dino_transform = T.Compose([
                    T.Resize(224, interpolation=T.InterpolationMode.BICUBIC),
                    T.CenterCrop(224),
                    T.ToTensor(),
                    T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
                ])
                _dino_model = model
    return _dino_model, _dino_transform


def embed_frames_dino_batch(frames: list, batch_size: int = 64) -> np.ndarray:
    """Embed BGR numpy frames with DINOv2. Returns L2-normalised (N, 1024) float32."""
    import torch
    model, transform = _get_dino_model()
    device = next(model.parameters()).device
    all_embs: list = []
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


def compute_dino_mean_embedding(frames: list) -> "np.ndarray | None":
    """L2-normalised mean DINOv2 embedding. Returns None when frames is empty."""
    if not frames:
        return None
    embs = embed_frames_dino_batch(frames)
    mean = embs.mean(axis=0).astype(np.float32)
    norm = np.linalg.norm(mean)
    if norm == 0.0:
        return None
    return mean / norm


def read_frame(video_path: Path | str, cv2_pos: int) -> np.ndarray | None:
    """Read a single frame at 0-based cv2_pos. Returns None if out of range."""
    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, cv2_pos)
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None


def _to_pil(frame_bgr: np.ndarray, crop: tuple | None = None) -> Image.Image:
    if crop is not None:
        fh, fw = frame_bgr.shape[:2]
        x, y, w, h = crop
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(fw, x + w), min(fh, y + h)
        if x2 > x1 and y2 > y1:
            frame_bgr = frame_bgr[y1:y2, x1:x2]
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
    norm = np.linalg.norm(mean)
    if norm == 0.0:
        raise ValueError("Cannot normalise a zero embedding vector")
    return mean / norm


def _compute_dino_mean_from_embeddings(embs: np.ndarray) -> np.ndarray:
    """L2-normalised mean of a (N, 1024) DINOv2 embedding matrix."""
    mean = embs.mean(axis=0).astype(np.float32)
    norm = np.linalg.norm(mean)
    return mean / norm if norm > 0 else mean


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


def load_combined_template(template_dirs: list) -> dict:
    """
    Load template_state.json from each clips_dir/template/ and stack embeddings.
    Returns {clip_matrix: ndarray (N,512) or None, dino_matrix: ndarray (N,D) or None}.
    """
    clip_embs, dino_embs = [], []
    for d in template_dirs:
        state_path = Path(d) / "template" / "template_state.json"
        state = load_template_state(state_path)
        if state["mean_embedding"] is not None:
            clip_embs.append(state["mean_embedding"])
        if state.get("dino_mean_embedding") is not None:
            dino_embs.append(state["dino_mean_embedding"])
    return {
        "clip_matrix": np.stack(clip_embs) if clip_embs else None,
        "dino_matrix": np.stack(dino_embs) if dino_embs else None,
    }


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
    dino_frames = [f["dino_embedding"] for f in state["frames"] if f.get("dino_embedding") is not None]
    if len(dino_frames) == len(state["frames"]):
        all_dino = np.stack(dino_frames)
        state["dino_mean_embedding"] = _compute_dino_mean_from_embeddings(all_dino)
    else:
        state["dino_mean_embedding"] = None
    save_template_state(state, state_path)
    return state


def remove_frame_from_template(
    state: dict, idx: int, state_path: Path | str
) -> dict:
    state["frames"].pop(idx)
    if state["frames"]:
        all_embs = np.stack([f["embedding"] for f in state["frames"]])
        state["mean_embedding"] = compute_mean_embedding(all_embs)
        dino_frames = [f["dino_embedding"] for f in state["frames"] if f.get("dino_embedding") is not None]
        if len(dino_frames) == len(state["frames"]):
            all_dino = np.stack(dino_frames)
            state["dino_mean_embedding"] = _compute_dino_mean_from_embeddings(all_dino)
        else:
            state["dino_mean_embedding"] = None
    else:
        state["mean_embedding"] = None
        state["dino_mean_embedding"] = None
    save_template_state(state, state_path)
    return state


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


def smooth_curve(values: np.ndarray, sigma: float = 3.0) -> np.ndarray:
    return gaussian_filter1d(values.astype(np.float64), sigma=sigma).astype(np.float32)


def find_sensor_triggers(
    csv_path: Path | str,
    trigger_value: int = 14,
    sensor_margin: int = 25,
) -> tuple[list[int], set[int]]:
    """
    Parse frame_line_status column to find sensor rising edges.

    Returns:
        rising_edge_frame_numbers: 1-based frame numbers at each rising edge
          of the dilated trigger burst — one per reaching event.
        covered_frame_set: all 1-based frame numbers inside any dilated burst,
          used to exclude them from the gap CLIP scan.
    """
    import pandas as pd

    try:
        df = pd.read_csv(csv_path, usecols=["frame_number", "frame_line_status"])
    except ValueError as exc:
        raise ValueError(
            f"CSV at {csv_path} is missing required columns (frame_number, frame_line_status): {exc}"
        ) from exc
    frames = df["frame_number"].to_numpy(dtype=np.int64)
    status = df["frame_line_status"].to_numpy(dtype=np.int64)

    if len(frames) == 0:
        return [], set()

    triggered = (status == trigger_value)
    structure = np.ones(2 * sensor_margin + 1, dtype=bool)
    dilated = binary_dilation(triggered, structure=structure)

    # Rising edges: False→True transitions (first element is a rising edge if True)
    rising_mask = np.zeros(len(dilated), dtype=bool)
    rising_mask[0] = dilated[0]
    rising_mask[1:] = dilated[1:] & ~dilated[:-1]

    rising_frame_numbers = [int(frames[i]) for i in np.where(rising_mask)[0]]
    covered_frame_set = {int(frames[i]) for i in np.where(dilated)[0]}

    return rising_frame_numbers, covered_frame_set


def find_peaks_in_curve(
    smoothed: np.ndarray,
    frame_indices: np.ndarray,
    threshold: float,
    min_spacing: int,
) -> list[int]:
    """
    Return list of original frame indices (0-based cv2_pos) at detected peaks.
    min_spacing is in original frame units; converted to curve-index units by
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
    positions: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Coarse scan: embed sampled frames, compute cosine similarity against template.

    If positions is provided, uses those 0-based frame numbers exactly.
    Otherwise samples every stride-th frame from the video.

    Returns (frame_indices, similarities) as 1D numpy arrays (0-based cv2_pos).
    Uses sequential reads (cap.grab() to skip) + a prefetch thread to overlap
    disk I/O with GPU embedding.
    progress_cb(current, total) is called after each batch if provided.
    """
    from concurrent.futures import ThreadPoolExecutor

    video_path_str = str(video_path)

    cap = cv2.VideoCapture(video_path_str)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    if positions is None:
        all_positions = np.arange(0, total_frames, stride, dtype=np.int64)
    else:
        all_positions = np.sort(np.asarray(positions, dtype=np.int64))

    similarities = np.zeros(len(all_positions), dtype=np.float32)

    if len(all_positions) == 0:
        return all_positions, similarities

    def read_batch(batch_positions):
        """Open a fresh VideoCapture and read the batch using sequential reads."""
        if len(batch_positions) == 0:
            return []
        vcap = cv2.VideoCapture(video_path_str)
        vcap.set(cv2.CAP_PROP_POS_FRAMES, int(batch_positions[0]))
        cur = int(batch_positions[0])
        frames = []
        try:
            for target in batch_positions:
                target = int(target)
                while cur < target:
                    vcap.grab()
                    cur += 1
                ret, frame = vcap.read()
                cur += 1
                frames.append(frame if ret else np.zeros((64, 64, 3), dtype=np.uint8))
        finally:
            vcap.release()
        return frames

    processed = 0
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(read_batch, all_positions[:batch_size])

        for batch_start in range(0, len(all_positions), batch_size):
            batch_pos = all_positions[batch_start : batch_start + batch_size]
            frames = future.result()

            next_start = batch_start + batch_size
            future = pool.submit(
                read_batch, all_positions[next_start : next_start + batch_size]
            )

            embs = embed_frames_batch(frames)
            sims = embs @ template_emb
            n = len(batch_pos)
            similarities[batch_start : batch_start + n] = sims[:n]
            processed += n
            if progress_cb:
                progress_cb(processed, len(all_positions))

    return all_positions, similarities


def get_similarity_curve_multi(
    video_path: Path | str,
    clip_matrix: np.ndarray,
    stride: int = 10,
    batch_size: int = 64,
    progress_cb=None,
    positions: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Like get_similarity_curve but uses max(clip_matrix @ frame_emb) over N templates.
    clip_matrix shape: (N, 512).
    """
    from concurrent.futures import ThreadPoolExecutor

    video_path_str = str(video_path)
    cap = cv2.VideoCapture(video_path_str)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    if positions is None:
        all_positions = np.arange(0, total_frames, stride, dtype=np.int64)
    else:
        all_positions = np.sort(np.asarray(positions, dtype=np.int64))

    similarities = np.zeros(len(all_positions), dtype=np.float32)
    if len(all_positions) == 0:
        return all_positions, similarities

    def read_batch(batch_positions):
        if len(batch_positions) == 0:
            return []
        vcap = cv2.VideoCapture(video_path_str)
        vcap.set(cv2.CAP_PROP_POS_FRAMES, int(batch_positions[0]))
        cur = int(batch_positions[0])
        frames = []
        try:
            for target in batch_positions:
                target = int(target)
                while cur < target:
                    vcap.grab()
                    cur += 1
                ret, frame = vcap.read()
                cur += 1
                frames.append(frame if ret else np.zeros((64, 64, 3), dtype=np.uint8))
        finally:
            vcap.release()
        return frames

    processed = 0
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(read_batch, all_positions[:batch_size])
        for batch_start in range(0, len(all_positions), batch_size):
            batch_pos = all_positions[batch_start: batch_start + batch_size]
            frames = future.result()
            next_start = batch_start + batch_size
            future = pool.submit(read_batch, all_positions[next_start: next_start + batch_size])
            embs = embed_frames_batch(frames)               # (B, 512)
            sims = (embs @ clip_matrix.T).max(axis=1)      # (B,)
            n = len(batch_pos)
            similarities[batch_start: batch_start + n] = sims[:n]
            processed += n
            if progress_cb:
                progress_cb(processed, len(all_positions))

    return all_positions, similarities


def fine_scan(
    video_path: Path | str,
    template_emb: "np.ndarray | None",
    coarse_cv2_pos: int,
    window: int = 50,
    dino_template_emb: "np.ndarray | None" = None,
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


def fine_scan_multi(
    video_path: Path | str,
    clip_matrix: "np.ndarray | None",
    coarse_cv2_pos: int,
    window: int = 50,
    dino_matrix: "np.ndarray | None" = None,
) -> tuple[int, float]:
    """
    Like fine_scan but uses max similarity across N template embeddings.
    clip_matrix: (N, 512) or None. dino_matrix: (N, D_dino) or None.
    """
    cap = cv2.VideoCapture(str(video_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    start = max(0, coarse_cv2_pos - window)
    end = min(total - 1, coarse_cv2_pos + window)
    positions = list(range(start, end + 1))
    frames = []
    for pos in positions:
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        frames.append(frame if ret else np.zeros((64, 64, 3), dtype=np.uint8))
    cap.release()

    if dino_matrix is not None:
        embs = embed_frames_dino_batch(frames)              # (B, D_dino)
        sims = (embs @ dino_matrix.T).max(axis=1)          # (B,)
    else:
        embs = embed_frames_batch(frames)                   # (B, 512)
        sims = (embs @ clip_matrix.T).max(axis=1)          # (B,)

    best_local = int(np.argmax(sims))
    return positions[best_local], float(sims[best_local])


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
    dino_template_emb: "np.ndarray | None" = None,
) -> list[dict]:
    """
    Full scan pipeline. Returns list of dicts:
      {cv2_pos, frame_number (1-based), similarity}
    phase_cb(phase, current, total) is called at each pipeline phase transition.
    """
    if phase_cb:
        phase_cb("coarse", 0, 1)
    frame_indices, raw_sims = get_similarity_curve(
        video_path, template_emb, stride=stride,
        batch_size=batch_size, progress_cb=progress_cb
    )

    if phase_cb:
        phase_cb("peak_detection", 0, 1)
    smoothed = smooth_curve(raw_sims, sigma=smooth_sigma)
    coarse_peaks = find_peaks_in_curve(smoothed, frame_indices, threshold, min_spacing)

    if phase_cb:
        phase_cb("fine", 0, max(len(coarse_peaks), 1))
    results = []
    for i, coarse_pos in enumerate(coarse_peaks):
        exact_pos, fine_sim = fine_scan(
            video_path, template_emb, coarse_pos,
            window=fine_window, dino_template_emb=dino_template_emb
        )
        results.append(
            {
                "cv2_pos": exact_pos,
                "frame_number": exact_pos + 1,  # 1-based
                "similarity": round(fine_sim, 4),
            }
        )
        if phase_cb:
            phase_cb("fine", i + 1, len(coarse_peaks))
    return results


def scan_video_sensor_guided(
    video_path: Path | str,
    csv_path: Path | str,
    template_emb: np.ndarray,
    trigger_value: int = 14,
    sensor_margin: int = 25,
    stride: int = 10,
    threshold: float = 0.70,
    min_spacing: int = 900,
    fine_window: int = 50,
    batch_size: int = 256,
    smooth_sigma: float = 3.0,
    progress_cb=None,
    phase_cb=None,
    dino_template_emb: "np.ndarray | None" = None,
) -> list[dict]:
    """
    Sensor-guided scan pipeline. Returns list of dicts:
      {cv2_pos, frame_number (1-based), similarity, source}

    source values:
      "sensor+clip" — sensor trigger, fine scan similarity >= threshold
      "sensor_only" — sensor trigger, fine scan similarity < threshold
      "clip_only"   — CLIP gap peak, no nearby sensor trigger
    """
    # Phase 0: sensor parse
    if phase_cb:
        phase_cb("sensor_parse", 0, 1)
    sensor_frames, covered_set = find_sensor_triggers(csv_path, trigger_value, sensor_margin)
    if phase_cb:
        phase_cb("sensor_parse", 1, 1)

    # Phase 1: gap CLIP scan — only frames NOT covered by sensor bursts
    if phase_cb:
        phase_cb("coarse", 0, 1)

    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    all_positions = np.arange(0, total_frames, stride, dtype=np.int64)
    # covered_set holds 1-based frame numbers; 0-based pos → 1-based = pos+1
    gap_positions = np.array(
        [p for p in all_positions if (int(p) + 1) not in covered_set], dtype=np.int64
    )

    if len(gap_positions) > 0:
        gap_indices, gap_sims = get_similarity_curve(
            video_path, template_emb,
            stride=stride, batch_size=batch_size,
            progress_cb=progress_cb, positions=gap_positions,
        )
    else:
        gap_indices = np.array([], dtype=np.int64)
        gap_sims = np.array([], dtype=np.float32)

    # Phase 2: peak detection on gap curve
    if phase_cb:
        phase_cb("peak_detection", 0, 1)

    clip_peaks: list[int] = []
    if len(gap_sims) > 0:
        smoothed = smooth_curve(gap_sims, sigma=smooth_sigma)
        clip_peaks = find_peaks_in_curve(smoothed, gap_indices, threshold, min_spacing)

    # Merge sensor rising edges (1-based → 0-based) with CLIP peaks
    candidates: list[tuple[int, str]] = []
    for sf in sensor_frames:
        candidates.append((sf - 1, "sensor"))
    for cp in clip_peaks:
        candidates.append((cp, "clip"))
    candidates.sort(key=lambda x: x[0])

    # Deduplicate: within min_spacing//2 frames, sensor candidate wins
    dedup: list[tuple[int, str]] = []
    half = min_spacing // 2
    for pos, src in candidates:
        if dedup and abs(pos - dedup[-1][0]) < half:
            prev_pos, prev_src = dedup[-1]
            if src == "sensor" and prev_src != "sensor":
                # Sensor displaces a CLIP candidate
                dedup[-1] = (pos, src)
            elif src == "sensor" and prev_src == "sensor":
                # Two close sensor events — keep both (both are authoritative)
                dedup.append((pos, src))
            # clip near anything: skip (already covered)
        else:
            dedup.append((pos, src))

    # Phase 3: fine scan
    if phase_cb:
        phase_cb("fine", 0, max(len(dedup), 1))

    results = []
    for i, (coarse_pos, src) in enumerate(dedup):
        exact_pos, fine_sim = fine_scan(
            video_path, template_emb, coarse_pos,
            window=fine_window, dino_template_emb=dino_template_emb
        )
        if src == "sensor":
            source_tag = "sensor+clip" if fine_sim >= threshold else "sensor_only"
        else:
            source_tag = "clip_only"
        results.append(
            {
                "cv2_pos": exact_pos,
                "frame_number": exact_pos + 1,
                "similarity": round(fine_sim, 4),
                "source": source_tag,
            }
        )
        if phase_cb:
            phase_cb("fine", i + 1, len(dedup))

    return results


def scan_video_sensor_guided_multi(
    video_path: Path | str,
    combined: dict,
    csv_path: Path | str,
    trigger_value: int = 14,
    sensor_margin: int = 25,
    stride: int = 10,
    threshold: float = 0.70,
    min_spacing: int = 900,
    fine_window: int = 50,
    batch_size: int = 256,
    smooth_sigma: float = 3.0,
    phase_cb=None,
) -> list[dict]:
    """
    Sensor-guided scan using multiple template embeddings (max similarity).
    Combined: output of load_combined_template().
    Returns same format as scan_video_sensor_guided: [{cv2_pos, frame_number, similarity, source}].
    """
    clip_matrix = combined.get("clip_matrix")
    dino_matrix = combined.get("dino_matrix")
    if clip_matrix is None:
        return []

    if phase_cb:
        phase_cb("sensor_parse", 0, 1)
    sensor_frames, covered_set = find_sensor_triggers(csv_path, trigger_value, sensor_margin)
    if phase_cb:
        phase_cb("sensor_parse", 1, 1)

    if phase_cb:
        phase_cb("coarse", 0, 1)

    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    all_positions = np.arange(0, total_frames, stride, dtype=np.int64)
    gap_positions = np.array(
        [p for p in all_positions if (int(p) + 1) not in covered_set], dtype=np.int64
    )

    if len(gap_positions) > 0:
        gap_indices, gap_sims = get_similarity_curve_multi(
            video_path, clip_matrix,
            stride=stride, batch_size=batch_size,
            positions=gap_positions,
        )
    else:
        gap_indices = np.array([], dtype=np.int64)
        gap_sims = np.array([], dtype=np.float32)

    if phase_cb:
        phase_cb("peak_detection", 0, 1)

    clip_peaks: list[int] = []
    if len(gap_sims) > 0:
        smoothed = smooth_curve(gap_sims, sigma=smooth_sigma)
        clip_peaks = find_peaks_in_curve(smoothed, gap_indices, threshold, min_spacing)

    candidates: list[tuple[int, str]] = []
    for sf in sensor_frames:
        candidates.append((sf - 1, "sensor"))
    for cp in clip_peaks:
        candidates.append((cp, "clip"))
    candidates.sort(key=lambda x: x[0])

    dedup: list[tuple[int, str]] = []
    half = min_spacing // 2
    for pos, src in candidates:
        if dedup and abs(pos - dedup[-1][0]) < half:
            prev_pos, prev_src = dedup[-1]
            if src == "sensor" and prev_src != "sensor":
                dedup[-1] = (pos, src)
            elif src == "sensor" and prev_src == "sensor":
                dedup.append((pos, src))
        else:
            dedup.append((pos, src))

    if phase_cb:
        phase_cb("fine", 0, max(len(dedup), 1))

    results = []
    for i, (coarse_pos, src) in enumerate(dedup):
        exact_pos, fine_sim = fine_scan_multi(
            video_path, clip_matrix, coarse_pos,
            window=fine_window, dino_matrix=dino_matrix,
        )
        if src == "sensor":
            source_tag = "sensor+clip" if fine_sim >= threshold else "sensor_only"
        else:
            source_tag = "clip_only"
        results.append({
            "cv2_pos": exact_pos,
            "frame_number": exact_pos + 1,
            "similarity": round(fine_sim, 4),
            "source": source_tag,
        })
        if phase_cb:
            phase_cb("fine", i + 1, len(dedup))

    return results


def find_template_candidates(
    video_path: Path | str,
    combined: dict,
    n_clusters: int = 10,
    threshold: float = 0.70,
    stride: int = 10,
    batch_size: int = 64,
    phase_cb=None,
    csv_path: Path | str | None = None,
    trigger_value: int = 14,
    sensor_margin: int = 25,
) -> dict:
    """
    K-means candidate pipeline for template frame discovery.

    Returns:
        {
            candidates: [{frame_number (1-based), similarity, cluster_id}],
            curve: [{frame_number (0-based cv2_pos), similarity}],  # all sampled frames
            embeddings: ndarray shape (N, 512),                      # parallel to curve
        }
    """
    from concurrent.futures import ThreadPoolExecutor
    from sklearn.cluster import KMeans

    clip_matrix = combined.get("clip_matrix")
    if clip_matrix is None:
        return {
            "candidates": [],
            "curve": [],
            "embeddings": np.zeros((0, 512), dtype=np.float32),
        }

    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    all_positions = np.arange(0, total_frames, stride, dtype=np.int64)

    # Sensor-guided: restrict to covered windows
    if csv_path is not None and Path(csv_path).exists():
        _, covered_set = find_sensor_triggers(csv_path, trigger_value, sensor_margin)
        positions = np.array(
            [p for p in all_positions if (int(p) + 1) in covered_set], dtype=np.int64
        )
    else:
        positions = all_positions

    if len(positions) == 0:
        return {
            "candidates": [],
            "curve": [],
            "embeddings": np.zeros((0, 512), dtype=np.float32),
        }

    if phase_cb:
        phase_cb("coarse", 0, len(positions))

    def read_batch(batch_positions):
        if len(batch_positions) == 0:
            return []
        vcap = cv2.VideoCapture(str(video_path))
        vcap.set(cv2.CAP_PROP_POS_FRAMES, int(batch_positions[0]))
        cur = int(batch_positions[0])
        frames = []
        try:
            for target in batch_positions:
                target = int(target)
                while cur < target:
                    vcap.grab()
                    cur += 1
                ret, frame = vcap.read()
                cur += 1
                frames.append(frame if ret else np.zeros((64, 64, 3), dtype=np.uint8))
        finally:
            vcap.release()
        return frames

    all_embs_chunks = []
    all_sims_chunks = []
    processed = 0

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(read_batch, positions[:batch_size])
        for batch_start in range(0, len(positions), batch_size):
            batch_pos = positions[batch_start: batch_start + batch_size]
            frames = future.result()
            next_start = batch_start + batch_size
            future = pool.submit(read_batch, positions[next_start: next_start + batch_size])
            embs = embed_frames_batch(frames)          # (B, 512)
            sims = (embs @ clip_matrix.T).max(axis=1) # (B,)
            n = len(batch_pos)
            all_embs_chunks.append(embs[:n])
            all_sims_chunks.append(sims[:n])
            processed += n
            if phase_cb:
                phase_cb("coarse", processed, len(positions))

    all_embs = np.vstack(all_embs_chunks) if all_embs_chunks else np.zeros((0, 512), dtype=np.float32)
    all_sims = np.concatenate(all_sims_chunks) if all_sims_chunks else np.array([], dtype=np.float32)

    curve = [
        {"frame_number": int(positions[i]), "similarity": float(all_sims[i])}
        for i in range(len(positions))
    ]

    # Filter above threshold
    mask = all_sims >= threshold
    filtered_pos = positions[mask]
    filtered_embs = all_embs[mask]
    filtered_sims = all_sims[mask]

    if len(filtered_pos) == 0:
        if phase_cb:
            phase_cb("done", 1, 1)
        return {"candidates": [], "curve": curve, "embeddings": all_embs}

    # Fewer frames than clusters: skip clustering, return all
    if len(filtered_pos) <= n_clusters:
        candidates = [
            {
                "frame_number": int(filtered_pos[i]) + 1,  # 1-based
                "similarity": float(filtered_sims[i]),
                "cluster_id": i,
            }
            for i in range(len(filtered_pos))
        ]
        if phase_cb:
            phase_cb("done", 1, 1)
        return {"candidates": candidates, "curve": curve, "embeddings": all_embs}

    if phase_cb:
        phase_cb("cluster", 0, 1)

    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
    km.fit(filtered_embs)
    labels = km.labels_
    centroids = km.cluster_centers_

    candidates = []
    for cid in range(n_clusters):
        idx_in_cluster = np.where(labels == cid)[0]
        if len(idx_in_cluster) == 0:
            continue
        cluster_embs = filtered_embs[idx_in_cluster]
        dists = np.linalg.norm(cluster_embs - centroids[cid], axis=1)
        nearest = idx_in_cluster[np.argsort(dists)[:2]]
        for j in nearest:
            candidates.append({
                "frame_number": int(filtered_pos[j]) + 1,  # 1-based
                "similarity": float(filtered_sims[j]),
                "cluster_id": int(cid),
            })

    candidates.sort(key=lambda c: c["frame_number"])

    if phase_cb:
        phase_cb("cluster", 1, 1)
        phase_cb("done", 1, 1)

    return {"candidates": candidates, "curve": curve, "embeddings": all_embs}


def scan_video_multi_template(
    video_path: Path | str,
    combined: dict,
    stride: int = 10,
    threshold: float = 0.70,
    min_spacing: int = 900,
    fine_window: int = 50,
    batch_size: int = 64,
    smooth_sigma: float = 3.0,
    progress_cb=None,
    phase_cb=None,
) -> list[dict]:
    """
    Full scan pipeline using multiple template embeddings (max similarity).
    combined: output of load_combined_template().
    Returns same format as scan_video(): [{cv2_pos, frame_number, similarity}, ...].
    """
    clip_matrix = combined.get("clip_matrix")
    dino_matrix = combined.get("dino_matrix")
    if clip_matrix is None:
        return []

    if phase_cb:
        phase_cb("coarse", 0, 1)

    frame_indices, similarities = get_similarity_curve_multi(
        video_path, clip_matrix,
        stride=stride, batch_size=batch_size,
        progress_cb=lambda c, t: phase_cb("coarse", c, t) if phase_cb else (progress_cb(c, t) if progress_cb else None),
    )

    if len(frame_indices) == 0:
        return []

    if phase_cb:
        phase_cb("peak_detection", 0, 1)
    smoothed = smooth_curve(similarities, sigma=smooth_sigma)
    coarse_peaks = find_peaks_in_curve(smoothed, frame_indices, threshold, min_spacing)

    detections = []
    if phase_cb:
        phase_cb("fine", 0, len(coarse_peaks))
    for i, cv2_pos in enumerate(coarse_peaks):
        best_pos, best_sim = fine_scan_multi(
            video_path, clip_matrix, cv2_pos,
            window=fine_window, dino_matrix=dino_matrix,
        )
        detections.append({
            "cv2_pos": best_pos,
            "frame_number": best_pos + 1,
            "similarity": round(best_sim, 4),
        })
        if phase_cb:
            phase_cb("fine", i + 1, len(coarse_peaks))

    return detections


def get_known_key_frames(clips_dir: Path | str) -> dict[int, str]:
    """
    Parse existing clip filenames to extract known key frames.
    Returns {key_frame_number (1-based): clip_stem}.
    Ignores DLC result files (those with 'DLC' anywhere in stem).
    Clip naming: {prefix}_{start}_{end}_{success|failure}.avi
    key_frame = start + 200 (1-based frame numbers).
    """
    clips_dir = Path(clips_dir)
    known = {}
    for p in clips_dir.glob("*.avi"):
        stem = p.stem
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
) -> "pd.DataFrame":
    """
    Slice rows from parent CSV where frame_number is in [start, end] inclusive.
    Appends a 1-based clip_frame column.
    frame_number values are 1-based as stored in the CSV.
    """
    import pandas as pd
    df = pd.read_csv(parent_csv_path)
    mask = (df["frame_number"] >= start_frame_number) & (
        df["frame_number"] <= end_frame_number
    )
    clip_df = df[mask].copy().reset_index(drop=True)
    clip_df["clip_frame"] = range(1, len(clip_df) + 1)
    return clip_df


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


def update_parent_csv_note(
    parent_csv_path: Path | str, frame_number: int, note: str
) -> None:
    """
    Write `note` into the note column of the row matching frame_number.
    All other rows and columns are unchanged. No rows are added or removed.
    Raises ValueError if frame_number is not found.
    """
    import pandas as pd
    df = pd.read_csv(parent_csv_path)
    matched = df["frame_number"] == frame_number
    if not matched.any():
        raise ValueError(f"frame_number {frame_number} not found in {parent_csv_path}")
    df["note"] = df["note"].fillna("")
    df.loc[matched, "note"] = note
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
    start/end are clamped to [1, total_frames].
    """
    from config import CLIP_PRE_FRAMES, CLIP_POST_FRAMES

    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    start_fn = max(1, key_frame_number - CLIP_PRE_FRAMES)           # 1-based, clamped
    end_fn = min(total_frames, key_frame_number + CLIP_POST_FRAMES - 1)  # 1-based, clamped

    stem = video_path.stem
    clip_stem = f"{stem}_{start_fn}_{end_fn}"
    avi_path = output_dir / f"{clip_stem}.avi"
    csv_path = output_dir / f"{clip_stem}.csv"

    extract_clip_video(video_path, cv2_start=start_fn - 1, cv2_end=end_fn - 1, output_path=avi_path)

    clip_df = build_clip_csv(parent_csv_path, start_fn, end_fn)
    clip_df.to_csv(csv_path, index=False)

    return {
        "avi_path": str(avi_path),
        "csv_path": str(csv_path),
        "start_frame_number": start_fn,
        "end_frame_number": end_fn,
    }

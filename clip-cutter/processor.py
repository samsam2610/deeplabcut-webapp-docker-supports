from __future__ import annotations

import base64
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

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
    path.parent.mkdir(parents=True, exist_ok=True)
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
        if p.stem.endswith("_success") or p.stem.endswith("_failure")
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
) -> tuple[np.ndarray, np.ndarray]:
    """
    Coarse scan: extract every `stride`th frame, embed, compute cosine similarity.
    Returns (frame_indices, similarities) as 1D numpy arrays (0-based cv2_pos).
    progress_cb(current, total) is called after each batch if provided.
    """
    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    all_positions = np.arange(0, total_frames, stride)
    similarities = np.zeros(len(all_positions), dtype=np.float32)

    for batch_start in range(0, len(all_positions), batch_size):
        batch_pos = all_positions[batch_start : batch_start + batch_size]
        frames = []
        for pos in batch_pos:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(pos))
            ret, frame = cap.read()
            frames.append(frame if ret else np.zeros((64, 64, 3), dtype=np.uint8))

        embs = embed_frames_batch(frames)
        sims = embs @ template_emb  # cosine similarity (both unit vectors)
        similarities[batch_start : batch_start + len(batch_pos)] = sims

        if progress_cb:
            progress_cb(batch_start + len(batch_pos), len(all_positions))

    cap.release()
    return all_positions, similarities


def fine_scan(
    video_path: Path | str,
    template_emb: np.ndarray,
    coarse_cv2_pos: int,
    window: int = 50,
) -> tuple[int, float]:
    """
    Scan ±window frames around coarse_cv2_pos at stride 1.
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

    embs = embed_frames_batch(frames)
    sims = embs @ template_emb
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
        exact_pos, fine_sim = fine_scan(video_path, template_emb, coarse_pos, window=fine_window)
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

from __future__ import annotations

import base64
import json
from pathlib import Path

import cv2
import numpy as np
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

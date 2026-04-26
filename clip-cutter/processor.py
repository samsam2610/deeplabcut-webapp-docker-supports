from __future__ import annotations

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

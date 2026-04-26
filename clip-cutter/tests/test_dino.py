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


def _make_synthetic_avi(path, n_frames=90, w=64, h=64, fps=30.0):
    import cv2 as _cv2
    writer = _cv2.VideoWriter(
        str(path), _cv2.VideoWriter_fourcc(*"XVID"), fps, (w, h)
    )
    rng = np.random.default_rng(7)
    for _ in range(n_frames):
        writer.write(rng.integers(0, 255, (h, w, 3), dtype=np.uint8))
    writer.release()


def test_fine_scan_uses_dino_when_emb_provided(tmp_path):
    avi = tmp_path / "test.avi"
    _make_synthetic_avi(avi, n_frames=90)

    rng = np.random.default_rng(99)
    dino_emb = rng.random(1024).astype(np.float32)
    dino_emb /= np.linalg.norm(dino_emb)

    pos, sim = processor.fine_scan(
        str(avi), template_emb=None, coarse_cv2_pos=45,
        window=20, dino_template_emb=dino_emb
    )
    assert 0 <= pos <= 89, f"position {pos} out of range"
    assert -1.0 <= sim <= 1.0, f"similarity {sim} out of [-1, 1]"


def test_fine_scan_falls_back_to_clip_when_no_dino_emb(tmp_path):
    avi = tmp_path / "test2.avi"
    _make_synthetic_avi(avi, n_frames=60)

    clip_emb = np.zeros(512, dtype=np.float32)
    clip_emb[0] = 1.0
    pos, sim = processor.fine_scan(
        str(avi), template_emb=clip_emb, coarse_cv2_pos=30,
        window=10, dino_template_emb=None
    )
    assert 0 <= pos <= 59

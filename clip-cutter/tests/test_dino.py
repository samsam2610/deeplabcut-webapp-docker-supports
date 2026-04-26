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

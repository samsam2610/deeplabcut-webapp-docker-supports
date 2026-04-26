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

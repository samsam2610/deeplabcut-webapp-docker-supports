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
    import base64
    frame = processor.read_frame(tiny_video, 0)
    thumb = processor.frame_to_thumbnail(frame)
    assert isinstance(thumb, str)
    # valid base64 JPEG
    data = base64.b64decode(thumb)
    assert data[:2] == b"\xff\xd8"  # JPEG magic bytes


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

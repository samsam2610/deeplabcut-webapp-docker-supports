import threading

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


def test_get_similarity_curve_shape(mock_model, tiny_video):
    import numpy as np
    rng = np.random.default_rng(0)
    template_emb = rng.random(512).astype(np.float32)
    template_emb /= np.linalg.norm(template_emb)
    frame_indices, sims = processor.get_similarity_curve(tiny_video, template_emb, stride=5)
    assert len(frame_indices) == len(sims)
    assert frame_indices[0] == 0
    assert sims.dtype == np.float32


def test_scan_video_returns_list(mock_model, tiny_video):
    import numpy as np
    rng = np.random.default_rng(0)
    template_emb = rng.random(512).astype(np.float32)
    template_emb /= np.linalg.norm(template_emb)
    # Use very low threshold so something is detected from random embeddings
    results = processor.scan_video(
        tiny_video, template_emb,
        stride=5, threshold=0.0, min_spacing=5, fine_window=2,
    )
    assert isinstance(results, list)
    for r in results:
        assert "cv2_pos" in r
        assert "frame_number" in r
        assert r["frame_number"] == r["cv2_pos"] + 1
        assert "similarity" in r


def test_extract_clip_video_creates_file(tiny_video, tmp_path):
    out = tmp_path / "clip.avi"
    processor.extract_clip_video(tiny_video, cv2_start=5, cv2_end=14, output_path=out)
    assert out.exists()
    import cv2 as _cv2
    cap = _cv2.VideoCapture(str(out))
    count = int(cap.get(_cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    assert count == 10  # frames 5..14 inclusive


def test_build_clip_csv_row_count(tiny_csv):
    df = processor.build_clip_csv(tiny_csv, start_frame_number=5, end_frame_number=14)
    assert len(df) == 10
    assert list(df.columns) == [
        "timestamp", "frame_number", "frame_line_status", "note", "clip_frame"
    ]
    assert df["clip_frame"].tolist() == list(range(1, 11))
    assert df["frame_number"].iloc[0] == 5


def test_update_parent_csv_note_writes_correctly(tiny_csv):
    import pandas as pd
    processor.update_parent_csv_note(tiny_csv, frame_number=10, note="start_reaching")
    df = pd.read_csv(tiny_csv, keep_default_na=False)
    row = df[df["frame_number"] == 10]
    assert row["note"].values[0] == "start_reaching"
    # All other rows untouched
    assert (df[df["frame_number"] != 10]["note"] == "").all()


def test_update_parent_csv_preserves_row_count(tiny_csv):
    import pandas as pd
    original_count = len(pd.read_csv(tiny_csv))
    processor.update_parent_csv_note(tiny_csv, frame_number=5, note="start_reaching")
    assert len(pd.read_csv(tiny_csv)) == original_count


def test_update_parent_csv_note_raises_on_missing_frame(tiny_csv):
    with pytest.raises(ValueError, match="frame_number 9999 not found"):
        processor.update_parent_csv_note(tiny_csv, frame_number=9999, note="oops")


def test_extract_clip_end_to_end(tiny_video, tiny_csv, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "CLIP_PRE_FRAMES", 5)
    monkeypatch.setattr(config, "CLIP_POST_FRAMES", 10)
    result = processor.extract_clip(tiny_video, tiny_csv, key_frame_number=20, output_dir=tmp_path)
    assert Path(result["avi_path"]).exists()
    assert Path(result["csv_path"]).exists()
    assert result["start_frame_number"] == 15  # 20 - 5
    assert result["end_frame_number"] == 29    # 20 + 10 - 1
    import pandas as pd
    clip_df = pd.read_csv(result["csv_path"])
    assert clip_df["clip_frame"].iloc[0] == 1
    assert len(clip_df) == 15  # frames 15..29 inclusive


def test_load_combined_template_empty_dirs(tmp_path):
    result = processor.load_combined_template([])
    assert result["clip_matrix"] is None
    assert result["dino_matrix"] is None


def test_load_combined_template_missing_state(tmp_path):
    # Directory exists but no template_state.json — should be skipped
    (tmp_path / "template").mkdir(parents=True)
    result = processor.load_combined_template([str(tmp_path)])
    assert result["clip_matrix"] is None


def test_load_combined_template_single_dir(tmp_path, mock_model):
    # Create a minimal template_state.json
    import json
    state = {
        "frames": [],
        "mean_embedding": [0.1] * 512,
        "dino_mean_embedding": [0.2] * 1024,
    }
    tpl_dir = tmp_path / "template"
    tpl_dir.mkdir()
    (tpl_dir / "template_state.json").write_text(json.dumps(state))
    result = processor.load_combined_template([str(tmp_path)])
    assert result["clip_matrix"].shape == (1, 512)
    assert result["dino_matrix"].shape == (1, 1024)


def test_load_combined_template_two_dirs(tmp_path, mock_model):
    import json
    for i in range(2):
        d = tmp_path / f"session{i}" / "template"
        d.mkdir(parents=True)
        state = {
            "frames": [],
            "mean_embedding": [float(i)] * 512,
            "dino_mean_embedding": [float(i)] * 1024,
        }
        (d / "template_state.json").write_text(json.dumps(state))
    dirs = [str(tmp_path / f"session{i}") for i in range(2)]
    result = processor.load_combined_template(dirs)
    assert result["clip_matrix"].shape == (2, 512)
    assert result["dino_matrix"].shape == (2, 1024)


def test_scan_video_multi_template_finds_detections(mock_model, tiny_video, tmp_path):
    """Multi-template scan returns detections list (may be empty for random embeddings)."""
    import json
    rng = np.random.default_rng(0)
    state = {
        "frames": [],
        "mean_embedding": rng.random(512).tolist(),
        "dino_mean_embedding": rng.random(1024).tolist(),
    }
    tpl_dir = tmp_path / "template"
    tpl_dir.mkdir()
    (tpl_dir / "template_state.json").write_text(json.dumps(state))
    combined = processor.load_combined_template([str(tmp_path)])
    detections = processor.scan_video_multi_template(
        tiny_video, combined,
        stride=5, threshold=0.0, min_spacing=1, fine_window=2, batch_size=10,
    )
    assert isinstance(detections, list)
    for d in detections:
        assert "frame_number" in d
        assert "similarity" in d


def test_scan_video_sensor_guided_multi_no_csv_raises(mock_model, tiny_video, tmp_path):
    """CSV path that doesn't exist should propagate as FileNotFoundError."""
    import processor
    rng = np.random.default_rng(0)
    clip_matrix = rng.random((2, 512)).astype(np.float32)
    clip_matrix /= np.linalg.norm(clip_matrix, axis=1, keepdims=True)
    combined = {"clip_matrix": clip_matrix, "dino_matrix": None}

    import pytest
    with pytest.raises((FileNotFoundError, Exception)):
        processor.scan_video_sensor_guided_multi(
            tiny_video, combined,
            csv_path=tmp_path / "missing.csv",
            trigger_value=14, sensor_margin=2,
            stride=2, threshold=0.0, min_spacing=10, fine_window=2,
        )


def test_scan_video_sensor_guided_multi_returns_list(mock_model, tiny_video, tmp_path):
    """With a well-formed CSV, returns a list (possibly empty)."""
    import csv, processor
    csv_path = tmp_path / "sensor.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame_number", "frame_line_status"])
        for i in range(1, 21):
            w.writerow([i, 14 if i in (5, 10) else 0])

    rng = np.random.default_rng(0)
    clip_matrix = rng.random((2, 512)).astype(np.float32)
    clip_matrix /= np.linalg.norm(clip_matrix, axis=1, keepdims=True)
    combined = {"clip_matrix": clip_matrix, "dino_matrix": None}

    results = processor.scan_video_sensor_guided_multi(
        tiny_video, combined,
        csv_path=csv_path,
        trigger_value=14, sensor_margin=2,
        stride=2, threshold=0.0, min_spacing=10, fine_window=2,
    )
    assert isinstance(results, list)
    for r in results:
        assert "frame_number" in r
        assert "similarity" in r
        assert "source" in r


def test_find_template_candidates_empty_video_returns_empty(mock_model, tmp_path):
    """Video that produces no frames above threshold returns empty candidates."""
    import processor
    rng = np.random.default_rng(0)
    clip_matrix = rng.random((2, 512)).astype(np.float32)
    clip_matrix /= np.linalg.norm(clip_matrix, axis=1, keepdims=True)
    combined = {"clip_matrix": clip_matrix, "dino_matrix": None}

    # Create a 1-frame video using OpenCV
    import cv2
    vpath = tmp_path / "tiny.avi"
    out = cv2.VideoWriter(str(vpath), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    out.write(np.zeros((48, 64, 3), dtype=np.uint8))
    out.release()

    result = processor.find_template_candidates(
        vpath, combined, n_clusters=3, threshold=0.99, stride=1
    )
    assert "candidates" in result
    assert "curve" in result
    assert "embeddings" in result
    assert isinstance(result["candidates"], list)


def test_find_template_candidates_fewer_than_clusters(mock_model, tiny_video):
    """When fewer above-threshold frames than clusters, all are returned without clustering."""
    import processor
    rng = np.random.default_rng(42)
    clip_matrix = rng.random((1, 512)).astype(np.float32)
    clip_matrix /= np.linalg.norm(clip_matrix, axis=1, keepdims=True)
    combined = {"clip_matrix": clip_matrix, "dino_matrix": None}

    result = processor.find_template_candidates(
        tiny_video, combined, n_clusters=100, threshold=0.0, stride=1
    )
    assert isinstance(result["candidates"], list)
    # All frames returned as candidates (skip clustering)
    assert len(result["candidates"]) == len(result["curve"])


def test_find_template_candidates_clustering(mock_model, tiny_video):
    """With enough frames, clustering runs and returns at most 2*n_clusters candidates."""
    import processor
    rng = np.random.default_rng(7)
    clip_matrix = rng.random((2, 512)).astype(np.float32)
    clip_matrix /= np.linalg.norm(clip_matrix, axis=1, keepdims=True)
    combined = {"clip_matrix": clip_matrix, "dino_matrix": None}

    result = processor.find_template_candidates(
        tiny_video, combined, n_clusters=2, threshold=0.0, stride=1
    )
    assert len(result["candidates"]) <= 4  # 2 clusters × 2 nearest each
    for c in result["candidates"]:
        assert "frame_number" in c
        assert "similarity" in c
        assert "cluster_id" in c


@pytest.fixture
def mock_dino_cuda1(monkeypatch):
    """Replace the CUDA:1 DINOv2 singleton with a deterministic fake."""
    import processor
    import numpy as np

    class FakeDinoModel:
        def __call__(self, tensors):
            import torch
            N = tensors.shape[0]
            rng = np.random.default_rng(0)
            arr = rng.random((N, 1024)).astype(np.float32)
            norms = np.linalg.norm(arr, axis=1, keepdims=True).clip(min=1e-8)
            arr = arr / norms
            return torch.tensor(arr)

        def parameters(self):
            import torch
            yield torch.tensor([0.0])  # device = cpu

        def to(self, device):
            return self

    import torchvision.transforms as T
    fake_transform = T.Compose([T.Resize(8), T.CenterCrop(8), T.ToTensor()])
    monkeypatch.setattr(processor, "_dino_model_cuda1", FakeDinoModel())
    monkeypatch.setattr(processor, "_dino_transform_cuda1", fake_transform)
    return FakeDinoModel()


def test_rescan_forward_candidates_returns_results(mock_dino_cuda1, tiny_video):
    """Returns one result per candidate with valid frame_number and similarity."""
    import processor
    import numpy as np

    template_state = {
        "dino_mean_embedding": np.ones(1024, dtype=np.float32).tolist(),
        "mean_embedding": None,
        "frames": [],
    }
    candidates = [
        {"idx": 3, "frame_number": 20},
        {"idx": 4, "frame_number": 30},
    ]
    results = processor.rescan_forward_candidates(
        video_path=str(tiny_video),
        candidates=candidates,
        fine_window=5,
        template_state=template_state,
    )
    assert len(results) == 2
    for r in results:
        assert "idx" in r
        assert "new_frame_number" in r
        assert "similarity" in r
        assert isinstance(r["new_frame_number"], int)
        assert r["new_frame_number"] >= 1
        assert 0.0 <= r["similarity"] <= 1.0


def test_rescan_forward_candidates_respects_cancel(mock_dino_cuda1, tiny_video):
    """Cancel event set before processing causes empty result."""
    import processor
    import numpy as np

    template_state = {
        "dino_mean_embedding": np.ones(1024, dtype=np.float32).tolist(),
        "mean_embedding": None,
        "frames": [],
    }
    candidates = [{"idx": 3, "frame_number": 20}]
    cancel_ev = threading.Event()
    cancel_ev.set()  # set before call
    results = processor.rescan_forward_candidates(
        video_path=str(tiny_video),
        candidates=candidates,
        fine_window=5,
        template_state=template_state,
        cancel_event=cancel_ev,
    )
    assert results == []


def test_rescan_forward_candidates_empty_template(mock_dino_cuda1, tiny_video):
    """Returns empty list when template has no mean embedding."""
    import processor

    template_state = {"dino_mean_embedding": None, "mean_embedding": None, "frames": []}
    candidates = [{"idx": 0, "frame_number": 10}]
    results = processor.rescan_forward_candidates(
        video_path=str(tiny_video),
        candidates=candidates,
        fine_window=5,
        template_state=template_state,
    )
    assert results == []


def test_rescan_forward_candidates_idx_preserved(mock_dino_cuda1, tiny_video):
    """Result idx values match the input candidate idx values."""
    import processor
    import numpy as np

    template_state = {
        "dino_mean_embedding": np.ones(1024, dtype=np.float32).tolist(),
        "mean_embedding": None,
        "frames": [],
    }
    candidates = [{"idx": 7, "frame_number": 15}, {"idx": 12, "frame_number": 25}]
    results = processor.rescan_forward_candidates(
        video_path=str(tiny_video),
        candidates=candidates,
        fine_window=3,
        template_state=template_state,
    )
    result_idxs = [r["idx"] for r in results]
    assert 7 in result_idxs
    assert 12 in result_idxs

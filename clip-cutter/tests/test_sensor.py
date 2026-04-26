"""Backend tests for sensor-trigger parsing."""
import cv2
import numpy as np
import pandas as pd
import pytest
import processor


def _make_csv(tmp_path, trigger_frames, total=100, trigger_value=14):
    data = {
        "frame_number": list(range(1, total + 1)),
        "frame_line_status": [
            trigger_value if i in trigger_frames else 0
            for i in range(1, total + 1)
        ],
    }
    path = tmp_path / "test.csv"
    pd.DataFrame(data).to_csv(path, index=False)
    return path


def test_find_sensor_triggers_single_burst(tmp_path):
    """Frames 41-50 triggered, margin=5 → one rising edge at frame 36."""
    csv = _make_csv(tmp_path, set(range(41, 51)))
    rising, covered = processor.find_sensor_triggers(csv, trigger_value=14, sensor_margin=5)
    # dilated: 41-5=36 to 50+5=55
    assert rising == [36]
    assert 36 in covered
    assert 55 in covered
    assert 35 not in covered
    assert 56 not in covered


def test_find_sensor_triggers_closes_intra_burst_gap(tmp_path):
    """Two bursts with a 4-frame gap, margin=3 → merged into one rising edge."""
    # Burst1: 10-14, Burst2: 19-23  (gap: 15-18, 4 frames)
    triggered = set(range(10, 15)) | set(range(19, 24))
    csv = _make_csv(tmp_path, triggered, total=50)
    rising, covered = processor.find_sensor_triggers(csv, trigger_value=14, sensor_margin=3)
    # Burst1 dilated: 7-17, Burst2 dilated: 16-26 → overlap at 16-17 → merged 7-26
    assert len(rising) == 1
    assert rising[0] == 7


def test_find_sensor_triggers_two_separate_bursts(tmp_path):
    """Two bursts far apart → two rising edges."""
    triggered = set(range(10, 15)) | set(range(40, 45))
    csv = _make_csv(tmp_path, triggered, total=60)
    rising, covered = processor.find_sensor_triggers(csv, trigger_value=14, sensor_margin=3)
    # Burst1 dilated: 7-17, Burst2 dilated: 37-47. No overlap.
    assert len(rising) == 2
    assert rising[0] < rising[1]


def test_find_sensor_triggers_empty_no_triggers(tmp_path):
    """No sensor triggers → empty results."""
    csv = _make_csv(tmp_path, set())
    rising, covered = processor.find_sensor_triggers(csv, trigger_value=14, sensor_margin=5)
    assert rising == []
    assert covered == set()


def test_find_sensor_triggers_custom_trigger_value(tmp_path):
    """Custom trigger_value=7 is respected."""
    data = {
        "frame_number": list(range(1, 21)),
        "frame_line_status": [7 if i in range(8, 13) else 0 for i in range(1, 21)],
    }
    csv = tmp_path / "t.csv"
    pd.DataFrame(data).to_csv(csv, index=False)
    rising, covered = processor.find_sensor_triggers(csv, trigger_value=7, sensor_margin=2)
    # triggered: 8-12 (indices 7-11). dilated ±2: indices 5-13 → frames 6-14
    assert len(rising) == 1
    assert rising[0] == 6


def test_find_sensor_triggers_empty_csv_rows(tmp_path):
    """CSV with no data rows returns empty results without crashing."""
    csv = tmp_path / "empty.csv"
    pd.DataFrame({"frame_number": [], "frame_line_status": []}).to_csv(csv, index=False)
    rising, covered = processor.find_sensor_triggers(csv, trigger_value=14, sensor_margin=5)
    assert rising == []
    assert covered == set()


@pytest.fixture
def small_avi(tmp_path):
    """20-frame 64×64 AVI with distinct blue channel per frame."""
    path = tmp_path / "small.avi"
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 64))
    for i in range(20):
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        frame[:, :, 0] = i * 12
        out.write(frame)
    out.release()
    return path


def test_get_similarity_curve_positions_kwarg_matches_stride(small_avi):
    """positions kwarg returns same indices/sims as stride-based scan."""
    import numpy as np
    template = np.ones(512, dtype=np.float32)
    template /= np.linalg.norm(template)

    # stride-based (original behaviour)
    idx_s, sim_s = processor.get_similarity_curve(small_avi, template, stride=5, batch_size=4)

    # explicit positions (should be identical)
    explicit = np.arange(0, 20, 5)
    idx_p, sim_p = processor.get_similarity_curve(
        small_avi, template, stride=5, batch_size=4, positions=explicit
    )

    np.testing.assert_array_equal(idx_s, idx_p)
    np.testing.assert_allclose(sim_s, sim_p, atol=1e-5)


def test_scan_video_sensor_guided_excludes_covered_frames(tmp_path, monkeypatch):
    """Gap CLIP scan skips frames covered by sensor bursts."""
    # 30-frame AVI
    avi = tmp_path / "v.avi"
    out = cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 64))
    for _ in range(30):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    # Triggered: frames 11-20; margin=2 → covered: frames 9-22
    data = {
        "frame_number": list(range(1, 31)),
        "frame_line_status": [14 if 11 <= i <= 20 else 0 for i in range(1, 31)],
    }
    csv = tmp_path / "v.csv"
    pd.DataFrame(data).to_csv(csv, index=False)

    captured = {}

    def mock_gsc(vp, temb, stride=10, batch_size=256, progress_cb=None, positions=None):
        captured["positions"] = list(positions) if positions is not None else None
        return np.array([], dtype=np.int64), np.array([], dtype=np.float32)

    monkeypatch.setattr(processor, "get_similarity_curve", mock_gsc)
    monkeypatch.setattr(processor, "fine_scan", lambda v, t, pos, window=50: (pos, 0.85))

    template = np.ones(512, dtype=np.float32)
    template /= np.linalg.norm(template)

    processor.scan_video_sensor_guided(
        avi, csv, template, trigger_value=14, sensor_margin=2, stride=5, threshold=0.70
    )

    # stride=5, total=30 → positions 0,5,10,15,20,25
    # covered (1-based): 9..22 → via margin=2 on frames 11-20
    # gap positions (pos+1 not in covered_set):
    #   pos=0 → fr1: ok; pos=5 → fr6: ok; pos=10 → fr11: covered;
    #   pos=15 → fr16: covered; pos=20 → fr21: covered; pos=25 → fr26: ok
    assert captured["positions"] is not None
    assert set(captured["positions"]) == {0, 5, 25}


def test_scan_video_sensor_guided_sensor_source_tag(tmp_path, monkeypatch):
    """Sensor candidate with fine_sim >= threshold gets source='sensor+clip'."""
    avi = tmp_path / "v.avi"
    out = cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 64))
    for _ in range(30):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    data = {
        "frame_number": list(range(1, 31)),
        "frame_line_status": [14 if i == 15 else 0 for i in range(1, 31)],
    }
    csv = tmp_path / "v.csv"
    pd.DataFrame(data).to_csv(csv, index=False)

    monkeypatch.setattr(
        processor, "get_similarity_curve",
        lambda *a, **kw: (np.array([], dtype=np.int64), np.array([], dtype=np.float32)),
    )
    monkeypatch.setattr(processor, "fine_scan", lambda v, t, pos, window=50: (pos, 0.85))

    template = np.ones(512, dtype=np.float32)
    template /= np.linalg.norm(template)

    results = processor.scan_video_sensor_guided(
        avi, csv, template, trigger_value=14, sensor_margin=0, threshold=0.70
    )
    assert len(results) == 1
    assert results[0]["source"] == "sensor+clip"
    assert results[0]["frame_number"] == results[0]["cv2_pos"] + 1


def test_scan_video_sensor_guided_low_sim_sensor_only(tmp_path, monkeypatch):
    """Sensor candidate with fine_sim < threshold gets source='sensor_only'."""
    avi = tmp_path / "v.avi"
    out = cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 64))
    for _ in range(30):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    data = {
        "frame_number": list(range(1, 31)),
        "frame_line_status": [14 if i == 15 else 0 for i in range(1, 31)],
    }
    csv = tmp_path / "v.csv"
    pd.DataFrame(data).to_csv(csv, index=False)

    monkeypatch.setattr(
        processor, "get_similarity_curve",
        lambda *a, **kw: (np.array([], dtype=np.int64), np.array([], dtype=np.float32)),
    )
    monkeypatch.setattr(processor, "fine_scan", lambda v, t, pos, window=50: (pos, 0.50))

    template = np.ones(512, dtype=np.float32)
    template /= np.linalg.norm(template)

    results = processor.scan_video_sensor_guided(
        avi, csv, template, trigger_value=14, sensor_margin=0, threshold=0.70
    )
    assert len(results) == 1
    assert results[0]["source"] == "sensor_only"


def test_scan_video_sensor_guided_clip_only_source(tmp_path, monkeypatch):
    """CLIP gap peak with no nearby sensor gets source='clip_only'."""
    avi = tmp_path / "v.avi"
    out = cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 64))
    for _ in range(30):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    # No triggers at all
    data = {
        "frame_number": list(range(1, 31)),
        "frame_line_status": [0] * 30,
    }
    csv = tmp_path / "v.csv"
    pd.DataFrame(data).to_csv(csv, index=False)

    # One CLIP gap peak at position 10
    monkeypatch.setattr(
        processor, "get_similarity_curve",
        lambda *a, **kw: (np.array([10], dtype=np.int64), np.array([0.80], dtype=np.float32)),
    )
    monkeypatch.setattr(processor, "smooth_curve", lambda arr, sigma=3.0: arr)
    monkeypatch.setattr(processor, "find_peaks_in_curve", lambda s, fi, th, ms: [10])
    monkeypatch.setattr(processor, "fine_scan", lambda v, t, pos, window=50: (pos, 0.80))

    template = np.ones(512, dtype=np.float32)
    template /= np.linalg.norm(template)

    results = processor.scan_video_sensor_guided(
        avi, csv, template, trigger_value=14, sensor_margin=0, threshold=0.70
    )
    assert len(results) == 1
    assert results[0]["source"] == "clip_only"


def test_scan_video_sensor_guided_dedup_sensor_wins(tmp_path, monkeypatch):
    """When sensor and CLIP peak are within min_spacing//2, sensor candidate wins."""
    avi = tmp_path / "v.avi"
    out = cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 64))
    for _ in range(30):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    # Sensor at frame 15 (cv2_pos=14); CLIP peak at cv2_pos=16 — within min_spacing//2=10
    data = {
        "frame_number": list(range(1, 31)),
        "frame_line_status": [14 if i == 15 else 0 for i in range(1, 31)],
    }
    csv = tmp_path / "v.csv"
    pd.DataFrame(data).to_csv(csv, index=False)

    monkeypatch.setattr(
        processor, "get_similarity_curve",
        lambda *a, **kw: (np.array([16], dtype=np.int64), np.array([0.80], dtype=np.float32)),
    )
    monkeypatch.setattr(processor, "smooth_curve", lambda arr, sigma=3.0: arr)
    monkeypatch.setattr(processor, "find_peaks_in_curve", lambda s, fi, th, ms: [16])
    monkeypatch.setattr(processor, "fine_scan", lambda v, t, pos, window=50: (pos, 0.85))

    template = np.ones(512, dtype=np.float32)
    template /= np.linalg.norm(template)

    results = processor.scan_video_sensor_guided(
        avi, csv, template,
        trigger_value=14, sensor_margin=0, threshold=0.70, min_spacing=20
    )
    # Should be 1 result (deduped), sourced from sensor
    assert len(results) == 1
    assert results[0]["source"] == "sensor+clip"
    assert results[0]["cv2_pos"] == 14  # sensor pos wins


def test_scan_video_sensor_guided_two_close_sensors_both_kept(tmp_path, monkeypatch):
    """Two sensor triggers within min_spacing//2 are BOTH kept (sensor is authoritative)."""
    avi = tmp_path / "v.avi"
    out = cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 64))
    for _ in range(30):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    # Two sensor triggers: frames 5 and 10 (cv2_pos 4 and 9), within min_spacing//2=10
    data = {
        "frame_number": list(range(1, 31)),
        "frame_line_status": [14 if i in (5, 10) else 0 for i in range(1, 31)],
    }
    csv = tmp_path / "v.csv"
    pd.DataFrame(data).to_csv(csv, index=False)

    monkeypatch.setattr(
        processor, "get_similarity_curve",
        lambda *a, **kw: (np.array([], dtype=np.int64), np.array([], dtype=np.float32)),
    )
    monkeypatch.setattr(processor, "fine_scan", lambda v, t, pos, window=50: (pos, 0.85))

    template = np.ones(512, dtype=np.float32)
    template /= np.linalg.norm(template)

    results = processor.scan_video_sensor_guided(
        avi, csv, template,
        trigger_value=14, sensor_margin=0, threshold=0.70, min_spacing=20
    )
    # Both sensor events should be kept
    assert len(results) == 2
    cv2_positions = {r["cv2_pos"] for r in results}
    assert 4 in cv2_positions   # frame 5 → cv2_pos 4
    assert 9 in cv2_positions   # frame 10 → cv2_pos 9
    for r in results:
        assert r["source"] == "sensor+clip"

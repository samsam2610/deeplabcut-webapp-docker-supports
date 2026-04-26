"""Backend tests for sensor-trigger parsing."""
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

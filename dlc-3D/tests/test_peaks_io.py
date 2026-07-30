import json
from pathlib import Path

import numpy as np
import pytest

from dlc_3d_bp import peaks_io as pio


def _sample(frames, bodyparts=("nose", "wrist"), k=3, fill=1.0):
    n, b = len(frames), len(bodyparts)
    xy = np.full((n, b, k, 2), np.nan, np.float32)
    score = np.zeros((n, b, k), np.float32)
    xy[:, :, 0, :] = fill
    score[:, :, 0] = fill
    return {
        "frames": np.asarray(frames, np.int32),
        "xy": xy,
        "score": score,
        "bodyparts": list(bodyparts),
        "meta": {"k": k, "min_distance": 3, "snapshot": "snap.pt",
                 "stride": 2.0, "locref_std": 7.2801},
    }


def test_sidecar_path_sits_beside_the_pose_h5():
    p = pio.peaks_sidecar_path("/data/vidDLC_resnet50_x.h5")
    assert p == Path("/data/vidDLC_resnet50_x_peaks.npz")


def test_round_trip_preserves_values_dtypes_and_meta(tmp_path):
    s = _sample([0, 5, 9])
    dst = tmp_path / "a_peaks.npz"
    pio.write_peaks_npz(dst, s["frames"], s["xy"], s["score"],
                        s["bodyparts"], s["meta"])
    got = pio.read_peaks_npz(dst)
    assert got["frames"].dtype == np.int32
    assert got["xy"].dtype == np.float32
    assert got["score"].dtype == np.float32
    np.testing.assert_array_equal(got["frames"], s["frames"])
    np.testing.assert_allclose(got["xy"], s["xy"], equal_nan=True)
    assert got["bodyparts"] == ["nose", "wrist"]
    assert got["meta"]["locref_std"] == pytest.approx(7.2801)


def test_write_sorts_frames_and_reorders_the_arrays_with_them(tmp_path):
    s = _sample([7, 1, 4])
    s["xy"][:, 0, 0, 0] = [70.0, 10.0, 40.0]
    dst = tmp_path / "b_peaks.npz"
    pio.write_peaks_npz(dst, s["frames"], s["xy"], s["score"],
                        s["bodyparts"], s["meta"])
    got = pio.read_peaks_npz(dst)
    np.testing.assert_array_equal(got["frames"], [1, 4, 7])
    np.testing.assert_allclose(got["xy"][:, 0, 0, 0], [10.0, 40.0, 70.0])


def test_write_rejects_duplicate_frames(tmp_path):
    s = _sample([3, 3])
    with pytest.raises(ValueError, match="duplicate"):
        pio.write_peaks_npz(tmp_path / "c_peaks.npz", s["frames"], s["xy"],
                            s["score"], s["bodyparts"], s["meta"])


def test_merge_unions_disjoint_frames_in_sorted_order():
    old, new = _sample([0, 2], fill=1.0), _sample([1, 3], fill=2.0)
    out = pio.merge_peaks(old, new)
    np.testing.assert_array_equal(out["frames"], [0, 1, 2, 3])
    np.testing.assert_allclose(out["xy"][:, 0, 0, 0], [1.0, 2.0, 1.0, 2.0])


def test_merge_prefers_the_new_run_on_overlapping_frames():
    old, new = _sample([0, 1, 2], fill=1.0), _sample([1], fill=9.0)
    out = pio.merge_peaks(old, new)
    np.testing.assert_array_equal(out["frames"], [0, 1, 2])
    np.testing.assert_allclose(out["xy"][:, 0, 0, 0], [1.0, 9.0, 1.0])


def test_merge_rejects_a_bodypart_mismatch():
    old = _sample([0], bodyparts=("nose", "wrist"))
    new = _sample([1], bodyparts=("nose", "elbow"))
    with pytest.raises(ValueError, match="bodypart"):
        pio.merge_peaks(old, new)


def test_merge_rejects_a_k_mismatch():
    old, new = _sample([0], k=3), _sample([1], k=5)
    with pytest.raises(ValueError, match="k"):
        pio.merge_peaks(old, new)


def test_merge_keeps_the_new_runs_meta():
    old, new = _sample([0]), _sample([1])
    new["meta"]["snapshot"] = "snapshot-best-999.pt"
    assert pio.merge_peaks(old, new)["meta"]["snapshot"] == "snapshot-best-999.pt"

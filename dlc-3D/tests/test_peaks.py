import numpy as np
import pytest

from dlc_3d_bp.peaks import extract_peaks


def _blob(hm, cx, cy, amp, sigma=1.2):
    """Add a small Gaussian blob centred on (cx, cy)."""
    h, w = hm.shape
    ys, xs = np.mgrid[0:h, 0:w]
    hm += amp * np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sigma ** 2)))
    return hm


def test_single_blob_gives_one_peak_at_its_centre():
    hm = _blob(np.zeros((40, 40), np.float32), 12, 25, 1.0)
    xy, sc = extract_peaks(hm, k=5, min_distance=3)
    assert xy.shape == (5, 2) and sc.shape == (5,)
    assert np.allclose(xy[0], [12, 25], atol=1.0)
    assert sc[0] > 0.9
    assert np.isnan(xy[1:]).all(), "one blob must not yield five peaks"
    assert (sc[1:] == 0).all()


def test_adjacent_cells_of_one_blob_are_suppressed():
    """The regression this exists for: without NMS, top-K returns the peak cell
    and its neighbours, so K distinct candidates would be one detection."""
    hm = _blob(np.zeros((40, 40), np.float32), 20, 20, 1.0, sigma=2.5)
    xy, sc = extract_peaks(hm, k=5, min_distance=3)
    found = xy[~np.isnan(xy[:, 0])]
    assert len(found) == 1, "a single wide blob must yield exactly one peak"


def test_two_separated_blobs_give_two_peaks_ordered_by_score():
    hm = np.zeros((40, 40), np.float32)
    _blob(hm, 8, 8, 0.6)
    _blob(hm, 30, 30, 0.95)
    xy, sc = extract_peaks(hm, k=5, min_distance=3)
    assert np.allclose(xy[0], [30, 30], atol=1.0), "highest score first"
    assert np.allclose(xy[1], [8, 8], atol=1.0)
    assert sc[0] > sc[1] > 0
    assert np.isnan(xy[2:]).all()


def test_k_limits_the_number_returned():
    hm = np.zeros((60, 60), np.float32)
    for i, (cx, cy) in enumerate([(5, 5), (20, 5), (35, 5), (50, 5), (5, 25), (20, 25)]):
        _blob(hm, cx, cy, 0.9 - 0.05 * i)
    xy, sc = extract_peaks(hm, k=3, min_distance=3)
    assert xy.shape == (3, 2)
    assert not np.isnan(xy).any(), "three of six blobs must be returned"
    assert sc[0] >= sc[1] >= sc[2]


def test_flat_heatmap_yields_nothing():
    xy, sc = extract_peaks(np.zeros((20, 20), np.float32), k=5, min_distance=3)
    assert np.isnan(xy).all()
    assert (sc == 0).all()


def test_scores_are_always_descending_and_padding_is_zero():
    rng = np.random.default_rng(0)
    hm = rng.random((50, 50)).astype(np.float32) * 0.2
    _blob(hm, 10, 10, 1.0)
    _blob(hm, 40, 40, 0.8)
    xy, sc = extract_peaks(hm, k=5, min_distance=4)
    real = sc[sc > 0]
    assert np.all(np.diff(real) <= 0)
    assert np.isnan(xy[len(real):]).all()


from dlc_3d_bp.peaks import heatmap_to_image


def test_heatmap_to_image_applies_stride_then_undoes_pad_and_scale():
    """A peak at heatmap cell (10, 5) with stride 8, 20px x-pad and a 0.5
    resize maps to ((10*8 + 8/2) - 20) / 0.5 in x."""
    xy = np.array([[10.0, 5.0]], dtype=np.float32)
    got = heatmap_to_image(xy, stride=8, pad_xy=(20, 0), scale_xy=(0.5, 0.5))
    assert got.shape == (1, 2)
    assert got[0, 0] == pytest.approx(((10 * 8 + 4) - 20) / 0.5)
    assert got[0, 1] == pytest.approx(((5 * 8 + 4) - 0) / 0.5)


def test_heatmap_to_image_is_identity_for_stride_1_no_pad_no_scale():
    xy = np.array([[3.0, 7.0]], dtype=np.float32)
    got = heatmap_to_image(xy, stride=1, pad_xy=(0, 0), scale_xy=(1.0, 1.0))
    assert got[0] == pytest.approx([3.5, 7.5])


def test_heatmap_to_image_propagates_nan_padding():
    xy = np.array([[1.0, 2.0], [np.nan, np.nan]], dtype=np.float32)
    got = heatmap_to_image(xy, stride=8, pad_xy=(0, 0), scale_xy=(1.0, 1.0))
    assert np.isfinite(got[0]).all()
    assert np.isnan(got[1]).all()

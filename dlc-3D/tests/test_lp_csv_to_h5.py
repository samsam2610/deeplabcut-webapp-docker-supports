"""Tests for the LP CSV → H5 sidecar emit step."""
from pathlib import Path
import csv

import pytest

# Skip the whole module if pytables isn't importable on the host. importorskip
# only catches ImportError; a stale install can raise ValueError on numpy
# binary-incompatibility, so we catch broadly and skip.
try:
    import tables  # noqa: F401
except Exception as _e:
    pytest.skip(f"pytables unavailable on host: {_e}", allow_module_level=True)
import pandas as pd

from dlc_3d_bp.lp.predict_runner import (
    csv_to_h5,
    emit_h5_sidecars,
    _is_lp_prediction_csv,
)


def _write_lp_csv(path: Path, n_frames: int = 5) -> None:
    """Write a tiny LP-format predictions CSV with a 3-row MultiIndex header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scorer"]    + ["lpmodel"] * 6)
        w.writerow(["bodyparts"] + ["kp1"] * 3 + ["kp2"] * 3)
        w.writerow(["coords"]    + ["x", "y", "likelihood"] * 2)
        for i in range(n_frames):
            w.writerow([f"img{i:08d}.png",
                        100 + i, 200 + i, 0.95,
                        300 - i, 150 + i, 0.9])


def test_is_lp_prediction_csv():
    assert _is_lp_prediction_csv(Path("/x/clip_lp.csv")) is True
    assert _is_lp_prediction_csv(Path("/x/clip_lp_pixel_error.csv")) is False
    assert _is_lp_prediction_csv(Path("/x/clip_lp_temporal_norm.csv")) is False
    assert _is_lp_prediction_csv(Path("/x/clip.csv")) is False
    assert _is_lp_prediction_csv(Path("/x/clip_lp.h5")) is False


def test_csv_to_h5_round_trip(tmp_path):
    csv_p = tmp_path / "v" / "clip_lp.csv"
    _write_lp_csv(csv_p, n_frames=4)
    h5_p = csv_to_h5(csv_p)
    assert h5_p == csv_p.with_suffix(".h5")
    assert h5_p.is_file()
    df = pd.read_hdf(str(h5_p), key="df_with_missing")
    assert len(df) == 4
    # MultiIndex columns survive the round-trip
    assert df.columns.nlevels == 3


def test_emit_h5_sidecars_filters_metric_csvs(tmp_path):
    d = tmp_path / "out"; d.mkdir()
    pred  = d / "clip_lp.csv";              _write_lp_csv(pred)
    metric = d / "clip_lp_pixel_error.csv"; _write_lp_csv(metric)
    not_lp = d / "clip.csv";                _write_lp_csv(not_lp)

    result = emit_h5_sidecars([pred, metric, not_lp])
    assert str(pred.with_suffix(".h5")) in result["emitted"]
    assert not (metric.with_suffix(".h5")).exists()
    assert not (not_lp.with_suffix(".h5")).exists()
    assert any("clip_lp_pixel_error.csv" in s for s in result["skipped"])
    assert any("clip.csv" in s for s in result["skipped"])

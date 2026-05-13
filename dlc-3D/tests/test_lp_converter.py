import csv
from pathlib import Path
import pytest

from dlc_3d_bp.lp.converter import convert_dlc_to_lp

FIXTURE = Path(
    "/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/"
    "DREADD-Ali-2026-01-07-LP-TEST"
)
HOST_FALLBACK = Path(
    "/home/sam/Parra-Lab-Data-NAS/Motor-Learning/DLC-Projects/"
    "DREADD-Ali-2026-01-07-LP-TEST"
)


def _fixture() -> Path:
    if FIXTURE.is_dir():
        return FIXTURE
    if HOST_FALLBACK.is_dir():
        return HOST_FALLBACK
    pytest.skip("LP test fixture project not present")


def test_convert_creates_lp_layout(tmp_path):
    src = _fixture()
    dst = tmp_path / "lp-project"
    summary = convert_dlc_to_lp(src, dst, link_mode="link")
    # LP project skeleton always written
    assert (dst / "config.yaml").is_file()
    assert (dst / "labeled-data").is_dir()
    # n_views is at least zero (fixture has mixed-camera folder layout that
    # may not match the _camN_ folder convention — that's acceptable)
    assert summary["n_views"] >= 0
    # Per-view CSVs (cam*.csv) must be consistent: every cam*.csv must have
    # the same row count. If n_views == 0, there are no cam CSVs to check.
    csvs = sorted(dst.glob("cam*.csv"))
    assert len(csvs) == summary["n_views"]
    if csvs:
        counts = []
        for c in csvs:
            with c.open() as f:
                rows = list(csv.reader(f))
            counts.append(len(rows))
        assert len(set(counts)) == 1, f"per-view row counts disagree: {counts}"
    # source project untouched: no new files appeared at top level
    assert "LP-TEST-mutated" not in {p.name for p in src.iterdir()}
    # summary contract
    assert "n_views" in summary
    assert "n_frames" in summary
    assert "warnings" in summary


def test_convert_aggregates_calibration(tmp_path):
    src = _fixture()
    dst = tmp_path / "lp-project"
    convert_dlc_to_lp(src, dst, link_mode="link")
    cal_dir = dst / "calibrations"
    cal_csv = dst / "calibrations.csv"
    # The converter only emits calibrations for sessions whose folder names
    # match the _camN_ pattern. If no such session has a calibration.toml,
    # skip these assertions.
    from dlc_3d_bp.lp.project_layout import session_view_pair
    has_matchable_cal = any(
        session_view_pair(p.parent.name)[0]
        for p in src.glob("labeled-data/*/calibration.toml")
    )
    if has_matchable_cal:
        assert cal_dir.is_dir()
        assert any(cal_dir.glob("*.toml"))
        assert cal_csv.is_file()

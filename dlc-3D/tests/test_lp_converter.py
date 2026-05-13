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
    # Fixture contains at least cam0 + cam1 in session-key folders
    assert summary["n_views"] >= 2
    assert summary["n_frames"] > 0
    # Per-view CSVs (cam*.csv) must be consistent: every cam*.csv must have
    # the same row count.
    csvs = sorted(dst.glob("cam*.csv"))
    assert len(csvs) == summary["n_views"]
    counts = []
    for c in csvs:
        with c.open() as f:
            rows = [
                r for r in csv.reader(f)
                if r and r[0] not in ("scorer", "bodyparts", "coords", "individuals")
            ]
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
    # The fixture's calibrations live in session-key folders (view-in-filename
    # layout). The converter aggregates these too.
    assert cal_dir.is_dir()
    assert any(cal_dir.glob("*.toml"))
    assert cal_csv.is_file()
    # calibrations.csv has more than just the header row
    with cal_csv.open() as f:
        rows = list(csv.reader(f))
    assert len(rows) >= 2


def test_view_in_filename_layout(tmp_path):
    """Folder name is a session key; cam is encoded in image filenames."""
    src = tmp_path / "dlc"; src.mkdir()
    (src / "config.yaml").write_text("bodyparts:\n  - Snout\n")
    ld = src / "labeled-data" / "rat1_20260101"; ld.mkdir(parents=True)
    # Two cams, two frames each (frames 100 and 200 in both cams)
    for cam in (0, 1):
        for order, fn in enumerate((100, 200)):
            (ld / f"img_cam{cam}_{order:04d}_{fn:05d}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    # Minimal newer-schema CSV: 3-col path + 2 columns of data
    cc = ld / "CollectedData_x.csv"
    with cc.open("w") as f:
        f.write("scorer,,,x,x\n")
        f.write("bodyparts,,,Snout,Snout\n")
        f.write("coords,,,x,y\n")
        for cam in (0, 1):
            for order, fn in enumerate((100, 200)):
                f.write(f"labeled-data,rat1_20260101,img_cam{cam}_{order:04d}_{fn:05d}.png,10,20\n")
    (ld / "calibration.toml").write_text("[cam_0]\nname='c0'\n")

    from dlc_3d_bp.lp.converter import convert_dlc_to_lp
    dst = tmp_path / "lp"
    summary = convert_dlc_to_lp(src, dst)
    assert summary["n_views"] == 2
    assert summary["n_frames"] == 4   # 2 frames * 2 cams
    assert (dst / "cam0.csv").is_file()
    assert (dst / "cam1.csv").is_file()
    # Row-count consistency
    import csv as _csv
    counts = []
    for v in ("cam0", "cam1"):
        with (dst / f"{v}.csv").open() as f:
            counts.append(sum(1 for r in _csv.reader(f) if r and r[0] not in ("scorer","bodyparts","coords")))
    assert counts[0] == counts[1] == 2
    # Calibration aggregated by session-key folder name
    assert (dst / "calibrations" / "rat1_20260101.toml").is_file()

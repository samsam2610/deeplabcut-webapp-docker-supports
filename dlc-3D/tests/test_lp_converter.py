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


# ── Upstream canonical default config: loader + substitution semantics ──

from dlc_3d_bp.lp.converter import (
    _load_upstream_default_config,
    _LP_DEFAULT_VENDORED,
    LP_DEFAULT_CONFIG_REF,
)


def test_load_upstream_default_uses_vendored_when_network_fails(tmp_path, monkeypatch):
    """Loader falls back to the vendored fallback when both GitHub URLs fail."""
    # Force cache miss
    monkeypatch.setattr("dlc_3d_bp.lp.converter._LP_DEFAULT_CACHE", tmp_path / "no-cache.yaml")

    def _boom(*args, **kwargs):
        raise OSError("network down")
    monkeypatch.setattr("urllib.request.urlopen", _boom)

    cfg = _load_upstream_default_config()
    # Canonical keys present from the vendored file
    assert "data" in cfg
    assert "training" in cfg
    assert "model" in cfg
    assert "dali" in cfg
    assert "losses" in cfg
    assert "eval" in cfg
    assert "callbacks" in cfg


def test_load_upstream_default_uses_cache(tmp_path, monkeypatch):
    """A pre-existing cache file short-circuits the network call."""
    cache = tmp_path / "cached.yaml"
    cache.write_text("data:\n  foo: bar\n")
    monkeypatch.setattr("dlc_3d_bp.lp.converter._LP_DEFAULT_CACHE", cache)

    def _boom(*args, **kwargs):
        raise AssertionError("urlopen should not be called when cache exists")
    monkeypatch.setattr("urllib.request.urlopen", _boom)

    cfg = _load_upstream_default_config()
    assert cfg == {"data": {"foo": "bar"}}


def test_vendored_default_matches_upstream_pinned_ref():
    """The vendored fallback must be present and parseable, with the same top-level keys as the upstream canonical config."""
    assert _LP_DEFAULT_VENDORED.is_file(), (
        f"vendored upstream default missing at {_LP_DEFAULT_VENDORED}; sync from "
        f"https://raw.githubusercontent.com/paninski-lab/lightning-pose/"
        f"{LP_DEFAULT_CONFIG_REF}/scripts/configs/config_default.yaml"
    )
    import yaml as _yaml
    cfg = _yaml.safe_load(_LP_DEFAULT_VENDORED.read_text())
    # Required canonical top-level keys per the v2.1.0 default
    for k in ("data", "training", "model", "dali", "losses", "eval", "callbacks", "hydra"):
        assert k in cfg, f"vendored fallback missing top-level key {k!r}"


def test_convert_emits_canonical_keys_with_substitutions(tmp_path):
    """convert_dlc_to_lp's output config.yaml must contain every canonical top-level
    key from upstream and substitute project-specific values where required."""
    src = tmp_path / "dlc"
    src.mkdir()
    (src / "config.yaml").write_text(
        "bodyparts:\n  - Snout\n  - Wrist\n"
    )
    # Minimal view-in-filename labeled-data set
    ld = src / "labeled-data" / "rat_20260101"
    ld.mkdir(parents=True)
    cc = ld / "CollectedData_x.csv"
    cc.write_text(
        "scorer,,,x,x,x,x\n"
        "bodyparts,,,Snout,Snout,Wrist,Wrist\n"
        "coords,,,x,y,x,y\n"
        "labeled-data,rat_20260101,img_cam0_0000_00100.png,1,2,3,4\n"
        "labeled-data,rat_20260101,img_cam1_0000_00100.png,5,6,7,8\n"
        "labeled-data,rat_20260101,img_cam0_0001_00200.png,9,0,1,2\n"
        "labeled-data,rat_20260101,img_cam1_0001_00200.png,3,4,5,6\n"
    )
    # Tiny PNGs (just IHDR; _probe_image_dims falls back to 384x384 if invalid)
    (ld / "img_cam0_0000_00100.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (ld / "img_cam1_0000_00100.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (ld / "img_cam0_0001_00200.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (ld / "img_cam1_0001_00200.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    from dlc_3d_bp.lp.converter import convert_dlc_to_lp
    dst = tmp_path / "lp"
    convert_dlc_to_lp(src, dst)

    import yaml as _yaml
    cfg = _yaml.safe_load((dst / "config.yaml").read_text())
    # All canonical top-level keys present
    for k in ("data", "training", "model", "dali", "losses", "eval", "callbacks", "hydra"):
        assert k in cfg, f"emitted config missing {k!r}"
    # Substituted project-specific values
    assert cfg["data"]["data_dir"] == str(dst.resolve())
    assert cfg["data"]["num_keypoints"] == 2
    assert cfg["data"]["keypoint_names"] == ["Snout", "Wrist"]
    assert cfg["data"]["view_names"] == ["cam0", "cam1"]
    assert cfg["data"]["csv_file"] == ["cam0.csv", "cam1.csv"]
    # Multi-view forces these
    assert cfg["model"]["model_type"] == "heatmap_multiview_transformer"
    assert cfg["model"]["backbone"] == "vits_dino"
    # Untouched canonical defaults survived
    assert cfg["training"]["optimizer"] == "Adam"
    assert cfg["training"]["lr_scheduler_params"]["multisteplr"]["milestones"] == [150, 200, 250]
    assert "anneal_weight" in cfg["callbacks"]
    assert "pca_multiview" in cfg["losses"]
    # Provenance recorded
    assert cfg["_converter"]["lp_default_ref"] == LP_DEFAULT_CONFIG_REF

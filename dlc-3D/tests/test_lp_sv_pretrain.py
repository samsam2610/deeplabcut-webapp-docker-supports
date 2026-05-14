"""Tests for the SV-pretrain branch of convert_dlc_to_lp."""
from __future__ import annotations

import csv
from pathlib import Path
import textwrap

import pytest

from dlc_3d_bp.lp.converter import _walk_all_labeled_data


def _seed(folder: Path, csv_name: str, rows: list[list[str]], png_names: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / csv_name).open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scorer", "", "", "x"])
        w.writerow(["bodyparts", "", "", "Snout"])
        w.writerow(["coords", "", "", "x"])
        for r in rows:
            w.writerow(r)
    for n in png_names:
        (folder / n).write_bytes(b"\x89PNG\r\n\x1a\n")


def test_walk_all_labeled_data_yields_view_in_filename(tmp_path):
    """A folder whose name is a session-key (view-in-filename layout) yields
    one entry per labeled row across all cams."""
    dlc = tmp_path / "dlc"
    ld = dlc / "labeled-data" / "rat_20260101"
    _seed(
        ld, "CollectedData_x.csv",
        rows=[
            ["labeled-data", "rat_20260101", "img_cam0_0000_00100.png", "10"],
            ["labeled-data", "rat_20260101", "img_cam1_0000_00100.png", "20"],
        ],
        png_names=["img_cam0_0000_00100.png", "img_cam1_0000_00100.png"],
    )
    entries = list(_walk_all_labeled_data(dlc))
    assert len(entries) == 2
    # Each entry is (src_png: Path, dest_rel: str, normalised_row: list[str])
    rel_paths = sorted(e[1] for e in entries)
    assert rel_paths == [
        "labeled-data/rat_20260101/img_cam0_0000_00100.png",
        "labeled-data/rat_20260101/img_cam1_0000_00100.png",
    ]


def test_walk_all_labeled_data_yields_view_in_folder(tmp_path):
    """A folder whose name contains _cam<N>_ (DLC legacy) yields rows verbatim."""
    dlc = tmp_path / "dlc"
    ld = dlc / "labeled-data" / "session_cam0_20260101_run"
    _seed(
        ld, "CollectedData_x.csv",
        rows=[
            ["labeled-data/session_cam0_20260101_run/imgABC.png", "5"],
            ["labeled-data/session_cam0_20260101_run/imgDEF.png", "7"],
        ],
        png_names=["imgABC.png", "imgDEF.png"],
    )
    entries = list(_walk_all_labeled_data(dlc))
    assert len(entries) == 2


def test_walk_all_labeled_data_yields_unrecognised_folder(tmp_path):
    """A folder with no _cam<N>_ and plain img names also yields its rows."""
    dlc = tmp_path / "dlc"
    ld = dlc / "labeled-data" / "1873_DAY9_10445_11244_f1"
    _seed(
        ld, "CollectedData_x.csv",
        rows=[
            ["labeled-data/1873_DAY9_10445_11244_f1/img00001.png", "3"],
            ["labeled-data/1873_DAY9_10445_11244_f1/img00002.png", "4"],
        ],
        png_names=["img00001.png", "img00002.png"],
    )
    entries = list(_walk_all_labeled_data(dlc))
    assert len(entries) == 2


def test_walk_all_labeled_data_skips_ipynb_checkpoints(tmp_path):
    """`.ipynb_checkpoints` and hidden dot-folders must not yield rows."""
    dlc = tmp_path / "dlc"
    bad = dlc / "labeled-data" / ".ipynb_checkpoints"
    _seed(bad, "CollectedData_x.csv",
          rows=[["labeled-data/.ipynb_checkpoints/img.png", "1"]],
          png_names=["img.png"])
    assert list(_walk_all_labeled_data(dlc)) == []


import yaml

from dlc_3d_bp.lp.converter import _write_sv_config


def test_write_sv_config_emits_singleview_canonical_shape(tmp_path, monkeypatch):
    sv_dir = tmp_path / "sv"
    sv_dir.mkdir()
    # Avoid network in tests — force the vendored fallback
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr("dlc_3d_bp.lp.converter._LP_DEFAULT_CACHE", tmp_path / "no-cache.yaml")

    _write_sv_config(
        sv_dir=sv_dir,
        dlc_dir=tmp_path / "src_dlc",
        bodyparts=["Snout", "Wrist"],
        img_h=480,
        img_w=640,
    )
    cfg = yaml.safe_load((sv_dir / "config.yaml").read_text())
    # Single-view convention: csv_file is a string, no view_names key
    assert cfg["data"]["csv_file"] == "labels.csv"
    assert "view_names" not in cfg["data"]
    # Substituted project-specific values
    assert cfg["data"]["data_dir"] == str(sv_dir)
    assert cfg["data"]["num_keypoints"] == 2
    assert cfg["data"]["keypoint_names"] == ["Snout", "Wrist"]
    assert cfg["data"]["image_orig_dims"] == {"height": 480, "width": 640}
    # ViT-required resize dims (multiple of 128, floor 256)
    assert cfg["data"]["image_resize_dims"]["height"] % 128 == 0
    assert cfg["data"]["image_resize_dims"]["height"] >= 256
    # Stage-1 model setup forces vits_dino + plain heatmap so the backbone
    # state-dict transfers cleanly into MVT in stage 2.
    assert cfg["model"]["backbone"] == "vits_dino"
    assert cfg["model"]["model_type"] == "heatmap"
    # Provenance
    assert cfg["_converter"]["sv_pretrain"] is True


from dlc_3d_bp.lp.converter import _build_sv_pretrain_project


def test_build_sv_pretrain_project_writes_layout(tmp_path, monkeypatch):
    """SV pretrain dir has config.yaml + labels.csv + labeled-data/<folder>/<png>."""
    dlc = tmp_path / "dlc"
    dlc.mkdir()
    (dlc / "config.yaml").write_text("bodyparts:\n  - Snout\n")
    # Two heterogeneous source folders
    _seed(
        dlc / "labeled-data" / "rat_view_in_filename",
        "CollectedData_x.csv",
        rows=[
            ["labeled-data", "rat_view_in_filename", "img_cam0_0000_00100.png", "10"],
            ["labeled-data", "rat_view_in_filename", "img_cam1_0000_00100.png", "20"],
        ],
        png_names=["img_cam0_0000_00100.png", "img_cam1_0000_00100.png"],
    )
    _seed(
        dlc / "labeled-data" / "session_cam0_20260101",
        "CollectedData_x.csv",
        rows=[
            ["labeled-data/session_cam0_20260101/imgZZZ.png", "5"],
        ],
        png_names=["imgZZZ.png"],
    )

    # Force vendored fallback (no network)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr("dlc_3d_bp.lp.converter._LP_DEFAULT_CACHE", tmp_path / "no-cache.yaml")

    lp_dir = tmp_path / "lp"
    lp_dir.mkdir()

    n_rows = _build_sv_pretrain_project(lp_dir=lp_dir, dlc_dir=dlc, bodyparts=["Snout"])
    assert n_rows == 3  # 2 + 1

    sv = lp_dir / "sv-pretrain"
    assert (sv / "config.yaml").is_file()
    assert (sv / "labels.csv").is_file()
    # PNGs hardlinked into sv-pretrain/labeled-data/<folder>/<png>
    assert (sv / "labeled-data" / "rat_view_in_filename" / "img_cam0_0000_00100.png").is_file()
    assert (sv / "labeled-data" / "session_cam0_20260101" / "imgZZZ.png").is_file()

    # labels.csv: 3 header rows + 3 data rows
    with (sv / "labels.csv").open() as f:
        lines = f.readlines()
    assert len(lines) == 6
    # First data row's path cell is the dest_rel (1-col, not 3-col split)
    data_rows = [l for l in lines if l.strip().startswith("labeled-data/")]
    assert len(data_rows) == 3


from dlc_3d_bp.lp.converter import convert_dlc_to_lp


def test_convert_emits_sv_pretrain_sibling(tmp_path, monkeypatch):
    """convert_dlc_to_lp summary includes sv_pretrain_dir + n_sv_rows."""
    dlc = tmp_path / "dlc"
    dlc.mkdir()
    (dlc / "config.yaml").write_text("bodyparts:\n  - Snout\n")
    ld = dlc / "labeled-data" / "rat_20260101"
    _seed(
        ld, "CollectedData_x.csv",
        rows=[
            ["labeled-data", "rat_20260101", "img_cam0_0000_00100.png", "10"],
            ["labeled-data", "rat_20260101", "img_cam1_0000_00100.png", "20"],
        ],
        png_names=["img_cam0_0000_00100.png", "img_cam1_0000_00100.png"],
    )

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr("dlc_3d_bp.lp.converter._LP_DEFAULT_CACHE", tmp_path / "no-cache.yaml")

    lp_dir = tmp_path / "lp"
    summary = convert_dlc_to_lp(dlc, lp_dir)

    assert "sv_pretrain_dir" in summary
    assert summary["sv_pretrain_dir"].endswith("sv-pretrain")
    assert summary["n_sv_rows"] == 2
    assert (Path(summary["sv_pretrain_dir"]) / "config.yaml").is_file()
    assert (Path(summary["sv_pretrain_dir"]) / "labels.csv").is_file()

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

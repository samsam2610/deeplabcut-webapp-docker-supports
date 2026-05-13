from pathlib import Path
import pytest

from dlc_3d_bp.lp import project_layout as L


def test_view_name_from_stem():
    assert L.view_name_from_stem("surv1_cam0_20260123_xyz") == "cam0"
    assert L.view_name_from_stem("surv1_cam2_20260123_xyz") == "cam2"
    assert L.view_name_from_stem("no_cam_pattern") is None


def test_session_view_pair_round_trip():
    s, v = L.session_view_pair("surv1_cam1_20260123_xyz")
    assert s == "surv1_20260123"
    assert v == "cam1"


def test_lp_csv_filename_for_view():
    assert L.lp_csv_for_view("cam0") == "cam0.csv"


def test_lp_labeled_dir_name():
    assert L.lp_labeled_dir_name("surv1_20260123", "cam0") == "surv1_20260123_cam0"

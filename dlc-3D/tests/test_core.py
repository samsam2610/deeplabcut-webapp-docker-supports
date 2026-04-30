import json
import re
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from routes import (
    _cam_index_from_stem,
    _find_sibling_video,
    _save_single_frame,
    _scan_videos,
    _session_key_from_stem,
)


def _make_video(path: Path, frames: int = 10, w: int = 32, h: int = 32) -> None:
    out = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"XVID"), 30.0, (w, h)
    )
    for i in range(frames):
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:] = (i * 25 % 256, 100, 50)
        out.write(frame)
    out.release()


def _fake_project(tmp_path: Path, cams=("cam0", "cam1"), clips=False) -> Path:
    """Create a minimal project layout with AVI files for each cam."""
    proj = tmp_path / "project"
    videos = proj / "videos"
    videos.mkdir(parents=True)
    (videos / "calibration.toml").write_text("[cam_0]\nname = '0'\n")
    for cam in cams:
        stem = f"surv1_{cam}_20260123_121732_0_trig1"
        avi = videos / f"{stem}.avi"
        _make_video(avi, frames=20)
        (videos / f"{stem}.csv").touch()
        if clips:
            clip_dir = videos / stem
            clip_dir.mkdir()
            _make_video(clip_dir / "clip_001.avi", frames=15)
    return proj


# ── _session_key_from_stem ───────────────────────────────────────────────────

def test_session_key_standard():
    assert _session_key_from_stem(
        "surv1_cam0_20260123_121732_0_trig1_fps200_exposure1500_gain10"
    ) == "surv1_20260123"


def test_session_key_hyphenated_subject():
    assert _session_key_from_stem("my-rat_cam1_20260205_090000_0") == "my-rat_20260205"


def test_session_key_no_cam_pattern_returns_none():
    assert _session_key_from_stem("MAP2_20250715_120050_0") is None


def test_session_key_no_date_returns_none():
    assert _session_key_from_stem("surv1_cam0_nodate") is None


# ── _cam_index_from_stem ─────────────────────────────────────────────────────

def test_cam_index_cam0():
    assert _cam_index_from_stem("surv1_cam0_20260123_121732_0") == 0


def test_cam_index_cam1():
    assert _cam_index_from_stem("surv1_cam1_20260123_121743_0") == 1


def test_cam_index_no_pattern_returns_none():
    assert _cam_index_from_stem("MAP2_20250715_120050_0") is None


# ── _scan_videos ─────────────────────────────────────────────────────────────

def test_scan_videos_groups_by_session(tmp_path):
    proj = _fake_project(tmp_path)
    sessions = _scan_videos(proj)
    assert "surv1_20260123" in sessions
    assert "cam0" in sessions["surv1_20260123"]
    assert "cam1" in sessions["surv1_20260123"]


def test_scan_videos_relative_paths(tmp_path):
    proj = _fake_project(tmp_path)
    sessions = _scan_videos(proj)
    cam0 = sessions["surv1_20260123"]["cam0"]
    assert cam0["avi"].startswith("videos/")
    assert not cam0["avi"].startswith("/")


def test_scan_videos_csv_included(tmp_path):
    proj = _fake_project(tmp_path)
    sessions = _scan_videos(proj)
    assert sessions["surv1_20260123"]["cam0"]["csv"] is not None


def test_scan_videos_no_clips_when_no_folder(tmp_path):
    proj = _fake_project(tmp_path, clips=False)
    cam0 = _scan_videos(proj)["surv1_20260123"]["cam0"]
    assert cam0["clip_folder"] is None
    assert cam0["clips"] is None


def test_scan_videos_detects_clip_folder(tmp_path):
    proj = _fake_project(tmp_path, clips=True)
    cam0 = _scan_videos(proj)["surv1_20260123"]["cam0"]
    assert cam0["clip_folder"] is not None
    assert len(cam0["clips"]) == 1
    assert cam0["clips"][0].endswith("clip_001.avi")


def test_scan_videos_skips_unmatched_avi(tmp_path):
    proj = _fake_project(tmp_path, cams=())
    (proj / "videos" / "unrelated.avi").touch()
    sessions = _scan_videos(proj)
    assert sessions == {}


# ── _find_sibling_video ───────────────────────────────────────────────────────

def test_find_sibling_raw_video(tmp_path):
    proj = _fake_project(tmp_path)
    sessions = _scan_videos(proj)
    videos_json = {"sessions": sessions}
    sibling = _find_sibling_video("videos/surv1_cam0_20260123_121732_0_trig1.avi", videos_json)
    assert sibling is not None
    assert "cam1" in sibling


def test_find_sibling_clip(tmp_path):
    proj = _fake_project(tmp_path, clips=True)
    sessions = _scan_videos(proj)
    videos_json = {"sessions": sessions}
    primary_clip = sessions["surv1_20260123"]["cam0"]["clips"][0]
    sibling = _find_sibling_video(primary_clip, videos_json)
    assert sibling is not None
    assert "cam1" in sibling
    assert sibling.endswith("clip_001.avi")


def test_find_sibling_returns_none_for_single_cam(tmp_path):
    proj = _fake_project(tmp_path, cams=("cam0",))
    sessions = _scan_videos(proj)
    videos_json = {"sessions": sessions}
    sibling = _find_sibling_video("videos/surv1_cam0_20260123_121732_0_trig1.avi", videos_json)
    assert sibling is None


# ── _save_single_frame ────────────────────────────────────────────────────────

def test_save_frame_creates_png(tmp_path):
    proj = _fake_project(tmp_path)
    result = _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 5)
    assert "saved" in result
    assert result["saved"] == "img_cam0_0000_00005.png"
    labeled_dir = proj / "labeled-data" / "surv1_20260123"
    assert (labeled_dir / "img_cam0_0000_00005.png").exists()


def test_save_frame_png_is_valid_image(tmp_path):
    proj = _fake_project(tmp_path)
    _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 3)
    labeled_dir = proj / "labeled-data" / "surv1_20260123"
    img = cv2.imread(str(labeled_dir / "img_cam0_0000_00003.png"))
    assert img is not None
    assert img.shape[:2] == (32, 32)


def test_save_frame_copies_calibration(tmp_path):
    proj = _fake_project(tmp_path)
    _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 3)
    calib_dest = proj / "labeled-data" / "surv1_20260123" / "calibration.toml"
    assert calib_dest.exists()


def test_save_frame_skips_calibration_copy_on_second_save(tmp_path):
    proj = _fake_project(tmp_path)
    _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 3)
    dest = proj / "labeled-data" / "surv1_20260123" / "calibration.toml"
    dest.write_text("modified")
    _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 7)
    assert dest.read_text() == "modified"


def test_save_frame_duplicate_skipped(tmp_path):
    proj = _fake_project(tmp_path)
    r1 = _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 5)
    r2 = _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 5)
    assert "saved" in r1
    assert r2.get("skipped") is True


def test_save_frame_order_increments(tmp_path):
    proj = _fake_project(tmp_path)
    r1 = _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 3)
    r2 = _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 7)
    assert r1["saved"] == "img_cam0_0000_00003.png"
    assert r2["saved"] == "img_cam0_0001_00007.png"


def test_save_frame_cam_order_independent(tmp_path):
    """cam0 and cam1 orders are counted separately."""
    proj = _fake_project(tmp_path)
    _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 3)
    _save_single_frame(proj, "videos/surv1_cam0_20260123_121732_0_trig1.avi", 7)
    r_cam1 = _save_single_frame(proj, "videos/surv1_cam1_20260123_121732_0_trig1.avi", 3)
    assert r_cam1["saved"] == "img_cam1_0000_00003.png"

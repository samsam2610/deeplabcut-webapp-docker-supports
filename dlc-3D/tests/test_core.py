import json
import re
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from dlc_3d_bp.routes import (
    _cam_index_from_stem,
    _find_sibling_on_filesystem,
    _find_sibling_video,
    _load_or_scan_videos,
    _resolve_video_path,
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


# ── _load_or_scan_videos ──────────────────────────────────────────────────────

def test_load_or_scan_creates_json_cache(tmp_path):
    from dlc_3d_bp.routes import _load_or_scan_videos
    proj = _fake_project(tmp_path)
    data = _load_or_scan_videos(proj)
    assert (proj / "videos.json").exists()
    assert "sessions" in data
    assert "surv1_20260123" in data["sessions"]


def test_load_or_scan_reads_existing_json(tmp_path):
    from dlc_3d_bp.routes import _load_or_scan_videos
    proj = _fake_project(tmp_path)
    # First call creates cache
    _load_or_scan_videos(proj)
    # Add a new video — should NOT appear because cache is used
    new_stem = "surv2_cam0_20260201_080000_0_trig1"
    _make_video(proj / "videos" / f"{new_stem}.avi", frames=5)
    data2 = _load_or_scan_videos(proj)
    assert "surv2_20260201" not in data2.get("sessions", {})


def test_save_frame_clip_path(tmp_path):
    proj = _fake_project(tmp_path, clips=True)
    sessions = _scan_videos(proj)
    clip_path = sessions["surv1_20260123"]["cam0"]["clips"][0]
    result = _save_single_frame(proj, clip_path, 3)
    assert "saved" in result
    assert result["saved"].startswith("img_cam0_")
    labeled_dir = proj / "labeled-data" / "surv1_20260123"
    assert (labeled_dir / result["saved"]).exists()


def test_browse_returns_video_files(tmp_path, monkeypatch):
    """browse() should include .avi and .mp4 files in entries."""
    from flask import Flask, request
    from flask.testing import FlaskClient
    from dlc_3d_bp import routes
    import config

    # Mock USER_DATA_ROOTS and _USER_DATA_ROOT to point to our test directory
    monkeypatch.setattr(config, "USER_DATA_ROOTS", [tmp_path])
    monkeypatch.setattr(routes, "_USER_DATA_ROOT", str(tmp_path))

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    client = app.test_client()

    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    (videos_dir / "surv1_cam0_20260123_121732.avi").write_bytes(b"")
    (videos_dir / "surv1_cam1_20260123_121732.avi").write_bytes(b"")
    (videos_dir / "clip.mp4").write_bytes(b"")
    (videos_dir / "readme.txt").write_bytes(b"")  # should NOT appear

    resp = client.get(f"/dlc-3d/browse?path={videos_dir}")
    assert resp.status_code == 200
    data = resp.get_json()
    types = {e["name"]: e["type"] for e in data["entries"]}
    assert types["surv1_cam0_20260123_121732.avi"] == "file"
    assert types["surv1_cam1_20260123_121732.avi"] == "file"
    assert types["clip.mp4"] == "file"
    assert "readme.txt" not in types


# ── _resolve_video_path ───────────────────────────────────────────────────────

def test_resolve_video_path_absolute_within_user_data():
    p = _resolve_video_path("/user-data/Parra-Data/videos/foo.avi", "/user-data/proj")
    assert p == Path("/user-data/Parra-Data/videos/foo.avi")


def test_resolve_video_path_absolute_outside_user_data_returns_none():
    p = _resolve_video_path("/etc/passwd", "/user-data/proj")
    assert p is None


def test_resolve_video_path_relative_within_project(tmp_path):
    p = _resolve_video_path("videos/foo.avi", str(tmp_path))
    assert p == (tmp_path / "videos/foo.avi").resolve()


def test_resolve_video_path_relative_escaping_project_returns_none(tmp_path):
    p = _resolve_video_path("../../etc/passwd", str(tmp_path))
    assert p is None


# ── _find_sibling_on_filesystem ───────────────────────────────────────────────

def test_find_sibling_on_filesystem_finds_cam1(tmp_path):
    vid_dir = tmp_path / "videos"
    vid_dir.mkdir()
    cam0 = vid_dir / "surv1_cam0_20260123_121732_0.avi"
    cam1 = vid_dir / "surv1_cam1_20260123_121732_0.avi"
    cam0.write_bytes(b"")
    cam1.write_bytes(b"")
    result = _find_sibling_on_filesystem(str(cam0))
    assert result == str(cam1)


def test_find_sibling_on_filesystem_no_sibling(tmp_path):
    vid_dir = tmp_path / "videos"
    vid_dir.mkdir()
    cam0 = vid_dir / "surv1_cam0_20260123_121732_0.avi"
    cam0.write_bytes(b"")
    result = _find_sibling_on_filesystem(str(cam0))
    assert result is None


def test_find_sibling_on_filesystem_no_pattern(tmp_path):
    vid_dir = tmp_path / "videos"
    vid_dir.mkdir()
    f = vid_dir / "recording.avi"
    f.write_bytes(b"")
    result = _find_sibling_on_filesystem(str(f))
    assert result is None


def test_find_sibling_on_filesystem_ignores_same_cam(tmp_path):
    vid_dir = tmp_path / "videos"
    vid_dir.mkdir()
    cam0a = vid_dir / "surv1_cam0_20260123_121732_0.avi"
    cam0b = vid_dir / "surv1_cam0_20260123_999999_0.avi"
    cam0a.write_bytes(b"")
    cam0b.write_bytes(b"")
    result = _find_sibling_on_filesystem(str(cam0a))
    assert result is None

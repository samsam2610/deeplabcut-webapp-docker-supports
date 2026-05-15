"""Unit tests for the MVT video sibling-pair filter."""
import os
from pathlib import Path
import pytest

from dlc_3d_bp.lp.train_runner import _build_mvt_video_subdir


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")


def test_filter_paired_only(tmp_path):
    videos = tmp_path / "videos"; videos.mkdir()
    stage2 = tmp_path / "stage2"; stage2.mkdir()
    _touch(videos / "sess1_cam0_x.mp4")
    _touch(videos / "sess1_cam1_x.mp4")
    _touch(videos / "sess2_cam0_y.mp4")          # orphan, no cam1 sibling
    _touch(videos / "sess3_cam0_z.mp4")
    _touch(videos / "sess3_cam1_z.mp4")

    out_dir, kept, dropped = _build_mvt_video_subdir(videos, ["cam0", "cam1"], stage2)

    assert out_dir == stage2 / "videos_mvt_filtered"
    assert out_dir.is_dir()
    kept_names = sorted(p.name for p in out_dir.iterdir())
    assert kept_names == sorted([
        "sess1_cam0_x.mp4", "sess1_cam1_x.mp4",
        "sess3_cam0_z.mp4", "sess3_cam1_z.mp4",
    ])
    assert kept == 2                                       # 2 sessions kept
    assert dropped == ["sess2_cam0_y.mp4"]                 # 1 orphan reported
    # All entries are symlinks to the originals
    for entry in out_dir.iterdir():
        assert entry.is_symlink()
        assert os.path.realpath(str(entry)) == str(videos / entry.name)


def test_filter_handles_three_views(tmp_path):
    videos = tmp_path / "videos"; videos.mkdir()
    stage2 = tmp_path / "stage2"; stage2.mkdir()
    for v in ("cam0", "cam1", "cam2"):
        _touch(videos / f"trio_{v}_a.mp4")
    _touch(videos / "duo_cam0_b.mp4")    # missing cam1 and cam2 siblings
    _touch(videos / "duo_cam1_b.mp4")

    out_dir, kept, dropped = _build_mvt_video_subdir(videos, ["cam0", "cam1", "cam2"], stage2)
    kept_names = sorted(p.name for p in out_dir.iterdir())
    assert kept_names == sorted([f"trio_{v}_a.mp4" for v in ("cam0", "cam1", "cam2")])
    assert kept == 1
    # Both partial siblings reported as dropped
    assert sorted(dropped) == sorted(["duo_cam0_b.mp4", "duo_cam1_b.mp4"])


def test_filter_idempotent(tmp_path):
    videos = tmp_path / "videos"; videos.mkdir()
    stage2 = tmp_path / "stage2"; stage2.mkdir()
    _touch(videos / "s_cam0_x.mp4")
    _touch(videos / "s_cam1_x.mp4")
    _build_mvt_video_subdir(videos, ["cam0", "cam1"], stage2)
    out_dir, kept, dropped = _build_mvt_video_subdir(videos, ["cam0", "cam1"], stage2)
    # Re-run produces the same result; no duplicate-symlink errors.
    assert kept == 1
    assert dropped == []
    assert sorted(p.name for p in out_dir.iterdir()) == ["s_cam0_x.mp4", "s_cam1_x.mp4"]


def test_filter_skips_unrecognised_stems(tmp_path):
    """Files without a _cam{N}_ token are ignored entirely (not orphans)."""
    videos = tmp_path / "videos"; videos.mkdir()
    stage2 = tmp_path / "stage2"; stage2.mkdir()
    _touch(videos / "no_cam_token.mp4")
    _touch(videos / "s_cam0_x.mp4")
    _touch(videos / "s_cam1_x.mp4")
    out_dir, kept, dropped = _build_mvt_video_subdir(videos, ["cam0", "cam1"], stage2)
    assert kept == 1
    assert dropped == []  # 'no_cam_token.mp4' is silently ignored (not an orphan)
    assert "no_cam_token.mp4" not in {p.name for p in out_dir.iterdir()}


def test_filter_empty_source(tmp_path):
    videos = tmp_path / "videos"; videos.mkdir()
    stage2 = tmp_path / "stage2"; stage2.mkdir()
    out_dir, kept, dropped = _build_mvt_video_subdir(videos, ["cam0", "cam1"], stage2)
    assert kept == 0
    assert dropped == []
    assert out_dir.is_dir()
    assert not list(out_dir.iterdir())

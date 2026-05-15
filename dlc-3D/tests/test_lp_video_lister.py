import os
from pathlib import Path

import pytest
from dlc_3d_bp.lp.video_lister import list_videos


def _make_lp(tmp_path: Path) -> Path:
    lp = tmp_path / "lp_proj"
    lp.mkdir()
    (lp / "config.yaml").write_text("data: {}\n")
    (lp / "videos").mkdir()
    return lp


def test_empty_videos_dir(tmp_path):
    lp = _make_lp(tmp_path)
    assert list_videos(lp) == []


def test_list_regular_file(tmp_path):
    lp = _make_lp(tmp_path)
    f = lp / "videos" / "v.mp4"
    f.write_bytes(b"hello")
    [entry] = list_videos(lp)
    assert entry["name"] == "v.mp4"
    assert entry["is_symlink"] is False
    assert entry["target"] is None
    assert entry["target_exists"] is True
    assert entry["size_bytes"] == 5


def test_list_symlink_target_exists(tmp_path):
    lp = _make_lp(tmp_path)
    real = tmp_path / "real.mp4"; real.write_bytes(b"abc")
    link = lp / "videos" / "v.mp4"
    os.symlink(str(real), str(link))
    [entry] = list_videos(lp)
    assert entry["name"] == "v.mp4"
    assert entry["is_symlink"] is True
    assert entry["target"] == str(real)
    assert entry["target_exists"] is True
    assert entry["size_bytes"] == 3


def test_list_symlink_broken(tmp_path):
    lp = _make_lp(tmp_path)
    link = lp / "videos" / "v.mp4"
    os.symlink("/no/such/path.mp4", str(link))
    [entry] = list_videos(lp)
    assert entry["is_symlink"] is True
    assert entry["target"] == "/no/such/path.mp4"
    assert entry["target_exists"] is False
    assert entry["size_bytes"] is None  # can't stat — surface as null


def test_rejects_non_lp_project(tmp_path):
    not_lp = tmp_path / "not_lp"; not_lp.mkdir()
    with pytest.raises(FileNotFoundError):
        list_videos(not_lp)


def test_listing_sorted_by_name(tmp_path):
    lp = _make_lp(tmp_path)
    for name in ("c.mp4", "a.mp4", "b.mp4"):
        (lp / "videos" / name).write_bytes(b"")
    names = [e["name"] for e in list_videos(lp)]
    assert names == ["a.mp4", "b.mp4", "c.mp4"]

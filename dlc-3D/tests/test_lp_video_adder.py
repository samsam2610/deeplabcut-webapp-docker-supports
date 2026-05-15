import os
from pathlib import Path
import pytest
from dlc_3d_bp.lp.video_adder import add_videos_to_lp


def _make_lp(tmp_path: Path) -> Path:
    lp = tmp_path / "lp_proj"
    lp.mkdir()
    (lp / "config.yaml").write_text("data: {}\n")
    (lp / "videos").mkdir()
    return lp


def test_symlink_mode_creates_symlinks(tmp_path):
    lp = _make_lp(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"fake")
    out = add_videos_to_lp(lp, [src], mode="symlink")
    assert out["added"] == [str(lp / "videos" / "src.mp4")]
    assert out["skipped"] == []
    dst = lp / "videos" / "src.mp4"
    assert dst.is_symlink()
    assert os.readlink(dst) == str(src)


def test_copy_mode_creates_real_files(tmp_path):
    lp = _make_lp(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"contents")
    out = add_videos_to_lp(lp, [src], mode="copy")
    dst = lp / "videos" / "src.mp4"
    assert not dst.is_symlink()
    assert dst.read_bytes() == b"contents"
    assert out["added"] == [str(dst)]


def test_hardlink_mode_links_on_same_fs(tmp_path):
    lp = _make_lp(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    out = add_videos_to_lp(lp, [src], mode="hardlink")
    dst = lp / "videos" / "src.mp4"
    # On the same filesystem hardlink should succeed -> same inode
    assert dst.stat().st_ino == src.stat().st_ino
    assert out["added"] == [str(dst)]


def test_skip_existing_destination(tmp_path):
    lp = _make_lp(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"a")
    (lp / "videos" / "src.mp4").write_bytes(b"already-there")
    out = add_videos_to_lp(lp, [src], mode="symlink")
    assert out["added"] == []
    assert out["skipped"] == [str(lp / "videos" / "src.mp4")]
    # Existing file untouched
    assert (lp / "videos" / "src.mp4").read_bytes() == b"already-there"


def test_rejects_non_lp_project(tmp_path):
    not_lp = tmp_path / "not_lp"
    not_lp.mkdir()
    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        add_videos_to_lp(not_lp, [src], mode="symlink")


def test_missing_source_video_reported_as_error(tmp_path):
    lp = _make_lp(tmp_path)
    out = add_videos_to_lp(lp, [tmp_path / "ghost.mp4"], mode="symlink")
    assert out["added"] == []
    assert out["skipped"] == []
    assert len(out["errors"]) == 1
    assert "ghost.mp4" in out["errors"][0]


def test_invalid_mode_raises(tmp_path):
    lp = _make_lp(tmp_path)
    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")
    with pytest.raises(ValueError):
        add_videos_to_lp(lp, [src], mode="bogus")

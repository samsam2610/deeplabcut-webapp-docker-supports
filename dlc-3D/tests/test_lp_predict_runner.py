from pathlib import Path

import pytest

from dlc_3d_bp.lp.predict_runner import relocate_predictions


def _seed_model_video_preds(model_dir: Path, video_stems: list[str], with_labeled_mp4: bool = True) -> None:
    """Create the `<model_dir>/video_preds/` layout litpose produces."""
    vp = model_dir / "video_preds"
    vp.mkdir(parents=True, exist_ok=True)
    for stem in video_stems:
        (vp / f"{stem}.csv").write_text("predictions,here\n")
        (vp / f"{stem}_pixel_error.csv").write_text("metric,here\n")
        if with_labeled_mp4:
            (vp / "labeled_videos").mkdir(exist_ok=True)
            (vp / "labeled_videos" / f"{stem}_labeled.mp4").write_bytes(b"\x00")


def test_relocate_to_explicit_dest_dir(tmp_path):
    """Outputs are renamed with '_lp' infix so they never clash with user files."""
    model_dir = tmp_path / "model"
    dest = tmp_path / "out"
    videos_dir = tmp_path / "vids"; videos_dir.mkdir()
    v1 = videos_dir / "clipA.mp4"; v1.write_bytes(b"")
    v2 = videos_dir / "clipB.mp4"; v2.write_bytes(b"")
    _seed_model_video_preds(model_dir, ["clipA", "clipB"])

    result = relocate_predictions(model_dir, [v1, v2], dest_dir=dest, overwrite=False)

    assert (dest / "clipA_lp.csv").is_file()
    assert (dest / "clipA_lp_pixel_error.csv").is_file()
    assert (dest / "clipA_lp_labeled.mp4").is_file()
    assert (dest / "clipB_lp.csv").is_file()
    assert (dest / "clipB_lp_labeled.mp4").is_file()
    # User-style canonical names must NOT appear at the destination
    assert not (dest / "clipA.csv").exists()
    assert not (dest / "clipA_labeled.mp4").exists()
    # Source side cleaned up
    assert not (model_dir / "video_preds" / "clipA.csv").exists()
    assert not (model_dir / "video_preds" / "labeled_videos" / "clipA_labeled.mp4").exists()
    assert result["moved"] >= 6
    assert result["skipped"] == []


def test_relocate_per_video_default(tmp_path):
    """dest_dir=None puts each video's outputs in that video's parent folder, with `_lp` infix."""
    model_dir = tmp_path / "model"
    vids_a = tmp_path / "session_a"; vids_a.mkdir()
    vids_b = tmp_path / "session_b"; vids_b.mkdir()
    va = vids_a / "rat1.mp4"; va.write_bytes(b"")
    vb = vids_b / "rat2.mp4"; vb.write_bytes(b"")
    _seed_model_video_preds(model_dir, ["rat1", "rat2"], with_labeled_mp4=False)

    result = relocate_predictions(model_dir, [va, vb], dest_dir=None)

    assert (vids_a / "rat1_lp.csv").is_file()
    assert (vids_a / "rat1_lp_pixel_error.csv").is_file()
    assert (vids_b / "rat2_lp.csv").is_file()
    # No cross-contamination
    assert not (vids_a / "rat2_lp.csv").exists()
    assert not (vids_b / "rat1_lp.csv").exists()
    assert result["dest_dir"] is None
    assert result["skipped"] == []


def test_relocate_never_overwrites_user_files_with_same_canonical_name(tmp_path):
    """Even if a pre-existing `<stem>.csv` is on disk, the LP output lands at `<stem>_lp.csv` and
    leaves the user's file untouched regardless of the `overwrite` flag."""
    model_dir = tmp_path / "model"
    vids = tmp_path / "v"; vids.mkdir()
    video = vids / "rat.mp4"; video.write_bytes(b"")
    _seed_model_video_preds(model_dir, ["rat"], with_labeled_mp4=False)

    # Pre-existing user-owned CSV with the canonical name
    existing = vids / "rat.csv"
    existing.write_text("DO_NOT_TOUCH\n")

    # overwrite=True must NOT clobber the user's file (different target name now)
    result = relocate_predictions(model_dir, [video], dest_dir=None, overwrite=True)

    assert existing.read_text() == "DO_NOT_TOUCH\n"           # untouched
    assert (vids / "rat_lp.csv").is_file()                    # LP output landed
    assert (vids / "rat_lp_pixel_error.csv").is_file()
    assert result["skipped"] == []


def test_relocate_skips_on_lp_filename_conflict(tmp_path):
    """If `<stem>_lp.csv` already exists at the destination, skip unless overwrite=True."""
    model_dir = tmp_path / "model"
    vids = tmp_path / "v"; vids.mkdir()
    video = vids / "rat.mp4"; video.write_bytes(b"")
    _seed_model_video_preds(model_dir, ["rat"], with_labeled_mp4=False)

    # An older LP run already wrote here
    prev = vids / "rat_lp.csv"
    prev.write_text("OLDER_RUN\n")

    result = relocate_predictions(model_dir, [video], dest_dir=None, overwrite=False)
    assert prev.read_text() == "OLDER_RUN\n"
    assert any("rat.csv" in s for s in result["skipped"])

    # With overwrite=True it replaces
    _seed_model_video_preds(model_dir, ["rat"], with_labeled_mp4=False)
    result2 = relocate_predictions(model_dir, [video], dest_dir=None, overwrite=True)
    assert prev.read_text().startswith("predictions,here")
    assert result2["skipped"] == []


def test_relocate_returns_dest_paths(tmp_path):
    """relocate_predictions surfaces the destination paths so the caller can chain a sidecar step."""
    model_dir = tmp_path / "model"
    vids = tmp_path / "v"; vids.mkdir()
    video = vids / "clipX.mp4"; video.write_bytes(b"")
    _seed_model_video_preds(model_dir, ["clipX"], with_labeled_mp4=False)

    result = relocate_predictions(model_dir, [video], dest_dir=None, overwrite=True)
    assert "dest_paths" in result
    assert str(vids / "clipX_lp.csv") in result["dest_paths"]
    assert str(vids / "clipX_lp_pixel_error.csv") in result["dest_paths"]

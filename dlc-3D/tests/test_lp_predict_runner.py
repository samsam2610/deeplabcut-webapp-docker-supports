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
    model_dir = tmp_path / "model"
    dest = tmp_path / "out"
    videos_dir = tmp_path / "vids"; videos_dir.mkdir()
    v1 = videos_dir / "clipA.mp4"; v1.write_bytes(b"")
    v2 = videos_dir / "clipB.mp4"; v2.write_bytes(b"")
    _seed_model_video_preds(model_dir, ["clipA", "clipB"])

    result = relocate_predictions(model_dir, [v1, v2], dest_dir=dest, overwrite=False)

    assert (dest / "clipA.csv").is_file()
    assert (dest / "clipA_pixel_error.csv").is_file()
    assert (dest / "clipA_labeled.mp4").is_file()
    assert (dest / "clipB.csv").is_file()
    assert (dest / "clipB_labeled.mp4").is_file()
    # Source side cleaned up
    assert not (model_dir / "video_preds" / "clipA.csv").exists()
    assert not (model_dir / "video_preds" / "labeled_videos" / "clipA_labeled.mp4").exists()
    assert result["moved"] >= 6
    assert result["skipped"] == []


def test_relocate_per_video_default(tmp_path):
    """dest_dir=None puts each video's outputs in that video's parent folder."""
    model_dir = tmp_path / "model"
    vids_a = tmp_path / "session_a"; vids_a.mkdir()
    vids_b = tmp_path / "session_b"; vids_b.mkdir()
    va = vids_a / "rat1.mp4"; va.write_bytes(b"")
    vb = vids_b / "rat2.mp4"; vb.write_bytes(b"")
    _seed_model_video_preds(model_dir, ["rat1", "rat2"], with_labeled_mp4=False)

    result = relocate_predictions(model_dir, [va, vb], dest_dir=None)

    assert (vids_a / "rat1.csv").is_file()
    assert (vids_a / "rat1_pixel_error.csv").is_file()
    assert (vids_b / "rat2.csv").is_file()
    # Don't cross-contaminate
    assert not (vids_a / "rat2.csv").exists()
    assert not (vids_b / "rat1.csv").exists()
    assert result["dest_dir"] is None
    assert result["skipped"] == []

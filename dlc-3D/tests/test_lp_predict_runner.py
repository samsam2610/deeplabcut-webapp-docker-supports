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

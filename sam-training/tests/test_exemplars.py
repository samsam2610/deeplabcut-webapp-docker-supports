"""The embedder's crop, and keeping the two cameras' banks apart.

The crop was one fixed cam0 rectangle. cam1's pellet sits 177 px right and 62 px
down, so that rectangle frames the wrong part of cam1 entirely — and a bank built
through it would be embedding background.
"""
import numpy as np
import pytest

from src import exemplars, pellet_model as pm


def _cam(cx, cy):
    return pm.CameraModel(cx=cx, cy=cy, half=22, margin=40)


def test_the_offsets_reproduce_the_original_cam0_crop():
    """The offsets are a refactor of a tuned constant, not a retune. If they
    ever stop reproducing it, the exemplar bank silently changes meaning."""
    assert exemplars.crop_for(_cam(416, 388)) == exemplars.CROP


def test_cam1_gets_its_own_crop_from_its_own_centre():
    # Rounded, not truncated: 449.7 - 238 is 211.7, and truncating biases every
    # crop up-and-left by up to a pixel.
    box = exemplars.crop_for(_cam(592.7, 449.7))
    assert box == (212, 482, 497, 697)


def test_the_crop_is_the_same_size_for_every_camera():
    """Different-sized crops would embed to different content scales, so the
    two cameras' similarities would not be comparable."""
    a = exemplars.crop_for(_cam(416, 388))
    b = exemplars.crop_for(_cam(592.7, 449.7))
    assert (a[1] - a[0], a[3] - a[2]) == (b[1] - b[0], b[3] - b[2])


def test_the_crop_follows_a_moved_box():
    """The centre comes from the placed box, so re-placing it moves the crop —
    that is the point of anchoring rather than hard-coding a second rectangle."""
    assert exemplars.crop_for(_cam(400, 380)) != exemplars.crop_for(_cam(416, 388))


def test_a_crop_near_the_edge_stays_inside_the_frame():
    """cv2 slicing a negative start silently wraps, producing a crop from the
    wrong side of the image rather than an error."""
    y0, y1, x0, x1 = exemplars.crop_for(_cam(30, 30), width=800, height=600)
    assert 0 <= y0 < y1 <= 600 and 0 <= x0 < x1 <= 800


def test_an_edge_crop_keeps_its_size():
    a = exemplars.crop_for(_cam(416, 388))
    b = exemplars.crop_for(_cam(30, 30), width=800, height=600)
    assert (b[1] - b[0], b[3] - b[2]) == (a[1] - a[0], a[3] - a[2])


def test_crop_rgb_uses_the_box_it_is_given():
    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    frame[212:482, 497:697] = 255
    out = exemplars.crop_rgb(frame, exemplars.crop_for(_cam(592.7, 449.7)))
    assert out.shape[:2] == (270, 200)
    assert out.min() == 255           # the whole crop landed on the white patch


def test_crop_rgb_defaults_to_the_cam0_rectangle():
    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    assert exemplars.crop_rgb(frame).shape[:2] == (270, 200)


# ── the two banks must not share a cache entry ──────────────────────────────

def test_each_camera_has_its_own_cache_entry(tmp_path):
    """Serving cam0's bank for a cam1 query would score cam1 crops against cam0
    exemplars — a similarity between two different views of the rig, which is
    not a similarity at all."""
    a = exemplars.cache_file("/p", 40, tmp_path, cam="cam0")
    b = exemplars.cache_file("/p", 40, tmp_path, cam="cam1")
    assert a != b


def test_the_camera_is_visible_in_the_cache_filename(tmp_path):
    # These files are inspected by hand when a bank looks wrong.
    assert "cam1" in exemplars.cache_file("/p", 40, tmp_path, cam="cam1").name


def test_a_bank_saved_for_one_camera_is_not_loaded_for_the_other(tmp_path):
    bank = exemplars.Bank(np.zeros((2, 4), dtype=np.float32),
                          np.array(["s", "f"]), np.array(["v", "v"]),
                          np.array([1, 2]))
    exemplars.save(bank, "/p", 40, tmp_path, cam="cam0")
    assert exemplars.load("/p", 40, tmp_path, cam="cam0") is not None
    assert exemplars.load("/p", 40, tmp_path, cam="cam1") is None


def test_the_crop_is_still_part_of_the_cache_key(tmp_path):
    """Changing the crop changes what was embedded, so an old bank must miss."""
    before = exemplars.cache_file("/p", 40, tmp_path, cam="cam0")
    original = exemplars.CROP_OFFSETS
    try:
        exemplars.CROP_OFFSETS = (-200, 40, -90, 110)
        assert exemplars.cache_file("/p", 40, tmp_path, cam="cam0") != before
    finally:
        exemplars.CROP_OFFSETS = original


def test_building_cam1_without_a_camera_model_refuses(monkeypatch, tmp_path):
    """A missing camera must not fall back to cam0's rectangle.

    crop_rgb defaults to CROP when given no box, which is right for a caller
    that has no model at all — but for cam1 it would embed cam0's region of a
    cam1 frame. Every exemplar would be background, the bank would look fine,
    and cam1 similarity would be noise.
    """
    from src import pellet_model as pm
    monkeypatch.setattr(pm, "load", lambda _p: pm.PelletModel())   # no cameras
    with pytest.raises(ValueError, match="cam1"):
        exemplars.build(tmp_path, per_session=1, cam="cam1")


def test_building_cam0_without_a_model_still_uses_the_tuned_rectangle(monkeypatch, tmp_path):
    """cam0's default IS the tuned rectangle, so this stays a working path."""
    from src import pellet_model as pm, tracked
    monkeypatch.setattr(pm, "load", lambda _p: pm.PelletModel())
    monkeypatch.setattr(tracked, "tag_done_videos", lambda _p: [])
    import src.models as models
    monkeypatch.setattr(models, "embed", lambda imgs: np.zeros((0, 8), dtype=np.float32))
    bank = exemplars.build(tmp_path, per_session=1, cam="cam0")
    assert len(bank) == 0

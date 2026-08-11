import json

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from src import rig


def scene(pellet=True, brightness=40):
    """Same synthetic rig as test_ncc: dark frame, black post, bright pellet."""
    img = np.full((600, 800), brightness, dtype=np.uint8)
    img[390:500, 390:410] = 10
    if pellet:
        img[350:385, 370:430] = 235
    return img


def test_canonical_template_is_shipped_and_loadable():
    # The whole design rests on this file existing: per-session derivation was
    # tried twice and broke a different session each time.
    t = rig.canonical_template()
    assert t.ndim == 2 and t.size > 0


def test_quality_is_high_when_the_template_discriminates():
    template = rig.ncc.crop(scene(True), rig.config.PELLET_TEMPLATE_BOX)
    grays = [scene(True), scene(True), scene(False), scene(False)]
    q = rig._quality(template, grays, rig.config.PELLET_SEARCH_BOX)
    assert q > 0.25


def test_quality_is_low_when_every_frame_looks_the_same():
    # A template that matches everything tells you nothing, and must not be
    # mistaken for a good one.
    template = rig.ncc.crop(scene(True), rig.config.PELLET_TEMPLATE_BOX)
    grays = [scene(True) for _ in range(4)]
    assert rig._quality(template, grays, rig.config.PELLET_SEARCH_BOX) < 0.25


def calib(**kw):
    base = dict(video="/v/a.avi", source="canonical", template_frame=-1,
                template_box=(0, 10, 0, 10), search_box=(0, 20, 0, 20),
                aperture_box=(0, 5, 0, 5), score=0.5, n_sampled=32)
    base.update(kw)
    return rig.RigCalibration(**base)


def test_trustworthy_reflects_the_spread_threshold():
    assert calib(score=rig.MIN_SPREAD).trustworthy
    assert not calib(score=rig.MIN_SPREAD - 0.01).trustworthy


def test_calibration_json_round_trips_with_tuple_boxes():
    c = calib()
    back = rig.RigCalibration.from_json(c.to_json())
    assert back == c
    assert isinstance(back.search_box, tuple)


def test_load_template_uses_the_canonical_without_touching_the_video():
    # source="canonical" must not try to open /v/a.avi, which does not exist.
    assert rig.load_template(calib()).ndim == 2


def test_save_and_load_round_trip(tmp_path):
    rig.save(tmp_path, "vid-a", calib(score=0.61))
    got = rig.load(tmp_path, "vid-a")
    assert got is not None and got.score == pytest.approx(0.61)


def test_save_preserves_other_sessions(tmp_path):
    rig.save(tmp_path, "a", calib(score=0.4))
    rig.save(tmp_path, "b", calib(score=0.7))
    assert rig.load(tmp_path, "a").score == pytest.approx(0.4)
    assert rig.load(tmp_path, "b").score == pytest.approx(0.7)


def test_load_missing_key_is_none(tmp_path):
    rig.save(tmp_path, "a", calib())
    assert rig.load(tmp_path, "nope") is None


def test_corrupt_cache_is_a_miss_not_a_crash(tmp_path):
    rig.cache_path(tmp_path).write_text("{ not json")
    assert rig.load(tmp_path, "a") is None


def test_cache_written_by_an_older_schema_is_a_miss(tmp_path):
    # Fields were added when calibration became validate-not-derive; an old
    # entry must re-derive rather than blow up on an unexpected keyword.
    rig.cache_path(tmp_path).write_text(json.dumps(
        {"a": {"video": "/v/a.avi", "template_frame": 3, "score": 0.5}}))
    assert rig.load(tmp_path, "a") is None


def test_save_leaves_no_temp_file(tmp_path):
    rig.save(tmp_path, "a", calib())
    assert not list(tmp_path.glob("*.tmp"))

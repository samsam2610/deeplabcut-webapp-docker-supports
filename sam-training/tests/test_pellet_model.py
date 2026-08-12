import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from src import pellet_model as pm


def patch(bright=True, size=44):
    """Synthetic pellet patch: bright dome on a dark ground."""
    img = np.full((size, size), 20, dtype=np.uint8)
    if bright:
        cv2.circle(img, (size // 2, size // 2), size // 3, 235, -1)
    return img


def test_template_box_is_centred_on_the_position():
    cam = pm.CameraModel(cx=400, cy=380, half=22)
    y0, y1, x0, x1 = cam.template_box
    assert (x0, x1, y0, y1) == (378, 422, 358, 402)


def test_search_box_extends_by_the_margin():
    cam = pm.CameraModel(cx=400, cy=380, half=22, margin=40)
    y0, y1, x0, x1 = cam.search_box
    assert (x1 - x0, y1 - y0) == (124, 124)      # 2*(22+40)


def test_search_box_is_clamped_at_the_frame_edge():
    cam = pm.CameraModel(cx=10, cy=10, half=22, margin=40)
    y0, _, x0, _ = cam.search_box
    assert y0 == 0 and x0 == 0


def test_seed_round_trips_through_base64():
    cam = pm.CameraModel(cx=1, cy=1)
    p = patch()
    cam.set_seed(p, 10)
    assert np.array_equal(cam.seed(), p)
    assert cam.n_samples == 10


def test_camera_without_a_template_scores_sentinel():
    cam = pm.CameraModel(cx=100, cy=100)
    score, _ = pm.match(np.zeros((200, 200), np.uint8), cam)
    assert score == -1.0


def test_build_camera_centres_on_the_median_position():
    patches = [patch() for _ in range(5)]
    positions = [(400, 380), (402, 381), (401, 379), (399, 380), (400, 382)]
    cam = pm.build_camera(patches, positions)
    assert cam.cx == 400 and cam.cy == 380
    assert cam.n_samples == 5


def test_built_template_matches_a_pellet_and_not_a_blank():
    cam = pm.build_camera([patch() for _ in range(3)], [(60, 60)] * 3)
    frame = np.full((140, 140), 20, dtype=np.uint8)
    cv2.circle(frame, (60, 60), 14, 235, -1)
    hit, _ = pm.match(frame, cam)
    miss, _ = pm.match(np.full((140, 140), 20, dtype=np.uint8), cam)
    assert hit > 0.8
    assert hit - miss > 0.3


def test_match_reports_the_patch_centre_not_its_corner():
    # Callers want where the pellet IS. Returning the corner silently offsets
    # every triangulation by half a patch.
    cam = pm.build_camera([patch() for _ in range(3)], [(60, 60)] * 3)
    frame = np.full((140, 140), 20, dtype=np.uint8)
    cv2.circle(frame, (60, 60), 14, 235, -1)
    _, (x, y) = pm.match(frame, cam)
    assert abs(x - 60) <= 2 and abs(y - 60) <= 2


def test_agreement_requires_both_cameras():
    assert pm.agree(0.8, 0.8, 0.55)
    assert not pm.agree(0.8, 0.2, 0.55)      # the single-camera failure mode
    assert not pm.agree(0.2, 0.8, 0.55)


def test_model_json_round_trip(tmp_path):
    m = pm.PelletModel()
    cam = pm.build_camera([patch() for _ in range(2)], [(400, 380)] * 2)
    m.cameras["cam0"] = cam
    m.ref_3d = [1.6, 10.0, 261.7]
    pm.save(tmp_path, m)
    back = pm.load(tmp_path)
    assert back is not None
    assert back.ref_3d == [1.6, 10.0, 261.7]
    assert np.array_equal(back.cameras["cam0"].template_u8(), cam.template_u8())


def test_corrupt_model_is_a_miss_not_a_crash(tmp_path):
    pm.model_path(tmp_path).write_text("{ not json")
    assert pm.load(tmp_path) is None


def test_missing_model_is_none(tmp_path):
    assert pm.load(tmp_path) is None


def test_save_leaves_no_temp_file(tmp_path):
    pm.save(tmp_path, pm.PelletModel())
    assert not list(tmp_path.glob("*.tmp"))


def test_user_corrections_survive_a_round_trip(tmp_path):
    # Corrections are the iteration mechanism; losing them on reload would make
    # the model un-improvable.
    m = pm.PelletModel()
    m.corrections = [{"video": "v.avi", "frame": 100, "cam": "cam0", "x": 411, "y": 388}]
    pm.save(tmp_path, m)
    assert pm.load(tmp_path).corrections[0]["frame"] == 100


def test_sibling_resolves_when_timestamps_differ(tmp_path):
    """cam0 and cam1 do not always share a timestamp -- banh-mi-1 Jul 7 is
    110532 vs 110542. A _cam0_ -> _cam1_ swap silently finds nothing."""
    (tmp_path / "rat_cam0_20260707_110532_5_trig1.avi").write_bytes(b"")
    (tmp_path / "rat_cam1_20260707_110542_5_trig1.avi").write_bytes(b"")
    got = pm.sibling_video(tmp_path / "rat_cam0_20260707_110532_5_trig1.avi")
    assert got is not None and "_cam1_" in got.name


def test_sibling_ignores_a_different_date(tmp_path):
    (tmp_path / "rat_cam0_20260707_110532_5.avi").write_bytes(b"")
    (tmp_path / "rat_cam1_20260708_110542_5.avi").write_bytes(b"")
    assert pm.sibling_video(tmp_path / "rat_cam0_20260707_110532_5.avi") is None


def test_sibling_ignores_a_different_animal(tmp_path):
    (tmp_path / "rat_cam0_20260707_110532_5.avi").write_bytes(b"")
    (tmp_path / "mouse_cam1_20260707_110542_5.avi").write_bytes(b"")
    assert pm.sibling_video(tmp_path / "rat_cam0_20260707_110532_5.avi") is None


# ── the pool: clicks ADD to the seed, they do not replace it ────────────────

def test_clicks_add_to_the_pool_rather_than_replacing_the_seed():
    """Three clicks once wiped a 261-sample template. The seed is the DLC-derived
    starting point; clicks grow the pool."""
    cam = pm.build_camera([patch() for _ in range(261)], [(400, 380)] * 261)
    before = cam.template_u8().copy()
    cam.add_exemplar(patch(bright=False))
    assert cam.seed_n == 261 and len(cam.exemplars) == 1
    assert cam.n_samples == 262
    # one click against 261 seed samples must barely move the template
    assert np.abs(cam.template_u8().astype(int) - before.astype(int)).max() < 6


def test_enough_clicks_do_move_the_template():
    # Otherwise "add more to the pool until it stops missing" would never work.
    cam = pm.build_camera([patch() for _ in range(10)], [(400, 380)] * 10)
    before = cam.template_u8().copy()
    for _ in range(40):
        cam.add_exemplar(patch(bright=False))
    assert np.abs(cam.template_u8().astype(int) - before.astype(int)).max() > 40


def test_seed_weight_lets_clicks_outvote_a_large_seed():
    cam = pm.build_camera([patch() for _ in range(261)], [(400, 380)] * 261)
    cam.seed_weight = 0.01
    before = cam.template_u8().copy()
    for _ in range(5):
        cam.add_exemplar(patch(bright=False))
    assert np.abs(cam.template_u8().astype(int) - before.astype(int)).max() > 40


def test_removing_an_exemplar_restores_the_template():
    cam = pm.build_camera([patch() for _ in range(5)], [(400, 380)] * 5)
    before = cam.template_u8().copy()
    cam.add_exemplar(patch(bright=False))
    cam.exemplars.pop()
    assert np.array_equal(cam.template_u8(), before)


def test_exemplars_survive_a_json_round_trip(tmp_path):
    m = pm.PelletModel()
    cam = pm.build_camera([patch() for _ in range(3)], [(400, 380)] * 3)
    cam.add_exemplar(patch(), video="v.avi", frame=42, x=411, y=388)
    m.cameras["cam0"] = cam
    pm.save(tmp_path, m)
    back = pm.load(tmp_path).cameras["cam0"]
    assert back.seed_n == 3 and len(back.exemplars) == 1
    assert back.exemplars[0].frame == 42
    assert np.array_equal(back.template_u8(), cam.template_u8())


def test_a_camera_with_only_clicks_still_has_a_template():
    cam = pm.CameraModel(cx=400, cy=380)
    assert cam.template() is None
    cam.add_exemplar(patch())
    assert cam.template_u8() is not None


def test_exemplar_carries_its_source_so_deletion_can_find_it():
    cam = pm.build_camera([patch() for _ in range(3)], [(400, 380)] * 3)
    cam.add_exemplar(patch(), video="/v/a.avi", frame=99, x=400, y=380)
    ex = cam.exemplars[0]
    assert ex.video == "/v/a.avi" and ex.frame == 99

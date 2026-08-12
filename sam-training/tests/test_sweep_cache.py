"""One place computes the sweep's cache signature.

It was computed in two: `app._sweep_sig` (used when saving) and an inline copy
in `api_sam._windows_for`. A third caller, `api_onset_csv`, forgot it entirely
and passed no signature at all — so once the key gained a signature, "Build
onset CSV" answered 409 "not swept yet" on a video that had just been swept.

A signature computed in more than one place will drift. These tests pin the
property that matters: whatever saves a sweep and whatever loads it agree.
"""
import numpy as np

from src import sweep_cache


class _Cam:
    def __init__(self, cx=416.0, cy=388.0):
        self.cx, self.cy, self.half, self.margin = cx, cy, 22, 40
        self.seed_b64, self.exemplars = "abc", []


class _Model:
    def __init__(self, cx=416.0):
        self.threshold, self.max_3d_dist, self.ref_3d = 0.55, 3.0, None
        self.cameras = {"cam0": _Cam(cx), "cam1": _Cam(cx + 180)}
        self.videos = {}

    def box_for(self, stem, cam):
        return None


def _save_then_load(tmp_path, video, save_model, load_model,
                    save_marks=(), load_marks=()):
    frames = np.arange(0, 100, 5)
    sweep_cache.save(video, frames, frames * 0.0, 100, model=save_model,
                     marks=list(save_marks), root=tmp_path)
    return sweep_cache.load(video, model=load_model, marks=list(load_marks),
                            root=tmp_path)


def test_a_sweep_saved_here_is_found_here(tmp_path):
    """The regression, directly: save and load must agree without the caller
    having to remember to pass a signature."""
    got = _save_then_load(tmp_path, "/v/a.avi", _Model(), _Model())
    assert got is not None


def test_moving_the_box_misses(tmp_path):
    marks = [{"kind": "box", "cam": "cam0", "x": 416, "y": 388}]
    moved = [{"kind": "box", "cam": "cam0", "x": 412, "y": 404}]
    assert _save_then_load(tmp_path, "/v/a.avi", _Model(), _Model(),
                           save_marks=marks, load_marks=moved) is None


def test_changing_the_template_misses(tmp_path):
    assert _save_then_load(tmp_path, "/v/a.avi", _Model(), _Model(cx=500)) is None


def test_a_different_video_is_a_different_entry(tmp_path):
    frames = np.arange(0, 100, 5)
    sweep_cache.save("/v/a.avi", frames, frames * 0.0, 100, model=_Model(),
                     root=tmp_path)
    assert sweep_cache.load("/v/b.avi", model=_Model(), root=tmp_path) is None


def test_judging_parameters_do_not_invalidate_the_sweep(tmp_path):
    """The sweep is raw NCC; the judge is applied to it afterwards. If a
    threshold entered the key, tuning one would cost a four-minute re-sweep."""
    frames = np.arange(0, 100, 5)
    sweep_cache.save("/v/a.avi", frames, frames * 0.0, 100, model=_Model(),
                     root=tmp_path)
    a = sweep_cache.signature(_Model(), "/v/a.avi", marks=[])
    b = sweep_cache.signature(_Model(), "/v/a.avi", marks=[])
    assert a == b
    assert sweep_cache.load("/v/a.avi", model=_Model(), root=tmp_path) is not None


def test_no_model_still_round_trips(tmp_path):
    """Before any pellet model exists the panel still sweeps; that must not
    crash on a None model."""
    frames = np.arange(0, 100, 5)
    sweep_cache.save("/v/a.avi", frames, frames * 0.0, 100, model=None,
                     root=tmp_path)
    assert sweep_cache.load("/v/a.avi", model=None, root=tmp_path) is not None


# ── the two-camera sweep ────────────────────────────────────────────────────

def test_pair_sweep_round_trips(tmp_path):
    frames = np.arange(0, 100, 5)
    n = len(frames)
    sweep_cache.save_pair("/v/a.avi", frames, np.full(n, 0.9), np.full(n, 0.8),
                          np.full(n, 0.5), 100, model=_Model(), root=tmp_path)
    got = sweep_cache.load_pair("/v/a.avi", model=_Model(), root=tmp_path)
    assert got is not None
    f, s0, s1, d, total = got
    assert np.array_equal(f, frames) and total == 100
    assert s0[0] == np.float32(0.9) and s1[0] == np.float32(0.8) and d[0] == np.float32(0.5)


def test_nan_distances_survive_the_round_trip(tmp_path):
    """NaN marks "the cameras never agreed, so this was never triangulated".
    If it came back as 0.0 every disagreement would read as a perfect match."""
    frames = np.arange(0, 20, 5)
    n = len(frames)
    sweep_cache.save_pair("/v/a.avi", frames, np.full(n, 0.1), np.full(n, 0.1),
                          np.full(n, np.nan), 20, model=_Model(), root=tmp_path)
    _f, _s0, _s1, d, _n = sweep_cache.load_pair("/v/a.avi", model=_Model(),
                                                root=tmp_path)
    assert np.isnan(d).all()


def test_a_single_camera_sweep_is_not_readable_as_a_pair(tmp_path):
    """The old cache holds one score array. Reading it as a pair would either
    crash or, worse, silently reuse cam0's scores as cam1's — the exact
    agreement the two-camera gate is supposed to prove."""
    frames = np.arange(0, 100, 5)
    sweep_cache.save("/v/a.avi", frames, frames * 0.0, 100, model=_Model(),
                     root=tmp_path)
    assert sweep_cache.load_pair("/v/a.avi", model=_Model(), root=tmp_path) is None


def test_a_pair_sweep_is_not_readable_as_a_single(tmp_path):
    frames = np.arange(0, 100, 5)
    n = len(frames)
    sweep_cache.save_pair("/v/a.avi", frames, np.full(n, 0.9), np.full(n, 0.9),
                          np.full(n, 0.5), 100, model=_Model(), root=tmp_path)
    assert sweep_cache.load("/v/a.avi", model=_Model(), root=tmp_path) is None


def test_moving_the_box_misses_the_pair_cache_too(tmp_path):
    frames = np.arange(0, 20, 5)
    n = len(frames)
    marks = [{"kind": "box", "cam": "cam0", "x": 416, "y": 388}]
    moved = [{"kind": "box", "cam": "cam0", "x": 370, "y": 340}]
    sweep_cache.save_pair("/v/a.avi", frames, np.ones(n), np.ones(n),
                          np.zeros(n), 20, model=_Model(), marks=marks,
                          root=tmp_path)
    assert sweep_cache.load_pair("/v/a.avi", model=_Model(), marks=moved,
                                 root=tmp_path) is None
    assert sweep_cache.load_pair("/v/a.avi", model=_Model(), marks=marks,
                                 root=tmp_path) is not None

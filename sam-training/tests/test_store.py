import time

import numpy as np

from src import store


def test_sweep_round_trips(tmp_path):
    frames = np.arange(0, 1000, 5)
    scores = np.random.default_rng(0).random(len(frames)).astype(np.float32)
    store.save_sweep("/videos/a.avi", 5, frames, scores, 1000, root=tmp_path)
    got = store.load_sweep("/videos/a.avi", 5, root=tmp_path)
    assert got is not None
    assert np.array_equal(got[0], frames) and got[2] == 1000


def test_cache_miss_returns_none(tmp_path):
    assert store.load_sweep("/videos/never.avi", 5, root=tmp_path) is None


def test_different_stride_is_a_different_cache_entry(tmp_path):
    # Serving a stride-5 trace to a stride-1 request would silently mislabel
    # every frame index on the timeline.
    frames = np.arange(0, 100, 5)
    store.save_sweep("/v/a.avi", 5, frames, frames * 0.0, 100, root=tmp_path)
    assert store.load_sweep("/v/a.avi", 1, root=tmp_path) is None
    assert store.load_sweep("/v/a.avi", 5, root=tmp_path) is not None


def test_corrupt_cache_is_a_miss_not_a_crash(tmp_path):
    path = store.cache_file("/v/a.avi", 5, root=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not an npz")
    assert store.load_sweep("/v/a.avi", 5, root=tmp_path) is None


def test_save_leaves_no_temp_file(tmp_path):
    store.save_sweep("/v/a.avi", 5, np.arange(3), np.zeros(3), 3, root=tmp_path)
    assert not list(tmp_path.glob("*.tmp.npz"))


def _wait(job, timeout=5.0):
    end = time.time() + timeout
    while job.state == "running" and time.time() < end:
        time.sleep(0.01)
    return job


def test_job_runs_and_reports_done():
    reg = store.JobRegistry()
    job = _wait(reg.start("t", lambda j: 42))
    assert job.state == "done" and job.result == 42 and job.progress == 1.0


def test_job_failure_is_captured_not_raised():
    reg = store.JobRegistry()

    def boom(job):
        raise ValueError("nope")

    job = _wait(reg.start("t", boom))
    assert job.state == "error" and "nope" in job.message


def test_job_progress_is_visible_to_the_caller():
    reg = store.JobRegistry()

    def slow(job):
        job.progress = 0.5
        time.sleep(0.05)
        return None

    job = reg.start("t", slow)
    time.sleep(0.02)
    assert job.progress == 0.5
    _wait(job)


def test_prune_keeps_running_jobs():
    reg = store.JobRegistry()
    done = _wait(reg.start("t", lambda j: 1))
    done.started_at = 0.0
    reg.prune(older_than=1.0)
    assert reg.get(done.id) is None


# ── the cache must not survive a detector change ────────────────────────────

def test_signature_changes_the_cache_key():
    """Moving the box must MISS the cache.

    The key was (path, stride) only, so after moving the box a sweep returned
    the previous result instantly and the placement had no effect at all —
    silently, and looking like success.
    """
    a = store.cache_key("/v/a.avi", 5, sig="box=416,388")
    b = store.cache_key("/v/a.avi", 5, sig="box=412,404")
    assert a != b


def test_same_signature_is_the_same_key():
    a = store.cache_key("/v/a.avi", 5, sig="box=416,388")
    b = store.cache_key("/v/a.avi", 5, sig="box=416,388")
    assert a == b


def test_signature_is_optional_for_callers_that_have_none():
    assert store.cache_key("/v/a.avi", 5) == store.cache_key("/v/a.avi", 5)


def test_a_sweep_saved_under_one_signature_is_not_read_under_another(tmp_path):
    frames = np.arange(0, 50, 5)
    store.save_sweep("/v/a.avi", 5, frames, frames * 0.0, 50,
                     root=tmp_path, sig="box=416,388")
    assert store.load_sweep("/v/a.avi", 5, root=tmp_path, sig="box=416,388") is not None
    assert store.load_sweep("/v/a.avi", 5, root=tmp_path, sig="box=412,404") is None


def test_model_signature_tracks_every_field_that_changes_the_result():
    from src import pellet_model as pm
    base = pm.PelletModel()
    base.cameras["cam0"] = pm.CameraModel(cx=416, cy=388, half=22, margin=40)
    first = store.model_signature(base, "vid")

    moved = pm.PelletModel()
    moved.cameras["cam0"] = pm.CameraModel(cx=412, cy=404, half=22, margin=40)
    assert store.model_signature(moved, "vid") != first

    resized = pm.PelletModel()
    resized.cameras["cam0"] = pm.CameraModel(cx=416, cy=388, half=30, margin=40)
    assert store.model_signature(resized, "vid") != first

    wider = pm.PelletModel()
    wider.cameras["cam0"] = pm.CameraModel(cx=416, cy=388, half=22, margin=60)
    assert store.model_signature(wider, "vid") != first

    thr = pm.PelletModel()
    thr.cameras["cam0"] = pm.CameraModel(cx=416, cy=388, half=22, margin=40)
    thr.threshold = 0.7
    assert store.model_signature(thr, "vid") != first


def test_signature_follows_the_per_video_box():
    from src import pellet_model as pm
    m = pm.PelletModel()
    m.cameras["cam0"] = pm.CameraModel(cx=416, cy=388)
    before = store.model_signature(m, "vid")
    m.videos["vid"] = pm.VideoBox(cx0=412, cy0=404)
    assert store.model_signature(m, "vid") != before
    # a DIFFERENT video keeps its own signature
    assert store.model_signature(m, "other") == before


def test_signature_prefers_the_sidecar_marks_over_the_legacy_video_box(tmp_path):
    """The onset CSV is the source of truth for the box.

    A VideoBox with coordinates is a leftover from before placement moved into
    the sidecar. If the signature read that while the detector reads the CSV,
    the cache key would describe a box nobody is using.
    """
    from src import pellet_model as pm
    m = pm.PelletModel()
    m.cameras["cam0"] = pm.CameraModel(cx=416, cy=388)
    m.videos["vid"] = pm.VideoBox(cx0=368, cy0=333)     # stale
    from_legacy = store.model_signature(m, "vid")
    from_marks = store.model_signature(
        m, "vid", marks=[{"kind": "box", "cam": "cam0", "x": 412, "y": 404}])
    assert from_marks != from_legacy


def test_signature_with_marks_ignores_pellet_rows():
    from src import pellet_model as pm
    m = pm.PelletModel()
    m.cameras["cam0"] = pm.CameraModel(cx=416, cy=388)
    box_only = [{"kind": "box", "cam": "cam0", "x": 412, "y": 404}]
    with_pellets = box_only + [{"kind": "pellet", "cam": "cam0", "x": 500, "y": 500}]
    assert store.model_signature(m, "vid", marks=box_only) == \
           store.model_signature(m, "vid", marks=with_pellets)

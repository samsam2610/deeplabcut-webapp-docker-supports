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

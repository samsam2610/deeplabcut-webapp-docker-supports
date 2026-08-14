"""Stage 0+1 end to end, from a cached sweep to trial windows.

Three endpoints needed this — the debug panel, /windows and /onset-csv — and
each grew its own copy. The last time they diverged, one forgot the cache
signature and "Build onset CSV" answered 409 on a freshly swept video. This
module is the single path; these tests cover the composition, not the pieces.
"""
import csv

import numpy as np
import pytest

from src import judging, onset_csv, pellet_model as pm, pipeline, sweep_cache


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    m = pm.PelletModel()
    m.cameras["cam0"] = pm.CameraModel(cx=416, cy=388, half=22, margin=40,
                                       seed_b64="x", seed_n=261)
    m.cameras["cam1"] = pm.CameraModel(cx=593, cy=450, half=22, margin=40,
                                       seed_b64="x", seed_n=261)
    m.ref_3d = [1.68, 11.09, 278.81]
    pm.save(root, m)
    return root


@pytest.fixture
def video(tmp_path):
    vid = tmp_path / "banh_cam0_20260707_110532.avi"
    vid.write_bytes(b"not really a video")
    with open(vid.with_suffix(".csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "frame_number", "frame_line_status", "note"])
        for frame, note in [(2000, "f"), (4000, "s")]:
            w.writerow([frame / 200.0, frame, "0", note])
    return vid


def _cache_a_pair(video, project, root, *, armed_from, armed_to,
                  score=0.9, dist=0.5, n=5000):
    """A sweep where one stretch looks like a pellet and the rest does not."""
    model = pm.load(project)
    frames = np.arange(0, n, 5)
    s0 = np.where((frames >= armed_from) & (frames < armed_to), score, 0.1)
    s1 = np.where((frames >= armed_from) & (frames < armed_to), score, 0.1)
    d = np.where((frames >= armed_from) & (frames < armed_to), dist, np.nan)
    sweep_cache.save_pair(video, frames, s0, s1, d, n, model=model,
                          marks=onset_csv.read_marks(video), root=root)
    return frames


def test_windows_come_back_from_a_cached_pair_sweep(tmp_path, project, video):
    _cache_a_pair(video, project, tmp_path, armed_from=1000, armed_to=1900)
    out = pipeline.windows_for(project, video, root=tmp_path)
    assert out is not None
    assert [w.outcome for w in out.windows] == ["f"]
    assert out.windows[0].end == 2000


def test_not_swept_yet_is_none_not_an_empty_result(tmp_path, project, video):
    """An empty window list and "never swept" mean different things to the
    panel: one offers a sweep, the other says the video has no trials."""
    assert pipeline.windows_for(project, video, root=tmp_path) is None


def test_the_3d_gate_removes_frames_both_cameras_liked(tmp_path, project, video):
    """The reported failure: frame 27591 scored 0.55/0.67 — both cameras above
    threshold — and triangulated 8.29 away from the pellet."""
    _cache_a_pair(video, project, tmp_path, armed_from=1000, armed_to=1900,
                  score=0.9, dist=8.29)
    out = pipeline.windows_for(project, video, root=tmp_path)
    assert out.windows == []


def test_retuning_the_gate_re_judges_without_touching_the_cache(tmp_path, project, video):
    _cache_a_pair(video, project, tmp_path, armed_from=1000, armed_to=1900,
                  score=0.9, dist=3.0)
    assert pipeline.windows_for(project, video, root=tmp_path).windows == []
    judging.save(project, judging.Judge(max_3d_dist=4.0))
    assert pipeline.windows_for(project, video, root=tmp_path).windows != []


def test_a_camera_that_disagrees_arms_nothing(tmp_path, project, video):
    model = pm.load(project)
    frames = np.arange(0, 5000, 5)
    hot = (frames >= 1000) & (frames < 1900)
    sweep_cache.save_pair(video, frames, np.where(hot, 0.9, 0.1),
                          np.full(len(frames), 0.1),      # cam1 never agrees
                          np.where(hot, 0.5, np.nan), 5000, model=model,
                          root=tmp_path)
    assert pipeline.windows_for(project, video, root=tmp_path).windows == []


def test_the_placed_box_reaches_the_detector(tmp_path, project, video):
    """The gate blocks sweeping until a box is placed; that box must be the one
    the sweep uses. sweep_pair read model.cameras straight through, so the
    placement guarded a value nothing consumed."""
    build = onset_csv.Build()
    build.add_mark(1, onset_csv.MARK_BOX, "cam0", 370.0, 340.0)
    build.add_mark(1, onset_csv.MARK_BOX, "cam1", 522.0, 396.0)
    onset_csv.write(video, build)
    resolved = pipeline.model_for(project, video)
    assert (resolved.cameras["cam0"].cx, resolved.cameras["cam0"].cy) == (370.0, 340.0)
    assert (resolved.cameras["cam1"].cx, resolved.cameras["cam1"].cy) == (522.0, 396.0)


def test_the_trace_reports_the_weaker_camera(tmp_path, project, video):
    """min(s0, s1) is the quantity that has to clear the threshold. Showing
    cam0 alone would draw a confident line for a frame cam1 rejected."""
    model = pm.load(project)
    frames = np.arange(0, 100, 5)
    n = len(frames)
    sweep_cache.save_pair(video, frames, np.full(n, 0.9), np.full(n, 0.3),
                          np.full(n, 0.5), 100, model=model, root=tmp_path)
    out = pipeline.windows_for(project, video, root=tmp_path)
    assert out.score.max() == pytest.approx(0.3, abs=1e-6)


# ── one index base ──────────────────────────────────────────────────────────
#
# The sweep counts video frames from 0; the companion CSV, the tags, the onset
# sidecar and motion3d all count from 1. build_windows was comparing armed
# intervals in the first base against outcome markers in the second, and a 3D
# run reported 0-based frames in its JSON while writing 1-based ones to its
# sidecar — two artefacts of one run disagreeing about which frame is which.
#
# Everything the pipeline hands out is now 1-based CSV frame_number. Only the
# cv2 seek converts back.

def test_the_pipeline_reports_one_based_frames(tmp_path, project, video):
    """The first sampled frame is video index 0, which is frame_number 1."""
    _cache_a_pair(video, project, tmp_path, armed_from=1000, armed_to=1900)
    out = pipeline.windows_for(project, video, root=tmp_path)
    assert int(out.frames[0]) == 1


def test_armed_intervals_and_the_outcome_marker_share_a_base(tmp_path, project, video):
    """A pellet present right up to the marker must arm THROUGH the marker.

    With the sweep 0-based and the marker 1-based it stopped one frame short,
    and every armed interval was silently a frame adrift of the trial it
    belonged to.
    """
    import numpy as np
    model = pm.load(project)
    frames = np.arange(0, 5000, 5)
    hot = frames >= 1000                      # present from 1000 to the end
    sweep_cache.save_pair(video, frames, np.where(hot, 0.9, 0.1),
                          np.where(hot, 0.9, 0.1),
                          np.where(hot, 0.5, np.nan), 5000, model=model,
                          root=tmp_path)
    w = [x for x in pipeline.windows_for(project, video, root=tmp_path).windows
         if x.end == 2000][0]
    assert max(iv.end for iv in w.armed) == 2000, \
        "armed must reach the marker, not stop a frame short"


def test_a_candidate_frame_is_a_companion_csv_frame_number(tmp_path, project, video):
    """The onset at companion frame N must be findable as candidate N."""
    _cache_a_pair(video, project, tmp_path, armed_from=1000, armed_to=1900)
    out = pipeline.windows_for(project, video, root=tmp_path)
    cands = out.windows[0].candidate_frames()
    assert min(cands) >= 1, "frame_number is 1-based, so 0 is not a frame"


# ── the 3D reference point ──────────────────────────────────────────────────
#
# ref_3d was a project-level constant, but a 3D coordinate only means anything
# in the frame of the calibration that produced it. Switching banh-mi-1 Jul 7
# from khoai-lang's calibration to its own moved the triangulated pellet from
# 0.48 to 29.30 away from the stored ref — every pellet would have been rejected
# by a 2.0 gate.
#
# The human already places the box on the stationary pellet in both cameras.
# Triangulating THAT with the video's own calibration gives the reference in the
# right frame for free, and it cannot go stale.

class _Cal:
    def triangulate(self, p0, p1):
        import numpy as np
        a = np.asarray(p0, float).reshape(-1, 2)
        b = np.asarray(p1, float).reshape(-1, 2)
        return np.column_stack([a[:, 0], a[:, 1], b[:, 0]])   # deterministic stand-in


def test_the_reference_comes_from_the_placed_box(tmp_path, project, video):
    build = onset_csv.Build()
    build.add_mark(1, onset_csv.MARK_BOX, "cam0", 419.0, 385.5)
    build.add_mark(1, onset_csv.MARK_BOX, "cam1", 591.9, 450.1)
    onset_csv.write(video, build)
    m = pipeline.with_reference(pm.load(project), _Cal(),
                                onset_csv.read_marks(video))
    assert [round(v, 1) for v in m.ref_3d] == [419.0, 385.5, 591.9]


def test_without_a_placed_box_the_stored_reference_is_kept(tmp_path, project, video):
    """Sweeping is gated on a placed box, so this is a belt-and-braces path —
    but inventing a reference from nothing would be far worse than keeping one."""
    m = pipeline.with_reference(pm.load(project), _Cal(), [])
    assert m.ref_3d == [1.68, 11.09, 278.81]


def test_one_camera_placed_is_not_enough(tmp_path, project, video):
    marks = [{"frame": 1, "kind": "box", "cam": "cam0", "x": 419.0, "y": 385.5}]
    m = pipeline.with_reference(pm.load(project), _Cal(), marks)
    assert m.ref_3d == [1.68, 11.09, 278.81]


def test_deriving_the_reference_does_not_mutate_the_project_model(tmp_path, project, video):
    base = pm.load(project)
    marks = [{"frame": 1, "kind": "box", "cam": "cam0", "x": 419.0, "y": 385.5},
             {"frame": 1, "kind": "box", "cam": "cam1", "x": 591.9, "y": 450.1}]
    pipeline.with_reference(base, _Cal(), marks)
    assert base.ref_3d == [1.68, 11.09, 278.81]


# ── the reference comes from the DETECTED pellet, not the click ─────────────
#
# eggtart-2 Jul 10: 151 trials, one window. Detections were fine — 22% of
# samples cleared both cameras, epipolar residual 0.29 px, so the calibration
# described the pair almost perfectly — but every detection sat 2.93 from the
# reference and the 2.0 gate rejected the lot.
#
# The reference was the triangulated CLICK. A click is accurate enough to aim a
# search box with a 40 px margin; it is not accurate enough to be the origin
# that a 2.0 gate measures from. Taking the median of the detections instead:
# median distance 2.93 -> 0.52, and 0% -> 95% inside the gate.

def test_the_reference_is_the_median_of_the_detections():
    pts = [(1.0, 9.0, 249.0), (1.5, 10.0, 250.0), (1.2, 9.8, 249.9)]
    got = pipeline.reference_from_points(pts, minimum=3)
    assert [round(v, 2) for v in got] == [1.2, 9.8, 249.9]


def test_a_few_wild_detections_do_not_move_it():
    """Median, not mean: a paw or the vane triangulating somewhere absurd must
    not drag the origin with it."""
    pts = [(1.0, 9.0, 249.0)] * 9 + [(500.0, 500.0, 500.0)]
    got = pipeline.reference_from_points(pts, minimum=3)
    assert got[0] < 2.0 and got[2] < 260.0


def test_too_few_detections_yields_none():
    """None means "fall back to the click" — better an imperfect origin than one
    derived from two frames that happened to match."""
    assert pipeline.reference_from_points([(1.0, 2.0, 3.0)], minimum=5) is None
    assert pipeline.reference_from_points([], minimum=5) is None


def test_the_click_is_still_the_fallback(tmp_path, project, video):
    """A session where nothing confident is found must still sweep, using the
    box the human placed."""
    m = pipeline.with_reference(pm.load(project), _Cal(),
                                [{"frame": 1, "kind": "box", "cam": "cam0",
                                  "x": 419.0, "y": 385.5},
                                 {"frame": 1, "kind": "box", "cam": "cam1",
                                  "x": 591.9, "y": 450.1}],
                                detected=None)
    assert [round(v, 1) for v in m.ref_3d] == [419.0, 385.5, 591.9]


def test_a_detected_reference_wins_over_the_click(tmp_path, project, video):
    m = pipeline.with_reference(pm.load(project), _Cal(),
                                [{"frame": 1, "kind": "box", "cam": "cam0",
                                  "x": 419.0, "y": 385.5},
                                 {"frame": 1, "kind": "box", "cam": "cam1",
                                  "x": 591.9, "y": 450.1}],
                                detected=(1.24, 9.77, 249.89))
    assert [round(v, 2) for v in m.ref_3d] == [1.24, 9.77, 249.89]

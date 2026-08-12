"""The parameters that decide what counts as a candidate frame.

These were compiled-in constants, each tuned once against one session. They are
now per-project and editable from the panel, because the right value is a
property of the rig and the animal, not of the code.

They are applied to the sweep's raw NCC trace, never to the sweep itself, so
they are deliberately ABSENT from the sweep cache key: re-judging is instant and
changing a threshold must never cost a four-minute re-sweep.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from . import intervals

FILENAME = "sam_training_judge.json"

# Below min_candidates a trial is skipped entirely. 30 armed frames at stride 5
# is 150 frames of video — less than that and there is nothing to rank.
MIN_CANDIDATES = 30

# Per-camera NCC a match must reach. 0.55 rather than the single-camera path's
# 0.50: with two cameras and a 3D gate behind it, this no longer has to be the
# only defence, so it can sit where the pooled template actually separates.
MATCH_THRESHOLD = 0.55

# Max distance, in the calibration's units, from the project's reference pellet
# point. Real pellets measured <= 1.03; the frame that exposed the original
# single-camera bug scored 0.79/0.74 in the two views and triangulated to 3.85,
# so this is the gate that rejected it. Frame 27591 of banh-mi-1 Jul 7 — the
# reported one — scores 0.55/0.67 and triangulates to 8.29.
MAX_3D_DIST = 2.0

# How far off cam0's epipolar line the cam1 PAW centroid may sit before the two
# views are judged to be looking at different paws.
#
# Measured on the REAL quantity: SAM mask centroids over 55 banh-mi-1 Jul 2
# frames where both views verifiably picked the correct paw (checked against the
# labels). With that session's own calibration, p50 3.39 px and p95 17.80 px, so
# 20 px keeps 98.2%.
#
# Two earlier attempts got this wrong, both by measuring a stand-in:
#
#   * `Left-Paw` gave 20 px, but it is a DECOY placed randomly to stop DLC
#     labelling that paw, so it measured random placement rather than geometry.
#   * the centroid of the real digit joints gave 15 px — anatomically
#     corresponding, but a SAM mask includes the forearm and each view sees a
#     different amount of it, which costs about 2x (p95 8.83 -> 17.80).
#
# Dwarfing both: the WRONG CALIBRATION. The same verified-correct pairs score
# p50 27.8 px under another session's calibration against 0.78 px under their
# own. See stereo.find_for_video.
MAX_EPI_PX = 20.0


@dataclass(frozen=True)
class Judge:
    threshold: float = MATCH_THRESHOLD
    min_run: int = intervals.MIN_RUN_SAMPLES
    lookback: int = intervals.MAX_LOOKBACK
    min_candidates: int = MIN_CANDIDATES
    guard: int = intervals.TRIAL_GUARD
    max_3d_dist: float = MAX_3D_DIST
    max_epi_px: float = MAX_EPI_PX

    def to_dict(self) -> dict:
        return asdict(self)


def _num(raw, default, cast):
    """A blank or unparsable field means "leave it alone", not zero.

    The panel sends "" for a cleared input; coercing that to 0 would set a
    threshold of 0 (everything is a pellet) or a lookback of 0 (nothing is
    searchable) from a stray keystroke.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return default


def _int(raw, default):
    """Truncate toward zero, via float.

    Plain ``int("6.7")`` raises, which would silently reset the field to its
    default; the panel's mirror truncates, and the two must agree.
    """
    value = _num(raw, None, float)
    return default if value is None else int(value)


def from_dict(data) -> Judge:
    """Build a Judge from panel/JSON input, clamping rather than rejecting.

    Clamping (not rejecting) so the panel and the backend cannot disagree: what
    is stored is what is applied, and the panel re-reads it after saving.
    """
    d = dict(data or {})
    base = Judge()
    threshold = min(1.0, max(0.0, _num(d.get("threshold"), base.threshold, float)))
    max_3d = max(0.0, _num(d.get("max_3d_dist"), base.max_3d_dist, float))
    max_epi = max(0.0, _num(d.get("max_epi_px"), base.max_epi_px, float))
    min_run = max(1, _int(d.get("min_run"), base.min_run))
    lookback = max(1, _int(d.get("lookback"), base.lookback))
    min_candidates = max(0, _int(d.get("min_candidates"), base.min_candidates))
    guard = max(0, _int(d.get("guard"), base.guard))
    return Judge(threshold=threshold, min_run=min_run, lookback=lookback,
                 min_candidates=min_candidates, max_3d_dist=max_3d,
                 max_epi_px=max_epi,
                 # Reaching further back than the window opens is not a state
                 # the panel should be able to describe.
                 guard=min(guard, lookback))


def path_for(project_path) -> Path:
    return Path(project_path) / FILENAME


def load(project_path) -> Judge:
    path = path_for(project_path)
    if not path.is_file():
        return Judge()
    try:
        return from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return Judge()          # a corrupt file must not block the panel


def save(project_path, judge: Judge) -> Path:
    path = path_for(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(judge.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


# ── applying it ─────────────────────────────────────────────────────────────
#
# One place, so the debug panel in app.py and the card's /windows can never
# judge the same trace differently.


def armed(frames, scores, judge: Judge):
    """Single-camera path. Kept for the legacy trace only — it decides presence
    from the best correlation anywhere in one band, which is what let a paw
    score 0.85 with no pellet on the frame."""
    return intervals.present_intervals(frames, scores,
                                       threshold=judge.threshold,
                                       min_run=judge.min_run)


def decide_pair(score0, score1, dist3d, judge: Judge):
    """The three-way test, as a per-sample mask.

    Applied HERE rather than during the sweep so the stored sweep stays raw
    scores: retuning either threshold re-judges instantly instead of costing
    another seven-minute pass over both videos.
    """
    from . import sweep2
    return sweep2.decide(score0, score1, dist3d, judge.threshold,
                         judge.max_3d_dist)


def paw_pair_ok(epi_px, judge: Judge) -> bool:
    """Are the two views looking at the same paw?

    None means SAM found no reaching paw in one view — there is no
    correspondence to check, so it cannot pass. NaN likewise. Both are guarded
    here rather than at the call sites: `None <= 15` raises, and `nan <= 15` is
    False by luck rather than by intent.
    """
    import math
    if epi_px is None:
        return False
    try:
        v = float(epi_px)
    except (TypeError, ValueError):
        return False
    return not math.isnan(v) and v <= judge.max_epi_px


def armed_pair(frames, score0, score1, dist3d, judge: Judge):
    return intervals.intervals_from_mask(
        frames, decide_pair(score0, score1, dist3d, judge), judge.min_run)


def build(trials, ivs, judge: Judge):
    return intervals.build_windows(trials, ivs, max_lookback=judge.lookback,
                                   min_candidates=judge.min_candidates,
                                   guard=judge.guard)

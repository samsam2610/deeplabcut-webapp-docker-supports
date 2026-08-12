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


@dataclass(frozen=True)
class Judge:
    threshold: float = intervals.PRESENT_THRESHOLD
    min_run: int = intervals.MIN_RUN_SAMPLES
    lookback: int = intervals.MAX_LOOKBACK
    min_candidates: int = MIN_CANDIDATES
    guard: int = intervals.TRIAL_GUARD

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
    min_run = max(1, _int(d.get("min_run"), base.min_run))
    lookback = max(1, _int(d.get("lookback"), base.lookback))
    min_candidates = max(0, _int(d.get("min_candidates"), base.min_candidates))
    guard = max(0, _int(d.get("guard"), base.guard))
    return Judge(threshold=threshold, min_run=min_run, lookback=lookback,
                 min_candidates=min_candidates,
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
    return intervals.present_intervals(frames, scores,
                                       threshold=judge.threshold,
                                       min_run=judge.min_run)


def build(trials, ivs, judge: Judge):
    return intervals.build_windows(trials, ivs, max_lookback=judge.lookback,
                                   min_candidates=judge.min_candidates,
                                   guard=judge.guard)

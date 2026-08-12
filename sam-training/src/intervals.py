"""Pure signal → interval logic for the pellet trace, and window construction.

No OpenCV, no video, no I/O — everything here is testable from arrays, which is
what keeps the fiddly debounce/edge rules honest.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# NCC above this = the pellet template matches = pellet sitting on the pedestal.
# Measured separation across 3 animals and 2 months: present ~0.76-0.82,
# absent ~0.34-0.50. Set at the low end of the gap on purpose — at the onset the
# paw is closing over the pellet and partially occluding the template, which
# drags the score down (median 0.64 at the tag vs 0.79 twenty frames later).
# Tuned against the worst-case session: 0.55 loses 12 of 82 onsets, 0.50 loses 0.
PRESENT_THRESHOLD = 0.50

# A state flip must persist this many CONSECUTIVE samples to count. The paw and
# the rat's body transiently occlude the pedestal, and the white reload vane
# sweeps through; without debouncing every one of those is a spurious edge.
#
# At stride 5 this is 30 frames (0.15s). It was 20 samples (100 frames) and that
# was far too aggressive — it eroded short armed stretches entirely and cost 12
# of 82 onsets on the worst-case session.
MIN_RUN_SAMPLES = 6

# How far back a window reaches from its outcome marker. Deliberately equal to
# notes.MAX_TRIAL_FRAMES: the pairing rule and the window rule then agree on what
# a trial can span, so a paired trial can never be un-searchable.
#
# The onset->outcome gap is strongly bimodal ACROSS SESSIONS — khoai-lang runs a
# median of ~340 frames while eggtart-1 Jul 1 and banh-mi-1 Jul 2 run ~1050-1200.
# Globally: median 372, p90 1080, p99 2217, max 2926. A 1200 lookback covers
# 93.3% overall but only ~45% of the two slow sessions; 3000 covers 100%.
MAX_LOOKBACK = 3000


@dataclass(frozen=True)
class Interval:
    """A run of frames over which the pellet is present, ends inclusive.

    ``start``/``end`` are coerced to plain ``int``: they originate in a numpy
    int64 sweep array, and numpy scalars are not JSON serialisable, so leaving
    them meant every consumer that serialises a window had to remember to cast.
    """
    start: int
    end: int

    def __post_init__(self):
        object.__setattr__(self, "start", int(self.start))
        object.__setattr__(self, "end", int(self.end))

    def __contains__(self, frame: int) -> bool:
        return self.start <= frame <= self.end

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def debounce(present, min_run: int = MIN_RUN_SAMPLES) -> list[bool]:
    """Suppress state flips shorter than ``min_run`` samples.

    The output holds the previous state until a new one has persisted long
    enough, so a 5-frame occlusion inside a long armed stretch does not split
    it into two intervals.
    """
    seq = [bool(x) for x in present]
    if not seq or min_run <= 1:
        return seq
    out: list[bool] = []
    state = seq[0]
    run_val, run_len = state, 0
    for value in seq:
        if value == state:
            run_len = 0
        else:
            run_len = run_len + 1 if value == run_val else 1
            run_val = value
            if run_len >= min_run:
                state = value
                # Retroactively flip the samples that formed the run: the state
                # changed when the run STARTED, not once it was confirmed.
                for k in range(1, min_run):
                    if out:
                        out[-k] = value
                run_len = 0
        out.append(state)
    return out


def present_intervals(frames, scores,
                      threshold: float = PRESENT_THRESHOLD,
                      min_run: int = MIN_RUN_SAMPLES) -> list[Interval]:
    """Runs of frames where the pellet is present, in absolute frame numbers.

    ``frames`` and ``scores`` come from a strided sweep, so an interval's
    bounds are the sampled frames — not necessarily every frame between them.
    """
    if len(frames) != len(scores):
        raise ValueError("frames and scores must be the same length")
    if not len(frames):
        return []
    flags = debounce([s > threshold for s in scores], min_run)
    out: list[Interval] = []
    start = None
    for frame, flag in zip(frames, flags):
        if flag and start is None:
            start = frame
        elif not flag and start is not None:
            out.append(Interval(start, prev))
            start = None
        prev = frame
    if start is not None:
        out.append(Interval(start, frames[-1]))
    return out


def intervals_from_mask(frames, present, min_run: int = MIN_RUN_SAMPLES) -> list[Interval]:
    """Armed intervals from an already-decided boolean mask.

    The two-camera detector decides presence from three signals (both cameras
    plus a 3D gate), so it cannot be expressed as one score against one
    threshold. Debouncing is identical either way, so it lives here once.
    """
    frames = np.asarray(frames)
    present = np.asarray(present, dtype=bool)
    if len(frames) != len(present):
        raise ValueError("frames and present must be the same length")
    if not len(frames):
        return []
    flags = debounce(present.tolist(), min_run)
    out: list[Interval] = []
    start = None
    prev = int(frames[0])
    for frame, flag in zip(frames.tolist(), flags):
        if flag and start is None:
            start = frame
        elif not flag and start is not None:
            out.append(Interval(start, prev))
            start = None
        prev = frame
    if start is not None:
        out.append(Interval(start, int(frames[-1])))
    return out


@dataclass(frozen=True)
class SearchWindow:
    """Where stage 2/3 look for one trial's onset.

    Closes at the human outcome marker and opens ``max_lookback`` before it.
    Both of the user's conditions are enforced here rather than downstream: the
    window exists only because an outcome marker follows it, and only
    pellet-stationary frames inside it are candidates.

    ``armed`` holds the pellet-present intervals clipped to the span. It is a
    per-frame MASK, not a single chosen interval — a trial's span routinely
    contains two armed stretches (the one the reach happens in, then the vane
    reloading a fresh pellet), and picking either one alone drops onsets.
    """
    start: int
    end: int                        # the outcome marker frame, inclusive
    outcome: str
    armed: tuple[Interval, ...] = ()
    onset_frame: int | None = None  # ground truth when known, for evaluation

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @property
    def n_candidates(self) -> int:
        return sum(iv.length for iv in self.armed)

    def is_candidate(self, frame: int) -> bool:
        return any(frame in iv for iv in self.armed)

    def candidate_frames(self) -> list[int]:
        """Every pellet-stationary frame in the span, ascending."""
        return [f for iv in self.armed for f in range(iv.start, iv.end + 1)]


def build_windows(trials, intervals, max_lookback: int = MAX_LOOKBACK,
                  min_candidates: int = 30) -> list[SearchWindow]:
    """One search window per trial that has any armed frame to search.

    See ``MAX_LOOKBACK`` for why the default is what it is — tuning it down to
    save stage-2 work silently drops onsets on the slow sessions, and stage 1 is
    the recall gate: anything it drops, nothing downstream can recover.
    """
    out: list[SearchWindow] = []
    for trial in trials:
        marker = trial.outcome_frame
        start = max(0, marker - max_lookback)
        armed = tuple(
            Interval(max(iv.start, start), min(iv.end, marker))
            for iv in intervals
            if iv.end >= start and iv.start <= marker
        )
        armed = tuple(iv for iv in armed if iv.end >= iv.start)
        if sum(iv.length for iv in armed) < min_candidates:
            continue
        out.append(SearchWindow(start=start, end=marker, outcome=trial.outcome,
                                armed=armed, onset_frame=trial.onset_frame))
    return out

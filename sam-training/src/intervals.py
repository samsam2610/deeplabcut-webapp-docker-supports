"""Pure signal → interval logic for the pellet trace, and window construction.

No OpenCV, no video, no I/O — everything here is testable from arrays, which is
what keeps the fiddly debounce/edge rules honest.
"""
from __future__ import annotations

from dataclasses import dataclass

# NCC above this = the pellet template matches = pellet sitting on the pedestal.
# Measured separation across 3 animals and 2 months: present ~0.76-0.82,
# absent ~0.34-0.50. 0.55 sits in the gap.
PRESENT_THRESHOLD = 0.55

# A state flip must persist this many CONSECUTIVE samples to count. The paw and
# the rat's body transiently occlude the pedestal, and the white reload vane
# sweeps through; without debouncing every one of those is a spurious edge.
MIN_RUN_SAMPLES = 20


@dataclass(frozen=True)
class Interval:
    """A half-open run of frames over which the pellet is present."""
    start: int
    end: int                        # inclusive

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


@dataclass(frozen=True)
class SearchWindow:
    """Where stage 2/3 look for one trial's onset.

    Closes at the human outcome marker; opens at the start of the pellet-present
    interval that the marker falls in or follows. Both of the user's conditions
    are enforced here rather than downstream: the window exists only because an
    outcome marker follows it, and it spans only pellet-stationary frames.
    """
    start: int
    end: int                        # the outcome marker frame, inclusive
    outcome: str
    onset_frame: int | None = None  # ground truth when known, for evaluation

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def build_windows(trials, intervals, max_lookback: int = 1200,
                  min_length: int = 30) -> list[SearchWindow]:
    """One search window per trial, or none where the trial cannot be bounded.

    ``max_lookback`` caps how far back a window may reach: the onset->outcome
    gap has p90 = 1080 frames, so 1200 covers essentially every real trial while
    refusing to run a window back into the previous one.
    """
    out: list[SearchWindow] = []
    for trial in trials:
        marker = trial.outcome_frame
        floor = marker - max_lookback
        # The interval the marker sits in, else the last one that ended before
        # it — the pellet often leaves the pedestal a beat before the human
        # keys the outcome, which closes the interval early.
        chosen = None
        for iv in intervals:
            if iv.start > marker:
                break
            if iv.end >= floor:
                chosen = iv
        if chosen is None:
            continue
        start = max(chosen.start, floor)
        if marker - start + 1 < min_length:
            continue
        out.append(SearchWindow(start=start, end=marker, outcome=trial.outcome,
                                onset_frame=trial.onset_frame))
    return out

"""Reading the companion CSV and pairing trials.

Each video has ``<video>.csv`` alongside it with columns
``timestamp, frame_number, frame_line_status, note``. ``frame_number`` is
**1-based**. See the reference memory for the full note vocabulary.

Matching is EXACT throughout, matching the main webapp's ``tagged_frames()``:
the human owns the spelling, so ``start-failure`` must never pick up
``start-failure-2`` — nor our own ``start-failure-candidate``.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

ONSET_SUCCESS = "start-success"
ONSET_FAILURE = "start-failure"
ONSETS = (ONSET_SUCCESS, ONSET_FAILURE)

OUTCOME_SUCCESS = "s"
OUTCOME_FAILURE = "f"
OUTCOMES = (OUTCOME_SUCCESS, OUTCOME_FAILURE)

CANDIDATE_SUFFIX = "-candidate"

# The outcome is keyed LIVE during the experiment, so the onset->outcome gap
# varies (median 373 frames, p90 1080 @200fps). Never assume a fixed offset.
# 3000 frames = 15 s, comfortably past p90 without spanning to the next trial
# (median inter-trial gap is ~2500 frames).
MAX_TRIAL_FRAMES = 3000


def csv_path_for(video_path) -> Path:
    return Path(video_path).with_suffix(".csv")


def read_notes(video_path) -> list[tuple[int, str]]:
    """Sorted ``(frame_number, note)`` for every row carrying a note.

    Returns [] when the CSV is missing or unreadable — a missing companion is a
    normal state (cam1's is empty by convention), not an error.
    """
    path = csv_path_for(video_path)
    if not path.is_file():
        return []
    out: list[tuple[int, str]] = []
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, skipinitialspace=True)
            if reader.fieldnames:
                reader.fieldnames = [n.strip() for n in reader.fieldnames]
            for row in reader:
                row = {(k.strip() if k else k): v for k, v in row.items()}
                note = (row.get("note") or "").strip()
                if not note:
                    continue
                raw = row.get("frame_number")
                if raw is None or str(raw).strip() == "":
                    # A note with no frame number is malformed; defaulting to 0
                    # would invent a trial at the start of the video.
                    continue
                try:
                    fn = int(float(raw))
                except (TypeError, ValueError):
                    continue
                if fn >= 0:
                    out.append((fn, note))
    except OSError:
        return []
    out.sort()
    return out


def onsets(rows) -> list[tuple[int, str]]:
    """Human onset tags only — exact matches, so ``*-candidate`` is excluded."""
    return [(f, n) for f, n in rows if n in ONSETS]


def outcomes(rows) -> list[tuple[int, str]]:
    """Human outcome markers, keyed live during the experiment."""
    return [(f, n) for f, n in rows if n in OUTCOMES]


@dataclass(frozen=True)
class Trial:
    """One reach, bounded by its outcome marker.

    ``onset`` is the human tag when there is one, else None — an *orphan*,
    which is exactly the work this tool exists to do.
    """
    outcome_frame: int
    outcome: str                    # "s" or "f"
    onset_frame: int | None = None

    @property
    def is_orphan(self) -> bool:
        return self.onset_frame is None

    @property
    def candidate_note(self) -> str:
        """The note we would write: label derived, never predicted."""
        base = ONSET_SUCCESS if self.outcome == OUTCOME_SUCCESS else ONSET_FAILURE
        return base + CANDIDATE_SUFFIX


def pair_trials(rows, max_gap: int = MAX_TRIAL_FRAMES) -> list[Trial]:
    """Pair each onset tag with the next matching outcome marker.

    An onset claims the first following outcome marker of the *matching* kind
    (``start-success`` -> ``s``) within ``max_gap``, and no marker may be
    claimed twice. Every unclaimed marker becomes an orphan Trial.

    Deriving the label from the marker rather than the onset is deliberate:
    at inference there is no onset tag, only the marker.
    """
    outs = outcomes(rows)
    claimed: set[int] = set()
    trials: list[Trial] = []

    for onset_frame, onset_note in onsets(rows):
        want = OUTCOME_SUCCESS if onset_note == ONSET_SUCCESS else OUTCOME_FAILURE
        for frame, note in outs:
            if frame <= onset_frame or frame in claimed:
                continue
            if frame - onset_frame > max_gap:
                break
            if note == want:
                claimed.add(frame)
                trials.append(Trial(outcome_frame=frame, outcome=note,
                                    onset_frame=onset_frame))
            # Stop at the first unclaimed marker either way: a mismatched one
            # means this onset's own marker is missing, and skipping past it
            # would steal the NEXT trial's marker.
            break

    for frame, note in outs:
        if frame not in claimed:
            trials.append(Trial(outcome_frame=frame, outcome=note))

    trials.sort(key=lambda t: t.outcome_frame)
    return trials

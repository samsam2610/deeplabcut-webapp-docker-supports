"""`<video>_trials.csv` — one stored scoring result per trial.

What makes a batch resumable and a result reviewable after the fact.

Keyed on the **marker** — the human `s`/`f` frame, which never moves. Keying on
the window span would orphan every stored result the moment `lookback` or
`past prev marker` changed, because the span is derived from them.

`judge_sig` invalidates nothing. It records the judging parameters in force when
the row was scored, so a result produced under a different gate is *visible*
rather than silently trusted.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

COLUMNS = ["marker", "window_start", "outcome", "mode", "pick", "score",
           "n_candidates", "n_kept", "prompt", "judge_sig", "scored_at"]

SUFFIX = "_trials.csv"


def path_for(video_path) -> Path:
    p = Path(video_path)
    return p.with_name(p.stem + SUFFIX)


@dataclass
class Row:
    marker: int
    window_start: int
    outcome: str
    mode: str
    pick: int
    score: float | None = None
    n_candidates: int | None = None
    n_kept: int | None = None
    prompt: str = ""
    judge_sig: str = ""
    scored_at: str = ""

    def as_csv(self) -> dict:
        def num(v, nd=4):
            return "" if v is None else f"{float(v):.{nd}f}"
        return {"marker": int(self.marker), "window_start": int(self.window_start),
                "outcome": self.outcome, "mode": self.mode, "pick": int(self.pick),
                "score": num(self.score),
                "n_candidates": "" if self.n_candidates is None else int(self.n_candidates),
                "n_kept": "" if self.n_kept is None else int(self.n_kept),
                "prompt": self.prompt, "judge_sig": self.judge_sig,
                "scored_at": self.scored_at}


def read(video_path, dest=None) -> list[dict]:
    src = Path(dest) if dest else path_for(video_path)
    if not src.is_file():
        return []
    try:
        with open(src, newline="", encoding="utf-8", errors="replace") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, csv.Error):
        return []                       # a damaged file must not lose this run
    return [r for r in rows if str(r.get("marker") or "").strip()]


def merge(video_path, rows, dest=None) -> Path:
    """Add rows, replacing any with the same marker; leave the rest untouched."""
    out = Path(dest) if dest else path_for(video_path)
    existing = {}
    for r in read(video_path, out):
        try:
            existing[int(float(r["marker"]))] = {c: r.get(c, "") for c in COLUMNS}
        except (TypeError, ValueError):
            continue
    for r in rows:
        existing[int(r.marker)] = r.as_csv()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for k in sorted(existing):
            w.writerow(existing[k])
    tmp.replace(out)                    # atomic: a killed batch leaves no stub
    return out


def scored_markers(video_path, dest=None) -> set:
    """Markers already stored — what makes a batch skip work it has done."""
    out = set()
    for r in read(video_path, dest):
        try:
            out.add(int(float(r["marker"])))
        except (TypeError, ValueError):
            continue
    return out

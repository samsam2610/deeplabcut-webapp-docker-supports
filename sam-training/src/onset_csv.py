"""The `<video>_onset.csv` sidecar — every signal used to decide an onset.

Why a sidecar rather than the companion CSV: the companion file IS the
experimental record, and the pipeline's intermediate signals are not
observations. Keeping them separate means a bad run is deleted with `rm`
instead of repaired, and the record can never be corrupted by a rewrite.

Shape mirrors the companion CSV — `timestamp, frame_number, …, note`, with
`frame_number` **1-based** — so the same tooling and the same eyes work on both.
Rows are written only for frames that carry information (swept frames, sensor
edges, scored candidates), which is ~1/5 of the video rather than all 252 k.

Columns:
    timestamp           seconds, from frame_number / fps
    frame_number        1-based, as the companion CSV
    frame_line_status   copied from the companion CSV — carries the reach sensor
    pellet_ncc          normalised cross-correlation against the pellet template
    pellet_present      1 when NCC clears the threshold
    sensor_edge         1 at a dilated rising edge of the hardware sensor
    armed               1 when the frame is a candidate (pellet stationary)
    window_id           index of the trial window this frame belongs to, else ""
    dino_sim            DINOv3 similarity to label-matched exemplars, when scored
    sam_score           SAM 3 reaching-paw confidence, when masked
    note                proposal (`start-*-candidate`) or the human tag, for reference
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import config

COLUMNS = ["timestamp", "frame_number", "frame_line_status", "pellet_ncc",
           "pellet_present", "sensor_edge", "armed", "window_id",
           "dino_sim", "sam_score", "note"]

SUFFIX = "_onset.csv"


def path_for(video_path) -> Path:
    p = Path(video_path)
    return p.with_name(p.stem + SUFFIX)


@dataclass
class Row:
    frame_number: int
    frame_line_status: str = ""
    pellet_ncc: float | None = None
    pellet_present: int | None = None
    sensor_edge: int = 0
    armed: int = 0
    window_id: int | None = None
    dino_sim: float | None = None
    sam_score: float | None = None
    note: str = ""

    def as_csv(self, fps: float) -> dict:
        def num(v, nd):
            return "" if v is None else f"{v:.{nd}f}"
        return {
            "timestamp": f"{self.frame_number / fps:.4f}",
            "frame_number": self.frame_number,
            "frame_line_status": self.frame_line_status,
            "pellet_ncc": num(self.pellet_ncc, 4),
            "pellet_present": "" if self.pellet_present is None else int(self.pellet_present),
            "sensor_edge": int(self.sensor_edge),
            "armed": int(self.armed),
            "window_id": "" if self.window_id is None else int(self.window_id),
            "dino_sim": num(self.dino_sim, 4),
            "sam_score": num(self.sam_score, 3),
            "note": self.note,
        }


@dataclass
class Build:
    """Accumulates rows keyed by frame, so signals arriving from different
    stages merge instead of overwriting each other."""
    fps: float = config.FPS
    rows: dict[int, Row] = field(default_factory=dict)

    def at(self, frame: int) -> Row:
        return self.rows.setdefault(int(frame), Row(frame_number=int(frame)))

    def add_sweep(self, frames, scores, threshold: float):
        for f, s in zip(np.asarray(frames).tolist(), np.asarray(scores).tolist()):
            row = self.at(int(f) + 1)            # sweep frames are 0-based
            row.pellet_ncc = float(s)
            row.pellet_present = int(s > threshold)

    def add_status(self, notes_rows):
        """`notes_rows` is [(frame_number, frame_line_status)] from the companion."""
        for frame, status in notes_rows:
            if frame in self.rows:
                self.rows[frame].frame_line_status = str(status)

    def add_sensor_edges(self, edges):
        for f in edges:
            self.at(int(f)).sensor_edge = 1

    def add_windows(self, windows):
        for i, w in enumerate(windows):
            for iv in w.armed:
                # Mark only frames we already have rows for (the swept ones);
                # writing all ~1800 armed frames per window would multiply the
                # file size with nothing new to say about the gaps.
                for f in range(iv.start, iv.end + 1):
                    key = f + 1
                    if key in self.rows:
                        self.rows[key].armed = 1
                        self.rows[key].window_id = i

    def add_scores(self, frames, sims, window_id=None):
        for f, s in zip(frames, sims):
            row = self.at(int(f) + 1)
            row.dino_sim = float(s)
            if window_id is not None:
                row.window_id = int(window_id)

    def add_masks(self, masks):
        for m in masks:
            self.at(int(m["frame"]) + 1).sam_score = float(m.get("score") or 0.0)

    def add_note(self, frame: int, note: str):
        self.at(int(frame)).note = note

    def to_rows(self) -> list[dict]:
        return [self.rows[f].as_csv(self.fps) for f in sorted(self.rows)]


def write(video_path, build: Build, dest: Path | None = None) -> Path:
    """Atomic write — a killed run must not leave a half-file that reads as
    valid CSV with a truncated tail."""
    out = Path(dest) if dest else path_for(video_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for row in build.to_rows():
            w.writerow(row)
    tmp.replace(out)
    return out


def read(video_path, dest: Path | None = None) -> list[dict]:
    src = Path(dest) if dest else path_for(video_path)
    if not src.is_file():
        return []
    with open(src, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def summarise(rows) -> dict:
    """Counts the panel shows above the timeline."""
    def truthy(r, k):
        return str(r.get(k) or "").strip() not in ("", "0")
    return {
        "rows": len(rows),
        "armed": sum(1 for r in rows if truthy(r, "armed")),
        "sensor_edges": sum(1 for r in rows if truthy(r, "sensor_edge")),
        "scored": sum(1 for r in rows if str(r.get("dino_sim") or "").strip()),
        "masked": sum(1 for r in rows if str(r.get("sam_score") or "").strip()),
        "notes": sum(1 for r in rows if str(r.get("note") or "").strip()),
    }

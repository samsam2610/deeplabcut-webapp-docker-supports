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
    pellet_ncc          cam0's normalised cross-correlation against the template
    pellet_ncc_cam1     cam1's, from the frame-synced sibling video
    pellet_dist3d       distance from the triangulated match to the reference
                        pellet point; blank when the cameras never agreed
    pellet_present      1 when both cameras match AND the 3D gate passes
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
           # The two-camera detector's other two signals. Without them a wrong
           # armed decision cannot be diagnosed from the file: frame 27591 read
           # "ncc 0.64, present 1" with no way to see that cam1 disagreed and
           # the triangulated point was 8.29 from the pellet.
           "pellet_ncc_cam1", "pellet_dist3d",
           "pellet_present", "sensor_edge", "armed", "window_id",
           "dino_sim", "sam_score", "note",
           # Human placements. The sidecar is the source of truth for both the
           # per-camera box centre and the pellet labels feeding the template
           # pool, so the box can never disagree with the labels.
           "mark_kind", "mark_cam", "mark_x", "mark_y"]

MARK_BOX = "box"
MARK_PELLET = "pellet"

SUFFIX = "_onset.csv"


def path_for(video_path) -> Path:
    p = Path(video_path)
    return p.with_name(p.stem + SUFFIX)


@dataclass
class Row:
    frame_number: int
    frame_line_status: str = ""
    pellet_ncc: float | None = None
    pellet_ncc_cam1: float | None = None
    pellet_dist3d: float | None = None
    pellet_present: int | None = None
    sensor_edge: int = 0
    armed: int = 0
    window_id: int | None = None
    dino_sim: float | None = None
    sam_score: float | None = None
    note: str = ""
    mark_kind: str = ""
    mark_cam: str = ""
    mark_x: float | None = None
    mark_y: float | None = None

    def as_csv(self, fps: float) -> dict:
        def num(v, nd):
            return "" if v is None else f"{v:.{nd}f}"
        return {
            "timestamp": f"{self.frame_number / fps:.4f}",
            "frame_number": self.frame_number,
            "frame_line_status": self.frame_line_status,
            "pellet_ncc": num(self.pellet_ncc, 4),
            "pellet_ncc_cam1": num(self.pellet_ncc_cam1, 4),
            # NaN is written blank: it means the cameras never agreed, so
            # nothing was triangulated. A 0.0 would read as a perfect match.
            "pellet_dist3d": num(self.pellet_dist3d, 3),
            "pellet_present": "" if self.pellet_present is None else int(self.pellet_present),
            "sensor_edge": int(self.sensor_edge),
            "armed": int(self.armed),
            "window_id": "" if self.window_id is None else int(self.window_id),
            "dino_sim": num(self.dino_sim, 4),
            "sam_score": num(self.sam_score, 3),
            "note": self.note,
            "mark_kind": self.mark_kind,
            "mark_cam": self.mark_cam,
            "mark_x": num(self.mark_x, 2),
            "mark_y": num(self.mark_y, 2),
        }


@dataclass
class Build:
    """Accumulates rows keyed by frame, so signals arriving from different
    stages merge instead of overwriting each other."""
    fps: float = config.FPS
    rows: dict[int, Row] = field(default_factory=dict)
    # Marks are keyed separately: several can share one frame_number, which the
    # frame-keyed `rows` dict cannot represent.
    _marks: dict = field(default_factory=dict)

    def at(self, frame: int) -> Row:
        return self.rows.setdefault(int(frame), Row(frame_number=int(frame)))

    def add_sweep(self, frames, scores, threshold: float):
        for f, s in zip(np.asarray(frames).tolist(), np.asarray(scores).tolist()):
            row = self.at(int(f) + 1)            # sweep frames are 0-based
            row.pellet_ncc = float(s)
            row.pellet_present = int(s > threshold)

    def add_pair_sweep(self, frames, score0, score1, dist3d, present):
        """The two-camera sweep: both scores, the 3D distance, and the verdict.

        Every sampled frame is written, rejected ones included — the evidence
        for a rejection is exactly what you need when a frame that should have
        been armed was not.
        """
        import math
        for f, a, b, d, p in zip(np.asarray(frames).tolist(),
                                 np.asarray(score0).tolist(),
                                 np.asarray(score1).tolist(),
                                 np.asarray(dist3d).tolist(),
                                 np.asarray(present).tolist()):
            row = self.at(int(f) + 1)            # sweep frames are 0-based
            row.pellet_ncc = float(a)
            row.pellet_ncc_cam1 = float(b)
            row.pellet_dist3d = None if (d is None or math.isnan(d)) else float(d)
            row.pellet_present = int(bool(p))

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

    def add_mark(self, frame: int, kind: str, cam: str, x: float, y: float):
        """Record a human placement.

        A box and a pellet on the same frame are SEPARATE rows even though they
        describe the same point: collapsing them would drop the pellet from the
        template pool. Rows are keyed by (frame, kind, cam) so a second click on
        one frame corrects rather than duplicates.
        """
        key = (int(frame), str(kind), str(cam))
        row = self._marks.get(key)
        if row is None:
            row = Row(frame_number=int(frame), mark_kind=str(kind),
                      mark_cam=str(cam))
            self._marks[key] = row
        row.mark_x = float(x)
        row.mark_y = float(y)

    def to_rows(self) -> list[dict]:
        out = [self.rows[f].as_csv(self.fps) for f in sorted(self.rows)]
        out += [self._marks[k].as_csv(self.fps) for k in sorted(self._marks)]
        out.sort(key=lambda r: (int(r["frame_number"]), r["mark_kind"], r["mark_cam"]))
        return out


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


# ── reading marks back ───────────────────────────────────────────────────────


def read_marks_from_rows(rows) -> list[dict]:
    out = []
    for r in rows:
        kind = str(r.get("mark_kind") or "").strip()
        if not kind:
            continue
        try:
            out.append({"frame": int(float(r["frame_number"])), "kind": kind,
                        "cam": str(r.get("mark_cam") or "").strip(),
                        "x": float(r["mark_x"]), "y": float(r["mark_y"])})
        except (TypeError, ValueError, KeyError):
            continue
    return out


def read_marks(video_path, dest=None) -> list[dict]:
    return read_marks_from_rows(read(video_path, dest))


def carry_marks(build: Build, marks) -> Build:
    """Re-add human placements to a Build that is rewriting the sidecar.

    Rebuilding the file regenerates every pipeline signal but knows nothing
    about the box, so without this "Build onset CSV" deletes the placement and
    sweeping blocks again on "place the pellet box first". The signals are
    derived and can be recomputed; a human's click cannot.
    """
    for m in marks or []:
        build.add_mark(m["frame"], m["kind"], m["cam"], m["x"], m["y"])
    return build


def box_centre(marks, cam: str):
    """(x, y) of this camera's box, or None when it has not been placed.

    None rather than a default: an unplaced camera must block sweeping, and a
    guessed centre would sweep happily and fill the mask with paws.
    """
    for m in marks:
        if m["kind"] == MARK_BOX and m["cam"] == cam:
            return (m["x"], m["y"])
    return None


def pellet_marks(marks, cam: str | None = None) -> list[dict]:
    return [m for m in marks if m["kind"] == MARK_PELLET
            and (cam is None or m["cam"] == cam)]


def row_from_csv(r) -> Row:
    """Rebuild a Row from a CSV dict, for read-modify-write.

    Without this, saving a placement would rewrite the sidecar from scratch and
    silently discard the sweep trace, the sensor edges and the tags.
    """
    def f(key):
        v = str(r.get(key) or "").strip()
        return float(v) if v else None

    def i(key):
        v = str(r.get(key) or "").strip()
        return int(float(v)) if v else None

    return Row(frame_number=int(float(r["frame_number"])),
               frame_line_status=str(r.get("frame_line_status") or ""),
               pellet_ncc=f("pellet_ncc"),
               pellet_ncc_cam1=f("pellet_ncc_cam1"),
               pellet_dist3d=f("pellet_dist3d"),
               pellet_present=i("pellet_present"),
               sensor_edge=i("sensor_edge") or 0, armed=i("armed") or 0,
               window_id=i("window_id"), dino_sim=f("dino_sim"),
               sam_score=f("sam_score"), note=str(r.get("note") or ""))

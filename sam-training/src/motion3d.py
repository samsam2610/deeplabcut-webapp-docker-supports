"""`<video>_motion3d.csv` — triangulated marker positions over time.

Tidy long format: one row per ``(frame, source, marker)``. A new marker, or a
new segmenter, is new ROWS — never a schema change. That is what lets this be
added to indefinitely without migrating what is already written, which a
column-per-marker layout cannot do.

    frame,source,marker,cam0_x,cam0_y,cam1_x,cam1_y,X,Y,Z,epi_px,score
    28496,sam3,paw_centroid,441.2,352.8,600.1,410.4,2.11,9.87,277.4,1.8,0.93
    28496,dlc,paw_centroid,440.0,351.0,599.0,409.0,2.20,9.70,277.2,1.2,0.99

``source`` is what makes the merge safe: re-running SAM replaces only its own
rows, so a DLC or hand-made row for the same frame and marker survives.

Rejected pairs are written too, with their ``epi_px`` and no 3D point. When a
frame that should have been kept was not, that residual is the only thing that
explains why — the same reason the onset sidecar records the inputs to its
decisions and not just the outcome.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

COLUMNS = ["frame", "source", "marker",
           "cam0_x", "cam0_y", "cam1_x", "cam1_y",
           "X", "Y", "Z", "epi_px", "score"]

SUFFIX = "_motion3d.csv"

SOURCE_SAM = "sam3"


def path_for(video_path) -> Path:
    p = Path(video_path)
    return p.with_name(p.stem + SUFFIX)


@dataclass
class Row:
    frame: int
    source: str
    marker: str
    cam0_x: float | None = None
    cam0_y: float | None = None
    cam1_x: float | None = None
    cam1_y: float | None = None
    X: float | None = None
    Y: float | None = None
    Z: float | None = None
    epi_px: float | None = None
    score: float | None = None

    @property
    def key(self):
        return (int(self.frame), str(self.source), str(self.marker))

    def as_csv(self) -> dict:
        def num(v, nd=3):
            # NaN blank, not 0.0: it means "not measured", and a zero here reads
            # as a perfect epipolar match or an origin-point triangulation.
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return ""
            return f"{float(v):.{nd}f}"
        return {"frame": int(self.frame), "source": self.source,
                "marker": self.marker,
                "cam0_x": num(self.cam0_x, 2), "cam0_y": num(self.cam0_y, 2),
                "cam1_x": num(self.cam1_x, 2), "cam1_y": num(self.cam1_y, 2),
                "X": num(self.X), "Y": num(self.Y), "Z": num(self.Z),
                "epi_px": num(self.epi_px, 2), "score": num(self.score, 4)}


def read(video_path, dest=None) -> list[dict]:
    src = Path(dest) if dest else path_for(video_path)
    if not src.is_file():
        return []
    try:
        with open(src, newline="", encoding="utf-8", errors="replace") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, csv.Error):
        # csv.Error, not just OSError: a NUL byte in a damaged file raises
        # "line contains NUL" from the reader itself. Losing the run that is
        # merging in because an OLD file is damaged is the worst trade here.
        return []
    # Only rows that carry the key; a damaged file degrades to what survives
    # rather than taking the caller down.
    return [r for r in rows if str(r.get("frame") or "").strip()
            and str(r.get("source") or "").strip()]


def _write_rows(dest: Path, rows) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    tmp.replace(dest)                   # atomic: a killed run leaves no stub
    return dest


def write(video_path, rows, dest=None) -> Path:
    """Replace the file with exactly these rows. Use `merge` unless you mean it."""
    out = Path(dest) if dest else path_for(video_path)
    ordered = sorted(rows, key=lambda r: r.key)
    return _write_rows(out, [r.as_csv() for r in ordered])


def merge(video_path, rows, dest=None) -> Path:
    """Add rows, replacing any with the same (frame, source, marker).

    Everything else in the file is carried through untouched — that is the
    whole contract: this file accumulates across runs and across segmenters.
    """
    out = Path(dest) if dest else path_for(video_path)
    existing = {}
    for r in read(video_path, out):
        try:
            key = (int(float(r["frame"])), str(r["source"]), str(r.get("marker") or ""))
        except (TypeError, ValueError):
            continue                    # unparsable leftovers are not carried
        existing[key] = {c: r.get(c, "") for c in COLUMNS}
    for r in rows:
        existing[r.key] = r.as_csv()
    ordered = [existing[k] for k in sorted(existing)]
    return _write_rows(out, ordered)

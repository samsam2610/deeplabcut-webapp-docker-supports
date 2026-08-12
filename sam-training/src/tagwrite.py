"""Writing onset tags into the companion CSV — the experimental record.

Everything else in this module writes sidecars precisely so the record cannot be
corrupted. This is the one place that touches it, so it is deliberately narrow:

* a write **sets the `note` on an existing row**. Every frame is already present
  (250 158 rows on the reference video), so nothing is ever inserted.
* the row's ``timestamp`` and ``frame_line_status`` are preserved verbatim. The
  main webapp's ``/annotate/save-row`` recomputes the timestamp as ``frame/fps``
  to three decimals; the real files carry full precision (``63.718505415``), so
  routing through it would quietly degrade whichever row got tagged.
* a batch is ONE read-modify-write. 129 rewrites of a 6 MB file is slow and is
  129 chances to be interrupted halfway through.
* every write is journalled with the value it replaced, so undo restores the
  prior state exactly rather than blanking the cell.
"""
from __future__ import annotations

import csv
import shutil
import time
import uuid
from pathlib import Path

# How far a tag may be nudged to avoid displacing an existing note. The tolerance
# the whole tool is judged against is +-5 frames, so a shift inside that window
# costs nothing that matters.
RADIUS = 5

# How many pre-write snapshots to keep. Each is a full copy of a ~6 MB file;
# deployment verification produced 74 MB from twelve writes and nothing pruned
# them, so a 129-trial batch would have left ~825 MB beside the video.
MAX_BACKUPS = 3

JOURNAL_SUFFIX = "_tagwrites.csv"
JOURNAL_COLUMNS = ["written_at", "batch_id", "frame", "note", "previous_note",
                   "window_start", "marker"]


def journal_path(csv_path) -> Path:
    p = Path(csv_path)
    return p.with_name(p.stem + JOURNAL_SUFFIX)


# ── placement ───────────────────────────────────────────────────────────────


def place(notes_by_frame, target: int, radius: int = RADIUS):
    """(frame, blockers) — where a tag can go near ``target``.

    Steps outward ``-1, +1, -2, +2 …``, earlier before later. The tie-break is
    arbitrary but deterministic, and the caller reports where it landed.

    Returns ``(None, blockers)`` when every row in range already carries a note.
    Widening the search to "somewhere it fits" would defeat the point of the
    rule, which is that a tag never displaces an existing note.
    """
    target = int(target)
    blockers = []
    for step in range(0, int(radius) + 1):
        for frame in ((target,) if step == 0 else (target - step, target + step)):
            if frame not in notes_by_frame:
                continue                    # not a row in this file
            current = (notes_by_frame[frame] or "").strip()
            if not current:
                return frame, blockers
            blockers.append((frame, current))
    return None, blockers


# ── reading and writing the companion ───────────────────────────────────────


def _read(path: Path):
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, skipinitialspace=True)
        fields = [n.strip() for n in (reader.fieldnames or [])]
        reader.fieldnames = fields
        rows = [{(k.strip() if k else k): v for k, v in r.items()} for r in reader]
    return fields, rows


def notes_by_frame(path) -> dict:
    """``{frame_number: note}`` — what `place` needs, and nothing else."""
    path = Path(path)
    if not path.is_file():
        return {}
    _fields, rows = _read(path)
    out = {}
    for r in rows:
        try:
            out[int(float(r["frame_number"]))] = (r.get("note") or "").strip()
        except (TypeError, ValueError, KeyError):
            continue
    return out


def _replace(tmp: Path, dest: Path):
    tmp.replace(dest)


def _backups(path: Path):
    return sorted(path.parent.glob(path.name + ".bak-*"))


def _snapshot(path: Path):
    """One pre-write copy per session, pruned to the newest MAX_BACKUPS.

    The session marker is the journal: a non-empty one means writes of ours are
    already outstanding, so the current file is NOT the pre-session state and
    copying it again would preserve the wrong thing as well as waste 6 MB.

    copy2 keeps the mtime, which is what lets a full undo put it back.
    """
    if journal_read(path):
        return None
    # Microseconds: a second-resolution stamp collides when two sessions land
    # in the same second, and the second copy then silently overwrites the
    # first — losing the older pre-write state that was the point of keeping it.
    # Lexicographic order stays chronological, which is what the pruning relies
    # on (copy2 gives every backup the SOURCE mtime, so mtime cannot order them).
    from datetime import datetime
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    dest = path.with_name(path.name + f".bak-{stamp}")
    shutil.copy2(path, dest)
    for old in _backups(path)[:-MAX_BACKUPS]:
        old.unlink(missing_ok=True)
    return dest


def write(path, pairs, backup: bool = False) -> dict:
    """Set ``note`` on each ``(frame, note)``. Returns ``{frame: previous}``.

    One pass, one atomic replace, whatever the length of ``pairs``.
    """
    path = Path(path)
    fields, rows = _read(path)
    wanted = {int(f): str(n) for f, n in pairs}
    previous = {}

    if backup:
        _snapshot(path)

    for r in rows:
        try:
            fn = int(float(r["frame_number"]))
        except (TypeError, ValueError, KeyError):
            continue
        if fn in wanted:
            previous[fn] = (r.get("note") or "").strip()
            r["note"] = wanted[fn]

    tmp = path.with_suffix(path.suffix + ".tmp")
    # csv's default lineterminator is \r\n, which is what these files use.
    # Setting it explicitly would be the way to silently rewrite 250k lines.
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    _replace(tmp, path)
    return previous


# ── journal ─────────────────────────────────────────────────────────────────


def journal_read(csv_path) -> list[dict]:
    p = journal_path(csv_path)
    if not p.is_file():
        return []
    try:
        with open(p, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except (OSError, csv.Error):
        return []


def _journal_write(csv_path, entries):
    p = journal_path(csv_path)
    if not entries:
        # Removed, not left as a bare header: "undo everything" should return
        # the directory to its prior state, not leave a husk behind.
        p.unlink(missing_ok=True)
        return
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=JOURNAL_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(entries)
    _replace(tmp, p)


def commit(csv_path, pairs, batch: str | None = None, spans=None,
           backup: bool = False) -> str:
    """Write tags AND journal them. ``spans`` maps frame -> (window_start, marker).

    The journal is what makes undo exact: it records the value each cell held
    before, so reverting restores that rather than blanking it.
    """
    csv_path = Path(csv_path)
    batch = batch or uuid.uuid4().hex[:12]
    spans = spans or {}
    previous = write(csv_path, pairs, backup=backup)
    # With an offset: the container runs UTC and the host does not, so a bare
    # local time is four hours out from the mtimes anyone would compare it to.
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    entries = journal_read(csv_path)
    for frame, note in pairs:
        start, marker = spans.get(int(frame), ("", ""))
        entries.append({"written_at": stamp, "batch_id": batch,
                        "frame": int(frame), "note": str(note),
                        "previous_note": previous.get(int(frame), ""),
                        "window_start": start, "marker": marker})
    _journal_write(csv_path, entries)
    return batch


def last_batch(csv_path) -> str | None:
    entries = journal_read(csv_path)
    return entries[-1]["batch_id"] if entries else None


def undo(csv_path) -> int:
    """Revert the most recent batch. Returns how many cells were restored.

    Only cells still holding what this tool wrote are touched: somebody may have
    corrected a tag in the main webapp since, and undo must revert OUR write,
    not whatever is there now.
    """
    csv_path = Path(csv_path)
    entries = journal_read(csv_path)
    if not entries:
        return 0
    batch = entries[-1]["batch_id"]
    mine = [e for e in entries if e["batch_id"] == batch]
    current = notes_by_frame(csv_path)

    restore = []
    for e in mine:
        try:
            frame = int(float(e["frame"]))
        except (TypeError, ValueError):
            continue
        if current.get(frame, None) != (e.get("note") or "").strip():
            continue                        # changed since; leave it alone
        restore.append((frame, e.get("previous_note") or ""))
    if restore:
        write(csv_path, restore)
    remaining = [e for e in entries if e["batch_id"] != batch]
    _journal_write(csv_path, remaining)
    if not remaining:
        # Nothing of ours is outstanding, so the file should stop claiming it
        # was modified. The newest snapshot carries the pre-session mtime
        # (copy2 preserves it), which is exactly what to put back.
        snaps = _backups(csv_path)
        if snaps:
            import os
            st = os.stat(snaps[-1])
            os.utime(csv_path, (st.st_atime, st.st_mtime))
    return len(restore)

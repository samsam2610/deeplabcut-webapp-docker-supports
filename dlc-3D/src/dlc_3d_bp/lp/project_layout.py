"""LP project on-disk layout helpers — derive view names, session keys,
and LP-spec file/dir names from DLC-style filenames."""
from __future__ import annotations

import re

_CAM_RE = re.compile(r"_cam(\d+)_")
_SESSION_RE = re.compile(r"^(.+?)_cam\d+_(\d{8})")


def view_name_from_stem(stem: str) -> str | None:
    m = _CAM_RE.search(stem)
    return f"cam{m.group(1)}" if m else None


def session_view_pair(stem: str) -> tuple[str | None, str | None]:
    sm = _SESSION_RE.match(stem)
    vm = _CAM_RE.search(stem)
    session = f"{sm.group(1)}_{sm.group(2)}" if sm else None
    view    = f"cam{vm.group(1)}" if vm else None
    return session, view


def lp_csv_for_view(view: str) -> str:
    return f"{view}.csv"


def lp_labeled_dir_name(session_key: str, view: str) -> str:
    return f"{session_key}_{view}"

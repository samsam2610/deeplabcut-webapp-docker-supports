"""List entries in an LP project's videos/ directory.

Uses os.lstat so symlinks are reported as symlinks (even broken ones) and never
followed at listing time. The result is JSON-serialisable for the route layer.
"""
from __future__ import annotations
import os
from pathlib import Path


def list_videos(lp_dir: Path | str) -> list[dict]:
    """Return a sorted list of entries under ``<lp_dir>/videos/``.

    Each entry is::

        {
          "name":          str,           # basename
          "is_symlink":    bool,
          "target":        str | None,    # readlink result if symlink, else None
          "target_exists": bool,          # for symlinks: target resolves; for files: True
          "size_bytes":    int | None,    # stat().st_size; None for broken symlinks
        }

    Raises FileNotFoundError if lp_dir is not an LP project (no config.yaml).
    """
    lp_dir = Path(lp_dir).resolve()
    if not (lp_dir / "config.yaml").is_file():
        raise FileNotFoundError(f"not an LP project (no config.yaml): {lp_dir}")

    videos = lp_dir / "videos"
    if not videos.is_dir():
        return []

    out: list[dict] = []
    for entry in sorted(videos.iterdir()):
        is_link = entry.is_symlink()
        target: str | None = None
        target_exists: bool
        size: int | None
        if is_link:
            target = os.readlink(str(entry))
            try:
                st = entry.stat()        # follows the symlink
                target_exists = True
                size = st.st_size
            except OSError:
                target_exists = False
                size = None
        else:
            try:
                st = entry.stat()
                target_exists = True
                size = st.st_size
            except OSError:
                target_exists = False
                size = None
        out.append({
            "name":          entry.name,
            "is_symlink":    is_link,
            "target":        target,
            "target_exists": target_exists,
            "size_bytes":    size,
        })
    return out

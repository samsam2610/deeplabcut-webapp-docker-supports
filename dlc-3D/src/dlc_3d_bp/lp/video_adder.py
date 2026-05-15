"""Place video files into an LP project's videos/ directory."""
from __future__ import annotations
import os
import shutil
from pathlib import Path
from typing import Iterable

_VALID_MODES = {"symlink", "copy", "hardlink"}


def add_videos_to_lp(
    lp_dir: Path | str,
    video_paths: Iterable[Path | str],
    mode: str = "symlink",
) -> dict:
    """Add videos to ``<lp_dir>/videos/`` without overwriting.

    Args:
        lp_dir: LP project root (must contain config.yaml).
        video_paths: source video files to add.
        mode: 'symlink' (default) | 'copy' | 'hardlink'. hardlink falls back
            to copy when source/dest live on different filesystems.

    Returns:
        ``{"added": [<dst>...], "skipped": [<dst>...], "errors": [str, ...]}``

    Raises:
        FileNotFoundError: lp_dir is not an LP project (no config.yaml).
        ValueError: unknown ``mode``.
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"invalid mode {mode!r}; expected one of {sorted(_VALID_MODES)}")

    lp_dir = Path(lp_dir).resolve()
    if not (lp_dir / "config.yaml").is_file():
        raise FileNotFoundError(f"not an LP project (no config.yaml): {lp_dir}")

    videos_dir = lp_dir / "videos"
    videos_dir.mkdir(exist_ok=True)

    added: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for raw in video_paths:
        src = Path(raw)
        if not src.is_file():
            errors.append(f"source missing: {src}")
            continue
        dst = videos_dir / src.name
        if dst.exists() or dst.is_symlink():
            skipped.append(str(dst))
            continue
        try:
            if mode == "symlink":
                # Resolve src to an absolute path so the symlink stays valid
                # regardless of where the worker reads it from.
                os.symlink(str(src.resolve()), str(dst))
            elif mode == "hardlink":
                try:
                    os.link(str(src), str(dst))
                except OSError:
                    shutil.copy2(str(src), str(dst))
            else:  # copy
                shutil.copy2(str(src), str(dst))
            added.append(str(dst))
        except OSError as e:
            errors.append(f"{src.name}: {e}")

    return {"added": added, "skipped": skipped, "errors": errors}

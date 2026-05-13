"""DLC → Lightning-Pose project conversion.

Pure-python; safe to call from the Flask container (no GPU, no LP imports).
The source DLC project is never mutated.
"""
from __future__ import annotations

import csv
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from .project_layout import session_view_pair, lp_csv_for_view, lp_labeled_dir_name


@dataclass
class ConversionSummary:
    n_views: int = 0
    n_sessions: int = 0
    n_frames: int = 0
    n_calibrations: int = 0
    warnings: List[str] = field(default_factory=list)
    output_dir: str = ""

    def asdict(self) -> dict:
        return {
            "n_views": self.n_views,
            "n_sessions": self.n_sessions,
            "n_frames": self.n_frames,
            "n_calibrations": self.n_calibrations,
            "warnings": self.warnings,
            "output_dir": self.output_dir,
        }


def _read_dlc_collected_csv(path: Path) -> Dict:
    """Return {frame_number: [row1, row2, ...]} from a CollectedData_*.csv.

    DLC schemas vary. We don't parse the header rows — we treat the file as
    opaque row blocks keyed by frame number, which is sufficient for ordering.
    """
    rows: Dict = {}
    if not path.is_file():
        return rows
    header: List[List[str]] = []
    body: List[List[str]] = []
    with path.open(newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            # DLC header rows start with literal 'scorer'/'bodyparts'/'coords'
            if row[0] in ("scorer", "bodyparts", "coords", "individuals"):
                header.append(row)
                continue
            body.append(row)
    for row in body:
        # Path is in column 0 (or columns 0-2 for newer schemas); frame number
        # is the last path segment like 'imgNNNNN.png'.
        path_cell = row[0] if len(row[0]) > 4 else "/".join(row[:3])
        name = Path(path_cell).name
        digits = "".join(ch for ch in name if ch.isdigit())
        if not digits:
            continue
        frame_no = int(digits[-5:]) if len(digits) >= 5 else int(digits)
        rows.setdefault(frame_no, []).append(row)
    rows["__header__"] = header  # type: ignore[index]
    return rows


def _list_calibrations(dlc_dir: Path) -> List[Tuple[str, Path]]:
    """Return [(session_key, calibration_toml_path), ...] from labeled-data/*/calibration.toml."""
    found: List[Tuple[str, Path]] = []
    ld = dlc_dir / "labeled-data"
    if not ld.is_dir():
        return found
    for session_dir in sorted(ld.iterdir()):
        if not session_dir.is_dir():
            continue
        cal = session_dir / "calibration.toml"
        if cal.is_file():
            found.append((session_dir.name, cal))
    return found


def _link_or_copy(src: Path, dst: Path, mode: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    if mode == "link":
        try:
            os.link(src, dst)
            return
        except OSError:
            pass  # fall back to copy across filesystems
    shutil.copy2(src, dst)


def convert_dlc_to_lp(
    dlc_dir,
    lp_dir,
    link_mode: str = "link",
    force: bool = False,
) -> dict:
    """Convert a DLC project to LP layout. Returns a summary dict.

    Raises FileNotFoundError / ValueError on bad inputs.
    """
    dlc_dir = Path(dlc_dir).resolve()
    lp_dir = Path(lp_dir).resolve()

    if not (dlc_dir / "config.yaml").is_file():
        raise FileNotFoundError(f"DLC config.yaml not found in {dlc_dir}")
    if lp_dir.exists() and any(lp_dir.iterdir()) and not force:
        raise ValueError(f"LP output dir {lp_dir} is not empty; pass force=True to overwrite")

    summary = ConversionSummary(output_dir=str(lp_dir))
    lp_dir.mkdir(parents=True, exist_ok=True)
    (lp_dir / "labeled-data").mkdir(exist_ok=True)
    (lp_dir / "videos").mkdir(exist_ok=True)

    # 1. Discover sessions and views from labeled-data folder names
    by_session: Dict[str, Dict[str, dict]] = {}
    ld_iter = sorted((dlc_dir / "labeled-data").iterdir()) if (dlc_dir / "labeled-data").is_dir() else []
    for session_dir in ld_iter:
        if not session_dir.is_dir():
            continue
        session_key, view = session_view_pair(session_dir.name)
        if not session_key or not view:
            summary.warnings.append(
                f"skipping unrecognised labeled-data folder: {session_dir.name}"
            )
            continue
        # CollectedData_*.csv path
        cc = next(session_dir.glob("CollectedData_*.csv"), None)
        by_session.setdefault(session_key, {})[view] = {
            "src_dir": session_dir,
            "collected_csv": cc,
        }

    # Keep only sessions with >=2 views (multi-view requirement); single-view
    # sessions are emitted as warnings.
    multi: Dict[str, Dict[str, dict]] = {}
    for skey, views in by_session.items():
        if len(views) >= 2:
            multi[skey] = views
        else:
            summary.warnings.append(f"session {skey} has only {len(views)} view(s); skipped")

    # 2. Determine the canonical view ordering across sessions
    all_views = sorted({v for views in multi.values() for v in views})
    summary.n_views = len(all_views)
    summary.n_sessions = len(multi)

    if not all_views:
        # write a minimal config and return
        _write_lp_config(lp_dir, dlc_dir, all_views)
        return summary.asdict()

    # 3. Per-view CSV builders — accumulate rows in canonical order
    per_view_rows: Dict[str, List[List[str]]] = {v: [] for v in all_views}
    per_view_header: Dict[str, List[List[str]]] = {v: [] for v in all_views}

    for session_key in sorted(multi):
        views = multi[session_key]
        # Load CSVs for each view
        view_to_frames: Dict[str, Dict[int, List[List[str]]]] = {}
        for v in all_views:
            entry = views.get(v)
            if not entry or not entry.get("collected_csv"):
                view_to_frames[v] = {}
                continue
            view_to_frames[v] = _read_dlc_collected_csv(entry["collected_csv"])
            if not per_view_header[v]:
                per_view_header[v] = view_to_frames[v].pop("__header__", [])
            else:
                view_to_frames[v].pop("__header__", None)

        # Intersect frame numbers across views present for this session
        present_views = [v for v in all_views if view_to_frames.get(v)]
        if len(present_views) < 2:
            summary.warnings.append(
                f"session {session_key}: <2 views with labels; skipped"
            )
            continue
        common = set.intersection(*[set(view_to_frames[v].keys()) for v in present_views])
        if not common:
            summary.warnings.append(
                f"session {session_key}: no common labeled frames across views; skipped"
            )
            continue

        # Emit rows + copy frames
        for frame_no in sorted(common):
            for v in all_views:
                if v in present_views:
                    for row in view_to_frames[v][frame_no]:
                        # Rewrite path column to new labeled-data location
                        new_dir = lp_labeled_dir_name(session_key, v)
                        new_rel = f"labeled-data/{new_dir}/img{frame_no:08d}.png"
                        new_row = [new_rel] + list(row[1:])
                        per_view_rows[v].append(new_row)
                else:
                    summary.warnings.append(
                        f"session {session_key} missing view {v} for frame {frame_no}"
                    )

            # Link/copy the frame PNGs (best-effort; original filename in DLC
            # is img_cam<N>_<order>_<frame>.png)
            for v in present_views:
                src_dir = views[v]["src_dir"]
                matches = list(src_dir.glob(f"img_*_{frame_no:05d}.png"))
                if not matches:
                    matches = list(src_dir.glob(f"img*{frame_no}*.png"))
                if matches:
                    dst = lp_dir / "labeled-data" / lp_labeled_dir_name(session_key, v) / f"img{frame_no:08d}.png"
                    _link_or_copy(matches[0], dst, link_mode)
                    summary.n_frames += 1

    # 4. Write per-view CSVs at LP project root
    for v in all_views:
        out_csv = lp_dir / lp_csv_for_view(v)
        with out_csv.open("w", newline="") as f:
            w = csv.writer(f)
            for hrow in per_view_header[v]:
                w.writerow(hrow)
            for row in per_view_rows[v]:
                w.writerow(row)

    # 5. Aggregate calibrations
    cal_entries = _list_calibrations(dlc_dir)
    if cal_entries:
        cal_dir = lp_dir / "calibrations"
        cal_dir.mkdir(exist_ok=True)
        # Take one calibration per session_key (use folder name's session part)
        seen: set = set()
        with (lp_dir / "calibrations.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["session", "calibration_file"])
            for folder_name, cal_path in cal_entries:
                skey, _ = session_view_pair(folder_name)
                if not skey or skey in seen:
                    continue
                seen.add(skey)
                dst = cal_dir / f"{skey}.toml"
                _link_or_copy(cal_path, dst, link_mode)
                w.writerow([skey, f"calibrations/{skey}.toml"])
                summary.n_calibrations += 1

    # 6. Write LP config.yaml
    _write_lp_config(lp_dir, dlc_dir, all_views)

    return summary.asdict()


def _write_lp_config(lp_dir: Path, dlc_dir: Path, views: List[str]) -> None:
    with (dlc_dir / "config.yaml").open() as f:
        dlc_cfg = yaml.safe_load(f) or {}
    bodyparts = dlc_cfg.get("bodyparts", []) or dlc_cfg.get("multianimalbodyparts", [])
    lp_cfg = {
        "data": {
            "data_dir": str(lp_dir),
            "video_dir": "videos",
            "csv_file": [f"{v}.csv" for v in views] if len(views) > 1 else (views[0] + ".csv" if views else "labels.csv"),
            "view_names": views,
            "keypoint_names": bodyparts,
            "num_keypoints": len(bodyparts),
        },
        "model": {
            "model_type": "heatmap_mhcrnn" if len(views) <= 1 else "multiview_heatmap",
            "backbone": "resnet50_animal_apose",
            "losses_to_use": [],
        },
        "training": {
            "max_epochs": 300,
            "train_batch_size": 16,
            "val_batch_size": 16,
            "test_batch_size": 16,
            "imgaug_3d": False,
        },
        "losses": {},
        "eval": {
            "predict_vids_after_training": False,
            "save_vids_after_training": False,
        },
        "callbacks": {},
        "_converter": {
            "source_dlc_dir": str(dlc_dir),
            "views": views,
        },
    }
    with (lp_dir / "config.yaml").open("w") as f:
        yaml.safe_dump(lp_cfg, f, sort_keys=False)

"""DLC → Lightning-Pose project conversion.

Pure-python; safe to call from the Flask container (no GPU, no LP imports).
The source DLC project is never mutated.

Supports two source layouts:

* "view-in-folder" (legacy DLC): folder name carries the cam, e.g.
  ``labeled-data/<session>_cam<N>_<date>/`` with one ``CollectedData_*.csv``
  per view-folder.
* "view-in-filename" (this project's ``dlc-3D`` extractor): folder name is a
  session key (e.g. ``labeled-data/khoai-lang-1_20260429/``); the cam is in
  the image filenames ``img_cam<N>_<order>_<frame>.png``; a single
  ``CollectedData_*.csv`` per folder contains rows for all cams.
"""
from __future__ import annotations

import csv
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

import yaml

from .project_layout import session_view_pair, lp_csv_for_view, lp_labeled_dir_name


# Matches images like ``img_cam0_0007_126161.png``: cam index then frame number.
_FRAME_IN_NAME_RE = re.compile(r"img_cam(\d+)_\d+_(\d+)\.png")


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

    Used for the view-in-folder layout: every data row belongs to the folder's
    single view. We don't parse the header rows — we treat the file as opaque
    row blocks keyed by frame number, which is sufficient for ordering.
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
                header.append(_normalize_header_row(row))
                continue
            body.append(_normalize_dlc_row(row))
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


def _normalize_dlc_row(row: List[str]) -> List[str]:
    """Drop the 3-column DLC path split (``labeled-data,session,filename``) so
    the row is ``[path, x1, y1, ...]``. Idempotent for already-1-column rows.
    """
    if len(row) >= 3 and row[0] == "labeled-data":
        return [row[0] + "/" + row[1] + "/" + row[2]] + list(row[3:])
    return list(row)


def _normalize_header_row(row: List[str]) -> List[str]:
    """Strip the two extra blank cells DLC puts after the leading tag for the
    3-column index format, so the header has one path column + coord columns.
    """
    # DLC header rows look like: ['scorer','','','Ali','Ali',...] when the
    # body uses a 3-col path index. Drop columns 1 and 2 if both are blank.
    if len(row) >= 3 and row[1] == "" and row[2] == "":
        return [row[0]] + list(row[3:])
    return list(row)


def _read_view_in_filename_csv(path: Path) -> Tuple[List[List[str]], Dict[str, Dict[int, List[List[str]]]]]:
    """Read a CollectedData_*.csv whose rows span multiple cams.

    Returns ``(header_rows, {view_name: {frame_number: [row, ...]}})`` where
    ``view_name`` is ``cam<N>`` parsed from the image filename. Rows whose
    image filename doesn't match :data:`_FRAME_IN_NAME_RE` are skipped.

    Rows and header rows are normalised so each has a single leading path
    column (LP's ``pd.read_csv(..., index_col=0)`` expects that shape).
    """
    header: List[List[str]] = []
    per_view: Dict[str, Dict[int, List[List[str]]]] = {}
    if not path.is_file():
        return header, per_view
    with path.open(newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            if row[0] in ("scorer", "bodyparts", "coords", "individuals"):
                header.append(_normalize_header_row(row))
                continue
            # Image filename may be in col 0 (1-col path) or col 2 (3-col split).
            name = ""
            if len(row) >= 3 and row[0] == "labeled-data":
                name = row[2]
            else:
                name = Path(row[0]).name
            m = _FRAME_IN_NAME_RE.search(name)
            if not m:
                continue
            cam_idx = int(m.group(1))
            frame_no = int(m.group(2))
            view = f"cam{cam_idx}"
            per_view.setdefault(view, {}).setdefault(frame_no, []).append(
                _normalize_dlc_row(row)
            )
    return header, per_view


def _classify_session_folder(folder: Path) -> str:
    """Return one of ``"view-in-folder"``, ``"view-in-filename"``, ``"unknown"``.

    A folder is "view-in-folder" iff ``session_view_pair(folder.name)`` returns
    both session key and view (the folder name encodes the cam).

    Otherwise, if any ``img_cam<N>_*.png`` is present, it's "view-in-filename".
    """
    skey, view = session_view_pair(folder.name)
    if skey and view:
        return "view-in-folder"
    for p in folder.iterdir():
        if p.is_file() and _FRAME_IN_NAME_RE.search(p.name):
            return "view-in-filename"
    return "unknown"


def _list_calibrations(dlc_dir: Path) -> List[Tuple[str, Path]]:
    """Return [(folder_name, calibration_toml_path), ...] from labeled-data/*/calibration.toml."""
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
    # by_session[session_key][view] -> dict describing where labels/frames live
    # For view-in-folder mode: {"src_dir": <view-folder>, "collected_csv": ...}
    # For view-in-filename mode: {"src_dir": <session-folder>,
    #                              "collected_csv": ...,
    #                              "mode": "view-in-filename",
    #                              "frames": {frame_no: [row,...]}}
    by_session: Dict[str, Dict[str, dict]] = {}
    # Track each folder's classification so calibration aggregation can map
    # the session-key folder name verbatim onto a session key.
    folder_modes: Dict[str, str] = {}

    ld_iter = sorted((dlc_dir / "labeled-data").iterdir()) if (dlc_dir / "labeled-data").is_dir() else []
    for session_dir in ld_iter:
        if not session_dir.is_dir():
            continue
        mode = _classify_session_folder(session_dir)
        folder_modes[session_dir.name] = mode
        if mode == "view-in-folder":
            session_key, view = session_view_pair(session_dir.name)
            cc = next(session_dir.glob("CollectedData_*.csv"), None)
            by_session.setdefault(session_key, {})[view] = {
                "src_dir": session_dir,
                "collected_csv": cc,
                "mode": "view-in-folder",
            }
        elif mode == "view-in-filename":
            session_key = session_dir.name
            cc = next(session_dir.glob("CollectedData_*.csv"), None)
            header, per_view = (([], {}) if cc is None else _read_view_in_filename_csv(cc))
            for view, frames in per_view.items():
                by_session.setdefault(session_key, {})[view] = {
                    "src_dir": session_dir,
                    "collected_csv": cc,
                    "mode": "view-in-filename",
                    "header": header,
                    "frames": frames,
                }
        else:
            summary.warnings.append(
                f"skipping unrecognised labeled-data folder: {session_dir.name}"
            )

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
            if not entry:
                view_to_frames[v] = {}
                continue
            if entry.get("mode") == "view-in-filename":
                view_to_frames[v] = dict(entry.get("frames") or {})
                if not per_view_header[v]:
                    per_view_header[v] = list(entry.get("header") or [])
            else:  # view-in-folder
                if not entry.get("collected_csv"):
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
                # Look for an image whose frame-number group matches frame_no.
                matches: List[Path] = []
                for p in src_dir.iterdir():
                    if not p.is_file():
                        continue
                    m = _FRAME_IN_NAME_RE.search(p.name)
                    if m and int(m.group(2)) == frame_no:
                        # For view-in-filename mode, also constrain to this cam.
                        if views[v].get("mode") == "view-in-filename":
                            if f"cam{m.group(1)}" != v:
                                continue
                        matches.append(p)
                if not matches:
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
        # Take one calibration per session_key.
        seen: set = set()
        with (lp_dir / "calibrations.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["session", "calibration_file"])
            for folder_name, cal_path in cal_entries:
                skey, _ = session_view_pair(folder_name)
                if not skey:
                    # If folder is view-in-filename, the folder name IS the
                    # session key.
                    if folder_modes.get(folder_name) == "view-in-filename":
                        skey = folder_name
                    else:
                        continue
                if skey in seen:
                    continue
                seen.add(skey)
                dst = cal_dir / f"{skey}.toml"
                _link_or_copy(cal_path, dst, link_mode)
                w.writerow([skey, f"calibrations/{skey}.toml"])
                summary.n_calibrations += 1

    # 6. Write LP config.yaml
    _write_lp_config(lp_dir, dlc_dir, all_views)

    return summary.asdict()


def _probe_image_dims(lp_dir: Path) -> Tuple[int, int]:
    """Return (height, width) by parsing the first labeled PNG header.

    Uses stdlib only (the dlc-3d Flask container doesn't ship Pillow). PNG IHDR
    chunk is at bytes 16..24, big-endian width then height. Falls back to
    (384, 384) if no PNGs can be read.
    """
    import struct
    for p in (lp_dir / "labeled-data").glob("*/img*.png"):
        try:
            with p.open("rb") as f:
                head = f.read(24)
            if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n":
                width, height = struct.unpack(">II", head[16:24])
                return int(height), int(width)
        except Exception:
            continue
    return 384, 384


# Pin the upstream lightning-pose default-config reference. Bump this when
# requirements-lp.txt's lightning-pose version is upgraded.
LP_DEFAULT_CONFIG_REF = "v2.1.0"
LP_DEFAULT_CONFIG_URL = (
    "https://raw.githubusercontent.com/paninski-lab/lightning-pose/"
    "{ref}/scripts/configs/config_default.yaml"
)
_LP_DEFAULT_CACHE = Path("/tmp") / f"dlc3d_lp_default_{LP_DEFAULT_CONFIG_REF}.yaml"
_LP_DEFAULT_VENDORED = Path(__file__).resolve().parent / "lp_config_default.yaml"


def _load_upstream_default_config() -> dict:
    """Return lightning-pose's canonical ``scripts/configs/config_default.yaml``
    as a dict, fetched from the pinned upstream ref.

    Tries (in order):
      1. ``/tmp`` cache for the pinned ref (avoids repeat network on the same
         container lifetime).
      2. GitHub raw at ``LP_DEFAULT_CONFIG_REF``. On success, populates cache.
      3. GitHub raw at ``main`` (best-effort newer defaults).
      4. Vendored copy at ``dlc_3d_bp/lp/lp_config_default.yaml`` (kept in sync
         with ``LP_DEFAULT_CONFIG_REF`` for offline / air-gapped fallback).

    Raises ``RuntimeError`` only if all four sources fail.
    """
    if _LP_DEFAULT_CACHE.is_file():
        try:
            return yaml.safe_load(_LP_DEFAULT_CACHE.read_text()) or {}
        except Exception:
            pass

    import urllib.request

    for ref in (LP_DEFAULT_CONFIG_REF, "main"):
        try:
            with urllib.request.urlopen(LP_DEFAULT_CONFIG_URL.format(ref=ref), timeout=5) as r:
                if getattr(r, "status", 200) == 200:
                    body = r.read().decode("utf-8")
                    parsed = yaml.safe_load(body) or {}
                    if ref == LP_DEFAULT_CONFIG_REF:
                        try:
                            _LP_DEFAULT_CACHE.parent.mkdir(parents=True, exist_ok=True)
                            _LP_DEFAULT_CACHE.write_text(body)
                        except Exception:
                            pass
                    return parsed
        except Exception:
            continue

    if _LP_DEFAULT_VENDORED.is_file():
        return yaml.safe_load(_LP_DEFAULT_VENDORED.read_text()) or {}

    raise RuntimeError(
        f"Cannot load LP default config: GitHub unreachable and no vendored "
        f"fallback at {_LP_DEFAULT_VENDORED}"
    )


def _write_lp_config(lp_dir: Path, dlc_dir: Path, views: List[str]) -> None:
    """Write the LP project's ``config.yaml`` by patching the upstream
    canonical default with project-specific values.

    Source of truth is lightning-pose's ``scripts/configs/config_default.yaml``
    at the pinned ref (see :data:`LP_DEFAULT_CONFIG_REF`). Everything except
    the substituted/derived fields is byte-identical to upstream.

    Substituted fields:
      - ``data.data_dir``                 → absolute LP project dir
      - ``data.video_dir``                → ``"videos"`` (relative to data_dir)
      - ``data.csv_file``                 → list of per-view CSVs (multi-view)
                                            or single ``"<view>.csv"`` (single-view)
      - ``data.num_keypoints`` /
        ``data.keypoint_names``           → derived from the DLC project's bodyparts
      - ``data.image_resize_dims``        → probed from the first labeled PNG; rounded
                                            to a multiple of 128 for ViT-backed models
      - ``data.view_names``               → only present for multi-view (LP requires
                                            it absent for single-view)

    Derived fields (LP 2.1.0 needs these even though they aren't in the
    canonical default):
      - ``data.image_orig_dims``          → probed from the first labeled PNG
      - ``model.model_type``              → ``heatmap_multiview_transformer``
                                            when multi-view
      - ``model.backbone``                → ``vits_dino`` for multi-view (ViT is
                                            required by the multi-view transformer)

    A non-canonical ``_converter`` block records provenance.
    """
    base = _load_upstream_default_config()

    with (dlc_dir / "config.yaml").open() as f:
        dlc_cfg = yaml.safe_load(f) or {}
    bodyparts = dlc_cfg.get("bodyparts", []) or dlc_cfg.get("multianimalbodyparts", [])
    img_h, img_w = _probe_image_dims(lp_dir)
    is_multi = len(views) > 1

    # ── Substitute project-specific fields under data ─────────────────────
    data = base.setdefault("data", {})
    data["data_dir"] = str(lp_dir)
    data["video_dir"] = "videos"
    data["num_keypoints"] = len(bodyparts)
    data["keypoint_names"] = bodyparts
    data["image_orig_dims"] = {"height": img_h, "width": img_w}

    if is_multi:
        # ViT-backed multi-view transformer requires image_resize_dims that are
        # multiples of 128 (LP's HeatmapDataset asserts this).
        side = max(256, (min(img_h, img_w) // 128) * 128)
        data["image_resize_dims"] = {"height": side, "width": side}
        data["csv_file"] = [f"{v}.csv" for v in views]
        data["view_names"] = views
    else:
        data["image_resize_dims"] = {"height": img_h, "width": img_w}
        data["csv_file"] = (views[0] + ".csv") if views else "CollectedData.csv"
        # LP's ModelConfig.is_multi_view raises if view_names is present with
        # length 1; drop the key entirely for single-view projects.
        data.pop("view_names", None)

    # ── Model-block overrides only where multi-view forces them ──────────
    model = base.setdefault("model", {})
    if is_multi:
        model["model_type"] = "heatmap_multiview_transformer"
        model["backbone"] = "vits_dino"

    # ── Provenance (non-canonical) ───────────────────────────────────────
    base["_converter"] = {
        "source_dlc_dir": str(dlc_dir),
        "views": views,
        "lp_default_ref": LP_DEFAULT_CONFIG_REF,
        "lp_default_source": LP_DEFAULT_CONFIG_URL.format(ref=LP_DEFAULT_CONFIG_REF),
    }

    with (lp_dir / "config.yaml").open("w") as f:
        yaml.safe_dump(base, f, sort_keys=False)


def _walk_all_labeled_data(dlc_dir) -> Iterator[Tuple[Path, str, List[str]]]:
    """Yield ``(src_png, dest_rel, normalised_row)`` for every labeled row in
    every labeled-data folder of *dlc_dir*, view-agnostically.

    Used by the SV-pretrain converter branch: it doesn't care about pairing or
    folder classification — just every (image, row) tuple that has a backing
    PNG on disk and is referenced in the folder's CollectedData CSV.

    ``dest_rel`` is the relative path the row's first column will carry in the
    output single-view CSV (``labeled-data/<orig_folder>/<orig_filename>.png``).
    ``normalised_row`` is the row after ``_normalize_dlc_row`` flattening (the
    3-col DLC path index → 1 cell).
    """
    dlc_dir = Path(dlc_dir)
    ld = dlc_dir / "labeled-data"
    if not ld.is_dir():
        return
    for folder in sorted(ld.iterdir()):
        if not folder.is_dir():
            continue
        if folder.name.startswith(".") or folder.name.startswith("@"):
            continue
        cc = next(folder.glob("CollectedData_*.csv"), None)
        if cc is None:
            continue
        # Read the CSV directly (don't go through _read_dlc_collected_csv, which
        # keys rows by frame number parsed out of the filename — we want every
        # row regardless of whether the filename has digits).
        with cc.open(newline="") as f:
            for raw_row in csv.reader(f):
                if not raw_row:
                    continue
                if raw_row[0] in ("scorer", "bodyparts", "coords", "individuals"):
                    continue
                row = _normalize_dlc_row(raw_row)
                # Path cell after normalisation
                path_cell = row[0]
                # Filename = last segment
                fname = Path(path_cell).name
                src_png = folder / fname
                if not src_png.is_file():
                    # Row references an image not on disk — skip it (DLC
                    # sometimes leaves stale rows after manual deletes).
                    continue
                dest_rel = f"labeled-data/{folder.name}/{fname}"
                yield src_png, dest_rel, row

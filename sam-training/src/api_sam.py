"""Endpoints the "3D Inline Analysis - SAM Model" card calls.

The card is a client: it renders what these return and never infers anything
itself. Splitting the routes out of app.py keeps the stage 0/1 debug panel and
the stage 2/3 scoring independently readable.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from flask import Blueprint, Response, jsonify, request

from . import (config, exemplars, intervals, models, ncc, notes, onset_csv,
               overlays, pellet_model as pm, rig, stereo, store)

bp = Blueprint("sam_api", __name__)
PREFIX = "/sam-training/api"

# How many candidate frames one /score call may embed. A window can hold ~1800
# armed frames; at DINOv3's ~300 img/s that is still only seconds, but the cap
# stops a pathological window from pinning the GPU for a minute.
MAX_CANDIDATES = 2500


def _project():
    import os
    return os.environ.get(
        "SAM_TRAINING_PROJECT",
        "/user-data/Parra-Data/Disk/DLC-Projects/DREADD-Ali-2026-01-07")


def _resolve(video: str) -> str | None:
    local = config.to_local(video or "")
    return local if local and Path(local).is_file() else None


def _windows_for(video: str):
    """Stage 0+1 for one video, from cache. None when it has not been swept."""
    calib = rig.load(_project(), Path(video).stem)
    if calib is None:
        calib = rig.calibrate(video)
        rig.save(_project(), Path(video).stem, calib)
    cached = store.load_sweep(video, config.SWEEP_STRIDE)
    if cached is None:
        return calib, None
    frames, scores, _n = cached
    ivs = intervals.present_intervals(frames, scores)
    trials = notes.pair_trials(notes.read_notes(video))
    return calib, intervals.build_windows(trials, ivs)


@bp.get(f"{PREFIX}/windows")
def api_windows():
    video = _resolve(request.args.get("video"))
    if not video:
        return jsonify({"error": "video not found"}), 404
    marks = onset_csv.read_marks(video)
    unplaced = [c for c in ("cam0", "cam1")
                if onset_csv.box_centre(marks, c) is None]
    if unplaced or not _model().is_confirmed(Path(video).stem):
        return jsonify({"error": "place the pellet box for this pair first — "
                                 "click the pellet on "
                                 + (" and ".join(unplaced) if unplaced
                                    else "each camera")
                                 + ", then Confirm"}), 428
    calib, wins = _windows_for(video)
    if wins is None:
        return jsonify({"error": "not swept yet — run the sweep in the "
                                 "sam-training panel first"}), 409
    return jsonify({
        "video": video,
        "calibration": {"source": calib.source, "score": round(calib.score, 3),
                        "trustworthy": calib.trustworthy},
        "windows": [{"start": w.start, "end": w.end, "outcome": w.outcome,
                     "onset": w.onset_frame, "n_candidates": w.n_candidates,
                     "armed": [{"start": a.start, "end": a.end} for a in w.armed]}
                    for w in wins],
    })


def _score_window(job, video, start, end, outcome, prompt, topk):
    """Stage 2 + 3 over one trial window."""
    calib, wins = _windows_for(video)
    if wins is None:
        raise RuntimeError("video has not been swept")
    match = [w for w in wins if w.start == start and w.end == end]
    armed = match[0].armed if match else ()
    candidates = [f for iv in armed for f in range(iv.start, iv.end + 1)]
    if not candidates:
        raise RuntimeError("window has no pellet-stationary frames")
    if len(candidates) > MAX_CANDIDATES:
        step = int(np.ceil(len(candidates) / MAX_CANDIDATES))
        candidates = candidates[::step]

    # ── read the candidate frames once, sequentially ──────────────────────
    cap = cv2.VideoCapture(video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, candidates[0])
    wanted = set(candidates)
    crops, kept, raw = [], [], {}
    idx = candidates[0]
    last = candidates[-1]
    while idx <= last:
        ok, frame = cap.read()
        if not ok:
            break
        if idx in wanted:
            crops.append(exemplars.crop_rgb(frame))
            kept.append(idx)
            if len(raw) < 12:
                raw[idx] = frame
        idx += 1
        if job is not None and len(kept) % 200 == 0:
            job.progress = 0.05 + 0.45 * (len(kept) / max(1, len(candidates)))
    cap.release()
    if not kept:
        raise RuntimeError("could not read any candidate frame")

    # ── stage 3: DINOv3 similarity to label-matched exemplars ─────────────
    bank = exemplars.get(_project())
    ref = bank.for_query(outcome, exclude_video=Path(video).stem)
    if not len(ref):
        raise RuntimeError(f"no '{outcome}' exemplars outside this session")
    if job is not None:
        job.progress = 0.55
    sim = models.similarity(models.embed(crops), ref, topk=topk)
    best = int(np.argmax(sim))
    pick = kept[best]
    if job is not None:
        job.progress = 0.8

    # ── stage 2: SAM 3 masks, only near the proposal ──────────────────────
    # Masking every candidate would be ~1800 SAM calls at 0.1 s each; the
    # panel only ever displays a handful, so mask the top few and the pick.
    order = np.argsort(-sim)[:6]
    top_frames = sorted({kept[int(i)] for i in order} | {pick})
    px = calib.template_box[2] + (calib.template_box[3] - calib.template_box[2]) / 2
    py = calib.template_box[0] + (calib.template_box[1] - calib.template_box[0]) / 2
    masks = []
    for f in top_frames:
        frame = raw.get(f) or ncc.read_frames(video, [f]).get(f)
        if frame is None:
            continue
        items = models.segment(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), prompt=prompt)
        paw = models.choose_reaching_paw(items, (px, py), calib.aperture_box)
        if paw is None:
            continue
        payload = overlays.encode_mask(paw["mask"])
        masks.append({"frame": int(f), "score": round(paw["score"], 3),
                      "bbox": list(paw["bbox"]), **payload})
    if job is not None:
        job.progress = 0.98

    return {
        "frames": [int(f) for f in kept],
        "similarity": [round(float(s), 4) for s in sim],
        "armed": [{"start": a.start, "end": a.end} for a in armed],
        "pick": int(pick),
        "n_exemplars": int(len(ref)),
        "masks": masks,
        "top": [{"frame": int(kept[int(i)]), "score": float(sim[int(i)])}
                for i in order],
    }


@bp.post(f"{PREFIX}/score")
def api_score():
    body = request.get_json(force=True) or {}
    video = _resolve(body.get("video"))
    if not video:
        return jsonify({"error": "video not found"}), 404
    try:
        start, end = int(body["start"]), int(body["end"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "start and end required"}), 400
    outcome = body.get("outcome") or "s"
    prompt = (body.get("prompt") or "paw").strip()
    topk = int(body.get("topk") or 5)

    def run(job):
        return _score_window(job, video, start, end, outcome, prompt, topk)

    job = store.registry.start("score", run)
    return jsonify({"job": job.id, "state": "running"})


@bp.get(f"{PREFIX}/job/<job_id>")
def api_job(job_id):
    job = store.registry.get(job_id)
    if job is None:
        return jsonify({"error": "unknown job"}), 404
    return jsonify({"state": job.state, "progress": round(job.progress, 3),
                    "message": job.message, "result": job.result})


@bp.get(f"{PREFIX}/thumb")
def api_thumb():
    """Small JPEG of the embedder's crop, optionally with the SAM mask burnt in.

    Burnt in rather than overlaid client-side because these are 104 px
    thumbnails in a scrolling strip — shipping an RLE per thumbnail to draw two
    dozen tiny canvases costs more than it saves.
    """
    video = _resolve(request.args.get("video"))
    if not video:
        return jsonify({"error": "video not found"}), 404
    try:
        n = int(request.args.get("n") or 0)
    except ValueError:
        return jsonify({"error": "bad frame"}), 400
    got = ncc.read_frames(video, [n])
    if n not in got:
        return jsonify({"error": f"frame {n} unreadable"}), 404

    y0, y1, x0, x1 = exemplars.CROP
    tile = got[n][y0:y1, x0:x1].copy()
    if request.args.get("mask") == "1":
        calib = rig.load(_project(), Path(video).stem)
        if calib is not None:
            items = models.segment(cv2.cvtColor(got[n], cv2.COLOR_BGR2RGB),
                                   prompt=request.args.get("prompt") or "paw")
            px = calib.template_box[2] + (calib.template_box[3] - calib.template_box[2]) / 2
            py = calib.template_box[0] + (calib.template_box[1] - calib.template_box[0]) / 2
            paw = models.choose_reaching_paw(items, (px, py), calib.aperture_box)
            if paw is not None:
                sub = paw["mask"][y0:y1, x0:x1]
                tile[sub] = (0.55 * np.array([80, 220, 120]) +
                             0.45 * tile[sub]).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", tile, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        return jsonify({"error": "encode failed"}), 500
    return Response(buf.tobytes(), mimetype="image/jpeg",
                    headers={"Cache-Control": "public, max-age=300"})


# ── onset sidecar ────────────────────────────────────────────────────────────

def _dilate(mask, margin: int):
    """1-D binary dilation, equivalent to scipy.ndimage.binary_dilation with a
    (2*margin+1) structure — without pulling scipy into a 7.8 GB image.

    Cumulative-sum window rather than np.convolve(mode="same"): convolve
    disagrees with scipy at the boundaries once the kernel is longer than the
    array, which a short CSV would hit.
    """
    mask = np.asarray(mask, dtype=bool)
    n = mask.size
    if n == 0:
        return mask
    cum = np.concatenate(([0], np.cumsum(mask.astype(np.int64))))
    idx = np.arange(n)
    lo = np.maximum(0, idx - margin)
    hi = np.minimum(n, idx + margin + 1)
    return (cum[hi] - cum[lo]) > 0


def _sensor_edges(video, margin: int = 25):
    """Rising edges of the hardware reach sensor in the companion CSV.

    `frame_line_status == 14` fires roughly once per reach and lands within ±25
    frames of the human tag on 76-96 % of trials — the cheapest bracketing
    signal available. Two of ten sessions have a dead sensor, so callers must
    treat an empty result as normal.
    """
    import csv as _csv

    path = notes.csv_path_for(video)
    if not path.is_file():
        return np.array([], dtype=int), []
    frames, status = [], []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in _csv.DictReader(fh, skipinitialspace=True):
            try:
                frames.append(int(float(row["frame_number"])))
                status.append(int(float(row["frame_line_status"])))
            except (TypeError, ValueError, KeyError):
                continue
    if not frames:
        return np.array([], dtype=int), []
    frames = np.asarray(frames)
    trig = np.asarray(status) == 14
    pairs = list(zip(frames.tolist(), status))
    if trig.sum() < 20:                       # a handful of stray 14s is noise
        return np.array([], dtype=int), pairs
    dil = _dilate(trig, margin)
    rise = np.zeros(len(dil), bool)
    rise[0] = dil[0]
    rise[1:] = dil[1:] & ~dil[:-1]
    return frames[rise], pairs


@bp.post(f"{PREFIX}/onset-csv")
def api_onset_csv():
    """Write `<video>_onset.csv` from whatever the pipeline currently knows."""
    body = request.get_json(force=True) or {}
    video = _resolve(body.get("video"))
    if not video:
        return jsonify({"error": "video not found"}), 404
    cached = store.load_sweep(video, config.SWEEP_STRIDE)
    if cached is None:
        return jsonify({"error": "not swept yet — run the pellet sweep first"}), 409

    frames, scores, _n = cached
    _calib, wins = _windows_for(video)
    build = onset_csv.Build()
    build.add_sweep(frames, scores, intervals.PRESENT_THRESHOLD)
    edges, status_pairs = _sensor_edges(video)
    build.add_sensor_edges(edges.tolist())
    if wins:
        build.add_windows(wins)
    # Human tags go in for reference so the sidecar can be read on its own.
    for frame, note in notes.onsets(notes.read_notes(video)):
        build.add_note(frame, note)
    # LAST, deliberately: add_status only fills rows that already exist, and
    # sensor edges and tags create rows off the sweep's stride grid. Running it
    # earlier left frame_line_status blank on exactly the tagged rows — the ones
    # where the sensor column matters most.
    build.add_status(status_pairs)
    out = onset_csv.write(video, build)
    rows = build.to_rows()
    return jsonify({"path": str(out), "summary": onset_csv.summarise(rows)})


@bp.get(f"{PREFIX}/onset-csv")
def api_onset_csv_read():
    """Rows for the timeline. `max_points` thins the pellet trace only — tagged
    rows (sensor edges, notes, scored frames) are always kept, because they are
    the ones the timeline draws as ticks."""
    video = _resolve(request.args.get("video"))
    if not video:
        return jsonify({"error": "video not found"}), 404
    rows = onset_csv.read(video)
    if not rows:
        return jsonify({"error": "no onset csv — build it first"}), 404

    def tagged(r):
        return (str(r.get("sensor_edge") or "0") != "0"
                or str(r.get("note") or "").strip()
                or str(r.get("dino_sim") or "").strip()
                or str(r.get("sam_score") or "").strip())

    keep = [r for r in rows if tagged(r)]
    trace = [r for r in rows if not tagged(r)]
    try:
        cap = max(200, int(request.args.get("max_points") or 4000))
    except ValueError:
        cap = 4000
    if len(trace) > cap:
        step = int(np.ceil(len(trace) / cap))
        trace = trace[::step]
    merged = sorted(keep + trace, key=lambda r: int(r["frame_number"]))
    return jsonify({"path": str(onset_csv.path_for(video)),
                    "summary": onset_csv.summarise(rows),
                    "columns": onset_csv.COLUMNS, "rows": merged})


# ── pellet model: geometry, labels, retraining ───────────────────────────────
#
# The click-to-label flow mirrors DeepLabCut's: the user clicks the pellet on a
# frame, repeats on however many frames they like, then retrains. Labels are
# kept rather than folded straight into the template so a bad click can be
# removed and the template rebuilt without it — clip-cutter's
# remove_frame_from_template makes the same choice for the same reason.


def _model():
    return pm.load(_project()) or pm.PelletModel()


def _cam_payload(cam: pm.CameraModel | None):
    if cam is None:
        return None
    return {"cx": cam.cx, "cy": cam.cy, "half": cam.half, "margin": cam.margin,
            "n_samples": cam.n_samples, "seed_n": cam.seed_n,
            "n_clicks": len(cam.exemplars), "seed_weight": cam.seed_weight,
            "template_box": list(cam.template_box),
            "search_box": list(cam.search_box),
            "has_template": cam.template() is not None}


@bp.get(f"{PREFIX}/pellet/model")
def api_pellet_model():
    m = _model()
    return jsonify({
        "cameras": {k: _cam_payload(v) for k, v in m.cameras.items()},
        "threshold": m.threshold,
        "max_3d_dist": m.max_3d_dist,
        "ref_3d": m.ref_3d,
        "labels": m.corrections,
        "path": str(pm.model_path(_project())),
    })


@bp.put(f"{PREFIX}/pellet/model")
def api_pellet_model_put():
    """Set the box geometry. One set of fields per camera."""
    body = request.get_json(force=True) or {}
    m = _model()
    for cam_name, vals in (body.get("cameras") or {}).items():
        cam = m.cameras.get(cam_name) or pm.CameraModel(cx=0, cy=0)
        for key in ("cx", "cy"):
            if key in vals:
                setattr(cam, key, float(vals[key]))
        for key in ("half", "margin"):
            if key in vals:
                setattr(cam, key, max(4, int(vals[key])))
        if "seed_weight" in vals:
            cam.seed_weight = max(0.0, float(vals["seed_weight"]))
        m.cameras[cam_name] = cam
    if "threshold" in body:
        m.threshold = float(body["threshold"])
    if "max_3d_dist" in body:
        m.max_3d_dist = float(body["max_3d_dist"])
    pm.save(_project(), m)
    return jsonify({"ok": True, "cameras": {k: _cam_payload(v) for k, v in m.cameras.items()}})


@bp.post(f"{PREFIX}/pellet/label")
def api_pellet_label():
    """Record one clicked pellet position."""
    body = request.get_json(force=True) or {}
    video = _resolve(body.get("video"))
    try:
        frame = int(body["frame"]); x = float(body["x"]); y = float(body["y"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "frame, x and y required"}), 400
    cam = body.get("cam") or "cam0"
    if not video:
        return jsonify({"error": "video not found"}), 404
    m = _model()
    m.corrections.append({"video": str(video), "frame": frame, "cam": cam,
                          "x": x, "y": y})
    pm.save(_project(), m)
    return jsonify({"ok": True, "n_labels": len(m.corrections)})


@bp.delete(f"{PREFIX}/pellet/label/<int:index>")
def api_pellet_label_delete(index):
    m = _model()
    if not (0 <= index < len(m.corrections)):
        return jsonify({"error": "no such label"}), 404
    gone = m.corrections.pop(index)
    # Drop the exemplar this click contributed, so the pool never disagrees with
    # the label list. Without this a removed click keeps influencing the template
    # until someone happens to retrain — a stale state with no visible cause.
    cam = m.cameras.get(gone.get("cam") or "cam0")
    if cam is not None:
        cam.exemplars = [e for e in cam.exemplars
                         if not (e.video == gone.get("video")
                                 and e.frame == gone.get("frame"))]
    pm.save(_project(), m)
    return jsonify({"ok": True, "n_labels": len(m.corrections),
                    "n_clicks_in_pool": len(cam.exemplars) if cam else 0})


@bp.post(f"{PREFIX}/pellet/retrain")
def api_pellet_retrain():
    """Fold the user's clicks into the template pool and re-aim the box.

    The workflow this serves: verify the box on a new video, sweep it, and if
    the pellet is being missed, click stationary pellets until it is not. So a
    click must ADD to the pool — the DLC-derived seed is the starting point, not
    the whole story, and it came from sessions whose pedestal sat elsewhere.

    Two earlier versions of this were wrong: one replaced the seed outright
    (three clicks wiped 261 samples), the other used clicks only to move the box
    and threw the appearance information away.
    """
    body = request.get_json(force=True) or {}
    m = _model()
    by_cam: dict[str, list] = {}
    for lab in m.corrections:
        by_cam.setdefault(lab.get("cam") or "cam0", []).append(lab)
    if not by_cam:
        return jsonify({"error": "no clicks yet"}), 400

    built = {}
    for cam_name, labels in by_cam.items():
        cam = m.cameras.get(cam_name)
        if cam is None:
            cam = pm.CameraModel(cx=float(labels[0]["x"]), cy=float(labels[0]["y"]))
            m.cameras[cam_name] = cam
        # Re-cut every click's patch from scratch so the pool always reflects the
        # current list — removing a click actually removes its influence.
        cam.exemplars = []
        added = 0
        for lab in labels:
            key = int(lab["frame"]) - 1
            frames = ncc.read_frames(lab["video"], [key])
            if key not in frames:
                continue
            gray = ncc.to_gray(frames[key])
            xi, yi, h = int(round(lab["x"])), int(round(lab["y"])), cam.half
            if (yi - h < 0 or yi + h > gray.shape[0]
                    or xi - h < 0 or xi + h > gray.shape[1]):
                continue
            cam.add_exemplar(gray[yi - h:yi + h, xi - h:xi + h],
                             video=lab["video"], frame=lab["frame"],
                             x=lab["x"], y=lab["y"])
            added += 1
        # Re-aim on the clicks: on a new video they are the only evidence of
        # where this rig's pedestal actually is.
        if added:
            cam.cx = float(np.median([float(l["x"]) for l in labels]))
            cam.cy = float(np.median([float(l["y"]) for l in labels]))
        built[cam_name] = (f"pool = {cam.seed_n} seed + {added} click(s); "
                           f"box at ({cam.cx:.0f}, {cam.cy:.0f})")

    try:
        cal_path = stereo.find_for_project(_project())
        if cal_path and "cam0" in by_cam and "cam1" in by_cam:
            cal = stereo.load(cal_path)
            key = lambda l: (Path(l["video"]).stem.replace("_cam0_", "_camX_")
                             .replace("_cam1_", "_camX_"), l["frame"])
            c0 = {key(l): l for l in by_cam["cam0"]}
            c1 = {key(l): l for l in by_cam["cam1"]}
            both = sorted(set(c0) & set(c1))
            if both:
                X = cal.triangulate([(c0[k]["x"], c0[k]["y"]) for k in both],
                                    [(c1[k]["x"], c1[k]["y"]) for k in both])
                m.ref_3d = [float(v) for v in np.median(X, axis=0)]
                built["ref_3d"] = f"re-derived from {len(both)} paired click(s)"
    except Exception as exc:                    # noqa: BLE001 - surfaced to the UI
        built["ref_3d"] = f"not updated: {exc}"

    pm.save(_project(), m)
    return jsonify({"ok": True, "built": built,
                    "cameras": {k: _cam_payload(v) for k, v in m.cameras.items()},
                    "ref_3d": m.ref_3d})


@bp.get(f"{PREFIX}/pellet/template.png")
def api_pellet_template_png():
    """The current template, for the panel to display."""
    m = _model()
    cam = m.cameras.get(request.args.get("cam") or "cam0")
    t = cam.template_u8() if cam else None
    if t is None:
        return jsonify({"error": "no template"}), 404
    big = cv2.resize(t, (t.shape[1] * 3, t.shape[0] * 3),
                     interpolation=cv2.INTER_NEAREST)
    ok, buf = cv2.imencode(".png", big)
    if not ok:
        return jsonify({"error": "encode failed"}), 500
    return Response(buf.tobytes(), mimetype="image/png",
                    headers={"Cache-Control": "no-store"})


# ── per-video box confirmation ───────────────────────────────────────────────


@bp.get(f"{PREFIX}/pellet/marks")
def api_marks_get():
    """Human placements for this pair, read from the onset sidecar.

    The sidecar is the source of truth for both the box centre and the pellet
    labels, so the two cannot drift apart. `confirmed` stays in the project
    model: it is a decision about the pair, not an observation of it.
    """
    video = _resolve(request.args.get("video"))
    if not video:
        return jsonify({"error": "video not found"}), 404
    marks = onset_csv.read_marks(video)
    m = _model()
    return jsonify({
        "video": video,
        "marks": marks,
        "confirmed": m.is_confirmed(Path(video).stem),
        "unplaced": [c for c in ("cam0", "cam1")
                     if onset_csv.box_centre(marks, c) is None],
    })


@bp.put(f"{PREFIX}/pellet/marks")
def api_marks_put():
    """Write the pair's marks, MERGING into any existing sidecar.

    Read-modify-write rather than a fresh file: the sidecar also holds the sweep
    trace, the sensor edges and the tags, and placing a box must not wipe them.
    """
    body = request.get_json(force=True) or {}
    video = _resolve(body.get("video"))
    if not video:
        return jsonify({"error": "video not found"}), 404

    build = onset_csv.Build()
    for row in onset_csv.read(video):
        if str(row.get("mark_kind") or "").strip():
            continue                       # marks are replaced wholesale
        build.rows[int(float(row["frame_number"]))] = onset_csv.row_from_csv(row)
    for mk in (body.get("marks") or []):
        try:
            build.add_mark(int(mk["frame"]), str(mk["kind"]), str(mk["cam"]),
                           float(mk["x"]), float(mk["y"]))
        except (KeyError, TypeError, ValueError):
            continue
    onset_csv.write(video, build)

    m = _model()
    if "confirmed" in body:
        vb = m.videos.get(Path(video).stem) or pm.VideoBox()
        vb.confirmed = bool(body["confirmed"])
        m.videos[Path(video).stem] = vb
        pm.save(_project(), m)
    saved = onset_csv.read_marks(video)
    return jsonify({"ok": True, "marks": saved,
                    "confirmed": m.is_confirmed(Path(video).stem),
                    "unplaced": [c for c in ("cam0", "cam1")
                                 if onset_csv.box_centre(saved, c) is None]})


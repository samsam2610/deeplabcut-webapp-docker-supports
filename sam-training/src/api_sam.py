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

from . import config, exemplars, intervals, models, ncc, notes, overlays, rig, store

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

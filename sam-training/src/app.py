"""sam-training debug panel.

Self-contained Flask app, reverse-proxied at /sam-training/ by the main webapp.
Its whole purpose is showing what each stage actually did to a given frame —
OpenCV's boxes and NCC score, SAM's mask, DINO's similarity — because every bug
found in this pipeline so far was invisible in the numbers and obvious in a
picture. See the vane-versus-paw episode in the design doc.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template, request

from . import (config, judging, ncc, notes, overlays, rig, store,
               sweep_cache, tracked)

app = Flask(__name__, template_folder="templates", static_folder="static",
            static_url_path="/sam-training/static")

# Stage 2/3 routes live in their own module — see api_sam.py.
from . import api_sam  # noqa: E402  (after app, avoids a circular import)
app.register_blueprint(api_sam.bp)

PREFIX = "/sam-training"
PROJECT_PATH = os.environ.get(
    "SAM_TRAINING_PROJECT",
    "/user-data/Parra-Data/Disk/DLC-Projects/DREADD-Ali-2026-01-07")

# The tracked DB stores container paths. Inside the container that resolves and
# this is identity; on the host, SAM_TRAINING_PATH_MAP translates. See
# config.to_local for why the failure mode this avoids is worth the indirection.
_host = config.to_local


@app.get(f"{PREFIX}/")
def index():
    return render_template("sam_training.html", prefix=PREFIX)


@app.get(f"{PREFIX}/api/videos")
def api_videos():
    """Tracked videos with their Tag state, so the panel can show which are
    training data and which are the targets."""
    labels = tracked.segment_labels(PROJECT_PATH, "Tag")
    out = []
    for path, tag in sorted(labels.items()):
        rows = notes.read_notes(_host(path))
        trials = notes.pair_trials(rows)
        out.append({
            "path": path,
            "name": Path(path).name,
            "tag": tag or "(unset)",
            "is_training": tag == "Done",
            "n_onsets": len(notes.onsets(rows)),
            "n_outcomes": len(notes.outcomes(rows)),
            "n_orphans": sum(1 for t in trials if t.is_orphan),
        })
    return jsonify({"project": PROJECT_PATH, "videos": out})


@app.post(f"{PREFIX}/api/calibrate")
def api_calibrate():
    body = request.get_json(force=True) or {}
    video = _host(body.get("video") or "")
    if not video or not Path(video).is_file():
        return jsonify({"error": "video not found"}), 404
    calib = rig.calibrate(video)
    rig.save(PROJECT_PATH, Path(video).stem, calib)
    return jsonify({
        "template_frame": calib.template_frame,
        "score": round(calib.score, 3),
        "n_sampled": calib.n_sampled,
        "boxes": [
            overlays.box_layer("pellet-search", calib.search_box, "#3ba7ff",
                               "pellet search"),
            overlays.box_layer("pellet-template", calib.template_box, "#ffd23b",
                               "template"),
            overlays.box_layer("aperture", calib.aperture_box, "#ff5ec4",
                               "aperture"),
        ],
    })


def _cache_args(video):
    """The model and marks that identify this video's sweep.

    Reads the box from the onset sidecar — the same place the sweep gate reads
    it — so the key can never describe a box the detector is not using.
    """
    from . import onset_csv as _oc, pellet_model as _pm
    return _pm.load(PROJECT_PATH), _oc.read_marks(video)


def _sweep_payload(video, stride):
    model, marks = _cache_args(video)
    cached = sweep_cache.load(video, model, marks, stride=stride)
    if cached is None:
        return None
    frames, scores, n_frames = cached
    judge = judging.load(PROJECT_PATH)
    ivs = judging.armed(frames, scores, judge)
    rows = notes.read_notes(video)
    trials = notes.pair_trials(rows)
    wins = judging.build(trials, ivs, judge)
    known = [w for w in wins if w.onset_frame is not None]
    hit = sum(1 for w in known if w.is_candidate(w.onset_frame))
    return {
        "n_frames": n_frames,
        "stride": stride,
        "trace": overlays.downsample_trace(frames, scores),
        "threshold": judge.threshold,
        "judge": judge.to_dict(),
        "armed": [{"start": iv.start, "end": iv.end} for iv in ivs],
        "onsets": [{"frame": f, "note": n} for f, n in notes.onsets(rows)],
        "outcomes": [{"frame": f, "note": n} for f, n in notes.outcomes(rows)],
        "windows": [{"start": w.start, "end": w.end, "outcome": w.outcome,
                     "onset": w.onset_frame, "n_candidates": w.n_candidates,
                     "armed": [{"start": a.start, "end": a.end} for a in w.armed]}
                    for w in wins],
        "acceptance": {"known": len(known), "onset_is_candidate": hit},
    }


@app.post(f"{PREFIX}/api/sweep")
def api_sweep():
    """Return a cached sweep, or start one and hand back a job id."""
    body = request.get_json(force=True) or {}
    video = _host(body.get("video") or "")
    stride = int(body.get("stride") or config.SWEEP_STRIDE)
    if not video or not Path(video).is_file():
        return jsonify({"error": "video not found"}), 404

    # A sweep with an unplaced or unconfirmed box wastes minutes and produces a
    # mask full of paws, so refuse until a human has placed and confirmed it.
    from . import onset_csv as _oc, pellet_model as _pm
    _m = _pm.load(PROJECT_PATH)
    if _m is not None and _m.cameras:
        _marks = _oc.read_marks(video)
        _unplaced = [c for c in ("cam0", "cam1")
                     if _oc.box_centre(_marks, c) is None]
        if _unplaced or not _m.is_confirmed(Path(video).stem):
            return jsonify({"error": "place and confirm the pellet box for this "
                                     "pair first"}), 428

    # `overwrite` forces a recompute even on a cache hit. The cache key already
    # covers the box and the template, so a hit means nothing that affects the
    # result has changed — this is for the cases the key cannot see, such as the
    # video file itself being replaced.
    overwrite = bool(body.get("overwrite"))
    payload = None if overwrite else _sweep_payload(video, stride)
    if payload is not None:
        return jsonify({"state": "done", "cached": True, **payload})

    def run(job):
        calib = rig.load(PROJECT_PATH, Path(video).stem) or rig.calibrate(video)
        rig.save(PROJECT_PATH, Path(video).stem, calib)
        template = rig.load_template(calib)

        def progress(idx, last):
            job.progress = min(0.99, idx / max(1, last))

        sw = ncc.sweep_video(video, template, calib.search_box, stride=stride,
                             progress=progress)
        model, marks = _cache_args(video)
        sweep_cache.save(video, sw.frames, sw.scores, sw.n_frames,
                         model=model, marks=marks, stride=stride)
        return True

    job = store.registry.start("sweep", run)
    return jsonify({"state": "running", "job": job.id})


# NOTE: /api/job/<id> lives in api_sam.py, which serves BOTH the sweep jobs
# started here and the scoring jobs started there. It used to be defined in
# both, with different response shapes — this one omitted `result`, the other
# included it — so which one answered depended on blueprint registration order,
# and the SAM panel silently rendered nothing whenever this one won.


@app.get(f"{PREFIX}/api/frame")
def api_frame():
    """One frame as JPEG. Overlays are drawn client-side, not baked in."""
    video = _host(request.args.get("video") or "")
    try:
        n = int(request.args.get("n") or 0)
    except ValueError:
        return jsonify({"error": "bad frame number"}), 400
    if not video or not Path(video).is_file():
        return jsonify({"error": "video not found"}), 404
    frames = ncc.read_frames(video, [n])
    if n not in frames:
        return jsonify({"error": f"frame {n} unreadable"}), 404
    ok, buf = cv2.imencode(".jpg", frames[n], [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        return jsonify({"error": "encode failed"}), 500
    return Response(buf.tobytes(), mimetype="image/jpeg",
                    headers={"Cache-Control": "public, max-age=300"})


@app.get(f"{PREFIX}/api/layers")
def api_layers():
    """Everything each stage says about ONE frame.

    Stage 2/3 layers are absent until those stages exist; the front-end renders
    whatever it is given, so wiring SAM and DINO in later is additive here and
    needs no front-end change.
    """
    video = _host(request.args.get("video") or "")
    try:
        n = int(request.args.get("n") or 0)
    except ValueError:
        return jsonify({"error": "bad frame number"}), 400
    if not video or not Path(video).is_file():
        return jsonify({"error": "video not found"}), 404

    calib = rig.load(PROJECT_PATH, Path(video).stem)
    if calib is None:
        return jsonify({"error": "not calibrated"}), 409
    frames = ncc.read_frames(video, [n])
    if n not in frames:
        return jsonify({"error": f"frame {n} unreadable"}), 404

    gray = ncc.to_gray(frames[n])
    template = rig.load_template(calib)
    score, top_left = ncc.match(gray, template, calib.search_box)

    layers = [
        overlays.box_layer("pellet-search", calib.search_box, "#3ba7ff",
                           "pellet search"),
        overlays.box_layer("aperture", calib.aperture_box, "#ff5ec4", "aperture"),
        overlays.match_layer("pellet-match", top_left, template.shape, "#ffd23b",
                             score),
        overlays.scalar_layer("ncc", score, 0.0, 1.0, "pellet NCC"),
    ]
    return jsonify({
        "frame": n,
        # The judge's threshold, not the compiled-in one: this endpoint answers
        # "is there a pellet on THIS frame", and it disagreeing with the armed
        # mask on the timeline would be a debugging trap in the one panel whose
        # whole job is showing what each stage decided.
        "pellet_present": bool(score > judging.load(PROJECT_PATH).threshold),
        "layers": layers,
        "pending": ["sam-mask", "dino-similarity"],
    })


@app.get(f"{PREFIX}/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("SAM_TRAINING_PORT", 5060)))

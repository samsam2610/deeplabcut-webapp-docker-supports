"""Endpoints the "3D Inline Analysis - SAM Model" card calls.

The card is a client: it renders what these return and never infers anything
itself. Splitting the routes out of app.py keeps the stage 0/1 debug panel and
the stage 2/3 scoring independently readable.
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
from flask import Blueprint, Response, jsonify, request

from . import (config, exemplars, intervals, judging, models, motion3d, ncc,
               notes, onset_csv, overlays, pellet_model as pm, pipeline, rig,
               stereo, store, sweep_cache, tagwrite, trials)

bp = Blueprint("sam_api", __name__)
PREFIX = "/sam-training/api"

# How many candidate frames one /score call may embed. A window can hold ~1800
# armed frames; at DINOv3's ~300 img/s that is still only seconds, but the cap
# stops a pathological window from pinning the GPU for a minute.
MAX_CANDIDATES = 2500

# How close a SAM instance must sit to the centroid the scorer recorded for the
# thumbnail to accept it as the same instance. Generous: SAM is re-run here and
# a mask can shift a little, but the wrong paw is hundreds of px away.
THUMB_MATCH_PX = 30.0


def _recorded_paw(video, frame: int, cam: str):
    """The paw centroid the scorer stored for this (frame, camera), or None.

    The motion sidecar belongs to the pair's cam0 member, so a cam1 thumbnail
    has to look across to its sibling for it.
    """
    src = video
    if "_cam0_" not in Path(video).name:
        sib = pm.sibling_video(video)
        if sib is None:
            return None
        src = str(sib)
    key = "cam0" if cam == "cam0" else "cam1"
    for r in motion3d.read(src):
        try:
            if (int(float(r["frame"])) != int(frame)
                    or r.get("source") != motion3d.SOURCE_SAM
                    or r.get("marker") != "paw_centroid"):
                continue
            x, y = r.get(f"{key}_x", ""), r.get(f"{key}_y", "")
            if not str(x).strip() or not str(y).strip():
                return None
            return (float(x), float(y))
        except (TypeError, ValueError):
            continue
    return None


def _project():
    import os
    return os.environ.get(
        "SAM_TRAINING_PROJECT",
        "/user-data/Parra-Data/Disk/DLC-Projects/DREADD-Ali-2026-01-07")


def _resolve(video: str) -> str | None:
    local = config.to_local(video or "")
    return local if local and Path(local).is_file() else None


def _judge():
    return judging.load(_project())


def _windows_for(video: str):
    """Stage 0+1 for one video, from cache. None when it has not been swept."""
    calib = rig.load(_project(), Path(video).stem)
    if calib is None:
        calib = rig.calibrate(video)
        rig.save(_project(), Path(video).stem, calib)
    st = pipeline.windows_for(_project(), video)
    return calib, (None if st is None else st.windows)


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
        "judge": _judge().to_dict(),
        # Every human note, so the strip can draw the marker that closes each
        # window — and any that a raised guard has let inside one. On a
        # tag-pending video these are the only human marks that exist.
        "markers": [{"frame": f, "note": n}
                    for f, n in notes.human_marks(notes.read_notes(video))],
        # EVERY note frame, including our own candidates: note navigation steps
        # through all of them, and the panel follows it to the containing trial.
        "note_frames": [f for f, _n in notes.read_notes(video)],
        "windows": [{"start": w.start, "end": w.end, "outcome": w.outcome,
                     "onset": w.onset_frame, "n_candidates": w.n_candidates,
                     "armed": [{"start": a.start, "end": a.end} for a in w.armed]}
                    for w in wins],
    })


@bp.get(f"{PREFIX}/pellet/check")
def api_pellet_check():
    """Score the pooled template at each camera's PLACED box on one frame.

    A wrong box is otherwise silent: it costs a seven-minute sweep and comes
    back with a mask full of paws. Two template matches on one frame is
    milliseconds, so there is no reason not to say so before the sweep.
    """
    video = _resolve(request.args.get("video"))
    if not video:
        return jsonify({"error": "video not found"}), 404
    sibling = pm.sibling_video(video)
    if sibling is None:
        return jsonify({"error": "no cam1 file found beside this video"}), 404
    frame = int(float(request.args.get("frame") or 1))
    model = pipeline.model_for(_project(), video)
    if model is None:
        return jsonify({"error": "no pellet model for this project"}), 404
    threshold = _judge().threshold

    out = {}
    for cam, path in (("cam0", video), ("cam1", str(sibling))):
        camera = model.cameras.get(cam)
        if camera is None:
            continue
        frames = ncc.read_frames(path, [max(0, frame - 1)])   # 1-based -> 0-based
        img = frames.get(max(0, frame - 1))
        if img is None:
            out[cam] = {"ok": False, "score": None,
                        "message": f"frame {frame} unreadable on {cam}"}
            continue
        score, _pt = pm.match(ncc.to_gray(img), camera)
        out[cam] = pm.placement_verdict(score, threshold)
        out[cam]["centre"] = [camera.cx, camera.cy]
    return jsonify({"frame": frame, "threshold": threshold, "cameras": out,
                    "ok": all(v.get("ok") for v in out.values()) and bool(out)})


# ── stored trial results, batch scoring, and writing tags ───────────────────


def _trial_rows(video):
    """Stored results joined to the current windows and the live tag state."""
    st = pipeline.windows_for(_project(), video)
    wins = [] if st is None else st.windows
    stored = {}
    for r in trials.read(video):
        try:
            stored[int(float(r["marker"]))] = r
        except (TypeError, ValueError):
            continue
    rows = notes.read_notes(video)
    sig = judging.signature(_judge())
    out = []
    for i, w in enumerate(wins):
        got = stored.get(w.end)
        state = notes.tag_state(rows, w.start, w.end)
        out.append({
            "index": i, "marker": w.end, "start": w.start, "end": w.end,
            "outcome": w.outcome, "n_candidates": w.n_candidates,
            "onset": w.onset_frame,
            "result": None if got is None else {
                "pick": int(float(got["pick"])), "mode": got.get("mode"),
                # Reconstructed from the per-frame scores when the row predates
                # the ranking column — exact, by the rule the scorer used, not
                # frames guessed around the pick.
                "top": (trials.parse_top(got.get("top"))
                        or motion3d.top_for_window(video, w.start, w.end)),
                "score": float(got["score"]) if str(got.get("score") or "").strip() else None,
                "judge_sig": got.get("judge_sig"),
                # Not an error, just visible: this row was scored under a
                # different gate than the one currently in force.
                "stale": got.get("judge_sig") not in ("", None, sig),
                "scored_at": got.get("scored_at"),
            },
            "tag": state,
        })
    return out


@bp.get(f"{PREFIX}/trials")
def api_trials():
    video = _resolve(request.args.get("video"))
    if not video:
        return jsonify({"error": "video not found"}), 404
    sib = pm.sibling_video(video)
    return jsonify({"video": video, "judge_sig": judging.signature(_judge()),
                    # cam1 thumbnails need it, and it is the same for every
                    # trial in the video, so it is sent once.
                    "sibling": None if sib is None else str(sib),
                    "trials": _trial_rows(video),
                    "can_undo": bool(tagwrite.last_batch(notes.csv_path_for(video)))})


@bp.post(f"{PREFIX}/trials/batch")
def api_trials_batch():
    """Score every trial and store the result. Resumable and cancellable."""
    body = request.get_json(force=True) or {}
    video = _resolve(body.get("video"))
    if not video:
        return jsonify({"error": "video not found"}), 404
    mode = "3d" if str(body.get("mode") or "").lower() == "3d" else "2d"
    recompute = bool(body.get("recompute"))
    prompt = (body.get("prompt") or "right paw").strip()
    topk = int(body.get("topk") or 5)

    def run(job):
        st = pipeline.windows_for(_project(), video)
        if st is None:
            raise RuntimeError("not swept yet — run the pellet sweep first")
        wins = st.windows
        done = set() if recompute else trials.scored_markers(video)
        todo = [w for w in wins if w.end not in done]
        scorer = _score_window_3d if mode == "3d" else _score_window
        ok, failed = 0, []
        for n, w in enumerate(todo):
            job.progress = n / max(1, len(todo))
            job.message = f"trial {n + 1}/{len(todo)} (marker {w.end})"
            try:
                res = scorer(None, video, w.start, w.end, w.outcome, prompt, topk)
            except Exception as exc:                    # noqa: BLE001
                # One bad trial must not abandon the other 128.
                failed.append({"marker": w.end, "error": f"{type(exc).__name__}: {exc}"[:200]})
                continue
            ok += 1          # the scorer stored it on the way out
        return {"scored": ok, "skipped": len(wins) - len(todo),
                "failed": failed, "mode": mode}

    job = store.registry.start(f"batch-{mode}", run)
    return jsonify({"job": job.id, "state": "running"})


def _store_result(video, start, end, outcome, mode, prompt, res):
    """Persist one scoring result.

    Called by the scorers themselves, so EVERY run stores — a single run used to
    vanish the moment you browsed away, which made the stored ranking look
    broken when it was simply never written.
    """
    kept = res.get("frames") or []
    trials.merge(video, [trials.Row(
        marker=int(end), window_start=int(start), outcome=outcome, mode=mode,
        pick=int(res["pick"]), score=_score_at(res, int(res["pick"])),
        top=[int(t["frame"]) for t in (res.get("top") or [])],
        n_candidates=len(kept),
        n_kept=len(kept) - int(res.get("n_rejected") or 0),
        prompt=prompt, judge_sig=judging.signature(_judge()),
        scored_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))])


def _score_at(result, frame):
    frames = result.get("frames") or []
    sims = result.get("similarity") or []
    if frame in frames and len(sims) == len(frames):
        return float(sims[frames.index(frame)])
    return None


def _write_tags(video, requests_):
    """Place and commit ``[(marker, start, frame, note)]``. Returns a report."""
    csv_path = notes.csv_path_for(video)
    existing = tagwrite.notes_by_frame(csv_path)
    pairs, spans, placed, refused = [], {}, [], []
    for marker, start, frame, note in requests_:
        at, blocked = tagwrite.place(existing, frame)
        if at is None:
            refused.append({"marker": marker, "frame": frame,
                            "blocked": [{"frame": f, "note": v} for f, v in blocked]})
            continue
        pairs.append((at, note))
        spans[at] = (start, marker)
        existing[at] = note              # so two tags cannot claim one row
        placed.append({"marker": marker, "frame": at, "note": note,
                       "shifted": at - frame})
    batch = tagwrite.commit(csv_path, pairs, spans=spans, backup=True) if pairs else None
    return {"written": len(pairs), "batch": batch,
            "placed": placed, "refused": refused}


@bp.post(f"{PREFIX}/tag")
def api_tag():
    """Write ONE reviewed tag: a real start-success / start-failure.

    Real, not `-candidate`: a human is looking at the frame when they press it.
    """
    body = request.get_json(force=True) or {}
    video = _resolve(body.get("video"))
    if not video:
        return jsonify({"error": "video not found"}), 404
    try:
        marker = int(body["marker"])
        frame = int(body["frame"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "marker and frame required"}), 400
    outcome = str(body.get("outcome") or "s")
    if outcome not in notes.OUTCOMES:
        return jsonify({"error": "outcome must be s or f"}), 400
    note = (notes.ONSET_SUCCESS if outcome == notes.OUTCOME_SUCCESS
            else notes.ONSET_FAILURE)
    start = int(body.get("start") or 0)
    report = _write_tags(video, [(marker, start, frame, note)])
    if report["refused"]:
        blocked = report["refused"][0]["blocked"]
        near = ", ".join(f"{b['frame']}:{b['note']}" for b in blocked[:4])
        return jsonify({"error": f"every frame within ±{tagwrite.RADIUS} of {frame} "
                                 f"already has a note ({near}) — nothing written",
                        **report}), 409
    return jsonify(report)


@bp.post(f"{PREFIX}/tag/batch")
def api_tag_batch():
    """Write every stored result as a `-candidate`.

    `-candidate`, not the real tag: nobody has looked at these. The suffix is
    also what keeps them out of the exemplar bank, since notes.onsets() matches
    exactly — so unreviewed output can never become training data.
    """
    body = request.get_json(force=True) or {}
    video = _resolve(body.get("video"))
    if not video:
        return jsonify({"error": "video not found"}), 404
    include_tagged = bool(body.get("include_tagged"))
    rows = notes.read_notes(video)
    todo, skipped = [], 0
    for t in _trial_rows(video):
        if not t["result"]:
            continue
        if t["tag"] and t["tag"]["kind"] == "human" and not include_tagged:
            skipped += 1
            continue
        base = (notes.ONSET_SUCCESS if t["outcome"] == notes.OUTCOME_SUCCESS
                else notes.ONSET_FAILURE)
        todo.append((t["marker"], t["start"], t["result"]["pick"],
                     base + notes.CANDIDATE_SUFFIX))
    report = _write_tags(video, todo)
    report["skipped_tagged"] = skipped
    return jsonify(report)


@bp.post(f"{PREFIX}/tag/undo")
def api_tag_undo():
    body = request.get_json(force=True) or {}
    video = _resolve(body.get("video"))
    if not video:
        return jsonify({"error": "video not found"}), 404
    n = tagwrite.undo(notes.csv_path_for(video))
    return jsonify({"reverted": n,
                    "can_undo": bool(tagwrite.last_batch(notes.csv_path_for(video)))})


@bp.get(f"{PREFIX}/judge")
def api_judge_get():
    return jsonify(_judge().to_dict())


@bp.put(f"{PREFIX}/judge")
def api_judge_put():
    """Store the judging parameters, clamped.

    Returns what was STORED, not what was sent: the panel re-renders from the
    response, so a clamped value is visible rather than silently applied.
    """
    judge = judging.from_dict(request.get_json(force=True) or {})
    judging.save(_project(), judge)
    return jsonify(judge.to_dict())


def _read_candidates(video, candidates, box, job=None, share=0.45, base=0.05,
                     on_frame=None, keep_raw=0):
    """Read a video's candidate frames once, sequentially, cropping as we go.

    Sequential rather than seeking per frame: at stride 5 a seek costs more than
    a decode, and this runs over the window twice (once per camera).

    ``on_frame`` is called with each full frame and its result kept instead of
    the frame. A window can hold 2500 candidates, and 2500 x 800x600x3 is 3.5 GB
    per camera — so the 3D path segments during the read and keeps a centroid,
    rather than buffering 7 GB of video to segment afterwards.

    ``keep_raw`` retains at most that many full frames for a caller that cannot
    know which ones it needs until later; the rest are re-read on demand.
    """
    # `candidates` are 1-based frame_numbers; cv2 counts from 0. This is the
    # only place the conversion happens on the way in.
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, candidates[0] - 1)
    wanted = set(candidates)
    crops, kept, raw, extra = [], [], {}, {}
    idx, last = candidates[0], candidates[-1]
    while idx <= last:
        ok, frame = cap.read()          # idx is the frame_number just read
        if not ok:
            break
        if idx in wanted:
            crops.append(exemplars.crop_rgb(frame, box))
            kept.append(idx)
            if on_frame is not None:
                extra[idx] = on_frame(idx, frame)
            if len(raw) < keep_raw:
                raw[idx] = frame
        idx += 1
        if job is not None and len(kept) % 100 == 0:
            job.progress = base + share * (len(kept) / max(1, len(candidates)))
    cap.release()
    return crops, kept, raw, extra


def _segment(frame_bgr, prompt):
    return models.segment(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB),
                          prompt=prompt)


def _paw_point(frame_bgr, camera, prompt):
    """(centroid, score, mask) for the reaching paw, or (None, None, None).

    The mask CENTROID, not the bbox centre: one splayed digit moves a bbox far
    more than it moves the mass, and this point is about to be compared across
    two views that see different silhouettes.
    """
    paw = models.choose_reaching_paw(_segment(frame_bgr, prompt),
                                     (camera.cx, camera.cy))
    if paw is None:
        return None, None, None
    centre = pm.mask_centroid(paw["mask"])
    if centre is None:
        return None, None, None
    return centre, float(paw.get("score") or 0.0), paw["mask"]


def _paw_on_epiline(frame_bgr, prompt, p0, cal, judge):
    """cam1's paw CHOSEN by cam0's epipolar line: (centroid, score, residual).

    Not "pick nearest cam1's pellet, then check". At the onset the emerging paw
    is small and the nearest-to-pellet instance in cam1 is a different paw, so
    that comparison rejected the best candidate in the window at ~189 px while
    the right instance sat at rank 2 in the same SAM output.
    """
    if p0 is None or cal is None:
        return None, None, None
    items = _segment(frame_bgr, prompt)
    centres, keep = [], []
    for it in items:
        c = pm.mask_centroid(it["mask"])
        if c is not None:
            centres.append(c)
            keep.append(it)
    if not centres:
        return None, None, None
    res = stereo.epipolar_residual(cal, [p0] * len(centres), centres)
    idx = judging.pick_by_epiline(res.tolist(), judge)
    if idx is None:
        # Report the best residual anyway: a rejection with no number attached
        # cannot be diagnosed from the motion CSV.
        return None, None, float(min(res))
    return centres[idx], float(keep[idx].get("score") or 0.0), float(res[idx])


def _score_window_3d(job, video, start, end, outcome, prompt, topk):
    """Stage 2 + 3 over one trial window, using BOTH cameras.

    Geometry vetoes and the learned model chooses: a candidate survives only if
    the two views' paws are the same paw (epipolar residual within the judge's
    tolerance), and among survivors the highest fused DINO similarity wins.

    The alternative — folding 3D terms into the score — needs blend weights that
    only the +-5 frame accuracy could justify, so the 3D evidence gates instead.
    """
    sibling = pm.sibling_video(video)
    if sibling is None:
        raise RuntimeError("no cam1 file beside this video; 3D scoring needs both")
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

    judge = _judge()
    model = pipeline.model_for(_project(), video)
    if model is None or not model.cameras:
        raise RuntimeError("no pellet model for this project")
    cams = {"cam0": model.cameras.get("cam0"), "cam1": model.cameras.get("cam1")}
    if not all(cams.values()):
        raise RuntimeError("the pellet model needs both cameras for 3D scoring")
    stereo_cal = stereo.load(stereo.find_for_video(_project(), video))

    # ── read both cameras ─────────────────────────────────────────────────
    c0, kept0, _r0, paw0 = _read_candidates(
        video, candidates, exemplars.crop_for(cams["cam0"]), job,
        share=0.35, base=0.02,
        on_frame=lambda _i, fr: _paw_point(fr, cams["cam0"], prompt))
    # cam1 is read SECOND and its paw is chosen by cam0's epipolar line for the
    # same frame — which is why cam0 must be complete before this starts.
    c1, kept1, _r1, paw1 = _read_candidates(
        str(sibling), candidates, exemplars.crop_for(cams["cam1"]), job,
        share=0.35, base=0.37,
        on_frame=lambda i, fr: _paw_on_epiline(
            fr, prompt, (paw0.get(i) or (None,))[0], stereo_cal, judge))
    common = sorted(set(kept0) & set(kept1))
    if not common:
        raise RuntimeError("no frame could be read from both cameras")
    i0 = {f: i for i, f in enumerate(kept0)}
    i1 = {f: i for i, f in enumerate(kept1)}

    # ── stage 3: DINO on both, fused by mean ──────────────────────────────
    # mean, not min: the paw is transiently occluded in one view on many frames,
    # and min lets either view veto a frame the other is certain about. A
    # wrong-paw match is the epipolar gate's job, not the score's.
    sims = {}
    for cam, crops, idx, keep in (("cam0", c0, i0, kept0), ("cam1", c1, i1, kept1)):
        bank = exemplars.get(_project(), cam=cam)
        ref = bank.for_query(outcome, exclude_video=Path(video).stem)
        if not len(ref):
            raise RuntimeError(f"no '{outcome}' exemplars outside this session ({cam})")
        sims[cam] = models.similarity(models.embed(crops), ref, topk=topk)
    if job is not None:
        job.progress = 0.82

    fused = np.array([(float(sims["cam0"][i0[f]]) + float(sims["cam1"][i1[f]])) / 2.0
                      for f in common])

    # ── stage 2: SAM on both, epipolar gate, triangulate ──────────────────
    rows, ok_mask, epi_all, masks = [], [], [], []
    for n, f in enumerate(common):
        p0, s0, m0 = paw0[f]
        p1, _s1, epi = paw1[f]
        X = None
        if p0 is not None and p1 is not None and stereo_cal is not None:
            X = stereo_cal.triangulate([p0], [p1])[0]
        keep = X is not None
        ok_mask.append(keep)
        epi_all.append(epi)
        if m0 is not None and keep:
            masks.append((f, m0, s0))
        # every candidate is recorded, rejections included: the residual is the
        # only thing that explains a frame that should have been kept and wasn't
        rows.append(motion3d.Row(
            frame=int(f), source=motion3d.SOURCE_SAM, marker="paw_centroid",
            cam0_x=None if p0 is None else p0[0], cam0_y=None if p0 is None else p0[1],
            cam1_x=None if p1 is None else p1[0], cam1_y=None if p1 is None else p1[1],
            X=None if X is None else float(X[0]),
            Y=None if X is None else float(X[1]),
            Z=None if X is None else float(X[2]),
            epi_px=epi, score=float(fused[n])))
        if job is not None and n % 100 == 0:
            job.progress = 0.85 + 0.14 * (n / max(1, len(common)))

    motion3d.merge(video, rows)

    ok = np.array(ok_mask, dtype=bool)
    if not ok.any():
        raise RuntimeError(
            f"every candidate failed the paw check (epipolar tol "
            f"{judge.max_epi_px:.0f}px) — widen it, or check the paw is visible "
            f"in both cameras")
    scored = np.where(ok, fused, -np.inf)
    pick = common[int(np.argmax(scored))]

    order = [i for i in np.argsort(-scored) if ok[i]][:5]
    out = {
        "mode": "3d",
        "frames": [int(f) for f in common],
        "similarity": [round(float(v), 4) for v in fused],
        "similarity_cam0": [round(float(sims["cam0"][i0[f]]), 4) for f in common],
        "similarity_cam1": [round(float(sims["cam1"][i1[f]]), 4) for f in common],
        "epi_px": [None if e is None else round(e, 2) for e in epi_all],
        "kept": [bool(v) for v in ok],
        "armed": [{"start": a.start, "end": a.end} for a in armed],
        "pick": int(pick),
        "n_rejected": int((~ok).sum()),
        "epi_tol": judge.max_epi_px,
        "sibling": str(sibling),
        "motion3d": str(motion3d.path_for(video)),
        "top": [{"frame": int(common[int(i)]), "score": float(fused[int(i)])}
                for i in order],
    }
    _store_result(video, start, end, outcome, "3d", prompt, out)
    return out


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

    # The shared reader: same 1-based -> cv2 conversion, and the crop follows
    # the placed box. This path had its own copy that seeked without the -1, so
    # once frames became 1-based every crop was a frame late.
    model = pipeline.model_for(_project(), video)
    cam0 = model.cameras.get("cam0") if model else None
    crops, kept, raw, _extra = _read_candidates(
        video, candidates, exemplars.crop_for(cam0) if cam0 else None, job,
        keep_raw=12)
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
        # f is a 1-based frame_number; ncc.read_frames indexes from 0.
        frame = raw.get(f)
        if frame is None:
            frame = ncc.read_frames(video, [f - 1]).get(f - 1)
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

    out = {
        "frames": [int(f) for f in kept],
        "similarity": [round(float(s), 4) for s in sim],
        "armed": [{"start": a.start, "end": a.end} for a in armed],
        "pick": int(pick),
        "n_exemplars": int(len(ref)),
        "masks": masks,
        "top": [{"frame": int(kept[int(i)]), "score": float(sim[int(i)])}
                for i in order],
    }
    _store_result(video, start, end, outcome, "2d", prompt, out)
    return out


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

    # One endpoint, two modes: the 3D path reuses the whole job/poll plumbing
    # rather than duplicating it under a second route.
    three_d = str(body.get("mode") or "").lower() in ("3d", "3D")
    scorer = _score_window_3d if three_d else _score_window

    def run(job):
        return scorer(job, video, start, end, outcome, prompt, topk)

    job = store.registry.start("score3d" if three_d else "score", run)
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
    # `cam` says which camera's crop and pellet centre to use. The crop is
    # anchored on the pellet, and cam1's sits 177px right of cam0's, so serving
    # a cam1 frame through cam0's rectangle shows the wrong part of the rig.
    cam = request.args.get("cam") or "cam0"
    model = pipeline.model_for(_project(), video)
    camera = (model.cameras.get(cam) if model else None)

    # `n` is a 1-based frame_number, like every other frame the API exchanges.
    got = ncc.read_frames(video, [n - 1])
    if (n - 1) not in got:
        return jsonify({"error": f"frame {n} unreadable"}), 404

    y0, y1, x0, x1 = exemplars.crop_for(camera) if camera else exemplars.CROP
    tile = got[n - 1][y0:y1, x0:x1].copy()
    if request.args.get("mask") == "1" and camera is not None:
        items = models.segment(cv2.cvtColor(got[n - 1], cv2.COLOR_BGR2RGB),
                               prompt=request.args.get("prompt") or "paw")
        centroids = [pm.mask_centroid(it["mask"]) for it in items]
        # Draw the instance the SCORER used, recorded in the motion sidecar.
        # Re-choosing here disagreed with the scorer on every frame of the trial
        # that was reported: cam1's paw is picked by cam0's epipolar line, and
        # nearest-this-camera's-pellet finds a different paw.
        ref = _recorded_paw(video, n, cam)
        idx = pm.pick_nearest(centroids, ref, THUMB_MATCH_PX)
        if idx is None and ref is None:
            # No record for this frame (a 2D run, or a stale sidecar): fall back
            # to the old rule rather than showing nothing.
            paw = models.choose_reaching_paw(items, (camera.cx, camera.cy))
            idx = items.index(paw) if paw is not None else None
        if idx is not None:
            mask = items[idx]["mask"]
            sub = mask[y0:y1, x0:x1]
            if sub.any():
                tile[sub] = (0.55 * np.array([80, 220, 120]) +
                             0.45 * tile[sub]).astype(np.uint8)
            else:
                # Found, but entirely outside the crop. Without this marker the
                # tile is indistinguishable from "SAM found nothing", which is
                # how a working detector reads as a broken one.
                c = centroids[idx]
                px = int(np.clip(c[0] - x0, 2, (x1 - x0) - 3))
                py = int(np.clip(c[1] - y0, 2, (y1 - y0) - 3))
                cv2.drawMarker(tile, (px, py), (60, 220, 255),
                               cv2.MARKER_TRIANGLE_UP, 12, 2)
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
    st = pipeline.windows_for(_project(), video)
    if st is None:
        return jsonify({"error": "not swept yet — run the pellet sweep first"}), 409

    wins = st.windows
    build = onset_csv.Build()
    # FIRST: the human's box and pellet clicks. Everything else in this file is
    # derived and can be recomputed; these cannot, and rewriting without them
    # deletes the placement and re-blocks sweeping.
    onset_csv.carry_marks(build, onset_csv.read_marks(video))
    build.add_pair_sweep(st.frames, st.score0, st.score1, st.dist3d,
                         judging.decide_pair(st.score0, st.score1, st.dist3d,
                                             st.judge))
    edges, status_pairs = _sensor_edges(video)
    build.add_sensor_edges(edges.tolist())
    if wins:
        build.add_windows(wins)
    # Human notes go in for reference so the sidecar can be read on its own —
    # the s/f MARKERS as well as the start tags, because a tag-pending video
    # has only the former and drawing onsets alone left its timeline blank.
    for frame, note in notes.human_marks(notes.read_notes(video)):
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
        # The calibration nearest the CLICKED video, not the project's last one:
        # a 3D reference is only meaningful in the frame that produced it, and
        # these clicks come from one specific recording.
        clicked = (by_cam.get("cam0") or by_cam.get("cam1") or [{}])[0].get("video")
        cal_path = stereo.find_for_video(_project(), clicked) if clicked else None
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


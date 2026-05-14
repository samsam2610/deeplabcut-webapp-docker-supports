"""Flask blueprint for /dlc-3d/lp/* endpoints."""
import os
from pathlib import Path
from flask import Blueprint, jsonify, request

lp_bp = Blueprint("dlc_3d_lp", __name__, url_prefix="/dlc-3d/lp")

_USER_DATA_ROOT = "/user-data"


def _under_user_data(p: Path) -> bool:
    try:
        return str(p.resolve()).startswith(_USER_DATA_ROOT + "/")
    except Exception:
        return False


def _worker_reachable() -> bool:
    """Best-effort: ping the lp_3d queue's worker via Celery inspect.

    Returns False if Celery isn't importable or no worker responds in 1s.
    """
    try:
        from dlc_3d_bp.lp.celery_app import celery
    except Exception:
        return False
    try:
        replies = celery.control.inspect(timeout=1.0).ping() or {}
        return bool(replies)
    except Exception:
        return False


@lp_bp.route("/health")
def health():
    return jsonify({
        "ok": True,
        "worker_reachable": _worker_reachable(),
        "queue": "lp_3d",
        "broker_url": os.environ.get("CELERY_BROKER_URL", ""),
    })


@lp_bp.route("/convert", methods=["POST"])
def convert():
    from dlc_3d_bp.lp.converter import convert_dlc_to_lp
    import dlc_3d_bp.routes as routes_mod

    body = request.get_json(force=True, silent=True) or {}
    dlc = (body.get("dlc_dir") or "").strip()
    lp = (body.get("lp_dir") or "").strip()
    force = bool(body.get("force", False))

    # Default dlc_dir to the server's active DLC project.
    if not dlc:
        with routes_mod._state_lock:
            dlc = routes_mod._active_project or ""
        if not dlc:
            return jsonify({"error": "no active DLC project — load one in the DLC project card first, or pass dlc_dir"}), 400

    # Default lp_dir to <dlc_dir>-LP/.
    if not lp:
        lp = dlc.rstrip("/") + "-LP"

    dlc_p, lp_p = Path(dlc), Path(lp)
    if not (_under_user_data(dlc_p) and _under_user_data(lp_p)):
        return jsonify({"error": "paths must resolve under /user-data/"}), 403
    try:
        summary = convert_dlc_to_lp(dlc_p, lp_p, force=force)
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(summary), 201


def _redis_conn():
    """Return a redis client or None if redis isn't reachable."""
    try:
        import redis
        url = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0")
        c = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1.0)
        c.ping()
        return c
    except Exception:
        return None


@lp_bp.route("/job/<job_id>")
def job_status(job_id: str):
    from dlc_3d_bp.lp import job_registry
    conn = _redis_conn()
    row = job_registry.get(conn, job_id) if conn else None
    if not row:
        return jsonify({"error": "unknown job"}), 404
    # Augment with Celery AsyncResult state
    try:
        from dlc_3d_bp.lp.celery_app import celery
        ar = celery.AsyncResult(job_id)
        row["celery_state"] = ar.state
        if ar.info and isinstance(ar.info, dict):
            row["celery_info"] = ar.info
    except Exception:
        pass
    # Tail recent log lines if present
    if conn:
        log_lines = conn.lrange(f"dlc3d:lp:log:{job_id}", -200, -1)
        if log_lines:
            row["log_tail"] = log_lines
    return jsonify(row)


@lp_bp.route("/jobs")
def jobs_index():
    from dlc_3d_bp.lp import job_registry
    conn = _redis_conn()
    if not conn:
        return jsonify({"jobs": []})
    return jsonify({"jobs": job_registry.list_recent(conn, limit=50)})


@lp_bp.route("/eks", methods=["POST"])
def eks_run():
    from dlc_3d_bp.lp.tasks import lp_eks

    body = request.get_json(force=True, silent=True) or {}
    mode = body.get("mode")
    in_paths = body.get("in_paths") or []
    if mode not in ("single", "multi"):
        return jsonify({"error": "mode must be 'single' or 'multi'"}), 400
    if not in_paths:
        return jsonify({"error": "in_paths required"}), 400
    for p in in_paths:
        if not _under_user_data(Path(p)):
            return jsonify({"error": f"path outside /user-data: {p}"}), 403
    if mode == "single":
        out_csv = (body.get("out_csv") or "").strip()
        if not out_csv:
            return jsonify({"error": "out_csv required for single mode"}), 400
        if not _under_user_data(Path(out_csv)):
            return jsonify({"error": f"out_csv outside /user-data: {out_csv}"}), 403
    else:  # multi
        out_dir = (body.get("out_dir") or "").strip()
        if not out_dir:
            return jsonify({"error": "out_dir required for multi mode"}), 400
        if not _under_user_data(Path(out_dir)):
            return jsonify({"error": f"out_dir outside /user-data: {out_dir}"}), 403

    async_result = lp_eks.apply_async(args=[body])
    conn = _redis_conn()
    if conn:
        from dlc_3d_bp.lp.job_registry import register
        register(conn, async_result.id, {
            "type": "eks",
            "mode": mode,
            "in_paths": in_paths,
            "out": body.get("out_csv") or body.get("out_dir"),
        })
    return jsonify({"job_id": async_result.id}), 202


@lp_bp.route("/train", methods=["POST"])
def train_run():
    from dlc_3d_bp.lp.tasks import lp_train
    import dlc_3d_bp.routes as routes_mod

    body = request.get_json(force=True, silent=True) or {}
    project = (body.get("lp_project") or "").strip()
    options = body.get("options") or {}

    # Default lp_project to <active DLC project>-LP/ when omitted.
    if not project:
        with routes_mod._state_lock:
            active_dlc = routes_mod._active_project or ""
        if active_dlc:
            project = active_dlc.rstrip("/") + "-LP"
        else:
            return jsonify({"error": "no active DLC project — load one first or pass lp_project"}), 400
    if not _under_user_data(Path(project)):
        return jsonify({"error": "lp_project must be under /user-data"}), 403

    async_result = lp_train.apply_async(args=[project, options])
    conn = _redis_conn()
    if conn:
        from dlc_3d_bp.lp.job_registry import register
        register(conn, async_result.id, {
            "type": "train",
            "lp_project": project,
            "options": options,
        })
    return jsonify({"job_id": async_result.id}), 202


def _active_lp_project_default() -> str:
    """Return '<active DLC project>-LP/' if a DLC project is loaded, else ''."""
    import dlc_3d_bp.routes as routes_mod
    with routes_mod._state_lock:
        active_dlc = routes_mod._active_project or ""
    return (active_dlc.rstrip("/") + "-LP") if active_dlc else ""


@lp_bp.route("/models")
def list_models_route():
    """List trained model run dirs in an LP project.

    Query: ?lp_project=<path>   (defaults to <active DLC project>-LP/)
    """
    from dlc_3d_bp.lp.predict_runner import list_models

    project = (request.args.get("lp_project") or "").strip()
    if not project:
        project = _active_lp_project_default()
    if not project:
        return jsonify({"error": "no active DLC project — load one first or pass lp_project", "models": []}), 400
    if not _under_user_data(Path(project)):
        return jsonify({"error": "lp_project must be under /user-data", "models": []}), 403
    if not Path(project).is_dir():
        return jsonify({"lp_project": project, "models": [], "warning": "lp_project does not exist"}), 200
    return jsonify({"lp_project": project, "models": list_models(project)})


@lp_bp.route("/predict", methods=["POST"])
def predict_run():
    from dlc_3d_bp.lp.tasks import lp_predict
    from dlc_3d_bp.lp.predict_runner import list_models

    body = request.get_json(force=True, silent=True) or {}
    model_dir = (body.get("model_dir") or "").strip()
    videos = body.get("videos") or []
    skip_viz = bool(body.get("skip_viz", False))
    overwrite = bool(body.get("overwrite", False))

    # Default model_dir to the newest model in <active LP project>/models/
    if not model_dir:
        lp_project = (body.get("lp_project") or "").strip() or _active_lp_project_default()
        if not lp_project:
            return jsonify({"error": "no active DLC project — load one first or pass model_dir/lp_project"}), 400
        if not _under_user_data(Path(lp_project)):
            return jsonify({"error": "lp_project must be under /user-data"}), 403
        models = list_models(lp_project)
        usable = [m for m in models if m["has_checkpoint"]]
        if not usable:
            return jsonify({"error": f"no trained models with a checkpoint found under {lp_project}/models/"}), 400
        model_dir = usable[0]["path"]  # newest first per list_models()

    if not _under_user_data(Path(model_dir)):
        return jsonify({"error": "model_dir must be under /user-data"}), 403
    if not Path(model_dir).is_dir():
        return jsonify({"error": f"model_dir does not exist: {model_dir}"}), 400

    if not videos:
        return jsonify({"error": "at least one video required"}), 400
    for v in videos:
        if not _under_user_data(Path(v)):
            return jsonify({"error": f"video path outside /user-data: {v}"}), 403

    async_result = lp_predict.apply_async(args=[model_dir, videos, skip_viz, overwrite])
    conn = _redis_conn()
    if conn:
        from dlc_3d_bp.lp.job_registry import register
        register(conn, async_result.id, {
            "type": "predict",
            "model_dir": model_dir,
            "videos": videos,
            "skip_viz": skip_viz,
            "overwrite": overwrite,
        })
    return jsonify({"job_id": async_result.id, "model_dir": model_dir}), 202

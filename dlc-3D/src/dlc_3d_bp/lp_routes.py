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

    body = request.get_json(force=True, silent=True) or {}
    dlc = (body.get("dlc_dir") or "").strip()
    lp = (body.get("lp_dir") or "").strip()
    force = bool(body.get("force", False))
    if not dlc or not lp:
        return jsonify({"error": "dlc_dir and lp_dir required"}), 400
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

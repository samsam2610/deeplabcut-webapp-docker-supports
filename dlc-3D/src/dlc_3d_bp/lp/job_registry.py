"""Redis-backed job index for LP/EKS jobs.

Tiny: one hash per job + one sorted-set index keyed by enqueue timestamp.
Used purely for surfacing in the UI; not authoritative for Celery state.
"""
from __future__ import annotations

import json
import time

_INDEX_KEY = "dlc3d:lp:jobs"
_JOB_KEY   = "dlc3d:lp:job:{id}"
_DEFAULT_LIMIT = 50


def register(redis_conn, job_id: str, meta: dict) -> None:
    score = time.time()
    redis_conn.zadd(_INDEX_KEY, {job_id: score})
    payload = dict(meta)
    payload["id"] = job_id
    payload["created_at"] = score
    redis_conn.hset(_JOB_KEY.format(id=job_id), mapping={
        k: (v if isinstance(v, str) else json.dumps(v)) for k, v in payload.items()
    })
    # Trim index to most recent 200
    redis_conn.zremrangebyrank(_INDEX_KEY, 0, -201)


def get(redis_conn, job_id: str) -> dict | None:
    raw = redis_conn.hgetall(_JOB_KEY.format(id=job_id))
    if not raw:
        return None
    return _decode(raw)


def list_recent(redis_conn, limit: int = _DEFAULT_LIMIT) -> list[dict]:
    ids = redis_conn.zrevrange(_INDEX_KEY, 0, limit - 1)
    out = []
    for jid in ids:
        raw = redis_conn.hgetall(_JOB_KEY.format(id=jid))
        if raw:
            out.append(_decode(raw))
    return out


def _decode(raw: dict) -> dict:
    out = {}
    for k, v in raw.items():
        try:
            out[k] = json.loads(v)
        except (TypeError, json.JSONDecodeError):
            out[k] = v
    return out

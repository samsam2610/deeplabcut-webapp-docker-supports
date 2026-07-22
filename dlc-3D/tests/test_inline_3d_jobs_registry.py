"""Tracking inline-analysis 'Start analysis' runs in the Jobs card.

Covers three surfaces:
  1. Backend  — POST /dlc-3d/lp/register-inline writes a ``type:"analyze"`` job
     into the SAME registry the Jobs card reads.
  2. JS wiring — inline_analysis_3d.js registers each dispatched req; lp_cards.js
     augments analyze rows from the inline-analysis status endpoint and renders them.
  3. Template  — the Jobs card is titled "Jobs" (holds LP + analyze rows).
"""
import re
import sys
import types
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
INLINE_JS = ROOT / "src" / "static" / "inline_analysis_3d.js"
CARDS_JS = ROOT / "src" / "static" / "lp_cards.js"
JOBS_HTML = ROOT / "src" / "templates" / "partials" / "card_lp_jobs.html"
LAUNCHER_HTML = ROOT / "src" / "templates" / "partials" / "card_lp_launcher.html"


# ── Backend route ──────────────────────────────────────────────────────────

def _app():
    from dlc_3d_bp import lp_routes
    a = Flask(__name__)
    a.register_blueprint(lp_routes.lp_bp)
    return a


def test_register_inline_writes_analyze_job(monkeypatch):
    """POST /register-inline calls job_registry.register with type=analyze."""
    captured = {}

    class _FakeRedis:
        def ping(self):
            return True

    def _fake_register(conn, job_id, meta):
        captured["job_id"] = job_id
        captured["meta"] = meta

    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: _FakeRedis())
    monkeypatch.setattr("dlc_3d_bp.lp.job_registry.register", _fake_register)

    c = _app().test_client()
    r = c.post("/dlc-3d/lp/register-inline", json={
        "req_id": "abc-123",
        "video": "/user-data/proj/videos/cam0.mp4",
        "start_frame": 100,
        "n_frames": 500,
    })
    assert r.status_code == 202, r.get_data(as_text=True)
    assert r.get_json()["job_id"] == "abc-123"
    assert captured["job_id"] == "abc-123"
    assert captured["meta"]["type"] == "analyze"
    assert captured["meta"]["video"] == "/user-data/proj/videos/cam0.mp4"
    assert captured["meta"]["range"] == [100, 500]


def test_register_inline_accepts_triangulate_type(monkeypatch):
    """POST /register-inline with type=triangulate stores a triangulate job."""
    captured = {}

    class _FakeRedis:
        def ping(self):
            return True

    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: _FakeRedis())
    monkeypatch.setattr("dlc_3d_bp.lp.job_registry.register",
                        lambda conn, jid, meta: captured.update(job_id=jid, meta=meta))

    c = _app().test_client()
    r = c.post("/dlc-3d/lp/register-inline", json={
        "req_id": "tri-9", "video": "/user-data/proj/videos/cam0.mp4",
        "start_frame": 192148, "n_frames": 800, "type": "triangulate",
    })
    assert r.status_code == 202, r.get_data(as_text=True)
    assert captured["meta"]["type"] == "triangulate"
    assert captured["meta"]["range"] == [192148, 800]


def test_register_inline_unknown_type_falls_back_to_analyze(monkeypatch):
    captured = {}

    class _FakeRedis:
        def ping(self):
            return True

    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: _FakeRedis())
    monkeypatch.setattr("dlc_3d_bp.lp.job_registry.register",
                        lambda conn, jid, meta: captured.update(meta=meta))
    c = _app().test_client()
    c.post("/dlc-3d/lp/register-inline", json={"req_id": "x", "type": "bogus"})
    assert captured["meta"]["type"] == "analyze"


def test_register_inline_requires_req_id(monkeypatch):
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: object())
    c = _app().test_client()
    r = c.post("/dlc-3d/lp/register-inline", json={"video": "/user-data/x.mp4"})
    assert r.status_code == 400


def test_register_inline_503_without_redis(monkeypatch):
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    c = _app().test_client()
    r = c.post("/dlc-3d/lp/register-inline", json={"req_id": "x"})
    assert r.status_code == 503


def test_register_inline_roundtrips_through_real_registry():
    """Job written via register() must be readable through list_recent/get —
    proving analyze rows land in the same index the Jobs card reads."""
    from dlc_3d_bp.lp import job_registry

    store = {}
    zset = {}

    class _FakeConn:
        def zadd(self, key, mapping):
            zset.setdefault(key, {}).update(mapping)

        def zrevrange(self, key, start, end):
            items = sorted(zset.get(key, {}).items(), key=lambda kv: kv[1], reverse=True)
            return [k for k, _ in items][start:end + 1]

        def zremrangebyrank(self, *a, **k):
            pass

        def hset(self, key, mapping=None):
            store[key] = dict(mapping)

        def hgetall(self, key):
            return store.get(key, {})

    conn = _FakeConn()
    job_registry.register(conn, "req-9", {"type": "analyze", "video": "/v.mp4", "range": [0, 10]})
    rows = job_registry.list_recent(conn)
    assert any(r["id"] == "req-9" and r["type"] == "analyze" for r in rows)
    one = job_registry.get(conn, "req-9")
    assert one["range"] == [0, 10]


# ── JS wiring: inline_analysis_3d.js registers each dispatched req ──────────

def test_submit_range_registers_inline_job():
    s = INLINE_JS.read_text()
    # _submitRange must call the register helper with the returned req_id.
    assert "_registerInlineJob(d.req_id" in s, "_submitRange must register the dispatched req"
    # Helper posts to the module route.
    assert "/dlc-3d/lp/register-inline" in s, "register helper must POST to /dlc-3d/lp/register-inline"
    m = re.search(r"function\s+_registerInlineJob\s*\(", s)
    assert m, "expected a _registerInlineJob helper"


# ── JS wiring: lp_cards.js renders analyze rows with live progress ─────────

def test_jobs_card_augments_analyze_rows_from_inline_status():
    s = CARDS_JS.read_text()
    # analyze rows pull state from the inline-analysis status endpoint.
    assert "/dlc/project/inline-analysis/range/status" in s, (
        "Jobs card must poll the inline-analysis status endpoint for analyze rows"
    )
    assert "augmentAnalyze" in s
    # inline status -> celery_state vocabulary mapping present.
    assert re.search(r"done\s*:\s*[\"']SUCCESS[\"']", s), "must map inline 'done' -> SUCCESS"
    assert re.search(r"error\s*:\s*[\"']FAILURE[\"']", s), "must map inline 'error' -> FAILURE"
    # fmtRow handles the analyze type and its video target.
    assert 'j.type === "analyze"' in s
    assert "j.video" in s, "fmtRow must fall back to j.video for analyze rows"


# ── JS wiring: triangulate rows registered + rendered ──────────────────────

def test_triangulate_runs_register_a_job():
    s = INLINE_JS.read_text()
    m = re.search(r"function\s+_registerTriangulateJob\s*\(", s)
    assert m, "expected a _registerTriangulateJob helper"
    # posts the triangulate type to the shared register route
    assert re.search(r'type:\s*"triangulate"', s), "helper must tag the job type triangulate"
    # both the single-range button and the tag-batch register their dispatched req
    assert s.count("_registerTriangulateJob(data.req_id") >= 2, (
        "both single-range and batch triangulate must register their req"
    )


def test_jobs_card_augments_triangulate_rows():
    s = CARDS_JS.read_text()
    assert "augmentTriangulate" in s
    assert "/dlc/project/triangulate/range/status" in s, (
        "Jobs card must poll the triangulate status endpoint for triangulate rows"
    )
    assert 'j.type === "triangulate"' in s, "fmtRow must handle the triangulate type"
    # triangulate rows (main-webapp Celery) are not LP-cancelable
    assert 'j.type !== "triangulate"' in s, "triangulate rows must not offer Cancel"
    assert "openTriangulateDetail" in s, "detail view must handle triangulate rows"


def test_jobs_card_idle_polls_while_open():
    """An open Jobs card must keep polling even with no live job, so a run started
    elsewhere (e.g. a triangulate batch) appears without a manual Refresh."""
    s = CARDS_JS.read_text()
    # dual-interval poll: fast when live, slow idle poll otherwise
    assert re.search(r"hasLive\s*\?\s*5000\s*:\s*15000", s), "must idle-poll (15s) when nothing is live"
    # the timer is gated on visibility, not on hasLive
    assert re.search(r"if\s*\(\s*!card\.classList\.contains\(\"hidden\"\)\s*\)\s*\{\s*\n\s*autoRefreshTimer", s), (
        "auto-refresh must run whenever the card is visible, not only when hasLive"
    )


# ── Template ───────────────────────────────────────────────────────────────

def test_jobs_card_title_is_jobs():
    html = JOBS_HTML.read_text()
    assert "<h2>Jobs</h2>" in html, "card title must be 'Jobs' (LP + analyze)"
    assert "LP Jobs" not in html, "old 'LP Jobs' title must be gone"
    assert "inline-analysis" in html.lower(), "subtitle should mention inline-analysis"


def test_launcher_button_renamed_to_jobs():
    html = LAUNCHER_HTML.read_text()
    assert "<span>Jobs</span>" in html
    assert "LP Jobs" not in html

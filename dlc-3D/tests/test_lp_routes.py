import sys, types
import pytest
from flask import Flask


# Partials referenced by dlc_3d.html that live in the main webapp's
# image at runtime (overlay via Docker) but are absent from this repo.
# The fixture writes empty stubs so the page renders in unit tests.
_OVERLAY_PARTIALS = (
    "session_dlc_bar.html",
    "session_anipose_bar.html",
    "card_dlc_project.html",
    "card_training_dataset.html",
    "card_train_network.html",
    "card_analyze.html",
    "card_annotator.html",
    "card_gpu_monitor.html",
    "card_dlc_config.html",
    "card_custom_script.html",
    "card_project_explorer.html",
    "card_session_actions.html",
    "card_config_editor.html",
    "card_admin.html",
)


@pytest.fixture
def lp_app(tmp_path):
    sys.modules.pop("app", None)
    sys.modules.pop("base_app", None)
    stub = types.ModuleType("base_app")
    stub.app = Flask(
        "base_app_stub",
        template_folder=str(tmp_path),
        static_folder=str(tmp_path),
    )
    sys.modules["base_app"] = stub
    (tmp_path / "base.html").write_text(
        "<html><head>{% block extra_head %}{% endblock %}</head>"
        "<body>{% block content %}{% endblock %}"
        "{% block scripts %}{% endblock %}</body></html>"
    )
    partials_dir = tmp_path / "partials"
    partials_dir.mkdir()
    for name in _OVERLAY_PARTIALS:
        (partials_dir / name).write_text("")
    import app as dlc3d_app_mod
    return dlc3d_app_mod.app


def test_lp_package_imports():
    from dlc_3d_bp import lp  # noqa: F401
    from dlc_3d_bp.lp import (  # noqa: F401
        celery_app, tasks, converter, eks_runner, train_runner,
        project_layout, job_registry,
    )


def test_lp_blueprint_imports():
    from dlc_3d_bp.lp_routes import lp_bp
    assert lp_bp.url_prefix == "/dlc-3d/lp"


def test_lp_blueprint_registered(lp_app):
    assert "dlc_3d_lp" in lp_app.blueprints


def test_health_endpoint(lp_app):
    client = lp_app.test_client()
    r = client.get("/dlc-3d/lp/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert "worker_reachable" in body


def test_index_renders_with_lp_cards(lp_app):
    client = lp_app.test_client()
    r = client.get("/dlc-3d/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    for cid in ("lp-convert-card", "lp-train-card", "lp-eks-card", "lp-jobs-card"):
        assert cid in html, f"missing {cid}"


def test_convert_endpoint_400_when_no_active_project_and_no_dlc_dir(lp_app, monkeypatch):
    # Ensure dlc-3D's active-project state is empty
    import dlc_3d_bp.routes as r_mod
    monkeypatch.setattr(r_mod, "_active_project", None, raising=False)
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/convert", json={})
    assert r.status_code == 400
    msg = r.get_json().get("error", "").lower()
    assert "project" in msg  # message should reference loading a project


def test_convert_endpoint_uses_active_project_when_dlc_dir_omitted(lp_app, monkeypatch, tmp_path):
    """Server-side _active_project is the source of truth when client omits dlc_dir."""
    import dlc_3d_bp.routes as r_mod

    fake_active = "/user-data/fake/proj"
    monkeypatch.setattr(r_mod, "_active_project", fake_active, raising=False)
    monkeypatch.setattr("dlc_3d_bp.lp_routes._under_user_data", lambda p: True)

    captured = {}
    def _fake_convert(dlc, lp, **kwargs):
        captured["dlc"], captured["lp"], captured["kwargs"] = str(dlc), str(lp), kwargs
        return {"n_views": 0, "n_frames": 0, "n_sessions": 0, "n_calibrations": 0,
                "warnings": [], "output_dir": str(lp)}
    monkeypatch.setattr("dlc_3d_bp.lp.converter.convert_dlc_to_lp", _fake_convert)

    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/convert", json={})
    assert r.status_code == 201, r.get_data(as_text=True)
    assert captured["dlc"] == fake_active
    # Default lp_dir = <dlc>-LP
    assert captured["lp"] == fake_active + "-LP"


def test_convert_endpoint_defaults_lp_dir(lp_app, monkeypatch):
    monkeypatch.setattr("dlc_3d_bp.lp_routes._under_user_data", lambda p: True)
    captured = {}
    def _fake_convert(dlc, lp, **kwargs):
        captured["lp"] = str(lp)
        return {"n_views": 0, "n_frames": 0, "n_sessions": 0, "n_calibrations": 0,
                "warnings": [], "output_dir": str(lp)}
    monkeypatch.setattr("dlc_3d_bp.lp.converter.convert_dlc_to_lp", _fake_convert)
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/convert", json={"dlc_dir": "/user-data/x/proj"})
    assert r.status_code == 201
    assert captured["lp"] == "/user-data/x/proj-LP"


def test_convert_endpoint_rejects_outside_user_data(lp_app):
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/convert", json={
        "dlc_dir": "/etc",
        "lp_dir":  "/etc-lp",
    })
    assert r.status_code == 403


def test_lp_launcher_renders_inside_main(lp_app):
    """Regression: LP includes must live INSIDE <main> so they inherit the
    centering layout. card_admin.html closes </main>, so LP partials must
    come BEFORE it in dlc_3d.html."""
    c = lp_app.test_client()
    r = c.get("/dlc-3d/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    end_main = html.find("</main>")
    launcher = html.find('id="lp-launcher-card"')
    assert launcher != -1
    assert end_main != -1
    assert launcher < end_main, "lp-launcher-card renders AFTER </main> — layout will break"


def test_job_status_endpoint_returns_404_for_unknown(lp_app, monkeypatch):
    # Force _redis_conn to return None so the registry lookup is skipped
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    c = lp_app.test_client()
    r = c.get("/dlc-3d/lp/job/does-not-exist")
    assert r.status_code == 404


def test_jobs_index_endpoint(lp_app, monkeypatch):
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    c = lp_app.test_client()
    r = c.get("/dlc-3d/lp/jobs")
    assert r.status_code == 200
    body = r.get_json()
    assert "jobs" in body and isinstance(body["jobs"], list)


def test_eks_endpoint_validates_input(lp_app):
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/eks", json={})
    assert r.status_code == 400


def test_eks_endpoint_enqueues(lp_app, monkeypatch):
    class _FakeAsync:
        id = "fake-job-id"

    monkeypatch.setattr(
        "dlc_3d_bp.lp.tasks.lp_eks.apply_async",
        lambda *a, **k: _FakeAsync(),
    )
    monkeypatch.setattr(
        "dlc_3d_bp.lp_routes._under_user_data",
        lambda p: True,
    )
    # No-op redis to skip registration side-effects
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/eks", json={
        "mode": "single",
        "in_paths": ["/user-data/x/pred.csv"],
        "out_csv": "/user-data/x/pred_eks.csv",
        "s": 1.0,
    })
    assert r.status_code == 202
    body = r.get_json()
    assert body["job_id"] == "fake-job-id"


def test_train_endpoint_enqueues(lp_app, monkeypatch):
    class _FakeAsync:
        id = "fake-train-id"

    monkeypatch.setattr(
        "dlc_3d_bp.lp.tasks.lp_train.apply_async",
        lambda *a, **k: _FakeAsync(),
    )
    monkeypatch.setattr(
        "dlc_3d_bp.lp_routes._under_user_data",
        lambda p: True,
    )
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/train", json={
        "lp_project": "/user-data/x/lp",
        "options": {"mvt_enabled": True, "reproj_loss_enabled": True},
    })
    assert r.status_code == 202
    assert r.get_json()["job_id"] == "fake-train-id"


def test_models_endpoint_400_without_active_project(lp_app, monkeypatch):
    import dlc_3d_bp.routes as r_mod
    monkeypatch.setattr(r_mod, "_active_project", None, raising=False)
    c = lp_app.test_client()
    r = c.get("/dlc-3d/lp/models")
    assert r.status_code == 400


def test_models_endpoint_lists_runs(lp_app, monkeypatch, tmp_path):
    """Server lists model run dirs newest-first with checkpoint detection."""
    monkeypatch.setattr("dlc_3d_bp.lp_routes._under_user_data", lambda p: True)
    # Synthetic LP project with two runs, one with a checkpoint
    lp = tmp_path / "fakelp"
    (lp / "models" / "20260101-000000" / "tb_logs" / "x" / "version_0" / "checkpoints").mkdir(parents=True)
    (lp / "models" / "20260101-000000" / "tb_logs" / "x" / "version_0" / "checkpoints" / "epoch=0-best.ckpt").write_bytes(b"")
    (lp / "models" / "20260102-000000").mkdir(parents=True)  # no checkpoint
    c = lp_app.test_client()
    r = c.get(f"/dlc-3d/lp/models?lp_project={lp}")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["models"]) == 2
    # newest first
    assert body["models"][0]["run_id"] == "20260102-000000"
    assert body["models"][0]["has_checkpoint"] is False
    assert body["models"][1]["has_checkpoint"] is True


def test_predict_endpoint_400_without_videos(lp_app, monkeypatch):
    monkeypatch.setattr("dlc_3d_bp.lp_routes._under_user_data", lambda p: True)
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/predict", json={"model_dir": "/user-data/x/m"})
    assert r.status_code == 400


def test_predict_endpoint_403_outside_user_data(lp_app):
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/predict", json={
        "model_dir": "/etc",
        "videos": ["/etc/passwd"],
    })
    assert r.status_code == 403


def test_predict_endpoint_enqueues_with_explicit_model(lp_app, monkeypatch, tmp_path):
    class _FakeAsync:
        id = "fake-predict-id"

    md = tmp_path / "m"
    md.mkdir()
    monkeypatch.setattr("dlc_3d_bp.lp_routes._under_user_data", lambda p: True)
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    monkeypatch.setattr(
        "dlc_3d_bp.lp.tasks.lp_predict.apply_async",
        lambda *a, **k: _FakeAsync(),
    )
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/predict", json={
        "model_dir": str(md),
        "videos": ["/user-data/x/v.mp4"],
        "skip_viz": True,
    })
    assert r.status_code == 202, r.get_data(as_text=True)
    assert r.get_json()["job_id"] == "fake-predict-id"


def test_predict_endpoint_picks_newest_model_with_checkpoint(lp_app, monkeypatch, tmp_path):
    class _FakeAsync:
        id = "fake-id"
    captured = {}
    def _fake_apply(args=None, **kwargs):
        captured["model_dir"] = args[0]
        return _FakeAsync()

    monkeypatch.setattr("dlc_3d_bp.lp_routes._under_user_data", lambda p: True)
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    monkeypatch.setattr("dlc_3d_bp.lp.tasks.lp_predict.apply_async", _fake_apply)

    lp = tmp_path / "lp"
    (lp / "models" / "20260101-000000" / "tb_logs" / "x" / "version_0" / "checkpoints").mkdir(parents=True)
    (lp / "models" / "20260101-000000" / "tb_logs" / "x" / "version_0" / "checkpoints" / "epoch=0-best.ckpt").write_bytes(b"")
    # Newer run without checkpoint should be skipped
    (lp / "models" / "20260102-000000").mkdir(parents=True)

    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/predict", json={
        "lp_project": str(lp),
        "videos": ["/user-data/x/v.mp4"],
    })
    assert r.status_code == 202, r.get_data(as_text=True)
    assert captured["model_dir"].endswith("20260101-000000")


def test_predict_endpoint_accepts_empty_dest_dir(lp_app, monkeypatch, tmp_path):
    class _FakeAsync:
        id = "fake-id"
    captured = {}
    def _fake_apply(args=None, **kwargs):
        captured["args"] = list(args)
        return _FakeAsync()

    md = tmp_path / "m"; md.mkdir()
    monkeypatch.setattr("dlc_3d_bp.lp_routes._under_user_data", lambda p: True)
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    monkeypatch.setattr("dlc_3d_bp.lp.tasks.lp_predict.apply_async", _fake_apply)
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/predict", json={
        "model_dir": str(md),
        "videos": ["/user-data/x/v.mp4"],
        "dest_dir": "",
    })
    assert r.status_code == 202, r.get_data(as_text=True)
    # Args order: [model_dir, videos, skip_viz, overwrite, dest_dir]
    assert captured["args"][-1] == ""


def test_predict_endpoint_forwards_dest_dir(lp_app, monkeypatch, tmp_path):
    class _FakeAsync:
        id = "fake-id"
    captured = {}
    def _fake_apply(args=None, **kwargs):
        captured["args"] = list(args)
        return _FakeAsync()

    md = tmp_path / "m"; md.mkdir()
    monkeypatch.setattr("dlc_3d_bp.lp_routes._under_user_data", lambda p: True)
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    monkeypatch.setattr("dlc_3d_bp.lp.tasks.lp_predict.apply_async", _fake_apply)
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/predict", json={
        "model_dir": str(md),
        "videos": ["/user-data/x/v.mp4"],
        "dest_dir": "/user-data/where/i/want/it",
    })
    assert r.status_code == 202, r.get_data(as_text=True)
    assert captured["args"][-1] == "/user-data/where/i/want/it"


def test_predict_endpoint_rejects_dest_dir_outside_user_data(lp_app, monkeypatch, tmp_path):
    md = tmp_path / "m"; md.mkdir()
    # Allow model_dir + videos through but NOT dest_dir
    def _under(p):
        return not str(p).startswith("/etc")
    monkeypatch.setattr("dlc_3d_bp.lp_routes._under_user_data", _under)
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/predict", json={
        "model_dir": str(md),
        "videos": ["/user-data/x/v.mp4"],
        "dest_dir": "/etc/badplace",
    })
    assert r.status_code == 403


def test_jobs_index_augments_with_celery_state(lp_app, monkeypatch):
    """`/lp/jobs` must surface celery_state and celery_info for each row, same
    as the single-job route — otherwise the Jobs card shows '?' for every job."""
    class _FakeAR:
        def __init__(self, jid):
            self.id = jid
            self.state = "STARTED"
            self.info = {"stage": "stage1_training", "last_line": "Epoch 0: 20%|..."}

    class _FakeRedis:
        def ping(self): return True

    def _fake_list_recent(conn, limit=50):
        return [
            {"id": "job-a", "type": "train", "lp_project": "/p"},
            {"id": "job-b", "type": "predict", "model_dir": "/m"},
        ]
    monkeypatch.setattr("dlc_3d_bp.lp.job_registry.list_recent", _fake_list_recent)
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: _FakeRedis())
    monkeypatch.setattr("dlc_3d_bp.lp.celery_app.celery.AsyncResult", lambda jid: _FakeAR(jid))

    c = lp_app.test_client()
    r = c.get("/dlc-3d/lp/jobs")
    body = r.get_json()
    assert r.status_code == 200
    jobs = body["jobs"]
    assert len(jobs) == 2
    # Each row must carry celery_state and celery_info
    for j in jobs:
        assert j["celery_state"] == "STARTED"
        assert j["celery_info"]["stage"] == "stage1_training"


def test_cancel_endpoint_revokes_job(lp_app, monkeypatch):
    """POST /lp/job/<id>/cancel issues a Celery revoke and returns 200."""
    revoked = {}
    class _FakeControl:
        def revoke(self, jid, terminate=False, signal=None):
            revoked["id"] = jid
            revoked["terminate"] = terminate
            revoked["signal"] = signal
    class _FakeCelery:
        control = _FakeControl()
    monkeypatch.setattr("dlc_3d_bp.lp.celery_app.celery", _FakeCelery())
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/job/abc-123/cancel")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert revoked["id"] == "abc-123"
    assert revoked["terminate"] is True
    assert revoked["signal"] == "SIGTERM"


def test_lp_videos_add_symlink(tmp_path, monkeypatch):
    from dlc_3d_bp import lp_routes
    # Allow tmp_path as USER_DATA root for this test
    monkeypatch.setattr(lp_routes, "_USER_DATA_ROOT", str(tmp_path.resolve()))

    lp = tmp_path / "proj"
    lp.mkdir()
    (lp / "config.yaml").write_text("d:{}\n")
    (lp / "videos").mkdir()
    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")

    a = Flask(__name__)
    a.register_blueprint(lp_routes.lp_bp)
    c = a.test_client()
    r = c.post("/dlc-3d/lp/videos/add",
               json={"lp_project": str(lp), "video_paths": [str(src)], "mode": "symlink"})
    assert r.status_code == 201, r.get_data(as_text=True)
    j = r.get_json()
    assert j["added"] == [str(lp / "videos" / "v.mp4")]


def test_lp_videos_add_rejects_outside_user_data(tmp_path, monkeypatch):
    from dlc_3d_bp import lp_routes
    monkeypatch.setattr(lp_routes, "_USER_DATA_ROOT", "/nope")
    a = Flask(__name__)
    a.register_blueprint(lp_routes.lp_bp)
    c = a.test_client()
    r = c.post("/dlc-3d/lp/videos/add",
               json={"lp_project": str(tmp_path / "proj"),
                     "video_paths": [str(tmp_path / "v.mp4")], "mode": "symlink"})
    assert r.status_code == 403


def test_lp_convert_sync_mode_passes_through(monkeypatch, tmp_path):
    from dlc_3d_bp import lp_routes
    monkeypatch.setattr(lp_routes, "_USER_DATA_ROOT", str(tmp_path.resolve()))

    received = {}

    def fake_convert(dlc, lp, **kwargs):
        received["dlc"] = str(dlc)
        received["lp"] = str(lp)
        received["kwargs"] = kwargs
        return {"output_dir": str(lp), "n_sessions": 0, "n_views": 0, "warnings": []}

    monkeypatch.setattr("dlc_3d_bp.lp.converter.convert_dlc_to_lp", fake_convert)

    dlc = tmp_path / "dlc"
    dlc.mkdir()
    (dlc / "config.yaml").write_text("")
    lp = tmp_path / "lp"
    lp.mkdir()

    a = Flask(__name__)
    a.register_blueprint(lp_routes.lp_bp)
    c = a.test_client()
    r = c.post("/dlc-3d/lp/convert",
               json={"dlc_dir": str(dlc), "lp_dir": str(lp), "mode": "sync"})
    assert r.status_code == 201, r.get_data(as_text=True)
    assert received["kwargs"].get("mode") == "sync"


def test_videos_list_endpoint(tmp_path, monkeypatch):
    from dlc_3d_bp import lp_routes
    monkeypatch.setattr(lp_routes, "_USER_DATA_ROOT", str(tmp_path))
    lp = tmp_path / "proj"; lp.mkdir()
    (lp / "config.yaml").write_text("d:{}\n"); (lp / "videos").mkdir()
    (lp / "videos" / "a.mp4").write_bytes(b"123")

    from flask import Flask
    a = Flask(__name__); a.register_blueprint(lp_routes.lp_bp)
    c = a.test_client()
    r = c.get(f"/dlc-3d/lp/videos/list?lp_project={lp}")
    assert r.status_code == 200
    j = r.get_json()
    assert j["videos"][0]["name"] == "a.mp4"
    assert j["videos"][0]["size_bytes"] == 3


def test_videos_list_rejects_outside_user_data(tmp_path, monkeypatch):
    from dlc_3d_bp import lp_routes
    monkeypatch.setattr(lp_routes, "_USER_DATA_ROOT", "/nope")
    from flask import Flask
    a = Flask(__name__); a.register_blueprint(lp_routes.lp_bp)
    c = a.test_client()
    r = c.get(f"/dlc-3d/lp/videos/list?lp_project={tmp_path / 'proj'}")
    assert r.status_code == 403


def test_videos_delete_endpoint(tmp_path, monkeypatch):
    from dlc_3d_bp import lp_routes
    monkeypatch.setattr(lp_routes, "_USER_DATA_ROOT", str(tmp_path))
    lp = tmp_path / "proj"; lp.mkdir()
    (lp / "config.yaml").write_text("d:{}\n"); (lp / "videos").mkdir()
    (lp / "videos" / "v.mp4").write_bytes(b"")

    from flask import Flask
    a = Flask(__name__); a.register_blueprint(lp_routes.lp_bp)
    c = a.test_client()
    r = c.post("/dlc-3d/lp/videos/delete",
               json={"lp_project": str(lp), "video_names": ["v.mp4"]})
    assert r.status_code == 200
    assert r.get_json()["deleted"] == ["v.mp4"]
    assert not (lp / "videos" / "v.mp4").exists()


def test_videos_delete_path_traversal_400(tmp_path, monkeypatch):
    from dlc_3d_bp import lp_routes
    monkeypatch.setattr(lp_routes, "_USER_DATA_ROOT", str(tmp_path))
    lp = tmp_path / "proj"; lp.mkdir()
    (lp / "config.yaml").write_text(""); (lp / "videos").mkdir()
    from flask import Flask
    a = Flask(__name__); a.register_blueprint(lp_routes.lp_bp)
    c = a.test_client()
    r = c.post("/dlc-3d/lp/videos/delete",
               json={"lp_project": str(lp), "video_names": ["../escape.txt"]})
    assert r.status_code == 400

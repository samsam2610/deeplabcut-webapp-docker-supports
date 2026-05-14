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
    def _fake_convert(dlc, lp, force=False):
        captured["dlc"], captured["lp"], captured["force"] = str(dlc), str(lp), force
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
    def _fake_convert(dlc, lp, force=False):
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

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


def test_convert_endpoint_validates_input(lp_app):
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/convert", json={})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_convert_endpoint_rejects_outside_user_data(lp_app):
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/convert", json={
        "dlc_dir": "/etc",
        "lp_dir":  "/etc-lp",
    })
    assert r.status_code == 403

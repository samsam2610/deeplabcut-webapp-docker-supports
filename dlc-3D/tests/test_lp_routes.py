import sys, types
import pytest
from flask import Flask


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

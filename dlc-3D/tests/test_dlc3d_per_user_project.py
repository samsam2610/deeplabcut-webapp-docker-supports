"""Two users must not overwrite each other's active project.

The bug this locks down: routes.py kept the project in a module global, so
whoever POSTed last won for everybody. Because _save_single_frame writes PNGs
into labeled-data/, the loser's saves landed in the winner's project.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dlc_3d_bp import routes as R  # noqa: E402


class FakeRedis:
    """Minimal stand-in. `fail` makes every call raise, for the Redis-down path."""
    def __init__(self, fail=False):
        self.store = {}
        self.fail = fail

    def get(self, key):
        if self.fail:
            raise ConnectionError("redis is down")
        return self.store.get(key)

    def ping(self):
        if self.fail:
            raise ConnectionError("redis is down")
        return True


@pytest.fixture
def projects(tmp_path):
    made = {}
    for name in ("alpha", "beta"):
        p = tmp_path / name
        p.mkdir()
        (p / "config.yaml").write_text("bodyparts: []\n")
        made[name] = p
    return made


@pytest.fixture
def redis_with(monkeypatch, projects):
    fake = FakeRedis()
    for uid, name in (("user-a", "alpha"), ("user-b", "beta")):
        fake.store[f"webapp:dlc_project:{uid}"] = json.dumps({
            "project_path": str(projects[name]),
            "project_name": name,
            "has_config": True,
            "config_path": str(projects[name] / "config.yaml"),
            "engine": "pytorch",
        })
    monkeypatch.setattr(R, "_redis_conn", lambda: fake)
    return fake


@pytest.fixture
def flask_app():
    """Deliberately NOT named `app`: pytest-flask's autouse `_push_request_context`
    fixture keys off a fixture literally named `app` and, when present, pushes ONE
    app context that stays alive for the whole test function. flask.g lives on the
    app context (not the request context), so every nested
    `with app.test_request_context(...)` in this file — and every real HTTP call
    via `app.test_client()` — would then share a single g and silently leak
    _active_project_for_user's per-request cache across calls make with different
    uids inside one test. Naming this fixture `flask_app` sidesteps pytest-flask's
    autouse hook so each context push below behaves like a real, isolated request,
    matching production (where nothing holds a context open across requests).
    """
    from flask import Flask
    a = Flask(__name__)
    a.register_blueprint(R.bp)
    a.config.update(TESTING=True)
    return a


def _resolve(flask_app, uid):
    """Whatever _active_project_for_user returns for this uid, in request scope."""
    headers = {"X-DLC-User": uid} if uid is not None else {}
    with flask_app.test_request_context("/dlc-3d/", headers=headers):
        return R._active_project_for_user()


def test_two_users_each_see_their_own_project(flask_app, redis_with, projects):
    """The regression test for the original bug."""
    assert _resolve(flask_app, "user-a") == str(projects["alpha"])
    assert _resolve(flask_app, "user-b") == str(projects["beta"])
    # And A is unchanged after B resolved — no shared state was written.
    assert _resolve(flask_app, "user-a") == str(projects["alpha"])


def test_the_global_is_gone(flask_app):
    """A later merge must not quietly reintroduce it."""
    assert not hasattr(R, "_active_project"), (
        "_active_project is back; two users will overwrite each other again"
    )


def test_no_header_means_no_project(flask_app, redis_with):
    assert _resolve(flask_app, None) is None


def test_unknown_user_means_no_project(flask_app, redis_with):
    assert _resolve(flask_app, "never-seen") is None


def test_redis_down_means_no_project_not_a_crash(flask_app, monkeypatch):
    monkeypatch.setattr(R, "_redis_conn", lambda: None)
    assert _resolve(flask_app, "user-a") is None


def test_redis_raising_means_no_project_not_a_crash(flask_app, monkeypatch):
    monkeypatch.setattr(R, "_redis_conn", lambda: FakeRedis(fail=True))
    assert _resolve(flask_app, "user-a") is None


def test_malformed_payload_means_no_project(flask_app, monkeypatch):
    fake = FakeRedis()
    fake.store["webapp:dlc_project:user-a"] = "{not json"
    monkeypatch.setattr(R, "_redis_conn", lambda: fake)
    assert _resolve(flask_app, "user-a") is None


def test_payload_without_project_path_means_no_project(flask_app, monkeypatch):
    fake = FakeRedis()
    fake.store["webapp:dlc_project:user-a"] = json.dumps({"engine": "pytorch"})
    monkeypatch.setattr(R, "_redis_conn", lambda: fake)
    assert _resolve(flask_app, "user-a") is None


def test_set_project_writes_no_server_state(flask_app, redis_with, projects):
    """It still validates and still returns sessions, but the selection itself
    now lives in the main webapp — this endpoint must not shadow it."""
    client = flask_app.test_client()
    r = client.post("/dlc-3d/project",
                    json={"path": str(projects["beta"])},
                    headers={"X-DLC-User": "user-a"})
    assert r.status_code == 200
    assert "sessions" in r.get_json()
    # user-a's project is unchanged: the POST did not write anything.
    assert _resolve(flask_app, "user-a") == str(projects["alpha"])


def test_set_project_still_404s_on_a_bad_path(flask_app, redis_with, tmp_path):
    client = flask_app.test_client()
    r = client.post("/dlc-3d/project",
                    json={"path": str(tmp_path / "nope")},
                    headers={"X-DLC-User": "user-a"})
    assert r.status_code == 404

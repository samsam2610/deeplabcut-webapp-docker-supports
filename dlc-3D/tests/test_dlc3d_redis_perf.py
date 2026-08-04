"""Redis cost properties for _active_project_for_user() / _redis_conn().

routes.py used to build a brand-new redis.Redis client — with a ping() round
trip — on EVERY call to _active_project_for_user(), and that call was the
first line of get_frame(), the timeline scrubber's hottest endpoint (hit on
every frame navigation, from four different JS files). This file locks in
the fix as three measured properties instead of an assertion:

  (a) a 304 response short-circuits before ever touching redis
  (b) resolving the project twice within one request costs exactly one GET
      (flask.g memoization)
  (c) ping() is paid once, at client creation, never again on later calls —
      including across separate requests (module-level client caching)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dlc_3d_bp import routes as R  # noqa: E402


class CountingRedis:
    """Fake redis client: counts operations instead of touching a socket."""

    def __init__(self, store=None):
        self.store = store or {}
        self.get_calls = 0
        self.ping_calls = 0

    def get(self, key):
        self.get_calls += 1
        return self.store.get(key)

    def ping(self):
        self.ping_calls += 1
        return True


@pytest.fixture
def counting_redis(monkeypatch):
    """Patch redis.Redis.from_url so routes._redis_conn()'s own creation path
    runs for real (including its one ping()), backed by a fake, socket-free
    client we can inspect afterwards. Also resets the module-level client
    cache so each test starts with nothing built yet, and restores it after
    (monkeypatch undoes both patches automatically at teardown).
    """
    import redis
    fake = CountingRedis()
    monkeypatch.setattr(redis.Redis, "from_url", lambda *a, **kw: fake)
    monkeypatch.setattr(R, "_redis_client", None)
    return fake


@pytest.fixture
def dlc_app():
    """A bare Flask app around the blueprint.

    Deliberately NOT named `app`: pytest-flask's autouse `_push_request_context`
    fixture keys off that literal fixture name and, when present, holds ONE app
    context open for the whole test function. flask.g lives on the app context,
    not the request context, so every nested `test_request_context()` push below
    would then share a single g and hide the very per-request isolation these
    tests are trying to measure. See test_dlc3d_per_user_project.py's
    `flask_app` fixture for the same fix, first found there.
    """
    from flask import Flask
    a = Flask(__name__)
    a.register_blueprint(R.bp)
    a.config.update(TESTING=True)
    return a


def test_304_performs_zero_redis_operations(dlc_app, counting_redis, tmp_path, monkeypatch):
    """(a) The etag short-circuit in get_frame must never reach redis."""
    monkeypatch.setattr(R, "_USER_DATA_ROOT", str(tmp_path))
    video = tmp_path / "v.avi"
    video.write_bytes(b"v")
    etag = f'"dlc3d-{video}-0"'

    client = dlc_app.test_client()
    resp = client.get(
        "/dlc-3d/frame",
        query_string={"video": str(video), "n": 0},
        headers={"X-DLC-User": "user-a", "If-None-Match": etag},
    )

    assert resp.status_code == 304
    assert counting_redis.get_calls == 0
    assert counting_redis.ping_calls == 0
    # No client was ever built for a request that never needed one.
    assert R._redis_client is None


def test_resolving_twice_in_one_request_costs_one_get(dlc_app, counting_redis):
    """(b) g-memoization: a second call within the same request is free."""
    counting_redis.store["webapp:dlc_project:user-a"] = (
        '{"project_path": "/user-data/proj"}'
    )
    with dlc_app.test_request_context("/dlc-3d/", headers={"X-DLC-User": "user-a"}):
        first = R._active_project_for_user()
        second = R._active_project_for_user()

    assert first == second == "/user-data/proj"
    assert counting_redis.get_calls == 1


def test_no_ping_after_client_is_established(dlc_app, counting_redis):
    """(c) ping() happens once at client creation, never again — across
    separate requests too, since the client itself is cached at module level."""
    counting_redis.store["webapp:dlc_project:user-a"] = (
        '{"project_path": "/user-data/proj"}'
    )
    for _ in range(5):
        with dlc_app.test_request_context("/dlc-3d/", headers={"X-DLC-User": "user-a"}):
            assert R._active_project_for_user() == "/user-data/proj"

    assert counting_redis.ping_calls == 1
    assert counting_redis.get_calls == 5

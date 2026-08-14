"""Per-project panel order for the three inline-analysis cards.

Stored per PROJECT, not per browser: the user asked for the order to follow the
project. That makes it shared between users of the same project, which is
deliberate -- panel order is a property of how a project is worked on.

The failure this store must never cause is worse than not saving: a bad read
must leave the card's shipped order alone rather than blank or scramble it. So
every failure path here resolves to "no opinion".
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dlc_3d_bp import routes as R  # noqa: E402

SAM = ["ia3ds-sam-panel", "ia3ds-triangulate-panel", "ia3ds-params-panel"]


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    return p


@pytest.fixture
def flask_app():
    """Not named `app` -- pytest-flask's autouse fixture keys off that name and
    would hold one app context open across calls, leaking flask.g between the
    requests below. See tests/test_dlc3d_per_user_project.py."""
    from flask import Flask
    a = Flask(__name__)
    a.register_blueprint(R.bp)
    a.config.update(TESTING=True)
    return a


@pytest.fixture
def client(flask_app, project, monkeypatch):
    monkeypatch.setattr(R, "_active_project_for_user", lambda: str(project))
    return flask_app.test_client()


@pytest.fixture
def no_project(flask_app, monkeypatch):
    monkeypatch.setattr(R, "_active_project_for_user", lambda: None)
    return flask_app.test_client()


def _put(client, card, order):
    return client.put("/dlc-3d/card-layout", json={"card": card, "order": order})


def test_round_trip(client):
    assert _put(client, "ia3ds", SAM).status_code == 200
    assert client.get("/dlc-3d/card-layout").get_json()["layout"]["ia3ds"] == SAM


def test_the_file_lands_in_the_project(client, project):
    _put(client, "ia3ds", SAM)
    stored = json.loads((project / R.LAYOUT_FILENAME).read_text())
    assert stored["ia3ds"] == SAM


def test_no_layout_yet_is_empty_not_an_error(client):
    r = client.get("/dlc-3d/card-layout")
    assert r.status_code == 200
    assert r.get_json()["layout"] == {}


def test_saving_one_card_leaves_the_others_alone(client):
    """Two cards can be open in two tabs; the second save must not erase the
    first card's order."""
    _put(client, "ia3d", ["ia3d-params-panel"])
    _put(client, "ia3ds", SAM)
    layout = client.get("/dlc-3d/card-layout").get_json()["layout"]
    assert layout["ia3d"] == ["ia3d-params-panel"]
    assert layout["ia3ds"] == SAM


def test_resaving_a_card_replaces_its_order(client):
    _put(client, "ia3ds", SAM)
    _put(client, "ia3ds", list(reversed(SAM)))
    layout = client.get("/dlc-3d/card-layout").get_json()["layout"]
    assert layout["ia3ds"] == list(reversed(SAM))


def test_an_unknown_card_is_refused(client):
    r = _put(client, "not-a-card", SAM)
    assert r.status_code == 400
    assert "not-a-card" in r.get_json()["error"]


def test_an_order_that_is_not_a_list_of_strings_is_refused(client):
    assert _put(client, "ia3ds", "ia3ds-sam-panel").status_code == 400
    assert _put(client, "ia3ds", [1, 2]).status_code == 400


def test_no_active_project_cannot_save(no_project):
    r = _put(no_project, "ia3ds", SAM)
    assert r.status_code == 400
    assert r.get_json()["error"] == "no active project"


def test_no_active_project_reads_as_empty(no_project):
    """A GET must not 400: the page loads before a project is chosen, and the
    card is perfectly usable with its shipped order."""
    r = no_project.get("/dlc-3d/card-layout")
    assert r.status_code == 200
    assert r.get_json()["layout"] == {}


def test_a_corrupt_file_reads_as_no_opinion(client, project):
    """The alternative is a 500 on page load, which would make a damaged
    preference file break the card itself."""
    (project / R.LAYOUT_FILENAME).write_text("{not json at all")
    assert client.get("/dlc-3d/card-layout").get_json()["layout"] == {}


def test_a_corrupt_file_is_overwritten_by_the_next_save(client, project):
    (project / R.LAYOUT_FILENAME).write_text("{not json at all")
    assert _put(client, "ia3ds", SAM).status_code == 200
    assert client.get("/dlc-3d/card-layout").get_json()["layout"]["ia3ds"] == SAM


def test_junk_keys_in_the_file_are_dropped_on_read(client, project):
    (project / R.LAYOUT_FILENAME).write_text(json.dumps(
        {"ia3ds": SAM, "evil": ["x"], "ia3d": "not-a-list"}))
    layout = client.get("/dlc-3d/card-layout").get_json()["layout"]
    assert set(layout) == {"ia3ds"}


def test_the_write_leaves_no_temp_file(client, project):
    _put(client, "ia3ds", SAM)
    assert [p.name for p in project.iterdir()] == [R.LAYOUT_FILENAME]

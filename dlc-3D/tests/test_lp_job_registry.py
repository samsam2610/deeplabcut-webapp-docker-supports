import fakeredis
import pytest

from dlc_3d_bp.lp import job_registry as J


@pytest.fixture
def rconn():
    return fakeredis.FakeStrictRedis(decode_responses=True)


def test_register_and_list(rconn):
    J.register(rconn, "abc123", {"type": "convert", "project": "/p"})
    J.register(rconn, "def456", {"type": "train",   "project": "/p"})
    rows = J.list_recent(rconn, limit=10)
    ids = [r["id"] for r in rows]
    assert "abc123" in ids and "def456" in ids


def test_get_one(rconn):
    J.register(rconn, "abc123", {"type": "convert", "project": "/p"})
    row = J.get(rconn, "abc123")
    assert row["type"] == "convert"
    assert row["project"] == "/p"

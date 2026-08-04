"""Configuration guards for running dlc-3D multi-worker.

-w 1 was not a performance choice: it was the only thing keeping the
_active_project global self-consistent, because each gunicorn worker holds its
own copy. Now that no request depends on process state, the module can serve
several users at once — but the per-process video-capture cache multiplies with
the worker count, so the two numbers are coupled and must move together.
"""
import re
from pathlib import Path

SRC = Path(__file__).parent.parent
DOCKERFILE = SRC / "Dockerfile"
VIEWER = SRC / "src" / "viewer.py"


def _worker_count():
    m = re.search(r'"-w",\s*"(\d+)"', DOCKERFILE.read_text())
    assert m, "could not find the gunicorn -w flag in the Dockerfile"
    return int(m.group(1))


def _vcap_max():
    m = re.search(r"^_VCAP_MAX\s*=\s*(\d+)", VIEWER.read_text(), re.M)
    assert m, "could not find _VCAP_MAX in viewer.py"
    return int(m.group(1))


def test_serves_more_than_one_request_at_a_time():
    assert _worker_count() >= 4, (
        "one worker serialises every /dlc-3d/ request behind the slowest one; "
        "get_frame_jpeg decodes a video frame per request, so one user "
        "scrubbing a timeline blocks everyone else's saves"
    )


def test_the_frame_cache_is_divided_across_workers():
    """_VCAP_MAX is per PROCESS. N workers hold N caches, so the open-handle
    count against NAS-mounted video is workers x _VCAP_MAX."""
    total = _worker_count() * _vcap_max()
    assert total <= 8, (
        f"{_worker_count()} workers x {_vcap_max()} cached captures = {total} "
        "open video handles; divide _VCAP_MAX when raising the worker count"
    )


def test_the_module_is_not_directly_reachable():
    """dlc-3D trusts the X-DLC-User header, which is only sound because the
    proxy is the sole route in. A ports: mapping would make user identity
    spoofable from the LAN."""
    compose = (SRC.parent.parent / "deeplabcut-webapp-docker"
               / "docker-compose.yml").read_text()
    rest = compose.split("\n  dlc-3d:")[1]
    # Cut at the next top-level (2-space-indented) service key, not the next
    # "\n  " substring — every key nested under dlc-3d is indented 4 spaces,
    # which itself starts with "\n  ", so a naive split("\n  ")[0] on the
    # remainder is always "" and the guard never fires.
    end_match = re.search(r"\n  \S", rest)
    block = rest[: end_match.start() if end_match else len(rest)]
    assert "ports:" not in block, (
        "dlc-3d must stay internal — see the trust boundary in the design doc"
    )

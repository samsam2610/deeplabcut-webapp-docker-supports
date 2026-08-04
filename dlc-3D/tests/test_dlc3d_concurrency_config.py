"""Configuration guards for running dlc-3D multi-worker.

-w 1 was not a performance choice: it was the only thing keeping the
_active_project global self-consistent, because each gunicorn worker holds its
own copy. Now that no request depends on process state, the module can serve
several users at once — but the per-process video-capture cache multiplies with
the worker count, so the two numbers are coupled and must move together.
"""
import re
from pathlib import Path

import yaml

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
    # 8 is not a validated NAS/OS handle limit — it's just "workers x
    # _VCAP_MAX" reverse-engineered from the two values we actually chose
    # (4 x 2). This assertion guards those two numbers against drifting apart
    # in future edits; it is not evidence that 8 itself is a safe ceiling.
    assert total <= 8, (
        f"{_worker_count()} workers x {_vcap_max()} cached captures = {total} "
        "open video handles; divide _VCAP_MAX when raising the worker count"
    )


def test_the_module_is_not_directly_reachable():
    """dlc-3D trusts the X-DLC-User header, which is only sound because the
    proxy is the sole route in. A ports: mapping would make user identity
    spoofable from the LAN.

    Parsed with a real YAML loader rather than string/regex slicing: a
    regex that cuts the dlc-3d block at the next 2-space-indented line
    misses `ports:` placed after an injected 2-space-indented comment
    mid-block, even though the key still belongs to services.dlc-3d
    under any real YAML parse. This guards a trust-boundary invariant, so
    it needs to be correct for arbitrary valid YAML, not just the file's
    current formatting style.
    """
    compose = (SRC.parent.parent / "deeplabcut-webapp-docker"
               / "docker-compose.yml").read_text()
    services = yaml.safe_load(compose)["services"]
    assert "ports" not in services["dlc-3d"], (
        "dlc-3d must stay internal — see the trust boundary in the design doc"
    )

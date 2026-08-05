"""The dlc-3d container must never proxy /dlc-3d/* to itself.

Found live on 2026-08-04: `GET /dlc-3d/` returned 500 after exactly 60 s, the
main webapp proxy's read timeout. The traceback came from `/app/base_app.py` —
inside the dlc-3d container — proving it was forwarding to `http://dlc-3d:5050`,
i.e. to itself, in a loop.

Cause: the Dockerfile bakes the main webapp's app.py in as `base_app`, and that
carries a `proxy_dlc_3d` route for `/dlc-3d/` + `/dlc-3d/<path:path>`. dlc-3D's
own app.py does `from base_app import app` BEFORE registering its blueprints, so
for the exact rule "/dlc-3d/" — which both define — Werkzeug picked the
first-registered endpoint, the proxy.

Static blueprint rules already outrank the proxy's `<path:path>`, so the whole
API kept working and only the index page was dead. That asymmetry is why this
survived unnoticed, and it is why the second test below matters as much as the
first: a fix that repaired `/dlc-3d/` while breaking the API would look fine to
a casual check.

Reproduced at both `-w 1` and `-w 4`, so it was never a worker-count problem.

These tests import the real `app.py`, which needs `base_app` on the path — that
only exists inside the built image. Skipped elsewhere.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

pytest.importorskip(
    "base_app",
    reason="base_app is baked into the dlc-3d image; run these in the container",
)

import app as dlc_app  # noqa: E402


@pytest.fixture(scope="module")
def url_map():
    return dlc_app.app.url_map.bind("localhost")


def test_index_does_not_route_to_the_proxy(url_map):
    """The exact bug: '/dlc-3d/' resolving to a view that forwards to us.

    Asserts on the VIEW that would actually run, not the endpoint name —
    resolution may legitimately land on either endpoint, but only two views are
    safe to run. Note we cannot compare against "base_app's proxy view" to
    detect the bug: `base_app.app` IS this same app object, so after the fix
    that lookup returns the replacement and the comparison would be vacuous.
    Allow-list the safe views instead; deleting the override in app.py leaves
    the real proxy bound here, which is in neither set, and this fails.
    """
    from dlc_3d_bp.routes import index as _bp_index

    endpoint, _args = url_map.match("/dlc-3d/")
    view = dlc_app.app.view_functions[endpoint]
    safe = {dlc_app._serve_index_never_self_proxy, _bp_index}
    assert view in safe, (
        f"GET /dlc-3d/ resolves to {endpoint} bound to {view!r}, which would "
        "forward to this same container and hang until the 60 s proxy timeout"
    )


def test_api_routes_still_beat_the_proxy(url_map):
    """A fix that repaired the index by clobbering the API would be worse."""
    for path, method in (
        ("/dlc-3d/labeled-frames", "GET"),
        ("/dlc-3d/labeled-epilines", "GET"),
        ("/dlc-3d/browse", "GET"),
        ("/dlc-3d/project", "POST"),
    ):
        endpoint, _ = url_map.match(path, method=method)
        assert endpoint.startswith("dlc_3d."), (
            f"{method} {path} -> {endpoint}; it must reach dlc-3D's own "
            "blueprint, never the inherited proxy"
        )


def test_unmatched_paths_404_rather_than_hang():
    """Previously an unmatched /dlc-3d/* self-proxied and hung; 404 is correct."""
    client = dlc_app.app.test_client()
    assert client.get("/dlc-3d/definitely-not-a-real-route").status_code == 404

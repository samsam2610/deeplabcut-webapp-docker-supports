"""dlc-3D module entry point.

Built on the main webapp's Flask app, which the Dockerfile bakes in as
`base_app` (`RUN mv /app/app.py /app/base_app.py`), so this module inherits its
templates, static handling and auth behaviour.
"""
from flask import jsonify

from base_app import app
from dlc_3d_bp.routes import bp, index as _dlc_3d_index
from dlc_3d_bp.lp_routes import lp_bp

app.register_blueprint(bp)
app.register_blueprint(lp_bp)


def _serve_index_never_self_proxy(path: str = ""):
    """Stand in for the inherited `proxy_dlc_3d` route inside THIS container.

    `base_app` is the main webapp's app.py, and it carries a `proxy_dlc_3d`
    route forwarding `/dlc-3d/*` to `http://dlc-3d:5050` — which, from in here,
    is us. Werkzeug resolves the exact rule "/dlc-3d/" to whichever endpoint
    registered first, and `from base_app import app` runs before our
    blueprints, so the proxy won: a plain `GET /dlc-3d/` proxied to itself
    until the caller's 60 s timeout and returned 500. Reproduced at both `-w 1`
    and `-w 4`, so it was never a worker-count problem.

    Only the bare index page and otherwise-unmatched paths were affected —
    every static blueprint rule (`/dlc-3d/labeled-frames`, …) already outranks
    the proxy's `<path:path>`, which is why the API kept working and this went
    unnoticed.

    Rebinding the endpoint's view function rather than deleting the rule is
    deliberate: on Werkzeug 3.x (3.1.8 here) the Map keeps rules behind a
    private `_matcher`, so removing one means reaching into internals that
    shift between releases. A view swap is public API and version-proof.
    """
    if path:
        # This used to self-proxy and hang. A miss is a miss — returned as a
        # response rather than raised via abort(404), because base_app installs
        # a catch-all Exception handler that swallows HTTPException too and
        # turns a clean 404 into a logged 500.
        return jsonify({"error": "not found"}), 404
    return _dlc_3d_index()


app.view_functions["proxy_dlc_3d"] = _serve_index_never_self_proxy

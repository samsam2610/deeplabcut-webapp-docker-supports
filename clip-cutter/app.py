import os
from datetime import timedelta

from flask import Flask
from routes import bp
import processor
import queue_manager


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # ── Auth / session config ────────────────────────────────────────────────
    # NOTE: Production deployments MUST set CLIP_CUTTER_SECRET_KEY to a
    # random, secret value (e.g. `python -c 'import secrets; print(secrets.token_hex(32))'`).
    # The fallback below is a fixed dev-only value and is unsafe for prod.
    app.secret_key = os.environ.get(
        "CLIP_CUTTER_SECRET_KEY",
        "clip-cutter-dev-secret-change-me-d3f6a1c9b2e74aa0",
    )
    app.config["AUTH_TOKEN"] = os.environ.get("CLIP_CUTTER_AUTH_TOKEN", "deeplabcut")
    # Path-scope the cookie so it does not collide with the parent webapp's session.
    app.config["SESSION_COOKIE_PATH"] = "/clip-cutter/"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.permanent_session_lifetime = timedelta(days=7)

    app.register_blueprint(bp)
    queue_manager.start_worker()
    processor.start_model_evictor()
    return app


if __name__ == "__main__":
    port = int(os.environ.get("CLIP_CUTTER_PORT", 5002))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    create_app().run(host="0.0.0.0", port=port, debug=debug, threaded=True)

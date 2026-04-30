from flask import Flask
from routes import bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.register_blueprint(bp)
    return app


if __name__ == "__main__":
    from config import PORT
    import os
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    create_app().run(host="0.0.0.0", port=PORT, debug=debug, threaded=True)

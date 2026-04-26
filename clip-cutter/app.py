from flask import Flask
from routes import bp, load_state


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(bp)
    load_state()
    return app


if __name__ == "__main__":
    create_app().run(debug=True, port=5001)

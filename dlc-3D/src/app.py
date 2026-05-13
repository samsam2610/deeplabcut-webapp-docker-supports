from base_app import app
from dlc_3d_bp.routes import bp
from dlc_3d_bp.lp_routes import lp_bp

app.register_blueprint(bp)
app.register_blueprint(lp_bp)

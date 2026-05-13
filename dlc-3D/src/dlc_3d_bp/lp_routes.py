"""Flask blueprint for /dlc-3d/lp/* endpoints."""
from flask import Blueprint

lp_bp = Blueprint(
    "dlc_3d_lp", __name__, url_prefix="/dlc-3d/lp",
)

from flask import Blueprint

bp = Blueprint("dlc_3d", __name__, url_prefix="/dlc-3d",
               template_folder="templates",
               static_folder="static", static_url_path="/static")

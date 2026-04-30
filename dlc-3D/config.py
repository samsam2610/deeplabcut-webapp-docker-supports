from pathlib import Path
import os

PORT = int(os.environ.get("DLC_3D_PORT", 5050))

USER_DATA_ROOTS = [
    Path("/user-data/Parra-Data/Disk"),
    Path("/user-data/Parra-Data/Cloud"),
    Path("/user-data/Martin-Data/USB"),
    Path("/user-data/NAS-Data-Share"),
]

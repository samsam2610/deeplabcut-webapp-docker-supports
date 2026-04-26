import os
from pathlib import Path

# --- Paths (override via environment variables for Docker) ---
_DATA_ROOT = Path(os.environ.get("CLIP_CUTTER_DATA_ROOT", "/user-data/Parra-Data/Cloud"))

VIDEO_DIR = Path(
    os.environ.get(
        "CLIP_CUTTER_VIDEO_DIR",
        str(_DATA_ROOT / "Reaching-Task-Data/RatBox Videos/MAP-2"),
    )
)
TRAINING_CLIPS_DIR = Path(
    os.environ.get(
        "CLIP_CUTTER_TRAINING_CLIPS_DIR",
        str(VIDEO_DIR / "MAP2_20250515_103618_0"),
    )
)
TEMPLATE_STATE_PATH = Path(
    os.environ.get(
        "CLIP_CUTTER_TEMPLATE_STATE_PATH",
        str(_DATA_ROOT / "Reaching-Task-Data/clip-cutter/template_state.json"),
    )
)

# --- Template ---
TRAINING_CROP = (401, 268, 581, 632)   # (x, y, w, h) in original 1376×900 frame

# --- Scanning ---
SCAN_STRIDE = 10           # extract every Nth frame for coarse pass
SCAN_BATCH_SIZE = 64       # CLIP batch size
SIMILARITY_THRESHOLD = 0.70
MIN_PEAK_SPACING = 900     # minimum frames between two detections (original frame units)
FINE_SCAN_WINDOW = 50      # ± frames around coarse peak for fine pass

# --- Clip extraction ---
CLIP_PRE_FRAMES = 200      # frames before key frame
CLIP_POST_FRAMES = 600     # frames after key frame (inclusive end = key + 599)

# --- "Done" detection ---
# A video is considered done if its _test_clips/ dir exists OR its CSV has any start_reaching note
TEST_CLIPS_SUFFIX = "_test_clips"

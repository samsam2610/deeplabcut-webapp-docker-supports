from __future__ import annotations

import threading
from collections import OrderedDict

import cv2

_VCAP_MAX = 4
_vcap_cache: OrderedDict = OrderedDict()
_vcap_lock = threading.Lock()


def get_video_info(video_path: str) -> dict:
    """Return {frame_count: int, fps: float}. Raises FileNotFoundError if unopenable."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {video_path}")
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()
    return {"frame_count": frame_count, "fps": fps}


def get_frame_jpeg(video_path: str, frame_number: int, quality: int = 80) -> bytes:
    """
    Return JPEG bytes for the given 0-based frame_number.
    Keeps a per-path VideoCapture open (LRU cache, max _VCAP_MAX entries).
    Sequential reads skip the seek for faster playback.
    Raises FileNotFoundError or ValueError on failure.
    """
    vpath = str(video_path)

    with _vcap_lock:
        if vpath not in _vcap_cache:
            if len(_vcap_cache) >= _VCAP_MAX:
                _, evicted = _vcap_cache.popitem(last=False)
                evicted["vcap"].release()
            _vcap_cache[vpath] = {
                "vcap": None,
                "pos": -1,
                "lock": threading.Lock(),
            }
        _vcap_cache.move_to_end(vpath)
        entry = _vcap_cache[vpath]

    with entry["lock"]:
        if entry["vcap"] is None or not entry["vcap"].isOpened():
            entry["vcap"] = cv2.VideoCapture(vpath)
            entry["pos"] = -1
            if not entry["vcap"].isOpened():
                raise FileNotFoundError(f"Cannot open video: {vpath}")

        if frame_number != entry["pos"] + 1:
            entry["vcap"].set(cv2.CAP_PROP_POS_FRAMES, frame_number)

        ok, frame = entry["vcap"].read()
        entry["pos"] = frame_number if ok else -1

    if not ok:
        raise ValueError(f"Cannot read frame {frame_number} from {vpath}")

    ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok2:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()

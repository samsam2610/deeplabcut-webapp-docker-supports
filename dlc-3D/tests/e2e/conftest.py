import pytest
import urllib.request
import json

@pytest.fixture(scope="session")
def base_url():
    return "http://172.26.0.5:5050/dlc-3d/"

@pytest.fixture(scope="session", autouse=False)
def om2_fixture_present(base_url):
    """Probe /dlc/project/labeled-frames for OM-2_20260424 with >=2 cams.

    The stem data is served by the main webapp at /dlc/project/labeled-frames
    (not the dlc-3D blueprint's own /labeled-frames, which requires a session
    query param and lists PNG files, not stems).  Each item in video_stems has
    the shape {"video_stem": "<name>", "frames": [...]}.

    Returns True only when OM-2_20260424 appears as a stem AND has frames from
    at least 2 distinct cameras (img_cam<N>_* filenames).
    """
    # The dlc-3D container reverse-proxies the main webapp at the same host,
    # so we probe the main webapp via the dlc-3D base URL's host:port.
    import re
    import urllib.parse

    parsed = urllib.parse.urlparse(base_url)
    probe_url = f"{parsed.scheme}://{parsed.netloc}/dlc/project/labeled-frames"
    try:
        with urllib.request.urlopen(probe_url, timeout=5) as r:
            data = json.loads(r.read())
    except Exception:
        return False

    stems = data.get("video_stems", []) if isinstance(data, dict) else []
    target = next(
        (s for s in stems if isinstance(s, dict) and s.get("video_stem") == "OM-2_20260424"),
        None,
    )
    if target is None:
        return False

    # Count distinct cam indices present in the frame list.
    frames = target.get("frames", [])
    cam_re = re.compile(r"img_cam(\d+)_")
    cam_ids = {m.group(1) for f in frames for m in [cam_re.match(f)] if m}
    return len(cam_ids) >= 2

"""E2E test infrastructure.

Tests hit the user-facing flask URL (http://localhost:5000/dlc-3d/) which
reverse-proxies to the dlc-3d container while serving /static/* from the main
webapp — this matches what real users see and avoids 500s on assets that only
exist in the flask container (CSS variables, training.js, etc.).

Auth is gated by APP_TOKEN; the autouse fixture authenticates each browser
context once via ?token=... so the session cookie is set, then activates the
DLC project so labeled-frames returns the test stems.

Override the base URL or auth token via env vars FL3D_E2E_BASE_URL / APP_TOKEN.
"""

import http.cookiejar
import json
import os
import re
import urllib.parse
import urllib.request

import pytest

PROJECT_PATH_IN_CONTAINER = (
    "/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07"
)
SESSION = "OM-2_20260424"
DEFAULT_BASE_URL = "http://localhost:5000/dlc-3d/"
DEFAULT_TOKEN = "deeplabcut"


def _base_url() -> str:
    url = os.environ.get("FL3D_E2E_BASE_URL", DEFAULT_BASE_URL)
    return url if url.endswith("/") else url + "/"


def _app_token() -> str:
    return os.environ.get("APP_TOKEN", DEFAULT_TOKEN)


@pytest.fixture(scope="session")
def base_url() -> str:
    return _base_url()


@pytest.fixture(scope="session")
def app_token() -> str:
    return _app_token()


@pytest.fixture(scope="session")
def om2_fixture_present(base_url, app_token) -> bool:
    """Pre-flight: authenticate, activate project, probe labeled-frames.

    Returns True iff OM-2_20260424 is present with frames from >=2 distinct cams.
    """
    parsed = urllib.parse.urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    try:
        # Authenticate (sets the auth session cookie via redirect)
        opener.open(f"{origin}/?token={app_token}", timeout=5).read()
        # Activate the DLC project for this session
        activate = urllib.request.Request(
            f"{origin}/dlc/project",
            data=json.dumps({"path": PROJECT_PATH_IN_CONTAINER}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if opener.open(activate, timeout=5).status != 200:
            return False
        with opener.open(f"{origin}/dlc/project/labeled-frames", timeout=5) as r:
            data = json.loads(r.read())
    except Exception:
        return False

    stems = data.get("video_stems", []) if isinstance(data, dict) else []
    target = next(
        (s for s in stems if isinstance(s, dict) and s.get("video_stem") == SESSION),
        None,
    )
    if target is None:
        return False
    cam_re = re.compile(r"img_cam(\d+)_")
    cam_ids = {m.group(1) for f in target.get("frames", []) for m in [cam_re.match(f)] if m}
    return len(cam_ids) >= 2


@pytest.fixture(autouse=True)
def _active_dlc_project(page, base_url, app_token, om2_fixture_present):
    """Authenticate the page's browser context, activate the DLC project.

    Skips the test if the pre-flight probe failed (stack down or fixture missing).
    """
    if not om2_fixture_present:
        pytest.skip(f"Skipping: {SESSION} not present or has no multi-cam frames.")
    parsed = urllib.parse.urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    # Authenticate via the token URL (lands on a 200 page after the redirect).
    page.goto(f"{origin}/?token={app_token}", wait_until="domcontentloaded")
    # Activate the DLC project on this context.
    resp = page.request.post(
        f"{origin}/dlc/project",
        data=json.dumps({"path": PROJECT_PATH_IN_CONTAINER}),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, f"failed to activate DLC project: {resp.status} {resp.text()}"

# Labeler Epipolar Lines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the 3D frame labeler, project every point placed on one camera as an epipolar line onto the other camera's tile, toggled by a checkbox and the `P` key, recomputed 2 s after the labels stop changing.

**Architecture:** Pure geometry helpers go in a node-testable `.mjs` module (the codebase's established pattern — see `pair_map.mjs`, `epiline_label.mjs`). Flask gains one field on an existing route plus one new route that reuses `epipolar_core`'s `fundamental_matrix` / `undistort_to_pixels` / `epiline_endpoints` verbatim, so lines agree exactly with the reprojection card. The client block in `frame_labeler_3d.js` debounces label edits, fetches once per fire, and paints stored segments inside the existing tile-draw function.

**Tech Stack:** Flask + numpy + OpenCV (`cv2`) server-side; vanilla ES modules client-side; pytest and `node:test` for tests.

**Spec:** `dlc-3D/docs/superpowers/specs/2026-08-04-labeler-epipolar-lines-design.md`

## Global Constraints

- Debounce constant is exactly **2000 ms**, named `FL3D_EPI_DEBOUNCE_MS`.
- Label-edit triggers are **debounced**; enabling the checkbox, pressing `P`, changing frame, and switching sync on are **immediate** (no wait).
- Line style must match the reprojection card exactly: `setLineDash([6, 4])`, `lineWidth = 1`, stroke = the bodypart's own marker colour `_flColor(bpIndex)`.
- Bodypart names are drawn at the frame edge via `labelAnchor(seg, order, 14)` + `nameLabelBox`; `order` increments **only for lines actually drawn**.
- The draw path must **never** call `fetch(` — tile repaints run on zoom, pan and hover.
- A generation counter must guard the async draw, incremented per invocation and re-checked after every `await` (recorded regression; see `docs/regression-catalog.md`).
- The reference camera is **the camera whose labels last changed**, never simply `_fl3dFocusedCam`.
- `config.toml` is never read. Only `calibration.toml`.
- This feature never writes a label and never modifies `labeled-data`.
- Camera keys in `calibration.toml` are `cam_0` / `cam_1`; filenames are `img_cam0_` / `img_cam1_`. Index N maps to key `cam_{N}`.
- Tile canvases are native image size (`_fl3dDrawTileMarkers` uses `sx = 1, sy = 1`) — segment coordinates are canvas coordinates. Do **not** add scaling.

**Running the tests.** Python: `cd dlc-3D && python3 -m pytest tests/<file> -q`. Node: run each file **directly** — `node --test tests/unit/<file>.mjs`. Node 16 finds 0 tests in directory mode, so never run `node --test tests/unit/`.

**Baseline:** `python3 -m pytest tests/ -q --ignore=tests/e2e` has **8 known pre-existing failures** (5 in `test_lp_predict_pairing.py`, 2 in `test_lp_csv_to_h5.py`, 1 `test_inline_analysis_3d_ui_isolation.py::test_finalize3d_confirms_before_overwrite`). A 9th means you broke something.

---

### Task 1: Pure request-shaping helpers

**Files:**
- Create: `src/static/internal/epiline_request.mjs`
- Test: `tests/unit/test_epiline_request.mjs`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `epiGateReason({syncOn, calibrationExists, camCount}) -> string|null` — `null` means enabled; otherwise the hint to show.
  - `collectRefPoints(labels, hidden, bodyparts) -> Array<{bodypart, x, y}>`
  - `payloadSignature(session, refCam, tgtCam, points) -> string`

- [ ] **Step 1: Write the failing test**

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { epiGateReason, collectRefPoints, payloadSignature }
  from "../../src/static/internal/epiline_request.mjs";

const OK = { syncOn: true, calibrationExists: true, camCount: 2 };

test("gate passes only when sync, calibration and two cams are all present", () => {
  assert.equal(epiGateReason(OK), null);
});

test("each blocked condition names itself", () => {
  // A single dead checkbox teaches the user nothing — each cause is distinct.
  assert.match(epiGateReason({ ...OK, syncOn: false }), /sync/i);
  assert.match(epiGateReason({ ...OK, calibrationExists: false }), /calibration\.toml/i);
  assert.match(epiGateReason({ ...OK, camCount: 1 }), /one camera/i);
});

test("sync is reported before calibration when both are missing", () => {
  // Sync is the one the user can fix instantly; lead with it.
  const r = epiGateReason({ syncOn: false, calibrationExists: false, camCount: 1 });
  assert.match(r, /sync/i);
});

test("collectRefPoints returns labelled, visible bodyparts in bodypart order", () => {
  const labels = { paw: [30, 40], wrist: [10, 20] };
  const out = collectRefPoints(labels, {}, ["wrist", "elbow", "paw"]);
  assert.deepEqual(out, [
    { bodypart: "wrist", x: 10, y: 20 },
    { bodypart: "paw",   x: 30, y: 40 },
  ]);
});

test("unlabelled, null and hidden bodyparts are excluded", () => {
  const labels = { wrist: [1, 2], elbow: null, paw: [5, 6] };
  const out = collectRefPoints(labels, { paw: true }, ["wrist", "elbow", "paw"]);
  assert.deepEqual(out, [{ bodypart: "wrist", x: 1, y: 2 }]);
});

test("collectRefPoints tolerates missing label and hidden maps", () => {
  assert.deepEqual(collectRefPoints(undefined, undefined, ["wrist"]), []);
});

test("signature changes when any point moves", () => {
  const a = payloadSignature("s1", 0, 1, [{ bodypart: "w", x: 1, y: 2 }]);
  const b = payloadSignature("s1", 0, 1, [{ bodypart: "w", x: 1, y: 3 }]);
  assert.notEqual(a, b);
});

test("signature changes when the camera direction flips", () => {
  const pts = [{ bodypart: "w", x: 1, y: 2 }];
  assert.notEqual(payloadSignature("s1", 0, 1, pts),
                  payloadSignature("s1", 1, 0, pts));
});

test("signature is stable for identical input", () => {
  const pts = [{ bodypart: "w", x: 1, y: 2 }];
  assert.equal(payloadSignature("s1", 0, 1, pts),
               payloadSignature("s1", 0, 1, pts));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && node --test tests/unit/test_epiline_request.mjs`
Expected: FAIL — `Cannot find module .../epiline_request.mjs`

- [ ] **Step 3: Write the implementation**

```javascript
// Pure request-shaping for the frame labeler's epipolar overlay. Kept free of
// DOM and fetch so the gating rules and payload construction are unit-testable,
// matching the pattern of pair_map.mjs and epiline_label.mjs.

/**
 * Why the overlay cannot run, or null when it can.
 * Ordered so the user hears the condition they can fix fastest first.
 */
export function epiGateReason({ syncOn, calibrationExists, camCount }) {
  if (!syncOn) return "turn on sync to see both cameras";
  if (camCount < 2) return "this frame has only one camera";
  if (!calibrationExists) return "no calibration.toml in this session folder";
  return null;
}

/**
 * Points to project: every bodypart with a label that is not hidden.
 * Returned in `bodyparts` order so the label staircase is stable across fires.
 */
export function collectRefPoints(labels, hidden, bodyparts) {
  const lab = labels || {};
  const hid = hidden || {};
  const out = [];
  for (const bp of bodyparts || []) {
    const pt = lab[bp];
    if (!pt || hid[bp]) continue;
    const [x, y] = pt;
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    out.push({ bodypart: bp, x, y });
  }
  return out;
}

/** Identity of a request, so an unchanged one is never re-issued. */
export function payloadSignature(session, refCam, tgtCam, points) {
  const pts = (points || [])
    .map((p) => `${p.bodypart}:${p.x}:${p.y}`)
    .join(",");
  return `${session}|${refCam}>${tgtCam}|${pts}`;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && node --test tests/unit/test_epiline_request.mjs`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/static/internal/epiline_request.mjs dlc-3D/tests/unit/test_epiline_request.mjs
git commit -m "feat(labeler): pure helpers for the epipolar-line request"
```

---

### Task 2: Report calibration availability on `/labeled-frames`

**Files:**
- Modify: `src/dlc_3d_bp/routes.py` — add `_session_calibration_info`, extend `labeled_frames()` (currently at `routes.py:611`)
- Test: `tests/test_labeled_epilines_route.py` (created here, extended in Task 3)

**Interfaces:**
- Consumes: `rp.load_calibration(path) -> dict[str, ec.Cam]` (`reprojection.py:60`), module globals `_active_project` and `_state_lock` (`routes.py:30-31`).
- Produces: `_session_calibration_info(labeled_dir: Path) -> dict` returning `{"exists": bool, "cams": list[str]}`; `/labeled-frames` response gains key `"calibration"` with that shape.

- [ ] **Step 1: Write the failing test**

```python
"""Route tests for the frame labeler's epipolar-line support.

Style follows tests/test_reproj_panel_wiring.py's sibling route tests: a
minimal Flask app registering only dlc_3d_bp.routes.bp, with the module-level
_active_project set directly. No fixtures from the LP suite are used.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dlc_3d_bp import routes as R  # noqa: E402


# Two cameras 100 mm apart looking down the same axis — enough for a real,
# non-degenerate fundamental matrix. Written as a literal so the test does not
# depend on any calibration file on disk.
CALIB_TOML = """
[cam_0]
name = "0"
size = [ 640, 480,]
matrix = [ [ 600.0, 0.0, 320.0,], [ 0.0, 600.0, 240.0,], [ 0.0, 0.0, 1.0,],]
distortions = [ 0.0, 0.0, 0.0, 0.0, 0.0,]
rotation = [ 0.0, 0.0, 0.0,]
translation = [ 0.0, 0.0, 0.0,]

[cam_1]
name = "1"
size = [ 640, 480,]
matrix = [ [ 600.0, 0.0, 320.0,], [ 0.0, 600.0, 240.0,], [ 0.0, 0.0, 1.0,],]
distortions = [ 0.0, 0.0, 0.0, 0.0, 0.0,]
rotation = [ 0.0, 0.1, 0.0,]
translation = [ -100.0, 0.0, 0.0,]

[metadata]
adjusted = false
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project root with one session folder holding a cam pair."""
    proj = tmp_path / "proj"
    session = proj / "labeled-data" / "sess1"
    session.mkdir(parents=True)
    (session / "img_cam0_0000_00010.png").write_bytes(b"")
    (session / "img_cam1_0000_00010.png").write_bytes(b"")
    monkeypatch.setattr(R, "_active_project", str(proj))
    return proj


@pytest.fixture
def calibrated(project):
    (project / "labeled-data" / "sess1" / "calibration.toml").write_text(CALIB_TOML)
    return project


@pytest.fixture
def client(project):
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(R.bp)
    app.config.update(TESTING=True)
    with app.test_client() as c:
        yield c


def test_labeled_frames_reports_calibration_present(client, calibrated):
    r = client.get("/labeled-frames?session=sess1")
    body = r.get_json()
    assert body["calibration"]["exists"] is True
    assert body["calibration"]["cams"] == ["cam_0", "cam_1"]


def test_labeled_frames_reports_calibration_absent(client, project):
    r = client.get("/labeled-frames?session=sess1")
    assert r.get_json()["calibration"] == {"exists": False, "cams": []}


def test_labeled_frames_survives_a_corrupt_calibration(client, project):
    """A broken toml must gate the feature off, not 500 the folder listing —
    the frame list is what the labeler needs to work at all."""
    (project / "labeled-data" / "sess1" / "calibration.toml").write_text("not [ toml")
    r = client.get("/labeled-frames?session=sess1")
    assert r.status_code == 200
    assert r.get_json()["calibration"]["exists"] is False
    assert len(r.get_json()["frames"]) == 2


def test_labeled_frames_still_lists_frames(client, calibrated):
    """The added field must not disturb the existing contract."""
    body = client.get("/labeled-frames?session=sess1").get_json()
    assert body["count"] == 2
    assert body["session_folder"] == "labeled-data/sess1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_labeled_epilines_route.py -q`
Expected: FAIL — `KeyError: 'calibration'`

- [ ] **Step 3: Write the implementation**

Add above `labeled_frames()` in `src/dlc_3d_bp/routes.py`:

```python
def _session_calibration_info(labeled_dir: Path) -> dict:
    """Whether this session folder can support epipolar lines, and for which cams.

    calibration.toml is copied in by _save_single_frame, so folders populated
    through the 3D labeler have it and older ones do not. A corrupt file is
    reported as absent rather than raised: the caller is the frame listing, and
    the labeler must keep working without the overlay.
    """
    calib = labeled_dir / "calibration.toml"
    if not calib.is_file():
        return {"exists": False, "cams": []}
    try:
        cams = sorted(rp.load_calibration(calib))
    except Exception:
        return {"exists": False, "cams": []}
    return {"exists": bool(cams), "cams": cams}
```

Then, in `labeled_frames()`, add the field to **both** return paths — the
early return for a missing directory and the main one:

```python
    if not labeled_dir.is_dir():
        return jsonify({
            "frames": [], "count": 0,
            "session_folder": f"labeled-data/{session_key}",
            "calibration": {"exists": False, "cams": []},
        })

    frames = sorted(f.name for f in labeled_dir.glob("img_cam*.png"))
    return jsonify({
        "frames":         frames,
        "count":          len(frames),
        "session_folder": f"labeled-data/{session_key}",
        "calibration":    _session_calibration_info(labeled_dir),
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_labeled_epilines_route.py -q`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/routes.py dlc-3D/tests/test_labeled_epilines_route.py
git commit -m "feat(labeler): report calibration availability on /labeled-frames"
```

---

### Task 3: The `/labeled-epilines` route

**Files:**
- Modify: `src/dlc_3d_bp/routes.py` — new route beside `labeled_frames()`
- Test: `tests/test_labeled_epilines_route.py` (append to the file from Task 2)

**Interfaces:**
- Consumes: `_session_calibration_info` (Task 2); `ec.fundamental_matrix(ref, tgt)`, `ec.undistort_to_pixels(cam, pts)`, `ec.epiline_endpoints(F, pt, width, height)` from `epipolar_core`; `rp.load_calibration`.
- Produces: `GET /labeled-epilines?session=&ref_cam=&tgt_cam=&points=<json>` returning `{"segments": {bodypart: [[x1,y1],[x2,y2]] | null}}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_labeled_epilines_route.py`:

```python
def _get(client, **kw):
    kw.setdefault("session", "sess1")
    kw.setdefault("ref_cam", 0)
    kw.setdefault("tgt_cam", 1)
    if isinstance(kw.get("points"), list):
        kw["points"] = json.dumps(kw["points"])
    q = "&".join(f"{k}={v}" for k, v in kw.items())
    return client.get(f"/labeled-epilines?{q}")


def test_returns_one_segment_per_point(client, calibrated):
    r = _get(client, points=[{"bodypart": "wrist", "x": 320, "y": 240},
                             {"bodypart": "paw",   "x": 200, "y": 300}])
    assert r.status_code == 200
    segs = r.get_json()["segments"]
    assert set(segs) == {"wrist", "paw"}
    for seg in segs.values():
        assert seg is None or (len(seg) == 2 and len(seg[0]) == 2)


def test_a_centred_point_yields_a_real_segment(client, calibrated):
    """Not just well-formed — an actual line across the target image. A route
    that returned all-null would satisfy the shape test above."""
    seg = _get(client, points=[{"bodypart": "wrist", "x": 320, "y": 240}]
               ).get_json()["segments"]["wrist"]
    assert seg is not None, "a centred point must project to a visible line"
    (x1, y1), (x2, y2) = seg
    assert (x1 - x2) ** 2 + (y1 - y2) ** 2 > 1.0, "degenerate segment"
    for x, y in seg:
        assert -1e-6 <= x <= 640 + 1e-6
        assert -1e-6 <= y <= 480 + 1e-6


def test_direction_matters(client, calibrated):
    """0->1 and 1->0 are different geometry; a route ignoring the direction
    would return the same line for both."""
    pts = [{"bodypart": "wrist", "x": 300, "y": 200}]
    a = _get(client, ref_cam=0, tgt_cam=1, points=pts).get_json()["segments"]["wrist"]
    b = _get(client, ref_cam=1, tgt_cam=0, points=pts).get_json()["segments"]["wrist"]
    assert a != b


def test_empty_points_is_not_an_error(client, calibrated):
    r = _get(client, points=[])
    assert r.status_code == 200
    assert r.get_json()["segments"] == {}


def test_missing_calibration_is_400(client, project):
    r = _get(client, points=[{"bodypart": "wrist", "x": 1, "y": 2}])
    assert r.status_code == 400
    assert "calibration" in r.get_json()["error"].lower()


def test_unknown_camera_index_is_400(client, calibrated):
    r = _get(client, tgt_cam=7, points=[{"bodypart": "wrist", "x": 1, "y": 2}])
    assert r.status_code == 400
    assert "cam_7" in r.get_json()["error"]


def test_same_camera_for_ref_and_target_is_400(client, calibrated):
    """A point's epipolar line in its own image is undefined."""
    r = _get(client, ref_cam=0, tgt_cam=0, points=[{"bodypart": "w", "x": 1, "y": 2}])
    assert r.status_code == 400


def test_malformed_points_is_400_not_500(client, calibrated):
    assert client.get(
        "/labeled-epilines?session=sess1&ref_cam=0&tgt_cam=1&points=notjson"
    ).status_code == 400
    r = _get(client, points=[{"bodypart": "w", "x": "abc", "y": 2}])
    assert r.status_code == 400


def test_session_key_cannot_escape_the_project(client, calibrated):
    r = _get(client, session="../../etc", points=[{"bodypart": "w", "x": 1, "y": 2}])
    assert r.status_code == 403


def test_a_point_whose_line_misses_the_image_is_null_not_missing(client, calibrated):
    """The client keys its draw loop on the bodypart, so an omitted key and a
    null mean different things — a dropped key would be read as 'not computed'."""
    segs = _get(client, points=[{"bodypart": "wrist", "x": 1e9, "y": 1e9}]
                ).get_json()["segments"]
    assert "wrist" in segs
    assert segs["wrist"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_labeled_epilines_route.py -q`
Expected: FAIL — 404 on `/labeled-epilines`

- [ ] **Step 3: Write the implementation**

Add after `labeled_frames()` in `src/dlc_3d_bp/routes.py`:

```python
@bp.route("/labeled-epilines")
def labeled_epilines():
    """Epipolar lines in the target camera for points labelled in the reference.

    Serves the frame labeler's overlay. Unlike /reproject/epiline the points
    come from the request, not a pose h5 — they are the human's own labels,
    which no file on disk holds yet.

    Uses exactly the primitives /reproject/epiline uses, so the two overlays
    cannot drift apart. undistort_to_pixels is not optional: fundamental_matrix
    is documented as acting on undistorted pixel coordinates.
    """
    with _state_lock:
        proj = _active_project
    session_key = (request.args.get("session") or "").strip()
    if not session_key or not proj:
        return jsonify({"error": "session required and a project must be open"}), 400

    root = Path(proj) / "labeled-data"
    labeled_dir = (root / session_key).resolve()
    if not str(labeled_dir).startswith(str(root.resolve())):
        return jsonify({"error": "session escapes the project"}), 403

    try:
        ref_cam = int(request.args.get("ref_cam", ""))
        tgt_cam = int(request.args.get("tgt_cam", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "ref_cam and tgt_cam must be ints"}), 400
    if ref_cam == tgt_cam:
        return jsonify({"error": "ref_cam and tgt_cam must differ"}), 400

    try:
        points = json.loads(request.args.get("points") or "[]")
        if not isinstance(points, list):
            raise ValueError("points must be a list")
        parsed = [
            (str(p["bodypart"]), float(p["x"]), float(p["y"])) for p in points
        ]
    except (TypeError, ValueError, KeyError) as exc:
        return jsonify({"error": f"bad points: {exc}"}), 400

    if not parsed:
        return jsonify({"segments": {}})

    calib = labeled_dir / "calibration.toml"
    if not calib.is_file():
        return jsonify({
            "error": f"no calibration.toml in labeled-data/{session_key}"
        }), 400
    try:
        cams = rp.load_calibration(calib)
    except Exception as exc:
        return jsonify({"error": f"unreadable calibration.toml: {exc}"}), 400

    ref_key, tgt_key = f"cam_{ref_cam}", f"cam_{tgt_cam}"
    for key in (ref_key, tgt_key):
        if key not in cams:
            return jsonify({
                "error": "unknown camera {!r}; calibration has {}".format(
                    key, sorted(cams))
            }), 400

    cam_ref, cam_tgt = cams[ref_key], cams[tgt_key]
    F = ec.fundamental_matrix(cam_ref, cam_tgt)   # once for every point
    segments = {}
    for bodypart, x, y in parsed:
        pt = ec.undistort_to_pixels(cam_ref, np.array([[x, y]]))[0]
        seg = ec.epiline_endpoints(F, pt, *cam_tgt.size)
        segments[bodypart] = None if seg is None else [list(seg[0]), list(seg[1])]
    return jsonify({"segments": segments})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_labeled_epilines_route.py -q`
Expected: PASS, 14 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/routes.py dlc-3D/tests/test_labeled_epilines_route.py
git commit -m "feat(labeler): /labeled-epilines route for human-placed points"
```

---

### Task 4: Checkbox, `P` shortcut and gating

**Files:**
- Modify: `src/templates/partials/card_frame_labeler.html` — new toggle after the "Show names" label (`card_frame_labeler.html:243-246`)
- Modify: `src/static/frame_labeler_3d.js` — element handle, gate refresh, `P` binding
- Test: `tests/test_frame_labeler_epiline_wiring.py`

**Interfaces:**
- Consumes: `epiGateReason` from `internal/epiline_request.mjs` (Task 1); the `calibration` field on `/labeled-frames` (Task 2).
- Produces: DOM ids `fl3d-epiline` (checkbox) and `fl3d-epiline-hint` (span); JS `_fl3dEpiOn` (bool), `_fl3dEpiCalib` (`{exists, cams}`), `_fl3dRefreshEpiGate()`, and `_fl3dSetEpiEnabled(on)` which Task 5 overrides the body of.

- [ ] **Step 1: Write the failing test**

```python
"""Source assertions for the frame labeler's epipolar overlay wiring.

Same approach as tests/test_reproj_panel_wiring.py: the behaviour lives in a
browser-only module, so we assert on the source. Pure logic that can be tested
for real lives in src/static/internal/epiline_request.mjs and is covered by
tests/unit/test_epiline_request.mjs — these tests cover only the wiring that
module cannot see.
"""
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
JS = SRC / "static" / "frame_labeler_3d.js"
HTML = SRC / "templates" / "partials" / "card_frame_labeler.html"


@pytest.fixture(scope="module")
def js():
    return JS.read_text()


@pytest.fixture(scope="module")
def html():
    return HTML.read_text()


def test_checkbox_and_hint_exist(html):
    assert 'id="fl3d-epiline"' in html
    assert 'id="fl3d-epiline-hint"' in html


def test_checkbox_advertises_its_shortcut(html):
    """Every other labeler toggle shows its key; this one must too."""
    assert "(P)" in html


def test_gate_uses_the_shared_helper(js):
    """The three gating rules are unit-tested in epiline_request.mjs. Wiring a
    second, hand-rolled copy here would put them beyond that test's reach."""
    assert "epiGateReason" in js
    assert "internal/epiline_request.mjs" in js


def test_p_is_bound_and_does_not_fire_while_typing(js):
    assert '"p"' in js.lower()
    block = js.split("document.addEventListener(\"keydown\"")[1]
    assert "INPUT" in block or "tagName" in block, (
        "P must not toggle while the user is typing in a field"
    )


def test_p_respects_the_disabled_gate(js):
    """Otherwise the key bypasses the very gate the checkbox enforces.

    Scoped to the keydown handler on purpose: _fl3dRefreshEpiGate assigns
    `flEpiCheckbox.disabled`, so an unscoped substring check would pass even
    with the P handler wide open.
    """
    block = js.split("document.addEventListener(\"keydown\"")[1]
    idx = block.lower().index('"p"')
    guard = block[max(0, idx - 200): idx + 400]
    assert "disabled" in guard, (
        "the P branch must consult the checkbox's disabled state"
    )


def test_calibration_field_is_read_from_labeled_frames(js):
    assert "_fl3dEpiCalib" in js
    assert ".calibration" in js
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_frame_labeler_epiline_wiring.py -q`
Expected: FAIL — `assert 'id="fl3d-epiline"' in html`

- [ ] **Step 3: Write the implementation**

In `card_frame_labeler.html`, immediately after the "Show names" `<label>` block that ends at line 246, insert:

```html
          <label style="display:flex;align-items:center;gap:.45rem;font-size:.78rem;color:var(--text-dim);cursor:pointer;user-select:none">
            <input type="checkbox" id="fl3d-epiline" style="accent-color:var(--accent)">
            Epipolar lines
          </label>
          <span id="fl3d-epiline-hint" style="font-size:.72rem;color:var(--text-dim);opacity:.7">(P)</span>
```

In `frame_labeler_3d.js`, add the import beside the existing `pair_map.mjs` one at the top of the file:

```javascript
import { epiGateReason, collectRefPoints, payloadSignature }
  from './internal/epiline_request.mjs';
```

Add element handles next to `flShowNamesInput`:

```javascript
    const flEpiCheckbox = document.getElementById("fl3d-epiline");
    const flEpiHint     = document.getElementById("fl3d-epiline-hint");
```

Add state beside `_fl3dSyncOn`:

```javascript
    let _fl3dEpiOn    = false;
    let _fl3dEpiCalib = { exists: false, cams: [] };
```

Where the `/labeled-frames` response is consumed, store the new field:

```javascript
      _fl3dEpiCalib = data.calibration || { exists: false, cams: [] };
      _fl3dRefreshEpiGate();
```

Add the gate and the setter:

```javascript
    // Enable the overlay only when it can actually draw, and say why when it
    // cannot — a checkbox that is simply dead teaches the user nothing.
    function _fl3dRefreshEpiGate() {
      if (!flEpiCheckbox) return;
      const camCount = _fl3dSyncOn
        ? document.querySelectorAll("#fl3d-canvas-row .fl3d-tile").length
        : 1;
      const reason = epiGateReason({
        syncOn:            _fl3dSyncOn,
        calibrationExists: !!_fl3dEpiCalib.exists,
        camCount,
      });
      flEpiCheckbox.disabled = !!reason;
      if (flEpiHint) flEpiHint.textContent = reason || "(P)";
      if (reason && _fl3dEpiOn) _fl3dSetEpiEnabled(false);
    }

    function _fl3dSetEpiEnabled(on) {
      _fl3dEpiOn = !!on;
      if (flEpiCheckbox) flEpiCheckbox.checked = _fl3dEpiOn;
    }

    flEpiCheckbox?.addEventListener("change", () => {
      _fl3dSetEpiEnabled(flEpiCheckbox.checked);
    });
```

Call `_fl3dRefreshEpiGate()` at the end of both branches of the sync-frame
checkbox handler (`frame_labeler_3d.js:709` and `:721`), so turning sync on or
off re-evaluates the gate.

In the `keydown` handler, beside the `Tab` block:

```javascript
      // P — toggle the epipolar overlay. Guarded on the same gate as the
      // checkbox, so the key cannot bypass it.
      if ((e.key === "p" || e.key === "P") && !flEpiCheckbox?.disabled) {
        const t = e.target;
        const tag = t && t.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        e.preventDefault();
        _fl3dSetEpiEnabled(!_fl3dEpiOn);
        return;
      }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_frame_labeler_epiline_wiring.py -q`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/templates/partials/card_frame_labeler.html dlc-3D/src/static/frame_labeler_3d.js dlc-3D/tests/test_frame_labeler_epiline_wiring.py
git commit -m "feat(labeler): epipolar-line toggle, P shortcut and gating"
```

---

### Task 5: Fetch, debounce and draw

**Files:**
- Modify: `src/static/frame_labeler_3d.js` — request/debounce/state plus drawing inside `_fl3dDrawTileMarkers`
- Test: `tests/test_frame_labeler_epiline_wiring.py` (append)

**Interfaces:**
- Consumes: `collectRefPoints`, `payloadSignature` (Task 1); `GET /labeled-epilines` (Task 3); `_fl3dEpiOn`, `_fl3dSetEpiEnabled`, `_fl3dRefreshEpiGate` (Task 4); existing `_fl3dDrawTileMarkers(tile, fname)`, `_flColor(i)`, `_flBodyparts`, `_flLabels`, `_flHidden`, `_fl3dFocusedCam`.
- Produces: nothing consumed downstream.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_frame_labeler_epiline_wiring.py`:

```python
def _epi_block(js):
    """The overlay section, delimited by its own banner comment."""
    assert "EPIPOLAR OVERLAY" in js, "overlay section must be banner-delimited"
    return js.split("EPIPOLAR OVERLAY")[1]


def test_debounce_is_two_seconds(js):
    assert "FL3D_EPI_DEBOUNCE_MS = 2000" in js


def test_enabling_does_not_wait_for_the_debounce(js):
    """A 2 s blank after ticking the box reads as the feature being broken.
    The debounce exists for label edits only."""
    block = _epi_block(js)
    assert "_fl3dEpiRecompute(" in block
    setter = js.split("function _fl3dSetEpiEnabled")[1].split("\n    }")[0]
    assert "_fl3dEpiRecompute" in setter, (
        "enabling must compute immediately, not schedule the debounce"
    )


def test_toggling_off_clears_stored_segments(js):
    setter = js.split("function _fl3dSetEpiEnabled")[1].split("\n    }")[0]
    assert "_fl3dEpiSegments = {}" in setter, (
        "a stale line must not outlive the toggle"
    )


def test_the_draw_path_never_fetches(js):
    """_fl3dDrawTileMarkers runs on zoom, pan and hover. A fetch in there is a
    request storm."""
    fn = js.split("function _fl3dDrawTileMarkers")[1].split("\n    function ")[0]
    assert "fetch(" not in fn
    assert "_fl3dEpiSegments" in fn, "the draw path must paint stored segments"


def test_a_generation_counter_guards_the_async_draw(js):
    """Recorded regression on the sibling overlay — see docs/regression-catalog.md."""
    block = _epi_block(js)
    assert "_fl3dEpiGen" in block
    assert "++_fl3dEpiGen" in block
    assert block.count("_fl3dEpiGen") >= 3, (
        "expected declare / bump / re-check after await"
    )


def test_reference_camera_is_the_last_edited_not_the_focused_one(js):
    """Projecting from the focused camera makes the lines vanish the moment the
    user clicks over to use them."""
    block = _epi_block(js)
    assert "_fl3dEpiRefCam" in block
    fn = js.split("function _fl3dEpiRecompute")[1].split("\n    }")[0]
    assert "_fl3dFocusedCam" not in fn, (
        "recompute must use _fl3dEpiRefCam, not the focused cam"
    )


def test_lines_are_drawn_on_the_non_reference_tile(js):
    fn = js.split("function _fl3dDrawTileMarkers")[1].split("\n    function ")[0]
    assert "_fl3dEpiRefCam" in fn


def test_style_matches_the_reprojection_card(js):
    block = _epi_block(js)
    assert "setLineDash([6, 4])" in block
    assert "_flColor(" in block
    assert "labelAnchor(" in block and "nameLabelBox(" in block


def test_label_step_advances_only_for_drawn_lines(js):
    """Otherwise gaps appear in the staircase where a line was null."""
    fn = js.split("function _fl3dDrawEpilines")[1].split("\n    }")[0]
    assert "order++" in fn
    assert fn.index("continue") < fn.index("order++"), (
        "order must advance after the null check, not before it"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_frame_labeler_epiline_wiring.py -q`
Expected: FAIL — `assert "EPIPOLAR OVERLAY" in js`

- [ ] **Step 3: Write the implementation**

Add the two label helpers to the imports at the top of `frame_labeler_3d.js`:

```javascript
import { labelAnchor } from './internal/epiline_label.mjs';
import { nameLabelBox } from './components/viewer/internal/name_label.mjs';
```

Add a banner-delimited section to `frame_labeler_3d.js`, before
`_fl3dDrawTileMarkers`:

```javascript
    // ── EPIPOLAR OVERLAY ─────────────────────────────────────────────────
    // Projects every point labelled on the reference camera onto the other
    // tile. The reference is the camera whose labels last CHANGED, not the
    // focused one: projecting from the focused camera would make the lines
    // vanish at the moment the user clicks across to use them.

    const FL3D_EPI_DEBOUNCE_MS = 2000;
    const FL3D_EPI_LABEL_STEP  = 14;   // matches the marker name-label height

    let _fl3dEpiSegments = {};    // bodypart -> [[x1,y1],[x2,y2]] | null
    let _fl3dEpiRefCam   = null;  // cam index whose labels were last edited
    let _fl3dEpiTimer    = null;
    let _fl3dEpiGen      = 0;     // stale-response guard
    let _fl3dEpiSig      = "";    // signature of the last issued request

    /** A label changed on `cam` — that camera becomes the reference. */
    function _fl3dEpiNoteEdit(cam) {
      if (Number.isFinite(cam)) _fl3dEpiRefCam = cam;
      _fl3dEpiSchedule();
    }

    /** Debounced: only label edits come through here. */
    function _fl3dEpiSchedule() {
      if (!_fl3dEpiOn) return;
      if (_fl3dEpiTimer) clearTimeout(_fl3dEpiTimer);
      _fl3dEpiTimer = setTimeout(() => {
        _fl3dEpiTimer = null;
        _fl3dEpiRecompute();
      }, FL3D_EPI_DEBOUNCE_MS);
    }

    function _fl3dEpiTileFor(cam) {
      return document.querySelector(
        `#fl3d-canvas-row .fl3d-tile[data-cam="${cam}"]`);
    }

    /** Repaint whichever tile carries the lines. */
    function _fl3dEpiRepaintTarget() {
      const tiles = document.querySelectorAll("#fl3d-canvas-row .fl3d-tile");
      tiles.forEach((t) => {
        if (+t.dataset.cam !== _fl3dEpiRefCam && t.dataset.fname) {
          _fl3dDrawTileMarkers(t, t.dataset.fname);
        }
      });
    }

    /** Immediate: enabling, frame change, sync change. Never debounced. */
    async function _fl3dEpiRecompute() {
      if (!_fl3dEpiOn || !Number.isFinite(_fl3dEpiRefCam)) return;
      const refTile = _fl3dEpiTileFor(_fl3dEpiRefCam);
      const tgtTile = Array.from(
        document.querySelectorAll("#fl3d-canvas-row .fl3d-tile")
      ).find((t) => +t.dataset.cam !== _fl3dEpiRefCam);
      if (!refTile || !tgtTile) return;

      const refFname = refTile.dataset.fname;
      const points = collectRefPoints(
        _flLabels[refFname], _flHidden[refFname], _flBodyparts);
      const sig = payloadSignature(
        _flVideoStem, _fl3dEpiRefCam, +tgtTile.dataset.cam, points);
      if (sig === _fl3dEpiSig) return;   // nothing moved; keep what is drawn
      _fl3dEpiSig = sig;

      if (!points.length) {
        _fl3dEpiSegments = {};
        _fl3dEpiRepaintTarget();
        return;
      }

      const gen = ++_fl3dEpiGen;
      try {
        const url = "/dlc-3d/labeled-epilines"
          + `?session=${encodeURIComponent(_flVideoStem)}`
          + `&ref_cam=${_fl3dEpiRefCam}&tgt_cam=${+tgtTile.dataset.cam}`
          + `&points=${encodeURIComponent(JSON.stringify(points))}`;
        const r = await fetch(url);
        if (gen !== _fl3dEpiGen) return;          // superseded mid-flight
        const d = await r.json().catch(() => ({}));
        if (gen !== _fl3dEpiGen) return;          // and again after the parse
        _fl3dEpiSegments = r.ok ? (d.segments || {}) : {};
        if (!r.ok && flEpiHint) flEpiHint.textContent = d.error || "epilines failed";
        else if (flEpiHint) flEpiHint.textContent = "(P)";
      } catch (e) {
        if (gen !== _fl3dEpiGen) return;
        _fl3dEpiSegments = {};
        if (flEpiHint) flEpiHint.textContent = "epilines unavailable";
      }
      _fl3dEpiRepaintTarget();
    }

    /** Paint stored segments. Never fetches — see the draw-path test. */
    function _fl3dDrawEpilines(tile) {
      const canvas = tile.querySelector(".fl3d-tile-canvas");
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      let order = 0;
      for (let i = 0; i < _flBodyparts.length; i++) {
        const bp = _flBodyparts[i];
        const seg = _fl3dEpiSegments[bp];
        if (!seg) continue;                   // null or absent — draw nothing
        const color = _flColor(i);
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(seg[0][0], seg[0][1]);
        ctx.lineTo(seg[1][0], seg[1][1]);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.setLineDash([6, 4]);
        ctx.stroke();
        ctx.restore();

        const anchor = labelAnchor(seg, order, FL3D_EPI_LABEL_STEP);
        if (anchor) {
          ctx.save();
          ctx.font = nameLabelBox(0, 0, 0, 0).font;
          const box = nameLabelBox(anchor.x, anchor.y, 0,
                                   ctx.measureText(bp).width);
          ctx.fillStyle = "rgba(12,13,16,.65)";
          ctx.fillRect(box.boxX, box.boxY, box.boxW, box.boxH);
          ctx.fillStyle = color;
          ctx.fillText(bp, box.textX, box.textY);
          ctx.restore();
        }
        order++;   // only a drawn line advances the staircase
      }
    }
```

At the **end** of `_fl3dDrawTileMarkers`, after its `_flBodyparts.forEach` loop:

```javascript
      // Epipolar lines belong on the tile that is NOT the reference.
      if (_fl3dEpiOn && Number.isFinite(_fl3dEpiRefCam)
          && +tile.dataset.cam !== _fl3dEpiRefCam) {
        _fl3dDrawEpilines(tile);
      }
```

Replace the Task 4 body of `_fl3dSetEpiEnabled` with:

```javascript
    function _fl3dSetEpiEnabled(on) {
      _fl3dEpiOn = !!on;
      if (flEpiCheckbox) flEpiCheckbox.checked = _fl3dEpiOn;
      if (_fl3dEpiTimer) { clearTimeout(_fl3dEpiTimer); _fl3dEpiTimer = null; }
      _fl3dEpiSig = "";
      if (_fl3dEpiOn) {
        // Immediate — the labels are already settled and the user is waiting.
        _fl3dEpiRecompute();
      } else {
        _fl3dEpiSegments = {};
        _fl3dEpiRepaintTarget();
      }
    }
```

`_fl3dEpiRefCam` is seeded — never inside `_fl3dEpiRecompute`, which must not
read the focused camera at all. Seed it in exactly two places:

```javascript
// in _fl3dSetEpiEnabled, before the _fl3dEpiRecompute() call:
      if (!Number.isFinite(_fl3dEpiRefCam)) _fl3dEpiRefCam = _fl3dFocusedCam;
```

and in `_flShowFrame`, after the new frame's tiles are rendered:

```javascript
      _fl3dEpiRefCam = _fl3dFocusedCam;   // new frame — reference resets
      _fl3dEpiSig = "";                   // force a recompute for this frame
      _fl3dEpiRecompute();                // immediate; the labels are settled
```

Then call `_fl3dEpiNoteEdit(_fl3dFocusedCam)` at each of these five label
mutation sites, all of which already exist in the file:

1. the `flCanvas` `click` handler, after `_flLabels[fname][_flSelectedBp] = [cx, cy]`
2. the `w`/`a`/`s`/`d` nudge branch in the `keydown` handler, after the label is written
3. `_flRemoveBpLabel` (right-click and `Backspace`)
4. the `Delete` branch in the `keydown` handler
5. `_flToggleVisibility` (`Space`)

Each is a one-line addition; none of them changes existing behaviour.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_frame_labeler_epiline_wiring.py -q`
Expected: PASS, 15 tests

- [ ] **Step 5: Run the whole suite for regressions**

Run: `cd dlc-3D && python3 -m pytest tests/ -q --ignore=tests/e2e`
Expected: 8 failures — the known baseline, no more. Then
`node --test tests/unit/test_epiline_request.mjs` — PASS.

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/static/frame_labeler_3d.js dlc-3D/tests/test_frame_labeler_epiline_wiring.py
git commit -m "feat(labeler): compute and draw epipolar lines on the sibling tile"
```

---

## Deployment

`dlc-3D/src/static` and `src/templates/partials/card_frame_labeler.html` reach
the `dlc-3d` container through bind mounts, but `src/dlc_3d_bp` is a **directory**
mount whose Python is imported once at boot. So:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d
```

Then verify inside the container rather than assuming:

```bash
docker compose exec -T dlc-3d grep -c "labeled-epilines" /app/dlc_3d_bp/routes.py
docker compose exec -T dlc-3d grep -c "fl3d-epiline" /app/templates/partials/card_frame_labeler.html
docker compose exec -T dlc-3d grep -c "EPIPOLAR OVERLAY" /app/static/frame_labeler_3d.js
```

The static JS has no cache-buster, so the browser needs a hard refresh
(Ctrl+Shift+R).

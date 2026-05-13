# DLC-3D Lightning-Pose Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four UI cards to the dlc-3D module exposing lightning-pose (LP) capabilities — DLC→LP project conversion, MVT training with patch-masking and 3D reprojection loss, and EKS post-hoc smoothing — without disturbing the existing DLC + Anipose flow.

**Architecture:** All new code lives inside `dlc-3D/`. A new GPU-enabled Celery worker container (`dlc-3d-worker`) consumes a dedicated `lp_3d` Redis queue, leaving the main webapp's existing workers untouched. The dlc-3D Flask blueprint gains a new `/dlc-3d/lp/*` sub-blueprint that enqueues jobs and polls their status. Conversion is synchronous; training and EKS go through Celery.

**Tech Stack:** Python 3, Flask Blueprints, Celery 5 + Redis, `lightning-pose` (pip), `ensemble-kalman-smoother` (pip), Docker Compose, vanilla ES modules, pytest.

**Reference spec:** `docs/superpowers/specs/2026-05-13-dlc-3d-lightning-pose-integration-design.md`

**Test fixture project:** `/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-TEST` (already provisioned — 1.9 GB copy of the live project with `dlc-models-pytorch/` and `training-datasets/` excluded).

**Repo paths used in this plan:**
- Module root: `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/`
- Main webapp: `/home/sam/docker-images/deeplabcut-webapp-docker/`

---

## File Structure

**Created:**
```
dlc-3D/
  Dockerfile.worker                         # NEW: pytorch + LP + EKS image
  requirements-lp.txt                       # NEW: LP/EKS pins
  src/dlc_3d_bp/
    lp_routes.py                            # NEW: /dlc-3d/lp/* Flask routes
    lp/
      __init__.py
      celery_app.py                         # NEW: Celery client for lp_3d queue
      tasks.py                              # NEW: lp_train, lp_eks tasks
      converter.py                          # NEW: DLC→LP conversion (pure-python)
      eks_runner.py                         # NEW: EKS wrapper
      train_runner.py                       # NEW: litpose train wrapper + config builder
      project_layout.py                     # NEW: LP project on-disk helpers
      job_registry.py                       # NEW: Redis-backed job index
  src/templates/partials/
    card_lp_convert.html                    # NEW
    card_lp_train.html                      # NEW
    card_lp_eks.html                        # NEW
    card_lp_jobs.html                       # NEW
  src/static/
    lp_cards.js                             # NEW: card wiring + polling
    lp_cards.css                            # NEW
  tests/
    test_lp_converter.py                    # NEW
    test_lp_eks.py                          # NEW
    test_lp_routes.py                       # NEW
    test_lp_train_config.py                 # NEW
    test_lp_project_layout.py               # NEW
    test_lp_job_registry.py                 # NEW
```

**Modified:**
- `dlc-3D/src/app.py` — register the new `lp_bp` blueprint
- `dlc-3D/src/templates/dlc_3d.html` — include the four new partial templates
- `dlc-3D/src/templates/partials/card_admin.html` — add four toggle entries in the card-visibility menu
- `deeplabcut-webapp-docker/docker-compose.yml` — add `dlc-3d-worker` service (only main-webapp change)

**Untouched (regression net):** `src/dlc_3d_bp/routes.py`, `src/viewer.py`, `src/config.py`, all existing card partials, all existing JS modules, `tests/test_core.py`.

---

## Phase 0 — Working directory & branch

- [ ] **Step 0.1: Verify clean working tree on the supports repo**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git status --short
```
Expected: spec from this session is committed (`bbde9c4` or later); nothing else dirty in `dlc-3D/`. Other modules (`clip-cutter/`) may have unstaged changes — leave them alone.

- [ ] **Step 0.2: Confirm fixture project exists**

Run:
```bash
ls /home/sam/Parra-Lab-Data-NAS/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-TEST/config.yaml
```
Expected: file listed, no error. If missing, run the rsync from the spec session — duplication is a prerequisite for converter tests.

---

## Phase 1 — Scaffold & blueprint registration

Goal: empty package + new blueprint registers without runtime errors. Tests that just verify imports + URL map. No behavior yet.

### Task 1.1: Create the `lp` package skeleton

**Files:**
- Create: `dlc-3D/src/dlc_3d_bp/lp/__init__.py`
- Create: `dlc-3D/src/dlc_3d_bp/lp/celery_app.py` (stub)
- Create: `dlc-3D/src/dlc_3d_bp/lp/tasks.py` (stub)
- Create: `dlc-3D/src/dlc_3d_bp/lp/converter.py` (stub)
- Create: `dlc-3D/src/dlc_3d_bp/lp/eks_runner.py` (stub)
- Create: `dlc-3D/src/dlc_3d_bp/lp/train_runner.py` (stub)
- Create: `dlc-3D/src/dlc_3d_bp/lp/project_layout.py` (stub)
- Create: `dlc-3D/src/dlc_3d_bp/lp/job_registry.py` (stub)
- Create: `dlc-3D/src/dlc_3d_bp/lp_routes.py` (stub)
- Test: `dlc-3D/tests/test_lp_routes.py`

- [ ] **Step 1.1.1: Write the failing import test**

Create `dlc-3D/tests/test_lp_routes.py`:
```python
import pytest

def test_lp_package_imports():
    from dlc_3d_bp import lp  # noqa: F401
    from dlc_3d_bp.lp import (  # noqa: F401
        celery_app, tasks, converter, eks_runner, train_runner,
        project_layout, job_registry,
    )

def test_lp_blueprint_imports():
    from dlc_3d_bp.lp_routes import lp_bp
    assert lp_bp.url_prefix == "/dlc-3d/lp"
```

- [ ] **Step 1.1.2: Run test to verify fail**

Run: `cd dlc-3D && python -m pytest tests/test_lp_routes.py -q`
Expected: ImportError on `dlc_3d_bp.lp`.

- [ ] **Step 1.1.3: Create stub files**

Create empty `dlc-3D/src/dlc_3d_bp/lp/__init__.py` (empty file).

Create stubs for each module — body is a single docstring:
```python
"""<module purpose>. Stub — implementation in later tasks."""
```

Create `dlc-3D/src/dlc_3d_bp/lp_routes.py`:
```python
"""Flask blueprint for /dlc-3d/lp/* endpoints."""
from flask import Blueprint

lp_bp = Blueprint(
    "dlc_3d_lp", __name__, url_prefix="/dlc-3d/lp",
)
```

- [ ] **Step 1.1.4: Run test to verify pass**

Run: `cd dlc-3D && python -m pytest tests/test_lp_routes.py -q`
Expected: 2 passed.

- [ ] **Step 1.1.5: Register blueprint in app.py**

Modify `dlc-3D/src/app.py`:
```python
from base_app import app
from dlc_3d_bp.routes import bp
from dlc_3d_bp.lp_routes import lp_bp

app.register_blueprint(bp)
app.register_blueprint(lp_bp)
```

- [ ] **Step 1.1.6: Add registration test with a fresh-import fixture**

The tests need a `base_app` stub and a fresh `app` module per test (re-registering a Blueprint on the same Flask instance raises in Flask ≥ 3). Append to `tests/test_lp_routes.py`:
```python
import sys, types
import pytest
from flask import Flask


@pytest.fixture
def lp_app(tmp_path):
    """Return a fresh Flask app with base_app stubbed and a tmp base.html.

    Pops cached modules so the dlc-3D `app.py` re-runs and registers
    blueprints onto a new Flask instance for every test.
    """
    sys.modules.pop("app", None)
    sys.modules.pop("base_app", None)
    stub = types.ModuleType("base_app")
    stub.app = Flask(
        "base_app_stub",
        template_folder=str(tmp_path),
        static_folder=str(tmp_path),
    )
    sys.modules["base_app"] = stub
    # Minimal base.html so {% extends %} works in dlc_3d.html
    (tmp_path / "base.html").write_text(
        "<html><head>{% block extra_head %}{% endblock %}</head>"
        "<body>{% block content %}{% endblock %}"
        "{% block scripts %}{% endblock %}</body></html>"
    )
    import app as dlc3d_app_mod
    return dlc3d_app_mod.app


def test_lp_blueprint_registered(lp_app):
    assert "dlc_3d_lp" in lp_app.blueprints
    rules = [r.rule for r in lp_app.url_map.iter_rules()]
    assert any(r.startswith("/dlc-3d/lp") for r in rules) or "dlc_3d_lp" in lp_app.blueprints
```

(Drop the earlier `test_lp_blueprint_imports` / `test_lp_package_imports` tests if they still use the cached-module pattern; the fixture replaces it.)

- [ ] **Step 1.1.7: Run tests**

Run: `cd dlc-3D && python -m pytest tests/test_lp_routes.py -q`
Expected: 3 passed.

- [ ] **Step 1.1.8: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/dlc_3d_bp/lp dlc-3D/src/dlc_3d_bp/lp_routes.py dlc-3D/src/app.py dlc-3D/tests/test_lp_routes.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): scaffold lp_routes blueprint + lp package"
```

### Task 1.2: Health endpoint

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp_routes.py`
- Test: `dlc-3D/tests/test_lp_routes.py`

- [ ] **Step 1.2.1: Write the failing test**

Append to `tests/test_lp_routes.py` (uses the `lp_app` fixture):
```python
def test_health_endpoint(lp_app):
    client = lp_app.test_client()
    r = client.get("/dlc-3d/lp/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert "worker_reachable" in body
```

- [ ] **Step 1.2.2: Verify fail**

Run: `cd dlc-3D && python -m pytest tests/test_lp_routes.py::test_health_endpoint -q`
Expected: 404 → assertion fail.

- [ ] **Step 1.2.3: Implement**

Edit `dlc-3D/src/dlc_3d_bp/lp_routes.py`:
```python
"""Flask blueprint for /dlc-3d/lp/* endpoints."""
import os
from flask import Blueprint, jsonify

lp_bp = Blueprint("dlc_3d_lp", __name__, url_prefix="/dlc-3d/lp")


def _worker_reachable() -> bool:
    """Best-effort: ping the lp_3d queue's worker via Celery inspect.

    Returns False if Celery isn't importable or no worker responds in 1s.
    """
    try:
        from dlc_3d_bp.lp.celery_app import celery
    except Exception:
        return False
    try:
        replies = celery.control.inspect(timeout=1.0).ping() or {}
        return bool(replies)
    except Exception:
        return False


@lp_bp.route("/health")
def health():
    return jsonify({
        "ok": True,
        "worker_reachable": _worker_reachable(),
        "queue": "lp_3d",
        "broker_url": os.environ.get("CELERY_BROKER_URL", ""),
    })
```

- [ ] **Step 1.2.4: Verify pass**

Run: `cd dlc-3D && python -m pytest tests/test_lp_routes.py -q`
Expected: 4 passed.

- [ ] **Step 1.2.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp_routes.py dlc-3D/tests/test_lp_routes.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): /dlc-3d/lp/health endpoint"
```

### Task 1.3: Card stubs (hidden by default)

**Files:**
- Create: `dlc-3D/src/templates/partials/card_lp_convert.html`
- Create: `dlc-3D/src/templates/partials/card_lp_train.html`
- Create: `dlc-3D/src/templates/partials/card_lp_eks.html`
- Create: `dlc-3D/src/templates/partials/card_lp_jobs.html`
- Create: `dlc-3D/src/static/lp_cards.js`
- Create: `dlc-3D/src/static/lp_cards.css`
- Modify: `dlc-3D/src/templates/dlc_3d.html`

- [ ] **Step 1.3.1: Create empty card partials**

For each of `card_lp_convert.html`, `card_lp_train.html`, `card_lp_eks.html`, `card_lp_jobs.html` write the same skeleton (replacing TITLE and ID):

`card_lp_convert.html`:
```html
<section class="card dlc-theme hidden" id="lp-convert-card">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.3rem">
    <h2>Convert to Lightning-Pose Project</h2>
    <button class="btn-sm" id="btn-close-lp-convert" title="Close">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      Close
    </button>
  </div>
  <p class="subtitle">Stub — implementation in Phase 2.</p>
</section>
```

Use ids `lp-train-card`, `lp-eks-card`, `lp-jobs-card` and titles
"Train Lightning-Pose Model", "EKS Post-Hoc Smoothing", "LP Jobs" respectively.

- [ ] **Step 1.3.2: Create empty JS/CSS files**

`dlc-3D/src/static/lp_cards.js`:
```javascript
// Lightning-Pose cards — wiring + job polling.
// Implemented in later phases.
export {};
```

`dlc-3D/src/static/lp_cards.css`:
```css
/* lp-* card styling. Implemented in later phases. */
```

- [ ] **Step 1.3.3: Include in main template**

Modify `dlc-3D/src/templates/dlc_3d.html`. Add the four includes inside the `<main class="cards">` block, after `card_admin.html`:
```html
    {% include "partials/card_admin.html" %}
    {% include "partials/card_lp_convert.html" %}
    {% include "partials/card_lp_train.html" %}
    {% include "partials/card_lp_eks.html" %}
    {% include "partials/card_lp_jobs.html" %}
```

Add the new asset references inside the `{% block extra_head %}` and `{% block scripts %}` blocks. Add to `extra_head`:
```html
<link rel="stylesheet" href="{{ url_for('dlc_3d.static', filename='lp_cards.css') }}">
```

Add to `scripts` (after the existing module scripts):
```html
<script type="module" src="{{ url_for('dlc_3d.static', filename='lp_cards.js') }}"></script>
```

- [ ] **Step 1.3.4: Write template-render test**

Append to `tests/test_lp_routes.py`:
```python
def test_index_renders_with_lp_cards(lp_app):
    client = lp_app.test_client()
    r = client.get("/dlc-3d/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    for cid in ("lp-convert-card", "lp-train-card", "lp-eks-card", "lp-jobs-card"):
        assert cid in html, f"missing {cid}"
```

- [ ] **Step 1.3.5: Run tests**

Run: `cd dlc-3D && python -m pytest tests/test_lp_routes.py -q`
Expected: 5 passed.

- [ ] **Step 1.3.6: Commit**

```bash
git add dlc-3D/src/templates dlc-3D/src/static/lp_cards.js dlc-3D/src/static/lp_cards.css dlc-3D/tests/test_lp_routes.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): scaffold 4 LP card partials + JS/CSS stubs"
```

---

## Phase 2 — DLC → Lightning-Pose Converter (Card 1)

Goal: a working `Convert to Lightning-Pose Project` card that converts the fixture project to a valid LP project on disk.

### Task 2.1: Project layout helpers

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/project_layout.py`
- Test: `dlc-3D/tests/test_lp_project_layout.py`

- [ ] **Step 2.1.1: Write failing tests**

Create `dlc-3D/tests/test_lp_project_layout.py`:
```python
from pathlib import Path
import pytest

from dlc_3d_bp.lp import project_layout as L


def test_view_name_from_stem():
    assert L.view_name_from_stem("surv1_cam0_20260123_xyz") == "cam0"
    assert L.view_name_from_stem("surv1_cam2_20260123_xyz") == "cam2"
    assert L.view_name_from_stem("no_cam_pattern") is None


def test_session_view_pair_round_trip():
    s, v = L.session_view_pair("surv1_cam1_20260123_xyz")
    assert s == "surv1_20260123"
    assert v == "cam1"


def test_lp_csv_filename_for_view():
    assert L.lp_csv_for_view("cam0") == "cam0.csv"


def test_lp_labeled_dir_name():
    assert L.lp_labeled_dir_name("surv1_20260123", "cam0") == "surv1_20260123_cam0"
```

- [ ] **Step 2.1.2: Verify fail**

Run: `cd dlc-3D && python -m pytest tests/test_lp_project_layout.py -q`
Expected: AttributeError on functions.

- [ ] **Step 2.1.3: Implement**

Replace `dlc-3D/src/dlc_3d_bp/lp/project_layout.py`:
```python
"""LP project on-disk layout helpers — derive view names, session keys,
and LP-spec file/dir names from DLC-style filenames."""
import re

_CAM_RE = re.compile(r"_cam(\d+)_")
_SESSION_RE = re.compile(r"^(.+?)_cam\d+_(\d{8})")


def view_name_from_stem(stem: str) -> str | None:
    m = _CAM_RE.search(stem)
    return f"cam{m.group(1)}" if m else None


def session_view_pair(stem: str) -> tuple[str | None, str | None]:
    sm = _SESSION_RE.match(stem)
    vm = _CAM_RE.search(stem)
    session = f"{sm.group(1)}_{sm.group(2)}" if sm else None
    view    = f"cam{vm.group(1)}" if vm else None
    return session, view


def lp_csv_for_view(view: str) -> str:
    return f"{view}.csv"


def lp_labeled_dir_name(session_key: str, view: str) -> str:
    return f"{session_key}_{view}"
```

- [ ] **Step 2.1.4: Verify pass**

Run: `cd dlc-3D && python -m pytest tests/test_lp_project_layout.py -q`
Expected: 4 passed.

- [ ] **Step 2.1.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/project_layout.py dlc-3D/tests/test_lp_project_layout.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): lp.project_layout — LP naming helpers"
```

### Task 2.2: Converter — fixture-based test first

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/converter.py`
- Test: `dlc-3D/tests/test_lp_converter.py`

- [ ] **Step 2.2.1: Write failing fixture-driven test**

Create `dlc-3D/tests/test_lp_converter.py`:
```python
import csv
from pathlib import Path
import pytest

from dlc_3d_bp.lp.converter import convert_dlc_to_lp

FIXTURE = Path(
    "/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/"
    "DREADD-Ali-2026-01-07-LP-TEST"
)
HOST_FALLBACK = Path(
    "/home/sam/Parra-Lab-Data-NAS/Motor-Learning/DLC-Projects/"
    "DREADD-Ali-2026-01-07-LP-TEST"
)


def _fixture() -> Path:
    if FIXTURE.is_dir():
        return FIXTURE
    if HOST_FALLBACK.is_dir():
        return HOST_FALLBACK
    pytest.skip("LP test fixture project not present")


def test_convert_creates_lp_layout(tmp_path):
    src = _fixture()
    dst = tmp_path / "lp-project"
    summary = convert_dlc_to_lp(src, dst, link_mode="link")
    assert (dst / "config.yaml").is_file()
    assert (dst / "labeled-data").is_dir()
    # At least one cam CSV at root
    csvs = sorted(dst.glob("cam*.csv"))
    assert len(csvs) >= 1, "no per-view CSVs written"
    # All cam*.csv files must have the same row count
    counts = []
    for c in csvs:
        with c.open() as f:
            rows = list(csv.reader(f))
        counts.append(len(rows))
    assert len(set(counts)) == 1, f"per-view row counts disagree: {counts}"
    # source project untouched: no new files appeared at top level
    assert "LP-TEST-mutated" not in {p.name for p in src.iterdir()}
    # summary contract
    assert "n_views" in summary
    assert "n_frames" in summary
    assert "warnings" in summary


def test_convert_aggregates_calibration(tmp_path):
    src = _fixture()
    dst = tmp_path / "lp-project"
    convert_dlc_to_lp(src, dst, link_mode="link")
    cal_dir = dst / "calibrations"
    cal_csv = dst / "calibrations.csv"
    # If the source has at least one calibration.toml, both must be populated
    has_cal = any(src.glob("labeled-data/*/calibration.toml"))
    if has_cal:
        assert cal_dir.is_dir()
        assert any(cal_dir.glob("*.toml"))
        assert cal_csv.is_file()
```

- [ ] **Step 2.2.2: Verify fail**

Run: `cd dlc-3D && python -m pytest tests/test_lp_converter.py -q`
Expected: ImportError or "function not defined".

- [ ] **Step 2.2.3: Implement converter**

Replace `dlc-3D/src/dlc_3d_bp/lp/converter.py`:
```python
"""DLC → Lightning-Pose project conversion.

Pure-python; safe to call from the Flask container (no GPU, no LP imports).
The source DLC project is never mutated.
"""
from __future__ import annotations

import csv
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .project_layout import session_view_pair, lp_csv_for_view, lp_labeled_dir_name


@dataclass
class ConversionSummary:
    n_views: int = 0
    n_sessions: int = 0
    n_frames: int = 0
    n_calibrations: int = 0
    warnings: list[str] = field(default_factory=list)
    output_dir: str = ""

    def asdict(self) -> dict:
        return {
            "n_views": self.n_views,
            "n_sessions": self.n_sessions,
            "n_frames": self.n_frames,
            "n_calibrations": self.n_calibrations,
            "warnings": self.warnings,
            "output_dir": self.output_dir,
        }


def _read_dlc_collected_csv(path: Path) -> dict[int, list[list[str]]]:
    """Return {frame_number: [row1, row2, ...]} from a CollectedData_*.csv.

    DLC schemas vary. We don't parse the header rows — we treat the file as
    opaque row blocks keyed by frame number, which is sufficient for ordering.
    """
    rows: dict[int, list[list[str]]] = {}
    if not path.is_file():
        return rows
    header: list[list[str]] = []
    body: list[list[str]] = []
    with path.open(newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            # DLC header rows start with literal 'scorer'/'bodyparts'/'coords'
            if row[0] in ("scorer", "bodyparts", "coords", "individuals"):
                header.append(row)
                continue
            body.append(row)
    for row in body:
        # Path is in column 0 (or columns 0-2 for newer schemas); frame number
        # is the last path segment like 'imgNNNNN.png'.
        path_cell = row[0] if len(row[0]) > 4 else "/".join(row[:3])
        name = Path(path_cell).name
        digits = "".join(ch for ch in name if ch.isdigit())
        if not digits:
            continue
        frame_no = int(digits[-5:]) if len(digits) >= 5 else int(digits)
        rows.setdefault(frame_no, []).append(row)
    rows["__header__"] = header  # type: ignore[index]
    return rows


def _list_calibrations(dlc_dir: Path) -> list[tuple[str, Path]]:
    """Return [(session_key, calibration_toml_path), ...] from labeled-data/*/calibration.toml."""
    found: list[tuple[str, Path]] = []
    ld = dlc_dir / "labeled-data"
    if not ld.is_dir():
        return found
    for session_dir in sorted(ld.iterdir()):
        if not session_dir.is_dir():
            continue
        cal = session_dir / "calibration.toml"
        if cal.is_file():
            found.append((session_dir.name, cal))
    return found


def _link_or_copy(src: Path, dst: Path, mode: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    if mode == "link":
        try:
            os.link(src, dst)
            return
        except OSError:
            pass  # fall back to copy across filesystems
    shutil.copy2(src, dst)


def convert_dlc_to_lp(
    dlc_dir: Path | str,
    lp_dir: Path | str,
    link_mode: str = "link",
    force: bool = False,
) -> dict:
    """Convert a DLC project to LP layout. Returns a summary dict.

    Raises FileNotFoundError / ValueError on bad inputs.
    """
    dlc_dir = Path(dlc_dir).resolve()
    lp_dir = Path(lp_dir).resolve()

    if not (dlc_dir / "config.yaml").is_file():
        raise FileNotFoundError(f"DLC config.yaml not found in {dlc_dir}")
    if lp_dir.exists() and any(lp_dir.iterdir()) and not force:
        raise ValueError(f"LP output dir {lp_dir} is not empty; pass force=True to overwrite")

    summary = ConversionSummary(output_dir=str(lp_dir))
    lp_dir.mkdir(parents=True, exist_ok=True)
    (lp_dir / "labeled-data").mkdir(exist_ok=True)
    (lp_dir / "videos").mkdir(exist_ok=True)

    # 1. Discover sessions and views from labeled-data folder names
    by_session: dict[str, dict[str, dict]] = {}
    for session_dir in sorted((dlc_dir / "labeled-data").iterdir()) if (dlc_dir / "labeled-data").is_dir() else []:
        if not session_dir.is_dir():
            continue
        session_key, view = session_view_pair(session_dir.name)
        if not session_key or not view:
            summary.warnings.append(
                f"skipping unrecognised labeled-data folder: {session_dir.name}"
            )
            continue
        # CollectedData_*.csv path
        cc = next(session_dir.glob("CollectedData_*.csv"), None)
        by_session.setdefault(session_key, {})[view] = {
            "src_dir": session_dir,
            "collected_csv": cc,
        }

    # Keep only sessions with >=2 views (multi-view requirement); single-view
    # sessions are emitted as warnings.
    multi: dict[str, dict[str, dict]] = {}
    for skey, views in by_session.items():
        if len(views) >= 2:
            multi[skey] = views
        else:
            summary.warnings.append(f"session {skey} has only {len(views)} view(s); skipped")

    # 2. Determine the canonical view ordering across sessions
    all_views = sorted({v for views in multi.values() for v in views})
    summary.n_views = len(all_views)
    summary.n_sessions = len(multi)

    if not all_views:
        # write a minimal config and return
        _write_lp_config(lp_dir, dlc_dir, all_views)
        return summary.asdict()

    # 3. Per-view CSV builders — accumulate rows in canonical order
    per_view_rows: dict[str, list[list[str]]] = {v: [] for v in all_views}
    per_view_header: dict[str, list[list[str]]] = {v: [] for v in all_views}

    for session_key in sorted(multi):
        views = multi[session_key]
        # Load CSVs for each view
        view_to_frames: dict[str, dict[int, list[list[str]]]] = {}
        for v in all_views:
            entry = views.get(v)
            if not entry or not entry.get("collected_csv"):
                view_to_frames[v] = {}
                continue
            view_to_frames[v] = _read_dlc_collected_csv(entry["collected_csv"])
            if not per_view_header[v]:
                per_view_header[v] = view_to_frames[v].pop("__header__", [])
            else:
                view_to_frames[v].pop("__header__", None)

        # Intersect frame numbers across views present for this session
        present_views = [v for v in all_views if view_to_frames.get(v)]
        if len(present_views) < 2:
            summary.warnings.append(
                f"session {session_key}: <2 views with labels; skipped"
            )
            continue
        common = set.intersection(*[set(view_to_frames[v].keys()) for v in present_views])
        if not common:
            summary.warnings.append(
                f"session {session_key}: no common labeled frames across views; skipped"
            )
            continue

        # Emit rows + copy frames
        for frame_no in sorted(common):
            for v in all_views:
                if v in present_views:
                    for row in view_to_frames[v][frame_no]:
                        # Rewrite path column to new labeled-data location
                        new_dir = lp_labeled_dir_name(session_key, v)
                        new_rel = f"labeled-data/{new_dir}/img{frame_no:08d}.png"
                        new_row = [new_rel] + list(row[1:])
                        per_view_rows[v].append(new_row)
                else:
                    summary.warnings.append(
                        f"session {session_key} missing view {v} for frame {frame_no}"
                    )

            # Link/copy the frame PNGs (best-effort; original filename in DLC
            # is img_cam<N>_<order>_<frame>.png)
            for v in present_views:
                src_dir = views[v]["src_dir"]
                matches = list(src_dir.glob(f"img_*_{frame_no:05d}.png"))
                if not matches:
                    matches = list(src_dir.glob(f"img*{frame_no}*.png"))
                if matches:
                    dst = lp_dir / "labeled-data" / lp_labeled_dir_name(session_key, v) / f"img{frame_no:08d}.png"
                    _link_or_copy(matches[0], dst, link_mode)
                    summary.n_frames += 1

    # 4. Write per-view CSVs at LP project root
    for v in all_views:
        out_csv = lp_dir / lp_csv_for_view(v)
        with out_csv.open("w", newline="") as f:
            w = csv.writer(f)
            for hrow in per_view_header[v]:
                w.writerow(hrow)
            for row in per_view_rows[v]:
                w.writerow(row)

    # 5. Aggregate calibrations
    cal_entries = _list_calibrations(dlc_dir)
    if cal_entries:
        cal_dir = lp_dir / "calibrations"
        cal_dir.mkdir(exist_ok=True)
        # Take one calibration per session_key (use folder name's session part)
        seen: set[str] = set()
        with (lp_dir / "calibrations.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["session", "calibration_file"])
            for folder_name, cal_path in cal_entries:
                skey, _ = session_view_pair(folder_name)
                if not skey or skey in seen:
                    continue
                seen.add(skey)
                dst = cal_dir / f"{skey}.toml"
                _link_or_copy(cal_path, dst, link_mode)
                w.writerow([skey, f"calibrations/{skey}.toml"])
                summary.n_calibrations += 1

    # 6. Write LP config.yaml
    _write_lp_config(lp_dir, dlc_dir, all_views)

    return summary.asdict()


def _write_lp_config(lp_dir: Path, dlc_dir: Path, views: list[str]) -> None:
    with (dlc_dir / "config.yaml").open() as f:
        dlc_cfg = yaml.safe_load(f) or {}
    bodyparts = dlc_cfg.get("bodyparts", []) or dlc_cfg.get("multianimalbodyparts", [])
    lp_cfg = {
        "data": {
            "data_dir": str(lp_dir),
            "video_dir": "videos",
            "csv_file": [f"{v}.csv" for v in views] if len(views) > 1 else (views[0] + ".csv" if views else "labels.csv"),
            "view_names": views,
            "keypoint_names": bodyparts,
            "num_keypoints": len(bodyparts),
        },
        "model": {
            "model_type": "heatmap_mhcrnn" if len(views) <= 1 else "multiview_heatmap",
            "backbone": "resnet50_animal_apose",
            "losses_to_use": [],
        },
        "training": {
            "max_epochs": 300,
            "train_batch_size": 16,
            "val_batch_size": 16,
            "test_batch_size": 16,
            "imgaug_3d": False,
        },
        "losses": {},
        "eval": {
            "predict_vids_after_training": False,
            "save_vids_after_training": False,
        },
        "callbacks": {},
        "_converter": {
            "source_dlc_dir": str(dlc_dir),
            "views": views,
        },
    }
    with (lp_dir / "config.yaml").open("w") as f:
        yaml.safe_dump(lp_cfg, f, sort_keys=False)
```

- [ ] **Step 2.2.4: Verify pass**

Run: `cd dlc-3D && python -m pytest tests/test_lp_converter.py -q`
Expected: 2 passed.

- [ ] **Step 2.2.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/converter.py dlc-3D/tests/test_lp_converter.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): lp.converter — DLC project → LP layout"
```

### Task 2.3: Convert route + Card 1 UI

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp_routes.py`
- Modify: `dlc-3D/src/templates/partials/card_lp_convert.html`
- Modify: `dlc-3D/src/static/lp_cards.js`
- Test: `dlc-3D/tests/test_lp_routes.py`

- [ ] **Step 2.3.1: Write failing test for /convert**

Append to `tests/test_lp_routes.py` (uses the `lp_app` fixture from Phase 1):
```python
def test_convert_endpoint_validates_input(lp_app):
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/convert", json={})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_convert_endpoint_rejects_outside_user_data(lp_app):
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/convert", json={
        "dlc_dir": "/etc",
        "lp_dir":  "/etc-lp",
    })
    assert r.status_code == 403
```

- [ ] **Step 2.3.2: Verify fail**

Run: `cd dlc-3D && python -m pytest tests/test_lp_routes.py -q`
Expected: failures on new tests (404).

- [ ] **Step 2.3.3: Implement route**

Append to `dlc-3D/src/dlc_3d_bp/lp_routes.py`:
```python
from pathlib import Path
from flask import request

_USER_DATA_ROOT = "/user-data"


def _under_user_data(p: Path) -> bool:
    try:
        return str(p.resolve()).startswith(_USER_DATA_ROOT + "/")
    except Exception:
        return False


@lp_bp.route("/convert", methods=["POST"])
def convert():
    from dlc_3d_bp.lp.converter import convert_dlc_to_lp

    body = request.get_json(force=True, silent=True) or {}
    dlc = (body.get("dlc_dir") or "").strip()
    lp  = (body.get("lp_dir") or "").strip()
    force = bool(body.get("force", False))
    if not dlc or not lp:
        return jsonify({"error": "dlc_dir and lp_dir required"}), 400
    dlc_p, lp_p = Path(dlc), Path(lp)
    if not (_under_user_data(dlc_p) and _under_user_data(lp_p)):
        return jsonify({"error": "paths must resolve under /user-data/"}), 403
    try:
        summary = convert_dlc_to_lp(dlc_p, lp_p, force=force)
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(summary), 201
```

- [ ] **Step 2.3.4: Verify pass**

Run: `cd dlc-3D && python -m pytest tests/test_lp_routes.py -q`
Expected: all passed.

- [ ] **Step 2.3.5: Build Card 1 UI**

Replace `dlc-3D/src/templates/partials/card_lp_convert.html`:
```html
<section class="card dlc-theme hidden" id="lp-convert-card">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.3rem">
    <h2>Convert to Lightning-Pose Project</h2>
    <button class="btn-sm" id="btn-close-lp-convert" title="Close">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      Close
    </button>
  </div>
  <p class="subtitle">Convert the active DLC project to a multi-view Lightning-Pose layout. Source project is never modified.</p>

  <div class="lp-field">
    <label>Source DLC project</label>
    <input type="text" id="lp-convert-src" readonly>
  </div>
  <div class="lp-field">
    <label>Output LP project path</label>
    <input type="text" id="lp-convert-dst" placeholder="auto-filled when source loads">
  </div>
  <div class="lp-field lp-checkbox">
    <input type="checkbox" id="lp-convert-force">
    <label for="lp-convert-force">Overwrite if target directory is not empty</label>
  </div>

  <button class="btn-primary" id="btn-lp-convert-run">Run conversion</button>

  <pre class="lp-result" id="lp-convert-result" hidden></pre>
</section>
```

- [ ] **Step 2.3.6: Wire Card 1 in lp_cards.js**

Replace `dlc-3D/src/static/lp_cards.js`:
```javascript
// Lightning-Pose cards — Card 1 (Convert) wiring.

const $ = (sel) => document.querySelector(sel);

function activeDlcProjectPath() {
  // The main dlc-3D UI exposes the active project on a known element if any.
  // Fall back to a global hint set by the project-load flow.
  return (window.__dlc3d_active_project__ || "").trim();
}

function defaultLpDst(src) {
  if (!src) return "";
  return src.replace(/\/+$/, "") + "-LP";
}

function initConvertCard() {
  const card = $("#lp-convert-card");
  if (!card) return;
  const srcEl = $("#lp-convert-src");
  const dstEl = $("#lp-convert-dst");
  const runEl = $("#btn-lp-convert-run");
  const resEl = $("#lp-convert-result");
  const closeBtn = $("#btn-close-lp-convert");

  closeBtn?.addEventListener("click", () => card.classList.add("hidden"));

  // Sync source field with active project when card opens
  const sync = () => {
    const p = activeDlcProjectPath();
    srcEl.value = p;
    if (!dstEl.value) dstEl.value = defaultLpDst(p);
  };
  // Observe class changes to refresh fields when shown
  new MutationObserver(sync).observe(card, { attributes: true, attributeFilter: ["class"] });
  sync();

  runEl.addEventListener("click", async () => {
    runEl.disabled = true;
    resEl.hidden = false;
    resEl.textContent = "Running…";
    try {
      const r = await fetch("/dlc-3d/lp/convert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dlc_dir: srcEl.value.trim(),
          lp_dir:  dstEl.value.trim(),
          force:   $("#lp-convert-force").checked,
        }),
      });
      const body = await r.json();
      resEl.textContent = JSON.stringify(body, null, 2);
    } catch (e) {
      resEl.textContent = "Error: " + e.message;
    } finally {
      runEl.disabled = false;
    }
  });
}

initConvertCard();
```

- [ ] **Step 2.3.7: Add base styles**

Replace `dlc-3D/src/static/lp_cards.css`:
```css
.lp-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin-bottom: 0.5rem;
}
.lp-field > label {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-dim);
}
.lp-field > input[type="text"],
.lp-field > input[type="number"],
.lp-field > select {
  font-family: var(--mono);
  font-size: 0.78rem;
  padding: 0.3rem 0.5rem;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
}
.lp-field.lp-checkbox {
  flex-direction: row;
  align-items: center;
  gap: 0.4rem;
}
.lp-result {
  margin-top: 0.7rem;
  max-height: 220px;
  overflow: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0.5rem;
  font-size: 0.72rem;
  font-family: var(--mono);
  white-space: pre-wrap;
}
.btn-primary {
  background: var(--accent, #4f7ad6);
  color: white;
  border: none;
  border-radius: 4px;
  padding: 0.4rem 0.9rem;
  font-size: 0.8rem;
  cursor: pointer;
}
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
```

- [ ] **Step 2.3.8: Verify all tests pass**

Run: `cd dlc-3D && python -m pytest tests/ -q`
Expected: existing 26 tests + all new ones pass.

- [ ] **Step 2.3.9: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp_routes.py dlc-3D/src/templates/partials/card_lp_convert.html dlc-3D/src/static/lp_cards.js dlc-3D/src/static/lp_cards.css dlc-3D/tests/test_lp_routes.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): /lp/convert route + Card 1 UI (DLC→LP)"
```

---

## Phase 3 — Worker container + Celery wiring

Goal: a working `dlc-3d-worker` service that can be enqueued and reports back, with a route that surfaces job status.

### Task 3.1: requirements + Dockerfile.worker

**Files:**
- Create: `dlc-3D/requirements-lp.txt`
- Create: `dlc-3D/Dockerfile.worker`

- [ ] **Step 3.1.1: Create `requirements-lp.txt`**

`dlc-3D/requirements-lp.txt`:
```
lightning-pose
lightning-pose-app
ensemble-kalman-smoother
celery>=5.3
redis>=5.0
PyYAML>=6
```

(No exact pins — let pip resolve; if conflicts arise during the image build, pin to the last working versions and update this file in the same task.)

- [ ] **Step 3.1.2: Create Dockerfile.worker**

`dlc-3D/Dockerfile.worker`:
```dockerfile
FROM pytorch/pytorch:2.9.1-cuda13.0-cudnn9-runtime

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg git curl && rm -rf /var/lib/apt/lists/*

ARG UID=1000
ARG GID=1000
RUN groupadd -g ${GID} dlcuser && useradd -m -u ${UID} -g ${GID} dlcuser

COPY deeplabcut-webapp-docker-supports/dlc-3D/requirements-lp.txt /tmp/req-lp.txt
RUN pip install --no-cache-dir -r /tmp/req-lp.txt

WORKDIR /app
COPY --chown=dlcuser:dlcuser deeplabcut-webapp-docker-supports/dlc-3D/src/ /app/

USER dlcuser
CMD ["celery", "-A", "dlc_3d_bp.lp.celery_app", "worker", \
     "--loglevel=info", "--concurrency=1", "--pool=prefork", "-Q", "lp_3d"]
```

- [ ] **Step 3.1.3: Implement celery_app.py**

Replace `dlc-3D/src/dlc_3d_bp/lp/celery_app.py`:
```python
"""Celery application for the dlc-3d lightning-pose worker.

Separate from the main webapp's Celery instance. Consumes the 'lp_3d' queue.
"""
import os
from celery import Celery

celery = Celery(
    "dlc_3d_lp",
    broker=os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0"),
    backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0"),
    include=["dlc_3d_bp.lp.tasks"],
)

celery.conf.update(
    task_default_queue="lp_3d",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 86400},
    result_extended=True,
)
```

- [ ] **Step 3.1.4: Stub the two tasks**

Replace `dlc-3D/src/dlc_3d_bp/lp/tasks.py`:
```python
"""Celery tasks for lightning-pose training and EKS smoothing."""
from .celery_app import celery


@celery.task(bind=True, name="dlc_3d_lp.train")
def lp_train(self, model_dir: str, options: dict) -> dict:
    """Stub — implemented in Phase 5."""
    return {"status": "stub", "model_dir": model_dir, "options": options}


@celery.task(bind=True, name="dlc_3d_lp.eks")
def lp_eks(self, spec: dict) -> dict:
    """Stub — implemented in Phase 4."""
    return {"status": "stub", "spec": spec}
```

- [ ] **Step 3.1.5: Commit**

```bash
git add dlc-3D/requirements-lp.txt dlc-3D/Dockerfile.worker dlc-3D/src/dlc_3d_bp/lp/celery_app.py dlc-3D/src/dlc_3d_bp/lp/tasks.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): worker image + Celery skeleton for lp_3d queue"
```

### Task 3.2: Job status route

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp_routes.py`
- Modify: `dlc-3D/src/dlc_3d_bp/lp/job_registry.py`
- Test: `dlc-3D/tests/test_lp_job_registry.py`
- Test: `dlc-3D/tests/test_lp_routes.py`

- [ ] **Step 3.2.1: Write failing test for job_registry**

Create `dlc-3D/tests/test_lp_job_registry.py`:
```python
import fakeredis
import pytest

from dlc_3d_bp.lp import job_registry as J


@pytest.fixture
def rconn():
    return fakeredis.FakeStrictRedis(decode_responses=True)


def test_register_and_list(rconn):
    J.register(rconn, "abc123", {"type": "convert", "project": "/p"})
    J.register(rconn, "def456", {"type": "train",   "project": "/p"})
    rows = J.list_recent(rconn, limit=10)
    ids = [r["id"] for r in rows]
    assert "abc123" in ids and "def456" in ids


def test_get_one(rconn):
    J.register(rconn, "abc123", {"type": "convert", "project": "/p"})
    row = J.get(rconn, "abc123")
    assert row["type"] == "convert"
    assert row["project"] == "/p"
```

- [ ] **Step 3.2.2: Verify fail**

Run: `cd dlc-3D && python -m pytest tests/test_lp_job_registry.py -q`
Expected: ImportError / AttributeError. (Install fakeredis if missing: `pip install fakeredis`.)

- [ ] **Step 3.2.3: Implement job_registry**

Replace `dlc-3D/src/dlc_3d_bp/lp/job_registry.py`:
```python
"""Redis-backed job index for LP/EKS jobs.

Tiny: one hash per job + one sorted-set index keyed by enqueue timestamp.
Used purely for surfacing in the UI; not authoritative for Celery state.
"""
from __future__ import annotations

import json
import time

_INDEX_KEY = "dlc3d:lp:jobs"
_JOB_KEY   = "dlc3d:lp:job:{id}"
_DEFAULT_LIMIT = 50


def register(redis_conn, job_id: str, meta: dict) -> None:
    score = time.time()
    redis_conn.zadd(_INDEX_KEY, {job_id: score})
    payload = dict(meta)
    payload["id"] = job_id
    payload["created_at"] = score
    redis_conn.hset(_JOB_KEY.format(id=job_id), mapping={
        k: (v if isinstance(v, str) else json.dumps(v)) for k, v in payload.items()
    })
    # Trim index to most recent 200
    redis_conn.zremrangebyrank(_INDEX_KEY, 0, -201)


def get(redis_conn, job_id: str) -> dict | None:
    raw = redis_conn.hgetall(_JOB_KEY.format(id=job_id))
    if not raw:
        return None
    return _decode(raw)


def list_recent(redis_conn, limit: int = _DEFAULT_LIMIT) -> list[dict]:
    ids = redis_conn.zrevrange(_INDEX_KEY, 0, limit - 1)
    out = []
    for jid in ids:
        raw = redis_conn.hgetall(_JOB_KEY.format(id=jid))
        if raw:
            out.append(_decode(raw))
    return out


def _decode(raw: dict) -> dict:
    out = {}
    for k, v in raw.items():
        try:
            out[k] = json.loads(v)
        except (TypeError, json.JSONDecodeError):
            out[k] = v
    return out
```

- [ ] **Step 3.2.4: Verify pass**

Run: `cd dlc-3D && python -m pytest tests/test_lp_job_registry.py -q`
Expected: 2 passed.

- [ ] **Step 3.2.5: Write failing test for /job/<id>**

Append to `tests/test_lp_routes.py`:
```python
def test_job_status_endpoint_returns_404_for_unknown(lp_app, monkeypatch):
    # Force _redis_conn to return None so the registry lookup is skipped
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    c = lp_app.test_client()
    r = c.get("/dlc-3d/lp/job/does-not-exist")
    assert r.status_code == 404


def test_jobs_index_endpoint(lp_app, monkeypatch):
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    c = lp_app.test_client()
    r = c.get("/dlc-3d/lp/jobs")
    assert r.status_code == 200
    body = r.get_json()
    assert "jobs" in body and isinstance(body["jobs"], list)
```

- [ ] **Step 3.2.6: Verify fail**

Run: `cd dlc-3D && python -m pytest tests/test_lp_routes.py -q`
Expected: failures on new tests.

- [ ] **Step 3.2.7: Implement /job and /jobs**

Append to `dlc-3D/src/dlc_3d_bp/lp_routes.py`:
```python
def _redis_conn():
    """Return a redis client or None if redis isn't reachable."""
    try:
        import redis
        url = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0")
        c = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1.0)
        c.ping()
        return c
    except Exception:
        return None


@lp_bp.route("/job/<job_id>")
def job_status(job_id: str):
    from dlc_3d_bp.lp import job_registry
    conn = _redis_conn()
    row = job_registry.get(conn, job_id) if conn else None
    if not row:
        return jsonify({"error": "unknown job"}), 404
    # Augment with Celery AsyncResult state
    try:
        from dlc_3d_bp.lp.celery_app import celery
        ar = celery.AsyncResult(job_id)
        row["celery_state"] = ar.state
        if ar.info and isinstance(ar.info, dict):
            row["celery_info"] = ar.info
    except Exception:
        pass
    # Tail recent log lines if present
    if conn:
        log_lines = conn.lrange(f"dlc3d:lp:log:{job_id}", -200, -1)
        if log_lines:
            row["log_tail"] = log_lines
    return jsonify(row)


@lp_bp.route("/jobs")
def jobs_index():
    from dlc_3d_bp.lp import job_registry
    conn = _redis_conn()
    if not conn:
        return jsonify({"jobs": []})
    return jsonify({"jobs": job_registry.list_recent(conn, limit=50)})
```

- [ ] **Step 3.2.8: Run all tests**

Run: `cd dlc-3D && python -m pytest tests/ -q`
Expected: all pass. (`fakeredis` and `redis` packages must be installed in the test env — add them to a `tests/requirements.txt` if needed, but most Flask images already have `redis`.)

- [ ] **Step 3.2.9: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/job_registry.py dlc-3D/src/dlc_3d_bp/lp_routes.py dlc-3D/tests/test_lp_job_registry.py dlc-3D/tests/test_lp_routes.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): Redis job registry + /lp/job and /lp/jobs"
```

### Task 3.3: docker-compose service

**Files:**
- Modify: `deeplabcut-webapp-docker/docker-compose.yml`

- [ ] **Step 3.3.1: Add the service**

Locate the existing `dlc-3d` service block. Immediately after it, add:
```yaml
  # ── DLC-3D GPU Worker (lightning-pose + EKS) ────────────────────
  dlc-3d-worker:
    build:
      context: ../
      dockerfile: deeplabcut-webapp-docker-supports/dlc-3D/Dockerfile.worker
    image: dlc-3d-worker:latest
    volumes:
      - /home/sam/data-disk/Parra-Data:/user-data/Parra-Data/Disk
      - /home/sam/synology/Parra-Lab-Data:/user-data/Parra-Data/Cloud
      - /home/sam/data-mount-dir:/user-data/Martin-Data/USB
      - /home/sam/Parra-Lab-Data-NAS:/user-data/NAS-Data-Share
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src:/app
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0
      - USER_DATA_DIR=/user-data
      - NVIDIA_VISIBLE_DEVICES=all
      - NVIDIA_DRIVER_CAPABILITIES=compute,utility
    depends_on:
      redis:
        condition: service_healthy
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    restart: on-failure
```

- [ ] **Step 3.3.2: Build the worker image**

Run (from the main webapp dir):
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d-worker
```
Expected: successful image build. If pip resolves lightning-pose to a version that conflicts with PyTorch 2.9.1, pin `lightning-pose` to a known-good release in `requirements-lp.txt` and rebuild.

- [ ] **Step 3.3.3: Start the worker and verify**

```bash
docker compose up -d dlc-3d-worker
sleep 5
docker compose logs --tail=80 dlc-3d-worker | grep -E "ready|celery@.*ready"
```
Expected: a "celery@... ready" line is printed; no traceback in the tail.

- [ ] **Step 3.3.4: Verify health endpoint sees the worker**

```bash
curl -s http://localhost:5000/dlc-3d/lp/health | python3 -m json.tool
```
Expected: `"worker_reachable": true`.

- [ ] **Step 3.3.5: Commit (main webapp repo)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add docker-compose.yml
git -c commit.gpgsign=false commit -m "feat: dlc-3d-worker GPU service (lightning-pose + EKS)"
```

---

## Phase 4 — EKS Post-Hoc Smoothing (Card 3)

Goal: a working Card 3 that smooths a single CSV/H5 prediction file end-to-end via `eks` Python API.

### Task 4.1: `eks_runner` — single-view path

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/eks_runner.py`
- Test: `dlc-3D/tests/test_lp_eks.py`

- [ ] **Step 4.1.1: Write failing test**

Create `dlc-3D/tests/test_lp_eks.py`:
```python
import csv
import pytest
from pathlib import Path

eks = pytest.importorskip("eks")
from dlc_3d_bp.lp.eks_runner import smooth_single_view_csv


def _write_lp_predictions(path: Path, n_frames: int = 60) -> None:
    """Write a tiny synthetic LP-format predictions CSV (2 keypoints)."""
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scorer", "lpmodel", "lpmodel", "lpmodel", "lpmodel", "lpmodel", "lpmodel"])
        w.writerow(["bodyparts", "kp1", "kp1", "kp1", "kp2", "kp2", "kp2"])
        w.writerow(["coords", "x", "y", "likelihood", "x", "y", "likelihood"])
        for i in range(n_frames):
            w.writerow([f"img{i:08d}.png",
                        100 + i + (i % 5), 200 + i, 0.95,
                        300 - i, 150 + i, 0.9])


def test_smooth_single_view_csv(tmp_path):
    in_csv = tmp_path / "pred.csv"
    out_csv = tmp_path / "pred_eks.csv"
    _write_lp_predictions(in_csv)
    result = smooth_single_view_csv(in_csv, out_csv, s=1.0)
    assert out_csv.is_file()
    assert result["n_frames"] >= 1
```

- [ ] **Step 4.1.2: Verify fail**

Run: `cd dlc-3D && python -m pytest tests/test_lp_eks.py -q`
Expected: skip (if `eks` not installed) OR import error on `smooth_single_view_csv`.

- [ ] **Step 4.1.3: Implement**

Replace `dlc-3D/src/dlc_3d_bp/lp/eks_runner.py`:
```python
"""EKS post-hoc smoothing wrapper.

Single-view (one CSV/H5) and multi-view (per-cam CSV set) entry points.
We import `eks` lazily so the Flask container — which does not have EKS
installed — can still import this module without crashing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable


def smooth_single_view_csv(in_csv: Path | str, out_csv: Path | str, s: float = 1.0) -> dict:
    """Run single-view EKS on an LP-format predictions CSV.

    Returns {"n_frames": N, "out_path": str}.
    """
    import pandas as pd
    from eks.singleview_smoother import ensemble_kalman_smoother_single_view

    in_csv, out_csv = Path(in_csv), Path(out_csv)
    df = pd.read_csv(in_csv, header=[0, 1, 2], index_col=0)
    # eks expects a list of dataframes (ensemble); single model → list of one
    smoothed_df, _diagnostics = ensemble_kalman_smoother_single_view(
        markers_list=[df],
        keypoint_ensemble_list=None,
        smooth_param=s,
    )
    smoothed_df.to_csv(out_csv)
    return {"n_frames": int(len(smoothed_df)), "out_path": str(out_csv)}


def smooth_multiview_csvs(in_csvs: Iterable[Path | str], out_dir: Path | str, s: float = 1.0) -> dict:
    """Run multi-view EKS over per-cam predictions CSVs.

    Returns a dict with output paths.
    """
    import pandas as pd
    from eks.multiview_pca_smoother import ensemble_kalman_smoother_multi_cam

    in_csvs = [Path(c) for c in in_csvs]
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    markers = [pd.read_csv(c, header=[0, 1, 2], index_col=0) for c in in_csvs]
    smoothed_list, _ = ensemble_kalman_smoother_multi_cam(
        markers_list_cameras=[[m] for m in markers],
        keypoint_ensemble_list=None,
        smooth_param=s,
    )
    out_paths = []
    for src, sm in zip(in_csvs, smoothed_list):
        out_path = out_dir / (src.stem + "_eks.csv")
        sm.to_csv(out_path)
        out_paths.append(str(out_path))
    return {"out_paths": out_paths, "n_views": len(in_csvs)}
```

- [ ] **Step 4.1.4: Verify pass (or graceful skip)**

Run: `cd dlc-3D && python -m pytest tests/test_lp_eks.py -q`
Expected: PASS if `eks` installed on host, otherwise SKIP. Either way: no regression.

- [ ] **Step 4.1.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/eks_runner.py dlc-3D/tests/test_lp_eks.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): eks_runner — single/multi-view smoothing"
```

### Task 4.2: `lp_eks` Celery task + /lp/eks route + Card 3 UI

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/tasks.py`
- Modify: `dlc-3D/src/dlc_3d_bp/lp_routes.py`
- Modify: `dlc-3D/src/templates/partials/card_lp_eks.html`
- Modify: `dlc-3D/src/static/lp_cards.js`
- Test: `dlc-3D/tests/test_lp_routes.py`

- [ ] **Step 4.2.1: Implement the lp_eks task**

Replace the `lp_eks` stub in `dlc-3D/src/dlc_3d_bp/lp/tasks.py` (keep `lp_train` stub):
```python
"""Celery tasks for lightning-pose training and EKS smoothing."""
from pathlib import Path
from .celery_app import celery


@celery.task(bind=True, name="dlc_3d_lp.train")
def lp_train(self, model_dir: str, options: dict) -> dict:
    """Stub — implemented in Phase 5."""
    return {"status": "stub", "model_dir": model_dir, "options": options}


@celery.task(bind=True, name="dlc_3d_lp.eks")
def lp_eks(self, spec: dict) -> dict:
    """Run EKS smoothing per `spec` and return paths.

    spec keys:
      mode:        'single' | 'multi'
      in_paths:    list[str] (one for single, N for multi)
      out_dir:     str (multi mode) | out_csv: str (single)
      s:           float (smoothing parameter)
    """
    from .eks_runner import smooth_single_view_csv, smooth_multiview_csvs
    mode = spec.get("mode")
    s = float(spec.get("s", 1.0))
    if mode == "single":
        in_path  = Path(spec["in_paths"][0])
        out_csv  = Path(spec["out_csv"])
        return {"mode": "single", **smooth_single_view_csv(in_path, out_csv, s=s)}
    if mode == "multi":
        return {"mode": "multi", **smooth_multiview_csvs(spec["in_paths"], spec["out_dir"], s=s)}
    raise ValueError(f"unknown mode: {mode!r}")
```

- [ ] **Step 4.2.2: Write failing test for /lp/eks**

Append to `tests/test_lp_routes.py`:
```python
def test_eks_endpoint_validates_input(lp_app):
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/eks", json={})
    assert r.status_code == 400


def test_eks_endpoint_enqueues(lp_app, monkeypatch):
    class _FakeAsync:
        id = "fake-job-id"

    monkeypatch.setattr(
        "dlc_3d_bp.lp.tasks.lp_eks.apply_async",
        lambda *a, **k: _FakeAsync(),
    )
    monkeypatch.setattr(
        "dlc_3d_bp.lp_routes._under_user_data",
        lambda p: True,
    )
    # No-op redis to skip registration side-effects
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/eks", json={
        "mode": "single",
        "in_paths": ["/user-data/x/pred.csv"],
        "out_csv":  "/user-data/x/pred_eks.csv",
        "s": 1.0,
    })
    assert r.status_code == 202
    body = r.get_json()
    assert body["job_id"] == "fake-job-id"
```

- [ ] **Step 4.2.3: Verify fail**

Run: `cd dlc-3D && python -m pytest tests/test_lp_routes.py -q`
Expected: 404 on `/lp/eks`.

- [ ] **Step 4.2.4: Implement the route**

Append to `dlc-3D/src/dlc_3d_bp/lp_routes.py`:
```python
@lp_bp.route("/eks", methods=["POST"])
def eks_run():
    from dlc_3d_bp.lp.tasks import lp_eks
    from dlc_3d_bp.lp import job_registry

    body = request.get_json(force=True, silent=True) or {}
    mode = body.get("mode")
    in_paths = body.get("in_paths") or []
    if mode not in ("single", "multi"):
        return jsonify({"error": "mode must be 'single' or 'multi'"}), 400
    if not in_paths:
        return jsonify({"error": "in_paths required"}), 400
    for p in in_paths:
        if not _under_user_data(Path(p)):
            return jsonify({"error": f"path outside /user-data: {p}"}), 403
    if mode == "single" and not body.get("out_csv"):
        return jsonify({"error": "out_csv required for single mode"}), 400
    if mode == "multi" and not body.get("out_dir"):
        return jsonify({"error": "out_dir required for multi mode"}), 400

    async_result = lp_eks.apply_async(args=[body])
    conn = _redis_conn()
    if conn:
        from dlc_3d_bp.lp.job_registry import register
        register(conn, async_result.id, {
            "type": "eks",
            "mode": mode,
            "in_paths": in_paths,
            "out": body.get("out_csv") or body.get("out_dir"),
        })
    return jsonify({"job_id": async_result.id}), 202
```

- [ ] **Step 4.2.5: Verify pass**

Run: `cd dlc-3D && python -m pytest tests/test_lp_routes.py -q`
Expected: all pass.

- [ ] **Step 4.2.6: Build Card 3 UI**

Replace `dlc-3D/src/templates/partials/card_lp_eks.html`:
```html
<section class="card dlc-theme hidden" id="lp-eks-card">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.3rem">
    <h2>EKS Post-Hoc Smoothing</h2>
    <button class="btn-sm" id="btn-close-lp-eks" title="Close">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      Close
    </button>
  </div>
  <p class="subtitle">Smooth existing predictions (DLC h5 or LP csv) with the Ensemble Kalman Smoother.</p>

  <div class="lp-field">
    <label>Mode</label>
    <select id="lp-eks-mode">
      <option value="single">Single file (CSV)</option>
      <option value="multi">Multi-view (per-cam CSVs)</option>
    </select>
  </div>

  <div class="lp-field">
    <label>Input path(s) — comma-separated for multi-view</label>
    <input type="text" id="lp-eks-in" placeholder="/user-data/.../predictions.csv">
  </div>
  <div class="lp-field">
    <label>Output (file for single, dir for multi)</label>
    <input type="text" id="lp-eks-out" placeholder="/user-data/.../predictions_eks.csv">
  </div>
  <div class="lp-field">
    <label>Smoothing parameter (s)</label>
    <input type="number" id="lp-eks-s" value="1.0" step="0.1" min="0">
  </div>

  <button class="btn-primary" id="btn-lp-eks-run">Run EKS</button>
  <pre class="lp-result" id="lp-eks-result" hidden></pre>
</section>
```

- [ ] **Step 4.2.7: Append Card 3 wiring + polling helper to lp_cards.js**

Append to `dlc-3D/src/static/lp_cards.js`:
```javascript
async function pollJob(jobId, onUpdate, intervalMs = 1500) {
  while (true) {
    const r = await fetch(`/dlc-3d/lp/job/${jobId}`);
    if (!r.ok) {
      onUpdate({error: `job poll failed: ${r.status}`});
      return;
    }
    const body = await r.json();
    onUpdate(body);
    const state = body.celery_state || "PENDING";
    if (["SUCCESS", "FAILURE", "REVOKED"].includes(state)) return;
    await new Promise((res) => setTimeout(res, intervalMs));
  }
}

function initEksCard() {
  const card = $("#lp-eks-card");
  if (!card) return;
  const modeEl = $("#lp-eks-mode");
  const inEl   = $("#lp-eks-in");
  const outEl  = $("#lp-eks-out");
  const sEl    = $("#lp-eks-s");
  const runEl  = $("#btn-lp-eks-run");
  const resEl  = $("#lp-eks-result");

  $("#btn-close-lp-eks")?.addEventListener("click", () => card.classList.add("hidden"));

  runEl.addEventListener("click", async () => {
    runEl.disabled = true;
    resEl.hidden = false;
    resEl.textContent = "Submitting…";
    const mode = modeEl.value;
    const inPaths = inEl.value.split(",").map((s) => s.trim()).filter(Boolean);
    const payload = { mode, in_paths: inPaths, s: parseFloat(sEl.value) || 1.0 };
    if (mode === "single") payload.out_csv = outEl.value.trim();
    else                   payload.out_dir = outEl.value.trim();

    try {
      const r = await fetch("/dlc-3d/lp/eks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await r.json();
      if (!r.ok) { resEl.textContent = "Error: " + JSON.stringify(body); return; }
      const jobId = body.job_id;
      resEl.textContent = `Job ${jobId}: PENDING`;
      await pollJob(jobId, (j) => {
        resEl.textContent = JSON.stringify(j, null, 2);
      });
    } finally {
      runEl.disabled = false;
    }
  });
}

initEksCard();
```

- [ ] **Step 4.2.8: Run all tests**

Run: `cd dlc-3D && python -m pytest tests/ -q`
Expected: all pass; new EKS tests included.

- [ ] **Step 4.2.9: End-to-end smoke against running worker (optional, manual)**

Manually verify the worker can process an EKS job. Generate a small CSV inside the user-data mount, then:
```bash
curl -s -X POST http://localhost:5000/dlc-3d/lp/eks \
  -H 'Content-Type: application/json' \
  -d '{"mode":"single","in_paths":["/user-data/.../pred.csv"],"out_csv":"/user-data/.../pred_eks.csv","s":1.0}'
# Then poll:
curl -s http://localhost:5000/dlc-3d/lp/job/<id>
```
Expected: state transitions PENDING → STARTED → SUCCESS; output file exists.

- [ ] **Step 4.2.10: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/tasks.py dlc-3D/src/dlc_3d_bp/lp_routes.py dlc-3D/src/templates/partials/card_lp_eks.html dlc-3D/src/static/lp_cards.js dlc-3D/tests/test_lp_routes.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): EKS smoothing — Card 3 + /lp/eks route + Celery task"
```

---

## Phase 5 — Lightning-Pose Training (Card 2)

Goal: a working Card 2 that builds a final `config.yaml` from form inputs (with MVT + patch-masking + 3D reprojection loss flags), enqueues `lp_train`, and surfaces live status.

### Task 5.1: `train_runner` — config materialization

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/train_runner.py`
- Test: `dlc-3D/tests/test_lp_train_config.py`

- [ ] **Step 5.1.1: Write failing test**

Create `dlc-3D/tests/test_lp_train_config.py`:
```python
from pathlib import Path
import yaml
import pytest

from dlc_3d_bp.lp.train_runner import build_train_config, make_run_dir


def _base_lp_config(tmp_path: Path) -> Path:
    cfg = {
        "data": {"csv_file": ["cam0.csv", "cam1.csv"], "view_names": ["cam0", "cam1"]},
        "model": {"model_type": "multiview_heatmap", "backbone": "resnet50_animal_apose", "losses_to_use": []},
        "training": {"max_epochs": 300, "train_batch_size": 16, "imgaug_3d": False},
        "losses": {},
        "eval": {"predict_vids_after_training": False, "save_vids_after_training": False},
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return p


def test_make_run_dir(tmp_path):
    lp_project = tmp_path / "lp"; lp_project.mkdir()
    d = make_run_dir(lp_project)
    assert d.parent == lp_project / "models"
    assert d.is_dir()


def test_build_config_mvt_default(tmp_path):
    base = _base_lp_config(tmp_path)
    out = tmp_path / "out" / "config.yaml"
    out.parent.mkdir()
    build_train_config(base, out, options={
        "mvt_enabled": True,
        "patch_masking_enabled": False,
        "reproj_loss_enabled": False,
        "max_epochs": 50,
        "batch_size": 8,
    })
    cfg = yaml.safe_load(out.read_text())
    assert cfg["model"]["model_type"] == "multiview_heatmap"
    assert cfg["training"]["max_epochs"] == 50
    assert cfg["training"]["train_batch_size"] == 8
    assert "supervised_reprojection_heatmap_mse" not in cfg["losses"]


def test_build_config_patch_masking(tmp_path):
    base = _base_lp_config(tmp_path)
    out = tmp_path / "out" / "config.yaml"
    out.parent.mkdir()
    build_train_config(base, out, options={
        "mvt_enabled": True,
        "patch_masking_enabled": True,
        "patch_masking_init_epoch": 10,
        "patch_masking_final_epoch": 100,
        "patch_masking_init_ratio": 0.0,
        "patch_masking_final_ratio": 0.5,
    })
    cfg = yaml.safe_load(out.read_text())
    pm = cfg["model"]["mvt"]["patch_masking"]
    assert pm["enabled"] is True
    assert pm["init_epoch"] == 10
    assert pm["final_ratio"] == 0.5


def test_build_config_3d_reprojection_loss(tmp_path):
    base = _base_lp_config(tmp_path)
    out = tmp_path / "out" / "config.yaml"
    out.parent.mkdir()
    build_train_config(base, out, options={
        "mvt_enabled": True,
        "reproj_loss_enabled": True,
        "reproj_loss_log_weight": 3.0,
    })
    cfg = yaml.safe_load(out.read_text())
    assert cfg["training"]["imgaug_3d"] is True
    assert cfg["losses"]["supervised_reprojection_heatmap_mse"]["log_weight"] == 3.0


def test_build_config_eval_flags(tmp_path):
    base = _base_lp_config(tmp_path)
    out = tmp_path / "out" / "config.yaml"
    out.parent.mkdir()
    build_train_config(base, out, options={
        "predict_vids_after_training": True,
        "save_vids_after_training":    True,
    })
    cfg = yaml.safe_load(out.read_text())
    assert cfg["eval"]["predict_vids_after_training"] is True
    assert cfg["eval"]["save_vids_after_training"] is True
```

- [ ] **Step 5.1.2: Verify fail**

Run: `cd dlc-3D && python -m pytest tests/test_lp_train_config.py -q`
Expected: ImportError on `build_train_config` / `make_run_dir`.

- [ ] **Step 5.1.3: Implement**

Replace `dlc-3D/src/dlc_3d_bp/lp/train_runner.py`:
```python
"""Lightning-pose training wrapper.

`build_train_config` is a pure config-shaping function (no GPU, no LP imports);
`run_train_subprocess` shells out to `litpose train`. The Celery task drives
both.
"""
from __future__ import annotations

import datetime
import shlex
import subprocess
import time
from pathlib import Path

import yaml

_DEFAULT_PATCH_MASKING = {
    "enabled": False,
    "init_epoch": 5,
    "final_epoch": 50,
    "init_ratio": 0.0,
    "final_ratio": 0.5,
}


def make_run_dir(lp_project: Path | str) -> Path:
    lp_project = Path(lp_project)
    runs = lp_project / "models"
    runs.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = runs / ts
    d.mkdir()
    return d


def build_train_config(
    base_config_path: Path | str,
    out_path: Path | str,
    options: dict,
) -> None:
    """Read the LP project's base config.yaml, apply options, write to out_path."""
    base_config_path = Path(base_config_path)
    out_path = Path(out_path)
    cfg = yaml.safe_load(base_config_path.read_text()) or {}
    cfg.setdefault("data", {})
    cfg.setdefault("model", {})
    cfg.setdefault("training", {})
    cfg.setdefault("losses", {})
    cfg.setdefault("eval", {})

    # MVT toggle
    if options.get("mvt_enabled", True):
        cfg["model"]["model_type"] = "multiview_heatmap"
    elif options.get("model_type"):
        cfg["model"]["model_type"] = options["model_type"]

    if options.get("backbone"):
        cfg["model"]["backbone"] = options["backbone"]

    # Patch masking
    if options.get("patch_masking_enabled"):
        pm = dict(_DEFAULT_PATCH_MASKING)
        pm.update({
            "enabled": True,
            "init_epoch":  options.get("patch_masking_init_epoch", pm["init_epoch"]),
            "final_epoch": options.get("patch_masking_final_epoch", pm["final_epoch"]),
            "init_ratio":  options.get("patch_masking_init_ratio", pm["init_ratio"]),
            "final_ratio": options.get("patch_masking_final_ratio", pm["final_ratio"]),
        })
        cfg["model"].setdefault("mvt", {})["patch_masking"] = pm

    # 3D reprojection loss
    if options.get("reproj_loss_enabled"):
        cfg["training"]["imgaug_3d"] = True
        cfg["losses"]["supervised_reprojection_heatmap_mse"] = {
            "log_weight": options.get("reproj_loss_log_weight", 3.0),
        }

    # Training params
    for src, dst in (("max_epochs", "max_epochs"),
                     ("batch_size", "train_batch_size"),
                     ("batch_size", "val_batch_size"),
                     ("batch_size", "test_batch_size")):
        if src in options:
            cfg["training"][dst] = options[src]

    # Eval flags
    if "predict_vids_after_training" in options:
        cfg["eval"]["predict_vids_after_training"] = bool(options["predict_vids_after_training"])
    if "save_vids_after_training" in options:
        cfg["eval"]["save_vids_after_training"] = bool(options["save_vids_after_training"])

    out_path.write_text(yaml.safe_dump(cfg, sort_keys=False))


def run_train_subprocess(model_dir: Path | str, log_callback=None, cwd: Path | str | None = None) -> int:
    """Spawn `litpose train`. Return process returncode.

    log_callback: optional callable(line: str) -> None invoked once per stdout line.
    """
    model_dir = Path(model_dir)
    cfg = model_dir / "config.yaml"
    cmd = ["litpose", "train", "--config", str(cfg), "--output_dir", str(model_dir)]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, cwd=str(cwd) if cwd else None,
    )
    last_emit = time.time()
    for line in proc.stdout:  # type: ignore[union-attr]
        if log_callback:
            try:
                log_callback(line.rstrip("\n"))
            except Exception:
                pass
        if time.time() - last_emit > 5:
            last_emit = time.time()
    return proc.wait()
```

- [ ] **Step 5.1.4: Verify pass**

Run: `cd dlc-3D && python -m pytest tests/test_lp_train_config.py -q`
Expected: 5 passed.

- [ ] **Step 5.1.5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/train_runner.py dlc-3D/tests/test_lp_train_config.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): lp.train_runner — config builder + litpose subprocess"
```

### Task 5.2: `lp_train` Celery task wiring

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp/tasks.py`

- [ ] **Step 5.2.1: Implement task**

Replace the `lp_train` stub in `dlc-3D/src/dlc_3d_bp/lp/tasks.py`:
```python
@celery.task(bind=True, name="dlc_3d_lp.train")
def lp_train(self, lp_project: str, options: dict) -> dict:
    """Build the run config from `options` and run `litpose train`."""
    import os
    from pathlib import Path
    from .train_runner import build_train_config, make_run_dir, run_train_subprocess
    from .celery_app import celery as _c

    project = Path(lp_project)
    base_config = project / "config.yaml"
    if not base_config.is_file():
        raise FileNotFoundError(f"LP base config not found at {base_config}")

    run_dir = make_run_dir(project)
    run_cfg = run_dir / "config.yaml"
    build_train_config(base_config, run_cfg, options)

    # Pin GPU 0 (matches DLC convention)
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"

    log_key = f"dlc3d:lp:log:{self.request.id}"
    try:
        import redis
        rconn = redis.Redis.from_url(
            os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0"),
            decode_responses=True,
        )
    except Exception:
        rconn = None

    def emit(line: str) -> None:
        if rconn:
            rconn.rpush(log_key, line)
            rconn.ltrim(log_key, -2000, -1)
        self.update_state(state="STARTED", meta={"last_line": line, "run_dir": str(run_dir)})

    rc = run_train_subprocess(run_dir, log_callback=emit)
    if rc != 0:
        raise RuntimeError(f"litpose train exited with code {rc}")
    return {"status": "ok", "run_dir": str(run_dir)}
```

- [ ] **Step 5.2.2: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp/tasks.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): lp_train Celery task wired to train_runner"
```

### Task 5.3: /lp/train route + Card 2 UI

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/lp_routes.py`
- Modify: `dlc-3D/src/templates/partials/card_lp_train.html`
- Modify: `dlc-3D/src/static/lp_cards.js`
- Test: `dlc-3D/tests/test_lp_routes.py`

- [ ] **Step 5.3.1: Write failing test for /train**

Append to `tests/test_lp_routes.py`:
```python
def test_train_endpoint_enqueues(lp_app, monkeypatch):
    class _FakeAsync:
        id = "fake-train-id"

    monkeypatch.setattr(
        "dlc_3d_bp.lp.tasks.lp_train.apply_async",
        lambda *a, **k: _FakeAsync(),
    )
    monkeypatch.setattr(
        "dlc_3d_bp.lp_routes._under_user_data",
        lambda p: True,
    )
    monkeypatch.setattr("dlc_3d_bp.lp_routes._redis_conn", lambda: None)
    c = lp_app.test_client()
    r = c.post("/dlc-3d/lp/train", json={
        "lp_project": "/user-data/x/lp",
        "options": {"mvt_enabled": True, "reproj_loss_enabled": True},
    })
    assert r.status_code == 202
    assert r.get_json()["job_id"] == "fake-train-id"
```

- [ ] **Step 5.3.2: Verify fail**

Run: `cd dlc-3D && python -m pytest tests/test_lp_routes.py -q`
Expected: 404.

- [ ] **Step 5.3.3: Implement route**

Append to `dlc-3D/src/dlc_3d_bp/lp_routes.py`:
```python
@lp_bp.route("/train", methods=["POST"])
def train_run():
    from dlc_3d_bp.lp.tasks import lp_train

    body = request.get_json(force=True, silent=True) or {}
    project = (body.get("lp_project") or "").strip()
    options = body.get("options") or {}
    if not project:
        return jsonify({"error": "lp_project required"}), 400
    if not _under_user_data(Path(project)):
        return jsonify({"error": "lp_project must be under /user-data"}), 403

    async_result = lp_train.apply_async(args=[project, options])
    conn = _redis_conn()
    if conn:
        from dlc_3d_bp.lp.job_registry import register
        register(conn, async_result.id, {
            "type": "train",
            "lp_project": project,
            "options": options,
        })
    return jsonify({"job_id": async_result.id}), 202
```

- [ ] **Step 5.3.4: Verify pass**

Run: `cd dlc-3D && python -m pytest tests/test_lp_routes.py -q`
Expected: all pass.

- [ ] **Step 5.3.5: Build Card 2 UI**

Replace `dlc-3D/src/templates/partials/card_lp_train.html`:
```html
<section class="card dlc-theme hidden" id="lp-train-card">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.3rem">
    <h2>Train Lightning-Pose Model</h2>
    <button class="btn-sm" id="btn-close-lp-train" title="Close">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      Close
    </button>
  </div>
  <p class="subtitle">Train an LP model on the converted multi-view project. Runs on the dlc-3d-worker (GPU 0).</p>

  <div class="lp-field">
    <label>LP project path</label>
    <input type="text" id="lp-train-project" placeholder="/user-data/.../project-LP">
  </div>

  <fieldset class="lp-group">
    <legend>Multi-View Options</legend>
    <div class="lp-field lp-checkbox">
      <input type="checkbox" id="lp-train-mvt" checked>
      <label for="lp-train-mvt">Enable Multi-View Transformer (MVT)</label>
    </div>
    <div class="lp-field lp-checkbox">
      <input type="checkbox" id="lp-train-pm">
      <label for="lp-train-pm">Enable patch masking</label>
    </div>
    <div class="lp-row" id="lp-train-pm-params" style="display:none">
      <label>init epoch <input type="number" id="lp-train-pm-init-epoch" value="5" min="0"></label>
      <label>final epoch <input type="number" id="lp-train-pm-final-epoch" value="50" min="1"></label>
      <label>init ratio <input type="number" id="lp-train-pm-init-ratio" value="0" min="0" max="1" step="0.05"></label>
      <label>final ratio <input type="number" id="lp-train-pm-final-ratio" value="0.5" min="0" max="1" step="0.05"></label>
    </div>
    <div class="lp-field lp-checkbox">
      <input type="checkbox" id="lp-train-reproj">
      <label for="lp-train-reproj">Enable 3D reprojection loss (requires calibration)</label>
    </div>
    <div class="lp-row" id="lp-train-reproj-params" style="display:none">
      <label>log weight <input type="number" id="lp-train-reproj-weight" value="3.0" step="0.1"></label>
    </div>
  </fieldset>

  <fieldset class="lp-group">
    <legend>Training</legend>
    <div class="lp-row">
      <label>Max epochs <input type="number" id="lp-train-epochs" value="300" min="1"></label>
      <label>Batch size <input type="number" id="lp-train-batch" value="16" min="1"></label>
    </div>
    <div class="lp-field lp-checkbox">
      <input type="checkbox" id="lp-train-predict-vids">
      <label for="lp-train-predict-vids">Predict on training videos after training</label>
    </div>
    <div class="lp-field lp-checkbox">
      <input type="checkbox" id="lp-train-save-vids">
      <label for="lp-train-save-vids">Render labeled videos</label>
    </div>
  </fieldset>

  <button class="btn-primary" id="btn-lp-train-run">Start training</button>
  <pre class="lp-result" id="lp-train-result" hidden></pre>
</section>
```

- [ ] **Step 5.3.6: Append Card 2 wiring to lp_cards.js**

Append to `dlc-3D/src/static/lp_cards.js`:
```javascript
function initTrainCard() {
  const card = $("#lp-train-card");
  if (!card) return;
  const projectEl = $("#lp-train-project");
  const runEl = $("#btn-lp-train-run");
  const resEl = $("#lp-train-result");

  $("#btn-close-lp-train")?.addEventListener("click", () => card.classList.add("hidden"));

  $("#lp-train-pm")?.addEventListener("change", (e) => {
    $("#lp-train-pm-params").style.display = e.target.checked ? "flex" : "none";
  });
  $("#lp-train-reproj")?.addEventListener("change", (e) => {
    $("#lp-train-reproj-params").style.display = e.target.checked ? "flex" : "none";
  });

  runEl.addEventListener("click", async () => {
    runEl.disabled = true;
    resEl.hidden = false;
    resEl.textContent = "Submitting…";

    const options = {
      mvt_enabled: $("#lp-train-mvt").checked,
      patch_masking_enabled: $("#lp-train-pm").checked,
      patch_masking_init_epoch:  +$("#lp-train-pm-init-epoch").value,
      patch_masking_final_epoch: +$("#lp-train-pm-final-epoch").value,
      patch_masking_init_ratio:  +$("#lp-train-pm-init-ratio").value,
      patch_masking_final_ratio: +$("#lp-train-pm-final-ratio").value,
      reproj_loss_enabled: $("#lp-train-reproj").checked,
      reproj_loss_log_weight: +$("#lp-train-reproj-weight").value,
      max_epochs: +$("#lp-train-epochs").value,
      batch_size: +$("#lp-train-batch").value,
      predict_vids_after_training: $("#lp-train-predict-vids").checked,
      save_vids_after_training:    $("#lp-train-save-vids").checked,
    };

    try {
      const r = await fetch("/dlc-3d/lp/train", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lp_project: projectEl.value.trim(), options }),
      });
      const body = await r.json();
      if (!r.ok) { resEl.textContent = "Error: " + JSON.stringify(body); return; }
      const jobId = body.job_id;
      resEl.textContent = `Job ${jobId}: PENDING`;
      await pollJob(jobId, (j) => {
        const tail = (j.log_tail || []).slice(-30).join("\n");
        resEl.textContent =
          `state: ${j.celery_state || "PENDING"}\n` +
          `run_dir: ${j.options?.lp_project || ""}\n` +
          `--- log tail ---\n${tail}`;
      }, 2500);
    } finally {
      runEl.disabled = false;
    }
  });
}

initTrainCard();
```

- [ ] **Step 5.3.7: Add styles for fieldset/row**

Append to `dlc-3D/src/static/lp_cards.css`:
```css
.lp-group {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
  margin: 0.6rem 0;
}
.lp-group > legend {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-dim);
  padding: 0 0.3rem;
}
.lp-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin: 0.3rem 0;
}
.lp-row > label {
  font-size: 0.72rem;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.lp-row > label > input {
  width: 5rem;
  font-family: var(--mono);
  padding: 0.2rem 0.35rem;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-size: 0.75rem;
}
```

- [ ] **Step 5.3.8: Run all tests**

Run: `cd dlc-3D && python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5.3.9: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/lp_routes.py dlc-3D/src/templates/partials/card_lp_train.html dlc-3D/src/static/lp_cards.js dlc-3D/src/static/lp_cards.css dlc-3D/tests/test_lp_routes.py
git -c commit.gpgsign=false commit -m "feat(dlc-3d): /lp/train route + Card 2 UI (MVT, patch masking, 3D loss)"
```

---

## Phase 6 — Jobs Index Card (Card 4) & menu wiring

Goal: Card 4 lists recent LP/EKS jobs and links to log tails. New entries appear in the existing card-visibility menu.

### Task 6.1: Card 4 UI

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_lp_jobs.html`
- Modify: `dlc-3D/src/static/lp_cards.js`

- [ ] **Step 6.1.1: Build Card 4 markup**

Replace `dlc-3D/src/templates/partials/card_lp_jobs.html`:
```html
<section class="card dlc-theme hidden" id="lp-jobs-card">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.3rem">
    <h2>LP Jobs</h2>
    <div style="display:flex;gap:.4rem">
      <button class="btn-sm" id="btn-lp-jobs-refresh">Refresh</button>
      <button class="btn-sm" id="btn-close-lp-jobs" title="Close">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        Close
      </button>
    </div>
  </div>
  <p class="subtitle">Recent LP / EKS jobs from this Redis instance.</p>
  <table class="lp-jobs-table">
    <thead>
      <tr><th>Type</th><th>Project / Input</th><th>Created</th><th>State</th><th></th></tr>
    </thead>
    <tbody id="lp-jobs-tbody"></tbody>
  </table>
  <pre class="lp-result" id="lp-jobs-detail" hidden></pre>
</section>
```

- [ ] **Step 6.1.2: Append wiring to lp_cards.js**

Append to `dlc-3D/src/static/lp_cards.js`:
```javascript
function initJobsCard() {
  const card = $("#lp-jobs-card");
  if (!card) return;
  const tbody = $("#lp-jobs-tbody");
  const detail = $("#lp-jobs-detail");
  $("#btn-close-lp-jobs")?.addEventListener("click", () => card.classList.add("hidden"));

  async function refresh() {
    const r = await fetch("/dlc-3d/lp/jobs");
    const body = await r.json();
    tbody.innerHTML = "";
    for (const j of body.jobs || []) {
      const created = new Date((j.created_at || 0) * 1000).toLocaleString();
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${j.type || ""}</td>
        <td title="${j.lp_project || j.out || (j.in_paths || []).join(",")}">${
          (j.lp_project || j.out || (j.in_paths || [])[0] || "").split("/").slice(-2).join("/")
        }</td>
        <td>${created}</td>
        <td>${j.celery_state || "?"}</td>
        <td><button class="btn-sm" data-job="${j.id}">view</button></td>`;
      tbody.appendChild(tr);
    }
    tbody.querySelectorAll("button[data-job]").forEach((b) => {
      b.addEventListener("click", async () => {
        const r2 = await fetch(`/dlc-3d/lp/job/${b.dataset.job}`);
        detail.hidden = false;
        detail.textContent = JSON.stringify(await r2.json(), null, 2);
      });
    });
  }

  $("#btn-lp-jobs-refresh")?.addEventListener("click", refresh);
  new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.attributeName === "class" && !card.classList.contains("hidden")) refresh();
    }
  }).observe(card, { attributes: true, attributeFilter: ["class"] });
}

initJobsCard();
```

- [ ] **Step 6.1.3: Append jobs table styles**

Append to `dlc-3D/src/static/lp_cards.css`:
```css
.lp-jobs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.74rem;
  margin-top: 0.3rem;
}
.lp-jobs-table th, .lp-jobs-table td {
  text-align: left;
  padding: 0.25rem 0.4rem;
  border-bottom: 1px solid var(--border);
  font-family: var(--mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 18rem;
}
```

- [ ] **Step 6.1.4: Commit**

```bash
git add dlc-3D/src/templates/partials/card_lp_jobs.html dlc-3D/src/static/lp_cards.js dlc-3D/src/static/lp_cards.css
git -c commit.gpgsign=false commit -m "feat(dlc-3d): Card 4 — LP jobs index"
```

### Task 6.2: Add LP cards to the existing card-visibility menu

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_admin.html` (or whichever partial currently hosts the card-toggle menu — confirm by `grep` before editing)

- [ ] **Step 6.2.1: Locate the menu**

Run:
```bash
grep -n "card.*hidden\|toggle\|menu" dlc-3D/src/templates/partials/card_admin.html | head
```
Identify the markup that lists card toggles. If a different partial owns the menu, target that file instead.

- [ ] **Step 6.2.2: Add four toggles**

Mirror the existing toggle markup for one of the LP cards. Example (adjust to match the existing pattern exactly — class names, data-attributes, etc., from the surrounding entries):
```html
<button class="card-toggle" data-card="lp-convert-card">LP — Convert</button>
<button class="card-toggle" data-card="lp-train-card">LP — Train</button>
<button class="card-toggle" data-card="lp-eks-card">LP — EKS Smoothing</button>
<button class="card-toggle" data-card="lp-jobs-card">LP — Jobs</button>
```

If toggles are wired via a generic `[data-card]` click handler, no JS change is needed. If they call named functions, append a corresponding handler in `lp_cards.js`.

- [ ] **Step 6.2.3: Smoke-check in the browser**

Open `http://localhost:5000/dlc-3d/`. Verify:
- All four LP entries appear in the card-visibility menu, defaulting OFF.
- Toggling each one shows the card.
- Toggling each one's "Close" button hides it.
- No console errors, and no change to any existing card's appearance.

- [ ] **Step 6.2.4: Commit**

```bash
git add dlc-3D/src/templates/partials/card_admin.html
git -c commit.gpgsign=false commit -m "feat(dlc-3d): expose four LP cards in card-visibility menu"
```

---

## Phase 7 — Live smoke test against fixture project

Goal: end-to-end real-world verification, recorded in project memory but not gated on CI.

### Task 7.1: Run a full convert → train → EKS sweep

- [ ] **Step 7.1.1: Convert the fixture**

```bash
curl -s -X POST http://localhost:5000/dlc-3d/lp/convert \
  -H 'Content-Type: application/json' \
  -d '{
        "dlc_dir": "/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-TEST",
        "lp_dir":  "/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-TEST-LP",
        "force":   true
     }' | python3 -m json.tool
```
Expected: `n_views >= 2`, `n_frames > 0`, output dir created.

- [ ] **Step 7.1.2: Verify LP layout**

```bash
ls /home/sam/Parra-Lab-Data-NAS/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-TEST-LP/
```
Expected: `config.yaml`, `labeled-data/`, `videos/`, at least one `cam*.csv`.

- [ ] **Step 7.1.3: Kick a 1-epoch training run as a smoke test**

```bash
curl -s -X POST http://localhost:5000/dlc-3d/lp/train \
  -H 'Content-Type: application/json' \
  -d '{
        "lp_project": "/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-TEST-LP",
        "options":    {"mvt_enabled": true, "max_epochs": 1, "batch_size": 4}
     }' | python3 -m json.tool
```
Then poll `/dlc-3d/lp/job/<id>` until SUCCESS or FAILURE. Record the run dir in memory.

- [ ] **Step 7.1.4: Run EKS on the produced predictions (if any)**

If the training run produced a `predictions*.csv`, kick an EKS smooth job:
```bash
curl -s -X POST http://localhost:5000/dlc-3d/lp/eks \
  -H 'Content-Type: application/json' \
  -d '{
        "mode": "single",
        "in_paths": ["/user-data/.../predictions.csv"],
        "out_csv":  "/user-data/.../predictions_eks.csv",
        "s": 1.0
     }'
```
Expected: SUCCESS, smoothed CSV exists.

- [ ] **Step 7.1.5: Save project memory**

Record outcomes (`session memory: dlc-3d-LP smoke run YYYY-MM-DD: convert ok, train rc=N, eks rc=N, paths=...`). Mark this task done.

- [ ] **Step 7.1.6: Final commit (none expected, but if any tweaks were needed)**

```bash
git status --short
# if any minor fixes needed:
git -c commit.gpgsign=false commit -am "fix(dlc-3d): smoke-test follow-ups"
```

---

## Self-Review Notes

(Filled inline by the planner before handing off.)

1. **Spec coverage:**
   - §1 Architecture → Phase 1 + Phase 3 (compose + worker container).
   - §2.2 Convert card → Phase 2.
   - §2.3 Train card (MVT + patch masking + 3D loss) → Phase 5 (`build_train_config` tests every option in spec).
   - §2.4 EKS card → Phase 4.
   - §2.5 Jobs card → Phase 6.
   - §3 Backend modules → all created in respective phases.
   - §4 Docker → Phase 3.
   - §5 Testing → tests created throughout; fixture path referenced in Phase 2 + Phase 7.
   - §6 Error handling → covered in route validators (400/403/409 paths) and in converter warnings.
   - §7 Roll-out → mirrored phase-by-phase.

2. **Placeholder scan:** No TBD/TODO. The only deferred decision is the exact `lightning-pose` pin in `requirements-lp.txt` — the plan instructs the engineer to pin if the unpinned install fails.

3. **Type consistency:** `lp_train` task signature `(lp_project: str, options: dict)` matches the `/lp/train` route's `apply_async(args=[project, options])`. `lp_eks` task signature `(spec: dict)` matches the route's `apply_async(args=[body])`. `build_train_config(base_config_path, out_path, options)` signature matches all five test cases. `pollJob(jobId, onUpdate, intervalMs)` consistent across Card 2 and Card 3.

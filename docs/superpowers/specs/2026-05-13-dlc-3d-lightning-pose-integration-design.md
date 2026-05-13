---
name: DLC-3D Lightning-Pose Integration — Design
description: Add four UI cards to the dlc-3D module that bring lightning-pose capabilities (project conversion, MVT training, 3D-reprojection-loss training, EKS post-hoc smoothing) into the existing 3D pipeline without disturbing current DLC/Anipose flow
type: project
---

# DLC-3D Lightning-Pose Integration

**Date:** 2026-05-13
**Scope:** Add four new cards to the dlc-3D module that expose lightning-pose (LP) capabilities. The existing DLC + Anipose flow is preserved unchanged; LP features are strictly additive.

**Why now:** Lightning-pose's Multi-View Transformer, patch-masking, and 3D reprojection loss directly exploit multi-camera data — which is exactly what dlc-3D already pairs by `_camN_` naming. The same Anipose `calibration.toml` format LP expects is already produced by our pipeline. EKS is a framework-agnostic post-hoc smoother that lifts both DLC and LP predictions.

---

## 1. Architecture

### 1.1 Service topology

One new Docker service alongside the existing dlc-3D Flask container:

```
flask          (existing, unchanged)
worker         (existing, unchanged — main DLC PyTorch + Anipose)
worker-tf      (existing, unchanged — legacy TF)
dlc-3d         (existing flask blueprint, GAINS new endpoints)
dlc-3d-worker  (NEW — GPU-enabled Celery worker on queue 'lp_3d')
redis          (existing — reused as broker/backend)
```

`dlc-3d-worker` consumes a dedicated Celery queue `lp_3d`. The existing `worker` and `worker-tf` services are untouched and never see LP/EKS jobs.

### 1.2 Why a separate worker

- The main `worker` image is the DLC PyTorch image (size, lock pins). Adding lightning-pose / EKS pip pins there would force a rebuild of the largest container and risk dep conflicts with DLC.
- The dlc-3D Flask container has no GPU access and isn't intended for heavy compute.
- A dedicated worker on its own queue gives us independent rebuilds, separate concurrency settings, and clean roll-back.

The new worker uses an `on-failure` restart policy. Unlike the main `worker` (which has idle self-shutdown logic baked in), `dlc-3d-worker` stays up but holds no GPU memory between jobs — the LP subprocess only allocates VRAM during a `litpose` invocation. If idle-shutdown becomes desirable later we can port the main worker's shutdown signal handler, but it is out of scope here.

### 1.3 Code home

All new code lives inside `dlc-3D/`. The dlc-3D Flask image and the new worker image share the same source tree via Docker multi-stage / overlay copies, so a single module owns its frontend, backend routes, and Celery task implementations.

```
dlc-3D/
  Dockerfile                ← (existing) flask overlay
  Dockerfile.worker         ← NEW: pytorch + lightning-pose + eks
  requirements-lp.txt       ← NEW: lightning-pose, ensemble-kalman-smoother pins
  src/
    app.py                  ← (existing) unchanged
    dlc_3d_bp/
      routes.py             ← (existing) unchanged
      lp_routes.py          ← NEW: /dlc-3d/lp/* Flask endpoints
      lp/                   ← NEW package, no Flask imports
        __init__.py
        celery_app.py       ← Celery client (reuses redis://redis:6379/0)
        tasks.py            ← Celery task implementations
        converter.py        ← DLC → LP conversion (pure-python, runs in Flask)
        eks_runner.py       ← EKS wrapper
        train_runner.py     ← litpose train wrapper
        project_layout.py   ← LP project on-disk layout helpers
    templates/partials/
      card_lp_convert.html    ← NEW
      card_lp_train.html      ← NEW
      card_lp_eks.html        ← NEW
      card_lp_jobs.html       ← NEW (shared job status panel for LP cards)
    templates/
      dlc_3d.html             ← MODIFIED: include the four new partials
    static/
      lp_cards.js             ← NEW: card wiring + job polling
      lp_cards.css            ← NEW: card-local styling
  tests/
    test_lp_converter.py    ← NEW
    test_lp_eks.py          ← NEW
    test_lp_routes.py       ← NEW
    test_lp_train_config.py ← NEW (config-shape tests only; not GPU)
```

### 1.4 Job lifecycle

```
Browser ──POST /dlc-3d/lp/{convert,train,eks}──> Flask blueprint
                                                       │
                                          enqueue Celery task on 'lp_3d' queue
                                                       │
                                          Redis ◄── dlc-3d-worker picks up
                                                       │
                                          runs lightning-pose / eks
                                                       │
                                          writes progress to Redis (task meta)
                                                       │
Browser ──GET /dlc-3d/lp/job/<id>──> Flask polls Celery AsyncResult
```

Conversion runs synchronously inside Flask (typically < 5s); training and EKS go through Celery.

### 1.5 Data-on-disk strategy

For each DLC project the user converts, an LP sibling project is created at `<dlc_project_dir>-LP/`. Calibration `.toml` files already present in the DLC `labeled-data/<session>/` folders are aggregated into `<lp_project>/calibrations/`. The DLC project itself is **never mutated**.

LP predictions and trained model checkpoints live under `<lp_project>/models/<run_id>/`. EKS outputs land alongside the source predictions with a `_eks` suffix.

---

## 2. UI / UX

### 2.1 Card placement

The four new cards go at the end of the existing card grid in `dlc_3d.html`, after `card_admin.html`:

```html
{% include "partials/card_lp_convert.html" %}
{% include "partials/card_lp_train.html" %}
{% include "partials/card_lp_eks.html" %}
{% include "partials/card_lp_jobs.html" %}
```

They follow the same visual idiom as existing cards (close button, `dlc-theme` class, subtitle, hidden-by-default with the same toggle pattern). New entries are added to the existing card-visibility menu so users opt in.

### 2.2 Card 1 — Convert DLC → Lightning-Pose

**Purpose:** One-shot conversion of the currently active DLC project to an LP project, with multi-view structure derived from the `_camN_` filenames.

**UI elements:**
- Title: "Convert to Lightning-Pose Project"
- Read-only display of current DLC project path (mirrors active project)
- Editable output path, defaults to `<dlc_project>-LP/`
- Checkbox: "Treat sibling cams as multi-view" (default on if any `_camN_` paired sessions exist)
- Read-only summary: detected view count, session count, label CSV count, calibration files found
- "Run conversion" primary button
- Result panel: paths written, warnings (e.g., missing calibration for some sessions)

**Backend endpoint:** `POST /dlc-3d/lp/convert` (sync, returns JSON summary).

**Conversion behavior:**
- Walks `labeled-data/`, groups frames by `_camN_` → produces one folder per view in the LP project.
- Reads each `CollectedData_*.csv`, writes one CSV per view at the LP project root (`view0.csv`, `view1.csv`, …) following LP's spec (rows = frames, columns = keypoints, identical row count + names across views).
- Writes an LP `config.yaml` populated from the DLC `config.yaml` (`bodyparts`, image dims, view names).
- Copies / hard-links videos and labeled frame PNGs into the LP project (hard-links by default to save space; falls back to copy across filesystems).
- Collects all `calibration.toml` files into `<lp_project>/calibrations/` and writes a `calibrations.csv` mapping image rows → calibration file.
- Frames that have no sibling-cam labels are skipped from the LP multi-view CSVs (recorded as a warning, not an error).

### 2.3 Card 2 — Train Lightning-Pose Model

**Purpose:** Train an LP model (single-view or multi-view) on the converted LP project, with the headline options the user asked for surfaced as checkboxes.

**UI elements:**
- Title: "Train Lightning-Pose Model"
- Read-only LP project path (auto-filled from last conversion or browseable)
- Backbone select: `resnet50_animal_apose` (default), `vits_dino`, `resnet50` (these are the names LP exposes — exact list is read from a `BACKBONES` constant we maintain to avoid runtime LP imports in Flask)
- Section "Multi-View Options" (greyed out if project is single-view):
  - Checkbox: **"Enable Multi-View Transformer (MVT)"** — sets `model.model_type: multiview`
  - Checkbox: **"Enable patch masking"** — sets `model.mvt.patch_masking.enabled: true`. Numeric inputs for `init_epoch`, `final_epoch`, `init_ratio`, `final_ratio` with sensible defaults.
  - Checkbox: **"Enable 3D reprojection loss"** — sets `training.imgaug_3d: true` and `losses.supervised_reprojection_heatmap_mse.log_weight: 3.0`. Requires calibration; greyed out if `calibrations/` is empty.
- Section "Training":
  - Numeric: max epochs (default 300)
  - Numeric: batch size (default 16)
  - Checkbox: "Predict on training videos after training" → sets `eval.predict_vids_after_training: true`
  - Checkbox: "Render labeled videos" → sets `eval.save_vids_after_training: true`
- "Start training" primary button → disables itself, shows job id, polls status.

**Backend endpoint:** `POST /dlc-3d/lp/train` — enqueues `lp_train` Celery task, returns `{job_id}`.

**Task behavior (`lp_train`):**
1. Reads the user options, materializes a final `config.yaml` in a fresh `<lp_project>/models/<timestamp>/` subdir.
2. Shells to `litpose train --config <model_dir>/config.yaml --output_dir <model_dir>` inside the worker (the worker has `litpose` on PATH via pip).
3. Streams stdout/stderr to Redis under the task id so the UI can show a live tail.
4. On success: marks task SUCCESS and stores the model dir; on failure: marks FAILURE with stderr captured.
5. **GPU pinning:** the task injects `CUDA_VISIBLE_DEVICES=0` into the subprocess env to match the project convention (RTX 5090 for DLC-class work).

**Why subprocess litpose vs. python API:** LP imports drag in PyTorch and many heavy modules — a subprocess gives us clean lifecycle, log capture, and survives Celery worker recycles without polluting the worker import space.

### 2.4 Card 3 — EKS Post-Hoc Smoothing

**Purpose:** Smooth existing predictions (DLC `.h5`, LP `predictions*.csv`, or per-view prediction sets) using the Ensemble Kalman Smoother.

**UI elements:**
- Title: "EKS Post-Hoc Smoothing"
- Source picker:
  - Mode A: "Smooth a single prediction file" — file picker bound to the existing `/dlc-3d/browse` route, filtered to `.h5` and `.csv`.
  - Mode B: "Smooth a multi-view set" — pick a directory holding `predictions_view*.csv` (LP) or per-cam `*.h5` (DLC paired by `_camN_`).
- Output dir display (defaults to alongside source with `_eks` suffix; editable)
- Smoothing-strength numeric (`s` parameter, default 1.0)
- Optional checkbox: "Use camera calibration for 3D smoothing" (only enabled when a calibration TOML is detectable — uses `eks.multicam_smoother` with calibration)
- "Run EKS" primary button → enqueues task and polls.

**Backend endpoint:** `POST /dlc-3d/lp/eks` — enqueues `lp_eks` Celery task.

**Task behavior (`lp_eks`):**
1. Routes to single-view, multi-view, or multi-view-calibrated EKS based on inputs.
2. Uses `eks` Python API (it's light enough to import in-process).
3. Writes smoothed predictions next to source with `_eks.csv` / `_eks.h5` suffix and emits an EKS run summary JSON.

### 2.5 Card 4 — LP Jobs status panel

A unified card that lists all in-flight and recent LP/EKS jobs from this browser session, sourced from a localStorage-backed job registry plus a `GET /dlc-3d/lp/jobs` index. Each row: job type, target project, start time, status badge, link to log tail. This keeps the train and EKS cards uncluttered.

### 2.6 No effect on existing UX

- None of the existing cards' DOM, ids, classes, or routes change.
- No existing JS module is modified — the four new cards live in `lp_cards.js` and only listen on their own elements.
- No existing route is renamed.
- The card-visibility menu gains four entries, defaulting to hidden so first-time users see no change to their workspace.

---

## 3. Backend modules

### 3.1 `lp/converter.py`

Pure-python (no Celery, no LP imports). Reads a DLC project dir, writes an LP project dir. Steps in detail:

```
1. Validate inputs (dlc_dir has config.yaml; lp_dir doesn't already exist OR is empty unless --force).
2. Scan labeled-data/ for CollectedData_*.csv per session.
3. Group sessions by _camN_ stem → derive view_names = ['cam0', 'cam1', ...].
4. Build per-view CSVs:
     a. For each labeled session, find frames present in ALL cams (intersection by frame number).
     b. Emit one row per matched frame in each view CSV with identical relative-path order.
5. Copy / hard-link the matched PNG frames to lp_dir/<labeled_dir>/sessionN_viewK/imgXXXXXX.png.
6. Copy / hard-link associated videos into lp_dir/videos/ with view-suffixed names.
7. Collect every calibration.toml present under labeled-data/* into lp_dir/calibrations/<session>.toml.
8. Write lp_dir/calibrations.csv mapping each image row → its session's calibration file.
9. Write lp_dir/config.yaml.
10. Return a summary dict (counts + warnings).
```

This is a substantial chunk of code (~400 lines) but it is self-contained, easy to test with a fixture project, and runs in the Flask container without any GPU.

### 3.2 `lp/celery_app.py`

```python
import os
from celery import Celery

celery = Celery(
    "dlc_3d_lp",
    broker=os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0"),
    backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0"),
)
celery.conf.update(
    task_default_queue="lp_3d",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 86400},
)
```

Separate `Celery()` instance, separate queue — no overlap with the main webapp's `celery_app.py`.

### 3.3 `lp/tasks.py`

Two tasks:

- `lp_train(model_dir: str, options: dict) -> dict` — materializes `config.yaml` from `options`, subprocesses `litpose train`, streams logs into Redis at `dlc3d:lp:log:<task_id>` (line-appended list with a cap).
- `lp_eks(spec: dict) -> dict` — runs EKS via its Python API; writes smoothed outputs.

Both tasks update `self.update_state(meta={...})` periodically so the Flask polling endpoint can surface progress.

### 3.4 `lp_routes.py`

New blueprint endpoints, all under `/dlc-3d/lp/`:

| Method | Path                          | Purpose                                  |
|--------|-------------------------------|------------------------------------------|
| GET    | `/dlc-3d/lp/health`           | sanity check that worker is reachable    |
| POST   | `/dlc-3d/lp/convert`          | run conversion (sync)                    |
| POST   | `/dlc-3d/lp/train`            | enqueue training, return job id          |
| POST   | `/dlc-3d/lp/eks`              | enqueue EKS, return job id               |
| GET    | `/dlc-3d/lp/job/<id>`         | status + meta + last log lines           |
| POST   | `/dlc-3d/lp/job/<id>/cancel`  | revoke task, kill subprocess             |
| GET    | `/dlc-3d/lp/jobs`             | recent jobs index (Redis-backed)         |
| GET    | `/dlc-3d/lp/projects`         | list known LP project dirs near user data|

All endpoints reuse the existing `_USER_DATA_ROOT` guard for path security.

---

## 4. Docker

### 4.1 New worker image (`dlc-3D/Dockerfile.worker`)

```dockerfile
FROM pytorch/pytorch:2.9.1-cuda13.0-cudnn9-runtime

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg git && rm -rf /var/lib/apt/lists/*

ARG UID=1000
ARG GID=1000
RUN groupadd -g ${GID} dlcuser && useradd -m -u ${UID} -g ${GID} dlcuser

# Install lightning-pose + EKS into a separate venv to keep base torch clean
COPY deeplabcut-webapp-docker-supports/dlc-3D/requirements-lp.txt /tmp/req-lp.txt
RUN pip install --no-cache-dir -r /tmp/req-lp.txt

WORKDIR /app
COPY --chown=dlcuser:dlcuser deeplabcut-webapp-docker-supports/dlc-3D/src/ /app/

USER dlcuser
CMD ["celery", "-A", "dlc_3d_bp.lp.celery_app", "worker", \
     "--loglevel=info", "--concurrency=1", "--pool=prefork", "-Q", "lp_3d"]
```

Build context: `../` (same as the existing dlc-3D Dockerfile) so we can reach into both repos if needed.

`requirements-lp.txt`:
```
lightning-pose>=1.7
ensemble-kalman-smoother>=2.0
celery>=5.3
redis>=5.0
```

(Exact pins resolved during phase 1 implementation.)

### 4.2 Compose change (main webapp `docker-compose.yml`)

Add one service to `deeplabcut-webapp-docker/docker-compose.yml`. The existing `dlc-3d` service stays as-is.

```yaml
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

This is the only main-webapp change. The existing `flask`, `worker`, `worker-tf`, `dlc-3d`, and `redis` services are not modified.

---

## 5. Testing

A copy of the live DLC project (excluding `dlc-models-pytorch/` and `training-datasets/`) is provisioned at:

```
/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP-TEST
```

This fixture project is used by the integration tests below. It is referenced by absolute path; tests that need it skip themselves with a clear message when the path is missing (so CI on a fresh machine still works).

### 5.1 Test categories

| File | Scope |
|------|-------|
| `tests/test_lp_converter.py` | Run converter against the fixture project; assert layout, CSV row consistency across views, calibration aggregation, no-mutation of source. |
| `tests/test_lp_routes.py` | Flask test client: hits `/dlc-3d/lp/health`, `/convert`, `/train` (mocking the Celery `delay()` call), `/job/<id>`, `/jobs`. |
| `tests/test_lp_eks.py` | Generate a tiny synthetic per-cam CSV pair, run `eks_runner` end-to-end, assert smoothed output exists and column count matches. Skip if `eks` not importable. |
| `tests/test_lp_train_config.py` | Pure-python: feed the train route various option dicts, assert the materialized `config.yaml` has the expected keys (MVT on/off, patch-masking, 3D-reproj-loss, eval flags). No actual training. |

Existing `tests/test_core.py` (26 tests) is untouched and remains the regression net for the existing dlc-3D behavior.

### 5.2 How tests run

```bash
# In the dlc-3D image (flask overlay), no GPU needed for these:
docker compose run --rm dlc-3d pytest -q

# Or for converter / EKS without docker (host venv with light deps):
cd deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q
```

Tests must pass before each commit per the per-phase commit policy (§7).

---

## 6. Error handling

- **Calibration missing for a session:** converter skips that session's multi-view rows and emits a warning in the response; UI shows the warning list.
- **No paired sibling for a labeled frame:** that frame is skipped (recorded in warnings).
- **`litpose` not found in worker:** training task fails fast with a clear "lightning-pose not installed in worker" error, logged to Redis.
- **GPU OOM during training:** subprocess returns non-zero; task marks FAILURE; UI shows stderr tail. User option in UI to retry with smaller batch.
- **EKS on a single prediction file with no cam pair:** runs single-view EKS, no error.
- **Path outside `/user-data`:** 403 from the route guards, matching existing dlc-3D behavior.
- **Concurrent train requests on same project:** the train route returns 409 if a job with status PENDING/STARTED already exists for that model dir.

---

## 7. Roll-out / commit policy

Per the user's "commit as you go" instruction, work is broken into phases each ending in a passing test run and a commit:

1. **Spec + writing-plans output** (this doc + the implementation plan).
2. **Scaffold + plumbing:** new files, blueprint registration, empty templates, no behavior. Tests for blueprint registration. Commit.
3. **Converter (Card 1) + tests against fixture project.** Commit.
4. **Worker container + Celery skeleton:** `Dockerfile.worker`, `celery_app.py`, `lp_eks` task stub returning a deterministic value, route + UI for EKS using the stub. Commit.
5. **EKS task implementation + tests.** Commit.
6. **Train task (subprocess + log streaming) + UI for Card 2 + config-shape tests.** Commit. (Actual training is verified manually against the fixture project but not in CI.)
7. **Jobs index card + polish.** Commit.

A live training smoke test is performed against the test project at the end of phase 6 and recorded in the project memory (path, command, outcome) but is not gated on CI.

---

## 8. Out of scope

- Replacing DLC with LP anywhere in the existing pipeline.
- Modifying the main webapp's `worker` or `worker-tf` containers.
- Inference on new (unlabeled) videos outside the LP project — covered by the existing `eval.predict_vids_after_training` LP option for now.
- Triangulating LP predictions back through Anipose — possible follow-up once LP outputs are validated against DLC.
- A LP-native labeling GUI (LP ships its own, but we already have a labeler).
- Distributed / multi-GPU training.

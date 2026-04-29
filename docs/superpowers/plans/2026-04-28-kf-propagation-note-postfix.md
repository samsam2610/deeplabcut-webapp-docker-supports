# KF Propagation + Note→Postfix Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two features to the clip-cutter extract panel: (1) optional automatic re-scan of pending forward candidates when the user sets a new keyframe, using a large batched DINOv2 embed on CUDA:1; (2) drag-and-drop mapping from CSV note chips to quicktag bubbles that auto-populates the postfix field for candidates.

**Architecture:** Feature 1 adds a `rescan_forward_candidates` function to `processor.py` (parallel frame prefetch + single large-batch DINOv2 embed on CUDA:1), three new routes in `routes.py` (start/stream/cancel), and client-side SSE handling in `enhanced_player.js`. Feature 2 is entirely client-side: localStorage mappings, a note palette rendered from `_epNoteColorMap`, drag-and-drop onto existing quicktag pills, and a scan over `_csvRows` per candidate window.

**Tech Stack:** Python/Flask (backend), vanilla JS (frontend), DINOv2 via `torch.hub` (embedding), SSE for streaming, HTML5 Drag and Drop API.

---

## File Map

| File | Role |
|------|------|
| `clip-cutter/processor.py` | Add `_dino_model_cuda1` singleton, `embed_frames_cuda1_batch`, `rescan_forward_candidates` |
| `clip-cutter/routes.py` | Add `_rescan_jobs` dict, `_run_rescan_forward` worker, 3 new routes |
| `clip-cutter/templates/clip_cutter.html` | Add propagate checkbox row, rescan progress row, note palette section, CSS |
| `clip-cutter/static/enhanced_player.js` | Add rescan state + `_epStartRescan` + `_epApplyRescanKF`; note mapping helpers + `_epRenderNotePalette`; drag-drop handlers; `_epAutoPopulatePostfixes` |
| `clip-cutter/static/clip_cutter.js` | Add `ep-conflict-badge` span to `buildResultCard`; call `_epAutoPopulatePostfixes` after `renderDetections` |
| `clip-cutter/tests/test_processor.py` | Tests for `rescan_forward_candidates` |
| `clip-cutter/tests/test_routes.py` | Tests for new rescan routes |

---

## Task 1: `rescan_forward_candidates` in processor.py

**Files:**
- Modify: `clip-cutter/processor.py`
- Test: `clip-cutter/tests/test_processor.py`

- [ ] **Step 1: Write the failing tests**

Add to `clip-cutter/tests/test_processor.py`:

```python
import threading


@pytest.fixture
def mock_dino_cuda1(monkeypatch):
    """Replace the CUDA:1 DINOv2 singleton with a deterministic fake."""
    import processor
    import numpy as np

    class FakeDinoModel:
        def __call__(self, tensors):
            import torch
            N = tensors.shape[0]
            rng = np.random.default_rng(0)
            arr = rng.random((N, 1024)).astype(np.float32)
            norms = np.linalg.norm(arr, axis=1, keepdims=True).clip(min=1e-8)
            arr = arr / norms
            return torch.tensor(arr)

        def parameters(self):
            import torch
            yield torch.tensor([0.0])  # device = cpu

        def to(self, device):
            return self

    import torchvision.transforms as T
    fake_transform = T.Compose([T.Resize(8), T.CenterCrop(8), T.ToTensor()])
    monkeypatch.setattr(processor, "_dino_model_cuda1", FakeDinoModel())
    monkeypatch.setattr(processor, "_dino_transform_cuda1", fake_transform)
    return FakeDinoModel()


def test_rescan_forward_candidates_returns_results(mock_dino_cuda1, tiny_video):
    """Returns one result per candidate with valid frame_number and similarity."""
    import processor
    import numpy as np

    template_state = {
        "dino_mean_embedding": np.ones(1024, dtype=np.float32).tolist(),
        "mean_embedding": None,
        "frames": [],
    }
    candidates = [
        {"idx": 3, "frame_number": 20},
        {"idx": 4, "frame_number": 30},
    ]
    results = processor.rescan_forward_candidates(
        video_path=str(tiny_video),
        candidates=candidates,
        fine_window=5,
        template_state=template_state,
    )
    assert len(results) == 2
    for r in results:
        assert "idx" in r
        assert "new_frame_number" in r
        assert "similarity" in r
        assert isinstance(r["new_frame_number"], int)
        assert r["new_frame_number"] >= 1
        assert 0.0 <= r["similarity"] <= 1.0


def test_rescan_forward_candidates_respects_cancel(mock_dino_cuda1, tiny_video):
    """Cancel event set before processing causes empty result."""
    import processor
    import numpy as np

    template_state = {
        "dino_mean_embedding": np.ones(1024, dtype=np.float32).tolist(),
        "mean_embedding": None,
        "frames": [],
    }
    candidates = [{"idx": 3, "frame_number": 20}]
    cancel_ev = threading.Event()
    cancel_ev.set()  # set before call
    results = processor.rescan_forward_candidates(
        video_path=str(tiny_video),
        candidates=candidates,
        fine_window=5,
        template_state=template_state,
        cancel_event=cancel_ev,
    )
    assert results == []


def test_rescan_forward_candidates_empty_template(mock_dino_cuda1, tiny_video):
    """Returns empty list when template has no mean embedding."""
    import processor

    template_state = {"dino_mean_embedding": None, "mean_embedding": None, "frames": []}
    candidates = [{"idx": 0, "frame_number": 10}]
    results = processor.rescan_forward_candidates(
        video_path=str(tiny_video),
        candidates=candidates,
        fine_window=5,
        template_state=template_state,
    )
    assert results == []


def test_rescan_forward_candidates_idx_preserved(mock_dino_cuda1, tiny_video):
    """Result idx values match the input candidate idx values."""
    import processor
    import numpy as np

    template_state = {
        "dino_mean_embedding": np.ones(1024, dtype=np.float32).tolist(),
        "mean_embedding": None,
        "frames": [],
    }
    candidates = [{"idx": 7, "frame_number": 15}, {"idx": 12, "frame_number": 25}]
    results = processor.rescan_forward_candidates(
        video_path=str(tiny_video),
        candidates=candidates,
        fine_window=3,
        template_state=template_state,
    )
    result_idxs = [r["idx"] for r in results]
    assert 7 in result_idxs
    assert 12 in result_idxs
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_processor.py::test_rescan_forward_candidates_returns_results -v
```

Expected: `FAILED` with `AttributeError: module 'processor' has no attribute 'rescan_forward_candidates'`

- [ ] **Step 3: Add CUDA:1 model singleton to processor.py**

After the existing `_dino_model_lock = threading.Lock()` block (around line 33), add:

```python
_dino_model_cuda1 = None
_dino_transform_cuda1 = None
_dino_model_cuda1_lock = threading.Lock()


def _get_dino_model_cuda1():
    global _dino_model_cuda1, _dino_transform_cuda1
    if _dino_model_cuda1 is None:
        with _dino_model_cuda1_lock:
            if _dino_model_cuda1 is None:
                import torch
                import torchvision.transforms as T
                n = torch.cuda.device_count()
                device = torch.device("cuda:1" if n > 1 else ("cuda:0" if n > 0 else "cpu"))
                model = torch.hub.load(
                    "facebookresearch/dinov2", config.DINO_MODEL_NAME, pretrained=True
                )
                model.eval()
                model = model.to(device)
                _dino_transform_cuda1 = T.Compose([
                    T.Resize(224, interpolation=T.InterpolationMode.BICUBIC),
                    T.CenterCrop(224),
                    T.ToTensor(),
                    T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
                ])
                _dino_model_cuda1 = model
    return _dino_model_cuda1, _dino_transform_cuda1
```

- [ ] **Step 4: Add `embed_frames_cuda1_batch` to processor.py**

After `_get_dino_model_cuda1`, add:

```python
def embed_frames_cuda1_batch(frames: list, batch_size: int = 256) -> np.ndarray:
    """Embed BGR numpy frames with DINOv2 on CUDA:1. Returns L2-normalised (N, 1024) float32."""
    import torch
    model, transform = _get_dino_model_cuda1()
    device = next(model.parameters()).device
    all_embs: list = []
    for i in range(0, len(frames), batch_size):
        batch = frames[i:i + batch_size]
        tensors = torch.stack([
            transform(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)))
            for f in batch
        ]).to(device)
        with torch.no_grad():
            feats = model(tensors)
        feats = feats.cpu().float().numpy()
        norms = np.linalg.norm(feats, axis=1, keepdims=True).clip(min=1e-8)
        all_embs.append(feats / norms)
    return np.concatenate(all_embs, axis=0)
```

- [ ] **Step 5: Add `rescan_forward_candidates` to processor.py**

After `embed_frames_cuda1_batch`, add:

```python
def rescan_forward_candidates(
    video_path: "str | Path",
    candidates: list,
    fine_window: int,
    template_state: dict,
    n_prefetch_threads: int = 12,
    cancel_event: "threading.Event | None" = None,
) -> list:
    """Re-run fine scan for candidates using updated template.

    candidates: list of {idx, frame_number} where frame_number is 1-based.
    Returns list of {idx, new_frame_number, similarity}.
    """
    from concurrent.futures import ThreadPoolExecutor

    mean_emb = template_state.get("dino_mean_embedding") or template_state.get("mean_embedding")
    if mean_emb is None:
        return []
    mean_emb = np.asarray(mean_emb, dtype=np.float32)
    norm = np.linalg.norm(mean_emb)
    if norm > 0:
        mean_emb = mean_emb / norm

    # Build per-candidate windows of 0-based frame indices
    windows = []
    for cand in candidates:
        kf0 = cand["frame_number"] - 1
        lo = max(0, kf0 - fine_window)
        hi = kf0 + fine_window
        windows.append((cand, list(range(lo, hi + 1))))

    all_tasks = [(ci, f0) for ci, (_, flist) in enumerate(windows) for f0 in flist]

    if cancel_event and cancel_event.is_set():
        return []

    # Parallel frame prefetch (I/O bound)
    frame_store: dict = {}

    def _read(task):
        ci, f0 = task
        return ci, f0, read_frame(str(video_path), f0)

    with ThreadPoolExecutor(max_workers=n_prefetch_threads) as pool:
        for ci, f0, frame in pool.map(_read, all_tasks):
            if frame is not None:
                frame_store[(ci, f0)] = frame

    if cancel_event and cancel_event.is_set():
        return []

    # Build ordered list for batch embed
    ordered_frames: list = []
    slice_map: list = []  # (ci, f0)
    for ci, (_, flist) in enumerate(windows):
        for f0 in flist:
            frame = frame_store.get((ci, f0))
            if frame is not None:
                slice_map.append((ci, f0))
                ordered_frames.append(frame)

    if not ordered_frames:
        return []

    # Single large batch embed — saturates CUDA:1
    embs = embed_frames_cuda1_batch(ordered_frames, batch_size=len(ordered_frames))

    if cancel_event and cancel_event.is_set():
        return []

    # Group back per candidate
    ci_to_pairs: dict = {}
    for local_i, (ci, f0) in enumerate(slice_map):
        ci_to_pairs.setdefault(ci, []).append((f0, embs[local_i]))

    results = []
    for ci, (cand, _) in enumerate(windows):
        if cancel_event and cancel_event.is_set():
            break
        pairs = ci_to_pairs.get(ci, [])
        if not pairs:
            continue
        fs, vecs = zip(*pairs)
        sims = np.array([float(np.dot(mean_emb, v)) for v in vecs])
        best = int(np.argmax(sims))
        results.append({
            "idx": cand["idx"],
            "new_frame_number": fs[best] + 1,
            "similarity": float(sims[best]),
        })

    return results
```

- [ ] **Step 6: Run all four tests to confirm they pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_processor.py::test_rescan_forward_candidates_returns_results tests/test_processor.py::test_rescan_forward_candidates_respects_cancel tests/test_processor.py::test_rescan_forward_candidates_empty_template tests/test_processor.py::test_rescan_forward_candidates_idx_preserved -v
```

Expected: 4 PASSED

- [ ] **Step 7: Run full test suite to check for regressions**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/ -v
```

Expected: all previously passing tests still PASS

- [ ] **Step 8: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/processor.py clip-cutter/tests/test_processor.py
git commit -m "feat: add rescan_forward_candidates with CUDA:1 batch embed"
```

---

## Task 2: Rescan-forward routes in routes.py

**Files:**
- Modify: `clip-cutter/routes.py`
- Test: `clip-cutter/tests/test_routes.py`

- [ ] **Step 1: Write the failing tests**

Add to `clip-cutter/tests/test_routes.py` (find the existing test file and append):

```python
# ── Rescan-forward routes ─────────────────────────────────────────────────────

def test_rescan_forward_missing_params(client):
    """Returns 400 when video_path or candidates is missing."""
    resp = client.post("/clip-cutter/rescan-forward",
                       json={"video_path": "/some/video.avi"})
    assert resp.status_code == 400

    resp2 = client.post("/clip-cutter/rescan-forward",
                        json={"candidates": [{"idx": 0, "frame_number": 10}]})
    assert resp2.status_code == 400


def test_rescan_forward_returns_job_id(client, monkeypatch, tiny_video):
    """POST returns a job_id string."""
    import routes
    monkeypatch.setattr(routes, "_state", {
        "frames": [],
        "mean_embedding": None,
        "dino_mean_embedding": [1.0] * 1024,
        "video_stem": "test",
        "video_parent": str(tiny_video.parent),
        "sibling_video_path": None,
    })
    # Patch processor so the worker doesn't actually run DINOv2
    import processor
    monkeypatch.setattr(processor, "rescan_forward_candidates", lambda **kw: [])

    resp = client.post("/clip-cutter/rescan-forward", json={
        "video_path": str(tiny_video),
        "candidates": [{"idx": 3, "frame_number": 20}],
        "params": {"fine_window": 5},
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert "job_id" in data
    assert isinstance(data["job_id"], str)


def test_rescan_forward_stream_unknown_job(client):
    """Stream endpoint returns 404 for unknown job_id."""
    resp = client.get("/clip-cutter/rescan-forward/stream?job_id=nonexistent")
    assert resp.status_code == 404


def test_rescan_forward_cancel_unknown_job(client):
    """Cancel endpoint returns 404 for unknown job_id."""
    resp = client.post("/clip-cutter/rescan-forward/nonexistent/cancel")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_routes.py::test_rescan_forward_missing_params -v
```

Expected: `FAILED` — route does not exist yet

- [ ] **Step 3: Add job dict and worker thread to routes.py**

Near the top of `routes.py`, after the existing `_scan_jobs` declaration, add:

```python
_rescan_jobs: dict[str, dict] = {}
_rescan_jobs_lock = threading.Lock()
```

Then add the worker function (before the first `@bp.route` decorator for the new routes):

```python
def _run_rescan_forward(job_id: str, video_path: str, candidates: list,
                        fine_window: int, template_state: dict) -> None:
    cancel_ev = threading.Event()
    with _rescan_jobs_lock:
        _rescan_jobs[job_id]["cancel_event"] = cancel_ev

    try:
        results = processor.rescan_forward_candidates(
            video_path=video_path,
            candidates=candidates,
            fine_window=fine_window,
            template_state=template_state,
            cancel_event=cancel_ev,
        )
        with _rescan_jobs_lock:
            if cancel_ev.is_set():
                _rescan_jobs[job_id]["phase"] = "cancelled"
            else:
                _rescan_jobs[job_id]["results"].extend(results)
                _rescan_jobs[job_id]["phase"] = "done"
    except Exception as exc:
        logging.exception("rescan_forward error")
        with _rescan_jobs_lock:
            _rescan_jobs[job_id]["phase"] = "error"
            _rescan_jobs[job_id]["error"] = str(exc)
```

- [ ] **Step 4: Add the three route handlers to routes.py**

After the `_run_rescan_forward` function, add:

```python
@bp.route("/rescan-forward", methods=["POST"])
def start_rescan_forward():
    body = request.get_json(force=True) or {}
    video_path = body.get("video_path")
    candidates = body.get("candidates", [])
    if not video_path or not candidates:
        return jsonify({"error": "video_path and candidates required"}), 400

    params = body.get("params", {})
    fine_window = int(params.get("fine_window", config.FINE_SCAN_WINDOW))

    with _state_lock:
        template_state = {
            "frames": list(_state["frames"]),
            "mean_embedding": _state.get("mean_embedding"),
            "dino_mean_embedding": _state.get("dino_mean_embedding"),
        }

    job_id = str(uuid.uuid4())
    with _rescan_jobs_lock:
        _rescan_jobs[job_id] = {
            "phase": "running",
            "results": [],
            "total": len(candidates),
            "error": None,
            "cancel_event": None,
        }

    threading.Thread(
        target=_run_rescan_forward,
        args=(job_id, video_path, candidates, fine_window, template_state),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})


@bp.route("/rescan-forward/stream")
def rescan_forward_stream():
    job_id = request.args.get("job_id")
    with _rescan_jobs_lock:
        if not job_id or job_id not in _rescan_jobs:
            return jsonify({"error": "unknown job_id"}), 404

    def generate():
        sent = 0
        while True:
            with _rescan_jobs_lock:
                job = _rescan_jobs[job_id]
                new_results = job["results"][sent:]
                phase = job["phase"]
            for r in new_results:
                yield f"data: {json.dumps(r)}\n\n"
                sent += 1
            if phase in ("done", "error", "cancelled"):
                yield f"data: {json.dumps({'phase': phase, 'error': job.get('error')})}\n\n"
                break
            time.sleep(0.3)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@bp.route("/rescan-forward/<job_id>/cancel", methods=["POST"])
def cancel_rescan_forward(job_id: str):
    with _rescan_jobs_lock:
        if job_id not in _rescan_jobs:
            return jsonify({"error": "unknown job_id"}), 404
        ev = _rescan_jobs[job_id].get("cancel_event")
        _rescan_jobs[job_id]["phase"] = "cancelled"
    if ev:
        ev.set()
    return jsonify({"ok": True})
```

- [ ] **Step 5: Run the route tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_routes.py::test_rescan_forward_missing_params tests/test_routes.py::test_rescan_forward_returns_job_id tests/test_routes.py::test_rescan_forward_stream_unknown_job tests/test_routes.py::test_rescan_forward_cancel_unknown_job -v
```

Expected: 4 PASSED

- [ ] **Step 6: Run full test suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat: add rescan-forward routes (start/stream/cancel)"
```

---

## Task 3: HTML/CSS — propagate checkbox, rescan progress, note palette

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html`

- [ ] **Step 1: Locate the extract panel in clip_cutter.html**

Open `clip-cutter/templates/clip_cutter.html` and search for `ep-warning`. The extract panel section is nearby. Also find `ep-postfix-tags` (the existing quicktag container).

- [ ] **Step 2: Add propagate checkbox and rescan progress rows**

Directly after the `<div id="ep-warning" ...>` element (which is the overlap warning), insert:

```html
<!-- Propagate KF — shown in clip mode only -->
<div id="ep-propagate-row" style="display:none;align-items:center;gap:6px;padding:3px 4px;margin-bottom:2px;">
  <input type="checkbox" id="ep-propagate-kf" checked style="accent-color:#388bfd;cursor:pointer;flex-shrink:0;">
  <label for="ep-propagate-kf" style="font-size:10px;color:#adbac7;cursor:pointer;flex:1;">↻ Propagate KF</label>
</div>
<!-- Rescan progress (hidden until a rescan job is running) -->
<div id="ep-rescan-progress" style="display:none;align-items:center;gap:6px;padding:3px 6px;background:#1e2d1e;border:1px solid #2e5a2e;border-radius:3px;font-size:9px;color:#3fb950;margin-bottom:2px;">
  <span id="ep-rescan-text">↻ Rescanning…</span>
  <span id="ep-rescan-count" style="margin-left:4px;color:#56d364;"></span>
  <button id="ep-rescan-cancel" class="player-btn" style="margin-left:auto;font-size:8px;">✕</button>
</div>
```

- [ ] **Step 3: Add note palette section**

Directly after `<div id="ep-postfix-tags" ...>` (the quicktag pills container), insert:

```html
<!-- Note → Tag mapping palette (visible only when CSV notes are loaded) -->
<div id="ep-note-mapping-section" style="display:none;margin-top:4px;">
  <div style="font-size:9px;color:#768390;margin-bottom:3px;">Note → tag — drag chip onto quicktag to map</div>
  <div id="ep-note-palette" style="display:flex;gap:4px;flex-wrap:wrap;min-height:18px;"></div>
</div>
```

- [ ] **Step 4: Add CSS**

Inside the `<style>` block (or at the end of the existing inline styles), add:

```css
.ep-note-chip-drag {
  background: #1e3a5f;
  border: 1px solid #388bfd;
  border-radius: 3px;
  padding: 2px 7px;
  cursor: grab;
  color: #88b4ff;
  user-select: none;
  font-size: 10px;
  display: inline-flex;
  align-items: center;
}
.ep-note-chip-drag:active { cursor: grabbing; }
.ep-postfix-tag.drop-hover {
  border-color: #56d364 !important;
  background: #1e3a1e !important;
}
.ep-tag-mapped-badge {
  position: absolute;
  top: -6px;
  right: -3px;
  background: #388bfd;
  color: #fff;
  border-radius: 2px;
  font-size: 7px;
  padding: 0 3px;
  line-height: 12px;
  display: flex;
  align-items: center;
  gap: 2px;
}
.ep-postfix-tag { position: relative; }
.ep-conflict-badge {
  display: none;
  font-size: 8px;
  color: #f0c040;
  margin-left: 4px;
  flex-shrink: 0;
  white-space: nowrap;
}
.result-card.has-conflict { border-left: 2px solid #f0c040; }
```

- [ ] **Step 5: Verify the app loads without JS errors**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python app.py &
# Open http://localhost:5001 (or whichever port) in browser
# Check browser console: no errors on load
# Kill server: kill %1
```

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/templates/clip_cutter.html
git commit -m "feat: add propagate KF checkbox, rescan progress, note palette HTML/CSS"
```

---

## Task 4: Frontend — rescan SSE client + `_epApplyRescanKF`

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js`

- [ ] **Step 1: Add rescan state variables**

Near the top of `enhanced_player.js`, after the existing `let _syncCamEnabled = false;` line, add:

```js
let _rescanJobId = null;
let _rescanEs = null;
```

- [ ] **Step 2: Add `_epApplyRescanKF`**

After the existing `_epApplyNewKF` function, add:

```js
function _epApplyRescanKF(idx, newFrame1Based) {
  if (typeof detections === "undefined" || !detections[idx]) return;
  const d = detections[idx];
  if (_detectionIdx === idx) return;  // user is on this candidate — discard
  if (d.status === "kept" || d.status === "rejected") return;  // already processed

  d.frame_number = newFrame1Based;
  const nameEl = document.getElementById("card-clipname-" + idx);
  if (nameEl) {
    const videoName = d.video_path.split("/").pop().replace(/\.avi$/i, "");
    const postfixSuffix = d.extract_postfix ? `_${d.extract_postfix}` : "";
    nameEl.textContent =
      videoName + "_" + (newFrame1Based - 200) + "_" + (newFrame1Based + 599) + postfixSuffix + ".avi";
  }
  if (_kfCanvasVisible) _epDrawKfCanvas();
  if (typeof saveDetections === "function") saveDetections();
}
```

- [ ] **Step 3: Add `_epStartRescan`**

After `_epApplyRescanKF`, add:

```js
async function _epStartRescan(detectionIdx) {
  if (!document.getElementById("ep-propagate-kf")?.checked) return;

  const candidates = [];
  for (let i = detectionIdx + 3; i < detections.length; i++) {
    const d = detections[i];
    if (!d || d.video_path !== _videoPath) continue;
    if (d.status === "kept" || d.status === "rejected") continue;
    candidates.push({ idx: i, frame_number: d.frame_number });
  }
  if (!candidates.length) return;

  const fineWindowEl = document.getElementById("fine-window");
  const fineWindow = fineWindowEl ? parseInt(fineWindowEl.value, 10) : 50;

  let data;
  try {
    const resp = await fetch("/clip-cutter/rescan-forward", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        video_path: _videoPath,
        candidates,
        params: { fine_window: fineWindow },
      }),
    });
    if (!resp.ok) return;
    data = await resp.json();
  } catch { return; }

  _rescanJobId = data.job_id;

  const prog = document.getElementById("ep-rescan-progress");
  const textEl = document.getElementById("ep-rescan-text");
  const countEl = document.getElementById("ep-rescan-count");
  if (prog) {
    prog.style.display = "flex";
    if (textEl) textEl.textContent = `↻ Rescanning ${candidates.length} ahead…`;
    if (countEl) countEl.textContent = "";
  }

  let done = 0;
  const total = candidates.length;
  const es = new EventSource(`/clip-cutter/rescan-forward/stream?job_id=${_rescanJobId}`);
  _rescanEs = es;

  function _finishRescan() {
    _rescanEs = null;
    _rescanJobId = null;
    if (prog) prog.style.display = "none";
  }

  es.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.phase) {
      es.close();
      _finishRescan();
      return;
    }
    done++;
    if (countEl) countEl.textContent = `${done} / ${total}`;
    _epApplyRescanKF(msg.idx, msg.new_frame_number);
  };
  es.onerror = () => { es.close(); _finishRescan(); };
}
```

- [ ] **Step 4: Call `_epStartRescan` at the end of `_epApplyNewKF`**

Find `_epApplyNewKF` in `enhanced_player.js`. At the very end of the function body (after `_epDrawKfCanvas()`), add:

```js
  _epStartRescan(_detectionIdx);
```

- [ ] **Step 5: Show/hide propagate row in `_epUpdateModeUI`**

Inside `_epUpdateModeUI`, in the `if (_mode === "clip")` branch (after existing statements), add:

```js
    const propagateRow = document.getElementById("ep-propagate-row");
    if (propagateRow) propagateRow.style.display = "flex";
```

In the `else` branch, add:

```js
    const propagateRow = document.getElementById("ep-propagate-row");
    if (propagateRow) propagateRow.style.display = "none";
```

- [ ] **Step 6: Wire up the cancel button in DOMContentLoaded**

In the `DOMContentLoaded` handler, add:

```js
  document.getElementById("ep-rescan-cancel")?.addEventListener("click", async () => {
    if (_rescanEs) { _rescanEs.close(); _rescanEs = null; }
    const jid = _rescanJobId;
    _rescanJobId = null;
    const prog = document.getElementById("ep-rescan-progress");
    if (prog) prog.style.display = "none";
    if (jid) {
      await fetch(`/clip-cutter/rescan-forward/${jid}/cancel`, { method: "POST" }).catch(() => {});
    }
  });
```

- [ ] **Step 7: Smoke test Feature 1**

```
1. Start the app: python app.py
2. Select a video with a template and multiple detections
3. Open a candidate card in the player
4. Verify "↻ Propagate KF" checkbox appears
5. Navigate to a frame, click "📌 Set KF here"
6. Verify the rescan progress bar appears briefly and candidate cards ahead update
7. While rescan is running, click candidate C+3 — verify that card's keyframe is NOT overwritten
8. Uncheck the checkbox, click "📌 Set KF here" again — verify no rescan fires
```

- [ ] **Step 8: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/static/enhanced_player.js
git commit -m "feat: rescan SSE client — propagate KF checkbox, _epApplyRescanKF, _epStartRescan"
```

---

## Task 5: Frontend — note mapping localStorage + `_epRenderNotePalette`

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js`

- [ ] **Step 1: Add note mapping state and localStorage helpers**

Near the top of `enhanced_player.js`, after `const _EP_POSTFIX_TAGS_KEY = ...`, add:

```js
const _EP_NOTE_MAPPINGS_KEY = "clip_cutter_note_mappings";
let _epNoteMappings = {};  // { note_value: postfix_tag }
```

After the existing `_epSavePostfixTags` function, add:

```js
function _epLoadNoteMappings() {
  try {
    const saved = localStorage.getItem(_EP_NOTE_MAPPINGS_KEY);
    _epNoteMappings = saved ? JSON.parse(saved) : {};
  } catch { _epNoteMappings = {}; }
}

function _epSaveNoteMapping(noteVal, tagVal) {
  // One tag can only map one note; remove any existing mapping TO this tag
  for (const k of Object.keys(_epNoteMappings)) {
    if (_epNoteMappings[k] === tagVal) delete _epNoteMappings[k];
  }
  _epNoteMappings[noteVal] = tagVal;
  localStorage.setItem(_EP_NOTE_MAPPINGS_KEY, JSON.stringify(_epNoteMappings));
}

function _epRemoveNoteMapping(noteVal) {
  delete _epNoteMappings[noteVal];
  localStorage.setItem(_EP_NOTE_MAPPINGS_KEY, JSON.stringify(_epNoteMappings));
}
```

- [ ] **Step 2: Add `_epRenderNotePalette`**

After `_epRemoveNoteMapping`, add:

```js
function _epRenderNotePalette() {
  const section = document.getElementById("ep-note-mapping-section");
  const palette = document.getElementById("ep-note-palette");
  if (!section || !palette) return;

  const noteVals = Object.keys(_epNoteColorMap);
  section.style.display = noteVals.length > 0 ? "" : "none";
  if (!noteVals.length) return;

  palette.innerHTML = "";
  noteVals.forEach(val => {
    const chip = document.createElement("span");
    chip.className = "ep-note-chip-drag";
    chip.textContent = "⠿ " + val;
    chip.draggable = true;
    chip.dataset.noteVal = val;
    chip.addEventListener("dragstart", e => {
      e.dataTransfer.setData("text/plain", val);
      e.dataTransfer.effectAllowed = "link";
    });
    palette.appendChild(chip);
  });

  // Re-render quicktag pills with drop-zone and badge behaviour
  _epRenderPostfixTags();
}
```

- [ ] **Step 3: Augment `_epRenderPostfixTags` to add drop zones and mapped-note badges**

Inside the existing `_epRenderPostfixTags` function, in the per-tag `forEach` loop, find where the `pill` element is created and its click listener is attached. After all existing pill setup code (but before `container.appendChild(pill)`), add:

```js
    // Mapped-note badge
    const mappedNote = Object.keys(_epNoteMappings).find(n => _epNoteMappings[n] === tag);
    if (mappedNote) {
      pill.style.borderStyle = "solid";
      const badge = document.createElement("span");
      badge.className = "ep-tag-mapped-badge";
      badge.textContent = mappedNote;
      const delX = document.createElement("span");
      delX.textContent = "×";
      delX.style.cssText = "cursor:pointer;margin-left:1px;";
      delX.addEventListener("click", e => {
        e.stopPropagation();
        _epRemoveNoteMapping(mappedNote);
        _epRenderNotePalette();
        if (typeof _epAutoPopulatePostfixes === "function") _epAutoPopulatePostfixes();
      });
      badge.appendChild(delX);
      pill.appendChild(badge);
    } else {
      pill.style.borderStyle = "dashed";
    }

    // Drop zone
    pill.addEventListener("dragover", e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "link";
      pill.classList.add("drop-hover");
    });
    pill.addEventListener("dragleave", () => pill.classList.remove("drop-hover"));
    pill.addEventListener("drop", e => {
      e.preventDefault();
      pill.classList.remove("drop-hover");
      const noteVal = e.dataTransfer.getData("text/plain");
      if (!noteVal) return;
      _epSaveNoteMapping(noteVal, tag);
      _epRenderNotePalette();
      if (typeof _epAutoPopulatePostfixes === "function") _epAutoPopulatePostfixes();
    });
```

- [ ] **Step 4: Call `_epLoadNoteMappings` and `_epRenderNotePalette` at startup**

In the `DOMContentLoaded` handler, where `_epLoadPostfixTags()` and `_epRenderPostfixTags()` are called, add immediately after them:

```js
  _epLoadNoteMappings();
```

In `openPlayer`, after `_epBuildTagBars()` is called, add:

```js
  _epRenderNotePalette();
```

- [ ] **Step 5: Smoke test note palette rendering**

```
1. Start the app: python app.py
2. Select a video whose CSV has note values
3. Open a candidate in the player
4. Verify note palette appears below the quicktag row showing note chips
5. Verify quicktag pills show dashed border (unmapped state)
6. (Drag-and-drop tested in Task 6)
```

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/static/enhanced_player.js
git commit -m "feat: note mapping localStorage helpers and note palette render"
```

---

## Task 6: Frontend — `_epAutoPopulatePostfixes` + conflict badge

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js`
- Modify: `clip-cutter/static/clip_cutter.js`

- [ ] **Step 1: Add `_epAutoPopulatePostfixes` to enhanced_player.js**

After `_epRenderNotePalette`, add:

```js
function _epAutoPopulatePostfixes() {
  if (!_csvRows.length) return;
  const mappings = _epNoteMappings;
  if (!Object.keys(mappings).length) return;
  if (typeof detections === "undefined") return;

  detections.forEach((d, i) => {
    if (!d || !d.frame_number) return;
    if (d.status === "kept" || d.status === "rejected") return;

    const lo = d.frame_number - 200;
    const hi = d.frame_number + 599;
    const notesInWindow = new Set(
      _csvRows
        .filter(r => Number(r.frame_number) >= lo && Number(r.frame_number) <= hi && r.note)
        .map(r => r.note)
    );
    const mappedNotes = [...notesInWindow].filter(n => mappings[n]);

    const card = document.getElementById("card-" + i);
    const conflictBadge = card ? card.querySelector(".ep-conflict-badge") : null;

    if (mappedNotes.length === 1) {
      const postfix = mappings[mappedNotes[0]];
      d.extract_postfix = postfix;

      const nameEl = document.getElementById("card-clipname-" + i);
      if (nameEl) {
        const videoName = d.video_path.split("/").pop().replace(/\.avi$/i, "");
        nameEl.textContent =
          videoName + "_" + (d.frame_number - 200) + "_" + (d.frame_number + 599) + "_" + postfix + ".avi";
      }
      if (_detectionIdx === i) {
        const pfEl = document.getElementById("ep-postfix");
        if (pfEl) pfEl.value = postfix;
      }
      if (card) card.classList.remove("has-conflict");
      if (conflictBadge) conflictBadge.style.display = "none";

    } else if (mappedNotes.length > 1) {
      if (card) card.classList.add("has-conflict");
      if (conflictBadge) {
        conflictBadge.textContent = "⚠ " + mappedNotes.join(" + ");
        conflictBadge.style.display = "";
      }

    } else {
      if (card) card.classList.remove("has-conflict");
      if (conflictBadge) conflictBadge.style.display = "none";
    }
  });

  if (typeof saveDetections === "function") saveDetections();
}
```

- [ ] **Step 2: Add conflict badge element to `buildResultCard` in clip_cutter.js**

In `buildResultCard`, find the `.result-row` inner HTML. Locate the spacer `<div style="flex:1;min-width:0;"></div>`. Immediately **after** that spacer div (but before the action buttons), add a conflict badge span. The HTML template inside `buildResultCard` should include:

```js
        <span class="ep-conflict-badge"></span>
```

The full `.result-row` section should look like:

```js
      <div class="result-row">
        <span style="font-size:9px;color:#768390;white-space:nowrap;">kf <span class="kf-num"></span></span>
        <span class="sim-pill"></span>
        <span class="match-pill ${isKnown ? "match-known" : "match-new"}"></span>
        <div style="flex:1;min-width:0;"></div>
        <span class="ep-conflict-badge"></span>
        <button class="btn-sm btn-green keep-btn" style="padding:1px 5px;font-size:9px;">&#10003;</button>
        <button class="btn-sm btn-red reject-btn" style="padding:1px 5px;font-size:9px;">&#10007;</button>
        <button class="btn-sm btn-blue add-btn" style="padding:1px 5px;font-size:9px;">+Tpl</button>
      </div>
```

- [ ] **Step 3: Call `_epAutoPopulatePostfixes` after `renderDetections` in clip_cutter.js**

In `clip_cutter.js`, at the end of the `renderDetections` function (after `applyFilter()`), add:

```js
  if (typeof _epAutoPopulatePostfixes === "function") _epAutoPopulatePostfixes();
```

- [ ] **Step 4: Call `_epAutoPopulatePostfixes` after CSV loads in openPlayer**

In `enhanced_player.js`, in `openPlayer`, after the CSV fetch block (the `if (csvPath)` block), add:

```js
  _epAutoPopulatePostfixes();
```

- [ ] **Step 5: Smoke test Feature 2 end-to-end**

```
1. Start the app: python app.py
2. Select a video whose CSV has note values (e.g. "f" and "s")
3. Create quicktags "failure" and "success" in the extract panel
4. Open a candidate — verify note palette shows "⠿ f" and "⠿ s" chips
5. Drag "f" chip onto "failure" quicktag — verify:
   - Badge "f" appears on "failure" pill
   - Candidate cards with only "f" in window show postfix "failure" in name
   - Candidate cards with both "f" and "s" show amber ⚠ badge
6. Click the × on the badge — verify mapping cleared and badges reset
7. Open a candidate that was auto-populated — verify ep-postfix field shows the tag value
8. Extract that candidate — verify status is "kept" and future auto-populate ignores it
```

- [ ] **Step 6: Run full test suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/static/enhanced_player.js clip-cutter/static/clip_cutter.js
git commit -m "feat: auto-populate postfix from note mappings, conflict badge on result cards"
```

---

## Self-Review Notes

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| Propagate KF checkbox, default checked, clip mode only | Tasks 3, 4 |
| Template enrichment before rescan (wait for add) | Task 4 — `_epStartRescan` awaits `template/add` response... **gap**: `_epApplyNewKF` already calls `template/add` via `addToTemplate` elsewhere — verify the existing flow calls `template/add` before `_epStartRescan`. If not, add `await addToTemplate(...)` before calling `_epStartRescan` in `_epApplyNewKF`. |
| C+3 buffer (skip C, C+1, C+2) | Task 4 — `detectionIdx + 3` ✓ |
| Discard if `_detectionIdx === idx` or status kept/rejected | Task 4 — `_epApplyRescanKF` ✓ |
| Extraction sets status to "kept" — covered by discard check | Existing code ✓ |
| Dual-GPU → CUDA:1 only, large batch to saturate | Tasks 1, 2 ✓ |
| Cancel button in progress row | Task 4 ✓ |
| Note palette from `_epNoteColorMap`, hidden when no CSV notes | Task 5 ✓ |
| Draggable chips, quicktags as drop zones, mapped badge with × | Task 5 ✓ |
| Persist mappings in `clip_cutter_note_mappings` localStorage | Task 5 ✓ |
| Auto-populate on mapping create/remove, video load, renderDetections | Tasks 5, 6 ✓ |
| Conflict indicator (amber ⚠) when multiple mapped notes in window | Task 6 ✓ |
| Skip kept/rejected in auto-populate | Task 6 ✓ |
| Return early from `_epAutoPopulatePostfixes` if `_csvRows` empty | Task 6 ✓ |

**Gap to fix (template enrichment ordering):** In `_epApplyNewKF`, the existing code does not call `template/add` — it only updates `detections[idx].frame_number` locally. The template add must be triggered explicitly before `_epStartRescan`. In Task 4 Step 4, add this before the `_epStartRescan` call:

```js
  // Enrich template with new keyframe frame before rescanning
  if (document.getElementById("ep-propagate-kf")?.checked) {
    try {
      await fetch("/clip-cutter/template/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_path: _videoPath, frame_number: kf1 }),
      });
    } catch { /* non-fatal */ }
  }
  _epStartRescan(_detectionIdx);
```

Since `_epApplyNewKF` is not async, change it to `async function _epApplyNewKF(kf1)` and update its two call sites to `await _epApplyNewKF(kf1)` (in the `ep-set-kf` click handler and the "Keep anyway" button handler).

# Library Scan Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two scan types (Clips / Template Frames), two sensor modes (Clip only / Sensor+Clip), a rethreshold bar, and a two-zone directory frame viewer inside each library card.

**Architecture:** Split into A1 (scan UI + backend) and A2 (directory frame viewer). A1 adds `scan_video_sensor_guided_multi` and `find_template_candidates` to `processor.py`, new routes in `routes.py` for batch-template-scan and template-frame-add, and pill toggle controls + candidate card rendering in `clip_cutter.js`. A2 adds `GET/DELETE /library-folder-frames` routes and rewires the library card body to a two-zone layout with a drag handle.

**Tech Stack:** Python/Flask backend, vanilla JS frontend, scikit-learn KMeans for clustering.

---

## File Map

| File | What changes |
|---|---|
| `processor.py` | Add `scan_video_sensor_guided_multi`, `find_template_candidates` |
| `routes.py` | Update `_run_batch_scan`; add `_batch_template_scan_jobs`, `_run_batch_template_scan`, 4 new routes for template scan + 2 for folder frames |
| `static/clip_cutter.js` | Add `_libScanType`, `_libSensorMode`, `_templateScanJobId` state; add pill handlers; update scan dispatch; add `startBatchTemplateScan`, `renderTemplateCandidateCards`, `showRethresholdBar`, `loadFolderFrames`; update `renderLibraries` for two-zone layout |
| `templates/clip_cutter.html` | Add pill toggles, sensor fields, target-clusters input, zone layout, CSS |
| `tests/test_processor.py` | Tests for new processor functions |
| `tests/test_routes.py` | Tests for new routes |

---

### Task 1: `scan_video_sensor_guided_multi` in processor.py

**Files:**
- Modify: `clip-cutter/processor.py`
- Test: `clip-cutter/tests/test_processor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_processor.py
def test_scan_video_sensor_guided_multi_no_csv_raises(mock_model, tiny_video, tmp_path):
    """CSV path that doesn't exist should propagate as FileNotFoundError."""
    import processor
    combined = {
        "clip_matrix": np.random.default_rng(0).random((2, 512)).astype(np.float32),
        "dino_matrix": None,
    }
    # Normalise rows so dot-products are valid
    clip_matrix = combined["clip_matrix"]
    clip_matrix /= np.linalg.norm(clip_matrix, axis=1, keepdims=True)
    combined["clip_matrix"] = clip_matrix

    import pytest
    with pytest.raises((FileNotFoundError, Exception)):
        processor.scan_video_sensor_guided_multi(
            tiny_video, combined,
            csv_path=tmp_path / "missing.csv",
            trigger_value=14, sensor_margin=2,
            stride=2, threshold=0.0, min_spacing=10, fine_window=2,
        )


def test_scan_video_sensor_guided_multi_returns_list(mock_model, tiny_video, tmp_path):
    """With a well-formed CSV, returns a list (possibly empty)."""
    import csv, processor
    csv_path = tmp_path / "sensor.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame_number", "frame_line_status"])
        for i in range(1, 21):
            w.writerow([i, 14 if i in (5, 10) else 0])

    rng = np.random.default_rng(0)
    clip_matrix = rng.random((2, 512)).astype(np.float32)
    clip_matrix /= np.linalg.norm(clip_matrix, axis=1, keepdims=True)
    combined = {"clip_matrix": clip_matrix, "dino_matrix": None}

    results = processor.scan_video_sensor_guided_multi(
        tiny_video, combined,
        csv_path=csv_path,
        trigger_value=14, sensor_margin=2,
        stride=2, threshold=0.0, min_spacing=10, fine_window=2,
    )
    assert isinstance(results, list)
    for r in results:
        assert "frame_number" in r
        assert "similarity" in r
        assert "source" in r
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd clip-cutter && pytest tests/test_processor.py::test_scan_video_sensor_guided_multi_returns_list -v
```

Expected: FAIL — `AttributeError: module 'processor' has no attribute 'scan_video_sensor_guided_multi'`.

- [ ] **Step 3: Implement `scan_video_sensor_guided_multi`**

Add this function to `processor.py` immediately after `scan_video_sensor_guided` (after line 767):

```python
def scan_video_sensor_guided_multi(
    video_path: Path | str,
    combined: dict,
    csv_path: Path | str,
    trigger_value: int = 14,
    sensor_margin: int = 25,
    stride: int = 10,
    threshold: float = 0.70,
    min_spacing: int = 900,
    fine_window: int = 50,
    batch_size: int = 256,
    smooth_sigma: float = 3.0,
    phase_cb=None,
) -> list[dict]:
    """
    Sensor-guided scan using multiple template embeddings (max similarity).
    Combined: output of load_combined_template().
    Returns same format as scan_video_sensor_guided: [{cv2_pos, frame_number, similarity, source}].
    """
    clip_matrix = combined.get("clip_matrix")
    dino_matrix = combined.get("dino_matrix")
    if clip_matrix is None:
        return []

    if phase_cb:
        phase_cb("sensor_parse", 0, 1)
    sensor_frames, covered_set = find_sensor_triggers(csv_path, trigger_value, sensor_margin)
    if phase_cb:
        phase_cb("sensor_parse", 1, 1)

    if phase_cb:
        phase_cb("coarse", 0, 1)

    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    all_positions = np.arange(0, total_frames, stride, dtype=np.int64)
    gap_positions = np.array(
        [p for p in all_positions if (int(p) + 1) not in covered_set], dtype=np.int64
    )

    if len(gap_positions) > 0:
        gap_indices, gap_sims = get_similarity_curve_multi(
            video_path, clip_matrix,
            stride=stride, batch_size=batch_size,
            positions=gap_positions,
        )
    else:
        gap_indices = np.array([], dtype=np.int64)
        gap_sims = np.array([], dtype=np.float32)

    if phase_cb:
        phase_cb("peak_detection", 0, 1)

    clip_peaks: list[int] = []
    if len(gap_sims) > 0:
        smoothed = smooth_curve(gap_sims, sigma=smooth_sigma)
        clip_peaks = find_peaks_in_curve(smoothed, gap_indices, threshold, min_spacing)

    candidates: list[tuple[int, str]] = []
    for sf in sensor_frames:
        candidates.append((sf - 1, "sensor"))
    for cp in clip_peaks:
        candidates.append((cp, "clip"))
    candidates.sort(key=lambda x: x[0])

    dedup: list[tuple[int, str]] = []
    half = min_spacing // 2
    for pos, src in candidates:
        if dedup and abs(pos - dedup[-1][0]) < half:
            prev_pos, prev_src = dedup[-1]
            if src == "sensor" and prev_src != "sensor":
                dedup[-1] = (pos, src)
            elif src == "sensor" and prev_src == "sensor":
                dedup.append((pos, src))
        else:
            dedup.append((pos, src))

    if phase_cb:
        phase_cb("fine", 0, max(len(dedup), 1))

    results = []
    for i, (coarse_pos, src) in enumerate(dedup):
        exact_pos, fine_sim = fine_scan_multi(
            video_path, clip_matrix, coarse_pos,
            window=fine_window, dino_matrix=dino_matrix,
        )
        if src == "sensor":
            source_tag = "sensor+clip" if fine_sim >= threshold else "sensor_only"
        else:
            source_tag = "clip_only"
        results.append({
            "cv2_pos": exact_pos,
            "frame_number": exact_pos + 1,
            "similarity": round(fine_sim, 4),
            "source": source_tag,
        })
        if phase_cb:
            phase_cb("fine", i + 1, len(dedup))

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd clip-cutter && pytest tests/test_processor.py::test_scan_video_sensor_guided_multi_returns_list tests/test_processor.py::test_scan_video_sensor_guided_multi_no_csv_raises -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add clip-cutter/processor.py clip-cutter/tests/test_processor.py
git commit -m "feat: add scan_video_sensor_guided_multi to processor"
```

---

### Task 2: `find_template_candidates` in processor.py

**Files:**
- Modify: `clip-cutter/processor.py`
- Test: `clip-cutter/tests/test_processor.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_processor.py
def test_find_template_candidates_empty_video_returns_empty(mock_model, tmp_path):
    """Video that produces no frames above threshold returns empty candidates."""
    import processor
    rng = np.random.default_rng(0)
    clip_matrix = rng.random((2, 512)).astype(np.float32)
    clip_matrix /= np.linalg.norm(clip_matrix, axis=1, keepdims=True)
    combined = {"clip_matrix": clip_matrix, "dino_matrix": None}

    # Create a 1-frame video using OpenCV
    import cv2
    vpath = tmp_path / "tiny.avi"
    out = cv2.VideoWriter(str(vpath), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    out.write(np.zeros((48, 64, 3), dtype=np.uint8))
    out.release()

    result = processor.find_template_candidates(
        vpath, combined, n_clusters=3, threshold=0.99, stride=1
    )
    assert "candidates" in result
    assert "curve" in result
    assert "embeddings" in result
    assert isinstance(result["candidates"], list)


def test_find_template_candidates_fewer_than_clusters(mock_model, tiny_video):
    """When fewer above-threshold frames than clusters, all are returned without clustering."""
    import processor
    rng = np.random.default_rng(42)
    clip_matrix = rng.random((1, 512)).astype(np.float32)
    clip_matrix /= np.linalg.norm(clip_matrix, axis=1, keepdims=True)
    combined = {"clip_matrix": clip_matrix, "dino_matrix": None}

    result = processor.find_template_candidates(
        tiny_video, combined, n_clusters=100, threshold=0.0, stride=1
    )
    assert isinstance(result["candidates"], list)
    # All frames returned as candidates (skip clustering)
    assert len(result["candidates"]) == len(result["curve"])


def test_find_template_candidates_clustering(mock_model, tiny_video):
    """With enough frames, clustering runs and returns at most 2*n_clusters candidates."""
    import processor
    rng = np.random.default_rng(7)
    clip_matrix = rng.random((2, 512)).astype(np.float32)
    clip_matrix /= np.linalg.norm(clip_matrix, axis=1, keepdims=True)
    combined = {"clip_matrix": clip_matrix, "dino_matrix": None}

    result = processor.find_template_candidates(
        tiny_video, combined, n_clusters=2, threshold=0.0, stride=1
    )
    assert len(result["candidates"]) <= 4  # 2 clusters × 2 nearest each
    for c in result["candidates"]:
        assert "frame_number" in c
        assert "similarity" in c
        assert "cluster_id" in c
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd clip-cutter && pytest tests/test_processor.py::test_find_template_candidates_clustering -v
```

Expected: FAIL — function not found.

- [ ] **Step 3: Implement `find_template_candidates`**

Add to `processor.py` after `scan_video_sensor_guided_multi`:

```python
def find_template_candidates(
    video_path: Path | str,
    combined: dict,
    n_clusters: int = 10,
    threshold: float = 0.70,
    stride: int = 10,
    batch_size: int = 64,
    phase_cb=None,
    csv_path: Path | str | None = None,
    trigger_value: int = 14,
    sensor_margin: int = 25,
) -> dict:
    """
    K-means candidate pipeline for template frame discovery.

    Returns:
        {
            candidates: [{frame_number (1-based), similarity, cluster_id}],
            curve: [{frame_number (0-based cv2_pos), similarity}],  # all sampled frames
            embeddings: ndarray shape (N, 512),                      # parallel to curve
        }
    """
    from concurrent.futures import ThreadPoolExecutor
    from sklearn.cluster import KMeans

    clip_matrix = combined.get("clip_matrix")
    if clip_matrix is None:
        return {
            "candidates": [],
            "curve": [],
            "embeddings": np.zeros((0, 512), dtype=np.float32),
        }

    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    all_positions = np.arange(0, total_frames, stride, dtype=np.int64)

    # Sensor-guided: restrict to covered windows
    if csv_path is not None and Path(csv_path).exists():
        _, covered_set = find_sensor_triggers(csv_path, trigger_value, sensor_margin)
        positions = np.array(
            [p for p in all_positions if (int(p) + 1) in covered_set], dtype=np.int64
        )
    else:
        positions = all_positions

    if len(positions) == 0:
        return {
            "candidates": [],
            "curve": [],
            "embeddings": np.zeros((0, 512), dtype=np.float32),
        }

    if phase_cb:
        phase_cb("coarse", 0, len(positions))

    def read_batch(batch_positions):
        if len(batch_positions) == 0:
            return []
        vcap = cv2.VideoCapture(str(video_path))
        vcap.set(cv2.CAP_PROP_POS_FRAMES, int(batch_positions[0]))
        cur = int(batch_positions[0])
        frames = []
        try:
            for target in batch_positions:
                target = int(target)
                while cur < target:
                    vcap.grab()
                    cur += 1
                ret, frame = vcap.read()
                cur += 1
                frames.append(frame if ret else np.zeros((64, 64, 3), dtype=np.uint8))
        finally:
            vcap.release()
        return frames

    all_embs_chunks = []
    all_sims_chunks = []
    processed = 0

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(read_batch, positions[:batch_size])
        for batch_start in range(0, len(positions), batch_size):
            batch_pos = positions[batch_start: batch_start + batch_size]
            frames = future.result()
            next_start = batch_start + batch_size
            future = pool.submit(read_batch, positions[next_start: next_start + batch_size])
            embs = embed_frames_batch(frames)          # (B, 512)
            sims = (embs @ clip_matrix.T).max(axis=1) # (B,)
            n = len(batch_pos)
            all_embs_chunks.append(embs[:n])
            all_sims_chunks.append(sims[:n])
            processed += n
            if phase_cb:
                phase_cb("coarse", processed, len(positions))

    all_embs = np.vstack(all_embs_chunks) if all_embs_chunks else np.zeros((0, 512), dtype=np.float32)
    all_sims = np.concatenate(all_sims_chunks) if all_sims_chunks else np.array([], dtype=np.float32)

    curve = [
        {"frame_number": int(positions[i]), "similarity": float(all_sims[i])}
        for i in range(len(positions))
    ]

    # Filter above threshold
    mask = all_sims >= threshold
    filtered_pos = positions[mask]
    filtered_embs = all_embs[mask]
    filtered_sims = all_sims[mask]

    if len(filtered_pos) == 0:
        return {"candidates": [], "curve": curve, "embeddings": all_embs}

    # Fewer frames than clusters: skip clustering, return all
    if len(filtered_pos) <= n_clusters:
        candidates = [
            {
                "frame_number": int(filtered_pos[i]) + 1,  # 1-based
                "similarity": float(filtered_sims[i]),
                "cluster_id": i,
            }
            for i in range(len(filtered_pos))
        ]
        return {"candidates": candidates, "curve": curve, "embeddings": all_embs}

    if phase_cb:
        phase_cb("cluster", 0, 1)

    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
    km.fit(filtered_embs)
    labels = km.labels_
    centroids = km.cluster_centers_

    candidates = []
    for cid in range(n_clusters):
        idx_in_cluster = np.where(labels == cid)[0]
        if len(idx_in_cluster) == 0:
            continue
        cluster_embs = filtered_embs[idx_in_cluster]
        dists = np.linalg.norm(cluster_embs - centroids[cid], axis=1)
        nearest = idx_in_cluster[np.argsort(dists)[:2]]
        for j in nearest:
            candidates.append({
                "frame_number": int(filtered_pos[j]) + 1,  # 1-based
                "similarity": float(filtered_sims[j]),
                "cluster_id": int(cid),
            })

    candidates.sort(key=lambda c: c["frame_number"])

    if phase_cb:
        phase_cb("cluster", 1, 1)

    return {"candidates": candidates, "curve": curve, "embeddings": all_embs}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd clip-cutter && pytest tests/test_processor.py::test_find_template_candidates_empty_video_returns_empty tests/test_processor.py::test_find_template_candidates_fewer_than_clusters tests/test_processor.py::test_find_template_candidates_clustering -v
```

Expected: PASS (3/3).

- [ ] **Step 5: Commit**

```bash
git add clip-cutter/processor.py clip-cutter/tests/test_processor.py
git commit -m "feat: add find_template_candidates to processor"
```

---

### Task 3: Update `_run_batch_scan` for sensor+clip + add batch-template-scan routes

**Files:**
- Modify: `clip-cutter/routes.py`
- Test: `clip-cutter/tests/test_routes.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_routes.py
def test_batch_template_scan_missing_template_dirs(client):
    resp = client.post("/clip-cutter/batch-template-scan",
                       json={"video_paths": ["/x/v.avi"], "params": {}})
    assert resp.status_code == 400
    assert b"template_dirs" in resp.data


def test_batch_template_scan_starts_and_streams(client, tmp_path, monkeypatch):
    import routes, numpy as np

    # Patch find_template_candidates to return immediately
    def fake_find(video_path, combined, **kwargs):
        return {
            "candidates": [{"frame_number": 5, "similarity": 0.8, "cluster_id": 0}],
            "curve": [{"frame_number": 0, "similarity": 0.8}],
            "embeddings": np.zeros((1, 512), dtype=np.float32),
        }

    monkeypatch.setattr("processor.find_template_candidates", fake_find)

    # Create a fake template dir with template_state.json
    tdir = tmp_path / "templ"
    tdir.mkdir()
    state_path = tdir / "template_state.json"
    state_path.write_text('{"frames": [{"video_path": "x.avi", "frame_number": 1, "embedding": [], "dino_embedding": [], "thumbnail": ""}]}')

    import processor
    monkeypatch.setattr(processor, "load_combined_template", lambda dirs: {
        "clip_matrix": np.ones((1, 512), dtype=np.float32),
        "dino_matrix": None,
    })

    resp = client.post("/clip-cutter/batch-template-scan", json={
        "template_dirs": [str(tdir)],
        "video_paths": ["/x/v.avi"],
        "params": {"stride": 10, "threshold": 0.7, "n_clusters": 5},
    })
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "job_id" in data

    import time
    time.sleep(0.2)

    # Stream until done
    with client.get(f"/clip-cutter/batch-template-scan/stream?job_id={data['job_id']}",
                    buffered=True) as stream_resp:
        assert stream_resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd clip-cutter && pytest tests/test_routes.py::test_batch_template_scan_missing_template_dirs -v
```

Expected: FAIL — route does not exist.

- [ ] **Step 3: Update `_run_batch_scan` for sensor+clip mode**

In `routes.py`, replace the current `_run_batch_scan` function with this updated version that accepts `scan_mode`:

```python
def _run_batch_scan(job_id: str, template_dirs: list, video_paths: list, params: dict):
    stride        = params.get("stride",        config.SCAN_STRIDE)
    threshold     = params.get("threshold",     config.SIMILARITY_THRESHOLD)
    min_spacing   = params.get("min_spacing",   config.MIN_PEAK_SPACING)
    fine_window   = params.get("fine_window",   config.FINE_SCAN_WINDOW)
    scan_mode     = params.get("scan_mode",     "clip_only")
    trigger_value = params.get("trigger_value", config.SENSOR_TRIGGER_VALUE)
    sensor_margin = params.get("sensor_margin", config.SENSOR_MARGIN)

    combined = processor.load_combined_template(template_dirs)
    if combined["clip_matrix"] is None:
        with _batch_scan_jobs_lock:
            _batch_scan_jobs[job_id]["phase"] = "error"
            _batch_scan_jobs[job_id]["error"] = "No valid templates found in selected directories"
        return

    results = []
    total_videos = len(video_paths)
    for i, video_path in enumerate(video_paths):
        def phase_cb(phase, current, total, _vpath=video_path, _i=i):
            with _batch_scan_jobs_lock:
                _batch_scan_jobs[job_id]["video"] = Path(_vpath).name
                _batch_scan_jobs[job_id]["video_index"] = _i + 1
                _batch_scan_jobs[job_id]["video_total"] = total_videos
                _batch_scan_jobs[job_id]["phase"] = phase
                _batch_scan_jobs[job_id]["current"] = current
                _batch_scan_jobs[job_id]["total"] = total

        try:
            if scan_mode == "sensor+clip":
                csv_path = Path(video_path).with_suffix(".csv")
                if not csv_path.exists():
                    raise FileNotFoundError(f"CSV not found for {video_path}")
                detections = processor.scan_video_sensor_guided_multi(
                    video_path, combined, csv_path,
                    trigger_value=trigger_value,
                    sensor_margin=sensor_margin,
                    stride=stride, threshold=threshold,
                    min_spacing=min_spacing, fine_window=fine_window,
                    batch_size=config.SCAN_BATCH_SIZE,
                    phase_cb=phase_cb,
                )
            else:
                detections = processor.scan_video_multi_template(
                    video_path, combined,
                    stride=stride, threshold=threshold,
                    min_spacing=min_spacing, fine_window=fine_window,
                    batch_size=config.SCAN_BATCH_SIZE,
                    phase_cb=phase_cb,
                )
            for d in detections:
                d["status"] = "pending"
                d["source"] = "global_library"
            results.append({"video": video_path, "detections": detections})
        except Exception as exc:
            results.append({"video": video_path, "error": str(exc), "detections": []})

    with _batch_scan_jobs_lock:
        _batch_scan_jobs[job_id]["phase"] = "done"
        _batch_scan_jobs[job_id]["results"] = results
```

- [ ] **Step 4: Add batch-template-scan state + routes**

After `_batch_scan_jobs_lock = threading.Lock()` (wherever the existing batch lock is defined), add:

```python
_batch_template_scan_jobs: dict[str, dict] = {}
_batch_template_scan_jobs_lock = threading.Lock()
```

Add the background worker and routes at the end of the batch-scan section (after `/batch-scan/stream`):

```python
def _run_batch_template_scan(job_id: str, template_dirs: list, video_paths: list, params: dict):
    stride        = params.get("stride",        config.SCAN_STRIDE)
    threshold     = params.get("threshold",     config.SIMILARITY_THRESHOLD)
    n_clusters    = params.get("n_clusters",    10)
    scan_mode     = params.get("scan_mode",     "clip_only")
    trigger_value = params.get("trigger_value", config.SENSOR_TRIGGER_VALUE)
    sensor_margin = params.get("sensor_margin", config.SENSOR_MARGIN)

    combined = processor.load_combined_template(template_dirs)
    if combined["clip_matrix"] is None:
        with _batch_template_scan_jobs_lock:
            _batch_template_scan_jobs[job_id]["phase"] = "error"
            _batch_template_scan_jobs[job_id]["error"] = "No valid templates found in selected directories"
        return

    per_video = []
    total_videos = len(video_paths)
    for i, video_path in enumerate(video_paths):
        def phase_cb(phase, current, total, _vpath=video_path, _i=i):
            with _batch_template_scan_jobs_lock:
                _batch_template_scan_jobs[job_id]["video"] = Path(_vpath).name
                _batch_template_scan_jobs[job_id]["video_index"] = _i + 1
                _batch_template_scan_jobs[job_id]["video_total"] = total_videos
                _batch_template_scan_jobs[job_id]["phase"] = phase
                _batch_template_scan_jobs[job_id]["current"] = current
                _batch_template_scan_jobs[job_id]["total"] = total

        try:
            csv_path = Path(video_path).with_suffix(".csv") if scan_mode == "sensor+clip" else None
            result = processor.find_template_candidates(
                video_path, combined,
                n_clusters=n_clusters,
                threshold=threshold,
                stride=stride,
                batch_size=config.SCAN_BATCH_SIZE,
                phase_cb=phase_cb,
                csv_path=csv_path,
                trigger_value=trigger_value,
                sensor_margin=sensor_margin,
            )
            per_video.append({
                "video_path": video_path,
                "candidates": result["candidates"],
                "curve": result["curve"],
                "embeddings": result["embeddings"],  # ndarray — stays in memory
            })
        except Exception as exc:
            per_video.append({
                "video_path": video_path,
                "candidates": [],
                "curve": [],
                "embeddings": None,
                "error": str(exc),
            })

    # Build serialisable results for SSE (exclude embeddings ndarray)
    sse_results = [
        {"video_path": v["video_path"], "candidates": v["candidates"]}
        for v in per_video
    ]
    with _batch_template_scan_jobs_lock:
        _batch_template_scan_jobs[job_id]["phase"] = "done"
        _batch_template_scan_jobs[job_id]["results"] = sse_results
        _batch_template_scan_jobs[job_id]["per_video"] = per_video


@bp.route("/batch-template-scan", methods=["POST"])
def start_batch_template_scan():
    body = request.get_json(force=True) or {}
    template_dirs = body.get("template_dirs", [])
    video_paths   = body.get("video_paths",   [])
    if not template_dirs:
        return jsonify({"error": "template_dirs required"}), 400
    if not video_paths:
        return jsonify({"error": "video_paths required"}), 400
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    job_id = str(uuid.uuid4())
    with _batch_template_scan_jobs_lock:
        _batch_template_scan_jobs[job_id] = {
            "phase": "starting", "video": "", "video_index": 0,
            "video_total": len(video_paths), "current": 0, "total": 1,
        }
    threading.Thread(
        target=_run_batch_template_scan,
        args=(job_id, template_dirs, video_paths, params),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@bp.route("/batch-template-scan/stream")
def batch_template_scan_stream():
    job_id = request.args.get("job_id")
    if not job_id or job_id not in _batch_template_scan_jobs:
        return jsonify({"error": "unknown job_id"}), 404

    def generate():
        while True:
            with _batch_template_scan_jobs_lock:
                job = {k: v for k, v in _batch_template_scan_jobs[job_id].items()
                       if k != "per_video"}  # per_video has ndarray, skip it
            yield f"data: {json.dumps(job)}\n\n"
            if job.get("phase") in ("done", "error"):
                break
            time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@bp.route("/batch-template-scan/<job_id>/recluster", methods=["POST"])
def batch_template_scan_recluster(job_id):
    import numpy as np
    from sklearn.cluster import KMeans

    body      = request.get_json(force=True) or {}
    threshold  = float(body.get("threshold",  0.70))
    n_clusters = int(body.get("n_clusters",   10))

    with _batch_template_scan_jobs_lock:
        if job_id not in _batch_template_scan_jobs:
            return jsonify({"error": "unknown job_id"}), 404
        job = _batch_template_scan_jobs[job_id]
        if job.get("phase") != "done":
            return jsonify({"error": "job not complete"}), 400
        per_video = job.get("per_video", [])

    results = []
    for vdata in per_video:
        video_path = vdata["video_path"]
        curve      = vdata.get("curve", [])
        embeddings = vdata.get("embeddings")

        if embeddings is None or len(curve) == 0:
            results.append({"video_path": video_path, "candidates": []})
            continue

        filtered_indices = [i for i, c in enumerate(curve) if c["similarity"] >= threshold]
        if not filtered_indices:
            results.append({"video_path": video_path, "candidates": []})
            continue

        filtered_pos  = np.array([curve[i]["frame_number"] for i in filtered_indices])
        filtered_embs = embeddings[filtered_indices]
        filtered_sims = np.array([curve[i]["similarity"]   for i in filtered_indices])

        if len(filtered_pos) <= n_clusters:
            candidates = [
                {"frame_number": int(filtered_pos[i]) + 1,
                 "similarity":   float(filtered_sims[i]),
                 "cluster_id":   i}
                for i in range(len(filtered_pos))
            ]
            results.append({"video_path": video_path, "candidates": candidates})
            continue

        km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
        km.fit(filtered_embs)
        candidates = []
        for cid in range(n_clusters):
            idx_in_cluster = np.where(km.labels_ == cid)[0]
            if len(idx_in_cluster) == 0:
                continue
            dists  = np.linalg.norm(filtered_embs[idx_in_cluster] - km.cluster_centers_[cid], axis=1)
            nearest = idx_in_cluster[np.argsort(dists)[:2]]
            for j in nearest:
                candidates.append({
                    "frame_number": int(filtered_pos[j]) + 1,
                    "similarity":   float(filtered_sims[j]),
                    "cluster_id":   int(cid),
                })
        candidates.sort(key=lambda c: c["frame_number"])
        results.append({"video_path": video_path, "candidates": candidates})

    return jsonify({"results": results})
```

- [ ] **Step 5: Update `reset_routes_state` fixture to clear template scan jobs**

In `tests/test_routes.py`, find `reset_routes_state` and add:
```python
    routes._batch_template_scan_jobs.clear()
```
in both setup and teardown blocks.

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd clip-cutter && pytest tests/test_routes.py::test_batch_template_scan_missing_template_dirs tests/test_routes.py::test_batch_template_scan_starts_and_streams -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat: add batch-template-scan routes and update _run_batch_scan for sensor+clip"
```

---

### Task 4: `/template-frame-add` route

**Files:**
- Modify: `clip-cutter/routes.py`
- Test: `clip-cutter/tests/test_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_routes.py
def test_template_frame_add_creates_entry(client, tmp_path, monkeypatch):
    import routes, processor, config, numpy as np

    # Create a tiny video at a known path inside tmp_path
    import cv2
    video_path = tmp_path / "rat" / "session.avi"
    video_path.parent.mkdir(parents=True)
    out = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    for _ in range(10):
        out.write(np.zeros((48, 64, 3), dtype=np.uint8))
    out.release()

    # Template dir: <video_parent>/<video_stem>/template/
    clips_dir = tmp_path / "rat" / "session"
    tdir = clips_dir / "template"
    tdir.mkdir(parents=True)

    resp = client.post("/clip-cutter/template-frame-add", json={
        "video_path": str(video_path),
        "frame_number": 1,
    })
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd clip-cutter && pytest tests/test_routes.py::test_template_frame_add_creates_entry -v
```

Expected: FAIL — 404 route not found.

- [ ] **Step 3: Implement `/template-frame-add`**

Add to `routes.py` after the recluster route:

```python
@bp.route("/template-frame-add", methods=["POST"])
def template_frame_add():
    body         = request.get_json(force=True) or {}
    video_path   = body.get("video_path",   "").strip()
    frame_number = body.get("frame_number")
    if not video_path or frame_number is None:
        return jsonify({"error": "video_path and frame_number required"}), 400

    clips_dir = Path(video_path).parent / Path(video_path).stem
    state_path = None
    for candidate in [
        clips_dir / "template" / "template_state.json",
        clips_dir / "template_state.json",
    ]:
        if candidate.exists():
            state_path = candidate
            break
    if state_path is None:
        # Default: create inside clips_dir/template/
        state_path = clips_dir / "template" / "template_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)

    state = processor.load_template_state(state_path)
    state = processor.add_frame_to_template(state, video_path, int(frame_number), state_path)
    return jsonify({"count": len(state["frames"])})
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd clip-cutter && pytest tests/test_routes.py::test_template_frame_add_creates_entry -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat: add /template-frame-add route"
```

---

### Task 5: `GET/DELETE /library-folder-frames` routes (A2 backend)

**Files:**
- Modify: `clip-cutter/routes.py`
- Test: `clip-cutter/tests/test_routes.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_routes.py
def test_library_folder_frames_empty(client, tmp_path):
    resp = client.get(f"/clip-cutter/library-folder-frames?path={tmp_path}")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["frames"] == []
    assert data["count"] == 0


def test_library_folder_frames_returns_frames(client, tmp_path, monkeypatch):
    import processor, json as _json, numpy as np

    state_path = tmp_path / "template_state.json"
    state = {
        "frames": [
            {"video_path": "/x/v.avi", "frame_number": 42,
             "embedding": np.zeros(512).tolist(),
             "dino_embedding": np.zeros(384).tolist(),
             "thumbnail": ""},
        ],
        "mean_embedding": np.zeros(512).tolist(),
        "dino_mean_embedding": None,
    }
    state_path.write_text(_json.dumps(state))

    resp = client.get(f"/clip-cutter/library-folder-frames?path={tmp_path}")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["count"] == 1
    assert data["frames"][0]["frame_number"] == 42
    assert data["frames"][0]["video_path"] == "/x/v.avi"


def test_delete_library_folder_frame(client, tmp_path, monkeypatch):
    import json as _json, numpy as np

    state_path = tmp_path / "template_state.json"
    state = {
        "frames": [
            {"video_path": "/x/v.avi", "frame_number": 42,
             "embedding": np.zeros(512).tolist(),
             "dino_embedding": np.zeros(384).tolist(),
             "thumbnail": ""},
        ],
        "mean_embedding": np.zeros(512).tolist(),
        "dino_mean_embedding": None,
    }
    state_path.write_text(_json.dumps(state))

    resp = client.delete("/clip-cutter/library-folder-frames",
                         json={"path": str(tmp_path), "frame_number": 42})
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["count"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd clip-cutter && pytest tests/test_routes.py::test_library_folder_frames_empty -v
```

Expected: FAIL — 404.

- [ ] **Step 3: Implement both routes**

Add to `routes.py`:

```python
@bp.route("/library-folder-frames")
def library_folder_frames():
    path = request.args.get("path", "").strip()
    if not path:
        return jsonify({"error": "path required"}), 400

    state_path = None
    for candidate in [
        Path(path) / "template" / "template_state.json",
        Path(path) / "template_state.json",
    ]:
        if candidate.exists():
            state_path = candidate
            break

    if state_path is None:
        return jsonify({"frames": [], "count": 0})

    state = processor.load_template_state(state_path)
    frames = [
        {"frame_number": f["frame_number"], "video_path": f["video_path"]}
        for f in state.get("frames", [])
    ]
    return jsonify({"frames": frames, "count": len(frames)})


@bp.route("/library-folder-frames", methods=["DELETE"])
def delete_library_folder_frame():
    body         = request.get_json(force=True) or {}
    path         = body.get("path",         "").strip()
    frame_number = body.get("frame_number")
    if not path or frame_number is None:
        return jsonify({"error": "path and frame_number required"}), 400

    state_path = None
    for candidate in [
        Path(path) / "template" / "template_state.json",
        Path(path) / "template_state.json",
    ]:
        if candidate.exists():
            state_path = candidate
            break

    if state_path is None:
        return jsonify({"error": "template not found"}), 404

    state = processor.load_template_state(state_path)
    idx = next(
        (i for i, f in enumerate(state["frames"]) if f["frame_number"] == int(frame_number)),
        None,
    )
    if idx is None:
        return jsonify({"error": "frame not found"}), 404

    state = processor.remove_frame_from_template(state, idx, state_path)
    return jsonify({"count": len(state["frames"])})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd clip-cutter && pytest tests/test_routes.py::test_library_folder_frames_empty tests/test_routes.py::test_library_folder_frames_returns_frames tests/test_routes.py::test_delete_library_folder_frame -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat: add GET/DELETE /library-folder-frames routes"
```

---

### Task 6: HTML — scan type/sensor mode toggles + Zone 2 layout + CSS

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html`

- [ ] **Step 1: Add pill toggle CSS**

Find the existing `.lib-folder-row` CSS (or any suitable location in the stylesheet). Add:

```css
.pill-group { display: flex; gap: 2px; }
.pill-btn {
  background: #21262d; border: 1px solid #444c56;
  color: #768390; border-radius: 4px;
  padding: 2px 8px; font-size: 10px; cursor: pointer;
}
.pill-btn.active {
  background: #1f6feb22; border-color: #1f6feb; color: #58a6ff;
}
.lib-settings-row {
  display: flex; align-items: center; gap: 6px;
  padding: 2px 0; font-size: 10px; color: #768390;
}
.lib-settings-label { min-width: 80px; color: #8b949e; }
.lib-settings-input { width: 56px; }
```

- [ ] **Step 2: Add two-zone library card CSS**

```css
.lib-zone1 {
  overflow-y: auto;
  height: 112px;
  min-height: 56px;
  max-height: 224px;
}
.lib-zone1-handle {
  height: 6px;
  cursor: ns-resize;
  background: transparent;
  border-top: 1px solid #21262d;
  margin: 2px 0;
}
.lib-zone1-handle:hover { background: #21262d; }
.lib-zone2 { border-top: 1px solid #21262d; padding-top: 4px; }
.lib-zone2-header { font-size: 10px; color: #768390; padding: 2px 4px 4px; }
.lib-zone2-frames { max-height: 160px; overflow-y: auto; }
.lib-frame-row {
  display: flex; align-items: center; gap: 4px;
  padding: 2px 4px; border-bottom: 1px solid #21262d14;
}
.lib-frame-num { font-size: 10px; color: #768390; flex: 1; }
.lib-frame-thumb { object-fit: cover; border-radius: 2px; }
.lib-folder-row.selected { background: #1f6feb22; }
```

- [ ] **Step 3: Update `#lib-settings-body` to add scan type + sensor mode toggles**

Find the `#lib-settings-body` div in `clip_cutter.html`. It currently contains the stride/threshold/min-spacing/fine-window rows. Replace the entire inner content of `#lib-settings-body` with:

```html
<div id="lib-settings-body" style="display:none; padding:4px 0;">
  <!-- Scan type -->
  <div class="lib-settings-row">
    <span class="lib-settings-label">Scan type</span>
    <div class="pill-group" id="lib-scan-type">
      <button class="pill-btn active" data-val="clips">Clips</button>
      <button class="pill-btn" data-val="template_frames">Template Frames</button>
    </div>
  </div>
  <!-- Sensor mode -->
  <div class="lib-settings-row">
    <span class="lib-settings-label">Sensor mode</span>
    <div class="pill-group" id="lib-sensor-mode">
      <button class="pill-btn active" data-val="clip_only">Clip only</button>
      <button class="pill-btn" data-val="sensor+clip">Sensor+Clip</button>
    </div>
  </div>
  <!-- Sensor-only fields -->
  <div id="lib-sensor-fields" style="display:none;">
    <div class="lib-settings-row">
      <label class="lib-settings-label" for="lib-trigger-value">Trigger value</label>
      <input type="number" id="lib-trigger-value" value="14" min="1" class="lib-settings-input">
    </div>
    <div class="lib-settings-row">
      <label class="lib-settings-label" for="lib-sensor-margin">Sensor margin</label>
      <input type="number" id="lib-sensor-margin" value="25" min="0" class="lib-settings-input">
    </div>
  </div>
  <!-- Common fields -->
  <div class="lib-settings-row">
    <label class="lib-settings-label" for="lib-scan-stride">Coarse stride</label>
    <input type="number" id="lib-scan-stride" value="10" min="1" class="lib-settings-input">
  </div>
  <div class="lib-settings-row">
    <label class="lib-settings-label" for="lib-scan-threshold">Threshold</label>
    <input type="number" id="lib-scan-threshold" value="0.70" min="0" max="1" step="0.01" class="lib-settings-input">
    <span id="lib-threshold-label" style="font-size:9px;color:#768390;">0.70</span>
  </div>
  <!-- Clips-only fields -->
  <div id="lib-clips-fields">
    <div class="lib-settings-row">
      <label class="lib-settings-label" for="lib-scan-min-spacing">Min spacing</label>
      <input type="number" id="lib-scan-min-spacing" value="900" min="1" class="lib-settings-input">
    </div>
    <div class="lib-settings-row">
      <label class="lib-settings-label" for="lib-scan-fine-window">Fine window</label>
      <input type="number" id="lib-scan-fine-window" value="50" min="1" class="lib-settings-input">
    </div>
  </div>
  <!-- Template-frames-only fields -->
  <div id="lib-template-fields" style="display:none;">
    <div class="lib-settings-row">
      <label class="lib-settings-label" for="lib-target-clusters">Target clusters</label>
      <input type="number" id="lib-target-clusters" value="10" min="1" class="lib-settings-input">
    </div>
  </div>
  <div id="lib-scan-progress" style="display:none;font-size:9px;color:#768390;padding:2px 0;"></div>
</div>
```

- [ ] **Step 4: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html
git commit -m "feat: add scan type/sensor mode toggles and two-zone CSS to library card"
```

---

### Task 7: JS — scan type state + pill handlers + `renderLibraries` two-zone restructure

**Files:**
- Modify: `clip-cutter/static/clip_cutter.js`

- [ ] **Step 1: Add new state variables at top**

After the existing state declarations at the top of `clip_cutter.js`:
```js
let _libScanType   = "clips";       // "clips" | "template_frames"
let _libSensorMode = "clip_only";   // "clip_only" | "sensor+clip"
let _templateScanJobId = null;
```

- [ ] **Step 2: Add pill toggle event handlers**

Find where the existing lib-settings-toggle listener is wired (currently around line 430):
```js
  document.getElementById("lib-settings-toggle").addEventListener("click", () => {
```

After those handlers, add:

```js
  // Scan type pills
  document.getElementById("lib-scan-type").querySelectorAll(".pill-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.getElementById("lib-scan-type")
        .querySelectorAll(".pill-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      _libScanType = btn.dataset.val;
      document.getElementById("lib-clips-fields").style.display    = _libScanType === "clips"            ? "" : "none";
      document.getElementById("lib-template-fields").style.display = _libScanType === "template_frames" ? "" : "none";
    });
  });

  // Sensor mode pills
  document.getElementById("lib-sensor-mode").querySelectorAll(".pill-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.getElementById("lib-sensor-mode")
        .querySelectorAll(".pill-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      _libSensorMode = btn.dataset.val;
      document.getElementById("lib-sensor-fields").style.display = _libSensorMode === "sensor+clip" ? "" : "none";
    });
  });
```

- [ ] **Step 3: Update `renderLibraries` card body to two-zone layout**

In `renderLibraries`, replace the existing `lib-card-body` innerHTML section. The current template generates folder rows then a scan button directly in the card body. Wrap them in `.lib-zone1` and add the zone handle + zone2 below:

Replace this part of the template string (the `lib-card-body` div and its contents):

```js
      <div class="lib-card-body${isActive ? " open" : ""}">
        ${folders.map(p => { ... }).join("")}
        <button class="player-btn lib-scan-btn" disabled>...</button>
      </div>
```

With:

```js
      <div class="lib-card-body${isActive ? " open" : ""}">
        <div class="lib-zone1">
          ${folders.map(p => {
            const escapedP = esc(p);
            const parts = p.split("/");
            const label = esc(parts[parts.length - 2] || parts[parts.length - 1]);
            const checked = _activeBatchFolders.has(p);
            const frameCount = counts[p] ?? "?";
            return `<div class="lib-folder-row">
              <input type="checkbox" class="lib-folder-check" data-path="${escapedP}" ${checked ? "checked" : ""}>
              <span class="lib-folder-label" title="${escapedP}">${label}</span>
              <span class="lib-folder-frames">${frameCount} fr</span>
              <button class="player-btn lib-folder-remove" data-path="${escapedP}" title="Remove folder">&#10005;</button>
            </div>`;
          }).join("")}
          <button class="player-btn lib-scan-btn" disabled>&#9654; Scan with checked (${
            folders.filter(p => _activeBatchFolders.has(p)).length
          })</button>
        </div>
        <div class="lib-zone1-handle"></div>
        <div class="lib-zone2" style="display:none;">
          <div class="lib-zone2-header"></div>
          <div class="lib-zone2-frames"></div>
        </div>
      </div>
```

- [ ] **Step 4: Add folder row click handler + zone1 drag handle in `renderLibraries`**

After the existing event listener attachments (after the scan button click handler), add:

```js
    // Folder row click → load Zone 2
    const zone2El = card.querySelector(".lib-zone2");
    card.querySelectorAll(".lib-folder-row").forEach(row => {
      row.addEventListener("click", (e) => {
        if (e.target.closest(".lib-folder-check") || e.target.closest(".lib-folder-remove")) return;
        const path  = row.querySelector(".lib-folder-check").dataset.path;
        const label = row.querySelector(".lib-folder-label").textContent;
        card.querySelectorAll(".lib-folder-row").forEach(r => r.classList.remove("selected"));
        row.classList.add("selected");
        loadFolderFrames(path, label, zone2El);
      });
    });

    // Zone 1 drag handle
    const zone1El = card.querySelector(".lib-zone1");
    const handleEl = card.querySelector(".lib-zone1-handle");
    handleEl.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const startY = e.clientY;
      const startH = zone1El.offsetHeight;
      const onMove = (me) => {
        zone1El.style.height = Math.max(56, Math.min(224, startH + me.clientY - startY)) + "px";
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
```

- [ ] **Step 5: Update scan button click to dispatch on `_libScanType`**

Find the existing scan button listener:
```js
    card.querySelector(".lib-scan-btn").addEventListener("click", () => startBatchScan());
```
Replace with:
```js
    card.querySelector(".lib-scan-btn").addEventListener("click", () => {
      if (_libScanType === "template_frames") startBatchTemplateScan();
      else startBatchScan();
    });
```

- [ ] **Step 6: Update `startBatchScan` to pass `scan_mode` to backend**

In `startBatchScan`, update the params object:
```js
        params: {
          stride:      parseInt(document.getElementById("lib-scan-stride").value, 10),
          threshold:   parseFloat(document.getElementById("lib-scan-threshold").value),
          min_spacing: parseInt(document.getElementById("lib-scan-min-spacing").value, 10),
          fine_window: parseInt(document.getElementById("lib-scan-fine-window").value, 10),
          scan_mode:     _libSensorMode,
          trigger_value: parseInt(document.getElementById("lib-trigger-value").value, 10) || 14,
          sensor_margin: parseInt(document.getElementById("lib-sensor-margin").value, 10) || 25,
        },
```

- [ ] **Step 7: Commit**

```bash
git add clip-cutter/static/clip_cutter.js
git commit -m "feat: add scan type pills, two-zone card layout, folder row click dispatch"
```

---

### Task 8: JS — `startBatchTemplateScan` + `renderTemplateCandidateCards` + `showRethresholdBar` + `loadFolderFrames`

**Files:**
- Modify: `clip-cutter/static/clip_cutter.js`

- [ ] **Step 1: Add `startBatchTemplateScan`**

Add this function after `startBatchScan()` in `clip_cutter.js`:

```js
async function startBatchTemplateScan() {
  const video_paths = _batchQueue.size > 0 ? [..._batchQueue] : (selectedVideoPath ? [selectedVideoPath] : []);
  if (_activeBatchFolders.size === 0 || video_paths.length === 0) return;
  const template_dirs = [..._activeBatchFolders];
  setStatus(`Starting template scan: ${template_dirs.length} template source(s), ${video_paths.length} video(s)…`);
  const progressEl = document.getElementById("lib-scan-progress");
  const setProgress = (msg) => { progressEl.style.display = msg ? "" : "none"; progressEl.textContent = msg; };

  const oldBar = document.getElementById("rethreshold-bar");
  if (oldBar) oldBar.remove();

  try {
    const resp = await fetch("/clip-cutter/batch-template-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        template_dirs,
        video_paths,
        params: {
          scan_mode:     _libSensorMode,
          stride:        parseInt(document.getElementById("lib-scan-stride").value, 10),
          threshold:     parseFloat(document.getElementById("lib-scan-threshold").value),
          n_clusters:    parseInt(document.getElementById("lib-target-clusters").value, 10),
          trigger_value: parseInt(document.getElementById("lib-trigger-value").value, 10) || 14,
          sensor_margin: parseInt(document.getElementById("lib-sensor-margin").value, 10) || 25,
        },
      }),
    });
    if (!resp.ok) { setStatus("Template scan error"); return; }
    const { job_id } = await resp.json();
    _templateScanJobId = job_id;

    const es = new EventSource(`/clip-cutter/batch-template-scan/stream?job_id=${job_id}`);
    es.onmessage = (e) => {
      const job = JSON.parse(e.data);
      if (job.phase === "done") {
        es.close();
        setProgress("");
        const allCandidates = [];
        (job.results || []).forEach(r => {
          (r.candidates || []).forEach(c => allCandidates.push({ ...c, video_path: r.video_path }));
        });
        renderTemplateCandidateCards(allCandidates);
        if (allCandidates.length > 0) showRethresholdBar();
        setStatus(`Template scan done — ${allCandidates.length} candidate(s)`);
      } else if (job.phase === "error") {
        es.close();
        setProgress("");
        setStatus("Template scan error: " + job.error);
      } else {
        const msg = `${job.video || "…"} (${job.video_index || "?"}/${job.video_total || "?"}) — ${job.phase}`;
        setProgress(msg);
      }
    };
    es.onerror = () => { es.close(); setProgress(""); setStatus("Template scan stream error"); };
  } catch (err) {
    setProgress("");
    setStatus("Template scan error: " + err.message);
  }
}
```

- [ ] **Step 2: Add `renderTemplateCandidateCards`**

```js
function renderTemplateCandidateCards(candidates) {
  const list = document.getElementById("results-list");
  list.innerHTML = "";
  candidates.forEach((c) => {
    const videoName = c.video_path.split("/").pop().replace(/\.avi$/i, "");
    const card = document.createElement("div");
    card.className = "result-card";
    card.dataset.resultType = "template-candidate";
    const sensorBadge = _libSensorMode === "sensor+clip"
      ? `<span class="source-badge source-sensor-clip">sensor+clip</span>` : "";
    card.innerHTML = `
      <img class="result-thumb" src="/clip-cutter/frame?video=${encodeURIComponent(c.video_path)}&n=${c.frame_number - 1}" style="width:80px;height:60px;object-fit:cover;border-radius:3px;">
      <div class="result-info">
        <div class="result-title">${esc(videoName)}</div>
        <div class="result-sub">Frame ${c.frame_number} &middot; sim ${c.similarity.toFixed(2)}</div>
        ${sensorBadge}
        <div style="display:flex;gap:4px;margin-top:4px;">
          <button class="player-btn tc-add-btn" data-video="${esc(c.video_path)}" data-frame="${c.frame_number}">Add to template</button>
          <button class="player-btn tc-skip-btn">Skip</button>
        </div>
      </div>
    `;

    card.querySelector(".tc-add-btn").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        const r = await fetch("/clip-cutter/template-frame-add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_path: btn.dataset.video, frame_number: parseInt(btn.dataset.frame, 10) }),
        });
        if (r.ok) {
          const { count } = await r.json();
          btn.textContent = "Added";
          setStatus(`Frame ${btn.dataset.frame} added. Template now has ${count} frame(s).`);
          loadLibraries();
        } else {
          btn.disabled = false;
          setStatus("Error adding frame to template");
        }
      } catch (err) {
        btn.disabled = false;
        setStatus("Network error: " + err.message);
      }
    });

    card.querySelector(".tc-skip-btn").addEventListener("click", (e) => {
      e.currentTarget.closest(".result-card").remove();
    });

    list.appendChild(card);
  });
}
```

- [ ] **Step 3: Add `showRethresholdBar`**

```js
function showRethresholdBar() {
  const resultsList = document.getElementById("results-list");
  const bar = document.createElement("div");
  bar.id = "rethreshold-bar";
  bar.style.cssText =
    "display:flex;align-items:center;gap:8px;padding:6px 8px;" +
    "background:#1c2128;border:1px solid #444c56;border-radius:4px;margin-bottom:6px;";
  const initVal = document.getElementById("lib-scan-threshold").value;
  bar.innerHTML = `
    <span style="font-size:10px;color:#768390;">Threshold</span>
    <input type="range" id="rethreshold-slider" min="0" max="1" step="0.01" value="${initVal}" style="flex:1;">
    <span id="rethreshold-label" style="font-size:10px;color:#cdd9e5;min-width:32px;">${parseFloat(initVal).toFixed(2)}</span>
    <button class="player-btn" id="rethreshold-apply">Apply</button>
  `;
  resultsList.parentElement.insertBefore(bar, resultsList);

  document.getElementById("rethreshold-slider").addEventListener("input", (e) => {
    document.getElementById("rethreshold-label").textContent = parseFloat(e.target.value).toFixed(2);
  });

  document.getElementById("rethreshold-apply").addEventListener("click", async () => {
    if (!_templateScanJobId) return;
    const threshold  = parseFloat(document.getElementById("rethreshold-slider").value);
    const n_clusters = parseInt(document.getElementById("lib-target-clusters").value, 10);
    try {
      const r = await fetch(`/clip-cutter/batch-template-scan/${_templateScanJobId}/recluster`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threshold, n_clusters }),
      });
      if (!r.ok) { setStatus("Recluster error"); return; }
      const { results } = await r.json();
      const allCandidates = [];
      (results || []).forEach(rv => {
        (rv.candidates || []).forEach(c => allCandidates.push({ ...c, video_path: rv.video_path }));
      });
      renderTemplateCandidateCards(allCandidates);
    } catch (err) {
      setStatus("Recluster error: " + err.message);
    }
  });
}
```

- [ ] **Step 4: Add `loadFolderFrames`**

```js
async function loadFolderFrames(path, label, zone2El) {
  zone2El.style.display = "";
  const headerEl = zone2El.querySelector(".lib-zone2-header");
  const framesEl = zone2El.querySelector(".lib-zone2-frames");
  headerEl.textContent = `${label} — loading…`;
  framesEl.innerHTML = "";

  try {
    const r = await fetch(`/clip-cutter/library-folder-frames?path=${encodeURIComponent(path)}`);
    if (!r.ok) { headerEl.textContent = "Error loading frames"; return; }
    const { frames, count } = await r.json();
    headerEl.textContent = `${label} — ${count} frame${count !== 1 ? "s" : ""}`;

    frames.forEach(f => {
      const row = document.createElement("div");
      row.className = "lib-frame-row";
      row.innerHTML = `
        <img class="lib-frame-thumb" src="/clip-cutter/frame?video=${encodeURIComponent(f.video_path)}&n=${f.frame_number - 1}" width="48" height="36">
        <span class="lib-frame-num">fr ${f.frame_number}</span>
        <button class="player-btn lib-frame-view">View</button>
        <button class="player-btn lib-frame-del">Del</button>
      `;

      row.querySelector(".lib-frame-view").addEventListener("click", async () => {
        await openPlayer({ mode: "template", videoPath: f.video_path });
        _epLoadFrame(f.frame_number - 1);  // navigate to this specific template frame
      });

      row.querySelector(".lib-frame-del").addEventListener("click", async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        const r2 = await fetch("/clip-cutter/library-folder-frames", {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path, frame_number: f.frame_number }),
        });
        if (r2.ok) {
          const { count: newCount } = await r2.json();
          row.remove();
          headerEl.textContent = `${label} — ${newCount} frame${newCount !== 1 ? "s" : ""}`;
          loadLibraries();
        } else {
          btn.disabled = false;
        }
      });

      framesEl.appendChild(row);
    });
  } catch (err) {
    headerEl.textContent = "Error: " + err.message;
  }
}
```

- [ ] **Step 5: Remove the old `lib-scan-progress` div from its current location in the HTML**

The `#lib-scan-progress` element is now inside `#lib-settings-body` (Task 6 HTML). If it existed elsewhere in the HTML, remove the duplicate. Verify the element ID is unique.

```bash
grep -n "lib-scan-progress" clip-cutter/templates/clip_cutter.html
```

- [ ] **Step 6: Run the full test suite**

```bash
cd clip-cutter && pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass (or pre-existing failures only).

- [ ] **Step 7: Commit**

```bash
git add clip-cutter/static/clip_cutter.js
git commit -m "feat: add startBatchTemplateScan, renderTemplateCandidateCards, showRethresholdBar, loadFolderFrames"
```

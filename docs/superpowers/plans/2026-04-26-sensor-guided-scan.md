# Sensor-Guided Scan, GPU Performance & UI Parameters — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace full-video CLIP scan with a sensor-first pipeline that uses `frame_line_status` to locate reaching events, supplemented by a targeted CLIP gap scan, with sequential frame reading + GPU batching for speed, and per-scan parameters exposed in the UI.

**Architecture:** `find_sensor_triggers()` parses the CSV alongside the video to get rising-edge frame numbers and a covered-frame set; `scan_video_sensor_guided()` runs CLIP only on the uncovered gaps, merges with sensor candidates, then fine-scans all merged candidates; `get_similarity_curve()` is refactored to accept an explicit positions array and uses sequential reads + a prefetch thread to overlap I/O and GPU work. Routes extract scan params from the POST body and choose the sensor-guided or legacy scan path. The HTML/JS gains a collapsible settings panel and a 4-step pipeline strip.

**Tech Stack:** Python, OpenCV, sentence-transformers (CLIP ViT-B/32), scipy (binary_dilation, gaussian_filter1d, find_peaks), pandas, Flask SSE, Playwright (frontend tests).

---

## File Map

| File | Change |
|------|--------|
| `clip-cutter/config.py` | Add `SENSOR_TRIGGER_VALUE=14`, `SENSOR_MARGIN=25`; raise `SCAN_BATCH_SIZE` to 256 |
| `clip-cutter/processor.py` | Add `find_sensor_triggers()`; add `scan_video_sensor_guided()`; refactor `get_similarity_curve()` (positions kwarg, sequential reads, threading) |
| `clip-cutter/routes.py` | `_run_scan` accepts `params` dict; `start_scan` extracts params; CSV detection routes to correct function |
| `clip-cutter/templates/clip_cutter.html` | 4-phase pipeline strip (sensor_parse first); collapsible settings panel with Sensor/CLIP tabs |
| `clip-cutter/static/clip_cutter.js` | `startScan` sends params; `updateProgress` handles sensor_parse phase; `buildResultCard` renders source badge; settings toggle/tabs/reset |
| `clip-cutter/tests/test_sensor.py` | New file — backend tests for `find_sensor_triggers` and `scan_video_sensor_guided` |
| `clip-cutter/tests/test_ui.py` | Add tests: settings panel, source badge, params in POST body |

---

### Task 1: Config constants

**Files:**
- Modify: `clip-cutter/config.py`

- [ ] **Step 1: Update config.py**

Replace the Scanning section (lines 36–40 of `clip-cutter/config.py`):

```python
# --- Scanning ---
SCAN_STRIDE = 10           # extract every Nth frame for coarse pass
SCAN_BATCH_SIZE = 256      # CLIP batch size (RTX 5090 handles 256 easily)
SIMILARITY_THRESHOLD = 0.70
MIN_PEAK_SPACING = 900     # minimum frames between two detections (original frame units)
FINE_SCAN_WINDOW = 50      # ± frames around coarse peak for fine pass

# --- Sensor-guided scan ---
SENSOR_TRIGGER_VALUE = 14  # frame_line_status value indicating sensor trigger
SENSOR_MARGIN = 25         # frames to dilate each side of trigger burst
```

- [ ] **Step 2: Verify Python parses the file**

```bash
cd clip-cutter && python -c "import config; print(config.SCAN_BATCH_SIZE, config.SENSOR_TRIGGER_VALUE, config.SENSOR_MARGIN)"
```

Expected output: `256 14 25`

- [ ] **Step 3: Commit**

```bash
git add clip-cutter/config.py
git commit -m "config: increase SCAN_BATCH_SIZE to 256, add sensor scan constants"
```

---

### Task 2: `find_sensor_triggers()` — TDD

**Files:**
- Create: `clip-cutter/tests/test_sensor.py`
- Modify: `clip-cutter/processor.py`

- [ ] **Step 1: Write failing tests**

Create `clip-cutter/tests/test_sensor.py`:

```python
"""Backend tests for sensor-trigger parsing."""
import numpy as np
import pandas as pd
import pytest
import processor


def _make_csv(tmp_path, trigger_frames, total=100, trigger_value=14):
    data = {
        "frame_number": list(range(1, total + 1)),
        "frame_line_status": [
            trigger_value if i in trigger_frames else 0
            for i in range(1, total + 1)
        ],
    }
    path = tmp_path / "test.csv"
    pd.DataFrame(data).to_csv(path, index=False)
    return path


def test_find_sensor_triggers_single_burst(tmp_path):
    """Frames 41-50 triggered, margin=5 → one rising edge at frame 36."""
    csv = _make_csv(tmp_path, set(range(41, 51)))
    rising, covered = processor.find_sensor_triggers(csv, trigger_value=14, sensor_margin=5)
    # dilated: 41-5=36 to 50+5=55
    assert rising == [36]
    assert 36 in covered
    assert 55 in covered
    assert 35 not in covered
    assert 56 not in covered


def test_find_sensor_triggers_closes_intra_burst_gap(tmp_path):
    """Two bursts with a 4-frame gap, margin=3 → merged into one rising edge."""
    # Burst1: 10-14, Burst2: 19-23  (gap: 15-18, 4 frames)
    triggered = set(range(10, 15)) | set(range(19, 24))
    csv = _make_csv(tmp_path, triggered, total=50)
    rising, covered = processor.find_sensor_triggers(csv, trigger_value=14, sensor_margin=3)
    # Burst1 dilated: 7-17, Burst2 dilated: 16-26 → overlap at 16-17 → merged 7-26
    assert len(rising) == 1
    assert rising[0] == 7


def test_find_sensor_triggers_two_separate_bursts(tmp_path):
    """Two bursts far apart → two rising edges."""
    triggered = set(range(10, 15)) | set(range(40, 45))
    csv = _make_csv(tmp_path, triggered, total=60)
    rising, covered = processor.find_sensor_triggers(csv, trigger_value=14, sensor_margin=3)
    # Burst1 dilated: 7-17, Burst2 dilated: 37-47. No overlap.
    assert len(rising) == 2
    assert rising[0] < rising[1]


def test_find_sensor_triggers_empty_no_triggers(tmp_path):
    """No sensor triggers → empty results."""
    csv = _make_csv(tmp_path, set())
    rising, covered = processor.find_sensor_triggers(csv, trigger_value=14, sensor_margin=5)
    assert rising == []
    assert covered == set()


def test_find_sensor_triggers_custom_trigger_value(tmp_path):
    """Custom trigger_value=7 is respected."""
    data = {
        "frame_number": list(range(1, 21)),
        "frame_line_status": [7 if i in range(8, 13) else 0 for i in range(1, 21)],
    }
    csv = tmp_path / "t.csv"
    pd.DataFrame(data).to_csv(csv, index=False)
    rising, covered = processor.find_sensor_triggers(csv, trigger_value=7, sensor_margin=2)
    # triggered: 8-12 (indices 7-11). dilated ±2: indices 5-13 → frames 6-14
    assert len(rising) == 1
    assert rising[0] == 6
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd clip-cutter && python -m pytest tests/test_sensor.py -v 2>&1 | head -30
```

Expected: `AttributeError: module 'processor' has no attribute 'find_sensor_triggers'`

- [ ] **Step 3: Implement `find_sensor_triggers` in processor.py**

Add after line 13 (`from scipy.signal import find_peaks`):

```python
from scipy.ndimage import binary_dilation
```

Add after the `smooth_curve` function (after line 198 in current `processor.py`):

```python
def find_sensor_triggers(
    csv_path: Path | str,
    trigger_value: int = 14,
    sensor_margin: int = 25,
) -> tuple[list[int], set[int]]:
    """
    Parse frame_line_status column to find sensor rising edges.

    Returns:
        rising_edge_frame_numbers: 1-based frame numbers at each rising edge
          of the dilated trigger burst — one per reaching event.
        covered_frame_set: all 1-based frame numbers inside any dilated burst,
          used to exclude them from the gap CLIP scan.
    """
    import pandas as pd

    df = pd.read_csv(csv_path, usecols=["frame_number", "frame_line_status"])
    frames = df["frame_number"].to_numpy(dtype=np.int64)
    status = df["frame_line_status"].to_numpy(dtype=np.int64)

    triggered = (status == trigger_value)
    structure = np.ones(2 * sensor_margin + 1, dtype=bool)
    dilated = binary_dilation(triggered, structure=structure)

    # Rising edges: False→True transitions (first element is a rising edge if True)
    rising_mask = np.zeros(len(dilated), dtype=bool)
    rising_mask[0] = dilated[0]
    rising_mask[1:] = dilated[1:] & ~dilated[:-1]

    rising_frame_numbers = [int(frames[i]) for i in np.where(rising_mask)[0]]
    covered_frame_set = {int(frames[i]) for i in np.where(dilated)[0]}

    return rising_frame_numbers, covered_frame_set
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd clip-cutter && python -m pytest tests/test_sensor.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add clip-cutter/processor.py clip-cutter/tests/test_sensor.py
git commit -m "feat: add find_sensor_triggers() with binary dilation"
```

---

### Task 3: Refactor `get_similarity_curve()` — sequential reads, threading, positions kwarg

**Files:**
- Modify: `clip-cutter/processor.py`

Context: the current implementation does `cap.set(CAP_PROP_POS_FRAMES, pos)` before every frame, forcing I-frame seeks. Replacing with sequential reads (grab to skip non-sampled frames) eliminates the seek overhead. A prefetch thread overlaps disk I/O with GPU embedding. The new `positions` kwarg lets callers supply an arbitrary frame list (used by the gap scan).

- [ ] **Step 1: Add a test that verifies identical output before/after the refactor**

Add to `clip-cutter/tests/test_sensor.py`:

```python
import cv2


@pytest.fixture
def small_avi(tmp_path):
    """20-frame 64×64 AVI with distinct blue channel per frame."""
    path = tmp_path / "small.avi"
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 64))
    for i in range(20):
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        frame[:, :, 0] = i * 12
        out.write(frame)
    out.release()
    return path


def test_get_similarity_curve_positions_kwarg_matches_stride(small_avi):
    """positions kwarg returns same indices/sims as stride-based scan."""
    import numpy as np
    template = np.ones(512, dtype=np.float32)
    template /= np.linalg.norm(template)

    # stride-based (original behaviour)
    idx_s, sim_s = processor.get_similarity_curve(small_avi, template, stride=5, batch_size=4)

    # explicit positions (should be identical)
    explicit = np.arange(0, 20, 5)
    idx_p, sim_p = processor.get_similarity_curve(
        small_avi, template, stride=5, batch_size=4, positions=explicit
    )

    np.testing.assert_array_equal(idx_s, idx_p)
    np.testing.assert_allclose(sim_s, sim_p, atol=1e-5)
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd clip-cutter && python -m pytest tests/test_sensor.py::test_get_similarity_curve_positions_kwarg_matches_stride -v 2>&1 | head -20
```

Expected: `TypeError: get_similarity_curve() got an unexpected keyword argument 'positions'`

- [ ] **Step 3: Replace `get_similarity_curve` in processor.py**

Replace the entire `get_similarity_curve` function (lines 218–252 in current `processor.py`) with:

```python
def get_similarity_curve(
    video_path: Path | str,
    template_emb: np.ndarray,
    stride: int = 10,
    batch_size: int = 64,
    progress_cb=None,
    positions: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Coarse scan: embed sampled frames, compute cosine similarity against template.

    If positions is provided, uses those 0-based frame numbers exactly.
    Otherwise samples every stride-th frame from the video.

    Returns (frame_indices, similarities) as 1D numpy arrays (0-based cv2_pos).
    Uses sequential reads (cap.grab() to skip) + a prefetch thread to overlap
    disk I/O with GPU embedding.
    progress_cb(current, total) is called after each batch if provided.
    """
    from concurrent.futures import ThreadPoolExecutor

    video_path_str = str(video_path)

    cap = cv2.VideoCapture(video_path_str)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    if positions is None:
        all_positions = np.arange(0, total_frames, stride, dtype=np.int64)
    else:
        all_positions = np.asarray(positions, dtype=np.int64)

    similarities = np.zeros(len(all_positions), dtype=np.float32)

    if len(all_positions) == 0:
        return all_positions, similarities

    def read_batch(batch_positions):
        """Open a fresh VideoCapture and read the batch using sequential reads."""
        if len(batch_positions) == 0:
            return []
        vcap = cv2.VideoCapture(video_path_str)
        vcap.set(cv2.CAP_PROP_POS_FRAMES, int(batch_positions[0]))
        cur = int(batch_positions[0])
        frames = []
        for target in batch_positions:
            target = int(target)
            while cur < target:
                vcap.grab()
                cur += 1
            ret, frame = vcap.read()
            cur += 1
            frames.append(frame if ret else np.zeros((64, 64, 3), dtype=np.uint8))
        vcap.release()
        return frames

    processed = 0
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(read_batch, all_positions[:batch_size])

        for batch_start in range(0, len(all_positions), batch_size):
            batch_pos = all_positions[batch_start : batch_start + batch_size]
            frames = future.result()

            next_start = batch_start + batch_size
            future = pool.submit(
                read_batch, all_positions[next_start : next_start + batch_size]
            )

            embs = embed_frames_batch(frames)
            sims = embs @ template_emb
            n = len(batch_pos)
            similarities[batch_start : batch_start + n] = sims[:n]
            processed += n
            if progress_cb:
                progress_cb(processed, len(all_positions))

    return all_positions, similarities
```

- [ ] **Step 4: Run all backend tests**

```bash
cd clip-cutter && python -m pytest tests/test_sensor.py tests/test_frame_routes.py -v
```

Expected: all tests pass (the new test plus the 5 from Task 2 plus the 12 frame-route tests).

- [ ] **Step 5: Commit**

```bash
git add clip-cutter/processor.py clip-cutter/tests/test_sensor.py
git commit -m "perf: sequential frame reads + prefetch thread + positions kwarg in get_similarity_curve"
```

---

### Task 4: `scan_video_sensor_guided()` — TDD

**Files:**
- Modify: `clip-cutter/processor.py`
- Modify: `clip-cutter/tests/test_sensor.py`

- [ ] **Step 1: Write failing tests**

Append to `clip-cutter/tests/test_sensor.py`:

```python
def test_scan_video_sensor_guided_excludes_covered_frames(tmp_path, monkeypatch):
    """Gap CLIP scan skips frames covered by sensor bursts."""
    # 30-frame AVI
    avi = tmp_path / "v.avi"
    out = cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 64))
    for _ in range(30):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    # Triggered: frames 11-20; margin=2 → covered: frames 9-22
    data = {
        "frame_number": list(range(1, 31)),
        "frame_line_status": [14 if 11 <= i <= 20 else 0 for i in range(1, 31)],
    }
    csv = tmp_path / "v.csv"
    pd.DataFrame(data).to_csv(csv, index=False)

    captured = {}

    def mock_gsc(vp, temb, stride=10, batch_size=256, progress_cb=None, positions=None):
        captured["positions"] = list(positions) if positions is not None else None
        return np.array([], dtype=np.int64), np.array([], dtype=np.float32)

    monkeypatch.setattr(processor, "get_similarity_curve", mock_gsc)
    monkeypatch.setattr(processor, "fine_scan", lambda v, t, pos, window=50: (pos, 0.85))

    template = np.ones(512, dtype=np.float32)
    template /= np.linalg.norm(template)

    processor.scan_video_sensor_guided(
        avi, csv, template, trigger_value=14, sensor_margin=2, stride=5, threshold=0.70
    )

    # stride=5, total=30 → positions 0,5,10,15,20,25
    # covered (1-based): 9..22 → covered (0-based): 8..21
    # gap positions (pos+1 not in covered_set):
    #   pos=0 → fr1: ok; pos=5 → fr6: ok; pos=10 → fr11: covered;
    #   pos=15 → fr16: covered; pos=20 → fr21: covered; pos=25 → fr26: ok
    assert captured["positions"] is not None
    assert set(captured["positions"]) == {0, 5, 25}


def test_scan_video_sensor_guided_sensor_source_tag(tmp_path, monkeypatch):
    """Sensor candidate with fine_sim >= threshold gets source='sensor+clip'."""
    avi = tmp_path / "v.avi"
    out = cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 64))
    for _ in range(30):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    data = {
        "frame_number": list(range(1, 31)),
        "frame_line_status": [14 if i == 15 else 0 for i in range(1, 31)],
    }
    csv = tmp_path / "v.csv"
    pd.DataFrame(data).to_csv(csv, index=False)

    monkeypatch.setattr(
        processor, "get_similarity_curve",
        lambda *a, **kw: (np.array([], dtype=np.int64), np.array([], dtype=np.float32)),
    )
    monkeypatch.setattr(processor, "fine_scan", lambda v, t, pos, window=50: (pos, 0.85))

    template = np.ones(512, dtype=np.float32)
    template /= np.linalg.norm(template)

    results = processor.scan_video_sensor_guided(
        avi, csv, template, trigger_value=14, sensor_margin=0, threshold=0.70
    )
    assert len(results) == 1
    assert results[0]["source"] == "sensor+clip"
    assert results[0]["frame_number"] == results[0]["cv2_pos"] + 1


def test_scan_video_sensor_guided_low_sim_sensor_only(tmp_path, monkeypatch):
    """Sensor candidate with fine_sim < threshold gets source='sensor_only'."""
    avi = tmp_path / "v.avi"
    out = cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 64))
    for _ in range(30):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    data = {
        "frame_number": list(range(1, 31)),
        "frame_line_status": [14 if i == 15 else 0 for i in range(1, 31)],
    }
    csv = tmp_path / "v.csv"
    pd.DataFrame(data).to_csv(csv, index=False)

    monkeypatch.setattr(
        processor, "get_similarity_curve",
        lambda *a, **kw: (np.array([], dtype=np.int64), np.array([], dtype=np.float32)),
    )
    monkeypatch.setattr(processor, "fine_scan", lambda v, t, pos, window=50: (pos, 0.50))

    template = np.ones(512, dtype=np.float32)
    template /= np.linalg.norm(template)

    results = processor.scan_video_sensor_guided(
        avi, csv, template, trigger_value=14, sensor_margin=0, threshold=0.70
    )
    assert len(results) == 1
    assert results[0]["source"] == "sensor_only"


def test_scan_video_sensor_guided_clip_only_source(tmp_path, monkeypatch):
    """CLIP gap peak with no nearby sensor gets source='clip_only'."""
    avi = tmp_path / "v.avi"
    out = cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 64))
    for _ in range(30):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    # No triggers at all
    data = {
        "frame_number": list(range(1, 31)),
        "frame_line_status": [0] * 30,
    }
    csv = tmp_path / "v.csv"
    pd.DataFrame(data).to_csv(csv, index=False)

    # One CLIP gap peak at position 10
    monkeypatch.setattr(
        processor, "get_similarity_curve",
        lambda *a, **kw: (np.array([10], dtype=np.int64), np.array([0.80], dtype=np.float32)),
    )
    monkeypatch.setattr(processor, "smooth_curve", lambda arr, sigma=3.0: arr)
    monkeypatch.setattr(processor, "find_peaks_in_curve", lambda s, fi, th, ms: [10])
    monkeypatch.setattr(processor, "fine_scan", lambda v, t, pos, window=50: (pos, 0.80))

    template = np.ones(512, dtype=np.float32)
    template /= np.linalg.norm(template)

    results = processor.scan_video_sensor_guided(
        avi, csv, template, trigger_value=14, sensor_margin=0, threshold=0.70
    )
    assert len(results) == 1
    assert results[0]["source"] == "clip_only"


def test_scan_video_sensor_guided_dedup_sensor_wins(tmp_path, monkeypatch):
    """When sensor and CLIP peak are within min_spacing//2, sensor candidate wins."""
    avi = tmp_path / "v.avi"
    out = cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 64))
    for _ in range(30):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    # Sensor at frame 15 (cv2_pos=14); CLIP peak at cv2_pos=16 — within min_spacing//2=10
    data = {
        "frame_number": list(range(1, 31)),
        "frame_line_status": [14 if i == 15 else 0 for i in range(1, 31)],
    }
    csv = tmp_path / "v.csv"
    pd.DataFrame(data).to_csv(csv, index=False)

    monkeypatch.setattr(
        processor, "get_similarity_curve",
        lambda *a, **kw: (np.array([16], dtype=np.int64), np.array([0.80], dtype=np.float32)),
    )
    monkeypatch.setattr(processor, "smooth_curve", lambda arr, sigma=3.0: arr)
    monkeypatch.setattr(processor, "find_peaks_in_curve", lambda s, fi, th, ms: [16])
    monkeypatch.setattr(processor, "fine_scan", lambda v, t, pos, window=50: (pos, 0.85))

    template = np.ones(512, dtype=np.float32)
    template /= np.linalg.norm(template)

    results = processor.scan_video_sensor_guided(
        avi, csv, template,
        trigger_value=14, sensor_margin=0, threshold=0.70, min_spacing=20
    )
    # Should be 1 result (deduped), sourced from sensor
    assert len(results) == 1
    assert results[0]["source"] == "sensor+clip"
    assert results[0]["cv2_pos"] == 14  # sensor pos wins
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd clip-cutter && python -m pytest tests/test_sensor.py -k "sensor_guided" -v 2>&1 | head -20
```

Expected: `AttributeError: module 'processor' has no attribute 'scan_video_sensor_guided'`

- [ ] **Step 3: Implement `scan_video_sensor_guided` in processor.py**

Add after the `scan_video` function (after line 328):

```python
def scan_video_sensor_guided(
    video_path: Path | str,
    csv_path: Path | str,
    template_emb: np.ndarray,
    trigger_value: int = 14,
    sensor_margin: int = 25,
    stride: int = 10,
    threshold: float = 0.70,
    min_spacing: int = 900,
    fine_window: int = 50,
    batch_size: int = 256,
    smooth_sigma: float = 3.0,
    progress_cb=None,
    phase_cb=None,
) -> list[dict]:
    """
    Sensor-guided scan pipeline. Returns list of dicts:
      {cv2_pos, frame_number (1-based), similarity, source}

    source values:
      "sensor+clip" — sensor trigger, fine scan similarity >= threshold
      "sensor_only" — sensor trigger, fine scan similarity < threshold
      "clip_only"   — CLIP gap peak, no nearby sensor trigger
    """
    # Phase 0: sensor parse
    if phase_cb:
        phase_cb("sensor_parse", 0, 1)
    sensor_frames, covered_set = find_sensor_triggers(csv_path, trigger_value, sensor_margin)
    if phase_cb:
        phase_cb("sensor_parse", 1, 1)

    # Phase 1: gap CLIP scan — only frames NOT covered by sensor bursts
    if phase_cb:
        phase_cb("coarse", 0, 1)

    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    all_positions = np.arange(0, total_frames, stride, dtype=np.int64)
    # covered_set holds 1-based frame numbers; 0-based pos → 1-based = pos+1
    gap_positions = np.array(
        [p for p in all_positions if (int(p) + 1) not in covered_set], dtype=np.int64
    )

    if len(gap_positions) > 0:
        gap_indices, gap_sims = get_similarity_curve(
            video_path, template_emb,
            stride=stride, batch_size=batch_size,
            progress_cb=progress_cb, positions=gap_positions,
        )
    else:
        gap_indices = np.array([], dtype=np.int64)
        gap_sims = np.array([], dtype=np.float32)

    # Phase 2: peak detection on gap curve
    if phase_cb:
        phase_cb("peak_detection", 0, 1)

    clip_peaks: list[int] = []
    if len(gap_sims) > 0:
        smoothed = smooth_curve(gap_sims, sigma=smooth_sigma)
        clip_peaks = find_peaks_in_curve(smoothed, gap_indices, threshold, min_spacing)

    # Merge sensor rising edges (1-based → 0-based) with CLIP peaks
    candidates: list[tuple[int, str]] = []
    for sf in sensor_frames:
        candidates.append((sf - 1, "sensor"))
    for cp in clip_peaks:
        candidates.append((cp, "clip"))
    candidates.sort(key=lambda x: x[0])

    # Deduplicate: within min_spacing//2 frames, sensor candidate wins
    dedup: list[tuple[int, str]] = []
    half = min_spacing // 2
    for pos, src in candidates:
        if dedup and abs(pos - dedup[-1][0]) < half:
            prev_pos, prev_src = dedup[-1]
            if src == "sensor" and prev_src != "sensor":
                dedup[-1] = (pos, src)
        else:
            dedup.append((pos, src))

    # Phase 3: fine scan
    if phase_cb:
        phase_cb("fine", 0, max(len(dedup), 1))

    results = []
    for i, (coarse_pos, src) in enumerate(dedup):
        exact_pos, fine_sim = fine_scan(video_path, template_emb, coarse_pos, window=fine_window)
        if src == "sensor":
            source_tag = "sensor+clip" if fine_sim >= threshold else "sensor_only"
        else:
            source_tag = "clip_only"
        results.append(
            {
                "cv2_pos": exact_pos,
                "frame_number": exact_pos + 1,
                "similarity": round(fine_sim, 4),
                "source": source_tag,
            }
        )
        if phase_cb:
            phase_cb("fine", i + 1, len(dedup))

    return results
```

- [ ] **Step 4: Run all sensor tests**

```bash
cd clip-cutter && python -m pytest tests/test_sensor.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add clip-cutter/processor.py clip-cutter/tests/test_sensor.py
git commit -m "feat: add scan_video_sensor_guided() with sensor+CLIP pipeline"
```

---

### Task 5: Routes — params from POST body, CSV detection, 4-phase SSE

**Files:**
- Modify: `clip-cutter/routes.py`

- [ ] **Step 1: Update `_run_scan` to accept params and route by CSV**

Replace the `_run_scan` function (lines 162–208 in current `routes.py`) with:

```python
def _run_scan(job_id: str, video_path: str, template_emb, params: dict):
    stride        = params.get("stride", config.SCAN_STRIDE)
    threshold     = params.get("threshold", config.SIMILARITY_THRESHOLD)
    min_spacing   = params.get("min_spacing", config.MIN_PEAK_SPACING)
    fine_window   = params.get("fine_window", config.FINE_SCAN_WINDOW)
    trigger_value = params.get("trigger_value", config.SENSOR_TRIGGER_VALUE)
    sensor_margin = params.get("sensor_margin", config.SENSOR_MARGIN)

    def progress_cb(current, total):
        with _jobs_lock:
            _scan_jobs[job_id]["current"] = current
            _scan_jobs[job_id]["total"] = total

    def phase_cb(phase, current, total):
        with _jobs_lock:
            _scan_jobs[job_id]["phase"] = phase
            _scan_jobs[job_id]["current"] = current
            _scan_jobs[job_id]["total"] = total

    try:
        csv_path = Path(video_path).with_suffix(".csv")
        if csv_path.exists():
            detections = processor.scan_video_sensor_guided(
                video_path, csv_path, template_emb,
                trigger_value=trigger_value,
                sensor_margin=sensor_margin,
                stride=stride,
                threshold=threshold,
                min_spacing=min_spacing,
                fine_window=fine_window,
                batch_size=config.SCAN_BATCH_SIZE,
                progress_cb=progress_cb,
                phase_cb=phase_cb,
            )
        else:
            detections = processor.scan_video(
                video_path, template_emb,
                stride=stride,
                threshold=threshold,
                min_spacing=min_spacing,
                fine_window=fine_window,
                batch_size=config.SCAN_BATCH_SIZE,
                progress_cb=progress_cb,
                phase_cb=phase_cb,
            )

        known = processor.get_known_key_frames(config.TRAINING_CLIPS_DIR)
        for d in detections:
            kf = d["frame_number"]
            match = next(
                (name for kf_known, name in known.items() if abs(kf - kf_known) <= 5),
                None,
            )
            d["known_match"] = match
            d["status"] = "pending"

        with _state_lock:
            template_frame_count = len(_state["frames"])
        processor.save_detections(
            video_path, detections, template_frame_count, config.DETECTIONS_DIR
        )

        with _jobs_lock:
            _scan_jobs[job_id]["status"] = "done"
            _scan_jobs[job_id]["detections"] = detections
    except Exception as exc:
        with _jobs_lock:
            _scan_jobs[job_id]["status"] = "error"
            _scan_jobs[job_id]["error"] = str(exc)
```

- [ ] **Step 2: Update `start_scan` to extract params and pass to thread**

Replace the `start_scan` route (lines 211–234):

```python
@bp.route("/scan", methods=["POST"])
def start_scan():
    body = request.get_json(force=True)
    video_path = body.get("video_path")
    if not video_path:
        return jsonify({"error": "video_path required"}), 400
    with _state_lock:
        mean_embedding = _state["mean_embedding"]
    if mean_embedding is None:
        return jsonify({"error": "template is empty — run /template/init first"}), 422

    params = body.get("params", {})

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _scan_jobs[job_id] = {
            "status": "running", "phase": "starting",
            "current": 0, "total": 1, "detections": [], "error": None,
        }

    template_emb = mean_embedding.copy()
    thread = threading.Thread(
        target=_run_scan, args=(job_id, video_path, template_emb, params), daemon=True
    )
    thread.start()
    return jsonify({"job_id": job_id})
```

- [ ] **Step 3: Verify the app still starts**

```bash
cd clip-cutter && python -c "from app import create_app; app = create_app(); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add clip-cutter/routes.py
git commit -m "feat: routes accept per-scan params, detect CSV for sensor-guided path"
```

---

### Task 6: HTML — 4-phase pipeline strip + scan settings panel

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html`

- [ ] **Step 1: Replace the pipeline strip HTML**

In `clip_cutter.html`, replace the `<div id="pipeline-steps">` block (lines 137–150) with the 4-phase version that has "Sensor parse" first:

```html
      <div id="pipeline-steps">
        <div class="pipeline-step" data-phase="sensor_parse">
          <div class="step-dot"></div>
          <span class="step-label">Sensor parse</span>
        </div>
        <div class="pipeline-connector" data-after="sensor_parse"></div>
        <div class="pipeline-step" data-phase="coarse">
          <div class="step-dot"></div>
          <span class="step-label">Coarse CLIP</span>
        </div>
        <div class="pipeline-connector" data-after="coarse"></div>
        <div class="pipeline-step" data-phase="peak_detection">
          <div class="step-dot"></div>
          <span class="step-label">Peaks</span>
        </div>
        <div class="pipeline-connector" data-after="peak_detection"></div>
        <div class="pipeline-step" data-phase="fine">
          <div class="step-dot"></div>
          <span class="step-label">Fine scan</span>
        </div>
      </div>
```

- [ ] **Step 2: Add settings panel CSS**

Add these rules inside the `<style>` block, after `.badge-pending { ... }` (before `#scan-btn`):

```css
/* Scan settings panel */
#scan-settings { margin-top: 8px; }
.settings-toggle-btn { width: 100%; text-align: left; padding: 4px 8px; background: #1c2128; border: 1px solid #30363d; border-radius: 4px; color: #cdd9e5; font-size: 11px; cursor: pointer; }
.settings-toggle-btn:hover { background: #30363d; }
#settings-body { background: #161b22; border: 1px solid #30363d; border-radius: 4px; margin-top: 4px; padding: 8px; }
.settings-tabs { display: flex; gap: 4px; margin-bottom: 8px; }
.tab-btn { font-size: 10px; padding: 2px 10px; border-radius: 3px; cursor: pointer; border: 1px solid #30363d; background: transparent; color: #768390; }
.tab-btn.active { background: #1f6feb22; border-color: #1f6feb; color: #cdd9e5; }
.tab-panel { display: flex; flex-direction: column; gap: 6px; }
.settings-row { display: flex; align-items: center; gap: 8px; font-size: 11px; color: #cdd9e5; }
.settings-row label { color: #768390; font-size: 10px; min-width: 110px; }
.settings-row input[type="number"] { width: 64px; padding: 2px 4px; background: #0d1117; border: 1px solid #30363d; border-radius: 3px; color: #cdd9e5; font-size: 11px; }
.settings-row input[type="range"] { flex: 1; accent-color: #1f6feb; }
.settings-footer { display: flex; justify-content: flex-end; margin-top: 8px; }
```

- [ ] **Step 3: Add settings panel HTML**

In `clip_cutter.html`, replace the existing `<button id="scan-btn" ...>` line (line 133) with:

```html
      <div id="scan-settings">
        <button class="settings-toggle-btn" id="settings-toggle">&#9881; Scan settings &#9660;</button>
        <div id="settings-body" style="display:none;">
          <div class="settings-tabs">
            <button class="tab-btn active" data-tab="sensor">Sensor</button>
            <button class="tab-btn" data-tab="clip">CLIP</button>
          </div>
          <div id="tab-sensor" class="tab-panel">
            <div class="settings-row">
              <label>Trigger value</label>
              <input type="number" id="trigger-value" value="14" min="0" max="255">
            </div>
            <div class="settings-row">
              <label>Sensor margin</label>
              <input type="number" id="sensor-margin" value="25" min="0" max="200">
              <span style="font-size:10px;color:#768390;">frames each side</span>
            </div>
          </div>
          <div id="tab-clip" class="tab-panel" style="display:none;">
            <div class="settings-row">
              <label>Coarse stride</label>
              <input type="number" id="scan-stride" value="10" min="1" max="100">
            </div>
            <div class="settings-row">
              <label>Similarity threshold</label>
              <input type="range" id="scan-threshold" min="0.50" max="0.95" step="0.01" value="0.70">
              <span id="threshold-label">0.70</span>
            </div>
            <div class="settings-row">
              <label>Min peak spacing</label>
              <input type="number" id="min-spacing" value="900" min="1">
              <span style="font-size:10px;color:#768390;">frames</span>
            </div>
            <div class="settings-row">
              <label>Fine scan window</label>
              <input type="number" id="fine-window" value="50" min="1">
              <span style="font-size:10px;color:#768390;">frames</span>
            </div>
          </div>
          <div class="settings-footer">
            <button class="btn-sm" id="settings-reset">Reset defaults</button>
          </div>
        </div>
      </div>
      <button id="scan-btn" disabled onclick="startScan()">&#9654; Scan selected video</button>
```

- [ ] **Step 4: Add source badge CSS**

Add to the `<style>` block, after `.match-new { ... }`:

```css
.source-badge { font-size: 9px; padding: 1px 5px; border-radius: 3px; flex-shrink: 0; }
.source-sensor-clip { background: #1a3a1a; color: #2ea043; }
.source-sensor-only { background: #2a2010; color: #d4a017; }
.source-clip-only { background: #1a2535; color: #388bfd; }
```

- [ ] **Step 5: Verify HTML is valid (no syntax errors)**

```bash
python3 -c "
from html.parser import HTMLParser
class V(HTMLParser): pass
p=V(); p.feed(open('clip-cutter/templates/clip_cutter.html').read()); print('HTML OK')
"
```

Expected: `HTML OK`

- [ ] **Step 6: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html
git commit -m "feat: 4-phase pipeline strip, scan settings panel, source badge CSS"
```

---

### Task 7: JavaScript — params, source badge, settings toggle/tabs/reset, 4-phase progress

**Files:**
- Modify: `clip-cutter/static/clip_cutter.js`

- [ ] **Step 1: Update `PIPELINE_PHASES` and `PHASE_LABELS`**

In `clip_cutter.js`, replace lines 234–239:

```javascript
const PIPELINE_PHASES = ["sensor_parse", "coarse", "peak_detection", "fine"];

const PHASE_LABELS = {
  sensor_parse: "Sensor parse",
  coarse: "Coarse CLIP",
  peak_detection: "Peak detection",
  fine: "Fine scan",
};
```

- [ ] **Step 2: Update `updateProgress` to handle sensor_parse phase**

Replace the `updateProgress` function (lines 242–275):

```javascript
function updateProgress(job) {
  const pct = job.total > 0 ? Math.round((job.current / job.total) * 100) : 0;
  document.getElementById("progress-fill").style.width = pct + "%";
  document.getElementById("progress-pct").textContent = pct + "%";

  const phase = job.phase || "sensor_parse";
  const phaseIdx = PIPELINE_PHASES.indexOf(phase);

  PIPELINE_PHASES.forEach((p, i) => {
    const stepEl = document.querySelector(`.pipeline-step[data-phase="${p}"]`);
    if (!stepEl) return;
    stepEl.classList.remove("active", "done");
    if (i < phaseIdx) stepEl.classList.add("done");
    else if (i === phaseIdx) stepEl.classList.add("active");
  });

  document.querySelectorAll(".pipeline-connector[data-after]").forEach((el) => {
    const afterPhase = el.dataset.after;
    const afterIdx = PIPELINE_PHASES.indexOf(afterPhase);
    el.classList.toggle("done", afterIdx < phaseIdx);
  });

  if (phase === "sensor_parse") {
    document.getElementById("progress-text").textContent = "Parsing sensor data…";
  } else if (phase === "peak_detection") {
    document.getElementById("progress-text").textContent = "Detecting peaks…";
  } else if (phase === "fine") {
    const label = job.total > 0
      ? `Fine scan — ${job.current} / ${job.total} candidate${job.total !== 1 ? "s" : ""}`
      : "Fine scan…";
    document.getElementById("progress-text").textContent = label;
  } else {
    document.getElementById("progress-text").textContent =
      `Coarse CLIP — frame ${job.current.toLocaleString()} / ${job.total.toLocaleString()}`;
  }
}
```

- [ ] **Step 3: Update `startScan` to collect and send params**

Replace the `startScan` function (lines 173–199):

```javascript
async function startScan() {
  if (!selectedVideoPath) return;
  document.getElementById("scan-btn").disabled = true;
  document.getElementById("results-list").innerHTML = "";
  document.getElementById("results-count").textContent = "";
  detections.length = 0;

  const params = {
    trigger_value: parseInt(document.getElementById("trigger-value").value, 10),
    sensor_margin: parseInt(document.getElementById("sensor-margin").value, 10),
    stride: parseInt(document.getElementById("scan-stride").value, 10),
    threshold: parseFloat(document.getElementById("scan-threshold").value),
    min_spacing: parseInt(document.getElementById("min-spacing").value, 10),
    fine_window: parseInt(document.getElementById("fine-window").value, 10),
  };

  try {
    const resp = await fetch("/clip-cutter/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_path: selectedVideoPath, params }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      setStatus("Error: " + err.error);
      document.getElementById("scan-btn").disabled = false;
      return;
    }
    const { job_id } = await resp.json();
    currentJobId = job_id;
    listenToScan(job_id);
  } catch (err) {
    setStatus("Network error: " + err.message);
    document.getElementById("scan-btn").disabled = false;
  }
}
```

- [ ] **Step 4: Update `buildResultCard` to render source badge**

In `buildResultCard`, after the `card.querySelector(".sim-pill").textContent = ...` line (line 341), add:

```javascript
  // Source badge (sensor_guided scans only)
  if (d.source) {
    const badgeMap = {
      "sensor+clip": { cls: "source-sensor-clip", text: "✓ sensor+CLIP" },
      "sensor_only": { cls: "source-sensor-only", text: "sensor only" },
      "clip_only":   { cls: "source-clip-only",   text: "CLIP only" },
    };
    const b = badgeMap[d.source];
    if (b) {
      const badge = document.createElement("span");
      badge.className = "source-badge " + b.cls;
      badge.textContent = b.text;
      card.querySelector(".result-info").appendChild(badge);
    }
  }
```

- [ ] **Step 5: Add settings toggle, tab switching, reset, and threshold label wiring**

Append to the `document.addEventListener("DOMContentLoaded", ...)` callback in `clip_cutter.js` (before the closing `}`):

```javascript
  // Settings panel toggle
  document.getElementById("settings-toggle").addEventListener("click", () => {
    const body = document.getElementById("settings-body");
    const btn = document.getElementById("settings-toggle");
    const open = body.style.display === "none";
    body.style.display = open ? "block" : "none";
    btn.innerHTML = (open ? "&#9881; Scan settings &#9650;" : "&#9881; Scan settings &#9660;");
  });

  // Tab switching
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => (p.style.display = "none"));
      btn.classList.add("active");
      document.getElementById("tab-" + btn.dataset.tab).style.display = "flex";
    });
  });

  // Threshold slider label
  document.getElementById("scan-threshold").addEventListener("input", (e) => {
    document.getElementById("threshold-label").textContent = parseFloat(e.target.value).toFixed(2);
  });

  // Reset defaults
  document.getElementById("settings-reset").addEventListener("click", () => {
    document.getElementById("trigger-value").value = "14";
    document.getElementById("sensor-margin").value = "25";
    document.getElementById("scan-stride").value = "10";
    document.getElementById("scan-threshold").value = "0.70";
    document.getElementById("threshold-label").textContent = "0.70";
    document.getElementById("min-spacing").value = "900";
    document.getElementById("fine-window").value = "50";
  });
```

- [ ] **Step 6: Verify JS syntax**

```bash
node --input-type=module < clip-cutter/static/clip_cutter.js 2>&1 | head -5
```

Expected: no output (no syntax errors). If `node` isn't available:

```bash
python3 -c "
import subprocess, sys
r = subprocess.run(['node', '--check', 'clip-cutter/static/clip_cutter.js'], capture_output=True, text=True)
print(r.stdout or r.stderr or 'OK')
"
```

- [ ] **Step 7: Commit**

```bash
git add clip-cutter/static/clip_cutter.js
git commit -m "feat: JS settings panel, params in scan POST, source badge on cards, 4-phase progress"
```

---

### Task 8: Frontend tests — settings panel + source badge + params in POST

**Files:**
- Modify: `clip-cutter/tests/test_ui.py`

Context: `test_ui.py` uses Playwright with mocked API routes. Run with `pytest tests/test_ui.py -v` while the app is running at `http://localhost:5002`. See the top of `test_ui.py` for the `setup_routes` helper and `BASE_URL` env var.

- [ ] **Step 1: Write new tests**

Append to `clip-cutter/tests/test_ui.py`:

```python
# ── Scan settings panel tests ─────────────────────────────────────────────────

def test_scan_settings_collapsed_on_load(page: Page) -> None:
    setup_routes(page)
    page.goto(BASE_URL + "/clip-cutter/")
    expect(page.locator("#settings-body")).not_to_be_visible()


def test_scan_settings_toggle_opens_and_closes(page: Page) -> None:
    setup_routes(page)
    page.goto(BASE_URL + "/clip-cutter/")
    page.click("#settings-toggle")
    expect(page.locator("#settings-body")).to_be_visible()
    page.click("#settings-toggle")
    expect(page.locator("#settings-body")).not_to_be_visible()


def test_scan_settings_clip_tab_switch(page: Page) -> None:
    setup_routes(page)
    page.goto(BASE_URL + "/clip-cutter/")
    page.click("#settings-toggle")
    # Sensor tab visible, CLIP tab hidden
    expect(page.locator("#tab-sensor")).to_be_visible()
    expect(page.locator("#tab-clip")).not_to_be_visible()
    # Click CLIP tab
    page.click(".tab-btn[data-tab='clip']")
    expect(page.locator("#tab-clip")).to_be_visible()
    expect(page.locator("#tab-sensor")).not_to_be_visible()


def test_scan_settings_reset_restores_defaults(page: Page) -> None:
    setup_routes(page)
    page.goto(BASE_URL + "/clip-cutter/")
    page.click("#settings-toggle")
    # Change trigger value
    page.fill("#trigger-value", "99")
    page.fill("#sensor-margin", "99")
    # Reset
    page.click("#settings-reset")
    assert page.input_value("#trigger-value") == "14"
    assert page.input_value("#sensor-margin") == "25"
    # Switch to CLIP tab and verify those defaults too
    page.click(".tab-btn[data-tab='clip']")
    assert page.input_value("#scan-stride") == "10"
    assert page.input_value("#scan-threshold") == "0.70"
    assert page.input_value("#min-spacing") == "900"
    assert page.input_value("#fine-window") == "50"


def test_threshold_slider_updates_label(page: Page) -> None:
    setup_routes(page)
    page.goto(BASE_URL + "/clip-cutter/")
    page.click("#settings-toggle")
    page.click(".tab-btn[data-tab='clip']")
    page.fill("#scan-threshold", "0.85")
    page.dispatch_event("#scan-threshold", "input")
    expect(page.locator("#threshold-label")).to_have_text("0.85")


def test_scan_post_includes_params(page: Page) -> None:
    """startScan() sends params object in POST body."""
    setup_routes(page)
    page.goto(BASE_URL + "/clip-cutter/")

    captured = {}

    def handle_scan(route):
        body = json.loads(route.request.post_data or "{}")
        captured["params"] = body.get("params")
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"job_id": "test-job"}),
        )

    page.route("**/clip-cutter/scan", handle_scan)
    page.route("**/clip-cutter/scan/stream**", lambda r: r.fulfill(
        status=200, content_type="text/event-stream",
        body='data: {"status":"done","detections":[],"phase":"fine","current":0,"total":0}\n\n',
    ))

    # Select a video and open settings to change trigger_value
    page.click(".video-row:not(.done)")
    page.click("#settings-toggle")
    page.fill("#trigger-value", "7")
    page.click("#scan-btn")
    page.wait_for_function("document.getElementById('scan-btn').disabled === false", timeout=5000)

    assert captured.get("params") is not None
    p = captured["params"]
    assert p["trigger_value"] == 7
    assert p["sensor_margin"] == 25  # default
    assert p["stride"] == 10
    assert "threshold" in p
    assert "min_spacing" in p
    assert "fine_window" in p


def test_source_badge_sensor_clip(page: Page) -> None:
    """Detection card shows green 'sensor+CLIP' badge when source='sensor+clip'."""
    det_with_source = {
        "cv2_pos": 20967,
        "frame_number": 20968,
        "similarity": 0.87,
        "known_match": None,
        "status": "pending",
        "source": "sensor+clip",
    }
    setup_routes(page, detections_override=[det_with_source])
    page.goto(BASE_URL + "/clip-cutter/")
    page.click(".video-row:not(.done)")

    page.route("**/clip-cutter/scan", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"job_id": "test-badge"}),
    ))
    page.route("**/clip-cutter/scan/stream**", lambda r: r.fulfill(
        status=200, content_type="text/event-stream",
        body='data: ' + json.dumps({
            "status": "done",
            "detections": [det_with_source],
            "phase": "fine", "current": 1, "total": 1,
        }) + '\n\n',
    ))

    page.click("#scan-btn")
    page.wait_for_function("document.getElementById('scan-btn').disabled === false", timeout=5000)

    badge = page.locator(".source-badge.source-sensor-clip")
    expect(badge).to_be_visible()
    expect(badge).to_have_text("✓ sensor+CLIP")


def test_source_badge_absent_for_legacy_detection(page: Page) -> None:
    """Detection without source field shows no badge."""
    det_no_source = {
        "cv2_pos": 20967,
        "frame_number": 20968,
        "similarity": 0.87,
        "known_match": None,
        "status": "pending",
    }
    setup_routes(page, detections_override=[det_no_source])
    page.goto(BASE_URL + "/clip-cutter/")
    page.click(".video-row:not(.done)")

    page.route("**/clip-cutter/scan", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"job_id": "test-nobadge"}),
    ))
    page.route("**/clip-cutter/scan/stream**", lambda r: r.fulfill(
        status=200, content_type="text/event-stream",
        body='data: ' + json.dumps({
            "status": "done",
            "detections": [det_no_source],
            "phase": "fine", "current": 1, "total": 1,
        }) + '\n\n',
    ))

    page.click("#scan-btn")
    page.wait_for_function("document.getElementById('scan-btn').disabled === false", timeout=5000)

    expect(page.locator(".source-badge")).to_have_count(0)
```

Note: `setup_routes` in `test_ui.py` needs a `detections_override` kwarg that controls what the scan SSE returns. Check whether the existing `setup_routes` helper already supports this (look for `_MOCK_DETECTIONS`). If not, add a `detections_override=None` parameter and use it in the scan stream mock:

```python
def setup_routes(page: Page, *, template_frames=None, init_count=19, detections_override=None) -> None:
    # ... existing code ...
    # In the scan stream mock, use detections_override if provided:
    scan_dets = detections_override if detections_override is not None else _MOCK_DETECTIONS
```

- [ ] **Step 2: Ensure the app is running, then run frontend tests**

```bash
cd clip-cutter
# Terminal 1: docker compose up (or flask run)
# Terminal 2:
python -m pytest tests/test_ui.py -v -k "settings or badge or params" 2>&1 | tail -20
```

Expected: 8 new tests pass.

- [ ] **Step 3: Run full test suite**

```bash
cd clip-cutter && python -m pytest tests/ -v 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add clip-cutter/tests/test_ui.py
git commit -m "test: settings panel, source badge, params in POST body"
```

---

### Task 9: Rebuild Docker container

**Files:** none (build step only)

- [ ] **Step 1: Rebuild and restart**

```bash
cd clip-cutter && docker compose build && docker compose up -d
```

- [ ] **Step 2: Verify container is running**

```bash
docker compose ps
```

Expected: `clip-cutter` service shows `Up`.

- [ ] **Step 3: Smoke test the settings panel**

Open `http://localhost:5002/clip-cutter/` in a browser:
- Click "⚙ Scan settings ▾" — panel expands
- Click "CLIP" tab — stride/threshold/spacing/window fields appear
- Move threshold slider — label updates
- Click "Reset defaults" — all fields revert
- Select a video, click Scan — pipeline strip shows 4 steps (Sensor parse → Coarse CLIP → Peaks → Fine scan)

- [ ] **Step 4: Commit performance timing note**

After running a real scan, note the wall time in the commit:

```bash
git commit --allow-empty -m "perf: sensor-guided scan live — record wall time here after first run"
```

# Sensor-Guided Scan, GPU Performance & UI Parameters — Design Spec

## Goal

Replace the slow full-video CLIP coarse scan with a sensor-first pipeline that uses the `frame_line_status` column of the parent CSV to locate reaching events directly. Supplement with a targeted CLIP gap scan for sensor misses. Add sequential frame reading and GPU batching for speed. Expose all scan parameters in the UI per-scan.

## Architecture

Three independent but coupled subsystems:

1. **Sensor-guided scan** — new `scan_video_sensor_guided()` in `processor.py` replaces `scan_video()` as the default when a CSV is found alongside the video. The existing `scan_video()` is preserved unchanged.
2. **Performance** — sequential frame reading (no random seeks), larger GPU batch size (64→256), thread-based I/O + GPU overlap.
3. **UI parameters panel** — collapsible panel in the frontend; Scan POST body carries per-scan parameters; `_run_scan` reads from request instead of `config.*`.

---

## Subsystem 1 — Sensor-Guided Scan

### CSV discovery

The parent CSV lives alongside the video file: `{video_stem}.csv` in the same directory. `routes.py` resolves the path before calling the scan function. If the CSV is missing (unexpected), falls back to `scan_video()`.

### Pipeline phases

```
Phase 0: Sensor parse      (instant — CSV read only)
Phase 1: CLIP gap scan     (coarse CLIP on frames outside sensor windows)
Phase 2: Peak detection    (on gap-scan curve only)
Phase 3: Fine scan         (CLIP ±window on all merged candidates)
```

The SSE progress strip gains a 4th step for Phase 0 labelled "Sensor parse".

### Sensor pass — `find_sensor_triggers(csv_path, trigger_value, sensor_margin)`

```python
def find_sensor_triggers(
    csv_path: Path | str,
    trigger_value: int = 14,
    sensor_margin: int = 25,
) -> tuple[list[int], set[int]]:
    """
    Returns (rising_edge_frame_numbers, covered_frame_set).

    rising_edge_frame_numbers: 1-based frame numbers at the rising edge of
      each dilated trigger burst — one per reaching event.
    covered_frame_set: all 1-based frame numbers inside any dilated burst
      (used to exclude them from the gap CLIP scan).

    Algorithm:
      1. Load frame_line_status column.
      2. Build boolean array: triggered[i] = (status[i] == trigger_value).
      3. Binary-dilate by sensor_margin frames each side using
         scipy.ndimage.binary_dilation with structure size 2*margin+1.
         This closes intra-burst gaps and extends each event's zone outward.
      4. Find rising edges of dilated signal.
      5. Return frame numbers at those edges + full covered set.
    """
```

### Gap CLIP scan

Runs `get_similarity_curve()` only on frames whose 1-based frame number is **not** in `covered_frame_set`. Implemented by building an explicit `positions` array that skips covered frames before passing to the batch loop.

### Merge and deduplicate

Sensor rising-edge frames and CLIP gap-scan peaks are merged into a single candidate list. Any two candidates within `min_spacing // 2` frames of each other are deduplicated (sensor candidate wins).

### Fine scan and source tagging

Each merged candidate undergoes `fine_scan()` (unchanged). After fine scan, each detection dict gains:

```json
{
  "cv2_pos": 20967,
  "frame_number": 20968,
  "similarity": 0.87,
  "source": "sensor+clip"
}
```

`source` values:
- `"sensor+clip"` — came from sensor trigger, fine scan improved/confirmed it
- `"sensor_only"` — came from sensor trigger, fine scan similarity below threshold
- `"clip_only"` — came from CLIP gap scan, no nearby sensor trigger

### New function signature

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
```

---

## Subsystem 2 — Performance

### Sequential frame reading

`get_similarity_curve()` currently does `cap.set(CAP_PROP_POS_FRAMES, pos)` before every frame, forcing I-frame decoding on each seek. Replace with:

```python
# Within each contiguous range of positions, read sequentially.
# cap.grab() advances without decoding — used to skip non-sampled frames.
cap.set(cv2.CAP_PROP_POS_FRAMES, range_start)
for pos in range(range_start, range_end):
    if pos % stride == 0:
        ret, frame = cap.read()
        ...
    else:
        cap.grab()  # skip without decode
```

For the sensor-guided gap scan, positions are grouped into contiguous runs first; each run is read sequentially.

### GPU batch size

Default `SCAN_BATCH_SIZE` increases from 64 to 256 in `config.py`. The RTX 5090 (32 GB VRAM) handles 256 × 512-float CLIP embeddings trivially. Per-scan override via UI params.

### Threading — I/O + GPU overlap

`get_similarity_curve()` uses a `concurrent.futures.ThreadPoolExecutor` with a single worker:

```python
# Producer thread: reads next batch of frames from disk.
# Main thread: embeds current batch on GPU.
# Queue depth: 1 (prefetch one batch ahead).
with ThreadPoolExecutor(max_workers=1) as pool:
    future = pool.submit(read_batch, positions[0:batch_size])
    for batch_start in range(batch_size, len(positions) + batch_size, batch_size):
        frames = future.result()
        future = pool.submit(read_batch, positions[batch_start:batch_start+batch_size])
        embs = embed_frames_batch(frames)  # GPU
        ...
```

---

## Subsystem 3 — UI Parameters Panel

### HTML/CSS

A collapsible `<div id="scan-settings">` is inserted between the video list section and the scan button. Toggle button labelled **⚙ Scan settings** with a chevron indicator. Two tab buttons switch between Sensor and CLIP parameter groups.

```
┌─ ⚙ Scan settings ▾ ──────────────────────────────────┐
│  [Sensor]  [CLIP]                                     │
│                                                       │
│  Trigger value:   [14]                                │
│  Sensor margin:   [25]  frames each side              │
│                                                       │
│                              Reset defaults           │
└───────────────────────────────────────────────────────┘

[Scan]
```

CLIP tab shows:
- Coarse stride: `[10]`
- Similarity threshold: slider 0.50–0.95 + value label `0.70`
- Min peak spacing: `[900]` frames
- Fine scan window: `[50]` frames

### JS — parameter collection

`startScan()` reads all six inputs and sends them in the POST body:

```javascript
const params = {
  trigger_value: parseInt(triggerValueEl.value),
  sensor_margin: parseInt(sensorMarginEl.value),
  stride: parseInt(strideEl.value),
  threshold: parseFloat(thresholdEl.value),
  min_spacing: parseInt(minSpacingEl.value),
  fine_window: parseInt(fineWindowEl.value),
};
// POST /clip-cutter/scan  body: { video_path, params }
```

### Routes — per-scan parameters

`POST /clip-cutter/scan` extracts `params` from the request body. `_run_scan` receives params explicitly and passes them to `scan_video_sensor_guided()` or `scan_video()`:

```python
def _run_scan(job_id, video_path, template_emb, params: dict):
    stride       = params.get("stride", config.SCAN_STRIDE)
    threshold    = params.get("threshold", config.SIMILARITY_THRESHOLD)
    min_spacing  = params.get("min_spacing", config.MIN_PEAK_SPACING)
    fine_window  = params.get("fine_window", config.FINE_SCAN_WINDOW)
    trigger_value = params.get("trigger_value", config.SENSOR_TRIGGER_VALUE)
    sensor_margin = params.get("sensor_margin", config.SENSOR_MARGIN)
    batch_size   = config.SCAN_BATCH_SIZE  # not user-adjustable, set via config
    ...
    csv_path = Path(video_path).with_suffix(".csv")
    if csv_path.exists():
        detections = processor.scan_video_sensor_guided(...)
    else:
        detections = processor.scan_video(...)
```

### Detection card source badge

`buildResultCard()` in `clip_cutter.js` renders a small badge next to the similarity pill:

- `"sensor+clip"` → green pill: `✓ sensor+CLIP`
- `"sensor_only"` → yellow pill: `sensor only`
- `"clip_only"` → blue pill: `CLIP only`
- absent/`"pending"` (legacy detections) → no badge

### Pipeline strip

The 4-phase pipeline strip replaces the current 3-phase strip:

```
● Sensor  ──  ● Coarse CLIP  ──  ● Peaks  ──  ● Fine scan
```

---

## Config additions

```python
SCAN_BATCH_SIZE    = 256   # increased from 64
SENSOR_TRIGGER_VALUE = 14
SENSOR_MARGIN      = 25    # frames to extend each side of trigger burst
```

---

## File Changes

| File | Action |
|------|--------|
| `config.py` | Add `SENSOR_TRIGGER_VALUE`, `SENSOR_MARGIN`; increase `SCAN_BATCH_SIZE` to 256 |
| `processor.py` | Add `find_sensor_triggers()`; add `scan_video_sensor_guided()`; refactor `get_similarity_curve()` for sequential reads + threading |
| `routes.py` | Extract `params` from scan POST body; pass to `_run_scan`; detect CSV path |
| `templates/clip_cutter.html` | Add scan settings panel HTML + CSS; update pipeline strip to 4 phases |
| `static/clip_cutter.js` | Collect params; send in POST; render source badge on cards; wire settings toggle + tabs + reset |
| `tests/test_frame_routes.py` | Add sensor trigger tests (synthetic CSV); sensor-guided scan integration test |
| `tests/test_ui.py` | Add settings panel open/close, reset, POST body contains params, source badge tests |

---

## Testing

### Backend

- `find_sensor_triggers` with a synthetic 10-row CSV returns correct rising edges and covered set
- Binary dilation closes a 5-frame intra-burst gap when margin ≥ 3
- Two bursts separated by less than `2×margin` merge into one candidate
- `scan_video_sensor_guided` with a synthetic AVI + CSV returns detections with correct `source` tags
- Gap scan skips sensor-covered frames (verify positions array excludes them)
- Falls back to `scan_video()` when no CSV path is provided

### Frontend

- Settings panel collapsed on load; toggle opens/closes it
- CLIP tab switches parameter group
- Reset restores all six fields to defaults
- Threshold slider updates displayed value label on input
- Scan POST body contains `params` object with all six values
- Source badge `"sensor+clip"` appears on card after mock scan returns `source` field

### Performance (manual)

Time `MAP2_20250515_103618_0.avi` before and after. Record wall time in commit message.

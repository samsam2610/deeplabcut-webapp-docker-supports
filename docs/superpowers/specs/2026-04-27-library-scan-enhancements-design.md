# Library Scan Enhancements Design

## Goal

Extend the global template library scan panel with two scan types (Clips / Template Frames), two sensor modes (Clip only / Sensor+Clip), and an inline directory frame viewer inside each library card.

## Architecture

Split into two sequential sub-features:

- **A1 — Scan UI + two scan types**: new processor functions, new/updated routes, updated lib settings panel and result rendering.
- **A2 — Directory frame viewer**: new route, new two-zone layout inside expanded library card body.

---

## A1 — Scan UI + Two Scan Types

### Lib Scan Settings Panel

`#lib-scan-settings` gains two toggle rows above the existing fields:

**Scan type** (pill toggle, default Clips):
- `Clips` — existing peak-finding pipeline producing clip candidates
- `Template Frames` — k-means candidate pipeline producing template frame candidates

**Sensor mode** (pill toggle, default Clip only):
- `Clip only` — CLIP similarity only, no CSV required
- `Sensor+Clip` — gates candidates to sensor-triggered windows; requires a CSV file alongside each video

When **Sensor+Clip** is selected, two extra inputs appear:
- `Trigger value` (number, default 14)
- `Sensor margin` (number, default 25 frames each side)

Existing fields and their visibility by scan type:

| Field | Clips | Template Frames |
|---|---|---|
| Coarse stride | ✓ | ✓ |
| Threshold | ✓ | ✓ |
| Min spacing | ✓ | hidden |
| Fine window | ✓ | hidden |
| Target clusters | hidden | ✓ (default 10) |

`Target clusters` (default 10) controls k in k-means; at 2 representatives per cluster this targets ~20 candidate frames.

### Clip Scan — Sensor+Clip Mode

**New processor function** `scan_video_sensor_guided_multi(video_path, combined, csv_path, trigger_value, sensor_margin, stride, threshold, min_spacing, fine_window, batch_size, phase_cb)`:

- Identical pipeline to `scan_video_sensor_guided` but replaces single `mean_embedding` dot-product with `(clip_matrix @ frame_emb).max()` over N templates.
- Phases: `sensor_parse` → `coarse` → `peak_detection` → `fine`.
- Returns same format as `scan_video_multi_template`: `[{frame_number, similarity, source}]`.

**Updated `POST /batch-scan`**:
- Accepts additional body fields: `scan_mode` (`"clip_only"` | `"sensor+clip"`), `trigger_value`, `sensor_margin`.
- `_run_batch_scan` routes to `scan_video_sensor_guided_multi` when `scan_mode == "sensor+clip"`, otherwise uses existing `scan_video_multi_template`.
- CSV path derived as `Path(video_path).with_suffix(".csv")` — if file does not exist, job errors with `"CSV not found for <video>"`.

### Template Frame Scan

**New processor function** `find_template_candidates(video_path, combined, n_clusters, threshold, stride, batch_size, phase_cb, csv_path, trigger_value, sensor_margin)`:

- **Phases**: `coarse` → `cluster` → `done`.
- **Coarse**: compute similarity curve using `get_similarity_curve_multi` (or sensor-windowed variant if `csv_path` given). Collects all sampled `(frame_index, similarity, embedding)` tuples — storing embeddings for post-hoc recluster.
- **Filter**: keep only frames where `similarity >= threshold`. If fewer than `n_clusters` frames survive, return all as candidates (skip clustering).
- **Cluster**: k-means with `k = n_clusters` on the filtered embeddings (using `scipy.cluster.vq.kmeans2` or `sklearn.cluster.KMeans`). Pick the 2 frames closest to each centroid by Euclidean distance.
- **Returns**: `{candidates: [{frame_number, similarity, cluster_id}], curve: [{frame_number, similarity}]}`. The `curve` covers all sampled frames (not just above-threshold) so recluster can re-filter without re-embedding.
- Embeddings stored in job dict for recluster.

**New routes**:

`POST /batch-template-scan`
- Body: `{template_dirs, video_paths, params: {scan_mode, stride, threshold, n_clusters, trigger_value, sensor_margin}}`
- Validates template_dirs non-empty, loads combined template, returns `{job_id}`.
- Background thread `_run_batch_template_scan` iterates videos, calls `find_template_candidates`, stores per-video `{video_path, candidates, curve, embeddings}` in job dict.

`GET /batch-template-scan/stream?job_id=`
- SSE stream; same structure as `/batch-scan/stream`. Terminal phases: `done`, `error`.

`POST /batch-template-scan/<job_id>/recluster`
- Body: `{threshold, n_clusters}`.
- Uses cached `curve` and `embeddings` from job dict — no re-embedding.
- Re-filters, re-clusters, returns `{results: [{video_path, candidates}]}`.

`POST /template-frame-add`
- Body: `{video_path, frame_number}`.
- Stateless: derives `clips_dir = Path(video_path).parent / Path(video_path).stem`, resolves template_state.json (same two-path logic as `_folder_frame_count`), calls `processor.add_frame_to_template` directly without touching `_state`.
- Returns `{count}`.

### Template Candidate Result Cards

Rendered into `#results-list` (same container as clip candidates), distinguished by `data-result-type="template-candidate"`.

Each card layout:
```
┌────────────────────────────────────────────┐
│ [80×60 frame img]  video_name              │
│                    Frame 4521 · sim 0.84   │
│                    [sensor+clip badge]      │
│                    [Add to template] [Skip] │
└────────────────────────────────────────────┘
```

- Frame image: `/clip-cutter/frame?video=<video_path>&n=<frame_number-1>`
- "Add to template" → `POST /template-frame-add` → on success, updates frame count badge in library card for that directory, disables button.
- "Skip" → removes card from DOM only.

After template scan results render, a **rethreshold bar** appears above `#results-list`:
```
Threshold ──●──── 0.70   [Apply]
```
- Dragging the slider and clicking Apply → `POST /batch-template-scan/<job_id>/recluster` → re-renders cards.
- Bar is removed when the results list is cleared (new scan or video switch).

### JS changes (`clip_cutter.js`)

- Add scan type + sensor mode toggle state variables: `_libScanType = "clips"`, `_libSensorMode = "clip_only"`.
- Toggle handlers show/hide conditional fields, update button label.
- `startBatchScan()` renamed internally; top-level "Scan with checked" handler dispatches to `startBatchScan()` or `startBatchTemplateScan()` based on `_libScanType`.
- `startBatchTemplateScan()`: same SSE pattern, calls `/batch-template-scan`, stores returned `job_id` in module-level `_templateScanJobId`, renders template candidate cards, shows rethreshold bar.
- Rethreshold Apply handler reads `_templateScanJobId` to call `POST /batch-template-scan/<job_id>/recluster`.

---

## A2 — Directory Frame Viewer

### Library Card Body Layout

Expanded card body becomes a two-zone layout:

**Zone 1 — Folder list** (scrollable, resizable):
- Default height: 112px (≈4 rows at 28px each).
- `overflow-y: auto`.
- A drag handle div at the bottom lets the user resize Zone 1 by dragging (same `mousedown`/`mousemove` pattern as `#ep-drag-handle`). Min height 56px (2 rows), max 224px (8 rows).
- Clicking a folder row (not checkbox, not ✕) selects it and loads Zone 2.
- Selected row gets a highlight class `.lib-folder-row.selected`.

**Zone 2 — Template frame list** (below drag handle):
- Header: `<folder_label> — N frames`.
- List of frame rows, each: small thumbnail (`/clip-cutter/frame?video=...&n=<frame_number-1>`, 48×36px) + frame number + **View** button + **Del** button.
- View: opens bottom player panel via existing `openPlayer(video_path, frame_number, "browse")`.
- Del: `DELETE /library-folder-frames` → removes frame from template_state.json → refreshes Zone 2.
- Zone 2 is empty/hidden until a folder row is clicked.

### New routes

`GET /library-folder-frames?path=<dir>`
- Resolves template_state.json (same two-path logic).
- Returns `{frames: [{frame_number, video_path}], count}`.
- Thumbnails are NOT returned here — frontend fetches per-frame images lazily via `/clip-cutter/frame`.

`DELETE /library-folder-frames`
- Body: `{path, frame_number}`.
- Reads template_state.json, removes the matching frame entry, saves.
- Returns `{count}`.

---

## Testing

- `test_routes.py`: add tests for `POST /batch-template-scan`, `GET /batch-template-scan/stream`, `POST /batch-template-scan/<job_id>/recluster`, `POST /template-frame-add`, `GET /library-folder-frames`, `DELETE /library-folder-frames`.
- `test_processor.py`: add tests for `scan_video_sensor_guided_multi` (mock CSV), `find_template_candidates` (empty curve, below-threshold, clustering, recluster).
- `test_ui.py`: update any selectors that reference library card body structure.

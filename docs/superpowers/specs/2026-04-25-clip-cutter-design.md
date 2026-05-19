# Clip Cutter — Design Spec

**Date:** 2026-04-25
**Module:** `clip-cutter/` (supplementary to `deeplabcut-webapp-docker`)

---

## Problem

Videos of rat reaching tasks are recorded as long continuous AVI files (e.g., 264k frames at 200fps). A human operator currently watches each video and manually marks the frame where the rat begins a reach ("start_reaching"). The goal is to automate this detection using CLIP-based template matching seeded from already-annotated clips.

---

## Data Layout

```
/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/MAP-2/
  MAP2_<date>_<time>_<idx>.avi        ← full recording (200fps, 1376×900)
  MAP2_<date>_<time>_<idx>.csv        ← per-frame CSV: timestamp, frame_number, frame_line_status, note
  MAP2_20250515_103618_0/             ← already-annotated clips folder (training source)
    MAP2_…_{start}_{end}_{label}.avi  ← 800-frame clip
    MAP2_…_{start}_{end}_{label}.csv  ← copy of parent CSV rows for those frames + clip_frame column
```

Inside Docker the synology mount appears at `/user-data/Parra-Data/Cloud/`.

**Clip naming convention:** `{video_name}_{start_frame}_{end_frame}_{success|failure}.avi`
Frame 200 of a clip (0-indexed: index 199) = the key reaching frame. So key frame in parent video = `start_frame + 200`.

---

## Template (Training Phase)

**Source:** 19 existing clips in `MAP2_20250515_103618_0/`.

**Method:**
1. From each clip, extract frame index 199 (the 200th frame).
2. Crop to `x=401, y=268, w=581, h=632` (original 1376×900 pixels) — this isolates the arena center, excluding the three mirrors (top, left, right).
3. Compute a CLIP ViT-B-32 embedding (via `sentence-transformers`) for each cropped frame.
4. L2-normalise each embedding, then compute the element-wise mean → **mean template vector**.

The template is persisted to `clip-cutter/template_state.json` so it survives restarts. Each entry records: source clip filename, embedding vector, thumbnail (base64 JPEG). Adding a new frame appends to this list and recomputes the mean.

---

## Scanning Phase

**Input:** a full-video AVI + its CSV.

**No crop at inference time** — the full 1376×900 frame is used. This ensures the model generalises to future videos where the arena or camera position may have shifted.

**Steps:**
1. **Coarse pass:** extract every 10th frame, batch through CLIP ViT-B-32 (batch size 64), compute cosine similarity vs. the mean template. Produces a ~26k-point similarity curve.
2. **Smooth:** apply a Gaussian kernel (σ=3) to reduce per-frame noise.
3. **Peak detection:** find local maxima above threshold (default 0.70), minimum spacing 900 frames (slightly more than one clip length) to prevent double-counting overlapping events.
4. **Fine pass:** for each coarse peak, scan ±50 frames at stride 1 to locate the exact maximum — the detected key frame `K`.

**Threshold** is a tunable constant at the top of `processor.py`.

---

## Output

### Clip video
`{output_dir}/{video_name}_{K-200}_{K+599}.avi` — 800 frames extracted from the full video. Codec matches source (MJPEG/AVI). No success/failure suffix for now.

### Clip CSV
A direct row-copy from the parent CSV for frames `K-200` through `K+599`, with a 5th column appended:

| timestamp | frame_number | frame_line_status | note | clip_frame |
|-----------|-------------|------------------|------|------------|
| (from parent) | (original video frame) | (from parent) | (from parent) | 1–800 |

`clip_frame` is 1-based.

### Parent CSV update
Write `start_reaching` into the `note` column of the row where `frame_number = K`. All other rows are untouched — no rows are added, removed, or reordered.

### Output folder (test run)
`{video_dir}/{video_name}_test_clips/` — created alongside the source video.

---

## Validation

The 19 known clips provide ground truth: detected `K` should equal `start_frame + 200` from the clip filename. The results UI shows a "matches known clip ✓" badge for any detection within ±5 frames of a known key frame.

---

## File Structure

```
clip-cutter/
  app.py              ← Flask factory; registers blueprint at /clip-cutter
  routes.py           ← all HTTP routes
  processor.py        ← CLIP logic: build_template, scan_video, extract_clips
  template_state.json ← persisted template embeddings + thumbnails (gitignored)
  templates/
    clip_cutter.html
  static/
    clip_cutter.js
```

Designed to be mounted into the main webapp by importing the blueprint from `app.py`.

---

## UI — Layout B (left sidebar + main panel)

**Left sidebar — Template Bank**
- Grid of thumbnails (one per training frame), each labelled with its source clip name.
- Click a thumbnail to remove it from the template batch (with confirmation).
- `+ Add` button opens a frame-picker for a selected clip.

**Main panel — top: Video selector**
- List of AVI files in the configured directory.
- A video is marked "done" if a `{video_name}_test_clips/` directory exists alongside it, or if any row in its parent CSV already has `start_reaching` in the `note` column.
- `▶ Scan selected video` button triggers the scan.

**Main panel — middle: Progress bar**
- Visible only during scanning.
- Shows current phase (coarse / fine), frame progress, and percentage.
- Streamed via Server-Sent Events (SSE).

**Main panel — bottom: Detections**
- Card per detection: clip filename, key frame number, similarity score, "matches known clip ✓" or "new detection" badge.
- Three actions per card:
  - **Keep** — writes the clip to disk and updates the parent CSV.
  - **Reject** — discards the detection (no files written).
  - **Add to template** — adds frame index 199 of this clip (full frame, no crop) to the template batch and recomputes the mean embedding.

---

## Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/clip-cutter/` | Main UI |
| GET | `/clip-cutter/template` | Returns template state JSON (thumbnails + count) |
| POST | `/clip-cutter/template/add` | Add a frame to template; body: `{clip_path, frame_index}` |
| DELETE | `/clip-cutter/template/<idx>` | Remove a template frame by index |
| POST | `/clip-cutter/scan` | Start scan in background thread; body: `{video_path}`; returns `{job_id}` |
| GET | `/clip-cutter/scan/stream?job_id=…` | SSE stream of scan progress events |
| POST | `/clip-cutter/extract` | Write a confirmed detection to disk + update parent CSV; body: `{video_path, key_frame}` |

---

## Dependencies

- `sentence-transformers` (CLIP ViT-B-32)
- `opencv-python`
- `pandas`
- `scipy` (Gaussian smoothing + peak finding)
- `flask`

GPU optional — falls back to CPU. Runs on the host (outside the DLC Docker containers).

---

## Out of Scope (this iteration)

- Success/failure classification
- Multi-video batch scanning in one click
- CLI mode / non-Flask usage
- Cropped-region inference for position-shifted future videos

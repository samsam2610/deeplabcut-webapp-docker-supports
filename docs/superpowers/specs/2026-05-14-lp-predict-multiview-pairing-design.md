---
name: LP Predict — multi-view sibling pairing and AVI transcoding
description: Make the LP Predict card accept a single video and automatically resolve sibling-cam views + transcode AVI → MP4 so litpose's multi-view path activates without forcing the user to pick a folder
type: project
---

# LP Predict — multi-view sibling pairing & AVI transcoding

**Date:** 2026-05-14
**Scope:** Make `POST /dlc-3d/lp/predict` accept individual video files and, before invoking `litpose predict`, resolve sibling-cam views and transcode AVI inputs to MP4. No UI change.

**Why:** `litpose 2.1.0`'s predict CLI raises `NotImplementedError: For multi view model predictions, either pass in multiple video views to be predicted, or a directory containing videos` whenever a multi-view model receives anything other than a full set of mp4 files split across views (or a directory of them). It also rejects AVI in both single- and multi-view paths — only `.mp4` is accepted. The dlc-3D pipeline produces `*_cam<N>_*.avi` videos. Without sibling pairing + a transcode step, users have to manually group + convert files outside the app.

---

## 1. Behaviour at the boundary

`prepare_predict_inputs(model_dir, videos) -> {mp4_paths, transcoded, sibling_warnings}`

Pure-python helper that runs on the dlc-3d-worker just before `litpose predict`. Two phases:

### 1.1 Detect model view configuration

Read `<model_dir>/config.yaml`. The relevant fields:
- `data.view_names: list[str]` — e.g. `["cam0", "cam1"]`

Multi-view ↔ `len(view_names) > 1`. Single-view ↔ `len(view_names) <= 1` (treat missing field as single-view).

### 1.2 Resolve sibling-cam views (multi-view only)

For each user-supplied video path, derive sibling paths by token substitution on the filename's `_<view>_` segment. Concretely: locate the first occurrence of `_<view>_` in the stem (where `<view>` is one of `view_names`), then replace it with `_<other_view>_` for every other view in `view_names`.

```
Input:  khoai-lang-1_cam0_20260507_102231_0_trig1_fps200_…avi   (view_names = ["cam0","cam1"])
Pairs:  khoai-lang-1_cam0_20260507_102231_0_trig1_fps200_…avi
        khoai-lang-1_cam1_20260507_102231_0_trig1_fps200_…avi
```

- All siblings must live in the **same directory** as the user-supplied file.
- If any sibling is missing for a session, drop that session entirely and record a `sibling_warning` mentioning which view was missing. Do not silently send a partial set to litpose.
- If a user supplies multiple files from the same session (e.g., both cam0 and cam1), dedupe the resolved set before returning.
- If a user supplies a video whose filename has no recognised `_<view>_` token, treat it as opaque: pass through unchanged with a `sibling_warning` so they can investigate.

### 1.3 Transcode non-MP4 inputs

For every resolved path that is not `.mp4`:
- Check for a same-stem `.mp4` in the same directory. If present, reuse it (cache hit).
- Otherwise run `ffmpeg -y -i <input> -c copy -movflags +faststart <input.stem>.mp4` in the source directory. This is a container remux — no re-encoding, no quality loss, runs at ~1 GB/sec on modern disks. A 10 GB AVI completes in seconds.
- If `-c copy` fails (e.g., codec is not mp4-compatible), fall back to `ffmpeg -y -i <input> -c:v libx264 -preset veryfast -crf 18 <input.stem>.mp4` to re-encode. Log which path was taken.
- The transcoded mp4 stays in place. Subsequent predicts reuse it via the cache check.
- Record each transcoded source in `transcoded`.

Source `.avi` files are never modified or deleted. We only ever write `<stem>.mp4` adjacent to them.

### 1.4 Return shape

```python
{
    "mp4_paths": [Path, ...],          # what we pass to litpose predict
    "transcoded": [str, ...],          # source .avi files we transcoded this call
    "sibling_warnings": [str, ...],    # human-readable explanations
    "is_multiview": bool,
    "view_names": list[str],
}
```

---

## 2. Task & route integration

### 2.1 `tasks.lp_predict`

Before calling `run_predict_subprocess`, invoke `prepare_predict_inputs(model_dir, videos)`. Substitute the returned `mp4_paths` for the subprocess's input list. Surface `transcoded` and `sibling_warnings` in the task's return value (alongside the existing `moved`, `skipped`, `dest_dir`, `model_dir`).

The post-predict `relocate_predictions` call already operates on the videos passed to litpose. We must pass it the **resolved mp4 paths** (not the user-supplied originals) so the move step finds `<stem>.csv` outputs that litpose wrote. The destination logic stays unchanged: empty `dest_dir` → each mp4's parent directory; explicit `dest_dir` → all outputs land there.

### 2.2 `/dlc-3d/lp/predict` route

No payload change. The existing validation (`videos` non-empty, each under `/user-data/`, optional `dest_dir` under `/user-data/`) covers the new behaviour. We pass the user's original list to the task; the task does the resolution.

### 2.3 ffmpeg dependency

The dlc-3d-worker base image already has `ffmpeg` (Dockerfile.worker has `apt-get install -y --no-install-recommends ffmpeg`). No image rebuild required.

---

## 3. UI

No changes to `card_lp_predict.html` or the picker JS. The existing flow is: user adds one or more videos to the queue → server resolves siblings + transcodes → predict runs. Job status response surfaces `sibling_warnings` and `transcoded` so the result panel can render them.

A small string addition in `lp_cards.js`'s polling output: when the celery_info contains `transcoded` or `sibling_warnings`, append a short section to the displayed result. This is a 5-line tweak, not a redesign.

---

## 4. Error handling

| Condition | Behaviour |
|---|---|
| Sibling file missing | Drop the session, record warning, continue with others |
| All sessions dropped | Task raises `RuntimeError("no usable sessions after sibling resolution: <warnings>")` |
| ffmpeg not on PATH | Task raises `FileNotFoundError("ffmpeg required for transcoding")` |
| ffmpeg `-c copy` fails | Fall back to `libx264 -preset veryfast`. Log the choice. |
| ffmpeg fallback also fails | Task raises `RuntimeError("transcode failed: <stderr tail>")` |
| User-supplied path is a directory | Pass through unchanged (litpose handles `path.is_dir()` itself) |
| Single-view model | Skip pairing entirely; still transcode AVI → MP4 |

The relocate step's existing skip-on-conflict semantics carry over: if a user-chosen `dest_dir` already has `<stem>.csv`, the move is skipped (warning) unless `overwrite=true`.

---

## 5. Files

**Created:**
- `dlc-3D/tests/test_lp_predict_pairing.py` — unit tests for `prepare_predict_inputs`

**Modified:**
- `dlc-3D/src/dlc_3d_bp/lp/predict_runner.py` — add `prepare_predict_inputs(model_dir, videos)` + small helpers `_load_view_names`, `_resolve_siblings`, `_transcode_to_mp4`
- `dlc-3D/src/dlc_3d_bp/lp/tasks.py` — `lp_predict` calls the new helper, passes resolved paths to subprocess + relocator, surfaces `transcoded`/`sibling_warnings` in return
- `dlc-3D/src/static/lp_cards.js` — Predict card's poll callback shows `transcoded`/`sibling_warnings` if present

**Untouched:** card markup, `/lp/predict` route, `relocate_predictions`, all other LP cards, docker-compose.yml.

---

## 6. Test plan

| Test | Verifies |
|---|---|
| `test_load_view_names_multiview` | Reads `data.view_names` from a synthetic LP config |
| `test_load_view_names_singleview_default` | Returns `[]` when `view_names` is absent or length ≤ 1 |
| `test_resolve_siblings_pairs_camN` | `khoai_cam0_…avi` resolves to `[…cam0…, …cam1…]` when both files exist on disk |
| `test_resolve_siblings_warns_on_missing` | If `_cam1_` sibling is absent, session is dropped, warning recorded |
| `test_resolve_siblings_dedupes_when_user_supplies_both` | User passes both cam0 and cam1 → result has each path once |
| `test_resolve_siblings_passthrough_unknown_pattern` | Path with no `_camN_` token in stem is passed through with warning |
| `test_transcode_skips_when_mp4_exists` | `<stem>.mp4` next to `<stem>.avi` → no ffmpeg call |
| `test_transcode_invokes_ffmpeg_stream_copy` | Monkeypatch subprocess; assert `-c copy` argv |
| `test_transcode_falls_back_on_copy_failure` | Mock `-c copy` returncode != 0 → re-encode invoked |
| `test_prepare_predict_inputs_end_to_end_multiview` | Multi-view config + one AVI input → returns two mp4 paths, one transcode (the sibling is reused) |

All unit tests run on host (mock ffmpeg subprocess; no real video files needed). One live smoke test on `dlc-3d-worker` against the user's specific cam0 video confirms the full path including real ffmpeg + real litpose predict on a multi-view model.

### Live smoke contract

Input: `/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/050726/khoai-lang-1_cam0_20260507_102231_0_trig1_fps200_exposure1500_gain10.avi`

Side effects we accept (per user instruction "test without destroying"):
- Writes `khoai-lang-1_cam0_…mp4` and `khoai-lang-1_cam1_…mp4` next to the AVI (cached transcodes).
- Writes per-video `.csv` outputs and (unless skip-viz) `_labeled.mp4` outputs to **the same folder** (default `dest_dir=""`).
- Source `.avi` files are not touched.
- An LP model run dir on `…-LP/models/<timestamp>/` is created by virtue of the litpose process; its `video_preds/` is drained by `relocate_predictions`.

Side effects we **reject**: any modification to existing `.avi` or `.csv` files, any change to non-LP files under that directory.

---

## 7. Out of scope

- Auto-pairing in the **UI picker** (queue still treats each pick as one entry; the backend does pairing). If users want to see the resolved set before submitting, that's a follow-up.
- Image / CSV inputs for predict (the route currently only carries video paths anyway).
- Cleaning up `_labeled.mp4` after relocation when the dest is the same as the source dir (already handled — `relocate_predictions` moves files in place; no double-write).

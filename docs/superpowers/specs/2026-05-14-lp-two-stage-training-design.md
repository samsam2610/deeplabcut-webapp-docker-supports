---
name: LP two-stage training — single-view pretrain → MVT
description: Convert produces a nested single-view sub-project alongside the multi-view one; Train Card runs a backbone-pretrain stage on all labeled frames then auto-switches to MVT initialized from that checkpoint
type: project
---

# LP Two-Stage Training

**Date:** 2026-05-14
**Scope:** Extend `convert_dlc_to_lp` to emit a nested single-view (SV) sub-project alongside the multi-view (MVT) project, and extend `lp_train` to orchestrate a two-stage curriculum — train `heatmap` + `vits_dino` on the SV project first, then train MVT on the parent project initialized from the SV checkpoint via LP's existing `cfg.model.checkpoint` fallback.

**Why:** The user has substantially more single-view-only labeled frames than paired multi-view frames in their DREADD-Ali project. LP's MVT can only train on paired data, leaving the rest of the labels unused. Pretraining a ViT-S/DINO backbone on all labels (single-view convention) and then initializing MVT's backbone from that checkpoint lets the cross-view fusion module learn from the paired set with a much better-initialized encoder. LP supports this out-of-the-box: `utils/scripts.py:584-608` falls back to loading only `backbone.*` weights when the heads don't match.

---

## 1. Data layout — `convert_dlc_to_lp` adds an SV sub-project

The converter's current output (multi-view LP project) gains a nested `sv-pretrain/` sub-project. Final layout:

```
<dlc>-LP/                       (multi-view LP project — unchanged content)
├── config.yaml                 (canonical multi-view config, project-specific substitutions)
├── labeled-data/<session>_<view>/imgNNNNNNNN.png
├── cam0.csv, cam1.csv          (paired-frame CSVs)
├── calibrations/, calibrations.csv
├── videos/
└── sv-pretrain/                NEW: stage-1 single-view sub-project
    ├── config.yaml             (canonical single-view config_default.yaml, substituted)
    ├── labeled-data/
    │   └── <orig_folder>/imgNNN.png      (mirrors DLC's labeled-data tree verbatim)
    └── labels.csv              (one flat CSV — every labeled row from every CollectedData_*.csv,
                                 paths point at `labeled-data/<orig_folder>/<orig_filename>.png`)
```

### SV CSV construction

For each labeled-data folder in the source DLC project — regardless of whether it matches `_cam<N>_` naming, has paired siblings, or is "unrecognised" — emit every labeled row into `labels.csv`. View identity is dropped. The CSV uses LP's single-view canonical 3-row header (`scorer / bodyparts / coords`). Path column rewrites to `labeled-data/<orig_folder>/<orig_filename>.png` after the existing `_normalize_dlc_row` flattening (which already handles DLC's 3-column path index).

This expands the training corpus from ~paired_frame_count to **all labeled frames in the DLC project**: the paired multi-view rows (counted once per view), the unrecognised-folder rows, and the partial-view rows. For DREADD-Ali, roughly:

```
paired multi-view (6 sessions × ~189 frames × 2 cams)   ≈  2272
unrecognised single-cam folders (24 folders × ~50 frames) ≈ 1200
partial-view (Surv1_*, surv1_*) ~50 frames each         ≈   200
TOTAL                                                   ≈ ~3700 SV rows
```

vs the ~1136 paired-view rows the current MVT-only path uses.

### Disk layout

`sv-pretrain/labeled-data/` is populated by **hardlinks** to the corresponding source PNGs when same-filesystem; copies otherwise. This is the same idiom `convert_dlc_to_lp` already uses. CollectedData CSVs are NOT copied — the unified `labels.csv` replaces them.

### Config

`sv-pretrain/config.yaml` is built by patching upstream's `config_default.yaml` (the single-view canonical, which our converter already vendors as `lp_config_default.yaml`) with:
- `data.data_dir = <lp_project>/sv-pretrain` (absolute)
- `data.video_dir = ../videos` (relative — points at the parent project's videos so semi-supervised losses in future could still work)
- `data.csv_file = "labels.csv"` (string, single-view convention)
- `data.num_keypoints` / `data.keypoint_names` from DLC config
- `data.image_orig_dims` / `data.image_resize_dims` probed from first PNG (multiple of 128 for ViT)
- `model.backbone = "vits_dino"` (required for the transfer-to-MVT path)
- `model.model_type = "heatmap"` (single-view canonical default — NOT `heatmap_mhcrnn`; we want a vanilla heatmap head whose backbone state-dict transfers cleanly)
- `_converter` provenance block

All other fields (training, eval, losses, callbacks, dali, hydra) inherit unchanged from upstream's canonical default.

### Converter summary

`convert_dlc_to_lp` return dict gains two fields:
```python
{
    ... existing fields ...
    "sv_pretrain_dir": "<lp_project>/sv-pretrain",
    "n_sv_rows": int,
}
```

---

## 2. Training orchestration — `lp_train` runs both stages in one task

When the user enables two-stage training, **one Celery job** runs the full curriculum:

```
[STAGE 1] litpose train <sv-pretrain/config.yaml> --output_dir <run>/stage1/
              ↓ on success, locate <run>/stage1/tb_logs/.../checkpoints/*-best.ckpt
[STAGE 2] litpose train <run>/stage2/config.yaml --output_dir <run>/stage2/
              with model.checkpoint = <stage1 best ckpt>
              ↓ on success, relocate predictions per the existing flow
```

### Layout under `<lp_project>/models/<timestamp>/`

```
models/20260514-XXXXXX/
├── stage1/
│   ├── config.yaml          (derived from sv-pretrain/config.yaml + user stage1 options)
│   ├── tb_logs/.../checkpoints/<epoch>-best.ckpt
│   └── train_status.json
└── stage2/
    ├── config.yaml          (derived from parent config.yaml + user stage2 options + model.checkpoint=<stage1 best>)
    ├── tb_logs/.../checkpoints/<epoch>-best.ckpt
    ├── predictions_camN.csv (after relocate_predictions)
    └── train_status.json
```

### Stage 1 options (curriculum: short, early-stopping enabled)

Defaults exposed in the Train card:
- `stage1_max_epochs: 100` (vs 300 for stage 2)
- `stage1_early_stopping: true`
- `stage1_early_stop_patience: 5` (epochs)

Stage 1 only trains the supervised heatmap loss on `labels.csv`. No reprojection loss (no calibration in the SV project). No patch masking. The point is fast, robust backbone pretraining.

### Stage 2 options

Same as the user already sets on Card 2 today (MVT toggle, patch_masking, reproj_loss, max_epochs, batch_size, predict_vids_after_training, save_vids_after_training). The orchestrator simply injects `model.checkpoint = <stage1_best_ckpt>` into the stage-2 config; LP's `get_model` does the rest.

### Status reporting

The task's Celery `update_state` meta carries a `stage` field that the UI's existing poll callback already surfaces:

```python
{"stage": "stage1_training", "last_line": "<litpose stdout>", "model_dir": "<run>/stage1"}
{"stage": "stage1_done", "best_ckpt": "<path>"}
{"stage": "stage2_training", "last_line": "<litpose stdout>", "model_dir": "<run>/stage2"}
{"stage": "stage2_done"}
```

The existing `pollJob` UI callback shows a single live tail; we extend it to surface the stage tag.

### Cancellation

`celery.control.revoke(job_id, terminate=True, signal="SIGTERM")` kills whichever litpose subprocess is active. No special handling needed — the task is a single Python function with two sequential subprocess invocations; SIGTERM kills the child and the function's exception propagation marks the task FAILURE.

### Failure semantics

- Stage 1 fails → task FAILURE, no stage 2 attempted, no partial cleanup. The `<run>/stage1/` dir is left in place for inspection.
- Stage 1 succeeds but no checkpoint is produced (e.g., training aborted before val tick) → task FAILURE with a clear message ("stage 1 produced no checkpoint at <path>").
- Stage 2 fails → task FAILURE; stage-1 checkpoint and stage-2 partial dir remain on disk. User can retry stage 2 manually by pointing the existing single-stage Train UI at the parent project and pasting the stage-1 checkpoint path into the existing `model.checkpoint` field (small UI tweak — see §3).

---

## 3. UI — Card 2 gets a two-stage toggle

Three new controls on `card_lp_train.html`, in a new `<fieldset>` labelled "Pretraining":

- Checkbox `lp-train-two-stage`: "Pretrain backbone on all labels (single-view first, then MVT)"
- Numeric `lp-train-stage1-epochs`: "Stage 1 max epochs" (default 100, only enabled when above is checked)
- Optional text `lp-train-stage1-ckpt-override`: "Existing stage-1 checkpoint (.ckpt path, optional)" — when populated, skip stage 1 and go straight to stage 2 with this checkpoint. Lets the user resume after a stage-1 success.

Existing Card 2 fields (MVT toggle, patch_masking, reproj_loss, max_epochs, batch_size, eval flags) all continue to control stage 2.

The result panel poll callback (already shows `transcoded`/`sibling_warnings`) gains a `stage` line.

### `lp_train` API contract

`POST /dlc-3d/lp/train` body gains:

```json
{
  "lp_project": "...",
  "options": {
    ... existing keys ...
    "two_stage": false,                 // NEW: default false (single-stage MVT, current behaviour)
    "stage1_max_epochs": 100,
    "stage1_early_stop_patience": 5,
    "stage1_ckpt_override": ""          // NEW: skip stage 1, use this .ckpt
  }
}
```

Backwards-compatible: omitting these reproduces today's behaviour exactly.

---

## 4. Files

**Modified:**
- `dlc-3D/src/dlc_3d_bp/lp/converter.py` — add `_build_sv_pretrain_project()`; call from `convert_dlc_to_lp`; return new summary fields
- `dlc-3D/src/dlc_3d_bp/lp/train_runner.py` — add `build_stage1_config(sv_pretrain_dir, run_dir, options)` and a helper `find_best_checkpoint(model_dir) -> Path | None`
- `dlc-3D/src/dlc_3d_bp/lp/tasks.py` — `lp_train` branches on `options.two_stage`; when True, runs stage 1 then stage 2 with `model.checkpoint`
- `dlc-3D/src/templates/partials/card_lp_train.html` — Pretraining fieldset
- `dlc-3D/src/static/lp_cards.js` — wire new controls; surface `stage` in poll output

**Created:**
- `dlc-3D/tests/test_lp_sv_pretrain.py` — converter + stage-config-builder tests
- `dlc-3D/tests/test_lp_two_stage_task.py` — orchestrator tests (mock subprocess; verify stage1 → stage2 ordering and checkpoint propagation)

**Untouched:** route handler (no payload schema changes other than additive fields), main webapp, docker-compose.yml. No new packages.

---

## 5. Tests

| Test | Scope |
|---|---|
| `test_sv_pretrain_dir_emitted` | After `convert_dlc_to_lp`, `<lp>/sv-pretrain/{config.yaml,labels.csv,labeled-data/}` exist |
| `test_sv_labels_csv_includes_all_labeled_frames` | Synthetic project with paired + unpaired sessions → flat CSV row count matches union, not intersection |
| `test_sv_config_is_singleview_canonical` | Emitted `sv-pretrain/config.yaml` has `csv_file: str` (not list), no `view_names`, `model_type: heatmap`, `backbone: vits_dino` |
| `test_find_best_checkpoint_returns_newest_best` | Synthetic `tb_logs/.../checkpoints/{epoch=0-step=100-best.ckpt, epoch=5-step=600-best.ckpt}` → newer path returned |
| `test_find_best_checkpoint_returns_none_when_absent` | Empty `tb_logs/` → None |
| `test_lp_train_two_stage_runs_both_stages` | Mock subprocess; assert two `litpose train` invocations in order, second has `--output_dir` ending in `/stage2/` |
| `test_lp_train_two_stage_propagates_checkpoint` | After stage1 success, stage2's materialized config.yaml has `model.checkpoint = <stage1_best_ckpt>` |
| `test_lp_train_two_stage_skips_stage1_when_override_set` | `options.stage1_ckpt_override` set → only one litpose invocation, stage2 only |
| `test_lp_train_two_stage_fails_on_no_stage1_checkpoint` | Stage 1 completes but tb_logs has no .ckpt → RuntimeError "stage 1 produced no checkpoint" |

Plus a live smoke test at the end (Phase 5) against the user's DREADD-Ali project: small `stage1_max_epochs=2, stage2_max_epochs=2` end-to-end, verifying both stages run, the stage2 config carries `model.checkpoint`, and predictions land beside the source video.

---

## 6. Out of scope (future)

- Adaptive switching (monitor val loss, switch when truly plateaued instead of fixed-epoch + early-stop). Today's `early_stopping: true` with patience already provides effective progress-based termination; this can be tightened later.
- Three-or-more-stage curricula (e.g., singleview → multiview-with-patch-masking → multiview-with-3D-loss).
- Reusing the SV-pretrain model standalone (e.g., as a single-view predictor on cam0-only future videos). The checkpoint is recoverable from `<run>/stage1/tb_logs/.../*.ckpt` but no UI is added to use it directly.
- Surfacing stage-1 metrics (val pixel error, etc.) in the Jobs card. Visible only via the live log tail today.

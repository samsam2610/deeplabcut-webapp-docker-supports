---
name: Pin dlc-3d-worker to a single GPU + resume two-stage from stage-1 ckpt
description: Apply the GPU-FD-leak fix to dlc-3d-worker docker config, recreate container after stage 1 completes, then resume stage 2 from the saved checkpoint
type: project
---

# dlc-3d-worker single-GPU pin + mid-training resume

**Date:** 2026-05-14
**Pre-approved by user.** Captured here for traceability only.

## Why

A peer-agent analysis confirmed the RTX 5090 (host PCI 0) is stuck at P0 / ~120W with no compute on it. Root cause: `dlc-3d-worker` is started with `NVIDIA_VISIBLE_DEVICES=all` / `count: all`, so both `/dev/nvidia0` and `/dev/nvidia1` are mounted. CUDA/NVML opens GPU 0 for topology queries; PyTorch's 30+ DataLoader forks inherit the FD; the driver pins the GPU in P0 while any reference exists. No nvidia-smi-visible compute on GPU 0, but power and clocks stay high.

Fix: restrict the container to only the RTX 5090 (host PCI 0) + force PCI bus ordering so the in-container CUDA enumeration matches CLAUDE.md.

## Constraints

- A two-stage training job (`9b5c2d51-348c-4072-9aa3-59356279c481`) is currently in stage 1, ~Epoch 170/200.
- User wants: wait for stage 1 to complete → apply fix → resume stage 2 from the saved checkpoint.
- The stage-1 best checkpoint is autosaved to `<lp>/models/<ts>/stage1/tb_logs/.../*-best.ckpt`; we capture and reuse it via the existing `stage1_ckpt_override` option.

## Sequence

1. **Monitor** the job's `celery_info.stage`. When it flips from `stage1_training` → `stage1_done` OR stage 2 begins (`stage2_training`), proceed. Use ScheduleWakeup for cache-efficient polling.
2. **Revoke** the celery task: `POST /dlc-3d/lp/job/<id>/cancel`. Kills any in-flight subprocess (whether stage 1 still finishing or stage 2 just started).
3. **Capture** the stage-1 best ckpt path from `<run_root>/stage1/tb_logs/*/version_*/checkpoints/*-best.ckpt`.
4. **Edit** `deeplabcut-webapp-docker/docker-compose.yml` for the `dlc-3d-worker` service:
   - Replace `NVIDIA_VISIBLE_DEVICES=all` (in `environment:`) with `CUDA_DEVICE_ORDER=PCI_BUS_ID`.
   - Replace `count: all` (in `deploy.resources.reservations.devices[0]`) with `device_ids: ['0']`.
5. **Recreate** the container: `docker compose up -d dlc-3d-worker` (compose detects the config change and recreates).
6. **Verify**:
   - Inside the container: `nvidia-smi -L` shows only RTX 5090; `torch.cuda.device_count() == 1`; `torch.cuda.get_device_name(0) == "NVIDIA GeForce RTX 5090"`.
   - On host: GPU 0 power < 30W, mem 2 MiB, no compute apps; GPU 1 (RTX PRO 6000) idle.
7. **Resume stage 2** via `POST /dlc-3d/lp/train` with the same options dict from the original job, but:
   - `two_stage: True`
   - `stage1_ckpt_override: <captured ckpt path>` (this skips stage 1)
   - All other options (mvt_enabled, patch_masking_*, reproj_loss_*, max_epochs=300, batch_size=64) carry over verbatim.
8. **Confirm** the new task spawns litpose on the RTX 5090 (host GPU 0): `nvidia-smi --query-compute-apps` lists a PID on GPU 0; GPU 1 returns to idle.

## Failure modes

- **Captured ckpt path doesn't exist**: stage 1 hadn't yet saved a `*-best.ckpt` (no val tick fired). Fallback: use any `*.ckpt` in the checkpoints dir, sorted newest. If still none, abort and ask user (lose the stage-1 work).
- **Stage 2 OOM on RTX 5090** (32 GB) when training previously ran on RTX PRO 6000 (96 GB): drop `batch_size` from 64 to 32 in the resume options. Surface clearly in the result panel.
- **Compose recreate fails** (e.g., volume mount mismatch): revert the compose edit, restart the container with old settings, surface error.

## Out of scope

- The `5090 = DLC` enforcement on `worker` / `worker-tf` containers — same problem in principle, but they're not currently training and the user didn't ask. Defer.

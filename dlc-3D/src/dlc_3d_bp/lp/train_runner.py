"""Lightning-pose training wrapper.

`build_train_config` is a pure config-shaping function (no GPU, no LP imports);
`run_train_subprocess` shells out to `litpose train`. The Celery task drives
both.
"""
from __future__ import annotations

import datetime
import os
import re
import subprocess
import time
from pathlib import Path

import yaml

_DEFAULT_PATCH_MASKING = {
    "enabled": False,
    "init_epoch": 5,
    "final_epoch": 50,
    "init_ratio": 0.0,
    "final_ratio": 0.5,
}

_CAM_RE = re.compile(r"_cam(\d+)_")


def _build_mvt_video_subdir(parent_videos, view_names, stage2_dir):
    """Create ``<stage2_dir>/videos_mvt_filtered/`` containing symlinks to only
    the videos in ``parent_videos`` that have a complete sibling set across
    ``view_names``. Returns ``(out_dir: Path, kept_sessions: int, dropped: list[str])``.

    Pairing rule: for each video stem containing a ``_cam{N}_`` token, build
    the session key by replacing that token with a placeholder. A session is
    "complete" iff for every view in ``view_names`` the substituted filename
    exists in ``parent_videos``. Files without a ``_cam{N}_`` token are skipped
    silently (they're not orphans, just not multi-view candidates).
    """
    parent_videos = Path(parent_videos)
    stage2_dir = Path(stage2_dir)
    out_dir = stage2_dir / "videos_mvt_filtered"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Bucket files by session key (path with the cam-token replaced by a marker)
    by_session: dict = {}
    untagged: list = []
    for p in sorted(parent_videos.iterdir()):
        if not p.is_file() and not p.is_symlink():
            continue
        m = _CAM_RE.search(p.name)
        if not m:
            untagged.append(p)
            continue
        view_token = f"_cam{m.group(1)}_"
        view_name = f"cam{m.group(1)}"
        session_key = p.name.replace(view_token, "_camX_", 1)
        by_session.setdefault(session_key, {})[view_name] = p

    kept_sessions = 0
    dropped: list = []
    expected = set(view_names)
    for session_key, view_to_path in by_session.items():
        present = set(view_to_path.keys())
        if expected.issubset(present):
            # Complete pair — symlink every requested view
            for view in view_names:
                src = view_to_path[view]
                dst = out_dir / src.name
                if dst.exists() or dst.is_symlink():
                    continue
                # symlink to the *resolved* target so cross-stage moves still work
                os.symlink(os.path.realpath(str(src)), str(dst))
            kept_sessions += 1
        else:
            # Orphan(s) — report each present view file
            for view_name, p in view_to_path.items():
                dropped.append(p.name)

    return out_dir, kept_sessions, dropped


def make_run_dir(lp_project: Path | str) -> Path:
    lp_project = Path(lp_project)
    runs = lp_project / "models"
    runs.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = runs / ts
    d.mkdir()
    return d


def build_train_config(
    base_config_path: Path | str,
    out_path: Path | str,
    options: dict,
) -> None:
    """Read the LP project's base config.yaml, apply options, write to out_path."""
    base_config_path = Path(base_config_path)
    out_path = Path(out_path)
    cfg = yaml.safe_load(base_config_path.read_text()) or {}
    cfg.setdefault("data", {})
    cfg.setdefault("model", {})
    cfg.setdefault("training", {})
    cfg.setdefault("losses", {})
    cfg.setdefault("eval", {})
    # LP 2.1.0's predict reads cfg.dali directly; bake defaults at train time so
    # predict doesn't need a runtime injection on the resulting model dir.
    cfg.setdefault("dali", {
        "general": {"seed": 123456},
        "base": {
            "train":   {"sequence_length": 32},
            "predict": {"sequence_length": 96},
        },
        "context": {
            "train":   {"batch_size": 16},
            "predict": {"sequence_length": 96},
        },
    })

    # MVT toggle. LP 2.1.0 calls the supervised multi-view model
    # ``heatmap_multiview_transformer``; older naming was ``multiview_heatmap``.
    if options.get("mvt_enabled", True):
        cfg["model"]["model_type"] = "heatmap_multiview_transformer"
    elif options.get("model_type"):
        cfg["model"]["model_type"] = options["model_type"]

    if options.get("backbone"):
        cfg["model"]["backbone"] = options["backbone"]

    # Patch masking
    if options.get("patch_masking_enabled"):
        pm = dict(_DEFAULT_PATCH_MASKING)
        pm.update({
            "enabled": True,
            "init_epoch":  options.get("patch_masking_init_epoch", pm["init_epoch"]),
            "final_epoch": options.get("patch_masking_final_epoch", pm["final_epoch"]),
            "init_ratio":  options.get("patch_masking_init_ratio", pm["init_ratio"]),
            "final_ratio": options.get("patch_masking_final_ratio", pm["final_ratio"]),
        })
        cfg["model"].setdefault("mvt", {})["patch_masking"] = pm

    # 3D reprojection loss. LP 2.1.0 anneals the unsupervised-loss weight via
    # the AnnealWeight callback, which is required to exist whenever an
    # unsupervised loss like supervised_reprojection_heatmap_mse is present.
    if options.get("reproj_loss_enabled"):
        cfg["training"]["imgaug_3d"] = True
        cfg["losses"]["supervised_reprojection_heatmap_mse"] = {
            "log_weight": options.get("reproj_loss_log_weight", 3.0),
        }
        cfg.setdefault("callbacks", {})["anneal_weight"] = {
            "attr_name": "total_unsupervised_importance",
            "init_val": 0.0,
            "increase_factor": 0.01,
            "final_val": 1.0,
            "freeze_until_epoch": 0,
        }

    # ── Semi-supervised training (temporal loss only, first cut) ────────
    if options.get("semi_supervised_enabled"):
        loss_log_weight = float(options.get("temporal_log_weight", 5.0))
        loss_epsilon    = float(options.get("temporal_epsilon", 0.0))
        cfg.setdefault("model", {}).setdefault("losses_to_use", [])
        if "temporal" not in cfg["model"]["losses_to_use"]:
            cfg["model"]["losses_to_use"].append("temporal")
        cfg.setdefault("losses", {})
        cfg["losses"]["temporal"] = {
            "log_weight": loss_log_weight,
            "epsilon":    loss_epsilon,
        }
        cfg.setdefault("callbacks", {}).setdefault("anneal_weight", {
            "attr_name": "total_unsupervised_importance",
            "init_val": 0.0,
            "increase_factor": 0.01,
            "final_val": 1.0,
            "freeze_until_epoch": 0,
        })
        # Stage-2 MVT video filter: when caller provides parent_videos_dir +
        # stage2_dir, build videos_mvt_filtered/ and re-point data.video_dir.
        parent_videos = options.get("parent_videos_dir")
        stage2_dir    = options.get("stage2_dir")
        if parent_videos and stage2_dir:
            out_dir, kept, dropped = _build_mvt_video_subdir(
                Path(parent_videos),
                cfg.get("data", {}).get("view_names", []),
                Path(stage2_dir),
            )
            cfg.setdefault("data", {})["video_dir"] = str(out_dir)
            # Annotate the cfg with the filter report so the run-time log
            # can pick it up (tasks.py emits this in the train log).
            cfg.setdefault("metadata", {})["mvt_video_filter"] = {
                "kept_sessions": kept,
                "dropped_files": dropped,
            }

    # Training params
    for src, dst in (("max_epochs", "max_epochs"),
                     ("batch_size", "train_batch_size"),
                     ("batch_size", "val_batch_size"),
                     ("batch_size", "test_batch_size")):
        if src in options:
            cfg["training"][dst] = options[src]

    # Early-stopping controls (stage 2 / single-stage). Mirror what stage 1 did:
    # honor an explicit `early_stop_patience` from options. When unset, leave
    # LP's canonical default in place (~5). Long runs on small val sets need a
    # bigger patience to ride out noisy validation curves — without this, an
    # MVT on 540/28 train/val split typically early-stops near epoch ~45 even
    # when max_epochs=300, leaving the model undertrained.
    if "early_stop_patience" in options:
        cfg["training"]["early_stopping"] = True
        cfg["training"]["early_stop_patience"] = int(options["early_stop_patience"])
    if options.get("disable_early_stopping"):
        cfg["training"]["early_stopping"] = False

    # Keep min_epochs <= max_epochs. LP 2.1.0 asserts both keys are present and
    # uses them as PL Trainer args; min_epochs > max_epochs would error.
    if "max_epochs" in options:
        max_e = int(options["max_epochs"])
        cfg["training"]["min_epochs"] = min(
            cfg["training"].get("min_epochs", 1), max_e
        )
        # Clamp val frequency so validation runs at least once before training
        # ends. Without this, short smoke runs (max_epochs < default 5) leave
        # `*-best.ckpt` unwritten and LP's post-train eval crashes with
        # "Checkpoint file not found, have you trained for enough epochs?".
        current_val = cfg["training"].get("check_val_every_n_epoch", 5) or 5
        cfg["training"]["check_val_every_n_epoch"] = max(1, min(current_val, max_e))
    # Lr scheduler milestones must be <= max_epochs or the multi-step LR is
    # a no-op for short smoke runs — that's fine, but ensure the list isn't
    # required to be filtered. (left as-is)

    # Eval flags. Upstream canonical defaults predict_vids_after_training=true,
    # which fires LP's _predict_test_videos at end-of-train. In our pipeline the
    # explicit Predict card is the right path for inference, so we make this an
    # explicit opt-in (default False) regardless of upstream canonical.
    cfg["eval"]["predict_vids_after_training"] = bool(
        options.get("predict_vids_after_training", False)
    )
    cfg["eval"]["save_vids_after_training"] = bool(
        options.get("save_vids_after_training", False)
    )

    out_path.write_text(yaml.safe_dump(cfg, sort_keys=False))


# tqdm progress line pattern: `<prefix>: NN%|<bar>| N/M [...]`.
# The prefix is everything before the first colon (e.g., 'Epoch 0',
# 'Predicting DataLoader 0', 'Validation DataLoader 0').
_TQDM_RE = re.compile(r"^(?P<prefix>[^:]+):\s+(?P<pct>\d+)%\|")


def _make_log_throttler(callback, min_interval: float = 3.0):
    """Wrap *callback* so tqdm progress-bar updates are rate-limited.

    litpose emits dozens of tqdm updates per second (~540 lines per training
    epoch, ~284 per predict loop). Without throttling, the last-N-line tail
    in the UI is always saturated with the current epoch's batch progress,
    pushing structural events (config dump, epoch transitions, our stage
    emits, errors) out of sight.

    Rules per emitted line:
      * Non-tqdm line → always pass through to ``callback``.
      * Tqdm line with a NEW prefix → emit (signals start of a new bar).
      * Tqdm line at 100% completion → emit (signals end of a bar).
      * Tqdm line within ``min_interval`` seconds of the last emit for the
        same prefix → drop.
      * Otherwise → emit (regular throttled tick).
    """
    state: dict = {}

    def filtered(line: str) -> None:
        if callback is None:
            return
        m = _TQDM_RE.match(line)
        if not m:
            callback(line)
            return
        prefix = m.group("prefix").strip()
        pct = int(m.group("pct"))
        now = time.time()
        last = state.get(prefix)
        if last is None or pct == 100 or (now - last) >= min_interval:
            callback(line)
            state[prefix] = now
        # else: throttled — drop silently

    return filtered


def run_train_subprocess(model_dir: Path | str, log_callback=None, cwd: Path | str | None = None) -> int:
    """Spawn `litpose train`. Return process returncode.

    log_callback: optional callable(line: str) -> None invoked once per stdout
    line, with tqdm progress lines throttled (see :func:`_make_log_throttler`).

    The installed `litpose` 2.1.0 CLI takes the config as a positional argument
    (not `--config`), and supports `--output_dir` for the model directory.
    """
    model_dir = Path(model_dir)
    cfg = model_dir / "config.yaml"
    cmd = ["litpose", "train", str(cfg), "--output_dir", str(model_dir)]
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "0"}
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, cwd=str(cwd) if cwd else None,
        env=env,
    )
    sink = _make_log_throttler(log_callback) if log_callback else None
    for line in proc.stdout:  # type: ignore[union-attr]
        if sink is not None:
            try:
                sink(line.rstrip("\n"))
            except Exception:
                pass
    return proc.wait()


def find_best_checkpoint(model_dir) -> Path | None:
    """Return the newest ``*-best.ckpt`` under ``<model_dir>/tb_logs/.../checkpoints/``.

    Falls back to any ``*.ckpt`` if no *-best is present. Returns None when
    no checkpoint exists at all.
    """
    model_dir = Path(model_dir)
    best = list(model_dir.glob("tb_logs/*/version_*/checkpoints/*-best.ckpt"))
    if best:
        return max(best, key=lambda p: p.stat().st_mtime)
    any_ckpt = list(model_dir.glob("tb_logs/*/version_*/checkpoints/*.ckpt"))
    if any_ckpt:
        return max(any_ckpt, key=lambda p: p.stat().st_mtime)
    return None


def build_stage1_config(
    sv_project,
    out_dir,
    options: dict,
) -> None:
    """Materialise stage-1's config.yaml at ``<out_dir>/config.yaml``.

    Starts from the SV-pretrain project's ``config.yaml`` and overlays
    short-run + early-stopping defaults so stage 1 finishes quickly once
    val loss plateaus.
    """
    sv_cfg_path = Path(sv_project) / "config.yaml"
    cfg = yaml.safe_load(sv_cfg_path.read_text()) or {}
    training = cfg.setdefault("training", {})
    max_epochs = int(options.get("stage1_max_epochs", 100))
    training["max_epochs"] = max_epochs
    training["min_epochs"] = min(training.get("min_epochs", 1) or 1, max_epochs)
    training["early_stopping"] = True
    training["early_stop_patience"] = int(options.get("stage1_early_stop_patience", 5))
    # Clamp val frequency so validation runs at least once before training ends.
    # LP's canonical default is check_val_every_n_epoch=5; if stage1_max_epochs
    # is smaller, no validation tick fires, no `*-best.ckpt` is saved, and LP's
    # post-train eval (predict_on_label_csv) crashes with FileNotFoundError.
    current_val = training.get("check_val_every_n_epoch", 5) or 5
    training["check_val_every_n_epoch"] = max(1, min(current_val, max_epochs))
    # Stage 1 only needs to produce a backbone checkpoint — skip post-train
    # video prediction so LP doesn't try to resolve `${data.video_dir}` (which
    # for the SV sub-project is a relative `../videos` path that Hydra fails
    # to resolve from its working dir).
    eval_block = cfg.setdefault("eval", {})
    eval_block["predict_vids_after_training"] = False
    eval_block["save_vids_after_training"] = False
    # No patch masking, no reproj for stage 1.
    cfg.setdefault("losses", {})
    cfg.setdefault("callbacks", {})
    # Optional semi-supervised temporal loss for stage 1 (SV-pretrain sees all
    # videos in the parent's `videos/` dir; no filter applies here).
    if options.get("semi_supervised_enabled"):
        loss_log_weight = float(options.get("temporal_log_weight", 5.0))
        loss_epsilon    = float(options.get("temporal_epsilon", 0.0))
        cfg.setdefault("model", {}).setdefault("losses_to_use", [])
        if "temporal" not in cfg["model"]["losses_to_use"]:
            cfg["model"]["losses_to_use"].append("temporal")
        cfg["losses"]["temporal"] = {
            "log_weight": loss_log_weight,
            "epsilon":    loss_epsilon,
        }
        cfg["callbacks"].setdefault("anneal_weight", {
            "attr_name": "total_unsupervised_importance",
            "init_val": 0.0,
            "increase_factor": 0.01,
            "final_val": 1.0,
            "freeze_until_epoch": 0,
        })
    Path(out_dir, "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))

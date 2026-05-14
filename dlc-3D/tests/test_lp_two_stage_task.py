"""Tests for two-stage training: checkpoint discovery + task orchestration."""
from pathlib import Path

import pytest

from dlc_3d_bp.lp.train_runner import find_best_checkpoint


def test_find_best_checkpoint_returns_newest_best(tmp_path):
    """When multiple *-best.ckpt files exist, return the newest by mtime."""
    base = tmp_path / "stage1" / "tb_logs" / "test" / "version_0" / "checkpoints"
    base.mkdir(parents=True)
    a = base / "epoch=0-step=100-best.ckpt"; a.write_bytes(b"a"); import os, time
    time.sleep(0.01)
    b = base / "epoch=5-step=600-best.ckpt"; b.write_bytes(b"b")
    assert find_best_checkpoint(tmp_path / "stage1") == b


def test_find_best_checkpoint_falls_back_to_last(tmp_path):
    """No *-best.ckpt → return the only .ckpt file present."""
    base = tmp_path / "stage1" / "tb_logs" / "test" / "version_0" / "checkpoints"
    base.mkdir(parents=True)
    only = base / "epoch=10-step=1000.ckpt"; only.write_bytes(b"x")
    assert find_best_checkpoint(tmp_path / "stage1") == only


def test_find_best_checkpoint_returns_none_when_absent(tmp_path):
    (tmp_path / "stage1").mkdir()
    assert find_best_checkpoint(tmp_path / "stage1") is None


import yaml
from dlc_3d_bp.lp.train_runner import build_stage1_config


def test_build_stage1_config_emits_short_run_with_early_stopping(tmp_path):
    # Source SV config (mock — just needs to be valid YAML)
    sv = tmp_path / "sv"; sv.mkdir()
    (sv / "config.yaml").write_text(yaml.safe_dump({
        "data": {"csv_file": "labels.csv", "video_dir": "../videos"},
        "model": {"backbone": "vits_dino", "model_type": "heatmap"},
        "training": {"max_epochs": 300, "min_epochs": 300, "early_stopping": False},
    }))

    out_dir = tmp_path / "run" / "stage1"
    out_dir.mkdir(parents=True)
    build_stage1_config(sv_project=sv, out_dir=out_dir, options={
        "stage1_max_epochs": 50,
        "stage1_early_stop_patience": 4,
    })

    cfg = yaml.safe_load((out_dir / "config.yaml").read_text())
    assert cfg["training"]["max_epochs"] == 50
    assert cfg["training"]["min_epochs"] <= 50
    assert cfg["training"]["early_stopping"] is True
    assert cfg["training"]["early_stop_patience"] == 4

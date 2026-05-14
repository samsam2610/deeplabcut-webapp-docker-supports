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

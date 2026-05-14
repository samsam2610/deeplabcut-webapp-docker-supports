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


import sys, types
from unittest.mock import patch, MagicMock


def _make_celery_self():
    """A stand-in for the bound `self` on a Celery task — enough surface for
    the task body to call update_state and access request.id."""
    s = MagicMock()
    s.request = MagicMock()
    s.request.id = "fake-task-id"
    return s


def test_lp_train_two_stage_runs_both_stages(tmp_path, monkeypatch):
    """When options.two_stage is True, the task invokes run_predict_subprocess-
    style litpose twice — once on sv-pretrain, once on the parent — and the
    stage-2 config gets model.checkpoint set to stage-1's best ckpt."""
    # Build a synthetic LP project layout
    lp = tmp_path / "lp"; lp.mkdir()
    (lp / "config.yaml").write_text("data:\n  view_names:\n    - cam0\n    - cam1\nmodel: {}\ntraining: {}\nlosses: {}\ncallbacks: {}\neval: {}\n")
    sv = lp / "sv-pretrain"; sv.mkdir()
    (sv / "config.yaml").write_text("data: {csv_file: labels.csv}\nmodel: {backbone: vits_dino, model_type: heatmap}\ntraining: {min_epochs: 1, max_epochs: 1}\nlosses: {}\ncallbacks: {}\neval: {}\n")

    calls = []

    def _fake_subprocess(model_dir, *, log_callback=None, **kw):
        # Record the call and synthesise the ckpt that find_best_checkpoint expects
        calls.append(("subprocess", Path(model_dir)))
        ckpt_dir = Path(model_dir) / "tb_logs" / "test" / "version_0" / "checkpoints"
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        (ckpt_dir / "epoch=0-step=10-best.ckpt").write_bytes(b"\x00")
        return 0  # success

    monkeypatch.setattr("dlc_3d_bp.lp.train_runner.run_train_subprocess", _fake_subprocess)
    monkeypatch.setattr("dlc_3d_bp.lp.predict_runner.relocate_predictions", lambda *a, **kw: {"moved":0,"skipped":[],"dest_dir":None,"dest_paths":[]})

    from dlc_3d_bp.lp.tasks import lp_train

    options = {
        "two_stage": True,
        "stage1_max_epochs": 1,
        "max_epochs": 1,
        "batch_size": 2,
    }
    # Call the task body bypassing Celery
    result = lp_train.__wrapped__(_make_celery_self(), str(lp), options)

    # Two subprocess invocations
    assert len(calls) == 2
    stage1_dir, stage2_dir = calls[0][1], calls[1][1]
    assert stage1_dir.name == "stage1"
    assert stage2_dir.name == "stage2"

    # Stage-2 config carries the stage-1 ckpt
    s2_cfg_path = stage2_dir / "config.yaml"
    cfg = yaml.safe_load(s2_cfg_path.read_text())
    assert cfg["model"]["checkpoint"].endswith("-best.ckpt")
    assert "stage1" in cfg["model"]["checkpoint"]


def test_lp_train_two_stage_skips_stage1_when_override_set(tmp_path, monkeypatch):
    """options.stage1_ckpt_override → skip stage 1, run stage 2 only with that ckpt."""
    lp = tmp_path / "lp"; lp.mkdir()
    (lp / "config.yaml").write_text("data:\n  view_names:\n    - cam0\n    - cam1\nmodel: {}\ntraining: {}\nlosses: {}\ncallbacks: {}\neval: {}\n")
    (lp / "sv-pretrain").mkdir()
    (lp / "sv-pretrain" / "config.yaml").write_text("data: {}\nmodel: {}\ntraining: {}\nlosses: {}\ncallbacks: {}\neval: {}\n")

    fake_ckpt = tmp_path / "external" / "epoch=99-best.ckpt"
    fake_ckpt.parent.mkdir(parents=True)
    fake_ckpt.write_bytes(b"x")

    calls = []
    def _fake_subprocess(model_dir, *, log_callback=None, **kw):
        calls.append(Path(model_dir))
        return 0
    monkeypatch.setattr("dlc_3d_bp.lp.train_runner.run_train_subprocess", _fake_subprocess)
    monkeypatch.setattr("dlc_3d_bp.lp.predict_runner.relocate_predictions", lambda *a, **kw: {"moved":0,"skipped":[],"dest_dir":None,"dest_paths":[]})

    from dlc_3d_bp.lp.tasks import lp_train
    lp_train.__wrapped__(_make_celery_self(), str(lp), {
        "two_stage": True,
        "stage1_ckpt_override": str(fake_ckpt),
        "max_epochs": 1, "batch_size": 2,
    })

    # Only one subprocess call (stage 2)
    assert len(calls) == 1
    assert calls[0].name == "stage2"
    # Stage 2 config has the override checkpoint
    cfg = yaml.safe_load((calls[0] / "config.yaml").read_text())
    assert cfg["model"]["checkpoint"] == str(fake_ckpt)


def test_lp_train_two_stage_fails_on_no_stage1_checkpoint(tmp_path, monkeypatch):
    """Stage 1 finishes (rc=0) but no ckpt → RuntimeError surfaces."""
    lp = tmp_path / "lp"; lp.mkdir()
    (lp / "config.yaml").write_text("data:\n  view_names:\n    - cam0\n    - cam1\nmodel: {}\ntraining: {}\nlosses: {}\ncallbacks: {}\neval: {}\n")
    (lp / "sv-pretrain").mkdir()
    (lp / "sv-pretrain" / "config.yaml").write_text("data: {}\nmodel: {}\ntraining: {}\nlosses: {}\ncallbacks: {}\neval: {}\n")

    def _fake_subprocess(model_dir, *, log_callback=None, **kw):
        # Don't write any ckpt
        return 0
    monkeypatch.setattr("dlc_3d_bp.lp.train_runner.run_train_subprocess", _fake_subprocess)

    from dlc_3d_bp.lp.tasks import lp_train
    with pytest.raises(RuntimeError, match="stage 1 produced no checkpoint"):
        lp_train.__wrapped__(_make_celery_self(), str(lp), {"two_stage": True})

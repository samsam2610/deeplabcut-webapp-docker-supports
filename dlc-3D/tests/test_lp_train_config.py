from pathlib import Path
import yaml
import pytest

from dlc_3d_bp.lp.train_runner import build_train_config, make_run_dir


def _base_lp_config(tmp_path: Path) -> Path:
    cfg = {
        "data": {"csv_file": ["cam0.csv", "cam1.csv"], "view_names": ["cam0", "cam1"]},
        "model": {"model_type": "multiview_heatmap", "backbone": "resnet50_animal_apose", "losses_to_use": []},
        "training": {"max_epochs": 300, "train_batch_size": 16, "imgaug_3d": False},
        "losses": {},
        "eval": {"predict_vids_after_training": False, "save_vids_after_training": False},
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return p


def test_make_run_dir(tmp_path):
    lp_project = tmp_path / "lp"; lp_project.mkdir()
    d = make_run_dir(lp_project)
    assert d.parent == lp_project / "models"
    assert d.is_dir()


def test_build_config_mvt_default(tmp_path):
    base = _base_lp_config(tmp_path)
    out = tmp_path / "out" / "config.yaml"
    out.parent.mkdir()
    build_train_config(base, out, options={
        "mvt_enabled": True,
        "patch_masking_enabled": False,
        "reproj_loss_enabled": False,
        "max_epochs": 50,
        "batch_size": 8,
    })
    cfg = yaml.safe_load(out.read_text())
    assert cfg["model"]["model_type"] == "heatmap_multiview_transformer"
    assert cfg["training"]["max_epochs"] == 50
    assert cfg["training"]["train_batch_size"] == 8
    assert "supervised_reprojection_heatmap_mse" not in cfg["losses"]


def test_build_config_patch_masking(tmp_path):
    base = _base_lp_config(tmp_path)
    out = tmp_path / "out" / "config.yaml"
    out.parent.mkdir()
    build_train_config(base, out, options={
        "mvt_enabled": True,
        "patch_masking_enabled": True,
        "patch_masking_init_epoch": 10,
        "patch_masking_final_epoch": 100,
        "patch_masking_init_ratio": 0.0,
        "patch_masking_final_ratio": 0.5,
    })
    cfg = yaml.safe_load(out.read_text())
    pm = cfg["model"]["mvt"]["patch_masking"]
    assert pm["enabled"] is True
    assert pm["init_epoch"] == 10
    assert pm["final_ratio"] == 0.5


def test_build_config_3d_reprojection_loss(tmp_path):
    base = _base_lp_config(tmp_path)
    out = tmp_path / "out" / "config.yaml"
    out.parent.mkdir()
    build_train_config(base, out, options={
        "mvt_enabled": True,
        "reproj_loss_enabled": True,
        "reproj_loss_log_weight": 3.0,
    })
    cfg = yaml.safe_load(out.read_text())
    assert cfg["training"]["imgaug_3d"] is True
    assert cfg["losses"]["supervised_reprojection_heatmap_mse"]["log_weight"] == 3.0


def test_build_config_eval_flags(tmp_path):
    base = _base_lp_config(tmp_path)
    out = tmp_path / "out" / "config.yaml"
    out.parent.mkdir()
    build_train_config(base, out, options={
        "predict_vids_after_training": True,
        "save_vids_after_training":    True,
    })
    cfg = yaml.safe_load(out.read_text())
    assert cfg["eval"]["predict_vids_after_training"] is True
    assert cfg["eval"]["save_vids_after_training"] is True

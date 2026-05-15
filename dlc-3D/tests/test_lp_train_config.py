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
    aw = cfg["callbacks"]["anneal_weight"]
    assert aw["attr_name"] == "total_unsupervised_importance"
    assert aw["final_val"] == 1.0


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


def test_build_config_includes_dali_defaults(tmp_path):
    """LP 2.1.0 requires cfg.dali for predict; build_train_config bakes defaults."""
    base = _base_lp_config(tmp_path)
    out = tmp_path / "out" / "config.yaml"
    out.parent.mkdir()
    build_train_config(base, out, options={"mvt_enabled": True, "max_epochs": 1})
    cfg = yaml.safe_load(out.read_text())
    assert "dali" in cfg
    assert cfg["dali"]["base"]["predict"]["sequence_length"] == 96
    assert cfg["dali"]["general"]["seed"] == 123456


def _make_cfgs(tmp_path: Path):
    """Adapter: return (src_cfg, dst_cfg) pair compatible with the upstream
    plan's test scaffolding. ``dst_cfg`` lives in its own subdir so callers
    can treat ``dst_cfg.parent`` as the stage2 dir."""
    src_cfg = _base_lp_config(tmp_path)
    dst_dir = tmp_path / "stage2"
    dst_dir.mkdir(exist_ok=True)
    return src_cfg, dst_dir / "config.yaml"


def test_temporal_loss_disabled_by_default(tmp_path):
    """No semi_supervised option → losses_to_use stays empty and temporal not configured."""
    src_cfg, dst_cfg = _make_cfgs(tmp_path)
    build_train_config(src_cfg, dst_cfg, options={})
    c = yaml.safe_load(dst_cfg.read_text())
    assert c["model"].get("losses_to_use", []) == []
    assert "temporal" not in (c.get("losses") or {})


def test_temporal_loss_enabled_writes_config(tmp_path):
    src_cfg, dst_cfg = _make_cfgs(tmp_path)
    build_train_config(src_cfg, dst_cfg, options={
        "semi_supervised_enabled": True,
        "temporal_log_weight": 4.5,
        "temporal_epsilon": 0.1,
    })
    c = yaml.safe_load(dst_cfg.read_text())
    assert c["model"]["losses_to_use"] == ["temporal"]
    assert c["losses"]["temporal"]["log_weight"] == 4.5
    assert c["losses"]["temporal"]["epsilon"] == 0.1
    # anneal_weight callback must exist (LP requires it for any unsup loss)
    assert "anneal_weight" in c.get("callbacks", {})


def test_stage2_video_dir_points_at_filtered_subdir(tmp_path):
    """When semi_supervised_enabled=True AND stage2_dir is supplied AND
    parent_videos_dir is supplied, build_train_config sets
    cfg.data.video_dir to a freshly-built videos_mvt_filtered/ subdir."""
    src_cfg, dst_cfg = _make_cfgs(tmp_path)
    parent_videos = tmp_path / "parent_videos"; parent_videos.mkdir()
    # Create one paired session and one orphan
    (parent_videos / "s_cam0_x.mp4").write_bytes(b"")
    (parent_videos / "s_cam1_x.mp4").write_bytes(b"")
    (parent_videos / "orphan_cam0_y.mp4").write_bytes(b"")
    stage2_dir = dst_cfg.parent  # build_train_config writes the cfg into stage2_dir

    build_train_config(src_cfg, dst_cfg, options={
        "semi_supervised_enabled": True,
        "temporal_log_weight": 5.0,
        "parent_videos_dir": str(parent_videos),
        "stage2_dir": str(stage2_dir),
    })
    c = yaml.safe_load(dst_cfg.read_text())
    assert c["data"]["video_dir"] == str(stage2_dir / "videos_mvt_filtered")
    kept = sorted(p.name for p in (stage2_dir / "videos_mvt_filtered").iterdir())
    assert kept == ["s_cam0_x.mp4", "s_cam1_x.mp4"]


def test_stage2_video_dir_unchanged_when_filter_skipped(tmp_path):
    """No parent_videos_dir / stage2_dir → keep upstream video_dir untouched."""
    src_cfg, dst_cfg = _make_cfgs(tmp_path)
    build_train_config(src_cfg, dst_cfg, options={
        "semi_supervised_enabled": True,
        "temporal_log_weight": 5.0,
    })
    c = yaml.safe_load(dst_cfg.read_text())
    # Upstream LP default — usually "videos" relative to data_dir
    assert "videos_mvt_filtered" not in (c.get("data", {}).get("video_dir") or "")

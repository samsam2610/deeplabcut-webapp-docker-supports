# LP Semi-Supervised Training (Temporal Loss) — Train-card UI + Stage-aware Video Filtering

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire LP's upstream semi-supervised training (Temporal loss only, first cut) into the dlc-3d Train card. Stage 1 (SV-pretrain) sees ALL videos in `<lp>/videos/`; Stage 2 (MVT) sees only sibling-paired videos via a filtered `videos_mvt_filtered/` subdir that the build creates from `view_names`-based pairing.

**Architecture:**
- `train_runner.build_train_config` / `build_stage1_config` honour new `semi_supervised_enabled`, `temporal_log_weight`, `temporal_epsilon` options.
- New helper `train_runner._build_mvt_video_subdir(parent_videos, view_names, stage2_dir) -> Path` (under `<stage2_dir>/videos_mvt_filtered/`, symlinked, returns the subdir + list of dropped orphan stems for the log).
- `card_lp_train.html`: one checkbox, one numeric input, hint text.
- `lp_cards.js` (`initTrainCard`): include the new options in the POST payload.

**Tech stack:** Python + pathlib for the filter; pytest with tmp_path for tests; vanilla JS for the toggle wiring. No new deps.

---

## File Structure

```
src/dlc_3d_bp/lp/
  train_runner.py                         ← MODIFY: add temporal loss + MVT video filter

src/templates/partials/
  card_lp_train.html                      ← MODIFY: checkbox + log_weight input

src/static/
  lp_cards.js                             ← MODIFY: initTrainCard passes new options

tests/
  test_lp_train_config.py                 ← MODIFY: temporal-loss + video-filter coverage
  test_lp_mvt_video_filter.py             ← NEW: unit-test the sibling pair filter
```

No backend route changes — `/lp/train` already passes the entire `options` dict through to the Celery task and on into `build_train_config`. Adding new option keys is purely additive.

---

### Task 1: MVT video-filter helper

**Files:**
- Modify: `src/dlc_3d_bp/lp/train_runner.py`
- Test:   `tests/test_lp_mvt_video_filter.py`

The filter mirrors the sibling-pairing rule already used by `predict_runner._resolve_siblings`: stems contain `_cam{N}_` for some `N`; a session is "paired" iff for every view in `view_names`, the stem with that view's `_cam{N}_` substitution exists in the source videos dir.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_lp_mvt_video_filter.py
"""Unit tests for the MVT video sibling-pair filter."""
import os
from pathlib import Path
import pytest

from dlc_3d_bp.lp.train_runner import _build_mvt_video_subdir


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")


def test_filter_paired_only(tmp_path):
    videos = tmp_path / "videos"; videos.mkdir()
    stage2 = tmp_path / "stage2"; stage2.mkdir()
    _touch(videos / "sess1_cam0_x.mp4")
    _touch(videos / "sess1_cam1_x.mp4")
    _touch(videos / "sess2_cam0_y.mp4")          # orphan, no cam1 sibling
    _touch(videos / "sess3_cam0_z.mp4")
    _touch(videos / "sess3_cam1_z.mp4")

    out_dir, kept, dropped = _build_mvt_video_subdir(videos, ["cam0", "cam1"], stage2)

    assert out_dir == stage2 / "videos_mvt_filtered"
    assert out_dir.is_dir()
    kept_names = sorted(p.name for p in out_dir.iterdir())
    assert kept_names == sorted([
        "sess1_cam0_x.mp4", "sess1_cam1_x.mp4",
        "sess3_cam0_z.mp4", "sess3_cam1_z.mp4",
    ])
    assert kept == 2                                       # 2 sessions kept
    assert dropped == ["sess2_cam0_y.mp4"]                 # 1 orphan reported
    # All entries are symlinks to the originals
    for entry in out_dir.iterdir():
        assert entry.is_symlink()
        assert os.path.realpath(str(entry)) == str(videos / entry.name)


def test_filter_handles_three_views(tmp_path):
    videos = tmp_path / "videos"; videos.mkdir()
    stage2 = tmp_path / "stage2"; stage2.mkdir()
    for v in ("cam0", "cam1", "cam2"):
        _touch(videos / f"trio_{v}_a.mp4")
    _touch(videos / "duo_cam0_b.mp4")    # missing cam1 and cam2 siblings
    _touch(videos / "duo_cam1_b.mp4")

    out_dir, kept, dropped = _build_mvt_video_subdir(videos, ["cam0", "cam1", "cam2"], stage2)
    kept_names = sorted(p.name for p in out_dir.iterdir())
    assert kept_names == sorted([f"trio_{v}_a.mp4" for v in ("cam0", "cam1", "cam2")])
    assert kept == 1
    # Both partial siblings reported as dropped
    assert sorted(dropped) == sorted(["duo_cam0_b.mp4", "duo_cam1_b.mp4"])


def test_filter_idempotent(tmp_path):
    videos = tmp_path / "videos"; videos.mkdir()
    stage2 = tmp_path / "stage2"; stage2.mkdir()
    _touch(videos / "s_cam0_x.mp4")
    _touch(videos / "s_cam1_x.mp4")
    _build_mvt_video_subdir(videos, ["cam0", "cam1"], stage2)
    out_dir, kept, dropped = _build_mvt_video_subdir(videos, ["cam0", "cam1"], stage2)
    # Re-run produces the same result; no duplicate-symlink errors.
    assert kept == 1
    assert dropped == []
    assert sorted(p.name for p in out_dir.iterdir()) == ["s_cam0_x.mp4", "s_cam1_x.mp4"]


def test_filter_skips_unrecognised_stems(tmp_path):
    """Files without a _cam{N}_ token are ignored entirely (not orphans)."""
    videos = tmp_path / "videos"; videos.mkdir()
    stage2 = tmp_path / "stage2"; stage2.mkdir()
    _touch(videos / "no_cam_token.mp4")
    _touch(videos / "s_cam0_x.mp4")
    _touch(videos / "s_cam1_x.mp4")
    out_dir, kept, dropped = _build_mvt_video_subdir(videos, ["cam0", "cam1"], stage2)
    assert kept == 1
    assert dropped == []  # 'no_cam_token.mp4' is silently ignored (not an orphan)
    assert "no_cam_token.mp4" not in {p.name for p in out_dir.iterdir()}


def test_filter_empty_source(tmp_path):
    videos = tmp_path / "videos"; videos.mkdir()
    stage2 = tmp_path / "stage2"; stage2.mkdir()
    out_dir, kept, dropped = _build_mvt_video_subdir(videos, ["cam0", "cam1"], stage2)
    assert kept == 0
    assert dropped == []
    assert out_dir.is_dir()
    assert not list(out_dir.iterdir())
```

- [ ] **Step 2: Run failing tests**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/test_lp_mvt_video_filter.py -v
```
Expected: `ImportError: cannot import name '_build_mvt_video_subdir'`.

- [ ] **Step 3: Implement the helper** in `train_runner.py`. Place it near the top of the file (after the imports / before `build_train_config`):

```python
import os, re
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
    from pathlib import Path
    parent_videos = Path(parent_videos)
    stage2_dir = Path(stage2_dir)
    out_dir = stage2_dir / "videos_mvt_filtered"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Bucket files by session key (path with the cam-token replaced by a marker)
    by_session: dict[str, dict[str, Path]] = {}
    untagged: list[Path] = []
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
    dropped: list[str] = []
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
```

- [ ] **Step 4: Tests pass**
```bash
pytest tests/test_lp_mvt_video_filter.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**
```bash
git add src/dlc_3d_bp/lp/train_runner.py tests/test_lp_mvt_video_filter.py
git commit -m "feat(dlc-3d): _build_mvt_video_subdir filters paired videos for stage-2 MVT"
```

---

### Task 2: Temporal-loss + video-filter wiring in `build_train_config`

**Files:**
- Modify: `src/dlc_3d_bp/lp/train_runner.py`
- Test:   `tests/test_lp_train_config.py`

- [ ] **Step 1: Read existing test file to match style.** Add the following tests to it (don't replace existing tests):

```python
def test_temporal_loss_disabled_by_default(tmp_path):
    """No semi_supervised option → losses_to_use stays empty and temporal not configured."""
    src_cfg, dst_cfg = _make_cfgs(tmp_path)
    build_train_config(src_cfg, dst_cfg, options={})
    import yaml
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
    import yaml
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
    import yaml
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
    import yaml
    c = yaml.safe_load(dst_cfg.read_text())
    # Upstream LP default — usually "videos" relative to data_dir
    assert "videos_mvt_filtered" not in (c.get("data", {}).get("video_dir") or "")
```

If `_make_cfgs(tmp_path)` doesn't exist in the test file, look for the existing fixture used by other tests in that file and reuse it. If you have to write one, mirror the smallest viable LP config dict that `build_train_config` will accept (project config.yaml seed).

- [ ] **Step 2: Run failing tests**
```bash
pytest tests/test_lp_train_config.py::test_temporal_loss_disabled_by_default \
       tests/test_lp_train_config.py::test_temporal_loss_enabled_writes_config \
       tests/test_lp_train_config.py::test_stage2_video_dir_points_at_filtered_subdir \
       tests/test_lp_train_config.py::test_stage2_video_dir_unchanged_when_filter_skipped -v
```
Expected: all four fail.

- [ ] **Step 3: Implement** — in `build_train_config`, after the reproj-loss block (~line 100) and before the `max_epochs` block, add:

```python
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
            from pathlib import Path as _P
            out_dir, kept, dropped = _build_mvt_video_subdir(
                _P(parent_videos), cfg.get("data", {}).get("view_names", []), _P(stage2_dir),
            )
            cfg.setdefault("data", {})["video_dir"] = str(out_dir)
            # Annotate the cfg with the filter report so the run-time log
            # can pick it up (tasks.py emits this in the train log).
            cfg.setdefault("metadata", {})["mvt_video_filter"] = {
                "kept_sessions": kept,
                "dropped_files": dropped,
            }
```

- [ ] **Step 4: Wire the stage-2 caller in `tasks.py`** so that the two new options flow through automatically when `two_stage=True`.

In `_lp_train_impl` (around the stage-2 branch), before `build_train_config(proj / "config.yaml", stage2_dir / "config.yaml", stage2_options)` is called, augment `stage2_options`:

```python
        # Pass through semi-supervised + parent videos dir so build_train_config
        # can construct the filtered videos_mvt_filtered/ subdir for MVT.
        if stage2_options.get("semi_supervised_enabled"):
            stage2_options.setdefault("parent_videos_dir", str(proj / "videos"))
            stage2_options.setdefault("stage2_dir", str(stage2_dir))
```

- [ ] **Step 5: Wire the stage-1 caller** — `build_stage1_config` already takes options; ensure it copies temporal-loss settings too. Find the function in train_runner.py and add the analogous block after its reproj/patch handling (if any). Stage-1's SV-pretrain project's video_dir stays unchanged (pointing at parent's videos/).

```python
    if options.get("semi_supervised_enabled"):
        loss_log_weight = float(options.get("temporal_log_weight", 5.0))
        loss_epsilon    = float(options.get("temporal_epsilon", 0.0))
        training_cfg.setdefault("model", {}).setdefault("losses_to_use", [])
        if "temporal" not in training_cfg["model"]["losses_to_use"]:
            training_cfg["model"]["losses_to_use"].append("temporal")
        training_cfg.setdefault("losses", {})
        training_cfg["losses"]["temporal"] = {
            "log_weight": loss_log_weight,
            "epsilon":    loss_epsilon,
        }
        training_cfg.setdefault("callbacks", {}).setdefault("anneal_weight", {
            "attr_name": "total_unsupervised_importance",
            "init_val": 0.0,
            "increase_factor": 0.01,
            "final_val": 1.0,
            "freeze_until_epoch": 0,
        })
```

The `training_cfg` symbol may have a different name in your code — match the local variable name `build_stage1_config` already uses for the cfg dict being written.

- [ ] **Step 6: Tests pass**
```bash
pytest tests/test_lp_train_config.py tests/test_lp_mvt_video_filter.py -v
```
Expected: all green (new + existing tests).

- [ ] **Step 7: Commit**
```bash
git add src/dlc_3d_bp/lp/train_runner.py src/dlc_3d_bp/lp/tasks.py tests/test_lp_train_config.py
git commit -m "feat(dlc-3d): temporal-loss semi-supervised + stage-2 MVT video filter"
```

---

### Task 3: Train-card UI

**Files:**
- Modify: `src/templates/partials/card_lp_train.html`
- Modify: `src/static/lp_cards.js` (initTrainCard)

- [ ] **Step 1: Add the markup**

Insert a new section in `card_lp_train.html` near the bottom of the train-options form (after the two-stage / patch-masking / reproj sections, before the Run button). Match the existing visual style (fieldsets + lp-checkbox class):

```html
<!-- ── Semi-supervised training (Temporal loss; uses unlabeled videos in videos/) ── -->
<fieldset class="lp-field">
  <legend>Semi-supervised training</legend>
  <label class="lp-checkbox">
    <input type="checkbox" id="lp-train-semi-supervised">
    Use unlabeled videos via temporal loss
  </label>
  <div id="lp-train-semi-supervised-params" style="display:none;margin-top:.4rem;display:flex;gap:.6rem;align-items:center;flex-wrap:wrap">
    <label style="font-size:.78rem;color:var(--text-dim);display:flex;align-items:center;gap:.3rem">
      log_weight
      <input type="number" id="lp-train-temporal-log-weight" value="5.0" step="0.5" min="0" max="10"
        style="width:5rem;font-family:var(--mono);font-size:.78rem;padding:.2rem .35rem;background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text)">
    </label>
    <label style="font-size:.78rem;color:var(--text-dim);display:flex;align-items:center;gap:.3rem">
      epsilon
      <input type="number" id="lp-train-temporal-epsilon" value="0.0" step="0.1" min="0" max="10"
        style="width:5rem;font-family:var(--mono);font-size:.78rem;padding:.2rem .35rem;background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text)">
    </label>
    <span style="font-size:.7rem;color:var(--text-dim)">Stage 2 (MVT) auto-filters videos to sibling-paired sessions only. Stage 1 (SV) uses all videos.</span>
  </div>
</fieldset>
```

Wire the show/hide toggle for params block: when the checkbox is on, show the params row.

- [ ] **Step 2: Wire the toggle + payload** in `initTrainCard()` of `lp_cards.js`

Add references near the top of the function:
```javascript
const semiEl = $("#lp-train-semi-supervised");
const semiParamsEl = $("#lp-train-semi-supervised-params");
const tempLwEl = $("#lp-train-temporal-log-weight");
const tempEpsEl = $("#lp-train-temporal-epsilon");

semiEl?.addEventListener("change", () => {
  semiParamsEl.style.display = semiEl.checked ? "flex" : "none";
});
```

Then in the run-handler's POST body, include the new keys:
```javascript
options.semi_supervised_enabled = !!semiEl?.checked;
if (semiEl?.checked) {
  options.temporal_log_weight = parseFloat(tempLwEl.value) || 5.0;
  options.temporal_epsilon    = parseFloat(tempEpsEl.value) || 0.0;
}
```

(Find the existing `options` payload construction in the run handler; insert there.)

- [ ] **Step 3: Restart dlc-3d** (template is single-file mount; needs a restart to flush the inode pin):
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d
sleep 3
docker compose exec dlc-3d python3 -c "
import urllib.request
html = urllib.request.urlopen('http://localhost:5050/dlc-3d/').read().decode()
print('lp-train-semi-supervised present:', 'lp-train-semi-supervised' in html)
print('lp-train-temporal-log-weight present:', 'lp-train-temporal-log-weight' in html)
"
```

Expected: both True.

- [ ] **Step 4: Commit**
```bash
git add src/templates/partials/card_lp_train.html src/static/lp_cards.js
git commit -m "feat(dlc-3d): Train card semi-supervised checkbox + temporal params"
```

---

### Task 4: Worker restart + verify

The worker must reload `train_runner.py` and `tasks.py` before any new training submission goes through.

- [ ] **Step 1: Restart worker**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d-worker
sleep 4
docker compose exec dlc-3d-worker bash -c 'ps -eo pid,etime,cmd | grep celery | grep -v grep | head -2'
```

- [ ] **Step 2: Submit a smoke training via the API**

```bash
docker compose exec dlc-3d python3 -c "
import urllib.request, json
body = {
  'lp_project': '/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP',
  'options': {
    'two_stage': True,
    'stage1_ckpt_override': '/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP/models/20260514-133929/stage1/tb_logs/test/version_0/checkpoints/epoch=189-step=35530-best.ckpt',
    'max_epochs': 600,
    'early_stop_patience': 25,
    'batch_size': 64,
    'semi_supervised_enabled': True,
    'temporal_log_weight': 5.0,
    'temporal_epsilon': 0.0,
  },
}
req = urllib.request.Request('http://localhost:5050/dlc-3d/lp/train',
  data=json.dumps(body).encode(), headers={'Content-Type':'application/json'}, method='POST')
print(urllib.request.urlopen(req).read().decode())
"
sleep 8
docker compose exec dlc-3d-worker python3 -c "
import redis, json
r = redis.Redis.from_url('redis://redis:6379/0', decode_responses=True)
keys = sorted(r.keys('dlc3d:lp:log:*'), key=lambda k: r.object('idletime', k) or 0)
# take whichever was modified most recently
newest = sorted(r.keys('dlc3d:lp:log:*'), key=lambda k: -(r.object('idletime', k) or 0))[-1] if r.keys('dlc3d:lp:log:*') else None
print('newest log key:', newest)
if newest:
    for l in r.lrange(newest, 0, 12):
        print('  ', l[:220])
"
```

Expected: the log emits “two-stage: using override ckpt …” → stage-2 starts; in the freshly-built `models/<ts>/stage2/config.yaml`, `data.video_dir` points at `videos_mvt_filtered/`. The `losses_to_use: [temporal]` and `losses.temporal.log_weight: 5.0` are present.

- [ ] **Step 3: Verify the rendered stage-2 config**

```bash
docker compose exec dlc-3d-worker bash -c '
LP=/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07-LP
latest=$(ls -td $LP/models/*/stage2 2>/dev/null | head -1)
echo "stage2 dir: $latest"
python3 -c "
import yaml
c = yaml.safe_load(open(\"$latest/config.yaml\"))
print(\"losses_to_use:\", c[\"model\"].get(\"losses_to_use\"))
print(\"losses.temporal:\", c.get(\"losses\", {}).get(\"temporal\"))
print(\"data.video_dir:\", c[\"data\"].get(\"video_dir\"))
print(\"metadata.mvt_video_filter:\", c.get(\"metadata\", {}).get(\"mvt_video_filter\"))
"
ls -1 "$latest/videos_mvt_filtered/" 2>/dev/null | head -10
'
```

Expected: `losses_to_use: ['temporal']`; `losses.temporal.log_weight: 5.0`; `data.video_dir` ends in `videos_mvt_filtered`; the filtered dir contains the 4 paired khoai-lang video symlinks (cam0+cam1 ×2 sessions).

- [ ] **Step 4: No commit** (smoke only).

---

### Task 5: Final pytest

- [ ] `cd dlc-3D && pytest tests/ -x -q`

Acceptable baseline: same pre-existing failures (e2e Playwright, dirty predict_runner.py). All new tests pass.

---

## Self-review

- [x] No new deps; LP 2.1.0 already exports `temporal` loss + `SemiSupervisedHeatmapTrackerMultiviewTransformer`.
- [x] Backwards-compatible: the semi-supervised toggle is opt-in; default-off matches today's behavior.
- [x] Stage-1 SV pretrain uses the parent's full `videos/` dir per the user's "use all videos" requirement.
- [x] Stage-2 MVT auto-filters to sibling-paired videos in a fresh symlinked subdir; orphans are reported (not crashing).
- [x] Worker restart required (changes to celery task body + train_runner). Flask restart required (template single-file mount).
- [x] Verification step inspects the rendered stage-2 config to confirm the filter and loss block actually wrote through.

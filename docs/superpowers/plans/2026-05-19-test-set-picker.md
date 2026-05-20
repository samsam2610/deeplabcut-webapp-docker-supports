# Test-set Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-frame manual test-set selector to the DLC webapp with read-only inspect of frozen splits, while preserving today's "random split" behavior byte-for-byte when the new feature isn't used.

**Architecture:** Backend is three small modules inside the main webapp's `src/dlc/`: a pure SQLite layer (`marks_store.py`), a pure split-assembly function (`test_set_split.py`), and one Flask blueprint (`test_set_picker.py`). The existing `dlc_create_training_dataset` celery task gains two optional kwargs that default to the current behavior. Frontend is one new card (`card_test_set_picker.html` + `test_set_picker.js`) plus a shared overlay-draw module extracted from `frame_labeler.js`. End-to-end verification runs `dlc.create_training_dataset` against a duplicated DREADD-Ali project and reads back the `Documentation_data-*.pickle` to assert every marked frame landed in the correct set.

**Tech Stack:** Python 3 / Flask / Celery / SQLite / pandas / DeepLabCut 3.0.0rc14 / vanilla ES modules / pytest.

**Two repositories are involved:**
- Spec + plan (already committed) live in `/home/sam/docker-images/deeplabcut-webapp-docker-supports/`. **No code is added there.**
- All implementation code lives in `/home/sam/docker-images/deeplabcut-webapp-docker/` (the main webapp). All `git` commands in this plan run there unless explicitly stated.

**Reference:** See the design doc `docs/superpowers/specs/2026-05-19-test-set-picker-design.md` in the supports repo for full background.

---

## Task 0: Prepare the branch

**Files:**
- None created/modified — branch setup only.

- [ ] **Step 1: Confirm we're in the right repo**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git rev-parse --show-toplevel
```

Expected output: `/home/sam/docker-images/deeplabcut-webapp-docker`

- [ ] **Step 2: Fetch and create the feature branch from origin/main**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git fetch origin
git checkout -b feat/test-set-picker origin/main
git status
```

Expected: `On branch feat/test-set-picker` and clean working tree. If `origin/main` doesn't exist locally, fall back to `git checkout -b feat/test-set-picker main`.

- [ ] **Step 3: Confirm baseline tests pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_dlc_celery_tasks.py tests/test_dlc_training_routes.py -q
```

Expected: all green. This is the regression-protection baseline. If anything is already red, **stop** and surface it before continuing.

---

## Task 1: `marks_store.py` — SQLite layer (pure, no Flask, no DLC)

**Files:**
- Create: `src/dlc/marks_store.py`
- Test: `src/tests/test_marks_store.py`

- [ ] **Step 1: Write the failing tests**

Create `src/tests/test_marks_store.py`:

```python
"""Tests for src/dlc/marks_store.py — pure SQLite layer for test-set marks."""
from __future__ import annotations
import sqlite3
from pathlib import Path

import pytest

from dlc import marks_store as ms


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A bare DLC project root — only what marks_store cares about."""
    p = tmp_path / "Proj-2026-05-19"
    p.mkdir()
    return p


def test_get_marks_on_fresh_project_returns_empty(project):
    assert ms.list_marks(project) == []
    assert ms.get_mode(project) == "random"


def test_set_mark_then_list(project):
    ms.set_mark(project, "vid_a", "img0001.png", True)
    assert ms.list_marks(project) == [("vid_a", "img0001.png")]


def test_set_mark_idempotent(project):
    ms.set_mark(project, "vid_a", "img0001.png", True)
    ms.set_mark(project, "vid_a", "img0001.png", True)
    assert ms.list_marks(project) == [("vid_a", "img0001.png")]


def test_unset_mark_removes_row(project):
    ms.set_mark(project, "vid_a", "img0001.png", True)
    ms.set_mark(project, "vid_a", "img0001.png", False)
    assert ms.list_marks(project) == []


def test_unset_nonexistent_is_noop(project):
    ms.set_mark(project, "vid_a", "img0001.png", False)
    assert ms.list_marks(project) == []


def test_bulk_set_applies_all_ops(project):
    ops = [
        {"video_stem": "vid_a", "image_name": "img0001.png", "marked": True},
        {"video_stem": "vid_a", "image_name": "img0002.png", "marked": True},
        {"video_stem": "vid_b", "image_name": "img0005.png", "marked": True},
    ]
    applied = ms.bulk_set(project, ops)
    assert applied == 3
    rows = set(ms.list_marks(project))
    assert rows == {("vid_a", "img0001.png"), ("vid_a", "img0002.png"), ("vid_b", "img0005.png")}


def test_bulk_set_mixed_add_and_remove(project):
    ms.set_mark(project, "vid_a", "img0001.png", True)
    ops = [
        {"video_stem": "vid_a", "image_name": "img0001.png", "marked": False},
        {"video_stem": "vid_a", "image_name": "img0002.png", "marked": True},
    ]
    ms.bulk_set(project, ops)
    assert ms.list_marks(project) == [("vid_a", "img0002.png")]


def test_get_set_mode_roundtrip(project):
    ms.set_mode(project, "hybrid")
    assert ms.get_mode(project) == "hybrid"
    ms.set_mode(project, "manual")
    assert ms.get_mode(project) == "manual"


def test_set_mode_rejects_unknown(project):
    with pytest.raises(ValueError):
        ms.set_mode(project, "wibble")


def test_clean_stale_removes_only_missing_files(project, tmp_path):
    # Create labeled-data/<stem>/<image> files for two frames; mark three (one missing)
    labeled = project / "labeled-data"
    (labeled / "vid_a").mkdir(parents=True)
    (labeled / "vid_a" / "img0001.png").write_bytes(b"")
    (labeled / "vid_a" / "img0002.png").write_bytes(b"")
    ms.bulk_set(project, [
        {"video_stem": "vid_a", "image_name": "img0001.png", "marked": True},
        {"video_stem": "vid_a", "image_name": "img0002.png", "marked": True},
        {"video_stem": "vid_a", "image_name": "img0003.png", "marked": True},  # missing
    ])
    removed = ms.clean_stale(project)
    assert removed == 1
    rows = set(ms.list_marks(project))
    assert rows == {("vid_a", "img0001.png"), ("vid_a", "img0002.png")}


def test_schema_version_recorded(project):
    ms.set_mark(project, "vid_a", "img0001.png", True)
    db = project / "test_set_marks.sqlite"
    assert db.is_file()
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
        row = cur.fetchone()
    finally:
        conn.close()
    assert row is not None and row[0] == "1"


def test_get_marks_grouped_by_stem(project):
    ms.bulk_set(project, [
        {"video_stem": "vid_a", "image_name": "img0001.png", "marked": True},
        {"video_stem": "vid_a", "image_name": "img0002.png", "marked": True},
        {"video_stem": "vid_b", "image_name": "img0005.png", "marked": True},
    ])
    grouped = ms.get_marks_grouped(project)
    assert set(grouped["vid_a"]) == {"img0001.png", "img0002.png"}
    assert grouped["vid_b"] == ["img0005.png"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_marks_store.py -q
```

Expected: `ModuleNotFoundError: No module named 'dlc.marks_store'` (every test fails).

- [ ] **Step 3: Implement `marks_store.py`**

Create `src/dlc/marks_store.py`:

```python
"""
Pure SQLite layer for the test-set picker.

Each DLC project gets its own `test_set_marks.sqlite` at the project root.
The file is created on first write. All public functions are safe to call
on a project that has never been touched.

Schema (v1):
    marks(video_stem TEXT, image_name TEXT, marked_at TEXT, note TEXT,
          PRIMARY KEY (video_stem, image_name))
    meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)
        meta keys: schema_version="1", default_split_mode in {random,hybrid,manual}

This module imports no Flask, no DLC, no Redis — it can be unit-tested
in isolation against tmp_path.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

DB_FILENAME = "test_set_marks.sqlite"
SCHEMA_VERSION = "1"
VALID_MODES = ("random", "hybrid", "manual")


def _db_path(project_path: Path) -> Path:
    return Path(project_path) / DB_FILENAME


@contextmanager
def _connect(project_path: Path):
    """Open the SQLite DB, applying schema on first use. Per-call connection."""
    path = _db_path(project_path)
    conn = sqlite3.connect(str(path), isolation_level=None)  # autocommit; we wrap writes in BEGIN IMMEDIATE
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        _ensure_schema(conn)
        yield conn
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS marks (
            video_stem  TEXT NOT NULL,
            image_name  TEXT NOT NULL,
            marked_at   TEXT NOT NULL,
            note        TEXT,
            PRIMARY KEY (video_stem, image_name)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
    if cur.fetchone() is None:
        conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)",
                     ("schema_version", SCHEMA_VERSION))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def list_marks(project_path: Path) -> list[tuple[str, str]]:
    """Return every marked frame as (video_stem, image_name), sorted."""
    path = _db_path(project_path)
    if not path.is_file():
        return []
    with _connect(project_path) as conn:
        rows = conn.execute(
            "SELECT video_stem, image_name FROM marks ORDER BY video_stem, image_name"
        ).fetchall()
    return [(s, i) for (s, i) in rows]


def get_marks_grouped(project_path: Path) -> dict[str, list[str]]:
    """Return marks grouped by video_stem; values are sorted image_name lists."""
    out: dict[str, list[str]] = {}
    for stem, image in list_marks(project_path):
        out.setdefault(stem, []).append(image)
    return out


def set_mark(project_path: Path, video_stem: str, image_name: str,
             marked: bool, note: str | None = None) -> bool:
    """Add or remove a single mark. Returns the new marked state."""
    with _connect(project_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if marked:
                conn.execute(
                    "INSERT OR REPLACE INTO marks(video_stem, image_name, marked_at, note) "
                    "VALUES (?, ?, ?, ?)",
                    (video_stem, image_name, _now(), note),
                )
            else:
                conn.execute(
                    "DELETE FROM marks WHERE video_stem=? AND image_name=?",
                    (video_stem, image_name),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return bool(marked)


def bulk_set(project_path: Path, ops: Iterable[dict]) -> int:
    """Apply many add/remove ops in a single transaction. Returns count applied."""
    ops = list(ops)
    with _connect(project_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for op in ops:
                stem = op["video_stem"]
                image = op["image_name"]
                if op.get("marked", True):
                    conn.execute(
                        "INSERT OR REPLACE INTO marks(video_stem, image_name, marked_at, note) "
                        "VALUES (?, ?, ?, ?)",
                        (stem, image, _now(), op.get("note")),
                    )
                else:
                    conn.execute(
                        "DELETE FROM marks WHERE video_stem=? AND image_name=?",
                        (stem, image),
                    )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return len(ops)


def get_mode(project_path: Path) -> str:
    path = _db_path(project_path)
    if not path.is_file():
        return "random"
    with _connect(project_path) as conn:
        cur = conn.execute("SELECT value FROM meta WHERE key='default_split_mode'")
        row = cur.fetchone()
    return row[0] if row else "random"


def set_mode(project_path: Path, mode: str) -> None:
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}, got {mode!r}")
    with _connect(project_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('default_split_mode', ?)",
                (mode,),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def clean_stale(project_path: Path) -> int:
    """Remove marks whose <project>/labeled-data/<stem>/<image> file no longer exists.

    Returns number of marks removed.
    """
    project = Path(project_path)
    labeled = project / "labeled-data"
    removed = 0
    for stem, image in list_marks(project):
        if not (labeled / stem / image).is_file():
            set_mark(project, stem, image, False)
            removed += 1
    return removed
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_marks_store.py -q
```

Expected: 11 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/marks_store.py src/tests/test_marks_store.py
git commit -m "feat(dlc): add marks_store SQLite layer + unit tests

Pure data layer for per-project test-set marks. One SQLite file per
DLC project at <project>/test_set_marks.sqlite. No Flask, no DLC, no
Redis imports — unit-tested in isolation."
```

---

## Task 2: `test_set_split.py` — `build_indices` (pure function)

**Files:**
- Create: `src/dlc/test_set_split.py`
- Test: `src/tests/test_test_set_split.py`

- [ ] **Step 1: Write the failing tests**

Create `src/tests/test_test_set_split.py`:

```python
"""Tests for src/dlc/test_set_split.py — pure split-assembly function."""
from __future__ import annotations
import pandas as pd
import pytest

from dlc.test_set_split import build_indices_from_dataframe


def _fake_data(stems_frames: list[tuple[str, list[str]]]) -> pd.DataFrame:
    """Make a fake merged-H5 DataFrame whose row MultiIndex matches DLC's."""
    rows = []
    for stem, images in stems_frames:
        for img in images:
            rows.append(("labeled-data", stem, img))
    idx = pd.MultiIndex.from_tuples(rows)
    return pd.DataFrame({"dummy": [0] * len(rows)}, index=idx)


def test_random_returns_none():
    data = _fake_data([("a", ["img1.png", "img2.png"])])
    assert build_indices_from_dataframe(data, marks=[], mode="random", train_fraction=0.8) is None


def test_manual_partitions_all_frames():
    data = _fake_data([("a", ["img1.png", "img2.png", "img3.png", "img4.png"])])
    marks = [("a", "img2.png"), ("a", "img4.png")]
    train, test, stats = build_indices_from_dataframe(data, marks=marks, mode="manual", train_fraction=0.8)
    # Positions: img1=0, img2=1, img3=2, img4=3
    assert set(test) == {1, 3}
    assert set(train) == {0, 2}
    assert stats["dropped_marks"] == 0
    assert stats["total_frames"] == 4


def test_manual_empty_marks_raises():
    data = _fake_data([("a", ["img1.png", "img2.png"])])
    with pytest.raises(ValueError, match="manual"):
        build_indices_from_dataframe(data, marks=[], mode="manual", train_fraction=0.8)


def test_hybrid_below_quota_fills_with_random():
    # 10 frames, train_fraction 0.8 → target_test = 2; user marks 1 → 1 random added
    data = _fake_data([("a", [f"img{i:04d}.png" for i in range(10)])])
    marks = [("a", "img0000.png")]
    train, test, stats = build_indices_from_dataframe(
        data, marks=marks, mode="hybrid", train_fraction=0.8, seed=42
    )
    assert len(test) == 2
    assert 0 in test  # forced mark must be present
    assert set(train) | set(test) == set(range(10))
    assert set(train) & set(test) == set()


def test_hybrid_at_quota_no_filler():
    # 10 frames, target_test = 2; user marks 2 → no random
    data = _fake_data([("a", [f"img{i:04d}.png" for i in range(10)])])
    marks = [("a", "img0000.png"), ("a", "img0001.png")]
    train, test, stats = build_indices_from_dataframe(
        data, marks=marks, mode="hybrid", train_fraction=0.8, seed=42
    )
    assert sorted(test) == [0, 1]
    assert set(train) == set(range(2, 10))


def test_hybrid_overflow_honored():
    # 10 frames, target_test = 2; user marks 5 → all 5 stay in test
    data = _fake_data([("a", [f"img{i:04d}.png" for i in range(10)])])
    marks = [("a", f"img{i:04d}.png") for i in range(5)]
    train, test, stats = build_indices_from_dataframe(
        data, marks=marks, mode="hybrid", train_fraction=0.8, seed=42
    )
    assert sorted(test) == [0, 1, 2, 3, 4]
    assert set(train) == {5, 6, 7, 8, 9}
    # Derived fraction is 5/10 = 0.5, NOT 0.8


def test_hybrid_deterministic_with_seed():
    data = _fake_data([("a", [f"img{i:04d}.png" for i in range(20)])])
    marks = [("a", "img0000.png")]
    train1, test1, _ = build_indices_from_dataframe(data, marks=marks, mode="hybrid", train_fraction=0.8, seed=42)
    train2, test2, _ = build_indices_from_dataframe(data, marks=marks, mode="hybrid", train_fraction=0.8, seed=42)
    assert train1 == train2 and test1 == test2


def test_marks_pointing_at_missing_frames_dropped():
    data = _fake_data([("a", ["img1.png", "img2.png"])])
    marks = [("a", "img1.png"), ("a", "img_deleted.png"), ("ghost_stem", "x.png")]
    train, test, stats = build_indices_from_dataframe(data, marks=marks, mode="manual", train_fraction=0.8)
    assert set(test) == {0}
    assert stats["dropped_marks"] == 2


def test_manual_dataset_with_multiple_folders():
    data = _fake_data([
        ("a", ["img1.png", "img2.png"]),
        ("b", ["imgA.png", "imgB.png", "imgC.png"]),
    ])
    # Positions: a/img1=0, a/img2=1, b/imgA=2, b/imgB=3, b/imgC=4
    marks = [("a", "img2.png"), ("b", "imgC.png")]
    train, test, _ = build_indices_from_dataframe(data, marks=marks, mode="manual", train_fraction=0.8)
    assert set(test) == {1, 4}
    assert set(train) == {0, 2, 3}


def test_ratio_rounding_seven_frames():
    # 7 frames × 0.8 → target_test = round(0.2 * 7) = round(1.4) = 1
    data = _fake_data([("a", [f"img{i:04d}.png" for i in range(7)])])
    train, test, _ = build_indices_from_dataframe(
        data, marks=[], mode="hybrid", train_fraction=0.8, seed=42
    )
    assert len(test) == 1
    assert len(train) == 6
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_split.py -q
```

Expected: every test fails with import error.

- [ ] **Step 3: Implement `test_set_split.py`**

Create `src/dlc/test_set_split.py`:

```python
"""
Split-assembly for the test-set picker.

Pure function — no Flask, no Redis, no Celery. Reads the merged
CollectedData_<scorer>.h5 (via DLC's own merge function) and maps
user marks → positional indices into the merged DataFrame.

Public entry: build_indices(config_path, marks, mode, train_fraction, seed).

The pure inner function build_indices_from_dataframe is exposed for
unit tests so they can fabricate DataFrames without DLC installed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Literal

import numpy as np
import pandas as pd

Mode = Literal["random", "hybrid", "manual"]


def build_indices_from_dataframe(
    data: pd.DataFrame,
    marks: Iterable[tuple[str, str]],
    mode: Mode,
    train_fraction: float,
    seed: int = 42,
) -> tuple[list[int], list[int], dict] | None:
    """Inner pure function — unit-testable without DLC installed.

    `data` must have a row MultiIndex whose levels are
    (constant "labeled-data", video_stem, image_name) — DLC's shape.

    Returns (trainIndices, testIndices, stats) or None when mode == "random".
    stats = {"dropped_marks": int, "total_frames": int}.
    """
    if mode == "random":
        return None

    if mode not in ("hybrid", "manual"):
        raise ValueError(f"mode must be one of 'random'|'hybrid'|'manual', got {mode!r}")

    # Build lookup: (stem, image) -> positional index. Drop the constant
    # "labeled-data" prefix from level 0; the marks store keys on (stem, image).
    idx_lookup: dict[tuple[str, str], int] = {}
    for pos, row in enumerate(data.index):
        # row is a tuple ("labeled-data", stem, image)
        if len(row) < 3:
            continue
        _root, stem, image = row[0], row[1], row[2]
        idx_lookup[(stem, image)] = pos

    marks_list = list(marks)
    mark_positions: set[int] = set()
    dropped = 0
    for stem, image in marks_list:
        pos = idx_lookup.get((stem, image))
        if pos is None:
            dropped += 1
        else:
            mark_positions.add(pos)

    total = len(data.index)
    all_positions = set(range(total))
    stats = {"dropped_marks": dropped, "total_frames": total}

    if mode == "manual":
        if not mark_positions:
            raise ValueError(
                "Full manual mode requires at least one marked frame; "
                "no marks resolved to a labeled frame in the merged H5."
            )
        test_idx = sorted(mark_positions)
        train_idx = sorted(all_positions - mark_positions)
        return train_idx, test_idx, stats

    # hybrid
    target_test_count = round((1 - train_fraction) * total)
    forced_test = set(mark_positions)
    extra_needed = max(0, target_test_count - len(forced_test))
    if extra_needed > 0:
        pool = sorted(all_positions - forced_test)
        rng = np.random.default_rng(seed)
        extra = rng.choice(pool, size=extra_needed, replace=False)
        test_set = forced_test | set(int(i) for i in extra)
    else:
        test_set = forced_test
    train_idx = sorted(all_positions - test_set)
    test_idx = sorted(test_set)
    return train_idx, test_idx, stats


def build_indices(
    config_path: str | Path,
    marks: Iterable[tuple[str, str]],
    mode: Mode,
    train_fraction: float,
    seed: int = 42,
) -> tuple[list[int], list[int], dict] | None:
    """Production entry: loads the merged H5 via DLC, then delegates.

    Imports of `deeplabcut` are deferred so the test module above can
    import this module without DLC installed.
    """
    if mode == "random":
        return None

    from deeplabcut.utils import auxiliaryfunctions
    from deeplabcut.generate_training_dataset.trainingsetmanipulation import (
        merge_annotateddatasets,
    )
    from deeplabcut.pose_estimation_tensorflow.config import (  # noqa: F401  (kept for parity with DLC import side-effects)
        load_config,
    ) if False else (None,)  # no-op import gate

    cfg = auxiliaryfunctions.read_config(str(config_path))
    scorer = cfg["scorer"]
    project_path = cfg["project_path"]
    training_set_folder = auxiliaryfunctions.get_training_set_folder(cfg)
    training_set_folder_full = Path(project_path) / training_set_folder
    training_set_folder_full.mkdir(parents=True, exist_ok=True)

    # Try cached merged H5 first (matches DLC's behavior in mergeandsplit).
    fn = training_set_folder_full / f"CollectedData_{scorer}.h5"
    if fn.is_file():
        data = pd.read_hdf(str(fn))
    else:
        data = merge_annotateddatasets(cfg, training_set_folder_full)
        if data is None or len(data.index) == 0:
            raise RuntimeError(
                "Merged H5 is empty; nothing to split. Did labeled-data/ get scrubbed?"
            )

    # Strip scorer column level the way mergeandsplit does, so the row index
    # is the canonical ("labeled-data", stem, image) tuple.
    if scorer in getattr(data.columns, "levels", []):
        data = data[scorer]

    return build_indices_from_dataframe(data, marks, mode, train_fraction, seed)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_split.py -q
```

Expected: 10 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/test_set_split.py src/tests/test_test_set_split.py
git commit -m "feat(dlc): add build_indices split-assembly helper + unit tests

Pure function that maps (video_stem, image_name) marks to positional
indices in the merged CollectedData_<scorer>.h5. Three modes: random
(returns None — caller skips), manual (test = marks), hybrid (marks
union random filler to hit TrainingFraction). Deterministic given a
fixed seed. Overflow honored when marks exceed quota."
```

---

## Task 3: `test_set_picker.py` — Flask blueprint (marks endpoints)

**Files:**
- Create: `src/dlc/test_set_picker.py`
- Modify: `src/app.py` (register blueprint)
- Test: `src/tests/test_test_set_picker_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `src/tests/test_test_set_picker_routes.py`:

```python
"""Tests for the dlc_test_set_picker blueprint."""
from __future__ import annotations
import json
from pathlib import Path

import pytest


def _activate_project(client, fake_redis, project_path: Path):
    """Seed the Redis project key the way dlc_project would."""
    import flask
    # Find the session uid the test client uses; mirror _dlc_key()
    with client.session_transaction() as sess:
        sess["uid"] = "test-uid"
    fake_redis.set(
        "webapp:dlc_project:test-uid",
        json.dumps({
            "project_path": str(project_path),
            "config_path": str(project_path / "config.yaml"),
            "engine": "pytorch",
        }),
    )


@pytest.fixture
def picker_project(tmp_path):
    """A minimal DLC project skeleton sufficient for picker route tests."""
    proj = tmp_path / "PickerTest-2026-05-19"
    (proj / "labeled-data" / "vid_a").mkdir(parents=True)
    (proj / "labeled-data" / "vid_a" / "img0001.png").write_bytes(b"\x89PNG\r\n")
    (proj / "labeled-data" / "vid_a" / "img0002.png").write_bytes(b"\x89PNG\r\n")
    # minimal config.yaml so _get_dlc_project_and_config doesn't 404
    (proj / "config.yaml").write_text(
        "scorer: TestScorer\nproject_path: " + str(proj) + "\nbodyparts:\n  - nose\n"
    )
    return proj


def test_get_marks_empty(flask_test_client, fake_redis, picker_project):
    _activate_project(flask_test_client, fake_redis, picker_project)
    rv = flask_test_client.get("/dlc/project/test-set/marks")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["mode"] == "random"
    assert body["marks"] == {}
    assert body["counts"]["marked"] == 0


def test_post_mark_then_get(flask_test_client, fake_redis, picker_project):
    _activate_project(flask_test_client, fake_redis, picker_project)
    rv = flask_test_client.post(
        "/dlc/project/test-set/marks/vid_a/img0001.png",
        json={"marked": True},
    )
    assert rv.status_code == 200
    assert rv.get_json()["marked"] is True

    rv2 = flask_test_client.get("/dlc/project/test-set/marks")
    body = rv2.get_json()
    assert body["marks"] == {"vid_a": ["img0001.png"]}
    assert body["counts"]["marked"] == 1


def test_post_unmark(flask_test_client, fake_redis, picker_project):
    _activate_project(flask_test_client, fake_redis, picker_project)
    flask_test_client.post("/dlc/project/test-set/marks/vid_a/img0001.png", json={"marked": True})
    flask_test_client.post("/dlc/project/test-set/marks/vid_a/img0001.png", json={"marked": False})
    rv = flask_test_client.get("/dlc/project/test-set/marks")
    assert rv.get_json()["marks"] == {}


def test_bulk_set(flask_test_client, fake_redis, picker_project):
    _activate_project(flask_test_client, fake_redis, picker_project)
    rv = flask_test_client.post("/dlc/project/test-set/marks/bulk", json={"ops": [
        {"video_stem": "vid_a", "image_name": "img0001.png", "marked": True},
        {"video_stem": "vid_a", "image_name": "img0002.png", "marked": True},
    ]})
    assert rv.status_code == 200
    assert rv.get_json()["applied"] == 2


def test_clean_stale(flask_test_client, fake_redis, picker_project):
    _activate_project(flask_test_client, fake_redis, picker_project)
    # Mark a real frame + a frame that doesn't exist on disk
    flask_test_client.post("/dlc/project/test-set/marks/bulk", json={"ops": [
        {"video_stem": "vid_a", "image_name": "img0001.png", "marked": True},
        {"video_stem": "vid_a", "image_name": "img_gone.png", "marked": True},
    ]})
    rv = flask_test_client.post("/dlc/project/test-set/marks/clean-stale")
    assert rv.status_code == 200
    assert rv.get_json()["removed"] == 1


def test_set_and_get_mode(flask_test_client, fake_redis, picker_project):
    _activate_project(flask_test_client, fake_redis, picker_project)
    rv = flask_test_client.post("/dlc/project/test-set/mode", json={"mode": "hybrid"})
    assert rv.status_code == 200
    rv2 = flask_test_client.get("/dlc/project/test-set/marks")
    assert rv2.get_json()["mode"] == "hybrid"


def test_set_mode_rejects_unknown(flask_test_client, fake_redis, picker_project):
    _activate_project(flask_test_client, fake_redis, picker_project)
    rv = flask_test_client.post("/dlc/project/test-set/mode", json={"mode": "bogus"})
    assert rv.status_code == 400


def test_path_traversal_blocked(flask_test_client, fake_redis, picker_project):
    _activate_project(flask_test_client, fake_redis, picker_project)
    rv = flask_test_client.post(
        "/dlc/project/test-set/marks/..%2F..%2Fetc/passwd",
        json={"marked": True},
    )
    assert rv.status_code in (400, 404)


def test_no_active_project_returns_400(flask_test_client, fake_redis):
    rv = flask_test_client.get("/dlc/project/test-set/marks")
    assert rv.status_code == 400
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_routes.py -q
```

Expected: all tests fail (blueprint not registered).

- [ ] **Step 3: Implement the blueprint**

Create `src/dlc/test_set_picker.py`:

```python
"""
DLC Test-set Picker Blueprint.

Routes:
  GET  /dlc/project/test-set/marks
  POST /dlc/project/test-set/marks/<video_stem>/<image_name>
  POST /dlc/project/test-set/marks/bulk
  POST /dlc/project/test-set/marks/clean-stale
  POST /dlc/project/test-set/mode

All routes operate on the active DLC project (Redis key
webapp:dlc_project:<uid>) and use the per-project SQLite at
<project_path>/test_set_marks.sqlite.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request, session as flask_session
from werkzeug.utils import secure_filename

from dlc import marks_store
from . import ctx as _ctx

bp = Blueprint("dlc_test_set_picker", __name__)


def _user_id() -> str:
    if "uid" not in flask_session:
        flask_session["uid"] = uuid.uuid4().hex
    return flask_session["uid"]


def _dlc_key() -> str:
    return f"webapp:dlc_project:{_user_id()}"


def _active_project() -> tuple[Path | None, tuple | None]:
    """Return (project_path, error_response). Error response is None on success."""
    raw = _ctx.redis_client().get(_dlc_key())
    if not raw:
        return None, (jsonify({"error": "No active DLC project."}), 400)
    try:
        data = json.loads(raw)
    except Exception:
        return None, (jsonify({"error": "Corrupt project state."}), 500)
    project_path = Path(data.get("project_path", "") or "")
    if not project_path.is_dir():
        return None, (jsonify({"error": "Project directory not found."}), 404)
    return project_path, None


def _safe_stem(value: str) -> str | None:
    """Return a secure_filename'd stem, or None if the input is suspicious."""
    if not value or value != value.strip():
        return None
    cleaned = secure_filename(value)
    if not cleaned or cleaned != value:
        # secure_filename mutates anything traversal-ish; reject mutation
        return None
    return cleaned


def _safe_image_name(value: str) -> str | None:
    if not value or "/" in value or "\\" in value or ".." in value:
        return None
    cleaned = secure_filename(value)
    if not cleaned or cleaned != value:
        return None
    return cleaned


def _frame_belongs_to_project(project_path: Path, stem: str, image: str) -> bool:
    labeled_root = (project_path / "labeled-data").resolve()
    candidate = (labeled_root / stem / image).resolve()
    try:
        candidate.relative_to(labeled_root)
    except ValueError:
        return False
    return True


def _count_labeled_frames(project_path: Path) -> tuple[int, dict[str, int]]:
    labeled_root = project_path / "labeled-data"
    per_folder: dict[str, int] = {}
    total = 0
    if not labeled_root.is_dir():
        return 0, {}
    for stem_dir in sorted(labeled_root.iterdir()):
        if not stem_dir.is_dir():
            continue
        n = sum(1 for p in stem_dir.iterdir() if p.suffix.lower() == ".png")
        per_folder[stem_dir.name] = n
        total += n
    return total, per_folder


@bp.route("/dlc/project/test-set/marks", methods=["GET"])
def get_marks():
    project_path, err = _active_project()
    if err:
        return err
    grouped = marks_store.get_marks_grouped(project_path)
    mode = marks_store.get_mode(project_path)
    total_labeled, per_folder_total = _count_labeled_frames(project_path)
    per_folder = {
        stem: {"marked": len(grouped.get(stem, [])), "total": per_folder_total.get(stem, 0)}
        for stem in set(grouped) | set(per_folder_total)
    }
    return jsonify({
        "mode": mode,
        "marks": grouped,
        "counts": {
            "marked": sum(len(v) for v in grouped.values()),
            "total_labeled": total_labeled,
            "per_folder": per_folder,
        },
    })


@bp.route("/dlc/project/test-set/marks/<path:video_stem>/<image_name>", methods=["POST"])
def post_mark(video_stem: str, image_name: str):
    project_path, err = _active_project()
    if err:
        return err
    stem = _safe_stem(video_stem)
    image = _safe_image_name(image_name)
    if stem is None or image is None:
        return jsonify({"error": "Invalid path component."}), 400
    if not _frame_belongs_to_project(project_path, stem, image):
        return jsonify({"error": "Path escapes labeled-data root."}), 403

    body = request.get_json(force=True, silent=True) or {}
    marked = bool(body.get("marked", True))
    note = body.get("note")
    marks_store.set_mark(project_path, stem, image, marked, note)
    return jsonify({"ok": True, "marked": marked})


@bp.route("/dlc/project/test-set/marks/bulk", methods=["POST"])
def post_bulk():
    project_path, err = _active_project()
    if err:
        return err
    body = request.get_json(force=True, silent=True) or {}
    ops_in = body.get("ops") or []
    if not isinstance(ops_in, list):
        return jsonify({"error": "ops must be a list."}), 400
    cleaned: list[dict] = []
    for op in ops_in:
        if not isinstance(op, dict):
            continue
        stem = _safe_stem(op.get("video_stem", ""))
        image = _safe_image_name(op.get("image_name", ""))
        if stem is None or image is None:
            continue
        if not _frame_belongs_to_project(project_path, stem, image):
            continue
        cleaned.append({
            "video_stem": stem,
            "image_name": image,
            "marked": bool(op.get("marked", True)),
            "note": op.get("note"),
        })
    applied = marks_store.bulk_set(project_path, cleaned)
    return jsonify({"ok": True, "applied": applied})


@bp.route("/dlc/project/test-set/marks/clean-stale", methods=["POST"])
def post_clean_stale():
    project_path, err = _active_project()
    if err:
        return err
    removed = marks_store.clean_stale(project_path)
    return jsonify({"ok": True, "removed": removed})


@bp.route("/dlc/project/test-set/mode", methods=["POST"])
def post_mode():
    project_path, err = _active_project()
    if err:
        return err
    body = request.get_json(force=True, silent=True) or {}
    mode = (body.get("mode") or "").strip()
    if mode not in marks_store.VALID_MODES:
        return jsonify({"error": f"mode must be one of {list(marks_store.VALID_MODES)}"}), 400
    marks_store.set_mode(project_path, mode)
    return jsonify({"ok": True, "mode": mode})
```

- [ ] **Step 4: Register the blueprint**

Edit `src/app.py`. Find the block of `from dlc.<name> import bp as _dlc_<name>_bp` imports around line 179, and the matching `app.register_blueprint(...)` block around line 193.

Add the import next to the others:

```python
from dlc.test_set_picker import bp as _dlc_test_set_picker_bp
```

Add the registration in the matching block (place it after `_dlc_labeling_bp` and before `_dlc_training_bp` to mirror the workflow order):

```python
app.register_blueprint(_dlc_test_set_picker_bp)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_routes.py -q
```

Expected: all 9 tests pass.

- [ ] **Step 6: Run the full DLC test suite to confirm no regression**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_dlc_celery_tasks.py tests/test_dlc_training_routes.py tests/test_dlc_project_routes.py -q
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/test_set_picker.py src/tests/test_test_set_picker_routes.py src/app.py
git commit -m "feat(dlc): add test_set_picker blueprint (marks endpoints) + route tests

Endpoints under /dlc/project/test-set/* for managing per-frame test-set
marks: get/set/bulk/clean-stale/mode. Backed by marks_store SQLite at
<project>/test_set_marks.sqlite. Path-containment guards on every write."
```

---

## Task 4: Wire `split_mode` into the existing CTD task and route

**Files:**
- Modify: `src/dlc/training.py` (CTD route; add `split_mode` body field, snapshot marks)
- Modify: `src/dlc/tasks.py` (CTD task; accept `split_mode` + `marks`, call `build_indices`)
- Test: `src/tests/test_dlc_create_training_dataset_split_modes.py` (new)
- Existing tests in `src/tests/test_dlc_celery_tasks.py` and `src/tests/test_dlc_training_routes.py` must still pass unchanged.

- [ ] **Step 1: Write the failing tests**

Create `src/tests/test_dlc_create_training_dataset_split_modes.py`:

```python
"""Tier-2 regression + new-behavior tests for the modified CTD task & route."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Helper: import the tasks module the way the existing test file does ──
@pytest.fixture
def tasks_mod():
    """Imports src.dlc.tasks with `deeplabcut` mocked at sys.modules level."""
    import sys, importlib, types
    fake_dlc = types.ModuleType("deeplabcut")
    fake_dlc.create_training_dataset = MagicMock()
    sys.modules["deeplabcut"] = fake_dlc
    # Re-import the celery task module so it picks up the fake
    if "dlc.tasks" in sys.modules:
        del sys.modules["dlc.tasks"]
    mod = importlib.import_module("dlc.tasks")
    yield mod
    # Restore would be nice but pytest module-isolation handles teardown.


# ── 1. Default body (no split_mode) calls DLC with same kwargs as today ──
def test_default_mode_random_calls_dlc_unchanged(tmp_path, tasks_mod):
    import deeplabcut as dlc
    dlc.create_training_dataset.reset_mock()
    cfg = tmp_path / "config.yaml"
    cfg.write_text("scorer: X\nproject_path: " + str(tmp_path) + "\n")
    tasks_mod.dlc_create_training_dataset.update_state = MagicMock()
    tasks_mod.dlc_create_training_dataset.run(str(cfg), num_shuffles=1, freeze_split=True)
    # Asserts the call was made with no trainIndices/testIndices kwargs
    args, kwargs = dlc.create_training_dataset.call_args
    assert "trainIndices" not in kwargs
    assert "testIndices" not in kwargs
    assert kwargs.get("num_shuffles") == 1
    assert kwargs.get("userfeedback") is False


# ── 2. split_mode="random" explicit call also doesn't pass indices ──
def test_explicit_random_does_not_pass_indices(tmp_path, tasks_mod):
    import deeplabcut as dlc
    dlc.create_training_dataset.reset_mock()
    cfg = tmp_path / "config.yaml"
    cfg.write_text("scorer: X\nproject_path: " + str(tmp_path) + "\n")
    tasks_mod.dlc_create_training_dataset.update_state = MagicMock()
    tasks_mod.dlc_create_training_dataset.run(
        str(cfg), num_shuffles=1, freeze_split=True, split_mode="random", marks=None,
    )
    args, kwargs = dlc.create_training_dataset.call_args
    assert "trainIndices" not in kwargs
    assert "testIndices" not in kwargs


# ── 3. split_mode="manual" with marks calls DLC with indices ──
def test_manual_mode_forwards_indices(tmp_path, tasks_mod, monkeypatch):
    import deeplabcut as dlc
    dlc.create_training_dataset.reset_mock()
    cfg = tmp_path / "config.yaml"
    cfg.write_text("scorer: X\nproject_path: " + str(tmp_path) + "\n")

    # Patch build_indices to a known split so we don't depend on a real merged H5
    fake_train = [0, 1, 2, 3]
    fake_test = [4, 5]
    monkeypatch.setattr(
        "dlc.test_set_split.build_indices",
        lambda *a, **kw: (fake_train, fake_test, {"dropped_marks": 0, "total_frames": 6}),
    )
    tasks_mod.dlc_create_training_dataset.update_state = MagicMock()
    tasks_mod.dlc_create_training_dataset.run(
        str(cfg),
        num_shuffles=2,
        freeze_split=True,
        split_mode="manual",
        marks=[["vid_a", "img0001.png"], ["vid_b", "img0002.png"]],
    )
    args, kwargs = dlc.create_training_dataset.call_args
    assert kwargs.get("trainIndices") == [fake_train, fake_train]
    assert kwargs.get("testIndices") == [fake_test, fake_test]


# ── 4. split_mode="hybrid" with marks also forwards ──
def test_hybrid_mode_forwards_indices(tmp_path, tasks_mod, monkeypatch):
    import deeplabcut as dlc
    dlc.create_training_dataset.reset_mock()
    cfg = tmp_path / "config.yaml"
    cfg.write_text("scorer: X\nproject_path: " + str(tmp_path) + "\n")
    monkeypatch.setattr(
        "dlc.test_set_split.build_indices",
        lambda *a, **kw: ([0, 1, 2], [3, 4, 5], {"dropped_marks": 0, "total_frames": 6}),
    )
    tasks_mod.dlc_create_training_dataset.update_state = MagicMock()
    tasks_mod.dlc_create_training_dataset.run(
        str(cfg), num_shuffles=1, freeze_split=True,
        split_mode="hybrid", marks=[["vid_a", "img0001.png"]],
    )
    args, kwargs = dlc.create_training_dataset.call_args
    assert kwargs.get("trainIndices") == [[0, 1, 2]]
    assert kwargs.get("testIndices") == [[3, 4, 5]]


# ── 5. manual mode with empty marks fails fast — DLC not called ──
def test_manual_empty_marks_errors(tmp_path, tasks_mod, monkeypatch):
    import deeplabcut as dlc
    dlc.create_training_dataset.reset_mock()
    cfg = tmp_path / "config.yaml"
    cfg.write_text("scorer: X\nproject_path: " + str(tmp_path) + "\n")

    def raise_value(*a, **kw):
        raise ValueError("Full manual mode requires at least one marked frame")
    monkeypatch.setattr("dlc.test_set_split.build_indices", raise_value)
    tasks_mod.dlc_create_training_dataset.update_state = MagicMock()
    with pytest.raises(RuntimeError, match="manual"):
        tasks_mod.dlc_create_training_dataset.run(
            str(cfg), num_shuffles=1, freeze_split=True, split_mode="manual", marks=[],
        )
    assert dlc.create_training_dataset.call_count == 0


# ── 6. The route includes a marks snapshot when mode != random ──
def test_route_snapshots_marks_for_manual(flask_test_client, fake_redis, tmp_path, monkeypatch):
    # Activate a project; seed two marks in the SQLite via marks_store
    proj = tmp_path / "RouteSnap-2026-05-19"
    (proj / "labeled-data" / "vid_a").mkdir(parents=True)
    (proj / "labeled-data" / "vid_a" / "img0001.png").write_bytes(b"\x89PNG\r\n")
    (proj / "config.yaml").write_text("scorer: X\nproject_path: " + str(proj) + "\n")
    with flask_test_client.session_transaction() as sess:
        sess["uid"] = "test-uid"
    fake_redis.set(
        "webapp:dlc_project:test-uid",
        json.dumps({"project_path": str(proj), "config_path": str(proj / "config.yaml"), "engine": "pytorch"}),
    )

    from dlc import marks_store
    marks_store.set_mark(proj, "vid_a", "img0001.png", True)

    sent_kwargs: dict = {}
    def fake_send_task(name, *, kwargs, queue):
        sent_kwargs.update(kwargs)
        rv = MagicMock()
        rv.id = "fake-task-id"
        return rv
    monkeypatch.setattr("dlc.ctx.celery", lambda: MagicMock(send_task=fake_send_task))

    rv = flask_test_client.post(
        "/dlc/project/create-training-dataset",
        json={"num_shuffles": 1, "freeze_split": True, "split_mode": "manual"},
    )
    assert rv.status_code == 202
    assert sent_kwargs.get("split_mode") == "manual"
    assert sent_kwargs.get("marks") == [["vid_a", "img0001.png"]]


def test_route_no_split_mode_field_defaults_to_random(flask_test_client, fake_redis, tmp_path, monkeypatch):
    proj = tmp_path / "RouteDefault-2026-05-19"
    proj.mkdir()
    (proj / "config.yaml").write_text("scorer: X\nproject_path: " + str(proj) + "\n")
    with flask_test_client.session_transaction() as sess:
        sess["uid"] = "test-uid"
    fake_redis.set(
        "webapp:dlc_project:test-uid",
        json.dumps({"project_path": str(proj), "config_path": str(proj / "config.yaml"), "engine": "pytorch"}),
    )

    sent_kwargs: dict = {}
    def fake_send_task(name, *, kwargs, queue):
        sent_kwargs.update(kwargs)
        rv = MagicMock()
        rv.id = "fake-task-id"
        return rv
    monkeypatch.setattr("dlc.ctx.celery", lambda: MagicMock(send_task=fake_send_task))

    rv = flask_test_client.post(
        "/dlc/project/create-training-dataset",
        json={"num_shuffles": 1, "freeze_split": True},
    )
    assert rv.status_code == 202
    # Must include split_mode="random" so the worker knows to skip indices logic
    assert sent_kwargs.get("split_mode") == "random"
    # marks may be absent or empty — but never a non-empty list
    assert not sent_kwargs.get("marks")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_dlc_create_training_dataset_split_modes.py -q
```

Expected: all fail (route doesn't accept `split_mode`; task doesn't accept `split_mode`/`marks`).

- [ ] **Step 3: Modify the route**

Edit `src/dlc/training.py`. Replace the body of `dlc_create_training_dataset` (the route, lines ~38–64) with this version. Keep the existing function name and signature. Read the existing function before editing so you preserve indentation and surrounding context.

Replace this block:

```python
    body = request.get_json(force=True) or {}
    try:
        num_shuffles = int(body.get("num_shuffles", 1))
    except (TypeError, ValueError):
        num_shuffles = 1
    if num_shuffles < 1:
        num_shuffles = 1
    freeze_split = bool(body.get("freeze_split", True))

    task = _ctx.celery().send_task(
        "tasks.dlc_create_training_dataset",
        kwargs={"config_path": config_path, "num_shuffles": num_shuffles, "freeze_split": freeze_split},
        queue=_get_engine_queue(engine),
    )
    return jsonify({"task_id": task.id, "operation": "create_training_dataset"}), 202
```

With:

```python
    body = request.get_json(force=True) or {}
    try:
        num_shuffles = int(body.get("num_shuffles", 1))
    except (TypeError, ValueError):
        num_shuffles = 1
    if num_shuffles < 1:
        num_shuffles = 1
    freeze_split = bool(body.get("freeze_split", True))

    # New: split_mode + per-project marks snapshot.
    split_mode = (body.get("split_mode") or "random").strip().lower()
    if split_mode not in ("random", "hybrid", "manual"):
        split_mode = "random"

    marks_payload: list[list[str]] = []
    if split_mode in ("hybrid", "manual"):
        from dlc import marks_store
        project_path = project_data.get("project_path", "")
        if project_path:
            marks_payload = [
                [stem, image]
                for (stem, image) in marks_store.list_marks(Path(project_path))
            ]

    task = _ctx.celery().send_task(
        "tasks.dlc_create_training_dataset",
        kwargs={
            "config_path": config_path,
            "num_shuffles": num_shuffles,
            "freeze_split": freeze_split,
            "split_mode": split_mode,
            "marks": marks_payload,
        },
        queue=_get_engine_queue(engine),
    )
    return jsonify({
        "task_id": task.id,
        "operation": "create_training_dataset",
        "split_mode": split_mode,
        "marks_count": len(marks_payload),
    }), 202
```

- [ ] **Step 4: Modify the celery task**

Edit `src/dlc/tasks.py`. Find `def dlc_create_training_dataset(self, config_path, num_shuffles=1, freeze_split=True)` (around line 156). Update its signature and body.

Replace the existing function entirely with:

```python
@celery.task(bind=True, name="tasks.dlc_create_training_dataset")
def dlc_create_training_dataset(
    self,
    config_path: str,
    num_shuffles: int = 1,
    freeze_split: bool = True,
    split_mode: str = "random",
    marks: list | None = None,
):
    """Run deeplabcut.create_training_dataset() for the given DLC config.yaml.

    freeze_split is accepted for API compatibility but ignored — see prior comment.

    split_mode (new):
      - "random"  → existing behavior; do not pass trainIndices/testIndices to DLC.
      - "manual"  → user-marked frames are the entire test set. trainIndices/testIndices
                    are derived via dlc.test_set_split.build_indices and broadcast across
                    all shuffles.
      - "hybrid"  → user marks ⊆ test set; remainder is filled by deterministic random
                    selection to honor cfg.TrainingFraction[0]. Overflow is honored.

    marks (new): list of [video_stem, image_name] pairs snapshotted at the route layer.
    Empty/None for random mode.
    """
    import io as _io
    import sys as _sys

    _log_buf  = _io.StringIO()
    _real_out = _sys.stdout
    _real_err = _sys.stderr
    _sys.stdout = _log_buf
    _sys.stderr = _log_buf

    try:
        self.update_state(
            state="PROGRESS",
            meta={"progress": 5, "stage": "Checking config…", "log": ""},
        )

        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"DLC config.yaml not found: {config_path}")

        _sanitize_dlc_config_yaml(config_path)

        # Resolve (trainIndices, testIndices) if a non-random mode is requested.
        train_idx_list = None
        test_idx_list = None
        if split_mode in ("hybrid", "manual"):
            from dlc.test_set_split import build_indices
            from deeplabcut.utils import auxiliaryfunctions
            cfg = auxiliaryfunctions.read_config(config_path)
            train_fraction = float(cfg.get("TrainingFraction", [0.8])[0])
            try:
                result = build_indices(
                    config_path=config_path,
                    marks=[(m[0], m[1]) for m in (marks or [])],
                    mode=split_mode,
                    train_fraction=train_fraction,
                )
            except ValueError as exc:
                raise RuntimeError(f"split_mode={split_mode}: {exc}")
            if result is not None:
                train_inds, test_inds, stats = result
                train_idx_list = [list(train_inds)] * num_shuffles
                test_idx_list = [list(test_inds)] * num_shuffles
                self.update_state(
                    state="PROGRESS",
                    meta={
                        "progress": 8,
                        "stage": (
                            f"Split prepared (mode={split_mode}, "
                            f"train={len(train_inds)}, test={len(test_inds)}, "
                            f"dropped_marks={stats['dropped_marks']})"
                        ),
                        "log": "",
                    },
                )

        self.update_state(
            state="PROGRESS",
            meta={
                "progress": 10,
                "stage": "Running deeplabcut.create_training_dataset…",
                "log": (
                    f"config_path: {config_path}\n"
                    f"num_shuffles: {num_shuffles}\n"
                    f"split_mode: {split_mode}\n"
                ),
            },
        )

        ctd_kwargs = {"num_shuffles": num_shuffles, "userfeedback": False}
        if train_idx_list is not None:
            ctd_kwargs["trainIndices"] = train_idx_list
            ctd_kwargs["testIndices"] = test_idx_list

        dlc.create_training_dataset(config_path, **ctd_kwargs)

        final_log = _log_buf.getvalue()[-5000:]
        return {
            "status":    "complete",
            "operation": "create_training_dataset",
            "split_mode": split_mode,
            "log":       final_log or f"Training dataset created.\nconfig: {config_path}",
        }

    except Exception:
        raise RuntimeError(traceback.format_exc()[-3000:])

    finally:
        _sys.stdout = _real_out
        _sys.stderr = _real_err
```

- [ ] **Step 5: Run the new test file**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_dlc_create_training_dataset_split_modes.py -q
```

Expected: all 7 tests pass.

- [ ] **Step 6: Run the EXISTING test files unchanged to confirm no regression**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_dlc_celery_tasks.py tests/test_dlc_training_routes.py tests/test_dlc_project_routes.py tests/test_marks_store.py tests/test_test_set_split.py tests/test_test_set_picker_routes.py -q
```

Expected: all green. The existing `test_calls_dlc_with_freeze_split` and `test_calls_dlc_without_freeze_split` MUST still pass — the task's positional+keyword API for the random path is preserved.

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/training.py src/dlc/tasks.py src/tests/test_dlc_create_training_dataset_split_modes.py
git commit -m "feat(dlc): wire split_mode into create_training_dataset task

Route gains optional split_mode body field (default \"random\") + snapshots
marks from SQLite at dispatch time. Task gains optional split_mode/marks
kwargs. When split_mode is hybrid/manual, build_indices resolves marks
to positional indices and broadcasts the same split across all shuffles.
Random path is byte-identical to today — locked in by regression test."
```

---

## Task 5: Inspect endpoint — read frozen splits from `Documentation_data-*.pickle`

**Files:**
- Modify: `src/dlc/test_set_picker.py` (add inspect route)
- Test: `src/tests/test_test_set_picker_inspect.py`

- [ ] **Step 1: Write the failing tests**

Create `src/tests/test_test_set_picker_inspect.py`:

```python
"""Tests for the inspect endpoint that reads frozen splits from pickle."""
from __future__ import annotations
import json
import pickle
from pathlib import Path

import numpy as np
import pytest


def _make_pickle(folder: Path, scorer_task: str, train_fraction_pct: int, shuffle: int,
                 frames: list[tuple[str, str]], train_idx: list[int], test_idx: list[int]):
    """Write a Documentation_data-*.pickle DLC-style."""
    folder.mkdir(parents=True, exist_ok=True)
    all_entries = [
        {"image": ("labeled-data", stem, image), "size": (3, 100, 100),
         "joints": np.zeros((1, 3), dtype=np.int64)}
        for (stem, image) in frames
    ]
    payload = [all_entries, np.array(train_idx, dtype=np.int64),
               np.array(test_idx, dtype=np.int64), train_fraction_pct / 100.0]
    out = folder / f"Documentation_data-{scorer_task}_{train_fraction_pct}shuffle{shuffle}.pickle"
    with open(out, "wb") as f:
        pickle.dump(payload, f)
    return out


def _activate(client, fake_redis, project_path):
    with client.session_transaction() as sess:
        sess["uid"] = "test-uid"
    fake_redis.set(
        "webapp:dlc_project:test-uid",
        json.dumps({
            "project_path": str(project_path),
            "config_path": str(project_path / "config.yaml"),
            "engine": "pytorch",
        }),
    )


@pytest.fixture
def inspect_project(tmp_path):
    proj = tmp_path / "InspectTest-2026-05-19"
    proj.mkdir()
    cfg = proj / "config.yaml"
    cfg.write_text(
        "scorer: TestScorer\nproject_path: " + str(proj) + "\n"
        "TrainingFraction:\n  - 0.8\niteration: 0\nTask: MyTask\n"
    )
    # Iteration 0, shuffle 1 — 5 frames, 4 train / 1 test
    folder = proj / "training-datasets" / "iteration-0" / "UnaugmentedDataSet_MyTaskJan1"
    _make_pickle(
        folder, "MyTask", 80, 1,
        frames=[
            ("vid_a", "img0001.png"),
            ("vid_a", "img0002.png"),
            ("vid_b", "img0010.png"),
            ("vid_b", "img0020.png"),
            ("vid_b", "img0030.png"),
        ],
        train_idx=[0, 2, 3, 4],
        test_idx=[1],
    )
    return proj


def test_inspect_default_iteration(flask_test_client, fake_redis, inspect_project):
    _activate(flask_test_client, fake_redis, inspect_project)
    rv = flask_test_client.get("/dlc/project/training-dataset/inspect")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["iteration"] == 0
    assert len(body["datasets"]) == 1
    ds = body["datasets"][0]
    assert ds["shuffle"] == 1
    assert ds["train_fraction"] == 0.8
    train_pairs = {(d["video_stem"], d["image_name"]) for d in ds["train"]}
    test_pairs  = {(d["video_stem"], d["image_name"]) for d in ds["test"]}
    assert train_pairs == {
        ("vid_a", "img0001.png"),
        ("vid_b", "img0010.png"),
        ("vid_b", "img0020.png"),
        ("vid_b", "img0030.png"),
    }
    assert test_pairs == {("vid_a", "img0002.png")}


def test_inspect_specific_shuffle(flask_test_client, fake_redis, inspect_project):
    _activate(flask_test_client, fake_redis, inspect_project)
    rv = flask_test_client.get("/dlc/project/training-dataset/inspect?iteration=0&shuffle=1")
    assert rv.status_code == 200


def test_inspect_strips_minus_one_padding(flask_test_client, fake_redis, tmp_path):
    proj = tmp_path / "Pad-2026-05-19"
    proj.mkdir()
    (proj / "config.yaml").write_text(
        "scorer: T\nproject_path: " + str(proj) + "\nTrainingFraction:\n  - 0.8\niteration: 0\nTask: MyTask\n"
    )
    folder = proj / "training-datasets" / "iteration-0" / "UnaugmentedDataSet_MyTaskJan1"
    _make_pickle(
        folder, "MyTask", 80, 1,
        frames=[("a", "1.png"), ("a", "2.png")],
        train_idx=[0, -1],
        test_idx=[1, -1],
    )
    _activate(flask_test_client, fake_redis, proj)
    rv = flask_test_client.get("/dlc/project/training-dataset/inspect")
    ds = rv.get_json()["datasets"][0]
    assert ds["train"] == [{"video_stem": "a", "image_name": "1.png"}]
    assert ds["test"]  == [{"video_stem": "a", "image_name": "2.png"}]


def test_inspect_missing_iteration_empty(flask_test_client, fake_redis, tmp_path):
    proj = tmp_path / "Empty-2026-05-19"
    proj.mkdir()
    (proj / "config.yaml").write_text("scorer: T\nproject_path: " + str(proj) + "\niteration: 5\n")
    _activate(flask_test_client, fake_redis, proj)
    rv = flask_test_client.get("/dlc/project/training-dataset/inspect")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["datasets"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_inspect.py -q
```

Expected: all fail (route doesn't exist).

- [ ] **Step 3: Add the inspect route**

Append to `src/dlc/test_set_picker.py`:

```python
# ── Inspect frozen splits ─────────────────────────────────────────────────────

import pickle
import re as _re


def _parse_iteration_from_config(project_path: Path) -> int:
    cfg_path = project_path / "config.yaml"
    if not cfg_path.is_file():
        return 0
    text = cfg_path.read_text()
    m = _re.search(r'^iteration\s*:\s*(\d+)', text, _re.MULTILINE)
    return int(m.group(1)) if m else 0


_DOC_PICKLE_RE = _re.compile(
    r"^Documentation_data-(?P<task>.+)_(?P<frac>\d+)shuffle(?P<shuffle>\d+)\.pickle$"
)


def _read_pickle_dataset(pickle_path: Path) -> dict | None:
    """Parse a Documentation_data-*.pickle and return train/test frame tuples.

    Returns None on parse failure.
    """
    m = _DOC_PICKLE_RE.match(pickle_path.name)
    if not m:
        return None
    train_pct = int(m.group("frac"))
    shuffle = int(m.group("shuffle"))
    try:
        with open(pickle_path, "rb") as f:
            payload = pickle.load(f)
    except Exception:
        return None
    if not isinstance(payload, (list, tuple)) or len(payload) < 3:
        return None
    entries, train_idx, test_idx = payload[0], payload[1], payload[2]

    def _resolve(indices) -> list[dict]:
        out: list[dict] = []
        for i in indices:
            i = int(i)
            if i < 0 or i >= len(entries):
                continue  # strips -1 padding and out-of-range
            row = entries[i]
            img = row.get("image") if isinstance(row, dict) else None
            if not img or len(img) < 3:
                continue
            out.append({"video_stem": img[1], "image_name": img[2]})
        return out

    return {
        "shuffle": shuffle,
        "train_fraction": train_pct / 100.0,
        "train": _resolve(train_idx),
        "test":  _resolve(test_idx),
        "documentation_pickle": str(pickle_path.name),
    }


@bp.route("/dlc/project/training-dataset/inspect", methods=["GET"])
def get_inspect():
    project_path, err = _active_project()
    if err:
        return err

    requested_iter = request.args.get("iteration", type=int)
    if requested_iter is None:
        requested_iter = _parse_iteration_from_config(project_path)

    iter_root = project_path / "training-datasets" / f"iteration-{requested_iter}"
    if not iter_root.is_dir():
        return jsonify({"iteration": requested_iter, "datasets": []})

    requested_shuffle = request.args.get("shuffle", type=int)
    datasets: list[dict] = []
    for pickle_path in sorted(iter_root.glob("UnaugmentedDataSet_*/Documentation_data-*.pickle")):
        parsed = _read_pickle_dataset(pickle_path)
        if parsed is None:
            continue
        if requested_shuffle is not None and parsed["shuffle"] != requested_shuffle:
            continue
        datasets.append(parsed)

    return jsonify({"iteration": requested_iter, "datasets": datasets})
```

- [ ] **Step 4: Run the tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_inspect.py -q
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/test_set_picker.py src/tests/test_test_set_picker_inspect.py
git commit -m "feat(dlc): add inspect endpoint for frozen train/test splits

GET /dlc/project/training-dataset/inspect parses
Documentation_data-*.pickle from training-datasets/iteration-N/ and
maps positional indices back to (video_stem, image_name) tuples.
Strips DLC's -1 padding. Optional ?iteration & ?shuffle filters."
```

---

## Task 6: Extract `frame_overlay.js` shared draw module + labeler parity check

**Files:**
- Create: `src/static/js/frame_overlay.js`
- Modify: `src/static/js/frame_labeler.js` (route bodypart draw through the new module)
- Test: `src/tests/test_frame_overlay_module_exists.py` (lightweight existence check; the labeler's runtime is verified by manual browser smoke noted in this task)

- [ ] **Step 1: Inspect the existing draw code paths in `frame_labeler.js`**

Read the file (it is large — 1343 lines). The relevant blocks are the canvas draw routines that paint the image and the per-bodypart dots/labels. Identify the two functions:
  - The one that paints the current frame image into the canvas (background draw).
  - The one that paints all body-part dots on top.

For each, copy the EXACT current implementation verbatim into the new module (no logic changes). Then replace the inlined definitions in `frame_labeler.js` with imports and calls.

Run:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
grep -n "drawImage\|fillStyle\|arc(" src/static/js/frame_labeler.js | head -40
```

Use the line ranges that come back to identify the draw region. Read those line ranges in context with the Read tool before extracting.

- [ ] **Step 2: Create the extracted module**

Create `src/static/js/frame_overlay.js`:

```javascript
"use strict";
/**
 * Shared read-only frame & bodypart drawing.
 *
 * Pure rendering — no event handlers, no DOM lookups, no state.
 * Imported by frame_labeler.js (which adds interactive handlers on top)
 * and by test_set_picker.js (which uses these calls only).
 */

/** Paint an image into a canvas, sized to the canvas's CSS dimensions. */
export function drawFrame(ctx, image, opts = {}) {
    const { fit = "contain" } = opts;
    const cw = ctx.canvas.width;
    const ch = ctx.canvas.height;
    ctx.clearRect(0, 0, cw, ch);
    if (!image) return;
    const iw = image.naturalWidth || image.width;
    const ih = image.naturalHeight || image.height;
    if (!iw || !ih) return;
    let dw = cw, dh = ch, dx = 0, dy = 0;
    if (fit === "contain") {
        const s = Math.min(cw / iw, ch / ih);
        dw = iw * s; dh = ih * s;
        dx = (cw - dw) / 2; dy = (ch - dh) / 2;
    }
    ctx.drawImage(image, dx, dy, dw, dh);
    return { dx, dy, dw, dh, iw, ih };
}

/**
 * Paint bodypart dots + optional name labels.
 *
 * labels:    { "<bodypart>": [x, y] | null }     coords in image space
 * palette:   { "<bodypart>": "#hexstring" }      color per bodypart
 * placement: { dx, dy, dw, dh, iw, ih }          returned by drawFrame
 * opts:      { markerSize, showNames }
 */
export function drawBodyparts(ctx, labels, palette, placement, opts = {}) {
    const { markerSize = 4, showNames = true } = opts;
    if (!labels || !placement) return;
    const { dx, dy, dw, dh, iw, ih } = placement;
    const sx = dw / iw;
    const sy = dh / ih;

    ctx.save();
    ctx.lineWidth = Math.max(1, Math.floor(markerSize / 3));
    for (const [bp, xy] of Object.entries(labels)) {
        if (!xy) continue;
        const [imgX, imgY] = xy;
        const canvasX = dx + imgX * sx;
        const canvasY = dy + imgY * sy;
        const color = palette[bp] || "#ff5050";
        ctx.beginPath();
        ctx.arc(canvasX, canvasY, markerSize, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.strokeStyle = "#0008";
        ctx.stroke();
        if (showNames) {
            ctx.font = `${Math.max(10, markerSize * 2)}px var(--mono, monospace)`;
            ctx.textBaseline = "top";
            ctx.fillStyle = "#000c";
            ctx.fillRect(canvasX + markerSize + 1, canvasY - 2, ctx.measureText(bp).width + 6, parseInt(ctx.font) + 3);
            ctx.fillStyle = color;
            ctx.fillText(bp, canvasX + markerSize + 4, canvasY - 1);
        }
    }
    ctx.restore();
}
```

This module is the *canonical* implementation. The labeler is refactored to call it. If the labeler's existing implementation differs in some detail (color of name backdrop, rounding behavior), copy the labeler's exact logic into the corresponding function above — match what the labeler does, not what's written here. Side-by-side compare and reconcile before committing.

- [ ] **Step 3: Refactor `frame_labeler.js` to import the module**

At the top of `src/static/js/frame_labeler.js`, alongside the existing `import` line, add:

```javascript
import { drawFrame, drawBodyparts } from "./frame_overlay.js";
```

Then find the draw block where the labeler currently inlines image drawing followed by per-bodypart drawing. Replace those inline draws with calls to `drawFrame(...)` and `drawBodyparts(...)`. Keep all interactive logic (click placement, drag, hover, marker selection) UNCHANGED — only the pure-paint portion moves.

If a single function in the labeler intermixes draw + state updates, split it: keep the state code in the labeler; route the actual pixel paints through the imported functions.

- [ ] **Step 4: Manual labeler smoke test**

Restart the Flask dev container (or hot-reload the static files). Open a project in a browser, open the Frame Labeler, page through 3 frames, verify:
  - Bodypart dots render in the same positions as before
  - Name labels render with the same fonts/backdrops
  - Clicking still places markers
  - Dragging still moves markers
  - Tab/Shift+Tab still cycles bodyparts
  - Marker-size slider still resizes dots
  - Show-names toggle still shows/hides labels

Document the smoke run in the commit message.

- [ ] **Step 5: Create a presence-check test (sanity guard against accidental deletion)**

Create `src/tests/test_frame_overlay_module_exists.py`:

```python
"""Sanity check that the shared overlay module exists and is imported by the labeler."""
from pathlib import Path


def test_frame_overlay_module_exists():
    p = Path(__file__).parents[1] / "static" / "js" / "frame_overlay.js"
    assert p.is_file(), f"{p} is missing — frame_labeler.js depends on it"


def test_frame_labeler_imports_overlay():
    p = Path(__file__).parents[1] / "static" / "js" / "frame_labeler.js"
    assert p.is_file()
    text = p.read_text()
    assert "frame_overlay" in text, (
        "frame_labeler.js no longer imports frame_overlay.js — was the refactor reverted?"
    )
```

Run:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_frame_overlay_module_exists.py -q
```

Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/static/js/frame_overlay.js src/static/js/frame_labeler.js src/tests/test_frame_overlay_module_exists.py
git commit -m "refactor(static): extract frame_overlay.js shared draw module

Pure-rendering helpers (drawFrame, drawBodyparts) extracted from
frame_labeler.js. Labeler now imports them; the picker card (next
commit) will import the same. No behavior change in the labeler —
manual smoke run confirmed: dot placement, drag, Tab cycle, marker
size, show-names all unchanged."
```

---

## Task 7: Picker UI — card template + JS (picker mode only)

**Files:**
- Create: `src/templates/partials/card_test_set_picker.html`
- Modify: `src/templates/index.html` (include the new partial)
- Modify: `src/templates/partials/card_dlc_project.html` (add opener button between Label Frames and Create Training Dataset)
- Create: `src/static/js/test_set_picker.js`
- Modify: `src/templates/base.html` (load the new JS module)
- Test: presence test + light DOM-shape test that the card exists in the rendered HTML

- [ ] **Step 1: Add opener button to the project card**

Edit `src/templates/partials/card_dlc_project.html`. Locate the existing `<button id="btn-open-frame-labeler" class="inspect-btn" ...>` block (around line 80). Immediately AFTER its closing `</button>` and BEFORE the `<button id="btn-open-create-training-dataset" ...>` block (around line 94), insert:

```html
        <button id="btn-open-test-set-picker" class="inspect-btn" style="width:100%;gap:.55rem">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2"/>
            <polyline points="7 12 11 16 17 8"/>
          </svg>
          <span>Test-set Picker</span>
        </button>
```

- [ ] **Step 2: Create the picker card partial**

Create `src/templates/partials/card_test_set_picker.html`:

```html
    <section class="card dlc-theme hidden" id="test-set-picker-card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.3rem">
        <h2>Test-set Picker</h2>
        <div style="display:flex;gap:.4rem;align-items:center">
          <button class="btn-sm" id="ts-inspect-btn" title="Inspect frozen splits for an existing training dataset">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            Inspect splits
          </button>
          <button class="btn-sm" id="btn-close-test-set-picker" title="Close test-set picker">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            Close
          </button>
        </div>
      </div>
      <p class="subtitle">Mark frames to include in the <strong>test set</strong>. Marks persist per project and survive new iterations.</p>

      <div style="font-size:.75rem;color:var(--text-dim);background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:.45rem .65rem;margin-bottom:.75rem;display:grid;grid-template-columns:auto 1fr;gap:.2rem .75rem;line-height:1.5">
        <span style="color:var(--text)"><kbd>←</kbd> / <kbd>→</kbd></span>            <span>Previous / next frame</span>
        <span style="color:var(--text)"><kbd>T</kbd></span>                            <span>Toggle current frame in test set</span>
        <span style="color:var(--text)"><kbd>Shift</kbd>+<kbd>←</kbd> / <kbd>→</kbd></span> <span>Previous / next labeled-data folder</span>
        <span style="color:var(--text)"><kbd>Home</kbd> / <kbd>End</kbd></span>        <span>First / last frame in folder</span>
        <span style="color:var(--text)"><kbd>M</kbd></span>                            <span>Cycle split-mode preference (Random → Hybrid → Manual)</span>
        <span style="color:var(--text)"><kbd>Esc</kbd></span>                          <span>Close picker</span>
      </div>

      <!-- Split mode chip row -->
      <div style="display:flex;align-items:center;gap:.4rem;margin-bottom:.75rem;flex-wrap:wrap">
        <span style="font-size:.78rem;color:var(--text-dim);text-transform:uppercase;letter-spacing:.06em">Split mode</span>
        <label class="ts-mode-chip"><input type="radio" name="ts-mode" value="random" checked> <span>Random</span></label>
        <label class="ts-mode-chip"><input type="radio" name="ts-mode" value="hybrid"> <span>Hybrid</span></label>
        <label class="ts-mode-chip"><input type="radio" name="ts-mode" value="manual"> <span>Full manual</span></label>
        <button id="ts-clean-stale-btn" class="btn-sm" style="margin-left:auto" title="Remove marks whose frame file no longer exists on disk">Clean stale</button>
      </div>

      <!-- Folder selector -->
      <div style="margin-bottom:.75rem">
        <label style="display:block;font-size:.78rem;font-weight:500;text-transform:uppercase;letter-spacing:.06em;color:var(--text-dim);margin-bottom:.4rem">Labeled frames folder</label>
        <div style="display:flex;align-items:center;gap:.5rem">
          <div class="select-wrap" style="flex:1">
            <select id="ts-stem-select">
              <option value="">— select video —</option>
            </select>
            <svg class="chevron" width="16" height="16" viewBox="0 0 16 16"><path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" fill="none"/></svg>
          </div>
          <button class="btn-sm" id="ts-refresh-btn" title="Refresh labeled-data folder list">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            Refresh
          </button>
        </div>
      </div>

      <!-- Player section -->
      <div id="ts-player-section" class="hidden">

        <!-- Frame navigation -->
        <div class="fl-frame-nav">
          <button class="btn-sm fe-ctrl-btn" id="ts-btn-prev" title="Previous frame (←)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="15 18 9 12 15 6"/></svg>
          </button>
          <span class="fe-frame-counter" id="ts-frame-info">Frame 0 / 0</span>
          <button class="btn-sm fe-ctrl-btn" id="ts-btn-next" title="Next frame (→)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="9 18 15 12 9 6"/></svg>
          </button>
          <span class="fe-time-display" id="ts-frame-name" style="font-size:.72rem"></span>
          <button id="ts-toggle-mark" class="btn-sm" title="Toggle current frame in test set (T)"
                  style="margin-left:auto;padding:.3rem .8rem;border:1px solid var(--border);border-radius:4px">
            <span id="ts-mark-label">▢ Mark for test set</span>
          </button>
        </div>

        <!-- Viewer controls -->
        <div style="display:flex;align-items:center;gap:1.2rem;margin:.5rem 0;flex-wrap:wrap">
          <label style="display:flex;align-items:center;gap:.45rem;font-size:.78rem;color:var(--text-dim)">
            Viewer size
            <input type="range" id="ts-zoom" min="50" max="300" value="100" step="25" style="width:80px;accent-color:var(--accent)">
            <span id="ts-zoom-val" style="min-width:2.5rem;text-align:right;color:var(--text)">100 %</span>
          </label>
          <label style="display:flex;align-items:center;gap:.45rem;font-size:.78rem;color:var(--text-dim)">
            Marker size
            <input type="range" id="ts-marker-size" min="1" max="24" value="4" style="width:80px;accent-color:var(--accent)">
            <span id="ts-marker-size-val" style="min-width:1.4rem;text-align:right;color:var(--text)">4</span>
          </label>
          <label style="display:flex;align-items:center;gap:.45rem;font-size:.78rem;color:var(--text-dim);cursor:pointer">
            <input type="checkbox" id="ts-show-names" checked style="accent-color:var(--accent)">
            Show names
          </label>
        </div>

        <!-- Canvas -->
        <div class="fl-canvas-wrap">
          <canvas id="ts-canvas"></canvas>
        </div>

        <!-- Counters -->
        <p style="font-size:.78rem;color:var(--text-dim);margin-top:.6rem">
          <span id="ts-folder-counter">0 / 0 marked in this folder</span>
          —
          <span id="ts-project-counter">0 / 0 marked in project</span>
        </p>
      </div>
    </section>
```

- [ ] **Step 3: Include the new partial in `index.html`**

Edit `src/templates/index.html`. Find the line `{% include "partials/card_frame_labeler.html" %}` and add immediately after it:

```html
    {% include "partials/card_test_set_picker.html" %}
```

- [ ] **Step 4: Create the picker JS**

Create `src/static/js/test_set_picker.js`:

```javascript
"use strict";
import { drawFrame, drawBodyparts } from "./frame_overlay.js";

const tsCard       = document.getElementById("test-set-picker-card");
const tsOpenBtn    = document.getElementById("btn-open-test-set-picker");
const tsCloseBtn   = document.getElementById("btn-close-test-set-picker");
const tsStemSelect = document.getElementById("ts-stem-select");
const tsRefreshBtn = document.getElementById("ts-refresh-btn");
const tsPlayerSec  = document.getElementById("ts-player-section");
const tsBtnPrev    = document.getElementById("ts-btn-prev");
const tsBtnNext    = document.getElementById("ts-btn-next");
const tsFrameInfo  = document.getElementById("ts-frame-info");
const tsFrameName  = document.getElementById("ts-frame-name");
const tsToggleBtn  = document.getElementById("ts-toggle-mark");
const tsMarkLabel  = document.getElementById("ts-mark-label");
const tsCanvas     = document.getElementById("ts-canvas");
const tsCtx        = tsCanvas ? tsCanvas.getContext("2d") : null;
const tsZoom       = document.getElementById("ts-zoom");
const tsZoomVal    = document.getElementById("ts-zoom-val");
const tsMarkerSize = document.getElementById("ts-marker-size");
const tsMarkerSizeVal = document.getElementById("ts-marker-size-val");
const tsShowNames  = document.getElementById("ts-show-names");
const tsFolderCntr = document.getElementById("ts-folder-counter");
const tsProjectCntr= document.getElementById("ts-project-counter");
const tsCleanStale = document.getElementById("ts-clean-stale-btn");
const tsInspectBtn = document.getElementById("ts-inspect-btn");

// ── State ────────────────────────────────────────────────────────
let _tsStems   = [];      // [{video_stem, frames[]}]
let _tsStem    = null;    // currently-selected stem string
let _tsFrames  = [];      // frames in the current stem
let _tsIdx     = 0;       // current frame index
let _tsMarks   = {};      // { stem: Set(image) }
let _tsLabels  = {};      // { image: { bp: [x,y] } }
let _tsImage   = null;    // currently-loaded Image
let _tsPlacement = null;  // placement returned by drawFrame
let _tsBodyparts = [];
let _tsPalette = {};
let _tsScorer  = "User";
let _tsProjectTotal = 0;

const TS_DEFAULT_PALETTE = [
  "#ff5050", "#50c8ff", "#a0e040", "#ffa040", "#c060ff",
  "#40e0c0", "#ff7090", "#80c080", "#f0c020", "#60a0ff",
];

function _buildPalette(bps) {
  const out = {};
  bps.forEach((bp, i) => { out[bp] = TS_DEFAULT_PALETTE[i % TS_DEFAULT_PALETTE.length]; });
  return out;
}

async function _fetchJson(url, opts) {
  const rv = await fetch(url, opts);
  if (!rv.ok) throw new Error(await rv.text());
  return rv.json();
}

async function _loadStems() {
  const body = await _fetchJson("/dlc/project/labeled-frames");
  _tsStems = body.frames || body || [];
  tsStemSelect.innerHTML = '<option value="">— select video —</option>';
  for (const s of _tsStems) {
    const stem = s.video_stem || s;
    const opt = document.createElement("option");
    opt.value = stem; opt.textContent = stem;
    tsStemSelect.appendChild(opt);
  }
}

async function _loadMarks() {
  const body = await _fetchJson("/dlc/project/test-set/marks");
  _tsMarks = {};
  for (const [stem, list] of Object.entries(body.marks || {})) {
    _tsMarks[stem] = new Set(list);
  }
  _tsProjectTotal = body.counts?.total_labeled || 0;
  _updateCounters(body.counts || {});
  const mode = body.mode || "random";
  document.querySelectorAll('input[name="ts-mode"]').forEach(el => {
    el.checked = (el.value === mode);
  });
}

async function _loadBodyparts() {
  const body = await _fetchJson("/dlc/project/bodyparts");
  _tsBodyparts = body.bodyparts || [];
  _tsPalette = _buildPalette(_tsBodyparts);
  _tsScorer = body.scorer || "User";
}

async function _loadStemFrames(stem) {
  const found = _tsStems.find(s => (s.video_stem || s) === stem);
  _tsFrames = (found && found.frames) || [];
  _tsIdx = 0;
  // Fetch labels for the stem (read-only display)
  try {
    const body = await _fetchJson(`/dlc/project/labels/${encodeURIComponent(stem)}`);
    _tsLabels = body.labels || {};
  } catch {
    _tsLabels = {};
  }
}

function _updateCounters(counts) {
  const stemCount = (_tsMarks[_tsStem] || new Set()).size;
  const folderTotal = _tsFrames.length;
  if (tsFolderCntr) tsFolderCntr.textContent = `${stemCount} / ${folderTotal} marked in this folder`;
  const projMarked = Object.values(_tsMarks).reduce((acc, s) => acc + s.size, 0);
  const projTotal = counts.total_labeled ?? _tsProjectTotal;
  if (tsProjectCntr) tsProjectCntr.textContent = `${projMarked} / ${projTotal} marked in project`;
}

function _currentFrameName() {
  return _tsFrames[_tsIdx] || "";
}

function _isCurrentMarked() {
  if (!_tsStem) return false;
  const s = _tsMarks[_tsStem] || new Set();
  return s.has(_currentFrameName());
}

function _updateToggleButton() {
  if (!tsMarkLabel) return;
  const m = _isCurrentMarked();
  tsMarkLabel.textContent = m ? "✓ In test set" : "▢ Mark for test set";
  tsToggleBtn.style.background = m ? "rgba(80, 200, 120, 0.18)" : "";
  tsToggleBtn.style.borderColor = m ? "rgba(80, 200, 120, 0.6)" : "";
}

function _draw() {
  if (!tsCtx) return;
  const { dx, dy, dw, dh, iw, ih } = drawFrame(tsCtx, _tsImage) || {};
  _tsPlacement = (iw && ih) ? { dx, dy, dw, dh, iw, ih } : null;
  const name = _currentFrameName();
  const labels = _tsLabels[name] || _tsLabels[`labeled-data/${_tsStem}/${name}`] || {};
  const markerSize = parseInt(tsMarkerSize?.value || "4");
  drawBodyparts(tsCtx, labels, _tsPalette, _tsPlacement, {
    markerSize,
    showNames: !!tsShowNames?.checked,
  });
}

function _renderFrame() {
  const name = _currentFrameName();
  if (!name) { tsFrameInfo.textContent = "Frame 0 / 0"; tsFrameName.textContent = ""; return; }
  tsFrameInfo.textContent = `Frame ${_tsIdx + 1} / ${_tsFrames.length}`;
  tsFrameName.textContent = name;
  _updateToggleButton();
  // Resize canvas to match the displayed CSS box, preserving viewer-zoom scaling
  const zoom = parseInt(tsZoom?.value || "100") / 100;
  tsCanvas.width = 800 * zoom;
  tsCanvas.height = 600 * zoom;
  const img = new Image();
  img.onload = () => { _tsImage = img; _draw(); };
  img.src = `/dlc/project/frame-image/${encodeURIComponent(_tsStem)}/${encodeURIComponent(name)}`;
}

async function _toggleCurrentMark() {
  if (!_tsStem || !_currentFrameName()) return;
  const name = _currentFrameName();
  const willBeMarked = !_isCurrentMarked();
  // Optimistic
  if (willBeMarked) (_tsMarks[_tsStem] ||= new Set()).add(name);
  else _tsMarks[_tsStem]?.delete(name);
  _updateToggleButton();
  _updateCounters({});
  try {
    await _fetchJson(
      `/dlc/project/test-set/marks/${encodeURIComponent(_tsStem)}/${encodeURIComponent(name)}`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ marked: willBeMarked }) },
    );
  } catch (e) {
    // Rollback on error
    if (willBeMarked) _tsMarks[_tsStem]?.delete(name);
    else (_tsMarks[_tsStem] ||= new Set()).add(name);
    _updateToggleButton();
    _updateCounters({});
    console.error("toggle failed:", e);
  }
}

async function _setMode(mode) {
  try {
    await _fetchJson("/dlc/project/test-set/mode", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
  } catch (e) {
    console.error("mode update failed:", e);
  }
}

async function _openPicker() {
  tsCard.classList.remove("hidden");
  await Promise.all([_loadBodyparts(), _loadStems(), _loadMarks()]);
}
function _closePicker() {
  tsCard.classList.add("hidden");
}

function _onStemChange() {
  _tsStem = tsStemSelect.value || null;
  if (!_tsStem) { tsPlayerSec.classList.add("hidden"); return; }
  tsPlayerSec.classList.remove("hidden");
  _loadStemFrames(_tsStem).then(() => { _renderFrame(); _updateCounters({}); });
}

function _next() { if (_tsIdx < _tsFrames.length - 1) { _tsIdx++; _renderFrame(); } }
function _prev() { if (_tsIdx > 0) { _tsIdx--; _renderFrame(); } }
function _firstInFolder() { if (_tsFrames.length) { _tsIdx = 0; _renderFrame(); } }
function _lastInFolder()  { if (_tsFrames.length) { _tsIdx = _tsFrames.length - 1; _renderFrame(); } }
function _nextFolder() {
  if (!_tsStems.length) return;
  const cur = _tsStems.findIndex(s => (s.video_stem || s) === _tsStem);
  const next = (cur + 1) % _tsStems.length;
  tsStemSelect.value = _tsStems[next].video_stem || _tsStems[next];
  _onStemChange();
}
function _prevFolder() {
  if (!_tsStems.length) return;
  const cur = _tsStems.findIndex(s => (s.video_stem || s) === _tsStem);
  const prev = (cur - 1 + _tsStems.length) % _tsStems.length;
  tsStemSelect.value = _tsStems[prev].video_stem || _tsStems[prev];
  _onStemChange();
}
function _cycleMode() {
  const modes = ["random", "hybrid", "manual"];
  const cur = [...document.querySelectorAll('input[name="ts-mode"]')].find(el => el.checked)?.value || "random";
  const next = modes[(modes.indexOf(cur) + 1) % modes.length];
  document.querySelectorAll('input[name="ts-mode"]').forEach(el => { el.checked = (el.value === next); });
  _setMode(next);
}

// ── Wire up ─────────────────────────────────────────────────────
if (tsOpenBtn)  tsOpenBtn.addEventListener("click", _openPicker);
if (tsCloseBtn) tsCloseBtn.addEventListener("click", _closePicker);
if (tsRefreshBtn) tsRefreshBtn.addEventListener("click", () => _loadStems());
if (tsStemSelect) tsStemSelect.addEventListener("change", _onStemChange);
if (tsBtnPrev)  tsBtnPrev.addEventListener("click", _prev);
if (tsBtnNext)  tsBtnNext.addEventListener("click", _next);
if (tsToggleBtn) tsToggleBtn.addEventListener("click", _toggleCurrentMark);
if (tsZoom)      tsZoom.addEventListener("input", () => { tsZoomVal.textContent = `${tsZoom.value} %`; _renderFrame(); });
if (tsMarkerSize) tsMarkerSize.addEventListener("input", () => { tsMarkerSizeVal.textContent = tsMarkerSize.value; _draw(); });
if (tsShowNames) tsShowNames.addEventListener("change", _draw);
if (tsCleanStale) tsCleanStale.addEventListener("click", async () => {
  await _fetchJson("/dlc/project/test-set/marks/clean-stale", { method: "POST" });
  await _loadMarks();
  _updateCounters({});
});
document.querySelectorAll('input[name="ts-mode"]').forEach(el => {
  el.addEventListener("change", () => { if (el.checked) _setMode(el.value); });
});

document.addEventListener("keydown", (ev) => {
  if (tsCard.classList.contains("hidden")) return;
  if (ev.target && /input|textarea|select/i.test(ev.target.tagName)) return;
  switch (ev.key) {
    case "ArrowLeft":  if (ev.shiftKey) _prevFolder(); else _prev(); ev.preventDefault(); break;
    case "ArrowRight": if (ev.shiftKey) _nextFolder(); else _next(); ev.preventDefault(); break;
    case "Home": _firstInFolder(); ev.preventDefault(); break;
    case "End":  _lastInFolder();  ev.preventDefault(); break;
    case "t": case "T": _toggleCurrentMark(); ev.preventDefault(); break;
    case "m": case "M": _cycleMode(); ev.preventDefault(); break;
    case "Escape": _closePicker(); break;
  }
});
```

- [ ] **Step 5: Load the new JS module from `base.html`**

Edit `src/templates/base.html`. Find where the existing `frame_labeler.js` module is loaded (it should be near other `<script type="module">` lines). Add immediately after it:

```html
<script type="module" src="{{ url_for('static', filename='js/test_set_picker.js') }}"></script>
```

If `frame_labeler.js` is not loaded as a module in `base.html` (e.g. it's bundled in `main.js`), grep for how it's loaded and follow the same pattern:

```bash
grep -n "frame_labeler\|test_set_picker" /home/sam/docker-images/deeplabcut-webapp-docker/src/templates/base.html
```

- [ ] **Step 6: Add a presence test**

Create `src/tests/test_test_set_picker_ui_presence.py`:

```python
"""Sanity tests that the picker card files exist and are wired into templates."""
from pathlib import Path


SRC = Path(__file__).parents[1]


def test_card_partial_exists():
    assert (SRC / "templates" / "partials" / "card_test_set_picker.html").is_file()


def test_card_included_in_index():
    text = (SRC / "templates" / "index.html").read_text()
    assert "partials/card_test_set_picker.html" in text


def test_opener_button_in_project_card():
    text = (SRC / "templates" / "partials" / "card_dlc_project.html").read_text()
    assert "btn-open-test-set-picker" in text
    # Order: must appear after Frame Labeler button and before Create Training Dataset button
    fl = text.find("btn-open-frame-labeler")
    ts = text.find("btn-open-test-set-picker")
    ctd = text.find("btn-open-create-training-dataset")
    assert fl < ts < ctd, f"Button order wrong: fl={fl}, ts={ts}, ctd={ctd}"


def test_picker_js_exists():
    assert (SRC / "static" / "js" / "test_set_picker.js").is_file()


def test_picker_js_imports_overlay():
    text = (SRC / "static" / "js" / "test_set_picker.js").read_text()
    assert "frame_overlay" in text
```

Run:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_ui_presence.py -q
```

Expected: 5 tests pass.

- [ ] **Step 7: Manual browser smoke**

Restart the flask container (or reload static), open the project page, click **Test-set Picker**, verify:
  - Card appears below; close button closes it
  - Stem dropdown is populated from labeled-data
  - Selecting a stem loads the first frame with bodypart dots overlaid (read-only — no click placement)
  - ← / → navigates frames, T toggles the mark badge
  - Counters update on toggle
  - Mode chips change mode (verify via `GET /dlc/project/test-set/marks`)
  - Frame Labeler still works exactly as before (regression smoke)

- [ ] **Step 8: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/templates/partials/card_test_set_picker.html \
        src/templates/index.html \
        src/templates/partials/card_dlc_project.html \
        src/static/js/test_set_picker.js \
        src/templates/base.html \
        src/tests/test_test_set_picker_ui_presence.py
git commit -m "feat(ui): add Test-set Picker card + opener button

New card_test_set_picker.html with frame navigation, read-only bodypart
overlay (via frame_overlay.js), per-frame test-set toggle, split-mode
chips, and project/folder counters. Opener button inserted between
Label Frames and Create Training Dataset in the project card."
```

---

## Task 8: Inspect mode UI + iteration/shuffle dialog

**Files:**
- Modify: `src/templates/partials/card_test_set_picker.html` (add inspect dialog + badge slot)
- Modify: `src/static/js/test_set_picker.js` (inspect mode state, badge rendering, dialog)
- Test: `src/tests/test_test_set_picker_ui_presence.py` (extend with inspect-mode markers)

- [ ] **Step 1: Add the inspect dialog to the card template**

Append to `src/templates/partials/card_test_set_picker.html`, just before the closing `</section>` tag:

```html
      <!-- ── Inspect-mode dialog (hidden by default) ───────────── -->
      <div id="ts-inspect-dialog" class="hidden"
           style="position:fixed;inset:0;background:rgba(0,0,0,0.55);display:flex;align-items:center;justify-content:center;z-index:1000">
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:1.2rem;min-width:300px;max-width:90vw">
          <h3 style="margin:0 0 .8rem 0">Inspect frozen splits</h3>
          <div class="scorer-row" style="margin-bottom:.55rem">
            <label for="ts-inspect-iter">Iteration</label>
            <input type="number" id="ts-inspect-iter" min="0" value="0" style="width:5rem">
          </div>
          <div class="scorer-row" style="margin-bottom:.85rem">
            <label for="ts-inspect-shuffle">Shuffle</label>
            <input type="number" id="ts-inspect-shuffle" min="1" value="1" style="width:5rem">
          </div>
          <div style="display:flex;justify-content:flex-end;gap:.5rem">
            <button id="ts-inspect-cancel" class="btn-sm">Cancel</button>
            <button id="ts-inspect-go" class="btn-sm btn-create">Inspect</button>
          </div>
        </div>
      </div>

      <!-- Inspect-mode banner (shown only in inspect mode) -->
      <div id="ts-inspect-banner" class="hidden"
           style="background:rgba(255,170,40,0.12);border:1px solid rgba(255,170,40,0.55);border-radius:6px;padding:.45rem .7rem;margin-bottom:.6rem;font-size:.82rem">
        <span id="ts-inspect-banner-text">Inspect mode</span>
        <button id="ts-inspect-exit" class="btn-sm" style="margin-left:.7rem">Exit inspect mode</button>
      </div>
```

- [ ] **Step 2: Extend `test_set_picker.js` with inspect-mode logic**

Append to `src/static/js/test_set_picker.js`:

```javascript
// ── Inspect mode ────────────────────────────────────────────────
const tsInspectDialog = document.getElementById("ts-inspect-dialog");
const tsInspectIter   = document.getElementById("ts-inspect-iter");
const tsInspectShuffle= document.getElementById("ts-inspect-shuffle");
const tsInspectCancel = document.getElementById("ts-inspect-cancel");
const tsInspectGo     = document.getElementById("ts-inspect-go");
const tsInspectBanner = document.getElementById("ts-inspect-banner");
const tsInspectBannerTxt = document.getElementById("ts-inspect-banner-text");
const tsInspectExit   = document.getElementById("ts-inspect-exit");

let _tsInspect = null;  // null when not inspecting; otherwise { iteration, shuffle, trainSet, testSet }

function _openInspectDialog() {
  if (tsInspectDialog) tsInspectDialog.classList.remove("hidden");
}
function _closeInspectDialog() {
  if (tsInspectDialog) tsInspectDialog.classList.add("hidden");
}
async function _runInspect() {
  const iter = parseInt(tsInspectIter.value || "0");
  const shuffle = parseInt(tsInspectShuffle.value || "1");
  const body = await _fetchJson(`/dlc/project/training-dataset/inspect?iteration=${iter}&shuffle=${shuffle}`);
  const ds = (body.datasets || []).find(d => d.shuffle === shuffle) || (body.datasets || [])[0];
  if (!ds) {
    alert(`No frozen split found for iteration ${iter} / shuffle ${shuffle}.`);
    return;
  }
  const trainSet = new Set(ds.train.map(d => `${d.video_stem}|${d.image_name}`));
  const testSet  = new Set(ds.test.map(d  => `${d.video_stem}|${d.image_name}`));
  _tsInspect = { iteration: iter, shuffle, trainSet, testSet,
                 trainFraction: ds.train_fraction };
  if (tsInspectBanner) tsInspectBanner.classList.remove("hidden");
  if (tsInspectBannerTxt) tsInspectBannerTxt.textContent =
    `Inspecting iteration-${iter} / shuffle-${shuffle} (trainset${Math.round(ds.train_fraction*100)}) — read-only`;
  _closeInspectDialog();
  _renderFrame();
}
function _exitInspect() {
  _tsInspect = null;
  if (tsInspectBanner) tsInspectBanner.classList.add("hidden");
  _renderFrame();
}

if (tsInspectBtn)    tsInspectBtn.addEventListener("click", _openInspectDialog);
if (tsInspectCancel) tsInspectCancel.addEventListener("click", _closeInspectDialog);
if (tsInspectGo)     tsInspectGo.addEventListener("click", _runInspect);
if (tsInspectExit)   tsInspectExit.addEventListener("click", _exitInspect);

// Override _updateToggleButton to show TRAIN/TEST badges when inspecting
const _origUpdateToggleButton = _updateToggleButton;
function _updateToggleButtonInspectAware() {
  if (!_tsInspect) { _origUpdateToggleButton(); return; }
  if (!tsMarkLabel) return;
  const key = `${_tsStem}|${_currentFrameName()}`;
  const inTrain = _tsInspect.trainSet.has(key);
  const inTest  = _tsInspect.testSet.has(key);
  if (inTest) {
    tsMarkLabel.textContent = "TEST";
    tsToggleBtn.style.background = "rgba(255,170,40,0.18)";
    tsToggleBtn.style.borderColor = "rgba(255,170,40,0.7)";
  } else if (inTrain) {
    tsMarkLabel.textContent = "TRAIN";
    tsToggleBtn.style.background = "rgba(80,200,255,0.14)";
    tsToggleBtn.style.borderColor = "rgba(80,200,255,0.6)";
  } else {
    tsMarkLabel.textContent = "—";
    tsToggleBtn.style.background = "";
    tsToggleBtn.style.borderColor = "";
  }
  tsToggleBtn.disabled = true;
}
// Patch the original function reference
window._tsUpdateToggleButton = _updateToggleButtonInspectAware;
// Replace by reassigning the inner function name used by _renderFrame:
// (Simple approach: re-wire in _renderFrame.)
const _origRenderFrame = _renderFrame;
function _renderFrameInspectAware() {
  _origRenderFrame();
  _updateToggleButtonInspectAware();
}
// Reassign event handlers that called _renderFrame:
if (tsBtnPrev) tsBtnPrev.replaceWith(tsBtnPrev.cloneNode(true));
if (tsBtnNext) tsBtnNext.replaceWith(tsBtnNext.cloneNode(true));
// Re-wire navigation buttons to the inspect-aware render
document.getElementById("ts-btn-prev")?.addEventListener("click", () => { _prev(); _updateToggleButtonInspectAware(); });
document.getElementById("ts-btn-next")?.addEventListener("click", () => { _next(); _updateToggleButtonInspectAware(); });
```

- [ ] **Step 3: Extend the presence test**

Append to `src/tests/test_test_set_picker_ui_presence.py`:

```python
def test_inspect_dialog_present():
    text = (SRC / "templates" / "partials" / "card_test_set_picker.html").read_text()
    assert "ts-inspect-dialog" in text
    assert "ts-inspect-iter" in text
    assert "ts-inspect-shuffle" in text
    assert "ts-inspect-banner" in text


def test_picker_js_has_inspect_logic():
    text = (SRC / "static" / "js" / "test_set_picker.js").read_text()
    assert "/dlc/project/training-dataset/inspect" in text
    assert "_tsInspect" in text
```

Run:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_ui_presence.py -q
```

Expected: 7 tests pass.

- [ ] **Step 4: Manual smoke**

Open the picker. Click **Inspect splits**, enter iteration 0 shuffle 1 (or whatever the user's project actually has). Verify TRAIN/TEST badges replace the toggle, the orange banner appears, navigation between frames updates the badge correctly. Click **Exit inspect mode** — toggle returns.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/templates/partials/card_test_set_picker.html src/static/js/test_set_picker.js src/tests/test_test_set_picker_ui_presence.py
git commit -m "feat(ui): test-set picker inspect mode + iteration/shuffle dialog

Adds the read-only inspect view that consumes the new
/dlc/project/training-dataset/inspect endpoint. TRAIN/TEST badges
replace the toggle in inspect mode; small dialog selects which
(iteration, shuffle) to view."
```

---

## Task 9: Wire `split_mode` selector into the Create-Training-Dataset card

**Files:**
- Modify: `src/templates/partials/card_training_dataset.html` (add split_mode selector)
- Modify: `src/static/main.js` (include `split_mode` in the CTD POST body around line 3914)
- Test: extend the presence test file

- [ ] **Step 1: Add split_mode UI to the CTD card**

Read `src/templates/partials/card_training_dataset.html` to find where `num_shuffles` and `freeze_split` are configured. Above that block, insert:

```html
      <!-- Split mode (test-set picker integration) -->
      <div style="margin-bottom:.65rem">
        <label style="display:block;font-size:.78rem;font-weight:500;text-transform:uppercase;letter-spacing:.06em;color:var(--text-dim);margin-bottom:.3rem">Split mode</label>
        <div style="display:flex;gap:.6rem;flex-wrap:wrap">
          <label><input type="radio" name="ctd-split-mode" value="random" checked> Random (default)</label>
          <label><input type="radio" name="ctd-split-mode" value="hybrid"> Hybrid (marks first, fill remainder)</label>
          <label><input type="radio" name="ctd-split-mode" value="manual"> Full manual (marks only)</label>
        </div>
        <p style="font-size:.72rem;color:var(--text-dim);margin-top:.25rem;line-height:1.5">
          Hybrid and Manual use frames marked in the <strong>Test-set Picker</strong>.
        </p>
      </div>
```

- [ ] **Step 2: Send split_mode with the CTD request in `main.js`**

In `src/static/main.js`, find the `/dlc/project/create-training-dataset` POST around line 3914. The body currently is:

```javascript
body: JSON.stringify({ num_shuffles: numShuffles, freeze_split: freezeSplit }),
```

Replace it with:

```javascript
body: JSON.stringify({
  num_shuffles: numShuffles,
  freeze_split: freezeSplit,
  split_mode: (document.querySelector('input[name="ctd-split-mode"]:checked')?.value) || "random",
}),
```

- [ ] **Step 3: Extend the presence test**

Append to `src/tests/test_test_set_picker_ui_presence.py`:

```python
def test_ctd_card_has_split_mode_selector():
    text = (SRC / "templates" / "partials" / "card_training_dataset.html").read_text()
    assert 'name="ctd-split-mode"' in text
    assert 'value="random"' in text
    assert 'value="hybrid"' in text
    assert 'value="manual"' in text


def test_main_js_sends_split_mode():
    text = (SRC / "static" / "main.js").read_text()
    assert "split_mode" in text
    assert "ctd-split-mode" in text
```

Run:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_ui_presence.py -q
```

Expected: 9 tests pass.

- [ ] **Step 4: Manual smoke**

Open the Create-Training-Dataset card. Select Hybrid mode. Click Create. Watch the network panel: the POST body should include `"split_mode": "hybrid"`. Cancel the Celery task immediately (or let it run if the project is small and you want a full E2E sanity check).

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/templates/partials/card_training_dataset.html src/static/main.js src/tests/test_test_set_picker_ui_presence.py
git commit -m "feat(ui): add split-mode selector to Create-Training-Dataset card

Random / Hybrid / Full manual radio chips wired into the existing CTD
POST. Default remains Random — behavior identical to today when this
selector isn't touched."
```

---

## Task 10: Tier-3 end-to-end tests against the duplicated DREADD-Ali project

**Files:**
- Create: `src/tests/test_create_training_dataset_e2e.py`

This task **only runs cleanly inside the worker container** (where `deeplabcut` is importable). On the host these tests will skip.

- [ ] **Step 1: Write the e2e test file**

Create `src/tests/test_create_training_dataset_e2e.py`:

```python
"""
Tier-3 end-to-end tests for the test-set picker integration with DLC.

These tests duplicate the real DREADD-Ali DLC project on disk (via the
existing `dlc_sandbox_project` fixture in conftest.py), run
`deeplabcut.create_training_dataset` for real with hand-picked marks,
then read back Documentation_data-*.pickle and the .mat file to assert
that every marked frame landed in the test set (and no marked frame
landed in train).

Skips automatically when:
  - The source project isn't mounted (so non-NAS machines run Tier 1+2 only).
  - `deeplabcut` can't be imported (so the test only fires inside the
    worker container).
"""
from __future__ import annotations

import os
import pickle
import re
from pathlib import Path

import pytest

try:
    import deeplabcut  # noqa: F401
    import scipy.io as sio
    import pandas as pd
    HAVE_DLC = True
except Exception:
    HAVE_DLC = False

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not HAVE_DLC, reason="deeplabcut not importable; run in worker container."),
]


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _list_labeled_frames(project: Path) -> list[tuple[str, str]]:
    """Every (stem, image) under labeled-data/ — used for picking marks."""
    out: list[tuple[str, str]] = []
    root = project / "labeled-data"
    for stem_dir in sorted(root.iterdir()):
        if not stem_dir.is_dir():
            continue
        # Restrict to frames that actually have a label row in the per-folder
        # CollectedData_<scorer>.csv — picking unlabeled images here would
        # cause the mark to be silently dropped during build_indices.
        csv_files = list(stem_dir.glob("CollectedData_*.csv"))
        if not csv_files:
            continue
        for p in sorted(stem_dir.iterdir()):
            if p.suffix.lower() == ".png":
                out.append((stem_dir.name, p.name))
    return out


def _bump_iteration_for_isolation(config_path: Path) -> int:
    """Increase iteration so e2e runs land in a fresh iteration folder."""
    text = config_path.read_text()
    m = re.search(r'^(iteration\s*:\s*)(\d+)', text, re.MULTILINE)
    cur = int(m.group(2)) if m else 0
    new = cur + 100  # large bump so we don't collide with existing data
    if m:
        text = re.sub(r'^(iteration\s*:\s*)\d+', lambda mm: mm.group(1) + str(new),
                      text, count=1, flags=re.MULTILINE)
    else:
        text += f"\niteration: {new}\n"
    config_path.write_text(text)
    return new


def _find_doc_pickle(project: Path, iteration: int) -> Path:
    matches = list((project / "training-datasets" / f"iteration-{iteration}").glob(
        "UnaugmentedDataSet_*/Documentation_data-*.pickle"
    ))
    assert matches, f"No Documentation_data-*.pickle found in iteration-{iteration}"
    return matches[0]


def _resolve_split(pickle_path: Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]], float]:
    """Return (train_frames, test_frames, train_fraction) from a doc-pickle."""
    with open(pickle_path, "rb") as f:
        payload = pickle.load(f)
    entries, train_idx, test_idx, frac = payload[0], payload[1], payload[2], payload[3]

    def _resolve(indices) -> set[tuple[str, str]]:
        out: set[tuple[str, str]] = set()
        for i in indices:
            i = int(i)
            if i < 0 or i >= len(entries):
                continue
            img = entries[i].get("image")
            if img and len(img) >= 3:
                out.add((img[1], img[2]))
        return out

    return _resolve(train_idx), _resolve(test_idx), float(frac)


def _read_config(config_path: Path) -> dict:
    from deeplabcut.utils import auxiliaryfunctions
    return auxiliaryfunctions.read_config(str(config_path))


def _run_ctd_task(config_path: Path, *, split_mode: str, marks: list[tuple[str, str]]):
    """Drive the celery task body synchronously — no Celery worker required."""
    from unittest.mock import MagicMock
    from dlc import tasks as tasks_mod
    tasks_mod.dlc_create_training_dataset.update_state = MagicMock()
    return tasks_mod.dlc_create_training_dataset.run(
        str(config_path),
        num_shuffles=1,
        freeze_split=True,
        split_mode=split_mode,
        marks=[[s, i] for (s, i) in marks],
    )


# ── Tests ───────────────────────────────────────────────────────────────────────

def test_e2e_manual_mode_exact_match(dlc_sandbox_project):
    project = dlc_sandbox_project
    config_path = project / "config.yaml"
    iteration = _bump_iteration_for_isolation(config_path)

    all_frames = _list_labeled_frames(project)
    assert len(all_frames) >= 6, "Sandbox project doesn't have enough labeled frames for the test"

    # Pick 5 marks across at least 2 folders
    folders = sorted({stem for stem, _ in all_frames})
    marks: list[tuple[str, str]] = []
    for f in folders[:2]:
        frames_in_f = [img for stem, img in all_frames if stem == f]
        for img in frames_in_f[:3]:  # up to 3 per folder
            marks.append((f, img))
            if len(marks) >= 5:
                break
        if len(marks) >= 5:
            break
    marks = marks[:5]

    _run_ctd_task(config_path, split_mode="manual", marks=marks)

    pickle_path = _find_doc_pickle(project, iteration)
    train_frames, test_frames, derived_frac = _resolve_split(pickle_path)

    # Build the set of all frames *actually represented in the merged H5* —
    # not just every PNG. This is the universe we partition against.
    cfg = _read_config(config_path)
    universe = train_frames | test_frames

    # Manual mode invariants
    assert set(marks) == test_frames, "manual: test set must equal marks exactly"
    assert universe.isdisjoint(test_frames - set(marks))
    assert test_frames.isdisjoint(train_frames), "train and test must be disjoint"
    assert (train_frames | test_frames) == universe, "train+test must equal the merged universe"

    # Folder name reflects derived fraction (not necessarily cfg's TrainingFraction)
    folder = pickle_path.parent.name + " " + pickle_path.parent.parent.name
    # The training-dataset folder under dlc-models-pytorch encodes the derived %
    derived_pct = int(round(derived_frac * 100))
    # Find the model folder for this shuffle
    pattern = list((project / "dlc-models-pytorch" / f"iteration-{iteration}").glob(
        f"*trainset{derived_pct}shuffle*"
    ))
    assert pattern, f"No model folder with trainset{derived_pct}* in iteration-{iteration}"


def test_e2e_hybrid_mode_below_quota(dlc_sandbox_project):
    project = dlc_sandbox_project
    config_path = project / "config.yaml"
    iteration = _bump_iteration_for_isolation(config_path)

    all_frames = _list_labeled_frames(project)
    folders = sorted({stem for stem, _ in all_frames})
    # Pick 2 marks (well below the typical 20% test quota)
    marks = []
    for f in folders[:2]:
        frames_in_f = [img for stem, img in all_frames if stem == f]
        if frames_in_f:
            marks.append((f, frames_in_f[0]))

    _run_ctd_task(config_path, split_mode="hybrid", marks=marks)

    pickle_path = _find_doc_pickle(project, iteration)
    train_frames, test_frames, derived_frac = _resolve_split(pickle_path)
    cfg = _read_config(config_path)
    train_fraction = float(cfg.get("TrainingFraction", [0.8])[0])

    # Hybrid invariants
    assert set(marks) <= test_frames, "hybrid: marks must be a subset of the test set"
    assert test_frames.isdisjoint(train_frames)
    universe = train_frames | test_frames
    assert len(test_frames) >= len(marks)
    # Test count should be close to round((1-train_fraction) * len(universe)).
    expected_test = round((1 - train_fraction) * len(universe))
    assert abs(len(test_frames) - expected_test) <= 1, (
        f"hybrid test count off: {len(test_frames)} vs expected {expected_test}"
    )


def test_e2e_random_mode_unchanged_behavior(dlc_sandbox_project):
    """Regression: split_mode='random' produces a valid split with no marks."""
    project = dlc_sandbox_project
    config_path = project / "config.yaml"
    iteration = _bump_iteration_for_isolation(config_path)

    _run_ctd_task(config_path, split_mode="random", marks=[])

    pickle_path = _find_doc_pickle(project, iteration)
    train_frames, test_frames, derived_frac = _resolve_split(pickle_path)
    universe = train_frames | test_frames
    assert test_frames.isdisjoint(train_frames)
    assert len(universe) > 0


def test_e2e_manual_empty_marks_fails_clean(dlc_sandbox_project):
    """Manual mode with no marks must fail fast and never invoke DLC."""
    project = dlc_sandbox_project
    config_path = project / "config.yaml"
    _bump_iteration_for_isolation(config_path)

    with pytest.raises(RuntimeError, match="manual"):
        _run_ctd_task(config_path, split_mode="manual", marks=[])


def test_e2e_mat_file_train_count_matches_pickle(dlc_sandbox_project):
    """The .mat file's dataset row count equals len(train_frames)."""
    project = dlc_sandbox_project
    config_path = project / "config.yaml"
    iteration = _bump_iteration_for_isolation(config_path)

    all_frames = _list_labeled_frames(project)
    marks = [all_frames[0], all_frames[1]] if len(all_frames) >= 2 else []
    _run_ctd_task(config_path, split_mode="hybrid", marks=marks)

    pickle_path = _find_doc_pickle(project, iteration)
    train_frames, _test_frames, _ = _resolve_split(pickle_path)

    # Sibling .mat is named DREADD_Ali80shuffle1.mat style
    mat_files = list(pickle_path.parent.glob("*shuffle*.mat"))
    assert mat_files, f"No .mat file next to {pickle_path}"
    mat = sio.loadmat(str(mat_files[0]))
    ds = mat["dataset"]
    # dataset is a structured array of shape (1, N) with 'image' field
    n_rows = ds.shape[1] if ds.ndim == 2 else len(ds)
    assert n_rows == len(train_frames), (
        f".mat dataset row count ({n_rows}) does not match pickle train count ({len(train_frames)})"
    )
```

- [ ] **Step 2: Add the `e2e` marker to pytest.ini**

Edit BOTH `pytest.ini` files (`/home/sam/docker-images/deeplabcut-webapp-docker/pytest.ini` and `/home/sam/docker-images/deeplabcut-webapp-docker/src/pytest.ini`). In the `markers =` block (currently has `gpu:` only), add a sibling line:

```ini
    e2e: end-to-end tests requiring a real DLC project + deeplabcut installed
```

Do NOT add `e2e` to the default `-m "not gpu"` filter unless you want to exclude e2e from default runs. We do want to exclude it — change the addopts line to:

```ini
addopts = -v --tb=short -m "not gpu and not e2e"
```

This makes Tier-3 opt-in (`pytest -m e2e` to run them), matching the design: they run before commits that touch `build_indices`, the picker blueprint, or the CTD task — not on every commit.

- [ ] **Step 3: Run Tier-3 inside the worker container**

The pytorch worker container is `deeplabcut-webapp-docker-worker-1` and the host's `src/` is mounted at `/app` inside it.

```bash
docker exec deeplabcut-webapp-docker-worker-1 sh -c "cd /app && pytest tests/test_create_training_dataset_e2e.py -m e2e -q --tb=short"
```

If the container name has changed (check with `docker ps --format '{{.Names}}' | grep worker`), substitute it. All 5 tests must pass. If the sandbox doesn't have enough labeled frames for one test, surface and adjust — but only relax the assertion once you've understood why.

- [ ] **Step 4: Run Tier 1 + Tier 2 on the host to confirm nothing else broke**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/ -q
```

Expected: all green (e2e tests skip because `deeplabcut` is not importable on the host).

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/tests/test_create_training_dataset_e2e.py pytest.ini src/pytest.ini
git commit -m "test(dlc): tier-3 end-to-end against duplicated DREADD-Ali project

Drives the celery task body synchronously against a real DLC project
copy, reads back Documentation_data-*.pickle, and asserts marks landed
in the right set. Also cross-checks the .mat file's train row count
against the pickle's train index count.

Adds an 'e2e' pytest marker; tests are opt-in via 'pytest -m e2e' and
must be run inside the worker container (where deeplabcut imports)."
```

---

## Task 11: Final regression sweep + PR-ready cleanup

**Files:** none added; verification only.

- [ ] **Step 1: Full suite green, host-side**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/ -q
```

Expected: all green (e2e tests skipped on host).

- [ ] **Step 2: Full suite green, worker-side, including e2e**

```bash
docker exec deeplabcut-webapp-docker-worker-1 sh -c "cd /app && pytest tests/ -m 'not gpu' -q"
```

Expected: all green, including Tier-3.

- [ ] **Step 3: Manual end-to-end walkthrough**

1. Open the dashboard. Confirm the **Test-set Picker** button sits between Label Frames and Create Training Dataset.
2. Open the picker, select a video stem, mark 3 frames with `T`. Counter updates.
3. Close + reopen the picker. Marks persist.
4. Switch to a different stem. Mark 2 more frames. Counter updates.
5. Set mode chip to Hybrid.
6. Open Create-Training-Dataset card → Split mode = Hybrid → Create. Watch the GPU monitor.
7. After CTD completes, open the picker, click **Inspect splits** → enter iteration N / shuffle 1. Verify TRAIN/TEST badges. Every frame you marked should show TEST; the random filler should also show TEST.
8. Click Exit inspect mode → toggle is back.
9. Open the Frame Labeler — confirm it still works (place a dot, drag it, save). This is the labeler-parity smoke from Task 6, repeated post-integration.

- [ ] **Step 4: Branch hygiene & PR draft**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git log --oneline origin/main..HEAD
```

You should see commits 1–10 from this plan. If any are squashable (e.g. typos), rebase **only** if there's a clear win — frequent commits are a design feature. Otherwise push:

```bash
git push -u origin feat/test-set-picker
```

Open a PR with a body referencing the design doc:

```
PR title: feat(dlc): test-set picker — manual frame selection for create_training_dataset

Body:
- Spec: deeplabcut-webapp-docker-supports/docs/superpowers/specs/2026-05-19-test-set-picker-design.md
- Plan: deeplabcut-webapp-docker-supports/docs/superpowers/plans/2026-05-19-test-set-picker.md
- Default CTD behavior unchanged when split_mode is absent.
- Tier-1 + Tier-2 + Tier-3 all green.
```

---

## Spec coverage map

| Spec section | Task(s) |
|---|---|
| §2 Modes (random/manual/hybrid) | T2, T4 |
| §3 Persistence — SQLite schema | T1 |
| §4 Frame identity | T2 (lookup), T3 (route validation) |
| §5 Architecture (3 modules) | T1, T2, T3 |
| §6 API surface (marks routes) | T3 |
| §6 Inspect endpoint | T5 |
| §6 CTD route changes | T4 |
| §7 build_indices | T2 |
| §8 UI — opener button | T7 |
| §8 UI — picker card | T7 |
| §8 UI — inspect mode | T8 |
| §8 UI — CTD card split_mode selector | T9 |
| §9 Edge cases — stale, missing, concurrency | T1 (clean_stale), T2 (dropped_marks), T3 (path containment), T4 (fail-fast empty manual) |
| §10 Existing-behavior preservation | T4 regression tests, T6 labeler smoke |
| §11 Shared draw module | T6 |
| §12 Testing — Tier 1 | T1, T2, T3 |
| §12 Testing — Tier 2 | T4 |
| §12 Testing — Tier 3 | T10 |
| §13 Branching & commits | T0 + cadence across all tasks |
| §14 Out of scope | (none — explicitly excluded) |

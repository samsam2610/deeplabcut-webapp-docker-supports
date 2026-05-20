# Test-set Picker — design

**Date:** 2026-05-19
**Status:** approved, ready for implementation plan
**Scope:** add a per-frame manual test-set selector to the DeepLabCut webapp, with read-only inspect of frozen splits

---

## 1. Goal

Give users a UI to manually choose which labeled frames go into the **test set** when DeepLabCut's `create_training_dataset` runs. Selections persist per DLC project and survive iteration changes, scorer changes, and dataset re-creation. The same UI can also be used to **inspect** the frozen split of any already-created training dataset.

A "validation set" is treated as identical to the test set, matching DLC's own 2-way split. There is no third held-out set.

## 2. Modes

Three modes for the train/test split, selectable per CTD run:

- **Random** — current behavior. DLC's internal uniform random split runs untouched. Manual marks are ignored. **This is the default for backward compatibility.**
- **Full manual** — only user-marked frames are in the test set. The rest are train. The actual train fraction may diverge from `cfg.TrainingFraction[0]`; the resulting training-dataset folder name reflects the derived fraction (e.g. `…trainset72shuffle1`).
- **Hybrid** — user-marked frames are forced into the test set; if their count is less than `(1 − train_fraction) × N`, the remainder is filled by deterministic random selection from the unmarked frames. If the marks already meet or exceed the quota, no random filler is added and the test-set count is honored as-is (overflow allowed).

For multi-shuffle runs, every shuffle receives the **same** trainIndices/testIndices derived from marks. Random filler in hybrid mode uses a fixed seed for reproducibility.

## 3. Persistence

Per-project SQLite file at `<project_path>/test_set_marks.sqlite`. One file per DLC project, travels with the project on backups / NAS moves / sharing.

### Schema

```sql
CREATE TABLE marks (
  video_stem  TEXT NOT NULL,
  image_name  TEXT NOT NULL,          -- e.g. "img0123.png" or "vlcsnap-00045.png"
  marked_at   TEXT NOT NULL,          -- ISO-8601 UTC
  note        TEXT,                   -- free-form, optional
  PRIMARY KEY (video_stem, image_name)
);

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- meta keys:
--   schema_version = "1"
--   default_split_mode = "random" | "hybrid" | "manual"
```

One row per marked frame; absence means "not marked". `meta.default_split_mode` lets the picker UI restore the user's last preference per project. The mode actually used to create a given training dataset is recorded by DLC itself in `Documentation_data-*.pickle`.

`schema_version` enables additive future migrations.

## 4. Frame identity

The stable triple `(project_path, video_stem, image_name)` — the same MultiIndex DLC uses internally for the merged `training-datasets/iteration-N/UnaugmentedDataSet_*/CollectedData_<scorer>.h5`. This identity is invariant across iterations, across recreations of the merged H5, and across scorer renames (the file path is the same; only the columns change).

## 5. Architecture

One new blueprint inside the **main webapp** (not a new docker-images support module). The feature is tightly coupled to DLC project state (config_path, scorer, labeled-data tree) that the existing `dlc_labeling` blueprint already manages; creating a separate module would duplicate that plumbing.

### Components

1. **`src/dlc/marks_store.py`** — pure data layer. Opens the per-project SQLite, exposes `get_marks(project_path)`, `set_mark(project_path, video_stem, image_name, marked, note=None)`, `bulk_set(project_path, ops)`, `list_marks(project_path)`, `get_mode(project_path)`, `set_mode(project_path, mode)`. No Flask, no DLC imports — unit-testable in isolation.
2. **`src/dlc/test_set_picker.py`** — Flask blueprint. HTTP wrapper around `marks_store` + reads project state via the existing `_dlc_key()` Redis lookup the labeling routes use. Endpoints under `/dlc/project/test-set/*` and `/dlc/project/training-dataset/inspect`.
3. **`src/dlc/test_set_split.py`** — pure function `build_indices(...)` invoked **inside the worker** during `dlc_create_training_dataset`. Loads the merged H5, maps marks → positional indices, returns `(trainIndices, testIndices)` or `None` for random mode.

The existing `dlc_create_training_dataset` celery task (`src/dlc/tasks.py`) gains two optional kwargs (`split_mode: str = "random"`, `marks: list[tuple[str, str]] | None = None`). When `split_mode == "random"` (default), behavior is byte-identical to today — `dlc.create_training_dataset` is called with the exact same kwargs.

## 6. API surface

All routes are under the new `dlc_test_set_picker` blueprint and validate `(video_stem, image_name)` against resolved-path containment in `<project>/labeled-data/`, matching the pattern in `dlc_serve_frame_image`.

```
GET  /dlc/project/test-set/marks
       → { mode: "manual"|"hybrid"|"random",
           marks: { "<video_stem>": ["img0001.png", ...], ... },
           counts: { marked: N, total_labeled: M,
                     per_folder: { "<video_stem>": { marked, total } } } }

POST /dlc/project/test-set/marks/<video_stem>/<image_name>
       Body: { marked: true|false, note?: string }
       → { ok: true, marked: bool }

POST /dlc/project/test-set/marks/bulk
       Body: { ops: [ { video_stem, image_name, marked, note? }, ... ] }
       → { ok: true, applied: N }

POST /dlc/project/test-set/marks/clean-stale
       Sweeps marks whose (video_stem, image_name) no longer exists on disk.
       → { ok: true, removed: N }

POST /dlc/project/test-set/mode
       Body: { mode: "manual"|"hybrid"|"random" }
       → { ok: true, mode }

GET  /dlc/project/test-set/labels/<video_stem>
       → reuses dlc_labeling.dlc_get_labels response shape verbatim
         (so the picker can render bodypart overlay using shared client code)

GET  /dlc/project/training-dataset/inspect
       Query: ?iteration=N&shuffle=K  (iteration defaults to cfg["iteration"])
       → { iteration: N,
           datasets: [
             { shuffle: K, train_fraction: 0.8,
               train: [ { video_stem, image_name }, ... ],
               test:  [ { video_stem, image_name }, ... ],
               documentation_pickle: "<rel-path>" }
           ] }
```

### Changes to the existing CTD route

`POST /dlc/project/create-training-dataset` (in `src/dlc/training.py`) gains one optional body field:

- `split_mode: "random" | "hybrid" | "manual"` — defaults to `"random"`.

When non-random, the route snapshots current marks from SQLite at dispatch time and forwards them as celery kwargs. This decouples the worker from filesystem access to `test_set_marks.sqlite`.

The existing `freeze_split` field is preserved unchanged.

## 7. Split assembly — `build_indices`

```python
def build_indices(
    config_path: str,
    marks: list[tuple[str, str]],           # [(video_stem, image_name), ...]
    mode: Literal["random", "hybrid", "manual"],
    train_fraction: float,                   # from cfg["TrainingFraction"][0]
    seed: int = 42,
) -> tuple[list[int], list[int], dict] | None:
    """
    Returns (trainIndices, testIndices, stats) as positional rows into the
    merged CollectedData_<scorer>.h5. Returns None when mode == "random".
    stats is a sidecar dict: {dropped_marks: N, total_frames: M, ...}.
    """
```

### Algorithm

1. `mode == "random"` → return `None`. Caller calls DLC with no indices kwargs.
2. Build the merged DataFrame via `deeplabcut.generate_training_dataset.trainingsetmanipulation.merge_annotateddatasets(cfg, training_set_folder)` — the same function DLC calls internally. This guarantees positional indices align with what DLC will use.
3. Build `idx_lookup: {(stem, image) -> position}` by enumerating `Data.index`. The merged H5's row MultiIndex is `("labeled-data", stem, image)`; we drop the constant `"labeled-data"` prefix so lookups are keyed on the marks store's identity tuple directly.
4. Resolve marks → positions. Marks whose `(stem, image)` is no longer in the merged H5 are dropped silently; the count is included in `stats`.
5. **manual:**
   - `testIndices = sorted(mark_positions)`
   - `trainIndices = sorted(all_positions − mark_positions)`
   - If `mark_positions` is empty → raise `ValueError("Full manual mode requires at least one marked frame")`.
6. **hybrid:**
   - `target_test_count = round((1 - train_fraction) * len(Data))`
   - `forced_test = mark_positions`
   - `extra_needed = max(0, target_test_count − len(forced_test))`
   - `extra_test = numpy.random.default_rng(seed).choice(sorted(all − forced_test), size=extra_needed, replace=False)` if `extra_needed > 0` else `[]`
   - `testIndices = sorted(forced_test ∪ set(extra_test))`
   - `trainIndices = sorted(all_positions − testIndices)`
   - Overflow honored: if `len(forced_test) > target_test_count`, the test set just exceeds the configured ratio.
7. Multi-shuffle: caller wraps the result as `trainIndices=[idx]*num_shuffles, testIndices=[tidx]*num_shuffles`. All shuffles share the same split.

### DLC integration detail

When `trainIndices`/`testIndices` are passed, DLC:
- Derives `trainFraction = round(len(train) / (len(train)+len(test)), 2)` and uses **that** value for the resulting folder name (`…trainsetXXshuffleN`).
- Strips `-1` padding from arrays before use (`build_indices` does not pad; DLC handles enforcement itself when requested).

## 8. UI

### Entry point

One new opener button **"Test-set Picker"** in `templates/partials/card_dlc_project.html`, inserted **between** `btn-open-frame-labeler` and `btn-open-create-training-dataset`. Final order:

```
Edit config.yaml
Extract Frames
Label Frames
Test-set Picker          ← new
Create Training Dataset
Train Network
Analyze Video / Frames
…
```

Reflects the workflow: label → pick test set → create dataset → train.

### Card

New top-level card `templates/partials/card_test_set_picker.html`, included from `index.html` after `card_frame_labeler.html`. Same `.card.dlc-theme.hidden` + close-button mechanics as Frame Labeler.

#### Contents (modeled 1:1 on the Frame Labeler card)

1. **Header**: title `Test-set Picker`, an `[ Inspect splits ↗ ]` chip that opens an iteration/shuffle dialog, and a `×` close button.
2. **Keyboard cheatsheet box** (same kbd-grid style as labeler):
   ```
   ← / →                Previous / next frame
   T                    Toggle current frame in test set
   Shift+← / Shift+→    Previous / next labeled-data folder
   Home / End           First / last frame in folder
   M                    Cycle split-mode preference (Random → Hybrid → Manual)
   Esc                  Close picker
   ```
   All non-conflicting with the labeler's bindings.
3. **Split-mode chip row**: three radio chips `Random / Hybrid / Full manual`. Selecting writes through `POST /dlc/project/test-set/mode`. This is the *preference*; the actual mode for a given CTD run is confirmed in the CTD card.
4. **Labeled-frames folder dropdown** (`ts-stem-select`) + Refresh button — identical to `fl-stem-select` and populated from the same `/dlc/project/labeled-frames` endpoint.
5. **Frame nav row**: Prev / "Frame N / M" / Next / `img####.png` chip — same DOM/styling as `fl-frame-nav`. Adds a chip on the right: **`[ ✓ IN TEST SET ]`** (green when marked, grey when not), clickable, bound to `T`.
6. **Viewer controls**: same `Viewer size`, `Marker size`, `Show names` controls as the labeler.
7. **Canvas** `ts-canvas`: renders the frame and overlays bodypart dots **read-only** — no click placement, no drag, no delete. Uses a new shared module `src/static/js/frame_overlay.js` extracted from `frame_labeler.js` (see §11).
8. **Counters row**: `marked in this folder: 3 / 40 — project total: 47 / 312`. Refreshes on every toggle and on a 5 s timer to stay consistent across tabs.
9. **No bodypart chip list, no Save / Clear / Delete buttons** — those are labeler-only.

### Inspect mode (same card, alternate state)

- Entered from the `[ Inspect splits ↗ ]` chip → small dialog to pick `iteration` and `shuffle` (defaults to current iteration / shuffle 1).
- Header gains a banner: `Inspecting iteration-4 / shuffle-1 (trainset80) — read-only`.
- Mode chip row is hidden.
- `IN TEST SET` toggle is replaced by a `TRAIN` / `TEST` badge (green/orange).
- Folder dropdown still navigates; counters show per-folder train/test split for the selected shuffle.

### CTD card change

`templates/partials/card_training_dataset.html` gains a small **Split mode** selector (Random / Hybrid / Full manual) above the existing num-shuffles + freeze-split fields. The current value is initialized from the picker's mode preference; submitting CTD sends it as `split_mode`. No other changes to that card.

## 9. Edge cases & integrity

- **Frame deleted from `labeled-data/`** → mark stays in SQLite; `build_indices` silently drops it and reports count in `stats`. Manual "Clean stale marks" button on the picker card invokes `POST /dlc/project/test-set/marks/clean-stale`.
- **Frame label data missing (no CSV row but PNG present)** → not in merged H5, treated same as deleted.
- **Scorer changed in config.yaml** → marks remain valid; `(stem, image)` lookup is rebuilt against the new merged H5.
- **Concurrent toggles across browser tabs** → optimistic UI, debounced 200 ms; per-write `BEGIN IMMEDIATE` transactions. Last-write-wins. 5 s polling refresh keeps counters consistent.
- **Project switching** → card auto-clears state and re-opens marks store against the new project path, using the same `_dlc_key()` lookup as the labeler.
- **Empty marks + manual mode** → CTD task fails fast with a clean error before invoking DLC; UI surfaces the message.
- **Multi-animal projects** → `merge_annotateddatasets` already handles both formats; the merged DataFrame's row MultiIndex is the same shape (`("labeled-data", video_stem, image_name)`), so our lookup works unchanged. Tier-3 tests cover the single-animal case (DREADD-Ali); multi-animal coverage deferred to a follow-up if/when a fixture project is available.

## 10. Preserving existing behavior

Each guarantee below is locked in by a regression test (see §12).

- POSTing to `/dlc/project/create-training-dataset` **without** `split_mode` defaults to `"random"`. `dlc.create_training_dataset` is called with the **exact same kwargs as today** (`config_path`, `num_shuffles`, `userfeedback=False`). No `trainIndices` / `testIndices` arguments are passed.
- The `freeze_split` body field is preserved verbatim (currently documentation-only in the task; that behavior is unchanged).
- `card_dlc_project.html` button column is preserved; only one button is inserted.
- Frame Labeler card is functionally untouched. The only labeler code that moves is bodypart-overlay drawing, extracted into `frame_overlay.js`; existing labeler tests must still pass, plus a new pixel-snapshot test asserts identical rendered output.
- No celery task other than `dlc_create_training_dataset` is modified.

## 11. Shared draw module

`src/static/js/frame_overlay.js` — extracted from `frame_labeler.js`. Exports a small pure-rendering API:

```js
export function drawFrame(ctx, image, opts) {…}
export function drawBodyparts(ctx, labels, palette, opts) {…}
```

Imported by both `frame_labeler.js` (which retains all input handling — clicks, drags, keyboard) and the new `test_set_picker.js` (which uses only the draw functions). No behavior change for the labeler; locked in by a snapshot test.

## 12. Testing strategy

Three tiers.

### Tier 1 — pure unit tests (fast, no DLC needed)

- `tests/dlc/test_test_set_split.py` covers `build_indices` against a fabricated `pandas.DataFrame` with a MultiIndex. Cases:
  - random returns `None`
  - manual happy path; result is deterministic and partitions all frames
  - manual with empty marks → `ValueError`
  - hybrid below target → marks ⊆ test, exact `target_test_count`, fixed-seed reproducibility
  - hybrid at exact target → no random filler
  - hybrid above target → marks-as-test verbatim, `derived_fraction < train_fraction`
  - marks pointing at frames not in H5 → dropped, count surfaced
  - ratio rounding edge case (7 frames × 0.8)

- `tests/dlc/test_marks_store.py` covers `marks_store` against `tmp_path`:
  - create/open, set/clear, idempotent toggles, bulk ops
  - schema version write & re-open
  - `clean_stale` removes only rows whose files are gone
  - deletion of nonexistent rows is a no-op
  - mode get/set with allowlist validation

- `tests/dlc/test_test_set_picker_routes.py` — Flask test client with `marks_store` and project state mocked:
  - every endpoint happy path
  - 400/404/403 paths
  - path-containment guard against `../`, absolute paths, symlink escape
  - mode setter rejects unknown values

### Tier 2 — integration: existing CTD path is unchanged when `mode == "random"`

Extends `tests/test_dlc_celery_tasks.py`:

- `test_create_training_dataset_random_mode_unchanged` — POST with `split_mode: "random"` (and also POST with the field absent); asserts `dlc.create_training_dataset` is called with the same kwargs as today, **no** `trainIndices` / `testIndices`.
- `test_create_training_dataset_manual_passes_indices` — POST with `split_mode: "manual"` + marks; asserts `trainIndices=[idx]*num_shuffles, testIndices=[tidx]*num_shuffles` are forwarded, with the expected shape.
- `test_create_training_dataset_hybrid_passes_indices` — same for hybrid; asserts marks ⊆ `testIndices` and counts sum to total.
- All pre-existing tests in `test_dlc_training_routes.py` and `test_dlc_celery_tasks.py` must pass unchanged.

### Tier 3 — end-to-end against a duplicated real project

**Fixture** (`tests/dlc/conftest.py`, session-scoped):

- `e2e_dlc_project_copy`: copies the source DLC project at `/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07` (container path; host `/home/sam/data-disk/Parra-Data/DLC-Projects/DREADD-Ali-2026-01-07`) to a tmp dir using `shutil.copytree`. Copies only `config.yaml` + `labeled-data/` + `videos/` (using dummy files for video bytes). Skips `dlc-models-pytorch/`, prior `training-datasets/iteration-*` folders, analyzed outputs.
- Rewrites `project_path` in the copied `config.yaml`.
- Skips with `pytest.skip(...)` if the source path isn't mounted (so Tier 1+2 still run in environments without the NAS).
- Tears down via `shutil.rmtree` after the session.

**Test file** (`tests/dlc/test_create_training_dataset_e2e.py`, marker `@pytest.mark.e2e`):

For each parameterized case below, the test:

1. Starts from the duplicated project, empty `test_set_marks.sqlite`.
2. Seeds marks via the `marks_store` API.
3. Runs `dlc_create_training_dataset` synchronously (calls the task body with mocked `self.update_state`), passing `split_mode=<mode>` and the marks snapshot.
4. Locates the newly-written `Documentation_data-*.pickle` under `training-datasets/iteration-<N>/UnaugmentedDataSet_*/` and reads it.
5. Extracts positions [1] (train) and [2] (test) from the pickle, strips `-1` padding.
6. Maps each index → frame entry in position [0] → recovers `("labeled-data", video_stem, image_name)` tuples (the constant prefix is dropped before comparing against marks).
7. Reads the `.mat` file via `scipy.io.loadmat`; asserts `dataset['image']` row count == `len(train_frames)` (DLC writes the train set into the .mat).

**Assertions per case:**

- `mode == "manual"`:
  - `set(test_frames) == set(marks)`
  - `set(train_frames) == set(all_labeled_frames) − set(marks)`
  - Resulting folder name reflects the derived train fraction (e.g. `…trainset72shuffle1`).
- `mode == "hybrid"`:
  - `set(marks) ⊆ set(test_frames)`
  - When marks below quota: `len(test_frames) == round((1 − cfg.TrainingFraction[0]) × len(all_labeled_frames))`
  - `set(train_frames) ∩ set(test_frames) == ∅`
  - `set(train_frames) ∪ set(test_frames) == set(all_labeled_frames)`
- `mode == "random"`:
  - `len(train) + len(test) == len(all)` and `len(train) ≈ train_fraction × len(all)` (regression smoke).

**Parameterized cases:**

- manual with 5 marks across 2 folders
- manual with marks in 1 folder only
- hybrid with 2 marks (below quota)
- hybrid with marks ≈ quota (no padding needed)
- hybrid with marks > quota (overflow honored, derived fraction < 0.8)
- random with no marks (default-path regression)
- manual with empty marks → task fails fast with a clean error; `dlc.create_training_dataset` never called

### Runner expectations

- Tier 1 + 2 run on every commit (fast, hermetic).
- Tier 3 runs inside the worker container before each commit that touches `build_indices`, `dlc_test_set_picker`, or `dlc_create_training_dataset`. Documented as verification gates in the implementation plan.

## 13. Branching & commit cadence

- New branch `feat/test-set-picker` created at the **start** of implementation, branched from current `main` (HEAD `3e8edf9`). Spec and plan land on `main` first.
- One logical unit per commit; each commit's verification gates must pass before moving on. Suggested chain:

  1. `feat(dlc): add marks_store SQLite layer + unit tests`
  2. `feat(dlc): add build_indices split-assembly helper + unit tests`
  3. `feat(dlc): add test_set_picker blueprint (marks endpoints) + route tests`
  4. `feat(dlc): wire split_mode into create_training_dataset task (random path unchanged) + Tier-2 regression tests`
  5. `feat(dlc): add inspect endpoint (read pickle + map indices to frames) + tests`
  6. `refactor(static): extract frame_overlay.js shared draw module + labeler pixel-snapshot test`
  7. `feat(ui): add card_test_set_picker.html + opener button + test_set_picker.js (picker mode)`
  8. `feat(ui): inspect mode + dialog + dashboard counter`
  9. `feat(ui): wire split-mode selector into the existing Create-Training-Dataset card`
  10. `test(dlc): add Tier-3 e2e tests against duplicated DREADD-Ali project`

Each commit is independently revertable. PR is the full chain on the feature branch.

## 14. Out of scope

- A true 3-way train/val/test split (would require patching DLC's PyTorch trainer; not done).
- Multi-animal-project Tier-3 coverage (deferred to a follow-up once a fixture project exists).
- Per-shuffle distinct manual selections (multi-shuffle shares one split, by design).
- Editing an already-frozen split in place (inspect mode is read-only; re-running CTD with new marks is the path).
- A CLI for managing marks; web UI only.

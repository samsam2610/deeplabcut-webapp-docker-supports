# Inline 3D "Analyze for tag": Ignore frames already in _analyzed — Design

**Date:** 2026-07-16
**Repos:** `deeplabcut-webapp-docker` (backend worker) + `deeplabcut-webapp-docker-supports` / `dlc-3D` (frontend)
**Status:** Approved design, ready for implementation plan
**Extends:** [[2026-07-16-inline-3d-analyze-for-tag-override-labels-design]]

## Goal

Add a checkbox **`ignore frames already in _analyzed`** (checked by default) to the
"Analyze for tag" batch that skips frames finalized in `<stem>_analyzed.h5`. This
has **higher priority than "override existing labels"**: a finalized frame is
skipped even when override is checked, protecting human-curated/finalized work.

## Background (verified on disk)

- Canonical file: `canonical.canonical_h5_path(video_path)` →
  `<video_stem>_analyzed.h5` **in the same directory as the video**
  (`deeplabcut-webapp-docker/src/dlc/canonical.py:22-24`). Frame index = absolute
  video frame number, dense `RangeIndex(0..N)`, MultiIndex columns
  `scorer/bodyparts/coords` with coords `x,y,likelihood`.
- A **finalized** frame is a non-NaN row; `unfinalize_range` sets the row to NaN
  (`canonical.py:91-109`); `write_to_canonical` fills finite data
  (`canonical.py:112-136`). No dedicated read helper — callers use
  `pandas.read_hdf`.
- The **`_analyzed` coverage timeline** marks a frame in **presence mode**: a frame
  is "marked" when any bodypart has a finite x —
  `covered = (~np.isnan(poses_np[:, :, 0])).any(axis=1)`
  (`deeplabcut-webapp-docker/src/dlc/viewer.py:355-356`). This is the rule to
  reuse.
- The range worker `_run_range` (`tasks.py:3025`) currently reads **only** the
  per-scorer h5 `<stem><scorer>.h5` (`_resolve_h5_path`, `tasks.py:2861-2864`),
  via `_ia_pd.read_hdf` (`_ia_pd` is pandas). It does **not** read `_analyzed`.
  `tasks.py` does **not** currently import `canonical`.
- The skip filter `_filter_skip_already_done(target, existing_df, overwrite=False)`
  (`tasks.py:2783-2798`) short-circuits `if overwrite or existing_df is None`.
- Prior feature added the `overwrite` flag (route→payload→worker); this feature
  adds `ignore_analyzed` the same way. `_run_range` writes only the per-scorer h5;
  it never writes `_analyzed`.

## Behavior

### New control — `#ia3d-ignore-analyzed`

- Checkbox in `.ia3d-tag-batch`, next to the tag-lock / override controls,
  **checked by default**. Scoped to the "Analyze for tag" batch only; the
  current-frame and for-range buttons are unchanged.
- "Marked in `_analyzed`" = a frame whose `<stem>_analyzed.h5` row has a finite x
  for any bodypart (the timeline's presence rule — reused, not re-invented).

### Priority — ignore wins over override

Per-frame decision for a frame in the tagged window:

| ignore _analyzed | override | finalized in `_analyzed`? | already in `<stem><scorer>.h5`? | action |
|:---:|:---:|:---:|:---:|:---|
| ☑ (default) | ☐ (default) | yes | — | **skip** (protected) |
| ☑ | ☐ | no | yes | skip (already done) |
| ☑ | ☐ | no | no | analyze |
| ☑ | ☑ | yes | — | **skip** (protected — ignore wins) |
| ☑ | ☑ | no | — | analyze (overwrite) |
| ☐ | ☑ | — | — | analyze all (overwrite) |
| ☐ | ☐ | — | yes | skip (already done) |
| ☐ | ☐ | — | no | analyze |

Default (ignore ☑, override ☐) = today's skip behavior **plus** protection of
finalized frames.

### Confirmation

When override is checked, the ⚠️ confirm line notes that frames finalized in
`_analyzed` remain protected while "ignore _analyzed" is checked (so the warning
isn't misleading about human/finalized work).

## Architecture & changes

### Backend — `deeplabcut-webapp-docker`

1. `src/dlc/canonical.py` — add:

   ```python
   def labeled_frames(analyzed_df):
       """Frame indices 'marked' in the _analyzed coverage timeline: any bodypart
       with a finite x (presence mode; mirrors viewer._coverage_buckets)."""
       if analyzed_df is None or not len(analyzed_df):
           return set()
       x = analyzed_df.xs("x", level="coords", axis=1)
       return set(analyzed_df.index[x.notna().any(axis=1)].tolist())
   ```

2. `src/dlc/tasks.py`:
   - `_filter_skip_already_done(target_frames, existing_df, overwrite=False,
     analyzed_labeled=None, ignore_analyzed=False)` — exclude `analyzed_labeled`
     frames first (only when `ignore_analyzed` and the set is non-empty), with
     priority over `overwrite`; then apply the existing overwrite/skip logic.
     Backward-compatible when the new args are omitted.
   - `_run_range` — read `<stem>_analyzed.h5` via
     `canonical.canonical_h5_path(req["video_path"])` **only when
     `ignore_analyzed`**; compute `analyzed_labeled = canonical.labeled_frames(...)`;
     pass both new args plus `req.get("ignore_analyzed", False)`. Lazy
     `from dlc import canonical`.
3. `src/dlc/inline_analysis.py` — `range_submit` payload gains
   `"ignore_analyzed": bool(body.get("ignore_analyzed", False))` (default False).

Reference skip-filter shape:

```python
def _filter_skip_already_done(target_frames, existing_df, overwrite=False,
                              analyzed_labeled=None, ignore_analyzed=False):
    labeled = analyzed_labeled if (ignore_analyzed and analyzed_labeled) else set()
    if overwrite:
        # ignore_analyzed has priority over overwrite: finalized frames stay skipped.
        return [f for f in target_frames if f not in labeled]
    have = existing_df.index if existing_df is not None else []
    return [
        f for f in target_frames
        if f not in labeled
        and (existing_df is None or f not in have or existing_df.loc[f].isna().all())
    ]
```

### Frontend — `dlc-3D`

4. `src/templates/partials/card_inline_analysis_3d.html` — add
   `#ia3d-ignore-analyzed` checkbox in `.ia3d-tag-batch`, **`checked`** by default.
5. `src/static/inline_analysis_3d.js`:
   - `_submitRange(sk, videoPath, startFrame, nFrames, overwrite = false,
     ignoreAnalyzed = false)` — send `ignore_analyzed: !!ignoreAnalyzed` in the
     body. The two other callers keep both defaults (unchanged).
   - `_onAnalyzeTagClick` — read `#ia3d-ignore-analyzed` into `const
     ignoreAnalyzed`; pass it to both `_submitRange` calls; extend the override
     ⚠️ confirm line to note `_analyzed` protection when ignore is checked.

## Testing

### Backend (`deeplabcut-webapp-docker/tests`)

- `tests/test_canonical_analysis_file.py`: `labeled_frames` — finite-x rows
  included; all-NaN rows excluded; `None`/empty → empty set.
- `tests/test_inline_analysis_worker.py`:
  - `_filter_skip_already_done` truth table, especially the priority case
    `ignore_analyzed=True, overwrite=True` → finalized frames excluded; and the
    no-op case `ignore_analyzed=False` → unchanged from prior behavior.
  - `_run_range` with `ignore_analyzed=True`: a `pandas.read_hdf` router returns
    the per-scorer seed and the `_analyzed` seed by path; assert finalized frames
    are skipped even with `overwrite=True` (they don't reach inference).
- `tests/test_inline_analysis_routes.py`: `ignore_analyzed` reaches the enqueued
  payload; defaults False when absent.

### Frontend (`dlc-3D/tests`)

- pytest static guards: `#ia3d-ignore-analyzed` present **and `checked`** in
  `.ia3d-tag-batch`; `_submitRange` includes `ignore_analyzed` in its body;
  `_onAnalyzeTagClick` reads `#ia3d-ignore-analyzed` and passes it to both submits.
- e2e (`tests/e2e/`): checkbox present and **checked** by default (read-only).

## Edge cases

- No `<stem>_analyzed.h5` (nothing finalized yet) → `analyzed_labeled` empty →
  `ignore_analyzed` has no effect; behavior falls through to overwrite/skip.
- `ignore_analyzed=False` (unchecked) → `labeled` is empty → filter is byte-for-byte
  the prior `overwrite`/skip behavior.
- A frame both finalized in `_analyzed` and predicted in the per-scorer h5 → skipped
  under any combination when ignore is checked (protection dominates).

## Out of scope (YAGNI)

- The range worker still never writes `_analyzed` (only the per-scorer h5).
- No per-bodypart partial protection — a frame is protected if ANY bodypart is
  finalized (matches the presence timeline rule).
- No `ignore_analyzed` control on the current-frame or for-range buttons.
- No refactor of `viewer._coverage_buckets` (it consumes `poses_np`; the new
  helper consumes the DataFrame — they share the finite-x rule by definition).

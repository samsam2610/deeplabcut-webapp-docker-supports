# Per-tag note colours — report

## Status

Done. Deterministic per-tag NOTE colours, user overrides via a colour control
on each chip, per-project persistence shared across both inline-3D cards, and
overridden-first-then-alphabetical chip ordering — implemented as two pure
functions in a new library module plus an opt-in `tagColors` config on
`statusNoteTimeline`, with the two inline-3D cards owning persistence.

## Commit SHAs

- `deeplabcut-webapp-docker-supports` (branch `fix/marker-save-race`): `0e7e3c2107f8e16129e53dedd620bc313b00fdf3`
- `deeplabcut-webapp-docker` (branch `fix/marker-save-race`): `fec55ad0fb4ebea4d701624e496319610d5e8eec`

## What changed

- **New**: `dlc-3D/src/static/components/viewer/internal/tag_colors.mjs` — pure,
  DOM-free: `tagColor(name, palette)` (FNV-1a hash of the name mod palette
  length — no `Math.random`/`Date`/insertion-order state), `sortTags(tags,
  overrides)` (overridden tags first — alphabetical within that group — then
  the rest alphabetically, ordinary non-locale string comparison), and
  `isValidHexColor(value)` (strict `^#[0-9a-fA-F]{6}$`).
- **Changed**: `dlc-3D/src/static/components/viewer/features/status_notes.js` —
  new optional `config.tagColors = { overrides, onColorChange }`. When absent,
  `recolor()`'s note-color branch is byte-identical to the old
  `assignColors(uniqueValues(rows, "note"), notePalette)` call and no colour
  control is rendered — unchanged behaviour. When present: note colours use
  `sortTags` + `tagColor`/override-with-validation-fallback; each note chip
  gets an `<input type="color" class="vv-tag-color-input">` that stops
  propagation (doesn't toggle chip active state), validates via
  `isValidHexColor`, mutates `tagColors.overrides` in place, repaints, and
  calls `tagColors.onColorChange(tag, color)`. New public method
  `refreshTagColors()` lets a consumer force a repaint after an async load of
  overrides resolves. Status chips are untouched (`colorControlPalette` is
  always `null` for them).
- **Changed**: `dlc-3D/src/static/inline_analysis_3d.js` and
  `inline_analysis_3d_reprojection.js` — each adds `IA3D(R)_NOTE_TAG_COLORS_KEY
  = "note_tag_colors"` (same literal, deliberately shared), a module-level
  `_noteTagColorOverrides` object passed by reference into
  `tagColors.overrides`, `_loadNoteTagColors()` (GET, called from
  `_loadAllQuickTags()` on every video open, then calls
  `_snTimeline?.refreshTagColors()`), and `_saveNoteTagColors()` (debounced
  POST, wired as `onColorChange`).
- **Changed**: `dlc-3D/src/static/inline_analysis_3d.css` and
  `inline_analysis_3d_reprojection.css` — small `.vv-tag-color-input` swatch
  styling, scoped to each card like the existing `.vv-tag-chip` rules.
- **Changed**: `deeplabcut-webapp-docker/src/dlc/inline_analysis.py` — added
  `"note_tag_colors"` to `_UI_SETTING_KEYS` (without this every GET/POST for
  the key 400s and nothing persists — this is exactly the bug just fixed for
  eight other keys).
- **New tests**:
  - `dlc-3D/tests/unit/test_viewer_tag_colors.mjs` (`node:test`) —
    `tagColor`/`sortTags`/`isValidHexColor` determinism, distribution,
    order-independence (including a cache-busting dynamic-import test that
    primes two independent module instances with different call orders and
    checks the target name still gets the same colour in both — this is what
    catches an insertion-order regression that a same-process test can't, since
    a warm per-name cache would otherwise mask it).
  - `dlc-3D/tests/test_status_notes_tag_colors.py` — static-analysis contract
    for the library-side change (imports, branch on `tagColorsCfg`, legacy
    else-branch preserved verbatim, `isValidHexColor` gating both apply and
    paint sites, colour-control markup + propagation guard, `onColorChange`
    wiring, `refreshTagColors()` export, status chips never get a colour
    control).
  - `dlc-3D/tests/test_note_tag_colors_wiring.py` — both cards declare the
    shared key literal, GET/POST it, wire `tagColors` into
    `statusNoteTimeline`, load-then-refresh, debounce + best-effort save, and
    that `note_tag_colors` is in the main webapp's `_UI_SETTING_KEYS`.

## Test summary

- `node --test tests/unit/*.mjs` (dlc-3D): 28 files, **27 pass / 1 fail** — the
  1 failure is `test_reproj_help.mjs`, pre-existing and unrelated (HELP
  parameter-coverage assertion, untouched by this change). The new
  `test_viewer_tag_colors.mjs` passes in full.
- `python3 -m pytest tests/ -q --ignore=tests/e2e` (dlc-3D): **8 failed, 862
  passed, 3 skipped** — the 8 failures are exactly the documented pre-existing
  baseline (`test_inline_analysis_3d_ui_isolation.py::test_finalize3d_confirms_before_overwrite`,
  `test_lp_csv_to_h5.py` x2, `test_lp_predict_pairing.py` x5), unrelated to
  this change. 862 = the 845-passing baseline + 17 new tests (11 +
  6) added by this work. No pre-existing assertion was modified or removed.
- `node --check --input-type=module` passed on every touched/added
  `.js`/`.mjs` file; grepped each new identifier
  (`tagColor`/`sortTags`/`isValidHexColor`/`refreshTagColors`/
  `_loadNoteTagColors`/`_saveNoteTagColors`/`_noteTagColorOverrides`) to
  confirm it's defined where used, in both cards.

## Mutation-proof output

**(a) `sortTags` mutated to plain alphabetical, ignoring overrides:**

```
$ node --test tests/unit/test_viewer_tag_colors.mjs
not ok 10 - sortTags: some overrides -> overridden tags first (alphabetical within group), then the rest alphabetically
...
# tests 15
# pass 14
# fail 1
```

Reverted; `diff` against the pre-mutation copy showed no residual difference,
and the full `tests/unit/test_viewer_tag_colors.mjs` re-run passed 15/15.

**(b) `tagColor` mutated to assign slots by first-seen call order (module-level
`_seenOrder` array) instead of hashing the name:**

```
$ node --test tests/unit/test_viewer_tag_colors.mjs
not ok 8 - tagColor: same name -> same color even under different call-order priming (catches insertion-order regressions)
  error: 'tagColor must not depend on prior calls for other names'
...
# tests 15
# pass 0
# fail 1
```

(Node's TAP reporter treats the whole test-runner run as one node when the
first `assert` throws before the runner iterates further subtests, hence
`pass 0` — the failure itself is `not ok 8`, the targeted mutation-proof test;
the other 14 tests were not reached in that particular run because the file
aborted early. A second run with reordered tests still isolated the same
failing assertion.) Reverted; `diff` showed no residual difference, and the
full suite re-passed (28 files, 27/28 — same pre-existing unrelated failure).

## Other consumers of `status_notes.js`

Found via `grep -rln "status_notes\|statusNoteTimeline" src/static`:

- `src/static/dlc_3d.js` ("3D Extract" card)
- `src/static/viewer_3d.js` ("View Analyzed" card)
- `src/static/inline_analysis_3d.js` (updated — passes `tagColors`)
- `src/static/inline_analysis_3d_reprojection.js` (updated — passes `tagColors`)

Confirmed `dlc_3d.js` and `viewer_3d.js` are unaffected: `grep -c "tagColors"`
returns 0 for both, so their `statusNoteTimeline({...})` calls never set
`config.tagColors` — `tagColorsCfg` stays `null` inside the feature, `recolor()`
takes the unchanged `assignColors(...)` branch, and `rebuildChips()` passes a
falsy `colorControlPalette` for note chips, so no colour-control markup is
added and note-chip ordering/colouring is byte-for-byte the same as before.
Also checked `clip-cutter/` (the frozen pre-library origin per
`docs/policies/video-viewer-component.md`) — it does not import
`status_notes.js` at all (`grep -rl "status_notes" clip-cutter/` empty), so it
is structurally unaffected.

## Concerns / notes

- **Load/construction race**: `_noteTagColorOverrides` is loaded via GET on
  every video open (`_loadAllQuickTags()`), while `_ensureViewer()` (which
  constructs `_snTimeline` referencing that same object) typically runs
  earlier in the same call chain, before the video/CSV finish loading. Since
  the overrides object is passed **by reference** and read live inside
  `recolor()`, and `_loadNoteTagColors()` explicitly calls
  `_snTimeline?.refreshTagColors()` after it resolves, both orderings converge
  correctly — but this is an async race handled by "eventually consistent +
  force a repaint," not a single deterministic ordering, worth knowing if this
  area is touched again.
- **Validation is centralized** in `status_notes.js` (`isValidHexColor` gates
  both the recolor's override-application and the chip's colour-control
  paint), not duplicated in the cards — a malformed/tampered
  `note_tag_colors` value from storage falls back to the deterministic
  default rather than reaching `style.setProperty`.
- Did not touch `dlc_3d.js` or `viewer_3d.js` — they weren't in scope (status
  colouring wasn't requested for them) and this preserves their behaviour
  exactly, per the backward-compatibility requirement.

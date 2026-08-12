# Pellet box placement — design

**Date:** 2026-08-11
**Card:** `3D Inline Analysis - SAM Model` (`dlc-3D/src/static/inline_analysis_3d_sam.*`)
**Status:** approved, tests first

## Problem

The pellet template needs a box centred on the stationary pellet, per camera, per
video pair. The project default is wrong on any session where the pedestal has
drifted — visibly so on banh-mi-1 Jul 7 — and a wrong box does not fail loudly:
it fills the armed mask with paws and costs a multi-minute sweep to discover.

A first attempt made the box draggable. It did not work, and shipped three bugs:

| symptom | cause |
|---|---|
| trail of after-images while dragging | box stroked onto the viewer's own tile canvas, nothing erasing the previous frame |
| cam1 undraggable after dragging cam0 | hit-testing a canvas the player also owns and repaints |
| **dozens of overlapping boxes** | `_pelletTiles()` selects every `<canvas>` in the card except two by id; the overlay canvases had no id, so each poll gave every overlay its own overlay — exponential |

The third is the one that matters for process: it is a two-line DOM invariant that
a single test would have caught, and no test existed. 141 Python tests covered the
backend; the panel had none. "Verification" was grepping the served file for
strings, which proves deployment, not behaviour.

## Interaction

Click to place, WASD to refine. No drag, no mode toggle.

| gesture | effect |
|---|---|
| click on a tile, that camera has **no box** yet | place **box centre + pellet label** at the point |
| click on a tile, box **already placed** | place a **pellet label** only |
| W / A / S / D | nudge **whatever was just placed** by 1 px (shift → 10 px) |
| Confirm | unlock sweeping for this pair |

A click always means "the pellet is here", so it is never ambiguous. The box is
placed once per pair; every later click grows the template pool.

Clicking a second time on the same (frame, camera) **overwrites** that frame's
pellet label rather than stacking a duplicate — a second click there is a
correction, not a new observation.

## Persistence — `<video>_onset.csv`

The sidecar becomes the source of truth for both, rather than a second copy in
the JSON model. Four new columns:

| column | meaning |
|---|---|
| `mark_kind` | `box` or `pellet` |
| `mark_cam` | `cam0` or `cam1` |
| `mark_x`, `mark_y` | full-frame pixel position |

* one `box` row per camera per video — its `frame_number` records the frame it
  was placed on, so it can be revisited
* `pellet` rows are the template-pool labels

On opening a pair, a camera with no `box` row is unplaced: the panel says so and
sweeping stays blocked (HTTP 428).

**The box centre is derived, never stored twice.** Centre for a camera =
its `box` row if present, else the project default. The box and the labels
cannot disagree because there is only one place either can come from.

## Rendering

One overlay canvas per tile, **created once and given an id** (`ia3ds-ov-cam0`,
`ia3ds-ov-cam1`), cleared before every draw. `_pelletTiles()` must exclude any
canvas whose id starts with `ia3ds-` — an allowlist of the two exclusions was
what let overlays be mistaken for tiles.

The checkbox controls **visibility only**. Clicking to place works regardless.

## Tests — written and passing before delivery

As `.mjs` unit tests under `dlc-3D/tests/unit/`, mirroring the DOM-bound logic as
pure functions, matching the 33 existing ones. Node's runner does not discover
them in directory mode, so each file runs directly.

1. tile selection excludes overlay canvases, **and** stays correct after a second
   pass (the exponential bug, pinned in both directions)
2. first click on a camera yields box + pellet; a second yields pellet only
3. a second click on the same (frame, camera) overwrites rather than duplicates
4. WASD moves only the most recent placement; when that was a first click, the
   box and its pellet move together
5. nudges clamp to frame bounds
6. centre derivation: box row wins, project default when absent
7. the four new CSV columns round-trip

Python-side, `onset_csv` gains matching tests for the new columns.

## Out of scope

Dragging is removed entirely rather than fixed. Placement by click plus keyboard
refinement covers the same need with far less that can go wrong, and none of the
three failures above are reachable from it.

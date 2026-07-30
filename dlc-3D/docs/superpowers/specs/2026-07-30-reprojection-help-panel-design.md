# Reprojection panel — in-panel contextual help

**Date:** 2026-07-30
**Status:** design approved, not yet implemented
**Module:** `dlc-3D`
**Builds on:** [2026-07-30-reprojection-per-camera-thresholds-design.md](2026-07-30-reprojection-per-camera-thresholds-design.md)

## Problem

The reprojection panel now carries ten controls: trusted camera, `k₁`, `k₂`, and
four likelihood parameters for each of two cameras. Their names are the engine's
own, chosen so the panel matches the audit JSON, which makes them precise but
opaque. Two of them behave counter-intuitively:

- **`high_conf`** never decides a verdict. It only chooses the calibration
  sample, and *lowering* it widens that sample, inflates the thresholds, and
  makes the rule more permissive — the opposite of what "raise the confidence
  bar" suggests.
- **`low_tgt`** gates rescues only. It has no effect on rejection at all.

Both are documented in `docs/reprojection-parameters.md`, but nobody reads a doc
while adjusting a slider.

## Scope

A help box in the empty space to the right of the per-camera groups. It shows a
short summary by default and, when a control is hovered or focused, that
parameter's explanation and a worked example from real data.

### Non-goals

- Explaining the epipolar method itself. This explains the controls.
- Replacing `docs/reprojection-parameters.md`, which stays the long-form
  reference. The panel carries a condensed version.
- Any change to the engine, the endpoints, or the shared viewer library.

## Layout

The per-camera groups already live in `.ia3dr-percam-wrap`, a
`display: flex; gap: 1rem; flex-wrap: wrap` container whose children have
`min-width: 12rem`. On a wide card the two fieldsets leave real empty space to
their right.

The help box becomes a **third child of that same container**:

```html
<div class="ia3dr-help" id="ia3dr-reproj-help" aria-live="polite"></div>
```

with `flex: 1 1 16rem; min-width: 14rem`. It fills the space beside cam0/cam1 and
wraps underneath on a narrow card, using the flex behaviour that is already
there. No restructuring, and nothing else in the panel moves.

`aria-live="polite"` so the swap is announced rather than silently replaced.

## Behaviour

- **Default** — a two-line summary of what the panel does, shown on open and
  restored whenever nothing is hovered or focused.
- **On hover or focus of a control** — that parameter's title, explanation and
  worked example replace the summary.
- **On leave or blur** — the default returns.

Focus matters as much as hover: tabbing through the inputs must teach the same
things as mousing over them, and focus is the only route for keyboard users.

One delegated listener on `#ia3dr-reproj-panel` handles `mouseover`, `focusin`,
`mouseout` and `focusout`, reading a `data-help="<key>"` attribute from the event
target or its closest ancestor carrying one. Delegation means adding a parameter
later needs one attribute on the markup, not another listener.

Both cameras' inputs for the same parameter carry the same key: `gate_ref` means
the same thing whichever camera it sits under, and the explanation says which
camera it applies to.

## Content

Text is condensed from `docs/reprojection-parameters.md`. Every entry has a
title, a body, and a concrete example measured on the `eggtart-1` reference
session — the example is what makes each one land.

| Key | The point | Example |
| --- | --- | --- |
| `trusted_cam` | Induces the epipolar line; the other camera is judged | cam1 is the better view here: mean likelihood 0.51 vs cam0's 0.39 |
| `k1` | Trust band, a multiplier on each bodypart's own noise | ×3 gives 3.30 px on the Pellet but 21.53 px on the Wrist |
| `k2` | Reject band; beyond it a marker is deleted | ×8 gives 7.28 px on the Pellet, 45.66 px on the Wrist |
| `gate_ref` | Coverage dial on the **trusted** camera | at 0.6, 3,293,909 of 4,026,240 slots were left unjudged |
| `low_tgt` | Rescue ceiling on the **judged** camera; no effect on rejection | below 0.6 a marker can be rescued; at or above it is simply confirmed |
| `high_conf` | Chooses the calibration sample. **Lowering it loosens the rule** | Wrist, cam0 0.9→0.7: 2,803 → 4,924 frames, t_ok 21.5 → 22.2 px |
| `rescue_floor` | Likelihood written on a rescue, on the **judged** camera | must exceed your downstream filter, or the rescue achieves nothing |

## Architecture

Help text lives in a pure data module, not inline in the markup:

```js
// src/static/internal/reproj_help.mjs
export const HELP_DEFAULT = { title, body };
export const HELP = { <key>: { title, body, example }, ... };
```

Keeping it out of the markup makes it unit-testable and keeps the card fragment
readable. The panel imports it and renders into the box.

## Testing

**Pure data** (`tests/unit/test_reproj_help.mjs`, `node --test`):

- every entry has a non-empty `title`, `body` and `example`
- `HELP_DEFAULT` has a title and body
- the key set is exactly the seven above — a guard against a stale key surviving
  a rename

**Markup/wiring** (`tests/test_reproj_panel_markup.py`,
`tests/test_reproj_panel_wiring.py`):

- the help box exists, inside `.ia3dr-percam-wrap`, and carries `aria-live`
- **every control carrying `data-help` has a matching key in `HELP`**, checked by
  parsing both files. This is the assertion that matters: when someone adds an
  eighth parameter and forgets its help text, a test fails instead of a user
  meeting a blank box.
- the listener covers `focusin`/`focusout`, not only mouse events
- the default is restored on leave

That cross-file check is deliberately stronger than the panel's usual
string-presence tests. Those already allowed a completely unwired overlay to ship
in this project; a test that merely confirmed the word "help" appeared would
repeat the mistake.

## Risks

- **The text drifts from the behaviour.** The examples cite measured numbers that
  will not change unless the engine changes, and the key-set test catches
  renames — but nothing detects a parameter whose *meaning* changed while its
  name stayed. `docs/reprojection-parameters.md` and this panel must be updated
  together; both are named in the spec so the link is discoverable.
- **Hover help is invisible to touch users.** Focus handling covers keyboard;
  touch gets the default summary only. Acceptable for a desktop research tool.

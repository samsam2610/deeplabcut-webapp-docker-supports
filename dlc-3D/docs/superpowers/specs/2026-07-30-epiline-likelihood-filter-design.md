# Epipolar line display threshold

**Date:** 2026-07-30
**Status:** design approved, not yet implemented
**Module:** `dlc-3D`
**Builds on:** [2026-07-30-epipolar-line-colour-and-labels-design.md](2026-07-30-epipolar-line-colour-and-labels-design.md)

## Problem

Every bodypart with a chip gets an epipolar line, however weak the reference
marker that induced it. A line drawn from a 0.05-likelihood marker is noise: it
points nowhere useful and adds to the sixteen already on screen.

There is no way to say "only show me lines I should take seriously".

## Scope

A likelihood field beside the **Show epipolar lines** checkbox. A line is drawn
only when the reference camera's marker for that bodypart clears it.

### Non-goals

- Changing any verdict. This gates **display only**; `gate_ref` still decides
  what the engine judges, and the two are deliberately separate.
- Any backend change. The endpoint already returns what is needed.

## Why no backend change

`GET /reproject/epiline` already responds with
`{"segment": [[x1,y1],[x2,y2]] | null, "likelihood": float}` — the reference
marker's likelihood at that frame and bodypart (`routes.py:1005`). The frontend
currently discards it:

```js
if (res.ok) seg = (await res.json()).segment || null;
```

The fix is to keep it. No extra request, no new endpoint.

## The control

A number input beside the checkbox:

- id `ia3dr-reproj-line-lik`, `min="0"`, `max="1"`, `step="0.05"`
- **default `0.4`**

0.4 sits deliberately **below** `gate_ref`'s 0.6. Lines between 0.4 and 0.6 are
drawn but were not strong enough for the engine to judge against — which is
often exactly what explains an `UNJUDGED` verdict, so hiding them would remove a
diagnostic.

**This changes what is on screen.** Today every line is drawn; after this,
reference markers below 0.4 stop producing one. That is the point of the
feature, but it is a visible behaviour change on first reload rather than a
purely additive one.

## Data flow

`_reprojFetchSegment(frame, bp)` currently returns a segment or `null` and caches
that. It changes to return and cache `{segment, likelihood}`:

- cache value becomes an object; `null` still means "asked, nothing there"
- the existing 4000-entry bound and the clear-on-bind behaviour are unchanged
- the cache is per page session and rebuilt on viewer bind, so no migration
  concern

## Drawing

Two changes in the `drawTile` loop:

1. Skip a bodypart whose `likelihood` is below the threshold.
2. **`order` must count only lines actually drawn.** It is currently the loop
   index over visible bodyparts; leaving it that way would open gaps in the
   label staircase wherever a line was filtered out. The counter therefore moves
   inside the loop and increments only after a successful draw.

Changing the field calls the existing `_reprojRepaint()`, so the effect is
immediate rather than waiting for the next seek.

## The filter decision is pure, so it gets tested

```js
// src/static/internal/epiline_filter.mjs
export function shouldDrawLine(likelihood, threshold) -> boolean
```

- `true` when `likelihood >= threshold`
- `false` for `null`, `undefined` or `NaN` likelihood — an unknown confidence is
  not a confident one
- a threshold of `0` still admits a `0` likelihood, so "0" genuinely means
  "show everything"
- a non-finite threshold falls back to drawing, so a blanked field cannot make
  every line vanish

That last case matters: a user clearing the input to retype should not silently
lose all lines.

## Persistence and help

`line_lik` joins the `reproj_params` blob, so the setting survives reopening the
card, alongside the trusted camera, `k₁`/`k₂`, the eight per-camera values and
the overrides.

The control carries `data-help="line_lik"` with an entry stating that it gates
display only, not judgement, and that its default sits below `gate_ref` on
purpose.

## Testing

**Pure** (`tests/unit/test_epiline_filter.mjs`, `node --test`): the six cases
above, each asserted separately.

**Wiring** (`tests/test_reproj_panel_markup.py`, `tests/test_reproj_panel_wiring.py`):

- the field exists beside the checkbox with the right bounds and a `0.4` default
- it carries `data-help`, and `line_lik` has a `HELP` entry (the existing
  cross-file guard covers this automatically)
- the draw loop consults `shouldDrawLine`
- `order` is incremented inside the loop rather than used as the loop index —
  the staircase-gap regression
- the field is **not** added to any request payload; it is client-side only

## Risks

- **A user may read it as a verdict threshold.** It sits next to the display
  checkbox rather than among the per-camera parameters, and its help text says
  so explicitly, but the confusion is plausible given `gate_ref` exists.
- **Fewer lines can look like the feature broke**, which has already happened
  twice in this project for unrelated reasons. The default of 0.4 is mild, and
  the field shows its own value, so the cause is visible on the panel.

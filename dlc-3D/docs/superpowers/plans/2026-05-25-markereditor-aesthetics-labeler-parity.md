# markerEditor Aesthetics → Frame-Labeler Parity (+ fix marker size) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the shared `markerEditor`'s marker aesthetics + options match `frame_labeler_3d.js` (FL color palette, white selected ring, dark contrast outline, hover-name + show-names toggle, hit-pad 6) and fix the marker-size slider that is currently a no-op in both 3D curation cards.

**Architecture:** Frontend-only. All visual logic lives in the **shared** `markerEditor` feature + the internal `palette.mjs` / `shapes.mjs` helpers, so the inline-3D card (`inline_analysis_3d.js`) **and** View Analyzed (`viewer_3d.js`) inherit every change from one place — no player fork. A new pure `name_label.mjs` holds the hover/name-label box geometry (node-tested). Consumers only gain two wiring changes each: marker-size slider → `setMarkerSize`, and a new "Show names" checkbox → `setShowNames`.

**Tech Stack:** Vanilla ES modules (browser ESM, bind-mounted live — no rebuild for `.js`/`.mjs`), `<canvas>` 2D rendering, Jinja2 partials (templates need `docker compose restart dlc-3d`), Node's built-in `node:test` for pure `.mjs` logic, pytest static-source assertions for the feature/consumer/template contracts, Python Playwright for live read-only verification.

---

## Grounding facts (read before starting)

- **Repo / branch:** `deeplabcut-webapp-docker-supports/dlc-3D`, branch `feat/marker-editor-labeler-mechanics` (already checked out; continues the labeler-parity work, not yet merged to main).
- **No player fork.** `tests/test_video_viewer_policy.py` must stay green. Never add `class Tile` or `const Controller`.
- **`markerEditor` is SHARED** by `inline_analysis_3d.js` AND `viewer_3d.js` (View Analyzed). Every aesthetic change lands in both automatically. The plan ends with an explicit **View-Analyzed regression step**.
- **View Analyzed edits via its overlay toggle** — `viewer_3d.js` mirrors `setEditable(on)` to `setOverlayEnabled(on)` at every call site (`viewer_3d.js:442/447` and `:953/954`). `tests/test_video_viewer_policy.py::test_viewer_3d_mirrors_setEditable_to_overlay_enabled_state` enforces that `setOverlayEnabled` and `setEditable` are called with identical args. **`setShowNames` is a NEW method — it is NOT `setEditable`, so wiring the show-names checkbox must NOT touch the overlay/editable lockstep.** Do not break that test.
- **No data-layer change.** No new routes, no backend edits.
- **Test runners:**
  - JS (pure `.mjs`): `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/<file>.mjs`
  - pytest: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/<file>.py -q`
  - `.js`/`.mjs` are bind-mounted (live, no rebuild). **Template (`.html`) edits require** `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart dlc-3d`.
- **Live verify (read-only):** Python Playwright. Auth via `GET http://localhost:5000/?token=deeplabcut`. Posed video: project **DREADD-Ali**, video **khoai-lang-1**, **cam0**. **NEVER click Save Adjustments / Add range / Extract / Finalize / Delete.** Verification is look-only (drag sliders, hover, toggle checkboxes — those don't persist).
- **No `viewer_3d` UI-isolation test file exists.** View-Analyzed assertions live in `tests/test_video_viewer_policy.py` (lockstep guard) and `tests/e2e/test_analyzed_viewer.py`. This plan adds the View-Analyzed consumer-wiring assertions to `test_video_viewer_policy.py`'s sibling style is not used; instead they go into a new lightweight check inside the existing `inline_analysis_3d` style or are verified live. See Task 3 and Task 6.

## Exact values to be used (copied verbatim from `frame_labeler_3d.js`)

These are the single source of truth for every later assertion. Do not paraphrase or round them.

- **`FL_COLORS`** (15 hexes, from `frame_labeler_3d.js:623-627`):
  ```js
  const FL_COLORS = [
    "#f87171","#fb923c","#fbbf24","#a3e635","#34d399",
    "#22d3ee","#818cf8","#e879f9","#f43f5e","#10b981",
    "#3b82f6","#ec4899","#f59e0b","#84cc16","#06b6d4",
  ];
  ```
- **`labelerColor(idx)`** — cycle, negative-safe (matches `_flColor` at `frame_labeler_3d.js:628`, hardened for negatives like `paletteColor`'s double-modulo at `palette.mjs:12`):
  ```js
  labelerColor(idx) = FL_COLORS[((idx % n) + n) % n]   // n = FL_COLORS.length = 15
  ```
- **Selected ring** (`frame_labeler_3d.js:1234-1235`): arc at `r + 3.5`, `strokeStyle = "rgba(255,255,255,0.85)"`, `lineWidth = 2`.
- **Marker fill + outline** (`frame_labeler_3d.js:1237-1239`): fill `color`, then arc at `r`, `strokeStyle = "rgba(0,0,0,0.55)"`, `lineWidth = 1.2`.
- **Name label** (`frame_labeler_3d.js:1243-1248`): `font = "bold 11px 'JetBrains Mono', monospace"`; box bg `fillStyle = "rgba(12,13,16,.65)"`, rect `fillRect(cx + r + 2, cy - 7, measureText(bp).width + 6, 14)`; text `fillStyle = color`, `fillText(bp, cx + r + 5, cy + 4)`.
- **DROP** (currently in `marker_editor.js:223-225` and `:239-240`): the amber selected ring `ring(ctx, cx, cy, r + (edited?6:3), "#facc15", 2)` AND the white edited ring `ring(ctx, ..., r + 3, "#fff", 1.5)`.
- **Hit pad:** change `8` → `6` at the three `hitTest(...)` call sites in `marker_editor.js` (`:337-338`, `:446`, `:466`). `marker_overlay.mjs::hitTest` already defaults `pad = 6` and is unchanged.

## How the existing node tests are structured (match these exactly)

- **`tests/unit/test_viewer_palette.mjs`** — `import test from "node:test"; import assert from "node:assert/strict";` then `import { hsvToRgb, paletteColor } from "../../src/static/components/viewer/internal/palette.mjs";`. Each `test("desc", () => { assert.equal(...) })` asserts exact return strings (e.g. `assert.equal(paletteColor(0, 4), "rgb(242,24,24)")`).
- **`tests/unit/test_viewer_shapes.mjs`** — imports the shape helpers, builds a recording `makeCtx()` stub (records `calls: [{name,args}]` for `arc/fill/stroke/strokeRect/...` and stores last `props.fillStyle / props.strokeStyle / props.lineWidth` via setters), and asserts on the recorded call args + props. Reuse this `makeCtx()` pattern verbatim for the shapes-outline test.
- **`tests/test_marker_editor_feature.py`** — STATIC-SOURCE style: `ROOT = Path(__file__).parent.parent`, `ME = ROOT / "src/static/components/viewer/features/marker_editor.js"`, `_src()` reads it, tests assert with `re.search` / substring `in src`. Mirror this `_src()` + regex idiom for new feature assertions.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/static/components/viewer/internal/palette.mjs` | Add `FL_COLORS` + `labelerColor(idx)` (HSV `hsvToRgb`/`paletteColor` untouched). | Modify |
| `src/static/components/viewer/internal/shapes.mjs` | Add dark contrast outline under the circle fill. | Modify |
| `src/static/components/viewer/internal/name_label.mjs` | NEW pure geometry: `nameLabelBox(cx, cy, r, textWidth)` → `{ font, boxX, boxY, boxW, boxH, textX, textY }`. | Create |
| `src/static/components/viewer/features/marker_editor.js` | `setMarkerSize`, `setShowNames`; FL palette for primary + chips; white selected ring (drop amber + edited); dark outline (via shapes); hover-bp tracking + name rendering; hit-pad 6. | Modify |
| `src/templates/partials/card_inline_analysis_3d.html` | Add `#ia3d-overlay-show-names` checkbox to overlay controls. | Modify |
| `src/templates/partials/card_viewer_3d.html` | Add `#va3d-overlay-show-names` checkbox to overlay controls. | Modify |
| `src/static/inline_analysis_3d.js` | Wire `#ia3d-overlay-marker-size` → `setMarkerSize`; wire `#ia3d-overlay-show-names` → `setShowNames`. | Modify |
| `src/static/viewer_3d.js` | Wire `#va3d-overlay-marker-size` → `setMarkerSize`; wire `#va3d-overlay-show-names` → `setShowNames`. | Modify |
| `tests/unit/test_viewer_palette.mjs` | Extend: `labelerColor` cycling + negative-safe. | Modify |
| `tests/unit/test_viewer_shapes.mjs` | Extend: circle-filled draws the dark outline stroke. | Modify |
| `tests/unit/test_name_label.mjs` | NEW node:test for `nameLabelBox` geometry. | Create |
| `tests/test_marker_editor_feature.py` | Contract for `setMarkerSize`/`setShowNames`, FL palette/`labelerColor`, white ring, dropped amber/edited rings, hover-name + show-names, hit-pad 6. | Modify |
| `tests/test_inline_analysis_3d_ui_isolation.py` | Marker-size slider now wired (not label-only); `#ia3d-overlay-show-names` present + wired. | Modify |
| `tests/test_video_viewer_policy.py` | Keep green; add a guard that `setShowNames` wiring did not disturb the `setOverlayEnabled`/`setEditable` lockstep (already covered) — verified, no new assertion needed beyond running it. | Verify |

---

## Task 1: `palette.mjs` — add `FL_COLORS` + `labelerColor`

**Files:**
- Modify: `src/static/components/viewer/internal/palette.mjs` (append after `paletteColor`, line 25)
- Test: `tests/unit/test_viewer_palette.mjs`

- [ ] **Step 1: Write the failing test** — append to `tests/unit/test_viewer_palette.mjs`

Update the import line at the top of the file from:
```js
import { hsvToRgb, paletteColor } from "../../src/static/components/viewer/internal/palette.mjs";
```
to:
```js
import { hsvToRgb, paletteColor, FL_COLORS, labelerColor } from "../../src/static/components/viewer/internal/palette.mjs";
```

Then append these tests to the end of the file:
```js
test("FL_COLORS is the 15-hex frame-labeler palette in order", () => {
  assert.deepEqual(FL_COLORS, [
    "#f87171", "#fb923c", "#fbbf24", "#a3e635", "#34d399",
    "#22d3ee", "#818cf8", "#e879f9", "#f43f5e", "#10b981",
    "#3b82f6", "#ec4899", "#f59e0b", "#84cc16", "#06b6d4",
  ]);
  assert.equal(FL_COLORS.length, 15);
});

test("labelerColor indexes FL_COLORS and cycles every 15", () => {
  assert.equal(labelerColor(0), "#f87171");
  assert.equal(labelerColor(4), "#34d399");
  assert.equal(labelerColor(14), "#06b6d4");
  assert.equal(labelerColor(15), "#f87171"); // wraps
  assert.equal(labelerColor(16), "#fb923c");
});

test("labelerColor is negative-safe (no undefined)", () => {
  assert.equal(labelerColor(-1), "#06b6d4");  // ((-1%15)+15)%15 = 14
  assert.equal(labelerColor(-15), "#f87171"); // wraps to 0
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_palette.mjs`
Expected: FAIL — `FL_COLORS` / `labelerColor` are `undefined` (e.g. `assert.deepEqual` reports `undefined !== [...]` or "The "labelerColor" is not a function").

- [ ] **Step 3: Write minimal implementation** — append to `src/static/components/viewer/internal/palette.mjs` (after line 25):

```js

// ── Frame-labeler (Napari-inspired) fixed palette ──
// 15 hexes copied verbatim from frame_labeler_3d.js:623-627. Used for
// primary-layer markers + bp-chips so the labeler, chips, and overlay all agree
// on a bodypart's color. Comparison layers keep paletteColor (HSV) above for
// per-layer differentiation.
export const FL_COLORS = [
  "#f87171", "#fb923c", "#fbbf24", "#a3e635", "#34d399",
  "#22d3ee", "#818cf8", "#e879f9", "#f43f5e", "#10b981",
  "#3b82f6", "#ec4899", "#f59e0b", "#84cc16", "#06b6d4",
];

// idx → hex, cycling every 15. Negative-safe (double-modulo, matching hsvToRgb's
// guard) so a stray -1 index never yields undefined.
export function labelerColor(idx) {
  const n = FL_COLORS.length;
  return FL_COLORS[(((idx % n) + n) % n)];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_palette.mjs`
Expected: PASS — all palette tests (original 3 + new 3) ok, `# fail 0`.

- [ ] **Step 5: Commit**

```bash
git add src/static/components/viewer/internal/palette.mjs tests/unit/test_viewer_palette.mjs
git commit -m "$(cat <<'EOF'
feat(dlc-3d): add FL_COLORS + labelerColor to viewer palette (labeler parity)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `shapes.mjs` — dark contrast outline under the circle fill

The labeler fills the marker, then strokes a `rgba(0,0,0,0.55)` width-1.2 outline at the same radius (`frame_labeler_3d.js:1237-1239`). Add that to `drawCircleFilled` so every filled circle marker (primary + edits-only) gets the outline. (Spec B4 says "applies to all shapes (harmless for comparison shapes)"; the comparison shapes draw via `strokeRect`/stroked paths and already have their own stroke, so the outline is added only in the filled-circle path — adding a second stroke to the stroked shapes would be a visual no-op at best and is out of the minimal change. The diamond is filled; see Step 3 note.)

**Files:**
- Modify: `src/static/components/viewer/internal/shapes.mjs:4-9` (`drawCircleFilled`)
- Test: `tests/unit/test_viewer_shapes.mjs`

- [ ] **Step 1: Write the failing test** — append to `tests/unit/test_viewer_shapes.mjs`

```js
test("circle-filled strokes a dark contrast outline after the fill", () => {
  const ctx = makeCtx();
  drawShape("circle-filled", ctx, 10, 20, 5, "#f87171");
  // fill happens, then a stroke (outline) is drawn
  const order = names(ctx);
  assert.ok(order.includes("fill"), "must fill");
  assert.ok(order.includes("stroke"), "must stroke an outline");
  assert.ok(order.indexOf("fill") < order.indexOf("stroke"), "fill before outline stroke");
  // outline uses the labeler's contrast values
  assert.equal(ctx.props.strokeStyle, "rgba(0,0,0,0.55)");
  assert.equal(ctx.props.lineWidth, 1.2);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_shapes.mjs`
Expected: FAIL — `drawCircleFilled` never strokes, so `order.includes("stroke")` is false and `ctx.props.strokeStyle` is `undefined`.

- [ ] **Step 3: Write minimal implementation** — replace `drawCircleFilled` in `src/static/components/viewer/internal/shapes.mjs:4-9`:

```js
export function drawCircleFilled(ctx, x, y, r, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, 2 * Math.PI);
  ctx.fill();
  // Dark contrast outline (frame_labeler_3d.js:1238-1239) so light markers stay
  // legible on bright frames. Stroked at the same radius after the fill.
  ctx.strokeStyle = "rgba(0,0,0,0.55)";
  ctx.lineWidth = 1.2;
  ctx.stroke();
}
```

Note: this is intentionally only on the filled-circle path (primary + edits-only markers). The diamond is also filled but is a comparison-layer shape (out of scope per spec: "keep diamond/square/triangle"); leaving it unchanged avoids touching comparison aesthetics.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_shapes.mjs`
Expected: PASS — all shapes tests ok, `# fail 0`. (The existing `"circle-filled fills an arc with the color"` test still passes: it only checks `fillStyle`, the `arc` args, and that `fill` is present — the new stroke does not break it.)

- [ ] **Step 5: Commit**

```bash
git add src/static/components/viewer/internal/shapes.mjs tests/unit/test_viewer_shapes.mjs
git commit -m "$(cat <<'EOF'
feat(dlc-3d): dark contrast outline under filled circle markers (labeler parity)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `setMarkerSize` + wire BOTH cards' sliders (the headline bug)

`markerSize` is currently a `const` captured at factory init (`marker_editor.js:37`) and the cards' slider handlers only update a label (`inline_analysis_3d.js:766-771`, `viewer_3d.js:476-482`). Make `markerSize` mutable, add `setMarkerSize`, and wire both sliders. `markerRadius`'s responsive scaling (`marker_overlay.mjs:20-22`, floor 1) is untouched.

**Files:**
- Modify: `src/static/components/viewer/features/marker_editor.js:37` (`const markerSize` → `let`), public-methods block (add `setMarkerSize` near `setThreshold` ~`:647`)
- Modify: `src/static/inline_analysis_3d.js:766-771`
- Modify: `src/static/viewer_3d.js:476-482`
- Test: `tests/test_marker_editor_feature.py`, `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_marker_editor_feature.py`:
```python
def test_setMarkerSize_exists_and_mutable():
    """B1: the marker-size slider was a no-op. markerEditor must expose
    setMarkerSize(px) that updates a MUTABLE markerSize and re-renders."""
    src = _src()
    assert re.search(r"setMarkerSize\s*\(", src), "must expose setMarkerSize(px)"
    # markerSize must be reassignable (let, not const) so the setter can change it
    assert re.search(r"\blet\s+markerSize\b", src), \
        "markerSize must be `let` (mutable) so setMarkerSize can change it"
    # the setter must re-render so the change shows immediately
    i = src.find("setMarkerSize")
    body = src[i:i + 200]
    assert "renderAll()" in body or "renderTile" in body or "onFrame(" in body, \
        "setMarkerSize must re-render after changing the size"
```

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:
```python
def test_inline_marker_size_slider_wired_to_setMarkerSize():
    """B1 (2026-05-25): the inline marker-size slider must drive
    markerEditor.setMarkerSize (it was previously a label-only no-op)."""
    js = JS.read_text()
    i = js.find('$("ia3d-overlay-marker-size")')
    assert i > 0, "ia3d-overlay-marker-size slider not wired"
    body = js[i:i + 400]
    assert "setMarkerSize(" in body, \
        "marker-size slider handler must call markerEditor.setMarkerSize"
    # the old 'no setMarkerSize API → update the label only' comment must be gone
    assert "markerEditor has no setMarkerSize API" not in js, \
        "stale no-op comment must be removed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py::test_setMarkerSize_exists_and_mutable tests/test_inline_analysis_3d_ui_isolation.py::test_inline_marker_size_slider_wired_to_setMarkerSize -q`
Expected: FAIL — `setMarkerSize` not found; `markerSize` is `const`; the stale comment is still present.

- [ ] **Step 3a: Make `markerSize` mutable** — `src/static/components/viewer/features/marker_editor.js:37`

Change:
```js
  const markerSize = config.markerSize || 6;
```
to:
```js
  let markerSize = config.markerSize || 6;
```

- [ ] **Step 3b: Add the setter** — `src/static/components/viewer/features/marker_editor.js`, in the returned public-methods object, immediately after `setThreshold(v) { ... },` (the block ending at line 653):

```js

    // Marker render size in video px (responsive scaling stays in markerRadius).
    // Wired to each card's marker-size slider (fixes the prior no-op). Re-renders
    // so the change shows immediately without a frame step.
    setMarkerSize(px) {
      const n = Number(px);
      if (Number.isFinite(n) && n > 0) markerSize = n;
      renderAll();
    },
```

- [ ] **Step 3c: Wire the inline slider** — replace `src/static/inline_analysis_3d.js:766-771`:

```js
  // Marker size → markerEditor.setMarkerSize (re-renders) + label.
  const ms = $("ia3d-overlay-marker-size");
  ms?.addEventListener("input", () => {
    _markerEditor?.setMarkerSize(parseInt(ms.value, 10));
    const lbl = $("ia3d-overlay-marker-size-val");
    if (lbl) lbl.textContent = ms.value;
  });
```

- [ ] **Step 3d: Wire the View-Analyzed slider** — replace `src/static/viewer_3d.js:476-482`:

```js
  // Marker size → markerEditor.setMarkerSize (re-renders) + label.
  const ms = $("va3d-overlay-marker-size");
  ms?.addEventListener("input", () => {
    _markerEditor?.setMarkerSize(parseInt(ms.value, 10));
    const lbl = $("va3d-overlay-marker-size-val");
    if (lbl) lbl.textContent = ms.value;
  });
```

- [ ] **Step 4: Run tests to verify they pass + policy stays green**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest \
  tests/test_marker_editor_feature.py \
  tests/test_inline_analysis_3d_ui_isolation.py \
  tests/test_video_viewer_policy.py -q
```
Expected: PASS — all green, `# fail 0`. In particular `test_video_viewer_policy.py::test_viewer_3d_mirrors_setEditable_to_overlay_enabled_state` still passes (we only added a `setMarkerSize` call, not a `setOverlayEnabled`/`setEditable` call).

- [ ] **Step 5: Commit**

```bash
git add src/static/components/viewer/features/marker_editor.js src/static/inline_analysis_3d.js src/static/viewer_3d.js tests/test_marker_editor_feature.py tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "$(cat <<'EOF'
feat(dlc-3d): add markerEditor.setMarkerSize + wire both cards' sliders (fix no-op)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: FL palette for primary markers + chips, white selected ring, drop edited ring, hit-pad 6

This is the core aesthetic swap inside `marker_editor.js`. It (a) imports `labelerColor`, (b) colors **primary-layer** markers + edits-only markers + bp-chips via `labelerColor(bodypartIndex)` while keeping `paletteColor` for **comparison** layers, (c) replaces the amber selected ring + white edited ring with a single white `rgba(255,255,255,0.85)` ring at `r+3.5` width 2, and (d) changes the three `hitTest` pads from 8 → 6.

**Files:**
- Modify: `src/static/components/viewer/features/marker_editor.js` — import (`:30`), `renderTile` pose loop (`:221-226`), edits-only block (`:238-240`), `rebuildBpChips` chip color (`:280`), three `hitTest` call sites (`:337-338`, `:446`, `:466`)
- Test: `tests/test_marker_editor_feature.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_marker_editor_feature.py`

```python
def test_imports_labelerColor():
    """B2: primary markers + chips use the FL palette via labelerColor."""
    src = _src()
    assert re.search(
        r"import\s*\{[^}]*\blabelerColor\b[^}]*\}\s*from\s*[\"'][^\"']*palette\.mjs[\"']", src), \
        "must import labelerColor from internal/palette.mjs"


def test_primary_markers_use_labelerColor_chips_too():
    """B2: the primary layer + bp-chips color by bodypart index via labelerColor;
    comparison layers keep paletteColor (HSV)."""
    src = _src()
    # both helpers are present (comparison layers still use paletteColor)
    assert "labelerColor(" in src, "primary/chips must color via labelerColor"
    assert "paletteColor(" in src, "comparison layers must keep paletteColor"


def test_b3_selected_ring_white_no_amber_no_edited():
    """B3: selected ring is white rgba(255,255,255,0.85) at r+3.5 width 2; the
    amber #facc15 ring and the white edited ring are dropped entirely."""
    src = _src()
    assert "rgba(255,255,255,0.85)" in src, "selected ring must be white rgba(255,255,255,0.85)"
    assert "r + 3.5" in src, "selected ring offset must be r + 3.5"
    assert "#facc15" not in src, "amber selected ring must be dropped"
    # the white edited ring used 'r + 3' with '#fff' width 1.5 — that exact draw must be gone
    assert '"#fff", 1.5' not in src, "white edited ring must be dropped"


def test_b7_hit_pad_is_6():
    """B7: hit-test pad is 6 (labeler parity) at all markerEditor hitTest sites."""
    src = _src()
    # no hitTest call may pass pad 8 anymore
    assert not re.search(r"hitTest\([^)]*,\s*8\s*\)", src), \
        "hitTest pad must be 6, not 8, at every call site"
    # at least one explicit pad-6 call (the others may rely on it too)
    assert re.search(r"hitTest\([^)]*,\s*6\s*\)", src), \
        "hitTest must be called with pad 6"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py -q -k "labelerColor or selected_ring or hit_pad or chips"`
Expected: FAIL — `labelerColor` not imported; `rgba(255,255,255,0.85)` / `r + 3.5` absent; `#facc15` and `"#fff", 1.5` still present; `hitTest(..., 8)` still present.

- [ ] **Step 3a: Import `labelerColor`** — `src/static/components/viewer/features/marker_editor.js:30`

Change:
```js
import { paletteColor } from "../internal/palette.mjs";
```
to:
```js
import { paletteColor, labelerColor } from "../internal/palette.mjs";
```

- [ ] **Step 3b: Primary markers FL color + white ring (drop amber + edited)** — replace the pose-loop body in `renderTile`, `src/static/components/viewer/features/marker_editor.js:219-226`:

Current:
```js
        const cx = Math.round(px * scale.sx);
        const cy = Math.round(py * scale.sy);
        const color = paletteColor(pose.color_idx, cached.n_bodyparts);
        drawShape(shape, ctx, cx, cy, r, color);
        if (isPrimaryLayer && editableTile && edited) ring(ctx, cx, cy, r + 3, "#fff", 1.5);
        if (isPrimaryLayer && editableTile && pose.bp === selectedBp) {
          ring(ctx, cx, cy, r + (edited ? 6 : 3), "#facc15", 2);
        }
```

Replace with:
```js
        const cx = Math.round(px * scale.sx);
        const cy = Math.round(py * scale.sy);
        // Primary layer + chips share the FL palette (labelerColor by bodypart
        // index); comparison layers keep paletteColor (HSV) for differentiation.
        const bpIdx = allBodyParts.indexOf(pose.bp);
        const color = isPrimaryLayer
          ? labelerColor(bpIdx >= 0 ? bpIdx : 0)
          : paletteColor(pose.color_idx, cached.n_bodyparts);
        drawShape(shape, ctx, cx, cy, r, color);
        // White selected ring (frame_labeler_3d.js:1234-1235). The amber selected
        // ring + the white "edited" ring are dropped (exact labeler match).
        if (isPrimaryLayer && editableTile && pose.bp === selectedBp) {
          ring(ctx, cx, cy, r + 3.5, "rgba(255,255,255,0.85)", 2);
        }
```

- [ ] **Step 3c: Edits-only markers FL color + white ring (drop edited ring)** — replace the edits-only block in `renderTile`, `src/static/components/viewer/features/marker_editor.js:237-240`:

Current:
```js
          const ci = layer.bodyparts ? layer.bodyparts.indexOf(bp) : -1;
          drawShape(shape, ctx, ex, ey, r, paletteColor(ci >= 0 ? ci : 0, cached.n_bodyparts));
          ring(ctx, ex, ey, r + 3, "#fff", 1.5);
          if (bp === selectedBp) ring(ctx, ex, ey, r + 6, "#facc15", 2);
```

Replace with:
```js
          // Edits-only markers (primary layer) share the FL palette by bodypart
          // index. White selected ring only; no amber, no edited ring.
          const ci = allBodyParts.indexOf(bp);
          drawShape(shape, ctx, ex, ey, r, labelerColor(ci >= 0 ? ci : 0));
          if (bp === selectedBp) ring(ctx, ex, ey, r + 3.5, "rgba(255,255,255,0.85)", 2);
```

- [ ] **Step 3d: Chip color via `labelerColor`** — `src/static/components/viewer/features/marker_editor.js:280`

Change:
```js
      chip.style.setProperty("--bp-color", paletteColor(idx, allBodyParts.length));
```
to:
```js
      chip.style.setProperty("--bp-color", labelerColor(idx));
```

- [ ] **Step 3e: Hit-pad 6 at all three sites**

`src/static/components/viewer/features/marker_editor.js:337-338` (in `updateHoverCursor`):
```js
    const hit = hitTest(hitPoses(tile.cam), cx, cy, tileScale(tile), markerSize,
      frameEditsOf(editsFor(tile.cam), currentFrame), 6);
```
`src/static/components/viewer/features/marker_editor.js:446` (mousedown):
```js
      const hit = hitTest(hitPoses(cam), cx, cy, tileScale(tile), markerSize, frameEditsOf(editsFor(cam), currentFrame), 6);
```
`src/static/components/viewer/features/marker_editor.js:466` (click):
```js
      const hit = hitTest(hitPoses(cam), cx, cy, tileScale(tile), markerSize, frameEditsOf(editsFor(cam), currentFrame), 6);
```

- [ ] **Step 4: Run tests to verify they pass + full feature contract + policy**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest \
  tests/test_marker_editor_feature.py \
  tests/test_video_viewer_policy.py -q
```
Expected: PASS — all green. The existing `test_b4_b5_hit_select_and_hover_cursor` (checks `selectBp(hit)` + the cursor strings) still passes since we kept the hit-test/select logic and the cursor strings.

- [ ] **Step 5: Commit**

```bash
git add src/static/components/viewer/features/marker_editor.js tests/test_marker_editor_feature.py
git commit -m "$(cat <<'EOF'
feat(dlc-3d): FL palette for primary markers+chips, white selected ring, drop amber/edited rings, hit-pad 6

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5a: `name_label.mjs` — pure label-box geometry + node test

Extract the name-label box geometry (position + rect + font) so it is unit-testable and reused by `renderTile`. Values copied verbatim from `frame_labeler_3d.js:1243-1248`.

**Files:**
- Create: `src/static/components/viewer/internal/name_label.mjs`
- Create: `tests/unit/test_name_label.mjs`

- [ ] **Step 1: Write the failing test** — create `tests/unit/test_name_label.mjs`

```js
import test from "node:test";
import assert from "node:assert/strict";
import { NAME_LABEL_FONT, nameLabelBox } from "../../src/static/components/viewer/internal/name_label.mjs";

test("NAME_LABEL_FONT matches the frame-labeler font", () => {
  assert.equal(NAME_LABEL_FONT, "bold 11px 'JetBrains Mono', monospace");
});

test("nameLabelBox positions the box at cx+r+2 / cy-7 with measured width+6 x 14", () => {
  // cx=100, cy=50, r=6, textWidth=30
  const b = nameLabelBox(100, 50, 6, 30);
  assert.equal(b.boxX, 108);  // cx + r + 2
  assert.equal(b.boxY, 43);   // cy - 7
  assert.equal(b.boxW, 36);   // textWidth + 6
  assert.equal(b.boxH, 14);
  assert.equal(b.textX, 111); // cx + r + 5
  assert.equal(b.textY, 54);  // cy + 4
  assert.equal(b.font, "bold 11px 'JetBrains Mono', monospace");
});

test("nameLabelBox tracks radius (bigger r pushes the box right)", () => {
  const b = nameLabelBox(0, 0, 12, 10);
  assert.equal(b.boxX, 14);   // 0 + 12 + 2
  assert.equal(b.textX, 17);  // 0 + 12 + 5
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_name_label.mjs`
Expected: FAIL — module not found / `nameLabelBox is not a function`.

- [ ] **Step 3: Write minimal implementation** — create `src/static/components/viewer/internal/name_label.mjs`

```js
// Pure geometry for the hover / show-names marker-name label box.
// Values copied verbatim from frame_labeler_3d.js:1243-1248 so the shared
// markerEditor's name label matches the frame labeler exactly.

export const NAME_LABEL_FONT = "bold 11px 'JetBrains Mono', monospace";

// Given a marker center (cx,cy), radius r, and the measured text width, return
// the label-box rect + text anchor. The caller sets ctx.font = NAME_LABEL_FONT,
// measures the text, fills the box (rgba(12,13,16,.65)), then fills the text in
// the marker's color.
export function nameLabelBox(cx, cy, r, textWidth) {
  return {
    font: NAME_LABEL_FONT,
    boxX: cx + r + 2,
    boxY: cy - 7,
    boxW: textWidth + 6,
    boxH: 14,
    textX: cx + r + 5,
    textY: cy + 4,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_name_label.mjs`
Expected: PASS — 3 tests ok, `# fail 0`.

- [ ] **Step 5: Commit**

```bash
git add src/static/components/viewer/internal/name_label.mjs tests/unit/test_name_label.mjs
git commit -m "$(cat <<'EOF'
feat(dlc-3d): add name_label.mjs pure label-box geometry (labeler parity)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5b: markerEditor hover-bp tracking + `setShowNames` + name rendering

Add `hoverBp` tracking in `updateHoverCursor` (re-render on change), a `setShowNames(bool)` method + `showNames` state, and a name-label draw in `renderTile` (when a marker is the hovered bp OR show-names is on). Uses `name_label.mjs` for geometry.

**Files:**
- Modify: `src/static/components/viewer/features/marker_editor.js` — import (`:31`), new state near `:49`, name draw in `renderTile` pose loop, `updateHoverCursor` (`:334-340`), public methods block, `setShowNames`
- Test: `tests/test_marker_editor_feature.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_marker_editor_feature.py`

```python
def test_b5_b6_hover_name_and_show_names():
    """B5/B6: markerEditor tracks a hovered bp, exposes setShowNames(bool), and
    renders a marker's name when hovered OR when show-names is on, using
    name_label.mjs geometry + the labeler font/bg."""
    src = _src()
    # imports the pure label-box geometry
    assert re.search(
        r"import\s*\{[^}]*\bnameLabelBox\b[^}]*\}\s*from\s*[\"'][^\"']*name_label\.mjs[\"']", src), \
        "must import nameLabelBox from internal/name_label.mjs"
    # public setter + state
    assert re.search(r"setShowNames\s*\(", src), "must expose setShowNames(bool)"
    assert "showNames" in src, "must track showNames state"
    # hover-bp tracking
    assert "hoverBp" in src, "must track the hovered bodypart (hoverBp)"
    # the render condition: hovered OR show-names
    assert re.search(r"showNames\s*\|\|\s*\w*\s*===\s*hoverBp", src) or \
        re.search(r"hoverBp\s*===|===\s*hoverBp", src), \
        "name renders when bp === hoverBp or showNames is on"
    # the labeler label-box bg color
    assert "rgba(12,13,16,.65)" in src, "name-label box bg must match the labeler"
    # uses the geometry helper + fillText
    assert "nameLabelBox(" in src and "fillText(" in src, \
        "must draw the name via nameLabelBox geometry + fillText"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py::test_b5_b6_hover_name_and_show_names -q`
Expected: FAIL — `nameLabelBox` not imported, `setShowNames`/`showNames`/`hoverBp` absent, `rgba(12,13,16,.65)` absent.

- [ ] **Step 3a: Import the geometry helper** — `src/static/components/viewer/features/marker_editor.js:31`

Change:
```js
import { drawShape, shapeForLayer } from "../internal/shapes.mjs";
```
to add a second import line right after it:
```js
import { drawShape, shapeForLayer } from "../internal/shapes.mjs";
import { nameLabelBox } from "../internal/name_label.mjs";
```

- [ ] **Step 3b: Add state** — `src/static/components/viewer/features/marker_editor.js`, after `let selectedBp = null;` (line 49):

```js
  let selectedBp = null;
  let showNames = false;     // B6: when true, draw every visible marker's name
  let hoverBp = null;        // B5: bodypart under the cursor on the focused tile
```

- [ ] **Step 3c: Draw the name in `renderTile`** — in the pose loop, after the selected-ring block added in Task 4 (the `if (isPrimaryLayer && editableTile && pose.bp === selectedBp) { ring(...) }`), add a name-draw for primary markers. Insert right after that block (within the `for (const pose of cached.poses)` loop):

```js
        // B5/B6: name label beside the dot when hovered or show-names is on
        // (primary layer only; geometry from name_label.mjs, values match the
        // frame labeler). `color` is the marker's FL color from above.
        if (isPrimaryLayer && (showNames || pose.bp === hoverBp)) {
          ctx.font = nameLabelBox(0, 0, 0, 0).font; // NAME_LABEL_FONT
          const box = nameLabelBox(cx, cy, r, ctx.measureText(pose.bp).width);
          ctx.fillStyle = "rgba(12,13,16,.65)";
          ctx.fillRect(box.boxX, box.boxY, box.boxW, box.boxH);
          ctx.fillStyle = color;
          ctx.fillText(pose.bp, box.textX, box.textY);
        }
```

- [ ] **Step 3d: Track `hoverBp` in `updateHoverCursor`** — replace `src/static/components/viewer/features/marker_editor.js:334-340` (`updateHoverCursor`):

Current:
```js
  function updateHoverCursor(tile, cx, cy) {
    if (!tile || !tile.canvasEl) return;
    if (tile.cam !== focusedCam || !isEditableCam(tile.cam)) { tile.canvasEl.style.cursor = "default"; return; }
    const hit = hitTest(hitPoses(tile.cam), cx, cy, tileScale(tile), markerSize,
      frameEditsOf(editsFor(tile.cam), currentFrame), 6);
    tile.canvasEl.style.cursor = hit ? "pointer" : (selectedBp ? "crosshair" : "default");
  }
```

Replace with (preserves the cursor logic; adds hover-bp tracking + re-render on change):
```js
  function updateHoverCursor(tile, cx, cy) {
    if (!tile || !tile.canvasEl) return;
    if (tile.cam !== focusedCam || !isEditableCam(tile.cam)) {
      tile.canvasEl.style.cursor = "default";
      if (hoverBp !== null) { hoverBp = null; renderTile(tile, currentFrame); }
      return;
    }
    const hit = hitTest(hitPoses(tile.cam), cx, cy, tileScale(tile), markerSize,
      frameEditsOf(editsFor(tile.cam), currentFrame), 6);
    if (hit !== hoverBp) { hoverBp = hit; renderTile(tile, currentFrame); }
    tile.canvasEl.style.cursor = hit ? "pointer" : (selectedBp ? "crosshair" : "default");
  }
```

- [ ] **Step 3e: Add `setShowNames`** — `src/static/components/viewer/features/marker_editor.js`, in the public-methods object after `setMarkerSize` (added in Task 3):

```js

    // B6: show every visible marker's name when on; on hover only when off.
    setShowNames(on) {
      showNames = !!on;
      renderAll();
    },
```

- [ ] **Step 4: Run tests to verify they pass + full feature contract + policy**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest \
  tests/test_marker_editor_feature.py \
  tests/test_video_viewer_policy.py -q
```
Expected: PASS — all green, `# fail 0`.

- [ ] **Step 5: Commit**

```bash
git add src/static/components/viewer/features/marker_editor.js tests/test_marker_editor_feature.py
git commit -m "$(cat <<'EOF'
feat(dlc-3d): markerEditor hover-name + setShowNames (labeler parity)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5c: "Show names" checkbox in both cards + wire `setShowNames`

Add a `Show names` checkbox to each card's overlay-controls block (beside Marker size) and wire it to `setShowNames`. Template edits require a `docker compose restart dlc-3d` before the live step.

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html:164-169` (Marker-size label block)
- Modify: `src/templates/partials/card_viewer_3d.html:156-161`
- Modify: `src/static/inline_analysis_3d.js` (overlay-chrome wiring, near the marker-size handler)
- Modify: `src/static/viewer_3d.js` (overlay-chrome wiring, near the marker-size handler)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`, `tests/test_video_viewer_policy.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:
```python
def test_show_names_checkbox_present_and_wired():
    """B6 consumer: a 'Show names' checkbox sits in the overlay controls and
    drives markerEditor.setShowNames."""
    html = CARD.read_text()
    assert 'id="ia3d-overlay-show-names"' in html, "Show-names checkbox id missing"
    # it lives inside the overlay controls block
    ctrls = html.index('id="ia3d-overlay-controls"')
    chk = html.index('id="ia3d-overlay-show-names"')
    assert chk > ctrls, "Show-names checkbox must sit inside #ia3d-overlay-controls"
    js = JS.read_text()
    i = js.find('$("ia3d-overlay-show-names")')
    assert i > 0, "Show-names checkbox not wired in JS"
    assert "setShowNames(" in js[i:i + 300], \
        "Show-names checkbox handler must call markerEditor.setShowNames"
```

Append to `tests/test_video_viewer_policy.py` (the View-Analyzed consumer assertions — there is no `va3d` UI-isolation file, so this lives with the policy/lockstep guard):
```python
def test_viewer_3d_show_names_checkbox_present_and_wired():
    """B6 consumer (View Analyzed): a 'Show names' checkbox in the overlay controls
    drives markerEditor.setShowNames — WITHOUT disturbing the setOverlayEnabled/
    setEditable lockstep (setShowNames is a distinct method)."""
    html = (ROOT / "src" / "templates" / "partials" / "card_viewer_3d.html").read_text()
    assert 'id="va3d-overlay-show-names"' in html, "Show-names checkbox id missing"
    ctrls = html.index('id="va3d-overlay-controls"')
    chk = html.index('id="va3d-overlay-show-names"')
    assert chk > ctrls, "Show-names checkbox must sit inside #va3d-overlay-controls"
    js = (ROOT / "src" / "static" / "viewer_3d.js").read_text()
    i = js.find('$("va3d-overlay-show-names")')
    assert i > 0, "Show-names checkbox not wired in JS"
    assert "setShowNames(" in js[i:i + 300], \
        "Show-names checkbox handler must call markerEditor.setShowNames"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest \
  tests/test_inline_analysis_3d_ui_isolation.py::test_show_names_checkbox_present_and_wired \
  tests/test_video_viewer_policy.py::test_viewer_3d_show_names_checkbox_present_and_wired -q
```
Expected: FAIL — checkbox ids absent in both templates; handlers absent in both JS files.

- [ ] **Step 3a: Inline card checkbox** — `src/templates/partials/card_inline_analysis_3d.html`, inside the same flex row as Marker size. Replace lines 164-169 (the Marker-size `<label>...</label>`) with the same label followed by a Show-names label:

Current:
```html
              <label style="display:flex;align-items:center;gap:.4rem;font-size:.78rem;color:var(--text-dim);white-space:nowrap">
                Marker size
                <input type="range" id="ia3d-overlay-marker-size" min="1" max="30" step="1" value="6"
                  style="width:70px;accent-color:var(--accent)">
                <span id="ia3d-overlay-marker-size-val" style="font-family:var(--mono);font-size:.75rem;min-width:1.8rem">6</span>px
              </label>
```

Replace with:
```html
              <label style="display:flex;align-items:center;gap:.4rem;font-size:.78rem;color:var(--text-dim);white-space:nowrap">
                Marker size
                <input type="range" id="ia3d-overlay-marker-size" min="1" max="30" step="1" value="6"
                  style="width:70px;accent-color:var(--accent)">
                <span id="ia3d-overlay-marker-size-val" style="font-family:var(--mono);font-size:.75rem;min-width:1.8rem">6</span>px
              </label>
              <label style="display:flex;align-items:center;gap:.4rem;font-size:.78rem;color:var(--text-dim);white-space:nowrap">
                <input type="checkbox" id="ia3d-overlay-show-names" style="accent-color:var(--accent)">
                Show names
              </label>
```

- [ ] **Step 3b: View-Analyzed card checkbox** — `src/templates/partials/card_viewer_3d.html`, replace lines 156-161 (the Marker-size `<label>...</label>`):

Current:
```html
              <label style="display:flex;align-items:center;gap:.4rem;font-size:.78rem;color:var(--text-dim);white-space:nowrap">
                Marker size
                <input type="range" id="va3d-overlay-marker-size" min="1" max="30" step="1" value="6"
                  style="width:70px;accent-color:var(--accent)">
                <span id="va3d-overlay-marker-size-val" style="font-family:var(--mono);font-size:.75rem;min-width:1.8rem">6</span>px
              </label>
```

Replace with:
```html
              <label style="display:flex;align-items:center;gap:.4rem;font-size:.78rem;color:var(--text-dim);white-space:nowrap">
                Marker size
                <input type="range" id="va3d-overlay-marker-size" min="1" max="30" step="1" value="6"
                  style="width:70px;accent-color:var(--accent)">
                <span id="va3d-overlay-marker-size-val" style="font-family:var(--mono);font-size:.75rem;min-width:1.8rem">6</span>px
              </label>
              <label style="display:flex;align-items:center;gap:.4rem;font-size:.78rem;color:var(--text-dim);white-space:nowrap">
                <input type="checkbox" id="va3d-overlay-show-names" style="accent-color:var(--accent)">
                Show names
              </label>
```

- [ ] **Step 3c: Wire inline** — `src/static/inline_analysis_3d.js`, immediately after the marker-size handler block (the `ms?.addEventListener(...)` updated in Task 3, before the Show-all/Hide-all no-op lines at `:773-775`):

```js
  // Show names → markerEditor.setShowNames (all names vs hover-only).
  const showNames = $("ia3d-overlay-show-names");
  showNames?.addEventListener("change", () => _markerEditor?.setShowNames(!!showNames.checked));
```

- [ ] **Step 3d: Wire View Analyzed** — `src/static/viewer_3d.js`, immediately after the marker-size handler block (updated in Task 3, before the Show-all/Hide-all no-op lines at `:487-488`):

```js
  // Show names → markerEditor.setShowNames (all names vs hover-only).
  const showNames = $("va3d-overlay-show-names");
  showNames?.addEventListener("change", () => _markerEditor?.setShowNames(!!showNames.checked));
```

- [ ] **Step 4a: Restart the module so template edits take effect**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart dlc-3d`
Expected: `dlc-3d` container restarts (the new `.html` is served).

- [ ] **Step 4b: Run tests to verify they pass + policy lockstep intact**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest \
  tests/test_inline_analysis_3d_ui_isolation.py \
  tests/test_video_viewer_policy.py -q
```
Expected: PASS — all green. Crucially `test_viewer_3d_mirrors_setEditable_to_overlay_enabled_state` still passes (we added a `setShowNames` handler, not a new `setOverlayEnabled`/`setEditable` pair).

- [ ] **Step 5: Commit**

```bash
git add src/templates/partials/card_inline_analysis_3d.html src/templates/partials/card_viewer_3d.html src/static/inline_analysis_3d.js src/static/viewer_3d.js tests/test_inline_analysis_3d_ui_isolation.py tests/test_video_viewer_policy.py
git commit -m "$(cat <<'EOF'
feat(dlc-3d): add Show-names overlay checkbox + wire setShowNames (both cards)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Holistic live verification (both cards) + View-Analyzed regression

Read-only Playwright verification. No data-layer change; **never** click Save Adjustments / Add range / Extract / Finalize / Delete. Dragging sliders, hovering, and toggling the show-names checkbox do not persist.

**Files:** none (verification only).

- [ ] **Step 1: Run the full test suite (regression gate)**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest \
  tests/test_marker_editor_feature.py \
  tests/test_inline_analysis_3d_ui_isolation.py \
  tests/test_video_viewer_policy.py -q && \
node --test tests/unit/test_viewer_palette.mjs tests/unit/test_viewer_shapes.mjs tests/unit/test_name_label.mjs
```
Expected: pytest `# fail 0`; node `# fail 0`.

- [ ] **Step 2: Confirm module is up + restarted for templates**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose ps dlc-3d`
Expected: `dlc-3d` is `Up`. (If templates changed since the last restart, run `docker compose restart dlc-3d` first.)

- [ ] **Step 3: Live verify the inline-3D card (cam0, posed video)**

Drive Playwright (Python) read-only:
1. `GET http://localhost:5000/?token=deeplabcut` to auth.
2. Open the **Inline Analysis 3D** card; load project **DREADD-Ali** / video **khoai-lang-1** / **cam0**; turn the overlay on so markers render.
3. **Marker size:** drag `#ia3d-overlay-marker-size` from 6 → ~20 and confirm the rendered dots grow (the headline bug). Drag back down → they shrink. Confirm `#ia3d-overlay-marker-size-val` updates.
4. **Palette:** confirm primary markers use the FL_COLORS hexes and **match the bp-chip dot colors** for the same bodypart (e.g. bodypart index 0 → `#f87171`, index 4 → `#34d399`). Confirm a **dark outline** rings each filled dot.
5. **Selected ring:** select a bodypart chip and confirm the selected marker shows a **white** ring (`rgba(255,255,255,0.85)`), not amber, and edited markers no longer get a separate white ring.
6. **Hover name:** hover a marker (no show-names) → its name pops in a dark box beside the dot, text in the marker's color. Move away → it disappears.
7. **Show names:** check `#ia3d-overlay-show-names` → all visible markers' names render; uncheck → back to hover-only.

Expected: all of the above behave as described; take a screenshot of the resized + named markers for the report.

- [ ] **Step 4: Live verify View Analyzed (the shared-feature regression guard)**

1. Open the **View Analyzed** card; load the same posed video / cam0; toggle the overlay **on** (this also arms editing via the `setEditable(on)` mirror).
2. Confirm markers render with the **new palette + white selected ring + dark outline** (same as inline).
3. Drag `#va3d-overlay-marker-size` → markers resize. Check `#va3d-overlay-show-names` → names show/hide.
4. Confirm hovering a marker shows its name; selecting a bodypart shows the white ring.
5. Confirm editing still works while the overlay is on: select a chip and verify the crosshair cursor + that a click would place (do **not** save). Toggle overlay **off** → markers + editing both stop (lockstep intact).

Expected: View Analyzed looks identical to inline (shared feature) and its editing/overlay lockstep is unchanged. Screenshot for the report.

- [ ] **Step 5: Commit (verification notes only, if any docs updated)**

No code change in this task. If a verification note file is updated, commit it; otherwise skip. (Do not create a report `.md`.)

---

## Self-Review

**1. Spec coverage** — every spec section maps to a task:

| Spec | Task |
|---|---|
| Files: `palette.mjs` `FL_COLORS`+`labelerColor` | Task 1 |
| Files: `shapes.mjs` dark outline | Task 2 |
| Files: `name_label.mjs` (create) | Task 5a |
| Files: `marker_editor.js` `setMarkerSize`/`setShowNames`, hover, white ring, FL palette, hit-pad 6 | Tasks 3, 4, 5b |
| Files: both card templates "Show names" checkbox | Task 5c |
| Files: both consumers wire marker-size + show-names | Tasks 3 (size), 5c (names) |
| Tests: `test_viewer_palette.mjs` labelerColor | Task 1 |
| Tests: `test_name_label.mjs` geometry | Task 5a |
| Tests: `test_marker_editor_feature.py` contract | Tasks 3, 4, 5b |
| Tests: UI-isolation both cards | Tasks 3, 5c |
| Tests: `test_video_viewer_policy.py` green | Tasks 3, 4, 5b, 5c (run) |
| B1 marker size | Task 3 |
| B2 FL palette | Tasks 1, 4 |
| B3 white ring, drop amber + edited | Task 4 |
| B4 contrast outline | Task 2 |
| B5 hover-to-show-name | Tasks 5a, 5b |
| B6 show/hide names toggle | Tasks 5b, 5c |
| B7 hit pad 6 | Task 4 |
| View Analyzed regression guard | Task 6 (+ policy lockstep guard untouched throughout) |
| Live verify (read-only, both cards) | Task 6 |

No gaps.

**2. Placeholder scan** — no "TBD/TODO/implement later/etc." The View-Analyzed "needs setMarkerSize" TODO comment in `viewer_3d.js:477` is removed by Task 3's replacement. All code steps contain complete code; all test steps contain complete tests; all commands give expected output.

**3. Name / value consistency** —
- `labelerColor` / `FL_COLORS` / `setMarkerSize` / `setShowNames` / `setEditable` / `setOverlayEnabled` / `nameLabelBox` / `NAME_LABEL_FONT` / `hoverBp` / `showNames` / `markerSize` spelled consistently across all tasks.
- Exact values consistent everywhere: selected ring `rgba(255,255,255,0.85)` at `r + 3.5` width `2`; outline `rgba(0,0,0,0.55)` width `1.2`; name box bg `rgba(12,13,16,.65)`, rect `(cx+r+2, cy-7, textWidth+6, 14)`, text `(cx+r+5, cy+4)`, font `"bold 11px 'JetBrains Mono', monospace"`; dropped amber `#facc15`; dropped edited ring `"#fff", 1.5`; hit pad `6`; FL_COLORS 15 hexes in order. These match the spec's "Exact values" block and `frame_labeler_3d.js` line citations.
- `markerSize` flipped from `const` (line 37) to `let` once (Task 3) and consumed unchanged everywhere else.
- Ordering safety: Task 1 (palette) → Task 2 (shapes) are pure additive helpers (nothing imports them yet, so no breakage). Task 3 adds `setMarkerSize` (new method + wiring; no aesthetic change) — safe. Task 4 swaps palette/ring + pad (depends on Task 1's `labelerColor`; imports it). Task 5a adds `name_label.mjs` (pure, unused) → 5b imports it and adds rendering → 5c adds the checkbox + template restart. Every commit leaves all tests green and View Analyzed working.

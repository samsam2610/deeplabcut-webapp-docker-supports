# Epipolar Line Colour and Edge Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Colour each epipolar line to match its bodypart's marker, label it at the frame edge with the bodypart name staggered along the line, and hide lines for bodyparts hidden in the marker overlay.

**Architecture:** Colour and visibility are read from the bp-chips that `markerEditor` already renders, so there is one source of truth and no change to the shared viewer library. Label placement is pure geometry in a new `.mjs` module, unit-tested with `node --test`. The drawing code composes the two.

**Tech Stack:** Vanilla ES modules, canvas 2D, `node --test` for pure logic, pytest for wiring assertions.

## Global Constraints

- **This card is LIVE and in use.** `dlc-3D/src/static/` is a Docker bind mount, so every commit is served to users on their next browser reload. Leave the file working at every commit, and run the syntax check each time.
- **Never modify the live original card:** `src/templates/partials/card_inline_analysis_3d.html`, `src/static/inline_analysis_3d.js`, `src/static/inline_analysis_3d.css`.
- **Never modify the shared viewer library** under `src/static/components/viewer/`. It is loaded by the original card too. Import from it; do not edit it.
- **Never modify anything under `src/dlc_3d_bp/`.** No backend change is needed; this is a pure frontend feature.
- **Every chip query MUST be rooted at `#ia3dr-bp-chips`.** `.vv-bp-chip` is created by the shared `markerEditor`, so both cards' chips live in the same document. A document-wide query would silently read the *other* card's colours and visibility, and would only misbehave when both cards are open.
- Keep the `ia3dr-` namespace. No new `ia3d-` (single r) identifiers.
- **Do NOT restart, rebuild or stop any container, and run NO docker command.** Frontend changes go live on browser reload. Deployment is Task 3, done by someone else.
- Ten tests already fail on this host for unrelated pre-existing reasons (numpy 2.x `isinstance(np.int64, int)`, absent playwright browser, ffmpeg-dependent LP tests). Not yours; do not fix them, do not count them as regressions.
- Run pytest from `dlc-3D/`; run `node --test` from `dlc-3D/` too.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/static/internal/epiline_label.mjs` | **New.** Pure label-anchor geometry. No DOM, no canvas. |
| `tests/unit/test_epiline_label.mjs` | **New.** Real assertions on that geometry, via `node --test`. |
| `src/static/inline_analysis_3d_reprojection.js` | Colour + visibility from chips; draw the coloured line and its label. |
| `tests/test_reproj_panel_wiring.py` | Wiring assertions, including the cross-card guard. |

---

### Task 1: `labelAnchor` pure geometry

**Files:**
- Create: `src/static/internal/epiline_label.mjs`
- Test: `tests/unit/test_epiline_label.mjs`

**Interfaces:**
- Consumes: nothing.
- Produces: `labelAnchor(segment, order, step) -> {x, y, ux, uy} | null`, where `segment` is `[[x1,y1],[x2,y2]]` in video-pixel coordinates, `order` is a non-negative integer, and `step` is pixels. Returns `null` for a degenerate or non-finite segment.

**Why a separate module:** the panel's other tests assert only that strings appear in the source, a convention that already allowed a completely unwired overlay to ship in this project. Geometry is pure, so it can carry real assertions — and it is the part most likely to be subtly wrong.

- [ ] **Step 1: Write the failing test**

```javascript
// tests/unit/test_epiline_label.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { labelAnchor } from "../../src/static/internal/epiline_label.mjs";

const SEG = [[10, 10], [110, 10]];   // horizontal, left end nearer top-left

test("labelAnchor: order 0 anchors exactly at the top-left-most endpoint", () => {
  const a = labelAnchor(SEG, 0, 14);
  assert.equal(a.x, 10);
  assert.equal(a.y, 10);
});

test("labelAnchor: endpoint choice does not depend on the order supplied", () => {
  const a = labelAnchor(SEG, 0, 14);
  const b = labelAnchor([[110, 10], [10, 10]], 0, 14);
  assert.deepEqual({ x: a.x, y: a.y }, { x: b.x, y: b.y });
});

test("labelAnchor: successive orders step further along the line", () => {
  const p0 = labelAnchor(SEG, 0, 14);
  const p1 = labelAnchor(SEG, 1, 14);
  const p2 = labelAnchor(SEG, 2, 14);
  assert.equal(p1.x, 24);
  assert.equal(p2.x, 38);
  assert.ok(p0.x < p1.x && p1.x < p2.x, "spacing must be monotonic");
});

test("labelAnchor: the anchor lies on the segment's line", () => {
  const seg = [[0, 0], [100, 50]];
  const p = labelAnchor(seg, 3, 10);
  // cross product of (p - start) with the segment direction must vanish
  const cross = (p.x - 0) * (50 - 0) - (p.y - 0) * (100 - 0);
  assert.ok(Math.abs(cross) < 1e-9, `anchor off the line, cross=${cross}`);
});

test("labelAnchor: ux,uy is a unit vector pointing at the far endpoint", () => {
  const p = labelAnchor([[0, 0], [0, 100]], 0, 14);
  assert.ok(Math.abs(Math.hypot(p.ux, p.uy) - 1) < 1e-12);
  assert.ok(p.uy > 0, "must point towards the far endpoint");
});

test("labelAnchor: ties on x+y are resolved deterministically", () => {
  // Both endpoints have x+y == 100; the result must not depend on argument order.
  const a = labelAnchor([[0, 100], [100, 0]], 0, 14);
  const b = labelAnchor([[100, 0], [0, 100]], 0, 14);
  assert.deepEqual({ x: a.x, y: a.y }, { x: b.x, y: b.y });
});

test("labelAnchor: degenerate and non-finite segments return null", () => {
  assert.equal(labelAnchor([[5, 5], [5, 5]], 0, 14), null);
  assert.equal(labelAnchor([[0, 0], [NaN, 10]], 0, 14), null);
  assert.equal(labelAnchor(null, 0, 14), null);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && node --test tests/unit/test_epiline_label.mjs`
Expected: FAIL — cannot find module `epiline_label.mjs`

- [ ] **Step 3: Write minimal implementation**

```javascript
// src/static/internal/epiline_label.mjs
// Pure geometry for placing an epipolar line's bodypart label at the frame edge.
//
// Labels are anchored at ONE end of the clipped segment and stepped along the
// line, so that where several lines converge near the epipole their labels form
// a staircase instead of a pile — and every label still sits on the line it
// names.

/**
 * @param {Array} segment  [[x1,y1],[x2,y2]] in video-pixel coordinates.
 * @param {number} order   Index among visible bodyparts; 0 sits at the endpoint.
 * @param {number} step    Pixels to advance per order.
 * @returns {{x:number,y:number,ux:number,uy:number}|null}
 */
export function labelAnchor(segment, order, step) {
  if (!segment || segment.length !== 2) return null;
  const [p, q] = segment;
  if (!p || !q || p.length !== 2 || q.length !== 2) return null;
  const [x1, y1] = p;
  const [x2, y2] = q;
  if (![x1, y1, x2, y2].every(Number.isFinite)) return null;

  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy);
  if (!(len > 0)) return null;

  // Anchor at the end nearer the frame's top-left so the label does not hop
  // between edges while scrubbing. Ties on x+y fall back to smaller x, then
  // smaller y, so the choice never depends on argument order.
  const pFirst =
    (x1 + y1 !== x2 + y2) ? (x1 + y1 < x2 + y2)
    : (x1 !== x2) ? (x1 < x2)
    : (y1 <= y2);

  const ax = pFirst ? x1 : x2;
  const ay = pFirst ? y1 : y2;
  const ux = (pFirst ? dx : -dx) / len;
  const uy = (pFirst ? dy : -dy) / len;

  const d = Math.max(0, order) * step;
  return { x: ax + ux * d, y: ay + uy * d, ux, uy };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && node --test tests/unit/test_epiline_label.mjs`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/static/internal/epiline_label.mjs dlc-3D/tests/unit/test_epiline_label.mjs
git commit -m "feat(reprojection): pure label-anchor geometry for epipolar lines"
```

---

### Task 2: Colour, visibility and label drawing

**Files:**
- Modify: `src/static/inline_analysis_3d_reprojection.js`
- Test: `tests/test_reproj_panel_wiring.py`

**Interfaces:**
- Consumes: `labelAnchor` (Task 1); `nameLabelBox` from `./components/viewer/internal/name_label.mjs`; the existing `_reprojDrawSegment(tile, seg, color)` and `_reprojActiveBodyparts()`.
- Produces: `_reprojBodypartColor(bp)`, `_reprojIsBodypartHidden(bp)`, and `_reprojDrawLabel(tile, seg, bp, order, color)`.

**Everything lands in ONE commit** because the card is live: a commit that colours lines but does not yet label them, or that filters visibility without colour, would ship a half-built look to users on reload.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reproj_panel_wiring.py`:

```python
def test_line_colour_comes_from_the_bodypart_chip(js):
    """The chip already carries labelerColor(idx) as --bp-color, so reading it
    keeps lines and markers in lockstep without duplicating palette logic or
    editing the shared viewer library."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "_reprojBodypartColor" in block
    assert "--bp-color" in block


def test_chip_queries_are_scoped_to_this_card(js):
    """CROSS-CARD GUARD. `.vv-bp-chip` is built by the shared markerEditor, so
    both cards' chips are in the same document. A document-wide query would
    silently read the OTHER card's colours and visibility, and would only
    misbehave when both cards are open."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    code = "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("//")
    )
    assert "ia3dr-bp-chips" in code, "chip lookups must be rooted at #ia3dr-bp-chips"
    assert 'document.querySelector(".vv-bp-chip' not in code, (
        "document-wide chip query would match the original card's chips"
    )


def test_hidden_bodyparts_get_no_line(js):
    """markerEditor marks hidden chips with .vis-hidden, which also covers
    per-frame hiding. Hiding a marker but keeping its line would be
    contradictory."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "vis-hidden" in block
    assert "_reprojIsBodypartHidden" in block


def test_labels_use_the_shared_geometry_and_label_box(js):
    """Reimplementing either would let the epipolar labels drift from the marker
    name labels."""
    assert "internal/epiline_label.mjs" in js
    assert "labelAnchor" in js
    assert "nameLabelBox" in js


def test_label_order_counts_only_visible_bodyparts(js):
    """order is the index among VISIBLE bodyparts so the staircase compacts when
    parts are hidden, instead of leaving gaps where hidden ones would have sat."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "visible" in block.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_wiring.py -k "colour or scoped or hidden_bodyparts or shared_geometry or label_order" -v`
Expected: FAIL — `_reprojBodypartColor` is undefined

- [ ] **Step 3: Add the imports**

At the top of `src/static/inline_analysis_3d_reprojection.js`, alongside the existing `marker_overlay.mjs` import, add:

```javascript
import { nameLabelBox } from "./components/viewer/internal/name_label.mjs";
import { labelAnchor } from "./internal/epiline_label.mjs";
```

If `nameLabelBox` is already imported, extend that statement rather than adding a duplicate.

- [ ] **Step 4: Add the chip helpers**

Insert into the EPIPOLAR OVERLAY block, just above `_reprojDrawSegment`:

```javascript
// ── Colour and visibility, sourced from the bp-chips ────────────────────────
// markerEditor renders one chip per bodypart carrying --bp-color (the exact
// labelerColor the marker uses) and toggles .vis-hidden on it. Reading the chip
// keeps the line in lockstep with its marker without duplicating palette logic
// or editing the shared viewer library.
//
// SCOPING IS LOAD-BEARING: `.vv-bp-chip` comes from the shared markerEditor, so
// the ORIGINAL card's chips are in this same document. Always root the lookup at
// this card's own container.
const REPROJ_LABEL_STEP = 14;   // matches the 14px marker name-label box height

function _reprojChip(bp) {
  const host = document.getElementById("ia3dr-bp-chips");
  if (!host) return null;
  return host.querySelector(`.vv-bp-chip[data-bp="${CSS.escape(bp)}"]`);
}

function _reprojBodypartColor(bp) {
  const c = _reprojChip(bp)?.style.getPropertyValue("--bp-color")?.trim();
  return c || "rgba(120,200,255,.85)";   // pre-colour default, e.g. before poses load
}

function _reprojIsBodypartHidden(bp) {
  return !!_reprojChip(bp)?.classList.contains("vis-hidden");
}

// Draw the bodypart name at the frame edge, stepped along its own line so that
// converging lines do not stack their labels.
function _reprojDrawLabel(tile, seg, bp, order, color) {
  const canvas = tile.canvasEl, img = tile.imgEl;
  if (!canvas || !img) return;
  const anchor = labelAnchor(seg, order, REPROJ_LABEL_STEP);
  if (!anchor) return;
  const scale = scaleFor(
    img.naturalWidth, img.naturalHeight, canvas.width, canvas.height,
  );
  const p = videoToCanvas(anchor.x, anchor.y, scale);
  const ctx = canvas.getContext("2d");
  ctx.save();
  ctx.font = nameLabelBox(0, 0, 0, 0).font;
  const box = nameLabelBox(p.cx, p.cy, 0, ctx.measureText(bp).width);
  ctx.fillStyle = "rgba(12,13,16,.65)";
  ctx.fillRect(box.boxX, box.boxY, box.boxW, box.boxH);
  ctx.fillStyle = color;
  ctx.fillText(bp, box.textX, box.textY);
  ctx.restore();
}
```

- [ ] **Step 5: Use them in the drawTile handler**

Replace the body of the `_viewer.on("drawTile", ...)` handler's loop so it skips
hidden bodyparts, colours each line, and labels it. The handler currently reads:

```javascript
    const gen = ++_reprojDrawGen;
    for (const bp of parts) {
      const seg = await _reprojFetchSegment(frame, bp);
      if (gen !== _reprojDrawGen) return;   // superseded — abandon this pass
      if (seg) _reprojDrawSegment(tile, seg, "rgba(120,200,255,.85)");
    }
```

Change it to:

```javascript
    const gen = ++_reprojDrawGen;
    // Only visible bodyparts get a line, and `order` counts within that visible
    // set so the label staircase compacts instead of leaving gaps.
    const visible = parts.filter((bp) => !_reprojIsBodypartHidden(bp));
    for (let order = 0; order < visible.length; order++) {
      const bp = visible[order];
      const seg = await _reprojFetchSegment(frame, bp);
      if (gen !== _reprojDrawGen) return;   // superseded — abandon this pass
      if (!seg) continue;
      const color = _reprojBodypartColor(bp);
      _reprojDrawSegment(tile, seg, color);
      _reprojDrawLabel(tile, seg, bp, order, color);
    }
```

Keep the `showLines` gate, the judged-camera filter and the generation guard
above it exactly as they are.

- [ ] **Step 6: Run the tests**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_wiring.py -q`
Expected: PASS

- [ ] **Step 7: Verify the module parses**

Run: `cd dlc-3D && node --input-type=module --check < src/static/inline_analysis_3d_reprojection.js && echo "parses OK"`
Expected: `parses OK`. The Python tests only match strings and never execute this
module, so this is the only syntax check.

- [ ] **Step 8: Run the pure geometry tests and the whole suite**

Run:
```bash
cd dlc-3D && node --test tests/unit/test_epiline_label.mjs && python3 -m pytest -q 2>&1 | tail -20
```
Expected: the geometry tests pass, and the only pytest failures are the ten
listed in Global Constraints.

- [ ] **Step 9: Commit**

```bash
git add dlc-3D/src/static/inline_analysis_3d_reprojection.js \
        dlc-3D/tests/test_reproj_panel_wiring.py
git commit -m "feat(reprojection): colour epipolar lines per bodypart and label them at the frame edge"
```

---

### Task 3: Verify the change is live

**Files:** none — this task changes no code.

**Interfaces:**
- Consumes: Tasks 1 and 2, committed and green.
- Produces: confirmation that the running container serves the new files.

**No restart is needed or wanted.** This feature is entirely frontend, and
`src/static/` is a bind mount, so the container already serves the new files;
a browser reload picks them up. The container was last restarted to deploy a
backend change and must not be restarted again for this.

- [ ] **Step 1: Confirm the tree is clean and green**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git status --porcelain | grep -v '^??' || echo "clean"
cd dlc-3D && node --test tests/unit/test_epiline_label.mjs 2>&1 | tail -3
python3 -m pytest tests/test_reproj_panel_wiring.py -q 2>&1 | tail -3
```

Expected: clean tree, geometry tests passing, wiring tests passing.

- [ ] **Step 2: Confirm the container serves the new module**

```bash
docker exec deeplabcut-webapp-docker-dlc-3d-1 \
  sh -c 'ls -l /app/static/internal/epiline_label.mjs && grep -c "_reprojBodypartColor" /app/static/inline_analysis_3d_reprojection.js'
```

Expected: the file listing succeeds and the count is at least 2 (the definition
plus its use). A missing file means the bind mount did not pick it up — report
that rather than restarting.

- [ ] **Step 3: Confirm the module is served over HTTP**

```bash
docker exec deeplabcut-webapp-docker-dlc-3d-1 python3 -c "
import urllib.request as u
r = u.urlopen('http://localhost:5050/dlc-3d/static/internal/epiline_label.mjs', timeout=15)
body = r.read().decode()
print('HTTP', r.status, len(body), 'bytes')
print('exports labelAnchor:', 'export function labelAnchor' in body)
"
```

Expected: `HTTP 200` and `exports labelAnchor: True`.

- [ ] **Step 4: Confirm nothing else was disturbed**

```bash
docker ps --format '{{.Names}}\t{{.Status}}' | grep deeplabcut
ls "/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/tdcs/070126" | grep -c reprojected
```

Expected: `dlc-3d` still up from its earlier start with no new restart, the other
five services untouched, and the reprojected-file count still **4** — the four
files already present from an earlier run. Report the number you actually
observe; do not report the expected one.

**Do NOT use `/reproject/run` as a health probe.** It writes
`<stem>_reprojected.*` beside the source data and overwrites any previous set.
`/reproject/thresholds` is the read-only endpoint.

- [ ] **Step 5: No commit** — this task produces no repository change.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
| --- | --- |
| Colour read from the chip's `--bp-color` | 2 |
| Chip query scoped to `#ia3dr-bp-chips` (cross-card guard) | 2, with a dedicated test |
| Fallback colour when no chip exists | 2 |
| `vis-hidden` suppresses the line | 2 |
| `labelAnchor(segment, order, step)` pure module | 1 |
| Anchor at the top-left-most endpoint, deterministic | 1 |
| Step along the line; `order` counts visible bodyparts only | 1 (geometry), 2 (the visible filter) |
| `step` default 14 px matching the marker label box | 2 (`REPROJ_LABEL_STEP`) |
| `null` for degenerate/non-finite segments | 1 |
| Labels drawn via `nameLabelBox` for visual parity | 2 |
| Real unit tests for the geometry | 1 |
| Live verification | 3 |

**Placeholder scan:** none. Every step has runnable code or an exact command.

**Type consistency:** `labelAnchor(segment, order, step) -> {x, y, ux, uy} | null`
is defined in Task 1 and called in Task 2 with that exact signature.
`_reprojBodypartColor(bp)`, `_reprojIsBodypartHidden(bp)` and
`_reprojDrawLabel(tile, seg, bp, order, color)` are defined and used within Task
2. `REPROJ_LABEL_STEP` is defined once and passed as `labelAnchor`'s `step`.
`_reprojDrawSegment(tile, seg, color)` keeps its existing three-argument
signature; only its caller changes.

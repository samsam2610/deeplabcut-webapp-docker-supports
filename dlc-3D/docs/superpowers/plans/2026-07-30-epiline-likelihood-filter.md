# Epipolar Line Display Threshold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A likelihood field beside the *Show epipolar lines* checkbox, so a line is drawn only when the reference marker that induced it clears that confidence.

**Architecture:** No backend change — the endpoint already returns the likelihood and the frontend simply discards it. The filter decision is a pure tested function; the draw loop consults it and counts label positions only for lines actually drawn.

**Tech Stack:** Vanilla ES modules, `node --test`, pytest.

## Global Constraints

- **This card is LIVE and in use.** `dlc-3D/src/static/` is a bind mount: every commit reaches users on their next browser reload. Leave the panel working at every commit.
- **`node --input-type=module --check` is NOT sufficient.** An identifier used without an import parses fine and throws `ReferenceError` only at runtime — that exact mistake silently killed this feature once already. If you add an import, run `python3 -m pytest tests/test_reproj_panel_wiring.py -q`, which contains a guard that catches it.
- **Never modify** `src/templates/partials/card_inline_analysis_3d.html`, `src/static/inline_analysis_3d.js`, `src/static/inline_analysis_3d.css`, anything under `src/static/components/viewer/`, or anything under `src/dlc_3d_bp/`. No backend change is needed.
- Keep the `ia3dr-` namespace. No new `ia3d-` (single r) identifiers.
- **Do NOT restart, rebuild or stop any container, and run NO docker command.** Deployment verification is Task 3, done by someone else.
- Ten tests fail on this host for unrelated pre-existing reasons. The two playwright e2e tests are FLAKY, so a run legitimately shows 9–11 failures. **Compare failure NAMES against the known ten, never counts.**
- `node --test <file>` prints "# tests 1" because it counts the FILE as one subtest. Run the file directly (`node tests/unit/<file>.mjs`) to see and report individual test counts.
- Run pytest and node from `dlc-3D/`.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/static/internal/epiline_filter.mjs` | **New.** `shouldDrawLine(likelihood, threshold)`. Pure. |
| `tests/unit/test_epiline_filter.mjs` | **New.** Real assertions on that decision. |
| `src/static/card_inline_analysis_3d_reprojection.html` | The field, beside the checkbox. |
| `src/static/internal/reproj_help.mjs` | A `line_lik` help entry. |
| `src/static/inline_analysis_3d_reprojection.js` | Cache the likelihood; filter; persist. |
| `tests/unit/test_reproj_help.mjs` | Key set grows to eight. |
| `tests/test_reproj_panel_markup.py`, `tests/test_reproj_panel_wiring.py` | Markup and wiring. |

---

### Task 1: `shouldDrawLine` pure filter

**Files:**
- Create: `src/static/internal/epiline_filter.mjs`
- Test: `tests/unit/test_epiline_filter.mjs`

**Interfaces:**
- Consumes: nothing.
- Produces: `shouldDrawLine(likelihood, threshold) -> boolean`.

- [ ] **Step 1: Write the failing test**

```javascript
// tests/unit/test_epiline_filter.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { shouldDrawLine } from "../../src/static/internal/epiline_filter.mjs";

test("draws when the reference marker clears the threshold", () => {
  assert.equal(shouldDrawLine(0.9, 0.4), true);
  assert.equal(shouldDrawLine(0.4, 0.4), true, "the threshold itself passes");
});

test("hides a marker below the threshold", () => {
  assert.equal(shouldDrawLine(0.39, 0.4), false);
  assert.equal(shouldDrawLine(0.0, 0.4), false);
});

test("an unknown likelihood is not a confident one", () => {
  assert.equal(shouldDrawLine(null, 0.4), false);
  assert.equal(shouldDrawLine(undefined, 0.4), false);
  assert.equal(shouldDrawLine(NaN, 0.4), false);
});

test("a threshold of 0 genuinely means show everything", () => {
  assert.equal(shouldDrawLine(0, 0), true);
  assert.equal(shouldDrawLine(0.01, 0), true);
});

test("a blanked field must not make every line vanish", () => {
  // Clearing the input to retype gives NaN; falling back to 'draw' keeps the
  // overlay usable instead of silently emptying it mid-edit.
  assert.equal(shouldDrawLine(0.5, NaN), true);
  assert.equal(shouldDrawLine(0.5, undefined), true);
  assert.equal(shouldDrawLine(0.5, null), true);
});

test("an unknown likelihood stays hidden even with a blanked threshold", () => {
  assert.equal(shouldDrawLine(NaN, NaN), false);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && node tests/unit/test_epiline_filter.mjs`
Expected: FAIL — cannot find module `epiline_filter.mjs`

- [ ] **Step 3: Write the module**

```javascript
// src/static/internal/epiline_filter.mjs
// Whether an epipolar line should be DRAWN, given the confidence of the
// reference marker that induced it.
//
// This gates display only. gate_ref still decides what the engine judges, and
// the two are deliberately separate: the default display threshold sits BELOW
// gate_ref so lines the engine ignored remain visible, which is often what
// explains an UNJUDGED verdict.

/**
 * @param {number|null|undefined} likelihood  reference marker confidence
 * @param {number|null|undefined} threshold   the panel's display threshold
 * @returns {boolean}
 */
export function shouldDrawLine(likelihood, threshold) {
  // An unknown confidence is not a confident one — hide it either way.
  if (!Number.isFinite(likelihood)) return false;
  // A blanked or malformed threshold must not empty the overlay while the user
  // is mid-edit, so fall back to drawing.
  if (!Number.isFinite(threshold)) return true;
  return likelihood >= threshold;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && node tests/unit/test_epiline_filter.mjs`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/static/internal/epiline_filter.mjs dlc-3D/tests/unit/test_epiline_filter.mjs
git commit -m "feat(reprojection): pure display-threshold decision for epipolar lines"
```

---

### Task 2: Field, filtering, persistence and help

**Files:**
- Modify: `src/static/card_inline_analysis_3d_reprojection.html`
- Modify: `src/static/internal/reproj_help.mjs`
- Modify: `src/static/inline_analysis_3d_reprojection.js`
- Test: `tests/unit/test_reproj_help.mjs`, `tests/test_reproj_panel_markup.py`, `tests/test_reproj_panel_wiring.py`

**Interfaces:**
- Consumes: `shouldDrawLine` (Task 1).
- Produces: `#ia3dr-reproj-line-lik`; `_reprojFetchSegment` returning `{segment, likelihood}`.

**One commit** — the card is live, and a field that does nothing would be worse than no field.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_reproj_help.mjs` — and update the existing `KEYS` array in that file to include `"line_lik"`:

```javascript
test("the display threshold explains it is display-only", () => {
  const e = HELP.line_lik;
  assert.ok(e, "line_lik needs a help entry");
  assert.match(e.body, /display|drawn|shown/i);
  // It must not be confused with gate_ref, which decides what is JUDGED.
  assert.match(e.body + e.example, /judge|verdict|gate_ref/i);
});
```

Append to `tests/test_reproj_panel_markup.py`:

```python
def test_line_likelihood_field_sits_beside_the_checkbox(card):
    assert 'id="ia3dr-reproj-line-lik"' in card
    # Same control row as the show-lines checkbox, so it reads as belonging to it.
    show = card.index('id="ia3dr-reproj-show-lines"')
    field = card.index('id="ia3dr-reproj-line-lik"')
    assert abs(show - field) < 600, "field is not adjacent to the checkbox"


def test_line_likelihood_field_bounds_and_default(card):
    frag = card.split('id="ia3dr-reproj-line-lik"')[1][:220]
    assert 'min="0"' in frag and 'max="1"' in frag
    assert 'value="0.4"' in frag, "default must be 0.4, below gate_ref's 0.6"
    assert "data-help" in frag
```

Append to `tests/test_reproj_panel_wiring.py`:

```python
def test_draw_loop_consults_the_pure_filter(js):
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "shouldDrawLine" in block


def test_fetch_keeps_the_likelihood_the_endpoint_already_sends(js):
    """The endpoint has always returned it; the frontend used to throw it away."""
    fn = js.split("async function _reprojFetchSegment")[1].split("\nasync function")[0]
    assert "likelihood" in fn


def test_label_order_counts_only_lines_actually_drawn(js):
    """REGRESSION: with lines now filtered by likelihood too, using the loop
    index as `order` would leave gaps in the label staircase wherever a line was
    filtered out."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    code = "\n".join(l for l in block.splitlines() if not l.lstrip().startswith("//"))
    assert "order++" in code, "order must increment on a successful draw"
    assert "order < visible.length" not in code, (
        "order is still the loop index, so filtered lines leave gaps"
    )


def test_display_threshold_is_client_side_only(js):
    """It gates drawing, not judgement, so it must never reach the engine."""
    block = js.split("REPROJECTION PANEL")[1]
    assert "line_lik" not in block.split("_reprojPayload")[1][:900], (
        "the display threshold must not be sent in a request payload"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd dlc-3D && node tests/unit/test_reproj_help.mjs; python3 -m pytest tests/test_reproj_panel_markup.py tests/test_reproj_panel_wiring.py -q`
Expected: FAIL — the field and the `line_lik` help entry do not exist

- [ ] **Step 3: Add the field**

In `src/static/card_inline_analysis_3d_reprojection.html`, find the row holding
`ia3dr-reproj-show-lines` and add, immediately after that `</label>`:

```html
          <label class="ia3dr-inline-check">
            min likelihood
            <input type="number" id="ia3dr-reproj-line-lik"
                   min="0" max="1" step="0.05" value="0.4"
                   data-help="line_lik">
          </label>
```

- [ ] **Step 4: Add the help entry**

In `src/static/internal/reproj_help.mjs`, add to `HELP`:

```javascript
  line_lik: {
    title: "min likelihood — display only",
    body:
      "A line is drawn only when the trusted camera's marker for that bodypart " +
      "reaches this confidence. It changes nothing about the verdicts: gate_ref " +
      "still decides what the engine judges.",
    example:
      "The default 0.4 sits below gate_ref's 0.6 on purpose, so lines the " +
      "engine ignored are still visible — often the reason a bodypart came " +
      "back UNJUDGED.",
  },
```

- [ ] **Step 5: Keep the likelihood, and filter on it**

In `src/static/inline_analysis_3d_reprojection.js`, add the import beside the
other `./internal/` imports:

```javascript
import { shouldDrawLine } from "./internal/epiline_filter.mjs";
```

Add to the `_reprojEl` map:

```javascript
  lineLik:    () => document.getElementById("ia3dr-reproj-line-lik"),
```

In `_reprojFetchSegment`, keep the likelihood instead of discarding it. The line
currently reading `if (res.ok) seg = (await res.json()).segment || null;` and the
surrounding cache handling become:

```javascript
  let entry = null;
  try {
    const res = await fetch(`/dlc-3d/reproject/epiline?${qs}`);
    if (res.ok) {
      const data = await res.json();
      // The endpoint has always returned the reference marker's likelihood; it
      // used to be thrown away. The display filter needs it.
      entry = data.segment
        ? { segment: data.segment, likelihood: data.likelihood }
        : null;
    }
  } catch (e) { /* leave entry null; the overlay simply draws nothing */ }
```

storing and returning `entry` wherever `seg` was stored and returned. Keep the
4000-entry cache bound and the clear-on-bind behaviour exactly as they are.

In the `drawTile` handler, replace the loop body so `order` counts drawn lines:

```javascript
    const gen = ++_reprojDrawGen;
    const minLik = parseFloat(_reprojEl.lineLik()?.value);
    const visible = parts.filter((bp) => !_reprojIsBodypartHidden(bp));
    let order = 0;
    for (const bp of visible) {
      const entry = await _reprojFetchSegment(frame, bp);
      if (gen !== _reprojDrawGen) return;   // superseded — abandon this pass
      if (!entry || !entry.segment) continue;
      if (!shouldDrawLine(entry.likelihood, minLik)) continue;
      const color = _reprojBodypartColor(bp);
      _reprojDrawSegment(tile, entry.segment, color);
      _reprojDrawLabel(tile, entry.segment, bp, order, color);
      order++;   // only a drawn line advances the label staircase
    }
```

- [ ] **Step 6: Repaint on change, and persist**

In `_reprojWirePanel`, make the field repaint immediately:

```javascript
  _reprojEl.lineLik()?.addEventListener("change", _reprojRepaint);
```

In `_reprojSaveParams`, add to the `prefs` object:

```javascript
    line_lik: parseFloat(_reprojEl.lineLik()?.value),
```

In `_reprojLoadParams`, after the k1/k2 restores, add:

```javascript
    setNum(_reprojEl.lineLik(), prefs.line_lik);
```

and add `_reprojEl.lineLik()` to the array of controls that get the
`change` → `_reprojSaveParams` listener.

- [ ] **Step 7: Run the tests**

Run:
```bash
cd dlc-3D && node tests/unit/test_epiline_filter.mjs && node tests/unit/test_reproj_help.mjs
python3 -m pytest tests/test_reproj_panel_markup.py tests/test_reproj_panel_wiring.py -q
```
Expected: all pass. The wiring file's import guard confirms `shouldDrawLine` is
genuinely imported — `node --check` alone would not.

- [ ] **Step 8: Whole suite**

Run: `cd dlc-3D && python3 -m pytest -q 2>&1 | grep -E "^FAILED" | sort`
Expected: every FAILED name is one of the known ten. Compare names, not counts.

- [ ] **Step 9: Commit**

```bash
git add dlc-3D/src/static/card_inline_analysis_3d_reprojection.html \
        dlc-3D/src/static/internal/reproj_help.mjs \
        dlc-3D/src/static/inline_analysis_3d_reprojection.js \
        dlc-3D/tests/unit/test_reproj_help.mjs \
        dlc-3D/tests/test_reproj_panel_markup.py \
        dlc-3D/tests/test_reproj_panel_wiring.py
git commit -m "feat(reprojection): display threshold for epipolar lines"
```

---

### Task 3: Verify it is live

**Files:** none.

**No restart.** Pure frontend on a bind mount; a browser reload picks it up.

- [ ] **Step 1: Confirm clean and green**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git status --porcelain | grep -v '^??' || echo "clean"
cd dlc-3D && node tests/unit/test_epiline_filter.mjs 2>&1 | tail -3
```

- [ ] **Step 2: Confirm the container serves it**

```bash
docker exec deeplabcut-webapp-docker-dlc-3d-1 sh -c '
  ls -l /app/static/internal/epiline_filter.mjs
  grep -c "ia3dr-reproj-line-lik" /app/static/card_inline_analysis_3d_reprojection.html
  grep -c "shouldDrawLine" /app/static/inline_analysis_3d_reprojection.js'
```

Expected: the file exists; the markup count is at least 1; the JS count is at
least 2 (import plus use).

- [ ] **Step 3: Confirm it is served over HTTP**

```bash
docker exec deeplabcut-webapp-docker-dlc-3d-1 python3 -c "
import urllib.request as u
r = u.urlopen('http://localhost:5050/dlc-3d/static/internal/epiline_filter.mjs', timeout=15)
b = r.read().decode()
print('HTTP', r.status, len(b), 'bytes, exports:', 'export function shouldDrawLine' in b)
"
```

Expected: `HTTP 200` and `exports: True`.

- [ ] **Step 4: Confirm nothing was disturbed**

```bash
docker ps --format '{{.Names}}\t{{.Status}}' | grep deeplabcut
ls "/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/tdcs/070126" | grep -c reprojected
```

Expected: `dlc-3d` still up from its earlier start with NO new restart, the other
five services unchanged, and the reprojected count still 4. **Report the numbers
you actually observe, never the expected ones** — a previous agent on this
session reported an expected 0 when the real answer was 4.

**Never call `/reproject/run`** — it writes `<stem>_reprojected.*` beside real
research data and overwrites any previous set. `/reproject/thresholds` is the
read-only endpoint.

- [ ] **Step 5: No commit.**

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
| --- | --- |
| Field beside the checkbox, bounds, 0.4 default | 2 |
| No backend change; keep the likelihood already returned | 2 |
| `shouldDrawLine` pure, with the blanked-threshold fallback | 1 |
| Unknown likelihood hidden even with a blank threshold | 1 |
| `order` counts drawn lines only (staircase gaps) | 2, with a regression test |
| Immediate repaint on change | 2 |
| Persisted in `reproj_params` | 2 |
| `data-help` + `line_lik` help entry | 2 |
| Client-side only, never in a payload | 2, with a test |
| Live verification | 3 |

**Placeholder scan:** none.

**Type consistency:** `shouldDrawLine(likelihood, threshold) -> boolean` is
defined in Task 1 and called in Task 2 with that signature.
`_reprojFetchSegment` changes from returning a segment to returning
`{segment, likelihood} | null`; Task 2 Step 5 updates its only consumer in the
same commit. `_reprojEl.lineLik()` is added in Task 2 and used by the draw loop,
the repaint listener and both persistence functions.

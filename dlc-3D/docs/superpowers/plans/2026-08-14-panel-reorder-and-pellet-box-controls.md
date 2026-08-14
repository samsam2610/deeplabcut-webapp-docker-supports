# Reorderable Panels and Pellet-Box Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the 3D inline-analysis cards a per-camera clear-box control, a Re-aim button that says what it costs, and a panel stack the user can drag into their own order, saved per project.

**Architecture:** Three near-clone cards (`ia3d-`, `ia3dr-`, `ia3ds-`) already hold their panels as a contiguous run of siblings inside `<prefix>player-section`. Reordering therefore moves existing elements with `insertBefore` — never rebuilds them — so every id, listener and canvas context inside a panel survives. Pure ordering logic lives in a testable `.mjs` module; the order is stored per project in one JSON file behind two new dlc-3D routes.

**Tech Stack:** Vanilla ES modules (no framework, no bundler), Flask blueprint (`dlc_3d_bp`), `node --test` for `.mjs` unit tests, pytest for routes, jsdom for DOM smoke tests.

## Global Constraints

- **Design spec:** `dlc-3D/docs/superpowers/specs/2026-08-14-panel-reorder-and-pellet-box-controls-design.md`. Read it before starting.
- **Repo root:** `/home/sam/docker-images/deeplabcut-webapp-docker-supports`. All paths below are relative to `dlc-3D/` unless stated.
- **`.mjs` tests run per file** — Node 16's `--test` finds 0 tests in directory mode. Always `node --test tests/unit/<file>.mjs`.
- **Python tests** run from `dlc-3D/` with `python -m pytest tests/<file>.py -v`. `tests/conftest.py` adds `src/` to `sys.path`.
- **Known-failing baseline:** dlc-3D has 8 pre-existing test failures. Check before blaming a change.
- **Panels are MOVED, never re-rendered.** Any implementation that rebuilds panel markup is wrong, regardless of whether tests pass.
- **No behaviour change to what a panel does.** The only intended behaviour changes are listed in Task 3.
- **Deployment happens in Task 7, via subagent, and only after every earlier task is green.** Do not restart any container mid-plan.
- Commit after every task. Commit messages: `feat(sam): …` / `feat(3d): …` / `fix(sam): …`, no trailing attribution beyond what the repo already uses.

---

### Task 1: Per-camera clear box

Each camera card grows its own `clear box` button beside its `show box` checkbox, and the `re-place [cam▾] [Clear box]` row is deleted. The header markup moves into the already-tested pure module so it can be asserted on.

**Files:**
- Modify: `src/static/internal/pellet_box.mjs` (append a new export)
- Modify: `src/static/inline_analysis_3d_sam.js:4737-4771` (`_pelletRenderCams`), `:5108-5114` (the handler being relocated)
- Modify: `src/static/card_inline_analysis_3d_sam.html:1006-1014` (delete the row, keep `ia3ds-bind-status`)
- Test: `tests/unit/test_pellet_box_placement.mjs`, `tests/unit/test_sam_panel_ids.mjs`

**Interfaces:**
- Consumes: `isVisible(vis, cam)` from `pellet_box.mjs` (already exported).
- Produces: `camCardHead(name, cam, visible, templateSrc = "") -> string` in `pellet_box.mjs`, used only by `_pelletRenderCams`. `cam` is the `/pellet/model` camera payload (`cx`, `cy`, `half`, `margin`, `n_samples`, `has_template`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_pellet_box_placement.mjs` (and add `camCardHead` to the existing import block at the top of that file):

```js
// ── camera card header ──────────────────────────────────────────────────────
//
// The header was built by string concatenation inside a 5000-line DOM-bound
// function, which is why the control it carries had no test. The clear button
// must name ITS OWN camera: the old single button read the camera from a
// dropdown, so a mis-wired per-camera button would clear the other camera's box
// and look like it worked.

test("the header carries a clear button for its own camera", () => {
  const html = camCardHead("cam1", { n_samples: 3, has_template: false }, false);
  assert.match(html, /data-clearcam="cam1"/);
  assert.equal(html.includes('data-clearcam="cam0"'), false);
});

test("each camera gets a show-box checkbox for its own camera", () => {
  const html = camCardHead("cam0", { n_samples: 0, has_template: false }, false);
  assert.match(html, /data-showcam="cam0"/);
});

test("show box reflects the visibility it was given", () => {
  const on = camCardHead("cam0", { n_samples: 0, has_template: false }, true);
  const off = camCardHead("cam0", { n_samples: 0, has_template: false }, false);
  assert.match(on, /data-showcam="cam0"[^>]*checked/);
  assert.equal(/data-showcam="cam0"[^>]*checked/.test(off), false);
});

test("the sample count is shown", () => {
  assert.match(camCardHead("cam0", { n_samples: 12 }, false), /12 samples/);
});

test("a camera with no template gets no <img>", () => {
  assert.equal(camCardHead("cam0", { has_template: false }, false).includes("<img"),
               false);
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `node --test tests/unit/test_pellet_box_placement.mjs`
Expected: FAIL — `camCardHead is not a function` / import error.

- [ ] **Step 3: Add `camCardHead` to `pellet_box.mjs`**

Append at the end of `src/static/internal/pellet_box.mjs`:

```js
// ── camera card header ──────────────────────────────────────────────────────
//
// Here rather than in the panel because the clear-box control is per camera and
// used to be one button plus a dropdown. That indirection is exactly what a
// unit test cannot see: a button that clears "whatever the dropdown says" looks
// identical, in source, to one that clears the camera it sits on.
//
// `templateSrc` is passed in rather than built here so this module stays free of
// the API's URL shape.

export function camCardHead(name, cam, visible, templateSrc = "") {
  const c = cam || {};
  const img = c.has_template && templateSrc
    ? `<img alt="" src="${templateSrc}"/>` : "";
  return `<h4>${img}
        ${name}
        <label class="ia3ds-cam-show" title="Draw this camera's box on its frame">
          <input type="checkbox" data-showcam="${name}"${visible ? " checked" : ""}/> show box
        </label>
        <button class="btn-sm ia3ds-cam-clear" data-clearcam="${name}"
                title="Forget this camera's box so the next click places a new one. Pellet labels are kept.">clear box</button>
        <span style="margin-left:auto">${c.n_samples || 0} samples</span></h4>`;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test tests/unit/test_pellet_box_placement.mjs`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Use it from `_pelletRenderCams`**

In `src/static/inline_analysis_3d_sam.js`, add `camCardHead` to the `pellet_box.mjs` import list at line 38-42. Then replace the `card.innerHTML = \`…\`` template in `_pelletRenderCams` (lines 4747-4759) with:

```js
    card.innerHTML = camCardHead(
      name, c, isVisible(_pellet.vis, name),
      c.has_template ? `${SAMAPI}/pellet/template.png?cam=${name}&t=${Date.now()}` : "")
      + `
      <div class="ia3ds-cam-fields">
        <label>cx<input type="number" step="1" data-cam="${name}" data-k="cx" value="${Math.round(c.cx)}"/></label>
        <label>cy<input type="number" step="1" data-cam="${name}" data-k="cy" value="${Math.round(c.cy)}"/></label>
        <label>half<input type="number" step="1" min="4" data-cam="${name}" data-k="half" value="${c.half}"/></label>
        <label>margin<input type="number" step="1" min="0" data-cam="${name}" data-k="margin" value="${c.margin}"/></label>
      </div>`;
```

Immediately after the existing `grid.querySelectorAll("input[data-showcam]")` block (lines 4762-4767), add the clear wiring:

```js
  grid.querySelectorAll("button[data-clearcam]").forEach((el) => {
    el.onclick = () => _pelletClearBox(el.dataset.clearcam);
  });
```

- [ ] **Step 6: Move the clear handler out of the deleted row's wiring**

Add this function next to `_pelletSave` (after line 4795) in the same file:

```js
// The box lives per camera, so the control does too. It used to be one button
// plus a `re-place` dropdown, which meant the camera being cleared and the
// camera being looked at could disagree.
async function _pelletClearBox(cam) {
  if (!cam) return;
  _pellet.state = clearBox(_pellet.state, cam);
  _pelletDrawBox();
  await _pelletPersist();
  _samSay(`${cam} box cleared — click the pellet on ${cam} to place it again`);
}
```

Then delete the whole `on("ia3ds-pellet-replace", "onclick", async () => { … });` block at lines 5108-5114.

- [ ] **Step 7: Delete the `re-place` row from the card**

In `src/static/card_inline_analysis_3d_sam.html`, replace lines 1006-1014 (the whole `<div class="ia3ds-sam-row">` containing `ia3ds-pellet-replace-cam`, `ia3ds-pellet-replace` and `ia3ds-bind-status`) with a row that keeps only the status:

```html
          <div class="ia3ds-sam-row">
            <span class="ia3ds-sam-status" id="ia3ds-bind-status" title="Which cameras are clickable, and the size of their click overlay"></span>
          </div>
```

- [ ] **Step 8: Update the id test**

In `tests/unit/test_sam_panel_ids.mjs`, in the `"the batch and tag controls exist"` test (line 82-88), remove `"ia3ds-pellet-replace", "ia3ds-pellet-replace-cam",` from the list. Then add a new test after it:

```js
test("the box is cleared per camera, not through a dropdown", () => {
  // The dropdown made the cleared camera and the looked-at camera two separate
  // facts. Re-adding it would restore that.
  assert.equal(declared.has("ia3ds-pellet-replace"), false);
  assert.equal(declared.has("ia3ds-pellet-replace-cam"), false);
  assert.match(js, /data-clearcam/, "the per-camera clear button must be rendered");
});
```

- [ ] **Step 9: Run the affected tests**

Run:
```bash
node --test tests/unit/test_pellet_box_placement.mjs
node --test tests/unit/test_sam_panel_ids.mjs
node --test tests/unit/test_sam_card_loads.mjs
```
Expected: all PASS. `test_sam_card_loads.mjs` proves the module still loads and wires — it is the guard against a typo in the edited render path.

- [ ] **Step 10: Commit**

```bash
git add dlc-3D/src/static/internal/pellet_box.mjs \
        dlc-3D/src/static/inline_analysis_3d_sam.js \
        dlc-3D/src/static/card_inline_analysis_3d_sam.html \
        dlc-3D/tests/unit/test_pellet_box_placement.mjs \
        dlc-3D/tests/unit/test_sam_panel_ids.mjs
git commit -m "feat(sam): clear box is per camera, next to its show-box toggle"
```

---

### Task 2: Re-aim left-aligned, and honest about its cost

The button moves to the left of its row, and gains the note that is the only place the user can learn that Re-aim invalidates cached sweeps project-wide.

**Files:**
- Modify: `src/static/card_inline_analysis_3d_sam.html:1016-1019`
- Test: `tests/test_inline_3d_sam_reaim_note.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. Markup-only.

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/test_inline_3d_sam_reaim_note.py`:

```python
"""Re-aim must say what it costs, and sit where the eye starts.

Re-aim rebuilds each camera's template pool from the user's clicks. The pool's
exemplar COUNT is part of the sweep cache key (sam-training/src/store.py:63-65
via sweep_cache.signature), so adding or deleting a click invalidates every
cached sweep in the project -- not just the clicked pair. Nothing on screen said
so, and the next sweep silently costs minutes per video.

The button also sat at the right edge, because .ia3ds-sam-status carries
`margin-left:auto` and preceded it in the markup.
"""
from pathlib import Path

import pytest

CARD = (Path(__file__).parent.parent / "src" / "static"
        / "card_inline_analysis_3d_sam.html")


@pytest.fixture
def markup():
    return CARD.read_text(encoding="utf-8")


def test_the_button_precedes_the_status_span(markup):
    """`margin-left:auto` on the status is what pushes everything after it
    right, so order in the markup IS the alignment."""
    btn = markup.index('id="ia3ds-pellet-retrain"')
    status = markup.index('id="ia3ds-pellet-status"')
    assert btn < status, "the Re-aim button must come before the status span"


def test_the_note_warns_that_sweeps_are_invalidated(markup):
    note = markup[markup.index('id="ia3ds-pellet-retrain"'):]
    assert "invalidates cached sweeps" in note
    assert "every video in the project" in note


def test_the_note_says_what_is_rebuilt(markup):
    note = markup[markup.index('id="ia3ds-pellet-retrain"'):]
    for phrase in ("template pool", "median click", "both", "reference"):
        assert phrase in note, f"the note must mention {phrase!r}"


def test_pressing_it_unchanged_is_described_as_free(markup):
    """Otherwise the warning reads as 'never press this', which is wrong -- the
    signature only moves when the number of clicks does."""
    note = markup[markup.index('id="ia3ds-pellet-retrain"'):]
    assert "costs nothing" in note
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_inline_3d_sam_reaim_note.py -v`
Expected: FAIL — `test_the_button_precedes_the_status_span` and all three note tests.

- [ ] **Step 3: Rewrite the row and add the note**

Replace lines 1016-1019 of `src/static/card_inline_analysis_3d_sam.html`:

```html
          <div class="ia3ds-sam-row">
            <button class="btn-sm" id="ia3ds-pellet-retrain">Re-aim box from clicks + rerun</button>
            <span class="ia3ds-sam-status" id="ia3ds-pellet-status"></span>
          </div>
          <p class="ia3ds-sam-note">
            <b>Re-aim</b> rebuilds each camera's <b>template pool</b> from the DLC
            seed plus every pellet click on this pair, recentres that camera's
            search box on the <b>median click</b>, re-derives the fallback 3D
            <b>reference</b> from frames clicked in <b>both</b> cameras, saves all
            of it to the project model, then reruns this pair. Deleting a click
            removes its influence — the pool is re-cut from scratch every time.
            <b>Adding or removing a click invalidates cached sweeps for every
            video in the project</b>, because the pool is part of the sweep's
            cache key. Pressing it again without changing the clicks
            <b>costs nothing</b>.
          </p>
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_inline_3d_sam_reaim_note.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the card's other guards**

Run:
```bash
node --test tests/unit/test_sam_panel_ids.mjs
node --test tests/unit/test_sam_card_loads.mjs
```
Expected: PASS — the ids are unchanged, so this is proving the markup edit did not break the fragment.

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/static/card_inline_analysis_3d_sam.html \
        dlc-3D/tests/test_inline_3d_sam_reaim_note.py
git commit -m "feat(sam): Re-aim sits left and states the sweep cost it hides"
```

---

### Task 3: The SAM panel becomes the sixth uniform panel

Gate it with a checkbox like its five neighbours and move it inside `ia3ds-player-section`, so it can take part in the reorder.

**Files:**
- Modify: `src/static/card_inline_analysis_3d_sam.html` (relocate `ia3ds-sam-panel`, currently 967-1187; insert before the `</div>` at 961 that closes `ia3ds-player-section`)
- Modify: `src/static/inline_analysis_3d_sam.js` (`_samWirePanel`, after line 5089)
- Test: `tests/unit/test_sam_panel_ids.mjs`, `tests/unit/test_sam_card_loads.mjs`

**Interfaces:**
- Consumes: nothing.
- Produces: DOM ids `ia3ds-sam-toggle` and `ia3ds-sam-controls`; `ia3ds-sam-panel` becomes a child of `ia3ds-player-section`. Task 6 relies on that parentage.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_sam_card_loads.mjs`:

```js
test("the SAM panel is one of the player section's panels", () => {
  // It has to share a parent with the other five to take part in the reorder,
  // and sharing that parent is also what makes it hide with the player instead
  // of lingering with a closed video's contents on screen.
  const section = dom.window.document.getElementById("ia3ds-player-section");
  const panel = dom.window.document.getElementById("ia3ds-sam-panel");
  assert.ok(section, "card must have #ia3ds-player-section");
  assert.ok(panel, "card must have #ia3ds-sam-panel");
  assert.equal(panel.parentElement, section);
});

test("the SAM panel starts collapsed, like its five neighbours", () => {
  const controls = dom.window.document.getElementById("ia3ds-sam-controls");
  const toggle = dom.window.document.getElementById("ia3ds-sam-toggle");
  assert.ok(controls, "card must have #ia3ds-sam-controls");
  assert.ok(controls.className.split(/\s+/).includes("hidden"));
  assert.equal(toggle.checked, false);
});

test("the trial picker lives inside the collapsible body", () => {
  // A control left outside the wrapper would still be on screen when the panel
  // is collapsed -- which is how a "collapsed" panel keeps acting.
  const controls = dom.window.document.getElementById("ia3ds-sam-controls");
  assert.ok(controls.querySelector("#ia3ds-sam-trial"),
    "the trial dropdown must be inside #ia3ds-sam-controls");
  assert.ok(controls.querySelector("#ia3ds-pellet"),
    "the pellet section must be inside #ia3ds-sam-controls");
});
```

Append to `tests/unit/test_sam_panel_ids.mjs`:

```js
test("the SAM panel is gated like the other five", () => {
  assert.ok(declared.has("ia3ds-sam-toggle"), "card is missing #ia3ds-sam-toggle");
  assert.ok(declared.has("ia3ds-sam-controls"), "card is missing #ia3ds-sam-controls");
  assert.match(js, /ia3ds-sam-toggle/, "the toggle must be wired, not just declared");
});
```

- [ ] **Step 2: Run them to verify they fail**

Run:
```bash
node --test tests/unit/test_sam_card_loads.mjs
node --test tests/unit/test_sam_panel_ids.mjs
```
Expected: FAIL — parentage is wrong, `#ia3ds-sam-controls` and `#ia3ds-sam-toggle` do not exist.

- [ ] **Step 3: Restructure the panel's head**

In `src/static/card_inline_analysis_3d_sam.html`, replace lines 967-972 (the opening `<div class="ia3ds-sam-panel">` and its `ia3ds-sam-head` block) with:

```html
        <div class="ia3ds-sam-panel" id="ia3ds-sam-panel">
          <div style="display:flex;align-items:center;gap:.6rem;flex-wrap:wrap">
            <label style="display:flex;align-items:center;gap:.45rem;font-size:.8rem;font-weight:500;cursor:pointer;user-select:none">
              <input type="checkbox" id="ia3ds-sam-toggle"
                     style="accent-color:var(--accent);width:14px;height:14px"/>
              SAM 3 + DINOv3
            </label>
            <span class="ia3ds-sam-sub">candidate frames for one trial</span>
            <span class="ia3ds-sam-status" id="ia3ds-sam-status">pick a trial</span>
          </div>
          <div id="ia3ds-sam-controls" class="hidden" style="margin-top:.5rem">
```

The status span stays in the header row deliberately: it is the panel's only
progress readout, and hiding it while collapsed would make a running batch look
like nothing is happening.

Then close the new wrapper: the panel's final `</div>` (line 1187 before the
edit) becomes two — `</div>` for `ia3ds-sam-controls`, `</div>` for
`ia3ds-sam-panel`. Re-indent the panel body by two spaces so the file stays
readable.

- [ ] **Step 4: Move the panel inside the player section**

Cut the whole `ia3ds-sam-panel` element and paste it inside `ia3ds-player-section`, immediately after `ia3ds-clip-panel-wrap`'s closing `</div>` and before the `</div>` that closes the section (line 961 before the edit). The panel keeps its `class="ia3ds-sam-panel"`, whose CSS (`inline_analysis_3d_sam.css:319-322`) already matches the other five panels' inline border/padding/background.

- [ ] **Step 5: Wire the toggle**

In `src/static/inline_analysis_3d_sam.js`, inside `_samWirePanel`, immediately after the `on("ia3ds-sam-run3d", …)` line (5089):

```js
  // Same shape as the five panels above it (see the triangulate toggle): the
  // checkbox controls VISIBILITY ONLY. Data flow — the video watcher, the
  // window loader, the reset on video change — must keep running while
  // collapsed, or expanding it later would show a stale panel.
  on("ia3ds-sam-toggle", "onchange", () => {
    const open = !!_samEl("ia3ds-sam-toggle")?.checked;
    _samEl("ia3ds-sam-controls")?.classList.toggle("hidden", !open);
  });
```

- [ ] **Step 6: Run the tests to verify they pass**

Run:
```bash
node --test tests/unit/test_sam_card_loads.mjs
node --test tests/unit/test_sam_panel_ids.mjs
node --test tests/unit/test_panel_state.mjs
```
Expected: PASS. `test_panel_state.mjs` is included because the reset path touches ids inside the panel that just moved.

- [ ] **Step 7: Commit**

```bash
git add dlc-3D/src/static/card_inline_analysis_3d_sam.html \
        dlc-3D/src/static/inline_analysis_3d_sam.js \
        dlc-3D/tests/unit/test_sam_card_loads.mjs \
        dlc-3D/tests/unit/test_sam_panel_ids.mjs
git commit -m "feat(sam): the SAM panel is a checkbox-gated panel like its neighbours"
```

---

### Task 4: `panel_order.mjs` — the ordering rules

Pure logic, no DOM. The DOM is the authority on which panels exist; a saved order is only an opinion about their sequence.

**Files:**
- Create: `src/static/internal/panel_order.mjs`
- Test: `tests/unit/test_panel_order.mjs` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `applyOrder(domIds: string[], savedOrder: string[]) -> string[]`
  - `reorder(ids: string[], movedId: string, beforeId: string|null) -> string[]`
  - `sameOrder(a: string[], b: string[]) -> boolean`

- [ ] **Step 1: Write the failing tests**

Create `dlc-3D/tests/unit/test_panel_order.mjs`:

```js
// Which panels a card shows, and in what order.
//
// The two ways a saved-layout feature normally breaks, both pinned below:
//
//   * a panel added in a later release is absent from every saved order, and a
//     naive "render the saved list" makes it VANISH for anyone who has ever
//     dragged a panel;
//   * a panel removed in a later release is still in the saved order, and a
//     naive render tries to place an element that is not there.
//
// The rule that avoids both: the DOM decides membership, the saved order only
// decides sequence.
import test from "node:test";
import assert from "node:assert/strict";

import { applyOrder, reorder, sameOrder } from
  "../../src/static/internal/panel_order.mjs";

const DOM = ["a", "b", "c"];

test("with nothing saved, the markup order stands", () => {
  assert.deepEqual(applyOrder(DOM, []), ["a", "b", "c"]);
  assert.deepEqual(applyOrder(DOM, null), ["a", "b", "c"]);
});

test("a saved order is applied", () => {
  assert.deepEqual(applyOrder(DOM, ["c", "a", "b"]), ["c", "a", "b"]);
});

test("an id no longer in the DOM is ignored", () => {
  assert.deepEqual(applyOrder(DOM, ["gone", "c", "a", "b"]), ["c", "a", "b"]);
});

test("a panel missing from the saved order still appears", () => {
  // The regression that would otherwise hide a newly shipped panel from every
  // user who has dragged anything.
  assert.deepEqual(applyOrder(DOM, ["c", "a"]), ["c", "a", "b"]);
});

test("panels missing from the saved order keep their markup order", () => {
  assert.deepEqual(applyOrder(["a", "b", "c", "d"], ["c"]), ["c", "a", "b", "d"]);
});

test("a duplicated id in the saved order is placed once", () => {
  assert.deepEqual(applyOrder(DOM, ["c", "c", "a"]), ["c", "a", "b"]);
});

test("an empty DOM yields an empty order", () => {
  assert.deepEqual(applyOrder([], ["a"]), []);
});

test("reorder moves a panel before another", () => {
  assert.deepEqual(reorder(DOM, "c", "a"), ["c", "a", "b"]);
  assert.deepEqual(reorder(DOM, "a", "c"), ["b", "a", "c"]);
});

test("reorder with a null target moves it to the end", () => {
  // Dropping below the last panel is the only way to reach the end, so this is
  // not an edge case -- it is one of the two moves a user makes.
  assert.deepEqual(reorder(DOM, "a", null), ["b", "c", "a"]);
});

test("reorder onto itself changes nothing", () => {
  assert.deepEqual(reorder(DOM, "b", "b"), ["a", "b", "c"]);
});

test("reordering an unknown id changes nothing", () => {
  assert.deepEqual(reorder(DOM, "zz", "a"), ["a", "b", "c"]);
});

test("reorder does not mutate its input", () => {
  const input = ["a", "b", "c"];
  reorder(input, "c", "a");
  assert.deepEqual(input, ["a", "b", "c"]);
});

test("sameOrder compares by sequence", () => {
  assert.equal(sameOrder(["a", "b"], ["a", "b"]), true);
  assert.equal(sameOrder(["a", "b"], ["b", "a"]), false);
  assert.equal(sameOrder(["a"], ["a", "b"]), false);
  assert.equal(sameOrder(null, []), true);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --test tests/unit/test_panel_order.mjs`
Expected: FAIL — cannot resolve `panel_order.mjs`.

- [ ] **Step 3: Write the module**

Create `dlc-3D/src/static/internal/panel_order.mjs`:

```js
// Which panels a card shows, and in what order.
//
// Pure so it can be tested without a DOM, and so the one rule that matters is
// stated in one place: the DOM decides WHICH panels exist, a saved order only
// decides their SEQUENCE. Let a saved list decide membership and a panel
// shipped after the user last dragged something disappears for them.

export function applyOrder(domIds, savedOrder) {
  const present = (domIds || []).filter((id) => typeof id === "string");
  const known = new Set(present);
  const seen = new Set();
  const out = [];
  for (const id of savedOrder || []) {
    if (known.has(id) && !seen.has(id)) {
      seen.add(id);
      out.push(id);
    }
  }
  for (const id of present) {
    if (!seen.has(id)) {
      seen.add(id);
      out.push(id);
    }
  }
  return out;
}

/** Move `movedId` before `beforeId`; a null target means the end. */
export function reorder(ids, movedId, beforeId) {
  const all = (ids || []).slice();
  if (!all.includes(movedId)) return all;
  const rest = all.filter((id) => id !== movedId);
  const at = beforeId == null ? -1 : rest.indexOf(beforeId);
  if (at < 0) {
    rest.push(movedId);
    return rest;
  }
  rest.splice(at, 0, movedId);
  return rest;
}

/** Sequence equality — lets the caller skip a pointless save. */
export function sameOrder(a, b) {
  const x = a || [];
  const y = b || [];
  return x.length === y.length && x.every((v, i) => v === y[i]);
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `node --test tests/unit/test_panel_order.mjs`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/static/internal/panel_order.mjs \
        dlc-3D/tests/unit/test_panel_order.mjs
git commit -m "feat(3d): panel ordering rules, with the DOM as the authority"
```

---

### Task 5: `GET/PUT /dlc-3d/card-layout`

Per-project storage for the three cards' panel orders.

**Files:**
- Modify: `src/dlc_3d_bp/routes.py` (append routes; `json`, `os`, `tempfile`, `Path`, `jsonify`, `request` are already imported — verify before adding any import)
- Test: `tests/test_card_layout_route.py` (create)

**Interfaces:**
- Consumes: `_active_project_for_user()` (`routes.py:81`).
- Produces:
  - `GET /dlc-3d/card-layout -> {"layout": {card: [ids]}}`
  - `PUT /dlc-3d/card-layout` body `{"card": str, "order": [str]}` -> `{"ok": true}`
  - Module constants `CARD_KEYS`, `LAYOUT_FILENAME` used by the tests.

- [ ] **Step 1: Write the failing tests**

Create `dlc-3D/tests/test_card_layout_route.py`:

```python
"""Per-project panel order for the three inline-analysis cards.

Stored per PROJECT, not per browser: the user asked for the order to follow the
project. That makes it shared between users of the same project, which is
deliberate -- panel order is a property of how a project is worked on.

The failure this store must never cause is worse than not saving: a bad read
must leave the card's shipped order alone rather than blank or scramble it. So
every failure path here resolves to "no opinion".
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dlc_3d_bp import routes as R  # noqa: E402

SAM = ["ia3ds-sam-panel", "ia3ds-triangulate-panel", "ia3ds-params-panel"]


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    return p


@pytest.fixture
def flask_app():
    """Not named `app` -- pytest-flask's autouse fixture keys off that name and
    would hold one app context open across calls, leaking flask.g between the
    requests below. See tests/test_dlc3d_per_user_project.py."""
    from flask import Flask
    a = Flask(__name__)
    a.register_blueprint(R.bp)
    a.config.update(TESTING=True)
    return a


@pytest.fixture
def client(flask_app, project, monkeypatch):
    monkeypatch.setattr(R, "_active_project_for_user", lambda: str(project))
    return flask_app.test_client()


@pytest.fixture
def no_project(flask_app, monkeypatch):
    monkeypatch.setattr(R, "_active_project_for_user", lambda: None)
    return flask_app.test_client()


def _put(client, card, order):
    return client.put("/dlc-3d/card-layout", json={"card": card, "order": order})


def test_round_trip(client):
    assert _put(client, "ia3ds", SAM).status_code == 200
    assert client.get("/dlc-3d/card-layout").get_json()["layout"]["ia3ds"] == SAM


def test_the_file_lands_in_the_project(client, project):
    _put(client, "ia3ds", SAM)
    stored = json.loads((project / R.LAYOUT_FILENAME).read_text())
    assert stored["ia3ds"] == SAM


def test_no_layout_yet_is_empty_not_an_error(client):
    r = client.get("/dlc-3d/card-layout")
    assert r.status_code == 200
    assert r.get_json()["layout"] == {}


def test_saving_one_card_leaves_the_others_alone(client):
    """Two cards can be open in two tabs; the second save must not erase the
    first card's order."""
    _put(client, "ia3d", ["ia3d-params-panel"])
    _put(client, "ia3ds", SAM)
    layout = client.get("/dlc-3d/card-layout").get_json()["layout"]
    assert layout["ia3d"] == ["ia3d-params-panel"]
    assert layout["ia3ds"] == SAM


def test_resaving_a_card_replaces_its_order(client):
    _put(client, "ia3ds", SAM)
    _put(client, "ia3ds", list(reversed(SAM)))
    layout = client.get("/dlc-3d/card-layout").get_json()["layout"]
    assert layout["ia3ds"] == list(reversed(SAM))


def test_an_unknown_card_is_refused(client):
    r = _put(client, "not-a-card", SAM)
    assert r.status_code == 400
    assert "not-a-card" in r.get_json()["error"]


def test_an_order_that_is_not_a_list_of_strings_is_refused(client):
    assert _put(client, "ia3ds", "ia3ds-sam-panel").status_code == 400
    assert _put(client, "ia3ds", [1, 2]).status_code == 400


def test_no_active_project_cannot_save(no_project):
    r = _put(no_project, "ia3ds", SAM)
    assert r.status_code == 400
    assert r.get_json()["error"] == "no active project"


def test_no_active_project_reads_as_empty(no_project):
    """A GET must not 400: the page loads before a project is chosen, and the
    card is perfectly usable with its shipped order."""
    r = no_project.get("/dlc-3d/card-layout")
    assert r.status_code == 200
    assert r.get_json()["layout"] == {}


def test_a_corrupt_file_reads_as_no_opinion(client, project):
    """The alternative is a 500 on page load, which would make a damaged
    preference file break the card itself."""
    (project / R.LAYOUT_FILENAME).write_text("{not json at all")
    assert client.get("/dlc-3d/card-layout").get_json()["layout"] == {}


def test_a_corrupt_file_is_overwritten_by_the_next_save(client, project):
    (project / R.LAYOUT_FILENAME).write_text("{not json at all")
    assert _put(client, "ia3ds", SAM).status_code == 200
    assert client.get("/dlc-3d/card-layout").get_json()["layout"]["ia3ds"] == SAM


def test_junk_keys_in_the_file_are_dropped_on_read(client, project):
    (project / R.LAYOUT_FILENAME).write_text(json.dumps(
        {"ia3ds": SAM, "evil": ["x"], "ia3d": "not-a-list"}))
    layout = client.get("/dlc-3d/card-layout").get_json()["layout"]
    assert set(layout) == {"ia3ds"}


def test_the_write_leaves_no_temp_file(client, project):
    _put(client, "ia3ds", SAM)
    assert [p.name for p in project.iterdir()] == [R.LAYOUT_FILENAME]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_card_layout_route.py -v`
Expected: FAIL — `AttributeError: module 'dlc_3d_bp.routes' has no attribute 'LAYOUT_FILENAME'`, 404s on the route.

- [ ] **Step 3: Write the routes**

Append to `src/dlc_3d_bp/routes.py` (place next to the other project-scoped routes, after `get_sessions` at line 464):

```python
# ── Card layout (per project) ─────────────────────────────────────────────────
#
# Which order the inline-analysis cards' panels sit in. Per PROJECT rather than
# per browser, because that is how the user asked for it: the order follows the
# work, not the machine.
#
# Every failure path resolves to "no opinion" and lets the shipped markup order
# stand. A preferences file must never be able to break the card it decorates.

CARD_KEYS = ("ia3d", "ia3dr", "ia3ds")
LAYOUT_FILENAME = "dlc3d_card_layout.json"


def _layout_path(project: str) -> Path:
    return Path(project) / LAYOUT_FILENAME


def _read_layout(project: str) -> dict:
    """Every card's saved order. Anything unrecognised is dropped, not trusted."""
    try:
        with open(_layout_path(project)) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        k: v for k, v in data.items()
        if k in CARD_KEYS and isinstance(v, list)
        and all(isinstance(i, str) for i in v)
    }


def _write_layout(project: str, data: dict) -> None:
    """Atomic, for the same reason videos.json is: a concurrent reader must see
    either the old file or the whole new one, never a truncated middle."""
    target = _layout_path(project)
    fd, tmp_name = tempfile.mkstemp(prefix=".dlc3d_card_layout.", suffix=".tmp",
                                    dir=str(Path(project)))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data, indent=2))
        os.replace(tmp_name, target)
    except Exception:
        os.unlink(tmp_name)
        raise


@bp.route("/card-layout")
def get_card_layout():
    proj = _active_project_for_user()
    return jsonify({"layout": _read_layout(proj) if proj else {}})


@bp.route("/card-layout", methods=["PUT"])
def put_card_layout():
    proj = _active_project_for_user()
    if not proj:
        return jsonify({"error": "no active project"}), 400
    body = request.get_json(silent=True) or {}
    card = body.get("card")
    order = body.get("order")
    if card not in CARD_KEYS:
        return jsonify({"error": f"unknown card {card!r}"}), 400
    if not isinstance(order, list) or not all(isinstance(i, str) for i in order):
        return jsonify({"error": "order must be a list of strings"}), 400
    # Read-modify-write one key: two cards may be open in two tabs, and a whole
    # -file overwrite would let the second save erase the first card's order.
    data = _read_layout(proj)
    data[card] = order
    _write_layout(proj, data)
    return jsonify({"ok": True})
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_card_layout_route.py -v`
Expected: PASS (13 tests).

- [ ] **Step 5: Check nothing else on the blueprint moved**

Run: `python -m pytest tests/test_dlc3d_per_user_project.py tests/test_frame_route_no_project.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/routes.py dlc-3D/tests/test_card_layout_route.py
git commit -m "feat(3d): per-project panel order behind /dlc-3d/card-layout"
```

---

### Task 6: Drag-to-reorder, wired into all three cards

**Files:**
- Create: `src/static/internal/panel_layout.mjs`
- Modify: `src/static/inline_analysis_3d.css` (drag affordance — the only one of the three stylesheets loaded page-wide, `templates/dlc_3d.html:8`)
- Modify: `src/static/inline_analysis_3d_sam.js` (`_samWireAfterInject`, line 5266)
- Modify: `src/static/inline_analysis_3d_reprojection.js` (`_reprojWireAfterInject`, line 4590)
- Modify: `src/static/inline_analysis_3d.js` (init block, line 3800-3809)
- Test: `tests/unit/test_panel_layout.mjs` (create)

**Interfaces:**
- Consumes: `applyOrder`, `reorder`, `sameOrder` from `panel_order.mjs` (Task 4); `GET/PUT /dlc-3d/card-layout` (Task 5); `#ia3ds-sam-panel` inside `#ia3ds-player-section` (Task 3).
- Produces:
  - `initPanelLayout({card, containerId, ids}) -> boolean` — idempotent, safe to call before the container exists (returns `false`).
  - `domOrder(container, ids) -> string[]` and `applyToDom(container, ids, order)`, exported for the test.

- [ ] **Step 1: Write the failing tests**

Create `dlc-3D/tests/unit/test_panel_layout.mjs`:

```js
// Drag-to-reorder, at the DOM level.
//
// The property this file exists to pin is IDENTITY. Panels hold canvases with
// live 2D contexts, listeners wired at injection time, and a VideoViewer. An
// implementation that re-rendered the markup would look right in a screenshot
// and be dead to the touch, and no assertion about ORDER would catch it.
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

import { domOrder, applyToDom } from
  "../../src/static/internal/panel_layout.mjs";

function build() {
  const dom = new JSDOM(`<!doctype html><body>
    <div id="sect">
      <div id="viewer">the video, which must never move</div>
      <div id="p1"><div>head 1</div></div>
      <div id="p2"><div>head 2</div></div>
      <div id="p3"><div>head 3</div></div>
      <div id="tail">not a movable panel</div>
    </div></body>`);
  globalThis.document = dom.window.document;
  return dom;
}

const IDS = ["p1", "p2", "p3"];

test("domOrder reports the panels in DOM order, ignoring everything else", () => {
  const dom = build();
  const sect = dom.window.document.getElementById("sect");
  assert.deepEqual(domOrder(sect, IDS), ["p1", "p2", "p3"]);
});

test("applyToDom puts the panels in the given order", () => {
  const dom = build();
  const sect = dom.window.document.getElementById("sect");
  applyToDom(sect, IDS, ["p3", "p1", "p2"]);
  assert.deepEqual(domOrder(sect, IDS), ["p3", "p1", "p2"]);
});

test("the panels are MOVED, not rebuilt", () => {
  // Identity, not markup: same node object, and anything attached to it lives.
  const dom = build();
  const sect = dom.window.document.getElementById("sect");
  const p1 = dom.window.document.getElementById("p1");
  p1.dataset.live = "yes";
  applyToDom(sect, IDS, ["p3", "p2", "p1"]);
  assert.equal(dom.window.document.getElementById("p1"), p1);
  assert.equal(dom.window.document.getElementById("p1").dataset.live, "yes");
});

test("nothing outside the movable set is disturbed", () => {
  // The viewer sits above the panels and the reprojection card has a panel
  // BELOW them. Reordering must not walk over either.
  const dom = build();
  const sect = dom.window.document.getElementById("sect");
  applyToDom(sect, IDS, ["p3", "p2", "p1"]);
  const ids = Array.from(sect.children).map((el) => el.id);
  assert.equal(ids[0], "viewer");
  assert.equal(ids[ids.length - 1], "tail");
});

test("an order naming a panel that is not there is survivable", () => {
  const dom = build();
  const sect = dom.window.document.getElementById("sect");
  applyToDom(sect, IDS, ["gone", "p2", "p1", "p3"]);
  assert.deepEqual(domOrder(sect, IDS), ["p2", "p1", "p3"]);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --test tests/unit/test_panel_layout.mjs`
Expected: FAIL — cannot resolve `panel_layout.mjs`.

- [ ] **Step 3: Write the module**

Create `dlc-3D/src/static/internal/panel_layout.mjs`:

```js
// Drag-to-reorder for a card's panel stack, saved per project.
//
// Two rules the implementation must keep:
//
//   1. Panels are MOVED (insertBefore relocates the same node), never
//      re-rendered. Each one holds canvases with live 2D contexts and handlers
//      wired at injection time; rebuilding the markup would leave a panel that
//      looks right and does nothing.
//   2. Only the ids passed in are movable, and they only ever occupy the
//      positions they already hold — the viewer above them, and the
//      reprojection panel below them in that card, must not be walked over.
import { applyOrder, reorder, sameOrder } from "./panel_order.mjs";

const ENDPOINT = "/dlc-3d/card-layout";
const DRAGGING = "ia3d-panel-dragging";
const BEFORE = "ia3d-panel-drop-before";
const AFTER = "ia3d-panel-drop-after";

/** The movable panels, in the order they currently sit in. */
export function domOrder(container, ids) {
  const wanted = new Set(ids || []);
  return Array.from(container.children)
    .filter((el) => wanted.has(el.id))
    .map((el) => el.id);
}

/** Rearrange the panels to `order`, moving the existing elements. */
export function applyToDom(container, ids, order) {
  const here = domOrder(container, ids);
  if (!here.length) return;
  const last = document.getElementById(here[here.length - 1]);
  // Anchor on whatever follows the block. Inserting each panel before that
  // anchor, in sequence, both preserves the block's position in the section and
  // leaves the panels in exactly `order`.
  const tail = last ? last.nextSibling : null;
  (order || []).forEach((id) => {
    const el = document.getElementById(id);
    if (el && el.parentElement === container) container.insertBefore(el, tail);
  });
}

let _layout = null;

async function loadLayout() {
  if (_layout) return _layout;
  _layout = (async () => {
    try {
      const r = await fetch(ENDPOINT);
      if (!r.ok) return {};
      return (await r.json()).layout || {};
    } catch {
      return {};                 // the shipped order is always a valid answer
    }
  })();
  return _layout;
}

const _timers = {};

function saveOrder(card, order) {
  clearTimeout(_timers[card]);
  _timers[card] = setTimeout(() => {
    fetch(ENDPOINT, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card, order }),
    }).catch(() => {});          // a failed save must not disturb the page
  }, 400);
}

function clearMarkers(container) {
  container.querySelectorAll(`.${BEFORE}, .${AFTER}`).forEach((el) => {
    el.classList.remove(BEFORE, AFTER);
  });
}

function wirePanel(container, panel, card, ids) {
  // Every one of these panels opens with its toggle row — a <div> for five of
  // them, a bare <label> for Create Clip. Both are the right grab target.
  const head = panel.firstElementChild;
  if (!head || head.dataset.panelDrag === "1") return;
  head.dataset.panelDrag = "1";
  head.classList.add("ia3d-panel-grab");

  head.addEventListener("mousedown", (ev) => {
    // Never arm a drag from the checkbox itself: the drag would swallow the
    // click that opens the panel, and ticking a box is the commoner action.
    panel.draggable = ev.target.tagName !== "INPUT";
    // Disarm on release. Left armed after a click that never became a drag, the
    // WHOLE panel stays draggable — and then a drag inside a number input or
    // across the viewer would pick the panel up instead.
    const off = () => {
      panel.draggable = false;
      document.removeEventListener("mouseup", off);
    };
    document.addEventListener("mouseup", off);
  });
  panel.addEventListener("dragstart", (ev) => {
    ev.dataTransfer.setData("text/plain", panel.id);
    ev.dataTransfer.effectAllowed = "move";
    panel.classList.add(DRAGGING);
  });
  panel.addEventListener("dragend", () => {
    panel.draggable = false;
    panel.classList.remove(DRAGGING);
    clearMarkers(container);
  });
  panel.addEventListener("dragover", (ev) => {
    ev.preventDefault();
    ev.dataTransfer.dropEffect = "move";
    const rect = panel.getBoundingClientRect();
    const low = ev.clientY - rect.top > rect.height / 2;
    panel.classList.toggle(AFTER, low);
    panel.classList.toggle(BEFORE, !low);
  });
  panel.addEventListener("dragleave", () => panel.classList.remove(BEFORE, AFTER));
  panel.addEventListener("drop", (ev) => {
    ev.preventDefault();
    const low = panel.classList.contains(AFTER);
    clearMarkers(container);
    const moved = ev.dataTransfer.getData("text/plain");
    if (!moved || moved === panel.id) return;
    const here = domOrder(container, ids);
    // Dropping on the lower half means "after this one" — without it there is
    // no gesture that reaches the end of the list.
    const at = here.indexOf(panel.id);
    const target = low ? (here[at + 1] ?? null) : panel.id;
    // Already in that slot. Falling through would pass `moved` as its own
    // target, and reorder would then send it to the end — a panel jumping to
    // the bottom when the user dropped it exactly where it already was.
    if (target === moved) return;
    const next = reorder(here, moved, target);
    applyToDom(container, ids, next);
    saveOrder(card, next);
  });
}

/**
 * Make a card's panel stack reorderable. Idempotent; returns false when the
 * card's markup is not in the document yet (two of the three cards inject
 * themselves at runtime).
 */
export function initPanelLayout({ card, containerId, ids }) {
  const container = document.getElementById(containerId);
  if (!container) return false;
  if (container.dataset.panelLayout === "1") return true;
  container.dataset.panelLayout = "1";

  const present = domOrder(container, ids);
  present.forEach((id) => {
    const el = document.getElementById(id);
    if (el) wirePanel(container, el, card, ids);
  });

  loadLayout().then((layout) => {
    const wanted = applyOrder(present, (layout || {})[card] || []);
    if (!sameOrder(wanted, domOrder(container, ids))) {
      applyToDom(container, ids, wanted);
    }
  });
  return true;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `node --test tests/unit/test_panel_layout.mjs`
Expected: PASS (5 tests).

- [ ] **Step 5: Add the drag affordance CSS**

Append to `src/static/inline_analysis_3d.css`:

```css
/* Panel reordering. Shared by all three inline-analysis cards, so it lives in
   the one stylesheet the page always loads. The drop markers are inset shadows
   rather than borders: a border would change the panel's height mid-drag and
   make the stack twitch under the cursor. */
.ia3d-panel-grab { cursor: grab; }
.ia3d-panel-grab:active { cursor: grabbing; }
.ia3d-panel-dragging { opacity: .55; }
.ia3d-panel-drop-before { box-shadow: inset 0 2px 0 0 var(--accent); }
.ia3d-panel-drop-after { box-shadow: inset 0 -2px 0 0 var(--accent); }
```

- [ ] **Step 6: Wire the SAM card**

In `src/static/inline_analysis_3d_sam.js`, add to the imports (next to the other `./internal/` imports around line 42):

```js
import { initPanelLayout } from "./internal/panel_layout.mjs";
```

and add to `_samWireAfterInject` (line 5266), after the `_samWirePanel()` line:

```js
  try {
    initPanelLayout({
      card: "ia3ds",
      containerId: "ia3ds-player-section",
      ids: ["ia3ds-triangulate-panel", "ia3ds-params-panel", "ia3ds-pose3d-panel",
            "ia3ds-curation-panel", "ia3ds-clip-panel-wrap", "ia3ds-sam-panel"],
    });
  } catch (e) { console.warn("[sam] panel layout", e); }
```

- [ ] **Step 7: Wire the reprojection card**

In `src/static/inline_analysis_3d_reprojection.js`, add the same import, and add to `_reprojWireAfterInject` (line 4590) after `_reprojWirePanel()`:

```js
  try {
    initPanelLayout({
      card: "ia3dr",
      containerId: "ia3dr-player-section",
      ids: ["ia3dr-triangulate-panel", "ia3dr-params-panel", "ia3dr-pose3d-panel",
            "ia3dr-curation-panel", "ia3dr-clip-panel-wrap"],
    });
  } catch (e) { console.warn("[reproj] panel layout", e); }
```

`ia3dr-reproj-panel` is deliberately absent: it is not checkbox-gated, and
gating it to match is a behaviour change outside this work. It stays the last
child, below the movable block — which is why `applyToDom` anchors on
`nextSibling` rather than appending.

- [ ] **Step 8: Wire the original card**

In `src/static/inline_analysis_3d.js`, add the same import, then add a helper next to the init block (line 3799) and call it from both branches:

```js
function _ia3dInitPanelLayout() {
  try {
    initPanelLayout({
      card: "ia3d",
      containerId: "ia3d-player-section",
      ids: ["ia3d-triangulate-panel", "ia3d-params-panel", "ia3d-pose3d-panel",
            "ia3d-curation-panel", "ia3d-clip-panel-wrap"],
    });
  } catch (e) { console.warn("[ia3d] panel layout", e); }
}

document.addEventListener("DOMContentLoaded", () => {
  _wireLauncher();
  _wireStereoDispatch();
  _ia3dPlaceNavButton();
  _ia3dInitPanelLayout();
});
if (document.readyState !== "loading") {
  // Module evaluated after DOMContentLoaded — run the nav placement now too
  // (the DOMContentLoaded listener above won't fire). Idempotent.
  _ia3dPlaceNavButton();
  _ia3dInitPanelLayout();
}
```

This card is server-rendered, so its container exists at both call sites;
`initPanelLayout` is idempotent, so calling it twice is harmless.

- [ ] **Step 9: Run every test that touches the three cards**

Run:
```bash
for f in tests/unit/test_panel_layout.mjs tests/unit/test_panel_order.mjs \
         tests/unit/test_sam_card_loads.mjs tests/unit/test_sam_panel_ids.mjs \
         tests/unit/test_panel_state.mjs tests/unit/test_no_const_reassignment.mjs; do
  echo "== $f"; node --test "$f" || break
done
python -m pytest tests/test_card_layout_route.py tests/test_reproj_card_bootstrap.py \
                 tests/test_reproj_card_namespace.py -v
```
Expected: all PASS. `test_sam_card_loads.mjs` is the important one — it executes the SAM module with the new import and would catch a bad import path or a temporal-dead-zone error that no source-text assertion can see. It is also the only test that runs `initPanelLayout` end to end: its `globalThis.fetch` stub (line 77) answers the layout GET with `{}`, which exercises the "no saved order, leave the markup alone" path. **Do not remove that stub** — without it the call rejects and the branch goes uncovered.

- [ ] **Step 10: Run the whole `.mjs` suite**

Run:
```bash
for f in tests/unit/*.mjs; do
  node --test "$f" >/dev/null 2>&1 || echo "FAILED: $f"
done
```
Expected: no output. (Directory mode finds 0 tests under Node 16 — that is why this loops.)

- [ ] **Step 11: Commit**

```bash
git add dlc-3D/src/static/internal/panel_layout.mjs \
        dlc-3D/src/static/inline_analysis_3d.css \
        dlc-3D/src/static/inline_analysis_3d.js \
        dlc-3D/src/static/inline_analysis_3d_reprojection.js \
        dlc-3D/src/static/inline_analysis_3d_sam.js \
        dlc-3D/tests/unit/test_panel_layout.mjs
git commit -m "feat(3d): drag the analysis panels into order, saved per project"
```

---

### Task 7: Deploy and verify

**Files:** none — deployment only.

**Interfaces:**
- Consumes: everything above, all tests green.
- Produces: a running `/dlc-3d/` serving the new routes and static files.

- [ ] **Step 1: Confirm nothing is running that a restart would kill**

Run:
```bash
docker ps --format '{{.Names}}\t{{.Status}}' | grep -E 'dlc-3d|worker|sam-training'
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml \
  logs --tail 20 dlc-3d
```
The `dlc-3d` web container holds no background threads (no `Thread(` anywhere in `src/dlc_3d_bp/*.py`) — LP jobs run in `dlc-3d-worker`, triangulate/analyze on the main `worker`. **Verify that is still true** before restarting:

```bash
grep -rn "Thread(" /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/dlc_3d_bp/*.py
```
Expected: no matches. If there are matches, stop and report rather than restarting.

**Never** restart or recreate `worker`, `worker-tf`, `dlc-3d-worker`, or `sam-training` in this task. Check the Jobs card for in-flight training or analysis first.

- [ ] **Step 2: Dispatch the deployment subagent**

Dispatch a subagent with this brief:

> Deploy the panel-reorder work to the running stack, and report what you
> verified rather than what you expect.
>
> 1. `src/static/` is a whole-directory mount — confirm the new files are
>    served, do not rebuild for them:
>    `curl -sf -o /dev/null -w '%{http_code}\n' http://localhost:5000/dlc-3d/static/internal/panel_order.mjs`
>    and the same for `internal/panel_layout.mjs`. Both must be 200.
> 2. `src/dlc_3d_bp` is a whole-directory mount but the Flask app has no
>    reloader, so the new routes need `docker compose restart dlc-3d` (from
>    `/home/sam/docker-images/deeplabcut-webapp-docker`). Before restarting,
>    confirm no in-flight work would be lost (see step 1). Restart nothing else.
> 3. Verify the routes against the LIVE app:
>    `curl -s http://localhost:5000/dlc-3d/card-layout` returns
>    `{"layout": …}` with HTTP 200.
> 4. Verify the served SAM card actually contains the changes:
>    `curl -s http://localhost:5000/dlc-3d/static/card_inline_analysis_3d_sam.html`
>    must contain `ia3ds-sam-toggle`, `ia3ds-sam-controls`, `data-clearcam` must
>    appear in the served `inline_analysis_3d_sam.js`, and
>    `ia3ds-pellet-replace-cam` must be ABSENT from the card.
> 5. Confirm the SAM panel is inside the player section in the SERVED markup,
>    not just on disk — the file is mounted, so a stale copy means a mount
>    problem, which has happened before with single-file mounts.
> 6. Report: each check, the command, and its actual output. If any check
>    fails, stop and report; do not attempt a rebuild.

- [ ] **Step 3: Manual verification in the browser**

Reload `http://localhost:5000/dlc-3d/`, open a video pair in the SAM card, and check:

1. The SAM panel is collapsed, with a `SAM 3 + DINOv3` checkbox; ticking it reveals the panel; the status text is readable while collapsed.
2. Each camera card has its own `clear box` button; clicking cam1's clears cam1's box and leaves cam0's alone.
3. `Re-aim box from clicks + rerun` sits at the left of its row, with the note beneath it.
4. Dragging a panel's header row reorders the stack; dropping on the lower half of the last panel moves a panel to the end.
5. Clicking a panel's checkbox still toggles it — a click must not be eaten by the drag.
6. Reload the page: the order is still what you left it.
7. Switch to a different video: the panel order is unchanged and the panel contents reset (the Task-3 relocation must not have disturbed `_samResetPanel`).

- [ ] **Step 4: Report**

Report what was verified and what was not. Anything only checkable by hand (points 4 and 5 above) is stated as unverified-by-test, not as done.

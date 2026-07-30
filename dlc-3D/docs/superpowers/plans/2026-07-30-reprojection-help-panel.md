# Reprojection Help Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A help box in the empty space beside the per-camera groups, showing a default summary and swapping to a parameter's explanation plus a worked example when a control is hovered or focused.

**Architecture:** Help text lives in a pure `.mjs` data module so it can be unit-tested and cross-checked against the markup. The box is a third flex child of the existing `.ia3dr-percam-wrap`, so it fills the empty space and wraps on narrow cards with no layout restructuring. One delegated listener drives it.

**Tech Stack:** Vanilla ES modules, `node --test` for pure data, pytest for markup and wiring assertions.

## Global Constraints

- **This card is LIVE and in use.** `dlc-3D/src/static/` is a bind mount, so every commit reaches users on their next browser reload. Leave the panel working at every commit and run the syntax check each time.
- **Never modify** `src/templates/partials/card_inline_analysis_3d.html`, `src/static/inline_analysis_3d.js`, `src/static/inline_analysis_3d.css`, anything under `src/static/components/viewer/` (shared, loaded by the original card too), or anything under `src/dlc_3d_bp/`.
- Keep the `ia3dr-` namespace. No new `ia3d-` (single r) identifiers.
- **Do NOT restart, rebuild or stop any container, and run NO docker command.** This is a pure frontend feature; it goes live on browser reload. Deployment verification is Task 3 and is done by someone else.
- Ten tests fail on this host for unrelated pre-existing reasons (numpy 2.x, absent playwright browser, ffmpeg). The two playwright e2e tests are FLAKY — a run may show 9, 10 or 11 failures. What matters is that no *new* test name appears. Compare names, not counts.
- Run pytest and `node --test` from `dlc-3D/`.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/static/internal/reproj_help.mjs` | **New.** Pure help content: `HELP_DEFAULT` and `HELP`. No DOM. |
| `tests/unit/test_reproj_help.mjs` | **New.** Real assertions on that content. |
| `src/static/card_inline_analysis_3d_reprojection.html` | Help box element; `data-help` on each control. |
| `src/static/inline_analysis_3d_reprojection.css` | Help box styles. |
| `src/static/inline_analysis_3d_reprojection.js` | Delegated listener; render into the box. |
| `tests/test_reproj_panel_markup.py` | Box exists; every control has `data-help`. |
| `tests/test_reproj_panel_wiring.py` | Listener covers focus; cross-file key check. |

---

### Task 1: Help content module

**Files:**
- Create: `src/static/internal/reproj_help.mjs`
- Test: `tests/unit/test_reproj_help.mjs`

**Interfaces:**
- Consumes: nothing.
- Produces: `HELP_DEFAULT = {title, body}` and `HELP = {key: {title, body, example}}` for exactly these seven keys: `trusted_cam`, `k1`, `k2`, `gate_ref`, `low_tgt`, `high_conf`, `rescue_floor`.

- [ ] **Step 1: Write the failing test**

```javascript
// tests/unit/test_reproj_help.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { HELP, HELP_DEFAULT } from "../../src/static/internal/reproj_help.mjs";

const KEYS = ["trusted_cam", "k1", "k2", "gate_ref", "low_tgt", "high_conf",
              "rescue_floor"];

test("HELP covers exactly the panel's parameters", () => {
  assert.deepEqual(Object.keys(HELP).sort(), [...KEYS].sort());
});

test("every entry has a title, body and worked example", () => {
  for (const [key, e] of Object.entries(HELP)) {
    assert.ok(e.title && e.title.trim().length, `${key}: empty title`);
    assert.ok(e.body && e.body.trim().length > 20, `${key}: body too thin`);
    assert.ok(e.example && e.example.trim().length > 10,
              `${key}: an example is what makes it land`);
  }
});

test("the default state has something to say", () => {
  assert.ok(HELP_DEFAULT.title && HELP_DEFAULT.title.trim().length);
  assert.ok(HELP_DEFAULT.body && HELP_DEFAULT.body.trim().length > 20);
});

test("the two counter-intuitive parameters say so explicitly", () => {
  // high_conf loosens the rule when lowered; low_tgt does not affect rejection.
  // If these ever stop being called out, the panel has lost its main value.
  assert.match(HELP.high_conf.body + HELP.high_conf.example, /loosen|wider|inflat/i);
  assert.match(HELP.low_tgt.body, /reject/i);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && node --test tests/unit/test_reproj_help.mjs`
Expected: FAIL — cannot find module `reproj_help.mjs`

- [ ] **Step 3: Write the module**

```javascript
// src/static/internal/reproj_help.mjs
// Contextual help for the reprojection panel's controls.
//
// Condensed from docs/reprojection-parameters.md — update BOTH together. Every
// entry carries a worked example measured on the eggtart-1 reference session,
// because the examples are what make the parameters land.

export const HELP_DEFAULT = {
  title: "Epipolar reprojection",
  body:
    "The trusted camera's marker induces an epipolar line in the other view. " +
    "Markers far off that line are deleted; markers on it that DeepLabCut " +
    "scored low are rescued. Nothing is ever moved. Hover or focus a control " +
    "to see what it does.",
};

export const HELP = {
  trusted_cam: {
    title: "Trusted camera",
    body:
      "Induces the epipolar line. The other camera is the one judged and " +
      "corrected. Per-bodypart overrides flip this for individual bodyparts, " +
      "which also flips which camera's thresholds apply.",
    example:
      "On this session cam1 is the better view: mean likelihood 0.51 against " +
      "cam0's 0.39.",
  },
  k1: {
    title: "Trust band k₁",
    body:
      "A multiplier, not pixels. t_ok = median + k₁ × MAD of each bodypart's " +
      "own residual spread. Inside this band, geometry confirms the marker.",
    example:
      "×3 gives 3.30 px on the Pellet but 21.53 px on the Wrist — the same " +
      "setting, scaled to how tightly each part localises.",
  },
  k2: {
    title: "Reject band k₂",
    body:
      "t_bad = median + k₂ × MAD. Beyond this the marker is geometrically " +
      "impossible: its coordinates are cleared and its likelihood set to 0. " +
      "Keep k₂ above k₁.",
    example: "×8 gives 7.28 px on the Pellet and 45.66 px on the Wrist.",
  },
  gate_ref: {
    title: "gate_ref — on the TRUSTED camera",
    body:
      "Below this likelihood the trusted marker cannot induce a line worth " +
      "believing, so the other camera's marker is left completely untouched. " +
      "This is the coverage dial: raise it for fewer, safer judgements.",
    example:
      "At 0.6, 3,293,909 of 4,026,240 frame × bodypart slots were left " +
      "unjudged — mostly frames where the animal is not reaching.",
  },
  low_tgt: {
    title: "low_tgt — on the JUDGED camera",
    body:
      "The ceiling for what is worth rescuing. Below it, a marker inside the " +
      "trust band becomes a rescue candidate; at or above it, the marker is " +
      "simply confirmed and nothing is written. It does not affect rejection.",
    example:
      "Raise it to admit more rescue candidates. A marker beyond t_bad is " +
      "still deleted whatever its likelihood.",
  },
  high_conf: {
    title: "high_conf — per camera",
    body:
      "Chooses the calibration sample only: frames where each camera clears " +
      "its own bar. Their spread sets t_ok and t_bad. Lowering it admits " +
      "sloppier correspondences, which inflates the thresholds and LOOSENS " +
      "the rule — the opposite of what it sounds like.",
    example:
      "Wrist, cam0 0.9 → 0.7: sample 2,803 → 4,924 frames, t_ok 21.5 → 22.2 px.",
  },
  rescue_floor: {
    title: "rescue_floor — on the JUDGED camera",
    body:
      "The likelihood written onto a successful rescue. It never lowers an " +
      "already-higher value. Set it above whatever threshold your downstream " +
      "filtering uses, or the rescued marker will be discarded anyway.",
    example:
      "Different floors per camera let you tell rescued markers apart by " +
      "which view they came from.",
  },
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && node --test tests/unit/test_reproj_help.mjs`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/static/internal/reproj_help.mjs dlc-3D/tests/unit/test_reproj_help.mjs
git commit -m "feat(reprojection): help content for the panel's parameters"
```

---

### Task 2: Help box, markup and wiring

**Files:**
- Modify: `src/static/card_inline_analysis_3d_reprojection.html`
- Modify: `src/static/inline_analysis_3d_reprojection.css`
- Modify: `src/static/inline_analysis_3d_reprojection.js`
- Test: `tests/test_reproj_panel_markup.py`, `tests/test_reproj_panel_wiring.py`

**Interfaces:**
- Consumes: `HELP`, `HELP_DEFAULT` (Task 1).
- Produces: `#ia3dr-reproj-help`, `data-help` attributes on the controls, and `_reprojWireHelp()`.

**One commit** because the card is live: markup with no listener would show a permanently static box.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reproj_panel_markup.py`:

```python
def test_help_box_exists_beside_the_per_camera_groups(card):
    assert 'id="ia3dr-reproj-help"' in card
    # It must be inside the flex wrap so it fills the space beside cam0/cam1.
    wrap = card.split('class="ia3dr-percam-wrap"')[1].split("</div>")[0]
    assert "ia3dr-reproj-help" in card
    assert card.index('class="ia3dr-percam-wrap"') < card.index('id="ia3dr-reproj-help"')


def test_help_box_announces_changes(card):
    frag = card.split('id="ia3dr-reproj-help"')[0][-200:]
    assert "aria-live" in frag or "aria-live" in card.split('id="ia3dr-reproj-help"')[1][:200]


def test_every_control_carries_a_help_key(card):
    """A control with no data-help silently shows the default summary, which
    reads as 'this one has no explanation'."""
    for element_id in ("ia3dr-reproj-ref-cam", "ia3dr-reproj-k1", "ia3dr-reproj-k2",
                       "ia3dr-reproj-cam0-gate-ref", "ia3dr-reproj-cam1-rescue-floor"):
        frag = card.split('id="{}"'.format(element_id))[1][:200]
        assert "data-help" in frag, "{} has no data-help".format(element_id)
```

Append to `tests/test_reproj_panel_wiring.py`:

```python
def test_help_keys_in_markup_all_exist_in_the_help_module():
    """CROSS-FILE GUARD. When someone adds a parameter and forgets its help
    text, this fails — instead of a user meeting a blank box."""
    import re
    from pathlib import Path
    static = Path(__file__).parent.parent / "src" / "static"
    card = (static / "card_inline_analysis_3d_reprojection.html").read_text()
    mod = (static / "internal" / "reproj_help.mjs").read_text()

    used = set(re.findall(r'data-help="([^"]+)"', card))
    assert used, "no data-help attributes found at all"
    defined = set(re.findall(r"^\s{2}(\w+):\s*\{", mod, re.M))
    missing = used - defined
    assert not missing, "markup uses help keys with no entry: {}".format(sorted(missing))


def test_help_listener_covers_focus_not_just_hover(js):
    """Focus is the only route for keyboard users, and tabbing through the
    inputs should teach the same things as mousing over them."""
    block = js.split("REPROJECTION PANEL")[1]
    assert "focusin" in block and "mouseover" in block
    assert "_reprojWireHelp" in block


def test_help_restores_the_default_on_leave(js):
    block = js.split("REPROJECTION PANEL")[1]
    assert "HELP_DEFAULT" in block
    assert "focusout" in block or "mouseout" in block
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_markup.py tests/test_reproj_panel_wiring.py -q`
Expected: FAIL — the help box and `data-help` attributes do not exist

- [ ] **Step 3: Add the help box and the `data-help` attributes**

In `src/static/card_inline_analysis_3d_reprojection.html`, add the box as the
LAST child inside `<div class="ia3dr-percam-wrap">`, after the cam1 `</fieldset>`:

```html
          <div class="ia3dr-help" id="ia3dr-reproj-help" aria-live="polite"></div>
```

Then add `data-help` to each control. On the trusted-camera select add
`data-help="trusted_cam"`; on `ia3dr-reproj-k1` add `data-help="k1"`; on
`ia3dr-reproj-k2` add `data-help="k2"`. On each of the eight per-camera inputs
add the key matching its parameter — both cameras' inputs share a key, e.g. both
`ia3dr-reproj-cam0-gate-ref` and `ia3dr-reproj-cam1-gate-ref` get
`data-help="gate_ref"`, and likewise `low_tgt`, `high_conf`, `rescue_floor`.

- [ ] **Step 4: Add the styles**

Append to `src/static/inline_analysis_3d_reprojection.css`:

```css
#ia3dr-reproj-panel .ia3dr-help {
  flex: 1 1 16rem; min-width: 14rem;
  border: 1px solid rgba(255, 255, 255, .14);
  border-radius: 6px; padding: .5rem .7rem;
  font-size: .85em; line-height: 1.4;
  background: rgba(255, 255, 255, .03);
}
#ia3dr-reproj-panel .ia3dr-help-title {
  font-weight: 600; margin-bottom: .25rem;
}
#ia3dr-reproj-panel .ia3dr-help-example {
  margin-top: .4rem; padding-top: .35rem;
  border-top: 1px solid rgba(255, 255, 255, .12);
  opacity: .8; font-style: italic;
}
```

- [ ] **Step 5: Wire it**

Add the import alongside the other `./internal/` imports in
`src/static/inline_analysis_3d_reprojection.js`:

```javascript
import { HELP, HELP_DEFAULT } from "./internal/reproj_help.mjs";
```

Add to the REPROJECTION PANEL block:

```javascript
// ── Contextual help ─────────────────────────────────────────────────────────
// One delegated listener, so adding a parameter later needs a data-help
// attribute on the markup and nothing else. Focus is handled as well as hover:
// it is the only route for keyboard users.

function _reprojRenderHelp(key) {
  const box = document.getElementById("ia3dr-reproj-help");
  if (!box) return;
  const e = (key && HELP[key]) || HELP_DEFAULT;
  const parts = [
    `<div class="ia3dr-help-title"></div>`,
    `<div class="ia3dr-help-body"></div>`,
  ];
  if (e.example) parts.push(`<div class="ia3dr-help-example"></div>`);
  box.innerHTML = parts.join("");
  // textContent, not innerHTML, so the copy can never inject markup.
  box.querySelector(".ia3dr-help-title").textContent = e.title;
  box.querySelector(".ia3dr-help-body").textContent = e.body;
  if (e.example) box.querySelector(".ia3dr-help-example").textContent = e.example;
}

function _reprojWireHelp() {
  const panel = _reprojEl.panel();
  if (!panel) return;
  const keyOf = (ev) => ev.target?.closest?.("[data-help]")?.dataset?.help || null;
  const show = (ev) => { const k = keyOf(ev); if (k) _reprojRenderHelp(k); };
  const reset = () => _reprojRenderHelp(null);
  panel.addEventListener("mouseover", show);
  panel.addEventListener("focusin", show);
  panel.addEventListener("mouseout", reset);
  panel.addEventListener("focusout", reset);
  _reprojRenderHelp(null);
}
```

Call it from `_reprojWirePanel()`, next to the existing wiring calls:

```javascript
  _reprojWireHelp();
```

- [ ] **Step 6: Run the tests**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_markup.py tests/test_reproj_panel_wiring.py -q`
Expected: PASS

- [ ] **Step 7: Verify the module parses**

Run: `cd dlc-3D && node --input-type=module --check < src/static/inline_analysis_3d_reprojection.js && echo "parses OK"`
Expected: `parses OK`

- [ ] **Step 8: Run everything**

Run:
```bash
cd dlc-3D && node --test tests/unit/*.mjs 2>&1 | tail -5
python3 -m pytest -q 2>&1 | grep -E "^FAILED" | sort
```
Expected: the `.mjs` tests pass, and every FAILED name is one of the ten
pre-existing ones. Compare NAMES, not the count — the two playwright e2e tests
are flaky and the total legitimately varies between 9 and 11.

- [ ] **Step 9: Commit**

```bash
git add dlc-3D/src/static/card_inline_analysis_3d_reprojection.html \
        dlc-3D/src/static/inline_analysis_3d_reprojection.css \
        dlc-3D/src/static/inline_analysis_3d_reprojection.js \
        dlc-3D/tests/test_reproj_panel_markup.py \
        dlc-3D/tests/test_reproj_panel_wiring.py
git commit -m "feat(reprojection): contextual help box in the panel"
```

---

### Task 3: Verify both frontend features are live

**Files:** none — this task changes no code.

**Interfaces:**
- Consumes: Tasks 1–2, plus the earlier line-colour/label work
  (`epiline_label.mjs`), which has not yet had its live check.
- Produces: confirmation that the running container serves all the new files.

**No restart is needed or wanted.** Both features are pure frontend and
`src/static/` is a bind mount, so the container already serves them; a browser
reload picks them up. The container was last restarted to deploy a backend
change and must not be restarted for this.

- [ ] **Step 1: Confirm the tree is clean and green**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git status --porcelain | grep -v '^??' || echo "clean"
cd dlc-3D && node --test tests/unit/test_reproj_help.mjs tests/unit/test_epiline_label.mjs 2>&1 | tail -4
```

Expected: clean tree; both `.mjs` suites pass.

- [ ] **Step 2: Confirm the container serves both new modules**

```bash
docker exec deeplabcut-webapp-docker-dlc-3d-1 sh -c '
  ls -l /app/static/internal/reproj_help.mjs /app/static/internal/epiline_label.mjs
  grep -c "data-help" /app/static/card_inline_analysis_3d_reprojection.html
  grep -c "_reprojWireHelp\|_reprojBodypartColor" /app/static/inline_analysis_3d_reprojection.js'
```

Expected: both files listed; `data-help` count at least 11 (three top controls
plus eight per-camera inputs); the JS grep at least 2.

- [ ] **Step 3: Confirm they are served over HTTP**

```bash
docker exec deeplabcut-webapp-docker-dlc-3d-1 python3 -c "
import urllib.request as u
for path, needle in (
    ('/dlc-3d/static/internal/reproj_help.mjs', 'export const HELP'),
    ('/dlc-3d/static/internal/epiline_label.mjs', 'export function labelAnchor'),
    ('/dlc-3d/static/card_inline_analysis_3d_reprojection.html', 'ia3dr-reproj-help'),
):
    r = u.urlopen('http://localhost:5050' + path, timeout=15)
    body = r.read().decode()
    print(path.split('/')[-1], r.status, len(body), 'bytes,', needle in body)
"
```

Expected: `200` for each and `True` for each needle.

- [ ] **Step 4: Confirm nothing else was disturbed**

```bash
docker ps --format '{{.Names}}\t{{.Status}}' | grep deeplabcut
ls "/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/tdcs/070126" | grep -c reprojected
```

Expected: `dlc-3d` still up from its earlier start with NO new restart, the other
five services untouched, and the reprojected-file count still **4**. Report the
number you actually observe — never the expected one.

**Do NOT use `/reproject/run` as a health probe.** It writes
`<stem>_reprojected.*` beside the source data and overwrites any previous set.
`/reproject/thresholds` is the read-only endpoint. This warning exists because
that mistake has already been made once on this session.

- [ ] **Step 5: No commit** — this task produces no repository change.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
| --- | --- |
| Help box as a third flex child, `flex: 1 1 16rem` | 2 (markup + CSS) |
| `aria-live="polite"` | 2, with a test |
| Default summary shown on open and restored on leave | 2 |
| Hover AND focus both trigger | 2, with a test naming `focusin` |
| Delegated listener reading `data-help` | 2 |
| Both cameras' inputs share a key | 2 (Step 3 states it explicitly) |
| Seven content entries with title/body/example | 1 |
| The two counter-intuitive parameters called out | 1, with a dedicated test |
| Pure data module, testable | 1 |
| Cross-file check: every `data-help` key exists in `HELP` | 2 |
| Live verification (also covers the earlier colour/label work) | 3 |

**Placeholder scan:** none. Every step has runnable code or an exact command.

**Type consistency:** `HELP_DEFAULT = {title, body}` and
`HELP = {key: {title, body, example}}` are defined in Task 1 and consumed by
`_reprojRenderHelp` in Task 2 with exactly those field names. The seven keys in
Task 1's module are the same seven the Task 2 markup applies via `data-help`, and
the Task 2 cross-file test enforces that correspondence.

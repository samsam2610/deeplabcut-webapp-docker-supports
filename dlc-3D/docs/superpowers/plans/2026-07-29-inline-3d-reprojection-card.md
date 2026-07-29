# 3D Inline Analysis - Reprojection Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a namespace-isolated clone of the *3D Inline Analysis* card, launched by a button directly below the existing one, extended with an epipolar reprojection panel and a live epipolar-line overlay.

**Architecture:** A byte-for-byte clone of `card_inline_analysis_3d.html`, `inline_analysis_3d.js` and `inline_analysis_3d.css`, mechanically renamed `ia3d-` → `ia3dr-`. The card markup ships as an HTML **fragment under `src/static/`** that the cloned JS fetches and injects, because `templates/partials/*.html` are bind-mounted file-by-file and a new partial would need a `docker-compose.yml` edit. Two approved behavioural divergences prevent the clone from disturbing the card people are using. The reprojection panel talks to the endpoints from the engine plan.

**Tech Stack:** Vanilla ES modules, the shared `VideoViewer` library in `src/static/components/viewer/`, Jinja (one line), pytest for markup and wiring assertions.

## Global Constraints

- **Requires the engine plan (`2026-07-29-inline-3d-reprojection-engine.md`) to be complete.** Tasks 5–6 call `POST /dlc-3d/reproject/thresholds`, `POST /dlc-3d/reproject/run` and `GET /dlc-3d/reproject/epiline`.
- **Do not modify `card_inline_analysis_3d.html`, `inline_analysis_3d.js` or `inline_analysis_3d.css`.** People are using that card right now. The only permitted edit to an existing file is a single `<script>` line in `dlc_3d.html`.
- **Do not restart the `dlc-3d` container.** Everything here is built dormant. The final restart is the user's call — Task 7 prepares it and stops.
- **Do not clone the shared viewer library.** `components/viewer/**` is imported, never copied.
- **Namespace completely.** No `ia3d-` identifier, no `window.__iaViewer`, and no un-suffixed `ui-setting` key may appear in cloned files. Task 1 enforces this with a test.
- **Never call `/dlc/project/inline-analysis/session/stop` from the clone.** See Task 3.
- Tests run from `dlc-3D/` with `python3 -m pytest` (host Python 3.9).

## File Structure

| File | Responsibility |
| --- | --- |
| `src/static/card_inline_analysis_3d_reprojection.html` | Cloned card markup, fetched and injected at runtime. |
| `src/static/inline_analysis_3d_reprojection.js` | Cloned consumer module, renamed, plus bootstrap and reprojection panel. |
| `src/static/inline_analysis_3d_reprojection.css` | Cloned styles, renamed. |
| `src/templates/dlc_3d.html` | Modify: one `<script>` line. |
| `scripts/clone_inline_analysis_card.sh` | The rename transformation, kept so it can be re-run if the original moves on. |
| `tests/test_reproj_card_namespace.py` | Namespace isolation and no-forbidden-call assertions. |
| `tests/test_reproj_card_bootstrap.py` | Bootstrap wiring assertions. |
| `tests/test_reproj_panel_markup.py` | Reprojection panel markup assertions. |
| `tests/test_reproj_panel_wiring.py` | Panel and overlay wiring assertions. |

These follow the existing convention in this repo of asserting on static file contents (see `tests/test_inline_3d_params_markup.py`, `tests/test_inline_3d_params_wiring.py`).

---

### Task 1: Generate the renamed clone

**Files:**
- Create: `scripts/clone_inline_analysis_card.sh`
- Create: `src/static/card_inline_analysis_3d_reprojection.html`
- Create: `src/static/inline_analysis_3d_reprojection.js`
- Create: `src/static/inline_analysis_3d_reprojection.css`
- Test: `tests/test_reproj_card_namespace.py`

**Interfaces:**
- Consumes: nothing.
- Produces: three cloned static files in which every `ia3d-` id/class is `ia3dr-`, every `inline-analysis-3d` element id is `inline-analysis-3d-reprojection`, JS identifiers `_ia3d*` are `_ia3dr*`, and the viewer global is `window.__iaViewerReproj`.

**Why a script rather than hand editing:** 227 unique ids across 168 KB. A scripted transformation is reproducible and can be re-run if the original card changes while both exist.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reproj_card_namespace.py
"""The clone must not share ids, CSS classes or globals with the original card.

Both cards live in the same document. Any shared id means one card's queries
return the other card's nodes.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).parent.parent / "src" / "static"
CARD = STATIC / "card_inline_analysis_3d_reprojection.html"
JS = STATIC / "inline_analysis_3d_reprojection.js"
CSS = STATIC / "inline_analysis_3d_reprojection.css"

ORIGINAL_CARD = (
    Path(__file__).parent.parent / "src" / "templates" / "partials"
    / "card_inline_analysis_3d.html"
)
ORIGINAL_JS = STATIC / "inline_analysis_3d.js"


@pytest.fixture(scope="module")
def clone_texts():
    for p in (CARD, JS, CSS):
        assert p.is_file(), "missing clone artifact: {}".format(p)
    return {p.name: p.read_text() for p in (CARD, JS, CSS)}


def test_no_bare_ia3d_identifier_survives(clone_texts):
    """`ia3d-` must be gone everywhere; `ia3dr-` is the clone's namespace."""
    for name, text in clone_texts.items():
        leaked = re.findall(r"\bia3d-[a-z0-9-]+", text)
        assert not leaked, "{} still references original ids: {}".format(
            name, sorted(set(leaked))[:10]
        )


def test_clone_uses_its_own_namespace(clone_texts):
    assert "ia3dr-" in clone_texts[CARD.name]
    assert "ia3dr-" in clone_texts[JS.name]
    assert "ia3dr-" in clone_texts[CSS.name]


def test_card_root_and_buttons_are_renamed(clone_texts):
    card = clone_texts[CARD.name]
    assert 'id="inline-analysis-3d-reprojection-card"' in card
    assert 'id="inline-analysis-3d-card"' not in card
    assert 'id="btn-close-inline-analysis-3d"' not in card


def test_js_does_not_clobber_the_original_viewer_global(clone_texts):
    js = clone_texts[JS.name]
    assert "__iaViewerReproj" in js
    assert re.search(r'"__iaViewer"', js) is None


def test_js_identifiers_are_renamed(clone_texts):
    js = clone_texts[JS.name]
    assert not re.search(r"\b_ia3d[A-Z]", js), "un-renamed _ia3dXxx identifier"


def test_clone_ids_are_disjoint_from_the_original_card(clone_texts):
    ids = lambda t: set(re.findall(r'id="([^"]+)"', t))
    shared = ids(clone_texts[CARD.name]) & ids(ORIGINAL_CARD.read_text())
    assert not shared, "ids shared with the original card: {}".format(
        sorted(shared)[:10]
    )


def test_clone_does_not_import_a_copied_viewer_library(clone_texts):
    """The shared viewer library must be imported, never cloned."""
    js = clone_texts[JS.name]
    assert "./components/viewer/video_viewer.js" in js
    assert not (STATIC / "components_reproj").exists()


def test_server_routes_were_not_renamed(clone_texts):
    """The rename must not touch fetch URLs — they are server contracts."""
    js = clone_texts[JS.name]
    for url in (
        "/dlc/project/inline-analysis/range",
        "/dlc/project/snapshots",
        "/dlc-3d/sibling-camera",
    ):
        assert url in js, "rename damaged the URL {}".format(url)
    assert "ia3dr" not in "".join(re.findall(r'fetch\(\s*[`"\']([^`"\']*)', js))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_card_namespace.py -v`
Expected: FAIL — `missing clone artifact: .../card_inline_analysis_3d_reprojection.html`

- [ ] **Step 3: Write the clone script**

```bash
# scripts/clone_inline_analysis_card.sh
#!/usr/bin/env bash
# Generate the "3D Inline Analysis - Reprojection" clone from the original card.
#
# Kept in-tree so the clone can be regenerated if the original card changes
# while both exist. Re-running OVERWRITES the three generated files, so any
# hand edits to the clone must be re-applied afterwards — that is why the
# reprojection panel lives in its own appended block (see Tasks 4-6), which
# this script preserves by refusing to run once that block is present.
set -euo pipefail

cd "$(dirname "$0")/.."
SRC_CARD="src/templates/partials/card_inline_analysis_3d.html"
SRC_JS="src/static/inline_analysis_3d.js"
SRC_CSS="src/static/inline_analysis_3d.css"
OUT_CARD="src/static/card_inline_analysis_3d_reprojection.html"
OUT_JS="src/static/inline_analysis_3d_reprojection.js"
OUT_CSS="src/static/inline_analysis_3d_reprojection.css"

for f in "$OUT_CARD" "$OUT_JS" "$OUT_CSS"; do
  if [ -f "$f" ] && grep -q "REPROJECTION PANEL" "$f"; then
    echo "refusing to overwrite $f: it contains hand-written panel code" >&2
    exit 1
  fi
done

rename() {
  # Order is irrelevant: the two patterns cannot overlap.
  #   inline-analysis-3d  -> inline-analysis-3d-reprojection  (card/button ids)
  #   ia3d-               -> ia3dr-                           (ids + CSS classes)
  #   _ia3d<Upper>        -> _ia3dr<Upper>                    (JS identifiers)
  #   __iaViewer          -> __iaViewerReproj                 (window global)
  # URLs are unaffected: no fetch path contains "inline-analysis-3d" or "ia3d-".
  sed -e 's/inline-analysis-3d/inline-analysis-3d-reprojection/g' \
      -e 's/ia3d-/ia3dr-/g' \
      -e 's/\b_ia3d\([A-Z]\)/_ia3dr\1/g' \
      -e 's/__iaViewer\b/__iaViewerReproj/g'
}

rename < "$SRC_CARD" > "$OUT_CARD"
rename < "$SRC_JS"   > "$OUT_JS"
rename < "$SRC_CSS"  > "$OUT_CSS"

# The card fragment is injected into an existing <main>, so strip the Jinja
# wrapper if the original partial has one.
sed -i -e '/^{%/d' "$OUT_CARD"

echo "generated:"
wc -c "$OUT_CARD" "$OUT_JS" "$OUT_CSS"
```

- [ ] **Step 4: Run the script**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
chmod +x scripts/clone_inline_analysis_card.sh
./scripts/clone_inline_analysis_card.sh
```

Expected: three files reported, roughly 40 KB / 170 KB / 15 KB.

- [ ] **Step 5: Retitle the card and fix the heading**

The clone still says "3D Inline Analysis". Change the card heading and the launcher button label:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
sed -i 's|<h2>3D Inline Analysis</h2>|<h2>3D Inline Analysis - Reprojection</h2>|' \
  src/static/card_inline_analysis_3d_reprojection.html
grep -n "3D Inline Analysis" src/static/card_inline_analysis_3d_reprojection.html
```

Expected: the heading reads `3D Inline Analysis - Reprojection`.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_card_namespace.py -v`
Expected: PASS, 8 tests

If `test_server_routes_were_not_renamed` fails, the `sed` damaged a URL — inspect the diff and narrow the pattern rather than editing the generated file by hand.

- [ ] **Step 7: Commit**

```bash
git add dlc-3D/scripts/clone_inline_analysis_card.sh \
        dlc-3D/src/static/card_inline_analysis_3d_reprojection.html \
        dlc-3D/src/static/inline_analysis_3d_reprojection.js \
        dlc-3D/src/static/inline_analysis_3d_reprojection.css \
        dlc-3D/tests/test_reproj_card_namespace.py
git commit -m "feat(reprojection): namespace-isolated clone of the 3D Inline Analysis card"
```

---

### Task 2: Bootstrap — self-inject CSS, launcher button, card fragment

**Files:**
- Modify: `src/static/inline_analysis_3d_reprojection.js`
- Test: `tests/test_reproj_card_bootstrap.py`

**Interfaces:**
- Consumes: the cloned module from Task 1.
- Produces: an appended bootstrap block that, on load, injects `<link>` for the cloned CSS, creates the launcher button `btn-open-inline-analysis-3d-reprojection`, places it immediately after `btn-open-inline-analysis-3d` in `#dlc-frame-extract-launch`, and injects the card fragment into `main.cards`.

**Context:** the original places its button with `_ia3dPlaceNavButton()` (`inline_analysis_3d.js:3567`), moving the node into `#dlc-frame-extract-launch` after `#btn-open-view-analyzed`. The clone must instead anchor **after the original's button** so it lands directly below it. The rename in Task 1 already produced `_ia3drPlaceNavButton` operating on the renamed id, so that function needs its anchor changed and the button needs creating, since it will no longer be declared in `dlc_3d.html`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reproj_card_bootstrap.py
from pathlib import Path

import pytest

STATIC = Path(__file__).parent.parent / "src" / "static"
JS = STATIC / "inline_analysis_3d_reprojection.js"
CARD = STATIC / "card_inline_analysis_3d_reprojection.html"


@pytest.fixture(scope="module")
def js():
    return JS.read_text()


def test_bootstrap_block_is_present(js):
    assert "REPROJECTION BOOTSTRAP" in js


def test_injects_its_own_stylesheet(js):
    assert "inline_analysis_3d_reprojection.css" in js


def test_fetches_and_injects_the_card_fragment(js):
    assert "card_inline_analysis_3d_reprojection.html" in js
    assert "main.cards" in js


def test_creates_its_own_launcher_button(js):
    assert "btn-open-inline-analysis-3d-reprojection" in js
    assert "3D Inline Analysis - Reprojection" in js


def test_launcher_anchors_below_the_original_button(js):
    """The button must sit directly below the original card's button, so the
    anchor is the ORIGINAL id — which must therefore still appear in the clone
    exactly once, as an anchor lookup and nothing else."""
    assert 'btn-open-inline-analysis-3d"' in js


def test_card_fragment_has_no_jinja(js):
    text = CARD.read_text()
    assert "{%" not in text and "{{" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_card_bootstrap.py -v`
Expected: FAIL — `assert "REPROJECTION BOOTSTRAP" in js`

- [ ] **Step 3: Append the bootstrap block**

Append to `src/static/inline_analysis_3d_reprojection.js`:

```javascript
// ── REPROJECTION BOOTSTRAP ───────────────────────────────────────────────────
// This clone owns its whole DOM footprint at runtime rather than through Jinja.
// templates/partials/*.html are bind-mounted file-by-file, so a new partial
// would require a docker-compose.yml edit and a container recreate; a fragment
// under static/ (a whole-directory mount) needs neither. dlc_3d.html therefore
// contains exactly one line for this card: the <script> tag that loads it.

const REPROJ_CARD_URL = "/dlc-3d/static/card_inline_analysis_3d_reprojection.html";
const REPROJ_CSS_URL = "/dlc-3d/static/inline_analysis_3d_reprojection.css";

function _reprojInjectStylesheet() {
  if (document.querySelector(`link[href="${REPROJ_CSS_URL}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = REPROJ_CSS_URL;
  document.head.appendChild(link);
}

function _reprojMakeLauncherButton() {
  let btn = document.getElementById("btn-open-inline-analysis-3d-reprojection");
  if (btn) return btn;
  btn = document.createElement("button");
  btn.id = "btn-open-inline-analysis-3d-reprojection";
  btn.className = "inspect-btn";
  btn.style.cssText = "width:100%;gap:.55rem;display:none";
  btn.innerHTML = `
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="3" width="14" height="14" rx="2"></rect>
      <rect x="7" y="7" width="14" height="14" rx="2"></rect>
      <path d="M3 17 L21 7"></path>
    </svg>
    <span>3D Inline Analysis - Reprojection</span>`;
  document.body.appendChild(btn);   // parked until placed in the nav list
  return btn;
}

// Overrides the renamed clone of _ia3dPlaceNavButton: anchor directly BELOW the
// original card's launcher button instead of below "View Analyzed".
function _reprojPlaceNavButton() {
  const nav = document.getElementById("dlc-frame-extract-launch");
  const btn = _reprojMakeLauncherButton();
  if (!nav) return;
  if (btn.parentElement !== nav) {
    const anchor = document.getElementById("btn-open-inline-analysis-3d");
    if (anchor && anchor.parentElement === nav) {
      anchor.insertAdjacentElement("afterend", btn);
    } else {
      nav.appendChild(btn);
    }
  }
  btn.style.display = "";
}

let _reprojCardInjected = null;

async function _reprojInjectCard() {
  if (_reprojCardInjected) return _reprojCardInjected;
  _reprojCardInjected = (async () => {
    if (document.getElementById("inline-analysis-3d-reprojection-card")) return;
    const host = document.querySelector("main.cards");
    if (!host) return;
    const res = await fetch(REPROJ_CARD_URL);
    if (!res.ok) throw new Error(`card fragment ${res.status}`);
    const holder = document.createElement("div");
    holder.innerHTML = await res.text();
    while (holder.firstElementChild) host.appendChild(holder.firstElementChild);
  })();
  return _reprojCardInjected;
}

async function _reprojBootstrap() {
  _reprojInjectStylesheet();
  await _reprojInjectCard();
  _reprojPlaceNavButton();
  // Wiring must run after the markup exists — the cloned wiring functions look
  // up ia3dr- ids directly.
  _reprojWireAfterInject();
}

// Re-runs the cloned module's own wiring against the freshly injected markup.
// The cloned _wireLauncher / _wireStereoDispatch already ran on
// DOMContentLoaded and found nothing, so they are re-invoked here.
function _reprojWireAfterInject() {
  try { _wireLauncher(); } catch (e) { console.warn("[reproj] wireLauncher", e); }
  try { _wireStereoDispatch(); } catch (e) { console.warn("[reproj] wireStereo", e); }
  try { _reprojWirePanel(); } catch (e) { console.warn("[reproj] wirePanel", e); }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => { _reprojBootstrap(); });
} else {
  _reprojBootstrap();
}
```

- [ ] **Step 4: Remove the cloned nav placement so it cannot fight the override**

The renamed clone of `_ia3dPlaceNavButton` (now `_ia3drPlaceNavButton`) still runs from the cloned `DOMContentLoaded` handler and would look for a button that no longer exists in the template. Neutralise it:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
grep -n "_ia3drPlaceNavButton" src/static/inline_analysis_3d_reprojection.js
```

Replace the body of `_ia3drPlaceNavButton` with a single delegating line so both call sites become harmless:

```javascript
function _ia3drPlaceNavButton() {
  // Superseded by _reprojPlaceNavButton (see REPROJECTION BOOTSTRAP): this
  // clone creates its own button at runtime and anchors it below the original
  // card's button, not below "View Analyzed".
  _reprojPlaceNavButton();
}
```

- [ ] **Step 5: Add a no-op `_reprojWirePanel` placeholder so bootstrap does not throw**

Task 5 replaces this. Append to `src/static/inline_analysis_3d_reprojection.js`:

```javascript
// Replaced in full by the REPROJECTION PANEL block (Task 5).
function _reprojWirePanel() {}
```

- [ ] **Step 6: Run tests**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_card_bootstrap.py tests/test_reproj_card_namespace.py -v`
Expected: PASS, 14 tests

- [ ] **Step 7: Commit**

```bash
git add dlc-3D/src/static/inline_analysis_3d_reprojection.js \
        dlc-3D/tests/test_reproj_card_bootstrap.py
git commit -m "feat(reprojection): runtime bootstrap for the cloned card"
```

---

### Task 3: The two approved divergences

**Files:**
- Modify: `src/static/inline_analysis_3d_reprojection.js`
- Test: `tests/test_reproj_card_namespace.py`

**Interfaces:**
- Consumes: the clone from Tasks 1–2.
- Produces: every `ui-setting` key the clone writes carries a `_reproj` suffix, and the clone contains no call to `/dlc/project/inline-analysis/session/stop`.

**Why:** the clone shares main-webapp server state with the original card.

1. `ui-setting` keys are per-project. `pose3d_bg_color`, `pose3d_view_prefs`, `finalize_window`, `clip_window`, `postfix_tags`, `status_tags` and `note_tags` would otherwise be the same stored setting in both cards, so changing the 3D background in one would change it in the other.
2. `session/stop` is keyed by `snap_key`, which the server derives from the snapshot and shuffle. Two cards warmed on the same snapshot share a `snap_key`, so the clone's stop — on card close or `beforeunload` — would kill the original card's warm session. The clone simply never stops a session; the `ttl_seconds` the session was started with expires it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reproj_card_namespace.py`:

```python
UI_SETTING_KEYS = (
    "pose3d_bg_color", "pose3d_view_prefs", "finalize_window",
    "clip_window", "postfix_tags", "status_tags", "note_tags",
)


def test_ui_setting_keys_are_namespaced(clone_texts):
    """Per-project ui-setting keys are shared storage; un-suffixed keys would
    make the two cards silently edit the same setting."""
    js = clone_texts[JS.name]
    for key in UI_SETTING_KEYS:
        assert key + "_reproj" in js, "{} not namespaced".format(key)
        assert not re.search(r'"{}"'.format(key), js), (
            '"{}" still used un-suffixed'.format(key)
        )


def test_clone_never_stops_an_inline_analysis_session(clone_texts):
    """snap_key is shared, so a stop from this card can kill the original
    card's warm session. Sessions expire via their own ttl_seconds instead."""
    assert "inline-analysis/session/stop" not in clone_texts[JS.name]


def test_clone_still_starts_its_own_session(clone_texts):
    assert "inline-analysis/session/start" in clone_texts[JS.name]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_card_namespace.py -v`
Expected: FAIL on `test_ui_setting_keys_are_namespaced` and `test_clone_never_stops_an_inline_analysis_session`

- [ ] **Step 3: Namespace the ui-setting keys**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
F=src/static/inline_analysis_3d_reprojection.js
for k in pose3d_bg_color pose3d_view_prefs finalize_window clip_window \
         postfix_tags status_tags note_tags; do
  sed -i "s/\"$k\"/\"${k}_reproj\"/g" "$F"
  sed -i "s/key=$k/key=${k}_reproj/g" "$F"
done
grep -c "_reproj" "$F"
```

- [ ] **Step 4: Remove both session-stop call sites**

Find them:

```bash
grep -n "session/stop" src/static/inline_analysis_3d_reprojection.js
```

There are two — one on card close, one in a `beforeunload` handler. Replace each with a comment explaining why, for example:

```javascript
      // Deliberately NOT calling /dlc/project/inline-analysis/session/stop.
      // snap_key is shared with the original 3D Inline Analysis card, so a stop
      // from here can kill a warm session that card is still using. The session
      // expires on its own ttl_seconds.
      _snapKey = null;
```

and for the `beforeunload` handler, delete the `sendBeacon` call, leaving the listener empty or removing it entirely.

- [ ] **Step 5: Run tests**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_card_namespace.py -v`
Expected: PASS, 11 tests

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/static/inline_analysis_3d_reprojection.js \
        dlc-3D/tests/test_reproj_card_namespace.py
git commit -m "fix(reprojection): namespace ui-setting keys and never stop a shared session"
```

---

### Task 4: Reprojection panel markup

**Files:**
- Modify: `src/static/card_inline_analysis_3d_reprojection.html`
- Test: `tests/test_reproj_panel_markup.py`

**Interfaces:**
- Consumes: the card fragment from Task 1.
- Produces: a panel whose element ids Task 5 wires — `ia3dr-reproj-panel`, `ia3dr-reproj-ref-cam`, `ia3dr-reproj-k1`, `ia3dr-reproj-k1-val`, `ia3dr-reproj-k2`, `ia3dr-reproj-k2-val`, `ia3dr-reproj-estimate`, `ia3dr-reproj-run`, `ia3dr-reproj-status`, `ia3dr-reproj-thresholds`, `ia3dr-reproj-counts`, `ia3dr-reproj-show-lines`, `ia3dr-reproj-overrides`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reproj_panel_markup.py
from pathlib import Path

import pytest

CARD = (
    Path(__file__).parent.parent / "src" / "static"
    / "card_inline_analysis_3d_reprojection.html"
)

REQUIRED_IDS = [
    "ia3dr-reproj-panel",
    "ia3dr-reproj-ref-cam",
    "ia3dr-reproj-k1",
    "ia3dr-reproj-k1-val",
    "ia3dr-reproj-k2",
    "ia3dr-reproj-k2-val",
    "ia3dr-reproj-estimate",
    "ia3dr-reproj-run",
    "ia3dr-reproj-status",
    "ia3dr-reproj-thresholds",
    "ia3dr-reproj-counts",
    "ia3dr-reproj-show-lines",
    "ia3dr-reproj-overrides",
]


@pytest.fixture(scope="module")
def card():
    return CARD.read_text()


@pytest.mark.parametrize("element_id", REQUIRED_IDS)
def test_required_element_present(card, element_id):
    assert 'id="{}"'.format(element_id) in card


def test_reference_camera_offers_both_cameras(card):
    panel = card.split('id="ia3dr-reproj-ref-cam"')[1][:400]
    assert 'value="cam_0"' in panel and 'value="cam_1"' in panel


def test_k_defaults_match_the_spec(card):
    """k1 = 3, k2 = 8 per the design spec."""
    k1 = card.split('id="ia3dr-reproj-k1"')[1][:300]
    k2 = card.split('id="ia3dr-reproj-k2"')[1][:300]
    assert 'value="3"' in k1
    assert 'value="8"' in k2


def test_panel_is_inside_the_cloned_card(card):
    assert card.index('id="inline-analysis-3d-reprojection-card"') < card.index(
        'id="ia3dr-reproj-panel"'
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_markup.py -v`
Expected: FAIL — all `test_required_element_present` cases

- [ ] **Step 3: Insert the panel markup**

Insert this immediately before the closing `</section>` of the cloned card in `src/static/card_inline_analysis_3d_reprojection.html`:

```html
      <!-- ── REPROJECTION PANEL ──────────────────────────────────────────── -->
      <div class="ia3dr-bar" id="ia3dr-reproj-panel">
        <div class="ia3dr-bar-header">Epipolar reprojection</div>

        <div class="ia3dr-ctrl-row">
          <label for="ia3dr-reproj-ref-cam">Trusted camera</label>
          <select id="ia3dr-reproj-ref-cam">
            <option value="cam_0">cam0</option>
            <option value="cam_1" selected>cam1</option>
          </select>
          <span class="ia3dr-hint">
            The other camera is judged against this one.
          </span>
        </div>

        <div class="ia3dr-ctrl-row">
          <label for="ia3dr-reproj-k1">Trust band k&#8321;</label>
          <input type="number" id="ia3dr-reproj-k1" min="0.5" max="20"
                 step="0.5" value="3">
          <span id="ia3dr-reproj-k1-val"></span>
          <label for="ia3dr-reproj-k2">Reject band k&#8322;</label>
          <input type="number" id="ia3dr-reproj-k2" min="1" max="50"
                 step="0.5" value="8">
          <span id="ia3dr-reproj-k2-val"></span>
        </div>

        <div class="ia3dr-ctrl-row">
          <button id="ia3dr-reproj-estimate" class="inspect-btn">
            Estimate thresholds
          </button>
          <button id="ia3dr-reproj-run" class="inspect-btn">
            Run and write _reprojected.h5
          </button>
          <label class="ia3dr-inline-check">
            <input type="checkbox" id="ia3dr-reproj-show-lines">
            Show epipolar lines
          </label>
        </div>

        <div id="ia3dr-reproj-status" class="ia3dr-status"></div>

        <div class="ia3dr-ctrl-row">
          <div id="ia3dr-reproj-thresholds" class="ia3dr-table-wrap"></div>
        </div>

        <div class="ia3dr-ctrl-row">
          <div id="ia3dr-reproj-counts" class="ia3dr-table-wrap"></div>
        </div>

        <details>
          <summary>Per-bodypart trusted-camera overrides</summary>
          <div id="ia3dr-reproj-overrides" class="ia3dr-bp-chips-wrap"></div>
        </details>
      </div>
```

- [ ] **Step 4: Add the panel's styles**

Append to `src/static/inline_analysis_3d_reprojection.css`:

```css
/* ── REPROJECTION PANEL ──────────────────────────────────────────────────── */
#ia3dr-reproj-panel .ia3dr-hint { opacity: .7; font-size: .85em; }
#ia3dr-reproj-panel .ia3dr-inline-check {
  display: inline-flex; align-items: center; gap: .35rem;
}
#ia3dr-reproj-panel .ia3dr-table-wrap { width: 100%; overflow-x: auto; }
#ia3dr-reproj-panel table { border-collapse: collapse; font-size: .85em; }
#ia3dr-reproj-panel th,
#ia3dr-reproj-panel td {
  padding: .15rem .5rem; text-align: right; white-space: nowrap;
}
#ia3dr-reproj-panel th:first-child,
#ia3dr-reproj-panel td:first-child { text-align: left; }
#ia3dr-reproj-panel tr.src-default td,
#ia3dr-reproj-panel tr.src-pooled td { opacity: .65; font-style: italic; }
#ia3dr-reproj-status { min-height: 1.2em; margin: .35rem 0; }
```

- [ ] **Step 5: Run tests**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_markup.py -v`
Expected: PASS, 16 tests

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/static/card_inline_analysis_3d_reprojection.html \
        dlc-3D/src/static/inline_analysis_3d_reprojection.css \
        dlc-3D/tests/test_reproj_panel_markup.py
git commit -m "feat(reprojection): epipolar reprojection panel markup and styles"
```

---

### Task 5: Panel wiring

**Files:**
- Modify: `src/static/inline_analysis_3d_reprojection.js`
- Test: `tests/test_reproj_panel_wiring.py`

**Interfaces:**
- Consumes: `_overlayPrimaryH5` and `_siblingPrimaryH5` (cloned module state holding the current primary and sibling h5 paths), the panel ids from Task 4, and the engine endpoints.
- Produces: `_reprojWirePanel()` replacing the Task 2 placeholder; module state `_reprojAudit` holding the last run summary; `_reprojResolveCalibration()`, `_reprojEstimate()`, `_reprojRun()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reproj_panel_wiring.py
import re
from pathlib import Path

import pytest

JS = (
    Path(__file__).parent.parent / "src" / "static"
    / "inline_analysis_3d_reprojection.js"
)


@pytest.fixture(scope="module")
def js():
    return JS.read_text()


def test_panel_block_present(js):
    assert "REPROJECTION PANEL" in js


def test_placeholder_wire_panel_is_gone(js):
    assert "function _reprojWirePanel() {}" not in js


def test_calls_the_three_engine_endpoints(js):
    assert "/dlc-3d/reproject/thresholds" in js
    assert "/dlc-3d/reproject/run" in js
    assert "/dlc-3d/reproject/epiline" in js


def test_sends_both_h5_paths_and_the_trusted_camera(js):
    block = js.split("REPROJECTION PANEL")[1]
    for field in ("ref_h5", "tgt_h5", "calibration", "ref_cam", "tgt_cam"):
        assert field in block, "run payload missing {}".format(field)


def test_sends_k1_and_k2(js):
    block = js.split("REPROJECTION PANEL")[1]
    assert "k1" in block and "k2" in block


def test_renders_threshold_source_so_uncalibrated_bodyparts_are_visible(js):
    """A bodypart whose thresholds fell back to pooled/default must be visibly
    marked — its verdicts are not trustworthy on their own."""
    block = js.split("REPROJECTION PANEL")[1]
    assert "threshold_source" in block


def test_run_button_is_disabled_while_running(js):
    block = js.split("REPROJECTION PANEL")[1]
    assert "disabled" in block


def test_overrides_are_sent_when_set(js):
    block = js.split("REPROJECTION PANEL")[1]
    assert "overrides" in block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_wiring.py -v`
Expected: FAIL — `assert "REPROJECTION PANEL" in js`

- [ ] **Step 3: Replace the placeholder with the panel block**

Delete the `function _reprojWirePanel() {}` line added in Task 2 and append:

```javascript
// ── REPROJECTION PANEL ──────────────────────────────────────────────────────
// Drives the epipolar reprojection engine. The trusted camera judges the other;
// the engine writes <stem>_reprojected.h5 for BOTH cameras so the existing
// _cam{N}_ sibling pairing still discovers the pair.

let _reprojAudit = null;              // last run summary (or estimate result)
let _reprojOverrides = {};            // bodypart -> "ref" | "tgt"

const _reprojEl = {
  panel:      () => document.getElementById("ia3dr-reproj-panel"),
  refCam:     () => document.getElementById("ia3dr-reproj-ref-cam"),
  k1:         () => document.getElementById("ia3dr-reproj-k1"),
  k1Val:      () => document.getElementById("ia3dr-reproj-k1-val"),
  k2:         () => document.getElementById("ia3dr-reproj-k2"),
  k2Val:      () => document.getElementById("ia3dr-reproj-k2-val"),
  estimate:   () => document.getElementById("ia3dr-reproj-estimate"),
  run:        () => document.getElementById("ia3dr-reproj-run"),
  status:     () => document.getElementById("ia3dr-reproj-status"),
  thresholds: () => document.getElementById("ia3dr-reproj-thresholds"),
  counts:     () => document.getElementById("ia3dr-reproj-counts"),
  showLines:  () => document.getElementById("ia3dr-reproj-show-lines"),
  overrides:  () => document.getElementById("ia3dr-reproj-overrides"),
};

function _reprojStatus(msg, isError) {
  const el = _reprojEl.status();
  if (!el) return;
  el.textContent = msg || "";
  el.style.color = isError ? "#ff6b6b" : "";
}

// calibration.toml sits in the video's folder, or its parent when the video is
// inside a clip subfolder — the same priority the save-frame route uses.
function _reprojResolveCalibration(h5Path) {
  if (!h5Path) return null;
  const parts = String(h5Path).split("/");
  parts.pop();
  return parts.join("/") + "/calibration.toml";
}

// The trusted camera drives which of the two h5 files is reference vs target.
function _reprojPair() {
  const refCam = _reprojEl.refCam()?.value || "cam_1";
  const tgtCam = refCam === "cam_0" ? "cam_1" : "cam_0";
  const primary = _overlayPrimaryH5;
  const sibling = _siblingPrimaryH5;
  if (!primary || !sibling) return null;

  // _overlayPrimaryH5 is cam0's file (the primary tile); the sibling is cam1's.
  const byCam = { cam_0: primary, cam_1: sibling };
  return {
    ref_cam: refCam,
    tgt_cam: tgtCam,
    ref_h5: byCam[refCam],
    tgt_h5: byCam[tgtCam],
    calibration: _reprojResolveCalibration(primary),
  };
}

function _reprojPayload() {
  const pair = _reprojPair();
  if (!pair) return null;
  return Object.assign({}, pair, {
    k1: parseFloat(_reprojEl.k1()?.value) || 3.0,
    k2: parseFloat(_reprojEl.k2()?.value) || 8.0,
    overrides: _reprojOverrides,
  });
}

function _reprojRenderThresholds(bodyparts) {
  const host = _reprojEl.thresholds();
  if (!host) return;
  const rows = Object.keys(bodyparts).map((bp) => {
    const s = bodyparts[bp];
    const cls = s.threshold_source === "self" ? "" : ` class="src-${s.threshold_source}"`;
    const fmt = (v) => (Number.isFinite(v) ? v.toFixed(2) : "—");
    return `<tr${cls}><td>${bp}</td><td>${fmt(s.t_ok)}</td><td>${fmt(s.t_bad)}</td>` +
           `<td>${fmt(s.med)}</td><td>${fmt(s.mad)}</td>` +
           `<td>${s.n_highconf}</td><td>${s.threshold_source}</td></tr>`;
  }).join("");
  host.innerHTML =
    `<table><thead><tr><th>bodypart</th><th>t_ok</th><th>t_bad</th>` +
    `<th>med</th><th>mad</th><th>n high-conf</th><th>source</th></tr></thead>` +
    `<tbody>${rows}</tbody></table>`;
}

function _reprojRenderCounts(counts) {
  const host = _reprojEl.counts();
  if (!host) return;
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  const rows = Object.keys(counts)
    .sort((a, b) => counts[b] - counts[a])
    .map((k) => `<tr><td>${k}</td><td>${counts[k]}</td>` +
                `<td>${(100 * counts[k] / total).toFixed(2)}%</td></tr>`)
    .join("");
  host.innerHTML =
    `<table><thead><tr><th>verdict</th><th>points</th><th>share</th></tr>` +
    `</thead><tbody>${rows}</tbody></table>`;
}

function _reprojRenderOverrides(bodyparts) {
  const host = _reprojEl.overrides();
  if (!host) return;
  host.innerHTML = Object.keys(bodyparts).map((bp) => {
    const cur = _reprojOverrides[bp] === "ref" ? "ref" : "tgt";
    return `<label class="ia3dr-inline-check"><span>${bp}</span>` +
           `<select data-reproj-bp="${bp}">` +
           `<option value="tgt"${cur === "tgt" ? " selected" : ""}>session default</option>` +
           `<option value="ref"${cur === "ref" ? " selected" : ""}>flip for this part</option>` +
           `</select></label>`;
  }).join("");
  host.querySelectorAll("select[data-reproj-bp]").forEach((sel) => {
    sel.addEventListener("change", () => {
      const bp = sel.getAttribute("data-reproj-bp");
      if (sel.value === "ref") _reprojOverrides[bp] = "ref";
      else delete _reprojOverrides[bp];
    });
  });
}

async function _reprojEstimate() {
  const payload = _reprojPayload();
  if (!payload) { _reprojStatus("Open a paired session with an overlay h5 first.", true); return; }
  const btn = _reprojEl.estimate();
  if (btn) btn.disabled = true;
  _reprojStatus("Estimating thresholds…");
  try {
    const res = await fetch("/dlc-3d/reproject/thresholds", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    _reprojRenderThresholds(data.bodyparts);
    _reprojRenderOverrides(data.bodyparts);
    const fellBack = Object.values(data.bodyparts)
      .filter((s) => s.threshold_source !== "self").length;
    _reprojStatus(
      fellBack
        ? `Thresholds ready. ${fellBack} bodypart(s) had too few confident frames — their verdicts are not self-calibrated.`
        : "Thresholds ready.",
    );
  } catch (e) {
    _reprojStatus(`Threshold estimation failed: ${e.message}`, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function _reprojRun() {
  const payload = _reprojPayload();
  if (!payload) { _reprojStatus("Open a paired session with an overlay h5 first.", true); return; }
  const btn = _reprojEl.run();
  if (btn) btn.disabled = true;
  _reprojStatus("Running reprojection — this rewrites nothing until it finishes…");
  try {
    const res = await fetch("/dlc-3d/reproject/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    _reprojAudit = data;
    _reprojRenderThresholds(data.bodyparts);
    _reprojRenderCounts(data.counts);
    _reprojStatus(
      `Wrote ${data.outputs.ref_h5.split("/").pop()} and ` +
      `${data.outputs.tgt_h5.split("/").pop()}.`,
    );
  } catch (e) {
    _reprojStatus(`Run failed: ${e.message}`, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function _reprojWirePanel() {
  if (!_reprojEl.panel()) return;
  _reprojEl.estimate()?.addEventListener("click", _reprojEstimate);
  _reprojEl.run()?.addEventListener("click", _reprojRun);
  const mirror = (input, out) => {
    const el = input(), o = out();
    if (!el || !o) return;
    const sync = () => { o.textContent = `×${el.value}`; };
    el.addEventListener("input", sync);
    sync();
  };
  mirror(_reprojEl.k1, _reprojEl.k1Val);
  mirror(_reprojEl.k2, _reprojEl.k2Val);
  _reprojEl.refCam()?.addEventListener("change", () => {
    _reprojStatus("Trusted camera changed — re-estimate thresholds.");
  });
  _reprojWireEpipolarOverlay();
}
```

- [ ] **Step 4: Add a temporary no-op for the overlay hook**

Task 6 replaces this. Append:

```javascript
// Replaced in full by the EPIPOLAR OVERLAY block (Task 6).
function _reprojWireEpipolarOverlay() {}
```

- [ ] **Step 5: Run tests**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_wiring.py -v`
Expected: PASS, 8 tests

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/static/inline_analysis_3d_reprojection.js \
        dlc-3D/tests/test_reproj_panel_wiring.py
git commit -m "feat(reprojection): wire the reprojection panel to the engine endpoints"
```

---

### Task 6: Epipolar line overlay

**Files:**
- Modify: `src/static/inline_analysis_3d_reprojection.js`
- Test: `tests/test_reproj_panel_wiring.py`

**Interfaces:**
- Consumes: `_viewer` (the cloned module's `VideoViewer` instance), `viewer.on("drawTile", (tile, frame))` from `components/viewer/video_viewer.js`, and `scaleFor` / `videoToCanvas` from `components/viewer/internal/marker_overlay.mjs`.
- Produces: `_reprojWireEpipolarOverlay()` replacing the Task 5 no-op, drawing the trusted camera's epipolar line onto the judged camera's tile.

**Context:** `VideoViewer` emits `drawTile(tile, frame)` per tile after every seek. `markerEditor` subscribes and calls `clearRect` before drawing markers, so this overlay must subscribe **after** `markerEditor` is composed to paint on top. Each `tile` exposes `cam`, `imgEl`, `canvasEl`. Coordinates come back from `/reproject/epiline` in the target view's pixel space, so they need `scaleFor(img.naturalWidth, img.naturalHeight, canvas.width, canvas.height)` then `videoToCanvas`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reproj_panel_wiring.py`:

```python
def test_overlay_block_present(js):
    assert "EPIPOLAR OVERLAY" in js


def test_overlay_placeholder_is_gone(js):
    assert "function _reprojWireEpipolarOverlay() {}" not in js


def test_overlay_subscribes_to_the_drawtile_hook(js):
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert '"drawTile"' in block


def test_overlay_scales_from_video_to_canvas_coordinates(js):
    """The canvas is not the image's natural size, so raw pixel coordinates
    would land in the wrong place."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "scaleFor" in block
    assert "naturalWidth" in block


def test_overlay_imports_the_shared_scaling_helpers(js):
    assert "internal/marker_overlay.mjs" in js
    assert "scaleFor" in js
    assert "videoToCanvas" in js


def test_overlay_only_draws_on_the_judged_camera(js):
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "tile.cam" in block


def test_overlay_is_gated_by_the_checkbox(js):
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "showLines" in block


def test_overlay_caches_per_frame_requests(js):
    """One request per (frame, bodypart) — the hook fires on every seek."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "cache" in block.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_wiring.py -v`
Expected: FAIL — `assert "EPIPOLAR OVERLAY" in js`

- [ ] **Step 3: Add the import**

Add to the import block at the top of `src/static/inline_analysis_3d_reprojection.js`:

```javascript
import { scaleFor, videoToCanvas } from "./components/viewer/internal/marker_overlay.mjs";
```

If the cloned module already imports from `marker_overlay.mjs`, extend that statement instead of adding a second one.

- [ ] **Step 4: Replace the no-op with the overlay block**

Delete `function _reprojWireEpipolarOverlay() {}` and append:

```javascript
// ── EPIPOLAR OVERLAY ────────────────────────────────────────────────────────
// Draws the trusted camera's epipolar line onto the judged camera's tile, so a
// marker can be eyeballed against the geometry it is being judged by.
//
// VideoViewer emits drawTile(tile, frame) per tile after every seek. markerEditor
// subscribes first and clears the canvas, so subscribing here — after the
// feature modules are composed — paints on top of the markers.

const _reprojLineCache = new Map();     // `${frame}|${bodypart}` -> segment|null
let _reprojOverlayBound = false;

function _reprojCacheKey(frame, bodypart) {
  return `${frame}|${bodypart}`;
}

function _reprojActiveBodyparts() {
  // Mirror whatever the marker overlay is currently showing; fall back to the
  // bodyparts the last threshold estimate reported.
  const posed = _markerEditor?.posedBodyparts?.();
  if (posed && posed.length) return posed;
  return _reprojAudit ? Object.keys(_reprojAudit.bodyparts) : [];
}

async function _reprojFetchSegment(frame, bodypart) {
  const key = _reprojCacheKey(frame, bodypart);
  if (_reprojLineCache.has(key)) return _reprojLineCache.get(key);

  const pair = _reprojPair();
  if (!pair) return null;
  const qs = new URLSearchParams({
    ref_h5: pair.ref_h5,
    calibration: pair.calibration,
    ref_cam: pair.ref_cam,
    tgt_cam: pair.tgt_cam,
    frame: String(frame),
    bodypart,
  });
  let seg = null;
  try {
    const res = await fetch(`/dlc-3d/reproject/epiline?${qs}`);
    if (res.ok) seg = (await res.json()).segment || null;
  } catch (e) { /* leave seg null; the overlay simply draws nothing */ }

  // Bound the cache so long scrubbing sessions cannot grow it without limit.
  if (_reprojLineCache.size > 4000) _reprojLineCache.clear();
  _reprojLineCache.set(key, seg);
  return seg;
}

function _reprojDrawSegment(tile, seg, color) {
  const canvas = tile.canvasEl, img = tile.imgEl;
  if (!canvas || !img || !seg) return;
  const scale = scaleFor(
    img.naturalWidth, img.naturalHeight, canvas.width, canvas.height,
  );
  const a = videoToCanvas(seg[0][0], seg[0][1], scale);
  const b = videoToCanvas(seg[1][0], seg[1][1], scale);
  const ctx = canvas.getContext("2d");
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.setLineDash([6, 4]);
  ctx.beginPath();
  ctx.moveTo(a.cx, a.cy);
  ctx.lineTo(b.cx, b.cy);
  ctx.stroke();
  ctx.restore();
}

function _reprojJudgedCam() {
  // The judged camera is the one that is NOT the trusted reference.
  return (_reprojEl.refCam()?.value || "cam_1") === "cam_0" ? 1 : 0;
}

function _reprojWireEpipolarOverlay() {
  if (_reprojOverlayBound || !_viewer) return;
  _reprojOverlayBound = true;

  _viewer.on("drawTile", async (tile, frame) => {
    if (!_reprojEl.showLines()?.checked) return;
    if (tile.cam !== _reprojJudgedCam()) return;
    const parts = _reprojActiveBodyparts();
    if (!parts.length) return;
    for (const bp of parts) {
      const seg = await _reprojFetchSegment(frame, bp);
      if (seg) _reprojDrawSegment(tile, seg, "rgba(120,200,255,.85)");
    }
  });

  // A trusted-camera change invalidates every cached line.
  _reprojEl.refCam()?.addEventListener("change", () => _reprojLineCache.clear());
  _reprojEl.showLines()?.addEventListener("change", () => {
    try { _viewer?.redraw?.(); } catch (e) { /* redraw is best-effort */ }
  });
}
```

- [ ] **Step 5: Run tests**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_wiring.py tests/test_reproj_card_namespace.py tests/test_reproj_card_bootstrap.py tests/test_reproj_panel_markup.py -v`
Expected: PASS, all

- [ ] **Step 6: Run the whole suite**

Run: `cd dlc-3D && python3 -m pytest -q`
Expected: all tests pass, including every pre-existing test

- [ ] **Step 7: Commit**

```bash
git add dlc-3D/src/static/inline_analysis_3d_reprojection.js \
        dlc-3D/tests/test_reproj_panel_wiring.py
git commit -m "feat(reprojection): draw epipolar lines on the judged camera's tile"
```

---

### Task 7: Template wiring and rollout preparation

**Files:**
- Modify: `src/templates/dlc_3d.html`
- Create: `docs/superpowers/plans/2026-07-29-reprojection-rollout-checklist.md`

**Interfaces:**
- Consumes: everything above.
- Produces: one `<script>` line in `dlc_3d.html`, and a checklist the user runs when they choose to restart.

**Important:** this task must NOT restart the container. It leaves the feature loaded-on-next-restart and stops.

- [ ] **Step 1: Add the single script line**

In `src/templates/dlc_3d.html`, inside `{% block scripts %}`, immediately after the existing `inline_analysis_3d.js` line, add:

```html
<script type="module" src="{{ url_for('dlc_3d.static', filename='inline_analysis_3d_reprojection.js') }}"></script>
```

This is the only edit to any pre-existing file. The clone injects its own stylesheet, launcher button and card markup at runtime (Task 2), so no `<link>`, no button and no `{% include %}` are needed.

- [ ] **Step 2: Verify the diff is exactly one line**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git diff --stat dlc-3D/src/templates/dlc_3d.html
```

Expected: `1 insertion(+)`, 0 deletions.

- [ ] **Step 3: Confirm nothing else pre-existing was touched**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git diff --stat HEAD~7 -- \
  dlc-3D/src/static/inline_analysis_3d.js \
  dlc-3D/src/static/inline_analysis_3d.css \
  dlc-3D/src/templates/partials/card_inline_analysis_3d.html
```

Expected: no output. If any of these three files shows changes, the clone leaked into the original — stop and fix before going further.

- [ ] **Step 4: Write the rollout checklist**

```markdown
# Reprojection rollout checklist

The `dlc-3d` container has NOT been restarted. Everything below is loaded on the
next restart, which is the user's call.

## What is already live without a restart

`src/static/` is a whole-directory bind mount, so the three cloned static files
and the card fragment are already inside the container. They do nothing yet:
nothing loads `inline_analysis_3d_reprojection.js` until the template is re-read.

## What the restart turns on

1. `src/dlc_3d_bp/` is a whole-directory mount, so `epipolar_core.py` and
   `reprojection.py` are present, but gunicorn must reload before the four
   `/dlc-3d/reproject/*` routes are registered.
2. `src/templates/dlc_3d.html` is individually mounted, but Flask caches
   templates in production, so the new `<script>` line needs the reload too.

No `docker-compose.yml` change is required — that is why the card markup ships
as a static fragment instead of a Jinja partial.

## Restart, when the tool is idle

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose up -d dlc-3d
```

## Smoke test after restart

1. Open `http://localhost:5000/dlc-3d/`.
2. Confirm **3D Inline Analysis - Reprojection** appears directly below
   **3D Inline Analysis** in the launcher list.
3. Open the original card first and confirm it still works — it must be
   untouched.
4. Open the reprojection card. Load the `070126` session, pick the
   `snapshot_best-180` overlay h5 on cam0.
5. Click **Estimate thresholds**. Expect a per-bodypart table with `t_ok`
   roughly 3–22 px and `source` = `self` for most bodyparts.
6. Tick **Show epipolar lines** and scrub. Lines should appear on the judged
   camera's tile and pass through well-tracked markers.
7. Click **Run**. Expect `_reprojected.h5` for both cameras plus the `.json`
   and `.npz` beside the source h5 files.
8. Re-open the original 3D Inline Analysis card and confirm its 3D background
   colour and view prefs are unchanged — proof the `ui-setting` namespacing
   holds.

## Rollback

Remove the one `<script>` line from `dlc_3d.html` and restart. The cloned static
files become inert; no data written by a run is removed, since every artifact is
a new `_reprojected.*` file and no original was modified.
```

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/templates/dlc_3d.html \
        dlc-3D/docs/superpowers/plans/2026-07-29-reprojection-rollout-checklist.md
git commit -m "feat(reprojection): load the cloned card and document the rollout"
```

- [ ] **Step 6: Report and stop**

Do not restart the container. Report to the user: what was built, that the whole
suite passes, and that the rollout checklist is ready for them to run when the
tool is idle.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
| --- | --- |
| Clone named "3D Inline Analysis - Reprojection" | 1 |
| Button directly below the existing one | 2 |
| `ia3d-` → `ia3dr-` rename across markup, JS, CSS | 1 |
| No shared `window.__iaViewer` | 1 |
| Divergence 1 — namespaced `ui-setting` keys | 3 |
| Divergence 2 — never stop a shared session | 3 |
| Card markup as a static fragment (Rollout Option 1) | 2 |
| Reference camera selector + per-bodypart overrides | 4, 5 |
| `k₁`/`k₂` controls showing live thresholds | 4, 5 |
| Run button writing artifacts | 5 |
| Epipolar lines on the target tile | 6 |
| Verdict counts | 5 |
| Restart deferred; one-time reload documented | 7 |

Not covered here by design: the engine itself, which is the first plan. The
spec's "timeline banded by verdict" is deliberately deferred — it needs the npz
arrays plumbed through the coverage-timeline component, which is worth doing
only once the verdicts are trusted on real sessions. Flagged rather than
silently dropped.

**Placeholder scan:** none. Task 2 and Task 5 each introduce a named no-op that
a later task deletes, and the tests assert the deletion.

**Type consistency:** panel element ids are defined in Task 4 and consumed by
`_reprojEl` in Task 5 — identical strings. `_reprojPair()` returns
`{ref_cam, tgt_cam, ref_h5, tgt_h5, calibration}` in Task 5 and is consumed with
those exact keys in Task 6. `_reprojAudit` is assigned in Task 5 and read in
Task 6. Threshold keys (`t_ok`, `t_bad`, `med`, `mad`, `n_highconf`,
`threshold_source`) match the engine plan's `auto_threshold` return value.
`_reprojWirePanel` is declared in Task 2, replaced in Task 5;
`_reprojWireEpipolarOverlay` is declared in Task 5, replaced in Task 6.

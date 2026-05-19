# File-Browser Component + Dblclick UX Fix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
1. Fix the multi-select file browser's double-click UX so that double-clicking a file ADDs to queue and shows brief "Added ✓" feedback *without* collapsing the browser.
2. Move the factory out of `lp_cards.js` into a shared ES module so any future picker re-uses one canonical implementation.
3. Write a policy doc + static-analysis pytest tests that enforce the contract (future contributors can't silently reintroduce divergent pickers).

**Architecture:**
- New module: `src/static/components/file_browser.js`, exporting `makeFileBrowser({ inputEl, paneEl, dirOnly, onPick })`. Same surface as the current `_lpMakeBrowser`, plus an optional `onPick` callback the factory invokes on dblclick (so the row-level feedback can stay encapsulated inside the component).
- `lp_cards.js` removes its internal copy, imports the factory, and re-exports nothing (private to the LP cards init).
- Add a policy doc at `docs/policies/file-browser-component.md`.
- Static-analysis tests in `tests/test_file_browser_policy.py` enforce: factory exports the right name; dblclick handler does NOT contain `classList.add("hidden")`; `lp_cards.js` imports the canonical factory and does NOT redefine an inline equivalent.

**Tech stack:** Vanilla ES modules, pytest for the policy tests. No new deps.

---

## File Structure

```
src/static/components/
  file_browser.js                       ← NEW: canonical factory

src/static/
  lp_cards.js                           ← MODIFY: import + use the factory; delete inline copy

docs/policies/
  file-browser-component.md             ← NEW: policy doc

tests/
  test_file_browser_policy.py           ← NEW: static-analysis enforcement

dlc-3D/CLAUDE.md                        ← MODIFY: add a paragraph pointing future contributors at the policy
```

---

### Task 1: Extract the factory into a new module + fix dblclick

**Files:**
- Create: `src/static/components/file_browser.js`
- Modify: `src/static/lp_cards.js` (remove inline copy, import the new module)
- Test:   `tests/test_file_browser_policy.py` (Step 6 — initial round of tests)

- [ ] **Step 1: Write failing static-analysis tests**

```python
# tests/test_file_browser_policy.py
"""Enforce the file-browser component policy:

- A single canonical factory lives at src/static/components/file_browser.js.
- It exports `makeFileBrowser` (named export).
- Its double-click handler does NOT hide the pane (no classList.add("hidden")
  inside the dblclick listener block) — double-clicking adds to queue and
  shows transient feedback while keeping the browser open.
- lp_cards.js imports the canonical factory; it does NOT redefine an inline
  equivalent.

These are deliberately static-analysis (regex over source) because the project
has no JS unit-test runner. The checks are tight enough to catch a future
divergent picker introduced by accident.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
FB_PATH    = ROOT / "src" / "static" / "components" / "file_browser.js"
LP_PATH    = ROOT / "src" / "static" / "lp_cards.js"
POLICY_DOC = ROOT.parent / "docs" / "policies" / "file-browser-component.md"


def test_file_browser_module_exists():
    assert FB_PATH.is_file(), f"missing canonical file browser at {FB_PATH}"


def test_file_browser_exports_makeFileBrowser():
    src = FB_PATH.read_text()
    # Match either ES export shape:
    #   export function makeFileBrowser
    #   export { makeFileBrowser }
    assert re.search(r"\bexport\s+function\s+makeFileBrowser\b", src) or \
           re.search(r"\bexport\s*\{[^}]*\bmakeFileBrowser\b[^}]*\}", src), \
        "file_browser.js must export `makeFileBrowser`"


def test_dblclick_handler_does_not_hide_pane():
    src = FB_PATH.read_text()
    # Find the dblclick listener block, then assert it does not add the "hidden" class.
    m = re.search(
        r"addEventListener\(\s*[\"']dblclick[\"']\s*,\s*[^{]*\{(?P<body>.*?)^\s*\}\s*\)",
        src,
        re.DOTALL | re.MULTILINE,
    )
    assert m, "no dblclick listener found in file_browser.js"
    body = m.group("body")
    assert 'classList.add("hidden")' not in body and "classList.add('hidden')" not in body, (
        "dblclick handler must NOT hide the browser pane — double-click should keep "
        "the browser open with a transient 'Added' badge instead"
    )


def test_lp_cards_imports_canonical_factory():
    src = LP_PATH.read_text()
    assert re.search(
        r"import\s*\{[^}]*\bmakeFileBrowser\b[^}]*\}\s*from\s*[\"']\./components/file_browser\.js[\"']",
        src,
    ), "lp_cards.js must import { makeFileBrowser } from ./components/file_browser.js"


def test_lp_cards_does_not_redefine_factory_inline():
    src = LP_PATH.read_text()
    # No inline `function _lpMakeBrowser` and no `function makeFileBrowser` definitions.
    assert "function _lpMakeBrowser(" not in src, \
        "lp_cards.js must not redefine the factory — import from ./components/file_browser.js"
    assert not re.search(r"\bfunction\s+makeFileBrowser\b", src), \
        "lp_cards.js must not define makeFileBrowser locally"


def test_policy_doc_exists():
    assert POLICY_DOC.is_file(), f"missing policy doc at {POLICY_DOC}"
    text = POLICY_DOC.read_text().lower()
    assert "makefilebrowser" in text or "make_file_browser" in text or "file_browser.js" in text, \
        "policy doc should reference the canonical component"
```

- [ ] **Step 2: Run failing tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/test_file_browser_policy.py -v
```

Expected: 6 failures (module missing, doc missing, etc.).

- [ ] **Step 3: Create `src/static/components/file_browser.js`**

```javascript
// src/static/components/file_browser.js
//
// Canonical multi-select directory-tree file browser.
//
// USAGE:
//   import { makeFileBrowser } from "./components/file_browser.js";
//   const picker = makeFileBrowser({
//     inputEl: document.getElementById("my-target"),
//     paneEl:  document.getElementById("my-browser"),
//     dirOnly: false,                  // true → hide files entirely
//     onPick:  (path) => addToQueue(path),  // called on dblclick file
//   });
//   document.getElementById("my-browse-btn").addEventListener("click",
//     () => picker.openAt("/user-data"));
//
// SEMANTICS:
//   - Single-click a row: highlight + write its path to inputEl. Folders also
//     expand inline.
//   - Double-click a file row: emit a transient "Added ✓" badge that fades
//     out, AND invoke onPick(path) if provided. THE BROWSER STAYS OPEN —
//     never auto-hide on dblclick. Users batch-select many files in one
//     browsing session.
//   - paneEl also receives a `file-browser:pick` CustomEvent on dblclick
//     for back-compat with listeners that prefer DOM events.
//
// SHARED HISTORICAL EVENT: legacy lp_cards code listens for
// `lp-picker-dblclick`. We dispatch BOTH names on the pane so the old wiring
// in lp_cards.js (if it lingers) keeps working during transitions.

const _VIDEO_EXTS = new Set([".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v"]);
const _IMAGE_EXTS = new Set([".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"]);

function _supportedFile(name) {
  const i = name.lastIndexOf(".");
  if (i < 0) return false;
  const ext = name.slice(i).toLowerCase();
  return _VIDEO_EXTS.has(ext) || _IMAGE_EXTS.has(ext);
}

function _flashAddedBadge(rowEl) {
  // Build (or reuse) a small badge that fades out after ~1.2s.
  let badge = rowEl.querySelector(".file-browser-added-badge");
  if (!badge) {
    badge = document.createElement("span");
    badge.className = "file-browser-added-badge";
    badge.textContent = "Added ✓";
    badge.style.cssText =
      "margin-left:.4rem;padding:.05rem .35rem;border-radius:3px;" +
      "background:var(--accent, #63b3ed);color:#0a0a1a;" +
      "font-size:.65rem;font-weight:600;font-family:var(--mono);" +
      "transition:opacity .9s ease-out;opacity:1;";
    rowEl.appendChild(badge);
  } else {
    // Restart the fade if the same row is dblclicked again.
    badge.style.transition = "none";
    badge.style.opacity = "1";
    // force reflow so the next transition runs
    void badge.offsetWidth;
    badge.style.transition = "opacity .9s ease-out";
  }
  // Fade and remove
  setTimeout(() => { badge.style.opacity = "0"; }, 300);
  setTimeout(() => { if (badge.parentNode) badge.parentNode.removeChild(badge); }, 1300);
}

export function makeFileBrowser({ inputEl, paneEl, dirOnly = false, onPick = null }) {
  let highlightedRow = null;
  let highlightedPath = "";
  let currentDir = "";

  function setHighlight(row, path) {
    if (highlightedRow && highlightedRow !== row) {
      highlightedRow.style.background = "";
      highlightedRow.style.outline = "";
    }
    highlightedRow = row;
    highlightedPath = path;
    inputEl.value = path;
    row.style.background = "var(--accent-dim, rgba(99,179,237,.18))";
    row.style.outline = "1px solid var(--accent, #63b3ed)";
  }

  function emitPick(path, rowEl) {
    if (onPick) {
      try { onPick(path); } catch (e) { /* swallow — never break the browser */ }
    }
    // Legacy + canonical DOM events (bubble:false → only the owner pane sees them)
    paneEl.dispatchEvent(new CustomEvent("file-browser:pick",
      { detail: { path }, bubbles: false }));
    paneEl.dispatchEvent(new CustomEvent("lp-picker-dblclick",
      { detail: { path }, bubbles: false }));
    if (rowEl) _flashAddedBadge(rowEl);
  }

  function makeEntry(name, fullPath, isDir) {
    const wrapper = document.createElement("div");
    const row = document.createElement("div");
    row.style.cssText =
      "display:flex;align-items:center;gap:.3rem;padding:.15rem .4rem;" +
      "border-radius:3px;cursor:pointer";
    const arrow = document.createElement("span");
    arrow.style.cssText = "width:.8rem;color:var(--text-dim);font-size:.7rem";
    arrow.textContent = isDir ? "▶" : "·";
    const label = document.createElement("span");
    label.style.cssText =
      "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;" +
      "white-space:nowrap;font-family:var(--mono);font-size:.74rem";
    label.textContent = name + (isDir ? "/" : "");
    row.appendChild(arrow); row.appendChild(label);
    wrapper.appendChild(row);

    const childContainer = document.createElement("div");
    childContainer.style.cssText = "display:none;padding-left:1rem";
    wrapper.appendChild(childContainer);

    let loaded = false, expanded = false;

    if (isDir) {
      row.addEventListener("click", async () => {
        setHighlight(row, fullPath);
        if (!expanded && !loaded) {
          childContainer.innerHTML =
            "<span style=\"font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block\">Loading…</span>";
          childContainer.style.display = "block";
          try {
            const res = await fetch(`/fs/ls?path=${encodeURIComponent(fullPath)}`);
            const d = await res.json();
            childContainer.innerHTML = "";
            if (!d.error) {
              const vis = (d.entries || []).filter((e) =>
                (e.type === "dir" && e.has_media !== false) ||
                (!dirOnly && e.type === "file" && _supportedFile(e.name)));
              vis.forEach((e) =>
                childContainer.appendChild(makeEntry(
                  e.name,
                  fullPath.replace(/\/+$/, "") + "/" + e.name,
                  e.type === "dir",
                )));
              if (!vis.length) {
                childContainer.innerHTML =
                  "<span style=\"font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block\">(no supported entries)</span>";
              }
            } else {
              childContainer.innerHTML =
                `<span style="font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block">${d.error}</span>`;
            }
          } catch (e) {
            childContainer.innerHTML =
              "<span style=\"font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block\">Error loading.</span>";
          }
          loaded = true; expanded = true; arrow.textContent = "▼";
        } else {
          expanded = !expanded;
          childContainer.style.display = expanded ? "block" : "none";
          arrow.textContent = expanded ? "▼" : "▶";
        }
      });
      // Directories on dblclick: same as single-click here (no auto-pick).
    } else {
      // File row
      row.addEventListener("click", () => setHighlight(row, fullPath));
      row.addEventListener("dblclick", (e) => {
        e.stopPropagation();
        inputEl.value = fullPath;
        // IMPORTANT: do NOT hide paneEl here. The browser stays open so the
        // user can keep adding more files in the same browse session. The
        // transient "Added ✓" badge gives feedback that the click registered.
        emitPick(fullPath, row);
      });
    }

    return wrapper;
  }

  async function browseDir(dirPath) {
    currentDir = dirPath;
    inputEl.value = dirPath;
    paneEl.innerHTML = "<span style=\"font-size:.8rem;color:var(--text-dim)\">Loading…</span>";
    try {
      const res = await fetch(`/fs/ls?path=${encodeURIComponent(dirPath)}`);
      const data = await res.json();
      if (data.error) { paneEl.textContent = data.error; return; }
      paneEl.innerHTML = "";
      const visible = (data.entries || []).filter((e) =>
        (e.type === "dir" && e.has_media !== false) ||
        (!dirOnly && e.type === "file" && _supportedFile(e.name)));
      if (!visible.length) {
        const empty = document.createElement("span");
        empty.style.cssText = "font-size:.78rem;color:var(--text-dim);padding:.3rem;display:block";
        empty.textContent = dirOnly ? "(no subfolders)" : "(no supported video or image files)";
        paneEl.appendChild(empty);
      } else {
        visible.forEach((e) =>
          paneEl.appendChild(makeEntry(
            e.name,
            (data.path || dirPath).replace(/\/+$/, "") + "/" + e.name,
            e.type === "dir",
          )));
      }
    } catch (err) {
      paneEl.textContent = "Failed to load.";
    }
  }

  function openAt(initialPath) {
    const isHidden = paneEl.classList.contains("hidden");
    paneEl.classList.toggle("hidden");
    if (!isHidden) return;
    const typed = inputEl.value.trim() || initialPath || "/user-data";
    browseDir(typed);
  }

  function up() {
    const cur = (inputEl.value.trim() || currentDir).replace(/\/+$/, "");
    if (!cur) return;
    const parent = cur.split("/").slice(0, -1).join("/") || "/";
    if (parent !== cur) { browseDir(parent); paneEl.classList.remove("hidden"); }
  }

  return { browseDir, openAt, up, getHighlighted: () => highlightedPath };
}
```

- [ ] **Step 4: Update `lp_cards.js`** — at the top of the file, add an import for the canonical factory, then delete the inline `_lpMakeBrowser`, `_lpSupportedFile`, `_LP_VIDEO_EXTS`, `_LP_IMAGE_EXTS` definitions. Replace every call site `_lpMakeBrowser(...)` with `makeFileBrowser(...)`.

The import line goes near the top, after any "use strict" or comments:
```javascript
import { makeFileBrowser } from "./components/file_browser.js";
```

Search for `_lpMakeBrowser(` to find the three call sites (predict's video and dest browsers, convert's add-videos browser). Replace the function name only — same argument shape.

If the convert-card's add-videos panel currently wires up a `lp-picker-dblclick` event listener on the pane, you can leave it; the new component emits BOTH `file-browser:pick` and the legacy `lp-picker-dblclick` so existing handlers keep working. New consumers should prefer `file-browser:pick` (it's named more descriptively).

- [ ] **Step 5: Run pytest**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/test_file_browser_policy.py tests/test_lp_routes.py tests/test_lp_video_adder.py -v
```

Expected: the `test_policy_doc_exists` test still fails (Task 2). The others pass.

- [ ] **Step 6: Commit**

```bash
git add src/static/components/file_browser.js src/static/lp_cards.js tests/test_file_browser_policy.py
git commit -m "feat(dlc-3d): canonical file_browser component + dblclick-keeps-open UX"
```

---

### Task 2: Policy doc

**File:** `docs/policies/file-browser-component.md` (under the parent supports/ docs/, NOT inside dlc-3D/).

The plan-writer note: the supports-repo policies dir already lives at `/home/sam/docker-images/deeplabcut-webapp-docker-supports/docs/`. We add a new `policies/` subdir if missing.

- [ ] **Step 1: Run failing test** (`test_policy_doc_exists` from Task 1) — confirm it fails.

- [ ] **Step 2: Create the doc**

```markdown
# Policy: file-browser component

**TL;DR:** Every multi-select directory-tree file picker in this module's frontend MUST use `src/static/components/file_browser.js`. Do not write a new one.

## The canonical component

Path: `dlc-3D/src/static/components/file_browser.js`
Export: `makeFileBrowser({ inputEl, paneEl, dirOnly?, onPick? })`

It owns:
- Single-click highlighting + recursive folder expansion
- File-type filtering (video + image extensions today; centralise extension changes there)
- The double-click "add to queue" UX, including the transient "Added ✓" badge that fades out without closing the browser
- The `file-browser:pick` and (legacy) `lp-picker-dblclick` events dispatched on the pane

## When to add a new browser

Only when your UX legitimately differs from "user picks one or many files/folders from a tree." Examples that justify a separate widget:
- A single-pick browser tied to "load this DLC project" (see `card_3d_extract.html`'s session picker — different shape, no queue).
- A grid-based image gallery (different layout, different selection semantics).

If you're tempted to copy `file_browser.js` and "tweak a few things," stop and extend the canonical component instead — add an option to its config object.

## Why this rule exists

Prior to this policy three near-identical implementations existed across `lp_cards.js`. A bug fix (double-click was collapsing the browser instead of just adding to queue) had to land in all three. Worse, a fourth divergent inline copy slipped into a card during a refactor and silently broke the picker for that card. The static-analysis tests in `dlc-3D/tests/test_file_browser_policy.py` enforce that:

1. The canonical component exists.
2. It exports `makeFileBrowser`.
3. Its `dblclick` handler does not hide the pane.
4. `lp_cards.js` imports from it (no inline duplicates).
5. This very policy doc exists.

If a future contributor adds another file picker by copying the factory, those tests will fail and force the conversation back to "extend the component instead."

## Adding a new consumer

```javascript
import { makeFileBrowser } from "./components/file_browser.js";

const picker = makeFileBrowser({
  inputEl: document.getElementById("my-target"),
  paneEl:  document.getElementById("my-browser-pane"),
  dirOnly: false,                       // true to hide files entirely
  onPick:  (path) => myAddToQueue(path) // dblclick callback (optional)
});

document.getElementById("my-browse-btn").addEventListener("click",
  () => picker.openAt("/user-data"));
document.getElementById("my-up-btn").addEventListener("click",
  () => picker.up());
```

Optional: subscribe to `file-browser:pick` instead of (or in addition to) `onPick` if you want multiple listeners.

## Adding capabilities to the component

If your card needs behavior the component doesn't have, **add it to the component**, not your card:
- New filter — extend the extension sets or add a `fileFilter: (name) => bool` option.
- Multi-select via Shift-click — add `multiSelect: true` and an `onSelectionChange(paths[])` callback.
- Different empty-state copy — add a `dirOnlyEmptyText` / `defaultEmptyText` option.

When you extend it, update both this policy doc and the static-analysis tests to cover the new contract.
```

- [ ] **Step 3: Append a reference in dlc-3D/CLAUDE.md**

Append to `dlc-3D/CLAUDE.md` (create the file if missing) a short paragraph:

```markdown
## File browsers

All multi-select directory-tree pickers MUST use `src/static/components/file_browser.js`'s `makeFileBrowser`. Do not redefine the factory inline. See `../docs/policies/file-browser-component.md` for the contract and the rationale.
```

If `dlc-3D/CLAUDE.md` doesn't exist yet (none was found at session start), create it with just this section.

- [ ] **Step 4: Re-run tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/test_file_browser_policy.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add docs/policies/file-browser-component.md dlc-3D/CLAUDE.md
git commit -m "docs: file-browser component policy + CLAUDE.md pointer"
```

(Run that `git add` from the supports repo root, not from inside `dlc-3D/`.)

---

### Task 3: Restart container + manual smoke

The Flask container uses single-file bind-mounts for individual templates but mounts `src/static/` as a directory, so the new `components/file_browser.js` file is picked up live without a restart. The lp_cards.js change is also picked up live (same directory mount).

- [ ] **Step 1: Verify served JS contains the import**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose exec dlc-3d python3 -c "
import urllib.request
js = urllib.request.urlopen('http://localhost:5050/dlc-3d/static/lp_cards.js').read().decode()
print('imports makeFileBrowser:', 'makeFileBrowser' in js and 'components/file_browser.js' in js)
print('still defines _lpMakeBrowser:', '_lpMakeBrowser' in js)
"
docker compose exec dlc-3d python3 -c "
import urllib.request
fb = urllib.request.urlopen('http://localhost:5050/dlc-3d/static/components/file_browser.js').read().decode()
print('file_browser.js size:', len(fb), 'bytes')
print('exports makeFileBrowser:', 'export function makeFileBrowser' in fb or 'export { makeFileBrowser' in fb)
"
```

Expected: imports=True, _lpMakeBrowser=False (not defined anymore), file_browser.js served and exports the function.

- [ ] **Step 2: Manual smoke check**

In the browser, hard-refresh the dlc-3d page, open the Predict card OR the Convert card's Add-videos panel, click Browse, then double-click a video file. Expected:
- File path appears in the input.
- File path is added to the queue list below.
- A small "Added ✓" badge appears next to the row and fades out in ~1.2s.
- **The browser pane stays open** — you can immediately double-click another file.

If anything misbehaves, capture the failure and report.

- [ ] **Step 3: No commit** (smoke only — no code changes).

---

### Task 4: Run the full test suite

- [ ] `cd dlc-3D && pytest tests/ -x -q`

Acceptable result: same baseline as the previous session (pre-existing e2e/Playwright failures and the user's dirty predict_runner.py-driven failures may remain). The new tests in `test_file_browser_policy.py` must all pass. No NEW regressions outside that scope.

If a previously-passing test starts failing because of these changes, fix it; if a previously-failing test is still failing for the same pre-existing reason, leave it and note it in the report.

---

## Self-review

- [x] No new backend dependencies. Pure frontend + policy + static-analysis tests.
- [x] Backward compatibility: the new component dispatches both `file-browser:pick` (canonical) and `lp-picker-dblclick` (legacy) so any code still listening to the old event keeps working.
- [x] dblclick keeps pane open — explicit comment in the file_browser.js source so a future contributor sees the intent.
- [x] Static-analysis tests are deliberate over a JS test runner — minimal infrastructure, catches the regressions that matter (factory absence, divergent inline copies, dblclick reintroducing hide()).
- [x] The frame-extractor browser in dlc_3d.js is intentionally NOT migrated — different UX (single-pick, no queue). Policy doc explains why.
- [x] No backend / no celery worker touched — no worker restart required.

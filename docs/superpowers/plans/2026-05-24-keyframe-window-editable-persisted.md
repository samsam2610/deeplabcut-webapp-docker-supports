# Editable Keyframe + Persisted Window (finalize + create-clip) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the keyframe editable (typing auto-locks), default length 800 with `before`/`after` remembered per project (sqlite), and unify the create-clip panel onto the same keyframe-window model — via one shared `makeKeyframeWindow` controller.

**Architecture:** Backend (main webapp): new pure `project_settings.py` (per-project `ui_settings.sqlite`) + two `ui-setting` endpoints. Frontend (dlc-3D): new `makeKeyframeWindow` controller reusing the existing pure `keyframe_window.mjs`; the finalize + clip panels each instantiate it. The clip controller writes computed start/length into the hidden inputs the existing `clipExtractor` already reads (no clipExtractor change).

**Tech Stack:** Python/Flask + sqlite (backend); vanilla ES modules + Jinja partial (frontend). pytest (backend + static contracts), node:test (pure math, already covered).

**Spec:** `docs/superpowers/specs/2026-05-24-keyframe-window-editable-persisted-design.md`

**Two repos:**
- Backend: `/home/sam/docker-images/deeplabcut-webapp-docker`
- Frontend: `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D`

**Run only the test files named in each task.**

---

### Task 1: Backend per-project settings store + endpoints (main webapp)

**Work from:** `/home/sam/docker-images/deeplabcut-webapp-docker`

**Files:**
- Create: `src/dlc/project_settings.py`
- Modify: `src/dlc/inline_analysis.py` (add two routes)
- Test: `tests/test_project_settings.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_project_settings.py`:

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dlc import project_settings as ps


def test_set_get_roundtrip(tmp_path):
    assert ps.get_setting(tmp_path, "clip_window") is None
    assert ps.get_setting(tmp_path, "clip_window", "DEF") == "DEF"
    ps.set_setting(tmp_path, "clip_window", '{"before":200,"after":599}')
    assert ps.get_setting(tmp_path, "clip_window") == '{"before":200,"after":599}'
    # overwrite
    ps.set_setting(tmp_path, "clip_window", '{"before":10,"after":20}')
    assert ps.get_setting(tmp_path, "clip_window") == '{"before":10,"after":20}'
    # independent keys
    ps.set_setting(tmp_path, "finalize_window", '{"before":1,"after":2}')
    assert ps.get_setting(tmp_path, "clip_window") == '{"before":10,"after":20}'
    assert ps.get_setting(tmp_path, "finalize_window") == '{"before":1,"after":2}'


def test_db_file_created_under_project(tmp_path):
    ps.set_setting(tmp_path, "k", "v")
    assert (tmp_path / "ui_settings.sqlite").is_file()
```

- [ ] **Step 2: Run to verify FAIL**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest tests/test_project_settings.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `project_settings.py`**

Create `src/dlc/project_settings.py` (mirrors `marks_store.py`'s isolated-sqlite pattern):

```python
"""
Per-project UI settings, persisted in <project>/ui_settings.sqlite.

A tiny key→value store (the value is an opaque string; callers may store JSON).
Used to remember inline-3D keyframe-window shapes (before/after) per project.
Imports no Flask/DLC/Redis — unit-testable against tmp_path.

Schema (v1): meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_FILENAME = "ui_settings.sqlite"


def _db_path(project_path) -> Path:
    return Path(project_path) / DB_FILENAME


@contextmanager
def _connect(project_path):
    conn = sqlite3.connect(str(_db_path(project_path)), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        yield conn
    finally:
        conn.close()


def get_setting(project_path, key: str, default=None):
    """Return the stored string for `key`, or `default` if absent."""
    if not _db_path(project_path).exists():
        return default
    with _connect(project_path) as conn:
        cur = conn.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
    return row[0] if row else default


def set_setting(project_path, key: str, value: str) -> None:
    """Insert or replace `key` = `value` (value is stored as text)."""
    with _connect(project_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, str(value)))
        conn.execute("COMMIT")
```

- [ ] **Step 4: Run to verify the store test PASSES**

Run: `python -m pytest tests/test_project_settings.py -q`
Expected: PASS.

- [ ] **Step 5: Add the two endpoints**

In `src/dlc/inline_analysis.py`, add (near the other routes; it already imports `Blueprint, request, jsonify` and defines `_active_project()` returning a dict with `project_path`). Add at module level near the top (after imports): `import dlc.project_settings as _project_settings` — match the existing import style in the file (check whether it uses `from dlc import …` or `import dlc.…`; mirror it). Then add:

```python
_UI_SETTING_KEYS = {"finalize_window", "clip_window"}


@bp.route("/dlc/project/ui-setting", methods=["GET"])
def get_ui_setting():
    project = _active_project()
    if not project:
        return jsonify({"error": "No active DLC project."}), 400
    key = request.args.get("key", "")
    if key not in _UI_SETTING_KEYS:
        return jsonify({"error": "unknown key"}), 400
    project_path = project.get("project_path", "")
    if not project_path:
        return jsonify({"error": "Active project has no path."}), 400
    return jsonify({"value": _project_settings.get_setting(project_path, key)})


@bp.route("/dlc/project/ui-setting", methods=["POST"])
def set_ui_setting():
    project = _active_project()
    if not project:
        return jsonify({"error": "No active DLC project."}), 400
    body = request.get_json(silent=True) or {}
    key, value = body.get("key", ""), body.get("value", "")
    if key not in _UI_SETTING_KEYS:
        return jsonify({"error": "unknown key"}), 400
    project_path = project.get("project_path", "")
    if not project_path:
        return jsonify({"error": "Active project has no path."}), 400
    _project_settings.set_setting(project_path, key, str(value))
    return jsonify({"ok": True})
```

(Verify the blueprint variable is named `bp` in this file; if it's different, match it. Verify `_active_project()` returns a dict containing `project_path` — it is populated from Redis by the project-load route; if the key is named differently, e.g. only `config_path`, derive `project_path = str(Path(config_path).parent)`.)

- [ ] **Step 6: Commit**

```bash
git add src/dlc/project_settings.py src/dlc/inline_analysis.py tests/test_project_settings.py
git commit -m "feat(dlc): per-project ui_settings sqlite store + ui-setting endpoints

project_settings.py keeps <project>/ui_settings.sqlite (meta key/value), mirroring
marks_store. GET/POST /dlc/project/ui-setting read/write an allow-listed key for the
active project — used to remember inline-3D keyframe-window shapes.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Shared `makeKeyframeWindow` controller (dlc-3D)

**Work from:** `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D`

**Files:**
- Create: `src/static/keyframe_window_ui.js`
- Test: `tests/test_keyframe_window_ui.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_keyframe_window_ui.py`:

```python
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "static" / "keyframe_window_ui.js"


def _src():
    assert SRC.is_file(), f"missing {SRC}"
    return SRC.read_text()


def test_exports_factory():
    assert re.search(r"export\s+function\s+makeKeyframeWindow\b", _src())


def test_uses_pure_math_and_behaviors():
    s = _src()
    assert "keyframe_window.mjs" in s and "syncWindow" in s and "finalizeRange" in s
    assert "frameChange" in s, "must track the viewer's current frame"
    assert re.search(r'e\.key\s*===\s*"l"', s) or re.search(r"\.key\s*===\s*'l'", s), "must wire the 'l' shortcut"
    assert "/dlc/project/ui-setting" in s, "must load+save the per-project setting"
    # typing the keyframe auto-locks
    assert "els.keyframe" in s and "setLock(true)" in s
    # exposes getRange + load
    assert "getRange" in s and re.search(r"\bload\b", s)
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_keyframe_window_ui.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the controller**

Create `src/static/keyframe_window_ui.js`:

```javascript
// Reusable keyframe-window controller for the inline-3D finalize + create-clip
// panels. Owns the editable keyframe (typing auto-locks), before/after/length
// sync, lock checkbox + 'l' shortcut, range readout, frameChange tracking, and
// per-project persistence of {before, after}. Pure math: keyframe_window.mjs.
//
// opts: { viewer, panelEl, els:{keyframe,lock,before,after,length,range}, settingKey, onChange? }
import { syncWindow, finalizeRange } from "./components/viewer/internal/keyframe_window.mjs";

export function makeKeyframeWindow({ viewer, panelEl, els, settingKey, onChange }) {
  let keyframe = 0;
  let locked = false;
  let saveTimer = null;

  const num = (el, min) => { const n = parseInt(el && el.value, 10); return Number.isFinite(n) ? Math.max(min, n) : min; };
  const vals = () => ({ before: num(els.before, 0), after: num(els.after, 0), length: num(els.length, 1) });
  const fc = () => (viewer ? viewer.frameCount() : 0);

  function refresh() {
    // don't clobber the keyframe input while the user is typing in it
    if (els.keyframe && document.activeElement !== els.keyframe) els.keyframe.value = String(keyframe);
    const { before, after } = vals();
    const r = finalizeRange(keyframe, before, after, fc());
    if (els.range) els.range.textContent = `frames ${r.start}–${r.end} (${r.n})`;
    if (onChange) onChange(r);
  }

  function setLock(on) {
    locked = !!on;
    if (els.lock) els.lock.checked = locked;
    if (!locked && viewer) keyframe = viewer.currentFrame();
    refresh();
  }

  function onWindowInput(edited) {
    const out = syncWindow(edited, vals());
    if (els.before) els.before.value = out.before;
    if (els.after) els.after.value = out.after;
    if (els.length) els.length.value = out.length;
    refresh();
    save();
  }

  function save() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const { before, after } = vals();
      fetch("/dlc/project/ui-setting", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: settingKey, value: JSON.stringify({ before, after }) }),
      }).catch(() => {});
    }, 400);
  }

  async function load() {
    try {
      const d = await (await fetch(`/dlc/project/ui-setting?key=${encodeURIComponent(settingKey)}`)).json();
      if (d && d.value) {
        const w = JSON.parse(d.value);
        if (els.before && Number.isFinite(w.before)) els.before.value = w.before;
        if (els.after && Number.isFinite(w.after)) els.after.value = w.after;
        if (els.length) els.length.value = num(els.before, 0) + num(els.after, 0) + 1;
      }
    } catch (_) { /* keep defaults */ }
    setLock(false);   // keyframe = current frame, unlocked, refresh
  }

  // ── wiring ──
  if (els.keyframe) {
    els.keyframe.addEventListener("input", () => {
      const n = parseInt(els.keyframe.value, 10);
      if (Number.isFinite(n)) { keyframe = n; setLock(true); }   // typing auto-locks
    });
  }
  for (const id of ["before", "after", "length"]) {
    if (els[id]) els[id].addEventListener("input", () => onWindowInput(id));
  }
  [els.keyframe, els.before, els.after, els.length].forEach((el) => {
    if (el) el.addEventListener("keydown", (e) => e.stopPropagation());
  });
  if (els.lock) els.lock.addEventListener("change", (e) => setLock(e.target.checked));
  if (viewer) viewer.on("frameChange", (n) => { if (!locked) { keyframe = n; refresh(); } });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "l" && e.key !== "L") return;
    if (!panelEl || panelEl.offsetParent === null) return;        // only when this panel is visible
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
    e.preventDefault();
    setLock(!locked);
  });

  return {
    getRange: () => { const { before, after } = vals(); return finalizeRange(keyframe, before, after, fc()); },
    refresh, load, setLock,
  };
}
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_keyframe_window_ui.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/static/keyframe_window_ui.js tests/test_keyframe_window_ui.py
git commit -m "feat(dlc-3d): shared makeKeyframeWindow controller

Editable keyframe (typing auto-locks), before/after/length sync via syncWindow,
lock checkbox + 'l', range readout, frameChange tracking, and debounced
per-project persistence of {before,after} via /dlc/project/ui-setting. Reused by
the finalize + create-clip panels.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Finalize panel — editable keyframe + use the shared controller (dlc-3D)

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html` (keyframe span→input; defaults)
- Modify: `src/static/inline_analysis_3d.js` (replace bespoke finalize-window glue with `makeKeyframeWindow`)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_finalize_keyframe_editable_and_uses_shared_controller():
    html = CARD.read_text()
    js = JS.read_text()
    # keyframe is now an editable input (not a span)
    assert re.search(r'<input[^>]*id="ia3d-finalize-keyframe"', html), "finalize keyframe must be an <input>"
    # shared controller imported + instantiated for finalize
    assert "makeKeyframeWindow" in js and "keyframe_window_ui" in js
    assert '"finalize_window"' in js or "'finalize_window'" in js
    assert "_finalizeKW" in js
    # old bespoke finalize-window helpers are gone
    assert "_refreshFinalizeWindow" not in js and "_onFinalizeWindowInput" not in js
    assert "_setFinalizeLock" not in js and "_finalizeKeyframe" not in js
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_finalize_keyframe_editable_and_uses_shared_controller -q`
Expected: FAIL.

- [ ] **Step 3: Markup — keyframe span → input + length default 800**

In `card_inline_analysis_3d.html`, replace the finalize keyframe `<span>`:
```html
              <span id="ia3d-finalize-keyframe" style="font-family:var(--mono);font-size:.78rem;color:var(--text);min-width:3rem">0</span>
```
with an input:
```html
              <input type="number" id="ia3d-finalize-keyframe" min="0" value="0"
                style="width:5rem;font-family:var(--mono);font-size:.78rem;background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.18rem .3rem" />
```
And set the finalize defaults to length 800: change `#ia3d-finalize-after` `value="200"` → `value="599"` and `#ia3d-finalize-length` `value="401"` → `value="800"`. (`#ia3d-finalize-before` stays `value="200"`.)

- [ ] **Step 4: JS — import the controller + module handle**

In `src/static/inline_analysis_3d.js`:
- Add import: `import { makeKeyframeWindow } from "./keyframe_window_ui.js";`
- Replace the two finalize state lines:
  ```javascript
  let _finalizeKeyframe = 0;     // ...
  let _finalizeLocked = false;   // ...
  ```
  with:
  ```javascript
  let _finalizeKW = null;        // shared keyframe-window controller for the finalize panel
  ```

- [ ] **Step 5: JS — instantiate the controller in `_wireViewerChrome`**

In `_wireViewerChrome(v)` (which has `v` and runs once), after the existing frameChange handlers, add:
```javascript
  _finalizeKW = makeKeyframeWindow({
    viewer: v,
    panelEl: $("ia3d-finalize-controls"),
    settingKey: "finalize_window",
    els: {
      keyframe: $("ia3d-finalize-keyframe"), lock: $("ia3d-finalize-lock"),
      before: $("ia3d-finalize-before"), after: $("ia3d-finalize-after"),
      length: $("ia3d-finalize-length"), range: $("ia3d-finalize-range"),
    },
  });
```
Then DELETE the now-redundant 2nd finalize frameChange block:
```javascript
  v.on("frameChange", (n) => {
    if (!_finalizeLocked) { _finalizeKeyframe = n; _refreshFinalizeWindow(); }
  });
```

- [ ] **Step 6: JS — delete the bespoke helpers + wiring; redirect populate + add**

- Delete the functions `_finalizeWindowVals`, `_refreshFinalizeWindow`, `_onFinalizeWindowInput`, `_setFinalizeLock` entirely.
- Replace `_ia3dPopulateFinalizeFields`'s body so the whole function becomes:
  ```javascript
  function _ia3dPopulateFinalizeFields() {
    _finalizeKW?.load();   // keyframe=current frame, before/after from the per-project setting
  }
  ```
- In the finalize wiring, DELETE the bespoke input/lock/'l' block (the lines wiring `ia3d-finalize-before/-after/-length` inputs, the keydown-stopPropagation forEach, the `ia3d-finalize-lock` change listener, and the document `keydown` 'l' handler that calls `_setFinalizeLock`). The controller now owns all of that.
- In `_onFinalizeAddClick`, replace:
  ```javascript
  const { before, after } = _finalizeWindowVals();
  const rng = finalizeRange(_finalizeKeyframe, before, after, _viewer ? _viewer.frameCount() : 0);
  const startFrame = rng.start, nFrames = rng.n;
  ```
  with:
  ```javascript
  const rng = _finalizeKW ? _finalizeKW.getRange() : { start: 0, n: 0 };
  const startFrame = rng.start, nFrames = rng.n;
  ```
- In `_resetForOpen`, the line `_finalizeLocked = false;` → remove it (the controller resets via `load()` on toggle-on; nothing else references it). If `finalizeRange`/`syncWindow` imports are now unused in `inline_analysis_3d.js`, remove those imports too (the controller owns them). Verify with grep.

- [ ] **Step 7: Run to verify PASS**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q`
Expected: PASS (all). Then `grep -n "_finalizeKeyframe\|_finalizeLocked\|_refreshFinalizeWindow\|_onFinalizeWindowInput\|_setFinalizeLock" src/static/inline_analysis_3d.js` → no output.

- [ ] **Step 8: Commit**

```bash
git add src/templates/partials/card_inline_analysis_3d.html src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): finalize uses shared keyframe-window controller; editable keyframe

Keyframe is now a typeable input (auto-locks on edit); before/after persist per
project (default 800). Replaces the bespoke finalize-window glue with one
makeKeyframeWindow instance.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Create-clip panel — keyframe window + hidden bridge (dlc-3D)

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html` (clip panel)
- Modify: `src/static/inline_analysis_3d.js` (clip controller + load on enable)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_clip_uses_keyframe_window_with_hidden_bridge():
    html = CARD.read_text()
    js = JS.read_text()
    for need in ["ia3d-clip-keyframe", "ia3d-clip-lock", "ia3d-clip-before",
                 "ia3d-clip-after", "ia3d-clip-length", "ia3d-clip-range"]:
        assert need in html, f"missing clip keyframe element {need!r}"
    # start/frames kept as HIDDEN bridge inputs (clipExtractor still reads them)
    assert re.search(r'id="ia3d-clip-start"[^>]*type="hidden"', html) or \
           re.search(r'type="hidden"[^>]*id="ia3d-clip-start"', html), "clip-start must be a hidden bridge input"
    assert re.search(r'id="ia3d-clip-frames"[^>]*type="hidden"', html) or \
           re.search(r'type="hidden"[^>]*id="ia3d-clip-frames"', html), "clip-frames must be a hidden bridge input"
    # second controller instance for the clip panel
    assert '"clip_window"' in js or "'clip_window'" in js
    assert "_clipKW" in js
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_clip_uses_keyframe_window_with_hidden_bridge -q`
Expected: FAIL.

- [ ] **Step 3: Markup — clip panel keyframe window + hidden bridge**

In `card_inline_analysis_3d.html`, the clip panel currently has (inside `#ia3d-clip-panel`):
```html
              <label>start <input type="number" id="ia3d-clip-start" min="0" value="0" style="..."></label>
              <label>length <input type="number" id="ia3d-clip-frames" min="1" value="800" style="..."></label>
              <label>end <input type="number" id="ia3d-clip-end" readonly style="..."></label>
              <label style="display:flex;align-items:center;gap:.3rem"><input type="checkbox" id="ia3d-clip-sibling" checked ...>both cams</label>
```
Replace the start/length/end labels (NOT the `both cams` checkbox) with the keyframe-window markup + hidden bridge inputs:
```html
              <span style="font-size:.74rem;color:var(--text-dim)">keyframe</span>
              <input type="number" id="ia3d-clip-keyframe" min="0" value="0"
                style="width:5rem;font-family:var(--mono);font-size:.78rem;background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.18rem .3rem" />
              <label style="display:flex;align-items:center;gap:.3rem;font-size:.74rem;color:var(--text-dim)"><input type="checkbox" id="ia3d-clip-lock" style="accent-color:var(--accent);width:13px;height:13px"/> Lock (l)</label>
              <label style="font-size:.74rem;color:var(--text-dim)">before <input type="number" id="ia3d-clip-before" min="0" value="200" style="width:4.2rem;font-family:var(--mono);background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.2rem .3rem"></label>
              <label style="font-size:.74rem;color:var(--text-dim)">after <input type="number" id="ia3d-clip-after" min="0" value="599" style="width:4.2rem;font-family:var(--mono);background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.2rem .3rem"></label>
              <label style="font-size:.74rem;color:var(--text-dim)">length <input type="number" id="ia3d-clip-length" min="1" value="800" style="width:4.7rem;font-family:var(--mono);background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.2rem .3rem"></label>
              <span id="ia3d-clip-range" style="font-size:.72rem;color:var(--text-dim);font-family:var(--mono)">frames 0–0 (0)</span>
              <input type="hidden" id="ia3d-clip-start" value="0" />
              <input type="hidden" id="ia3d-clip-frames" value="800" />
              <input type="hidden" id="ia3d-clip-end" value="0" />
```
(The `both cams`, postfix, Extract/Rename/Delete, and status elements stay unchanged. `clipExtractor`'s `els.endDisplay: $("ia3d-clip-end")` now points at a hidden input — harmless.)

- [ ] **Step 4: JS — clip controller + load on enable**

In `src/static/inline_analysis_3d.js`:
- Add module state near `_finalizeKW`: `let _clipKW = null;`
- In `_wireViewerChrome(v)`, after the `_finalizeKW = makeKeyframeWindow({…})` instantiation, add the clip instance (writes computed start/frames into the hidden bridge inputs that `clipExtractor` reads):
  ```javascript
  _clipKW = makeKeyframeWindow({
    viewer: v,
    panelEl: $("ia3d-clip-panel"),
    settingKey: "clip_window",
    els: {
      keyframe: $("ia3d-clip-keyframe"), lock: $("ia3d-clip-lock"),
      before: $("ia3d-clip-before"), after: $("ia3d-clip-after"),
      length: $("ia3d-clip-length"), range: $("ia3d-clip-range"),
    },
    onChange: (r) => {
      const s = $("ia3d-clip-start"), f = $("ia3d-clip-frames"), e = $("ia3d-clip-end");
      if (s) s.value = r.start;
      if (f) f.value = r.n;
      if (e) e.value = r.end;
    },
  });
  ```
- Wire load on clip-enable: find `$("ia3d-clip-enable")` usage; the `clipExtractor` feature owns the enable→panel-show. ADD a listener so the controller loads its setting when enabled:
  ```javascript
  $("ia3d-clip-enable")?.addEventListener("change", (e) => { if (e.target.checked) _clipKW?.load(); });
  ```
  Place this right after the `_viewer.use(clipExtractor({…}))` block (so the element exists; both listeners coexist — clipExtractor's own enable listener shows the panel, ours loads the setting).
- Reset: in `_resetForOpen`, nothing extra needed (controllers reload via `load()`); ensure no dangling refs.

- [ ] **Step 5: Run to verify PASS + full affected suites**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py tests/test_keyframe_window_ui.py tests/test_video_viewer_base.py tests/test_status_notes_feature.py -q && node --test tests/unit/*.mjs`
Expected: pytest all PASS; node `# fail 0`.

- [ ] **Step 6: Commit**

```bash
git add src/templates/partials/card_inline_analysis_3d.html src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): create-clip uses the keyframe-window model (hidden start/frames bridge)

Replaces the clip panel's start/length/end inputs with the same keyframe window
(editable keyframe, before/after/length, lock + 'l', clip_window persistence). The
controller writes computed start/frames into hidden inputs clipExtractor already
reads, so Extract/Rename/Delete are unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Live verification (controller, after all tasks)
Restart BOTH services (backend route in flask; templates in dlc-3d): `docker compose restart flask dlc-3d`. With the inline card open on a video + overlay:
1. **Finalize:** keyframe input shows current frame; typing a keyframe auto-checks Lock and freezes it; before/after edits update length + range; `l` toggles lock.
2. **Persistence:** change finalize before/after, close + reopen the card (or reload) → values restored (round-tripped through `ui_settings.sqlite`). Confirm the GET returns the saved JSON.
3. **Create-clip:** enable the clip panel → keyframe window shows; editing it updates the hidden `#ia3d-clip-start`/`#ia3d-clip-frames` (read them); defaults give length 800; clip_window persists independently of finalize_window.
4. Do NOT click Add/Extract (writes). Verify computed start/n via the range readout + hidden inputs only.

## Out of scope (YAGNI)
- View Analyzed / clip-cutter legacy.
- Persisting the keyframe value (per-session only).
- General settings UI.

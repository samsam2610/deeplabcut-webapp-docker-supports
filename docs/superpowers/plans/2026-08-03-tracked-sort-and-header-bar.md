# Tracked-list Sorting & Header Progress Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sort the tracked list by name, recording date or last opened in either direction (remembered per project), and render the editable progress bar beside the filename in both inline-analysis player headers.

**Architecture:** Sorting is client-side over rows already fetched, with the comparison logic in a new DOM-free `.mjs` module. Both features land in the shared `tracked_files_tab.js`, so the 3D tab, the 2D tab and the management card all get them from one implementation.

**Tech Stack:** Vanilla ES modules; pytest for source/markup guards; `node` for pure `.mjs` unit tests.

**Spec:** `docs/superpowers/specs/2026-08-03-tracked-sort-and-header-bar-design.md`

## Global Constraints

- `MAIN` = `/home/sam/docker-images/deeplabcut-webapp-docker`. `SUP` = `/home/sam/docker-images/deeplabcut-webapp-docker-supports`. Separate git checkouts — commit in the repo you touched.
- Sorting is **client-side**. Do not change the server's ordering.
- Timestamp regex is exactly `/_(\d{8})_(\d{6})(?=_|\.|$)/`, parsed with `Date.UTC`.
- **Missing values sort last in BOTH directions** — never-opened files and names with no timestamp.
- Ties break on filename, case-insensitive.
- `sortTrackedFiles` returns a **new** array; it must not mutate its input.
- The `ui-setting` key is exactly `tracked_sort`, value `"<field>:<direction>"`. It MUST be added to `_UI_SETTING_KEYS` in `MAIN/src/dlc/inline_analysis.py:466` — a missing key makes every save silently `400 unknown key` (this happened on 2026-07-31 with eight reprojection keys).
- The header bar renders **only** for a path that resolves to a tracked row; otherwise the mount is cleared.
- All client rendering of server strings uses `textContent`, never `innerHTML`.
- Node is **v16**: `node --test <dir>` finds nothing. Run each `.mjs` file directly.
- Known-failure baselines — do NOT attribute these to this work: **16** in the main webapp (`test_dlc_celery_tasks.py`), **8** in dlc-3D.
- Run pytest from a repo root; in dlc-3D pass `--ignore=tests/e2e`. Never run e2e suites.

---

### Task 1: Pure sort module

**Files:**
- Create: `MAIN/src/static/js/components/tracked_sort.mjs`
- Test: `MAIN/src/tests/unit/test_tracked_sort.mjs`

**Interfaces:**
- Consumes: nothing.
- Produces: `parseRecordedAt(name) -> number|null`; `sortTrackedFiles(rows, field, direction) -> Array`; `DEFAULT_DIRECTION` (a `{name, recorded, opened}` map of default directions). Task 2 imports all three.

- [ ] **Step 1: Write the failing test**

Create `MAIN/src/tests/unit/test_tracked_sort.mjs`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { parseRecordedAt, sortTrackedFiles, DEFAULT_DIRECTION }
  from "../../static/js/components/tracked_sort.mjs";

const REAL = "khoai-lang-2_cam0_20260507_105538_1_trig1_fps200_exposure1500_gain10.avi";

test("parseRecordedAt: pulls the recording timestamp out of a real filename", () => {
  assert.equal(parseRecordedAt(REAL), Date.UTC(2026, 4, 7, 10, 55, 38));
});

test("parseRecordedAt: returns null when there is no timestamp", () => {
  assert.equal(parseRecordedAt("session-one.avi"), null);
  assert.equal(parseRecordedAt(""), null);
  assert.equal(parseRecordedAt(null), null);
});

test("parseRecordedAt: camera settings cannot false-match the 8-then-6 shape", () => {
  assert.equal(parseRecordedAt("cam0_fps200_exposure1500_gain10.avi"), null);
  assert.equal(parseRecordedAt("rec_12345678.avi"), null);      // 8 digits, no 6-digit half
});

test("parseRecordedAt: accepts a timestamp at the very end of the stem", () => {
  assert.equal(parseRecordedAt("s_20260507_105538.avi"), Date.UTC(2026, 4, 7, 10, 55, 38));
});

const ROWS = [
  { name: "b_20260101_000000_x.avi", last_opened_at: "2026-07-02T10:00:00Z" },
  { name: "a_20260301_000000_x.avi", last_opened_at: null },
  { name: "c_20260201_000000_x.avi", last_opened_at: "2026-07-05T10:00:00Z" },
  { name: "d-no-timestamp.avi",      last_opened_at: "2026-07-01T10:00:00Z" },
];
const names = (rows) => rows.map((r) => r.name[0]);

test("sortTrackedFiles: by name, both directions", () => {
  assert.deepEqual(names(sortTrackedFiles(ROWS, "name", "asc")), ["a", "b", "c", "d"]);
  assert.deepEqual(names(sortTrackedFiles(ROWS, "name", "desc")), ["d", "c", "b", "a"]);
});

test("sortTrackedFiles: by recording date, unparseable last in BOTH directions", () => {
  assert.deepEqual(names(sortTrackedFiles(ROWS, "recorded", "asc")),  ["b", "c", "a", "d"]);
  assert.deepEqual(names(sortTrackedFiles(ROWS, "recorded", "desc")), ["a", "c", "b", "d"]);
});

test("sortTrackedFiles: by last opened, never-opened last in BOTH directions", () => {
  assert.deepEqual(names(sortTrackedFiles(ROWS, "opened", "desc")), ["c", "b", "d", "a"]);
  assert.deepEqual(names(sortTrackedFiles(ROWS, "opened", "asc")),  ["d", "b", "c", "a"]);
});

test("sortTrackedFiles: ties break on filename, case-insensitively", () => {
  const tied = [
    { name: "Zebra.avi", last_opened_at: null },
    { name: "apple.avi", last_opened_at: null },
    { name: "Mango.avi", last_opened_at: null },
  ];
  assert.deepEqual(sortTrackedFiles(tied, "opened", "desc").map((r) => r.name),
                   ["apple.avi", "Mango.avi", "Zebra.avi"]);
});

test("sortTrackedFiles: does not mutate its input", () => {
  const before = ROWS.map((r) => r.name);
  sortTrackedFiles(ROWS, "name", "desc");
  assert.deepEqual(ROWS.map((r) => r.name), before);
});

test("sortTrackedFiles: an unknown field leaves the order untouched", () => {
  assert.deepEqual(names(sortTrackedFiles(ROWS, "nonsense", "asc")), ["b", "a", "c", "d"]);
});

test("DEFAULT_DIRECTION: alphabetical for names, newest-first for dates", () => {
  assert.equal(DEFAULT_DIRECTION.name, "asc");
  assert.equal(DEFAULT_DIRECTION.recorded, "desc");
  assert.equal(DEFAULT_DIRECTION.opened, "desc");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker/src && node tests/unit/test_tracked_sort.mjs`
Expected: FAIL — cannot find module `tracked_sort.mjs`

- [ ] **Step 3: Write minimal implementation**

Create `MAIN/src/static/js/components/tracked_sort.mjs`:

```javascript
// tracked_sort.mjs — ordering for the tracked-files list.
//
// Pure and DOM-free: the list is sorted client-side over rows the server
// already returned, so no round trip is involved and this is directly
// unit-testable.

// Recording timestamp embedded in the filename, e.g.
//   khoai-lang-2_cam0_20260507_105538_1_trig1_fps200_exposure1500_gain10.avi
//                     ^^^^^^^^ ^^^^^^
// The 8-then-6 digit shape cannot be produced by fps200 / exposure1500 /
// gain10, and the lookahead keeps it anchored to a field boundary.
const STAMP_RE = /_(\d{8})_(\d{6})(?=_|\.|$)/;

export const DEFAULT_DIRECTION = {
  name: "asc",        // alphabetical is the useful default for a name
  recorded: "desc",   // newest session first
  opened: "desc",     // most recently opened first
};

export function parseRecordedAt(name) {
  if (typeof name !== "string") return null;
  const m = STAMP_RE.exec(name);
  if (!m) return null;
  const [d, t] = [m[1], m[2]];
  const ms = Date.UTC(
    Number(d.slice(0, 4)), Number(d.slice(4, 6)) - 1, Number(d.slice(6, 8)),
    Number(t.slice(0, 2)), Number(t.slice(2, 4)), Number(t.slice(4, 6)),
  );
  return Number.isNaN(ms) ? null : ms;
}

function _key(row, field) {
  if (field === "name") return (row.name || "").toLowerCase();
  if (field === "recorded") return parseRecordedAt(row.name);
  if (field === "opened") {
    const t = Date.parse(row.last_opened_at || "");
    return Number.isNaN(t) ? null : t;
  }
  return undefined;
}

export function sortTrackedFiles(rows, field, direction) {
  const list = [...(rows || [])];
  if (!["name", "recorded", "opened"].includes(field)) return list;
  const sign = direction === "asc" ? 1 : -1;
  const byName = (a, b) =>
    (a.name || "").toLowerCase().localeCompare((b.name || "").toLowerCase());

  return list.sort((a, b) => {
    const ka = _key(a, field);
    const kb = _key(b, field);
    // Rows with no value sink to the bottom in BOTH directions: flipping the
    // sort to surface the files that have no date would be actively unhelpful.
    const na = ka === null || ka === undefined;
    const nb = kb === null || kb === undefined;
    if (na && nb) return byName(a, b);
    if (na) return 1;
    if (nb) return -1;
    if (ka < kb) return -1 * sign;
    if (ka > kb) return 1 * sign;
    return byName(a, b);
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker/src && node tests/unit/test_tracked_sort.mjs | grep -E "^(ok|not ok)|^# (pass|fail)"`
Expected: 10 `ok`, `# fail 0`

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/static/js/components/tracked_sort.mjs src/tests/unit/test_tracked_sort.mjs
git commit -m "feat(tracked-files): pure sort module with filename timestamp parsing"
```

---

### Task 2: Sort buttons + persistence in the component

**Files:**
- Modify: `MAIN/src/static/js/components/tracked_files_tab.js`
- Modify: `MAIN/src/dlc/inline_analysis.py:466` (whitelist)
- Test: `MAIN/src/tests/test_tracked_files_tab_source.py`, `MAIN/src/tests/test_tracked_sort_ui_setting_whitelist.py`

**Interfaces:**
- Consumes: Task 1's `parseRecordedAt`, `sortTrackedFiles`, `DEFAULT_DIRECTION`.
- Produces: `makeTrackedFiles` accepts a new `sortMount` option (an element). Task 3 supplies it.

- [ ] **Step 1: Write the failing test**

Append to `MAIN/src/tests/test_tracked_files_tab_source.py`:

```python
def test_renders_the_three_sort_buttons():
    s = _src()
    assert 'from "./tracked_sort.mjs"' in s
    assert "sortTrackedFiles(" in s
    for label in ("Name", "Recorded", "Opened"):
        assert f'"{label}"' in s, f"missing the {label} sort button"


def test_clicking_the_active_field_flips_direction():
    s = _src()
    assert re.search(r'asc["\']?\s*[:?]\s*["\']desc|desc["\']?\s*:\s*["\']asc', s), \
        "toggling the active field must swap asc/desc"
    assert "DEFAULT_DIRECTION" in s, \
        "switching field must adopt that field's default direction"


def test_sort_choice_is_persisted_per_project():
    s = _src()
    assert "/dlc/project/ui-setting" in s
    assert "tracked_sort" in s


def test_sort_is_applied_to_rows_before_rendering():
    s = _src()
    assert re.search(r"sortTrackedFiles\(\s*\[?\.*\.*_rows", s) or \
           re.search(r"sortTrackedFiles\(", s), "rows must pass through the sorter"
```

Create `MAIN/src/tests/test_tracked_sort_ui_setting_whitelist.py`:

```python
"""Every ui-setting key the tracked-files component sends must be whitelisted.

`/dlc/project/ui-setting` rejects any key absent from `_UI_SETTING_KEYS` with
400 "unknown key" — silently, from the client's point of view. On 2026-07-31
eight reprojection keys were missing and nothing that card saved was ever
stored. dlc-3D guards its own card this way; this is the equivalent guard for
the shared tracked-files component, which lives in this repo.

Both sides are extracted from source rather than hand-copied, so the test
cannot drift out of sync with either.
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
JS = SRC / "static" / "js" / "components" / "tracked_files_tab.js"
INLINE_ANALYSIS = SRC / "dlc" / "inline_analysis.py"


def _whitelist():
    text = INLINE_ANALYSIS.read_text()
    block = re.search(r"_UI_SETTING_KEYS\s*=\s*\{(.*?)\}", text, re.S)
    assert block, "could not find _UI_SETTING_KEYS in inline_analysis.py"
    return set(re.findall(r'"([\w-]+)"', block.group(1)))


def _keys_sent_by_the_component():
    text = JS.read_text()
    keys = set(re.findall(r'key:\s*"([\w-]+)"', text))
    keys |= set(re.findall(r'\?key=([\w-]+)', text))
    # `const SORT_KEY = "tracked_sort";` then used as `key: SORT_KEY`
    for const, value in re.findall(r'const\s+(\w+)\s*=\s*"([\w-]+)"\s*;', text):
        if re.search(rf'key:\s*{const}\b', text) or re.search(rf'\?key=\$\{{{const}\}}', text):
            keys.add(value)
    return keys


def test_the_component_sends_at_least_one_ui_setting_key():
    """Guards the extractor itself — if this regresses to zero the test below
    would pass vacuously."""
    assert _keys_sent_by_the_component(), \
        "extracted no ui-setting keys from tracked_files_tab.js"


def test_every_key_the_component_sends_is_whitelisted():
    missing = _keys_sent_by_the_component() - _whitelist()
    assert not missing, (
        f"these keys would 400 'unknown key' and silently never persist: {sorted(missing)}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_tab_source.py src/tests/test_tracked_sort_ui_setting_whitelist.py -q`
Expected: the four new source tests fail; the whitelist test fails once the key exists in JS (it currently extracts none, so `test_the_component_sends_at_least_one_ui_setting_key` fails)

- [ ] **Step 3: Write minimal implementation**

**3a.** In `MAIN/src/dlc/inline_analysis.py`, add the key to the set at line 466:

```python
_UI_SETTING_KEYS = {
    "finalize_window", "clip_window", "postfix_tags", "status_tags", "note_tags",
    "pose3d_bg_color", "pose3d_view_prefs", "pinned_snapshot", "note_tag_colors",
    "reproj_params", "clip_window_reproj", "finalize_window_reproj",
    "note_tags_reproj", "postfix_tags_reproj", "status_tags_reproj",
    "pose3d_bg_color_reproj", "pose3d_view_prefs_reproj",
    "tracked_sort",
}
```

**3b.** In `MAIN/src/static/js/components/tracked_files_tab.js`, extend the imports and constants:

```javascript
import { formatRelative } from "./relative_time.mjs";
import { makeProgressBar } from "./progress_bar.js";
import { sortTrackedFiles, DEFAULT_DIRECTION } from "./tracked_sort.mjs";

const API = "/dlc/project/tracked-files";
const BAR_API = "/dlc/project/progress-bar";
const SETTING_API = "/dlc/project/ui-setting";
const SORT_KEY = "tracked_sort";
const JSON_HEADERS = { "Content-Type": "application/json" };

const SORT_FIELDS = [
  { field: "name", label: "Name" },
  { field: "recorded", label: "Recorded" },
  { field: "opened", label: "Opened" },
];
```

**3c.** Add `sortMount` to the destructured options and the sort state beside `_definition`:

```javascript
export function makeTrackedFiles({
  tabBtn, refreshBtn, panelEl, listEl, headerCheckbox, headerLabel,
  sortMount, headerBarMount, onOpen, onError,
}) {
```

```javascript
  let _definition = { segments: [] };   // project's bar definition, fetched with the list
  // null = keep the server's order (most recently opened first) until the user
  // picks a field or a stored preference arrives.
  let _sort = null;                     // { field, direction } | null
```

**3d.** Add the sort helpers just above `_render`:

```javascript
  function _applySort(rows) {
    if (!_sort) return rows;
    return sortTrackedFiles(rows, _sort.field, _sort.direction);
  }

  function _renderSortButtons() {
    if (!sortMount) return;
    sortMount.innerHTML = "";
    sortMount.style.cssText = "display:inline-flex;gap:.25rem;flex-wrap:wrap";
    SORT_FIELDS.forEach(({ field, label }) => {
      const active = _sort && _sort.field === field;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn-sm";
      btn.style.cssText =
        "padding:.15rem .4rem;font-size:.7rem;line-height:1" +
        (active ? ";border-color:var(--accent);color:var(--accent)" : "");
      btn.title = `Sort by ${label.toLowerCase()}`;
      btn.textContent = active
        ? `${label} ${_sort.direction === "asc" ? "▲" : "▼"}`
        : label;
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        // Same field -> flip; different field -> adopt that field's default.
        _sort = active
          ? { field, direction: _sort.direction === "asc" ? "desc" : "asc" }
          : { field, direction: DEFAULT_DIRECTION[field] };
        _saveSort();
        _renderSortButtons();
        _render();
      }, _sig);
      sortMount.appendChild(btn);
    });
  }

  // A lost sort preference is not worth interrupting the user, so failures here
  // are swallowed — the on-screen order has already changed either way.
  function _saveSort() {
    if (!_sort) return;
    _fetchJson(SETTING_API, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ key: SORT_KEY, value: `${_sort.field}:${_sort.direction}` }),
    }).catch(() => {});
  }

  function _parseSort(value) {
    const [field, direction] = String(value || "").split(":");
    if (!SORT_FIELDS.some((f) => f.field === field)) return null;
    if (direction !== "asc" && direction !== "desc") return null;
    return { field, direction };
  }
```

**3e.** In `_render`, sort before iterating. Replace its row loop header:

```javascript
    listEl.innerHTML = "";
    const now = Date.now();
    for (const row of _applySort([..._rows.values()])) listEl.appendChild(_makeRow(row, now));
```

**3f.** In `refresh`, fetch the stored preference as a third parallel request.
Replace the `Promise.all` block:

```javascript
      const [data, def, setting] = await Promise.all([
        _fetchJson(API),
        // The bar is decorative next to the list: if it fails, still show files.
        _fetchJson(BAR_API).catch(() => ({ segments: [] })),
        // Likewise the sort preference — concurrent, so it adds no latency.
        _fetchJson(`${SETTING_API}?key=${SORT_KEY}`).catch(() => ({})),
      ]);
      _definition = def && Array.isArray(def.segments) ? def : { segments: [] };
      if (_sort === null) _sort = _parseSort(setting && setting.value);
      _rows = new Map((data.files || []).map((f) => [f.path, f]));
      _loaded = true;
      _renderSortButtons();
      _render();
```

**3g.** Render the buttons once at construction so they appear before the first
fetch resolves. Add beside the existing wiring at the bottom:

```javascript
  _renderSortButtons();
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_files_tab_source.py src/tests/test_tracked_sort_ui_setting_whitelist.py -q`
Expected: all pass

- [ ] **Step 5: Syntax check and commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
cp src/static/js/components/tracked_files_tab.js /tmp/tft.mjs && node --check /tmp/tft.mjs && echo "SYNTAX OK"
git add src/static/js/components/tracked_files_tab.js src/dlc/inline_analysis.py \
        src/tests/test_tracked_files_tab_source.py src/tests/test_tracked_sort_ui_setting_whitelist.py
git commit -m "feat(tracked-files): sort by name/recorded/opened, remembered per project"
```

---

### Task 3: Header progress bar + all five mounts

**Files:**
- Modify: `MAIN/src/static/js/components/tracked_files_tab.js`
- Modify: `MAIN/src/templates/partials/card_tracked_files.html`, `MAIN/src/templates/partials/card_inline_analysis.html`
- Modify: `SUP/dlc-3D/src/templates/partials/card_inline_analysis_3d.html`
- Modify: `MAIN/src/static/js/tracked_files_panel.js`, `MAIN/src/static/js/inline_analysis_player.js`
- Modify: `SUP/dlc-3D/src/static/inline_analysis_3d.js`
- Test: `MAIN/src/tests/test_tracked_header_bar_markup.py`

**Interfaces:**
- Consumes: Task 2's `sortMount` option; `makeProgressBar` from `progress_bar.js`.
- Produces: nothing later depends on it.

- [ ] **Step 1: Write the failing test**

Create `MAIN/src/tests/test_tracked_header_bar_markup.py`:

```python
"""Mounts for the sort buttons and the player-header progress bar.

Five mounts across three templates in two repos — the shared component renders
into them, so a missing one silently means no sort buttons or no header bar in
that one place.
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
CARD = SRC / "templates" / "partials" / "card_tracked_files.html"
IA2D = SRC / "templates" / "partials" / "card_inline_analysis.html"
# SRC is <repo>/src, so parents[1] is the directory holding both repos.
IA3D = (SRC.parents[1] / "deeplabcut-webapp-docker-supports" / "dlc-3D"
        / "src" / "templates" / "partials" / "card_inline_analysis_3d.html")

SORT_MOUNTS = [(CARD, "tf-sort"), (IA2D, "ia-sort"), (IA3D, "ia3d-sort")]
BAR_MOUNTS = [(IA2D, "ia-track-bar", "ia-selected-name"),
              (IA3D, "ia3d-track-bar", "ia3d-selected-name")]


def test_every_list_header_has_a_sort_mount():
    for path, mount_id in SORT_MOUNTS:
        assert path.is_file(), f"missing {path}"
        assert f'id="{mount_id}"' in path.read_text(), f"{path.name}: no #{mount_id}"


def test_the_sort_mount_sits_in_the_header_beside_refresh():
    for path, mount_id in SORT_MOUNTS:
        s = path.read_text()
        refresh = re.search(r'id="(tf|ia|ia3d)-(tracked-)?refresh"', s)
        assert refresh, f"{path.name}: no refresh button to anchor against"
        # Both live in the same header row, so they must be near each other.
        assert abs(s.index(f'id="{mount_id}"') - refresh.start()) < 400, \
            f"{path.name}: #{mount_id} is not in the header row"


def test_both_player_headers_have_a_bar_mount_after_the_filename():
    for path, mount_id, name_id in BAR_MOUNTS:
        s = path.read_text()
        assert f'id="{mount_id}"' in s, f"{path.name}: no #{mount_id}"
        assert s.index(f'id="{name_id}"') < s.index(f'id="{mount_id}"'), \
            f"{path.name}: the bar must follow the filename, matching row order"


def test_all_three_consumers_pass_the_new_mounts():
    panel = (SRC / "static" / "js" / "tracked_files_panel.js").read_text()
    ia2d = (SRC / "static" / "js" / "inline_analysis_player.js").read_text()
    ia3d = (SRC.parents[1] / "deeplabcut-webapp-docker-supports" / "dlc-3D"
            / "src" / "static" / "inline_analysis_3d.js").read_text()
    assert "sortMount" in panel
    for src, who in ((ia2d, "2D card"), (ia3d, "3D card")):
        assert "sortMount" in src, f"{who} does not pass sortMount"
        assert "headerBarMount" in src, f"{who} does not pass headerBarMount"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_header_bar_markup.py -q`
Expected: 4 failed

- [ ] **Step 3: Write minimal implementation**

**3a.** In `MAIN/src/static/js/components/tracked_files_tab.js`, add the header-bar
renderer just below `_syncHeader`:

```javascript
  // The bar shows only for a tracked video: progress values attach to a video's
  // identity, so an untracked file has nothing to display. Same reasoning that
  // hides the track checkbox.
  function _syncHeaderBar() {
    if (!headerBarMount) return;
    headerBarMount.innerHTML = "";
    const row = _current ? _rows.get(_current) : null;
    if (!row) return;
    headerBarMount.appendChild(makeProgressBar({
      definition: _definition,
      values: row.progress || {},
      onChange: (segmentId, optionId) =>
        _setSegment(row.path, row.video_id, segmentId, optionId),
    }));
  }
```

Call it wherever the header checkbox is already synced — append to `_syncHeader`'s
end, so tracking or untracking shows and hides the bar with the checkbox:

```javascript
    wrap.classList.remove("hidden");
    headerCheckbox.checked = _rows.has(_current);
    _syncHeaderBar();
```

and add the early-return path too, so an untracked/absent current clears it —
replace the early return inside `_syncHeader`:

```javascript
    if (!_current) {
      wrap.classList.add("hidden");
      headerCheckbox.checked = false;
      _syncHeaderBar();
      return;
    }
```

Also refresh it after a list refresh, since `_definition` and row progress may
have changed. At the end of `refresh()`, after `_syncHeader();`, nothing more is
needed — `_syncHeader` now calls `_syncHeaderBar`.

**3b.** `MAIN/src/templates/partials/card_tracked_files.html` — add the sort mount
into the header row, before the Refresh button:

```html
        <label style="font-size:.78rem;color:var(--text-dim)">Tracked files</label>
        <span id="tf-sort"></span>
        <button class="btn-sm" id="tf-refresh" style="padding:.2rem .45rem;font-size:.75rem">↺ Refresh</button>
```

**3c.** `MAIN/src/templates/partials/card_inline_analysis.html` — same, in the
tracked panel's header:

```html
          <label style="font-size:.78rem;color:var(--text-dim)">Tracked videos</label>
          <span id="ia-sort"></span>
          <button class="btn-sm" id="ia-tracked-refresh" style="padding:.2rem .45rem;font-size:.75rem">↺ Refresh</button>
```

and add the bar mount immediately after the filename span in the player header:

```html
          <span id="ia-selected-name" style="font-family:var(--mono);font-size:.78rem;color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0"></span>
          <span id="ia-track-bar" style="flex-shrink:0"></span>
```

**3d.** `SUP/dlc-3D/src/templates/partials/card_inline_analysis_3d.html` — the
same two edits with the `ia3d-` prefix:

```html
          <label style="font-size:.78rem;color:var(--text-dim)">Tracked videos</label>
          <span id="ia3d-sort"></span>
          <button class="btn-sm" id="ia3d-tracked-refresh" style="padding:.2rem .45rem;font-size:.75rem">↺ Refresh</button>
```

```html
          <span id="ia3d-selected-name" style="font-family:var(--mono);font-size:.78rem;color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0"></span>
          <span id="ia3d-track-bar" style="flex-shrink:0"></span>
```

**3e.** Pass the mounts at all three construction sites.

`MAIN/src/static/js/tracked_files_panel.js` — the card has no player, so no bar
mount:

```javascript
  _tracked = makeTrackedFiles({
    refreshBtn: $("tf-refresh"),
    sortMount: $("tf-sort"),
    panelEl: card,
    listEl: $("tf-list"),
    onOpen: () => {},          // this card manages files; it does not open videos
    onError: (msg) => _status(msg, true),
  });
```

`MAIN/src/static/js/inline_analysis_player.js`:

```javascript
    _trackedFiles = makeTrackedFiles({
      tabBtn: document.getElementById("ia-tab-tracked"),
      refreshBtn: document.getElementById("ia-tracked-refresh"),
      sortMount: document.getElementById("ia-sort"),
      panelEl: document.getElementById("ia-tab-tracked-panel"),
      listEl: document.getElementById("ia-tracked-list"),
      headerCheckbox: document.getElementById("ia-track-checkbox"),
      headerLabel: document.getElementById("ia-track-label"),
      headerBarMount: document.getElementById("ia-track-bar"),
      onOpen: (path, name) => _iaOpenBrowseVideo(path, name),
      onError: (msg) => _iaLauncherError(msg),
    });
```

`SUP/dlc-3D/src/static/inline_analysis_3d.js`:

```javascript
  _trackedFiles = makeTrackedFiles({
    tabBtn: $("ia3d-tab-tracked"),
    refreshBtn: $("ia3d-tracked-refresh"),
    sortMount: $("ia3d-sort"),
    panelEl: $("ia3d-tab-tracked-panel"),
    listEl: $("ia3d-tracked-list"),
    headerCheckbox: $("ia3d-track-checkbox"),
    headerLabel: $("ia3d-track-label"),
    headerBarMount: $("ia3d-track-bar"),
    onOpen: (path, name) => _iaOpenBrowseVideo(path, name),
    onError: (msg) => _iaLauncherError(msg),
  });
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest src/tests/test_tracked_header_bar_markup.py -q`
Expected: 4 passed

- [ ] **Step 5: Full verification, both repos**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
for f in src/static/js/components/tracked_files_tab.js src/static/js/inline_analysis_player.js \
         src/static/js/tracked_files_panel.js; do
  cp "$f" /tmp/chk.mjs && node --check /tmp/chk.mjs && echo "OK  $f"; done
cp /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/inline_analysis_3d.js /tmp/chk3.mjs \
  && node --check /tmp/chk3.mjs && echo "OK  inline_analysis_3d.js"
cd src && python -m pytest -q -p no:randomly 2>&1 | tail -4
for f in tests/unit/*.mjs; do printf "%-34s " "$(basename $f)"; \
  node "$f" 2>&1 | grep -E "^# (pass|fail)" | tr '\n' ' '; echo; done
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q --ignore=tests/e2e 2>&1 | tail -3
```
Expected: every `node --check` prints OK; main webapp at the **16** known
failures and no others; every `.mjs` `# fail 0`; dlc-3D at the **8** known
failures.

- [ ] **Step 6: Commit (two repos)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/static/js/components/tracked_files_tab.js src/static/js/tracked_files_panel.js \
        src/static/js/inline_analysis_player.js src/templates/partials/card_tracked_files.html \
        src/templates/partials/card_inline_analysis.html src/tests/test_tracked_header_bar_markup.py
git commit -m "feat(tracked-files): progress bar in both player headers; sort mounts"

cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/partials/card_inline_analysis_3d.html dlc-3D/src/static/inline_analysis_3d.js
git commit -m "feat(inline-3d): sort buttons and header progress bar mounts"
```

---

### Task 4: Deploy and verify

**Files:** none — deployment and verification only.

Dispatch to a **subagent** with this brief verbatim:

> Deploy and verify the tracked-list sorting + header progress bar change. Report findings only — do NOT edit, fix, or commit anything.
>
> 1. `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart flask dlc-3d`. A plain restart is correct here: every file changed lives under a DIRECTORY mount (`./src/dlc`, `./src/static`, `./src/templates`, and dlc-3D's own `src/static` + its individually-mounted partial), so no inode rebinding is involved. Do NOT rebuild. Do NOT touch `worker` or `worker-tf`.
> 2. `docker compose ps`, then `docker compose logs --tail=40 flask dlc-3d`. Quote any traceback mentioning `tracked_sort`, `tracked_files` or `inline_analysis`.
> 3. The app is behind session auth — unauthenticated requests 302 to /login, a FALSE NEGATIVE. Seed a cookie jar: `curl -sc /tmp/cj.txt "http://localhost:5000/?token=deeplabcut" -o /dev/null`, then use `-b /tmp/cj.txt` everywhere below. Also note: this app's error handler turns an unrouted URL into HTTP 500 carrying a `"404 Not Found..."` body, so a 500 with that body means MISSING route.
> 4. New asset is served: `curl -sb /tmp/cj.txt -o /dev/null -w '%{http_code}\n' http://localhost:5000/static/js/components/tracked_sort.mjs` must be 200.
> 5. The whitelist accepted the new key — this is the check that matters most, because a missing whitelist entry fails silently:
>    `curl -sb /tmp/cj.txt -w ' [%{http_code}]\n' "http://localhost:5000/dlc/project/ui-setting?key=tracked_sort"`
>    Expect 400 `{"error":"No active DLC project."}` (no project active) — **but NOT** `{"error":"unknown key"}`. Report the exact body. If it says "unknown key", that is a HARD FAILURE.
>    For contrast, confirm the guard works: `curl -sb /tmp/cj.txt "http://localhost:5000/dlc/project/ui-setting?key=definitely_not_a_key"` should differ.
> 6. Markup mounts are served — each count must be >= 1:
>    `curl -sb /tmp/cj.txt http://localhost:5000/ | grep -c 'id="tf-sort"'`
>    `curl -sb /tmp/cj.txt http://localhost:5000/ | grep -c 'id="ia-sort"'`
>    `curl -sb /tmp/cj.txt http://localhost:5000/ | grep -c 'id="ia-track-bar"'`
>    `curl -sb /tmp/cj.txt http://localhost:5000/dlc-3d/ | grep -c 'id="ia3d-sort"'`
>    `curl -sb /tmp/cj.txt http://localhost:5000/dlc-3d/ | grep -c 'id="ia3d-track-bar"'`
>    The last two prove dlc-3d re-read its partial.
>
> Report the restart result, any log errors quoted, the status code and BODY for steps 4-5, and each count from step 6, with one-line PASS/FAIL per check.

- [ ] **Step 1: Dispatch the deployment subagent with the brief above**

- [ ] **Step 2: Act on the report** — fix anything that failed, re-run that task's tests, re-dispatch.

- [ ] **Step 3: Manual smoke test** at `http://localhost:5000/` with a project active:

1. Open **Tracked Files & Progress**. Three sort buttons sit beside the title.
2. Click **Name** — list goes A→Z and the button shows `Name ▲`. Click again — `Name ▼`, order reverses.
3. Click **Recorded** — sessions order newest-first by the timestamp in their filename, not by when you tracked them. Any file whose name has no timestamp sits at the bottom; click again and it is *still* at the bottom.
4. Click **Opened**, then reload the page and reopen the card — the same field and direction are still selected.
5. In the 3D card, open a tracked video from the Tracked Files tab: a progress bar appears beside the filename in the player header. Change a segment there; go **← Back** and confirm the list row shows the same value.
6. Open an **untracked** video via Browse Folders — no bar in the header. Tick the track checkbox — the bar appears.
7. Repeat 5 on the 2D Inline Analysis card.

---

## Self-Review

**Spec coverage:** pure sort + timestamp parsing → Task 1; buttons, toggle, persistence, whitelist → Task 2; header bar, all five mounts, three construction sites → Task 3; deployment → Task 4. The spec's "missing values last in both directions" is enforced by two Task 1 tests; the whitelist-drift risk by Task 2's dedicated guard.

**Placeholder scan:** none — every step carries its code. Task 3 step 3a gives targeted edits rather than the whole file because `_syncHeader` is short and quoted at both edit points.

**Type consistency:** `sortTrackedFiles(rows, field, direction)` and `DEFAULT_DIRECTION` are defined in Task 1 and called with exactly those shapes in Task 2. The new `makeTrackedFiles` options `sortMount` and `headerBarMount` are declared in Task 2/3a and supplied at all three call sites in Task 3e — note the management card deliberately omits `headerBarMount` (it has no player), which the component tolerates via its `if (!headerBarMount) return;` guard. Row fields used by the sorter (`name`, `last_opened_at`) match what the listing returns.

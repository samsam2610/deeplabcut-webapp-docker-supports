# Main-webapp file-browser component port + dblclick UX fix

Date: 2026-05-19
Repo: `deeplabcut-webapp-docker` (main webapp).
Branch: whatever is currently checked out (`feat/posture-match-refiner` at
time of writing). Do not switch branches.

## Problem

Double-clicking a file in the Analyze Video / Frames card's file picker
adds it to the queue but also **closes the browser**, forcing the user
to reopen + renavigate for every file they want to add. The bug is in
`src/static/js/analyze.js:244-250`:

```js
row.addEventListener("dblclick", (e) => {
  e.stopPropagation();
  _avAddToList(fullPath);
  avTargetPath.value = fullPath;
  avBrowser.classList.add("hidden");   // ← closes the browser
  _avBrowserLoaded = false;             // ← forces reload next time
});
```

The dlc-3D module hit the exact same bug across three copies of a
similar picker in `lp_cards.js` last month. That fix established a
canonical component (`makeFileBrowser`), a policy doc
(`docs/policies/file-browser-component.md`), and static-analysis tests
that enforce its usage. The main webapp has **6+ inline pickers** with
the same antipattern waiting to bite.

## Goal

1. Port the canonical `makeFileBrowser` factory into the main webapp.
2. Refactor every inline file picker in the main webapp to use it.
3. Mirror the dlc-3D policy doc and static-analysis tests so future
   contributors can't re-introduce divergent inline pickers.

## Why a port instead of a shared import

The main webapp and the dlc-3D module are intentionally separate trees
per `deeplabcut-webapp-docker-supports/CLAUDE.md`:

> "Each module is fully self-contained in its own subdirectory.
>  Modules do not share code with the main webapp."

We therefore copy the file rather than import across the boundary. Two
near-identical copies exist after this, one per module, each governed
by its own policy doc + static-analysis tests. Any future divergence is
caught by the tests rather than going silently. This matches the
codebase's existing "two trees, parallel policies" pattern for things
like `CLAUDE.md` and `settings.json`.

## Architecture

### New file: `src/static/js/components/file_browser.js`

A verbatim port of `dlc-3D/src/static/components/file_browser.js`, with
**one extension**: a `fileFilter: (filename) => boolean` option.

Existing dlc-3D `_supportedFile` hardcodes a video+image extension set.
The main webapp's viewer card needs `.h5`-only filtering. Per the dlc-3D
policy doc's "Adding capabilities to the component" guidance, the right
move is to add a config option, not to fork the file. Change:

```js
// Before (hardcoded):
function _supportedFile(name) { /* video + image only */ }

// After:
function _supportedFile(name, filter) {
  if (filter) return filter(name);
  /* fall back to the same video+image set */
}
```

`makeFileBrowser`'s opts gain `fileFilter`, which is plumbed into
`_supportedFile` calls inside the factory. When `fileFilter` is omitted,
behavior is identical to the dlc-3D component today.

### Component surface (identical to dlc-3D + the new option)

```js
makeFileBrowser({
  inputEl,                 // <input> that receives the highlighted/picked path
  paneEl,                  // <div> that owns the tree pane
  dirOnly?: boolean,       // default false; true hides files entirely
  fileFilter?: (name) => boolean,   // NEW: override the supported-extension set
  onPick?: (path) => void, // invoked on dblclick file (browser stays open!)
}) → {
  openAt(path),            // open at a directory, fetch+render
  up(),                    // navigate up one level
  refresh(),               // re-fetch the current dir
}
```

The pane also dispatches `file-browser:pick` (CustomEvent with
`detail.path`) on dblclick for listeners that prefer DOM events.

### Behavior contract (verbatim from dlc-3D policy)

- **Single-click** on a row: highlight + write its path to `inputEl`.
  Folders also expand inline.
- **Double-click** on a file row: emit a transient "Added ✓" badge that
  fades out, AND invoke `onPick(path)` if provided. **The browser
  STAYS OPEN.** Users batch-select many files in one browsing session.
- File-type filtering is centralized inside the component. New
  filetypes go through `fileFilter` or an extension-set update — never
  through a card's own filter logic shadowing the component.

## Per-card refactor map

Each inline picker is replaced with a `makeFileBrowser` instance. Map
of existing surface to component config:

| Card / file                       | Inline anchor                     | Replacement |
|-----------------------------------|-----------------------------------|-------------|
| `analyze.js` (file picker)        | `_avMakeEntry`, dblclick at L244  | `makeFileBrowser({ inputEl: avTargetPath, paneEl: avBrowser, onPick: _avAddToList })` |
| `analyze.js` (destfolder picker)  | dir-only browser at L538          | `makeFileBrowser({ inputEl: ..., paneEl: ..., dirOnly: true })` |
| `viewer.js` (H5 picker)           | `_vaH5BrowseDir` at L1600         | `makeFileBrowser({ inputEl: ..., paneEl: ..., fileFilter: n => n.toLowerCase().endsWith(".h5") })` |
| `annotator.js` (folder browser)   | `_anvBrowseDir` at L608           | `makeFileBrowser({ inputEl: ..., paneEl: ..., dirOnly: true })` |
| `annotator.js` (clip browser)     | `_anvClipBrowseDir` at L690       | `makeFileBrowser({ inputEl: ..., paneEl: ..., onPick: <clip-add-handler> })` |
| `postprocess.js` (folder picker)  | `_ppBrowseDir` at L73             | `makeFileBrowser({ inputEl: ..., paneEl: ..., dirOnly: true })` |

For cards whose behavior diverges from the component's contract today
(e.g. a single-click navigation pattern where the component
single-click is "highlight + expand"), do the minimum to map to the
component's contract. Behavioral parity beats feature creep. If a card
needs a feature the component doesn't expose (multi-select, custom
empty-state copy, etc.), **extend the component** per the policy —
never copy-and-tweak.

## Files touched

```
src/static/js/components/file_browser.js          NEW: canonical factory
src/static/js/analyze.js                          MODIFY: use makeFileBrowser ×2
src/static/js/viewer.js                           MODIFY: use makeFileBrowser (H5)
src/static/js/annotator.js                        MODIFY: use makeFileBrowser ×2
src/static/js/postprocess.js                      MODIFY: use makeFileBrowser
docs/policies/file-browser-component.md           NEW: policy doc (port of dlc-3D's)
tests/test_file_browser_policy.py                 NEW: static-analysis enforcement
```

The policy doc lives in the **main webapp** (`deeplabcut-webapp-docker`)
this time, not in the supports docs tree. Each module's policies stay
with the module. The supports `docs/` folder still hosts the spec for
this change (this file).

## Testing

### Static-analysis pytest (`tests/test_file_browser_policy.py`)

Mirrors `dlc-3D/tests/test_file_browser_policy.py` (already in
the supports tree). Tests:

1. `test_canonical_component_exists` — `src/static/js/components/file_browser.js` exists.
2. `test_factory_exported` — module exports `makeFileBrowser`.
3. `test_dblclick_does_not_hide_pane` — the file's `dblclick` handler
   body does NOT contain `classList.add("hidden")` (regression guard
   against the bug we're fixing).
4. `test_consumers_import_canonical_factory` — for each card in the
   refactor map, the JS source imports `makeFileBrowser` from
   `./components/file_browser.js` (or via a relative path that
   resolves there).
5. `test_no_inline_factory_in_consumers` — for each card, the source
   does NOT define a `function _XxMakeEntry` style inline factory
   anymore (regression guard against a contributor copying the factory
   back in).
6. `test_policy_doc_exists` — `docs/policies/file-browser-component.md`
   exists.

Tests use string-level inspection (read source files) — same convention
as the existing `test_frame_labeler_*` and `test_log_stream_module.py`
guards. No JS runtime required.

### Behavioral test

The refactor preserves observable behavior per card, so a small
behavioral pytest is OPTIONAL. If the subagent has time and the
existing test harness makes it cheap, add a single test that mounts
`analyze.js` (via a tiny HTML harness + a stub `/fs/ls`) in a
Playwright session and asserts: dblclick a file row → row gets the
"Added ✓" badge, the pane is still visible, the input value is the
file's path. If the harness is non-trivial, SKIP — the static-analysis
guards plus a manual smoke check are sufficient.

### Manual smoke

After the subagent finishes its commits and runs `docker compose
restart flask`, the user (or the subagent itself with an authed curl
of the static asset) verifies:

- `/static/js/components/file_browser.js` returns 200 and contains
  `export function makeFileBrowser`.
- The Analyze Video / Frames card, when opened in a browser, allows
  double-clicking multiple files in one session WITHOUT the browser
  collapsing. (Cannot be verified by curl; flag explicitly as
  "frontend-needs-browser-test" in the report if it's the case.)

## Hard constraints

- An ANALYZE job is currently running in the `worker` container (CPU
  ~1216% at spec time). It must NOT be interrupted.
- **Do NOT restart, stop, kill, or down**: `worker`, `worker-tf`,
  `dlc-3d-worker`, `redis`, `dlc-3d`. Leave them alone.
- `flask` restart is allowed (and may be needed for the templates if
  they ever cache; static JS is bind-mounted so the new component file
  is visible immediately, but a flask restart is harmless and confirms
  a clean process state). The flask restart MUST be followed by a
  worker-CPU sanity check before sign-off.
- Verification before declaring done:
  ```
  docker stats --no-stream --format "{{.Name}} {{.CPUPerc}}" \
    deeplabcut-webapp-docker-worker-1
  # worker must still be >500% CPU (i.e. the analyze job is still chewing)
  ```
- Do NOT push commits to remotes.
- Do NOT use `git add .` or `--no-verify`. Stage files explicitly.

## Staging (recommended commit boundaries)

To keep the change reviewable and bisectable, the subagent should
produce ONE commit per logical step:

1. **`feat(file-browser): port canonical component + policy + tests`**
   — adds `src/static/js/components/file_browser.js`, the policy doc,
   and the static-analysis pytest file. Tests will be PARTIALLY red
   until the consumer commits land — that's expected. The subagent
   marks any consumer-side tests as `pytest.mark.skip(reason="…")` in
   this commit, OR splits the consumer-side tests out so they land
   alongside the consumer commits.

2. **`refactor(analyze): use canonical file_browser component`**
   — refactors `analyze.js`'s two pickers. This is the commit that
   fixes the user's reported bug. Unskips the analyze-related portion
   of the policy tests.

3. **`refactor(viewer): use canonical file_browser component (H5)`**
   — viewer.js H5 picker.

4. **`refactor(annotator): use canonical file_browser component`**
   — annotator.js's two pickers.

5. **`refactor(postprocess): use canonical file_browser component`**
   — postprocess.js picker.

Each commit must leave the test suite green (or skipped with a TODO
linking to a later commit). After commit 2 lands, the user's reported
bug is fixed even if 3-5 are deferred.

## Out of scope

- Backend changes. The `/fs/ls` endpoint stays as-is.
- Multi-select via Shift-click. The dlc-3D component doesn't have it
  today; if a future card needs it, extend the component per policy.
- A unified design-system pass on the pane styling. The component's
  inline styles get ported verbatim.
- Cards that don't currently have a file picker (frame_extractor,
  frame_labeler, etc.). They're listed in the survey for context only.

## Risks

- **Risk**: a card uses a picker behavior the component doesn't model
  (e.g. drag-to-rearrange selected files). Mitigation: the subagent
  reads each card's full picker code before refactoring and flags any
  divergence in the final report; if a card cannot be cleanly
  refactored, SKIP it and report rather than producing a half-working
  commit.
- **Risk**: the component's hardcoded inline styles clash visually
  with one of the cards. Mitigation: the policy doc allows the
  consumer to pass extra classes on the pane via standard DOM, since
  `paneEl` is owned by the consumer; if a real visual regression
  appears, fix it in CSS, not by forking the component.
- **Risk**: a card's pickup callback has side effects that don't fit
  `onPick(path)`'s narrow signature. Mitigation: subscribe to the
  `file-browser:pick` CustomEvent instead, which gives the card full
  DOM context.

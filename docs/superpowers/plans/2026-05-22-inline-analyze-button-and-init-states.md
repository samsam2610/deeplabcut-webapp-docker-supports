# Inline Analysis: "Start Analysis" button restyle + Init-button states — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the inline-analysis "Analyze…" button to match the "Start Analysis" button, and make the Initialize-analysis-file button show clear disabled/partial states based on which analysis files already exist.

**Architecture:** Pure front-end change in two repos. The 2D card lives in the `deeplabcut-webapp-docker` (main webapp) repo; the 3D card lives in the `deeplabcut-webapp-docker-supports/dlc-3D` repo. Each repo guards its inline-analysis UI with a static source-assertion pytest file (the test reads the `.html`/`.js` source text and asserts substrings — there is no browser/DOM runtime). We follow that exact pattern: write/extend a source-assertion test, watch it fail, edit the source, watch it pass, commit.

**Tech Stack:** Vanilla JS, Jinja HTML partials, pytest (static text assertions over source files).

---

## Conventions used by every task

- **Two repos.** Tasks 1–3 are in `deeplabcut-webapp-docker` (run commands from
  `/home/sam/docker-images/deeplabcut-webapp-docker`). Tasks 4–6 are in
  `deeplabcut-webapp-docker-supports/dlc-3D` (run commands from
  `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D`). Each task's
  command block starts with the correct `cd`.
- **Tests are static.** They call `Path.read_text()` on the source file and
  `assert "<literal substring>" in text`. No fixtures, no DOM. Fast (<1s) and
  disk-safe.
- **Branch:** the dlc-3D repo is on `feat/3d-inline-analysis`. Commit there as
  normal. For the main webapp repo, check the current branch first with
  `git -C /home/sam/docker-images/deeplabcut-webapp-docker branch --show-current`;
  if it is `main`, create a branch `feat/inline-analyze-button-restyle` before the
  first commit (Task 1, Step 5 handles this).
- **The reference button** (do not edit it) is `#btn-run-analyze` in
  `deeplabcut-webapp-docker/src/templates/partials/card_analyze.html:136`:

```html
<button id="btn-run-analyze" class="btn-sm btn-create">
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
  Start Analysis
</button>
```

---

## Task 1: 2D — restyle the Analyze button (markup)

**Files:**
- Modify: `deeplabcut-webapp-docker/src/templates/partials/card_inline_analysis.html:79`
- Test: `deeplabcut-webapp-docker/tests/test_inline_analysis_ui_isolation.py`

- [ ] **Step 1: Write the failing test**

Add this function to the end of `tests/test_inline_analysis_ui_isolation.py`:

```python
def test_analyze_button_matches_start_analysis_style():
    """The inline Analyze button mirrors the Analyze-card 'Start Analysis'
    button: btn-create class, outline play-triangle SVG, static label."""
    html = CARD.read_text()
    m = re.search(r'<button[^>]*id="ia-btn-analyze-range".*?</button>', html, re.S)
    assert m, "ia-btn-analyze-range button not found"
    btn = m.group(0)
    assert "btn-create" in btn, "must adopt the btn-create accent style"
    assert "<svg" in btn and 'points="5 3 19 12 5 21 5 3"' in btn, \
        "must include the outline play-triangle icon"
    assert "Start Analysis" in btn, "label must read 'Start Analysis'"
    assert "width:100%" not in btn, "drop full-width so it matches the compact reference"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
python -m pytest tests/test_inline_analysis_ui_isolation.py::test_analyze_button_matches_start_analysis_style -v
```

Expected: FAIL — current button is `class="btn-sm"`, has `▶`, and has `width:100%`.

- [ ] **Step 3: Edit the markup**

In `card_inline_analysis.html`, replace line 79:

```html
        <button id="ia-btn-analyze-range" class="btn-sm" style="width:100%;margin-top:.3rem">▶ Analyze 500 frames from frame 0</button>
```

with:

```html
        <button id="ia-btn-analyze-range" class="btn-sm btn-create" style="margin-top:.3rem">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          Start Analysis
        </button>
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
python -m pytest tests/test_inline_analysis_ui_isolation.py::test_analyze_button_matches_start_analysis_style -v
```

Expected: PASS.

- [ ] **Step 5: Commit (create a branch first if on main)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
if [ "$(git branch --show-current)" = "main" ]; then git checkout -b feat/inline-analyze-button-restyle; fi
git add src/templates/partials/card_inline_analysis.html tests/test_inline_analysis_ui_isolation.py
git commit -m "feat(inline-analysis): restyle Analyze button to match Start Analysis

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: 2D — remove the dynamic-label JS (so the SVG icon survives)

**Why:** `_iaSyncLabel()` sets `iaBtnAnalyze.textContent`, which erases the SVG icon added in Task 1. The "N frames from frame K" info is still written to the separate `#ia-last-run-status` line by the click handler (`inline_analysis_player.js:2326`), so removing the label sync loses nothing.

**Files:**
- Modify: `deeplabcut-webapp-docker/src/static/js/inline_analysis_player.js:2230-2241`
- Test: `deeplabcut-webapp-docker/tests/test_inline_analysis_ui_isolation.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_inline_analysis_ui_isolation.py`:

```python
def test_player_does_not_rewrite_analyze_button_text():
    """After the restyle, nothing may overwrite the Analyze button's
    textContent (it would wipe the SVG icon). The old dynamic label is gone."""
    src = PLAYER_JS.read_text()
    assert "_iaSyncLabel" not in src, "dynamic label fn must be removed"
    assert "iaBtnAnalyze.textContent" not in src, \
        "nothing may set the Analyze button textContent"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
python -m pytest tests/test_inline_analysis_ui_isolation.py::test_player_does_not_rewrite_analyze_button_text -v
```

Expected: FAIL — `_iaSyncLabel` and `iaBtnAnalyze.textContent` still present.

- [ ] **Step 3: Delete the dynamic-label block**

In `inline_analysis_player.js`, delete this entire block (currently lines 2230-2241):

```javascript
      // ── Live label on the Analyze button ────────────────────────────
      function _iaSyncLabel() {
        const n = parseInt(iaFramesPerCk?.value, 10) || 500;
        const k = _iaCurrentFrame || 0;
        iaBtnAnalyze.textContent = `▶ Analyze ${n} frames from frame ${k}`;
      }
      iaFramesPerCk?.addEventListener("input", _iaSyncLabel);
      // Keep in sync with the player's frame counter via MutationObserver.
      if (iaFrameCounter) {
        new MutationObserver(_iaSyncLabel)
          .observe(iaFrameCounter, { childList: true, characterData: true, subtree: true });
      }
```

Leave everything above (the snapshot-loader wiring ending at the
`iaOpenBtn?.addEventListener("click", _iaLoadSnapshots);` line) and below (the
`_iaEnsureSession` function) untouched. Do not remove the `iaBtnAnalyze` const
(`:2183`) or the `if (!iaBtnAnalyze) return;` guard (`:2188`) — the click handler
at `:2294` still uses `iaBtnAnalyze`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
python -m pytest tests/test_inline_analysis_ui_isolation.py::test_player_does_not_rewrite_analyze_button_text tests/test_inline_analysis_ui_isolation.py::test_player_has_analyze_dispatch_block -v
```

Expected: both PASS (the second confirms the click-dispatch wiring still references `ia-btn-analyze-range`).

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/static/js/inline_analysis_player.js tests/test_inline_analysis_ui_isolation.py
git commit -m "refactor(inline-analysis): drop dynamic Analyze-button label

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: 2D — Init button reads "Analysis file exist" when file present

**Files:**
- Modify: `deeplabcut-webapp-docker/src/static/js/inline_analysis_player.js:2403-2411` (`_iaRefreshInitFileBtn`)
- Test: `deeplabcut-webapp-docker/tests/test_inline_analysis_ui_isolation.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_inline_analysis_ui_isolation.py`:

```python
def test_init_button_shows_file_exists_note_when_initialized():
    """When the analysis file already exists the Init button is disabled and
    its label reads 'Analysis file exist'."""
    src = PLAYER_JS.read_text()
    assert "Analysis file exist" in src, "disabled-state label must be 'Analysis file exist'"
    assert "Analysis file ready" not in src, "old 'ready' wording must be replaced"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
python -m pytest tests/test_inline_analysis_ui_isolation.py::test_init_button_shows_file_exists_note_when_initialized -v
```

Expected: FAIL — source still says `"✓ Analysis file ready"`.

- [ ] **Step 3: Edit the label string**

In `inline_analysis_player.js`, find line 2410 inside `_iaRefreshInitFileBtn`:

```javascript
          iaInitFileBtn.textContent = d.initialized ? "✓ Analysis file ready" : "○ Initialize analysis file";
```

Replace with:

```javascript
          iaInitFileBtn.textContent = d.initialized ? "Analysis file exist" : "○ Initialize analysis file";
```

Also update the click-handler success line (`:2422`) for wording consistency:

```javascript
          if (r.ok || r.status === 409) { iaInitFileBtn.textContent = "✓ Analysis file ready"; }
```

Replace with:

```javascript
          if (r.ok || r.status === 409) { iaInitFileBtn.textContent = "Analysis file exist"; iaInitFileBtn.disabled = true; }
```

(The `iaInitFileBtn.disabled = !!d.initialized;` on `:2409` already disables the button in the initialized state — no change needed there.)

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
python -m pytest tests/test_inline_analysis_ui_isolation.py -v
```

Expected: all PASS (full file — confirms no regression in the other 2D assertions).

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/static/js/inline_analysis_player.js tests/test_inline_analysis_ui_isolation.py
git commit -m "feat(inline-analysis): Init button shows 'Analysis file exist' when present

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: 3D — restyle the Analyze button (markup)

**Files:**
- Modify: `deeplabcut-webapp-docker-supports/dlc-3D/src/templates/partials/card_inline_analysis_3d.html:80`
- Test: `deeplabcut-webapp-docker-supports/dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py`

Note: the 3D button keeps its `disabled` attribute (sibling gating relies on it —
guarded by the existing `test_analyze_button_disabled_by_default`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_analyze_button_matches_start_analysis_style():
    """3D Analyze button mirrors the Analyze-card 'Start Analysis' button:
    btn-create class, outline play-triangle SVG, 'Start Analysis' label.
    It must stay default-disabled (sibling gating)."""
    html = CARD.read_text()
    m = re.search(r'<button[^>]*id="ia3d-btn-analyze-range".*?</button>', html, re.S)
    assert m, "ia3d-btn-analyze-range button not found"
    btn = m.group(0)
    assert "btn-create" in btn
    assert "<svg" in btn and 'points="5 3 19 12 5 21 5 3"' in btn
    assert "Start Analysis" in btn
    assert "disabled" in btn, "must remain default-disabled until a sibling resolves"
    assert "width:100%" not in btn
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_analyze_button_matches_start_analysis_style -v
```

Expected: FAIL — current button is `class="btn-sm"`, `▶ Analyze both cameras`, `width:100%`.

- [ ] **Step 3: Edit the markup**

In `card_inline_analysis_3d.html`, replace line 80:

```html
        <button id="ia3d-btn-analyze-range" class="btn-sm" disabled style="width:100%;margin-top:.3rem">▶ Analyze both cameras</button>
```

with:

```html
        <button id="ia3d-btn-analyze-range" class="btn-sm btn-create" disabled style="margin-top:.3rem">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          Start Analysis
        </button>
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_analyze_button_matches_start_analysis_style tests/test_inline_analysis_3d_ui_isolation.py::test_analyze_button_disabled_by_default -v
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/templates/partials/card_inline_analysis_3d.html tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): restyle Analyze button to match Start Analysis

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: 3D — Init button three-way state (both / neither / partial)

**Files:**
- Modify: `deeplabcut-webapp-docker-supports/dlc-3D/src/static/inline_analysis_3d.js:3465-3474` (`_refreshInitFileBtn`)
- Test: `deeplabcut-webapp-docker-supports/dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py`

The click handler at `:3486` needs no change (`_initOne` already treats HTTP 409
as success, so a partial-state click generates only the missing camera).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_init_button_three_way_state_logic():
    """_refreshInitFileBtn distinguishes both-exist / neither / partial, and the
    partial branch writes a 'will generate camN only' note to the status line."""
    js = JS.read_text()
    i = js.find("async function _refreshInitFileBtn")
    assert i > 0, "_refreshInitFileBtn definition not found"
    body = js[i:i + 1800]
    # both exist -> disabled with the 'exist' wording
    assert "Analysis files exist" in body
    assert "Analysis files ready" not in js, "old 'ready' wording must be replaced"
    # partial-state note text (both directions)
    assert "Initialize will generate cam1 only" in body
    assert "Initialize will generate cam0 only" in body
    # partial-state names the missing camera on the button
    assert "Initialize cam1 analysis file" in body
    assert "Initialize cam0 analysis file" in body
    # partial messaging is guarded by a resolved sibling
    assert "_siblingPath" in body
    # the note is written to the existing status line
    assert "initFileStatus" in body
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_init_button_three_way_state_logic -v
```

Expected: FAIL — current `_refreshInitFileBtn` only has the `a && b` / else branches and the `"✓ Analysis files ready"` wording.

- [ ] **Step 3: Rewrite `_refreshInitFileBtn`**

In `inline_analysis_3d.js`, replace the current function (lines 3465-3474):

```javascript
      async function _refreshInitFileBtn() {
        if (!initFileBtn) return;
        const cam0 = _cam0Path();
        if (!cam0) { initFileBtn.disabled = true; return; }
        initFileBtn.disabled = false;
        const a = await _initStatus(cam0);
        const b = _siblingPath ? await _initStatus(_siblingPath) : true;
        if (a && b) { initFileBtn.textContent = "✓ Analysis files ready"; initFileBtn.disabled = true; }
        else { initFileBtn.textContent = "○ Initialize analysis files (both cameras)"; }
      }
```

with:

```javascript
      async function _refreshInitFileBtn() {
        if (!initFileBtn) return;
        const cam0 = _cam0Path();
        if (!cam0) {
          initFileBtn.disabled = true;
          if (initFileStatus) initFileStatus.textContent = "";
          return;
        }
        const a = await _initStatus(cam0);
        const hasSibling = !!_siblingPath;
        const b = hasSibling ? await _initStatus(_siblingPath) : true;

        if (a && b) {
          // both cameras already have analysis files
          initFileBtn.textContent = "Analysis files exist";
          initFileBtn.disabled = true;
          if (initFileStatus) initFileStatus.textContent = "";
        } else if (hasSibling && (a !== b)) {
          // exactly one camera has a file — generate only the missing one
          const present = a ? "cam0" : "cam1";
          const missing = a ? "cam1" : "cam0";
          initFileBtn.textContent = `○ Initialize ${missing} analysis file`;
          initFileBtn.disabled = false;
          if (initFileStatus)
            initFileStatus.textContent =
              `${present} already has an analysis file — Initialize will generate ${missing} only.`;
        } else {
          // neither camera has a file
          initFileBtn.textContent = "○ Initialize analysis files (both cameras)";
          initFileBtn.disabled = false;
          if (initFileStatus) initFileStatus.textContent = "";
        }
      }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_init_button_three_way_state_logic tests/test_inline_analysis_3d_ui_isolation.py::test_init_analysis_file_button_wired -v
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): Init button distinguishes both/neither/partial analysis-file states

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Full guard-suite sweep (both repos)

**Files:** none (verification only).

- [ ] **Step 1: Run the 2D guard suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
python -m pytest tests/test_inline_analysis_ui_isolation.py -v
```

Expected: all PASS (16 existing + 3 added in Tasks 1–3 = 19).

- [ ] **Step 2: Run the 3D guard suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -v
```

Expected: all PASS (13 existing + 2 added in Tasks 4–5 = 15).

- [ ] **Step 3: No commit needed** (verification task). If any test fails, fix the
  source in the owning task's file and re-run before considering the plan done.

---

## Self-review notes (author)

- **Spec coverage:** Change 1 → Tasks 1, 2 (2D) + Task 4 (3D). Change 2 → Task 3
  (2D) + Task 5 (3D, including the partial-state requirement). Task 6 = the
  spec's "keep guard tests green" requirement. All spec rows mapped.
- **Cross-repo:** The 2D tasks (1–3) commit in `deeplabcut-webapp-docker`; the 3D
  tasks (4–5) commit in `dlc-3D`. Task 1 Step 5 branches off `main` if needed.
- **Icon-clobber risk:** Task 2 removes the only writer of
  `iaBtnAnalyze.textContent`; Task 4's 3D button has no textContent writer
  (verified — only `.disabled` is toggled). Both safe.
- **No server changes:** all four endpoints used already exist.

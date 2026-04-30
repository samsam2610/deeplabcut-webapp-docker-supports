# DLC-3D File Browser Collapse — Design Spec

**Date:** 2026-04-30
**Status:** Approved

## Goal

Two UX fixes to the 3D Frame Extractor's source section:
1. Stop auto-navigating to `videos/` on project load — browser starts hidden.
2. Add a Browse toggle button that expands/collapses the file browser; collapses automatically after a video is selected.

---

## Section 1: Remove auto-browse on project load

**Current:** `_loadProject()` calls `_browseDir(_projectPath + "/videos")` after setting the project path, immediately populating the file browser.

**Fix:** Remove that call. After project loads, only `#dlc3d-project-display` is updated. The file browser (`#dlc3d-file-browser`) stays hidden; the Browse button (see Section 2) appears.

---

## Section 2: Browse toggle button

### HTML — `card_3d_extract.html`

Replace the current project display line in `#dlc3d-source-section`:

```html
<div style="font-size:.75rem;color:var(--text-dim);margin-bottom:.35rem">
  Project: <span id="dlc3d-project-display" style="color:var(--text)">—</span>
</div>
```

With a flex row that adds the Browse button:

```html
<div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.35rem">
  <div style="font-size:.75rem;color:var(--text-dim);flex:1">
    Project: <span id="dlc3d-project-display" style="color:var(--text)">—</span>
  </div>
  <button id="dlc3d-browse-btn" class="btn-sm btn-server-pick"
          style="display:none" title="Browse project files">Browse</button>
</div>
```

### JS — `dlc_3d.js`

**`_loadProject()`:** After setting `_projectPath` and updating `#dlc3d-project-display`, show the Browse button. Do NOT call `_browseDir`.

```javascript
document.getElementById("dlc3d-browse-btn").style.display = "";
```

**Browse button toggle** (new listener in `DOMContentLoaded`):

```javascript
document.getElementById("dlc3d-browse-btn")?.addEventListener("click", () => {
  const browser = document.getElementById("dlc3d-file-browser");
  if (browser.style.display === "none") {
    _browseDir(_projectPath);   // always re-browse from project root on expand
  } else {
    browser.style.display = "none";
    const empty = document.getElementById("dlc3d-session-empty");
    if (empty) empty.style.display = "";
  }
});
```

**`_selectVideo()`:** After a video is selected, collapse the browser:

```javascript
const browser = document.getElementById("dlc3d-file-browser");
if (browser) browser.style.display = "none";
const empty = document.getElementById("dlc3d-session-empty");
if (empty) empty.style.display = "none"; // already hidden by _browseDir
```

**`_resetExtractorUI()`:** Hide the Browse button:

```javascript
document.getElementById("dlc3d-browse-btn").style.display = "none";
```

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dlc-3D/src/templates/partials/card_3d_extract.html` |
| Modify | `dlc-3D/src/static/dlc_3d.js` |

---

## Testing

1. `docker compose build dlc-3d && docker compose up -d dlc-3d`
2. Open extractor → file browser is hidden, Browse button is hidden
3. Load project via "Manage DLC Project" → project name appears, Browse button appears, file browser stays hidden
4. Click Browse → file browser expands showing project root contents (not videos/)
5. Click Browse again → file browser collapses
6. Click Browse → navigate into `videos/` → click a `.avi` → player loads AND file browser collapses
7. Change project → Browse button hides, file browser hides, player hides

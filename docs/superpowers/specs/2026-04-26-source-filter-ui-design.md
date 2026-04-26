# Source Filter UI — Design Spec

## Goal

Add a three-mode filter bar above the detection results list so the user can show only sensor+CLIP detections, only CLIP-only detections, or all detections. Default after a scan is `sensor+CLIP`.

## Architecture

Pure frontend change — no backend routes, no data model changes. A `currentFilter` variable drives visibility. Each result card gets a `data-source` attribute. `applyFilter()` iterates cards and toggles `display:none`.

---

## Filter Bar

### HTML (in `clip_cutter.html`)

A `<div id="source-filter">` is inserted immediately above `#results-list` (inside the results section). It contains three buttons:

```html
<div id="source-filter">
  <button class="filter-btn active" data-filter="sensor+clip">✓ sensor+CLIP</button>
  <button class="filter-btn" data-filter="clip_only">CLIP only</button>
  <button class="filter-btn" data-filter="all">All</button>
</div>
```

The `sensor+clip` button carries `active` class on page load (visual default only — actual filter state is set after each scan completes).

### CSS (in `clip_cutter.html` `<style>`)

```css
#source-filter { display: flex; gap: 6px; margin-bottom: 8px; }
.filter-btn { padding: 3px 10px; border-radius: 12px; border: 1px solid #30363d;
              background: #1c2128; color: #768390; font-size: 11px; cursor: pointer; }
.filter-btn.active { background: #1f6feb; border-color: #1f6feb; color: #fff; }
```

---

## JavaScript (`clip_cutter.js`)

### State

```js
let currentFilter = "sensor+clip";
```

### `applyFilter()`

```js
function applyFilter() {
  document.querySelectorAll(".result-card").forEach((card) => {
    const src = card.dataset.source || "";
    const visible =
      currentFilter === "all" ||
      (currentFilter === "sensor+clip" && src === "sensor+clip") ||
      (currentFilter === "clip_only" && src === "clip_only");
    card.style.display = visible ? "" : "none";
  });
}
```

### `buildResultCard()` — add `data-source`

After `card.id = \`card-${idx}\``, add:

```js
card.dataset.source = d.source || "";
```

### Filter button wiring in `DOMContentLoaded`

```js
document.querySelectorAll(".filter-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    currentFilter = btn.dataset.filter;
    document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    applyFilter();
  });
});
```

### Reset filter on scan complete

In `listenToScan()`, after `renderDetections(job.detections)`:

```js
currentFilter = "sensor+clip";
document.querySelectorAll(".filter-btn").forEach((b) => {
  b.classList.toggle("active", b.dataset.filter === "sensor+clip");
});
applyFilter();
```

### Apply filter on saved-detection load

In `loadSavedDetections()`, after `renderDetections(data.detections)`:

```js
applyFilter();
```

---

## File Changes

| File | Action |
|------|--------|
| `templates/clip_cutter.html` | Add `#source-filter` HTML + CSS |
| `static/clip_cutter.js` | Add `currentFilter` state, `applyFilter()`, `data-source` on cards, button wiring, reset on scan, apply on load |

---

## Testing

- Filter bar visible above results after scan
- Default active button is `sensor+CLIP`
- Clicking `CLIP only` hides all `sensor+clip` and `sensor_only` cards, shows `clip_only` cards
- Clicking `All` shows every card
- After a new scan, filter resets to `sensor+CLIP` automatically
- Loading saved detections respects current filter state
- Cards with no source (legacy detections without `source` field) are shown only in `All` mode
- Cards with `source = "sensor_only"` are shown only in `All` mode (they match neither the `sensor+clip` nor `clip_only` filter)

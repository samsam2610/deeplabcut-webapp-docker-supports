# Unified Radio-Timeline Design

**Date:** 2026-04-28  
**Module:** clip-cutter — enhanced player tag bars  
**Status:** Approved

---

## Problem

The tag bar (Status / Note) chip interaction was broken: chips either did nothing (when no sub-row existed) or silently auto-created sub-rows without a coherent model. The main canvas started pre-populated with all chip events, making it visually cluttered and defeating the purpose of the chip-toggle interaction.

---

## Design

### Concept

Each bar section (Status, Note) contains a vertical stack of **timelines**. Every timeline — including the main canvas — has a radio button at its left edge. All radios in a bar share one group; only one may be selected at a time. The selected timeline is the target for chip interactions.

### Layout

```
bar header: [Label] [◀] [▶] [+]   [chip] [chip] [chip]
            [◉]  █████████████ main canvas ████████████
            [○]  ████ sub-row 1 █████████████████  [×]
            [○]  ████ sub-row 2 █████████████████  [×]
```

The main canvas row and each sub-row are visually identical except:
- The main canvas row has no `×` button (it cannot be removed).
- The main canvas radio is checked on load and whenever the previously selected sub-row is removed.

### Startup State

- Only the main canvas row exists.
- Main radio is auto-selected.
- Main canvas is **blank** — `_epActiveStatus` and `_epActiveNote` start as empty Sets.
- No chips are highlighted.

### `+` Button

Appends a new sub-row immediately below all existing rows. The new row:
- Has a blank canvas.
- Owns an empty active-chip Set.
- Has its radio auto-selected (focus shifts to new row).

### Chip Interaction

Chips respond to whichever timeline's radio is currently checked.

- **Click a chip** → toggle that chip value in the selected timeline's active-chip Set → redraw that timeline's canvas.
- **Click same chip again** → remove from Set → canvas updates (may go blank).
- **Other timelines are untouched.**

Multiple chips may be active on any single timeline simultaneously.

### Per-Timeline State

Each timeline independently owns a `Set<string>` of active chip values:

| Timeline | State storage |
|---|---|
| Main canvas | `_epActiveStatus` / `_epActiveNote` (module-level `let`) |
| Sub-row | `row._activeChips` (property on the DOM element) |

`row.dataset.chipVal` (single string) is replaced by `row._activeChips` (Set) for sub-rows.

### Chip Highlight

The chip highlight reflects the **currently selected radio's timeline** active-chip Set. When the user switches radios, `_epRenderStatusChips()` / `_epRenderNoteChips()` re-runs and updates `active` class based on the newly focused timeline's Set.

### `×` Button (sub-rows only)

Removes the sub-row and its state. If that row's radio was checked, the main row's radio becomes checked and chip highlights update accordingly.

### Prev / Next Navigation

Navigate occurrences of `_epActiveChip` within the currently selected timeline. `_epActiveChip` is set to the last-toggled-ON chip on the selected timeline, or `null` if none.

### Canvas Drawing

`_epDrawSubCanvas` is updated to accept a `Set<string>` of active chip values instead of a single string, drawing all active chips in their respective colors.

The main canvas draw call (`_epRedrawStatusCanvas`) already accepts `_epActiveStatus` (a Set) — no change needed there.

---

## Files Changed

| File | Change |
|---|---|
| `static/enhanced_player.js` | Radio on main canvas row; per-row `_activeChips` Set; chip toggle logic; `_epDrawSubCanvas` accepts Set; radio `change` handler updates chip highlights |
| `templates/clip_cutter.html` | Wrap main canvas in `.ep-main-row` div with radio; CSS for `.ep-main-row` |
| `tests/test_ui.py` | Update/add chip-toggle tests to match new model |

---

## Out of Scope

- The cursor triangle and cursor canvas above the main canvas are unchanged.
- The sync-cam feature is unchanged.
- Library / scan flows are unchanged.

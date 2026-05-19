# Frame Labeler — Lock body-part selection

Date: 2026-05-18
Scope: main webapp (`deeplabcut-webapp-docker`) and `dlc-3D` module — both
frame labelers.

## Problem

After placing a label, the frame labeler auto-advances the selected body part
to the next unlabeled one (`_flAutoAdvanceBp()`). When a user is refining a
single tricky landmark — clicking, eyeballing, clicking again to overwrite —
this auto-advance gets in the way: each placement bumps the selection off the
BP they're trying to nail down.

## Feature

A "Lock BP" checkbox. When checked, the currently selected body part stays
selected after a click; consecutive clicks overwrite that BP's marker on the
current frame. When unchecked, behavior is unchanged from today.

## UI

In each labeler template, insert a new row between the body-part chip list
and the existing Save row:

```
[ ] Lock body-part selection — keep current BP after placing (overwrite on next click)   (L)
```

- `<input type="checkbox">`
  - main webapp: `id="fl-lock-bp"`
  - dlc-3D:      `id="fl3d-lock-bp"`
- Default: **unchecked** on every page load. No persistence (no localStorage,
  no backend, no per-frame reset — purely session/DOM state).
- Label text describes the behavior; tooltip / hint indicates the `L`
  keyboard shortcut.

## Behavior

1. In `_flAutoAdvanceBp()` (both `frame_labeler.js` and `frame_labeler_3d.js`),
   read the checkbox; if `checked`, return immediately without advancing.
   The existing "cycle to next unlabeled BP" logic runs only when the lock is
   off.
2. In each module's `keydown` handler, add a branch that toggles
   `checkbox.checked` when the pressed key is `L` (matched case-insensitively
   via `e.key.toLowerCase() === "l"`, so both `l` and `Shift-L` work). Guard
   with the same `INPUT/TEXTAREA/SELECT` focus check the other shortcuts use,
   plus the existing `flCard.classList.contains("hidden")` guard.
3. No interaction with frame navigation: navigating to a new frame does not
   clear the lock (we already explicitly chose "no persistence per frame"
   in brainstorming — the lock is a session-level user preference).

Overwrite semantics: today, clicking the canvas while a BP is selected
already replaces that BP's point on the current frame. So "stay on same BP →
overwrite on next click" requires no additional code on the placement path;
it falls out automatically once auto-advance is suppressed.

## Files touched

Main webapp (`/home/sam/docker-images/deeplabcut-webapp-docker`):
- `src/static/js/frame_labeler.js` — lock check in `_flAutoAdvanceBp`,
  keybinding for `L`.
- `src/templates/partials/card_frame_labeler.html` — new checkbox row.
- `tests/test_frame_labeler_lock_bp.py` — new static-source guard test.

dlc-3D module
(`/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D`):
- `src/static/frame_labeler_3d.js` — same change with `fl3d-` ids.
- `src/templates/partials/card_frame_labeler.html` — new checkbox row.
- `tests/test_frame_labeler_3d_lock_bp.py` — new static-source guard test.

No backend / route changes. No DB schema change. No Docker rebuild required —
both are pure static-asset edits (Flask serves the files unchanged).

## Testing

Follow the static-source guard convention established by
`tests/test_frame_labeler_no_auto_frame_advance.py`. Each new test file:

1. **Template assertion** — read the `card_frame_labeler.html` partial and
   assert the checkbox id (`fl-lock-bp` / `fl3d-lock-bp`) appears as an
   `<input type="checkbox">`.
2. **JS auto-advance gate assertion** — extract the body of
   `_flAutoAdvanceBp` (reuse the brace-walking helper from the existing
   test) and assert the body references the lock element id and contains an
   early-return pattern (e.g. matches `return` near the id reference).
3. **JS keybinding assertion** — assert the JS source has a keydown branch
   that case-insensitively matches the `L` key (e.g.
   `e.key.toLowerCase() === "l"`) and toggles `.checked` on the lock element.

Run pytest in both repos:

```
cd /home/sam/docker-images/deeplabcut-webapp-docker && pytest tests/test_frame_labeler_lock_bp.py tests/test_frame_labeler_no_auto_frame_advance.py
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && pytest tests/test_frame_labeler_3d_lock_bp.py tests/test_frame_labeler_3d_no_auto_frame_advance.py
```

Both must pass before sign-off.

## Out of scope

- Per-frame auto-reset of the lock state.
- localStorage / cross-session persistence.
- Visual indicator on the BP chip itself ("pinned" badge) — the checkbox is
  the only indicator.
- Lock for keyboard-based BP cycling (Tab / Shift-Tab) — those are explicit
  user actions and should not be intercepted.

## Non-goals / why it's small

This is a one-knob behavior toggle. There is no state to persist, no
network, no schema. The entire feature is ~10 lines of JS and one row of
HTML per module, plus a static-source test per module.

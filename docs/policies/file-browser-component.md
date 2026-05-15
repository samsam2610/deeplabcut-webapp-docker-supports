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

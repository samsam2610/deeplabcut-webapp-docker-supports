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

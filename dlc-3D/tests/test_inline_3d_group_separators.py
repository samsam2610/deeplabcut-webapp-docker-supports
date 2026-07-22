"""Static guards for the two .ia3d-group-sep dividers in the Finalize-analysis block.

See docs/superpowers/specs/2026-07-22-inline-3d-ui-rearrangements-design.md (feature 3).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"
CSS = ROOT / "src" / "static" / "inline_analysis_3d.css"


def test_group_sep_css_rule():
    css = CSS.read_text()
    assert ".ia3d-group-sep" in css, "missing .ia3d-group-sep CSS rule"
    m = re.search(r"\.ia3d-group-sep\s*\{[^}]*\}", css)
    assert m
    rule = m.group(0)
    assert "border-top" in rule and "var(--border)" in rule
    assert "margin" in rule


def test_two_group_sep_dividers_after_hints():
    html = CARD.read_text()
    assert html.count('class="ia3d-group-sep"') == 2, "expected exactly two .ia3d-group-sep dividers"
    # one below #ia3d-start-hint, one below #ia3d-tag-hint
    start = html.find('id="ia3d-start-hint"')
    tag = html.find('id="ia3d-tag-hint"')
    sep1 = html.find('class="ia3d-group-sep"', start)
    sep2 = html.find('class="ia3d-group-sep"', tag)
    assert start < sep1 < tag, "first divider must sit below #ia3d-start-hint"
    assert tag < sep2, "second divider must sit below #ia3d-tag-hint"

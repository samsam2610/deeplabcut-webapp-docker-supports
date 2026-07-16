"""Frozen note chips need a non-interactive visual. See design spec 2026-07-16."""
import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "src" / "static" / "inline_analysis_3d.css"


def test_locked_chip_rule_present():
    css = CSS.read_text()
    m = re.search(r"#inline-analysis-3d-card\s+\.vv-tag-chip\.locked\s*\{([^}]*)\}", css)
    assert m, "missing .vv-tag-chip.locked rule"
    body = m.group(1)
    assert "cursor" in body and "default" in body, "locked chips must not show a pointer cursor"

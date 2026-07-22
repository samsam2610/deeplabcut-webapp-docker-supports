"""Static guards for the 3D-coverage nav arrows (#ia3d-triangulate-prev/next),
mirroring the Finalized-frames nav pair.

See docs/superpowers/specs/2026-07-22-inline-3d-ui-rearrangements-design.md (feature 1).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"
JS = ROOT / "src" / "static" / "inline_analysis_3d.js"


def test_triangulate_nav_buttons_in_coverage_header():
    """◀ ▶ buttons live inside the #ia3d-triangulate-coverage-wrap bar-header,
    mirroring the finalize pair (disabled by default)."""
    html = CARD.read_text()
    i = html.find('id="ia3d-triangulate-coverage-wrap"')
    assert i >= 0, "missing #ia3d-triangulate-coverage-wrap"
    j = html.find('id="ia3d-triangulate-coverage"', i)   # the canvas closes the header region
    assert j >= 0
    header = html[i:j]
    for bid in ("ia3d-triangulate-prev", "ia3d-triangulate-next"):
        assert f'id="{bid}"' in header, f"missing nav button #{bid} in the 3D-coverage header"
    # disabled by default (parity with #ia3d-finalize-prev/next).
    for bid in ("ia3d-triangulate-prev", "ia3d-triangulate-next"):
        k = header.find(f'id="{bid}"')
        tag = header[header.rindex("<button", 0, k):header.index(">", k)]
        assert "disabled" in tag, f"#{bid} must be disabled by default"


def test_triangulate_nav_defined_and_wired():
    s = JS.read_text()
    assert re.search(r"_triangulateNav\s*=\s*\(dir\)\s*=>", s), "must define _triangulateNav(dir)"
    m = re.search(r"_triangulateNav\s*=\s*\(dir\)\s*=>\s*\{[\s\S]{0,600}", s)
    body = m.group(0)
    assert "_triCoverageBuckets" in body, "_triangulateNav must key off _triCoverageBuckets"
    assert "bucketToFrame(" in body, "_triangulateNav seeks to bucketToFrame (buckets-only endpoint)"
    # wired to both buttons
    assert 'ia3d-triangulate-prev")?.addEventListener("click", () => _triangulateNav(-1)' in s
    assert 'ia3d-triangulate-next")?.addEventListener("click", () => _triangulateNav(1)' in s


def test_triangulate_nav_buttons_gated_on_buckets():
    """_redrawTriangulateCoverage enables/disables the two nav buttons on bucket
    presence, exactly like _redrawFinalizeCoverage."""
    s = JS.read_text()
    # The real assignment (not the forward-declaration stub) contains _drawCoverageBar.
    m = re.search(r"_redrawTriangulateCoverage\s*=\s*\(\)\s*=>\s*\{\s*\n[\s\S]{0,500}?\n  \};", s)
    assert m, "missing _redrawTriangulateCoverage body"
    body = m.group(0)
    assert 'ia3d-triangulate-prev' in body and 'ia3d-triangulate-next' in body
    assert ".disabled = !has" in body, "buttons must be gated on _triCoverageBuckets presence"

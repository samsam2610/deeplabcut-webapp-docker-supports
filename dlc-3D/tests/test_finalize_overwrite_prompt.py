"""Guard: the 'Overwrite frames … in _analyzed' prompt only fires when those frames
actually hold finalized data.

Before: the prompt fired whenever the _analyzed FILE existed (_initStatus .initialized),
so an empty range still warned about overwriting curated values. Now it is gated on the
finalized-coverage bar (_finalizeCoverageBuckets) — the same data the amber '_analyzed'
timeline draws from — so an empty range skips the prompt; unknown coverage still prompts.
"""
import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "src" / "static" / "inline_analysis_3d.js"


def _src():
    return JS.read_text()


def test_range_overlap_helper_uses_coverage_buckets():
    s = _src()
    assert re.search(r"function\s+_rangeOverlapsFinalized\s*\(", s), "must define the range-overlap helper"
    m = re.search(r"function\s+_rangeOverlapsFinalized[\s\S]{0,600}", s)
    body = m.group(0)
    assert "_finalizeCoverageBuckets" in body, "helper must read the finalized-coverage buckets"
    assert "return null" in body, "must return null when coverage isn't loaded (unknown → still prompt)"


def test_overwrite_prompt_gated_on_actual_overlap():
    s = _src()
    # the confirm must be gated on the overlap result, not just file existence
    assert re.search(r"const\s+overlap\s*=\s*_rangeOverlapsFinalized\(", s), "must compute overlap before prompting"
    assert re.search(r"overlap\s*!==\s*false\s*&&\s*!window\.confirm", s), (
        "prompt must be skipped when the range is empty in _analyzed (overlap === false)"
    )

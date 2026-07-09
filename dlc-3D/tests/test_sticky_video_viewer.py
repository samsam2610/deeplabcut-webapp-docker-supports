"""Guard: the inline-3D Finalize-analysis sub-card is sticky so it follows the scroll.

Sticky behavior itself needs a browser (verified manually / by e2e); this just guards
that the CSS rule exists with the pieces that make a sticky sidebar work: the .ia3d-right
column is position:sticky with a top offset and align-self:flex-start (so it keeps its
natural height inside the flex-start split), plus a max-height/overflow so a tall
finalize panel stays usable.

See docs/superpowers/specs/2026-07-09-sticky-video-viewer-design.md.
"""
import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "src" / "static" / "inline_analysis_3d.css"


def _right_rule():
    css = CSS.read_text()
    m = re.search(r"#inline-analysis-3d-card\s+\.ia3d-right\s*\{([^}]*)\}", css)
    assert m, "missing a .ia3d-right rule scoped to the inline-3D card"
    return m.group(1)


def test_finalize_card_is_sticky_with_top():
    body = _right_rule()
    assert re.search(r"position:\s*sticky", body), ".ia3d-right (finalize card) must be position: sticky"
    assert re.search(r"top:\s*[^;]+", body), "sticky needs a top offset"
    assert re.search(r"align-self:\s*flex-start", body), (
        "must keep natural height inside the flex-start split"
    )


def test_finalize_card_caps_height_for_tall_content():
    body = _right_rule()
    assert re.search(r"max-height:\s*[^;]+", body), "must cap height so a tall finalize panel stays usable"
    assert re.search(r"overflow-y:\s*auto", body), "must let the finalize panel scroll internally when tall"


def test_video_mount_not_sticky():
    # The pin was moved off the video onto the finalize card (user correction).
    css = CSS.read_text()
    m = re.search(r"#inline-analysis-3d-card\s+#ia3d-viewer-mount\s*\{([^}]*)\}", css)
    assert not (m and "position: sticky" in m.group(1)), "the video mount must NOT be sticky"

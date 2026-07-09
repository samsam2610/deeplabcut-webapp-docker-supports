"""Guard: the inline-3D video mount is sticky so it stays in view while scrolling.

Sticky behavior itself needs a browser (verified manually / by e2e); this just guards
that the CSS rule exists with the pieces that make it work: position:sticky, a top
offset, and an opaque background so the pinned tile paints over the scrolling content.

See docs/superpowers/specs/2026-07-09-sticky-video-viewer-design.md.
"""
import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "src" / "static" / "inline_analysis_3d.css"


def _mount_rule():
    css = CSS.read_text()
    m = re.search(r"#inline-analysis-3d-card\s+#ia3d-viewer-mount\s*\{([^}]*)\}", css)
    assert m, "missing a #ia3d-viewer-mount rule scoped to the inline-3D card"
    return m.group(1)


def test_video_mount_is_sticky_with_top():
    body = _mount_rule()
    assert re.search(r"position:\s*sticky", body), "video mount must be position: sticky"
    assert re.search(r"top:\s*[^;]+", body), "sticky needs a top offset"


def test_video_mount_has_opaque_background():
    body = _mount_rule()
    assert re.search(r"background:\s*var\(--bg\)", body), (
        "pinned mount needs an opaque background so scrolled content passes behind it"
    )

"""Guard: the status/note ◀▶ nav arrows sit next to the Status/Notes labels.

The label span used to carry `flex:1`, which stretched it and pushed the arrows to
the far right of the header row. Removing `flex:1` puts the arrows immediately after
the label text. Applies to both cards that render these timelines.

See docs/superpowers/specs/2026-07-09-timeline-nav-arrows-and-ctrl-shortcut-design.md.
"""
import re
from pathlib import Path

PARTIALS = Path(__file__).resolve().parents[1] / "src" / "templates" / "partials"
TEMPLATES = ["card_inline_analysis_3d.html", "card_viewer_3d.html"]


def test_label_spans_have_no_flex_grow():
    for name in TEMPLATES:
        p = PARTIALS / name
        assert p.is_file(), f"missing {p}"
        html = p.read_text()
        # The two status/note bar labels must still exist...
        labels = re.findall(r'<span class="fe-csv-bar-label"[^>]*>(Status|Notes)</span>', html)
        assert set(labels) >= {"Status", "Notes"}, f"{name}: Status/Notes labels missing"
        # ...but none of the status/note bar labels may keep flex:1 (which right-shifts the arrows)
        for m in re.finditer(r'<span class="fe-csv-bar-label"([^>]*)>(Status|Notes)</span>', html):
            assert "flex:1" not in m.group(1), f"{name}: {m.group(2)} label must not use flex:1"

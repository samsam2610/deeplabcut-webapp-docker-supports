"""Enforce the video-viewer component policy (docs/policies/video-viewer-component.md).

Frame-by-frame video curation viewers MUST be composed from the canonical
`VideoViewer` base + the shared feature modules — not forked per card. This
generalizes the per-feature contract tests (test_*_feature.py) into a single
module-wide rule:

1. The base + the four feature modules exist and export their factories.
2. Every feature factory returns an object exposing `attach` (composition contract).
3. Each consumer card imports `VideoViewer` from the canonical path and composes
   at least one feature.
4. No consumer reintroduces a player fork (`class Tile` / `const Controller`).
5. The policy doc exists and references the component.

Deliberately static-analysis (regex over source) — the project has no JS unit-test
runner. Tight enough to catch a future divergent player added by accident.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
VIEWER_DIR = ROOT / "src" / "static" / "components" / "viewer"
BASE_PATH = VIEWER_DIR / "video_viewer.js"
FEATURES_DIR = VIEWER_DIR / "features"
POLICY_DOC = ROOT.parent / "docs" / "policies" / "video-viewer-component.md"

# feature module stem → exported factory name
FEATURES = {
    "status_notes": "statusNoteTimeline",
    "frame_extractor": "frameExtractor",
    "clip_extractor": "clipExtractor",
    "marker_editor": "markerEditor",
}

# Cards migrated onto the library. Each must compose VideoViewer + ≥1 feature
# and must NOT fork the player.
CONSUMERS = ["dlc_3d.js", "viewer_3d.js", "inline_analysis_3d.js"]


def _read(p: Path) -> str:
    assert p.is_file(), f"missing {p}"
    return p.read_text()


# ── 1. canonical base ────────────────────────────────────────────────────────

def test_base_exists_and_exports_VideoViewer():
    src = _read(BASE_PATH)
    assert re.search(r"\bexport\s+class\s+VideoViewer\b", src), \
        "video_viewer.js must `export class VideoViewer`"


# ── 2. feature modules exist, export their factory, return { attach } ────────

@pytest.mark.parametrize("stem,factory", FEATURES.items())
def test_feature_exports_factory(stem, factory):
    src = _read(FEATURES_DIR / f"{stem}.js")
    assert re.search(rf"\bexport\s+function\s+{factory}\b", src) or \
           re.search(rf"\bexport\s*\{{[^}}]*\b{factory}\b[^}}]*\}}", src), \
        f"{stem}.js must export `{factory}`"


@pytest.mark.parametrize("stem,factory", FEATURES.items())
def test_feature_exposes_attach(stem, factory):
    src = _read(FEATURES_DIR / f"{stem}.js")
    # The factory returns a composition object exposing `attach` (method shorthand
    # `attach(` or key `attach:`). This is what `viewer.use(feature)` calls.
    assert re.search(r"\breturn\s*\{", src), f"{stem}.js factory must return an object"
    assert re.search(r"\battach\b\s*[(:]", src), \
        f"{stem}.js must expose `attach` on its returned object (the .use() contract)"


# ── 3 & 4. consumers compose the library and do not fork the player ──────────

@pytest.mark.parametrize("consumer", CONSUMERS)
def test_consumer_imports_VideoViewer_from_canonical_path(consumer):
    src = _read(ROOT / "src" / "static" / consumer)
    assert re.search(
        r"import\s*\{[^}]*\bVideoViewer\b[^}]*\}\s*from\s*[\"']\./components/viewer/video_viewer\.js[\"']",
        src,
    ), f"{consumer} must import {{ VideoViewer }} from ./components/viewer/video_viewer.js"


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_consumer_composes_at_least_one_feature(consumer):
    src = _read(ROOT / "src" / "static" / consumer)
    assert re.search(r"from\s*[\"']\./components/viewer/features/", src), \
        f"{consumer} must import at least one feature from ./components/viewer/features/"


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_consumer_does_not_fork_the_player(consumer):
    src = _read(ROOT / "src" / "static" / consumer)
    assert not re.search(r"\bclass\s+Tile\b", src), \
        f"{consumer} must not define its own `class Tile` — compose VideoViewer instead"
    assert not re.search(r"\bconst\s+Controller\s*=", src), \
        f"{consumer} must not define a `Controller` player singleton — compose VideoViewer instead"


# ── 5. policy doc ────────────────────────────────────────────────────────────

def test_policy_doc_exists_and_references_component():
    text = _read(POLICY_DOC).lower()
    assert "videoviewer" in text or "video_viewer.js" in text, \
        "policy doc should reference the canonical component"


# ── 6. View Analyzed editing regression guard (2026-05-24) ───────────────────
#
# viewer_3d.js is wired for marker editing (bp-chips, edit banner, Save
# Adjustments) but NEVER calls setEditable — its editing relied on the OLD
# markerEditor `editingAllowed=true` default. Now the default is `false`, so the
# render/edit gate (`overlayEnabled || editingAllowed`) leaves editing dead there
# unless setEditable is armed. The faithful fix mirrors setEditable to the
# overlay-enabled state at EVERY setOverlayEnabled call site, restoring the prior
# behaviour (overlay ON → render + editable; overlay OFF → neither). This guards
# that lockstep so a future edit can't silently re-break View Analyzed editing.

def test_viewer_3d_mirrors_setEditable_to_overlay_enabled_state():
    src = _read(ROOT / "src" / "static" / "viewer_3d.js")
    overlay_calls = re.findall(r"setOverlayEnabled\(([^)]*)\)", src)
    editable_calls = re.findall(r"setEditable\(([^)]*)\)", src)
    assert overlay_calls, "viewer_3d.js must call setOverlayEnabled (overlay/marker editing)"
    # Every setOverlayEnabled(X) must have a paired setEditable(X) with the SAME
    # argument, so editing tracks the overlay (the new gate is overlayEnabled ||
    # editingAllowed — tying editable to overlay keeps both off when overlay is off).
    from collections import Counter
    over = Counter(a.strip() for a in overlay_calls)
    edit = Counter(a.strip() for a in editable_calls)
    assert over == edit, (
        "viewer_3d.js must call setEditable in lockstep with setOverlayEnabled "
        f"(same boolean each time): setOverlayEnabled args={dict(over)} vs "
        f"setEditable args={dict(edit)}"
    )

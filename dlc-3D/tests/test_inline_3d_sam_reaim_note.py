"""Re-aim must say what it costs, and sit where the eye starts.

Re-aim rebuilds each camera's template pool from the user's clicks. The pool's
exemplar COUNT is part of the sweep cache key (sam-training/src/store.py:63-65
via sweep_cache.signature), so adding or deleting a click invalidates every
cached sweep in the project -- not just the clicked pair. Nothing on screen said
so, and the next sweep silently costs minutes per video.

The button also sat at the right edge, because .ia3ds-sam-status carries
`margin-left:auto` and preceded it in the markup.
"""
from pathlib import Path

import pytest

CARD = (Path(__file__).parent.parent / "src" / "static"
        / "card_inline_analysis_3d_sam.html")


@pytest.fixture
def markup():
    return CARD.read_text(encoding="utf-8")


def _note(markup):
    """Just the Re-aim note.

    Slicing to end-of-file instead made two assertions vacuous: 'reference' and
    'both' occur elsewhere in the card, so they passed whether or not the note
    contained them.
    """
    start = markup.index('id="ia3ds-pellet-retrain"')
    end = markup.index("</p>", start)
    return markup[start:end]


def test_the_button_precedes_the_status_span(markup):
    """`margin-left:auto` on the status is what pushes everything after it
    right, so order in the markup IS the alignment."""
    btn = markup.index('id="ia3ds-pellet-retrain"')
    status = markup.index('id="ia3ds-pellet-status"')
    assert btn < status, "the Re-aim button must come before the status span"


def test_the_note_warns_that_sweeps_are_invalidated(markup):
    note = _note(markup)
    assert "invalidates cached sweeps" in note
    assert "every video in the project" in note


def test_the_note_says_what_is_rebuilt(markup):
    note = _note(markup)
    for phrase in ("template pool", "median click", "both", "reference"):
        assert phrase in note, f"the note must mention {phrase!r}"


def test_pressing_it_unchanged_is_described_as_free(markup):
    """Otherwise the warning reads as 'never press this', which is wrong -- the
    signature only moves when the number of clicks does."""
    note = _note(markup)
    assert "costs nothing" in note

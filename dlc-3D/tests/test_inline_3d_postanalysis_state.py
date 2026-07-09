"""Static guards for inline-3D post-analysis view-state preservation.

Two bugs (branch fix/inline-3d-postanalysis-state):
  (a) active status/note tag filters were cleared when analysis finished (the
      post-run _viewer.load re-fires loadCsv, which clears them).
  (b) the "show kinematic markers" primary jumped to the wrong model — the fresh
      output is a raw companion (<stem><scorer>.h5, ts=null), but _pickLatestKinematic
      preferred a pre-existing postproc run (newer ts).

See docs/superpowers/specs/2026-07-09-inline-3d-postanalysis-state-design.md.
"""
import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "src" / "static" / "inline_analysis_3d.js"


def _src():
    assert JS.is_file(), f"missing {JS}"
    return JS.read_text()


# ── Bug (b): select the model just used, by scorer ──────────────────────────
def test_reload_primary_takes_scorer_and_matches_by_filename():
    s = _src()
    assert re.search(r"function\s+_reloadPrimaryAfterAnalysis\s*\(\s*scorer\s*\)", s), (
        "_reloadPrimaryAfterAnalysis must accept a scorer argument"
    )
    assert re.search(r'endsWith\(\s*scorer\s*\+\s*["\']\.h5["\']\s*\)', s), (
        "must select the variant whose path ends with scorer + '.h5'"
    )
    assert "_pickLatestKinematic(variants)" in s, "must fall back to _pickLatestKinematic"


def test_both_handlers_pass_scorer():
    s = _src()
    assert len(re.findall(r"_reloadPrimaryAfterAnalysis\(\s*d0\.scorer\s*\)", s)) >= 2, (
        "both analyze handlers must pass d0.scorer"
    )
    # the old no-arg call must be gone
    assert not re.search(r"_reloadPrimaryAfterAnalysis\(\s*\)", s), "no-arg call must be removed"


# ── Bug (a): preserve active tag filters across the reload ──────────────────
def test_pending_tag_restore_wired():
    s = _src()
    assert "_pendingTagRestore" in s, "must declare a pending-tag-restore stash"
    # snapshot taken before the reload from the timeline's getActiveTags
    assert re.search(r"_pendingTagRestore\s*=\s*_snTimeline\?\.getActiveTags\(\)", s), (
        "must snapshot active tags before _viewer.load()"
    )
    # restored via the onCsv hook (fires at the end of loadCsv)
    assert "onCsv" in s, "must wire the timeline's onCsv hook"
    assert re.search(r"setActiveTags\(\s*_pendingTagRestore\s*\)", s), (
        "onCsv must restore the stashed tags"
    )

"""Static guards for the session-stop-guard fix (data-loss bug).

Bug: closing a browser tab silently abandons queued analysis work. Both the
`beforeunload` handler and the card-close handler used to send an
unconditional stop to `/dlc/project/inline-analysis/session/stop`. Since
`snap_key` is deterministic (sha1 of config|shuffle|snapshot) and therefore
shared across cards/tabs, closing ANY tab with the original card open could
kill a batch analysis started from either card, stranding whatever was still
queued (observed: 261 of 263 ranges stranded in one run).

The fix moved the guard server-side (`only_if_idle` in
src/dlc/inline_analysis.py::session_stop, main webapp repo) but that only
protects callers that actually SET the flag. These tests pin down that both
handlers in inline_analysis_3d.js send `only_if_idle: true`, and that the
reprojection card's deliberate no-op (it must never stop the shared session)
is untouched.

See docs/superpowers/session-stop-guard-report.md.
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
JS = STATIC / "inline_analysis_3d.js"
REPROJ_JS = STATIC / "inline_analysis_3d_reprojection.js"


def _src(p: Path) -> str:
    assert p.is_file(), f"missing {p}"
    return p.read_text()


def test_card_close_handler_sends_only_if_idle_true():
    s = _src(JS)
    # Two separate listeners are wired on btn-close-inline-analysis-3d (one
    # hides the card / calls _iaBack, one does the session/stop cleanup) —
    # find the session-cleanup one specifically.
    blocks = re.findall(
        r'\$\(\s*["\']btn-close-inline-analysis-3d["\']\s*\)\?\.addEventListener\(\s*'
        r'["\']click["\']\s*,\s*\(\)\s*=>\s*{(.*?)\n  }\);',
        s, re.S,
    )
    assert blocks, "could not locate any click handler for btn-close-inline-analysis-3d"
    handler = next((b for b in blocks if "session/stop" in b), None)
    assert handler is not None, "card-close handler no longer calls session/stop"
    assert re.search(r"only_if_idle\s*:\s*true", handler), (
        "card-close handler must send only_if_idle: true — otherwise it can "
        "kill a session another tab/card is still feeding"
    )


def test_beforeunload_handler_sends_only_if_idle_true():
    s = _src(JS)
    m = re.search(
        r'window\.addEventListener\(\s*["\']beforeunload["\']\s*,\s*\(\)\s*=>\s*{(.*?)\n  }\);',
        s, re.S,
    )
    assert m, "could not locate the beforeunload handler in inline_analysis_3d.js"
    handler = m.group(1)
    assert "session/stop" in handler, "beforeunload handler no longer calls session/stop"
    assert re.search(r"only_if_idle\s*:\s*true", handler), (
        "beforeunload handler must send only_if_idle: true — this is the "
        "exact handler that stranded 261 of 263 queued ranges on tab close"
    )


def test_beforeunload_prefers_sendbeacon_with_a_keepalive_fetch_fallback():
    """sendBeacon can't reliably set a JSON content-type in general, but its
    Blob(type: 'application/json') form was verified (manually, against the
    real route) to parse via request.get_json(silent=True) — see the report.
    A keepalive fetch fallback covers browsers/paths without sendBeacon."""
    s = _src(JS)
    m = re.search(
        r'window\.addEventListener\(\s*["\']beforeunload["\']\s*,\s*\(\)\s*=>\s*{(.*?)\n  }\);',
        s, re.S,
    )
    assert m
    handler = m.group(1)
    assert "sendBeacon" in handler
    assert re.search(r'type:\s*["\']application/json["\']', handler), (
        "sendBeacon's Blob must be typed application/json for the server to "
        "parse it via request.get_json(silent=True)"
    )
    assert "keepalive" in handler, "must fall back to a keepalive fetch"


def test_reprojection_card_still_sends_no_stop_at_all():
    """The reprojection card's beforeunload must remain a deliberate no-op —
    it shares the snap_key with the original card and must never race it."""
    s = _src(REPROJ_JS)
    m = re.search(
        r'window\.addEventListener\(\s*["\']beforeunload["\']\s*,\s*\(\)\s*=>\s*{(.*?)\n  }\);',
        s, re.S,
    )
    assert m, "could not locate the reprojection card's beforeunload handler"
    handler = m.group(1)
    assert "session/stop" not in handler, (
        "the reprojection card's beforeunload must remain a no-op — it must "
        "never send session/stop"
    )
    assert "No-op" in handler or "no-op" in handler.lower()

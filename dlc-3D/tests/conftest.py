import atexit
import shutil
import sys
import tempfile
from pathlib import Path

# Add src/ so tests can import config, viewer, dlc_3d_bp.*
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ── Aggressive tmp cleanup (DON'T REMOVE — prevents catastrophic disk fill) ────
# Mirrors the guard in the parent webapp (../../deeplabcut-webapp-docker). Repeated
# /interrupted e2e runs can otherwise accumulate pytest tmp dirs (the parent leaked
# 614 GB). The pytest.ini retention settings bound steady-state; this hook wipes the
# session basetemp on exit (even on failure) so multi-run accumulation can't grow.
_SESSION_TMP = tempfile.mkdtemp(prefix="dlc3d_test_session_")
atexit.register(shutil.rmtree, _SESSION_TMP, True)  # guard against ctrl-C / crash


def pytest_sessionfinish(session, exitstatus):
    """Remove this session's pytest tmp basetemp on exit (runs even on failure).

    To inspect a single failing test's tmp_path artefacts, comment this out and
    re-run that test in isolation — do not let multi-session runs accumulate.
    """
    try:
        factory = getattr(session.config, "_tmp_path_factory", None)
        if factory is None:
            return
        root = factory.getbasetemp()
        if root and "pytest-" in str(root) and Path(root).exists():
            shutil.rmtree(str(root), ignore_errors=True)
    except Exception as exc:  # never fail the run because of cleanup
        print(f"[conftest cleanup] could not remove pytest basetemp: {exc}")

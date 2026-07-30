"""The main webapp carries a verbatim copy of two peak functions.

The repositories build separate containers, so a shared import would need a
cross-repo bind mount. The copy is deliberate; this test is what stops it
drifting into two subtly different implementations of one measured pipeline.
"""
import ast
import textwrap
from pathlib import Path

import pytest

_MAIN = Path(__file__).resolve().parents[3] / \
    "deeplabcut-webapp-docker/src/dlc/peaks_emit.py"
_OURS = Path(__file__).resolve().parents[1] / "src/dlc_3d_bp/peaks.py"


def _source_of(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return textwrap.dedent(ast.get_source_segment(path.read_text(), node))
    raise AssertionError(f"{name} not found in {path}")


@pytest.mark.skipif(not _MAIN.is_file(),
                    reason="main webapp checkout not present beside this repo")
@pytest.mark.parametrize("name", ["extract_peaks", "heatmap_to_image"])
def test_the_copied_functions_are_identical(name):
    assert _source_of(_MAIN, name) == _source_of(_OURS, name), (
        f"{name} has drifted between dlc_3d_bp/peaks.py and dlc/peaks_emit.py. "
        "These are one measured pipeline in two files — change both.")


@pytest.mark.skipif(not _MAIN.is_file(), reason="main webapp checkout not present")
def test_the_five_measured_constants_survived_the_port():
    src = _MAIN.read_text()
    for want in ("0.485", "0.456", "0.406", "0.229", "0.224", "0.225",
                 "_STRIDE = 2.0", "7.2801",
                 'out["bodypart"]["heatmap"]', 'out["bodypart"]["locref"]'):
        assert want in src, f"{want} missing — the verified pipeline was altered"


@pytest.mark.skipif(not _MAIN.is_file(), reason="main webapp checkout not present")
def test_the_emitter_does_not_resize_the_frame():
    """Resizing to 448x448 produced 427 px median error. It must not reappear."""
    assert "cv2.resize" not in _MAIN.read_text()


@pytest.mark.skipif(not _MAIN.is_file(), reason="main webapp checkout not present")
def test_the_sidecar_path_rule_matches_on_both_sides():
    assert '"_peaks.npz"' in _MAIN.read_text()
    assert '"_peaks.npz"' in _OURS.parent.joinpath("peaks_io.py").read_text()

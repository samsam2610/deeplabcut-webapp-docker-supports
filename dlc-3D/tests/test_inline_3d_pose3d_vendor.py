"""Vendor guard for the locally-hosted three.js (r0.160.0) used by the 3D pose viewer.

See docs/superpowers/specs/2026-07-21-inline-3d-pose-viewer-threejs-spike-design.md.
The module is offline/self-hosted (no runtime CDN), so three.js is vendored under
src/static/vendor/three/. OrbitControls' bare `from 'three'` specifier is rewritten
to the relative `./three.module.js` so it resolves without a bundler / import map.
"""
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "src" / "static" / "vendor" / "three"


def test_three_module_present_and_nontrivial():
    f = VENDOR / "three.module.js"
    assert f.is_file(), "vendored three.module.js must exist"
    # Full r0.160.0 build is ~1.2MB; guard against an HTML error page / stub.
    assert f.stat().st_size > 500_000, "three.module.js looks too small to be the real build"
    head = f.read_text(errors="ignore")[:200]
    assert "<!DOCTYPE" not in head and "<html" not in head.lower(), \
        "three.module.js must be JS, not an HTML error page"


def test_orbitcontrols_present_and_nontrivial():
    f = VENDOR / "OrbitControls.js"
    assert f.is_file(), "vendored OrbitControls.js must exist"
    assert f.stat().st_size > 5_000, "OrbitControls.js looks too small"
    head = f.read_text(errors="ignore")[:200]
    assert "<!DOCTYPE" not in head, "OrbitControls.js must be JS, not an HTML error page"


def test_orbitcontrols_imports_relative_not_bare():
    text = (VENDOR / "OrbitControls.js").read_text()
    assert "from './three.module.js'" in text, \
        "OrbitControls must import from the relative './three.module.js'"
    # The only allowed mention of the bare specifier is the header comment noting
    # the edit; there must be no live `import ... from 'three'` statement.
    assert "} from 'three'" not in text, \
        "OrbitControls must NOT import from the bare 'three' specifier"


def test_version_note_present():
    f = VENDOR / "VERSION"
    assert f.is_file(), "vendor/three/VERSION provenance note must exist"
    assert "three@0.160.0" in f.read_text(), "VERSION must pin three@0.160.0"

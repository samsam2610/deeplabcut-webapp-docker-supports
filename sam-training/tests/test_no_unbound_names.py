"""No function may reference a local name it never binds.

Shipped 2026-08-12: switching `stereo.find_for_project(_project())` to
`stereo.find_for_video(_project(), video)` was applied to every call site by
text replacement, but `api_pellet_retrain` has no `video` in scope. Python
compiles that happily; it raises NameError only when a user presses "Re-aim box
from clicks", on a route with no test.

`python -c "import src.app"` does not catch it — the module imports fine. This
walks the symbol table instead, which is the same net the .mjs suite has for
const reassignment, and for the same reason: the failure is at call time, not
import time.
"""
import builtins
import symtable
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
BUILTINS = set(dir(builtins))


def _unbound(table, path, out):
    """Names a scope reads but never binds, and that are not module-level."""
    for child in table.get_children():
        if child.get_type() == "function":
            for sym in child.get_symbols():
                name = sym.get_name()
                if not sym.is_referenced():
                    continue
                # NOT is_global(): Python marks an unassigned name as
                # GLOBAL_IMPLICIT, which is exactly the case being hunted. The
                # module-level filter below is what separates a real global
                # from a typo. Excluding is_global() here made this test pass
                # on the very bug it was written for.
                if (sym.is_assigned() or sym.is_parameter()
                        or sym.is_free() or sym.is_imported()):
                    continue
                if name in BUILTINS:
                    continue
                out.append(f"{path.name}:{child.get_name()}: {name}")
        _unbound(child, path, out)


@pytest.mark.parametrize("path", sorted(SRC.glob("*.py")), ids=lambda p: p.name)
def test_no_function_reads_a_name_it_never_binds(path):
    table = symtable.symtable(path.read_text(), path.name, "exec")
    module_level = {s.get_name() for s in table.get_symbols()}
    found = []
    _unbound(table, path, found)
    # A module-level name read inside a function is legal and normal.
    found = [f for f in found if f.rsplit(": ", 1)[1] not in module_level]
    assert found == [], "unbound local reads: " + "; ".join(found)

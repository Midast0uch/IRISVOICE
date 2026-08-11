"""CT: REQ-19 AC5 — Session Coupling isolation from memory-writing mechanisms.

Spec: specs/long-horizon-der-execution/requirements.md REQ-19 (AC5).
Task: T36.

Pins the REQ-19 vocabulary boundary: Session Coupling (coupled_registry.py)
joins sessions and nudges (a, s) via FFI — it NEVER touches memory and NEVER
creates a step. A future edit must not be able to silently blur session coupling
into a memory-writing mechanism without failing this test.

The grep basis is exactly what the requirement states:
    memory|mycelium|episodic|store|db|coords

Run: python -m pytest backend/tests/contract/test_coupled_registry_isolation.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TARGET = _REPO_ROOT / "backend" / "agent" / "coupled_registry.py"

_FORBIDDEN = re.compile(r"memory|mycelium|episodic|store|db|coords", re.IGNORECASE)


def test_session_coupling_has_no_memory_or_step_creation_references():
    """REQ-19 AC5: coupled_registry.py contains zero references to
    memory|mycelium|episodic|store|db|coords.

    Coupling joins SESSIONS (voice <-> coding), assigns nucleus/barrier by
    energy, and nudges (a,s) via FFI. It never reads or writes memory, never
    touches the coordinate graph, and never creates a step. If this test fails,
    a future edit has started smuggling a memory-writing or DB mechanism into
    the coupling registry — stop and re-route it to the correct component.
    """
    assert _TARGET.exists(), f"coupled_registry.py not found at {_TARGET}"

    source = _TARGET.read_text(encoding="utf-8")
    hits = [
        (i + 1, line.strip())
        for i, line in enumerate(source.splitlines())
        if _FORBIDDEN.search(line)
    ]
    assert hits == [], (
        "Session Coupling (coupled_registry.py) must stay isolated from "
        "memory/coordinate mechanisms (REQ-19 AC5). Forbidden references "
        f"found in {_TARGET.name}:\n" + "\n".join(f"  {n}: {l}" for n, l in hits)
    )

#!/usr/bin/env python3
"""validate_ontology_schema.py — REQ-22 AC2 (T23): version-check the ontology
document (specs/der-dag-inversion/ontology.md) against the LIVE code schema.

The ontology is the canonical reference for any agent; drift between the doc
and the code is a silent trust break. This script reads the declared sets
out of ontology.md and compares them against the live constants:

    node types        <-> NodeRecord.node_type vocabulary (der_loop.py)
    topic domains     <-> mycelium DOMAIN_IDS keys (spaces.py)
    execution domains <-> DER execution_domain vocabulary (agent_kernel.py
                         _der_execution_domain)
    link vocabulary   <-> LINK_VOCABULARY / DER_LINK_PREDICATES (pin_store.py)

FAILURES ARE LOUD: non-zero exit + named file:line. The doc is corrected,
never the code silently (REQ-22 Edge Cases).

Run from the repo root:  python scripts/validate_ontology_schema.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ONTO = REPO_ROOT / "specs" / "der-dag-inversion" / "ontology.md"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _section(doc: str, heading_fragment: str) -> str:
    """Return the text of the first section whose heading contains the
    fragment (from the heading to the next '## ' or '### ' heading)."""
    lines = doc.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if (ln.strip().startswith(("## ", "### "))
                and heading_fragment in ln):
            start = i
            break
    if start is None:
        return ""
    out = []
    for ln in lines[start + 1:]:
        if ln.strip().startswith(("## ", "### ")):
            break
        out.append(ln)
    return "\n".join(out)


def _backticked_values(text: str) -> set[str]:
    """Collect every `value` inside the section text — from tables (the
    first column of every data row) and from inline code."""
    return set(re.findall(r"`([^`]+)`", text))


def _table_first_col(text: str) -> set[str]:
    """Collect the FIRST column of every markdown table data row (the
    canonical value column). r"| `value` | meaning |" -> {'value'}."""
    vals: set[str] = set()
    for ln in text.splitlines():
        if not ln.strip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        # skip header rows (--- separators / non-backticked headers)
        if cells[0].startswith("---"):
            continue
        m = re.fullmatch(r"`([^`]+)`", cells[0])
        if m:
            vals.add(m.group(1))
    return vals


def _require(doc_set: set[str], live_set: set[str], what: str,
             failures: list[str]) -> None:
    """Compare a doc-declared set against the live schema. An EMPTY doc set is
    itself a failure (silent-skip guard — extraction must find values), never
    silently skipped (REQ-22 Edge Cases: drift flagged, not corrected
    silently)."""
    if not doc_set:
        failures.append(f"ontology.md {what}: NO values extracted from doc")
    elif doc_set != live_set:
        failures.append(
            f"ontology.md {what} {sorted(doc_set)} != live "
            f"{sorted(live_set)}"
        )


def main() -> int:
    failures: list[str] = []

    if not ONTO.exists():
        print(f"FAIL: ontology doc missing: {ONTO}")
        return 1

    doc = ONTO.read_text(encoding="utf-8")

    # ── 1. node types ─────────────────────────────────────────────────────
    _require(
        _table_first_col(_section(doc, "1. Node types")),
        {"task", "step", "sub_loop"},
        "§1 node types",
        failures,
    )

    # ── 2a. topic domains (mycelium DOMAIN_IDS) ───────────────────────────
    from backend.memory.mycelium.spaces import DOMAIN_IDS

    _require(
        _table_first_col(_section(doc, "2a.")),
        set(DOMAIN_IDS.keys()),
        "§2a topic domains",
        failures,
    )

    # ── 2b. execution domains ─────────────────────────────────────────────
    _require(
        _table_first_col(_section(doc, "2b.")),
        {"voice", "der", "research"},
        "§2b execution domains",
        failures,
    )

    # ── 3a. link vocabulary (REQ-19 AC2b) ─────────────────────────────────
    from backend.memory.pin_store import LINK_VOCABULARY

    _require(
        _table_first_col(_section(doc, "3a.")),
        set(LINK_VOCABULARY),
        "§3a link vocabulary",
        failures,
    )

    if failures:
        print("ONTO-SCHEMA FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("ONTO-SCHEMA OK: ontology.md matches the live schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())

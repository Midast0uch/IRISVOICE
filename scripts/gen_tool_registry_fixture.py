#!/usr/bin/env python3
"""
Generate the frontend fixture snapshot of `backend/agent/tool_registry.py`.

REQ-14 (T8a) — the verb registry (`lib/cards/verbRegistry.ts`) is TypeScript
and cannot import a Python module, so the CT-6 guard test
(`__tests__/cards/verbRegistry.test.ts`) reads a checked-in JSON fixture
instead of the live registry.

KNOWN SEAM: this fixture is a SNAPSHOT, not a live read. If a tool is added,
renamed or removed in `tool_registry.py` and nobody re-runs this script, the
frontend test keeps testing the OLD tool list — it will not fail on drift by
itself. Re-run this script (and re-run the jest suite) whenever
`tool_registry.py` changes tool names. This is the tradeoff called out in the
T8a task brief: "If you cannot read the Python list from a TS test, generate
the fixture and note that keeping it in sync is a known seam."

Usage:
    python scripts/gen_tool_registry_fixture.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_PATH = ROOT / "__tests__" / "cards" / "__fixtures__" / "tool_registry_snapshot.json"


def main() -> None:
    from backend.agent import tool_registry as tr

    specs = tr.get_all_specs()
    tools = sorted(
        (
            {
                "name": s.name,
                "category": s.category,
                "aliases": list(s.aliases),
            }
            for s in specs
        ),
        key=lambda d: d["name"],
    )
    payload = {
        "_generated_by": "scripts/gen_tool_registry_fixture.py",
        "_source": "backend/agent/tool_registry.py:get_all_specs()",
        "_note": (
            "Snapshot, not live. Re-run this script after any tool_registry.py "
            "change. See CT-6 (specs/task-card-v2-liquid-ink) for why this "
            "fixture exists."
        ),
        "tool_count": len(tools),
        "tools": tools,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(tools)} tools to {OUT_PATH}")


if __name__ == "__main__":
    main()

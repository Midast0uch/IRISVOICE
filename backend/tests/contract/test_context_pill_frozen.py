"""Contract test CT-I2: ContextPill props and design unchanged this phase.

design.md Ripple-Effect Map: `components/chat/ContextPill.tsx` is a CONTRACT
LOCK for Phase 2 — props and design unchanged; Phase 5 owns it. Its
denominator shifts as a *behavioral* consequence of Phase 1 REQ-2 (expected),
but the component's own prop surface must not move as a side effect of
Phase 2's card/narration work.

Pinned by reading the real source file (the effect: what the shipped
component actually declares), not by re-deriving what it "should" declare.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONTEXT_PILL_PATH = ROOT / "components" / "chat" / "ContextPill.tsx"

EXPECTED_PROPS = {"usedTokens", "maxTokens", "phase", "currentAction"}


def _read_props() -> set[str]:
    src = CONTEXT_PILL_PATH.read_text(encoding="utf-8")
    m = re.search(r"export interface ContextPillProps \{(.*?)\}", src, re.DOTALL)
    assert m is not None, "ContextPillProps interface not found in ContextPill.tsx"
    body = m.group(1)
    # Field lines look like `usedTokens: number` or `currentAction?: string`.
    return set(re.findall(r"^\s*(\w+)\??:\s*\w", body, re.MULTILINE))


class TestContextPillFrozen:
    def test_props_are_exactly_the_frozen_set(self):
        found = _read_props()
        assert found == EXPECTED_PROPS, (
            f"ContextPillProps changed this phase: found={found} expected={EXPECTED_PROPS} "
            f"— Phase 2 is a CONTRACT LOCK on this component (Phase 5 owns changes)."
        )

    def test_default_export_still_destructures_the_frozen_props(self):
        """The interface alone can drift from what the component body actually
        reads — pin the destructuring signature too, so a partial prop-plumb
        change (declared but unused, or used but undeclared) is caught."""
        src = CONTEXT_PILL_PATH.read_text(encoding="utf-8")
        m = re.search(r"export default function ContextPill\(\{(.*?)\}: ContextPillProps\)",
                      src, re.DOTALL)
        assert m is not None, "ContextPill default export signature not found"
        destructured = set(re.findall(r"(\w+)", m.group(1)))
        assert EXPECTED_PROPS.issubset(destructured), (
            f"component body no longer destructures all frozen props: {destructured}"
        )

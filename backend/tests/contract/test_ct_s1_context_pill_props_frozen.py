"""Contract test CT-S1 (specs/phase-5-switcher/design.md).

"`ContextPillProps`: Four props, same names and types (REQ-3 AC1)."

Phase 5 REQ-3 AC1: "THE SYSTEM SHALL keep `ContextPillProps` unchanged — the
switcher SHALL be a **sibling** component, not a new prop." This phase is the
one that ADDS the sibling (`ModelSwitcher`) beside the pill, so it is the
phase most likely to be tempted to thread a `switcher`/`activeModel`-style
prop into `ContextPillProps` instead. This test is Phase 5's own pin,
distinct from Phase 2's CT-I2 (`test_context_pill_frozen.py`, which locked the
same fact against Phase 2's card/narration work) — same technique, so a
regression is caught regardless of which phase's changes caused it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONTEXT_PILL_PATH = ROOT / "components" / "chat" / "ContextPill.tsx"

FROZEN_PROPS = {"usedTokens", "maxTokens", "phase", "currentAction"}


def _read_props() -> set[str]:
    src = CONTEXT_PILL_PATH.read_text(encoding="utf-8")
    m = re.search(r"export interface ContextPillProps \{(.*?)\}", src, re.DOTALL)
    assert m is not None, "ContextPillProps interface not found in ContextPill.tsx"
    return set(re.findall(r"^\s*(\w+)\??:\s*\w", m.group(1), re.MULTILINE))


class TestCTS1ContextPillPropsFrozen:
    def test_exactly_four_frozen_props_no_switcher_prop_added(self):
        found = _read_props()
        assert found == FROZEN_PROPS, (
            f"ContextPillProps changed in Phase 5: found={found} "
            f"expected={FROZEN_PROPS} — the model switcher must be a SIBLING "
            f"component (D-2), never a new ContextPill prop (REQ-3 AC1, "
            f"Decision Locked #1)."
        )

    def test_no_model_or_switcher_named_prop_leaked_in(self):
        """Belt-and-suspenders: even if someone renamed a frozen prop to
        something that happens to still total four fields, explicitly reject
        any switcher/model-shaped name."""
        found = _read_props()
        forbidden_substrings = ("model", "switch", "provider", "binding")
        for prop in found:
            lowered = prop.lower()
            assert not any(bad in lowered for bad in forbidden_substrings), (
                f"ContextPillProps gained a switcher-shaped prop: {prop!r}"
            )

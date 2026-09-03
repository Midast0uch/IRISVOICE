"""Contract tests: long-running tool narration (blueprint-pure).

Verifies the narration heartbeat is a TOOL CAPABILITY (ToolSpec.long_running),
not a web-mode override (docs/architecture/der-coupled-action-cycle-blueprint.md:
"no mode-driven fan-out, no web-regex override"). The DER operator's tool layer
(execute_tool) wraps long_running tools with backend/agent/narration.run_with_narration,
which speaks periodic low-priority progress through the SpeakTool.

pin_9e97e21340e7.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.agent.narration import run_with_narration
from backend.agent.tool_registry import ToolSpec


@pytest.fixture(autouse=True)
def _reset_narration_gate():
    """Isolate the PROCESS-WIDE narration gate between tests.

    ``may_narrate()`` allows at most one utterance per
    ``_NARRATION_GATE_INTERVAL`` (18s), tracked in a module-level global, so the
    first narration test in a session consumes it and later ones see silence.
    Resets state only — the load each test drives is unchanged.
    """
    import backend.agent.narration as _narration

    _narration._narration_gate_last = 0.0
    yield
    _narration._narration_gate_last = 0.0


class TestLongRunningCapability:
    def test_crawler_query_is_long_running(self):
        """crawler_query must carry the long_running capability so execute_tool
        wraps it with the narration heartbeat — not a hardcoded web check."""
        spec = ToolSpec(
            name="crawler_query",
            description="Deep web research",
            executor="crawler",
            requires_internet=True,
            long_running=True,
        )
        assert spec.long_running is True

    def test_default_tools_are_not_long_running(self):
        spec = ToolSpec(name="read_file", description="Read a file", executor="internal")
        assert spec.long_running is False


class TestNarrationHeartbeat:
    def test_speaks_periodic_low_priority_while_running(self):
        spoken = []

        def fake_speak(text, priority):
            spoken.append((text, priority))

        async def slow_tool():
            await asyncio.sleep(0.35)
            return {"ok": True}

        async def main():
            return await run_with_narration(
                lambda: slow_tool(), fake_speak, "crawler_query", interval_s=0.1
            )

        result = asyncio.run(main())
        assert result == {"ok": True}
        # At least one heartbeat fired while the tool ran.
        assert len(spoken) >= 1
        # All heartbeats are low priority (never interrupt the final answer).
        assert all(p == "low" for _, p in spoken)
        # Generic message, not a web-specific hardcoded string.
        #
        # REQ-7 AC7 / T4.1: this previously asserted `"Still" in t`, i.e. the
        # literal "Still researching the web." that narration.py T37 removed —
        # a string which was itself web-specific, contradicting this very
        # comment. The contract is now stated positively AND negatively: the
        # heartbeat speaks the generic per-tool verb, and the superseded
        # wording must never come back. Load and scale are unchanged.
        assert all(t.strip() for t, _ in spoken), "heartbeat spoke an empty string"
        assert all("reading" in t for t, _ in spoken), (
            f"crawler_query heartbeat should speak the generic verb; got {spoken}"
        )
        assert not any("Still" in t or "researching" in t for t, _ in spoken), (
            f"superseded 'Still researching' wording is back: {spoken}"
        )

    def test_returns_tool_result(self):
        spoken = []

        def fake_speak(text, priority):
            spoken.append(text)

        async def tool():
            return "done"

        async def main():
            return await run_with_narration(
                lambda: tool(), fake_speak, "web_search", interval_s=0.05
            )

        assert asyncio.run(main()) == "done"

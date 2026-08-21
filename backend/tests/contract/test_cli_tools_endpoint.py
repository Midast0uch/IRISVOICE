"""Contract test: GET /api/dev/cli-tools surfaces the existing CLI registry (REQ-20 AC5).

Tested by calling the endpoint coroutine directly (bypassing TestClient's
lifespan, which hangs in this environment). The dev-mode dependency is not
exercised here — that gate is covered by require_developer_mode's own tests.

The endpoint must expose backend/dev/cli_tools.yaml (display_name +
when_to_use) to the UI — never a second hardcoded copy. A tool whose command
is not on PATH renders as available=false with a reason, never hidden
(REQ-20 edge case).
"""
import asyncio


def test_cli_tools_endpoint_surfaces_registry():
    from backend.main import get_cli_tools

    result = asyncio.run(get_cli_tools())
    assert "tools" in result
    tools = result["tools"]
    assert len(tools) >= 1
    names = {t["name"] for t in tools}
    assert "kilo_code" in names
    for t in tools:
        # REQ-20 AC5: when_to_use surfaced from cli_tools.yaml, not hardcoded
        assert "when_to_use" in t and t["when_to_use"].strip()
        assert "display_name" in t and t["display_name"]
        assert "available" in t and isinstance(t["available"], bool)
        # unavailable tools carry a reason, never hidden (REQ-20 edge case)
        if not t["available"]:
            assert t["reason"]

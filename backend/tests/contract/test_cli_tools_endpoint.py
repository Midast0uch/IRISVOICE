"""Contract test: GET /api/dev/cli-tools surfaces IRIS's own dev command surface (REQ-0 AC4).

Test updated 2026-08-25 for REQ-0 (D7): the external CLI registry
(backend/dev/cli_tools.yaml, kilo_code/claude_code/opencode) was DELETED and
the endpoint repointed at IRIS's own command surface. The previous version of
this test asserted "kilo_code" in names — that encoded the removed behavior.

The response SHAPE contract is unchanged: {tools: [{name, display_name,
when_to_use, available, reason}]}, one entry per command, descriptions
non-empty. The endpoint remains the single source of truth the slash menu
reads — never a second hardcoded copy in the frontend.
"""
import asyncio

# REQ-7 AC1 initial surface — must match backend.main.IRIS_DEV_COMMANDS exactly.
EXPECTED_COMMANDS = {"run", "help", "review", "debt", "term", "clear"}


def test_cli_tools_endpoint_surfaces_iris_command_surface():
    from backend.main import get_cli_tools

    result = asyncio.run(get_cli_tools())
    assert "tools" in result
    tools = result["tools"]
    assert len(tools) >= 1
    names = {t["name"] for t in tools}
    # REQ-0 AC4: IRIS's own command surface, not an external CLI registry
    assert names == EXPECTED_COMMANDS
    assert "kilo_code" not in names
    for t in tools:
        assert "when_to_use" in t and t["when_to_use"].strip()
        assert "display_name" in t and t["display_name"]
        assert "available" in t and isinstance(t["available"], bool)
        # built-in commands are always available; no PATH dependency
        assert t["available"] is True

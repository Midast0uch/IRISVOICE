"""Regression (execution audit B2, 2026-09-29): the call that writes tool
arguments must not be capped at 500 output tokens.

For write_file the arguments ARE the file body, so max_tokens=500 made any
file over ~1,500 characters impossible to write. The router's default cap
(4096) still bounds a runaway generation. Fails on the old call site.
"""

import json
from types import SimpleNamespace

from backend.agent.tool_decision import ToolDecisionBox


class _RecordingRouter:
    def __init__(self):
        self.calls = []

    def generate(self, role, messages, **kwargs):
        self.calls.append(kwargs)
        call = {"function": {"name": "write_file",
                             "arguments": json.dumps({"path": "a.py", "content": "x"})}}
        return "", None, [call]


def test_argument_call_is_not_capped_below_router_default():
    router = _RecordingRouter()
    box = ToolDecisionBox(
        router=router,
        tool_bridge=SimpleNamespace(),
        get_available_tools=lambda: [
            {"name": "write_file", "description": "Write a file", "category": "file",
             "parameters": {"path": {"type": "string"}, "content": {"type": "string"}}},
        ],
        validate_tool_call=lambda t, p: (True, None),
    )
    box._resolve_legacy({"description": "write the module a.py"})
    assert router.calls, "the resolver never called the router"
    for kwargs in router.calls:
        cap = kwargs.get("max_tokens")
        assert cap is None or cap >= 4096, f"tool-argument call capped at {cap}"

"""
Tests for Phase 4 concurrent step execution helpers in agent_kernel.
Run: python -m pytest backend/tests/test_der_concurrent.py -v
"""

import asyncio
import unittest
from unittest.mock import MagicMock

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import QueueItem


class _FakeKernel(AgentKernel):
    """Minimal AgentKernel subclass that skips the heavy __init__ and only
    exposes the attributes the exec helpers touch."""

    def __init__(self):
        self._bridge = MagicMock()
        self.captured = []
        self.adapter = MagicMock()
        # The TOOL path calls _get_tool_box(), which constructs
        # ToolDecisionBox(router=self._router, ...). The real __init__ sets
        # self._router = InferenceRouter(...); this fixture skips it, so it
        # must supply the attribute or every tool-path test dies with
        # "object has no attribute '_router'" before the tool call is sent.
        self._router = MagicMock()
        # _resolve_legacy unpacks `text, thinking, tool_calls` straight out of
        # router.generate() (tool_decision.py:1640). A bare MagicMock returns a
        # MagicMock, which raises "not enough values to unpack (expected 3,
        # got 0)". Configure the 3-tuple: non-empty text with no tool_calls is
        # the "model replied without naming a tool" shape, which becomes
        # DecisionKind.REASON -> the step runs direct (no tool).
        self._router.generate.return_value = ("no tool needed", "", [])
        # The exec helpers also read self.conversation_id directly (resolve()
        # and dispatch() both take it; the web-content repeat guard keys on it).
        # The real __init__ sets `conversation_id or session_id`; sibling DER
        # fixtures use "test-conv".
        self.conversation_id = "test-conv"

    @property
    def _tool_bridge(self):
        return self._bridge

    def mark_external_tool(self, tool):
        pass

    def _capture_tool_result(self, *a, **k):
        self.captured.append(a)

    def _run_step_direct(self, item, ctx, session):
        return f"direct:{item.step_number}"


def test_der_run_step_execution_serial_tool():
    fake = _FakeKernel()

    async def _fake_exec(tool_name=None, params=None, session_id=None, plan_title=None,
                         decision_meta=None, _skip_resilience=False):
        # Real execute_tool returns a Dict (tool_bridge.py:1398) and
        # ToolDecisionBox.dispatch rejects a non-dict as "Unexpected tool
        # result type". Return the production shape; the assertion below
        # (the result reaches step_result) is unchanged.
        return {"success": True, "result": f"serial-result-{tool_name}"}

    fake._bridge.execute_tool = _fake_exec

    item = QueueItem(step_id="s1", step_number=1, description="a", tool="search")
    step_result, step_success = AgentKernel._der_run_step_execution(
        fake, item, None, "sess", "t", None
    )
    assert step_result == "serial-result-search"
    assert step_success is True


def test_der_run_step_execution_toolless_step_answers_through_node():
    """A step with no tool runs as a node in EVERY mode (owner 2026-10-03,
    V10). Its model answers without a tool call, so the step succeeds with
    that answer. (Was test_der_run_step_execution_direct_fallback: it pinned
    the retired one-tool decision path - REASON -> _run_step_direct - and
    passed only while data/iris_config.json said "personal".)"""
    fake = _FakeKernel()
    item = QueueItem(step_id="s1", step_number=1, description="a")  # no tool
    step_result, step_success = AgentKernel._der_run_step_execution(
        fake, item, None, "sess", "t", None
    )
    assert step_result == "no tool needed"
    assert step_success is True


def test_der_run_step_execution_tool_error_is_caught():
    fake = _FakeKernel()

    async def _boom(tool_name=None, params=None, session_id=None, plan_title=None,
                    decision_meta=None, _skip_resilience=False):
        raise RuntimeError("tool exploded")

    fake._bridge.execute_tool = _boom

    item = QueueItem(step_id="s1", step_number=1, description="a", tool="search")
    step_result, step_success = AgentKernel._der_run_step_execution(
        fake, item, None, "sess", "t", None
    )
    assert step_success is False
    assert "[STEP ERROR" in step_result


# ── Phase 4b: tool-result refinement (_format_tool_result) ────────────────────
def test_format_tool_result_passthrough_strings():
    assert AgentKernel._format_tool_result("plain text") == "plain text"
    assert AgentKernel._format_tool_result(None) == ""
    assert AgentKernel._format_tool_result(42) == "42"


def test_format_tool_result_extracts_content_key():
    # Success dict with a content key -> return that string (not the wrapper)
    assert (
        AgentKernel._format_tool_result(
            {"success": True, "result": "the answer"}
        )
        == "the answer"
    )
    assert (
        AgentKernel._format_tool_result(
            {"success": True, "results": "bulk results"}
        )
        == "bulk results"
    )


def test_format_tool_result_surfaces_errors():
    out = AgentKernel._format_tool_result(
        {"success": False, "error": "boom happened"}
    )
    assert "boom happened" in out


def test_format_tool_result_json_fallback_for_unknown_dict():
    # Dict with no recognized content key -> compact JSON (valid, not repr)
    out = AgentKernel._format_tool_result({"success": True, "foo": [1, 2]})
    assert '"foo"' in out  # json.dumps, not Python repr
    assert "'foo'" not in out


def test_format_tool_result_summarizes_document_envelope():
    # get_rendered_documents envelope (no content key) must render human
    # text, never the raw payload (live 2026-09-09 card leak).
    out = AgentKernel._format_tool_result(
        {
            "success": True,
            "conversation_id": "conv-96",
            "documents": [
                {"document_id": "a", "title": "Piper"},
                {"document_id": "b", "title": "Coqui TTS"},
            ],
        }
    )
    assert out == "2 document(s) retrieved: Piper, Coqui TTS"
    assert "conversation_id" not in out
    out_empty = AgentKernel._format_tool_result(
        {"success": True, "conversation_id": "c", "documents": []}
    )
    assert out_empty == "0 document(s) retrieved"


def test_format_tool_result_non_string_value_jsonified():
    # A content key holding structured data -> jsonified, not str(repr)
    out = AgentKernel._format_tool_result(
        {"success": True, "data": {"a": 1}}
    )
    assert out == '{"a": 1}'


def test_der_run_step_execution_applies_formatting():
    """The exec helper must route raw tool output through _format_tool_result."""
    fake = _FakeKernel()

    async def _fake_exec(tool_name=None, params=None, session_id=None, plan_title=None,
                         decision_meta=None, _skip_resilience=False):
        return {"success": True, "result": "cleaned output"}

    fake._bridge.execute_tool = _fake_exec

    item = QueueItem(step_id="s1", step_number=1, description="a", tool="search")
    step_result, step_success = AgentKernel._der_run_step_execution(
        fake, item, None, "sess", "t", None
    )
    assert step_result == "cleaned output"
    assert step_success is True


def test_caducean_modulate_temperature_compress_lowers():
    # COMPRESS (rec==1) -> temperature halved, floored at 0.0
    with _monkeypatch_recommend(1):
        assert AgentKernel._caducean_modulate_temperature(0.3, "s") == 0.15


def test_caducean_modulate_temperature_expand_raises_capped():
    # EXPAND (rec==0) -> *1.2, capped at 0.6
    with _monkeypatch_recommend(0):
        assert AgentKernel._caducean_modulate_temperature(0.3, "s") == 0.36
    with _monkeypatch_recommend(0):
        # base high enough that *1.2 would exceed cap -> clamped to 0.6
        assert AgentKernel._caducean_modulate_temperature(0.6, "s") == 0.6


def test_caducean_modulate_temperature_maintain_unchanged():
    # MAINTAIN (rec==2) -> base unchanged
    with _monkeypatch_recommend(2):
        assert AgentKernel._caducean_modulate_temperature(0.3, "s") == 0.3


def test_caducean_modulate_temperature_error_returns_base():
    # Any error reading the recommendation -> base unchanged (never raises)
    with _monkeypatch_recommend_raise(RuntimeError("no caducean")):
        assert AgentKernel._caducean_modulate_temperature(0.3, "s") == 0.3


class _MonkeyPatcher:
    def __init__(self, value=None, exc=None):
        self._value = value
        self._exc = exc
        self._patcher = None

    def __enter__(self):
        import backend.gateway.iris_ffi as _ffi

        def _fake(session_id):
            if self._exc is not None:
                raise self._exc
            return self._value

        self._patcher = unittest.mock.patch.object(
            _ffi, "ffi_caducean_recommend", _fake
        )
        self._patcher.start()
        return self

    def __exit__(self, *a):
        if self._patcher is not None:
            self._patcher.stop()


def _monkeypatch_recommend(value):
    return _MonkeyPatcher(value=value)


def _monkeypatch_recommend_raise(exc):
    return _MonkeyPatcher(exc=exc)

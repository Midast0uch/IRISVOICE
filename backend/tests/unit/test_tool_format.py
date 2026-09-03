"""
Tests for provider-agnostic tool normalization (InferenceRouter._normalize_tools).

Regression guard: tool-calling previously passed IRIS *internal* tool dicts
({name, description, parameters, category}) straight to providers, which made
Cerebras reject the call with `tools.0.type: Field required` / `tools.0.name is
unsupported` (HTTP 400) — forcing the DER synthesis step into a retry loop and
triggering REQ-10 escalation.

The fix lives ONCE in InferenceRouter.generate(): it normalizes tools to the
OpenAI function-calling schema (the de-facto standard every compatible provider
— Cerebras, OpenAI, Groq, LM Studio, Ollama, vLLM, in-process local models —
accepts).  This keeps tool-calling provider-agnostic with no per-provider
hardcoding.  The normalization is idempotent: already-OpenAI-format tools pass
through unchanged.

Run: python -m pytest backend/tests/test_tool_format.py -v
"""
import sys
import types
import importlib.util
import logging
from unittest.mock import MagicMock

import pytest

# DEBT FIX (pin_fd5b312e69bf / c01534199cdb): was module-level
# logging.disable(CRITICAL) — process-global state that killed all caplog
# assertions in every later-collected test. Now scoped to this module.
@pytest.fixture(autouse=True)
def _silence_logs():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def _load_router():
    # Put the real backend package on the path so the router's relative imports
    # (backend.agent.inference.keyring, etc.) resolve as a real package.
    import os
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    if os.path.join(_root, "backend") not in sys.path:
        sys.path.insert(0, os.path.join(_root, "backend"))
    from backend.agent.inference.router import InferenceRouter
    return InferenceRouter


@pytest.fixture
def router():
    InferenceRouter = _load_router()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(InferenceRouter, "__init__", lambda self: None)
        inst = InferenceRouter.__new__(InferenceRouter)
    return inst


def test_internal_tools_normalized_to_openai():
    r = _load_router().__new__(_load_router())
    internal = [
        {"name": "web_search", "description": "Search the web", "parameters": {"type": "object"}, "category": "web"},
        {"name": "create_file", "description": "Make a file", "parameters": {"type": "object", "properties": {}}, "category": "fs"},
    ]
    out = r._normalize_tools(internal)
    assert len(out) == 2
    for entry in out:
        assert entry["type"] == "function"
        assert "function" in entry
        assert "name" in entry["function"]
        assert "description" in entry["function"]
        assert "parameters" in entry["function"]


def test_already_openai_tools_pass_through_idempotent():
    r = _load_router().__new__(_load_router())
    openai_tools = [
        {"type": "function", "function": {"name": "x", "description": "d", "parameters": {"type": "object"}}}
    ]
    out = r._normalize_tools(openai_tools)
    assert out == openai_tools  # unchanged


def test_empty_and_none_return_none():
    r = _load_router().__new__(_load_router())
    assert r._normalize_tools([]) is None
    assert r._normalize_tools(None) is None


def test_missing_parameters_gets_default_object():
    r = _load_router().__new__(_load_router())
    internal = [{"name": "x", "description": "d"}]  # no parameters key
    out = r._normalize_tools(internal)
    assert out[0]["function"]["parameters"] == {"type": "object", "properties": {}}

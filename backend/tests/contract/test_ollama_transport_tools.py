"""Execution audit B1 (2026-09-29): the Ollama transport carries tools.

It never sent tool definitions, dropped tool calls from the reply, turned a
tool-only reply into "Empty response from Ollama", and used a fixed 30 s
timeout. The Brain runs on Ollama, so it could not call a tool at all.
"""

import json
from unittest.mock import patch

from backend.agent.inference.transport import OllamaTransport

TOOLS = [{"type": "function", "function": {"name": "edit_file", "description": "d",
                                            "parameters": {"type": "object", "properties": {}}}}]


class _Resp:
    def __init__(self, body):
        self.status_code, self._body, self.text, self.headers = 200, body, json.dumps(body), {}

    def json(self):
        return self._body


class _Client:
    def __init__(self, body, **kw):
        self.body, self.sent, self.kw = body, [], kw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, headers=None):
        self.sent.append(json)
        return _Resp(self.body)


def _run(body, **kw):
    made = []

    def factory(**ckw):
        c = _Client(body, **ckw)
        made.append(c)
        return c

    with patch("httpx.Client", side_effect=factory):
        out = OllamaTransport(endpoint="http://test").generate("gemma4:31b-cloud", kw.pop("messages"), **kw)
    return out, made[0]


def test_tools_are_sent_and_tool_calls_come_back_openai_shaped():
    body = {"message": {"content": "", "tool_calls": [
        {"function": {"name": "edit_file", "arguments": {"path": "m.py", "old": "a", "new": "b"}}}]}}
    (text, _think, calls), client = _run(body, messages=[{"role": "user", "content": "fix"}], tools=TOOLS)
    assert client.sent[0]["tools"] == TOOLS
    assert text == ""
    assert calls[0]["function"]["name"] == "edit_file"
    assert json.loads(calls[0]["function"]["arguments"]) == {"path": "m.py", "old": "a", "new": "b"}


def test_history_is_converted_for_ollama():
    history = [
        {"role": "user", "content": "fix"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_0", "type": "function",
             "function": {"name": "read_file", "arguments": '{"path": "m.py"}'}}]},
        {"role": "tool", "tool_call_id": "call_0", "name": "read_file", "content": "x = 1"},
    ]
    _, client = _run({"message": {"content": "done"}}, messages=history, tools=TOOLS)
    sent = client.sent[0]["messages"]
    assert sent[1]["tool_calls"][0]["function"]["arguments"] == {"path": "m.py"}
    assert sent[2] == {"role": "tool", "content": "x = 1", "tool_name": "read_file"}


def test_timeout_is_the_callers_not_a_fixed_30s():
    _, client = _run({"message": {"content": "ok"}}, messages=[{"role": "user", "content": "hi"}], timeout_s=300)
    assert client.kw["timeout"].read == 300


def test_plain_call_payload_is_unchanged():
    _, client = _run({"message": {"content": "ok"}}, messages=[{"role": "user", "content": "hi"}])
    assert "tools" not in client.sent[0] and "options" not in client.sent[0]

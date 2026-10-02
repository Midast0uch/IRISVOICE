"""Tool model runs node calls (owner 2026-10-01): the system causes it hit.

Eval B (20261001, tool model LFM2.5-2.6B on every node call) failed tasks for
four SYSTEM reasons, each pinned here so it cannot come back:
  1. IRIS's own tool rate limit (10/min/tool) answered ordinary reads with
     "Rate limit exceeded" and the fast model retried in a loop (24 hits;
     0 with the cloud Brain). Owner: limit only destructive tools.
  2. llama-server answers HTTP 500 when the model's tool-call JSON is invalid
     (raw line breaks in file text); IRIS reported "Could not connect" and
     the step died - the model never got to correct it.
  3. The model copied the long absolute project path and cut it
     ("c03_rename_across_f"); every read after that failed.
  4. Node calls should run without hidden reasoning on the local model.
"""

import json
from types import SimpleNamespace

import pytest

from backend.agent.inference.errors import MalformedToolCallError
from backend.agent.node_executor import NodeContext, run_node

TOOLS = [{"type": "function", "function": {"name": n, "parameters": {}}}
         for n in ("read_file", "write_file", "run_command")]


# ── 1. rate limit: destructive tools only ─────────────────────────────────


class _CountingFilter:
    def __init__(self):
        self.checked = []

    def check_tool_execution_rate_limit(self, session_id, tool_name):
        self.checked.append(tool_name)
        return True  # "over the limit" whenever it is asked


def _bridge(flt):
    from backend.agent.tool_bridge import AgentToolBridge

    b = AgentToolBridge.__new__(AgentToolBridge)
    b._security_filter = flt
    return b


@pytest.mark.parametrize("tool", ["read_file", "list_directory", "grep_files", "edit_file"])
def test_ordinary_work_is_never_rate_limited(tool):
    flt = _CountingFilter()
    assert _bridge(flt)._over_rate_limit("s", tool, {"path": "m.py"}) is False
    assert flt.checked == []


def test_a_destructive_tool_keeps_the_limit():
    from backend.agent.permissions import PermissionTier, classify_tool

    destructive = next(t for t in ("delete_file", "shutdown", "restart")
                       if classify_tool(t, None) == PermissionTier.DESTRUCTIVE)
    flt = _CountingFilter()
    assert _bridge(flt)._over_rate_limit("s", destructive, {}) is True
    assert flt.checked == [destructive]


# ── 2. malformed tool-call JSON goes back to the model ────────────────────


def _ctx(gen, results=None, workdir=""):
    results = results or {}
    return NodeContext(generate=gen, execute=lambda n, p: results.get(n, {"success": True}),
                       format_result=lambda n, r: json.dumps(r), tools=TOOLS, workdir=workdir)


def test_a_rejected_tool_call_is_fed_back_and_the_step_continues():
    seen = []
    replies = iter([
        MalformedToolCallError("http://127.0.0.1:8082", "Failed to parse tool call arguments"),
        ("Wrote main.py.\nSTATUS: done", []),
    ])

    def gen(role, messages, **kw):
        seen.append([dict(m) for m in messages])
        r = next(replies)
        if isinstance(r, Exception):
            raise r
        return r[0], "", r[1]

    r = run_node("write main.py", _ctx(gen))
    assert r.success, r.error
    assert "not valid JSON" in seen[1][-1]["content"]


def test_three_rejections_in_a_row_fail_the_step_honestly():
    def gen(role, messages, **kw):
        raise MalformedToolCallError("http://127.0.0.1:8082", "Failed to parse tool call arguments")

    r = run_node("write main.py", _ctx(gen))
    assert r.success is False and "MalformedToolCallError" in r.error


def test_the_transport_names_a_rejected_tool_call_not_a_dead_server(monkeypatch):
    import httpx

    from backend.agent.inference.transport import OpenAICompatTransport

    class _Resp:
        status_code = 500
        headers = {}
        text = ('{"error":{"code":500,"message":"Failed to parse tool call arguments as JSON: '
                'invalid string: control character U+000A"}}')

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    t = OpenAICompatTransport.__new__(OpenAICompatTransport)
    t._endpoint = "http://127.0.0.1:8082"
    t._quota_id = None
    t._provider_id = "local"
    with pytest.raises(MalformedToolCallError):
        t._nonstream("u", "u1", {"messages": []}, timeout_s=5)


# ── 3. the project folder is written `.` ──────────────────────────────────

_WD = r"C:\Users\midas\AppData\Local\Temp\iris-evals\20261001-223059\c03_rename_across_files"


def test_the_model_never_reads_the_absolute_project_path():
    seen = []

    def gen(role, messages, **kw):
        seen.append(messages)
        return "Done.\nSTATUS: done", "", []

    ctx = _ctx(gen, workdir=_WD)
    ctx.task = f"The project is in {_WD}. Rename calc_total in {_WD}\\main.py."
    run_node("rename calc_total", ctx)
    text = json.dumps(seen[0])
    assert "c03_rename_across_files" not in text
    assert "./main.py" in seen[0][1]["content"]


def test_tool_results_are_written_relative_too():
    from backend.agent.node_executor import _relative

    assert _relative(f"FAILED {_WD}\\test_x.py::test_a", _WD) == "FAILED ./test_x.py::test_a"


# ── 4. node calls ask for no hidden reasoning ─────────────────────────────


def test_node_calls_ask_for_no_thinking():
    kws = []

    def gen(role, messages, **kw):
        kws.append(kw)
        return "Done.\nSTATUS: done", "", []

    run_node("x", _ctx(gen))
    assert kws[0].get("thinking") is False


def test_the_router_forwards_thinking_only_to_a_transport_that_takes_it():
    from backend.agent.inference.router import InferenceRouter

    got = {}

    class _WithThinking:
        def generate(self, model, messages, tools=None, *, thinking=None, **kw):
            got["thinking"] = thinking
            return "ok", "", []

    class _Without:
        def generate(self, model, messages, tools=None, *, max_tokens=1, temperature=0.0,
                     chunk_callback=None, reasoning_callback=None, timeout_s=None,
                     budget_check=None):
            return "ok", "", []

    r = InferenceRouter.__new__(InferenceRouter)
    r._turn_budget_check = None
    r._window_resolver = None
    inst = SimpleNamespace(id="t", model="m", kind=SimpleNamespace(value="openai_compat"))
    r.resolve = lambda role: inst
    for transport, expect in ((_WithThinking(), False), (_Without(), None)):
        got.clear()
        r._build_transport = lambda i, _t=transport: _t
        r.generate("tool_execution", [{"role": "user", "content": "x"}], thinking=False)
        assert got.get("thinking") is expect

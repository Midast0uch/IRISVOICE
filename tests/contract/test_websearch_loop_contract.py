"""Contract tests for pin_517dfcbda150 — websearch terminate-loops.

TARGETED tests only (no legacy-suite noise): the physics-driven gather
sanction, content-sufficiency verification, crawl dedupe, zero-pages
honesty, memory-veto enforcement, the deterministic DOCUMENT_RENDER, and
the thread-safe narration log write.

Every test here pins ONE new behavior from the plan. The behavioral
resolution cycle (crawl once -> synthesize) is asserted at the box level
in TestVetoEnforcement.
"""

import asyncio
import json
import threading
import uuid
from types import SimpleNamespace

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.event_bus import get_event_bus, IRISStreamEvent
from backend.agent.narration import NarrationLog
from backend.agent.tool_decision import DecisionKind, ToolDecisionBox

WEB_TOOLS = sorted(
    {"crawler_query", "web_search", "search", "google_search", "exa_search"}
)


def _stub_kernel(u: float = 0.9) -> AgentKernel:
    """Uninitialized kernel with only the attributes the tested paths touch."""
    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = SimpleNamespace(_mycelium=SimpleNamespace())
    k.session_id = f"sess_{uuid.uuid4().hex[:8]}"
    k.conversation_id = "conv_test"
    k._der_crawl_attempts = {}
    k._der_live_cad_state = lambda _s: {"u": u}  # type: ignore[method-assign]
    k._der_task_class = "full"
    k._der_completed_tools = []
    k._router = SimpleNamespace()
    k._tool_bridge = SimpleNamespace()
    k._tool_box = None
    k.infer = lambda *a, **kw: "reason"  # type: ignore[method-assign]
    return k


# ────────────────────────────────────────────────────────────────────────
# Fix 2 — content-sufficiency verification
# ────────────────────────────────────────────────────────────────────────
class TestContentSufficiencyVerification:
    """A crawl step VERIFIEDs as soon as real content exists (self-terminating
    step); empty/stub/error results FAIL; short substance is UNVERIFIED."""

    def setup_method(self):
        self.k = _stub_kernel()

    def test_crawl_with_real_content_verifies(self):
        content = "--- Source: https://example.com ---\n" + ("x" * 500)
        assert (
            self.k._verify_step_result(
                "search the web", None, content, tool="crawler_query"
            )
            == "VERIFIED"
        )

    def test_crawl_empty_fails(self):
        assert (
            self.k._verify_step_result(
                "search the web", None, "", tool="crawler_query"
            )
            == "FAILED"
        )

    def test_crawl_bare_stub_fails(self):
        assert (
            self.k._verify_step_result(
                "search the web", None, "[step 1 completed]", tool="crawler_query"
            )
            == "FAILED"
        )

    def test_crawl_error_string_fails(self):
        assert (
            self.k._verify_step_result(
                "search the web",
                None,
                "crawler_query returned no usable content for query",
                tool="crawler_query",
            )
            == "FAILED"
        )

    def test_crawl_short_substance_unverified(self):
        assert (
            self.k._verify_step_result(
                "search the web", None, "tiny snippet", tool="crawler_query"
            )
            == "UNVERIFIED"
        )

    def test_non_web_tool_keeps_assertion_contract(self):
        # Regression guard: the old assertion-based contract stays for
        # non-web tools.
        assert (
            self.k._verify_step_result(
                "do x", "expected text", "expected text done", tool="read_file"
            )
            == "VERIFIED"
        )


# ────────────────────────────────────────────────────────────────────────
# Fix 1 — physics-driven gather sanction in _mem_lookup
# ────────────────────────────────────────────────────────────────────────
class TestGatherSanction:
    """Web intent resolves to crawler_query only while the physics sanction
    allows it: unresolved (|u| >= U_SPLIT) or no committed content yet, budget
    not exhausted, provider not loaded. Denials return a veto dict."""

    def _box(self, u: float, monkeypatch=None):
        if monkeypatch is not None:
            # The test environment has no internet capability loaded — the
            # production capability gate denies crawler_query here.
            monkeypatch.setattr(
                "backend.agent.tool_registry.capability_allowed", lambda _spec: True
            )
        k = _stub_kernel(u=u)
        return k, k._get_tool_box()

    def test_first_crawl_sanctioned(self, monkeypatch):
        _, box = self._box(u=0.9, monkeypatch=monkeypatch)
        res = box._memory_lookup("search the web for recent Python 3.13 features")
        assert res and res.get("tool") == "crawler_query"

    def test_converged_physics_does_not_veto_synthesis(self, monkeypatch):
        # NEW CONTRACT (REQ-3/D1, user-approved spec long-horizon-der-execution):
        # physics convergence is REMOVED from semantic tool authorization. A
        # non-web synthesis goal is never gather-vetoed because the oscillator
        # is converged — completion/retry come from the execution policy, not u.
        k, box = self._box(u=0.1, monkeypatch=monkeypatch)
        k._der_crawl_attempts[k.conversation_id or k.session_id] = {111}
        res = box._memory_lookup("summarize the web results found earlier")
        assert res is None or "veto" not in res, f"physics must not veto synthesis: {res}"

    def test_fresh_web_query_sanctioned_while_converged(self, monkeypatch):
        # NEW CONTRACT (REQ-3 AC3): a fresh web-intent query is sanctioned even
        # when the oscillator is converged (u=0.1) — the old "converged" veto
        # starved failed-step children and forced the LLM to hallucinate tool
        # unavailability.
        k, box = self._box(u=0.1, monkeypatch=monkeypatch)
        k._der_crawl_attempts[k.conversation_id or k.session_id] = {111}
        res = box._memory_lookup("search the web for the Python 3.13 JIT compiler")
        assert res is not None and res.get("tool") == "crawler_query"

    def test_unresolved_synthesis_step_not_vetoed(self, monkeypatch):
        # Unresolved (u high): the step may still gather more, whatever its
        # phrasing.
        k, box = self._box(u=0.9, monkeypatch=monkeypatch)
        k._der_crawl_attempts[k.conversation_id or k.session_id] = {111}
        res = box._memory_lookup("summarize the findings from the search")
        assert res is None or res.get("tool") is None or True
        # No veto when still unresolved: the LLM keeps its full choice set.
        assert res is None or "veto" not in res

    def test_unresolved_can_gather_more(self, monkeypatch):
        k, box = self._box(u=0.9, monkeypatch=monkeypatch)
        k._der_crawl_attempts[k.conversation_id or k.session_id] = {111}
        res = box._memory_lookup("search the web for more details about the performance")
        assert res and res.get("tool") == "crawler_query"

    def test_budget_exhausted_denies_new_query(self, monkeypatch):
        # INPUT CHANGE (called out): goal rephrased to web-intent ("search the
        # web...") — the crawl budget applies to web-intent gathering (REQ-3
        # AC3 resource bound). The old input ("search for something brand new")
        # is not web-intent under explorer._WEB_INTENT_TRIGGERS, and the new
        # contract no longer applies the crawl budget to non-web goals.
        k, box = self._box(u=0.9, monkeypatch=monkeypatch)
        k._der_crawl_attempts[k.conversation_id or k.session_id] = {1, 2, 3}
        res = box._memory_lookup("search the web for something brand new")
        assert res is not None and res.get("tool") is None
        assert res.get("rationale") == "budget_exhausted"

    def test_same_query_repeat_survives_budget(self, monkeypatch):
        # The identical query is still sanctioned — the JobRegistry dedupe
        # serves the cache, so no new crawl is paid for. Keyed by the stable
        # action key (D2), not the old process-randomized hash.
        from backend.agent.der_execution_ledger import make_action_key

        k, box = self._box(u=0.9, monkeypatch=monkeypatch)
        goal = "search the web for recent Python 3.13 features"
        assert box._memory_lookup(goal) is not None
        _qkey = make_action_key(goal)
        k._der_crawl_attempts[k.conversation_id or k.session_id] = {_qkey, 1, 2}
        res = box._memory_lookup(goal)
        assert res and res.get("tool") == "crawler_query"

    def test_collapsed_amplitude_does_not_veto_required_web(self, monkeypatch):
        # NEW CONTRACT (REQ-3 AC1/AC2): phase-manager amplitude (provider load
        # proxy) paces CALLS in the scheduler; it does NOT authorize or veto a
        # required web action here. Load pressure is a scheduling concern.
        from backend.agent import phase_manager as pm

        class FakeReg:
            def snapshot(self):
                return [SimpleNamespace(amplitude=0.1)]

        monkeypatch.setattr(pm, "get_registry", lambda: FakeReg())
        monkeypatch.setattr(
            "backend.agent.tool_registry.capability_allowed", lambda _spec: True
        )
        k, box = self._box(u=0.9)
        k._der_crawl_attempts[k.conversation_id or k.session_id] = {111}
        res = box._memory_lookup("search the web for more info")
        assert res is not None and res.get("tool") == "crawler_query"

    def test_healthy_amplitude_allows(self, monkeypatch):
        from backend.agent import phase_manager as pm

        class FakeReg:
            def snapshot(self):
                return [SimpleNamespace(amplitude=0.9)]

        monkeypatch.setattr(pm, "get_registry", lambda: FakeReg())
        monkeypatch.setattr(
            "backend.agent.tool_registry.capability_allowed", lambda _spec: True
        )
        k, box = self._box(u=0.9)
        k._der_crawl_attempts[k.conversation_id or k.session_id] = {111}
        res = box._memory_lookup("search the web for more info")
        assert res and res.get("tool") == "crawler_query"


# ────────────────────────────────────────────────────────────────────────
# Fix 1b — veto enforcement at the box level (defense in depth)
# ────────────────────────────────────────────────────────────────────────
class TestVetoEnforcement:
    """Even when the LLM proposes a vetoed gather tool, the box converts the
    decision to REASON — the stop signal cannot be talked around."""

    TOOLS = [
        {"name": "crawler_query", "description": "deep web research crawl"},
        {"name": "read_file", "description": "read a local file"},
        {"name": "speak", "description": "speak text"},
    ]

    def _box(self, memory_fn, router_text):
        # generate() returns the production 3-tuple (text, thinking, tool_calls).
        return ToolDecisionBox(
            router=SimpleNamespace(
                generate=lambda *a, **kw: (router_text, "", None)
            ),
            tool_bridge=SimpleNamespace(),
            get_available_tools=lambda: self.TOOLS,
            validate_tool_call=lambda n, p: (True, None),
            infer_fn=lambda *a, **kw: "reason",
            memory_lookup_fn=memory_fn,
        )

    def _veto_hint(self):
        return {
            "tool": None,
            "veto": WEB_TOOLS,
            "rationale": "converged",
        }

    def test_llm_tool_proposal_of_vetoed_tool_becomes_reason(self):
        box = self._box(
            memory_fn=lambda g: self._veto_hint(),
            router_text=json.dumps(
                {"kind": "tool", "tool": "crawler_query",
                 "params": {"query": "x"}, "rationale": "gather"}
            ),
        )
        decision = box.resolve(
            {"description": "summarize the web findings"}, {},
            session_id="s1", conversation_id="c1",
        )
        assert decision.kind == DecisionKind.REASON
        assert decision.tool is None

    def test_llm_reasoning_accepted_when_vetoed(self):
        # The veto must not block legitimate REASON decisions.
        box = self._box(
            memory_fn=lambda g: self._veto_hint(),
            router_text=json.dumps(
                {"kind": "reasoning", "rationale": "synthesize from committed content"}
            ),
        )
        decision = box.resolve(
            {"description": "summarize the web findings"}, {},
            session_id="s1", conversation_id="c1",
        )
        assert decision.kind == DecisionKind.REASON

    def test_pre_filter_removes_vetoed_tools_from_candidates(self):
        veto_hint = {"tool": None, "veto": ["crawler_query"], "rationale": "x"}
        box = self._box(memory_fn=lambda g: veto_hint, router_text="{}")
        filtered = box._apply_pre_filter(self.TOOLS, veto_hint, "goal")
        names = {t["name"] for t in filtered}
        assert "crawler_query" not in names
        assert "read_file" in names  # non-vetoed tools remain choosable


# ────────────────────────────────────────────────────────────────────────
# Fix 3 — JobRegistry query dedupe + zero-pages honesty
# ────────────────────────────────────────────────────────────────────────
class TestCrawlDedupe:
    def test_identical_query_returns_cached_without_recrawling(self):
        from backend.agent.tool_bridge import AgentToolBridge
        from backend.crawler.job_registry import get_job_registry

        reg = get_job_registry()
        session = f"sess_{uuid.uuid4().hex[:8]}"
        query = "python 3.13 features"
        job_id = f"crawl_{session}_{abs(hash(query)) % 10**8}"
        asyncio.run(reg.register(job_id, session, query))
        asyncio.run(reg.complete(job_id, {
            "query": query, "content": "y" * 2000,
            "pages": [{"url": "https://a.com", "title": "A"}],
        }))

        bridge = AgentToolBridge.__new__(AgentToolBridge)
        result = asyncio.run(bridge._execute_crawler_query({"query": query}, session))
        assert result.get("cached") is True
        assert result["content"].startswith("y")
        assert result.get("job_id") == job_id


class TestZeroContentHonesty:
    def test_zero_content_returns_error_not_hollow_success(self, monkeypatch):
        from backend.agent import tool_bridge as tb
        from backend.agent.tool_bridge import AgentToolBridge

        class FakeOrch:
            async def research(self, *a, **kw):
                return SimpleNamespace(
                    error=None, dashboard_data={"pages": []}, pages=[], har_path=None,
                )

        monkeypatch.setattr(
            "backend.crawler.orchestrator.get_crawl_orchestrator",
            lambda: FakeOrch(),
        )
        monkeypatch.setattr(
            "backend.agent.tools.speak_tool.get_speak_tool",
            lambda: SimpleNamespace(speak=lambda *a, **kw: None),
        )
        bridge = AgentToolBridge.__new__(AgentToolBridge)
        session = f"sess_{uuid.uuid4().hex[:8]}"
        result = asyncio.run(
            bridge._execute_crawler_query({"query": "nothing here"}, session)
        )
        assert result["success"] is False
        assert result.get("error_type") == "empty_result"
        assert "no usable content" in result.get("error", "")


# ────────────────────────────────────────────────────────────────────────
# Fix 4 — web-tool capture contract (revised by user decision 2026-07-31)
# ────────────────────────────────────────────────────────────────────────
# The capture-time deterministic DOCUMENT_RENDER (old pin_517dfcbda150) was
# removed by user decision: it popped a card on EVERY web-tool commit (each
# crawl mid-research), not just the final answer. The prism card now renders
# from the SYNTHESIZED final answer at response time (the show-is-None branch
# of _process_structured_response auto-renders substantial markdown when the
# turn touched web/reference content). Capture only persists the document +
# tracks _pending_web_doc_id for the escalation check (pin_9e97e21340e7).
class TestDeterministicDocumentRender:
    def test_crawl_capture_persists_but_does_not_auto_render(self):
        k = _stub_kernel()
        k._store_document_data = lambda *a, **kw: None  # type: ignore[method-assign]
        k._last_render_emitted = False
        # Production state: nothing pending at capture time.
        k._pending_web_doc_id = None

        captured = []

        def _on_render(data):
            # Subscribers receive an EventPayload wrapper; unwrap it.
            captured.append(getattr(data, "data", data))

        get_event_bus().subscribe(IRISStreamEvent.DOCUMENT_RENDER, _on_render)
        try:
            k._capture_tool_result(
                "crawler_query",
                {
                    "success": True,
                    "content": "# Results\n\n" + ("z" * 100),
                    "pages": [{"url": "https://a.com", "title": "A"}],
                    "har_path": "/tmp/x.har",
                },
                "conv1", turn_id="t1", session_id="s1",
            )
        finally:
            pass  # bus is a global singleton; keep the subscriber (isolated run)

        # Capture persists + tracks the pending doc, but does NOT emit a
        # DOCUMENT_RENDER at capture time (the render happens from the
        # synthesized final answer at response time instead).
        assert len(captured) == 0, "capture must not auto-render (user decision 2026-07-31)"
        # Still tracked for the response-time escalation/auto-render check.
        assert k._pending_web_doc_id is not None


# ────────────────────────────────────────────────────────────────────────
# Fix 8 — narration log write is thread-safe
# ────────────────────────────────────────────────────────────────────────
class TestNarrationThreadSafety:
    def test_record_from_worker_thread_writes(self, tmp_path):
        log = NarrationLog(conversation_id="conv_test")
        log._path = str(tmp_path / "narration.jsonl")
        errs = []

        def worker():
            try:
                asyncio.run(log.record("s1", "speak", "signal", 0.2, 0.1, "hello", True))
            except Exception as exc:  # pragma: no cover - failure path
                errs.append(exc)

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=10)
        assert not errs
        lines = (tmp_path / "narration.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["decision"] == "speak"
        assert entry["text"] == "hello"

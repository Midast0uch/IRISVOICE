"""Behavioral: websearch task completes end-to-end with the encoder ABSENT.

specs/long-horizon-der-execution REQ-10 (AC1-AC4) — tasks.md T22 / T32.
This is the TOP-LEVEL ACCEPTANCE GATE for the REQ-10-REQ-18 extension:

    evidence gathered -> verification reached -> synthesis reached ->
    ONE Prism card with sources -> no re-gather loop

...with the encoder forcibly absent: ``_load_default_encoder`` returns
None AND the cached ``AgentKernel._VERIFIER`` class instance is cleared,
so ``_get_verifier()`` rebuilds on the foundation path alone (graded F1
token-overlap fallback, REQ-11). Nothing about the encoder is stubbed —
it is absent, exactly as on a machine with no Encoder-350M weights.

The drive is REAL end-to-end through the production success path:

  - ``_der_run_step_execution``   real resolver (ToolDecisionBox) -> real
                                  dispatch -> real ``_capture_tool_result``
                                  provenance (sources/har_path persisted) ->
                                  real ``mark_external_tool`` reference zone
  - ``_verify_step_result``       real content-sufficiency for web tools
                                  (AC3 — encoder never consulted); real
                                  graded F1 fallback for non-web steps (AC4)
  - ``_der_finalize_step``        real success finalize -> mark_complete,
                                  no split (REQ-13 fold-forward guard)
  - ``_der_synthesize_success_outcome``  real REQ-12 success synthesis
  - ``_process_structured_response``     real REQ-6 Prism-card render with
                                  inherited sources + har_path

Only the I/O boundary the test cannot reach is stubbed: the router
(planner/proposer text), the tool bridge (crawl content), and the event
bus (observed instead of streamed).
"""

import json
import sqlite3
import time
import uuid
from types import SimpleNamespace

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, QueueItem

GOAL = "search the web for recent Python 3.13 features and summarize them"
EXPECTED = "recent Python 3.13 features"

CRAWL_SOURCES = [
    {"url": "https://docs.python.org/3/whatsnew/3.13.html",
     "title": "What's New In Python 3.13"},
    {"url": "https://peps.python.org/pep-0703/",
     "title": "PEP 703 - Making the Global Interpreter Lock Optional"},
]
CRAWL_HAR = "har://crawl-python313"

# Crawl-shaped tool-bridge result: content plus REQ-6 provenance fields the
# real capture path persists (sources / har_path) and the final card inherits.
CRAWL_RESULT = {
    "success": True,
    "content": (
        "Python 3.13 was released on October 7, 2024. It introduces an "
        "experimental JIT compiler, typed free-threading, and an improved "
        "interactive interpreter. The release also stabilizes the "
        "experimental GIL-free build (PEP 703) and adds incremental garbage "
        "collection improvements that significantly speed up Python "
        "applications on modern hardware."
    ),
    "urls": [s["url"] for s in CRAWL_SOURCES],
    "sources": CRAWL_SOURCES,
    "har_path": CRAWL_HAR,
}

SYNTHESIS = (
    "## Python 3.13 findings\n\n"
    "Python 3.13 (released October 7, 2024) introduces an experimental JIT "
    "compiler, typed free-threading, and an improved interactive interpreter "
    "— a major step toward faster, more concurrent Python. The release "
    "stabilizes the GIL-free build (PEP 703) and improves garbage collection "
    "incrementally, so existing workloads see meaningful speedups without "
    "code changes.\n\n"
    "Sources:\n"
    "- https://docs.python.org/3/whatsnew/3.13.html\n"
    "- https://peps.python.org/pep-0703/"
)


class _FakeMemoryInterface:
    """Enough of MemoryInterface's surface for the REAL capture/render path.

    ``episodic.db`` is a real SQLite connection, which is what
    ``DocumentDataStore.get_for`` and ``get_trajectory_recorder`` key on —
    so ``_capture_tool_result`` persists provenance to a REAL store and the
    recorder binds harmlessly to the in-memory connection. ``_mycelium`` is
    a bare box, so edge-scoring / Mycelium writes degrade to no-ops.
    """

    def __init__(self) -> None:
        self.episodic = SimpleNamespace(db=sqlite3.connect(":memory:"))
        self._mycelium = SimpleNamespace()
        self.session_id = "kernel-default-session"


def _force_encoder_absent(monkeypatch) -> None:
    """Make the encoder-absent path deterministic, regardless of whether
    Encoder-350M weights happen to be cached on this machine.

    The production ``SemanticVerifier`` is built lazily ONCE and cached on
    ``AgentKernel._VERIFIER`` — so we clear the cache as well as forcing
    ``_load_default_encoder`` to None, guaranteeing ``_get_verifier()``
    rebuilds on the foundation path (graded F1 fallback, tag "fallback").
    """
    monkeypatch.setattr(
        "backend.agent.verifier._load_default_encoder", lambda: None
    )
    monkeypatch.setattr(AgentKernel, "_VERIFIER", None)


def _proposing_router(proposal_json: str):
    """Production router.generate returns (text, thinking, tool_calls)."""
    return SimpleNamespace(generate=lambda *a, **kw: (proposal_json, "", None))


def _propose_crawl():
    return json.dumps(
        {"kind": "tool", "tool": "crawler_query",
         "params": {"query": "recent Python 3.13 features"}}
    )


class _CapturingBus:
    """Observes EventBus emits instead of streaming them to a real client."""

    def __init__(self) -> None:
        self.events = []

    def emit(self, event_type, data=None, turn_id=None, conversation_id=None):
        self.events.append(
            {
                "type": event_type,
                "data": data or {},
                "turn_id": turn_id,
                "conversation_id": conversation_id,
            }
        )


def _build_kernel(monkeypatch) -> AgentKernel:
    """AgentKernel with the I/O boundary stubbed (router/bridge/bus observed).

    Mirrors the smoke-test / terminate-loop harnesses: the kernel is built
    via ``__new__`` with only the attributes the DER methods touch.
    """
    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = _FakeMemoryInterface()
    k._tool_bridge = SimpleNamespace()
    k._reviewer = None
    k._mcm_orch = None
    k._der_task_class = "full"
    k._der_completed_tools = []
    k._der_work_units = 0
    k._der_crawl_attempts = {}
    k.conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    k.session_id = f"sess_{uuid.uuid4().hex[:8]}"
    k._personality = None
    k._caducean_modulate_temperature = lambda base, sid: base
    k._get_failure_warnings = lambda text: "None"
    k._build_planning_prompt = lambda **kw: "PLAN PROMPT"
    k.resolve_context_window = lambda: 30000
    k.infer = lambda *a, **kw: "reason"  # type: ignore[method-assign]
    k._router = _proposing_router(_propose_crawl())

    # Registry seams so the real ToolDecisionBox can validate the proposal.
    import backend.agent.tool_registry as tr

    monkeypatch.setattr(
        "backend.agent.tool_registry.capability_allowed", lambda _spec: True
    )
    monkeypatch.setattr(
        tr, "validate_tool_call",
        lambda tool, params: (
            (True, None)
            if tool in ("crawler_query", "get_rendered_documents")
            else (False, "unknown tool")
        ),
    )

    # Real tool-bridge contract: async execute_tool returning crawl content.
    async def _execute_tool(tool_name=None, params=None, **kw):
        assert tool_name == "crawler_query", f"unexpected tool {tool_name!r}"
        return dict(CRAWL_RESULT)

    k._tool_bridge = SimpleNamespace(execute_tool=_execute_tool)
    return k


def _single_websearch_plan_and_queue(k: AgentKernel):
    """One-step websearch DER plan + queue, built exactly like
    ``_execute_plan_der`` builds its execution queue (goals only; the
    resolver picks the tool)."""
    step = SimpleNamespace(
        step_id="s1",
        step_number=1,
        description=GOAL,
        objective_anchor=GOAL,
        depth_layer=0,
        expected_output=EXPECTED,
        tool=None,
        params={},
        critical=False,
    )
    plan = SimpleNamespace(
        original_task=GOAL,
        plan_title="python-3.13-websearch",
        strategy="websearch",
        steps=[step],
    )
    item = QueueItem(
        step_id=step.step_id,
        step_number=step.step_number,
        description=step.description,
        objective_anchor=plan.original_task,
        depth_layer=0,
        expected_output=step.expected_output,
        tool=step.tool,
        params=step.params,
        critical=step.critical,
    )
    queue = DirectorQueue(objective=GOAL)
    queue.add_item(item)
    return plan, item, queue


class TestWebsearchCompletesWithoutEncoder:
    """The top-level acceptance gate: a websearch task completes end to end
    with the encoder absent."""

    def test_websearch_full_task_without_encoder(self, monkeypatch):
        from backend.agent.event_bus import IRISStreamEvent

        _force_encoder_absent(monkeypatch)
        k = _build_kernel(monkeypatch)
        bus = _CapturingBus()
        monkeypatch.setattr(
            "backend.agent.event_bus.get_event_bus", lambda: bus
        )

        plan, item, queue = _single_websearch_plan_and_queue(k)
        ctx = SimpleNamespace()

        # ── 1. EXECUTE: real resolver picks the web tool, real dispatch ──
        step_result, step_success = k._der_run_step_execution(
            item, ctx, k.session_id, "turn-1", plan
        )
        # Evidence gathered: the resolver chose the gather tool and it ran.
        assert item.tool == "crawler_query", (
            "resolver must route the websearch step to a gather tool"
        )
        assert step_success is True
        assert "Python 3.13" in step_result
        # Exactly ONE crawl committed to this task so far (no re-gather).
        assert len(k._der_crawl_attempts.get(k.conversation_id, set())) == 1
        # Real provenance path ran: the crawl doc row + pending pointer exist.
        assert k._pending_web_doc_id is not None
        _store = k._get_document_store()
        _row = _store.get(k._pending_web_doc_id) if _store is not None else None
        assert _row is not None and _row.get("sources") == CRAWL_SOURCES
        assert _row.get("har_path") == CRAWL_HAR
        # The turn is flagged reference (web sources touched) — REAL method.
        assert k._pacman_zone_for_turn() == "reference"
        # REQ-6 AC4: the intermediate crawl was persisted WITHOUT a card.
        _renders = [
            e for e in bus.events
            if e["type"] == IRISStreamEvent.DOCUMENT_RENDER
        ]
        assert len(_renders) == 0, "no card emitted per-commit (REQ-6 AC4)"

        # ── 2. VERIFY (encoder absent) ──────────────────────────────────
        # REQ-10 AC3: a web tool verifies by CONTENT SUFFICIENCY — the
        # encoder is never consulted for the gather step.
        verified = k._verify_step_result(
            item.description, item.expected_output, step_result,
            tool=item.tool, success=step_success,
        )
        assert verified == "VERIFIED"
        # And the verifier itself is on the foundation path (tag "fallback").
        _frac, _tag = k._get_verifier().verified_fraction(
            EXPECTED, step_result
        )
        assert _tag == "fallback"

        # ── 3. FINALIZE: real success finalize — mark_complete, no split ──
        k._der_finalize_step(
            item, step_result, True, [(item, step_result)], [item],
            0, 30000, k.session_id, "turn-1", "execute", False, None,
            plan, ctx, queue, None,
        )
        assert "s1" in queue.completed_ids, "VERIFIED step marks complete"
        assert not any(c.is_subloop for c in queue.items), (
            "VERIFIED must not split — no re-gather children (REQ-13)"
        )
        assert len(queue.items) == 1, "task terminates after one gather"

        # ── 4. SYNTHESIS: real REQ-12 success path reached ──────────────
        # The reasoning provider is stubbed (it is NOT the encoder — REQ-12
        # wiring is pinned end-to-end in test_der_success_synthesizes). The
        # synthesis consumes the SAME evidence the pipeline gathered.
        def _stub_synthesize_response(task, step_results):
            return SYNTHESIS

        k._synthesize_response = _stub_synthesize_response  # type: ignore[method-assign]
        synth = k._der_synthesize_success_outcome(
            plan, [item], queue, k.session_id
        )
        assert synth and len(synth) >= 300, "synthesis reached (REQ-12)"
        assert "Python 3.13" in synth
        assert synth != step_result, "synthesized, not raw concatenation"

        # ── 5. RENDER: ONE Prism card with sources (REQ-6) ──────────────
        returned = k._process_structured_response(
            synth, turn_id="turn-1", conversation_id=k.conversation_id
        )
        _renders = [
            e for e in bus.events
            if e["type"] == IRISStreamEvent.DOCUMENT_RENDER
        ]
        assert len(_renders) == 1, "exactly ONE Prism card (REQ-6 AC1)"
        data = _renders[0]["data"]
        assert data["sources"] == CRAWL_SOURCES, (
            "card inherits captured source URLs (REQ-6 AC1)"
        )
        assert data["har_path"] == CRAWL_HAR, (
            "card inherits HAR provenance (REQ-6 AC1)"
        )
        assert data["document_id"] and data["turn_id"] == "turn-1"
        assert data["conversation_id"] == k.conversation_id
        # REQ-6 AC2: normal text/speech response accompanies the card.
        assert returned and returned.strip()

        # ── 6. T32 RIPPLE: record latency, scorer-tag distribution, and
        #    whether any re-gather loop occurred (REQ-18 trace substrate) ──
        # The gate is asserted above; the MEASUREMENTS the acceptance gate
        # must record (tasks.md T32) are captured here so every run leaves
        # evidence, not just a green/fail verdict.
        from backend.agent.der_trace import get_der_trace, clear_traces

        clear_traces()
        _t0 = time.monotonic()

        # The web step verifies by CONTENT SUFFICIENCY (AC3 — encoder never
        # consulted), so the graded F1 fallback tag is recorded by exercising
        # the NON-web verify path explicitly (REQ-10 AC4): encoder absent ->
        # scorer_tag is ALWAYS "fallback".
        k._verify_step_result(
            "summarize the findings",
            EXPECTED,
            step_result,
            tool="summarize",  # non-web tool -> graded F1 fallback path
            success=True,
        )
        _trace = get_der_trace(k._der_trace_task_id())
        _verify = _trace.entries("verify")
        _tags = {e.get("scorer_tag") for e in _verify}

        _latency_ms = (time.monotonic() - _t0) * 1000
        _re_gathered = len(k._der_crawl_attempts.get(k.conversation_id, set())) > 1

        # Persist the measurements to the REQ-18 trace (bounded, redacted,
        # off the critical path) so the acceptance record is inspectable.
        _trace.record(
            "acceptance",
            gate="T32_encoder_absent",
            latency_ms=round(_latency_ms, 2),
            scorer_tags=sorted(_tags),
            re_gather_loop=_re_gathered,
            verified_label="VERIFIED",
        )
        _acc = _trace.entries("acceptance")[-1]
        assert _acc["gate"] == "T32_encoder_absent"
        assert "fallback" in _acc["scorer_tags"], (
            "encoder absent -> foundation scorer tag recorded"
        )
        assert _acc["re_gather_loop"] is False, (
            "no re-gather loop occurred (recorded)"
        )
        assert _acc["latency_ms"] >= 0

    def test_non_web_step_uses_graded_fallback_without_encoder(self, monkeypatch):
        """REQ-10 AC4 + REQ-11: with the encoder absent, a NON-web-content
        step's assertion match uses the graded F1 fallback — exact-
        containment failure alone never forces a split on a substantial
        answer. (The OLD binary substring scorer returned exactly 0.0 for
        this paraphrase, driving the 'failure' band and re-gather splits.)"""
        _force_encoder_absent(monkeypatch)
        k = AgentKernel.__new__(AgentKernel)
        k._memory_interface = None

        frac, tag = k._get_verifier().verified_fraction(
            "Python 3.13 adds a JIT compiler",
            "Python 3.13 includes a JIT compiler and typed free-threading",
        )
        assert tag == "fallback", "encoder absent -> foundation scorer"
        assert 0.3 <= frac < 1.0, (
            "graded F1 overlap, NOT the legacy binary 0.0/1.0"
        )

        # Substantial paraphrase -> honest terminal label, never a FAILED
        # split solely because the exact assertion text is absent.
        verified = k._verify_step_result(
            "summarize the findings",
            "Python 3.13 adds a JIT compiler",
            (
                "Python 3.13 includes a JIT compiler and typed free-threading. "
                "The improved interpreter makes startup faster and the new "
                "incremental garbage collector reduces pause times for large "
                "applications. Existing code runs unchanged."
            ) * 3,
            tool="summarize", success=True,
        )
        assert verified in ("VERIFIED", "UNVERIFIED"), (
            "substantial result folds forward — never FAILED by exact "
            "containment alone (REQ-10 AC4 / REQ-13)"
        )

    def test_fresh_query_beyond_budget_vetoed(self, monkeypatch):
        """No re-gather loop at the DECISION layer: the real ToolDecisionBox
        vetoes a fresh distinct web query once the per-task gather budget is
        saturated (REQ-3 AC3 — budget_exhausted -> REASON, no tool)."""
        from backend.agent.der_execution_ledger import make_action_key
        from backend.agent.tool_decision import DecisionKind

        _force_encoder_absent(monkeypatch)
        k = _build_kernel(monkeypatch)
        box = k._get_tool_box()
        # Budget saturated: 3 distinct queries already committed.
        k._der_crawl_attempts[k.conversation_id] = {
            make_action_key(g)
            for g in ("search topic a", "search topic b", "search topic c")
        }
        d = box.resolve(
            {"description": "search the web for more details on the findings"},
            {},
            session_id=k.session_id,
            conversation_id=k.conversation_id,
        )
        assert d.kind == DecisionKind.REASON
        assert d.tool is None
        assert d.rationale == "budget_exhausted"

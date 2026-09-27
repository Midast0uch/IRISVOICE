"""CT-11..CT-16 (specs/tool-result-envelope Wave 5 gate TG-5).

Contract pins for the ledger/chooser/identity/deadline/recovery instruments:
envelope sources bounds + pointers-only ledger, exclusion filtering, guard on
resolved seeds, exact body identity + dead memory, honest timeouts, recovery
lane rules. Pure functions + stub-bound methods; no live web, no live model.

Twin fixtures live here AND in behavioral/test_wave5_replay_behavior.py (the
intertwined rule: same conv-102 shapes, both sides).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.agent.der_loop import QueueItem
from backend.agent.tool_envelope import (
    ToolResultEnvelope,
    body_hashes_of,
    build_envelope,
    derive_novelty,
    evaluate_streak,
    extract_sources,
)
from backend.crawler.crawler_engine import CrawlResult


# ── shared conv-102 fixtures (twin: test_wave5_replay_behavior.py) ───────────

WIKI = "https://github.com/ggerganov/whisper.cpp/wiki"
STALE_404 = "https://github.com/ggerganov/whisper.cpp/blob/master/examples/streaming/streaming.cpp"
BODY_A = (("whisper.cpp streaming support implementation approach limitations " * 12).strip()
          + " see https://github.com/ggml-org/whisper.cpp"
          + " and https://arxiv.org/abs/2400.12345 for background.")
TAIL_MARKER = "TAIL-MARKER-NEVER-IN-PROMPT-9e77"


def _gather_result(url, body):
    return f"--- Source: {url} ---\n{body}"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── CT-11: envelope sources bounded + marked, ledger pointers-only ───────────


def test_ct11_sources_capped_and_truncation_marked():
    text = "\n".join(
        f"--- Source: https://s{i}.example/p ---\n{('body text ' * 30)}"
        for i in range(12)
    )
    sources, total = extract_sources(text)
    assert len(sources) == 8
    assert total == 12
    assert total > len(sources)  # the truncation mark
    env = build_envelope(
        result_text=text, step_success=True, outcome="VERIFIED",
        expected_output="", tool="crawler_query", params_digest="p",
        verified_fraction=1.0, prev_verified_fraction=None, raw_doc_id="d",
        coords_from=None, coords_to=None, turn_memory={},
    )
    assert len(env.sources) == 8
    assert env.sources_total == 12


def test_ct11_ledger_block_is_pointers_only():
    from backend.agent.agent_kernel import AgentKernel
    from types import SimpleNamespace

    body_with_marker = BODY_A + " " + TAIL_MARKER
    stub = SimpleNamespace(
        conversation_id="c",
        _der_crawled_urls={"c": {WIKI}},
        _der_crawled_steps={"c": {WIKI: "s1"}},
    )
    stub._der_visited_block = AgentKernel._der_visited_block.__get__(stub)
    block = stub._der_visited_block()
    assert WIKI in block and "(step s1)" in block
    assert TAIL_MARKER not in block and BODY_A not in block
    # the planning prompt carries the block; user history legitimately
    # echoes user text (pre-existing CT-2 scope is tool payloads, not this)
    prompt = AgentKernel._build_planning_prompt(
        stub, task="research",
        context=[{"role": "user", "content": "short question"}],
    )
    assert "VISITED THIS TURN" in prompt


# ── CT-12: chooser exclusions (the south road gets the rulebook) ─────────────


def test_ct12_exclude_visited_filters_and_is_empty_safe():
    from backend.crawler.orchestrator import CrawlOrchestrator

    o = CrawlOrchestrator()
    assert o._exclude_visited([WIKI, "https://fresh.example/a"], {WIKI}, "j", "t") == [
        "https://fresh.example/a"
    ]
    assert o._exclude_visited(None, None, "j", "t") == []


def test_ct12_research_with_fully_visited_seeds_is_honest_empty():
    from types import SimpleNamespace

    from backend.crawler.orchestrator import CrawlOrchestrator

    o = CrawlOrchestrator()

    def _explode(_query):
        raise AssertionError("planner must not run for fully-visited seeds")

    o._planner = SimpleNamespace(plan=_explode)
    res = _run(
        o.research(
            "whisper.cpp streaming", session_id="",
            seed_urls=[WIKI], excluded_urls=[WIKI],
        )
    )
    assert res.error and "already visited" in res.error
    assert res.pages == []


# ── CT-13: guard judges resolved seeds (params-carried URLs) ─────────────────


def _guard_stub(crawled):
    from types import SimpleNamespace

    return SimpleNamespace(
        conversation_id="c",
        _envelope_counters=None,
        _der_seen_dispatches={},
        _der_envelope_registry={},
        _der_crawled_urls={"c": set(crawled)},
    )


def test_ct13_guard_blocks_all_crawled_params_urls_with_reroute():
    from backend.agent.agent_kernel import AgentKernel

    stub = _guard_stub({WIKI})
    item = SimpleNamespace(
        tool="fetch_url", params={"known_urls": [WIKI]}, step_id="s9",
    )
    verdict = AgentKernel._der_pre_dispatch_guard(stub, item)
    assert verdict is not None
    assert verdict["reroute_tool"] == "get_rendered_documents"


def test_ct13_guard_passes_query_only_crawl():
    # Documents the boundary: a bare query carries no addresses, so the
    # guard cannot judge it — the crawler queue-time filter (CT-12) owns
    # that road instead.
    from backend.agent.agent_kernel import AgentKernel

    stub = _guard_stub({WIKI})
    item = SimpleNamespace(
        tool="crawler_query", params={"query": "whisper.cpp streaming"},
        step_id="s9",
    )
    assert AgentKernel._der_pre_dispatch_guard(stub, item) is None


# ── CT-14: exact body identity + dead-address memory ──────────────────────────


def test_ct14_identical_bodies_match_across_urls_stubs_ignored():
    t1 = _gather_result("https://a.example/1", BODY_A)
    t2 = _gather_result("https://b.example/other", BODY_A)
    t3 = _gather_result("https://c.example/3", "completely different " * 30)
    h1, h2, h3 = (
        body_hashes_of(t1), body_hashes_of(t2), body_hashes_of(t3),
    )
    assert h1 == h2 and len(h1) == 1
    assert h1 != h3
    assert body_hashes_of("short") == []
    mem = {"crawled_urls": set(), "tool_params": {}, "body_hashes": {h1[0]: "s1"}}
    assert (
        derive_novelty(t2, "crawler_query", "other-digest", mem) == "repeat_of_s1"
    )
    assert (
        derive_novelty(t3, "crawler_query", "d3", mem) == "new"
    )


def test_ct14_dead_urls_default_and_preserved():
    assert CrawlResult(
        query="q", pages=[], duration_ms=1, crawled_at="t",
    ).dead_urls == []
    assert CrawlResult(
        query="q", pages=[], duration_ms=1, crawled_at="t",
        dead_urls=[STALE_404],
    ).dead_urls == [STALE_404]


# ── CT-15: honest timeouts ───────────────────────────────────────────────────


def test_ct15_timeout_envelope_shape_and_streak():
    env = build_envelope(
        result_text="[STEP TIMEOUT after 90s (deadline 90s)]",
        step_success=False, outcome="FAILED", expected_output="fresh sources",
        tool="crawler_query", params_digest="p", verified_fraction=0.0,
        prev_verified_fraction=None, raw_doc_id="", coords_from=None,
        coords_to=None, turn_memory={}, timeout=True, elapsed_s=90.2,
    )
    assert env.status == "timeout"
    assert env.stuck_shape == "flat_tire"
    assert env.suggestion == "try_different"
    assert env.error_type == "timeout"
    assert "90.2" in env.recovery_hint
    w = {"status": "timeout", "novelty": "new", "match": "unclear",
         "stuck_shape": "flat_tire"}
    fired, reason = evaluate_streak([w, dict(w)], 2, 2)
    assert fired and reason.startswith("stuck_streak")


def test_ct15_run_async_enforces_and_releases():
    import time

    from backend.agent.tool_decision import ToolDecisionBox

    async def _fast():
        return {"ok": True}

    # _run_async is synchronous (returns values, not coroutines)
    assert ToolDecisionBox._run_async(_fast(), timeout_s=5) == {"ok": True}

    async def _hang():
        await asyncio.sleep(3)

    t0 = time.monotonic()
    with pytest.raises(BaseException):
        ToolDecisionBox._run_async(_hang(), timeout_s=0.2)
    # wait_for CANCELS (no orphan); fails closed fast
    assert time.monotonic() - t0 < 5


def test_ct15_deadline_mapping_per_family():
    from types import SimpleNamespace

    from backend.agent.agent_kernel import AgentKernel

    # AMENDED 2026-09-26: the gather deadline is 240s, not the spec's original
    # 150s — specs/tool-result-envelope T18 recorded that triple as
    # "150/60/90s UNVERIFIED", and measurement resolved it. Two live crawls
    # died at 157-159s (at the finish line), so `der_constants.py` raised
    # DEADLINE_CRAWL_S to 240 with the reason written in place; the sibling
    # read (60) and default (90) values are unchanged. The assertion keeps its
    # exact-equality strength against the current table — only the stale
    # expected constant moved. This test-input change is reported, not silent.
    assert AgentKernel._der_tool_deadline(SimpleNamespace(), "crawler_query") == 240
    assert AgentKernel._der_tool_deadline(SimpleNamespace(), "read_file") == 60
    assert AgentKernel._der_tool_deadline(SimpleNamespace(), "speak") == 90


# ── CT-16: recovery lane rules ────────────────────────────────────────────────


def _recovery_stub(visited=(), opened=()):
    from types import SimpleNamespace

    return SimpleNamespace(
        conversation_id="c",
        _der_crawled_urls={"c": set(visited)},
        _der_recovery_opened={"c": set(opened)},
    )


def _recovery_item(env_sources=(), step_id="s1"):
    from types import SimpleNamespace

    env = build_envelope(
        result_text="", step_success=False, outcome="FAILED",
        expected_output="streaming docs", tool="crawler_query",
        params_digest="p", verified_fraction=0.0,
        prev_verified_fraction=None, raw_doc_id="", coords_from=None,
        coords_to=None, turn_memory={},
    )
    env.sources = list(env_sources)
    return SimpleNamespace(
        step_id=step_id, step_number=1, description="research X",
        tool="crawler_query", params={}, objective_anchor="obj",
        expected_output="streaming docs", declared_criticality="supporting",
        envelope=env, recovery_of="",
    )


_DEAD_RES = (
    "--- Attempted: https://dead.example/old-page ---\n"
    "--- Outlinks (uncrawled candidates):\n"
    "  - https://dead.example/new-page\n"
    "  - https://dead.example/old-page\n"
)


def test_ct16_recovery_opens_once_with_unvisited_in_site_seeds():
    from backend.agent.agent_kernel import AgentKernel
    from types import SimpleNamespace

    stub = _recovery_stub(
        visited={"https://dead.example/old-page", "https://dead.example/used"},
    )
    queue = SimpleNamespace(items=[])
    rec = AgentKernel._der_maybe_open_recovery(
        stub, _recovery_item(), _DEAD_RES, [], queue,
    )
    assert rec is not None
    assert rec.recovery_of == "s1" and rec.step_id == "recovery_s1"
    assert rec.recovery_seeds == [
        "https://dead.example/new-page", "https://dead.example/",
    ]
    # same-address re-fetch stays blocked inside recovery too
    assert "https://dead.example/old-page" not in rec.recovery_seeds
    # second trigger for the same host: refused (one recovery per host)
    assert (
        AgentKernel._der_maybe_open_recovery(stub, _recovery_item(), _DEAD_RES, [], queue)
        is None
    )


def test_ct16_no_chains_no_false_positives_budget_cap():
    from backend.agent.agent_kernel import AgentKernel
    from types import SimpleNamespace

    stub = _recovery_stub(visited={"https://h.example/dead"})
    queue = SimpleNamespace(items=[])
    chained = _recovery_item()
    chained.recovery_of = "s0"
    assert (
        AgentKernel._der_maybe_open_recovery(stub, chained, _DEAD_RES, [], queue)
        is None
    )
    sourced = _recovery_item(env_sources=["https://h.example/dead"])
    assert (
        AgentKernel._der_maybe_open_recovery(
            stub, sourced,
            "--- Attempted: https://h.example/dead ---\n", [], queue,
        )
        is None
    )
    # AC9.7 (session-319): the page cap is a RUNAWAY SAFETY NET, not the
    # operating limit — the owner made recovery agent-determined and the cap
    # moved 5 -> 25. Re-pinned to the CONSTANT so it tracks tuning, and
    # STRENGTHENED: it now drives more candidates than the cap and asserts the
    # truncation, where the old form generated fewer than the cap and asserted
    # a bound that could not fail.
    from backend.agent.der_constants import RECOVERY_PAGE_BUDGET
    _over_cap = int(RECOVERY_PAGE_BUDGET) + 5
    many_links = "".join(
        f"  - https://h.example/p{i}\n" for i in range(_over_cap)
    )
    res = (
        "--- Attempted: https://h.example/dead ---\n"
        "--- Outlinks (uncrawled candidates):\n" + many_links
    )
    rec = AgentKernel._der_maybe_open_recovery(
        _recovery_stub(visited={"https://h.example/dead"}),
        _recovery_item(), res, [], queue,
    )
    assert rec is not None
    assert len(rec.recovery_seeds) == int(RECOVERY_PAGE_BUDGET)  # page budget cap


def test_ct16_recovery_of_rides_the_envelope():
    env = build_envelope(
        result_text="recovered body text", step_success=True, outcome="VERIFIED",
        expected_output="", tool="crawler_query", params_digest="p",
        verified_fraction=1.0, prev_verified_fraction=None, raw_doc_id="d",
        coords_from=None, coords_to=None, turn_memory={}, recovery_of="s4",
    )
    assert env.recovery_of == "s4"


def test_ct17_per_host_recovery_budget_holds_under_concurrent_calls():
    """Session-319: ONE CREW PER BUILDING must hold when steps run together.

    Parallel_safe steps run concurrently (Phase 4). The per-host budget used to
    be a read near the top of the method and a write near the bottom with no
    lock in between — so in principle two steps hitting the same dead host at the
    same instant could both read "not yet opened" and each open a recovery.

    HONEST SCOPE (verified, session-319): this test asserts the INVARIANT (exactly
    one winner, and the host is claimed afterwards). It does NOT reproduce the
    race, and it will pass with or without the lock. Measured: 8 threads released
    through a barrier give 1 winner with the lock AND 1 without it, because the
    critical section is short, CPU-only, and the GIL serialises it — a thread
    finishes read→compute→claim inside one interpreter switch interval. So the
    lock is insurance against the section LATER growing or acquiring I/O, not a
    fix for an observed bug. Do not cite this test as race-reproduction evidence.
    """
    import threading
    from backend.agent.agent_kernel import AgentKernel
    from types import SimpleNamespace

    _CONTENDERS = 8
    stub = _recovery_stub(visited={"https://dead.example/old-page"})
    queue = SimpleNamespace(items=[])
    results = []
    _barrier = threading.Barrier(_CONTENDERS)
    _lock = threading.Lock()

    def _race():
        _barrier.wait()  # release every thread at the same instant
        try:
            _r = AgentKernel._der_maybe_open_recovery(
                stub, _recovery_item(), _DEAD_RES, [], queue,
            )
        except Exception:
            _r = "error"
        with _lock:
            results.append(_r)

    _threads = [threading.Thread(target=_race) for _ in range(_CONTENDERS)]
    for _t in _threads:
        _t.start()
    for _t in _threads:
        _t.join()

    _winners = [r for r in results if r is not None and r != "error"]
    assert len(results) == _CONTENDERS
    assert not [r for r in results if r == "error"], "recovery raised under contention"
    assert len(_winners) == 1, (
        f"per-host budget leaked: {len(_winners)} recoveries opened for one host"
    )
    # The host is now claimed, so a later step is refused.
    assert AgentKernel._der_maybe_open_recovery(
        stub, _recovery_item(), _DEAD_RES, [], queue,
    ) is None


def test_ct18_routed_recovery_is_enqueued_not_run_inline():
    """Session-319 job board: a routed recovery must be QUEUED as its own step.

    Before this change the router ran the recovery node INLINE and blocked the
    failing step for the whole recovery (measured ~33 s Chromium cold start), and
    built no envelope of its own. AC9.5/AC9.6 require a SEPARATE step and a brain
    that never waits. This pins the new behaviour.
    """
    from backend.agent.agent_kernel import AgentKernel
    from backend.agent.der_constants import RECOVERY_PAGE_BUDGET
    from types import SimpleNamespace

    enqueued = []

    class _Queue:
        def add_item(self, _it):
            enqueued.append(_it)

    stub = _recovery_stub(visited={"https://dead.example/old-page"})
    stub._card_envelope = lambda _t: {}
    item = _recovery_item()
    node = SimpleNamespace(name="fetch.vision")
    outcome = SimpleNamespace(reason=SimpleNamespace(value="empty"))
    queue = _Queue()

    # Returns None ALWAYS: the failing step settles honestly, it really failed.
    assert AgentKernel._der_enqueue_recovery(
        stub, item, node, _DEAD_RES, "sess", "turn-1", outcome,
        "crawler_query", queue,
    ) is None

    assert len(enqueued) == 1, "exactly one recovery step must be queued"
    rec = enqueued[0]
    assert rec.recovery_of == item.step_id, "parent link must ride the step"
    assert rec.recovery_seeds, "the resolved seeds must ride the step"
    assert rec.tool == "fetch.vision", "the ROUTER's node must be used"
    assert rec.step_id.startswith("recovery_")
    # The pre-resolved seeds are handed to the crawl, capped by the budget.
    assert rec.params.get("seed_urls"), "seed_urls must reach the dispatch"
    assert rec.params.get("max_pages") == int(RECOVERY_PAGE_BUDGET)

    # ONE CREW PER BUILDING: the host is claimed, so a second step is refused.
    assert AgentKernel._der_enqueue_recovery(
        stub, item, node, _DEAD_RES, "sess", "turn-1", outcome,
        "crawler_query", queue,
    ) is None
    assert len(enqueued) == 1, "a second crew for one host must not be queued"

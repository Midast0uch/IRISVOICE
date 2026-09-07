"""T43 (vision-goal-directed-search GAP closure, user-approved session-304):

Closes the 4 GAP rows from the Traceability Matrix backfill (2026-09-07):
- AC3.4  (REQ-3):  CT-2 `iris:vision_status` lifecycle-chip contract missing.
                   T23 claimed CT-2 but wrote no proving test.
- AC18.1 (REQ-18): `to_batch_tool_call` bridge has NO test (types only in
                   test_goal_anatomy.py).
- AC18.3 (REQ-18): `collect_batch_outcome` fold has NO test (types only).
- AC21.2 (REQ-21): dispatch entry check exists (orchestrator.py:880-902, wired
                   by T31) but has NO fail-closed test proving it returns an
                   explicit CrawlResult.error and never raises.

All four are producer-side (no network, no browser, no mic). The test is the
requirement (TEST RULE ABSOLUTE) — these tests pin existing behavior, they do
not change production code.
"""
from __future__ import annotations

import asyncio

import pytest


# ---------------------------------------------------------------------------
# AC3.4 (REQ-3, CT-2): vision_status lifecycle shape for VisionLifecycleChip
# ---------------------------------------------------------------------------

async def _emit_lifecycle(state: str, reason: str = "", trigger: str = "test") -> dict:
    """Drive the real `_broadcast_vision_lifecycle` with a fake ws_manager.

    The gateway __init__ does heavy work (ws_bridge, wake-word scan), so the
    instance is built via object.__new__ — the method under contract only
    touches self._ws_manager.broadcast, which the fake captures.
    """
    from backend.iris_gateway import IRISGateway

    captured: list[dict] = []

    class _FakeWS:
        async def broadcast(self, msg: dict) -> None:
            captured.append(msg)

    gw = object.__new__(IRISGateway)
    gw._ws_manager = _FakeWS()  # type: ignore[attr-defined]
    await gw._broadcast_vision_lifecycle(state, reason, trigger)
    assert len(captured) == 1, f"expected exactly 1 broadcast, got {captured}"
    return captured[0]


@pytest.mark.parametrize("state", ["cold", "spawning", "warm", "error"])
def test_ct2_vision_lifecycle_shape_per_state(state):
    """AC3.4: lifecycle broadcast carries status=lifecycle + valid state.

    Frontend contract (VisionLifecycleChip.tsx:12-14,36): payload
    { status: "lifecycle", state, reason?, trigger? } — additive on the
    existing vision_status shape; payloads without `state` are legacy and
    ignored by the chip. The backend MUST always include `state`.
    """
    msg = asyncio.run(_emit_lifecycle(state, reason="t43-pin", trigger="t43"))
    assert msg["type"] == "vision_status"
    payload = msg["payload"]
    assert payload["status"] == "lifecycle"
    assert payload["state"] == state
    assert payload["reason"] == "t43-pin"
    assert payload["trigger"] == "t43"
    # Additive invariant: the legacy status values ("enabled"/"error"/...) are
    # untouched — "lifecycle" is a NEW status value, never a replacement.
    assert payload["status"] not in ("enabled", "error", "loading")


def test_ct2_vision_lifecycle_never_raises():
    """AC3.4 edge: a dead broadcast path must not break the caller.

    The method wraps broadcast in try/except (gateway never blocks vision on
    a socket fault) — pin that it swallows instead of raising.
    """
    from backend.iris_gateway import IRISGateway

    class _DeadWS:
        async def broadcast(self, msg: dict) -> None:
            raise RuntimeError("socket gone")

    gw = object.__new__(IRISGateway)
    gw._ws_manager = _DeadWS()  # type: ignore[attr-defined]
    # Must not raise — returns None silently.
    assert asyncio.run(gw._broadcast_vision_lifecycle("warm", "", "t43")) is None


# ---------------------------------------------------------------------------
# AC18.1 (REQ-18): to_batch_tool_call bridge
# ---------------------------------------------------------------------------

def _stub_brain(task: str, n_needed: int, existing: list[str]):  # pragma: no cover
    return [
        "technical specifications for halide tablets",
        "pricing and availability for halide tablets",
    ]


def test_to_batch_tool_call_marks_parallel_safe_independent():
    """AC18.1: the facet set bridges into a composite BatchToolCall node with
    parallel_safe=True and independent=True so the DAG may release items
    together under the caller's concurrency governance."""
    from backend.agent.query_synthesizer import synthesize_for_task, to_batch_tool_call

    batch = synthesize_for_task("halide tablets", brain=_stub_brain)
    assert 2 <= len(batch.queries) <= 4
    call = to_batch_tool_call(batch, batch_id="t43-b1")
    assert getattr(call, "batch_id") == "t43-b1"
    assert getattr(call, "parallel_safe") is True
    assert getattr(call, "independent") is True
    items = list(getattr(call, "items"))
    assert len(items) == len(batch.queries)
    for item, facet in zip(items, batch.queries):
        assert item["query"] == facet.query
        assert item["axis"] == facet.axis
        assert item["task"] == batch.task


def test_to_batch_tool_call_empty_facets_stays_valid():
    """AC18.1 edge: an empty facet set still yields a valid (empty) node —
    the DAG decides release, never the bridge."""
    from backend.agent.query_synthesizer import QueryBatch, to_batch_tool_call

    call = to_batch_tool_call(QueryBatch(task="t", queries=[]), batch_id="t43-empty")
    assert list(getattr(call, "items")) == []
    assert getattr(call, "parallel_safe") is True


# ---------------------------------------------------------------------------
# AC18.3 (REQ-18): collect_batch_outcome fold
# ---------------------------------------------------------------------------

def test_collect_batch_outcome_folds_mixed_results():
    """AC18.3: per-item (key, ok, result, error) tuples fold into one
    consolidated BatchOutcome; BatchItemResults pass through; malformed
    entries stay visible as ok=False instead of raising."""
    from backend.agent.query_synthesizer import collect_batch_outcome
    from backend.core_models import BatchItemResult

    class _Batch:
        batch_id = "t43-b2"
        tool = "crawler.dispatch"

    outcome = collect_batch_outcome(
        _Batch(),
        [
            ("a", True, {"price": 5}, None),
            ("b", False, None, "timeout"),
            BatchItemResult(item_key="c", ok=True, result={"spec": "16GB"}),
            object(),  # malformed — must not raise
        ],
    )
    assert getattr(outcome, "batch_id") == "t43-b2"
    results = list(getattr(outcome, "results"))
    assert len(results) == 4
    assert results[0].item_key == "a" and results[0].ok is True
    assert results[1].item_key == "b" and results[1].ok is False
    assert results[1].error == "timeout"
    assert results[2].item_key == "c" and results[2].ok is True
    assert results[3].ok is False and results[3].error == "malformed item result"
    assert outcome.ok_count == 2
    assert [r.item_key for r in outcome.usable()] == ["a", "c"]


# ---------------------------------------------------------------------------
# AC21.2 (REQ-21): dispatch entry rejects bad schemas fail-closed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "keyword", ["oneOf", "additionalProperties", "const", "allOf", "$ref"]
)
def test_dispatch_rejects_unsupported_keyword_fail_closed(keyword):
    """AC21.2: dispatch_urls validates output_schema BEFORE any fetch burns.

    Fail-closed = explicit CrawlResult.error starting with
    "schema_validation:" (this funnel never raises), pages empty, no fetch
    attempted (returns before capability lookup — no network in this test).
    """
    from backend.crawler.orchestrator import CrawlOrchestrator

    orch = CrawlOrchestrator()
    schema = {"type": "object", "properties": {"x": {"type": "string", keyword: 1}}}
    result = asyncio.run(
        orch.dispatch_urls(
            ["https://example.com/never-fetched"],
            query="t43",
            job_id="t43-schema",
            output_schema=schema,
        )
    )
    assert result.pages == []
    assert isinstance(result.error, str) and result.error.startswith(
        "schema_validation:"
    ), result.error
    assert keyword in result.error


def test_dispatch_valid_schema_passes_entry_gate():
    """AC21.2 companion: a 12-keyword-allowlisted schema must NOT trip the
    entry gate. It proceeds past validation (here it fails later with zero
    usable pages in this offline environment — the assertion is only that the
    failure is NOT a schema_validation rejection and nothing raises)."""
    from backend.crawler.capabilities import CAPABILITIES
    from backend.crawler.orchestrator import CrawlOrchestrator

    # Hermetic registry: other suites clear CAPABILITIES without restoring, so
    # pin our own stub (never called — the URL list is empty) and restore.
    _saved = dict(CAPABILITIES)

    class _StubCap:
        name = "fetch.crawl"

        async def available(self):
            return True

        async def fetch_one(self, url, goal, job_id, **kw):
            raise AssertionError("unreachable: empty URL list dispatches nothing")

    CAPABILITIES.clear()
    CAPABILITIES["fetch.crawl"] = _StubCap()
    try:
        orch = CrawlOrchestrator()
        schema = {
            "type": "object",
            "properties": {"price": {"type": "number", "minimum": 0}},
            "required": ["price"],
        }
        result = asyncio.run(
            orch.dispatch_urls(
                [],
                query="t43",
                job_id="t43-schema-ok",
                output_schema=schema,
                max_pages=1,
                timeout_s=1.0,
                concurrency_limit=1,
            )
        )
        # Whatever the empty run yields, it must not be the entry gate
        # (empty URL list dispatches zero fetches — no network in this test).
        assert not (isinstance(result.error, str) and result.error.startswith(
            "schema_validation:"
        )), result.error
    finally:
        CAPABILITIES.clear()
        CAPABILITIES.update(_saved)

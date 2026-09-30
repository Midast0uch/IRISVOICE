"""Spec A6 (websearch-vision-browser, REQ-3 AC3.4-3.5, RC6): output quality of a web answer.

r02 (2026-09-30) showed two defects after a good search:

1. `goal_contract.extract_required` stored the tool result's `--- Source: URL ---` header lines
   as "facts", which opened a needless bonus pass.
2. A 14-token synthesis stub fell straight through to the deterministic close, which printed the
   raw `--- Source:` page dump as the reply.

Now: scaffolding lines are ignored; a stub synthesis is retried ONCE with the same inputs; a
stub that persists falls to a deterministic close that names the sources, never their raw text.

The page text below is the real Exa response fixture (backend/tests/data/exa_search_response.json)
laid out exactly as the quick tier lays it out (`_quick_search_via_provider`).

Hermetic: no model, no I/O.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.agent import goal_contract as gc
from backend.agent.agent_kernel import AgentKernel

_FIXTURE = Path(__file__).resolve().parent.parent / "data" / "exa_search_response.json"


def _tool_result_text() -> str:
    """The quick tier's envelope `content` for the recorded Exa response."""
    results = json.loads(_FIXTURE.read_text(encoding="utf-8"))["results"]
    return "\n\n".join(f"--- Source: {r['url']} ---\n{r['highlights'][0]}" for r in results)


# ── AC3.4: goal_contract ignores scaffolding ─────────────────────────────────

def test_source_header_lines_are_not_facts():
    text = _tool_result_text()
    assert "--- Source:" in text

    facts = gc.extract_required(text)

    assert facts, "page prose should still yield facts"
    assert not any("Source:" in f or f.startswith("---") for f in facts), facts
    assert not any(f.startswith("http") for f in facts), facts


def test_all_page_scaffolding_lines_are_ignored():
    text = (
        "--- Source: https://en.wikipedia.org/wiki/Python_(programming_language) ---\n"
        "Guido van Rossum began working on Python in the late 1980s.\n"
        "[...truncated...]\n"
        "--- Attempted: https://a.example/x https://b.example/y\n"
        "--- Dead: https://c.example/z\n"
        "--- Outlinks (uncrawled candidates):\n"
        "  - https://d.example/one\n"
        "  - https://e.example/two\n"
        "  (+3 already-visited or over cap)"
    )
    facts = gc.extract_required(text)
    assert facts == ("Guido van Rossum began working on Python in the late 1980s",), facts


def test_a_text_that_is_only_scaffolding_has_no_fact():
    only = "--- Source: https://a.example/x ---\n--- Attempted: https://a.example/x"
    assert gc.extract_required(only) == ("",)


def test_user_requests_are_unchanged_by_the_scaffold_filter():
    req = "1. find the year Python was released 2. find who created it"
    assert gc.extract_required(req) == (
        "find the year Python was released",
        "find who created it",
    )


# ── AC3.5: a stub synthesis retries once, never dumps raw sources ────────────

def _kernel(replies):
    """A kernel whose `_synthesize_response` returns `replies` in order; `.calls` counts."""
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv-a6"
    k.calls = 0

    def _syn(task, results):
        i = min(k.calls, len(replies) - 1)
        k.calls += 1
        return replies[i]

    k._synthesize_response = _syn  # type: ignore[method-assign]
    return k


def _run_success_synthesis(k):
    plan = SimpleNamespace(original_task="Who created Python and when?")
    item = SimpleNamespace(
        tool="search", description="look up who created Python", result="x",
        node_record=None, footprint=None,
    )
    return k._der_synthesize_success_outcome(plan, [item], SimpleNamespace(), "sess-a6")


_STUB = "Guido van Rossum."  # 17 chars - under the 80-char floor
_REAL = (
    "Python was created by Guido van Rossum, who began work on it in the late 1980s; "
    "its first public version, 0.9.0, was released in February 1991."
)


def test_a_stub_synthesis_is_retried_once_and_the_retry_answer_is_used():
    k = _kernel([_STUB, _REAL])
    out = _run_success_synthesis(k)
    assert out == _REAL
    assert k.calls == 2


def test_a_persistent_stub_is_retried_exactly_once_then_falls_to_the_deterministic_close():
    k = _kernel([_STUB, _STUB, _STUB])
    out = _run_success_synthesis(k)
    assert out == "", "a persistent stub must return '' so the deterministic close answers"
    assert k.calls == 2, "exactly ONE retry"


def test_a_real_synthesis_is_not_retried():
    k = _kernel([_REAL])
    assert _run_success_synthesis(k) == _REAL
    assert k.calls == 1


def _gather_item():
    summary = _tool_result_text()
    return SimpleNamespace(
        tool="search", description="look up who created Python",
        envelope=SimpleNamespace(summary=summary, error_type="", status="success"),
        node_record=None, footprint=None, result=summary,
    )


def test_the_deterministic_close_names_sources_never_their_raw_text():
    plan = SimpleNamespace(original_task="t", steps=[object()])
    queue = SimpleNamespace(items=[object()], failed_ids=[])

    out = AgentKernel._der_deterministic_success_summary(plan, [_gather_item()], queue)

    assert "--- Source:" not in out, out
    assert "en.wikipedia.org" in out, out
    # none of the page text leaks into the reply
    first_highlight = json.loads(_FIXTURE.read_text(encoding="utf-8"))["results"][0]["highlights"][0]
    assert first_highlight[:60] not in out, out


def test_non_source_evidence_is_untouched_by_the_source_dump_guard():
    assert AgentKernel._no_raw_source_dump("Written to zz_a.md") == "Written to zz_a.md"
    assert AgentKernel._no_raw_source_dump("") == ""

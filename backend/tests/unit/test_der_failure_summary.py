"""
Unit test for the deterministic (no-LLM) "task incomplete" summary (Part B).

When a research DER step fails and the LLM is rate-limited/unavailable, the
old path returned "" (silence). _der_deterministic_failure_summary guarantees
the user always gets a clear, actionable message naming the failed steps.
"""
import sys
import types

import pytest

from backend.agent import agent_kernel


class _Item:
    def __init__(self, step_id, description, result=""):
        self.step_id = step_id
        self.description = description
        self.result = result


class _Queue:
    def __init__(self, failed_ids, items):
        self.failed_ids = failed_ids
        self.items = items


class _Plan:
    original_task = "research the best laptops 2026"
    steps = [object(), object()]  # len used for total_steps


def test_deterministic_failure_summary_names_failed_steps():
    items = [
        _Item("s1", "Search the web for laptops", "no candidate urls"),
        _Item("s2", "Summarize findings", ""),
    ]
    queue = _Queue(failed_ids=["s1"], items=items)
    summary = agent_kernel.AgentKernel._der_deterministic_failure_summary(
        _Plan(), ["s2"], queue
    )
    assert "couldn't complete" in summary.lower()
    assert "Search the web for laptops" in summary
    assert "no candidate urls" in summary
    # No LLM call required -> returns a non-empty string even offline.
    assert summary.strip()


def test_deterministic_failure_summary_handles_empty_reason():
    items = [_Item("s9", "Do a thing", "")]
    queue = _Queue(failed_ids=["s9"], items=items)
    summary = agent_kernel.AgentKernel._der_deterministic_failure_summary(
        _Plan(), [], queue
    )
    assert "Do a thing" in summary
    assert summary.strip()

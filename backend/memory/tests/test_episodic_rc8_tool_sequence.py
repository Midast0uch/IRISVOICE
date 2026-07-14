"""RC8 — stop dropping tool_sequence in episodic context (Phase 0.2).

``assemble_episodic_context`` must surface the proven ``tool_sequence`` of
past successes so the planner can replay a known-good method instead of
re-deriving it. Verifies both the Mycelium path and the plain fallback path.
"""
import pytest
from types import SimpleNamespace

from backend.memory.episodic import EpisodicStore


def _make_store(mycelium=None, successes=None, failures=None):
    store = SimpleNamespace()
    store._mycelium = mycelium
    store.retrieve_similar = lambda task, limit=3, min_score=0.6: successes or []
    store.retrieve_failures = lambda task, limit=2: failures or []
    return store


def test_plain_path_includes_proven_sequence():
    seq = [{"tool": "read_file"}, {"tool": "run_command"}, {"tool": "write_file"}]
    store = _make_store(
        mycelium=None,
        successes=[{
            "task_summary": "resize image",
            "outcome_score": 0.9,
            "tool_sequence": seq,
        }],
    )
    ctx = EpisodicStore.assemble_episodic_context(store, "resize an image")
    assert "PROVEN SEQUENCE:" in ctx
    assert "read_file" in ctx
    assert "run_command" in ctx
    assert "write_file" in ctx


def test_mycelium_path_includes_proven_sequences():
    class FakeScorer:
        def format_context(self, successes, failures):
            return "RELEVANT PAST SUCCESSES:\n  - resize image (score: 0.9)"

    class FakeMycelium:
        resonance_scorer = FakeScorer()

    seq = [{"tool": "a"}, {"tool": "b"}]
    store = _make_store(
        mycelium=FakeMycelium(),
        successes=[{
            "task_summary": "resize image",
            "outcome_score": 0.9,
            "tool_sequence": seq,
        }],
    )
    ctx = EpisodicStore.assemble_episodic_context(store, "resize an image")
    assert "PROVEN SEQUENCES:" in ctx
    assert "a → b" in ctx


def test_no_sequence_does_not_emit_marker():
    store = _make_store(
        mycelium=None,
        successes=[{
            "task_summary": "resize image",
            "outcome_score": 0.9,
            "tool_sequence": [],
        }],
    )
    ctx = EpisodicStore.assemble_episodic_context(store, "resize an image")
    assert "PROVEN SEQUENCE" not in ctx

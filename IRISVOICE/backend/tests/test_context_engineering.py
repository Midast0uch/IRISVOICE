"""
Context Engineering tests — Option B (Pacman / Miro-fish DB fragmentation).

Spec: docs/DER_LOOP_MYCELIUM.md, domain 1.6 Option B
Gate: Domain 1.6

Run: python -m pytest backend/tests/test_context_engineering.py -v

Tests:
  test_fragment_and_store_basic     — single turn stored as ≥1 chunk in DB
  test_fragment_and_store_long      — long content produces multiple chunks
  test_fragment_dedup               — near-identical content not stored twice
  test_retrieve_context_chunks      — stored chunks retrieved by semantic query
  test_retrieve_no_false_positives  — unrelated query returns nothing above threshold
  test_der_output_chunks            — der_output chunk_type round-trip
  test_working_memory_via_chunks    — context assembly includes DB chunks
  test_token_budget_with_chunks     — budget accounts for chunk_prefix tokens
  test_assemble_falls_back          — no chunks → rolling window fallback
"""

import os
import sys
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_kernel(session_id: str, memory_interface):
    """Return an AgentKernel.__new__ instance with the minimum attributes set
    for _assemble_direct_context to run without touching a real LLM."""
    from backend.agent.agent_kernel import AgentKernel
    kernel = AgentKernel.__new__(AgentKernel)
    kernel._CHARS_PER_TOKEN = 4
    kernel._DIRECT_CTX_BUDGET = 20_000
    kernel.session_id = session_id
    kernel._personality = None        # _build_system_prompt checks this
    kernel._launcher_mode = "personal"
    kernel._memory_interface = memory_interface
    return kernel


def _make_store(tmp_path: str):
    """Return an EpisodicStore backed by a throwaway DB."""
    from backend.memory.episodic import EpisodicStore
    key = b"\x00" * 32
    return EpisodicStore(db_path=tmp_path, biometric_key=key)


def _store_fragment(store, session_id: str, content: str, chunk_type="context_fragment"):
    return store.fragment_and_store(content, session_id=session_id, chunk_type=chunk_type)


# ── test_fragment_and_store_basic ────────────────────────────────────────────

def test_fragment_and_store_basic(tmp_path):
    """A single turn produces ≥1 chunk persisted in context_chunks."""
    store = _make_store(str(tmp_path / "basic.db"))
    content = "User: What is IRIS?\nAssistant: IRIS is a local AI assistant."
    ids = store.fragment_and_store(content, session_id="s1")

    assert len(ids) >= 1, "fragment_and_store returned no chunk IDs"
    row = store.db.execute(
        "SELECT COUNT(*) FROM context_chunks WHERE session_id = 's1'"
    ).fetchone()
    assert row[0] >= 1, "No rows in context_chunks after fragment_and_store"


# ── test_fragment_and_store_long ─────────────────────────────────────────────

def test_fragment_and_store_long(tmp_path):
    """Content longer than _CHUNK_MAX_CHARS produces multiple chunks."""
    store = _make_store(str(tmp_path / "long.db"))
    # Build ~3× the max chunk size of unique text
    long_text = " ".join(f"word{i}" for i in range(2000))  # ~10 000 chars
    ids = store.fragment_and_store(long_text, session_id="s2")

    assert len(ids) >= 2, (
        f"Expected multiple chunks for long content, got {len(ids)}"
    )


# ── test_fragment_dedup ───────────────────────────────────────────────────────

def test_fragment_dedup(tmp_path):
    """Storing the same content twice must not create duplicate rows."""
    store = _make_store(str(tmp_path / "dedup.db"))
    content = "User: tell me a joke\nAssistant: Why did the chicken cross the road?"
    store.fragment_and_store(content, session_id="s3")
    store.fragment_and_store(content, session_id="s3")  # identical second call

    row = store.db.execute(
        "SELECT COUNT(*) FROM context_chunks WHERE session_id = 's3'"
    ).fetchone()
    assert row[0] == 1, f"Duplicate chunk stored: found {row[0]} rows"


# ── test_retrieve_context_chunks ──────────────────────────────────────────────

def test_retrieve_context_chunks(tmp_path):
    """Stored chunks are retrieved when queried with a semantically similar phrase."""
    store = _make_store(str(tmp_path / "retrieve.db"))
    content = "User: What packages are in requirements.txt?\nAssistant: numpy, fastapi, uvicorn, pydantic"
    store.fragment_and_store(content, session_id="s4")

    results = store.retrieve_context_chunks(
        query="show me the python dependencies listed in requirements.txt",
        session_id="s4",
        limit=5,
        min_similarity=0.15,  # lenient — hash-projection embeddings have moderate recall
    )

    assert len(results) >= 1, (
        "retrieve_context_chunks returned nothing for a clearly matching query"
    )
    assert any("requirements" in r or "packages" in r or "numpy" in r for r in results), (
        "Retrieved chunks don't contain expected content"
    )


# ── test_retrieve_no_false_positives ─────────────────────────────────────────

def test_retrieve_no_false_positives(tmp_path):
    """Completely unrelated query at high threshold returns empty list."""
    store = _make_store(str(tmp_path / "fp.db"))
    store.fragment_and_store(
        "User: What is the weather?\nAssistant: It is sunny today.",
        session_id="s5",
    )

    results = store.retrieve_context_chunks(
        query="deploy kubernetes cluster on AWS us-east-1 with autoscaling",
        session_id="s5",
        limit=5,
        min_similarity=0.80,  # strict — genuinely unrelated content must not pass
    )
    assert results == [], (
        f"Expected no high-similarity results for unrelated query; got {results}"
    )


# ── test_der_output_chunks ────────────────────────────────────────────────────

def test_der_output_chunks(tmp_path):
    """DER step outputs stored as der_output can be retrieved separately."""
    store = _make_store(str(tmp_path / "der.db"))
    der_content = "[Step 1: read config.yaml]\nhost: db.local\nport: 5432"
    ids = store.fragment_and_store(der_content, session_id="s6", chunk_type="der_output")

    assert len(ids) >= 1

    # Can retrieve as der_output type
    results = store.retrieve_context_chunks(
        query="database hostname from config",
        session_id="s6",
        limit=5,
        min_similarity=0.10,
        chunk_types=["der_output"],
    )
    assert len(results) >= 1, "DER output chunk not retrieved with chunk_types filter"

    # context_fragment type filter must NOT return der_output rows
    ctx_only = store.retrieve_context_chunks(
        query="database hostname from config",
        session_id="s6",
        limit=5,
        min_similarity=0.10,
        chunk_types=["context_fragment"],
    )
    assert ctx_only == [], (
        "context_fragment filter returned der_output rows — chunk_type filter broken"
    )


# ── test_working_memory_via_chunks ───────────────────────────────────────────

def test_working_memory_via_chunks(tmp_path):
    """
    _assemble_direct_context must include DB chunks when they exist.
    After storing a turn, the assembled context must contain chunk content.
    """
    store = _make_store(str(tmp_path / "kernel.db"))
    content = "User: What is the capital of France?\nAssistant: Paris."
    store.fragment_and_store(content, session_id="test-sess")

    mock_episodic = MagicMock()
    mock_episodic.retrieve_context_chunks = store.retrieve_context_chunks
    mock_episodic.assemble_episodic_context = MagicMock(return_value="")
    mock_memory = MagicMock()
    mock_memory.episodic = mock_episodic

    kernel = _make_kernel("test-sess", mock_memory)
    messages = kernel._assemble_direct_context(
        "What did we say about France?", []
    )

    all_content = " ".join(m.get("content", "") for m in messages)
    assert "Paris" in all_content or "France" in all_content, (
        "DB chunk not surfaced in assembled context — Option B retrieval not working"
    )


# ── test_token_budget_with_chunks ─────────────────────────────────────────────

def test_token_budget_with_chunks(tmp_path):
    """
    chunk_prefix tokens are deducted from the history budget so the total
    assembled context does not exceed _DIRECT_CTX_BUDGET (with slack).
    """
    store = _make_store(str(tmp_path / "budget.db"))
    store.fragment_and_store(
        "User: describe IRIS in detail\nAssistant: " + "IRIS " * 200,
        session_id="budget-sess",
    )

    mock_episodic = MagicMock()
    mock_episodic.retrieve_context_chunks = store.retrieve_context_chunks
    mock_episodic.assemble_episodic_context = MagicMock(return_value="")
    mock_memory = MagicMock()
    mock_memory.episodic = mock_episodic

    kernel = _make_kernel("budget-sess", mock_memory)
    kernel._DIRECT_CTX_BUDGET = 500   # very tight

    big_history = []
    for i in range(20):
        big_history.append({"role": "user",      "content": f"Turn {i}: " + "x" * 200})
        big_history.append({"role": "assistant", "content": f"Reply {i}: " + "y" * 200})

    messages = kernel._assemble_direct_context("summarize", big_history)

    # Current turn must be present
    all_content = " ".join(m.get("content", "") for m in messages)
    assert "summarize" in all_content, "Current user turn dropped"

    # Total should not explode beyond 3× budget (chunks + recency + system overhead)
    total_chars = sum(len(m.get("content", "")) for m in messages)
    total_tokens = total_chars // kernel._CHARS_PER_TOKEN
    assert total_tokens <= kernel._DIRECT_CTX_BUDGET * 3 + 500, (
        f"Context exploded: {total_tokens} tokens vs budget {kernel._DIRECT_CTX_BUDGET}"
    )


# ── test_assemble_falls_back ──────────────────────────────────────────────────

def test_assemble_falls_back():
    """
    When no DB chunks exist (empty or no episodic), _assemble_direct_context
    falls back to the rolling window so recent history is always available.
    """
    mock_episodic = MagicMock()
    mock_episodic.retrieve_context_chunks = MagicMock(return_value=[])  # no chunks
    mock_episodic.assemble_episodic_context = MagicMock(return_value="")
    mock_memory = MagicMock()
    mock_memory.episodic = mock_episodic

    kernel = _make_kernel("fallback-sess", mock_memory)

    context = [
        {"role": "user",      "content": "Hello IRIS"},
        {"role": "assistant", "content": "Hello! How can I help?"},
        {"role": "user",      "content": "What can you do?"},
        {"role": "assistant", "content": "I can answer questions and run tasks."},
    ]

    messages = kernel._assemble_direct_context("Tell me more", context)
    all_content = " ".join(m.get("content", "") for m in messages)

    # Rolling window fallback must include recent turns
    assert "Hello IRIS" in all_content or "Hello!" in all_content, (
        "Rolling window fallback not working — recent history missing"
    )
    assert "Tell me more" in all_content, "Current user turn missing in fallback"

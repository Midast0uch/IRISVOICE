"""CT-W10-6 (T44, REQ-12 AC7 / REQ-6 AC1b/AC2): the memory bench measures the
path the app actually runs.

Four defects were found in ``evals/memory_bench.py`` (2026-10-29 audit):

1. ``WHERE embedding IS NOT NULL OR vec_i8 IS NOT NULL`` was concatenated with
   ``AND folded_into IS NULL`` without parentheses, so SQL precedence made the
   fold filter apply to only the second arm - folded rows stayed in the pool.
2. ``ceiling_by_m`` reused the DEFAULT (M=1000) candidate list for the M=200
   point, so the curve was flat and understated a smaller scan.
3. The candidate union left out the exact-word (FTS) leg, so ``recall@10_live``
   understated what the model receives.
4. The delivered order left out the single reserved keyword slot.

Each test below drives the module's real helpers on a real temp store and fails
on the pre-T44 code.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BENCH_PATH = _REPO_ROOT / "evals" / "memory_bench.py"


def _load_bench():
    spec = importlib.util.spec_from_file_location("iris_memory_bench_ct_w10_6", _BENCH_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {_BENCH_PATH}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bench():
    return _load_bench()


def _chunk_table(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE context_chunks ("
        "id INTEGER PRIMARY KEY, session_id TEXT, chunk_type TEXT, zone TEXT, "
        "content TEXT, embedding BLOB, retrieval_count INTEGER, timestamp TEXT, "
        "embedding_backend TEXT, tool_name TEXT, vec_fp BLOB, vec_i8 BLOB, "
        "vec_scale REAL, folded_into INTEGER)"
    )


def _vec(bench) -> bytes:
    from backend.memory import vector_quant

    return np.zeros(vector_quant.DIM, dtype="<f4").tobytes()


def test_fold_filter_binds_to_both_arms_of_the_vector_test(bench, tmp_path):
    """The parens defect: a folded row with a vector must not be loaded."""
    con = sqlite3.connect(str(tmp_path / "c.db"))
    _chunk_table(con)
    v = _vec(bench)
    con.execute(
        "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content, "
        "embedding, retrieval_count, timestamp, embedding_backend, folded_into) "
        "VALUES (1, 's', 'context_fragment', 'trusted', 'see abcdef12.py once', ?, 0, "
        "'2026-10-01T00:00:00', 'e5', 99)",
        (v,),
    )
    con.execute(
        "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content, "
        "embedding, retrieval_count, timestamp, embedding_backend, folded_into) "
        "VALUES (2, 's', 'context_fragment', 'trusted', 'the live row', ?, 0, "
        "'2026-10-02T00:00:00', 'e5', NULL)",
        (v,),
    )
    con.commit()

    ids, _meta, _mat = bench._load(con)
    assert ids.tolist() == [2], "a folded row leaked into the bench pool (missing parens)"

    # The exact-word case set must not be built from a folded row either.
    assert bench._words_cases(con, limit=40) == []


def test_candidate_union_carries_the_exact_word_leg(bench, tmp_path):
    """A row only the FTS leg can find must still reach the candidate set."""
    from backend.memory import chunk_fts

    con = sqlite3.connect(str(tmp_path / "k.db"))
    _chunk_table(con)
    assert chunk_fts.ensure_schema(con) is True
    con.execute(
        "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content, "
        "retrieval_count, timestamp, embedding_backend) VALUES "
        "(7, 's', 'context_fragment', 'trusted', 'the zebra protocol is documented', "
        "0, '2026-10-01T00:00:00', 'e5')"
    )
    con.commit()

    class _NoFingerprint:
        def candidates(self, *a, **k):
            return []

    pos = {7: 0}
    cand, kw = bench._candidate_union(
        con, "zebra protocol", _NoFingerprint().candidates(con, None, None),
        None, {}, [], pos)
    assert kw == {7}, "the bench did not run the exact-word leg"
    assert 0 in cand, "a keyword-only hit never reached the candidate set"


def test_delivered_order_reserves_exactly_one_keyword_slot(bench):
    """One keyword hit below the cut takes the last slot; never two slots."""
    ids = np.arange(100, 112)
    sims = np.linspace(1.0, 0.0, 12).astype(np.float32)
    rec = np.zeros(12, dtype=np.float32)
    cand = set(range(12))

    one = bench._live_top(cand, {111}, ids, sims, rec)
    assert 11 in one and one.index(11) == 9, "the reserved slot was not applied"

    two = bench._live_top(cand, {110, 111}, ids, sims, rec)
    assert len({i for i in two if i in (10, 11)}) == 1, "two keyword slots were taken"


def test_ceiling_asks_for_the_m_of_the_point(bench, tmp_path):
    """ceiling_by_m must pass m=_m, not reuse the default list for M=200."""
    seen = []

    class _Recording:
        def candidates(self, con, vec, backend, session_id=None,
                       chunk_types=None, zones=None, m=None):
            seen.append(m)
            return []

    class _Query:
        vector = np.zeros(4, dtype=np.float32)
        backend = "e5"

    sims = np.array([1.0, 0.5], dtype=np.float32)
    bench._ceiling_at(_Recording(), None, _Query(), None, {}, [], {}, sims, {0}, 200)
    assert seen == [200], f"the M=200 point asked for M={seen[0]}"

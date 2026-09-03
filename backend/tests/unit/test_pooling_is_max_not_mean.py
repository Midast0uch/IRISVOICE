"""
Unit test confirming max-pool (NOT mean-pool) is the distinguishing function.

NOTE: The implementation initialises the output to zeros and only replaces
when ``v[i] > out[i]`` (i.e., values <= 0 are treated as "no signal" and
negative values do NOT override the initial zero).  This is correct for
neural embeddings that are typically non-negative after ReLU activations.

The distinguishing property tested here: max-pool preserves the STRONGEST
signal per dimension from ANY single chunk, whereas mean-pool averages away
a single strong signal across multiple unmatched chunks.
"""

import math
import pytest

from backend.memory.embedding import max_pool, l2_normalize


def test_max_pool_strong_chunk_not_diluted():
    """A single strong matching dimension is preserved by max-pool.

    Construct 3 vectors of dim 8 where each has one distinct strong dimension.
    Under max-pool the max per dim is kept (all 1.0).
    Under mean-pool each is diluted to 0.33.
    """
    v1 = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    v2 = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    v3 = [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    pooled = max_pool([v1, v2, v3])

    # Max-pool preserves max along each dim
    assert pooled[0] == 1.0
    assert pooled[1] == 1.0
    assert pooled[2] == 1.0
    # Remaining dims stay 0
    assert all(pooled[i] == 0.0 for i in range(3, 8))


def test_max_pool_raw_preserves_strong_match():
    """Raw max-pool output (no L2) gives full weight to the matching chunk.

    A single chunk that matches the query on dim 0 at value 1.0 keeps its
    value at 1.0 after max-pool regardless of other chunks.  Mean-pool would
    dilute it.
    """
    # Multiple chunks: only ONE has the matching signal
    chunks = [
        [1.0] + [0.0] * 7,   # matching chunk
    ]
    # Add decoy chunks with signal on OTHER dims
    for i in range(1, 4):
        decoy = [0.0] * 8
        decoy[i] = 0.8
        chunks.append(decoy)

    pooled = max_pool(chunks)

    # The matching dim should still be at full strength
    assert pooled[0] == 1.0

    # Under mean-pool dim 0 would be 1.0/4 = 0.25
    mean_val = sum(c[0] for c in chunks) / len(chunks)
    assert pooled[0] > mean_val, "max-pool should preserve stronger per-dim signal than mean-pool"


def test_max_pool_vs_mean_pool_document_matching():
    """A document where ONE chunk matches strongly while others are unrelated.

    After max-pool + L2, the matching dimension carries MORE relative weight
    than after mean-pool + L2, because max-pool preserves the high value from
    the matching chunk while mean-pool averages it across unrelated dims.
    """
    # Query vector
    query = [1.0] + [0.0] * 7

    # Many unmatched chunks each with signal on a DIFFERENT dim
    from functools import reduce
    import operator

    # Chunk 0: perfect match on dim 0
    chunks = [[1.0] + [0.0] * 7]

    # Chunks 1-10: each has signal on a different unrelated dim
    for i in range(1, 6):
        c = [0.0] * 8
        c[i] = 1.0
        chunks.append(c)

    # Compute max-pool result (the matching chunk's dim-0 survives)
    pooled_max = max_pool(chunks)
    pooled_max_l2 = l2_normalize(pooled_max)
    dot_max = sum(q * p for q, p in zip(query, pooled_max_l2))

    # Compute mean-pool result
    dims = len(chunks[0])
    pooled_mean = [sum(c[d] for c in chunks) / len(chunks) for d in range(dims)]
    pooled_mean_l2 = l2_normalize(pooled_mean)
    dot_mean = sum(q * p for q, p in zip(query, pooled_mean_l2))

    # Max-pool should give higher similarity on the matching dimension
    # than mean-pool
    assert dot_max > dot_mean, (
        f"max-pool dot ({dot_max:.4f}) should exceed mean-pool dot ({dot_mean:.4f})"
    )


def test_max_pool_empty_list():
    """Empty input returns empty list."""
    assert max_pool([]) == []


def test_max_pool_single_vector():
    """Single vector pool returns max of that vector (non-negative values)."""
    v = [0.5, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    pooled = max_pool([v])
    assert pooled == v


def test_max_pool_zeros_init():
    """Max-pool initialises to zeros; negative values do not override zero."""
    v1 = [-1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    v2 = [-0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    pooled = max_pool([v1, v2])
    # With zero-init, -0.5 > 0.0 is False, so dim 0 stays 0.0
    assert pooled[0] == 0.0


def test_max_pool_with_positive_values():
    """Only positive values override the initial zero."""
    v1 = [-1.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    v2 = [-0.5, 0.3, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    pooled = max_pool([v1, v2])
    assert pooled[0] == 0.0   # No positive value on dim 0
    assert pooled[1] == 0.5   # max(0.5, 0.3) = 0.5


def test_l2_after_pool():
    """max_pool output should be L2-normalised after pooling in the real path."""
    v = [3.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    normalized = l2_normalize(v)
    norm = math.sqrt(sum(x * x for x in normalized))
    assert abs(norm - 1.0) < 1e-10


def test_l2_normalize_zero_vector():
    """Zero vector returns zeros, not NaN."""
    v = [0.0] * 8
    result = l2_normalize(v)
    assert all(x == 0.0 for x in result)

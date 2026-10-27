"""The compact recall forms of a chunk vector (specs/memory-recall-reach REQ-4 AC1).

Today a chunk's vector is 4,096 bytes of float32 - 52% of the store. Two smaller
forms say the same thing for recall:

* FINGERPRINT - 128 bytes, one bit per dimension (the sign). It is the index
  (``recall_reach`` scans it). It is STORED, never re-derived from the code: a
  component smaller than half a quantisation step rounds to zero and loses its
  sign, so re-deriving would move ~0.4% of the bits.
* INT8 CODE - 1,024 bytes plus one float scale, symmetric per-vector:
  ``q = round(v / max|v| * 127)``. Restoring gives ``q * scale / 127``.

Why symmetric: cosine only needs the DIRECTION. The scale cancels in the dot
product, so the quantisation error is a fixed ~1/127 of the largest component
instead of depending on the mean magnitude.

``vector_of`` is the one reader: it returns the float vector from whichever form
is present, so a caller keeps working after the float is dropped (AC1 keeps the
float only while the bench shows int8 loses more than 0.02 recall@10 for that
chunk type).
"""
from __future__ import annotations

from typing import Optional, Tuple

FP_BYTES = 128
I8_BYTES = 1024
DIM = I8_BYTES


def fingerprint(vec) -> Optional[bytes]:
    """128-byte sign bitmap of a 1024-dim vector (None if the shape is wrong)."""
    import numpy as np

    arr = np.asarray(vec, dtype=np.float32)
    if arr.shape != (DIM,) or not np.all(np.isfinite(arr)):
        return None
    return np.packbits(arr > 0).tobytes()


def compress(vec) -> Tuple[Optional[bytes], Optional[bytes], Optional[float]]:
    """``(fingerprint, int8 code, scale)``. All three are None for a bad vector.

    A zero vector keeps a valid (all-ones) fingerprint and a zero code, so the
    row stays scannable and scores 0 - it does not disappear from recall.
    """
    import numpy as np

    arr = np.asarray(vec, dtype=np.float32)
    fp = fingerprint(arr)
    if fp is None:
        return None, None, None
    scale = float(np.abs(arr).max()) if arr.size else 0.0
    if not scale or not np.isfinite(scale):
        return fp, bytes(I8_BYTES), 0.0
    q = np.clip(np.rint(arr / scale * 127.0), -127.0, 127.0).astype(np.int8)
    return fp, q.tobytes(), scale


def decompress(code, scale) -> Optional["object"]:
    """The float32 vector a stored int8 code stands for (None if unusable)."""
    import numpy as np

    if not code or len(code) != I8_BYTES:
        return None
    try:
        s = float(scale or 0.0)
    except (TypeError, ValueError):
        return None
    if not s or not np.isfinite(s):
        return np.zeros(DIM, dtype=np.float32)
    q = np.frombuffer(code, dtype=np.int8).astype(np.float32)
    return q * (s / 127.0)


def float_of(blob) -> Optional["object"]:
    """A float32 vector from a packed float blob (1024 dims = 4,096 bytes).

    Any length that is a multiple of 4 is read as floats: a store from an older
    backend (768 dims) keeps its rows scored instead of silently losing them.
    """
    import numpy as np

    if not blob or len(blob) % 4:
        return None
    return np.frombuffer(blob, dtype="<f4")


def vector_of(emb_blob, i8_blob=None, scale=None) -> Optional[list]:
    """The stored vector, from the int8 code when the float is gone (AC1).

    Returns a Python list on purpose: the answer path's cosine walks the vector
    element by element, and a list of floats is ~2x faster there than a numpy
    view of the same numbers.
    """
    vec = float_of(emb_blob)
    if vec is not None:
        return vec.tolist()
    back = decompress(i8_blob, scale)
    return back.tolist() if back is not None else None


def bytes_per_row() -> dict:
    """What one chunk's recall forms cost, for the bench and the standard."""
    return {"fingerprint": FP_BYTES, "int8": I8_BYTES + 8, "total": FP_BYTES + I8_BYTES + 8}

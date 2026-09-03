"""
Tests for LocalModelManager.parse_gguf_metadata — GGUF header parser.

Covers:
  - Basic standard-enum parse (architecture / params_b / context_length / block_count).
  - GAP 2: a single unparseable key must NOT discard every key after it. The
    parse must not crash, must retain keys parsed before the bad key, and must
    mark the result ``_partial`` (the old code did a bare ``break`` and set
    nothing — so the ``_partial`` assertion FAILS on the pre-fix code).
  - GAP 2: a recoverable weird value (type-4 with an unreasonable length prefix)
    must let the loop CONTINUE so subsequent keys are still parsed.
  - GAP 3: architecture sanity detection — garbage/non-sane architecture must not
    crash; a standard file parses with a sane architecture; non-standard numeric
    values are still read via the auto heuristic.

These are behavioral tests built from hand-constructed GGUF byte buffers, so they
exercise the real parser without needing a model file.
"""

import struct
import tempfile
from pathlib import Path

from backend.agent.local_model_manager import LocalModelManager


def _enc_str(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<Q", len(b)) + b


def _enc_kv(key: str, vtype: int, value: bytes) -> bytes:
    return _enc_str(key) + struct.pack("<I", vtype) + value


def _build_gguf(kvs, version: int = 3, tensor_count: int = 0) -> bytes:
    buf = b"GGUF" + struct.pack("<I", version)
    buf += struct.pack("<Q", tensor_count) + struct.pack("<Q", len(kvs))
    for key, vtype, vb in kvs:
        buf += _enc_kv(key, vtype, vb)
    return buf


def _write_tmp(buf: bytes) -> Path:
    p = Path(tempfile.mkdtemp()) / "model.gguf"
    p.write_bytes(buf)
    return p


# GGUF value types (standard enum)
T_STRING = 4
T_UINT32 = 0
T_ARRAY = 8


def test_basic_standard_parse():
    """A normal standard-enum GGUF parses all expected fields."""
    kvs = [
        ("general.architecture", T_STRING, _enc_str("llama")),
        ("general.parameter_count", T_UINT32, struct.pack("<I", 2_000_000_000)),
        ("general.name", T_STRING, _enc_str("Test-7B")),
        ("llama.context_length", T_UINT32, struct.pack("<I", 32768)),
        ("llama.block_count", T_UINT32, struct.pack("<I", 32)),
    ]
    meta = LocalModelManager().parse_gguf_metadata(_write_tmp(_build_gguf(kvs)))
    assert meta.get("architecture") == "llama", meta
    assert meta.get("params_b") == 2.0, meta
    assert meta.get("context_length") == 32768, meta
    assert meta.get("block_count") == 32, meta
    assert meta.get("_partial") is not True, "clean parse should not be partial"


def test_gap2_unparseable_key_marks_partial_and_retains_prior():
    """GAP 2: an unknown value type in the MIDDLE must not discard everything.

    Proven-failable: the pre-fix code did ``except Exception: break`` and set
    nothing, so ``meta['_partial']`` would be absent -> this assertion FAILS on
    the old code.
    """
    kvs = [
        ("general.architecture", T_STRING, _enc_str("llama")),   # parsed OK
        ("broken.key", 99, struct.pack("<I", 1)),                # unknown vtype -> stop
        ("llama.context_length", T_UINT32, struct.pack("<I", 32768)),  # after bad key
    ]
    meta = LocalModelManager().parse_gguf_metadata(_write_tmp(_build_gguf(kvs)))
    # Key before the bad one is retained:
    assert meta.get("architecture") == "llama", meta
    # Result is marked partial (the fix):
    assert meta.get("_partial") is True, f"expected _partial marker, got {meta}"
    # Key after an unsizable bad value is unrecoverable -> not parsed (correct):
    assert "context_length" not in meta, meta


def test_gap2_recoverable_weird_value_continues():
    """GAP 2: a recoverable weird value must let the loop CONTINUE so later
    keys are still parsed (one bad key must not discard every key after it)."""
    # type-4 value whose 4 bytes look like a UINT32 (unreasonable as a string
    # length) -> auto heuristic falls back to UINT32 and the loop continues.
    weird = struct.pack("<I", 32768)
    kvs = [
        ("general.architecture", T_STRING, _enc_str("llama")),
        ("weird.key", T_STRING, weird),
        ("llama.context_length", T_UINT32, struct.pack("<I", 32768)),
    ]
    meta = LocalModelManager().parse_gguf_metadata(_write_tmp(_build_gguf(kvs)))
    assert meta.get("architecture") == "llama", meta
    # The key AFTER the weird value is still parsed -> loop continued:
    assert meta.get("context_length") == 32768, meta


def test_gap3_sane_architecture_detection():
    """GAP 3: a standard file yields a sane architecture and parses cleanly."""
    kvs = [("general.architecture", T_STRING, _enc_str("qwen2"))]
    meta = LocalModelManager().parse_gguf_metadata(_write_tmp(_build_gguf(kvs)))
    assert meta.get("architecture") == "qwen2"
    assert meta.get("_partial") is not True


def test_gap3_nonsane_architecture_does_not_crash():
    """GAP 3: an architecture that auto reads as a non-sane value (non-printable
    garbage from a misread) must not raise — detection retries both enums and the
    parser returns a dict, staying resilient."""
    # type-4 value that auto reads as a 3-byte non-printable string -> non-sane ->
    # retry standard/non_standard -> fall back to auto result without crashing.
    value = struct.pack("<Q", 3) + b"\x01\x02\x03"
    kvs = [("general.architecture", T_STRING, value)]
    meta = LocalModelManager().parse_gguf_metadata(_write_tmp(_build_gguf(kvs)))
    assert isinstance(meta, dict)


def test_gap3_nonstandard_numeric_read_via_auto():
    """GAP 3: a non-standard numeric value (type-4 UINT32) is still read by the
    auto heuristic, so params_b is computed correctly."""
    kvs = [
        ("general.architecture", T_STRING, _enc_str("llama")),
        ("general.parameter_count", T_STRING, struct.pack("<I", 3_000_000_000)),
    ]
    meta = LocalModelManager().parse_gguf_metadata(_write_tmp(_build_gguf(kvs)))
    assert meta.get("params_b") == 3.0, meta

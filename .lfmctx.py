"""Throwaway: the LFM 2.6B's own max context vs what the app asks for.

Reads the GGUF header (no model load) for the architecture keys, then prints the
app's profile ceilings and the VRAM the machine currently has.
"""
from __future__ import annotations

import struct

PATH = (
    r"C:\Users\midas\.lmstudio\models\LiquidAI\LFM2.5-2.6B-GGUF"
    r"\LFM2.5-2.6B-QAD-Q4_0.gguf"
)
SCALARS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?",
           10: "q", 11: "Q", 12: "d"}
SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}


def rstr(f):
    (n,) = struct.unpack("<Q", f.read(8))
    return f.read(n).decode("utf-8", "replace")


def rval(f, t):
    if t == 8:
        return rstr(f)
    if t == 9:
        (et,) = struct.unpack("<I", f.read(4))
        (cnt,) = struct.unpack("<Q", f.read(8))
        vals = [rval(f, et) for _ in range(cnt)]
        return f"<array count={cnt} first={vals[0]!r}>" if cnt > 8 else vals
    return struct.unpack("<" + SCALARS[t], f.read(SIZES[t]))[0]


keys = {}
with open(PATH, "rb") as fh:
    assert fh.read(4) == b"GGUF"
    struct.unpack("<I", fh.read(4))
    struct.unpack("<Q", fh.read(8))
    (kv,) = struct.unpack("<Q", fh.read(8))
    for _ in range(kv):
        k = rstr(fh)
        (t,) = struct.unpack("<I", fh.read(4))
        v = rval(fh, t)
        if ("context" in k or "block_count" in k or "attention" in k
                or "embedding_length" in k):
            keys[k] = v

for k, v in keys.items():
    print(f"{k} = {v}")

from backend.agent.local_model_manager import MAX_CTX, MIN_CTX, PROFILES  # noqa: E402

print(f"\napp MIN_CTX={MIN_CTX} MAX_CTX={MAX_CTX}")
for name, prof in (PROFILES or {}).items():
    print(f"  profile {name:10} n_ctx={prof.get('n_ctx')} kv={prof.get('cache_type_k')}")

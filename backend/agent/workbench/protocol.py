"""Workbench protocol v1: JSON lines, one frame per line, UTF-8.

Pure and stdlib-only; no I/O. The child (`worker.py`) cannot import this file
(it is stdlib-only and shipped as a data file), so it repeats the constants;
the contract test pins both against the golden frames.

Request frames carry `op`; reply frames carry `re` (the op they answer).

  hello     {"v":1,"op":"hello"}
  exec      {"v":1,"op":"exec","id":int,"code":str,"timeout_s":number}
  inspect   {"v":1,"op":"inspect","id":int,"expr":str,"offset":int,"limit":int}
  put       {"v":1,"op":"put","id":int,"name":str,"value":<json>}
  shutdown  {"v":1,"op":"shutdown"}

  hello reply    {"v":1,"re":"hello","ok":true,"version":1,"incarnation":hex}
  exec reply     {"v":1,"re":"exec","id","ok","stdout","stderr","value",
                  "error":null|{"type","message","trace_tail"},
                  "vars":[{"name","type","size","preview"}],"kept":[{"name","note"}],
                  "wall_ms","truncated","incarnation"}
  inspect reply  {"v":1,"re":"inspect","id","ok","text","total","error","incarnation"}
  put reply      {"v":1,"re":"put","id","ok","error","incarnation"}
  shutdown reply {"v":1,"re":"shutdown","ok":true}
"""
import json

PROTOCOL_VERSION = 1

OPS = ("hello", "exec", "inspect", "put", "shutdown")

# Required keys per op, besides "v" and the discriminator ("op" / "re").
REQUEST_KEYS = {
    "hello": (),
    "exec": ("id", "code", "timeout_s"),
    "inspect": ("id", "expr", "offset", "limit"),
    "put": ("id", "name", "value"),
    "shutdown": (),
}
REPLY_KEYS = {
    "hello": ("ok", "version", "incarnation"),
    "exec": ("id", "ok", "stdout", "stderr", "value", "error", "vars", "kept",
             "wall_ms", "truncated", "incarnation"),
    "inspect": ("id", "ok", "text", "total", "error", "incarnation"),
    "put": ("id", "ok", "error", "incarnation"),
    "shutdown": ("ok",),
}


class ProtocolError(ValueError):
    """A frame is malformed, names an unknown op, or has another version."""


def encode(frame: dict) -> bytes:
    """One JSON line, UTF-8, newline-terminated. ASCII-escaped, so no raw newline."""
    if not isinstance(frame, dict):
        raise ProtocolError("frame must be a dict")
    return json.dumps(frame, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n"


def decode(data: bytes) -> dict:
    """Parse and validate one frame (request or reply)."""
    try:
        frame = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError(f"not a JSON frame: {exc}") from exc
    if not isinstance(frame, dict):
        raise ProtocolError("frame is not an object")
    if frame.get("v") != PROTOCOL_VERSION:
        raise ProtocolError(f"protocol version mismatch: got {frame.get('v')!r}, want {PROTOCOL_VERSION}")
    if "op" in frame:
        op, table, kind = frame["op"], REQUEST_KEYS, "request"
    elif "re" in frame:
        op, table, kind = frame["re"], REPLY_KEYS, "reply"
    else:
        raise ProtocolError("frame has neither 'op' nor 're'")
    if op not in table:
        raise ProtocolError(f"unknown op {op!r}")
    missing = [k for k in table[op] if k not in frame]
    if missing:
        raise ProtocolError(f"{kind} {op!r} missing keys: {missing}")
    return frame

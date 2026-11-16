"""Workbench protocol v2: JSON lines, one frame per line, UTF-8.

Pure and stdlib-only; no I/O. The child (`worker.py`) cannot import this file
(it is stdlib-only and shipped as a data file), so it repeats the constants;
the contract test pins both against the golden frames.

Request frames carry `op`; reply frames carry `re` (the op they answer); a worker
event during an exec carries `ev`. v2 adds the check and the callbacks (frames of
v1 stay valid: `check` is optional, and decode accepts "v" 1 or 2).

  hello     {"v":1,"op":"hello"}
  exec      {"v":1,"op":"exec","id":int,"code":str,"timeout_s":number[,"check":str]}
  inspect   {"v":1,"op":"inspect","id":int,"expr":str,"offset":int,"limit":int}
  put       {"v":1,"op":"put","id":int,"name":str,"value":<json>}
  shutdown  {"v":1,"op":"shutdown"}
  result    {"v":2,"op":"result","id":int,"seq":int,"ok":bool,"value":<json>,"error":null|str}
            (the parent's answer to a `call` event of the exec `id`)

  call      {"v":2,"ev":"call","id":int,"seq":int,"tool":str,"args":{...}}
            (worker -> parent, while exec `id` runs: `tools.<name>(**args)` in the
            script. The worker blocks for the matching `result`. At most 24 per exec.)

  hello reply    {"v":1,"re":"hello","ok":true,"version":1,"incarnation":hex}
  exec reply     {"v":1,"re":"exec","id","ok","stdout","stderr","value",
                  "error":null|{"type","message","trace_tail"},
                  "vars":[{"name","type","size","preview"}],
                  "wall_ms","truncated","out_n","incarnation"[,"check":{"ok":bool,"error":null|str}]}
                  ("check" only when the request carried one; if the body raised, the
                  check is not run: {"ok":false,"error":"body raised"})
  inspect reply  {"v":1,"re":"inspect","id","ok","text","total","error","incarnation"}
  put reply      {"v":1,"re":"put","id","ok","error","incarnation"}
  shutdown reply {"v":1,"re":"shutdown","ok":true}
  error reply    {"v":1,"re":"error","ok":false,"error":{"type","message","trace_tail"}}
                 (the worker could not read or run a request frame; it keeps running)
"""
import json

PROTOCOL_VERSION = 2
SUPPORTED_VERSIONS = (1, 2)

OPS = ("hello", "exec", "inspect", "put", "shutdown")

# Required keys per op, besides "v" and the discriminator ("op" / "re").
REQUEST_KEYS = {
    "hello": (),
    "exec": ("id", "code", "timeout_s"),
    "inspect": ("id", "expr", "offset", "limit"),
    "put": ("id", "name", "value"),
    "shutdown": (),
    "result": ("id", "seq", "ok", "value", "error"),
}
EVENT_KEYS = {
    "call": ("id", "seq", "tool", "args"),
}
REPLY_KEYS = {
    "hello": ("ok", "version", "incarnation"),
    "exec": ("id", "ok", "stdout", "stderr", "value", "error", "vars",
             "wall_ms", "truncated", "out_n", "incarnation"),
    "inspect": ("id", "ok", "text", "total", "error", "incarnation"),
    "put": ("id", "ok", "error", "incarnation"),
    "shutdown": ("ok",),
    "error": ("ok", "error"),
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
    if frame.get("v") not in SUPPORTED_VERSIONS:
        raise ProtocolError(f"protocol version mismatch: got {frame.get('v')!r}, want {PROTOCOL_VERSION}")
    if "op" in frame:
        op, table, kind = frame["op"], REQUEST_KEYS, "request"
    elif "ev" in frame:
        op, table, kind = frame["ev"], EVENT_KEYS, "event"
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

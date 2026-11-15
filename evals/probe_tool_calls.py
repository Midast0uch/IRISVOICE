"""Does the model on a llama-server port return STRUCTURED tool calls? (CLM T2.8 pre-check)

    python evals/probe_tool_calls.py [--port 8091] [--model NAME]

The node loop (node_executor.run_node) needs `message.tool_calls` with a function name and
JSON arguments in the OpenAI shape - IRIS reads nothing else (inference/transport.py,
`_msg.get("tool_calls")`). Whether a GGUF gives that depends on its embedded chat template
and the llama-server's tool-call parser, which only a real request shows. This sends three
requests and prints, per request, whether the call came back structured and whether its
`path` is the one the prompt named (the 2.6B model invented paths in the 2026-10-08 live
test, specs/phonon2-d1-model-swap/VERIFY.md T2.5). It also prints the server's real n_ctx
(GET /props), the number the router's window must agree with.

Exit 0 when every probe returned a structured, correct call; 1 otherwise. Read-only against
the server; loads nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

TOOLS = [
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a file. Optional start_line/end_line (1-based).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "list_directory", "description": "List a folder.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
]
SYSTEM = "You work inside the project folder ./ . Call a tool whenever you need file contents. Use only paths the user gave."

PROBES = [
    ("read one named file", "Read service-logs/svc-01.txt and tell me its first line.",
     "read_file", lambda a: "service-logs/svc-01.txt" in str(a.get("path", "")).replace("\\", "/")),
    ("read a line range", "Read lines 10 to 20 of kv/shard-03.kv.",
     "read_file", lambda a: "kv/shard-03.kv" in str(a.get("path", "")).replace("\\", "/")
     and int(a.get("start_line") or 0) == 10 and int(a.get("end_line") or 0) == 20),
    ("list a folder", "What files are in the reports folder?",
     "list_directory", lambda a: "reports" in str(a.get("path", ""))),
]


def _post(url: str, body: dict, timeout: float = 180.0) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--model", default="local-model")
    a = ap.parse_args()
    base = f"http://127.0.0.1:{a.port}"
    try:
        with urllib.request.urlopen(base + "/props", timeout=10) as r:
            props = json.loads(r.read())
        print("server n_ctx:", (props.get("default_generation_settings") or {}).get("n_ctx"))
    except Exception as exc:  # noqa: BLE001 - a probe reports, never raises
        print(f"note: /props unavailable ({exc!r})")
    bad = 0
    for name, prompt, want_tool, check in PROBES:
        try:
            res = _post(base + "/v1/chat/completions", {
                "model": a.model, "temperature": 0.2, "max_tokens": 256, "tools": TOOLS,
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]})
            msg = (res.get("choices") or [{}])[0].get("message") or {}
            calls = msg.get("tool_calls") or []
            if not calls:
                print(f"FAIL {name}: no structured tool_calls; content head: {str(msg.get('content'))[:120]!r}")
                bad += 1
                continue
            fn = calls[0].get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = None
            ok = fn.get("name") == want_tool and isinstance(args, dict) and check(args)
            print(f"{'ok  ' if ok else 'FAIL'} {name}: {fn.get('name')}({json.dumps(args)}) "
                  f"prompt_tokens={(res.get('usage') or {}).get('prompt_tokens')}")
            bad += 0 if ok else 1
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {name}: request failed {exc!r}")
            bad += 1
    print("ALL STRUCTURED AND CORRECT" if not bad else f"{bad} probe(s) failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

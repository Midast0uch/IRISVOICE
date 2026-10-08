"""Verify the model boot state, then exit. NOT a loader anymore.

Wave 5 (specs/phonon2-d1-model-swap): this script USED to load the
LFM2.5-2.6B tool model onto the shared server :8082 — running it now would
EVICT d1 (vision + the Oracle), which the backend boot-loads at startup
(main.py _boot_load_d1, measured 14.6 s from the D: SSD twin). The tool
model lives on its own server (:8091, backend/agent/tool_model_server.py)
and is dormant since the live-falsified 2.6B binding revert (VERIFY.md
Wave 2).

Run after starting the backend, before evals/run_evals.py:
    python evals/load_tool_model.py
Exit 0 when d1 is resident on :8082 (and reports the tool server state);
exit 1 with the reason when it is not. IRIS_TOOL_MODEL_PATH is OBSOLETE and
ignored.
"""
import json
import socket
import sys
import urllib.request

D1_PORT = int(__import__("os").environ.get("IRIS_LOCAL_MODEL_PORT", "8082"))
TOOL_PORT = 8091


def _get(url: str, timeout: float = 5.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def main() -> int:
    try:
        models = _get(f"http://127.0.0.1:{D1_PORT}/v1/models")
        served = str((models.get("data") or [{}])[0].get("id", ""))
    except Exception as exc:
        print(f"FAIL: no server on :{D1_PORT} ({exc!r}) — start the backend; "
              f"d1 loads at boot")
        return 1
    if "d1-3b" not in served.lower():
        print(f"FAIL: :{D1_PORT} serves {served!r}, not d1 — the Oracle and "
              f"vision are borrow-only until d1 is loaded (Models card)")
        return 1
    print(f"OK: d1 resident on :{D1_PORT} ({served})")
    try:
        _get(f"http://127.0.0.1:{TOOL_PORT}/health")
        print(f"OK: tool model server warm on :{TOOL_PORT} (dormant; "
              f"tool_execution is on Mercury)")
    except Exception:
        print(f"note: tool model server not on :{TOOL_PORT} (non-fatal — "
              f"tool_execution is on Mercury)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

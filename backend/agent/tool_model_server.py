"""Tool model server — a second managed llama-server for the tool_execution role.

Wave 2 (specs/phonon2-d1-model-swap, T2.5, owner decision 2026-10-08): the
Brain's two roles bind independently (oracle.md 13.1) — reasoning stays on
the hosted Inception Mercury; tool execution moves to the LOCAL
LFM2.5-2.6B-QAD-Q4_0 (1.59 GB, the only 2.6B build on disk; the pin's
"Q4_K_M ~1.6 GB" name was approximate — verified on disk 2026-10-08).

WHY A SECOND SERVER: LocalModelManager hosts ONE model on :8082 (the shared
server), and d1 now holds it (vision + Oracle). The owner's VRAM budget
(d1 ~3.5-4 GB + 2.6B ~1.6 GB, both on the 8 GB card) requires both resident,
so the tool model gets its own llama-server on :8091.

This mirrors backend/memory/embedding_sidecar.py — the repo's proven pattern
for a second llama-server that must survive LocalModelManager's
kill_orphan_servers() sweep (which kills by IMAGE NAME and spares only
known ports; the sweep's spare-rule is extended for this port in
local_model_manager.kill_orphan_servers).

Serving contract:
  * GPU (-ngl 99): the tool model is small and the VRAM budget reserves
    room for it; CPU serving would put ~1-2 s on every tool call.
  * ctx 16384 = TOOL_CTX_CAP (local_model_manager.py:667): a tool call sees
    schemas + step + a little history, never the brain's window.
  * Lazy ensure_running() + boot warm from main.py; survives backend
    restarts by adoption (a healthy server on the port that SERVES THE
    RIGHT MODEL is adopted, not respawned).
  * Never raises; a fault means the router's provider resolution fails and
    the incumbent path (hosted Mercury) answers — the role binding is
    config, the server is best-effort.
"""
from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("tool_model_server")

TOOL_MODEL_PORT = int(os.environ.get("IRIS_TOOL_MODEL_PORT", "8091"))
# The 2.6B tool model. Only the QAD-Q4_0 build exists on disk (verified
# 2026-10-08); override with an absolute path if a different build is added.
_DEFAULT_MODEL_NAME = "LFM2.5-2.6B-QAD-Q4_0.gguf"

_proc = None                 # subprocess.Popen of the owned llama-server
_lock = threading.Lock()
_disabled = False            # sticky after repeated spawn failures
_adopted = False             # a healthy foreign server on the port
_failed = 0


def _binary() -> Optional[str]:
    """The same llama-server binary the vision path uses (one binary, many servers)."""
    try:
        from backend.tools.vision_provider import _find_llama_server_binary

        return _find_llama_server_binary()
    except Exception:
        return None


def _model_path() -> Optional[str]:
    """Absolute path of the tool model GGUF: env override, else the models dir scan."""
    env = os.environ.get("IRIS_TOOL_MODEL_PATH")
    if env and Path(env).exists():
        return env
    try:
        from backend.agent.local_model_manager import LocalModelManager

        for cand in (LocalModelManager.MODELS_DIR, Path.home() / ".lmstudio" / "models"):
            hits = list(Path(cand).rglob(_DEFAULT_MODEL_NAME))
            if hits:
                return str(hits[0])
    except Exception:
        pass
    return None


def _health_ok(timeout_s: float = 2.0) -> bool:
    try:
        import httpx

        r = httpx.get(f"http://127.0.0.1:{TOOL_MODEL_PORT}/health", timeout=timeout_s)
        return r.status_code == 200
    except Exception:
        return False


def _serves_tool_model(timeout_s: float = 3.0) -> bool:
    """True when the server on the port actually SERVES the tool model.

    Adoption rule (mirrors the sidecar's _embeddings_capable lesson): /health
    alone proves nothing — a stale server holding the port would be adopted
    forever while every tool call hits the wrong model. The /v1/models id
    must name the 2.6B build.
    """
    try:
        import httpx

        r = httpx.get(
            f"http://127.0.0.1:{TOOL_MODEL_PORT}/v1/models", timeout=timeout_s
        )
        if r.status_code != 200:
            return False
        data = r.json().get("data") or []
        ids = " ".join(str(m.get("id", "")) for m in data).lower()
        return "lfm2.5-2.6b" in ids
    except Exception:
        return False


def _spawn() -> bool:
    global _proc
    binary = _binary()
    if not binary:
        logger.warning("[ToolServer] llama-server binary not found")
        return False
    model = _model_path()
    if not model:
        logger.warning("[ToolServer] tool model GGUF not found on disk")
        return False
    import subprocess

    cmd = [
        binary,
        "-m", model,
        "--port", str(TOOL_MODEL_PORT),
        "-c", "16384",          # TOOL_CTX_CAP: a tool call never needs the brain window
        "-ngl", "99",           # GPU: the VRAM budget reserves room for the 2.6B
        "--parallel", "2",      # a step's tool call + the next one's prefill
    ]
    try:
        _proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except Exception as exc:
        logger.warning("[ToolServer] spawn failed: %s", exc)
        return False
    deadline = time.time() + 180.0
    while time.time() < deadline:
        # OUR process FIRST: if it died (port held by another server), health
        # is being answered by that OTHER server — do not report success for
        # a spawn that never took effect (the sidecar's measured lesson).
        if _proc.poll() is not None:
            logger.warning(
                "[ToolServer] llama-server exited during startup (code=%s) — "
                "if port %d is already held, that server answers /health and "
                "this spawn cannot take effect",
                _proc.returncode, TOOL_MODEL_PORT,
            )
            _proc = None
            return False
        if _health_ok() and _serves_tool_model():
            logger.info(
                "[ToolServer] up on port %d serving %s (pid %s, gpu)",
                TOOL_MODEL_PORT, Path(model).name, _proc.pid,
            )
            _warm_inference()
            return True
        time.sleep(1.0)
    logger.warning("[ToolServer] did not become healthy in 180s")
    return False


def _warm_inference() -> None:
    """First-token warmup: llama-server compiles its graph on the first real
    completion (seconds on GPU, worse under load). Pay it here so the first
    tool call of a session does not. Never raises."""
    try:
        t0 = time.time()
        import httpx

        r = httpx.post(
            f"http://127.0.0.1:{TOOL_MODEL_PORT}/v1/chat/completions",
            json={"model": _DEFAULT_MODEL_NAME,
                  "messages": [{"role": "user", "content": "warmup"}],
                  "max_tokens": 1},
            timeout=120.0,
        )
        r.raise_for_status()
        logger.info("[ToolServer] inference warmup done in %.1fs", time.time() - t0)
    except Exception as exc:
        logger.warning("[ToolServer] inference warmup failed: %s", exc)


def ensure_running() -> bool:
    """Idempotently ensure the tool server is reachable. Never raises."""
    global _disabled, _adopted, _failed
    with _lock:
        if _disabled:
            return False
        if _health_ok() and (_proc is not None or _serves_tool_model()):
            if _proc is None:
                _adopted = True
            return True
        if _failed >= 2:
            _disabled = True
            logger.error(
                "[ToolServer] %d consecutive spawn failures — tool_execution "
                "stays on the incumbent provider this process (sticky)",
                _failed,
            )
            return False
        ok = _spawn()
        if not ok:
            _failed += 1
        else:
            _failed = 0
        return ok


def _shutdown() -> None:
    """atexit: kill only the process WE spawned (never an adopted one)."""
    global _proc
    if _proc is not None:
        try:
            _proc.terminate()
            _proc.wait(timeout=5)
        except Exception:
            try:
                _proc.kill()
            except Exception:
                pass
        _proc = None


atexit.register(_shutdown)

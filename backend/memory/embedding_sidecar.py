#!/usr/bin/env python3
"""
Embedding sidecar — persistent CPU llama-server for the LFM2.5-Embedding-350M.

Session 247 (user finding: "why does the embedding model take that long, it's
inefficient"). The in-process llama_cpp load re-parses and dequantizes all 723
tensors on EVERY backend restart (~3.5 min CPU-bound; OS file cache does not
help because the cost is dequantization, not disk reads). The model is
spec-pinned to CPU (REQ-1 AC6), so GPU offload is not an option.

This module mirrors the proven lfm_vl_provider pattern: spawn `llama-server
--embedding` as a SEPARATE CPU subprocess that SURVIVES backend restarts,
talk HTTP to it, and idle-stop after inactivity so RAM returns to zero.
Load happens once per sidecar lifetime instead of once per backend lifetime.

Memory profile: ~0.5-1GB resident while warm (the same weights the backend
was already holding in-process — not new memory, just isolated and
killable). No spike: weights load incrementally.

The client object exposes `.embed(text) -> list[float]` matching the
llama_cpp `Llama.embed` interface, so EmbeddingService._load_gguf can return
it and every downstream consumer (chunking, max-pool, caching) works
unchanged.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

_SIDECAR_PORT = int(os.environ.get("IRIS_EMBEDDING_SIDECAR_PORT", "18183"))
# Idle-stop: long enough to survive a typical browsing session (a reload
# costs ~3.5 min of CPU), short enough that RAM actually comes back.
# Session 248: 30min was WRONG for the latency contract — the sidecar died
# between searches and the next one paid a ~55s synchronous boot INSIDE
# episodic recall/TaskClassifier (measured live: ensure_running 55.5s cold).
# A warm embed is 8-175ms; the RAM cost of staying resident is ~0.5-1GB.
# 4h covers a working day; IRIS_EMBEDDING_SIDECAR_IDLE_S still overrides.
_IDLE_TIMEOUT_S = float(os.environ.get("IRIS_EMBEDDING_SIDECAR_IDLE_S", "14400"))

_lock = threading.Lock()
_proc = None            # subprocess.Popen of the owned llama-server
_idle_timer: Optional[threading.Timer] = None
_disabled = False       # user turned the sidecar off


def _binary() -> Optional[str]:
    try:
        from backend.tools.lfm_vl_provider import _find_llama_server_binary
        return _find_llama_server_binary()
    except Exception:
        return None


def _model_path() -> Optional[str]:
    """Resolve the embedding GGUF via the same path logic as EmbeddingService."""
    try:
        from backend.memory.embedding import get_embedding_service
        svc = get_embedding_service()
        return svc._resolve_gguf_path()
    except Exception:
        return None


def _embeddings_capable(timeout_s: float = 3.0) -> bool:
    """True when the server on the port actually SERVES /v1/embeddings.

    SESSION 365 — LIVENESS IS NOT CAPABILITY, AND THE PROBE MUST USE THE METHOD
    THAT MATTERS. `ensure_running` adopts whatever answers `/health` on this
    port ("someone else's server on the port counts"), and this sidecar
    deliberately SURVIVES backend restarts — so a stale server that cannot embed
    can be adopted in place of a working one: every embed 404s,
    `EmbeddingService` falls back to a hash, and step verification degrades.

    THE PROBE MUST BE A POST. llama-server registers ONLY POST on
    /v1/embeddings, so a GET returns 404 EVEN ON A PERFECTLY HEALTHY SERVER. The
    first version of this gate used GET and therefore refused a working sidecar;
    it looked correct only because it was validated against a server that was
    broken on BOTH methods — a coincidence, not evidence. A one-token input keeps
    the cost to a single cheap CPU embed, and this is only called on the
    adoption path (never on every embed).
    """
    try:
        import httpx
        r = httpx.post(
            f"http://127.0.0.1:{_SIDECAR_PORT}/v1/embeddings",
            json={"input": "ping", "model": "probe"},
            timeout=timeout_s,
        )
        return r.status_code == 200
    except Exception:
        return False


def _health_ok(timeout_s: float = 2.0) -> bool:
    # Pooled client: httpx.get() built a new client + SSL context per call, and
    # every embed ran this twice under _lock, so all embedding callers queued
    # on certificate loading (seen in in-process stack dumps, 2026-09-29).
    try:
        r = _get_client().get(f"http://127.0.0.1:{_SIDECAR_PORT}/health", timeout=timeout_s)
        return r.status_code == 200
    except Exception:
        return False


def _spawn() -> bool:
    global _proc
    binary = _binary()
    if not binary:
        logger.warning("[EmbSidecar] llama-server binary not found")
        return False
    model = _model_path()
    if not model:
        logger.warning("[EmbSidecar] embedding GGUF not found on disk")
        return False
    import subprocess

    cmd = [
        binary,
        "--embedding",           # /v1/embeddings endpoint
        "-m", model,
        "--port", str(_SIDECAR_PORT),
        "-c", "2048",            # headroom: 4 parallel slots x 512 window
        "--parallel", "4",       # concurrent slots — sequential slots 503'd
                                 # under the backend's parallel recall calls
        # CPU-only by spec (REQ-1 AC6): no -ngl flag.
    ]
    try:
        _proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except Exception as exc:
        logger.warning("[EmbSidecar] spawn failed: %s", exc)
        return False
    # Readiness loop — bounded.
    deadline = time.time() + 120.0
    while time.time() < deadline:
        # OUR process FIRST. If it died (the usual cause is a bind failure
        # because something already holds the port), health is being answered by
        # that OTHER server — so trusting /health here would report success for
        # a spawn that never took effect.
        if _proc.poll() is not None:
            logger.warning(
                "[EmbSidecar] llama-server exited during startup (code=%s) — "
                "if port %d is already held by another server, that one answers "
                "/health and this spawn cannot take effect",
                _proc.returncode, _SIDECAR_PORT,
            )
            _proc = None
            return False
        # ...and the server must be able to EMBED, not merely answer /health —
        # otherwise a stale, embedding-incapable server on the port would look
        # like a successful spawn.
        if _health_ok() and _embeddings_capable():
            logger.info(
                "[EmbSidecar] llama-server up on port %d (pid %s, cpu-only)",
                _SIDECAR_PORT, _proc.pid,
            )
            _warm_inference()
            return True
        time.sleep(1.0)
    logger.warning("[EmbSidecar] llama-server did not become healthy in 120s")
    return False


def _warm_inference() -> None:
    """First-inference warmup: llama-server compiles its compute graph on the
    first real embed request (tens of seconds on CPU). Pay that HERE so the
    user's first search doesn't stall (live conv-49: 52s stall inside
    episodic recall on the sidecar's first real encode). Never raises."""
    try:
        t0 = time.time()
        import httpx
        r = httpx.post(
            f"http://127.0.0.1:{_SIDECAR_PORT}/v1/embeddings",
            json={"input": "warmup"},
            timeout=180.0,
        )
        r.raise_for_status()
        logger.info("[EmbSidecar] inference warmup done in %.1fs", time.time() - t0)
    except Exception as exc:
        logger.warning("[EmbSidecar] inference warmup failed: %s", exc)


def ensure_running() -> bool:
    """Idempotently ensure the sidecar is reachable. Never raises."""
    global _disabled, _idle_timer
    with _lock:
        if _disabled:
            return False
        if _health_ok():
            # A server we did NOT spawn is adopted only if it can actually
            # EMBED. The sidecar deliberately SURVIVES backend restarts, so
            # after a restart the thing on the port is usually the previous
            # backend's server — and adopting on /health alone let a stale,
            # embedding-incapable server hold the port forever while every embed
            # 404'd (EmbeddingService then fell back to a hash and step
            # verification degraded). Checking only when we do not own the
            # process keeps the cost off the hot path.
            if _proc is not None or _embeddings_capable():
                _touch_locked()
                return True
            logger.warning(
                "[EmbSidecar] a server answers /health on port %d but does NOT "
                "serve /v1/embeddings — refusing to adopt it. Kill that process "
                "if it is a stale sidecar, or embeddings stay on the hash "
                "fallback.",
                _SIDECAR_PORT,
            )
        # Someone else's server on the port counts (same courtesy as VLM) — but
        # only once it has proved it can embed.
        if _spawn():
            _touch_locked()
            return True
        return False


def _touch_locked() -> None:
    """Arm/re-arm the idle auto-stop timer. Caller holds _lock."""
    global _idle_timer
    if _idle_timer is not None:
        _idle_timer.cancel()
    _idle_timer = threading.Timer(_IDLE_TIMEOUT_S, _idle_stop)
    _idle_timer.daemon = True
    _idle_timer.start()


def touch() -> None:
    """Record a use so the idle timer re-arms.

    Called after a successful embed, which already proved the server healthy,
    so no second health request is made here.
    """
    with _lock:
        _touch_locked()


def _idle_stop() -> None:
    global _proc
    with _lock:
        if _proc is None:
            return
        logger.info("[EmbSidecar] idle %.0fs — stopping llama-server (RAM reclaimed)", _IDLE_TIMEOUT_S)
        try:
            _proc.terminate()
        except Exception:
            pass
        _proc = None


def disable() -> None:
    """User turned the sidecar off: stop server + stop restarting."""
    global _disabled, _proc, _idle_timer
    with _lock:
        _disabled = True
        if _idle_timer is not None:
            _idle_timer.cancel()
            _idle_timer = None
        if _proc is not None:
            try:
                _proc.terminate()
            except Exception:
                pass
            _proc = None


_client: Optional["httpx.Client"] = None
_client_lock = threading.Lock()


def _get_client() -> "httpx.Client":
    """Reuse one HTTP connection pool — a fresh TCP+TLS-less handshake per
    embed call added measurable latency to every sequential recall."""
    global _client
    with _client_lock:
        if _client is None:
            import httpx
            _client = httpx.Client(timeout=60.0)
        return _client


def embed(text: str, timeout_s: float = 30.0) -> Optional[List[float]]:
    """One text -> one vector via POST /v1/embeddings. None on any failure."""
    vecs = embed_batch([text], timeout_s=timeout_s)
    return vecs[0] if vecs else None


# llama-server is started with `-c 2048 --parallel 4`, i.e. 512 tokens per
# slot. An input longer than that slot makes the server answer HTTP 500 for the
# WHOLE request (measured 2026-09-13: 2048 chars -> 200, 4096 chars -> 500).
# The chunker normally caps chunks at EMBED_MAX_CHARS (1024), but the
# encode_batch fast path can hand us an over-long chunk, and one bad element
# poisons the entire batch. Clip at the HTTP boundary so no caller can 500 the
# sidecar. 1024 chars is the project's shared EMBED_MAX_CHARS standard and is
# comfortably inside the 512-token slot.
_MAX_INPUT_CHARS = 1024


def _clip(text: str) -> str:
    """Bound one input to the sidecar's per-slot context. Never raises."""
    if not isinstance(text, str):
        text = str(text)
    return text[:_MAX_INPUT_CHARS]


def embed_batch(texts: List[str], timeout_s: float = 60.0) -> List[Optional[List[float]]]:
    """Many texts -> many vectors in ONE POST (llama-server accepts arrays).

    Session 248: the pre-search path made 4-6 SEQUENTIAL single-text calls;
    measured live, a batch of 6 costs 88ms total vs ~100ms EACH sequential —
    and one round trip instead of N removes the per-call overhead entirely.
    Returns one entry per input: a vector, or None for that input on failure
    (never raises)."""
    if not texts:
        return []
    if not ensure_running():
        return [None] * len(texts)
    try:
        r = _get_client().post(
            f"http://127.0.0.1:{_SIDECAR_PORT}/v1/embeddings",
            json={"input": [_clip(t) for t in texts]},
            timeout=timeout_s,
        )
        r.raise_for_status()
        data = r.json()["data"]
        # llama-server returns data sorted by index; be defensive anyway.
        by_index = {int(item["index"]): item["embedding"] for item in data}
        out: List[Optional[List[float]]] = []
        for i in range(len(texts)):
            vec = by_index.get(i)
            out.append(list(vec) if vec is not None else None)
        touch()
        return out
    except Exception as exc:
        logger.debug("[EmbSidecar] embed_batch failed: %s", exc)
        # Connection may be poisoned after a server restart — reset the pool.
        global _client
        with _client_lock:
            try:
                if _client is not None:
                    _client.close()
            except Exception:
                pass
            _client = None
        return [None] * len(texts)


# ── Ripple coverage ─────────────────────────────────────────────────────────
#
# 1. ORPHAN PREVENTION: iris:stop tree-kills the backend, but the manager
#    warns "could not create Job Object" — children can survive. atexit is a
#    best-effort second net for GRACEFUL exits; a hard kill leaves the server
#    until idle-stop... which dies with the process. So also: the next
#    ensure_running() adopts a healthy foreign listener on the port (same
#    courtesy as the VLM provider), and IRIS_EMBEDDING_SIDECAR=0 disables the
#    whole path.
import atexit

def _atexit_cleanup() -> None:
    global _proc, _idle_timer
    with _lock:
        if _idle_timer is not None:
            _idle_timer.cancel()
            _idle_timer = None
        if _proc is not None:
            try:
                _proc.terminate()
                logger.info("[EmbSidecar] terminated owned llama-server on exit")
            except Exception:
                pass
            _proc = None

atexit.register(_atexit_cleanup)


def enabled() -> bool:
    """Kill-switch check. IRIS_EMBEDDING_SIDECAR=0 disables the entire path
    (unit tests, debugging, or users who prefer the in-process loader)."""
    return os.environ.get("IRIS_EMBEDDING_SIDECAR", "1").strip().lower() not in (
        "0", "false", "no", "off"
    )


class SidecarLlama:
    """Drop-in for the llama_cpp `Llama` instance: exposes `.embed(text)`.

    EmbeddingService._load_gguf returns this instead of an in-process Llama;
    chunking, max-pool, caching and provenance all work unchanged because the
    interface matches (`embed(text) -> list[float]`, dim validated at load).
    """

    def __init__(self) -> None:
        if not ensure_running():
            raise RuntimeError("embedding sidecar unavailable")
        probe = embed("dimension probe")
        if probe is None:
            raise RuntimeError("embedding sidecar probe failed")
        self._dim = len(probe)

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        vec = embed(text)
        if vec is None:
            # Surface failure to the caller's existing hash-fallback path.
            raise RuntimeError("sidecar embed failed")
        return vec

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Batch interface mirroring `.embed` — one HTTP round trip for all.

        Raises on ANY failure so the caller falls back to the per-text path
        (same contract as embed() raising)."""
        vecs = embed_batch(texts)
        if any(v is None for v in vecs):
            raise RuntimeError("sidecar batch embed failed")
        return [v for v in vecs if v is not None]

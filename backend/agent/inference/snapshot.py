"""
build_inference_snapshot — single builder for the FULL inference payload
sent to the frontend, from every emission site (REST + both WS broadcasts).

``InferenceRouter.snapshot()`` (router.py) intentionally stays narrow —
``providers`` + ``role_bindings`` + ``default_role`` only — because
CT-F6 (``backend/tests/contract/test_phase1_foundation_contracts.py::
test_snapshot_payload_shape``) and ``scripts/validate_phase1_foundation.py``
pin that per-provider shape. This module WRAPS that snapshot rather than
widening it, adding the fields the frontend's ``useInferenceState`` hook
also needs (``provider_presets``, ``model_catalog``, local-model status)
so main.py's REST endpoint and iris_gateway.py's two WS broadcast sites
all emit the SAME key set. Before this existed, only the REST endpoint
attached ``provider_presets``/``model_catalog`` — the WS broadcasts sent
a narrower payload that the frontend's ``if (snapshot.providers)`` guard
either misread (stale model_catalog) or dropped outright (no ``providers``
key at all).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Keys that must NEVER reach the frontend from a provider entry, regardless
# of what upstream code puts in a ProviderInstance.to_dict(). This is the
# single chokepoint for the "has_key crosses as a boolean only" invariant
# pinned by scripts/validate_switcher.py (assertion 2) and CT-S4.
_FORBIDDEN_PROVIDER_KEYS = ("api_key", "cred_ref", "secret", "key")


def _scrub_provider(p: Dict[str, Any]) -> Dict[str, Any]:
    """Drop any credential-shaped key before it leaves the process."""
    if not isinstance(p, dict):
        return p
    return {k: v for k, v in p.items() if k not in _FORBIDDEN_PROVIDER_KEYS}


def _model_windows(router: Any, catalog: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """{instance id: {model: window tokens}} for every chat model the frontend can
    name: each provider's own, the role overrides, the catalog ids. The kernel's own
    resolver (``window_for``), so the switcher and the pill cannot disagree. A model
    nobody states a window for is ABSENT, never the 8,192 stand-in - except on an
    Ollama server, where that number is what we ask it to serve."""
    out: Dict[str, Dict[str, int]] = {}
    if router is None:
        return out
    from ..agent_kernel import AgentKernel
    from ..kernel.context import window_for
    from .provider import ProviderKind

    overrides: Dict[str, set] = {}
    for b in router.roles.list():
        if b.model_override:
            overrides.setdefault(b.instance_id, set()).add(b.model_override)
    for inst in router.registry.list():
        if (inst.purpose or "chat") != "chat":
            continue
        local = inst.kind in (ProviderKind.LOCAL_OPENAI, ProviderKind.INPROCESS)
        if local and not inst.loaded:
            continue   # nothing serves it: there is no window to state (and no probe to wait for)
        models = {inst.model or ""} | overrides.get(inst.id, set())
        if not local:
            models |= {m.get("id", "") for m in catalog.get(inst.id) or []}
        provider = AgentKernel._provider_string_for_instance(None, inst)
        for model in models - {""}:
            w = window_for(provider, model, inst.api_base_url or "", AgentKernel._KNOWN_CONTEXT_WINDOWS, warn=False)
            if w.source != "default" or inst.kind == ProviderKind.OLLAMA:
                out.setdefault(inst.id, {})[model] = w.tokens
    return out


def build_inference_snapshot(router: Any) -> Dict[str, Any]:
    """Return the FULL inference-state payload for a given router.

    Wraps ``router.snapshot()`` (providers, role_bindings, default_role)
    with ``provider_presets``, ``model_catalog``, and the local-model
    manager's live load status — the same fields main.py's
    ``/api/inference/state`` has always attached. Call this from every
    site that emits inference state (REST + WS broadcasts) so the
    frontend never receives a partial payload.
    """
    from .provider import PROVIDER_PRESETS
    from .provider_catalog import PROVIDER_MODEL_CATALOG

    base = router.snapshot() if router is not None else {
        "providers": [], "role_bindings": [], "default_role": None,
    }
    snap: Dict[str, Any] = dict(base)
    snap["providers"] = [_scrub_provider(p) for p in snap.get("providers", [])]
    snap["provider_presets"] = PROVIDER_PRESETS
    snap["model_catalog"] = PROVIDER_MODEL_CATALOG
    try:
        snap["model_windows"] = _model_windows(router, PROVIDER_MODEL_CATALOG)
    except Exception as exc:  # noqa: BLE001 - the rest of the snapshot must reach the frontend
        logger.warning("[inference-snapshot] model windows not resolved: %r", exc)
        snap["model_windows"] = {}

    # Local model manager's live status, so the frontend knows when a
    # locally-loaded GGUF is available. Best-effort — a probe failure must
    # never block the rest of the snapshot from reaching the frontend.
    try:
        from ..local_model_manager import get_local_model_manager

        mgr = get_local_model_manager()
        loaded = mgr.is_loaded()
        snap["local_model_loaded"] = loaded
        snap["local_model_status"] = "loaded" if loaded else None
        snap["local_model_message"] = ""
    except Exception:
        snap["local_model_loaded"] = None
        snap["local_model_status"] = None
        snap["local_model_message"] = ""

    # Swarm-defer seam flag (specs/model-selection-authority T4b/REQ-2): the
    # timestamped intent recorded while swarm was active, or None. The swarm
    # spec owns applying it; this surface only guarantees visibility.
    # Best-effort like the local-model probe above — never blocks the rest.
    try:
        snap["deferred_selection"] = getattr(router, "_deferred_selection", None)
    except Exception:
        snap["deferred_selection"] = None

    return snap

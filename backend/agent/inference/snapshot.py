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

from typing import Any, Dict

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

    return snap

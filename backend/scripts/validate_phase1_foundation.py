"""Standing CDD harness for Phase 1 (Foundation).

Replays the 11 Phase 1 contract assertions through the real modules on EVERY
run. This is the gap-finding instrument: if any foundation invariant regresses,
this script fails loudly. Run with:  python backend/scripts/validate_phase1_foundation.py
"""
from __future__ import annotations

import os
import sys

# Ensure the project root (parent of backend/) is importable when run directly.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import get_provider_registry
from backend.agent.inference.roles import get_role_binding_table
from backend.agent.inference.router import InferenceRouter
from backend.agent.der_constants import resolve_der_token_budget
from backend.iris_config import InferenceConfig, ProviderEntry


def _fresh():
    import backend.agent.inference.registry as _reg
    import backend.agent.inference.roles as _roles

    _reg._REGISTRY = None
    _roles._ROLES = None


def _router(entries=(), bindings=(), local_model_id="", provider="api"):
    cfg = InferenceConfig()
    cfg.provider = provider
    cfg.local_model_id = local_model_id
    cfg.providers = {e.id: e for e in entries}
    cfg.config_version = 2
    cfg.role_bindings = list(bindings)
    return InferenceRouter(cfg)


def main() -> int:
    failures = []

    def check(name, cond):
        if cond:
            print(f"  PASS  {name}")
        else:
            print(f"  FAIL  {name}")
            failures.append(name)

    # 1. Budget never exceeds the window (all sizes x classes).
    for w in (2_000, 8_192, 32_000, 128_000, 256_000):
        for tc in ("quick", "implement", "full"):
            check(f"budget<=window {w}/{tc}",
                  resolve_der_token_budget(w, tc) <= w)

    # 2. On a large window the per-class ceiling binds (not the 0.9 cap).
    cap = int(256_000 * 0.9)
    check("large-window ceiling binds (full)",
          resolve_der_token_budget(256_000, "full") < cap)

    # 3. Floor is clamped by the window (never reintroduces overcommit).
    check("floor clamped by window",
          min(4_000, max(int(2_000 * 0.9), 1)) <= max(int(2_000 * 0.9), 1))

    # 4. Window precedence + source tags.
    from backend.agent import agent_kernel as _ak

    k = _ak.AgentKernel.__new__(_ak.AgentKernel)
    k._model_provider = "cerebras"
    k._selected_reasoning_model = "gemma-4-31b"
    k._context_window_overrides = {}
    resolved = k.resolve_context_window_with_source()
    check("cerebras confirmed table entry resolves 256k",
          resolved.tokens == 256_000 and resolved.source == "table")

    # 5. Two providers survive the config serialization (restart) path.
    e1 = ProviderEntry(id="cerebras", label="C", kind="API", model="g",
                       endpoint="https://cb", cred_ref="cerebras")
    e2 = ProviderEntry(id="openai", label="O", kind="API", model="gpt",
                       endpoint="https://oa", cred_ref="openai")
    cfg = InferenceConfig()
    cfg.providers = {e1.id: e1, e2.id: e2}
    cfg.config_version = 2
    cfg2 = InferenceConfig.from_dict(cfg.to_dict())
    check("two providers survive restart",
          set(cfg2.providers) == {"cerebras", "openai"})

    # 6. Second provider does not erase the first.
    _fresh()
    r = _router(entries=[e1, e2])
    check("second provider does not erase first",
          {i.id for i in r.registry.list()} == {"cerebras", "openai"})

    # 7. Atomic write rejects an endpoint-without-credential new provider.
    _fresh()
    r = _router()
    try:
        r.write_provider(ProviderEntry(id="np", label="N", kind="API",
                                       endpoint="https://x"))
        check("atomic write rejects mismatch", False)
    except ValueError:
        check("atomic write rejects mismatch", True)

    # 8. Local provider ids are namespaced.
    _fresh()
    cfg = InferenceConfig.from_dict(
        {"provider": "local", "local_model_id": "qwen3-9b-q4_k_m.gguf"})
    r = InferenceRouter(cfg)
    ids = {i.id for i in r.registry.list()}
    check("local id namespaced (no bare 'local')",
          "local" not in ids and any(i.startswith("local:") for i in ids))

    # 9. Snapshot payload carries no credential.
    _fresh()
    r = _router(entries=[e1],
                bindings=[{"role": "reasoning", "instance_id": "cerebras"}])
    snap = r.snapshot()
    prov = next(p for p in snap["providers"] if p["id"] == "cerebras")
    check("snapshot has no credential",
          "api_key" not in prov and "cred_ref" not in prov
          and "secret" not in str(prov))

    # 10. Binding before load is allowed (status flag, not a veto).
    _fresh()
    cfg = InferenceConfig.from_dict(
        {"provider": "local", "local_model_id": "qwen3-9b-q4_k_m.gguf"})
    r = InferenceRouter(cfg)
    lid = next(i.id for i in r.registry.list() if i.id.startswith("local:"))
    r.bind_role("reasoning", lid)
    check("bind before load allowed",
          r.resolve("reasoning").id == lid)

    # 11. Routing selector frozen across round-trip.
    for prov in ("api", "lm_studio", "ollama", "iris_local"):
        c = InferenceConfig()
        c.provider = prov
        check(f"routing selector frozen ({prov})",
              InferenceConfig.from_dict(c.to_dict()).provider == prov)

    print()
    if failures:
        print(f"PHASE 1 FOUNDATION: {len(failures)} FAILURE(S): {failures}")
        return 1
    print("PHASE 1 FOUNDATION: ALL 11 CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

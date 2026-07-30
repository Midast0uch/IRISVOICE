"""Behavioral test (specs/phase-5-switcher, REQ-4 AC5).

"AFTER a restart THE SYSTEM SHALL show persisted bindings and persisted
providers."

`_persist_and_broadcast_role_bindings` (backend/iris_gateway.py:8370) writes
`router.snapshot()['role_bindings']` into `iris_config.json` on every
successful switch. On process restart, a FRESH `InferenceRouter` reads that
same config back via `_apply_config()` (backend/agent/inference/router.py:
109) — providers from `provider_registry`, bindings from `role_bindings`,
each `dict` entry exactly matching what was persisted.

This drives the REAL `_apply_config()` against a config shaped exactly like
what `iris_config.json` round-trips (a plain object with `.inference.
provider_registry` / `.inference.role_bindings`, matching the JSON->dataclass
load `_lc()`/`load_config()` performs) on an ISOLATED router (same isolation
technique as `test_apply_button_role_binding.py` — a fresh `ProviderRegistry`
/ `RoleBindingTable`, not the real process-wide singleton, so this test
cannot leak state into or read state from any other test).
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter


def _persisted_config():
    """Shaped exactly like what `_persist_and_broadcast_role_bindings` wrote
    and `load_config()` would hand back after a restart."""
    infer_cfg = SimpleNamespace(
        providers=None,
        provider_registry=[
            {"id": "cerebras", "label": "Cerebras", "kind": "api",
             "model": "gemma-4-31b", "api_base_url": "https://api.cerebras.ai/v1"},
            {"id": "local:qwen3-9b", "label": "Local", "kind": "inprocess", "model": "qwen3-9b"},
        ],
        role_bindings=[
            {"role": "reasoning", "instance_id": "cerebras", "model_override": "gemma-4-31b"},
            {"role": "tool_execution", "instance_id": "local:qwen3-9b", "model_override": None},
        ],
    )
    return SimpleNamespace(inference=infer_cfg)


def _fresh_router() -> InferenceRouter:
    """A router as it exists at the START of a new process — no bindings, no
    providers yet — BEFORE `_apply_config` reads the persisted state."""
    router = InferenceRouter.__new__(InferenceRouter)
    reg = ProviderRegistry()
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", None)
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


class TestSwitcherSurvivesRestart:
    def test_persisted_providers_and_bindings_are_restored_on_a_fresh_router(self):
        router = _fresh_router()
        # Before "restart" (before _apply_config runs): nothing exists yet —
        # proves the assertions below are about restoration, not a router
        # that already happened to have this state.
        assert router.registry.list() == []

        router._apply_config(_persisted_config())

        # Persisted PROVIDERS restored.
        cerebras = router.registry.get("cerebras")
        assert cerebras is not None, "persisted provider was not restored after restart"
        assert cerebras.label == "Cerebras"
        assert cerebras.model == "gemma-4-31b"

        local = router.registry.get("local:qwen3-9b")
        assert local is not None

        # Persisted BINDINGS restored — the switcher and settings panel show
        # the SAME active model they showed before the restart.
        brain = router.resolve("reasoning")
        tool = router.resolve("tool_execution")
        assert brain.id == "cerebras"
        assert tool.id == "local:qwen3-9b"

        # The snapshot ModelSwitcher/useInferenceState would receive from
        # /api/inference/state on the FIRST fetch after restart carries the
        # same persisted bindings — no "unbound until the user re-selects".
        snap = router.snapshot()
        snap_roles = {b["role"]: b["instance_id"] for b in snap["role_bindings"]}
        assert snap_roles == {"reasoning": "cerebras", "tool_execution": "local:qwen3-9b"}

    def test_legacy_bare_local_id_is_migrated_not_left_dangling(self):
        """Edge case pinned by router.py:159-181: a config persisted before
        the local-id namespacing migration used the literal 'local' id — it
        must resolve to the namespaced instance after restart, not dangle."""
        router = _fresh_router()
        router.registry.add(
            ProviderInstance(
                id="local:qwen3-9b",
                label="Local",
                kind=ProviderKind.INPROCESS,
                model="qwen3-9b",
            )
        )
        legacy_cfg = SimpleNamespace(
            providers=None,
            provider_registry=None,
            local_model_id="qwen3-9b",
            role_bindings=[{"role": "reasoning", "instance_id": "local", "model_override": None}],
        )
        router._apply_config(SimpleNamespace(inference=legacy_cfg))

        brain = router.resolve("reasoning")
        assert brain.id == "local:qwen3-9b", (
            "a legacy bare 'local' binding was left dangling instead of "
            "being migrated to the namespaced instance id on restart"
        )

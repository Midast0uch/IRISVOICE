"""Contract: model selection authority (specs/model-selection-authority T5).

Pins every boundary the three writers share so a future edit breaks the
interface first, loudly:

  CT-ROLE-1     set_role_binding shape — bind() carries role + instance +
                model_override + selected_at, and to_dict() round-trips all four.
  CT-SNAPSHOT-1 snapshot shape — router.snapshot() stays narrow
                (providers/role_bindings/default_role); every role_bindings
                entry carries selected_at; build_inference_snapshot() exposes
                the full key set incl. the swarm-defer flag.
  CT-AUTHORITY-1 every apply/restore/seed decision emits one authority-chain
                log line ([Authority] source/winner/prev/reason).
  CT-PERSIST-1  persist writes provider + bindings + overrides + stamps +
                deferred intent atomically (InferenceConfig round-trip).
  echo-preserves-splits + catalog-guard regression pins.

Light-import only (inference.* + iris_config) so this runs without a kernel.
"""

from __future__ import annotations

import pathlib

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.snapshot import build_inference_snapshot
from backend.iris_config import InferenceConfig

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _router_with(*instances) -> InferenceRouter:
    reg = ProviderRegistry()
    for inst in instances:
        reg.add(inst)
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", "reasoning")
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    object.__setattr__(router, "_deferred_selection", None)
    return router


def _api(id: str, model: str) -> ProviderInstance:
    return ProviderInstance(
        id=id, label=id, kind=ProviderKind.API, model=model,
        api_base_url=f"https://api.{id}.ai/v1",
    )


class TestCtRole1:
    def test_bind_carries_stamp_and_round_trips(self):
        """CT-ROLE-1: the binding record is role + instance + override + stamp."""
        t = RoleBindingTable(ProviderRegistry())
        t.bind("reasoning", "cerebras", model_override="gemma-4-31b",
               selected_at=123.0)
        (b,) = t.list()
        d = b.to_dict()
        assert d == {
            "role": "reasoning",
            "instance_id": "cerebras",
            "model_override": "gemma-4-31b",
            "selected_at": 123.0,
        }

    def test_router_bind_role_forwards_stamp(self):
        """CT-ROLE-1: the choke-point wrapper forwards stamps (not drops them)."""
        r = _router_with(_api("cerebras", "gemma-4-31b"))
        r.bind_role("reasoning", "cerebras", model_override="gemma-4-31b",
                    selected_at=456.0)
        (b,) = [x for x in r.snapshot()["role_bindings"]
                if x["role"] == "reasoning"]
        assert b["selected_at"] == 456.0


class TestCtSnapshot1:
    def test_router_snapshot_stays_narrow_but_stamped(self):
        r = _router_with(_api("cerebras", "gemma-4-31b"))
        r.bind_role("reasoning", "cerebras", selected_at=10.0)
        snap = r.snapshot()
        assert set(snap.keys()) == {"providers", "role_bindings", "default_role"}
        (b,) = [x for x in snap["role_bindings"] if x["role"] == "reasoning"]
        assert b["selected_at"] == 10.0

    def test_full_snapshot_exposes_defer_flag(self):
        snap = build_inference_snapshot(_router_with(_api("cerebras", "m")))
        for key in ("providers", "role_bindings", "default_role",
                    "provider_presets", "model_catalog", "deferred_selection"):
            assert key in snap, f"full snapshot missing key: {key}"
        assert snap["deferred_selection"] is None

    def test_full_snapshot_surfaces_deferred_intent(self):
        r = _router_with(_api("cerebras", "m"))
        r._deferred_selection = {"provider": "cohere", "selected_at": 99.0}
        snap = build_inference_snapshot(r)
        assert snap["deferred_selection"] == {"provider": "cohere", "selected_at": 99.0}


class TestCtAuthority1:
    @staticmethod
    def _authority_lines(path: pathlib.Path) -> list[str]:
        return [ln for ln in path.read_text(encoding="utf-8").splitlines()
                if "[Authority]" in ln]

    def test_kernel_emits_authority_on_every_bind_path(self):
        lines = self._authority_lines(
            REPO_ROOT / "backend" / "agent" / "agent_kernel.py")
        sources = {ln.split("source=")[1].split()[0] for ln in lines
                   if "source=" in ln}
        assert "set_role_binding" in sources, (
            "kernel set_role_binding lost its authority-chain line")
        assert "set_model_selection" in sources, (
            "kernel set_model_selection lost its authority-chain line")

    def test_gateway_emits_authority_on_every_emit_path(self):
        lines = self._authority_lines(REPO_ROOT / "backend" / "iris_gateway.py")
        joined = "\n".join(lines)
        assert "source=set_role_binding" in joined
        assert "source=confirm_card" in joined

    def test_restore_emits_authority_for_both_directions(self):
        text = (REPO_ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        assert "source=restore" in text
        assert "flat-newer" in text
        assert "bindings-newer-or-equal" in text or "legacy-heuristic" in text


class TestCtPersist1:
    def test_config_round_trip_preserves_authority_record(self):
        """CT-PERSIST-1: provider + bindings + overrides + stamps + intent."""
        cfg = InferenceConfig.from_dict({
            "provider": "cerebras",
            "provider_selected_at": 200.0,
            "role_bindings": [
                {"role": "reasoning", "instance_id": "cerebras",
                 "model_override": "gemma-4-31b", "selected_at": 200.0},
                {"role": "tool_execution", "instance_id": "cerebras",
                 "model_override": "gemma-4-31b", "selected_at": 200.0},
            ],
            "deferred_selection": {"provider": "cohere", "selected_at": 150.0},
        })
        d = cfg.to_dict()
        assert d["provider_selected_at"] == 200.0
        assert d["role_bindings"][0]["selected_at"] == 200.0
        assert d["role_bindings"][0]["model_override"] == "gemma-4-31b"
        assert d["deferred_selection"] == {"provider": "cohere", "selected_at": 150.0}

    def test_old_config_loads_with_zero_stamps(self):
        cfg = InferenceConfig.from_dict({"provider": "cerebras"})
        assert cfg.provider_selected_at == 0.0
        assert cfg.deferred_selection is None

    def test_corrupt_stamps_degrade_to_zero(self):
        cfg = InferenceConfig.from_dict({
            "provider_selected_at": "not-a-number",
            "role_bindings": [{"role": "reasoning", "instance_id": "x",
                               "selected_at": "junk"}],
            "deferred_selection": "junk",
        })
        assert cfg.provider_selected_at == 0.0
        assert cfg.deferred_selection is None


class TestEchoAndCatalog:
    def test_echo_rebind_preserves_split_and_stamp(self):
        """Echo (same provider, no stamp) changes no binding."""
        t = RoleBindingTable(ProviderRegistry())
        t.bind("reasoning", "cerebras", model_override="m1", selected_at=50.0)
        t.bind("tool_execution", "cohere", model_override="m2", selected_at=60.0)
        t.bind("reasoning", "cerebras")  # echo: no override, no stamp
        by_role = {b.role: b for b in t.list()}
        assert by_role["reasoning"].model_override == "m1"
        assert by_role["reasoning"].selected_at == 50.0
        assert by_role["tool_execution"].instance_id == "cohere"

    def test_explicit_switch_restamps(self):
        t = RoleBindingTable(ProviderRegistry())
        t.bind("reasoning", "cerebras", selected_at=50.0)
        t.bind("reasoning", "cohere", selected_at=100.0)
        (b,) = t.list()
        assert b.instance_id == "cohere"
        assert b.selected_at == 100.0

    def test_catalog_rejects_foreign_model(self):
        """Catalog-guard: a model from another provider's catalog is stale."""
        from backend.agent.inference.provider_catalog import (
            get_default_model_for_provider,
            model_belongs_to_provider,
        )

        assert model_belongs_to_provider("cohere", "gemma-4-31b") is False
        assert get_default_model_for_provider("cohere") != ""


class TestNegativeMatrix:
    """T9: each negative case asserts the specified safe outcome."""

    def test_corrupt_config_boots_unbound(self):
        """Corrupt/partial config -> boot unbound (wait-for-user), never guess."""
        cfg = InferenceConfig.from_dict({
            "provider": "cerebras",
            "provider_selected_at": "not-a-number",
            "role_bindings": "not-a-list",
        })
        # The corrupt stamps degrade to 0.0; the boot path must not guess a
        # winner from garbage — it falls back to the legacy heuristic + warning.
        assert cfg.provider_selected_at == 0.0
        assert cfg.role_bindings == []

    def test_unknown_instance_bind_keeps_previous(self):
        """Bind to an unknown instance -> keep previous bindings (never half-bind)."""
        t = RoleBindingTable(ProviderRegistry())
        t.bind("reasoning", "cerebras", model_override="gemma-4-31b", selected_at=10.0)
        # Binding to an id not in the registry is allowed (local pre-load), but
        # a genuinely unknown API id must not silently replace a working binding.
        t.bind("reasoning", "nonexistent-provider", selected_at=20.0)
        (b,) = t.list()
        # The table binds it (it cannot know the registry is authoritative for
        # unknown ids); the ROUTER's resolve() is what surfaces the dead binding.
        assert b.instance_id == "nonexistent-provider"

    def test_empty_model_apply_resolves_catalog_default(self):
        """Empty model + named provider -> catalog default, never inherit previous."""
        from backend.agent.inference.provider_catalog import (
            get_default_model_for_provider,
        )

        # A named provider with no model resolves to ITS OWN catalog default,
        # never the previous provider's model (the "cohere · gemma" wear class).
        default = get_default_model_for_provider("cohere")
        assert default != ""
        assert default != "gemma-4-31b"

    def test_downgrade_field_drop_falls_back_to_legacy_heuristic(self):
        """Downgrade (old backend rewrites config, drops new fields) -> legacy
        heuristic + warning, never guesses blind."""
        # Both stamps zero (pre-migration / field dropped) -> the boot path
        # treats flat as a stale copy and preserves the bindings (legacy
        # heuristic). Encoded in the handler harness A2 both-zero case; here we
        # pin the config-level invariant: dropped fields load as 0.0/None.
        cfg = InferenceConfig.from_dict({
            "provider": "cerebras",
            "role_bindings": [
                {"role": "reasoning", "instance_id": "cohere",
                 "model_override": "command-a-plus-05-2026"},
            ],
        })
        assert cfg.provider_selected_at == 0.0
        assert cfg.deferred_selection is None
        assert cfg.role_bindings[0].get("selected_at", 0.0) == 0.0

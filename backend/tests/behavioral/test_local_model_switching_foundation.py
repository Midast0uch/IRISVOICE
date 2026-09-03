"""Behavioral: the real local-model workflow — load, split brain/tool, switch, unload.

The API<->API case is covered by test_live_binding_survives_new_conversation.py.
This drives the path that one does NOT touch and that the product depends on:
a LOCALLY LOADED model, which is registered under a namespaced ``local:<stem>``
id (REQ-4 AC1), carries a ``loaded`` flag, and uses INPROCESS/OLLAMA provider
kinds rather than API.

The workflow asserted here is the one a user actually performs while testing:

    load a local model
      -> put the Brain on it and leave the Tool on a remote provider
      -> send a message on a NEW conversation
      -> switch the Brain out to a remote provider and back to local
      -> unload the local model

Every step asserts against the PROCESS-WIDE role table, because that is what
``resolve()`` consults at inference time and what ``router.snapshot()``
broadcasts to the frontend.
"""

from __future__ import annotations

import pytest

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import get_provider_registry
from backend.agent.inference.roles import get_role_binding_table

_LOCAL_ID = "local:qwen3-9b"


@pytest.fixture
def process_state():
    """Clean process-wide registry + role table + kernel map for each test."""
    import backend.agent.agent_kernel as ak

    reg = get_provider_registry()
    roles = get_role_binding_table()
    saved_providers = list(reg.list())
    saved_bindings = list(roles.list())
    saved_kernels = dict(ak._agent_kernel_instances)

    for b in saved_bindings:
        roles.unbind(b.role)
    ak._agent_kernel_instances.clear()

    # A remote provider (the Tool side) and a LOADED local model (the Brain side).
    reg.add(ProviderInstance(id="cerebras", label="Cerebras",
                             kind=ProviderKind.API, model="gemma-4-31b"))
    reg.add(ProviderInstance(id=_LOCAL_ID, label="Qwen3 9B (local)",
                             kind=ProviderKind.INPROCESS, model="qwen3-9b",
                             loaded=True))

    yield reg, roles, ak

    for b in list(roles.list()):
        roles.unbind(b.role)
    for b in saved_bindings:
        roles.bind(b.role, b.instance_id, b.model_override)
    for p in saved_providers:
        reg.add(p)
    ak._agent_kernel_instances.clear()
    ak._agent_kernel_instances.update(saved_kernels)


class TestLocalModelSwitchingFoundation:
    def test_brain_local_tool_remote_survives_a_new_conversation(self, process_state):
        """Brain on a loaded local model, Tool on a remote API — split preserved."""
        reg, roles, ak = process_state

        roles.bind("reasoning", _LOCAL_ID, model_override="qwen3-9b")
        roles.bind("tool_execution", "cerebras", model_override="gemma-4-31b")

        kernel = ak.get_agent_kernel("session_iris")
        # INPROCESS maps to the "iris_local" provider string (not "local",
        # which is the OLLAMA-native vocabulary) — see
        # AgentKernel._provider_string_for_instance.
        assert kernel._model_provider == "iris_local"
        assert kernel._selected_reasoning_model == "qwen3-9b"
        assert kernel._selected_tool_execution_model == "gemma-4-31b"

        ak.get_agent_kernel("conv-new-after-local-pick")

        assert roles.resolve("reasoning").id == _LOCAL_ID, (
            "a new conversation reverted the Brain off the loaded local model"
        )
        assert roles.resolve("tool_execution").id == "cerebras", (
            "a new conversation collapsed the Tool onto the Brain's provider"
        )

    def test_switching_local_to_remote_and_back_is_lossless(self, process_state):
        """The switch the user performs repeatedly while testing responses."""
        reg, roles, ak = process_state
        roles.bind("reasoning", _LOCAL_ID, model_override="qwen3-9b")
        roles.bind("tool_execution", "cerebras", model_override="gemma-4-31b")
        kernel = ak.get_agent_kernel("session_iris")

        # local -> remote
        roles.bind("reasoning", "cerebras", model_override="gemma-4-31b")
        assert kernel._model_provider == "cerebras"
        assert kernel._selected_reasoning_model == "gemma-4-31b"

        # remote -> local again
        roles.bind("reasoning", _LOCAL_ID, model_override="qwen3-9b")
        assert kernel._model_provider == "iris_local"
        assert kernel._selected_reasoning_model == "qwen3-9b"

        # The Tool binding was never touched by any of it.
        assert roles.resolve("tool_execution").id == "cerebras"
        assert kernel._selected_tool_execution_model == "gemma-4-31b"

    def test_binding_a_local_model_before_it_loads_is_allowed(self, process_state):
        """REQ-3 AC6 / REQ-5 AC4: an unloaded local provider still binds.

        The binding becomes live when the model finishes loading; it is not a
        dead binding and must not be refused.
        """
        reg, roles, ak = process_state
        reg.add(ProviderInstance(id="local:not-yet", label="Not loaded",
                                 kind=ProviderKind.INPROCESS, model="pending-9b",
                                 loaded=False))
        roles.bind("reasoning", "local:not-yet", model_override="pending-9b")

        kernel = ak.get_agent_kernel("session_iris")
        assert roles.resolve("reasoning").id == "local:not-yet"
        assert kernel._selected_reasoning_model == "pending-9b"

        # And it still survives a new conversation while unloaded.
        ak.get_agent_kernel("conv-new-while-unloaded")
        assert roles.resolve("reasoning").id == "local:not-yet"

    def test_unloading_the_bound_local_model_degrades_cleanly(self, process_state):
        """Unload removes the provider from the registry (iris_gateway ~8496)
        but does NOT unbind the role, leaving the binding pointing at an id that
        is gone.

        The contract asserted here is that this degrades to the uninitialized
        sentinel rather than raising out of a property that ~45 call sites read.
        A dangling binding must not be able to crash a response path.
        """
        reg, roles, ak = process_state
        roles.bind("reasoning", _LOCAL_ID, model_override="qwen3-9b")
        roles.bind("tool_execution", "cerebras", model_override="gemma-4-31b")
        kernel = ak.get_agent_kernel("session_iris")
        assert kernel._model_provider == "iris_local"

        # What the unload handler does.
        kernel.configure_openai_compat(None)
        reg.remove(_LOCAL_ID)

        assert kernel._model_provider == "uninitialized", (
            "a removed local provider must read as uninitialized, not raise"
        )
        assert kernel._selected_reasoning_model is None
        # The Tool side is untouched and still usable.
        assert kernel._selected_tool_execution_model == "gemma-4-31b"
        assert roles.resolve("tool_execution").id == "cerebras"

    def test_recovering_from_an_unloaded_brain_by_picking_a_remote_provider(
        self, process_state
    ):
        """After an unload leaves the Brain dangling, picking any provider
        restores it — the user is never stuck."""
        reg, roles, ak = process_state
        roles.bind("reasoning", _LOCAL_ID, model_override="qwen3-9b")
        kernel = ak.get_agent_kernel("session_iris")
        reg.remove(_LOCAL_ID)
        assert kernel._model_provider == "uninitialized"

        roles.bind("reasoning", "cerebras", model_override="gemma-4-31b")
        assert kernel._model_provider == "cerebras"
        assert kernel._selected_reasoning_model == "gemma-4-31b"

    def test_ollama_native_maps_to_the_local_provider_string(self, process_state):
        """OLLAMA-kind providers report "local" (the native-API vocabulary),
        distinct from INPROCESS's "iris_local". Both are locally-served models
        and both must round-trip through the binding."""
        reg, roles, ak = process_state
        reg.add(ProviderInstance(id="ollama", label="Ollama",
                                 kind=ProviderKind.OLLAMA,
                                 model="gpt-oss:120b-cloud",
                                 api_base_url="http://localhost:11434"))
        roles.bind("reasoning", "ollama", model_override="nemotron-3-nano:30b-cloud")

        kernel = ak.get_agent_kernel("session_iris")
        assert kernel._model_provider == "local"
        # The per-role override wins over the instance's registered model.
        assert kernel._selected_reasoning_model == "nemotron-3-nano:30b-cloud"

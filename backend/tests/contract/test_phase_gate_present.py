"""Contract test CT-I3: InferenceRouter.generate()'s phase-gate call survives
Phase 2's card/narration work.

design.md Ripple-Effect Map: the phase scheduler's gate call inside
`InferenceRouter.generate()` is a CONTRACT LOCK, untouched by Phase 2 — "the
phase scheduler passed live testing; do not disturb." Pinned here (not just
in Phase 1's CT-F3) because Phase 2 touches agent_kernel.py / narration.py /
tool_bridge.py narration paths that sit right next to inference call sites;
this guards against an incidental import-order or call-site regression.

Asserts the EFFECT: `phase_manager.acquire()` is actually invoked during a
real `generate()` call, not merely that the source text mentions it.
"""

from __future__ import annotations

from unittest.mock import patch

import backend.agent.inference.registry as _registry_mod
import backend.agent.inference.roles as _roles_mod
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.transport import ApiHttpxTransport
from backend.iris_config import InferenceConfig, ProviderEntry


def _fresh():
    _registry_mod._REGISTRY = None
    _roles_mod._ROLES = None


def _router_with_bound_provider() -> InferenceRouter:
    _fresh()
    cfg = InferenceConfig()
    entry = ProviderEntry(
        id="ct-i3-probe", label="Probe", kind="API", model="probe-model",
        endpoint="https://example.invalid/v1", cred_ref="ct-i3-probe",
    )
    cfg.providers = {entry.id: entry}
    cfg.config_version = 2
    cfg.role_bindings = [{"role": "reasoning", "instance_id": entry.id}]
    return InferenceRouter(cfg)


class TestPhaseGatePresent:
    def test_generate_calls_the_phase_scheduler_gate(self):
        router = _router_with_bound_provider()
        with patch("backend.agent.inference.router.acquire") as acquire_mock, \
             patch.object(ApiHttpxTransport, "generate", return_value=("ok", "", [])):
            router.generate("reasoning", [{"role": "user", "content": "hi"}])
        assert acquire_mock.called, (
            "InferenceRouter.generate() no longer calls the phase-scheduler "
            "gate (phase_manager.acquire) — this is the one Caducean component "
            "that passed live testing (CT-I3 / design.md CONTRACT LOCK)."
        )

    def test_gate_receives_an_oscillator_and_quota_identity(self):
        """Not just "called" — called with the identity the scheduler needs to
        tell this request apart from every other oscillator in the system."""
        router = _router_with_bound_provider()
        with patch("backend.agent.inference.router.acquire") as acquire_mock, \
             patch.object(ApiHttpxTransport, "generate", return_value=("ok", "", [])):
            router.generate("reasoning", [{"role": "user", "content": "hi"}])
        _, kwargs = acquire_mock.call_args
        assert kwargs.get("oscillator_id"), "acquire() called without an oscillator_id"
        assert "quota_id" in kwargs, "acquire() called without a quota_id kwarg"

"""
Role binding table — maps abstract capability roles to provider instances.

Roles are capability slots (e.g. ``reasoning``, ``tool_execution``,
``researcher``).  Each role binds to a single ``ProviderInstance`` (by id)
with an optional ``model_override``.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, replace
from typing import Optional, TYPE_CHECKING

logger = logging.getLogger(__name__)

# Roles that may only be served by a purpose="chat" provider (Phase 4 REQ-6).
# An embedding/rerank model has no chat head; binding one here would fail at
# generate time in a confusing place, far from the misconfiguration.
_CHAT_ONLY_ROLES = frozenset({"reasoning", "tool_execution"})

if TYPE_CHECKING:
    from .provider import ProviderInstance
    from .registry import ProviderRegistry


@dataclass
class RoleBinding:
    """Maps a named role to a provider instance id.

    Attributes:
        role: Capability slot name (e.g. ``"reasoning"``).
        instance_id: References a ``ProviderInstance.id`` in the registry.
        model_override: Optional per-role model name override.
    """

    role: str
    instance_id: str
    model_override: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        return {
            "role": self.role,
            "instance_id": self.instance_id,
            "model_override": self.model_override,
        }


class RoleBindingTable:
    """One-directional mapping from role → ``ProviderInstance``.

    Requires a ``ProviderRegistry`` so that :meth:`resolve` can
    return a ``ProviderInstance`` directly.
    """

    def __init__(self, registry: ProviderRegistry) -> None:
        self._bindings: dict[str, RoleBinding] = {}
        self._registry = registry
        self._lock = threading.Lock()

    def bind(
        self,
        role: str,
        instance_id: str,
        model_override: Optional[str] = None,
    ) -> None:
        """Bind *role* to the provider instance identified by *instance_id*.

        A non-chat provider is REFUSED for the chat-only roles (Phase 4 REQ-6):
        an embedding or rerank model must never serve as the brain or the tool
        runner. That rule was previously enforced only by two frontend
        candidate-list filters (``ModelSwitcher.tsx``, ``ModelInferenceSection``),
        which is not an enforcement boundary — a ``role_bindings`` entry loaded
        from config, or any direct ``bind_role()`` call, bypassed it entirely.

        The check is deliberately narrow: it applies only when the instance is
        ALREADY in the registry and declares a non-chat purpose. An unregistered
        id must still bind, because Phase 1 REQ-3 AC6 requires binding a local
        provider BEFORE its model is loaded (CT-F7), and ``_apply_config`` may
        apply role bindings before the provider collection is populated.

        Refuses rather than raises: ``_apply_config`` binds in a loop with no
        handler, so raising here would turn one bad config line into a failure to
        construct the router at all. The role is left unbound (falling back to the
        default role) and the refusal is logged at ERROR.
        """
        canon = self._canon(role)
        if canon in _CHAT_ONLY_ROLES:
            _inst = self._registry.get(instance_id)
            _purpose = (getattr(_inst, "purpose", "chat") or "chat") if _inst else "chat"
            if _inst is not None and _purpose != "chat":
                logger.error(
                    "[RoleBindingTable] refusing to bind role=%s to provider %r: "
                    "purpose=%r, and %s accepts only purpose='chat' providers "
                    "(Phase 4 REQ-6). The role is left unbound.",
                    canon, instance_id, _purpose, canon,
                )
                return
        with self._lock:
            _existing = self._bindings.get(canon)
            if (
                model_override is None
                and _existing is not None
                and _existing.instance_id == instance_id
            ):
                # Provider-only rebind (no model): preserve the existing
                # model override. Without this, a provider-only
                # set_role_binding (chat ModelSwitcher, dashboard provider
                # pick) wipes the user's model choice and the router falls
                # back to the provider's registered default model — which
                # may be stale (nemotron-3-super-cloud restored from the
                # startup snapshot, 2026-08-16). A rebind to a DIFFERENT
                # instance still resets the model (new provider, no choice
                # yet).
                model_override = _existing.model_override
            self._bindings[canon] = RoleBinding(
                role=canon,
                instance_id=instance_id,
                model_override=model_override,
            )

    def resolve(self, role: str) -> "ProviderInstance":
        """Resolve *role* to its bound ``ProviderInstance``.

        Resolution is case-insensitive and canonicalizes role aliases
        (``"EXECUTION"`` matches ``"tool_execution"``, ``"REASONING"`` matches
        ``"reasoning"``). Raises ``RuntimeError`` if *role* has no binding or
        if the bound instance id no longer exists in the registry.
        """
        canon = self._canon(role)
        with self._lock:
            binding = self._bindings.get(canon)
            if binding is None:
                # Legacy case-insensitive fallback for any un-canonicalized roles.
                for _k, _v in self._bindings.items():
                    if _k.lower() == role.lower():
                        binding = _v
                        break
            if binding is None:
                raise RuntimeError(
                    f"No provider instance bound to role '{role}'"
                )
            inst = self._registry.get(binding.instance_id)
        if inst is None:
            raise RuntimeError(
                f"Provider instance '{binding.instance_id}' (bound to role "
                f"'{role}') not found in registry"
            )
        if binding.model_override:
            # The binding's model_override is the user's explicit per-role
            # choice (dashboard Brain/Tool dropdowns). It must win over the
            # provider's registered default model — otherwise the override is
            # decorative (displayed but never routed): e.g. ollama defaulted
            # to gpt-oss:120b-cloud while the user chose nemotron-3-super-cloud
            # (2026-08-16). Return a copy so the registry entry is untouched.
            inst = replace(inst, model=binding.model_override)
        return inst

    def list(self) -> list[RoleBinding]:
        """Return a snapshot of all current role bindings."""
        with self._lock:
            return list(self._bindings.values())

    def is_bound(self, role: str) -> bool:
        """True if *role* currently has a binding (case/alias-insensitive).

        This is the guard that makes persisted config a SEED rather than a
        continuous authority. The table is a process-wide singleton holding the
        user's LIVE choice; anything replaying a stored copy of that choice
        (``InferenceRouter._apply_config``, which runs on every router
        construction and therefore on every new conversation kernel) must
        consult this first and bind only what nobody has chosen yet.
        """
        canon = self._canon(role)
        with self._lock:
            return canon in self._bindings

    def unbind(self, role: str) -> None:
        """Remove the binding for *role* (case-insensitive). No-op if unbound."""
        with self._lock:
            if role in self._bindings:
                del self._bindings[role]
                return
            for _k in list(self._bindings.keys()):
                if _k.lower() == role.lower():
                    del self._bindings[_k]
                    return

    @staticmethod
    def _canon(role: str) -> str:
        """Canonicalize a role name so the various spellings used across the
        codebase resolve to the same binding.

        - reasoning / brain / REASONING / ``"reasoning"`` -> ``reasoning``
        - tool_execution / tool / execution / EXECUTION / ``"tool_execution"``
          -> ``tool_execution``
        """
        r = (role or "").strip().lower()
        if r in ("reasoning", "brain", "think", "reason"):
            return "reasoning"
        if r in ("tool_execution", "tool", "execution", "exec", "tools"):
            return "tool_execution"
        return r


# Process-wide singleton. REQ-5: role bindings live in ONE place, not per
# kernel. Shares the process-wide registry so the API endpoint and the live
# session cannot disagree about which provider serves which role.
_ROLES: Optional["RoleBindingTable"] = None
_ROLES_LOCK = threading.Lock()


def get_role_binding_table() -> "RoleBindingTable":
    """Return the process-wide role-binding table (creating it once)."""
    from .registry import get_provider_registry

    global _ROLES
    if _ROLES is None:
        with _ROLES_LOCK:
            if _ROLES is None:
                _ROLES = RoleBindingTable(get_provider_registry())
    return _ROLES



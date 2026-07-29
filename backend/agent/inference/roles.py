"""
Role binding table — maps abstract capability roles to provider instances.

Roles are capability slots (e.g. ``reasoning``, ``tool_execution``,
``researcher``).  Each role binds to a single ``ProviderInstance`` (by id)
with an optional ``model_override``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

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
        """Bind *role* to the provider instance identified by *instance_id*."""
        canon = self._canon(role)
        with self._lock:
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
        return inst

    def list(self) -> list[RoleBinding]:
        """Return a snapshot of all current role bindings."""
        with self._lock:
            return list(self._bindings.values())

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



"""
Role binding table — maps abstract capability roles to provider instances.

Roles are capability slots (e.g. ``reasoning``, ``tool_execution``,
``researcher``).  Each role binds to a single ``ProviderInstance`` (by id)
with an optional ``model_override``.
"""

from __future__ import annotations

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

    def bind(
        self,
        role: str,
        instance_id: str,
        model_override: Optional[str] = None,
    ) -> None:
        """Bind *role* to the provider instance identified by *instance_id*."""
        self._bindings[role] = RoleBinding(
            role=role,
            instance_id=instance_id,
            model_override=model_override,
        )

    def resolve(self, role: str) -> ProviderInstance:
        """Resolve *role* to its bound ``ProviderInstance``.

        Resolution is case-insensitive (``"REASONING"`` matches
        ``"reasoning"``). Raises ``RuntimeError`` if *role* has no binding
        (and no case-insensitive match) or if the bound instance id no
        longer exists in the registry.
        """
        binding = self._bindings.get(role)
        if binding is None:
            # Case-insensitive fallback
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
        return list(self._bindings.values())

    def unbind(self, role: str) -> None:
        """Remove the binding for *role* (case-insensitive). No-op if unbound."""
        if role in self._bindings:
            del self._bindings[role]
            return
        for _k in list(self._bindings.keys()):
            if _k.lower() == role.lower():
                del self._bindings[_k]
                return

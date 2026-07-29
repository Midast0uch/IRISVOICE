"""
Thread-safe in-memory provider registry.

Stores named ``ProviderInstance`` objects so the router can look them up
by id when resolving role bindings.
"""

from __future__ import annotations

import threading
from typing import Optional

from .provider import ProviderInstance


class ProviderRegistry:
    """Registry of named provider instances.

    Thread-safe (uses a single lock around all mutations).  Instances
    are identified by their ``id`` field.
    """

    def __init__(self) -> None:
        self._instances: dict[str, ProviderInstance] = {}
        self._lock = threading.Lock()

    def add(self, inst: ProviderInstance) -> None:
        """Add or replace a provider instance by id."""
        with self._lock:
            self._instances[inst.id] = inst

    def get(self, id: str) -> Optional[ProviderInstance]:
        """Look up a provider instance by id, or return *None*."""
        with self._lock:
            return self._instances.get(id)

    def list(self) -> list[ProviderInstance]:
        """Return a snapshot of all registered instances."""
        with self._lock:
            return list(self._instances.values())

    def remove(self, id: str) -> None:
        """Remove the instance identified by *id* (no-op if missing)."""
        with self._lock:
            self._instances.pop(id, None)

    def all_providers(self) -> dict[str, "ProviderInstance"]:
        """Return a copy of the id → instance map (for introspection)."""
        with self._lock:
            return dict(self._instances)


# Process-wide singleton. REQ-5: provider state lives in ONE place, not per
# kernel. Every InferenceRouter and every WebSocket session reads this same
# registry, so the API endpoint and the live session cannot disagree about
# which models exist.
_REGISTRY: Optional["ProviderRegistry"] = None
_REGISTRY_LOCK = threading.Lock()


def get_provider_registry() -> "ProviderRegistry":
    """Return the process-wide provider registry (creating it once)."""
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = ProviderRegistry()
    return _REGISTRY

"""
Provider definitions for the inference routing layer.

ProviderKind enumerates the four transport families.
ProviderInstance is the canonical data object that pairs a logical provider
identity with its concrete kind, model name, and endpoint URL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ProviderKind(str, Enum):
    """Transport families that the InferenceRouter dispatches to."""

    API = "api"
    LOCAL_OPENAI = "local_openai"
    INPROCESS = "inprocess"
    OLLAMA = "ollama"


@dataclass
class ProviderInstance:
    """A named provider instance that can be bound to one or more roles.

    Attributes:
        id: Unique identifier for this instance (e.g. ``"cerebras"``).
        label: Human-readable label for UI display.
        kind: Which transport family to use.
        model: Default model name string (may be overridden per role).
        api_base_url: Base URL for API / LOCAL_OPENAI / OLLAMA transports.
    """

    id: str
    label: str
    kind: ProviderKind
    model: Optional[str] = None
    api_base_url: str = ""

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict (enum → its string value)."""
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind.value,
            "model": self.model,
            "api_base_url": self.api_base_url,
        }

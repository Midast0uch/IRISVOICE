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
        id: Unique identifier for this instance (e.g. ``"cerebras"`` or
            ``"local:qwen3-9b"`` — never the bare literal ``"local"``).
        label: Human-readable label for UI display.
        kind: Which transport family to use.
        model: Default model name string (may be overridden per role).
        api_base_url: Base URL for API / LOCAL_OPENAI / OLLAMA transports.
        purpose: What the provider is for (``chat`` | ``embedding`` | ``rerank``).
            Defaults to ``chat``; non-chat providers are filtered out of the
            chat-model UI (Phase 4).
        loaded: Whether the model backing this (local) provider is currently
            loaded into memory. Additive to the payload (REQ-3 AC2).
        loading: Whether a load is in progress. Additive to the payload.
    """

    id: str
    label: str
    kind: ProviderKind
    model: Optional[str] = None
    api_base_url: str = ""
    api_key: str = ""
    purpose: str = "chat"
    loaded: bool = False
    loading: bool = False

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict (enum → its string value).

        Additive: ``id`` / ``label`` / ``kind`` / ``model`` / ``api_base_url`` /
        ``has_key`` are retained (CT-F6) and ``loaded`` / ``loading`` /
        ``purpose`` are added. No credential or credential fragment is ever
        included.
        """
        # Resolve whether a credential exists: prefer an explicitly attached
        # key, else fall back to the secret store (legacy config keys are
        # persisted there keyed by provider id at router init).
        _has_key = bool(self.api_key)
        if not _has_key:
            try:
                from .keyring import get_secret
                _has_key = bool(get_secret(self.id))
            except Exception:
                pass
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind.value,
            "model": self.model,
            "api_base_url": self.api_base_url,
            # Signal to the UI whether a credential is already configured for
            # this provider instance, so it can show "Key set" instead of a
            # blank input and allow Apply without re-entering the key.
            "has_key": _has_key,
            # Additive load-state + purpose fields (REQ-3 AC2, REQ-4 AC3).
            "loaded": self.loaded,
            "loading": self.loading,
            "purpose": self.purpose,
        }


# Canonical list of supported providers. Single source of truth:
# the frontend sources its Provider dropdown from this list, and the backend
# derives the default api_base_url when a provider is selected in
# set_model_selection. `needs_key` distinguishes API providers (require an
# API key) from local OpenAI-compatible servers (LM Studio) which only need a
# base URL.
PROVIDER_PRESETS: list[dict] = [
    {"id": "openai", "label": "OpenAI", "kind": "api", "needs_key": True,
     "api_base_url": "https://api.openai.com/v1"},
    {"id": "cerebras", "label": "Cerebras", "kind": "api", "needs_key": True,
     "api_base_url": "https://api.cerebras.ai/v1"},
    {"id": "opencodego", "label": "OpenCodeGo", "kind": "api", "needs_key": True,
     "api_base_url": "https://opencode.ai/zen/go/v1"},
    {"id": "chutes", "label": "Chutes AI", "kind": "api", "needs_key": True,
     "api_base_url": "https://llm.chutes.ai/v1"},
    {"id": "cohere", "label": "Cohere", "kind": "api", "needs_key": True,
     "api_base_url": "https://api.cohere.ai/compatibility/v1"},
    {"id": "deepseek", "label": "DeepSeek", "kind": "api", "needs_key": True,
     "api_base_url": "https://api.deepseek.com"},
    {"id": "anthropic", "label": "Anthropic", "kind": "api", "needs_key": True,
     "api_base_url": "https://api.anthropic.com/v1"},
    {"id": "lmstudio", "label": "LM Studio", "kind": "local_openai", "needs_key": False,
     "api_base_url": "http://localhost:1234"},
]


def get_provider_default_endpoint(provider_id: Optional[str]) -> Optional[str]:
    """Return the canonical default api_base_url for a provider preset id,
    or None if the provider is unknown / local-only. This is the dynamic
    resolution used when a provider is selected in set_model_selection and
    when the router re-applies config on restart — the URL always follows
    the provider id from the config, never a stale stored value."""
    if not provider_id:
        return None
    for _p in PROVIDER_PRESETS:
        if _p["id"] == provider_id:
            return _p.get("api_base_url")
    return None


def register_builtin_encoder_providers() -> None:
    """Register the LFM2.5 encoder providers as non-chat, CPU-only providers
    (REQ-6 AC1/AC2/AC4). They are NOT bound to reasoning/tool_execution, so they
    can never serve as the user's brain or tool runner.

    Embedding-350M is always registered (purpose="embedding"). ColBERT-350M
    (purpose="rerank") is deferred behind a quality gate (REQ-7 AC6) and only
    registered when explicitly enabled via IRIS_ENABLE_COLBERT, so it stays out
    of the default provider list until its retrieval quality is measured.
    """
    import os
    from .registry import get_provider_registry

    reg = get_provider_registry()

    if reg.get("embedding:lfm25-emb-350m") is None:
        reg.add(
            ProviderInstance(
                id="embedding:lfm25-emb-350m",
                label="LFM2.5 Embedding 350M",
                kind=ProviderKind.INPROCESS,
                model="LFM2.5-Embedding-350M",
                purpose="embedding",
            )
        )

    if os.environ.get("IRIS_ENABLE_COLBERT", "").lower() in ("1", "true", "yes"):
        if reg.get("rerank:lfm25-colbert-350m") is None:
            reg.add(
                ProviderInstance(
                    id="rerank:lfm25-colbert-350m",
                    label="LFM2.5 ColBERT 350M (rerank)",
                    kind=ProviderKind.INPROCESS,
                    model="LFM2.5-ColBERT-350M",
                    purpose="rerank",
                )
            )

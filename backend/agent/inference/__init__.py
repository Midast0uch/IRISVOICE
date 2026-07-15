"""
Inference routing layer for IRIS Voice.

Provides a clean, modular replacement for the ad-hoc provider dispatch
currently embedded in ``AgentKernel``.  See ``docs/LLM_ROUTING_TARGET.md``
for the full design.
"""

from .provider import ProviderInstance, ProviderKind
from .registry import ProviderRegistry
from .roles import RoleBindingTable
from .router import InferenceRouter
from .transport import Transport

__all__ = [
    "InferenceRouter",
    "ProviderInstance",
    "ProviderKind",
    "ProviderRegistry",
    "RoleBindingTable",
    "Transport",
]

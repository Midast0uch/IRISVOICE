"""
Provider Model Catalog — Single Source of Truth for available models per provider.

Provides comprehensive, up-to-date model lists for all supported cloud & local AI providers,
including Venice AI, OpenCodeGo, Cerebras, Chutes, CommandCode, Cohere, OpenAI, Anthropic, DeepSeek,
Groq, Mistral, Together, OpenRouter, LM Studio, and Ollama.
"""

from __future__ import annotations

from typing import Dict, List, Optional

PROVIDER_MODEL_CATALOG: Dict[str, List[Dict[str, str]]] = {
    "venice": [
        {"id": "default", "name": "Default (Venice Recommended)"},
        {"id": "default_reasoning", "name": "Default Reasoning (DeepSeek R1)"},
        {"id": "default_code", "name": "Default Code (Qwen Coder)"},
        {"id": "inkling", "name": "Inkling 975B MoE (Thinking Machines Lab)"},
        {"id": "gpt-5.6-terra-pro", "name": "GPT-5.6 Terra Pro"},
        {"id": "terra", "name": "Terra (Alias)"},
        {"id": "deepseek-r1-671b", "name": "DeepSeek R1 671B"},
        {"id": "deepseek-v3", "name": "DeepSeek V3"},
        {"id": "llama-3.3-70b", "name": "Llama 3.3 70B"},
        {"id": "qwen-2.5-72b", "name": "Qwen 2.5 72B"},
        {"id": "dolphin-2.9.2-qwen2-72b", "name": "Venice Uncensored (Dolphin Qwen 72B)"},
        {"id": "qwen-2.5-coder-32b", "name": "Qwen 2.5 Coder 32B"},
        {"id": "llama-3.2-3b", "name": "Llama 3.2 3B"},
        {"id": "mistral-3b-venice", "name": "Mistral 3B Venice Edition"},
    ],
    "opencodego": [
        {"id": "gpt-5.6-luna", "name": "GPT-5.6 Luna"},
        {"id": "luna", "name": "Luna Code (Alias)"},
        {"id": "kimi-k3", "name": "Kimi K3 (2.8T MoE)"},
        {"id": "kimi-k2.7", "name": "Kimi K2.7"},
        {"id": "kimi-k2.6", "name": "Kimi K2.6"},
        {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro"},
        {"id": "deepseek-v4-flash", "name": "DeepSeek V4 Flash"},
        {"id": "deepseek-v3", "name": "DeepSeek V3"},
        {"id": "deepseek-r1", "name": "DeepSeek R1"},
        {"id": "qwen3.7-max", "name": "Qwen 3.7 Max"},
        {"id": "qwen3-32b", "name": "Qwen 3 32B"},
        {"id": "glm-5.2", "name": "GLM 5.2"},
        {"id": "glm-5.1", "name": "GLM 5.1"},
        {"id": "minimax-m3", "name": "MiniMax M3"},
        {"id": "minimax-m2.7", "name": "MiniMax M2.7"},
    ],
    "deepseek": [
        {"id": "deepseek-v4", "name": "DeepSeek V4 (Flagship)"},
        {"id": "deepseek-v4-flash", "name": "DeepSeek V4 Flash"},
        {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro"},
        {"id": "deepseek-reasoner", "name": "DeepSeek R1 (Reasoner)"},
        {"id": "deepseek-chat", "name": "DeepSeek V3 / V3.2 (Chat)"},
        {"id": "deepseek-r1-zero", "name": "DeepSeek R1 Zero"},
        {"id": "deepseek-coder", "name": "DeepSeek Coder V2"},
        {"id": "deepseek-r1", "name": "DeepSeek R1 (Alias)"},
        {"id": "deepseek-v3", "name": "DeepSeek V3 (Alias)"},
    ],
    "cerebras": [
        {"id": "gpt-oss-120b", "name": "GPT OSS 120B (Recommended)"},
        {"id": "zai-glm-4.7", "name": "Z.ai GLM 4.7"},
        {"id": "gemma-4-31b", "name": "Gemma 4 31B Preview"},
        {"id": "qwen-3-235b-instruct", "name": "Qwen 3 235B Instruct"},
        {"id": "qwen-3-235b-thinking", "name": "Qwen 3 235B Thinking"},
        {"id": "qwen-3-32b", "name": "Qwen 3 32B"},
        {"id": "llama-3.3-70b", "name": "Llama 3.3 70B"},
        {"id": "llama-3.1-70b", "name": "Llama 3.1 70B"},
        {"id": "llama-3.1-8b", "name": "Llama 3.1 8B"},
        {"id": "deepseek-r1-distill-llama-70b", "name": "DeepSeek R1 70B"},
    ],
    "chutes": [
        {"id": "deepseek-ai/DeepSeek-V3.2-TEE", "name": "DeepSeek V3.2 TEE"},
        {"id": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek V3"},
        {"id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek R1"},
        {"id": "Qwen/Qwen3.5-397B", "name": "Qwen 3.5 397B"},
        {"id": "Qwen/Qwen3-32B-TEE", "name": "Qwen3 32B TEE"},
        {"id": "google/gemma-4-31B-turbo-TEE", "name": "Gemma 4 31B Turbo TEE"},
        {"id": "zai-org/GLM-5.2-TEE", "name": "GLM 5.2 TEE"},
        {"id": "zai-org/GLM-5.1-TEE", "name": "GLM 5.1 TEE"},
        {"id": "moonshotai/Kimi-K2.6-TEE", "name": "Kimi K2.6 TEE"},
    ],
    "commandcode": [
        {"id": "gpt-5.5", "name": "GPT-5.5"},
        {"id": "gpt-5.4", "name": "GPT-5.4"},
        {"id": "gpt-5.4-mini", "name": "GPT-5.4 Mini"},
        {"id": "gpt-5.3-codex", "name": "GPT-5.3 Codex"},
        {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
        {"id": "claude-opus-4-7", "name": "Claude Opus 4.7"},
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
        {"id": "moonshotai/Kimi-K2.6", "name": "Kimi K2.6"},
        {"id": "zai-org/GLM-5.1", "name": "GLM 5.1"},
    ],
    "cohere": [
        {"id": "command-a-plus-05-2026", "name": "Command A+ (latest)"},
        {"id": "command-a-03-2025", "name": "Command A"},
        {"id": "command-r-plus-08-2024", "name": "Command R+"},
        {"id": "command-r-08-2024", "name": "Command R"},
        {"id": "command-r7b-12-2024", "name": "Command R7B"},
        {"id": "command-r-plus", "name": "Command R+ (Alias)"},
        {"id": "command-r", "name": "Command R (Alias)"},
    ],
    "openai": [
        {"id": "gpt-5.5", "name": "GPT-5.5"},
        {"id": "gpt-5.4", "name": "GPT-5.4"},
        {"id": "gpt-5.4-mini", "name": "GPT-5.4 Mini"},
        {"id": "o4-mini", "name": "o4-mini"},
        {"id": "o3", "name": "o3"},
        {"id": "o3-mini", "name": "o3-mini"},
        {"id": "o1", "name": "o1"},
        {"id": "o1-mini", "name": "o1-mini"},
        {"id": "o1-preview", "name": "o1-preview"},
        {"id": "gpt-4o", "name": "GPT-4o"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
        {"id": "gpt-4.5-preview", "name": "GPT-4.5 Preview"},
        {"id": "gpt-4-turbo", "name": "GPT-4 Turbo"},
    ],
    "anthropic": [
        {"id": "claude-opus-5", "name": "Claude Opus 5"},
        {"id": "claude-sonnet-5", "name": "Claude Sonnet 5"},
        {"id": "claude-opus-4", "name": "Claude Opus 4"},
        {"id": "claude-sonnet-4", "name": "Claude Sonnet 4"},
        {"id": "claude-3-7-sonnet-20250219", "name": "Claude 3.7 Sonnet (Reasoning)"},
        {"id": "claude-3-7-sonnet", "name": "Claude 3.7 Sonnet (Alias)"},
        {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet"},
        {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku"},
        {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus"},
    ],
    "groq": [
        {"id": "deepseek-r1-distill-llama-70b", "name": "DeepSeek R1 Distill Llama 70B"},
        {"id": "deepseek-r1-distill-qwen-32b", "name": "DeepSeek R1 Distill Qwen 32B"},
        {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B Versatile"},
        {"id": "llama-3.3-70b-specdec", "name": "Llama 3.3 70B SpecDec"},
        {"id": "llama-3.1-70b-versatile", "name": "Llama 3.1 70B Versatile"},
        {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B Instant"},
        {"id": "llama-3.2-3b-preview", "name": "Llama 3.2 3B Preview"},
        {"id": "llama-3.2-1b-preview", "name": "Llama 3.2 1B Preview"},
        {"id": "qwen-2.5-32b", "name": "Qwen 2.5 32B"},
        {"id": "qwen-2.5-coder-32b", "name": "Qwen 2.5 Coder 32B"},
        {"id": "gemma2-9b-it", "name": "Gemma 2 9B"},
        {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B"},
    ],
    "mistral": [
        {"id": "mistral-large-latest", "name": "Mistral Large"},
        {"id": "pixtral-large-latest", "name": "Pixtral Large"},
        {"id": "codestral-latest", "name": "Codestral"},
        {"id": "mistral-small-latest", "name": "Mistral Small"},
        {"id": "open-mixtral-8x22b", "name": "Mixtral 8x22B"},
        {"id": "open-mixtral-8x7b", "name": "Mixtral 8x7B"},
        {"id": "mistral-embed", "name": "Mistral Embed"},
    ],
    "together": [
        {"id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek R1"},
        {"id": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek V3"},
        {"id": "deepseek-ai/DeepSeek-R1-Distill-Llama-70B", "name": "DeepSeek R1 Distill 70B"},
        {"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "name": "Llama 3.3 70B Turbo"},
        {"id": "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo", "name": "Llama 3.1 405B Turbo"},
        {"id": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", "name": "Llama 3.1 70B Turbo"},
        {"id": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo", "name": "Llama 3.1 8B Turbo"},
        {"id": "Qwen/Qwen2.5-72B-Instruct-Turbo", "name": "Qwen 2.5 72B Turbo"},
        {"id": "Qwen/Qwen2.5-Coder-32B-Instruct", "name": "Qwen 2.5 Coder 32B"},
        {"id": "mistralai/Mistral-Small-24B-Instruct-2501", "name": "Mistral Small 24B"},
        {"id": "mistralai/Mixtral-8x22B-Instruct-v0.1", "name": "Mixtral 8x22B"},
    ],
    "openrouter": [
        {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1"},
        {"id": "deepseek/deepseek-chat", "name": "DeepSeek V3"},
        {"id": "anthropic/claude-3.7-sonnet", "name": "Claude 3.7 Sonnet"},
        {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet"},
        {"id": "openai/gpt-4o", "name": "GPT-4o"},
        {"id": "openai/o3-mini", "name": "o3-mini"},
        {"id": "openai/o1", "name": "o1"},
        {"id": "google/gemini-2.0-flash-001", "name": "Gemini 2.0 Flash"},
        {"id": "google/gemini-2.0-pro-exp-02-05", "name": "Gemini 2.0 Pro"},
        {"id": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B"},
        {"id": "qwen/qwen-2.5-coder-32b-instruct", "name": "Qwen 2.5 Coder 32B"},
    ],
    "lmstudio": [
        {"id": "local-model", "name": "Currently Loaded Model"},
        {"id": "deepseek-r1-distill-qwen-7b", "name": "DeepSeek R1 Distill Qwen 7B"},
        {"id": "deepseek-r1-distill-llama-8b", "name": "DeepSeek R1 Distill Llama 8B"},
        {"id": "llama-3.3-70b-instruct", "name": "Llama 3.3 70B Instruct"},
        {"id": "llama-3.2-3b-instruct", "name": "Llama 3.2 3B Instruct"},
        {"id": "llama-3.1-8b-instruct", "name": "Llama 3.1 8B Instruct"},
        {"id": "mistral-7b-instruct-v0.3", "name": "Mistral 7B Instruct"},
        {"id": "qwen2.5-7b-instruct", "name": "Qwen 2.5 7B Instruct"},
        {"id": "qwen2.5-coder-32b-instruct", "name": "Qwen 2.5 Coder 32B Instruct"},
    ],
    "ollama": [
        # ── Cloud models (run on ollama.com, proxied via local server) ──
        # VERIFIED against ollama.com 2026-08-16: every id below pulls cleanly
        # (`ollama pull` succeeds). The previous list was ~80% fabricated —
        # nemotron-3-super-cloud, nemotron-3-ultra-cloud, glm-5.2-cloud,
        # kimi-k3-cloud, kimi-k2.6-cloud, kimi-k2.7-code-cloud, gpt-oss:20b-cloud,
        # minimax-*, gemma4:31b-cloud, qwen3.5:397b-cloud, mistral-large-3:675b-cloud
        # and all deepseek-v4-* variants return "pull model manifest: file does
        # not exist" and 404 at inference. IDs use the ollama `:` tag format
        # (glm-5.1:cloud, NOT glm-5.1-cloud).
        {"id": "gpt-oss:120b-cloud", "name": "GPT-OSS (120B, cloud)"},
        {"id": "nemotron-3-nano:30b-cloud", "name": "Nemotron 3 Nano (30B, cloud)"},
        {"id": "glm-5.1:cloud", "name": "GLM 5.1 (cloud)"},
        {"id": "kimi-k2.5:cloud", "name": "Kimi K2.5 (cloud)"},
        {"id": "kimi-k2-thinking:cloud", "name": "Kimi K2 Thinking (1T, cloud)"},
        # ── Local models (run on this machine) ──
        {"id": "deepseek-r1:7b", "name": "DeepSeek R1 (7B)"},
        {"id": "deepseek-r1:8b", "name": "DeepSeek R1 (8B)"},
        {"id": "deepseek-r1:14b", "name": "DeepSeek R1 (14B)"},
        {"id": "deepseek-r1:32b", "name": "DeepSeek R1 (32B)"},
        {"id": "deepseek-r1:70b", "name": "DeepSeek R1 (70B)"},
        {"id": "deepseek-v3", "name": "DeepSeek V3"},
        {"id": "llama3.3", "name": "Llama 3.3 (70B)"},
        {"id": "llama3.2", "name": "Llama 3.2 (3B)"},
        {"id": "llama3.2:1b", "name": "Llama 3.2 (1B)"},
        {"id": "llama3.1", "name": "Llama 3.1 (8B)"},
        {"id": "llama3.1:70b", "name": "Llama 3.1 (70B)"},
        {"id": "qwen2.5:7b", "name": "Qwen 2.5 (7B)"},
        {"id": "qwen2.5:32b", "name": "Qwen 2.5 (32B)"},
        {"id": "qwen2.5-coder", "name": "Qwen 2.5 Coder"},
        {"id": "mistral", "name": "Mistral 7B"},
        {"id": "mixtral", "name": "Mixtral 8x7B"},
        {"id": "phi4", "name": "Phi-4 (14B)"},
        {"id": "codellama", "name": "Code Llama"},
        # ── Models present on this machine (from `ollama list`) ──
        {"id": "granite3.3:8b", "name": "Granite 3.3 (8B)"},
        {"id": "ibm/granite3.3:2b-base", "name": "Granite 3.3 (2B base)"},
        {"id": "openbmb/minicpm-o4.5:latest", "name": "MiniCPM-O 4.5"},
        {"id": "koiiLlama:latest", "name": "Koii Llama"},
    ],
}


def get_catalog_for_provider(provider_id: Optional[str]) -> List[Dict[str, str]]:
    """Return model catalog for a given provider id, falling back to empty list if unknown."""
    if not provider_id:
        return []
    p = provider_id.lower().strip()
    return PROVIDER_MODEL_CATALOG.get(p, [])


def get_default_model_for_provider(provider_id: Optional[str]) -> Optional[str]:
    """Return the first (recommended) model id for *provider_id*, or None.

    Used when a provider instance is registered without a model: a provider
    whose ``model`` is empty makes every downstream "which model?" resolution
    fall through to whatever value the caller happened to be carrying — which
    is how a freshly-selected provider ended up wearing the PREVIOUS
    provider's model id.
    """
    cat = get_catalog_for_provider(provider_id)
    return cat[0]["id"] if cat else None


def model_belongs_to_provider(
    provider_id: Optional[str], model_id: Optional[str]
) -> bool:
    """True when *model_id* is offered by *provider_id*.

    A provider with NO catalog entry (local:<stem>, ollama at runtime, a custom
    endpoint) accepts anything — absence of a catalog is not evidence that a
    model is wrong. Callers must only enforce this for providers whose catalog
    is authoritative (the hosted API presets), never for local servers where the
    catalog is a suggestion list.
    """
    if not model_id:
        return False
    cat = get_catalog_for_provider(provider_id)
    if not cat:
        return True
    return any(m.get("id") == model_id for m in cat)

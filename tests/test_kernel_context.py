"""
Direct kernel-level tests: context window, provider switching, modes
Tests the AgentKernel methods without needing WebSocket.
"""

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_resolve_context_window():
    """Test that resolve_context_window returns correct values per provider+model."""
    from backend.agent.agent_kernel import get_agent_kernel

    kernel = get_agent_kernel("test_ctx_001")
    results = []

    # Test 1: Default (no model selected)
    ctx = kernel.resolve_context_window()
    results.append(("Default context window", ctx == 8192, f"got {ctx}"))

    # Test 2: Cohere command-r-plus
    kernel.set_model_selection(
        reasoning_model="command-r-plus",
        tool_execution_model="command-r-plus",
        model_provider="cohere",
    )
    ctx = kernel.resolve_context_window()
    results.append(("Cohere command-r-plus → 128k", ctx == 128_000, f"got {ctx}"))

    # Test 3: OpenAI gpt-4o
    kernel.set_model_selection(
        reasoning_model="gpt-4o", tool_execution_model="gpt-4o", model_provider="openai"
    )
    ctx = kernel.resolve_context_window()
    results.append(("OpenAI gpt-4o → 128k", ctx == 128_000, f"got {ctx}"))

    # Test 4: Groq llama3-70b
    kernel.set_model_selection(
        reasoning_model="llama3-70b-8192",
        tool_execution_model="llama3-70b-8192",
        model_provider="groq",
    )
    ctx = kernel.resolve_context_window()
    results.append(("Groq llama3-70b → 8k", ctx == 8_192, f"got {ctx}"))

    # Test 5: LM Studio LFM-2-8B
    kernel.set_model_selection(
        reasoning_model="LFM-2-8B",
        tool_execution_model="LFM-2-8B",
        model_provider="lmstudio",
    )
    ctx = kernel.resolve_context_window()
    results.append(("LM Studio LFM-2-8B → 32k", ctx == 32_768, f"got {ctx}"))

    # Test 6: User override
    kernel._context_window_overrides["LFM-2-8B"] = 16_000
    ctx = kernel.resolve_context_window()
    results.append(("Override LFM-2-8B → 16k", ctx == 16_000, f"got {ctx}"))
    del kernel._context_window_overrides["LFM-2-8B"]

    # Test 7: Token budget is 75% of context window
    kernel.set_model_selection(
        reasoning_model="gpt-4o", tool_execution_model="gpt-4o", model_provider="openai"
    )
    budget = kernel.get_effective_token_budget()
    expected = int(128_000 * 0.75)
    results.append(
        ("Token budget = 75% of 128k = 96k", budget == expected, f"got {budget}")
    )

    # Test 8: DeepSeek
    kernel.set_model_selection(
        reasoning_model="deepseek-chat",
        tool_execution_model="deepseek-chat",
        model_provider="deepseek",
    )
    ctx = kernel.resolve_context_window()
    results.append(("DeepSeek deepseek-chat → 65k", ctx == 65_536, f"got {ctx}"))

    # Test 9: IRIS Local
    kernel.set_model_selection(
        reasoning_model="LFM-2-8B",
        tool_execution_model="LFM-2-8B",
        model_provider="iris_local",
    )
    ctx = kernel.resolve_context_window()
    results.append(("IRIS Local LFM-2-8B → 32k", ctx == 32_768, f"got {ctx}"))

    return results


def test_memory_config_sync():
    """Test that memory config gets updated when context window changes."""
    from backend.agent.agent_kernel import get_agent_kernel
    from backend.memory.config import get_config, update_context_size

    kernel = get_agent_kernel("test_mem_001")
    results = []

    # Set initial context
    update_context_size(32_000)
    config = get_config()
    results.append(
        (
            "Memory config set to 32k",
            config.max_context_size == 32_000,
            f"got {config.max_context_size}",
        )
    )

    # Update via kernel
    kernel.set_model_selection(
        reasoning_model="gpt-4o", tool_execution_model="gpt-4o", model_provider="openai"
    )
    config = get_config()
    expected = int(128_000 * 0.75)
    results.append(
        (
            "Memory config synced to 96k (75% of 128k)",
            config.max_context_size == expected,
            f"got {config.max_context_size}",
        )
    )

    return results


def test_provider_switching():
    """Test that switching providers mid-session works."""
    from backend.agent.agent_kernel import get_agent_kernel

    kernel = get_agent_kernel("test_switch_001")
    results = []

    # Start with Cohere
    kernel.configure_api("cohere_key", "https://api.cohere.com/compatibility/v1")
    kernel._model_provider = "cohere"
    kernel._selected_reasoning_model = "command-r-plus"
    ctx1 = kernel.resolve_context_window()
    results.append(("Cohere → 128k", ctx1 == 128_000, f"got {ctx1}"))

    # Switch to LM Studio
    kernel.configure_lmstudio("http://localhost:1234")
    kernel._model_provider = "lmstudio"
    kernel._model_name = "LFM-2-8B"
    kernel._selected_reasoning_model = "LFM-2-8B"
    ctx2 = kernel.resolve_context_window()
    results.append(("Switch to LM Studio → 32k", ctx2 == 32_768, f"got {ctx2}"))

    # Switch back to Cohere
    kernel.configure_api("cohere_key2", "https://api.cohere.com/compatibility/v1")
    kernel._model_provider = "cohere"
    kernel._selected_reasoning_model = "command-r-plus"
    ctx3 = kernel.resolve_context_window()
    results.append(("Switch back to Cohere → 128k", ctx3 == 128_000, f"got {ctx3}"))

    return results


def test_mode_endpoint():
    """Test mode switching (personal/developer)."""
    import urllib.request

    results = []

    # Check current mode
    try:
        r = urllib.request.urlopen("http://localhost:8000/api/mode", timeout=5)
        data = __import__("json").loads(r.read())
        mode = data.get("mode", "unknown")
        results.append(("Mode endpoint responds", True, f"mode={mode}"))
    except Exception as e:
        results.append(("Mode endpoint responds", False, str(e)))

    return results


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  KERNEL-LEVEL TESTS: Context Window + Provider Switching")
    print("=" * 60)

    all_results = []

    print("\n[Context Window Resolution]")
    all_results.extend(test_resolve_context_window())

    print("\n[Memory Config Sync]")
    all_results.extend(test_memory_config_sync())

    print("\n[Provider Switching]")
    all_results.extend(test_provider_switching())

    print("\n[Mode Endpoint]")
    all_results.extend(test_mode_endpoint())

    # Print results
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    for name, passed, detail in all_results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {detail}")

    total = len(all_results)
    passed = sum(1 for _, p, _ in all_results if p)
    print(f"\n  {passed}/{total} passed")
    print("=" * 60 + "\n")

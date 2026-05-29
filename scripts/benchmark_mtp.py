#!/usr/bin/env python3
"""
Benchmark MTP speculative decoding vs baseline on a local GGUF model.

Usage:
    # Baseline (no MTP)
    python scripts/benchmark_mtp.py --model "Qwopus3.6-27B-v2-MTP-Q3_K_S" --profile balanced --prompts 5

    # MTP enabled
    python scripts/benchmark_mtp.py --model "Qwopus3.6-27B-v2-MTP-Q3_K_S" --profile balanced_mtp --prompts 5

Requires:
    - Compiled llama-server at IRISVOICE/llama.cpp/build/bin/Release/llama-server.exe
    - model present in C:/Users/midas/.lmstudio/models (or IRIS_MODELS_DIR)
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "agent"))

import httpx
from local_model_manager import LocalModelManager


PROMPTS = [
    "Explain quantum computing in simple terms.",
    "Write a short Python function that sorts a list of dictionaries by a key.",
    "Describe the causes of the French Revolution in three bullet points.",
    "What are the main differences between TCP and UDP?",
    "Summarize the plot of Romeo and Juliet in two sentences.",
]


async def benchmark(args):
    mgr = LocalModelManager()

    # Resolve model path
    model_path = None
    for m in mgr.scan_models():
        if args.model.lower() in m["display_name"].lower():
            model_path = m["path"]
            print(f"Found model: {m['display_name']}")
            print(f"  Path: {model_path}")
            print(f"  MTP capable: {m['is_mtp_capable']}")
            print(f"  VRAM est: {m['vram_estimate_gb']} GB")
            break

    if not model_path:
        print(f"Model '{args.model}' not found in {mgr.MODELS_DIR}")
        sys.exit(1)

    # Ensure clean state
    print("\nUnloading any existing model...")
    await mgr.unload_model()
    await asyncio.sleep(1)

    # Build custom params from CLI overrides
    custom_params = {}
    if args.n_ctx is not None:
        custom_params["n_ctx"] = args.n_ctx
    if args.n_gpu_layers is not None:
        custom_params["n_gpu_layers"] = args.n_gpu_layers

    # Load with selected profile
    print(f"\nLoading model with profile '{args.profile}'...")
    if custom_params:
        print(f"  Overrides: {custom_params}")
    ok = await mgr.load_model(model_path, profile=args.profile, custom_params=custom_params or None)
    if not ok:
        print("Model load failed.")
        sys.exit(1)

    print("Model loaded. Running inference benchmark...\n")

    async with httpx.AsyncClient(timeout=120.0) as client:
        results = []
        for i, prompt in enumerate(PROMPTS[: args.prompts]):
            print(f"  [{i + 1}/{args.prompts}] Prompt: {prompt[:60]}...")
            start = time.perf_counter()
            try:
                payload = {
                    "model": "local",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 128,
                    "temperature": 0.7,
                }
                r = await client.post(
                    f"http://127.0.0.1:{mgr.PORT}/v1/chat/completions",
                    json=payload,
                )
                r.raise_for_status()
                data = r.json()
                elapsed = time.perf_counter() - start
                text = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("completion_tokens", 0)
                tps = tokens / elapsed if elapsed > 0 else 0
                print(f"       -> {tokens} tokens in {elapsed:.2f}s = {tps:.1f} tok/s")
                results.append({"prompt": prompt, "tokens": tokens, "elapsed": elapsed, "tps": tps, "ok": True})
            except Exception as exc:
                elapsed = time.perf_counter() - start
                print(f"       -> ERROR: {exc}")
                results.append({"prompt": prompt, "tokens": 0, "elapsed": elapsed, "tps": 0, "ok": False})

    # Summary
    ok_results = [r for r in results if r["ok"]]
    if ok_results:
        avg_tps = sum(r["tps"] for r in ok_results) / len(ok_results)
        avg_ttft = sum(r["elapsed"] for r in ok_results) / len(ok_results)
        print(f"\n{'=' * 50}")
        print(f"Profile: {args.profile}")
        print(f"Successful runs: {len(ok_results)}/{len(results)}")
        print(f"Average tok/s: {avg_tps:.1f}")
        print(f"Average time: {avg_ttft:.2f}s")
        if mgr._mtp_acceptance_window:
            rolling = sum(mgr._mtp_acceptance_window) / len(mgr._mtp_acceptance_window)
            print(f"MTP acceptance (rolling): {rolling:.1%}")
        print(f"{'=' * 50}")

    # Save results
    out = Path(__file__).parent.parent / f"benchmark_{args.profile}.json"
    with open(out, "w") as f:
        json.dump(
            {
                "profile": args.profile,
                "model": args.model,
                "results": results,
                "mtp_acceptance_window": mgr._mtp_acceptance_window,
            },
            f,
            indent=2,
        )
    print(f"Results saved to {out}")

    mgr.unload_model()


def main():
    parser = argparse.ArgumentParser(description="Benchmark local GGUF model")
    parser.add_argument("--model", default="qwopus", help="Model name substring (case-insensitive)")
    parser.add_argument("--profile", default="balanced_mtp", choices=["balanced", "balanced_mtp"], help="Hardware profile")
    parser.add_argument("--prompts", type=int, default=3, help="Number of prompts to run")
    parser.add_argument("--n-ctx", type=int, default=None, help="Override context size (default from profile)")
    parser.add_argument("--n-gpu-layers", type=int, default=None, help="Override GPU layers (default from profile, -1=all)")
    args = parser.parse_args()
    asyncio.run(benchmark(args))


if __name__ == "__main__":
    main()

"""
bench_9b_tps.py — IRIS Gate 1 TPS benchmark for 9B GGUF models on RTX 3070.

Tests both available 9B quantizations with optimal settings for RTX 3070 8 GB VRAM.
Target: >= 25 tok/s sustained generation.

Usage:
  python scripts/bench_9b_tps.py
  python scripts/bench_9b_tps.py --model Q3_K_S   # only test Q3_K_S variant
  python scripts/bench_9b_tps.py --model Q4_K_M   # only test Q4_K_M variant
  python scripts/bench_9b_tps.py --ctx 4096        # custom context window
"""
import argparse
import sys
import time
from pathlib import Path

# ── Target ──────────────────────────────────────────────────────────────────
TARGET_TPS = 25.0
GEN_TOKENS = 256      # tokens to generate per run
N_WARMUP   = 1        # warmup passes (not counted)
N_RUNS     = 3        # timed passes averaged

# ── Model paths ─────────────────────────────────────────────────────────────
MODELS_DIR = Path.home() / ".lmstudio" / "models"

MODELS = {
    "Q3_K_S": MODELS_DIR / "unsloth" / "Qwen3.5-9B-GGUF" / "Qwen3.5-9B-Q3_K_S.gguf",
    "Q4_K_M": MODELS_DIR / "HauhauCS" / "Qwen3.5-9B-Uncensored-HauhauCS-Aggressive" / "Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf",
}

# Fallback: glob for any 9B GGUF if paths don't match LM Studio's folder structure
def _find_model(quant: str) -> Path | None:
    # Try exact path first
    p = MODELS.get(quant)
    if p and p.exists():
        return p
    # Glob fallback — LM Studio nests in author/repo/filename
    for candidate in MODELS_DIR.rglob(f"*.{quant}.gguf"):
        if "9b" in candidate.name.lower() or "9B" in candidate.name:
            return candidate
    # Try case-insensitive quant match
    quant_up = quant.upper()
    for candidate in MODELS_DIR.rglob("*.gguf"):
        name_up = candidate.name.upper()
        if quant_up in name_up and ("9B" in name_up or "9b" in candidate.name):
            return candidate
    return None


# ── Optimal settings per VRAM tier ──────────────────────────────────────────
# RTX 3070 — 8 GB VRAM, 448 GB/s bandwidth.
# Rule: maximize GPU utilisation, minimise KV cache overhead.
def optimal_params(ctx: int = 4096) -> dict:
    # At >= 64k context, switch to Q4 KV to keep VRAM under 8 GB on RTX 3070.
    # Q3_K_S model (4.32 GB) + Q4 KV at 100k ≈ 1.8 GB = 6.1 GB total (fits).
    # Q3_K_S model (4.32 GB) + Q8 KV at 100k ≈ 3.6 GB = 7.9 GB (tight, may OOM).
    kv_type = "q4_0" if ctx >= 65536 else "q8_0"
    return {
        "n_gpu_layers": -1,          # all layers on GPU — mandatory for 25+ tok/s
        "n_ctx": ctx,
        "n_batch": 2048,             # large physical batch = fast prompt processing
        "n_threads": 4,              # minimal CPU threads (GPU does the work)
        "flash_attn": True,          # mandatory at long contexts — saves VRAM + latency
        "cache_type_k": kv_type,
        "cache_type_v": kv_type,
        "use_mmap": True,
        "use_mlock": False,
        "verbose": True,
    }


PROMPT = """\
You are a fast local language model. Write a detailed technical explanation of how \
transformer attention mechanisms work, covering multi-head attention, key-value caching, \
flash attention optimizations, and why these matter for inference speed on modern GPUs. \
Be specific and thorough."""


def bench_model(model_path: Path, quant: str, ctx: int) -> dict:
    """Load model, run warmup + timed passes, return results dict."""
    print(f"\n{'='*60}")
    print(f"  MODEL : {model_path.name}")
    print(f"  SIZE  : {model_path.stat().st_size / 1e9:.2f} GB")
    print(f"  QUANT : {quant}")
    print(f"  CTX   : {ctx} tokens")
    print(f"  GEN   : {GEN_TOKENS} tokens x {N_RUNS} runs (+ {N_WARMUP} warmup)")
    print(f"{'='*60}\n")

    try:
        import llama_cpp
    except ImportError:
        print("[FAIL] llama_cpp not installed. Run: pip install llama-cpp-python")
        return {"error": "llama_cpp missing"}

    cuda_ok = llama_cpp.llama_supports_gpu_offload()
    if not cuda_ok:
        print("[WARN] CUDA not available — running CPU only (will be slow)")

    params = optimal_params(ctx)
    if not cuda_ok:
        params["n_gpu_layers"] = 0

    print(f"[INFO] Loading model...")
    load_t0 = time.perf_counter()
    try:
        llm = llama_cpp.Llama(model_path=str(model_path), **params)
    except Exception as e:
        print(f"[FAIL] Load failed: {e}")
        return {"error": str(e)}
    load_s = time.perf_counter() - load_t0
    print(f"[INFO] Loaded in {load_s:.1f}s\n")

    tps_results = []
    pp_tps_results = []  # prompt-processing tokens/sec

    for i in range(N_WARMUP + N_RUNS):
        phase = "WARMUP" if i < N_WARMUP else f"RUN {i - N_WARMUP + 1}/{N_RUNS}"
        prompt_tokens = len(PROMPT.split())  # rough estimate
        print(f"[{phase}] Generating {GEN_TOKENS} tokens (prompt ~{prompt_tokens} tok)...",
              end="", flush=True)

        t0 = time.perf_counter()
        out = llm(
            PROMPT,
            max_tokens=GEN_TOKENS,
            temperature=0.0,    # greedy — deterministic, removes sampling overhead
            echo=False,
        )
        elapsed = time.perf_counter() - t0

        # llama_cpp returns usage stats in the response
        usage = out.get("usage", {})
        completion_tokens = usage.get("completion_tokens", GEN_TOKENS)
        prompt_tokens_actual = usage.get("prompt_tokens", prompt_tokens)
        tps = completion_tokens / elapsed if elapsed > 0 else 0

        # Prompt processing speed: llama_cpp logs "prompt eval time = Xms / N tokens"
        # We get this from llama_context perf which is printed to stderr/stdout.
        # Approximate from timing: total_time - eval_time = pp_time
        # (available in usage dict as 'total_time' in some versions)

        text_preview = out["choices"][0]["text"][:80].replace("\n", " ")
        print(f" {tps:.1f} tok/s gen")
        print(f"         preview: \"{text_preview}...\"")

        if i >= N_WARMUP:
            tps_results.append(tps)

    avg_tps = sum(tps_results) / len(tps_results) if tps_results else 0
    max_tps = max(tps_results) if tps_results else 0
    min_tps = min(tps_results) if tps_results else 0
    passed = avg_tps >= TARGET_TPS

    # Cleanup
    del llm

    kv_type = "q4_0" if ctx >= 65536 else "q8_0"
    return {
        "model": model_path.name,
        "quant": quant,
        "ctx": ctx,
        "kv_type": kv_type,
        "avg_tps": round(avg_tps, 1),
        "max_tps": round(max_tps, 1),
        "min_tps": round(min_tps, 1),
        "load_s": round(load_s, 1),
        "passed": passed,
    }


def main():
    parser = argparse.ArgumentParser(description="IRIS 9B TPS benchmark")
    parser.add_argument("--model", choices=["Q3_K_S", "Q4_K_M", "both"], default="Q3_K_S",
                        help="Which quant to test (Q3_K_S is faster to load for iteration)")
    parser.add_argument("--ctx", type=int, default=0,
                        help="Context window (0=sweep: 4096, 32768, 102400)")
    args = parser.parse_args()

    quants = ["Q3_K_S", "Q4_K_M"] if args.model == "both" else [args.model]
    ctx_sizes = [4096, 32768, 102400] if args.ctx == 0 else [args.ctx]
    results = []

    for quant in quants:
        path = _find_model(quant)
        if not path:
            print(f"\n[SKIP] No {quant} 9B model found in {MODELS_DIR}")
            print(f"       Expected pattern: *9B*{quant}*.gguf")
            continue
        for ctx in ctx_sizes:
            # Use Q4 KV cache for 100k context to fit in 8 GB VRAM
            r = bench_model(path, quant, ctx)
            r["ctx"] = ctx
            results.append(r)

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("GATE 1 — 9B TPS BENCHMARK RESULTS")
    print(f"Target: >= {TARGET_TPS:.0f} tok/s")
    print(f"{'='*60}")
    all_pass = True
    for r in results:
        if "error" in r:
            print(f"  [FAIL] {r.get('model','?')}: {r['error']}")
            all_pass = False
            continue
        status = "[PASS]" if r["passed"] else "[FAIL]"
        ctx_k = r['ctx'] // 1024
        print(f"  {status} {r['quant']:10s}  avg={r['avg_tps']:5.1f} tok/s  "
              f"(min={r['min_tps']} max={r['max_tps']})  ctx={ctx_k}k  kv={r.get('kv_type','?')}  load={r['load_s']}s")
        if not r["passed"]:
            all_pass = False

    print(f"{'='*60}")
    if not results:
        print(">>> No 9B models found — download a Qwen3.5-9B GGUF to run this benchmark")
        sys.exit(1)
    elif all_pass:
        best = max(results, key=lambda r: r.get("avg_tps", 0))
        print(f">>> GATE 1 9B TPS VERIFIED — best: {best['quant']} at {best['avg_tps']} tok/s")
        print(f"    Recommended for IRIS: profile=balanced, model={best['model']}")
    else:
        best_passing = [r for r in results if r.get("passed")]
        failing = [r for r in results if not r.get("passed")]
        if best_passing:
            best = max(best_passing, key=lambda r: r.get("avg_tps", 0))
            print(f">>> PARTIAL — {best['quant']} passes at {best['avg_tps']} tok/s")
        for r in failing:
            gap = TARGET_TPS - r.get("avg_tps", 0)
            print(f">>> {r['quant']} at {r.get('avg_tps',0)} tok/s — {gap:.1f} tok/s below target")
        sys.exit(1)


if __name__ == "__main__":
    main()

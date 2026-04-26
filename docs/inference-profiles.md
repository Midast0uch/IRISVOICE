# IRIS Inference Profiles — Reference Guide

**Hardware reference:** RTX 2070 Super (8 GB VRAM) · 16 GB RAM · i7-7700 8T
**Backend:** llama-cpp-python server mode (port 8082) · OpenAI-compatible API

---

## Dense Model Behavior

Dense models (standard transformers — LLaMA, Mistral, Qwen, Phi, Gemma) activate **all parameters on every token**. Unlike MoE models (DeepSeek, Mixtral), there is no expert routing — every weight participates in every forward pass.

Consequences for hardware:
- VRAM pressure scales with model size × quantization, not with context length
- KV cache is a **separate** VRAM consumer that scales linearly with context × layers
- Decode speed (t/s) is dominated by: GPU layers loaded + KV cache bandwidth
- Prefill (prompt eval) speed is dominated by: batch size + KV precision
- Flash Attention cuts peak attention memory ≈50-70%, speeds decode 1.5–3×

---

## Settings Reference

| Setting | What it does | Performance effect |
|---|---|---|
| **n_ctx** (Context Length) | Max tokens (prompt + generation). Pre-allocates KV cache. | ↑ctx = ↑VRAM linear, ↑prefill time, ↓decode t/s |
| **n_gpu_layers** | Layers fully on GPU (-1 = auto/all). | Biggest t/s lever. Each GPU layer = 5–30× faster vs CPU |
| **flash_attn** | Fused blockwise attention, recompute instead of materialize | ↓KV VRAM 50-70%, ↑decode speed 1.5-3×, always ON on NVIDIA |
| **cache_type_k / cache_type_v** | Quantize the KV cache keys/values | ↓VRAM, trade prefill speed for memory. K more sensitive than V |
| **n_batch** | Tokens per prefill chunk | Larger = faster prompt eval. No effect on decode |
| **n_threads** | CPU threads for offloaded layers | Match logical core count (8 for i7-7700) |
| **unified_kv_cache** | Shared KV pool vs per-slot | Saves VRAM with concurrent requests |
| **use_mmap** | Memory-map model from disk | Lower peak RAM, slight overhead. ON for ≥16 GB RAM |
| **use_mlock** (keep_in_memory) | Lock model in RAM, prevent OS swapping | Smoother reloads, uses more RAM |
| **rope_freq_base / scale** | Rotary positional embedding tuning | Only change if model card requires. Wrong = garbage output |

---

## KV Cache Quantization — Tradeoff Matrix

| Type | VRAM vs F16 | Prefill speed | Quality | Best for |
|---|---|---|---|---|
| F16 | 100% (baseline) | Fastest | Lossless | Short context, coding, max speed |
| q8_0 | ~50% | Moderate (dequant overhead) | Near-lossless | Long context, research, balanced |
| q6_K | ~37% | Slower | Very good | VRAM-constrained, long ctx |
| q5_0 | ~31% | Slower | Good | Heavy VRAM pressure |
| q4_0 | ~25% | Slowest | Acceptable | CPU fallback, minimal VRAM |

**Rule:** K cache more quality-sensitive than V cache. When using asymmetric quantization, K should be one step higher (e.g., K=q8_0, V=q5_0).

---

## VRAM Estimation Formula

```
VRAM_needed_GB = params_billions × bits_per_weight / 8 × 1.1
```

**Bits per weight (bpw) by quantization:**

| Quant | bpw | Example: 7B model |
|---|---|---|
| F16 | 16.0 | 15.4 GB |
| Q8_0 | 8.5 | 8.2 GB |
| Q6_K | 6.56 | 6.3 GB |
| Q5_K_M | 5.69 | 5.5 GB |
| Q4_K_M | 4.85 | 4.7 GB |
| Q4_0 | 4.5 | 4.3 GB |
| Q3_K_M | 3.35 | 3.2 GB |
| Q2_K | 2.56 | 2.5 GB |

Add ~10% overhead for runtime allocations.

---

## IRIS Hardware Profiles

All profiles except Eco also set: `use_mmap=True`, `use_mlock=True`, `n_threads=cpu_count()`.

| Profile | n_gpu_layers | n_ctx | Flash Attn | KV Cache (K/V) | n_batch | KV on GPU | Unified KV | Sweet spot |
|---|---|---|---|---|---|---|---|---|
| **Eco** | 0 (CPU only) | 2048 | OFF | F16 / F16 | 512 | OFF | OFF | No GPU, minimum VRAM |
| **Balanced** | -1 (auto) | 16384 | ON | q8_0 / q8_0 | 2048 | ON | ON | Everyday default |
| **Performance** | -1 (auto) | 8192 | ON | F16 / F16 | 4096 | ON | ON | Max decode t/s, coding |
| **Voice-First** | -1 (auto) | 4096 | ON | F16 / F16 | 1024 | ON | ON | Fastest first-token |
| **Research** | -1 (auto) | 32768 | ON | q8_0 / q8_0 | 1024 | ON | ON | Long docs, summarization |
| **Custom** | slider | slider | toggle | dropdown / dropdown | slider | toggle | toggle | Full control |

---

## Use-Case Configurations

### 1. Fast Coding / Autopilot Iteration

**Goal:** Highest decode t/s, fast first token, short context.
**Models:** 7B–9B Q4_K_M (Qwen 2.5, Llama 3.1, Mistral 7B)
**Profile:** `Performance`

| Setting | Value |
|---|---|
| n_ctx | 8192–16384 |
| n_gpu_layers | -1 (full offload on 9B Q4) |
| KV cache | F16 / F16 |
| n_batch | 4096 |
| Expected decode | **35–60+ t/s** on 8 GB VRAM, 9B Q4 |

**Why:** F16 KV avoids dequant overhead on prefill. Large batch = fast prompt processing.

---

### 2. Research / Long Document Analysis

**Goal:** Extended context without quality collapse, acceptable speed.
**Models:** 8B–14B Q4/Q5 (Qwen 2.5 14B, Llama 3.1 8B)
**Profile:** `Research`

| Setting | Value |
|---|---|
| n_ctx | 16384–32768 |
| n_gpu_layers | -1 (partial for 14B on 8 GB VRAM) |
| KV cache | q8_0 / q8_0 |
| n_batch | 1024–2048 |
| Expected decode | **15–35 t/s** |

**Why:** q8_0 KV frees VRAM needed for long context. Trade-off: slower prefill, but research cares more about total tokens than instant response.

---

### 3. Multi-Task / Parallel Requests

**Goal:** Handle concurrent conversations or agent tool calls without OOM.
**Models:** 7B–13B Q4/Q5
**Profile:** `Balanced` (with Unified KV ON)

| Setting | Value |
|---|---|
| n_ctx | 8192–16384 |
| n_gpu_layers | -1 (max stable) |
| KV cache | q8_0 / q8_0 |
| n_batch | 512–1024 |
| unified_kv | ON (critical) |
| Expected decode | **20–40 t/s per task** (2–3 concurrent) |

---

### 4. Balanced General Purpose (Default)

**Goal:** Versatile daily use — coding, chat, analysis.
**Models:** 9B–14B Q4_K_M
**Profile:** `Balanced`

| Setting | Value |
|---|---|
| n_ctx | 16384 |
| n_gpu_layers | -1 |
| KV cache | q8_0 / q8_0 |
| n_batch | 2048 |
| Expected decode | **20–40 t/s** |

---

## Hardware Scaling Table

| GPU VRAM | Recommended profile | Max model size | Notes |
|---|---|---|---|
| No GPU / integrated | Eco | 3B Q4 | CPU only, ~3–8 t/s |
| 4 GB | Eco / Balanced | 7B Q3 (partial) | Very limited headroom |
| 6 GB | Balanced | 7B Q4_K_M (full) | Some headroom for context |
| 8 GB | Performance / Balanced | 9B Q4_K_M (full) | RTX 2070S sweet spot |
| 12 GB | Performance | 13B Q4_K_M (full) | Comfortable headroom |
| 16 GB | Performance / Research | 13B Q5_K_M / 7B F16 | Excellent |
| 24 GB+ | Performance / Research | 34B Q4 / 13B Q6 | Full-context capable |

---

## Quick Start for RTX 2070 Super (8 GB VRAM)

1. **For everyday conversation:** Load any 7B–9B Q4_K_M → **Balanced** profile
2. **For fast code generation:** Load same model → **Performance** profile
3. **For long documents:** Load 7B–9B Q4_K_M → **Research** profile (q8_0 KV frees VRAM)
4. **For voice assistant speed:** Load same model → **Voice-First** profile (4K ctx, minimum latency)
5. **For 13B+ models:** Use **Balanced** or **Research** (q8_0 KV required to fit in 8 GB)

**Golden rule:** Watch the VRAM bar in Models Browser. If it turns amber (<20% free headroom), switch to a lower KV quantization or reduce n_ctx.

---

## Notes on llama-cpp-python Server Mode

IRIS runs llama-cpp-python as a subprocess (`python -m llama_cpp.server`) on port 8082. It exposes an OpenAI-compatible API (`/v1/chat/completions`, `/v1/models`, `/v1/health`). The same routing code used for LM Studio is reused — no duplication.

Subprocess lifecycle:
- **Starts:** only when user clicks "Load" in Models Browser
- **Stops:** on "Unload", on model switch, on IRIS backend shutdown (atexit handler)
- **Port conflict:** If port 8082 is in use, load will fail with an error banner in the UI

Model files location: `IRISVOICE/models/gguf/*.gguf`
Per-model settings (last profile, pin state): `IRISVOICE/models/gguf/.iris_model_settings.json`

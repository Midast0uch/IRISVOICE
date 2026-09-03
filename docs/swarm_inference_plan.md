# Swarm Inference Architecture Plan

## Hardware Constraints
- RTX 3070 8GB VRAM
- 16GB System RAM
- 30% VRAM headroom reserved for OS + apps = ~5.6GB usable

## Architecture Decision: Director = Brain

**No separate brain model.** The Director role in the DER loop already carries:
- Mycelium pins (shared context artifacts)
- PAC-MAN episodic memory
- Full task context via ContextPackage

Adding a separate "brain" model would duplicate context overhead. Instead:
- Director runs on **same model as swarm** or **API endpoint** (configurable)
- For local-only: Director uses larger context window, workers use small windows
- For hybrid: Director calls API (OpenAI/Claude), workers run local fast models

## Model Inventory & Benchmarks

### Swarm Worker Models (Fast, Small Context)

| Model | Size | Context | GPU Layers | VRAM | Gen tok/s | Swarm Instances |
|-------|------|---------|------------|------|-----------|-----------------|
| Bonsai 8B TurboQuant | 1.1 GB | 1k | All | ~1.0 GB | **122.6** | 5 GPU |
| Bonsai 8B TurboQuant | 1.1 GB | 2k | All | ~1.1 GB | **115.6** | 4 GPU |
| Bonsai 8B Q2_K | 2.8 GB | 2k | All | ~2.9 GB | **79.0** | 1 GPU |
| Ternary Bonsai 8B Q2_K | 3.1 GB | 2k | All | ~3.3 GB | **54.6** | 1 GPU |
| clone-Ternary Bonsai 8B Q2_0 | 2.0 GB | — | — | — | **FAILED** ❌ | — |
| Ternary Bonsai 8B Q2_0 (prism-ml) | 2.0 GB | — | — | — | **FAILED** ❌ | — |

### Director/Brain Models (Quality, Larger Context)

| Model | Size | Context | GPU Layers | VRAM | Gen tok/s | Role | Status |
|-------|------|---------|------------|------|-----------|------|--------|
| Qwopus 3.5-9B Coder MTP | 4.8 GB | 2k | 12 | ~4.8 GB | **4.5** | Local Director | ⚠️ Too slow |
| Qwopus 3.5-9B Coder MTP | 4.8 GB | 2k | 10 | ~4.5 GB | **Stalled** | Local Director | ❌ Warmup hang |
| **API (OpenAI/Claude)** | - | 8k-128k | N/A | 0 GB | Variable | Remote Director | ✅ **Recommended** |
| **Bonsai 8B TurboQuant** | 1.1 GB | 4k | All | ~1.2 GB | **~100** | Local Director | ✅ Fast enough |
| **Bonsai 8B-unpacked Q3_K_M** | 4.3 GB | 2k | All | ~4.5 GB | **65.2** | Local Director | ✅ **Best quality local** |

## Swarm Configurations

### Option A: Pure Local (All Bonsai TurboQuant)
- **5 workers** on GPU (1k context each)
- **1 Director** on CPU or same GPU instance (4k context)
- Combined: ~500+ tok/s for workers, Director slower on CPU
- Total VRAM: ~5.0 GB

### Option B: Hybrid (API Director + Local Workers)
- **Director**: API endpoint (OpenAI/Claude)
- **4-5 workers**: Bonsai TurboQuant on GPU (1k context)
- Workers: ~490 tok/s combined
- Director: Unlimited quality/context via API
- Total VRAM: ~4-5 GB

### Option C: Quality Local (TurboQuant Director + Workers) — NOT VIABLE ❌
- ~~Qwopus 9B with 10 GPU layers~~ — Stalls during warmup, never completes
- ~~Qwopus 9B with 12 GPU layers~~ — 4.5 tok/s (unusably slow)
- **Reason**: "Gated Delta Net" architecture not supported for partial GPU offload
- **Alternative**: Use Bonsai TurboQuant for Director too (4k context, ~100 tok/s)

### Option D: Mixed Quality Director + Fast Workers ✅ **NEW**
- **Director**: Bonsai 8B-unpacked Q3_K_M on GPU (12k context, 65.2 tok/s)
- **4 workers**: Bonsai 8B TurboQuant on GPU (2k context, 122 tok/s each)
- **Setup**: Two `llama-server` instances — one for Director, one for workers
- **Director VRAM**: ~5.3 GB (Q3_K_M weights + 12k KV cache)
- **Workers VRAM**: ~1.4 GB (TurboQuant weights + 2k KV cache x4)
- **Total**: ~6.8 GB **→ EXCEEDS 5.6 GB**
- **Fix**: Partial GPU offload for Director (20 layers GPU, 13 CPU) → ~3.9 GB GPU
  - Director drops to ~40 tok/s, but workers stay at 122 tok/s
  - Total: ~5.3 GB → FITS

### CPU/GPU Mixing — Can It Work?

**Yes, but with tradeoffs.** `llama-server` supports `--parallel N` on one device only. To mix CPU and GPU agents:

**Option 1: Separate llama-server instances**
```
# Director on GPU
llama-server --model Q3_K_M --gpu-layers 99 --port 8081 --parallel 1

# Workers on CPU
llama-server --model TurboQuant --gpu-layers 0 --port 8082 --parallel 4 --threads 8
```
- Director: 65 tok/s (GPU)
- Workers: ~5-10 tok/s each (CPU) — **much slower**
- Total throughput lower than all-GPU

**Option 2: All on GPU (Recommended)**
```
# One llama-server for Director (port 8081)
# Another llama-server for workers (port 8082, --parallel 4)
```
- Director: 65 tok/s (GPU)
- Workers: 122 tok/s each (GPU)
- Total throughput: ~550 tok/s
- VRAM: ~5.5 GB (tight but fits)

**Verdict**: All-GPU is much faster. Only use CPU offload if VRAM is the bottleneck.

## Key Findings

### What Works
- **Bonsai 8B TurboQuant**: 122 tok/s at 1k context, loads fully on GPU, best swarm worker
- **Bonsai 8B-unpacked Q3_K_M**: 65 tok/s at 2k context, excellent quality Director model
- **Bonsai 8B Q2_K**: 79 tok/s at 2k context, good quality backup option
- **Ternary Bonsai 8B Q2_K**: 54 tok/s at 2k context, works but slower than standard Q2_K

### What Does NOT Work
- **Both Ternary Q2_0 models** (prism-ml + clone): GGUF tensor type 42 not supported by current llama.cpp build. Would need llama.cpp update (risks breaking CUDA build).
- **Qwopus 9B Coder MTP**: "Gated Delta Net" architecture breaks partial GPU offload. 12 layers = 4.5 tok/s. 10 layers = warmup stall. Completely unusable on RTX 3070.
- **Qwopus 27B MTP**: Previously removed by user for same reason — not viable on 8GB VRAM.

### Recommendation

**UI has 3 simple modes — pick one:**

1. **`local_fast`** — All TurboQuant (default)
   - Director + Workers all run TurboQuant
   - 122 tok/s per instance, 4k context Director, 2k context workers
   - Simplest, fastest, lowest quality

2. **`api_director`** — API Brain + Local Workers ⭐ **Recommended**
   - Director uses OpenAI/Claude API (unlimited quality)
   - Workers run TurboQuant at 122 tok/s each
   - Zero VRAM for Director, ~1.4 GB for workers
   - Best quality + speed combo

3. **`quality_director`** — Q3_K_M Brain + TurboQuant Workers
   - Director runs Q3_K_M with partial GPU offload (20 layers GPU, 13 CPU)
   - ~40 tok/s Director, 122 tok/s workers
   - Fits in 5.3 GB VRAM
   - Good local quality without API dependency

**Fallback:** If Q3_K_M Director is still not smart enough, use `api_director` mode.

### UI Implementation

The `inference_mode` card now has:
- `swarm_enabled` toggle (existing)
- `swarm_mode` dropdown: `local_fast` | `api_director` | `quality_director`
- `worker_context` slider: 1k–4k tokens per worker
- `swarm_status` display: Shows running models + GPU layers

**Models auto-load** — no manual picking. Backend `SwarmInferenceManager` handles all llama-server startup.

## Parallel DER Architecture Changes Needed

Current: Sequential loop (one step at a time)
```
while not complete:
    item = queue.next_ready()
    verdict = reviewer.review(item)
    if pass: result = explorer.execute(item)
```

Target: Parallel dispatch
```
while not complete:
    items = queue.next_ready_n(6)  # Get up to 6 ready items
    results = await asyncio.gather(*[explore(i) for i in items])
    for result in results:
        reviewer.review(result)
```

Changes required in `agent_kernel.py`:
1. `_execute_plan_der()` needs parallel Explorer dispatch
2. `LocalModelManager` needs to support `--parallel N` slots
3. `llama-server` startup needs `--parallel 6` flag

## llama-server Multi-Slot Configuration

```bash
llama-server.exe \
  --model Bonsai-8B.gguf \
  --port 8082 \
  --ctx-size 1024 \
  --parallel 6 \          # 6 concurrent slots
  --batch-size 2048 \     # Process all 6 requests in one batch
  --gpu-layers 99 \
  --flash-attn on
```

With 6 slots + 1k context:
- 6 × 1k KV cache = small overhead
- Batch processing means GPU processes all 6 requests together
- Individual tok/s may drop slightly but combined throughput increases

## Next Steps

1. [ ] Benchmark clone-Ternary Bonsai 8B Q2_0
2. [ ] Benchmark Qwopus 9B Coder with 10-12 GPU layers
3. [ ] Test llama-server with `--parallel 6` on TurboQuant
4. [ ] Modify `LocalModelManager._build_server_cmd` to add `--parallel` flag
5. [ ] Prototype parallel DER dispatch in `agent_kernel.py`
6. [ ] Add Director mode config (local vs API)

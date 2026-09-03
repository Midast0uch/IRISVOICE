# Swarm Implementation Plan — Mixed Director + Workers

## Executive Summary

Based on VRAM analysis, **three viable configurations** exist for your RTX 3070 8GB (~5.6GB usable):

| Config | Director | Workers | Total GPU | Fits? | Director Speed | Workers Speed |
|--------|----------|---------|-----------|-------|----------------|---------------|
| **C** | Q3_K_M 12k GPU | TurboQuant CPU | 5.33 GB | ✅ | 65 tok/s | 5-10 tok/s |
| **D** | Q2_K 12k GPU | TurboQuant GPU | 4.78 GB | ✅ | 80 tok/s | 122 tok/s |
| **E** | API | TurboQuant GPU | 1.44 GB | ✅ | Variable | 122 tok/s |

**Recommended: Config D** (Q2_K Director + TurboQuant Workers) for all-local with best balance.
**Fallback: Config E** (API Director) if Q2_K quality is insufficient.

---

## 1. Context Management at 12k+ (How Overflow Works)

### Current System (Already Implemented)

Your backend already has a 3-layer context pipeline that handles overflow gracefully:

```
Layer 1: System Prompt  → Mycelium coordinates (always kept)
Layer 2: Episodic       → Semantic memory summaries (compressed history)
Layer 3: Recency        → Last 4 raw turns (short-term memory)
```

**Token Budget:** `_DIRECT_CTX_BUDGET = 20_000` tokens

When messages exceed this budget, the system:
1. Keeps Layer 1 (system prompt) — always preserved
2. Keeps Layer 2 (episodic summaries) — compressed long-term memory
3. Trims Layer 3 (recency) from the oldest side — only keeps the last N turns that fit

### MCM Protocol (Automatic Compression)

After every turn, `MCMOrchestrator.post_turn()` runs the `post_turn_flow` workflow:
- **MCM:999** → DCP prune: strips tool-call bloat (saves ~30-50% tokens)
- **MCM:998** → Pin artifacts: saves important outputs to `mycelium_pins` table
- **MCM:997** → MCM compress: condenses old turns into summaries, injects recovery context
- **MCM:996** → Coordinate broadcast: shares state with swarm collective

### What Happens at 12k Context?

**Nothing different from 4k.** The same 3-layer system works — it just holds more recency turns before compressing. With 12k context:
- System prompt: ~500 tokens
- Episodic layer: ~2,000 tokens
- Recency buffer: ~9,000 tokens (last ~20 turns instead of 4)
- Response budget: ~500 tokens

**When 12k fills:**
1. Oldest recency turns get compressed into episodic summaries (Layer 2)
2. Key artifacts are pinned to Mycelium (permanent storage)
3. Tool-call bloat is pruned via DCP
4. The model never "loses" information — it's just summarized

### llama-server Native Handling

Even if the backend didn't compress, `llama-server --ctx-size 12288` would **automatically drop oldest tokens** when context fills. The MCM system just makes this smarter — it preserves important information instead of blindly dropping.

### What Needs Enhancement for 12k+

| Enhancement | Current | Target | File |
|-------------|---------|--------|------|
| `_DIRECT_CTX_BUDGET` | 20k tokens | 24k tokens | `agent_kernel.py:1417` |
| `_RECENCY_TURNS` | 4 raw turns | 8 raw turns | `agent_kernel.py:1478` |
| `post_turn_flow` | Compresses every turn | Compress at 75% fill | `mcm_protocol/workflows/*.json` |
| KV cache type | q8_0 | q4_0 (half the memory) | llama-server startup |

---

## 2. CPU RAM Utilization (24GB Available)

### What Can Go to CPU?

| Component | GPU Preferred? | CPU Viable? | Impact |
|-----------|---------------|-------------|--------|
| Model weights (Q3_K_M) | ✅ Yes | ✅ Yes | **3-5x slower** |
| Model weights (TurboQuant) | ✅ Yes | ✅ Yes | 10-20x slower (1-bit has no AVX) |
| KV cache | ✅ Yes | ✅ Yes | Slight slowdown |
| Compute buffers | ✅ Yes | ❌ No | Must stay on GPU for CUDA kernels |

### How llama.cpp Handles CPU Offload

`llama-server --gpu-layers N` puts N layers on GPU, rest on CPU:
```bash
# Example: 24 of 33 layers on GPU, 9 on CPU
llama-server --model Q3_K_M.gguf --gpu-layers 24 --ctx-size 12288
```

**KV cache is split too:** GPU layers' KV stays on GPU, CPU layers' KV stays on CPU.

### Practical CPU Offload for Director

To fit Q3_K_M @ 12k + TurboQuant workers @ 1k x4:

```bash
# Director: partial GPU offload (20 layers GPU, 13 CPU)
llama-server --model Q3_K_M.gguf --port 8081 --ctx-size 12288 \
  --gpu-layers 20 --cache-type-k q4_0 --cache-type-v q4_0

# Workers: full GPU
llama-server --model TurboQuant.gguf --port 8082 --ctx-size 1024 \
  --parallel 4 --gpu-layers 99
```

**VRAM usage:**
- Director GPU portion: ~3.1 GB weights + ~0.45 GB KV (q4_0) + 0.3 GB compute = ~3.85 GB
- Workers: ~1.1 GB weights + ~0.12 GB KV (q4_0) x4 + 0.1 GB compute = ~1.6 GB
- **Total: ~5.45 GB** → FITS with 0.15 GB headroom!

**Tradeoff:** Director drops from 65 tok/s to ~40 tok/s (20 layers GPU, 13 CPU).

---

## 3. UI/Backend Mode Switching

### Current Architecture

The UI already sends `inference_mode` and `model_selection` cards to `iris_gateway.py`, which:
1. Normalizes provider names (`"LM Studio"` → `lmstudio`, `"API"` → `api`)
2. Configures the `AgentKernel` provider (`configure_lmstudio`, `configure_api`, etc.)
3. Sets `swarm_enabled` boolean

### Missing: Swarm Model Configuration

Currently, the UI lets you pick **one** model provider. For a mixed swarm, we need:
1. **Director model** (endpoint + model file)
2. **Worker model** (endpoint + model file)
3. **Swarm mode** (local-only / api-director / full-api)

### Proposed UI Card: `swarm_config`

```json
{
  "swarm_mode": "mixed_local",
  "director": {
    "provider": "local_llama_server",
    "endpoint": "http://localhost:8081/v1",
    "model": "prism-ml_Bonsai-8B-unpacked-Q3_K_M.gguf",
    "ctx_size": 12288,
    "gpu_layers": 20
  },
  "workers": {
    "provider": "local_llama_server",
    "endpoint": "http://localhost:8082/v1",
    "model": "Bonsai-8B.gguf",
    "ctx_size": 1024,
    "parallel": 4,
    "gpu_layers": 99
  }
}
```

### Swarm Modes

| Mode | Director | Workers | Use Case |
|------|----------|---------|----------|
| `local_uniform` | TurboQuant GPU | TurboQuant GPU | Fastest, lowest quality |
| `mixed_local` | Q3_K_M/Q2_K GPU | TurboQuant GPU | Balanced (Config D) |
| `api_director` | OpenAI/Claude API | TurboQuant GPU | Best Director quality |
| `full_api` | OpenAI/Claude API | OpenAI/Claude API | No local GPU usage |
| `cpu_fallback` | Q3_K_M GPU | TurboQuant CPU | VRAM-constrained |

---

## 4. Implementation Steps

### Phase 1: Context Budget Expansion (1 hour)

1. **Edit `agent_kernel.py`**:
   - `_DIRECT_CTX_BUDGET`: 20k → 24k (line 1417)
   - `_RECENCY_TURNS`: 4 → 8 (line 1478)
   - Add `_CTX_FILL_THRESHOLD = 0.75` for proactive compression

2. **Add KV cache compression** to llama-server startup:
   - `--cache-type-k q4_0 --cache-type-v q4_0` (halves KV memory)

### Phase 2: Swarm Inference Manager (4 hours)

Create `backend/agent/swarm_inference_manager.py`:

```python
class SwarmInferenceManager:
    """Manages two llama-server instances: Director + Workers."""
    
    def __init__(self):
        self.director_proc = None   # subprocess.Popen
        self.workers_proc = None  # subprocess.Popen
        self.director_port = 8081
        self.workers_port = 8082
    
    def start_swarm(self, config: SwarmConfig):
        if config.mode == "mixed_local":
            self._start_director(config.director)
            self._start_workers(config.workers)
        elif config.mode == "api_director":
            self._start_workers(config.workers)  # Director is external API
        # ... etc
    
    def stop_swarm(self):
        self._kill(self.director_proc)
        self._kill(self.workers_proc)
```

### Phase 3: UI Integration (3 hours)

1. **Add `swarm_config` card** to frontend settings
2. **Add mode selector** dropdown: Local / API Director / Mixed / Full API
3. **Add model path pickers** for Director and Worker models
4. **Wire to `iris_gateway.py`** — new `confirm_card` handler for `swarm_config`

### Phase 4: Context Overflow Integration (2 hours)

1. **Trigger MCM:997 at 75% fill** instead of every turn
2. **Add `mycelium_pins` checkpoint** before context drops
3. **Inject recovery context** after compression so Director knows what was lost

### Phase 5: Testing (2 hours)

1. Benchmark Config D (Q2_K Director + TurboQuant Workers)
2. Benchmark Config C (Q3_K_M Director + Workers CPU)
3. Test context overflow with 12k context + long conversation
4. Verify MCM compression preserves critical information

---

## 5. File Changes Required

| File | Change | Priority |
|------|--------|----------|
| `backend/agent/agent_kernel.py` | Increase `_DIRECT_CTX_BUDGET`, `_RECENCY_TURNS` | P1 |
| `backend/agent/swarm_inference_manager.py` | **NEW** — manages two llama-server instances | P1 |
| `backend/iris_gateway.py` | Add `swarm_config` card handler | P2 |
| `backend/agent/model_router.py` | Add `SWARM` inference mode | P2 |
| `frontend/settings/SwarmConfigCard.tsx` | **NEW** — UI for swarm mode + model selection | P2 |
| `mcm_protocol/workflows/post_turn_flow.json` | Trigger compression at 75% fill | P3 |
| `backend/agent/swarm/context_control.py` | Add proactive overflow detection | P3 |
| `docs/swarm_inference_plan.md` | Update with final benchmarks | P4 |

---

## 6. Open Questions

1. **Does Q2_K Director quality suffice for DER planning?** — Needs task benchmarks
2. **Is 40 tok/s (partial offload) acceptable for Director?** — Test with partial GPU
3. **Should workers ever use CPU?** — Only if VRAM < 5GB with all-GPU Director
4. **API fallback on Director failure?** — Auto-switch to API if local model crashes?

---

## Immediate Next Steps

1. ✅ Download Q3_K_M model (DONE)
2. ✅ VRAM analysis (DONE)
3. **Benchmark Q2_K Director** — verify quality vs TurboQuant
4. **Implement Phase 1** — expand context budgets
5. **Implement Phase 2** — create `SwarmInferenceManager`

Ready to proceed with Phase 1 and Phase 2 implementation.

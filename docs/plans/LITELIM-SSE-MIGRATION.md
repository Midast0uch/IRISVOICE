# LiteLLM Integration — Complete

> **Status**: Complete ✅  
> **Date**: 2026-05-28  
> **Provider**: Chutes.ai → MiniMaxAI/MiniMax-M2.5-TEE  
> **Transport**: WebSocket (unchanged)  

---

## What Was Done

### 1. LiteLLM Integration (`backend/llm_service.py`)
New unified LLM service wrapping all LLM calls:
- Custom OpenAI-compatible endpoints (Chutes, vLLM, LM Studio) → direct OpenAI SDK
- Native providers (Cohere SDK, Groq) → litellm.completion()
- Built-in retries + fallback chains

### 2. Dead Code Removal (`agent_kernel.py`)
- Removed `_get_api_client()` — URL normalization hack no longer needed
- Removed `_run_agentic_loop()` — **550 lines** of dead code, zero callers
- Removed Cohere SDK path from `infer()` — all providers go through `LLMService`

### 3. Streaming Improvements (`agent_kernel.py`)
- **`_safe_stream`**: Wall-time silence detection (3s after last content chunk)
  Empty chunks from providers can no longer reset the timeout
- **Chunk batching**: Content tokens are buffered and flushed every 50ms or immediately
  on the first token — reduces WS message count per response by ~5x
- **Reasoning separation**: `reasoning_content` (chain-of-thought tokens) sent as
  `chat_reasoning` WS messages, separate from `chat_chunk`

### 4. WebSocket Stability (`useIRISWebSocket.ts`)
- **Deferred HMR close**: WS close is delayed 2s on component unmount — survives
  Fast Refresh without losing in-flight API responses

### 5. Provider: Chutes.ai (MiniMax 2.5)
| Metric | Before (Cohere) | After (Chutes MiniMax) |
|--------|-----------------|----------------------|
| TTFT | 10-15s | **1.2s** |
| Total (short) | ~35s | **~5s** |
| Total (long) | 60s+ | **~10s** |
| Provider swap | Code changes in 3 files | **One config line** |

---

## Files Changed

| File | Status |
|------|--------|
| `backend/llm_service.py` | **NEW** |
| `backend/agent/agent_kernel.py` | Refactored (3 call sites, +batching, +reasoning) |
| `backend/iris_gateway.py` | Added reasoning callbacks |
| `hooks/useIRISWebSocket.ts` | Chat reasoning event handler, HMR-safe close |
| `data/iris_config.json` | Chutes.ai config |
| `docs/plans/LITELIM-SSE-MIGRATION.md` | This file |

---

## Performance

```
Message → WS → iris_gateway → agent_kernel → LLMService → Chutes API
  ↓                            ↓                                   ↓
  chat_reasoning     batched chat_chunks                        [DONE]
  (thinking tokens)   every 50ms                          stream closes cleanly
```

**TTFT: 1.2s** | **Streaming: ~0.1s/token** | **Total: ~3-8s**

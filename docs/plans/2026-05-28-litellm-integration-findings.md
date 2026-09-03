# LiteLLM Integration — Findings & Solutions

## Problems Found & Fixed

### 1. Cohere API 404 — Wrong Endpoint URL
**Root cause**: The API base URL was `https://api.cohere.com/v2/chat` (Cohere native), but the backend used it as an OpenAI-compatible base, constructing `{url}/chat/completions` → `https://api.cohere.com/v2/chat/chat/completions` (double `/chat` -> 404).
**Fix**: LiteLLM routes `cohere/command-r-plus` natively — no URL manipulation needed. For custom endpoints, `LLMService` passes `api_base` directly to the OpenAI SDK.

### 2. 30s Silence Timeout
**Root cause**: `_safe_stream` had `silence_timeout=30.0`. After the last API token, the code waited 30s of stream silence before closing.
**Fix**: Wall-time silence detection (3s after last contentful chunk). Empty/done chunks from providers (Cohere, litellm) no longer reset the timer.

### 3. Stream Never Terminates (Cohere + litellm)
**Root cause**: litellm's streaming iterator kept yielding empty chunks after the response was complete. The `_reader` thread in `_safe_stream` stayed alive, and the main loop kept processing empty chunks indefinitely.
**Fix**: Wall-time silence check fires after 3s of no contentful tokens, regardless of thread state.

### 4. HMR Kills WebSocket, Drops In-Flight Responses
**Root cause**: Component cleanup called `ws.close()` immediately on unmount (Fast Refresh). Any API response being streamed was lost because the backend sent it to the now-closed WebSocket.
**Fix**: Deferred WS close (2s delay). If the component remounts within 2s (HMR), the close is cancelled.

### 5. Dead Code — `_run_agentic_loop` (550 lines)
**Root cause**: Function was replaced by the DER loop but never removed. Zero callers.
**Fix**: Removed entirely.

### 6. No Reasoning Token Separation
**Root cause**: `reasoning_content` and `content` were concatenated into one `full_reply` and sent as identical `chat_chunk` WS messages. The frontend couldn't distinguish thinking from answering.
**Fix**: `reasoning_content` sent as separate `chat_reasoning` WS messages. Content tokens are buffered and flushed every 50ms (reducing WS messages ~5x).

## Performance Before/After

| Metric | Before (Cohere) | After (Chutes MiniMax 2.5) |
|--------|-----------------|---------------------------|
| TTFT (time to first token) | 10-15s | **1.2s** |
| Short response total | ~35s | **~5s** |
| Adding a new provider | 3+ files changed | **1 config line** |
| Code paths for LLM calls | 3 different (Cohere SDK, OpenAI compat, raw) | **1 unified call** |
| WS messages per response | ~50 (1 per token) | **~10 (batched)** |
| Thinking/answering separation | None | `chat_reasoning` vs `chat_chunk` |

## Current Provider

Chutes.ai → MiniMaxAI/MiniMax-M2.5-TEE
- Base URL: `https://llm.chutes.ai/v1`
- Average response time: 3-8 seconds

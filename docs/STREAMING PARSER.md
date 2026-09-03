# Streaming Parser — IRIS Agent Guide (Model-Agnostic + Local Runtime)

## Why This Document Exists

IRIS loads and runs models directly — it is its own inference host, not a proxy to
LM Studio or Ollama. That means the streaming format IRIS receives depends entirely
on which endpoint IRIS’s inference layer exposes internally. This document covers all
three wire formats you will encounter, how to detect which one is active, how to
normalize them into a single internal event shape, and the IRIS-specific rules that
govern how normalized events flow into the ChatView, TTS queue, and STT pipeline.

-----

## The Three Wire Formats

### Format A — Anthropic Native SSE

**Used by:** Claude (direct Anthropic API), llama.cpp server `/v1/messages` endpoint
(available since January 2026), any backend that explicitly implements the Anthropic
Messages API spec.

Events arrive as typed objects with an explicit `type` and block `index`.

```
data: {"type":"message_start", ...}
data: {"type":"content_block_start", "index":0, "content_block":{"type":"thinking"}}
data: {"type":"content_block_delta", "index":0, "delta":{"type":"thinking_delta","thinking":"..."}}
data: {"type":"content_block_stop", "index":0}
data: {"type":"content_block_start", "index":1, "content_block":{"type":"text"}}
data: {"type":"content_block_delta", "index":1, "delta":{"type":"text_delta","text":"..."}}
data: {"type":"content_block_stop", "index":1}
data: {"type":"message_stop"}
```

Block types: `text`, `thinking`, `redacted_thinking`, `tool_use`

Thinking notes for Claude models:

- Opus 4.8 / 4.7: only `thinking: {type: "adaptive"}` supported; manual `budget_tokens`
  returns a 400 error
- Opus 4.6 / Sonnet 4.6: adaptive recommended; manual mode deprecated but functional
- Thinking blocks for Claude 4 models return a **summary**, not raw chain-of-thought
- `redacted_thinking` blocks: carry a signature, no content — open and close silently

When llama.cpp serves `/v1/messages`, it internally converts to OpenAI format for
inference then converts the response back to Anthropic SSE format. The stream shape
is identical to the Anthropic API. Thinking blocks will not appear unless the loaded
model natively produces them.

-----

### Format B — OpenAI-Compatible SSE

**Used by:** OpenAI API, llama.cpp server `/v1/chat/completions` endpoint, any
OpenAI-compatible backend IRIS spins up internally.

Events arrive as chunk objects. Text lives at `choices[0].delta.content`.

```
data: {"choices":[{"delta":{"role":"assistant","content":""},"index":0}]}
data: {"choices":[{"delta":{"content":"Hello"},"index":0}]}
data: {"choices":[{"delta":{"content":" world"},"index":0}]}
data: {"choices":[{"delta":{},"finish_reason":"stop","index":0}]}
data: [DONE]
```

**Reasoning tokens — field names vary by provider:**

|Provider / Backend            |Reasoning field in delta |
|------------------------------|-------------------------|
|OpenAI o-series (via vLLM)    |`delta.reasoning_content`|
|Ollama (thinking models)      |`delta.reasoning`        |
|DeepSeek-R1 via compatible API|`delta.reasoning_content`|
|Most others / non-thinking    |absent — text only       |

Always treat reasoning fields as optional. A chunk may carry `content`,
`reasoning_content`, `reasoning`, some combination, or none.

**Critical: `<think>` tag bleed-through**

When a thinking-capable model (Qwen3, DeepSeek-R1) is loaded via llama.cpp’s
`/v1/chat/completions` endpoint **without** native thinking extraction enabled, the
model’s raw reasoning tokens may stream directly inside `delta.content` wrapped in
`<think>...</think>` tags:

```
data: {"choices":[{"delta":{"content":"<think>\nLet me reason..."},"index":0}]}
data: {"choices":[{"delta":{"content":"step two\n</think>\n"},"index":0}]}
data: {"choices":[{"delta":{"content":"Final answer"},"index":0}]}
```

This is not a reasoning block — it is raw text. The parser must detect and extract it.

**Detection and extraction rule:**

Maintain a per-stream state machine with three modes: `text`, `in_think`, `post_think`.

- On first `<think>` encountered in `delta.content`: switch to `in_think`, route
  everything until `</think>` to `thinking_delta` events, do not write to the thread.
- On `</think>`: switch to `post_think`, resume routing to `text_delta`.
- If `<think>` never appears: stay in `text` mode, all content is `text_delta`.

Never write `<think>`, `</think>`, or the content between them into the ChatView
thread, text field, or TTS queue. They are reasoning content only.

Tag bleed can also split across chunk boundaries — the opening `<think>` may arrive
in one chunk and the closing `</think>` in a later one. The state machine handles
this correctly because it persists across chunks within a single stream.

-----

### Format C — llama.cpp Native `/completion`

**Used by:** llama.cpp server’s non-OpenAI-compatible completion endpoint. Only
relevant if IRIS’s inference layer exposes this endpoint directly rather than the
`/v1/chat/completions` wrapper.

Each streamed chunk is a flat JSON object with a `content` field and a `stop` boolean:

```
data: {"content":"Hello","stop":false,"tokens":[],...}
data: {"content":" world","stop":false,...}
data: {"content":"","stop":true,"generation_settings":{...},"timings":{...}}
```

Key properties:

- No `choices` wrapper — text is directly at `chunk.content`
- Stream end is `chunk.stop === true`, not a `[DONE]` sentinel
- No native thinking block concept — reasoning tokens appear as raw `<think>` tags
  in `content` (same bleed-through problem as Format B, same state machine applies)
- No `finish_reason` field — use `stop` boolean instead

This format is lower-level. Prefer wiring IRIS’s inference layer to expose
`/v1/chat/completions` (Format B) so the same adapter handles all non-Anthropic cases.
Only use Format C if IRIS calls the native endpoint directly.

-----

## Which Format Will IRIS Use?

Since IRIS is its own model host, the format is determined by which endpoint IRIS’s
Python inference layer exposes and which endpoint the TypeScript frontend calls.

|IRIS inference endpoint           |Format|Notes                                                       |
|----------------------------------|------|------------------------------------------------------------|
|`/v1/messages`                    |A     |Anthropic-compatible; llama.cpp supports this since Jan 2026|
|`/v1/chat/completions`            |B     |OAI-compatible; default for all local models                |
|`/completion` (llama.cpp native)  |C     |Avoid unless necessary; harder to normalize                 |
|Anthropic API (remote Claude)     |A     |Always Format A regardless of model                         |
|OpenAI API (remote GPT / o-series)|B     |Always Format B                                             |

**Recommendation:** Wire IRIS’s internal inference server to expose `/v1/chat/completions`
for all locally loaded models. This gives you Format B for everything local, Format A
only for remote Claude calls, and a clean two-adapter system.

-----

## Normalization Layer

Both adapters and the tag extractor emit the same internal event type. Nothing
downstream — ChatView, TTS queue, STT handler — ever sees a raw wire event.

```typescript
type IRISStreamEvent =
  | { kind: "text_delta";      delta: string }
  | { kind: "text_done";       full: string  }
  | { kind: "thinking_delta";  delta: string }
  | { kind: "thinking_done";   full: string  }
  | { kind: "stream_done" }
  | { kind: "stream_error";    error: Error  };
```

### Format A adapter (Anthropic SSE)

```typescript
function adaptAnthropicEvent(
  raw: Record<string, any>,
  blockTypes: Map<number, string>,
  buffers: Map<number, string>,
  emit: (e: IRISStreamEvent) => void
) {
  switch (raw.type) {
    case "content_block_start": {
      blockTypes.set(raw.index, raw.content_block.type);
      buffers.set(raw.index, "");
      break;
    }
    case "content_block_delta": {
      const kind = blockTypes.get(raw.index);
      const buf = buffers.get(raw.index) ?? "";
      if (raw.delta.type === "text_delta" && kind === "text") {
        buffers.set(raw.index, buf + raw.delta.text);
        emit({ kind: "text_delta", delta: raw.delta.text });
      } else if (raw.delta.type === "thinking_delta" && kind === "thinking") {
        buffers.set(raw.index, buf + raw.delta.thinking);
        emit({ kind: "thinking_delta", delta: raw.delta.thinking });
      }
      // signature_delta, input_json_delta: accumulate silently
      break;
    }
    case "content_block_stop": {
      const kind = blockTypes.get(raw.index);
      const full = buffers.get(raw.index) ?? "";
      if (kind === "text")     emit({ kind: "text_done",     full });
      if (kind === "thinking") emit({ kind: "thinking_done", full });
      blockTypes.delete(raw.index);
      buffers.delete(raw.index);
      break;
    }
    case "message_stop":
      emit({ kind: "stream_done" });
      break;
  }
}
```

### Format B adapter (OpenAI-compatible SSE) with `<think>` extraction

```typescript
type ThinkState = "text" | "in_think" | "post_think";

function adaptOpenAIChunk(
  raw: Record<string, any>,
  state: {
    textBuffer: string;
    thinkBuffer: string;
    thinkState: ThinkState;
    remainder: string; // handles tags split across chunk boundaries
  },
  emit: (e: IRISStreamEvent) => void
) {
  const choice = raw.choices?.[0];
  if (!choice) return;
  const delta = choice.delta ?? {};

  // Reasoning field (explicit — no tag parsing needed)
  const explicit_reasoning = delta.reasoning_content ?? delta.reasoning ?? null;
  if (explicit_reasoning != null) {
    state.thinkBuffer += explicit_reasoning;
    emit({ kind: "thinking_delta", delta: explicit_reasoning });
  }

  // Main content — may contain <think> tags if model bleeds through
  if (delta.content != null) {
    let text = state.remainder + delta.content;
    state.remainder = "";
    let out = "";

    while (text.length > 0) {
      if (state.thinkState === "text") {
        const start = text.indexOf("<think>");
        if (start === -1) {
          // Check for partial tag at end of chunk
          const partial = partialTagAt(text, "<think>");
          if (partial > 0) {
            out += text.slice(0, text.length - partial);
            state.remainder = text.slice(text.length - partial);
            text = "";
          } else {
            out += text;
            text = "";
          }
        } else {
          out += text.slice(0, start);
          text = text.slice(start + "<think>".length);
          state.thinkState = "in_think";
        }
      } else if (state.thinkState === "in_think") {
        const end = text.indexOf("</think>");
        if (end === -1) {
          state.thinkBuffer += text;
          emit({ kind: "thinking_delta", delta: text });
          text = "";
        } else {
          const chunk = text.slice(0, end);
          if (chunk) {
            state.thinkBuffer += chunk;
            emit({ kind: "thinking_delta", delta: chunk });
          }
          text = text.slice(end + "</think>".length);
          state.thinkState = "post_think";
        }
      } else {
        // post_think — everything after </think> is normal text
        out += text;
        text = "";
      }
    }

    if (out) {
      state.textBuffer += out;
      emit({ kind: "text_delta", delta: out });
    }
  }

  // Stream end
  if (choice.finish_reason != null) {
    if (state.thinkBuffer) emit({ kind: "thinking_done", full: state.thinkBuffer });
    emit({ kind: "text_done", full: state.textBuffer });
    emit({ kind: "stream_done" });
  }
}

// Returns how many chars at the end of str could be the start of tag
function partialTagAt(str: string, tag: string): number {
  for (let i = 1; i < tag.length; i++) {
    if (str.endsWith(tag.slice(0, i))) return i;
  }
  return 0;
}
```

### Format C adapter (llama.cpp native `/completion`)

```typescript
function adaptLlamaCppNative(
  raw: Record<string, any>,
  state: { textBuffer: string; thinkBuffer: string; thinkState: ThinkState; remainder: string },
  emit: (e: IRISStreamEvent) => void
) {
  // Reuse the same <think> extraction logic as Format B
  // but read from raw.content instead of delta.content
  const syntheticDelta = { choices: [{ delta: { content: raw.content ?? "" }, finish_reason: raw.stop ? "stop" : null }] };
  adaptOpenAIChunk(syntheticDelta, state, emit);
}
```

-----

## IRIS Integration Rules

These rules apply regardless of which model is active. All subsystems speak
`IRISStreamEvent` only.

### Text → ChatView + Text Field

```
text_delta  →  ChatView.appendToActiveBubble(delta)
               ChatView.updateTextField(delta)

text_done   →  ChatView.finalizeActiveBubble(full)
               TTSQueue.enqueue(full)
```

### TTS pipeline

TTS receives the finalized text from `text_done`. It is strictly one-directional:

```
text_delta events ──→ thread bubble + text field
                  └──→ (accumulated in state.textBuffer)
text_done         ──→ TTSQueue.enqueue(full) → audio only
```

TTS output is **never** written back to the thread or text field. The text is already
there before TTS begins. Do not write it again.

Thinking content is **never** passed to TTS regardless of format.

### STT pipeline

STT produces a user-turn transcription. It is not part of the streaming parser path.

```
STT transcription → ChatView.appendUserBubble(text)
                  → (optionally) ChatView.updateInputField(text)
                  → API call → new stream starts
```

STT text writes to the user bubble exactly once. It is never written again by TTS or
the streaming parser. The streaming parser only ever writes to the assistant bubble.

### Thinking content

```
thinking_delta  →  ThinkingPanel.append(delta)    (if panel exists)
thinking_done   →  ThinkingPanel.finalize(full)
```

Thinking content never enters the conversation thread, text field, or TTS queue.
If IRIS has no thinking panel UI component, discard thinking events silently.

-----

## Provider Detection and Format Assignment

Detect format at call construction time. Never branch on format inside the parser
or inside any downstream subsystem.

```typescript
type StreamFormat = "anthropic" | "openai-compatible" | "llamacpp-native";

function resolveStreamFormat(model: IRISModel): StreamFormat {
  if (model.provider === "anthropic")      return "anthropic";
  if (model.endpoint.endsWith("/v1/messages"))     return "anthropic";
  if (model.endpoint.endsWith("/v1/chat/completions")) return "openai-compatible";
  if (model.endpoint.endsWith("/completion"))      return "llamacpp-native";
  return "openai-compatible"; // safe default for unknown OAI-compat backends
}
```

Instantiate the correct adapter once per stream. Do not switch adapters mid-stream.

-----

## Error and Interruption Handling

On stream interruption:

- Emit `stream_error`
- Mark the active bubble as truncated (e.g., append `[interrupted]`)
- Do not pass a truncated text block to TTS
- Stop the TTS audio queue if playback was already started from a prior sentence
- For Format A: text block content is recoverable up to last `text_delta`; thinking
  and tool_use blocks are not — discard their buffers
- For Format B / C: `state.textBuffer` holds the recoverable partial text

-----

## Implementation Checklist

- [ ] `resolveStreamFormat` runs at call construction, result stored on the stream context
- [ ] Parser state (buffers, blockTypes, thinkState, remainder) is reset per API call
- [ ] Format A adapter tracks `index → type` in a map; never assumes block position
- [ ] Format B adapter checks `delta.reasoning_content` then `delta.reasoning` (both)
- [ ] Format B / C `<think>` state machine persists across chunk boundaries via `remainder`
- [ ] `<think>` / `</think>` tags and their content never reach `text_delta` events
- [ ] `text_delta` routes to both the conversation thread bubble and the text field
- [ ] `text_done` triggers `TTSQueue.enqueue` — called exactly once per assistant turn
- [ ] TTS output is never written back to thread or text field
- [ ] STT transcription writes to user bubble exactly once, then triggers the API call
- [ ] `thinking_delta` / `thinking_done` route to thinking panel only — never to TTS
- [ ] Tool use blocks (Format A) and `tool_calls` deltas (Format B) never reach the thread
- [ ] Format A: `redacted_thinking` opens and closes silently, no events emitted
- [ ] Format B / C: `[DONE]` or `stop: true` triggers `stream_done` if `finish_reason` absent
- [ ] Stream interruption marks bubble truncated and halts TTS queue
- [ ] No model-name branching anywhere in the parser or downstream subsystems
- [ ] `llama.cpp /completion` (Format C) is proxied through the Format B state machine
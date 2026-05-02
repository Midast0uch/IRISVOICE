# Recall-as-Cognition — Architecture Reference

## Overview

Recall-as-Cognition (Domain 16) replaces the traditional "stuff context into the window" approach to memory with a protocol where the model actively retrieves what it needs before answering. The context window becomes a working scratch-pad; the coordinate graph database is the brain.

Every response runs through a two-phase protocol:

```
Phase R (Recall)   — model emits structured <recall .../> ops → memory queries
      ↓
Resolve            — RecallDecoder executes ops against live memory primitives
      ↓
Phase A (Answer)   — model answers with resolved memory injected as prior context
```

**Measured results (live A/B, DeepSeek API, 10-task cross-domain):**

| Metric | Result | Target |
|---|---|---|
| Prompt token reduction | 84.3% | ≥30% |
| Empty answers | 0 | 0 |
| p95 latency ratio (recall/baseline) | 0.99× | ≤1.5× |
| Regressions | 0 / 799 original tests | 0 |

---

## Core Components

### `backend/agent/recall_phases.py`
The two-phase orchestrator. Provider-agnostic — accepts a callable `infer_fn(messages, max_tokens, temperature, stop) -> str` so it never duplicates provider logic.

### `backend/agent/recall_decoder.py`
Parses `<recall .../>` ops from Phase R output and resolves each against the live memory brain. All resolvers degrade gracefully to sentinel spans when memory is absent.

### Integration points
| Location | Role |
|---|---|
| `agent_kernel.py:set_memory_interface()` | Wires RecallDecoder after memory connects |
| `agent_kernel.py:_respond_direct()` | Runs RecallPhases.run() as default inference path |
| `agent_kernel.py:_build_recall_infer_fn()` | Builds provider-specific infer_fn |
| `iris_gateway.py:_handle_chat()` | Closes episode feedback loop after chat turns |
| `iris_gateway.py:_process_voice_transcription()` | Closes episode feedback loop after voice turns |

---

## Phase R — Recall Grammar

Phase R is a short, low-temperature (0.2) completion capped at 256 tokens with a stop sequence (`</recall_phase>`). The model emits self-closing XML ops; it does not answer.

### Grammar Primer (injected into system prompt)

```
Emit <recall .../> ops before answering.
Ops by context: structure→coord  fact→pin query='X'  concept→semantic query='X'
  pattern→similar target='X'  next-step→predict task='X'.
Empty result: emit <recall coord/> to probe, then decompose.
```

### Op Reference

| Op | When to use | Resolver |
|---|---|---|
| `<recall coord/>` | Project structure, file layout, topology navigation | Mycelium coordinate neighborhood |
| `<recall pin query='X'/>` | Named decisions, permanent landmarks, stored facts | Semantic store categories |
| `<recall semantic query='X'/>` | Concept questions, past context retrieval | Episodic chunk retrieval (vector search) |
| `<recall similar target='X'/>` | Repeat a past task pattern, resonance ranking | Episodic similar-episode retrieval |
| `<recall predict task='X'/>` | What comes next in a workflow | BehavioralPredictor next-step hints |
| `<recall route depth=N/>` | Speculative path planning | Immortus SpeculativeRouter |
| `<recall skill query='X'/>` | Invoke a registered action module | SkillsLoader + SkillRegistry |

All ops are self-closing. Attributes may be quoted or unquoted; numeric values are coerced to int/float.

### Cold-start behaviour

When memory is empty or Mycelium is absent, every resolver returns a `ResolvedSpan` with `status="empty"` and a `suggest` hint (`"bootstrap"`, `"decompose"`, `"probe"`) instead of raising or returning blank content. The model can act on these hints in Phase A.

---

## Phase A — Answer with Memory

Phase A shares the identical message prefix with Phase R (system prompt + conversation history). This makes Phase A's prefix a cache hit on every provider with prompt caching (Anthropic, OpenAI, LM Studio, llama-cpp, Ollama, VPS).

### Message structure

```
[system: ... + RECALL_GRAMMAR_PRIMER]
[...conversation history...]
[assistant: "I checked my memory and found:\n<recalled>...</recalled>"]   ← resolved spans
[user: "original question\n\n(Answer directly now — no more <recall/> ops needed.)"]
```

The resolved block is formatted by `RecallDecoder.format_spans_for_phase_a()`. Empty/sparse spans are included so the model can act on probe/decompose suggestions.

---

## Iterative Recall (Multi-Hop Phase R)

For complex tasks requiring chained retrieval, Phase R runs in a bounded loop (max 3 iterations) before Phase A fires.

```
iter 0: Phase R → ops A → resolve → spans_A (conf=0.7)
          ↓
        spans_A injected as "Already recalled:" in next Phase R
          ↓
iter 1: Phase R → ops B (new, not seen before) → resolve → spans_B
          ↓
        all_spans = spans_A + spans_B → Phase A
```

**Termination conditions (first match):**
1. Phase R emits no ops
2. All emitted ops are duplicates of ops already resolved (M2 dedup — `seen_op_keys` set)
3. All resolved spans have `confidence=0.0` (empty memory — no value in chaining)
4. All resolved spans have `confidence≥0.6` (high-confidence — no further hops needed)
5. Max iterations reached (3)

**Cost:** Each Phase R iteration costs only the new tokens (prefix is cached). In practice, cold-start memory terminates in 1 hop; a populated graph with multi-hop tasks terminates in 2-3.

---

## Streaming Provenance Filter

When streaming is active, `_StreamingProvenanceFilter` wraps the chunk callback to strip `<recalled>...</recalled>` blocks and `<recall .../>` ops before they reach the UI. The filter is stateful — it handles tags that arrive split across chunk boundaries.

```python
# Correct: model leaks a tag mid-stream
chunk 1: "Here is my ans"
chunk 2: "wer.<recalled op="pin" confidence="0.90">"
chunk 3: "stored content</recalled> Final answer."

# User sees: "Here is my answer. Final answer."
```

The non-streaming path uses `_strip_provenance()` (regex-based) on the complete Phase A output.

---

## Episode Feedback Loop

Every completed Phase R / Phase A pair is logged as an episodic memory entry with `source_channel='recall'` and `outcome_type='partial'`. The gateway closes the loop:

```python
# iris_gateway.py — after each chat or voice turn:
_ap = getattr(agent_kernel, "_active_recall_phases", None)
if _ap is not None:
    _ap.update_recall_outcome("success" if response else "partial")
```

`update_recall_outcome()` updates the exact episode by its stored ID — never by similarity search (C1 fix). This is safe to call even if recall was not the inference path (it silently no-ops when `_last_episode_id` is not set).

### Episode task_summary format

Recall episodes use a prefixed `task_summary` to prevent episodic dedup from merging different op patterns for the same question:

```
[recall:coord:semantic] What is OAuth PKCE?    ← episode for coord+semantic pattern
[recall:pin]            What is OAuth PKCE?    ← distinct row for pin-only pattern
```

The prefix ensures cosine similarity stays below the 0.95 dedup threshold so each unique op pattern gets its own row and is independently visible to skill genesis.

---

## Skill Genesis from Recall Patterns

`AgentKernel._maybe_trigger_skill_creation()` scans recent `source_channel='recall'` episodes after each DER task close. When any op-type sequence recurs 3+ times with `outcome_type='success'`, it queues a skill-creation prompt:

```sql
SELECT tool_sequence FROM episodes
WHERE source_channel='recall' AND outcome_type='success'
ORDER BY id DESC LIMIT 30
```

The Python-side aggregation counts unique `op_type` sequences and fires once per pattern (tracked in `_prompted_skill_patterns`). The resulting SKILL.md in `backend/agent/skills/` lets future sessions invoke the recall pattern by name.

---

## Distillation Cycle

The 4-hour idle distillation cycle reads recall episodes and promotes repeated `op_type` patterns to `tool_proficiency` semantic entries. These feed back into Phase R op selection over time — IRIS learns which ops work for which task classes without retraining.

---

## Performance Characteristics

### Token cost model

```
Per-turn cost (recall-native):
  Phase R completion:  ~50-150 tokens  (capped at 256, stop sequence)
  Phase A prefix:      cache hit        (shared with Phase R prefix)
  Phase A completion:  same as baseline (same answer length)
  
  Net: +50-150 tokens Phase R, -84% prompt tokens from memory compression
  Break-even: ~2 turns on any session with memory
```

### Provider compatibility

| Provider | Cache | Streaming | Ollama temp |
|---|---|---|---|
| LM Studio (OpenAI-compat) | Prefix KV cache | Yes | N/A |
| DeepSeek API | Prompt caching | Yes | N/A |
| Ollama | Prefix KV cache | Yes (NDJSON) | Always set |
| VPS Gateway | Prefix KV cache | Yes | N/A |
| Local in-process | None | One-shot | N/A |

Ollama streaming uses the `/api/chat` NDJSON endpoint with `stream=True`. Temperature is always included in `options` regardless of value (C4 fix — Ollama server default differs from 0.6).

---

## Disable / Debug

```bash
# Disable recall-native mode entirely (falls back to standard context injection)
IRIS_RECALL_NATIVE=0 uvicorn backend.main:app

# Recall fires only when RecallDecoder is wired (set_memory_interface called)
# If memory interface is unavailable at startup, recall silently does not activate
```

---

## File Map

```
backend/agent/
├── recall_phases.py        — Two-phase orchestrator, streaming filter, episode logging
├── recall_decoder.py       — Op parser, 7 resolvers, NBL cache, sentinel spans
└── tests/
    ├── test_recall_decoder.py      — 34 unit tests for parser + resolvers
    ├── test_recall_integration.py  — 24 integration tests + 5 live DeepSeek
    ├── test_recall_ab.py           — A/B token reduction benchmark (live)
    └── test_recall_fixes.py        — 16 regression tests for Phase 2 correctness fixes
```

---

## Known Limitations

| Gap | Status |
|---|---|
| M3: Outcome signal is response-existence only, not user correction | Tracked in GOALS.md [16.7] — requires thumbs UI |
| `_active_recall_phases` is per-kernel, not per-request — concurrent sessions could mix outcome pointers | Low risk in single-user voice/chat; multi-tab concurrent call could clobber |
| Model may re-emit `<recalled>` (closing form) instead of `<recall>` (op form) in iterative mode | Parser silently ignores, episode costs slightly more Phase R tokens |

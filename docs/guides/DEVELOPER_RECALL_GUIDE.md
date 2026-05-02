# Developer Guide — Recall-as-Cognition

This guide covers how to work with, extend, debug, and test the recall system.
For architecture details see [RECALL_AS_COGNITION.md](../architecture/RECALL_AS_COGNITION.md).

---

## How Recall Activates

Recall-native mode activates automatically when:
1. `AgentKernel.set_memory_interface()` has been called (wires `_recall_decoder`)
2. `IRIS_RECALL_NATIVE` environment variable is not `"0"`
3. The kernel can build a valid `infer_fn` for the current provider

If any condition is false, the kernel falls back to the standard context-injection path silently. No user-visible error.

```python
# Check whether recall is active for a kernel instance
active = (
    kernel._recall_decoder is not None
    and os.environ.get("IRIS_RECALL_NATIVE", "1") != "0"
    and kernel._build_recall_infer_fn() is not None
)
```

---

## Running a Recall Turn Manually

```python
from backend.agent.recall_phases import RecallPhases, make_openai_compat_infer
from backend.agent.recall_decoder import RecallDecoder
from backend.memory.interface import MemoryInterface
import openai

client = openai.OpenAI(base_url="http://localhost:1234/v1", api_key="x")
infer_fn = make_openai_compat_infer(client, model="local-model")

decoder = RecallDecoder(memory_interface=memory, session_id="dev")
phases = RecallPhases(infer_fn=infer_fn, decoder=decoder,
                     memory_interface=memory, session_id="dev")

messages = [
    {"role": "system", "content": "You are IRIS."},
    {"role": "user",   "content": "What were the last 3 tasks I completed?"},
]

answer, spans = phases.run(messages)
print(answer)
for s in spans:
    print(f"  {s.op.op_type} → {s.status} conf={s.confidence:.2f}")
    print(f"  {s.content[:120]}")
```

---

## Adding a New Recall Op

### 1. Register the op type in `recall_decoder.py`

```python
# Add to _VALID_OPS
_VALID_OPS = frozenset({"coord", "pin", "semantic", "predict", "route", "similar", "skill", "YOUR_OP"})

# Add to resolver dispatch in RecallDecoder.resolve()
resolver = {
    ...
    "your_op": self._resolve_your_op,
}
```

### 2. Write the resolver

```python
def _resolve_your_op(self, op: RecallOp) -> ResolvedSpan:
    if self._mem is None:
        return _empty_span(op, hint="no_memory", suggest="bootstrap")
    
    query = op.args.get("your_op", "")
    if not query:
        return _empty_span(op, hint="no_query")
    
    try:
        # call an existing memory primitive — never build new retrieval logic here
        result = self._mem.your_existing_primitive(query)
        if not result:
            return _empty_span(op, hint="no_result", suggest="decompose")
        return ResolvedSpan(
            op=op,
            content=str(result),
            confidence=0.8,
            source="your/source",
        )
    except Exception as exc:
        return _error_span(op, exc)
```

### 3. Update the grammar primer

```python
# recall_phases.py — RECALL_GRAMMAR_PRIMER
# Add the new op to the context guide (keep total under 300 chars)
```

### 4. Write a test

```python
# backend/agent/tests/test_recall_decoder.py
def test_resolve_your_op_returns_span(self):
    mem = MagicMock()
    mem.your_existing_primitive.return_value = "result"
    decoder = RecallDecoder(memory_interface=mem)
    op = RecallOp("your_op", {"your_op": "query"}, "<recall your_op='query'/>")
    span = decoder.resolve(op)
    self.assertEqual(span.status, "ok")
    self.assertIn("result", span.content)
```

---

## The Episode Feedback Loop

Every `phases.run()` call logs a recall episode. The gateway closes the outcome after the turn:

```
phases.run() → _log_recall_episode() → store_episode() → _last_episode_id set
                                                              ↓
gateway: update_recall_outcome("success"|"partial")  →  UPDATE episodes SET outcome_type=? WHERE id=?
                                                              ↓
distillation cycle → scan recall episodes → compress patterns → semantic tool_proficiency entries
                                                              ↓
_maybe_trigger_skill_creation → scan 'success' recall episodes → queue SKILL.md if 3+ matching
```

To inspect what's in the feedback loop:

```python
# Read recent recall episodes directly
import sqlite3
conn = sqlite3.connect("data/databases/coordinates.db")
rows = conn.execute(
    "SELECT task_summary, outcome_type, tool_sequence FROM episodes "
    "WHERE source_channel='recall' ORDER BY timestamp DESC LIMIT 10"
).fetchall()
for task, outcome, ops in rows:
    print(f"{outcome:8s} | {task[:60]}")
    print(f"         | ops: {ops[:80]}")
```

---

## Debugging Recalls

### Force-disable recall

```bash
IRIS_RECALL_NATIVE=0 uvicorn backend.main:app --reload
```

### Enable debug logging

```python
import logging
logging.getLogger("backend.agent.recall_phases").setLevel(logging.DEBUG)
logging.getLogger("backend.agent.recall_decoder").setLevel(logging.DEBUG)
```

Debug logs show:
- Which ops Phase R emitted
- Which were deduplicated (M2)
- Resolution status and confidence per op
- Episode storage and outcome updates

### Inspect a streaming provenance filter

```python
from backend.agent.recall_phases import _StreamingProvenanceFilter

chunks_seen = []
filt = _StreamingProvenanceFilter(callback=chunks_seen.append)

# Simulate streaming chunks
filt.feed("Normal text <recalled op=")
filt.feed('"pin" confidence="0.9">secret content</recalled> visible.')
filt.flush()

print(chunks_seen)  # ["Normal text ", " visible."]
```

---

## Testing Recall Components

The test suite is split by scope:

| File | Scope | Runs without network |
|---|---|---|
| `test_recall_decoder.py` | Parser + all 7 resolvers with mocked memory | Yes |
| `test_recall_integration.py` | Full two-phase protocol with mock infer | Yes (non-live tests) |
| `test_recall_ab.py` | A/B token reduction vs baseline | No (live DeepSeek API) |
| `test_recall_fixes.py` | Correctness fixes C1–C5, M1–M2 | Yes |

```bash
# Run all non-live tests
venv/bin/python -m pytest backend/agent/tests/ -k "not Live" -q

# Run live A/B benchmark (requires DEEPSEEK_API_KEY)
venv/bin/python -m pytest backend/agent/tests/ -m live -v
```

### Writing a mock-based integration test

```python
from backend.agent.recall_phases import RecallPhases, _RECALL_STOP
from backend.agent.recall_decoder import RecallDecoder

def fake_infer(messages, max_tokens=-1, temperature=0.6, stop=None, chunk_callback=None):
    if stop and "</recall_phase>" in stop:
        return '<recall semantic query="topic"/>'  # Phase R output
    return "Here is the answer."                   # Phase A output

phases = RecallPhases(infer_fn=fake_infer, decoder=RecallDecoder())
answer, spans = phases.run([
    {"role": "system", "content": "You are IRIS."},
    {"role": "user",   "content": "Tell me about topic."},
])
assert answer == "Here is the answer."
assert any(s.op.op_type == "semantic" for s in spans)
```

---

## What Each Critical Fix Prevents

These are the bugs that were found and fixed in Phase 2 review. Understanding them helps avoid re-introducing them.

### C1 — Episode ID, not similarity search
`update_recall_outcome()` must use `self._last_episode_id` (the ID returned by `store_episode()`). Never re-derive the episode by calling `retrieve_similar()` — that is a fuzzy semantic search that can match a different row, especially when multiple sessions share similar task summaries.

### C2 — Op-keyed task_summary
Recall episodes for the same user question but different op patterns would merge under the 0.95 cosine dedup threshold if the task_summary were identical. The `[recall:coord:semantic]` prefix makes them embed differently. Do not strip or alter this prefix — it is load-bearing for skill genesis.

### C3 — SQL filter is `outcome_type='success'`
The episodic store never writes `'hit'` to the episodes table (`'hit'` is a Mycelium-domain value). The skill genesis query must filter for `'success'` only. Adding `'hit'` back to the IN clause would be a silent no-op that makes it look like skill genesis is searching more broadly than it is.

### C4 — Ollama temperature
Ollama's server default temperature is typically 0.8, not 0.6. Always pass `temperature` in the `options` dict regardless of its value. The `if temperature != 0.6` guard that caused this bug must not be re-introduced.

### C5 — chunk_callback in direct path
`process_text_message()` calls `_respond_direct(text, context, chunk_callback=chunk_callback)`. The `chunk_callback` argument must be forwarded. Removing it makes all non-tool conversational responses appear as a single block (no streaming) — a silent UX regression that is easy to miss in testing since the response content is still correct.

---

## Skill Genesis Lifecycle

When a recall op pattern recurs 3+ times with `outcome_type='success'`:

1. `_maybe_trigger_skill_creation()` appends a prompt to `_pending_follow_ups`
2. `_flush_pending_follow_ups()` in `iris_gateway.py` sends it to the client after the next response
3. The agent writes `backend/agent/skills/<skill_name>.skill.md`
4. `SkillsLoader` picks it up on next load — `<recall skill query="name"/>` can then surface it

Skills generated from recall patterns are marked with a `[recall-pattern]` tag in their frontmatter so they can be distinguished from manually authored skills.

---

## Phase 3 — Pending (M3)

The only remaining gap is real user correction signal. Currently `update_recall_outcome` is called with `'success'` when any non-empty response is returned — it cannot distinguish "answered well" from "answered at all."

What needs building: a thumbs-up / thumbs-down button on each assistant bubble in ChatView that emits `{ type: "recall_feedback", payload: { outcome: "success" | "failure" } }`. The gateway handler calls `agent_kernel.update_last_recall_outcome(outcome)`.

See GOALS.md [16.7] for the full spec and graduation condition.

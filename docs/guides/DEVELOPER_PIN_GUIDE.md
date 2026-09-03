# Developer Guide — PiN System

This guide covers how to use, extend, and debug the PiN (Primordial Information
Node) system. For architecture details see
[PIN_SYSTEM.md](../architecture/PIN_SYSTEM.md). For recall integration see
[RECALL_AS_COGNITION.md](../architecture/RECALL_AS_COGNITION.md).

---

## Quick Start — Creating a Pin from the Agent

The agent invokes pins via tools just like any other tool call:

```python
# Inside an agentic loop or DER plan step
result = await tool_bridge.execute_tool("pin_add", {
    "title": "OAuth PKCE flow",
    "content": "# PKCE\n\nProof Key for Code Exchange...\n\n## Why\n\nPrevents code interception attacks.",
    "pin_type": "decision",
    "tags": ["auth", "oauth"],
    "file_refs": ["src/auth/pkce.py"],
}, session_id=session_id)
# {"success": True, "pin_id": "abc-123-..."}
```

Then on a future turn the agent can pull it back:

```xml
<recall pin query="PKCE"/>
```

---

## Quick Start — Creating a Pin from the User

The user can ask the agent to pin something:

> *"Pin this conversation about the OAuth PKCE flow as a decision record."*

The agent should invoke `pin_add` with:
- `title` derived from the topic
- `content` summarising the conversation in markdown
- `pin_type='decision'`
- relevant `tags` and `file_refs`

There is no separate UI for pin creation yet — the user goes through the agent.
The dedicated MCM Browser panel is tracked in GOALS.md [16.8].

---

## Using PinStore Programmatically

```python
from backend.memory.pin_store import PinStore
from backend.memory.db import open_encrypted_memory

conn = open_encrypted_memory("data/databases/coordinates.db", biometric_key=b"...")
store = PinStore(conn=conn, origin_id="my-instance")

# Create
pid = store.add(title="Note", content="# heading\n\nbody", tags=["x"])

# Search with custom weights
hits = store.search("body",
                    weights={"title": 100, "content": 10})  # bias toward titles
for pin, score in hits:
    print(score, pin.title)

# Link to another pin
other = store.add(title="Other")
store.link(pid, other, relationship="related_to")

# Walk the wiki graph
neighbours = store.linked(pid, depth=2)
```

---

## Auto-Checkpoint Behaviour

Every successful `write_file` tool call triggers `_maybe_auto_checkpoint()` in
`tool_bridge.py`. When the content size crosses
`auto_pin.checkpoint_threshold_kb` (default 2KB), a checkpoint pin is created
automatically:

```python
# What gets stored:
title:    'checkpoint:src/auth.py@3450'      # path + offset
pin_type: 'checkpoint'
tags:     ['checkpoint', 'auto']
file_refs: ['src/auth.py']
content: """
**Checkpoint summary**

Auto-checkpoint after write to `src/auth.py` (3.4KB).

Lead line: `def authenticate(request, mfa_required=False):`

**Last bytes (2048 chars):**
```
... last 2KB of generated content ...
```
"""
```

Recovery on a future turn:
```xml
<recall pin file="src/auth.py"/>
```

Returns all checkpoints chronologically. The agent reads the summaries and
the truncated content snapshots and reconstructs context.

### Disabling auto-checkpoint

```python
kernel.set_auto_pin_settings(enabled=False)
```

Or per-threshold:
```python
kernel.set_auto_pin_settings(checkpoint_threshold_kb=10.0)  # only files >10KB
```

---

## Tuning Search Weights

Default weights from `mcm/actions/search.json`:

| Field | Weight |
|---|---|
| `title` | 50.0 |
| `content` | 30.0 |
| `tags` | 20.0 |
| `file_refs` | 15.0 |

### Per kernel (persisted across recall ops)

```python
kernel.set_auto_pin_settings(search_weights={
    "title": 75.0,
    "content": 50.0,    # boosted for content-heavy notes
    "tags": 20.0,
    "file_refs": 15.0,
})
```

### Per call (one-off override)

```python
store.search("auth", weights={"title": 100.0})  # ignore content/tags entirely
```

### How to know when to tune

- **Pins not surfacing for clear queries** → boost `content` or `tags`
- **Wrong pin always wins** → check whether title or content match dominates by
  inspecting the score returned alongside each result
- **File-anchored pins missed** → boost `file_refs`

---

## Debugging Pin Recall

### Check whether the PinStore is wired

```python
from backend.agent.agent_kernel import get_agent_kernel
k = get_agent_kernel("default")
print("pin_store:", k._pin_store)             # should be a PinStore instance
print("decoder pin_store:", k._recall_decoder._pin_store)  # same object
```

If either is `None`, `set_memory_interface()` was either never called or the
episodic store had no `db` attribute.

### Inspect recent pins

```python
import sqlite3
conn = sqlite3.connect("data/databases/coordinates.db")
rows = conn.execute(
    "SELECT pin_id, pin_type, title, datetime(created_at, 'unixepoch') "
    "FROM mycelium_pins ORDER BY created_at DESC LIMIT 20"
).fetchall()
for r in rows:
    print(r)
```

### Trace what `<recall pin query='X'/>` returned

```python
import logging
logging.getLogger("backend.agent.recall_decoder").setLevel(logging.DEBUG)
```

Debug logs show op type, args, status, confidence per call.

---

## Adding a New Pin Type

Pin types are an informal vocabulary — no schema change required.

1. **Add the constant** to `backend/memory/pin_store.py`:
   ```python
   PIN_TYPES = ("note", "file", ..., "your_new_type")
   ```
2. **Document its meaning** in `docs/architecture/PIN_SYSTEM.md` (the Pin types table).
3. **(Optional) special-case behaviour** — if your type needs auto-creation,
   special rendering, or filtered queries, add helpers to `PinStore` similar
   to `checkpoint()` / `list_checkpoints_for_file()`.

---

## Adding a New Recall Op for Pins

The `<recall pin .../>` decoder is in `recall_decoder.py:_resolve_pin()`. It
branches on the args dict in priority order:

1. `file=` → checkpoint recovery
2. `tags=` → tag-filtered search
3. `query=` → ranked search (with optional `depth=`)
4. `pin=` → exact title lookup
5. legacy semantic-store fallback

To add a new branch (e.g. `<recall pin author='X'/>`):

```python
author = op.args.get("author", "")
if author and self._pin_store is not None:
    pins = self._pin_store.search_by_author(author)  # add to PinStore
    ...
```

Place the new branch above the legacy fallback so it takes precedence.
Update the test suite (`test_pin_store.py`) and the architecture doc.

---

## Linking Pins as a Wiki Graph

The `link()` API forms typed edges between pins (and between pins and
landmarks/episodes/nodes):

```python
auth_pin = store.add(title="OAuth", content="...")
pkce_pin = store.add(title="PKCE", content="...")
mfa_pin  = store.add(title="MFA", content="...")

store.link(auth_pin, pkce_pin, relationship="contains")
store.link(auth_pin, mfa_pin,  relationship="contains")
store.link(pkce_pin, mfa_pin,  relationship="depends_on")
```

The agent can then walk the graph:

```xml
<recall pin query="OAuth" depth=2/>   <!-- returns OAuth + PKCE + MFA -->
```

Or call `pin_get` + `linked` programmatically for explicit traversal.

### Relationship vocabulary

| Relationship | Meaning |
|---|---|
| `documents` | source explains target (pin → landmark/episode/node) |
| `references` | source cites target |
| `implements` | source is the implementation of target (decision) |
| `depends_on` | source content depends on target's existence |
| `contains` | parent → child |
| `related_to` | loose association (default) |

These are not enforced — they are conventions for the agent to reason over.

---

## Testing Pin Code

```bash
# Run all pin tests
venv/bin/python -m pytest backend/agent/tests/test_pin_store.py -v

# Run a specific test class
venv/bin/python -m pytest backend/agent/tests/test_pin_store.py::TestCheckpoint -v
```

The test file uses an in-memory SQLite database that mirrors the production
schema, so tests are fast and require no fixtures.

### Writing a new test

```python
def test_my_thing(self):
    self.store = PinStore(conn=_make_pin_db())  # helper at top of test file
    pid = self.store.add(title="X")
    # ... assertions
```

---

## Common Pitfalls

### 1. Forgetting `on_write` invalidation
If you add a new mutating method to `PinStore`, call `self._notify_write()` at
the end. Otherwise the recall decoder's cache may serve stale results.

### 2. JSON list fields
`tags`, `file_refs`, `image_refs`, `url_refs` are stored as JSON strings. The
PinStore handles serialization automatically — never write raw lists into the
columns directly.

### 3. Unicode in titles
`get_by_title` does an exact string match. If the agent writes a title with a
trailing space, `<recall pin="Title"/>` won't find it. Recommend using `query=`
form when title fidelity is uncertain.

### 4. The IRIS-app PinStore is NOT the IRIS-development MCM SDK
The MCM SDK (`mcm pin_add ...`) is a developer tool used while building IRIS.
The IRIS application has its own PinStore (this module) backed by the same
schema in `coordinates.db`. They are separate code paths — do not import or
delegate between them.

---

## Performance Notes

- `search()` is a full-table scan with Python-side scoring. Acceptable up to
  ~10k pins; profile and migrate to FTS5 if you exceed that.
- `linked(depth=N)` is breadth-first with one query per hop. Limit `depth` to
  3-4 in practice.
- `list_checkpoints_for_file()` uses `LIKE '%"path"%'` against the JSON
  `file_refs` column. Fast for small DBs; if checkpoint count grows large per
  file, denormalise into a dedicated index table.

---

## Settings Reference

```python
kernel.set_auto_pin_settings(
    enabled=True,                       # master toggle
    checkpoint_threshold_kb=2.0,        # min file size for auto-checkpoint
    search_weights={                    # tunable ranking
        "title": 50.0,
        "content": 30.0,
        "tags": 20.0,
        "file_refs": 15.0,
    },
)
```

These settings are per-AgentKernel (per-session). To apply them globally you
would persist them in user settings and call `set_auto_pin_settings()` in
`set_memory_interface()` or shortly after.

# PiN System — Architecture Reference

## What a PiN Is

A **Primordial Information Node** (PiN) is any knowledge artifact anchored to IRIS memory:
a markdown note, a file/folder reference, an image, a URL, an architectural decision,
or a mid-file-write checkpoint. PiNs serve three distinct roles:

1. **Wiki anchors** — linked via `mycelium_pin_links` to landmarks, episodes, or other pins.
   The agent and user can navigate them as a graph.

2. **Recall anchors** — surfaced by the recall decoder via `<recall pin .../>` ops when the
   agent reasons over a related task. Pin content is markdown and is rendered verbatim into
   the Phase A context.

3. **Checkpoints** — special `pin_type='checkpoint'` anchors written mid-file-write when
   context pressure rises or after a large file is written. The next session can recover
   the in-progress work via `<recall pin file='X.md'/>`.

Pins are available in **both Personal and Developer modes** — they have no mode gate.

---

## Data Model

The schema lives in `backend/memory/db.py:308`:

```sql
CREATE TABLE mycelium_pins (
    pin_id       TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    pin_type     TEXT DEFAULT 'note',
    content      TEXT,                  -- markdown body
    tags         TEXT DEFAULT '[]',     -- JSON array
    file_refs    TEXT DEFAULT '[]',
    image_refs   TEXT DEFAULT '[]',
    url_refs     TEXT DEFAULT '[]',
    project_id   TEXT,
    origin_id    TEXT,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    is_permanent INTEGER DEFAULT 0
);

CREATE TABLE mycelium_pin_links (
    link_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type  TEXT NOT NULL,         -- 'pin' | 'landmark' | 'episode' | 'node'
    source_id    TEXT NOT NULL,
    target_type  TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    relationship TEXT NOT NULL,         -- 'documents'|'references'|'implements'|
                                        -- 'depends_on'|'contains'|'related_to'
    weight       REAL DEFAULT 1.0,
    created_at   REAL NOT NULL
);
```

### Pin types (informal vocabulary)

| Type | Use |
|---|---|
| `note` | Default — generic markdown note |
| `file` | Anchored to a specific file in the workspace |
| `folder` | Anchored to a directory |
| `image` | Image with description (path in `image_refs`) |
| `doc` | Long-form document reference |
| `url` | External URL (in `url_refs`) |
| `decision` | Architectural decision record |
| `fragment` | Sub-piece of a larger artifact |
| `checkpoint` | Mid-write recovery anchor (auto-created) |

The `pin_type` column has no CHECK constraint — these are conventional values.
Adding a new type costs nothing.

---

## API — `backend/memory/pin_store.py`

All pin operations go through the `PinStore` class. It's instantiated by the
`AgentKernel.set_memory_interface()` method using the same SQLite connection
as the episodic store, so writes are WAL-safe and visible across all consumers.

### Core methods

```python
store.add(title, content, pin_type, tags, file_refs, image_refs, url_refs,
          project_id, is_permanent) -> pin_id
store.get(pin_id) -> Pin | None
store.get_by_title(title) -> Pin | None
store.update(pin_id, **fields) -> bool
store.delete(pin_id) -> bool
store.list(project_id, pin_type, limit) -> [Pin]
store.search(query, limit, types, project_id, weights) -> [(Pin, score)]
store.link(source_id, target_id, relationship, source_type, target_type, weight) -> link_id
store.linked(pin_id, relationship, depth) -> [Pin]
store.checkpoint(file_path, offset, summary_md, content_snapshot, project_id) -> pin_id
store.list_checkpoints_for_file(file_path, limit) -> [Pin]
```

### `Pin.to_markdown()`

Every pin renders as a self-contained Markdown block. The recall decoder uses this
when injecting pins into Phase A context:

```markdown
## OAuth PKCE notes
_type: `decision`_
_tags: `auth`, `oauth`_
_files: `src/auth/pkce.py`_

# PKCE flow

1. Client generates code verifier...
```

---

## Recall Integration

`<recall pin .../>` resolves through `RecallDecoder._resolve_pin()`. Five op forms
are supported:

| Op | Behaviour |
|---|---|
| `<recall pin="Title"/>` | Exact title lookup, returns most recent matching pin |
| `<recall pin query="text"/>` | Ranked search across title/content/tags/file_refs |
| `<recall pin query="text" depth=1/>` | Search + 1-hop link expansion |
| `<recall pin file="path/X.md"/>` | All checkpoints for that file, chronological |
| `<recall pin tags="api,auth"/>` | Pins matching any of the given tags |

When no `PinStore` is wired (early init or fallback), the resolver degrades to the
legacy semantic-store lookup so existing callers continue to work.

### Cache invalidation

The `PinStore` accepts an `on_write` callback that is fired after every mutating
operation. The kernel wires this to `RecallDecoder.invalidate_cache()`, ensuring
freshly added pins are visible to the next recall op without waiting for the NBL
fingerprint to shift.

---

## Search Ranking

Search uses substring matching with weighted contribution per field. Defaults match
the spec in `mcm/actions/search.json`:

| Field | Default weight |
|---|---|
| `title` | 50.0 |
| `content` | 30.0 |
| `tags` | 20.0 |
| `file_refs` | 15.0 |
| `context_overlap` | 10.0 (reserved for future) |

**Tunable per call:**
```python
store.search("auth", weights={"title": 100, "content": 10})
```

**Tunable per kernel:**
```python
kernel.set_auto_pin_settings(search_weights={"title": 75, "content": 50})
```

Substring matching is fast on small/medium databases (~10k pins). Migrate to FTS5
only when pin counts cross that threshold.

---

## Auto-Checkpoint Heuristic

`tool_bridge._maybe_auto_checkpoint()` fires after a successful `write_file` tool
call. When the written content exceeds the configured threshold (default 2KB),
a `pin_type='checkpoint'` pin is created automatically.

Checkpoint content layout:

```markdown
**Checkpoint summary**

Auto-checkpoint after write to `src/auth.py` (3.4KB).

Lead line: `def authenticate(request, mfa_required=False):`

**Last bytes (2048 chars):**
```
... last 2KB of generated content ...
```
```

Recovery is a single recall op:

```xml
<recall pin file="src/auth.py"/>
```

Returns all checkpoints for that file in chronological order, allowing the agent
to reconstruct the in-progress write.

### Settings

Configured via `AgentKernel.set_auto_pin_settings()`:

| Field | Default | Effect |
|---|---|---|
| `enabled` | `True` | Master toggle for auto-checkpointing |
| `checkpoint_threshold_kb` | `2.0` | Min file size that triggers a checkpoint |
| `search_weights` | `None` (use defaults) | Per-kernel ranking override |

---

## Agent Tool Surface

The agent invokes pins via these tool names (routed through `tool_bridge.execute_tool`):

| Tool | Parameters | Return |
|---|---|---|
| `pin_add` | title, content, pin_type, tags, file_refs, image_refs, url_refs, project_id, is_permanent | `{success, pin_id}` |
| `pin_search` | query, limit, types, project_id | `{success, results: [{pin, score}]}` |
| `pin_link` | source_id, target_id, relationship, source_type, target_type, weight | `{success, link_id}` |
| `pin_checkpoint` | file_path, offset, summary_md, content_snapshot, project_id | `{success, pin_id}` |
| `pin_get` | pin_id | `{success, pin}` |
| `pin_list` | project_id, pin_type, limit | `{success, pins: [...]}` |

All pin tools are session-scoped — they write through the `PinStore` instance
attached to the current session's `AgentKernel`. Field whitelisting prevents
the agent from injecting arbitrary columns.

---

## Wiki Graph — `pin_link` Use Cases

Linking pins forms a navigable knowledge graph. Common patterns:

```
PinA  documents     →  Landmark42        (this pin explains a verified landmark)
PinB  references    →  PinA              (this pin cites another pin)
PinC  implements    →  Decision-D9       (code-impl pin → decision pin)
PinD  depends_on    →  PinE              (this pin's content depends on another)
PinF  contains      →  PinG              (parent → child relationship)
PinH  related_to    →  PinI              (loose association — default)
```

The decoder's `<recall pin query="X" depth=1/>` form returns search hits plus
their direct neighbours, surfacing related pins the agent might not have
queried for explicitly.

---

## Performance Characteristics

| Operation | Cost |
|---|---|
| `add` | 1 INSERT, 1 commit, on_write callback |
| `get` / `get_by_title` | 1 indexed SELECT |
| `search` | full table scan + Python-side scoring (acceptable up to ~10k pins) |
| `list_checkpoints_for_file` | indexed SELECT with `LIKE` on JSON file_refs |
| `linked(depth=1)` | 1 JOIN per hop |

Indexes that exist (from `db.py:430`):
- `idx_pins_type`, `idx_pins_origin`, `idx_pins_project`
- `idx_pin_links_source(source_type, source_id)`
- `idx_pin_links_target(target_type, target_id)`

---

## File Map

```
backend/memory/
├── db.py                      — schema (mycelium_pins, mycelium_pin_links)
└── pin_store.py               — PinStore CRUD service

backend/agent/
├── recall_decoder.py          — _resolve_pin() — 5 op forms
├── agent_kernel.py            — set_memory_interface() wires PinStore + decoder
└── tool_bridge.py             — pin_add/search/link/checkpoint/get/list routing
                                — _maybe_auto_checkpoint() after write_file

backend/agent/tests/
└── test_pin_store.py          — 34 regression tests
```

---

## Future Work — `[16.8]` MCM Browser Panel

A dedicated UI panel surfacing the entire MCM database in human-readable form is
tracked in `bootstrap/GOALS.md [16.8]`. The PinStore foundation must be live and
stable before that panel is built — see GOALS.md for the full spec and graduation
condition.

---

## Known Limitations

| Gap | Impact |
|---|---|
| Substring search, no FTS5 | Slow at >10k pins; upgrade trivially when needed |
| Auto-checkpoint only on completed writes, not mid-stream | Long single-turn writes >context window are still vulnerable |
| `_maybe_trigger_skill_creation` doesn't yet read pin patterns | Pins don't drive skill genesis; they could |
| No UI panel yet | Pin browsing requires direct DB access or recall ops |

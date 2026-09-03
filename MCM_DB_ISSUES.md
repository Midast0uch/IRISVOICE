# MCM coordinates.db — failure modes found in the standalone SDK

Written 2026-08-03 for the IRISVOICE agent.

IRISVOICE embeds an MCM-style memory layer **inside the application**, rather than
running it only as an MCP server. Everything below was found and fixed in the
standalone SDK (`C:\Users\midas\MCM-EML-SDK2.0-worktrees\caducean-integration`)
against this project's own 853 MB `.mcm/coordinates.db`. The same shapes are
likely present in the in-app implementation, and several are *worse* when the
writer is the application itself, because an app writes far more often than an
agent does and nobody is reading the errors.

Every number here is measured on the live DB, not estimated.

---

## 0. Read this first: the pattern behind all of it

Every one of these was a **silent failure**. Nothing crashed, nothing alerted.
The DB kept accepting writes while quietly losing, duplicating, or stranding
data. Two consequences worth internalising before you touch anything:

- **"No error" is not evidence of correctness.** Several of these bugs sat
  behind `try/except`, fire-and-forget calls, or fail-open handlers.
- **Verify by asserting an observable side effect**, never by the absence of an
  exception. Read the row back. Count it before and after.

---

## 1. `file_nodes` has TWO unique constraints — match on both

```sql
file_id   TEXT PRIMARY KEY
file_path TEXT UNIQUE NOT NULL
```

The upsert looked up by `file_id` only. When a row existed under an older id
scheme (12-hex ids where the current hash emits 16), the lookup missed, the code
fell to `INSERT`, and the insert collided on `file_path`:

```
UNIQUE constraint failed: file_nodes.file_path
```

The node with the **largest edit history (31 edits)** was frozen — every
subsequent write to that file raised, and it silently accepted no more history.

**Check in IRISVOICE:** any upsert against a table with a second unique column.
Match on `file_id OR file_path`, prefer the id hit so current-scheme rows stay
authoritative, and accumulate onto whichever row actually exists — not onto the
id you just computed, or the `UPDATE` matches nothing and the write vanishes.

---

## 2. Path spelling fragments a file's history

`file_id = sha256(file_path)`, so every spelling of the same file becomes a
different node:

```
backend/agent/agent_kernel.py                                    31 edits
IRISVOICE/backend/agent/agent_kernel.py                          14 edits
C:\Users\midas\Desktop\IRISVOICE\backend\agent\agent_kernel.py    5 edits
C:\dev\IRISVOICE\backend\agent\agent_kernel.py                   16 edits
```

Measured across the DB: **113 logical files spread over 267 nodes, 403 edits
stranded** off the primary node. Confidence, activation counts, and topology
classification are all computed per-node, so a fragmented file looks cold in
every one of them despite being the most-edited file in the project.

**This is the highest-risk item for an in-app MCM.** An application has even
more path sources than an agent does: config, CWD-relative, user-selected,
OS-normalised, and whatever the UI passes. Canonicalise at the **write
boundary** — one function every write path goes through — not at read time.

### Canonicalisation: do not anchor on the project name

The obvious approach (strip everything up to the project directory name) fails
twice: it mis-groups any path containing that word at another nesting level,
**and it breaks if the project is ever moved or renamed** — the canonical form
shifts and every node re-fragments against its own history.

What works is learning roots from the data, accepting a prefix only when the DB
corroborates it: `P` is a root when some path `P/R` exists **and** `R` exists
independently as its own path. Two spellings of one file must both be present
before anything is stripped. See `mcm/protocols/node_merge.py::learn_roots`.

**Only absolute prefixes may become roots.** A first version learned from
relative pairs too, so `backend/foo.py` alongside `foo.py` made `backend` a
root — and `backend/agent/agent_kernel.py` was stripped to
`agent/agent_kernel.py`, silently amputating a real directory and splitting the
file from its own history under a mangled key. That is worse than the bug being
fixed. Restrict roots to drive-letter or leading-slash prefixes.

---

## 3. Co-edit edges explode quadratically

The pheromone-trail builder joined against every file the session had ever
touched, unbounded:

```sql
SELECT DISTINCT file_path FROM code_events WHERE session_number = ?
```

The Nth edit in a session creates N-1 edges, so a session touching N files
produces ~N²/2. Result on the live DB:

| | |
|---|---|
| `graph_edges` rows | **3,386,800** |
| `file_nodes` | 6,691 (~500 edges per node) |
| `co_edit` | 3,386,771 |
| ever reinforced (weight > 1.0) | **713** |
| duplicates / self-edges | 0 |

The mechanism is *correct* — no duplicates, dedup works — but **99.98% of it is
fan-out noise**, and it is the main reason the DB is 853 MB. Edge count grew
with session *length*, not with relatedness.

**Fix:** bound the link set to the K most-recently-touched files (K=8 in the
SDK). O(N·K) instead of O(N²). This matters much more in-app: an application
touching hundreds of files per run would generate edges without limit.

**When cleaning up existing edges, never delete reinforced ones.** A first pass
removed 98 reinforced edges via an "orphan" rule. "Orphan" does not always mean
dead: an edge pointing at a legacy-scheme id looks orphaned while its file still
exists under a different id, and a node merge would re-attach it. Weight-gate
any orphan cleanup.

---

## 4. `code_events` never deduplicated or decayed

`event_id = sha256(agent_id|event_type|timestamp)` — the timestamp differs on
every call, so genuine double-records always insert cleanly. There is no
uniqueness constraint that can catch them.

**Dedup on a time window, not on identity.** A naive "same session + type + file
+ description" grouping reports 408 duplicates on this DB; the true count within
a 60-second window is **8**. The rest are legitimate re-runs — the same test run
ten minutes later is a real, distinct event. A naive dedup would destroy real
history. Landmark-anchored events should be exempt entirely.

---

## 5. Decay must be reinforcement-aware, and pins are not events

The pin expiry rule deleted non-permanent pins older than 30 days **by
`created_at`**, so a pin actively updated every week still died at day 30.

Two rules worth carrying over:

- Age from **last touch** (`MAX(created_at, updated_at)`), so anything still in
  use never expires.
- **Pins decay far slower than events.** Events are telemetry (7-day grace,
  0.98/pass); pins are curated knowledge (stale at 90 days, removed at 180, and
  two-stage so nothing disappears without first being visibly demoted).

On this DB the old rule would have deleted **55 pins** the first time it ran.

---

## 6. Maintenance that never runs is not maintenance

The KYUDO gate — integrity checks, decay, dedup, reorganisation — was only
reachable from a CLI subcommand. It had **never executed** in normal operation.
Everything above accumulated for months as a result.

If IRISVOICE has an equivalent, verify it is actually invoked, and:

- **Throttle it.** Once per 6h via a timestamp file, claimed *before* the work
  starts so two concurrent starts cannot both launch it.
- **Keep it off the critical path.** `PRAGMA integrity_check` takes >2 minutes
  on an 853 MB DB. Run maintenance on a background thread; never block session
  start.
- **Order matters.** Node merge must run **before** orphan-edge cleanup, or
  decay deletes exactly the history the merge would have recovered.
- **Do not swallow its errors.** A bare `except: pass` around metrics collection
  meant quorum could never fire and reorganisation silently never ran.

---

## 7. In-app specific risks (not applicable to the standalone server)

These are the ones I would check first in IRISVOICE, because the SDK does not
have them:

1. **Concurrent writers.** An MCP server is a single stdio process. An app may
   write from multiple threads, the UI, and a background worker at once. Verify
   WAL mode, a `busy_timeout`, and that maintenance holds no long write
   transaction while the app is live.
2. **Write volume.** Every issue above scales with write frequency. An app
   recording per-action rather than per-agent-decision will hit the edge
   explosion and event duplication far faster.
3. **Semantically empty auto-recording.** Hook-driven recording in the SDK
   passed the *tool name* as the event description — every event's description
   was literally `"edit"` or `"read"`. Description is what feeds landmark
   crystallisation and pheromone trails, so this is worse than not recording.
   If the app records automatically, make sure it supplies real intent.
4. **Schema drift across versions.** The legacy 12-hex `file_id` rows exist
   because the id scheme changed without a migration. If the app ships versions,
   any change to an id derivation needs a migration, not just new code.
5. **DB growth is unbounded without decay.** 853 MB for 6,691 files and 9,091
   events. Almost all of it was edges.

---

## 8. Before you change anything

1. **Back up with the SQLite backup API**, not a file copy — the app may hold
   the DB open. `src.backup(dst)` is lock-safe and reads every page, so a
   successful backup also proves the DB is structurally sound.
2. **Test migrations on a copy.** Every number in this document came from runs
   against copies; the live DB was never touched.
3. **Make migrations idempotent** and verify by re-running — a second run should
   report zero work.
4. **Assert what was preserved, not just what changed.** The merge verification
   checks that events, pins, and landmarks are unchanged and that reinforced
   edges survive, because the interesting failures are the ones that quietly
   delete things.

---

## Reference implementation

In the SDK worktree, on branch `feat/audit-remediation`:

| File | What it covers |
|---|---|
| `mcm/protocols/node_merge.py` | canonicalisation, root learning, fragment merge |
| `mcm/protocols/events.py` | upsert fix, event dedup/decay, pin decay, edge hygiene, bounded co-edit |
| `mcm/constants.py` | all thresholds, each with the reasoning inline |
| `mcm/kyudo.py` | maintenance ordering |

Commits `6d1c48d`, `a75b872`, `3872d54`, `2759b86` carry the full reasoning in
their messages, including the two wrong turns (over-stripping relative roots,
deleting reinforced orphans) and why they were wrong.

**Status caveat:** the fragment merge was verified end-to-end with the earlier
name-based canonicalisation (154 nodes removed, 403 edits reunited, idempotent
re-run clean). The final full-apply run using the newer *learned-roots*
canonicalisation was interrupted before completing, so its dry-run numbers
(172 groups / 563 edits) are verified but the full apply on that version is not.
Re-run it on a copy before trusting it.

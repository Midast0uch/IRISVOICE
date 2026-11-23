# CLM - Context Lifecycle Management: architecture and blueprint

**CLM** controls what a model sees in its window: a block leaves the window only through
a gate, keeps an address in the record, and returns byte for byte. It is the context half
of the app's memory design; its execution surface, the Workbench (CLM-11), has its own
document: [`WORKBENCH.md`](./WORKBENCH.md).

This document describes the code as it is on branch `kernel-split-2026-11-11`. The specs
are the source for intent and measurement; the code is the source for names.

- Requirements: [`specs/clm-memory/requirements.md`](../../specs/clm-memory/requirements.md) (CLM-0 .. CLM-11)
- Design (decisions, rounds, ripple map): [`specs/clm-memory/design.md`](../../specs/clm-memory/design.md)
- Tasks and measured results: [`specs/clm-memory/tasks.md`](../../specs/clm-memory/tasks.md)
- Kernel layout (where node code lives): [`KERNEL_DECOMPOSITION.md`](./KERNEL_DECOMPOSITION.md)
- Execution model these plug into: [`DER_DAG.md`](./DER_DAG.md)

This is the **app's** context machinery. It is not the MCM dev-memory SDK
(`backend/agent/mcm.py` is a separate, lite port; see `CLAUDE.md`).

---

## 1. The live context view

### 1.1 Purpose

Before CLM, a window that was too full was cut blind: the router dropped the oldest
messages and logged a number. What left had no address and could not return. The model
could not see how full its window was, and three places estimated tokens differently.

CLM replaces the blind cut with a **view over a record**:

- **Record** (append-only): `tool_results` rows in `conversations.db`, plus the existing
  stores (`context_chunks`, `memory_chain`, pins, `memory_events` in `data/memory.db`).
- **View** (in memory, rebuilt per turn or per DER run, never persisted): the list of
  blocks the model sees, each with a reference into the record.

Plain picture: the window is a desk. A paper leaves the desk only into the filing
cabinet, a slip with its number stays on the desk, and the paper comes back by number.
The router cap stays as a last safety net; any drop it makes that the view did not make
is counted as a **blind drop** (an alarm, expected 0).

### 1.2 Components

| Component | File : symbol | Job |
|---|---|---|
| Block, Ref, ContextView | `backend/agent/context_view.py` : `Ref`, `Block`, `ContextView.admit/admit_live/render/units/set_aside/set_aside_batch/restore` | Hold blocks and zones; render provider messages; apply an offload batch; restore a unit |
| Placeholder | `context_view.py` : `render_placeholder`, `parse_placeholder` | One line that names the record row, time frame, domain, reason |
| Offload gate | `context_view.py` : `offload_decision`, `OffloadDecision`, `unit_saving`, `MIN_SAVING` (256), `held_resolver`, `offload_refusal_counts` | Decide if a unit may leave; nine counted refusal reasons (`REFUSE_NO_REF`, `REFUSE_UNREADABLE`, `REFUSE_INCOMPLETE`, `REFUSE_PROTECTED`, `REFUSE_NEWEST`, `REFUSE_OPEN_ITEMS`, `REFUSE_BREAK_EVEN`, `REFUSE_ALREADY_ASIDE`, `REFUSE_NOT_IN_VIEW`) |
| Gauge | `backend/agent/context_gauge.py` : `estimate_tokens`, `ContextGauge.observe/ratio/estimate`, `GAUGE`, `record_blind_drop`, `blind_drop_snapshot` | The one count function: a conservative char estimate times an EMA ratio (alpha 0.3, clamp 0.25..4.0) per (provider, model), fitted to the server's `usage.prompt_tokens`. No tokenizer is loaded |
| Node loop (the pressure site) | `backend/agent/node_executor.py` : `run_node`, `_SHRINK_MARGIN` (0.20), `_gauge_line`, `_ledger_section`, `_clip`, `_ref_line`, `clm_node_stats` | Build the node view, run the shrink at the boundary, re-stretch, emit events |
| Node hooks (record, readability, events, pins, ledger) | `backend/agent/kernel/der/node.py` : `_clm_offload_on`, `_clm_node_hooks` (`record_result`, `ref_readable`, `on_clm_event`, `write_pin`), `_clm_dead_ends`, `_clm_recall_menu`, `_clm_menu_budget` | Bind the record and the event sink to a `NodeContext` |
| Record write/read | `backend/conversation_store.py` : `add_tool_result`, `get_tool_result` (table `tool_results`) | Queue a result on a lane; read it by id |
| Expand / set-aside surface | `backend/agent/tool_bridge.py` : `_expand_tool_result`, `_expand_workbench`, `_audit_pin`, and the `recall_memory` branches `expand` / `set_aside` | The model gets a block back by reference |
| Router cap as alarm | `backend/agent/inference/router.py` : `_cap_messages_to_window` reports to `record_blind_drop` | Safety net, counted |
| Baseline instrument | `backend/agent/inference/clm_baseline.py` | Measurement only (section 2) |

`NodeContext` fields that carry CLM (all in `node_executor.py:NodeContext`):
`record_result`, `ref_readable`, `on_clm_event`, `window`, `write_pin`, `dead_ends`. With
none of them set, `run_node` behaves exactly as before (flag off = byte for byte).

### 1.3 Behavior

- **The record.** `record_result` writes a tool result to `tool_results` only when it is
  longer than `_CLM_KEEP_CHARS` (2,500 chars), the tool is not a read tool in
  `_DER_READ_TOOLS`, and it is not `recall_memory` (`_CLM_NO_RECORD`). The write is
  queued (`add_tool_result` never blocks the caller). Row: `id`, `conversation_id`,
  `turn_id`, `step_id`, `call_ord`, `tool`, `target`, `chars`, `cut`, `content`,
  `created_at`.
- **Offload.** At a node boundary, when the gauge count exceeds
  `(window - reserve) * (1 - 0.20)`, `run_node` picks units (a tool call stays with its
  result) by the default order: duplicate tool results, results of verified steps, recalled
  chunks not referenced since admit, old history. A unit leaves only if
  `offload_decision` passes: ref readable (`ref_readable`, a bounded wait on the queued
  write), complete unit, not protected, not the newest unit, open items carried, saving at
  least `MIN_SAVING`. The unit is replaced by its placeholder; the digest (the step result)
  and the open items stay.
- **Re-stretch.** The model calls `recall_memory` with `expand=<ref>` (handled in
  `_expand_tool_result`), or a trigger fires inside `run_node`; the original bytes return.
  Four named failure cases (`pruned`, `reingestable`, `forgotten`, `error`) are shown,
  never an empty reply.
- **Model edits.** `recall_memory` also takes `set_aside=[block_id...]` with a reason.
  Outside a node it returns `case: "not_in_a_node"` (`tool_bridge.py`). The harness shrink
  works with a model that never edits.
- **Gauge line.** Tool results carry a one-line gauge (`_gauge_line`: used / window,
  count set aside).
- **The band in the chat footer (2026-11-23).** The pill draws the view as a rubber band hung
  on the model switcher. `run_node` reports the view's size through `NodeContext.on_gauge`
  (`_band`): once before a shrink (stretched past the limit) and once at every model call.
  `kernel/der/node.py:_live_band` multiplies it by the gauge's learned ratio, so the numbers
  are the server's tokens; `kernel/context.py:note_context_view` keeps one reading per live
  node (removed in the node's `finally`) and `_emit_context_usage` adds `_context_band` to
  `context:usage`: `now_tokens`, `now_window`, `limit_tokens` (where CLM sets results aside,
  0 with the hooks off), `peak_tokens`, `aside`, `aside_tokens`, `views`. While nodes run it is
  the fullest view against its own model's window; at rest it is the last call. The older keys
  keep their meaning (`used_tokens` = the turn's largest call). Band length is the square root
  of the share, because real views live in the first tenth of a 128k window. It moves in both
  modes; only `IRIS_CLM_OFFLOAD=1` gives it a limit post and a set-aside count. Guard:
  `test_context_band_contract.py`, `__tests__/components/ContextPill.test.tsx`.
- **Pins with provenance.** `write_pin` creates a `PinStore` pin of type `model_summary`
  with tags `model_summary`, `author:model`, `clm`, `conv:<id>`, then links it with
  `derives_from` to each source ref on the `memory_events` lane. A pin never replaces its
  sources and never renders in a system block.
- **Dead-end ledger and open items.** `_clm_dead_ends` reads `dead_ends_for(conn,
  "<session>:<turn>")` (`backend/memory/memory_events.py`); `_ledger_section` renders them
  as a protected block. A repeated dead-end action triggers a re-stretch.
- **DCP removal (CLM-9).** `backend/agent/dcp.py` is deleted. Its job (dedup, error purge)
  is the reversible default order above. `git grep` finds no `dcp.py` module.

### 1.4 Events and where they surface

| Event | Emitted from | Surfaces |
|---|---|---|
| `OFFLOADED` | `node_executor.py:run_node` via `ctx.on_clm_event` | `memory_events` (lane); `memory/surface_queries.py` maps it to "set a thought aside" |
| `RESTRETCHED` | `run_node`, and `tool_bridge.py:_expand_tool_result` on a successful expand | same; "brought a thought back" |
| `PREMATURE_EVICTION` | `run_node`, when a ref returns within a few calls of its offload | same; "let a thought go too early". Count per block kind = the signal that the order or margin is wrong |

The sink is `_clm_node_hooks.on_clm_event`, which calls `_emit_event(kernel, label,
payload)` (`kernel/base.py`). The labels are already in the closed alphabet
(`memory/event_alphabet.py`); no new label was added.

### 1.5 Flags

| Flag | Read at | Default | Meaning |
|---|---|---|---|
| `IRIS_CLM_OFFLOAD=1` | `kernel/der/node.py:_clm_offload_on` | off when unset | Passes the CLM hooks into `NodeContext`. Unset: today's node |
| `IRIS_CLM_BASELINE=1` | `inference/clm_baseline.py` (`ENV`) | off | One JSON line per model call and per direct-context assembly in `logs/clm_baseline.jsonl`, written on `lane("clm_baseline")` |
| `IRIS_CLM_DUMP_DIR=<dir>` | `clm_baseline.py` | unset | With baseline on, also dumps message lists to that directory |

Check the live state in `specs/clm-memory/tasks.md` before relying on a default; the gate
results are written there with date and measurement.

### 1.6 Failure and fallback

- Ref unresolved at assembly: the block renders, marked unresolved, and is counted.
- Gate wait expires or ref unreadable: the block stays. Nothing is dropped on a timeout.
- View raises: the call site falls back to the old list builder, logs, and increments
  `view_fallback` (`context_view.py:count_view_fallback`, `view_fallback_count`). Alarm; expected 0.
- Invalid model edit (unknown id, protected block): the tool returns the reason and valid ids.

### 1.7 Guards

`backend/tests/contract/`: `test_view_parity_contract.py`, `test_view_parity_node_contract.py`
(same inputs, same bytes with no edit), `test_view_offload_gate_contract.py`,
`test_view_refs_contract.py`, `test_context_gauge_contract.py`,
`test_router_gauge_wiring_contract.py`, `test_clm_record_expand_contract.py`,
`test_clm_pin_provenance_contract.py`, `test_view_agent_protocol_contract.py`.
`backend/tests/behavioral/`: `test_clm_offload_node_behavior.py`,
`test_clm_zones_ledger_behavior.py`. `backend/tests/unit/test_view_scaler_injection.py`.

---

## 2. Measurement

CLM's baseline, view parity and offload results are in
[`specs/clm-memory/tasks.md`](../../specs/clm-memory/tasks.md) (Waves 0-6, TG-0 .. TG-6).
The Workbench's A/B results are in [`WORKBENCH.md`](./WORKBENCH.md#3-measured-results).

## 3. Status (2026-11-22) - the spec is not finished

- **Built and guarded:** Waves 0-6 code (view, gauge, offload gate, expand by reference with
  the named failure cases, the three events, pins with provenance, zones, the dead-end
  ledger, re-stretch, the landmark header, the counter report, the direct-path offload).
- **TG-2:** cloud arm off 23/28, on 24/28; small-model arm (LFM3-1.7B, 8,192 tokens) 5/14
  both arms, 9 `OFFLOADED` on the on arm, 0 `RESTRETCHED`. Offload changes no pass and
  breaks none. Not closed: blind drops per arm, the standards row per arm and an x06
  re-run are still to read. **`IRIS_CLM_OFFLOAD` stays off** until TG-2 closes.
- **Fixed on the way (2026-11-22):** the internet gate no longer refuses a memory question
  on the Oracle's `web_intent` guess (`kernel/turn.py:_web_off_reply`; x06 passes live);
  DER links in the shared link store are named `node:<session>:<step>`, written once
  (unique index `idx_pin_links_unique`) and bounded (`der_links.DER_LINKS_MAX_ROWS`).
- **Still to run:** the direct-path offload live, the Round 6 full gate and its small-model
  arm, TG-4, TG-5. The verdicts are kept in the tasks status block.


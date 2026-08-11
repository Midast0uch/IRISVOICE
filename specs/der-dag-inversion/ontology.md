# DER DAG-Inversion — Ontology

Canonical reference for the memory graph: node types, the two domain
registries, the link vocabulary (with the REQ-19 AC2b disambiguation), and the
recall filters. **Schema-versioned** — the CI check
(`scripts/validate_ontology_schema.py`) verifies this document against the live
code constants and FAILS loudly on drift (REQ-22 AC2). If this document and the
code disagree, the CI flag names the file:line; the doc is corrected, never the
code silently.

Spec: `specs/der-dag-inversion/requirements.md` REQ-18 / REQ-19 / REQ-20 /
REQ-21 / REQ-22. Grounding (file:line evidence for every symbol): see
`grounding.md` in this directory.

---

## 1. Node types (REQ-18 AC1)

Every DER node carries `node_type` from exactly this set. It describes where
the node sits in the execution tree.

| node_type | meaning | written at |
|---|---|---|
| `task` | the top-level task / plan node (the whole objective) | plan → queue build |
| `step` | an individual plan step | plan → queue build |
| `sub_loop` | a split child that resolves a specific blocker of its parent | `_split_step` |

A node's **ROLE** (REQ-18 AC1b) is a separate boolean marker —
`committed_decision` — True when the node surfaced ≥1 candidate branch and
chose one (REQ-5 AC2), making it a valid coupling endpoint. `{task, step,
sub_loop}` answers "where is it in the tree"; `committed_decision` answers
"did it decide".

## 2. Domain registries (REQ-18 AC2/AC3)

Two independent axes, **both registry-backed — free text is never a production
value**. A registry miss resolves to the registry's `general`/unknown bucket
and is LOGGED, never invented.

### 2a. `topic_domain` — what the node is ABOUT (recall axis)

Values come from the mycelium `DOMAIN_IDS` registry (`backend/memory/mycelium/
spaces.py`), 13 canonical topics. The write-time resolver is
`resolve_topic_domain(text)` (`backend/memory/mycelium/extractor.py`), which
reuses the same keyword patterns the coordinate extractor uses. Miss →
`general` + logged.

| topic_domain | notes |
|---|---|
| `ai` | ML / neural nets / LLMs / embeddings |
| `web` | web dev, frontend/backend, APIs |
| `data` | SQL, databases, ETL, analytics |
| `devops` | docker, k8s, CI/CD, deployment |
| `mobile` | iOS, Android, React Native |
| `systems` | C++, Rust, kernels, low-level |
| `security` | security, pentest, crypto |
| `finance` | trading, stocks, risk models |
| `science` | physics, chemistry, biology, simulation |
| `design` | UI/UX, graphics, product design |
| `hardware` | embedded, IoT, circuits |
| `gaming` | game dev, engines, assets |
| `general` | registry miss / unknown bucket |

### 2b. `execution_domain` — HOW the node runs (physics axis)

One of three values from the active winding (`backend/agent/coupled_registry.py`
`domain_windings`; resolved in `AgentKernel._der_execution_domain`):

| execution_domain | winding |
|---|---|
| `voice` | turn entered via voice (`from_voice=True`) |
| `research` | task_class ∈ {research, explore, investigate} |
| `der` | default DER winding |

## 3. Link vocabulary (REQ-19 AC2b — the disambiguation)

DER relationships land in the **shared mycelium link store** (`mycelium_pin_links`
via `PinStore.link`), extended from the pre-existing vocabulary. One store, no
second edge store (REQ-19 AC4).

### 3a. The vocabulary (10 predicates, exactly)

| predicate | meaning | who writes it |
|---|---|---|
| `documents` | source documents a target (pre-existing) | pin/landmark system |
| `references` | source references target (pre-existing) | pin/landmark system |
| `implements` | source implements target (pre-existing) | pin/landmark system |
| `contains` | source contains target (pre-existing, content containment) | pin/landmark system |
| `depends_on` | source depends on target (pre-existing) | DER: step → prerequisite step |
| `related_to` | semantic similarity discovered by scoring (pre-existing) | mycelium scorer |
| `derives_from` | source node is a direct continuation/spawn of target | DER: graft/recovery child → frozen parent |
| `part_of` | source is structurally part of target | DER: sub_loop → parent step; step → task |
| `relevant_to` | source was surfaced as a candidate to a decision (REQ-5 AC1) | DER: node → surfaced branch candidate |
| `failed_like` | source failed the same way as target (same failure class) | DER: failed node → prior failed node |

### 3b. The AC2b hard rules (write-side, enforced by `PinStore.link`)

1. **`part_of` vs `contains` — ONE canonical direction.** DER writes `part_of`
   (child → parent) ONLY. `contains` is the inverse, derived at query time,
   never written by DER. A DER containment relationship is always written
   source=child, target=parent, predicate=`part_of`.
2. **`relevant_to` vs `related_to` — provenance vs similarity.** `relevant_to`
   is written by DER only when a branch was actually SURFACED to a decision
   (REQ-5 AC1) — it is provenance, not affinity. `related_to` is written by
   the scorer from measured similarity. The two are never interchangeable.
3. **`derives_from` is forward-only (REQ-24).** A recovery/graft child is a NEW
   node with an edge FROM the frozen node (`derives_from`), never a
   modification of the frozen node. No node ever points `derives_from` to a
   node it predates.
4. **`failed_like` carries the failure class.** The class comes from
   `classify_failure` (`backend/agent/der_execution_ledger.py`). A node links
   `failed_like` only to prior failures sharing the SAME class — the AVOID
   recall walk must land on nodes that failed the same way.
5. **Out-of-vocabulary predicates are rejected loudly.** `PinStore.link`
   accepts only the 10 predicates above; anything else is logged and dropped
   (returns 0 rows), never written. `mycelium_pin_links.relationship` is a
   free column in the schema — the vocabulary is enforced at the write
   boundary, which is why the CI check pins the constant.

## 4. Recall filters (REQ-20)

Recall paths (mid-loop episodic hint, AVOID, proven-path, chain recall) accept
optional filters keyed on the ontology:

- `node_type` ∈ {task, step, sub_loop}
- `topic_domain` ∈ §2a registry
- `execution_domain` ∈ {voice, der, research}
- `relationship` ∈ §3a vocabulary

**Zero-hit widen order (REQ-20 AC2):** on an empty result, the filter widens
in strict order — drop `relationship` → drop `node_type` → drop domain axes —
and the WINNING scope (the widest filter that returned results, or "fully
widened, zero results") is LOGGED. The winning scope is part of the recall
response so a caller can see how far it had to widen. Conversation/session are
ranking inputs, never hard filters (cross-conversation recall, REQ-20 AC1b).

## 5. Per-domain physics aggregation (REQ-21)

Read-only, off the hot path. Aggregates over `caducean_trajectories` rows
grouped by `execution_domain` (and `topic_domain`) per session:

| metric | definition |
|---|---|
| `avg_u` | mean \|u\| over the session's rows in that domain |
| `oscillation_rate` | fraction of consecutive-row pairs whose u sign flips |
| `convergence_rate` | fraction of rows with \|u\| below the U_CONVERGED band |
| `split_count` | rows whose node_type = sub_loop (a split child executed) |
| `collapse_count` | sub_loop rows whose final \|u\| < U_CONVERGED (the child folded back) |
| `n` | row count |

Consumed by the outer loop (REQ-16) and narration measurement (REQ-15). Never
written by the app path — aggregation is a pure read.

## 6. Schema version

| element | live source of truth |
|---|---|
| node types | `NodeRecord.node_type` (der_loop.py) + this §1 |
| topic registry | `DOMAIN_IDS` (spaces.py) + this §2a |
| execution registry | `_der_execution_domain` (agent_kernel.py) + this §2b |
| link vocabulary | `LINK_VOCABULARY` (pin_store.py) + this §3a |
| recall filters | filter helper (§4) + this §4 |
| chain row typing | memory_chain columns `node_type`/`topic_domain`/`execution_domain` (iris_ffi.py) + this §1/§2 |

The CI check (`scripts/validate_ontology_schema.py`) compares every row of this
table against the live code and fails loudly on any drift (REQ-22 AC2).

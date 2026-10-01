# Event Taxonomy v1 - the alphabet of IRIS memory (for the Oracle, Wormhole/Aperture/NodeChains, CLM)

Status: PROPOSAL FOR OWNER REVIEW, 2026-09-30 (session 64237209). The alphabet (section 3) is the
one irreversible part: review it before anything is built on it. Supersedes the coding-only list
of spec `research-memory-chain-browser` D9 (BUG/ATTEMPT/DEAD_END/FIX/VERIFIED_FIX/LESSON become
labels of the `problem` family). Read with `docs/architecture/FAULTLINE.md`,
`specs/wormhole-aperture/requirements.md` (REQ-11, REQ-17-25, REQ-46 AC7 and its 7 open
questions) and `docs/Design/CLM_MYCELIUM_DESIGN_BRIEF.md`.

## 1. Why this has to be right now

The wormhole spec states the rule (REQ-46 AC7): **the dimensions are an alphabet; node chains are
sentences written in it.** New words (labels, tools, bars) are data edits and safe. Widening the
alphabet invalidates every stored chain sequence hash, defeats chain dedup, and can crystallize a
chain from a partial run - silently. Three systems read the same events:

| Reader | Needs |
|---|---|
| Oracle | small closed menus; a reference label + its source for calibration |
| Wormhole / Aperture / NodeChains | exact addresses (state hash, cause lattice, outcome lattice); the outcome that gates chain genesis; attribution of a delivered recall to what happened next (Beta counts) |
| CLM training | ordered trajectories: state, action, cost, outcome, the EVIDENCE behind the outcome, and the context-management actions (offload, re-expand, admit, evict) |

The aperture can only deliver what was curated well. If an event's evidence is mislabeled, a lucky
run becomes a chain, a wrong landmark gets promoted, and the Beta posteriors learn noise.

## 2. The pattern (FAULTLINE, generalized)

- Layer 1 - ALPHABET: closed lattices, hardcoded, pinned by tests that assert their size.
- Layer 2 - WORDS: an open label registry; a label = a named bundle of alphabet values + prose.
  New label = data edit. Consumers read the alphabet, so a new label works everywhere at once.
- Layer 3 - UNCLASSIFIED: anything no rule/Oracle types confidently is stored raw, counted, and is a
  promotion candidate. The vocabulary grows from evidence; the alphabet never does.

## 3. The alphabet (closed) - REVIEW THIS

An event's address is a composition of small closed lattices. Three already exist in code and are
REUSED, never re-modelled:

| Lattice | Values | Status |
|---|---|---|
| cause (FAULTLINE, `tool_errors.FailureDimensions`) | retryable {yes,no,maybe} x blame {self,world,query} x info_state {blocked,missing,unknown} = 27 | EXISTS - for set-back events |
| outcome (`tool_envelope.ExpectationDimensions`) | alignment {matched,mismatched,unclear} x identity {new,repeat,unknown} x yield_state {full,partial,empty} = 27 | EXISTS - for any event with a result |
| trigger (`nodes/outcome.Reason`) | closed enum (none, empty, too_short, challenge, transport_error, no_candidates, wall, robots_refused, permission_denied, ...) | EXISTS - why a node failed / pivoted |

NEW closed lattices proposed:

| Lattice | Values | Why closed, why these |
|---|---|---|
| family (9) | intent, control, problem, knowledge, feedback, delivery, memory, safety, environment | one problem-solving arc each, present in every domain (section 4); the Oracle's first menu |
| valence (3) | advances, sets_back, neutral | did this move the GOAL (outcome lattice says whether the TOOL met its expectation - a matched search can still set the goal back) |
| actor (5) | user, agent, tool, world, subagent | who caused it; the reward function treats user and world signals differently from the agent's own |
| evidence (8) | none, claim, verifier, test, completion, user, recurrence, corroboration | THE curation dimension: only test / completion / user / recurrence / corroboration are OUTSIDE evidence; claim and verifier are inside; this gates chain genesis, landmark promotion and RL reward |

Open (not alphabet, not hashed): exec_domain x topic_domain (the existing ontology registry),
labels, tools, bars.

## 4. Families and starting labels (Layer 2 - words, open)

| Family | Labels v1 | Across domains |
|---|---|---|
| intent | GOAL_SET, GOAL_REFINED, CLARIFY_ASKED, CLARIFY_ANSWERED, PREFERENCE_STATED, GOAL_ABANDONED | "flights under $300" / "make it Friday" / "always metric" |
| control | PLAN_MADE, REPLAN, PIVOT (NodeChains REQ-21 PivotEvent), SPLIT, DELEGATED, ESCALATED, HALTED, BUDGET_HIT | escalation timed out -> PIVOT; TOPO_VIOLATION -> HALTED |
| problem | OBSTACLE (coding label BUG), ATTEMPT, DEAD_END, RESOLUTION (FIX), VERIFIED_RESOLUTION (VERIFIED_FIX) | failing test, walled page, missing file, rejected form, wrong selector |
| knowledge | OBSERVED, CLAIM_CORROBORATED, CLAIM_UPDATED, CLAIM_CONTRADICTED, SOURCE_UNRELIABLE, BELIEF_STALE | research cross-check; screen/page observation |
| feedback | CONFIRMATION, CORRECTION, APPROVAL, DENIAL, NO_RESPONSE | "that's wrong, it's 2019" -> CORRECTION (strongest negative signal) |
| delivery | ANSWER_GIVEN, ARTIFACT_PRODUCED, NARRATED, CARD_SHOWN | what reached the user - the CLAUDE.md contract "spoken subset of visible" is checkable here |
| memory | RECALL_DELIVERED, RECALL_USED, RECALL_HELPED, RECALL_MISLED, RECALL_MISSED, APERTURE_DROPPED, OFFLOADED, RESTRETCHED, PREMATURE_EVICTION, LESSON, LANDMARK_PROMOTED, LANDMARK_STALE, LANDMARK_DEMOTED, CHAIN_CREATED, CHAIN_VARIANT | the Aperture's `aperture_decision` outcomes and CLM's offload/re-stretch, as events |
| safety | UNSAFE_REFUSED, ESCALATED_UNSURE, INJECTION_SUSPECTED, PERMISSION_DENIED | click-safety verdicts (Wave W2) |
| environment | DEPENDENCY_CHANGED, RESOURCE_LIMIT, WORLD_CHANGED | a landmark's file edited; rate limit; page changed |

Links on every event (the hyperedge view): episode, case (problem arc), claim (knowledge arc), goal
(intent arc), chain + node_index, recall_trace_id (attribution, Wormhole REQ-17), parent_event.

## 5. Proposed answers to the wormhole spec's 7 open questions (REQ-46 AC7 notes)

1. **outcome_type mapping.** `success` = envelope status success AND alignment=matched AND
   yield_state=full AND the episode holds OUTSIDE evidence (evidence in {test, completion, user,
   recurrence, corroboration}). `partial` = matched with yield partial, OR success without outside
   evidence. `failure` = mismatched or a sets_back terminal. Genesis (REQ-19/20) only on `success`.
   This is where curation decides chain quality: a run the verifier liked but nobody outside
   confirmed is `partial` and never becomes a chain.
2. **Lattices combine?** No - two separate keys. A hyperedge is scoped by the lattice of its target
   event (failures by cause, findings by outcome). Join them only if telemetry (REQ-46 AC6) shows a
   measured gain.
3. **Sequence hash input.** The ordered list of `(mediator, outcome key)` for the chain's VERIFIED
   nodes - tool names are Layer-2 words (adding a tool makes new sentences, breaks none); the
   outcome key is alphabet. Not text, not args.
4. **Recovery nodes.** A recovery that worked IS a chain node (it is what worked). `recovery_of`
   stays provenance-only, outside the hash. Failed attempts are not nodes: they are DEAD_END /
   PIVOT events attached to the fork point - the material a variant (REQ-22) is promoted from.
5. **hit / partial.** `hit` is not an outcome corner: it is the memory event RECALL_USED (delivered
   and used, outcome not yet evidenced). `partial` occupies matched|*|partial.
6. **Tool-less nodes.** Synthesis / consolidation nodes get a registered mediator word
   (`synthesis`) with its own bar, so they take part (they are COMPRESS steps in Sigma too). Truly
   unknown nodes are excluded from the hash and counted.
7. **Registry and attribution.** The expectation registry does NOT feed attribution. Attribution is
   delivery (recall_trace_id) + use evidence only.

## 6. Who labels (and how the Oracle learns)

- Rules label most events at existing chokepoints (DER finalize, verifier, envelope, click gate,
  ask_user/permission, research cross-check, dependency edits, recall/aperture paths). Rule labels
  carry `label_source=rule` and are exact calibration rows.
- The Oracle, SHADOW first: `event_family` (9 options), `event_type:<family>`, and `user_feedback`
  (confirmation | correction | preference | refinement | new_request | none) on every user message
  - the events rules cannot type. The Brain labels a sample as reference until the bar.
- Layer 3 collects the rest; repeated unknowns are proposed as labels (data edit after review).

## 7. The record

`memory_events` (append-only, canonical; the chain keeps a compact reference row per event):
event_id, ts, schema_version, episode_id, step_index, family, label, valence, actor, evidence,
cause key, outcome key, trigger, exec_domain, topic_domain, label_source, label_confidence,
sigma_from, sigma_to, hash_signature + hash_scheme (Wormhole REQ-1, computed at write time),
action_signature, cost (ms, tokens_in, tokens_out, tool_calls, context_tokens), links, bounded
payload (references, never content - S12). Rewards are NOT stored: a versioned reward function
derives them (success-gated, then cost among successes), so a policy change never rewrites history.

## 8. Curation quality - what tells us the aperture will work

Measured before Wormhole/Aperture/NodeChains build on it: label agreement per family (rule vs
Oracle vs Brain), unclassified rate, share of episodes with outside evidence, chains that would
crystallize from `partial` under the old mapping (should be 0), landmark false-promotion rate,
recall attribution coverage (delivered recalls with a known use/outcome).

## 9. Build order

1. Alphabet as code (closed enums + size-pinning tests) + `memory_events` + registry + Layer 3;
   Wave E labels migrated into the `problem` family.
2. Rule emitters per family at the existing chokepoints.
3. Oracle shadow consumers (`event_family`, `event_type:*`, `user_feedback`).
4. Trajectory exporter + curation report (section 8).
Then the joint program in `.mcm/GOALS.md` 7a: Wormhole (Stage A) + Aperture (B) + NodeChains (C) +
CLM live view, which all read this stream.

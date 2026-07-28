# Execution Phases — read this before opening any spec

Specs are cut by **execution order**. Each phase is self-contained: its `requirements.md` /
`design.md` / `tasks.md` carry everything needed to execute it. There are no "blocked on another
spec" references and nothing else to consult.

**Execute in order. Do not start a phase until the previous one's final wave is green.**

| Phase | Spec | Blocked on | Unblocks |
|---|---|---|---|
| **1** | [`phase-1-foundation/`](phase-1-foundation/) | — | everything |
| **2** | [`phase-2-instrument/`](phase-2-instrument/) | 1 | validation of 3–6 |
| **3** | [`phase-3-local-loader/`](phase-3-local-loader/) | 1 | 4, 5 |
| **4** | [`phase-4-encoder/`](phase-4-encoder/) | 1, 3 | 5, 6 |
| **5** | [`phase-5-switcher/`](phase-5-switcher/) | 1, 3, 4 | — |
| **6** | [`phase-6-der-integrity/`](phase-6-der-integrity/) | 2, 4 | — |

**Phases 2 and 3 can run in parallel** once Phase 1 is green — different files, no shared state.

---

## What each phase covers

**1 — Foundation.** DER's budget derived from the real context window (fractional per-class
ceilings); context-window precedence (override → authoritative → table → default); measured-cost
work-unit debit; resolver fallback ordering; local providers declarative rather than a side effect
of loading; namespaced ids + `purpose`; one process-wide registry; one provider collection keyed by
id with atomic endpoint+credential writes; flat-config migration; routing mode frozen.

**2 — The instrument.** Agent-driven narration (text + TTS); task cards driven by real `TOOL_CALL`
records; plan text immutable while live progress rotates beside the tool name; phase transitions
emitted from long tool calls; sub-loop steps appended to the same card; learning signals visible;
**the frontend test suite made to run at all**.

**3 — Local model loader.** Config derivation from parsed metadata + hardware; GPU-only degradation
ladder (ctx → batch) scoped to `purpose == "chat"`; VRAM estimation including KV cache; per-model
config cache; symlink-aware folder scan; measured-throughput feedback loop.

**4 — Encoder.** LFM2.5 Embedding-350M replacing BGE-M3 (CPU); chunk + max-pool for the 21% of PiNs
over 512 tokens; background re-index with dual-read and cross-space refusal; Encoder-350M for
semantic step verification and task classification; ColBERT deferred behind a measured quality gate.

**5 — Switcher UI.** Send pill removed (its guards moved into the send path first); model switcher
in the chat input row; ContextPill design preserved, showing the real window and live on **every**
response.

**6 — DER integrity + self-tuning.** Every executed action commits a labeled outcome; the outer
loop's compound acceptance gate repaired from **1 live guard to 3**; per-domain gating; the
"never split" reward-hack rejected by the gate rather than absent from the candidate list; depth
check on VERIFIED-but-shallow steps.

---

## For the executing agent — read this section

### The recurring defect in this codebase

**An authoritative value exists and a guess outranks it**, or **a value is computed and discarded.**
Nearly every requirement across all six phases is one of those two shapes. When you find something
that looks broken, check first whether the correct code already exists and is simply ordered wrong,
unused, or unreachable. Several times it did:

- `resolve_context_window` had the authoritative branch **below** the substring guess.
- `record_tps` measured throughput and only warned.
- `verified_count` was correctly derived from the ledger and then replaced by a literal `1.0`.
- The keyring was already keyed by provider id; only the config could not hold two providers.

**Prefer reordering, wiring, or consuming an existing value over writing a new one.**

### Failures that produce no error

These are the ones that survived for months. Each phase's harness has an assertion aimed at them:

| Failure | Phase | Why it is silent |
|---|---|---|
| Budget exceeding the context window | 1 | Steps keep issuing while every call truncates |
| A credential written to a config file | 1 | Nothing reads it back that would notice |
| One provider's URL paired with another's key | 1 | The request succeeds — at the wrong vendor |
| Plan text overwritten by live progress | 2 | The card still renders, just not the plan |
| A swallowed speech exception | 2 | 100% failure presents as intermittence |
| CPU model counted against VRAM | 3 | Chat context is quietly smaller forever |
| Cross-space vector comparison | 4 | Both backends are 1024-dim — returns a plausible number |
| A truncated document | 4 | The vector is valid; the document is unfindable |
| Send guards deleted with the button | 5 | `Enter` sends mid-response, no error |
| A guard reporting pass with no input | 6 | The gate looks compound and gates on one signal |

### Three fixes are already live and were **untested** at the time of writing

Landed in `01e6625b` and `a7c6d853`, all with silent failure modes. Their pinning tests are the
first tasks of their phases — **do these before new work**:

| Fix | Pinned by |
|---|---|
| DER budget from the real window (fractional ceilings) | Phase 1 **T1.3** |
| Plan immutability; resolved `toolName`; `speak()` emitting | Phase 2 **T1.2 / T1.3 / T1.4** |

### Test rules that apply to every phase

- **Never modify a test to make it pass.** A test's INPUTS are part of it — reducing a parametrize
  matrix, loosening a tolerance, or stubbing a dependency that could fail all count.
- Several phases say "dropping a case from the parametrize list is a test modification." Those
  matrices are load-bearing: Phase 6's two dead guards survived precisely because the compound gate
  was only ever tested end-to-end.
- **When a test and a spec genuinely conflict, report it — do not reconcile it.** Phase 2 T4.1 is
  the worked example: two tests assert narration wording that a requirement explicitly removed. The
  tests move, the implementation does not.
- Assert the **effect**, never the computation. Phase 3 T4.2: a test that checks `record_tps` logs a
  warning passes without the feedback loop closing.

### Known pre-existing failures

Not caused by this work. Do not "fix" them by editing assertions:

| Failure | Resolved by |
|---|---|
| `test_narration_contract`, `test_narration_flow` — assert superseded wording | Phase 2 T4.1 |
| `test_kernel_separation_behavior` — asserts sync `tts.speak`; dispatch is now threaded | Phase 2 T4.2 |
| `test_crawler_task_progress` ×2 — stale stub signature, `InternetGate` in-fixture | Phase 2 T4.3 |
| `npx jest` runs **0 tests** (7/7 suites fail to parse) | Phase 2 T1.1 |
| `pytest_httpx` missing → `test_exa_provider.py` collection error | not scheduled; ignore that file |

### Environment notes

- `npx tsc --noEmit` reports errors in vendored `llama.cpp-prismml-src/` and `data/cards.ts`. Filter
  to `components/`, `hooks/`, `app/` for this project's gate.
- Never `pip install` or `npm install` without checking first.
- `git push` is currently blocked by a machine-wide TLS failure. Commit locally; do not attempt
  workarounds.

### A NO-CHANGE claim expires

Each phase's Ripple-Effect Map marks areas **NO CHANGE (verified)** with file:line proof. That
verification is valid **against the change that made it**, not forever. The worked example:
`ModelInferenceSection.tsx:80` maps providers unfiltered — genuinely NO-CHANGE for Phases 1 and 3,
and wrong the moment Phase 4 registers a non-chat provider. Phase 4 T2.2 owns the fix and must land
in the same change as registration.

When a later phase contradicts an earlier NO-CHANGE, the later phase wins and says so explicitly.

### Open Questions are decisions, not blockers

Each phase carries a short OQ list. They are things that must be decided **from data during
execution** rather than guessed up front — chunk size from the probe set, a confidence floor from
rollout disagreement, a depth threshold from post-Phase-4 labels. Record the answer in the spec when
you resolve it.

# QA-Emb Integration — Discussion Document

**Status:** DISCUSSION INPUT — **not locked, not scheduled, not a stage.**
**Does NOT amend `REQ-1`–`REQ-47`.** Every existing requirement stands exactly as written.
**UPDATE 2026-10-05:** the Oracle (`docs/architecture/oracle.md` §0) now answers ONE yes/no
question per run with per-consumer calibration and two-key enforcement (`decision_engine.decides()`).
QA-Emb questions must be evaluated AS Oracle consumers (shadow rows, the hardened bar), not as a
second model. The `der-ground-truth` / GT-G4 references below are superseded (requirements U1).
**Purpose:** decide *whether* and *where* QA-Emb (question-answering embeddings) belongs in
WORMHOLE / APERTURE, and how it would coexist with the mechanisms already specified here.
**Parent spec:** `specs/wormhole-aperture/requirements.md` · `design.md` · `tasks.md`
**Paper:** Benara, Singh, Morris, Antonello, Stoica, Huth, Gao — *"Crafting Interpretable
Embeddings by Asking LLMs Questions"* — <https://arxiv.org/abs/2405.16714> (v1, 26 May 2024)
· code: <https://github.com/csinva/interpretable-embeddings>

> **How to read this.** Sections 1–2 are fact. Sections 3–5 are the actual discussion and
> need your call. Section 6 is a sketch of what the spec *would* gain if adopted — it is
> deliberately not written as REQ text, because writing locked EARS requirements before the
> discussion is exactly the "phantom requirements" failure the spec workflow warns about.

---

## 1. The paper, in enough detail to reimplement

QA-Emb builds an embedding by **asking questions** instead of learning weights.

### 1.1 Definition

Given input text `x` and a set of yes/no questions `Q`:

```
v_Q(x) ∈ {0,1}^d      # dimension j = the answer to question Q_j about x
                      # yes → 1, no → 0
```

Each dimension is a **human-readable question answer**. That is the whole idea. The paper's
motivation is that LLM embeddings are opaque, which is intolerable in domains where a result
must be justified — the same complaint that applies to a coordinate hash.

### 1.2 Training = question selection, not weight fitting

The objective (their Eq. 1) has a **discrete outer loop** and a **continuous inner loop**:

```
Q = argmin over Q ⊆ Q_yes/no  [  min over θ ∈ ℝ^d  Σ_i ‖Y⁽ⁱ⁾ − θᵀ v_Q(X⁽ⁱ⁾)‖ + λ‖θ‖₂  ]
```

- **Outer:** search over *sets of questions* — the hard part, and the actual "training".
- **Inner:** ordinary ridge regression. `θ` is the interpretable per-question weight.
- Their practical substitute for the intractable outer search: **generate a large candidate
  pool, then do feature selection.** Not greedy forward selection.

### 1.3 The pipeline, with their numbers

| Step | What they did |
|---|---|
| Generate candidates | GPT-4 (`gpt-4-0125-preview`), **6 prompts** → **674** questions |
| Select | `MultiTaskElasticNet`, **20 log-spaced λ from 10⁻³ to 1** |
| Fit | Ridge regression, λ from 12 log-spaced values in [10, 10⁴] |
| Result | **29 questions** → mean test correlation **0.122**, beating Eng1000's **0.118** at **985 features** |
| Importance | mean absolute coefficient, normalized so the top question = 1.000 |

**The headline result is 29 questions beating 985 features.** A tiny, human-readable question
set beat a large opaque feature space.

### 1.4 Where questions come from

Prompt template, one line:

```
Generate a bulleted list of questions with yes/no answers that is relevant for {{task description}}.
```

Customizable with dataset examples to get data-relevant questions. Two cheaper alternatives to
full elastic-net selection:

- **LLM-based filtering** — hand the model the question list and ask for the subset relevant to
  a task description. This is the **zero-shot adaptation** path (§1.7).
- **Sequential generation** — generate new questions from the high-error examples, described as
  gradient-boosting-like. The paper cites this as an *extension*, not their reported procedure.

### 1.5 How answers become numbers

This is the paper's **least specified** part, and worth knowing before we copy it.

- Stated: black-box LLM access only; one generated token per question; **KV-cache reuse**
  across questions because they share the input prefix; embedding is binary.
- The standard answering prompt actually asks for *"Answer with yes or no, then give an
  explanation"* — so they **parse the leading yes/no from generated text**, they do not read a
  probability. (No log-probability formulation appears anywhere.)
- Answers are **averaged across Mistral-7B-Instruct-v0.2 + LLaMA-3-8B-Instruct × 2 prompts**
  for a small boost. Averaging yields non-binary values, which sits uneasily with the stated
  `{0,1}^d` — the paper does not reconcile this.
- **The distilled model resolves it:** its feature value is **predicted P(yes)** — and that
  probabilistic variant *outperforms* the binarized one (**0.113 vs 0.111**, original 0.114).

**Takeaway for us:** store the **calibrated probability**, not the bit.

### 1.6 Distillation — one pass instead of d calls

Their §5.1 solves "d LLM calls per embedding":

- **`roberta-base` + 674 classification heads**, one feedforward pass for all questions.
- Trained on LLaMA-3-8B few-shot answers over 10-grams: **123,203 train / 30,801 val /
  4,594 test**. AdamW, **lr 5×10⁻⁵**.
- **88.5% yes/no agreement** on test; downstream quality **0.111 (binary) / 0.113
  (probabilistic) vs 0.114 original** — i.e. per-answer error is real but **errors aggregate
  out** across many questions and n-grams.

This is the single most important section for us, because **it is the architecture we already
have.** A small encoder with N typed heads, scored in one forward pass, is exactly the GLiNER
ONNX decision backend, and `Noul` (a calibrated P(statement true)) is exactly a QA-Emb feature.

### 1.7 The two other applications

**Information retrieval (MSMarco).** 4,000 queries / 5,210 documents, **2,000** GPT-4 questions
rewritten by regex to apply to documents. One **learned scalar per question** (sign + magnitude)
multiplies its binary output; loss = negative cosine to ground-truth docs (×10) + cosine to the
rest (×1), Adam lr 10⁻⁴, 8 epochs.

| Method | MRR | Size |
|---|---:|---:|
| Bag of trigrams | 0.39 | 444,403 |
| **QA-Emb alone** | **0.45** | 2,000 |
| BM-25 | 0.77 | 27,677 |
| **BM-25 + QA-Emb** | **0.80** | 29,677 |

**Read this row carefully.** QA-Emb **alone loses badly** to keyword search. It only wins when
*added* to it. This is the constraint that should shape any adoption here.

**Zero-shot clustering.** 25 questions per dataset; then ask the LLM to select the subset
relevant to a task description — **100 dims → 25.75**, and clustering got **better**
(0.095 → 0.191). Fewer, better-targeted questions beat more questions.

### 1.8 Stated limitations

- `d` LLM calls per embedding is "often prohibitively expensive" (mitigated by KV-cache +
  single-token answers + distillation).
- **Faithfulness is a real failure mode.** On the D3 binary-classification collection their
  worst dataset was **near-chance (~50%)**: *"Is the input about math research?"* answered yes
  for chemistry examples too, because negatives carried numbers and notation. Surface-similar
  negatives break the question.
- Reproducing everything took ~**4 days on 64 AMD MI210 GPUs**.

---

## 2. Why this lands in *this* spec specifically

Three seams in `wormhole-aperture` are shaped exactly like the problem QA-Emb solves. This is
not a general "AI improvement" — it is three specific collisions.

### Seam 1 — `REQ-1`'s `hash_signature` is a semantics-free fingerprint

`REQ-1` defines the address as a quantized **4D Caducean confounder state** `(x, y, xi, u)` plus
`topic_domain` / `execution_domain`, and `AC3` explicitly forbids semantic comparison on it.
`REQ-16` exists because two genuinely different tasks can quantize to the same signature.

The spec already names the disease, in `REQ-6 AC5`:

> *"the confounder signature is lumping together things the world treats differently"*

That **is** the fingerprint problem. The current remedy is a tagging signal. QA-Emb would give
the collision a **cause** — not just "these two collide" but **which question separates them**.

### Seam 2 — node activation is keyword matching, and it is the thing starving the graph

`Decisions Locked 11b` is the load-bearing finding:

> node activation runs through `navigate_from_task` (`navigator.py:93`), whose entry matching is
> **KEYWORD-based** against **37 nodes spanning 3 of 7 coordinate spaces**. A live read-only
> probe returned **0 nodes** for an ordinary coding task. So the region-mediator guard rarely
> passes and **no edge is written** — `mycelium_edges` = 0 rows.

A keyword list matched against labels is a **hand-written question set with no selection
procedure and no measurement** — precisely the artifact QA-Emb replaces. And it is the gate
that `Stage A` is currently blocked on.

### Seam 3 — `REQ-46` is already "recall by CAUSE"

`REQ-46` makes the **FAULTLINE dimensions a retrieval axis** ("recall by CAUSE"), and `REQ-33`
feeds FAULTLINE outcomes into hyperedge posteriors. A failure-cause axis *is* a set of yes/no
questions — "did this fail on a timeout? a permission? a bad parameter?" Each is naturally a
calibrated `P(yes)`. This seam needs no invention; it needs the features formalized.

**Two secondary seams** worth noting but not leading with: `REQ-6 AC1` seeds coupling from
"confounder-signature overlap", which could instead be QA-Emb feature overlap weighted by
per-question importance (elastic-net gives those weights for free); and the `Tier-2` walk
(`REQ-3`) is weighted only by posterior and recency-resonance, so a semantic term could be
added to ranking without touching the hash.

---

## 3. Proposed insertion points

Each row states what changes and — more importantly — **what does not.**

### A. Collision diagnosis (`REQ-16` amendment) — *lowest risk, do first*

- **What changes:** on a `semantic_collision` (`REQ-16`), mint the QA-Emb vector for both
  colliding states and report the **discriminating questions** (largest `|P(yes)|` gap).
- **What does not change:** `REQ-1 AC3` stands untouched. The hash remains the address; the
  QA-Emb vector is a *diagnostic payload*, computed only on collision, never on the hot path.
- **Why first:** it costs nothing on the normal path, it converts an opaque flag into an
  actionable one, and it validates the question pool against real collisions before anything
  depends on it.

### B. Activation gate (replaces the keyword extraction behind `navigator.py:371`)

- **What changes:** score a QA-Emb question set against the live task; activate nodes whose
  feature vectors clear a threshold, instead of matching keywords to labels.
- **What does not change:** `CoordinateNavigator`'s walk, `record_path_outcome`, and the
  `mycelium_traversals` persistence all stay — this replaces only the **entry matching**.
- **Why this is the highest-value seam:** it attacks the starvation root cause in `DL 11b`.
- **Risk:** it is on the path that decides whether anything else works, so it must ship behind
  a gate (see §5), with the keyword path retained as the fallback.

### C. FAULTLINE axis as calibrated questions (`REQ-46` amendment)

- **What changes:** express the FAULTLINE retrieval axis as a question set whose `P(yes)`
  answers *are* the axis coordinates, rather than a fixed taxonomy.
- **What does not change:** `REQ-32` (failures become FAULTLINE labels) and `REQ-33`
  (outcomes feed hyperedge posteriors) both stand; the labels are unchanged, only their
  representation as a scored vector is new.
- **Note:** this is the seam with the most design freedom and the least existing constraint,
  so it is the one most likely to over-build. Recommend deferring it behind A and B.

### D. Seed coupling from feature overlap (`REQ-6 AC1` refinement)

- **What changes:** seed the Beta prior from weighted QA-Emb feature overlap rather than raw
  signature overlap.
- **What does not change:** the Beta prior formulation itself (`DL 5`) — no sigmoid, no
  crossover, no steepness constant. Only the *input* to the prior changes.
- **Guard:** `REQ-6 AC5`'s divergence signal must survive; it becomes more informative, not less.

### E. Tier-2 ranking term (`REQ-3` refinement)

- **What changes:** add a semantic term to the walk's ranking, bounded so posterior still
  dominates.
- **What does not change:** `REQ-4 AC5`'s `-log(posterior)` path cost, and `REQ-4 AC7`'s
  direction discipline.

---

## 4. Tensions that must be decided

These are the reasons this is a discussion document and not a spec amendment.

1. **QA-Emb cannot be the `Tier-1a` address.** `REQ-1 AC3` forbids semantic or threshold
   comparison on the hash, and a QA-Emb vector is *inherently* a similarity/threshold object.
   They must **coexist**: hash = O(1) exact address, QA-Emb = a second, semantic index.
   *Recommend: QA-Emb never appears on the `Tier-1a` path.*

2. **Hot-path cost vs `REQ-12`'s deadline.** One batched engine pass is cheap in absolute terms
   (the tool-choice battery measured **119ms p50** for 60 cases), but that is orders of
   magnitude above an exact-hash lookup. `REQ-3 AC2` already requires `Tier-2` off the
   generation path under deadline — QA-Emb inherits that discipline. It cannot be a
   per-node, per-hop cost.

3. **`Decisions Locked 12` blocks this too, for the same reason.** The spec refuses to begin
   scoring until `specs/der-ground-truth/` clears gate **GT-G4**, because *"a Beta-Bernoulli fed
   a corpus with no negative evidence produces posteriors that all converge to 1.0 and a graph
   that is confidently meaningless."* **That argument applies verbatim to question selection:**
   you cannot select questions against outcomes that are not recorded. QA-Emb must inherit the
   same block, not route around it.

4. **Question *selection* has no volume yet.** The paper needed **123k labelled examples**;
   `DL 13` records ~**200 DER runs in three months**. Selection over our own ledger is not
   viable now.
   *Recommend the exact shape of `DL 14` (hex bins):* the **pool** can be authored once as an
   offline artifact (the paper's step 1 is just an LLM generating candidates), the **scoring**
   can ship, and the **selection** ships behind a corpus gate. Fully specified, not deleted,
   not early.

5. **Engine contention.** The CPU-resident engine also serves `tool_choice`. Polling QA-Emb
   questions competes for the same session and lock. *Recommend: a stated budget and priority,
   with tool choice winning* — otherwise a recall improvement silently slows tool selection.

6. **Where does the question registry live?** `DL 2` says extend the mycelium tables, do not
   fork a store, and *"nothing here is a new subsystem"*. *Recommend: the feature vector lives
   on `mycelium_nodes` (additive column, like `hash_signature`), and the question set is a
   **versioned artifact*** — versioned the same way `REQ-10` versions the quantization scheme,
   so a question-set change is detectable rather than silent. No new table for the registry.

7. **The faithfulness failure mode applies to us concretely.** Their worst case was near-chance
   where negatives shared surface features. Ours: *"is this a search task?"* answers **yes** for
   both "search the web" and "search my files" — the same split `_GATHER_SIGNALS` vs
   `_ACTION_SIGNALS` exists to make. The paper's remedy is **measurement, not better wording**,
   which means a per-question accuracy report is mandatory, not optional.

8. **Interpretability is a bonus here, not the reason.** The paper's motivation is
   explainability; WORMHOLE's motivation is retrieval quality under a deadline. Adopting
   QA-Emb *for interpretability* would be over-building. Adopt it because it addresses
   Seams 1 and 2 — and take the explainability as a free side effect.

9. **Store `P(yes)`, not the bit.** Their probabilistic variant beat binarization
   (0.113 vs 0.111). Also note the paper never used log-probabilities — **we would**, because
   `Noul` already returns a calibrated probability, which is strictly better than parsing
   "yes" out of generated text.

10. **Direction discipline.** `REQ-4 AC7` scores a hyperedge only in the direction travelled.
    A feature vector is direction-free, so if features ever gate edges, that rule must be
    preserved explicitly rather than assumed.

---

## 5. Gating proposal

Mirrors `DL 14`, so it introduces no new governance concept:

| Stage | Ships when | Contents |
|---|---|---|
| **Q0** | Immediately, shadow only | Question pool authored offline as a versioned artifact; QA-Emb vectors minted for **collision diagnosis only** (insertion A); zero hot-path cost; nothing steered |
| **Q1** | `der-ground-truth` clears **GT-G4** | Vectors written to `mycelium_nodes`; per-question accuracy measured against recorded outcomes; no enforcement |
| **Q2** | Corpus gate (volume TBD with owner) | Question **selection** (elastic-net over our own ledger); the pool shrinks to the questions that earn their place |
| **Q3** | Q2 green + measured parity | Activation gate (insertion B) enforced, keyword path retained as fallback |

**Nothing in Q0–Q3 may weaken an existing requirement.** In particular `REQ-1 AC3`,
`REQ-4 AC5/AC7`, `REQ-6 AC5`, and `REQ-45` (scoring lives in Stage A, never in delivery) all
stand unchanged.

---

## 6. If adopted — the shape it would take

Sketch only. **Not applied to `requirements.md`.** Listed so the cost is visible before deciding.

- **REQ-48: QA-Emb question registry and versioning** — pool as a versioned artifact; the
  version recorded alongside `hash_scheme_version`; a set change is detectable.
- **REQ-49: QA-Emb feature minting** — vectors minted off the hot path under the `REQ-12`
  deadline, stored additively on `mycelium_nodes`, `P(yes)` not binarized.
- **REQ-50: Collision diagnosis** — `REQ-16` amendment reporting discriminating questions.
- **REQ-51: Activation by feature score** — replaces `navigator.py:371` keyword matching,
  behind the Q3 gate, keyword path as fallback.
- **REQ-52: Per-question measurement** — per-question accuracy + coverage against recorded
  outcomes, so a faithful question is distinguishable from a coin-flip one (the §1.8 failure).
- **REQ-53: FAULTLINE axis as calibrated questions** — `REQ-46` amendment, deferred.
- **Observability** — the polling act logs the question-set version, per-question answers, and
  the vector, joined to `recall_trace_id` (`REQ-17`) so a recall can be attributed to the
  features that caused it.

Tests would follow the spec's existing standard: contract pins on the vector/envelope shape,
behavioral drives asserting that a collision becomes diagnosable and that an activation
decision is reproducible, and a standing CDD harness replaying recorded trajectories. Per the
project's TEST RULE, the tests would be written against the requirement, not against whatever
the first implementation happens to do.

---

## 7. Open questions (need your call)

- **OQ-QA-1:** Is QA-Emb a **collision diagnostic only** (insertion A), or does it also become
  the **activation gate** (insertion B)? *Recommend: A first, B behind the Q3 gate.*
- **OQ-QA-2:** Is the question pool an **offline authored artifact** (generated once, versioned),
  or generated per session? *Recommend: offline — per-session generation puts an LLM on a hot
  path and makes the feature space non-stationary.*
- **OQ-QA-3:** Does the **FAULTLINE axis** become QA-Emb features (`REQ-46` amendment), or stay
  a fixed taxonomy? This is the largest design change on the table.
- **OQ-QA-4:** Does QA-Emb polling **share the tool-decision engine**, or get its own budget?
- **OQ-QA-5:** Does Q0 ship before `der-ground-truth` clears `GT-G4`? *Recommend yes for the
  diagnostic-only variant, since it writes no scores.*
- **OQ-QA-6:** Does this become a **Stage E** in this spec, or its own spec that depends on
  this one? *Recommend its own spec if OQ-QA-3 is answered "yes" — a FAULTLINE-axis change is
  large enough to deserve its own requirement set.*

---

## 8. Explicit non-claims

- This document does **not** modify `REQ-1`–`REQ-47`, `design.md`, or `tasks.md`.
- It does **not** claim QA-Emb improves recall here. The paper's IR result shows it **loses to
  keyword search alone** (0.45 vs 0.77); the case for it rests on Seams 1 and 2, and on the
  fact that we already own the efficient approximator it needs — neither is yet measured on
  our corpus.
- It does **not** propose replacing the hash address, the Beta-Bernoulli scorecard, the
  `-log(posterior)` path cost, or any decay mechanism.
- It does **not** propose new infrastructure beyond one additive column and one versioned
  artifact.

---

## 9. References

- **Paper:** <https://arxiv.org/abs/2405.16714> — Benara, V., Singh, C., Morris, J. X.,
  Antonello, R., Stoica, I., Huth, A. G., Gao, J. *Crafting Interpretable Embeddings by Asking
  LLMs Questions.* arXiv:2405.16714 [cs.CL], 26 May 2024.
- **PDF:** <https://arxiv.org/pdf/2405.16714> · **HTML:** <https://arxiv.org/html/2405.16714v1>
- **Code:** <https://github.com/csinva/interpretable-embeddings> (prompts, the 29 selected
  questions, and the generated pools are published there)
- **Sibling evidence in-repo:** `specs/tool-decision-engine-improvements/BENCH-2026-09-25-model-comparison.md`
  (the measured 119ms / calibrated-confidence result that makes the engine a viable QA-Emb
  scorer) and `docs/architecture/tool-decision-engine-improvements.md` §10.

# Oracle addendum: proposals (§19–§24)

> **Status: PROPOSED.** Nothing here is implemented or measured. Written against `oracle.md` (verified 2026-09-26/27). I have read that doc, not the code.
>
> Tags: **[doc]** = taken from `oracle.md` · **[proposal]** = new · **[unmeasured]** = a number I do not have; log it first.
>
> Nothing here reaches enforcement except through the existing bar (§17). Every item carries a baseline, a shadow phase, and a kill criterion.

---

## 19. The organizing idea: decisions descend a cost ladder

| Level | Cost | Examples | A decision arrives here when |
|---|---|---|---|
| Brain | seconds [unmeasured] | planning, escalations | default for anything unproven |
| Vision model | seconds [unmeasured] | unlabeled UI, CAPTCHA, canvas | structure alone is insufficient |
| Oracle | ~166 ms p50 [doc §8] | `tool_choice`, `mode`, monitors | its consumer passes the bar (§17) |
| Rule / cache | ~0 ms | known routes, cached page-state descriptions | it has been right for N consecutive **audited** occurrences [proposal] |

Rules:

- A decision moves **down** only on evidence and keeps a permanent audit floor.
- It moves back **up** automatically when audits disagree.
- Repeated, verified judgments turning into reflexes is the "subconscious" arc.

Every lever below does one of three things: fewer Oracle calls per turn, fewer Brain or vision calls, or cheaper labels.

---

## 20. Vision gate: consumer `vision_needed` (Noul)

### 20.1 Does it pass §17.2?

| Criterion | Answer |
|---|---|
| 1. Repeated decision made by a keyword list, timer, or Brain call | Yes, if vision today runs by default or by Brain choice **[assumption: confirm]** |
| 2. Choice among named options, or yes/no | Yes/no (Noul) |
| 3. Observable reference | Yes, once audit sampling (20.4) is wired |
| 4. Enough volume; wrong is cheap or gated | Yes. A wrong "sufficient" costs a failed action and a retry. A wrong "needs vision" costs one vision call. Errors are asymmetric in the safe direction. |

### 20.2 The feature frame (computed in code)

Fix the frame's shape early. A different instruction or frame shape invalidates the calibration [doc §8].

- `unnamed_interactive_ratio`, `icon_only_buttons`
- `canvas_area_fraction`, `video_present`
- cross-origin iframes, closed shadow roots
- overlay or modal present
- `labeled_coverage` (fraction of viewport covered by named or text elements)
- empty accessibility tree after the page settles
- DOM still mutating (`stability_ms`)
- recent failures on this page signature
- goal words that imply visual content (color, chart, image, layout)

### 20.3 Hard triggers (code decides, the Oracle is never asked)

These force vision:

- CAPTCHA markers
- canvas-dominant page
- empty accessibility tree after settle
- two consecutive failed actions on the same page signature

### 20.4 The reference: audit sampling

On a fraction of steps where the Oracle said "sufficient" and the structured path acted:

1. Run vision afterwards, in the background, with one fixed question: would it have chosen a different target, or seen a blocker?
2. Record that verdict as `brain_bool` on the shadow row.
3. Confirm the key is on `_DECISION_META_KEYS` before trusting a row [doc §14.2].

Audit rate: high until 100 rows, lower afterwards, never zero. A small permanent floor catches site redesigns.

### 20.5 Is it worth 166 ms?

```
net saving per gated step  =  P(skip) · V  −  g  −  P(skip) · (1 − precision) · F
```

- `g` ≈ 0.166 s [doc]
- `V` = vision call latency [unmeasured]
- `F` = cost of a wrong skip: failed action plus recovery [unmeasured]
- `P(skip)` = fraction of steps the gate lets structure handle [unmeasured]

Log all three in shadow before deciding anything.

### 20.6 Vision output stays text

- Fixed, short schema. Elements map to element-table ids; unmapped ones become virtual ids.
- Whatever menu the Oracle then sees must be **narrowed in code to the calibrated width (6)** [doc §5, AC25.5]. A wider menu turns enforcement off.

### 20.7 Kill criterion

Stay in shadow if net saving ≤ 0 on your real traffic, or if precision on audit rows cannot reach the bar.

---

## 21. Vision cache (deterministic; does not touch the pass mark)

- **Key:** perceptual hash of the crop + page signature + question id.
- **Value:** vision's structured text.
- **Invalidate:** when the DOM diff shows change in that region.
- A cache is a listed lever that does not invalidate calibration [doc §8].
- It only pays if page states actually repeat [unmeasured].
- **Step 1 is log-only:** record the hashes for about a week of real traffic and compute the repeat rate. If it is low, do not build it.

---

## 22. Recall for documents and pictures

### 22.1 Diagnosis [proposal]

From what I know of Mycelium, recall is **coordinate-addressed**: an exact key expands into a stored context payload. Content is not reachable until it has been **placed**. So gains for documents and pictures come from:

- placement at ingest
- content-level retrieval

They do not come from making coordinate lookup faster. I have not seen your ingest code, so the stage names below are a shape, not a description of what exists.

### 22.2 Spend Oracle calls where latency is free: ingest

At ~166 ms per question, an Oracle call in the turn path is costly. In a background ingest job it costs nothing the user feels. Candidates already in your twelve use cases:

- **Entity alignment:** merge / review / no_change
- **Promotion gate:** promote / discard
- **Extraction acceptance:** accept / escalate

Each still has to pass §17.2 and needs a reference (for example review outcomes, or later "was this recalled item useful").

### 22.3 Ingest pipeline (shape)

```
parse
 → structure-aware chunks (headings, tables) with provenance (doc, page, offset)
 → contextual header per chunk (title + section path; written by the Brain, async)
 → cheap entity/fact extraction
 → Oracle alignment against existing nodes
 → assign coordinates / hyperedges
 → index (lexical; optionally vectors)
```

**Pictures:**

- Run vision **once, at ingest**. Store caption, OCR text, and entities as structured text.
- Perceptual-hash near-duplicates **before** spending vision.
- Keep provenance.
- Retrieve through the derived text and coordinates like everything else. No vision at query time.
- Questionable captions take the accept/escalate route (use case 6).

### 22.4 Query funnel: cheapest first, stop when the margin is clear

| Stage | Method | Cost |
|---|---|---|
| 1 | Exact hash / coordinate (existing) | ~0 |
| 2 | Lexical: SQLite FTS5 BM25 (verify FTS5 is compiled into your Python's SQLite) | ms |
| 3 | Optional vectors (adds an embedding model and an index; measure before adopting) | [unmeasured] |
| 4 | Deterministic fusion of 2 and 3 (reciprocal rank fusion) | ~0 |
| 5 | **Oracle only when the fused top scores are close:** choose among the top 6, one run at the calibrated width | ~166 ms |
| 6 | Optional Noul `context_sufficient` before the Brain call | ~166 ms |

**Why margin-triggered instead of always:** the Oracle is one question per run, so scoring N candidates one at a time costs N × 166 ms (20 candidates ≈ 3.3 s). Use it as a tie-breaker, not a reranker.

### 22.5 Free labels close the loop

- After each answer, **code** (not the Oracle) marks every recalled item **used** or **ignored**, using citation or quote overlap.
- That feeds the Beta-Bernoulli update on hyperedges.
- It is also the reference for a `recall_keep` consumer that trims unused context before the Brain prompt. Fewer prompt tokens means faster Brain calls. [proposal]

### 22.6 Measure before believing

Build a golden set of 30–50 real questions with known source passages. Track:

- recall@k
- MRR
- context tokens per answer
- time to context

**Expectation:** a step change in what is findable, since things that were unretrievable become retrievable. Not exponential growth. Compounding comes from 22.5's loop.

---

## 23. Other levers, ranked

1. **Calibration before more enforcement.** Draw the reliability diagram for `mode` (ECE 0.263 [doc §17.1]). Whether it is under- or over-confident decides the fix. A monotone recalibration changes the distribution, so by §2 it is a **new calibrated identity**. Fit per consumer on older rows, test on newer (time-ordered split). The judge paper (arXiv:2609.26550 §6) found one temperature fitted on a pilot set improved one workload and worsened two others, so never share a temperature across consumers, and treat recalibration as an experiment that can fail. ECE from ~100 rows is noisy: report a bootstrap interval before reading 0.05 as pass or fail.
2. **Zero-Oracle steps.** Deterministic pre-gates so trivial steps ask nothing (your lever 1 [doc §8]).
3. **Stable Brain prompt prefix.** Static system prompt and tool schemas first, dynamic content last, so a local server's or a hosted provider's prompt cache can hit. Measure time-to-first-token. Confirm the setting for your local server build.
4. **Perceived latency.** Narrate through Brain and vision waits (you already have TTS narration).
5. **Speculative vision.** On pages with a high prior for needing vision, start vision alongside the gate and cancel it if the gate says "sufficient." It trades compute for latency and may contend with any GPU-hosted model. Adopt only if it beats baseline with no regression (your parallelism rule [doc §9]).
6. **Known-route memory.** The existing pre-filter hint can skip the gate entirely on pages with verified routes.

---

## 24. Adoption rule and order

**Rule:** baseline → shadow → kill criterion → the §17 bar. Nothing skips §17.

**Order:**

1. Confirm web steps complete end to end [doc §15]. Without completed steps there are no rows.
2. Log-only instrumentation: gate frame, hard triggers, vision-cache hashes. No behavior change.
3. Reliability diagram and ECE diagnosis.
4. Audit sampling for `vision_needed`; collect 100 rows.
5. Golden set and an FTS5 + fusion baseline for recall.
6. Ingest-time alignment and picture-to-text ingest.
7. Enforce `vision_needed` only if it clears the bar **and** net saving > 0.

---

## 25. Improving the Brain's success criteria (informed by arXiv:2609.26550)

> **Source note.** **[paper]** = the full text of arXiv:2609.26550 (main body read through Appendix B; appendices C–L not read). The paper judges preference pairs, factuality, and final-answer adjudication with hosted Jev. It is not about agents, and its numbers do not transfer to your local GLiNER Oracle. The **method** does.

### 25.1 What the paper's protocol protects against

| Paper practice [paper] | Risk it guards against | Your version [proposal] |
|---|---|---|
| Split by source question, not by item | Correlated rows inflate the sample | Split and bootstrap by **task/session**, not by step |
| Fit thresholds on a selection set; evaluate on a frozen extension never used in any fit | Optimistic thresholds | Held-out **tasks** the improving agent never sees |
| Threshold rule: maximum coverage while accuracy stays within 2 points of the fallback | Per-decision precision says nothing about what the cascade costs vs the fallback | Add a paired **cascade vs Brain-alone** test on task success, with a tolerance δ you choose |
| Paired cluster bootstrap intervals | Small-n overconfidence | Report the interval, not only the point estimate |
| Invalid outputs count as errors | Hidden failures | Count engine refusals, timeouts, and unparseable outputs in the denominators (verify your report does) |
| Blinded human adjudication only where judges disagree | Expensive labeling | Adjudicate rows where `chosen != brain_choice`; that is where the information is |
| Exploratory analyses labeled as exploratory | Forking paths | Tag them |

### 25.2 Criteria must be anchored to a reference

- Judging against a supplied reference works: about 94% on final-answer adjudication [paper §3/§5].
- **Reference-free prose is near chance for every judge tested,** while mean confidence stays around 0.90–0.96 [paper §5].
- So Brain success criteria should be:
  - terminal-state and policy-constraint checks
  - the evidence or tool result placed in the frame
  - rubric items with **label definitions** (the paper's request format defines each label)
- Do not ask the Oracle "was that a good answer?" without a reference.
- Changing an instruction's shape changes the calibration [doc §8], so version it.

### 25.3 What the Oracle should not judge for the Brain

- **Multi-step derivations:** about 15 points behind the strong judge on JudgeBench (−14.6, CI [−18.9, −10.3]).
- **Fluent-but-wrong answers:** about 20 points behind on style-adversarial pairs (−19.8, CI [−27.7, −12.7]).
- **Reference-free prose.**
- Use code checks or a stronger model for these.

### 25.4 Confidence is a ranking signal, not a certificate

- In the paper, accuracy rose from 47.7% (q < 0.6) to 99.1% (q = 1).
- On style-adversarial pairs, about a third of items scored in [0.9, 0.95) were still wrong, and error-detection AUROC fell to 0.77.
- **Add error-detection AUROC to your report line.** Your bar (precision, ECE, rows) does not include it.
- Keep code floors and audit sampling on confident accepts, especially on pages or tasks with adversarial content.

### 25.5 Cheap offline diagnostics on your ledger [proposal]

- **Order sensitivity.** Reversing candidate order flipped 3.25% (RewardBench) and 11.14% (JudgeBench) of decisions, with no positional preference [paper §6]. Replay ledger rows with a permuted menu order and measure the flip rate per consumer. This costs no live latency. Consider two-order averaging only if flips are high; it doubles the runs.
- **Interface disagreement.** Choice, Noul, and binary Score probabilities differed by about 0.055 on average, with co-question context named as one cause [paper §6]. This corroborates your `decide_many` removal and your "a 2-way softmax is not a Noul" rule [doc §6].

### 25.6 Guardrails for the agent that tunes the Brain's criteria

1. **Freeze an eval set of tasks.** The improving agent sees aggregate pass/fail only, never items. Refresh it when contaminated. The paper concedes its own extension "was not newly hidden from the analyst."
2. **Shadow first.** Proposed criteria run on the selection set; promote only if the paired cascade-vs-Brain-alone difference stays inside δ, with its interval reported.
3. **One change at a time,** with a **criteria version** logged on every row. Scope reports to (Oracle, Brain, criteria version), the same lesson as §16.
4. **Labels come from outcomes,** never from the improving agent's own judgment. Adjudicate disagreements blind (you, or a second model family, labeled as such).
5. **Expect wide intervals.** The paper's 510-pair frozen test still gave −0.59 points with an interval of [−1.78, +0.59]. Choose δ knowing that.
6. **Stop rule.** If N consecutive proposals show no held-out gain, stop.

### 25.7 What not to import

- The paper's accuracy and fee numbers (hosted Jev, not your local model).
- Its single-annotator adjudication. It is a stated limitation, and 36 of its 183 labels were indecisive.
- "Fee saved" as the currency. Yours is Brain and vision calls avoided, and wall-clock time.

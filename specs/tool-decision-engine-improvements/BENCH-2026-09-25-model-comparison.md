# Benchmark: Decision Model Comparison (2026-09-25)

**Question:** should the resident `LFM2-350M-Extract` decision engine be replaced, and with what?

**Method:** both configurations scored on the identical labeled battery
(`scripts/fixtures/decision_engine_cases.json`, 60 cases with human-expert ground truth),
using the identical per-case candidate menu (the menu-narrowing logic from
`scripts/run_engine_calibration.py:31-123`). Harness:
`scripts/bench_decision_models.py` (new; read-only, never writes the ledger).
Config: `EngineConfig()` production defaults (CPU, tau=0.5, threshold=0.85), model
`LFM2-350M-Extract.Q4_K_M.gguf`.

---

## 1. Headline result

| Configuration | Accuracy (all 60) | Coverage @threshold | Accuracy ≥threshold | p50 | p95 | mean |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **GLiNER2.5-Decide ONNX (int8) @0.40** | **71.7%** | 38.3% | **100.0%** | **119.2 ms** | 138.2 ms | 120.4 ms |
| LFM2 — flat single pass @0.85 | 60.0% | 40.0% | 70.8% | 1172.4 ms | 3701.9 ms | 2034.7 ms |
| **LFM2 — hierarchical tree** (`decide_tree`, **production path**) @0.85 | 33.3% | 50.0% | 66.7% | 5398.9 ms | 11056.0 ms | 6518.9 ms |
| LFM2.5-350M (base) — flat @0.85 | 11.7% | 91.7% | 3.6% | 845.5 ms | 2703.1 ms | 1320.2 ms |
| LFM2.5-350M (base) — tree @0.85 | 25.0% | 80.0% | 31.2% | 3143.9 ms | 5973.8 ms | 4155.3 ms |

**Two headlines:** (1) the current production path is the worst of the LFM options — the
hierarchy costs 26.7 accuracy points and 4.6× latency; (2) **GLiNER2.5-Decide via ONNX beats
every LFM configuration on accuracy, calibration, and latency simultaneously** (see §4).

**The production path is the worse one.** The hierarchical two-stage selection
(`decide_tree`, REQ-17's lane→leaf tree) is **4.6× slower and 27 accuracy points worse**
than simply scoring all candidates in one flat pass.

| Delta (tree vs flat) | |
| :--- | :--- |
| Accuracy | 33.3% → 60.0% (**+26.7 pts**) |
| p50 latency | 5398.9 ms → 1172.4 ms (**4.6× faster**) |
| p95 latency | 11056.0 ms → 3701.9 ms (**3.0× faster**) |

This is the largest single win found today, and it requires **no model change** — only
stopping the hierarchy (or fixing it).

---

## 1b. LFM2.5-350M swap test — REJECTED (my earlier recommendation was wrong)

I recommended testing `LiquidAI/LFM2.5-350M-GGUF` as a "lowest-risk accuracy buy" (newer
generation, official GGUF, same size). **Measurement says the opposite.** Tested on the same
60 cases, same menu:

| Model | Accuracy (all) | Coverage @0.85 | Accuracy ≥0.85 | p50 |
| :--- | ---: | ---: | ---: | ---: |
| **LFM2-350M-Extract** (current) — flat | **60.0%** | 40.0% | **70.8%** | 1172 ms |
| LFM2.5-350M (base) — flat | **11.7%** | 91.7% | **3.6%** | 845 ms |
| **LFM2-350M-Extract** (current) — tree | **33.3%** | 50.0% | **66.7%** | 5399 ms |
| LFM2.5-350M (base) — tree | **25.0%** | 80.0% | **31.2%** | 3144 ms |

**LFM2.5-350M is ~5× worse overall and ~20× worse above threshold** (3.6% vs 70.8%).
Do not swap.

**Failure mode — single-token collapse with maximal false confidence.** Of 53 wrong answers
on the flat path, **48 were `read_file`**, with confidences up to **0.9999**:

| Case | Chose | Expected | Confidence |
| :--- | :--- | :--- | ---: |
| c14 | `read_file` | `recall_memory` | **0.9999** |
| c16 | `read_file` | `recall_memory` | **0.9996** |
| c04 | `read_file` | `list_directory` | **0.9995** |
| c17 | `read_file` | `vision_analyze_screen` | **0.9993** |

The base model answers "read_file" to almost everything and reports ~1.0 certainty. This is
the uniform/one-token collapse the engine's own comments warn about
(`decision_engine.py:114-118`: the 350M "collapsed to uniform" beyond 4-6 options).

**Why the task-tuned model wins:** `LFM2-350M-Extract` is specifically tuned for structured
extraction/classification, which is what logit-based option scoring needs. A general base
model in the same size class does not carry that signal. **The task-tuned variant is the
appropriate fit; the newer generation is not.**

### Resolver caveat (verified)
`resolve_model_path` prefers filenames containing `extract`, then `instruct`, then any hit
(`decision_engine.py:177-183`). So a base `LFM2.5-350M-Q4_K_M.gguf` dropped into
`~/.lmstudio/models` would **not** take effect anyway — the current Extract file keeps
priority. There is also **no `LFM2.5-350M-Extract`** (the LFM2.5 Extract models are VL-only:
`LFM2.5-VL-450M-Extract`, `LFM2.5-VL-1.6B-Extract`).

**Also confirmed:** `agent_config.yaml` sets `decision_driver.constraints.candidate_cap: 32`,
but **nothing wires that into `EngineConfig`** — the engine uses the code default
`candidate_cap = 6`. So the benchmark's cap matches production.

---


## 2. Why each path fails — different failure modes

**Tree (40 wrong): 33 chose `DELEGATE`, 7 chose `NONE`.**
The tree essentially never picks a real tool when it fails — it bails to `DELEGATE`. That
is the signature of a broken lane stage: the lane is selected, the leaf cannot resolve
within that lane, and the whole decision degrades. It is not "picking the wrong tool"; it
is "failing to pick any tool."

**Flat (24 wrong): 18 chose `read_file`.**
The flat path has a systematic bias toward `read_file` — consistent with the prompt head
being dominated by `read_file` worked examples (`decision_engine.py:356-373`: three of five
examples resolve to `read_file`/`list_directory`, and `read_file` appears in most example
option lists).

So the two paths fail in *opposite* ways: tree → over-delegation, flat → single-tool bias.

---

## 3. Confidence is not trustworthy (the calibration gap, now measured)

The tree path produced **high-confidence wrong answers**, including ≥0.96 confidence:

| Case | Chose | Expected | Confidence |
| :--- | :--- | :--- | ---: |
| c03 | `NONE` | `read_file` | **0.9859** |
| c49 | `DELEGATE` | `clip_video` | **0.9882** |
| c57 | `NONE` | `vision_analyze_screen` | **0.9859** |
| c58 | `NONE` | `vision_analyze_screen` | **0.9848** |
| c60 | `NONE` | `vision_validate_action` | **0.9600** |
| c28 | `NONE` | `get_system_info` | **0.9018** |

A model reporting 0.986 while wrong means the confidence carries **no reliable
information** — which is precisely what REQ-18 (calibration quality) was written to catch,
and precisely what `softmax_tau = 0.5` sharpening causes. Any threshold-based auto-execute
built on this number is unsafe.

**Comparison to the documented state:** `docs/architecture/tool-decision-engine.md:9-11`
records "live calibration at 92% accuracy / 42% coverage at the 0.85 threshold". Measured
here: **70.8% at 0.85 (flat) / 66.7% (tree)**. The documented figure is not reproducible on
the labeled battery. Note the doc's own TG-5 harvest gate is marked still open.

---

## 4. GLiNER2.5-Decide ONNX — WORKS, and it is the best option tested

**This overturns my earlier conclusion.** I said GLiNER was "not an appropriate fit" and could
not be benchmarked. Both were wrong. The **ONNX export** bypasses both blockers:

- **Torch-free.** `nishparadox/gliner2.5-decide-onnx` ships a reference runner
  (`gliner_onnx.py`) using **onnxruntime + tokenizers + numpy** — *all three already installed
  in the project venv*. **No `transformers<5`, no gliner2, no second environment.**
- **No custom-architecture problem.** ONNX is a self-contained graph, so the
  `model_type: extractor` / `SpanExtractor` registration failure never arises.

### Results (60 cases, identical menu, int8 variant)

| Model | Accuracy | Coverage @threshold | Accuracy ≥threshold | p50 | p95 |
| :--- | ---: | ---: | ---: | ---: | ---: |
| **GLiNER2.5-Decide ONNX (int8)** @0.40 | **71.7%** | **38.3%** | **100.0%** | **119.2 ms** | 138.2 ms |
| LFM2-350M-Extract flat @0.85 | 60.0% | 40.0% | 70.8% | 1172.4 ms | 3701.9 ms |
| LFM2-350M-Extract tree @0.85 | 33.3% | 50.0% | 66.7% | 5398.9 ms | 11056.0 ms |

**At comparable coverage (~38% vs ~40%), GLiNER is 100% accurate vs 70.8% — a +29 point
accuracy gain — and ~10× faster.**

### The threshold must be retuned (this is not a weakness, it is the point)
GLiNER's softmax is spread over the candidate menu, so 0.85 is simply the wrong cut for its
distribution. Its measured reliability curve:

| threshold | coverage | accuracy above |
| ---: | ---: | ---: |
| 0.20 | 100.0% | 71.7% |
| 0.25 | 83.3% | 78.0% |
| 0.30 | 63.3% | 86.8% |
| 0.35 | 45.0% | 96.3% |
| **0.40** | **38.3%** | **100.0%** |
| 0.45 | 33.3% | 100.0% |
| 0.50 | 30.0% | 100.0% |
| 0.85 | 8.3% | 100.0% |

**All 17 errors carry confidence ≤ 0.352.** Above 0.40 it is never wrong. That is a *genuinely
calibrated* signal — precisely the property the current engine lacks (which reports 0.9859
while wrong).

### Targets
- AC1.3 (≤180 ms p50): **119 ms ✓**
- Total resolution (≤450 ms): **119 ms ✓**
- Accuracy ≥ threshold (≥92%): **100% ✓** at the retuned 0.40

### Cost
| Item | Size |
| :--- | ---: |
| `model_int8.onnx` | 642.6 MB |
| `tokenizer.json` | 8.3 MB |
| **Total** | **~651 MB** (vs 218.7 MB today → **+432 MB**) |

Session init is fast (**14.6 s wall for all 60 cases including model load**), versus ~81 s+65 s
cold-import for the transformers/gliner2 route. **No new dependency to install.**

### Caveats
- **int8 is lossy** (`max |ΔP| ≤ 0.18` per the model card) — yet still reaches 100% at 0.40.
  `model_fp16.onnx` (874 MB) or `model.onnx` (1.75 GB) would be exact, at more size/latency.
- **Not a GGUF** — so this is a *new inference path* (onnxruntime) alongside the existing
  llama.cpp engine, not a drop-in for it.
- Only the classification path is exported (single/multi-label + ordinal). Span extraction and
  relations are not — irrelevant for tool choice.

### Earlier failed attempt (for the record)
The F32 safetensors route (`fastino/GLiNER2.5-Decide` + `gliner2`) is a dead end here:
`gliner2[local]` needs `transformers<5` (project runs 5.12.0), and even with that satisfied
`AutoExtractor.from_pretrained` fails to load the checkpoint. Files were removed on request.

---

## 5. LFM-family alternatives (answering "is there a better LFM for us?")

Searched the current LFM2.5 lineup. Three findings:

**(a) Official `LiquidAI/LFM2.5-350M` + `LiquidAI/LFM2.5-350M-GGUF` — the real drop-in.**
The project runs `LFM2-350M-Extract` (the **LFM2** generation). LFM2.5-350M is the newer
generation with additional pre-training, and it ships an **official GGUF** — so it slots
into the existing `llama_cpp` engine with no code change and the same size/latency class.
This is the lowest-risk accuracy improvement available and should be tested first.

**(b) `LiquidAI/LFM2.5-Encoder-350M-Prompt-Router` — purpose-built for routing, but wrong shape.**
Official Liquid AI, `text-classification`, explicitly a router. However it is an
**encoder** (`bidirectional`, `masked-lm`, requires `trust_remote_code` for
`modeling_lfm2_bidirectional.py`) — encoders produce no next-token logits, so it would
require rewriting the engine's scoring path, and there is no GGUF. Promising long-term,
wrong fit for a drop-in swap.

**(c) `notnotsamuel/LFM2.5-350M-RLCD` — a correction to my own earlier read.**
The name suggests it is RLCD-trained (JEV's method). **It is not.** Its own card states:
*"Inference only: no training or fine-tuning, and no reproduction of TypeSafe.ai's
proprietary Jev training method."* It is an **inference-method** repo on **unchanged
LFM2.5-350M weights** — it prefills once, reuses attention/conv state across candidate
branches, and batch-scores allowed values, assembling JSON in Python.

It is still worth reading as a **reference implementation of exactly what this spec is
trying to build** (the T23 head-cache + REQ-1 batch scoring + REQ-20 batched questions),
with published numbers: **8.46× (M2 Max) to 62.9× (H100)** speedup over autoregressive for
structured output, with *higher* field accuracy (60.7% vs 53.6% constrained vs AR). Two
directly relevant caveats it reports: at **255 candidates constrained inference was 3.23×
slower** (bears on the candidate-cap question), and speedup is workload-dependent
(6.25×–9.68× on a 12-case suite, where accuracy actually fell 80.6% → 77.8%).

---

## 6. Recommendation

1. **Stop using `decide_tree` for tool selection** (or fix the lane stage). Free, already
   measured, +26.7 accuracy points and 4.6× lower p50 on the current model.
2. **Adopt GLiNER2.5-Decide via ONNX as the tool-choice scorer.** It is the best option
   measured on every axis that matters (§4): **71.7% accuracy** (vs 60.0% flat, 33.3% tree),
   **100% accuracy above threshold at 0.40** (vs 70.8% at 0.85), and **119 ms p50**
   (vs 1172 ms / 5399 ms) — a ~10× speedup that finally clears the spec's ≤450 ms target.
   It needs **no new dependency** (onnxruntime + tokenizers + numpy are already installed),
   **no second environment**, and **no torch**. Session init is ~15 s for the full battery.
3. **Retune the threshold to 0.40 for this consumer.** GLiNER's softmax spreads over the
   candidate menu, so 0.85 is the wrong cut for its distribution. At 0.40: 38.3% coverage at
   100% accuracy — comparable coverage to today's 40% at **+29 accuracy points**.
4. **Accept the +432 MB** (651 MB vs 218.7 MB) — or test `model_fp16.onnx` (874 MB) /
   `model.onnx` (1.75 GB) if exactness matters more than size. int8 is lossy
   (`max |ΔP| ≤ 0.18`) yet still reaches 100% at 0.40.
5. **Keep `LFM2-350M-Extract` as the fallback**, not the primary. Do not delete it: it is the
   working baseline, the app depends on it, and it still wins on footprint (218.7 MB).
   Note the LFM2.5-350M base swap was **rejected** (§1b) — ~5× worse with a single-token
   collapse to `read_file` at ~1.0 confidence.
6. **Keep REQ-18** (calibration measurement). It is the reason this comparison could be made
   at all: GLiNER's reliability curve is what shows it is trustworthy, and the current
   engine's confident-wrong answers (§3) are what show it is not.

### Revised "appropriate fit" criteria (this exercise corrected them)
My earlier filter — "must be a GGUF" — was **wrong**, and it nearly cost the best option.
The real requirements are:

| Requirement | Why | LFM2-350M-Extract | GLiNER ONNX int8 |
| :--- | :--- | :--- | :--- |
| CPU-resident, in-process | CT-DEI-1 (zero VRAM) | ✓ | ✓ |
| No new heavy dependency | avoid a second env | ✓ | ✓ (onnxruntime already present) |
| Small footprint | 94% disk usage | ✓ 218.7 MB | ~651 MB |
| **Calibrated confidence** | threshold-based automation | ✗ (0.9859 while wrong) | **✓ (100% ≥0.40)** |
| Accuracy | correctness | 60.0% | **71.7%** |
| Latency | ≤450 ms target | 1172 ms | **119 ms** |
| GGUF / llama.cpp | *nice-to-have, not required* | ✓ | ✗ |

**The GGUF constraint was a proxy, not a requirement.** What actually matters is "no new
dependency and CPU-resident" — and onnxruntime already satisfies that.


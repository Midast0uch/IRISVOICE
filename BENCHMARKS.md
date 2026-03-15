# IRIS Mycelium Layer — Benchmark Validation

This document records the proof-of-concept validation claims for the Mycelium coordinate-graph memory system and defines the benchmark setup needed to verify them.

---

## Background

The Mycelium layer replaces prose semantic headers with ~15-token coordinate paths that identify the user's position in seven coordinate spaces (`conduct`, `domain`, `style`, `chrono`, `context`, `capability`, `toolpath`). The hypothesis is that coordinate-path context is cheaper and compoundingly more accurate than static prose headers as the session graph matures.

The original research inspiration is Andrej Karpathy's framing of token budget as the primary cost lever in inference pipelines. Coordinate navigation converts orientation cost from a fixed per-session overhead into a variable that decreases as the graph accumulates traversal history.

---

## Three Core Claims

### Claim 1 — Lower Context Cost Over Time

**Statement:** Average tokens injected per session decreases as `mycelium_traversals` accumulates history, because `PredictiveLoader` cache hits eliminate full graph traversal and `WhiteboardSlicer` partial profiles replace full profile injection.

**Measurement:**
- `MyceliumInterface.get_stats()` field: `avg_context_tokens_per_task`
- Log this value every 50 sessions (INFO level)
- Expected trend: monotonically decreasing over the first 200 sessions, then stabilizing

**Threshold to pass:** By session 100, average context tokens ≤ 60% of the baseline (session 1 value). By session 300, ≤ 40%.

---

### Claim 2 — Smaller Model + Mature Graph > Larger Cold Model

**Statement:** After the graph reaches `is_mature() == True` (≥ 8 crystallized landmarks), a smaller inference model using coordinate-path context achieves equivalent or better task success rates than a larger model with no Mycelium context.

**Measurement:**
- Run identical task suites against two configurations:
  - A: Large model (e.g. `lfm2-8b`) + cold start (no Mycelium, prose headers only)
  - B: Small model (e.g. `lfm2.5-1.2b-instruct`) + mature Mycelium graph (≥ 8 landmarks)
- Record task success rate per configuration (binary: did the agent complete the task without clarification?)

**Threshold to pass:** Configuration B success rate ≥ Configuration A success rate on ≥ 70% of task categories. The gain in orientation precision compensates for the reduction in raw model capacity.

---

### Claim 3 — Compounding Effect

**Statement:** Cost reduction compounds: each additional mature landmark reduces not just navigation cost for that domain, but increases `PredictiveLoader` hit rate, reduces `TaskClassifier` ambiguity, and narrows partial profile selections — all simultaneously.

**Measurement:**
- Track `prediction_cache_hit_rate` from `get_stats()` at 0, 5, 10, 20, 50 crystallized landmarks
- Expected: super-linear increase in hit rate as landmark count grows (compounding)
- Also track `avg_spaces_navigated` — this should decrease as task-class-specific partial profiles become accurate

**Threshold to pass:** `prediction_cache_hit_rate` doubles between 5 and 20 landmarks. `avg_spaces_navigated` decreases by ≥ 1.5 spaces on average between 0 and 50 landmarks.

---

## Benchmark Setup

### Prerequisites

1. A working Mycelium implementation passing all Phase 12 tests
2. At least 300 recorded sessions in `data/memory.db` (use the session replay script or real usage)
3. Both inference models available locally

### Running the Benchmark

```bash
# Collect per-session stats (already logged by MyceliumInterface)
# Parse IRIS log output for "avg_context_tokens_per_task" lines
python tests/mycelium/benchmark_cost_trend.py --log-file iris.log --output cost_trend.csv

# Run task suite for Claim 2
python tests/mycelium/benchmark_model_comparison.py \
    --config-a large-cold \
    --config-b small-mature \
    --task-suite tests/mycelium/task_suite.json \
    --output model_comparison.csv

# Extract compounding metrics from stats
python tests/mycelium/benchmark_compounding.py --db data/memory.db --output compounding.csv
```

### Stats Fields Required

The following `MyceliumInterface.get_stats()` fields must exist for benchmarking:

| Field | Description |
|-------|-------------|
| `avg_context_tokens_per_task` | Rolling average tokens injected per session |
| `prediction_cache_hit_rate` | Fraction of sessions where PredictiveLoader served from cache |
| `avg_spaces_navigated` | Average number of coordinate spaces traversed per session |
| `whiteboard_broadcast_tokens` | Total tokens saved by WhiteboardSlicer slicing |
| `failure_warning_tokens` | Total tokens used for MicroAbstract failure warnings |

---

## Notes

- Benchmarks run against real usage data in `data/memory.db` — do not use a synthetic database
- The compounding claim requires ≥ 50 sessions to show statistical significance
- `PREDICTION_CACHE_TTL = 300` seconds may need tuning depending on session cadence; cache TTL is not a benchmark variable
- All three claims must pass before the Mycelium layer is considered production-validated

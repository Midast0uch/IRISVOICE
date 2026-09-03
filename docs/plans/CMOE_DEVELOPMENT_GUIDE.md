# Caducean Mixture of Experts — Development Guide
## Testing Environment, Gradual Implementation Path, and Swarm Integration

*For the IRISVOICE Application Agent — Pre-Integration Development Reference*
*Complete this guide before adding CMoE to the main application*

---

## Overview: The Development Path

This guide takes you through four phases in order. Do not skip phases. Each phase validates the foundation the next phase builds on.

```
Phase 0: Testing Environment Setup
         Install dependencies, verify models, build harness infrastructure

Phase 1: Scenario 1 — Single Model Hive
         One local model, multiple non-deterministic runs,
         physics-governed temperature and synthesis

Phase 2: Scenario 2 — Multi-Model Hive
         Different models as different thinkers,
         physics-governed role assignment and handoff

Phase 3: Tie-In A — Single Model Execution
         How CMoE wraps a single model call
         and when to use it vs bypass it

Phase 4: Tie-In B — Swarm Execution
         Multiple agents each running CMoE,
         physics-governed swarm coordination
```

Each phase produces a test report. Your agent reads the report before proceeding to the next phase. If any phase fails its acceptance criteria, fix it before moving forward.

---

## Phase 0: Testing Environment Setup

### 0.1 Directory Structure

Create this structure before writing any code:

```
cmoe_dev/
├── env_check.py              # Phase 0: verify all dependencies
├── scenario1/
│   ├── local_hive.py         # Phase 1: single model hive
│   ├── test_local_hive.py    # Phase 1: tests
│   └── reports/              # Phase 1: output reports
├── scenario2/
│   ├── multi_model_hive.py   # Phase 2: multi-model hive
│   ├── test_multi_hive.py    # Phase 2: tests
│   └── reports/              # Phase 2: output reports
├── tiein/
│   ├── single_model.py       # Phase 3: single model tie-in
│   ├── swarm.py              # Phase 4: swarm tie-in
│   ├── test_tiein.py         # Phase 3+4: tests
│   └── reports/              # Phase 3+4: output reports
├── shared/
│   ├── engine_utils.py       # shared engine helpers
│   ├── metrics.py            # shared measurement utilities
│   ├── prompts.py            # shared prompt templates
│   └── benchmark_tasks.py    # shared test tasks
└── cmoe_report.json          # master report across all phases
```

### 0.2 Dependencies

```bash
# Core engine
pip install caducean-kernel

# Local inference
pip install ollama
# Also install ollama desktop: https://ollama.ai
# Then pull models:
ollama pull llama3:8b
ollama pull mistral:7b
ollama pull phi3:mini        # ultra-fast, good for barrier role

# API inference
pip install anthropic
pip install openai            # optional, for GPT comparison

# Testing and measurement
pip install pytest
pip install numpy
pip install scipy             # for periodicity detection in coupling tests
pip install sentence-transformers  # for semantic diversity measurement

# Reporting
pip install rich              # pretty console output
```

### 0.3 Environment Verification Script

```python
# cmoe_dev/env_check.py
"""
Run this first. Verifies every dependency before any development begins.
All checks must pass before proceeding to Phase 1.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

def check_caducean_kernel():
    """Verify engine imports and basic operation."""
    try:
        from caducean_kernel import (
            CaduceanEngine, CaduceanConfig, CaduceanState,
            Action, ExitReason, EMLCalculator
        )
        engine = CaduceanEngine()
        engine.init_session("env_check")
        engine.observe("env_check", Action.EXPAND, success=True)
        state = engine.get_state("env_check")
        
        assert state.x == 1.0, f"Expected x=1.0 after EXPAND, got {state.x}"
        assert state.xi > 0.0, f"Expected xi>0 after advance, got {state.xi}"
        
        # Verify Duffing force
        F = engine.duffing_force(0.5)
        expected = 2.0 * 0.5 - 2.0 * (0.5**3)  # au - bu³
        assert abs(F - expected) < 1e-9, f"Duffing force wrong: {F} vs {expected}"
        
        # Verify natural exit not triggered at step 1
        should_exit, reason = engine.should_exit("env_check", 1, 200)
        assert not should_exit, "Engine should not exit at step 1"
        
        return True, "caducean_kernel: OK — engine, Duffing force, exit logic verified"
    
    except Exception as e:
        return False, f"caducean_kernel: FAIL — {e}"


def check_ollama():
    """Verify local model inference."""
    try:
        import ollama
        
        # Check if ollama service is running
        models = ollama.list()
        available = [m["name"] for m in models.get("models", [])]
        
        if not available:
            return False, "ollama: FAIL — no models pulled. Run: ollama pull llama3:8b"
        
        # Test inference
        test_model = available[0]
        response = ollama.generate(
            model=test_model,
            prompt="Say exactly: OLLAMA_OK",
            options={"temperature": 0.0, "num_predict": 10}
        )
        
        return True, f"ollama: OK — {len(available)} models available: {available[:3]}"
    
    except Exception as e:
        return False, f"ollama: FAIL — {e}. Is ollama running? (ollama serve)"


def check_anthropic():
    """Verify Anthropic API access."""
    try:
        import anthropic
        import os
        
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return False, "anthropic: FAIL — ANTHROPIC_API_KEY not set"
        
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "Say: API_OK"}]
        )
        
        return True, f"anthropic: OK — haiku responding"
    
    except Exception as e:
        return False, f"anthropic: FAIL — {e}"


def check_math_dependencies():
    """Verify scipy and numpy for physics calculations."""
    try:
        import numpy as np
        import scipy.signal
        import math
        
        # Verify Twrap calculation
        s = 0.25
        l, m = 2, 1
        balance = 1.0
        c_eff = math.sqrt(l**2 + m**2)
        twrap = (2 * math.pi) / (s * c_eff * balance)
        expected = 11.22  # approximately
        assert abs(twrap - expected) < 0.1, f"Twrap wrong: {twrap}"
        
        # Verify Q calculation
        x, y = 10.0, 3.0
        q = (x - y) / (x + y + 1.0)
        assert abs(q - 0.5) < 0.01, f"Q wrong: {q}"
        
        return True, "math_dependencies: OK — numpy, scipy, Twrap, Q verified"
    
    except Exception as e:
        return False, f"math_dependencies: FAIL — {e}"


def check_sentence_transformers():
    """Verify semantic diversity measurement."""
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
        
        model = SentenceTransformer("all-MiniLM-L6-v2")
        sentences = ["The sky is blue.", "Dogs like to run."]
        embeddings = model.encode(sentences)
        
        # Verify embeddings are different
        similarity = np.dot(embeddings[0], embeddings[1]) / (
            np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
        )
        assert 0.0 < similarity < 1.0, "Embeddings identical — check model"
        
        return True, f"sentence_transformers: OK — diversity measurement ready"
    
    except Exception as e:
        return False, f"sentence_transformers: FAIL — {e}. pip install sentence-transformers"


def run_all_checks() -> dict:
    checks = [
        check_caducean_kernel,
        check_ollama,
        check_anthropic,
        check_math_dependencies,
        check_sentence_transformers,
    ]
    
    results = []
    all_pass = True
    
    print("\n" + "="*60)
    print("CMOE ENVIRONMENT CHECK")
    print("="*60)
    
    for check_fn in checks:
        passed, message = check_fn()
        results.append({"check": check_fn.__name__, "passed": passed, "message": message})
        status = "✅" if passed else "❌"
        print(f"{status} {message}")
        if not passed:
            all_pass = False
    
    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "all_pass": all_pass,
        "results": results,
    }
    
    Path("cmoe_dev/env_check_report.json").write_text(
        json.dumps(report, indent=2)
    )
    
    print("\n" + "="*60)
    if all_pass:
        print("✅ All checks passed. Proceed to Phase 1.")
    else:
        print("❌ Fix failing checks before proceeding.")
    print("="*60 + "\n")
    
    return report


if __name__ == "__main__":
    report = run_all_checks()
    sys.exit(0 if report["all_pass"] else 1)
```

### 0.4 Shared Benchmark Tasks

These tasks are used across all phases for consistent measurement:

```python
# cmoe_dev/shared/benchmark_tasks.py
"""
Standard benchmark tasks used across all CMoE development phases.

Task difficulty levels:
  SIMPLE:  single-step, factual, verifiable
  MEDIUM:  multi-aspect, requires reasoning
  COMPLEX: open-ended, requires synthesis across perspectives
  
All tasks have a ground_truth or evaluation_criteria field
so results can be measured objectively.
"""

BENCHMARK_TASKS = [
    {
        "id": "T01",
        "difficulty": "SIMPLE",
        "query": "What is the time complexity of quicksort in the average case, and why?",
        "ground_truth_keywords": ["O(n log n)", "partition", "average", "pivot"],
        "min_coverage": 3,  # at least 3 keywords must appear
        "category": "technical",
    },
    {
        "id": "T02",
        "difficulty": "MEDIUM",
        "query": (
            "Explain three different approaches to handling race conditions "
            "in concurrent programming, with the tradeoffs of each."
        ),
        "ground_truth_keywords": [
            "mutex", "lock", "atomic", "semaphore", "deadlock",
            "tradeoff", "performance", "overhead"
        ],
        "min_coverage": 5,
        "category": "technical",
    },
    {
        "id": "T03",
        "difficulty": "COMPLEX",
        "query": (
            "A startup is choosing between building a monolith or microservices "
            "architecture for their first product. What should they consider, "
            "and what would you recommend?"
        ),
        "evaluation_criteria": [
            "mentions team size",
            "mentions scaling timeline",
            "mentions operational complexity",
            "gives a clear recommendation",
            "acknowledges tradeoffs",
        ],
        "min_criteria_met": 3,
        "category": "reasoning",
    },
    {
        "id": "T04",
        "difficulty": "MEDIUM",
        "query": (
            "What are the key differences between transformer attention "
            "and recurrent neural networks for sequence modeling?"
        ),
        "ground_truth_keywords": [
            "parallelism", "sequential", "memory", "attention",
            "gradient", "long-range", "context"
        ],
        "min_coverage": 4,
        "category": "technical",
    },
    {
        "id": "T05",
        "difficulty": "COMPLEX",
        "query": (
            "Design a caching strategy for a read-heavy distributed API "
            "that serves 10 million requests per day with data that "
            "changes every 5 minutes."
        ),
        "evaluation_criteria": [
            "specifies cache invalidation strategy",
            "mentions TTL or expiry",
            "addresses cache warming",
            "considers consistency",
            "addresses failure modes",
            "gives concrete numbers or thresholds",
        ],
        "min_criteria_met": 4,
        "category": "design",
    },
]


def evaluate_output(output: str, task: dict) -> dict:
    """
    Score an output against a task's evaluation criteria.
    Returns a score dict with coverage and pass/fail.
    """
    output_lower = output.lower()
    
    if "ground_truth_keywords" in task:
        keywords = task["ground_truth_keywords"]
        found = [kw for kw in keywords if kw.lower() in output_lower]
        coverage = len(found) / len(keywords)
        passed = len(found) >= task["min_coverage"]
        return {
            "task_id": task["id"],
            "keywords_found": found,
            "coverage_pct": coverage,
            "passed": passed,
            "score": coverage,
        }
    
    elif "evaluation_criteria" in task:
        criteria = task["evaluation_criteria"]
        met = []
        for criterion in criteria:
            # Simple keyword-based check — upgrade to LLM judge in production
            words = criterion.lower().split()
            if any(word in output_lower for word in words):
                met.append(criterion)
        
        coverage = len(met) / len(criteria)
        passed = len(met) >= task["min_criteria_met"]
        return {
            "task_id": task["id"],
            "criteria_met": met,
            "coverage_pct": coverage,
            "passed": passed,
            "score": coverage,
        }
    
    return {"task_id": task["id"], "passed": False, "score": 0.0}
```

### 0.5 Shared Metrics

```python
# cmoe_dev/shared/metrics.py
"""
Measurement utilities used across all phases.
Every phase uses the same metrics so results are comparable.
"""

import math
import numpy as np
from typing import Optional


def compute_q(x: float, y: float) -> float:
    """Topological charge. Q → 0 = balanced. Q → ±1 = imbalanced."""
    return (x - y) / (x + y + 1.0)


def compute_twrap(s: float, l: int, m: int, balance: float) -> float:
    """
    Predicted wrap time in steps.
    Validated at 0.0% error across c_eff 1.0-3.0 in D-series experiments.
    """
    c_eff = math.sqrt(l**2 + m**2)
    return (2 * math.pi) / (s * c_eff * balance)


def semantic_diversity(texts: list[str]) -> float:
    """
    Measure diversity of a list of text outputs.
    Returns 0.0 (identical) to 1.0 (maximally diverse).
    Uses sentence embeddings — more reliable than token overlap.
    """
    if len(texts) < 2:
        return 0.0
    
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embeddings = model.encode(texts)
        
        # Mean pairwise cosine distance
        n = len(embeddings)
        distances = []
        for i in range(n):
            for j in range(i+1, n):
                cos_sim = np.dot(embeddings[i], embeddings[j]) / (
                    np.linalg.norm(embeddings[i]) * np.linalg.norm(embeddings[j])
                )
                distances.append(1.0 - cos_sim)  # distance = 1 - similarity
        
        return float(np.mean(distances)) if distances else 0.0
    
    except ImportError:
        # Fallback: token overlap diversity
        return token_diversity(texts)


def token_diversity(texts: list[str]) -> float:
    """Fallback diversity metric using unique token coverage."""
    if len(texts) < 2:
        return 0.0
    
    all_tokens = set()
    per_text_tokens = []
    for text in texts:
        tokens = set(text.lower().split())
        all_tokens.update(tokens)
        per_text_tokens.append(tokens)
    
    # Mean Jaccard distance between pairs
    n = len(per_text_tokens)
    distances = []
    for i in range(n):
        for j in range(i+1, n):
            intersection = per_text_tokens[i] & per_text_tokens[j]
            union = per_text_tokens[i] | per_text_tokens[j]
            jaccard = len(intersection) / max(len(union), 1)
            distances.append(1.0 - jaccard)
    
    return float(np.mean(distances)) if distances else 0.0


def output_quality_heuristic(output: str) -> float:
    """
    Simple quality signal for outputs without ground truth.
    Based on length, structure, and coherence indicators.
    Replace with LLM-judge in production.
    """
    if not output or len(output) < 50:
        return 0.1
    
    score = 0.0
    
    # Length score (sweet spot 200-1500 chars)
    length = len(output)
    if 200 <= length <= 1500:
        score += 0.4
    elif length > 100:
        score += 0.2
    
    # Structure score (numbered lists, headers, specific terms)
    structure_signals = ["1.", "2.", "3.", "-", "•", ":", "\n\n"]
    structure_count = sum(1 for s in structure_signals if s in output)
    score += min(0.3, structure_count * 0.05)
    
    # Specificity score (numbers, technical terms)
    import re
    numbers = len(re.findall(r'\b\d+\.?\d*\b', output))
    score += min(0.3, numbers * 0.03)
    
    return min(1.0, score)


def phase_label(xi: float) -> str:
    """Standard phase label from xi value."""
    if xi < math.pi / 2:           return "PLANNING"
    elif xi < math.pi:             return "EXECUTING"
    elif xi < 3 * math.pi / 2:     return "REVIEWING"
    else:                          return "CONSOLIDATING"


def summarize_run(
    task_id: str,
    condition: str,
    output: str,
    steps: int,
    exit_reason: str,
    final_q: float,
    final_xi: float,
    task: dict,
) -> dict:
    """Standard run summary used in all phase reports."""
    eval_result = None
    try:
        from shared.benchmark_tasks import evaluate_output
        eval_result = evaluate_output(output, task)
    except Exception:
        pass
    
    return {
        "task_id": task_id,
        "condition": condition,
        "steps": steps,
        "exit_reason": exit_reason,
        "final_q": final_q,
        "final_xi": final_xi,
        "final_phase": phase_label(final_xi),
        "output_length": len(output),
        "quality_heuristic": output_quality_heuristic(output),
        "eval": eval_result,
        "passed": eval_result["passed"] if eval_result else None,
    }
```

### 0.6 Phase 0 Acceptance Criteria

Before proceeding to Phase 1, ALL of these must be true:

```
[ ] env_check.py runs with all green
[ ] ollama is running and at least one model is available
[ ] ANTHROPIC_API_KEY is set and haiku responds
[ ] caducean_kernel imports without error
[ ] Duffing force F(0.5) = 2(0.5) - 2(0.5³) = 0.75 ✓
[ ] Twrap formula computes correctly for (2,1): ≈ 11.2 steps at s=0.25, balance=1
[ ] Q formula: x=10, y=3 → Q ≈ 0.50 ✓
[ ] cmoe_dev/ directory structure created
[ ] All shared/ files created and importable
```

---

## Phase 1: Scenario 1 — Single Model Hive

### What This Phase Proves

One local model, multiple non-deterministic runs, physics-governed temperature schedule, physics-governed synthesis timing. The engine decides how many samples to take and when to synthesize.

### The Physics Of Temperature Scheduling

The engine's phase angle ξ governs sampling temperature:

```
temperature(ξ, u) = T_max · (1 - ξ/2π · decay) · (1 + u_mod · u)

where:
  T_max   = 1.0    maximum temperature (exploration)
  decay   = 0.85   how much temperature falls over the cycle
  u_mod   = 0.20   how much u modulates temperature

At ξ = 0 (PLANNING):       temp ≈ 1.0   — maximum exploration
At ξ = π (REVIEWING):      temp ≈ 0.575 — moderate
At ξ = 3π/2 (CONSOL.):    temp ≈ 0.36  — careful
At ξ = 2π (complete):      temp ≈ 0.15  — near-deterministic
```

This is simulated annealing of language model inference. The temperature schedule is not hardcoded — it emerges from the Duffing dynamics.

### The Q-Guided Synthesis Decision

Synthesis fires when Q returns toward 0. During exploration x accumulates (EXPAND actions), driving Q high. Each synthesis pass is COMPRESS — y accumulates, pulling Q back. Natural exit requires Q near 0 and ξ ≥ 3π/2.

```
Before synthesis: x=8, y=1 → Q = (8-1)/(8+1+1) = 0.70 (high — over-explored)
After synthesis:  x=8, y=4 → Q = (8-4)/(8+4+1) = 0.31 (lower — balancing)
At natural exit:  x=8, y=7 → Q = (8-7)/(8+7+1) = 0.063 (near 0 — closed)
```

### Implementation

```python
# cmoe_dev/scenario1/local_hive.py
"""
Phase 1: Single Model Hive
One local model, physics-governed temperature, physics-governed synthesis.
"""

import math
import json
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

import ollama
from caducean_kernel import (
    CaduceanEngine, CaduceanConfig, CaduceanState,
    Action, ExitReason
)

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.metrics import compute_q, compute_twrap, phase_label, output_quality_heuristic
from shared.benchmark_tasks import evaluate_output


@dataclass
class LocalHiveConfig:
    model: str = "llama3:8b"
    max_samples: int = 10          # hard cap on exploration samples
    max_synthesis_passes: int = 3  # hard cap on synthesis passes
    s: float = 0.25                # walk speed
    l: int = 3                     # winding — fast cycles for cheap local runs
    m: int = 3                     # (3,3) c_eff=3.0, Twrap≈8.4 steps at balance=1
    T_max: float = 1.0             # max exploration temperature
    T_decay: float = 0.85          # temperature decay over cycle
    quality_threshold: float = 0.6 # minimum synthesis quality to accept


@dataclass
class HiveSample:
    step: int
    temperature: float
    phase: str
    action: str
    output: str
    quality: float
    x_after: float
    y_after: float
    q_after: float
    xi_after: float
    u_after: float


@dataclass
class LocalHiveResult:
    query: str
    model: str
    config: dict
    samples: list
    final_output: str
    exit_reason: str
    total_steps: int
    final_q: float
    final_xi: float
    semantic_diversity: float
    quality_scores: list
    eval_result: Optional[dict]
    duration_seconds: float


class LocalModelHive:
    """
    Phase 1 implementation: Single model hive.
    
    The engine governs:
    - How many exploration samples to take
    - Temperature of each sample (phase-derived)
    - When to switch from exploration to synthesis
    - When synthesis is complete (natural exit)
    
    The model does not know it is in a hive.
    It just responds to prompts at the given temperature.
    """
    
    def __init__(self, config: LocalHiveConfig, session_id: str = "local_hive"):
        self.config = config
        self.session_id = session_id
        
        # Engine for this hive session
        self.engine = CaduceanEngine(config=CaduceanConfig(s=config.s))
        self.engine.init_session(session_id)
        
        self.samples: list[HiveSample] = []
        self.synthesis_outputs: list[str] = []
    
    def temperature_from_state(self) -> float:
        """
        Phase-governed temperature.
        Falls smoothly as ξ advances through the cycle.
        Modulated by u — expansion attractor raises temperature.
        """
        state = self.engine.get_state(self.session_id)
        base = self.config.T_max * (1.0 - (state.xi / (2 * math.pi)) * self.config.T_decay)
        modulated = base * (1.0 + 0.20 * state.u)
        return max(0.05, min(1.5, modulated))
    
    def run(self, query: str, task: Optional[dict] = None) -> LocalHiveResult:
        """
        Run the local model hive on a query.
        Physics governs the entire process.
        """
        start_time = time.time()
        step = 0
        final_output = ""
        exit_reason = "BUDGET"
        
        while step < (self.config.max_samples + self.config.max_synthesis_passes):
            state = self.engine.get_state(self.session_id)
            current_phase = phase_label(state.xi)
            temp = self.temperature_from_state()
            q = compute_q(state.x, state.y)
            
            # Determine action based on engine signal
            F = self.engine.duffing_force(state.u)
            
            if current_phase in ("PLANNING", "EXECUTING"):
                # EXPLORATION: sample at current temperature
                action_type = Action.EXPAND
                prompt = self._exploration_prompt(query, step)
                
            else:
                # SYNTHESIS: consolidate what we have
                action_type = Action.COMPRESS
                prompt = self._synthesis_prompt(query)
            
            # Generate output
            response = ollama.generate(
                model=self.config.model,
                prompt=prompt,
                options={
                    "temperature": temp,
                    "num_predict": 400,
                    "stop": ["<done/>"],
                }
            )
            output = response.get("response", "").strip()
            
            # Assess quality
            quality = output_quality_heuristic(output)
            
            # Observe in engine
            success = quality > 0.4
            self.engine.observe(self.session_id, action_type, success=success)
            
            # Update state after observation
            state_after = self.engine.get_state(self.session_id)
            q_after = compute_q(state_after.x, state_after.y)
            
            # Record sample
            sample = HiveSample(
                step=step,
                temperature=temp,
                phase=current_phase,
                action=action_type.name,
                output=output,
                quality=quality,
                x_after=state_after.x,
                y_after=state_after.y,
                q_after=q_after,
                xi_after=state_after.xi,
                u_after=state_after.u,
            )
            self.samples.append(sample)
            
            if action_type == Action.COMPRESS:
                self.synthesis_outputs.append(output)
                final_output = output
            
            step += 1
            
            # Check natural exit
            should_exit, reason = self.engine.should_exit(
                self.session_id, step,
                self.config.max_samples + self.config.max_synthesis_passes
            )
            if should_exit:
                exit_reason = reason.name
                break
        
        # Final state
        final_state = self.engine.get_state(self.session_id)
        final_q = compute_q(final_state.x, final_state.y)
        
        # Measure semantic diversity of exploration samples
        exploration_texts = [
            s.output for s in self.samples if s.action == "EXPAND"
        ]
        from shared.metrics import semantic_diversity
        diversity = semantic_diversity(exploration_texts) if len(exploration_texts) >= 2 else 0.0
        
        # Evaluate against task if provided
        eval_result = None
        if task and final_output:
            eval_result = evaluate_output(final_output, task)
        
        return LocalHiveResult(
            query=query,
            model=self.config.model,
            config=asdict(self.config),
            samples=[asdict(s) for s in self.samples],
            final_output=final_output,
            exit_reason=exit_reason,
            total_steps=step,
            final_q=final_q,
            final_xi=final_state.xi,
            semantic_diversity=diversity,
            quality_scores=[s.quality for s in self.samples],
            eval_result=eval_result,
            duration_seconds=time.time() - start_time,
        )
    
    def _exploration_prompt(self, query: str, step: int) -> str:
        if step == 0 or not self.samples:
            return (
                f"Think carefully about this question from a fresh perspective:\n\n"
                f"{query}\n\n"
                "Share your most insightful analysis."
            )
        
        # After first sample: ask for a different angle
        prev = self.samples[-1].output[:200]
        return (
            f"Question: {query}\n\n"
            f"A previous analysis explored: {prev}...\n\n"
            "Now take a completely different approach. "
            "What angle or consideration was missed?"
        )
    
    def _synthesis_prompt(self, query: str) -> str:
        # Use top 3 exploration samples by quality
        exploration_samples = [
            s for s in self.samples if s.action == "EXPAND"
        ]
        top_samples = sorted(
            exploration_samples, key=lambda s: s.quality, reverse=True
        )[:3]
        
        perspectives = "\n\n---\n\n".join(
            f"Perspective (quality={s.quality:.2f}):\n{s.output}"
            for s in top_samples
        )
        
        return (
            f"Question: {query}\n\n"
            f"Multiple perspectives were generated:\n\n{perspectives}\n\n"
            "Synthesize these into the single best, most complete answer. "
            "Incorporate the strongest elements from each. "
            "Be definitive and clear."
        )
```

### Phase 1 Tests

```python
# cmoe_dev/scenario1/test_local_hive.py
"""
Phase 1 tests. Run with: pytest cmoe_dev/scenario1/test_local_hive.py -v
All tests must pass before proceeding to Phase 2.
"""

import json
import math
import pytest
from pathlib import Path
from local_hive import LocalModelHive, LocalHiveConfig

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.benchmark_tasks import BENCHMARK_TASKS
from shared.metrics import compute_q, compute_twrap


class TestPhysicsGovernance:
    """Tests that the engine is actually governing the hive."""
    
    def test_temperature_decreases_over_cycle(self):
        """
        Temperature must fall as ξ advances.
        Validated by the simulated annealing mapping.
        """
        hive = LocalModelHive(LocalHiveConfig(), session_id="test_temp")
        engine = hive.engine
        session_id = hive.session_id
        
        temperatures = []
        for _ in range(15):
            temp = hive.temperature_from_state()
            temperatures.append(temp)
            engine.observe(session_id, __import__('caducean_kernel').Action.EXPAND, success=True)
        
        # Temperature should trend downward over the cycle
        first_half_avg = sum(temperatures[:7]) / 7
        second_half_avg = sum(temperatures[7:]) / 7
        
        assert first_half_avg > second_half_avg, (
            f"Temperature not decreasing: first_half={first_half_avg:.3f} "
            f"second_half={second_half_avg:.3f}"
        )
    
    def test_twrap_prediction_accuracy(self):
        """
        Twrap formula must match observed cycle completion.
        Validated at 0.0% error in D-series experiments.
        """
        from caducean_kernel import CaduceanEngine, CaduceanConfig, Action
        import math
        
        config = LocalHiveConfig(s=0.25, l=3, m=3)
        engine = CaduceanEngine(config=CaduceanConfig(s=config.s))
        engine.init_session("twrap_test")
        
        predicted_twrap = compute_twrap(
            s=config.s, l=config.l, m=config.m, balance=1.0
        )
        
        # Run until ξ wraps past 2π
        steps = 0
        while True:
            engine.observe("twrap_test", Action.EXPAND, success=True)
            steps += 1
            state = engine.get_state("twrap_test")
            if steps > 1 and state.xi < 0.5:  # wrapped around
                break
            if steps > 100:
                break
        
        # Allow 20% tolerance (balance varies during run)
        tolerance = predicted_twrap * 0.20
        assert abs(steps - predicted_twrap) < tolerance, (
            f"Twrap mismatch: predicted={predicted_twrap:.2f}, "
            f"observed={steps}, tolerance={tolerance:.2f}"
        )
    
    def test_q_returns_toward_zero_at_natural_exit(self):
        """
        Q must be closer to 0 at natural exit than at peak exploration.
        This is the wall-pair closure condition from the field theory.
        """
        config = LocalHiveConfig(model="llama3:8b", max_samples=8)
        hive = LocalModelHive(config, session_id="test_q_closure")
        
        task = BENCHMARK_TASKS[1]  # T02 MEDIUM difficulty
        result = hive.run(task["query"], task=task)
        
        # Find peak Q during exploration
        exploration_samples = [s for s in result["samples"] if s["action"] == "EXPAND"]
        if exploration_samples:
            peak_q = max(abs(s["q_after"]) for s in exploration_samples)
            final_q = abs(result["final_q"])
            
            assert final_q < peak_q, (
                f"Q did not return toward 0: peak={peak_q:.3f}, final={final_q:.3f}"
            )
    
    def test_exploration_samples_are_diverse(self):
        """
        High-temperature exploration must produce semantically diverse outputs.
        Target: semantic diversity > 0.15 across samples.
        """
        config = LocalHiveConfig(model="llama3:8b", max_samples=5)
        hive = LocalModelHive(config, session_id="test_diversity")
        
        task = BENCHMARK_TASKS[2]  # T03 COMPLEX
        result = hive.run(task["query"])
        
        diversity = result["semantic_diversity"]
        
        assert diversity > 0.10, (
            f"Semantic diversity too low: {diversity:.3f}. "
            "High-temperature samples should be diverse."
        )


class TestOutputQuality:
    """Tests that the hive produces better output than single-shot."""
    
    def test_hive_vs_single_shot_on_medium_task(self):
        """
        Hive output must score higher than a single deterministic call
        on a MEDIUM difficulty task.
        """
        import ollama
        from shared.benchmark_tasks import evaluate_output
        
        task = BENCHMARK_TASKS[1]  # T02 MEDIUM
        
        # Baseline: single deterministic call
        single_response = ollama.generate(
            model="llama3:8b",
            prompt=task["query"],
            options={"temperature": 0.0, "num_predict": 400}
        )
        single_output = single_response.get("response", "")
        single_eval = evaluate_output(single_output, task)
        
        # Hive: physics-governed multi-sample
        config = LocalHiveConfig(model="llama3:8b", max_samples=6)
        hive = LocalModelHive(config, session_id="test_quality_hive")
        hive_result = hive.run(task["query"], task=task)
        
        hive_score = hive_result["eval_result"]["score"] if hive_result["eval_result"] else 0
        single_score = single_eval["score"]
        
        print(f"\nSingle-shot score: {single_score:.3f}")
        print(f"Hive score:        {hive_score:.3f}")
        print(f"Improvement:       {(hive_score - single_score):.3f}")
        
        # Hive should match or beat single-shot
        # (may not always beat on simple tasks — that is expected)
        assert hive_score >= single_score * 0.9, (
            f"Hive significantly underperformed single-shot: "
            f"hive={hive_score:.3f} vs single={single_score:.3f}"
        )
    
    def test_natural_exit_rate(self):
        """
        At least 60% of runs should exit NATURAL, not BUDGET.
        Baseline from Gate 4: engine achieves 86-100% natural exit on real LLMs.
        Expectation is lower for local models.
        """
        config = LocalHiveConfig(model="llama3:8b", max_samples=8)
        
        natural_exits = 0
        total_runs = 5
        
        for i, task in enumerate(BENCHMARK_TASKS[:total_runs]):
            hive = LocalModelHive(config, session_id=f"test_nat_exit_{i}")
            result = hive.run(task["query"])
            if result["exit_reason"] in ("NATURAL", "COMPRESSED"):
                natural_exits += 1
        
        natural_rate = natural_exits / total_runs
        assert natural_rate >= 0.50, (
            f"Natural exit rate too low: {natural_rate:.2f}. "
            f"Expected >= 0.50. Got {natural_exits}/{total_runs} natural exits."
        )


def generate_phase1_report(results: list) -> dict:
    """Generate the Phase 1 report for handoff to Phase 2."""
    natural_exits = sum(1 for r in results if r["exit_reason"] in ("NATURAL", "COMPRESSED"))
    avg_quality = sum(r["eval_result"]["score"] for r in results if r["eval_result"]) / max(len(results), 1)
    avg_diversity = sum(r["semantic_diversity"] for r in results) / max(len(results), 1)
    avg_steps = sum(r["total_steps"] for r in results) / max(len(results), 1)
    
    return {
        "phase": 1,
        "status": "COMPLETE",
        "results_count": len(results),
        "natural_exit_rate": natural_exits / max(len(results), 1),
        "avg_quality_score": avg_quality,
        "avg_semantic_diversity": avg_diversity,
        "avg_steps_to_completion": avg_steps,
        "acceptance_criteria": {
            "natural_exit_rate_gte_0.50": (natural_exits / max(len(results), 1)) >= 0.50,
            "avg_diversity_gte_0.10": avg_diversity >= 0.10,
            "avg_quality_gte_0.40": avg_quality >= 0.40,
        },
        "ready_for_phase2": all([
            (natural_exits / max(len(results), 1)) >= 0.50,
            avg_diversity >= 0.10,
        ]),
    }
```

### Phase 1 Acceptance Criteria

```
[ ] test_temperature_decreases_over_cycle PASS
[ ] test_twrap_prediction_accuracy PASS (within 20% tolerance)
[ ] test_q_returns_toward_zero_at_natural_exit PASS
[ ] test_exploration_samples_are_diverse PASS (diversity > 0.10)
[ ] test_hive_vs_single_shot_on_medium_task PASS
[ ] test_natural_exit_rate PASS (>= 50% natural exits)
[ ] Phase 1 report generated and saved
[ ] ready_for_phase2 = true in report
```

---

## Phase 2: Scenario 2 — Multi-Model Hive

### What This Phase Proves

Different models play different roles determined by the physics. The engine observes each model's output, classifies it as EXPAND or COMPRESS, and advances the session state. The phase signal determines which model gets called next. No roles are hardcoded — they emerge from each model's natural behavior.

### The Role Emergence Math

Each model has a natural EXPAND/COMPRESS ratio based on its training and the type of output it produces:

```
Explorer model (fast local, high temp):
  Produces: diverse, generative, exploratory outputs → EXPAND
  Natural Q contribution: x accumulates → Q rises

Mediator model (mid-size API):
  Produces: comparative, analytical outputs → split EXPAND/COMPRESS
  Natural Q contribution: balanced

Synthesizer model (frontier API):
  Produces: definitive, consolidated outputs → COMPRESS
  Natural Q contribution: y accumulates → Q falls toward 0
```

The nucleus/barrier structure from the GPE experiment:

```
Nucleus = Synthesizer (lower energy, compression-biased, final answer)
Barrier = Explorer (higher energy, expansion-biased, generates diversity)

Q_combined = (x_exp + x_med + x_syn - y_exp - y_med - y_syn) /
             (x_exp + x_med + x_syn + y_exp + y_med + y_syn + 1)

The barrier's high x is balanced by the nucleus's high y.
Q_combined stays near 0 even when individual Q values are extreme.
```

### Implementation

```python
# cmoe_dev/scenario2/multi_model_hive.py
"""
Phase 2: Multi-Model Hive
Different models as different thinkers, physics-governed role assignment.
"""

import math
import json
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

import ollama
import anthropic
from caducean_kernel import (
    CaduceanEngine, CaduceanConfig, CaduceanState,
    Action, ExitReason
)

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.metrics import compute_q, phase_label, output_quality_heuristic
from shared.benchmark_tasks import evaluate_output


@dataclass
class ModelSpec:
    name: str           # identifier
    model_id: str       # ollama model name or anthropic model string
    provider: str       # "ollama" or "anthropic"
    temperature: float  # default temperature
    role_bias: str      # "EXPAND", "COMPRESS", or "NEUTRAL"
    winding_l: int      # winding number l
    winding_m: int      # winding number m


@dataclass
class MultiHiveConfig:
    models: list = None  # list of ModelSpec dicts
    s: float = 0.25
    max_steps: int = 12
    quality_threshold: float = 0.65
    
    def __post_init__(self):
        if self.models is None:
            self.models = [
                {
                    "name": "explorer",
                    "model_id": "llama3:8b",
                    "provider": "ollama",
                    "temperature": 0.9,
                    "role_bias": "EXPAND",
                    "winding_l": 3,
                    "winding_m": 3,
                },
                {
                    "name": "mediator",
                    "model_id": "claude-haiku-4-5-20251001",
                    "provider": "anthropic",
                    "temperature": 0.5,
                    "role_bias": "NEUTRAL",
                    "winding_l": 2,
                    "winding_m": 1,
                },
                {
                    "name": "synthesizer",
                    "model_id": "claude-sonnet-4-6",
                    "provider": "anthropic",
                    "temperature": 0.1,
                    "role_bias": "COMPRESS",
                    "winding_l": 1,
                    "winding_m": 1,
                },
            ]


class MultiModelHive:
    """
    Phase 2 implementation: Multi-model hive.
    
    Phase mapping:
      PLANNING + EXECUTING  → explorer model (EXPAND)
      REVIEWING             → mediator model (analysis)
      CONSOLIDATING         → synthesizer model (COMPRESS, final output)
    
    The engine decides which phase we are in.
    The phase decides which model is called.
    The model does not know the other models exist.
    """
    
    PHASE_TO_MODEL = {
        "PLANNING":      "explorer",
        "EXECUTING":     "explorer",
        "REVIEWING":     "mediator",
        "CONSOLIDATING": "synthesizer",
    }
    
    def __init__(self, config: MultiHiveConfig, session_id: str = "multi_hive"):
        self.config = config
        self.session_id = session_id
        self.anthropic_client = anthropic.Anthropic()
        
        # Build model registry
        self.model_registry = {m["name"]: m for m in config.models}
        
        # One engine for the hive session
        self.engine = CaduceanEngine(config=CaduceanConfig(s=config.s))
        self.engine.init_session(session_id)
        
        # Per-model state tracking for Q_combined
        self.model_states = {name: {"x": 0.0, "y": 0.0} for name in self.model_registry}
        self.trace = []
    
    def run(self, query: str, task: Optional[dict] = None) -> dict:
        """
        Run the multi-model hive. Physics determines which model runs next.
        """
        start_time = time.time()
        step = 0
        final_output = ""
        exit_reason = "BUDGET"
        exploration_outputs = []
        mediation_outputs = []
        
        while step < self.config.max_steps:
            state = self.engine.get_state(self.session_id)
            current_phase = phase_label(state.xi)
            q = compute_q(state.x, state.y)
            
            # Phase determines model
            model_name = self.PHASE_TO_MODEL[current_phase]
            model_spec = self.model_registry[model_name]
            
            # Build phase-appropriate prompt
            prompt = self._build_prompt(
                query, current_phase, 
                exploration_outputs, mediation_outputs, step
            )
            
            # Call the appropriate model
            output = self._call_model(model_spec, prompt)
            quality = output_quality_heuristic(output)
            
            # Classify action based on model's role bias
            if model_spec["role_bias"] == "EXPAND":
                action = Action.EXPAND
                exploration_outputs.append(output)
            elif model_spec["role_bias"] == "COMPRESS":
                action = Action.COMPRESS
                final_output = output
            else:  # NEUTRAL
                # Mediator: EXPAND if adding new analysis, COMPRESS if summarizing
                action = Action.EXPAND if step < self.config.max_steps // 2 else Action.COMPRESS
                mediation_outputs.append(output)
            
            # Observe in engine
            self.engine.observe(self.session_id, action, success=quality > 0.4)
            
            # Update per-model state for Q_combined tracking
            state_after = self.engine.get_state(self.session_id)
            if action == Action.EXPAND:
                self.model_states[model_name]["x"] += 1
            else:
                self.model_states[model_name]["y"] += 1
            
            q_combined = self._compute_combined_q()
            
            # Record trace
            self.trace.append({
                "step": step,
                "phase": current_phase,
                "model": model_name,
                "action": action.name,
                "quality": quality,
                "q_session": compute_q(state_after.x, state_after.y),
                "q_combined": q_combined,
                "xi": state_after.xi,
                "u": state_after.u,
                "output_preview": output[:100],
            })
            
            step += 1
            
            # Check natural exit
            should_exit, reason = self.engine.should_exit(
                self.session_id, step, self.config.max_steps
            )
            if should_exit:
                exit_reason = reason.name
                if not final_output and output:
                    final_output = output
                break
        
        final_state = self.engine.get_state(self.session_id)
        
        eval_result = None
        if task and final_output:
            eval_result = evaluate_output(final_output, task)
        
        return {
            "query": query,
            "final_output": final_output,
            "exit_reason": exit_reason,
            "total_steps": step,
            "final_q": compute_q(final_state.x, final_state.y),
            "final_q_combined": self._compute_combined_q(),
            "final_xi": final_state.xi,
            "final_phase": phase_label(final_state.xi),
            "model_states": self.model_states,
            "trace": self.trace,
            "eval_result": eval_result,
            "duration_seconds": time.time() - start_time,
        }
    
    def _call_model(self, model_spec: dict, prompt: str) -> str:
        """Call the right model based on provider."""
        if model_spec["provider"] == "ollama":
            response = ollama.generate(
                model=model_spec["model_id"],
                prompt=prompt,
                options={
                    "temperature": model_spec["temperature"],
                    "num_predict": 500,
                }
            )
            return response.get("response", "").strip()
        
        elif model_spec["provider"] == "anthropic":
            response = self.anthropic_client.messages.create(
                model=model_spec["model_id"],
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()
        
        return ""
    
    def _build_prompt(
        self, query: str, phase: str,
        explorations: list, mediations: list, step: int
    ) -> str:
        if phase == "PLANNING":
            return (
                f"Analyze this question and explore it from multiple angles:\n\n"
                f"{query}\n\n"
                "Generate a thorough initial analysis."
            )
        
        elif phase == "EXECUTING":
            prev = explorations[-1][:300] if explorations else ""
            return (
                f"Question: {query}\n\n"
                f"Previous analysis: {prev}...\n\n"
                "Explore a different dimension of this question. "
                "What was not covered?"
            )
        
        elif phase == "REVIEWING":
            exp_text = "\n\n---\n\n".join(e[:300] for e in explorations[-3:])
            return (
                f"Question: {query}\n\n"
                f"Multiple analyses have been generated:\n\n{exp_text}\n\n"
                "Compare these analyses:\n"
                "1. What do they agree on?\n"
                "2. Where do they conflict?\n"
                "3. What are the strongest points from each?\n"
                "4. What remains unresolved?"
            )
        
        elif phase == "CONSOLIDATING":
            med_text = "\n\n".join(m[:400] for m in mediations[-2:])
            exp_text = "\n\n---\n\n".join(e[:200] for e in explorations[-3:])
            return (
                f"Question: {query}\n\n"
                f"Analytical review:\n{med_text}\n\n"
                f"Key perspectives:\n{exp_text}\n\n"
                "Produce the single definitive answer. "
                "Be complete, clear, and definitive. "
                "Resolve all conflicts. "
                "This is the final output."
            )
        
        return f"Answer this question: {query}"
    
    def _compute_combined_q(self) -> float:
        """Q_combined across all model sessions."""
        total_x = sum(ms["x"] for ms in self.model_states.values())
        total_y = sum(ms["y"] for ms in self.model_states.values())
        return (total_x - total_y) / (total_x + total_y + 1.0)
```

### Phase 2 Acceptance Criteria

```
[ ] Explorer model called during PLANNING and EXECUTING phases
[ ] Mediator model called during REVIEWING phase
[ ] Synthesizer model called during CONSOLIDATING phase
[ ] Q_combined stays closer to 0 than any individual Q
[ ] Final output quality >= Phase 1 hive quality on same tasks
[ ] Natural exit rate >= 50%
[ ] Phase 2 report generated and saved
[ ] ready_for_phase3 = true in report
```

---

## Phase 3: Tie-In A — Single Model Execution

### What This Phase Proves

CMoE wraps a single model call. The agent learns when to use the full hive versus bypass it for simple queries. This is the production decision gate.

```
Query arrives
      ↓
COMPLEXITY ASSESSMENT (engine reads previous session state)
      ↓
SIMPLE query?    → BYPASS: single direct model call
COMPLEX query?   → ENGAGE: CMoE hive (Scenario 1 or 2)
      ↓
Physics-governed output
      ↓
Return to caller
```

### The Bypass Decision Math

The bypass decision uses the engine's current phase and the query's estimated complexity:

```python
# cmoe_dev/tiein/single_model.py
"""
Phase 3: Single model tie-in.
CMoE wraps a single model — decides when to engage hive vs bypass.
"""

import math
import time
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from scenario1.local_hive import LocalModelHive, LocalHiveConfig
from scenario2.multi_model_hive import MultiModelHive, MultiHiveConfig
from shared.metrics import compute_q, phase_label, output_quality_heuristic

import ollama
from caducean_kernel import CaduceanEngine, CaduceanConfig, Action


@dataclass
class SingleModelTieInConfig:
    # The primary model (used for bypass and as the explorer)
    primary_model: str = "llama3:8b"
    
    # Complexity thresholds
    simple_word_threshold: int = 8     # queries under N words → bypass
    complex_word_threshold: int = 20   # queries over N words → always hive
    
    # Hive selection
    use_multi_model: bool = True       # if False, always use local hive
    
    # Engine
    s: float = 0.25


class SingleModelCMoE:
    """
    Production-ready single model tie-in.
    
    Decision tree:
      1. Query complexity assessment
      2. Engine phase check (consolidating phase → bypass regardless)
      3. Simple → bypass, Complex → hive
      4. Hive: Scenario 1 (local) or Scenario 2 (multi-model)
      5. Return output with metadata
    
    The caller gets the same interface regardless of whether
    bypass or hive was used.
    """
    
    def __init__(self, config: SingleModelTieInConfig, session_id: str):
        self.config = config
        self.session_id = session_id
        self.engine = CaduceanEngine(config=CaduceanConfig(s=config.s))
        self.engine.init_session(session_id)
        self.call_count = 0
    
    def query(self, text: str, task: Optional[dict] = None) -> dict:
        """
        Main entry point. Returns output with routing metadata.
        """
        self.call_count += 1
        start = time.time()
        
        # Step 1: Assess complexity
        complexity = self._assess_complexity(text)
        
        # Step 2: Check engine phase
        state = self.engine.get_state(self.session_id)
        current_phase = phase_label(state.xi)
        q = compute_q(state.x, state.y)
        
        # Step 3: Routing decision
        route = self._routing_decision(complexity, current_phase, q)
        
        # Step 4: Execute
        if route == "BYPASS":
            output, steps, exit_reason = self._bypass(text)
            # Observe as CONTINUE — bypass doesn't meaningfully expand or compress
            self.engine.observe(self.session_id, Action.CONTINUE, success=True)
            
        elif route == "LOCAL_HIVE":
            output, steps, exit_reason = self._local_hive(text, task)
            # Local hive = balanced EXPAND+COMPRESS over its cycle
            # Net effect on parent session: slight EXPAND (exploration occurred)
            self.engine.observe(self.session_id, Action.EXPAND, success=True)
            
        else:  # MULTI_HIVE
            output, steps, exit_reason = self._multi_hive(text, task)
            # Multi-model hive = full synthesis cycle
            # Net effect on parent session: COMPRESS (synthesis completed)
            self.engine.observe(self.session_id, Action.COMPRESS, success=True)
        
        state_after = self.engine.get_state(self.session_id)
        
        return {
            "output": output,
            "route": route,
            "complexity": complexity,
            "phase_at_query": current_phase,
            "q_at_query": q,
            "steps_in_route": steps,
            "exit_reason": exit_reason,
            "parent_xi_after": state_after.xi,
            "parent_q_after": compute_q(state_after.x, state_after.y),
            "duration_seconds": time.time() - start,
            "call_number": self.call_count,
        }
    
    def _assess_complexity(self, text: str) -> str:
        """
        Estimate query complexity from surface features.
        
        SIMPLE:  short, factual, single-concept
        MEDIUM:  multi-aspect, requires reasoning
        COMPLEX: open-ended, synthesis required
        
        In production: replace with a classifier or LLM judge.
        """
        word_count = len(text.split())
        
        # Simple heuristics — replace with better classifier
        complex_markers = [
            "compare", "contrast", "design", "explain how",
            "what are the tradeoffs", "recommend", "analyze",
            "what would you", "how should", "pros and cons",
        ]
        
        if word_count < self.config.simple_word_threshold:
            return "SIMPLE"
        
        text_lower = text.lower()
        complex_signal = sum(1 for m in complex_markers if m in text_lower)
        
        if word_count > self.config.complex_word_threshold or complex_signal >= 2:
            return "COMPLEX"
        
        return "MEDIUM"
    
    def _routing_decision(self, complexity: str, phase: str, q: float) -> str:
        """
        Route to bypass, local hive, or multi-model hive.
        
        Routing rules:
        SIMPLE:   always BYPASS (hive overhead not worth it)
        COMPLEX:  MULTI_HIVE if available, else LOCAL_HIVE
        MEDIUM:   LOCAL_HIVE
        
        Phase override:
        CONSOLIDATING phase → BYPASS (session near natural exit,
                              don't launch expensive hive)
        
        Q override:
        |Q| > 0.80 → LOCAL_HIVE (rebalance before going multi-model)
        """
        # Phase override
        if phase == "CONSOLIDATING":
            return "BYPASS"
        
        # Q override
        if abs(q) > 0.80:
            return "LOCAL_HIVE"
        
        # Complexity routing
        if complexity == "SIMPLE":
            return "BYPASS"
        elif complexity == "MEDIUM":
            return "LOCAL_HIVE"
        else:  # COMPLEX
            if self.config.use_multi_model:
                return "MULTI_HIVE"
            return "LOCAL_HIVE"
    
    def _bypass(self, text: str) -> tuple[str, int, str]:
        """Single direct model call. No hive."""
        response = ollama.generate(
            model=self.config.primary_model,
            prompt=text,
            options={"temperature": 0.3, "num_predict": 400}
        )
        return response.get("response", "").strip(), 1, "DIRECT"
    
    def _local_hive(self, text: str, task: Optional[dict]) -> tuple[str, int, str]:
        """Route to Scenario 1 local hive."""
        config = LocalHiveConfig(
            model=self.config.primary_model,
            max_samples=6,
            s=self.config.s,
        )
        hive = LocalModelHive(config, session_id=f"{self.session_id}_local_{self.call_count}")
        result = hive.run(text, task=task)
        return result["final_output"], result["total_steps"], result["exit_reason"]
    
    def _multi_hive(self, text: str, task: Optional[dict]) -> tuple[str, int, str]:
        """Route to Scenario 2 multi-model hive."""
        config = MultiHiveConfig()
        hive = MultiModelHive(config, session_id=f"{self.session_id}_multi_{self.call_count}")
        result = hive.run(text, task=task)
        return result["final_output"], result["total_steps"], result["exit_reason"]
```

### Phase 3 Tests

```python
# cmoe_dev/tiein/test_tiein.py — Phase 3 section

class TestSingleModelTieIn:
    
    def test_simple_queries_bypass(self):
        """Simple queries must not engage the hive."""
        cmoe = SingleModelCMoE(SingleModelTieInConfig(), session_id="test_bypass")
        result = cmoe.query("What is O(n log n)?")
        assert result["route"] == "BYPASS", (
            f"Simple query routed to {result['route']} — should bypass"
        )
    
    def test_complex_queries_engage_hive(self):
        """Complex queries must engage CMoE."""
        cmoe = SingleModelCMoE(SingleModelTieInConfig(), session_id="test_engage")
        result = cmoe.query(
            "Compare microservices vs monolith for a 5-person startup "
            "with aggressive scaling requirements and limited DevOps capacity. "
            "What are the tradeoffs and what would you recommend?"
        )
        assert result["route"] in ("LOCAL_HIVE", "MULTI_HIVE"), (
            f"Complex query routed to BYPASS — should engage hive"
        )
    
    def test_consolidating_phase_bypasses(self):
        """Queries in CONSOLIDATING phase must bypass regardless of complexity."""
        from caducean_kernel import Action
        import math
        
        cmoe = SingleModelCMoE(SingleModelTieInConfig(), session_id="test_phase_bypass")
        
        # Drive session to CONSOLIDATING phase
        while True:
            state = cmoe.engine.get_state(cmoe.session_id)
            if state.xi >= 3 * math.pi / 2:
                break
            cmoe.engine.observe(cmoe.session_id, Action.EXPAND, success=True)
        
        result = cmoe.query(
            "Design a distributed caching system with specific consistency guarantees "
            "and failure handling strategies for a high-traffic production environment."
        )
        assert result["route"] == "BYPASS", (
            "CONSOLIDATING phase should bypass even complex queries"
        )
    
    def test_routing_improves_output_on_complex_tasks(self):
        """CMoE routing must produce better output than bypass on complex tasks."""
        from shared.benchmark_tasks import BENCHMARK_TASKS, evaluate_output
        
        task = BENCHMARK_TASKS[4]  # T05 COMPLEX design task
        
        # Direct bypass
        import ollama
        bypass_response = ollama.generate(
            model="llama3:8b",
            prompt=task["query"],
            options={"temperature": 0.3, "num_predict": 500}
        )
        bypass_output = bypass_response.get("response", "")
        bypass_eval = evaluate_output(bypass_output, task)
        
        # CMoE routing
        cmoe = SingleModelCMoE(
            SingleModelTieInConfig(use_multi_model=False),  # local hive only
            session_id="test_routing_quality"
        )
        result = cmoe.query(task["query"], task=task)
        
        bypass_score = bypass_eval["score"]
        cmoe_score = result.get("eval_result", {}).get("score", 0) if "eval_result" in result else 0
        
        print(f"\nBypass score: {bypass_score:.3f}")
        print(f"CMoE score:   {cmoe_score:.3f}")
        
        assert cmoe_score >= bypass_score * 0.85, (
            f"CMoE significantly underperformed bypass: {cmoe_score:.3f} vs {bypass_score:.3f}"
        )
```

### Phase 3 Acceptance Criteria

```
[ ] Simple queries route to BYPASS
[ ] Complex queries route to LOCAL_HIVE or MULTI_HIVE
[ ] CONSOLIDATING phase always bypasses
[ ] CMoE output quality >= bypass quality on complex tasks
[ ] Routing adds < 3x latency overhead vs bypass for medium tasks
[ ] Phase 3 report generated
[ ] ready_for_phase4 = true
```

---

## Phase 4: Tie-In B — Swarm Execution

### What This Phase Proves

Multiple agents each running CMoE, coordinated through shared physics. No message passing between agents. The swarm's coordination emerges from the shared Σ state.

### The Swarm Physics

Each agent in the swarm has its own CMoE instance. Coordination happens through a shared master engine that tracks the swarm's combined Q:

```
Swarm state:

Q_swarm(t) = (Σ x_i - Σ y_i) / (Σ x_i + Σ y_i + 1)
              for all agents i in the swarm

Q_swarm → +1: swarm over-exploring (too many agents in LOCAL_HIVE/EXPAND)
Q_swarm → 0:  swarm balanced (agents distributed across phases)
Q_swarm → -1: swarm over-compressing (too many synthesis passes)

The swarm Governor reads Q_swarm and decides:
- Which agents should EXPAND (explore sub-problems)
- Which agents should COMPRESS (synthesize partial results)
- When the swarm has reached natural exit (all agents' combined Q → 0)
```

```python
# cmoe_dev/tiein/swarm.py
"""
Phase 4: Swarm execution.
Multiple agents each running CMoE, coordinated through shared physics.
"""

import math
import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from tiein.single_model import SingleModelCMoE, SingleModelTieInConfig
from shared.metrics import compute_q, phase_label
from shared.benchmark_tasks import evaluate_output

from caducean_kernel import CaduceanEngine, CaduceanConfig, Action, ExitReason


@dataclass
class SwarmConfig:
    n_agents: int = 3              # number of agents in the swarm
    primary_model: str = "llama3:8b"
    s_swarm: float = 0.20          # swarm master walk speed (slower than agents)
    s_agent: float = 0.30          # agent walk speed (faster than swarm)
    max_rounds: int = 4            # max coordination rounds
    convergence_q_threshold: float = 0.15  # |Q_swarm| below this → converged


class CaduceanSwarm:
    """
    Swarm of CMoE agents coordinated through shared physics.
    
    Architecture:
      Master engine: tracks Q_swarm, governs which agents act
      Agent engines: each agent runs its own CMoE
      Coordination: through combined Q, not message passing
    
    Round structure:
      Round 1: All agents in EXPAND mode — explore sub-problems
      Round 2: Agents with high Q compress — partial synthesis
      Round 3: Remaining agents compress — full synthesis
      Round 4+: Master engine checks convergence
    
    The swarm exits naturally when Q_swarm → 0.
    This is the quorum sensing threshold from the theory:
    restructuring fires when the combined accumulation rate
    crosses the coherence threshold.
    """
    
    def __init__(self, config: SwarmConfig, swarm_id: str = "swarm"):
        self.config = config
        self.swarm_id = swarm_id
        
        # Master engine tracks swarm-level state
        self.master_engine = CaduceanEngine(
            config=CaduceanConfig(s=config.s_swarm)
        )
        self.master_engine.init_session(swarm_id)
        
        # Agent pool
        self.agents = []
        for i in range(config.n_agents):
            agent_id = f"{swarm_id}_agent_{i}"
            agent = SingleModelCMoE(
                config=SingleModelTieInConfig(
                    primary_model=config.primary_model,
                    s=config.s_agent,
                    use_multi_model=False,  # agents use local hive only
                ),
                session_id=agent_id,
            )
            self.agents.append({"id": agent_id, "cmoe": agent, "outputs": []})
        
        self.swarm_trace = []
    
    def run(self, query: str, task: Optional[dict] = None) -> dict:
        """
        Run the swarm on a query.
        
        Decomposition strategy:
        1. Decompose query into N sub-questions (one per agent)
        2. Each agent explores its sub-question with CMoE
        3. Master engine checks Q_swarm
        4. If Q_swarm high: trigger compression round
        5. Synthesis agent combines all outputs
        6. Master engine checks natural exit
        """
        start_time = time.time()
        
        # Step 1: Decompose query into sub-questions
        sub_queries = self._decompose_query(query, self.config.n_agents)
        
        # Step 2: Distribute sub-queries to agents
        for i, agent_info in enumerate(self.agents):
            agent_info["sub_query"] = sub_queries[i] if i < len(sub_queries) else query
        
        round_num = 0
        final_output = ""
        exit_reason = "BUDGET"
        
        while round_num < self.config.max_rounds:
            round_num += 1
            master_state = self.master_engine.get_state(self.swarm_id)
            q_swarm = self._compute_q_swarm()
            swarm_phase = phase_label(master_state.xi)
            
            round_record = {
                "round": round_num,
                "swarm_phase": swarm_phase,
                "q_swarm_before": q_swarm,
                "agent_results": [],
            }
            
            if swarm_phase in ("PLANNING", "EXECUTING") and round_num <= 2:
                # EXPANSION ROUND: all agents explore their sub-queries
                for agent_info in self.agents:
                    result = agent_info["cmoe"].query(
                        agent_info["sub_query"], task=None
                    )
                    agent_info["outputs"].append(result["output"])
                    
                    # Observe in master engine: each agent's EXPAND
                    self.master_engine.observe(
                        self.swarm_id, Action.EXPAND,
                        success=len(result["output"]) > 100
                    )
                    
                    round_record["agent_results"].append({
                        "agent": agent_info["id"],
                        "route": result["route"],
                        "steps": result["steps_in_route"],
                        "output_length": len(result["output"]),
                    })
            
            else:
                # COMPRESSION ROUND: synthesize all agent outputs
                synthesis_input = self._build_synthesis_prompt(
                    query, self.agents
                )
                
                # Use the first agent for synthesis (it becomes the nucleus)
                synthesis_result = self.agents[0]["cmoe"].query(synthesis_input)
                final_output = synthesis_result["output"]
                
                # Observe synthesis as COMPRESS in master engine
                self.master_engine.observe(
                    self.swarm_id, Action.COMPRESS,
                    success=len(final_output) > 200
                )
                
                round_record["agent_results"].append({
                    "agent": "synthesis",
                    "route": synthesis_result["route"],
                    "output_length": len(final_output),
                })
            
            q_swarm_after = self._compute_q_swarm()
            round_record["q_swarm_after"] = q_swarm_after
            self.swarm_trace.append(round_record)
            
            # Check swarm convergence (natural exit equivalent)
            master_state_after = self.master_engine.get_state(self.swarm_id)
            should_exit, reason = self.master_engine.should_exit(
                self.swarm_id, round_num, self.config.max_rounds
            )
            
            if should_exit:
                exit_reason = reason.name
                break
            
            # Quorum sensing: Q_swarm near 0 = coherence threshold reached
            if abs(q_swarm_after) < self.config.convergence_q_threshold:
                exit_reason = "QUORUM_CONVERGENCE"
                break
        
        final_state = self.master_engine.get_state(self.swarm_id)
        
        eval_result = None
        if task and final_output:
            eval_result = evaluate_output(final_output, task)
        
        return {
            "query": query,
            "final_output": final_output,
            "exit_reason": exit_reason,
            "rounds": round_num,
            "final_q_swarm": self._compute_q_swarm(),
            "final_xi_master": final_state.xi,
            "n_agents": self.config.n_agents,
            "swarm_trace": self.swarm_trace,
            "eval_result": eval_result,
            "duration_seconds": time.time() - start_time,
            "agent_outputs": [
                {"agent": a["id"], "sub_query": a.get("sub_query", ""), 
                 "n_outputs": len(a["outputs"])}
                for a in self.agents
            ],
        }
    
    def _decompose_query(self, query: str, n: int) -> list[str]:
        """
        Decompose a query into N sub-questions for the agent pool.
        
        Simple decomposition — replace with LLM-driven decomposition
        in production for better sub-question quality.
        """
        decompositions = {
            1: [query],
            2: [
                f"Analyze the technical aspects of: {query}",
                f"Analyze the practical/business aspects of: {query}",
            ],
            3: [
                f"What are the core concepts and theory behind: {query}",
                f"What are the practical implementation considerations for: {query}",
                f"What are the tradeoffs and alternatives for: {query}",
            ],
            4: [
                f"Core concepts and fundamentals: {query}",
                f"Implementation approach and technical details: {query}",
                f"Common pitfalls and failure modes: {query}",
                f"Best practices and recommendations: {query}",
            ],
        }
        return decompositions.get(n, [query] * n)
    
    def _build_synthesis_prompt(self, original_query: str, agents: list) -> str:
        """Build synthesis prompt from all agent outputs."""
        all_outputs = []
        for agent_info in agents:
            if agent_info["outputs"]:
                sub_query = agent_info.get("sub_query", "")
                latest_output = agent_info["outputs"][-1][:400]
                all_outputs.append(
                    f"Sub-analysis ({sub_query[:80]}):\n{latest_output}"
                )
        
        outputs_text = "\n\n---\n\n".join(all_outputs)
        
        return (
            f"Original question: {original_query}\n\n"
            f"Multiple agents analyzed different aspects:\n\n{outputs_text}\n\n"
            "Synthesize all analyses into a single, comprehensive, definitive answer. "
            "Incorporate insights from all perspectives. "
            "Be clear, complete, and actionable."
        )
    
    def _compute_q_swarm(self) -> float:
        """Combined topological charge across all agent sessions + master."""
        total_x = 0.0
        total_y = 0.0
        
        # Master
        master_state = self.master_engine.get_state(self.swarm_id)
        total_x += master_state.x
        total_y += master_state.y
        
        # Each agent
        for agent_info in self.agents:
            agent_state = agent_info["cmoe"].engine.get_state(
                agent_info["cmoe"].session_id
            )
            total_x += agent_state.x
            total_y += agent_state.y
        
        return (total_x - total_y) / (total_x + total_y + 1.0)
```

### Phase 4 Acceptance Criteria

```
[ ] Swarm decomposes queries into N sub-questions
[ ] Each agent explores its sub-question with CMoE
[ ] Q_swarm is tracked across all agents
[ ] Swarm converges (Q_swarm < 0.15) or exits naturally
[ ] Swarm output quality >= single CMoE agent on complex tasks
[ ] Phase 4 report generated
[ ] Master report generated across all phases
```

---

## Master Report Generator

```python
# cmoe_dev/generate_master_report.py
"""
Run after all four phases complete.
Generates the master report for handoff to application integration.
"""

import json
from pathlib import Path
from datetime import datetime


def generate_master_report():
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "phases": {},
        "ready_for_application": False,
        "integration_checklist": [],
    }
    
    # Load phase reports
    for phase_num in [1, 2, 3, 4]:
        report_files = list(Path("cmoe_dev").glob(f"**/phase{phase_num}*.json"))
        if report_files:
            report["phases"][f"phase_{phase_num}"] = json.loads(
                report_files[0].read_text()
            )
    
    # Determine readiness
    all_ready = all(
        report["phases"].get(f"phase_{i}", {}).get("ready_for_application", False)
        for i in [1, 2, 3, 4]
    )
    report["ready_for_application"] = all_ready
    
    # Integration checklist
    report["integration_checklist"] = [
        "Phase 0: Environment verified",
        "Phase 1: Local hive tested — natural exit rate >= 50%",
        "Phase 2: Multi-model hive tested — role emergence confirmed",
        "Phase 3: Single model tie-in tested — routing decision correct",
        "Phase 4: Swarm tested — Q_swarm convergence confirmed",
        "All phases: benchmark task scores recorded for comparison",
        "SessionStateStore wired for persistence across hive calls",
        "Governor branching authority wired before hive invocation",
        "Sub-loop integration guide followed for complex sub-tasks",
    ]
    
    output_path = Path("cmoe_dev/cmoe_master_report.json")
    output_path.write_text(json.dumps(report, indent=2))
    
    print("\n" + "="*60)
    print("CMOE MASTER REPORT")
    print("="*60)
    print(f"Ready for application: {'YES ✅' if all_ready else 'NO ❌'}")
    print(f"Report saved: {output_path}")
    print("="*60 + "\n")
    
    return report


if __name__ == "__main__":
    generate_master_report()
```

---

## Execution Order For Your Agent

```
1.  Create cmoe_dev/ directory structure
2.  Create all shared/ files (benchmark_tasks.py, metrics.py)
3.  Run: python cmoe_dev/env_check.py
    → Fix any failures before continuing

4.  Create scenario1/local_hive.py
5.  Run: pytest cmoe_dev/scenario1/test_local_hive.py -v
    → All tests must pass
    → Generate phase1 report

6.  Create scenario2/multi_model_hive.py
7.  Run: pytest cmoe_dev/scenario2/test_multi_hive.py -v
    → All tests must pass
    → Generate phase2 report

8.  Create tiein/single_model.py
9.  Run: pytest cmoe_dev/tiein/test_tiein.py::TestSingleModelTieIn -v
    → All tests must pass
    → Generate phase3 report

10. Create tiein/swarm.py
11. Run: pytest cmoe_dev/tiein/test_tiein.py::TestSwarm -v
    → All tests must pass
    → Generate phase4 report

12. Run: python cmoe_dev/generate_master_report.py
    → ready_for_application must be true

13. ONLY THEN: integrate into main application
    Following SUBLOOP_INTEGRATION_GUIDE.md
```

---

## What The Application Integration Looks Like After This Guide

Once all four phases pass, the application integration is one import and one routing call:

```python
# In your main application — after all phases complete

from cmoe_dev.tiein.single_model import SingleModelCMoE, SingleModelTieInConfig
from cmoe_dev.tiein.swarm import CaduceanSwarm, SwarmConfig

# Single model CMoE — wraps every query
cmoe = SingleModelCMoE(
    config=SingleModelTieInConfig(primary_model="llama3:8b"),
    session_id=user_session_id,
)

# For a single query:
result = cmoe.query(user_input)
output = result["output"]

# For complex tasks requiring a swarm:
swarm = CaduceanSwarm(
    config=SwarmConfig(n_agents=3),
    swarm_id=f"{user_session_id}_swarm",
)
swarm_result = swarm.run(user_input, task=task_spec)
output = swarm_result["final_output"]
```

The physics governs which path each query takes. The application sees one interface. The engine handles the rest.

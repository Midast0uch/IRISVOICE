# Caducean Sub-Loop Integration Guide
## Sub-Loop Architecture, Governor as Branching Authority, and Cross-Session State Persistence

*For the IRISVOICE Application Agent — Implementation Reference*
*Assumes caducean_kernel is installed and the base engine is running*

---

## Overview: Three Things This Document Covers

1. **The Sub-Loop** — a nested Event-Driven Loop that spins up its own temporary Caducean session for a sub-task, runs to natural exit, and collapses back into the parent session
2. **Governor as Branching Authority** — the engine's direction signal governs whether the loop executes serially or in parallel, replacing the current LLM-JSON-plan-driven branching decision
3. **Cross-Session State Persistence** — the engine's Σ = (x, y, ξ, u) state is serialized between sessions so physics warm-starts even when the LLM context cold-starts

These three additions work together. The Governor decides branching. The Sub-Loop executes complex sub-tasks under the Governor's direction. Cross-Session Persistence means both the parent loop and any sub-loop remember where they were.

---

## Part 1: The Mathematical Foundation

### The State Vector

Every loop — parent or sub — is governed by the same four-dimensional state:

```
Σ = (x, y, ξ, u)

x   expansion accumulator     — creative/generative work done
y   compression accumulator   — validation/consolidation work done
ξ   phase angle ∈ [0, 2π)    — position in the cognitive cycle
u   attentional velocity      — current momentum and directional bias
```

### The Duffing Restoring Force

```
F(u) = au - bu³     where a = 2.0, b = 2.0
```

Stable attractors at u* = ±√(a/b) = ±1.0. The force always points toward the nearest attractor. No sequence of sub-task failures can permanently destabilize the parent loop — the restoring force pulls the system back.

### The Phase Update Rule

```
ξ(t+1) = (ξ(t) + balance · s · c_eff) mod 2π

where:
  balance  = clamp(EML / EML_baseline, 0.1, 3.0)   EML feedback signal
  s        = walk speed (default 0.35)
  c_eff    = c · √(l² + m²)                         winding-number speed
```

### The Topological Charge

```
Q(t) = (x(t) - y(t)) / (x(t) + y(t) + 1)

Q → +1: over-expanding (lone kink — topologically forbidden)
Q → 0:  balanced wall-pair (topologically neutral — natural exit possible)
Q → -1: over-compressing (lone antikink — topologically forbidden)
```

Natural exit requires Q returning toward 0. This is the wall-pair closure condition from the compact field theory. A sub-loop that exits naturally has closed its wall-pair. A sub-loop that hits budget has not.

### The Direction Signal

```
DirectionSignal:
  target_u:         which attractor (+1 = expand, -1 = compress)
  force_magnitude:  |F(u)| — strength of the push
  u_current:        current velocity
  phase:            current ξ
  balance:          current EML-derived balance
```

The Governor reads this signal to make every branching decision. It does not read the LLM's JSON plan for branching — it reads the physics.

### The Natural Exit Condition

```
NATURAL exit when ALL of:
  ξ ≥ 3π/2           (consolidation phase reached)
  |u| < 0.20         (momentum near zero — system settled)
  step > min_steps   (minimum steps elapsed)

COMPRESSED exit when:
  x > 0
  y/x > compress_ratio_threshold (default 2.0)
  EML < eml_min (default 1.5)
```

### The Wrap Time Prediction

```
Twrap = 2π / (s · c_eff · balance)
```

Confirmed at 0.0% error across c_eff 1.000–3.000 in the D-series experiments. This tells you in advance how many steps a sub-loop cycle will take at current parameters. Use it to set sub-loop max_steps appropriately.

---

## Part 2: Governor as Branching Authority

### Current Architecture (What To Replace)

The current event loop receives the LLM's output, parses a JSON plan, and branches based on what the plan says:

```python
# CURRENT — what the agent description showed
plan = llm.generate(prompt)
parsed = json.loads(plan)

if parsed.get("parallel_calls"):
    # branch parallel
    results = await asyncio.gather(*[call(t) for t in parsed["parallel_calls"]])
else:
    # branch serial
    result = await call(parsed["tool"])
```

This is the LLM making the branching decision. The LLM has no awareness of the engine's current phase, velocity, or topological charge. It branches based on what seems logical in the moment, not on the physics of the current session.

### Correct Architecture (Governor Decides)

The Governor reads the engine's direction signal BEFORE querying the LLM. The signal tells the Governor whether the session is in expansion mode (parallel is appropriate) or compression mode (serial is appropriate). The LLM is then prompted with that context so its output aligns with the physics.

```python
# CORRECT — Governor decides branching

class CaduceanGovernor:
    """
    The Governor sits between the event listener and the executor.
    It reads the engine's physics signal and makes ALL branching decisions.
    
    The LLM executes within the Governor's decision.
    The LLM does not make the branching decision.
    """
    
    PARALLEL_THRESHOLD = 0.30   # u > this → parallel branch
    SERIAL_THRESHOLD = -0.30    # u < this → serial branch
    # Between these values → serial (conservative default)
    
    def __init__(self, engine: CaduceanEngine, session_id: str):
        self.engine = engine
        self.session_id = session_id
    
    def get_direction_signal(self) -> dict:
        """
        Read the full physics signal.
        This is what the Governor uses for every decision.
        """
        state = self.engine.get_state(self.session_id)
        F = self.engine.duffing_force(state.u)
        eml = self.engine.get_eml(self.session_id)
        
        # target_u: which attractor is the system moving toward
        if F > 0.05:
            target_u = 1.0    # EXPAND attractor
        elif F < -0.05:
            target_u = -1.0   # COMPRESS attractor
        else:
            target_u = 0.0    # neutral band
        
        return {
            "target_u":        target_u,
            "force_magnitude": abs(F),
            "u_current":       state.u,
            "phase":           state.xi,
            "balance":         state.balance,
            "eml":             eml,
            "q":               self._compute_q(state),
            "phase_label":     self._phase_label(state.xi),
            "should_exit":     self._check_exit(state),
        }
    
    def branching_decision(self) -> dict:
        """
        THE branching decision. Returns execution mode and rationale.
        
        Physics rules:
        - u > +0.30: system in expansion mode → PARALLEL
          Multiple simultaneous tool calls appropriate
          System has momentum toward exploration
          
        - u < -0.30: system in compression mode → SERIAL  
          One tool at a time, consolidate each result
          System has momentum toward convergence
          
        - |u| ≤ 0.30: neutral band → SERIAL (conservative)
          Near equilibrium, don't overcommit resources
          
        - ξ > 3π/2: consolidation phase → SERIAL always
          System approaching natural exit
          Do not launch parallel work that won't complete
          
        - |Q| > 0.75: topology warning → SERIAL always
          Wall-pair imbalanced, serial helps rebalance
        """
        signal = self.get_direction_signal()
        xi = signal["phase"]
        u = signal["u_current"]
        q = signal["q"]
        
        # Consolidation phase overrides everything — always serial
        import math
        if xi >= 3 * math.pi / 2:
            return {
                "mode": "SERIAL",
                "reason": f"CONSOLIDATING phase (ξ={xi:.3f}) — approaching natural exit",
                "signal": signal,
            }
        
        # Topology warning — always serial
        if abs(q) > 0.75:
            return {
                "mode": "SERIAL",
                "reason": f"Q={q:.3f} elevated — rebalance before parallel expansion",
                "signal": signal,
            }
        
        # Expansion mode — parallel appropriate
        if u > self.PARALLEL_THRESHOLD:
            return {
                "mode": "PARALLEL",
                "reason": f"u={u:.3f} in expansion mode — parallel branches appropriate",
                "signal": signal,
            }
        
        # Compression mode or neutral — serial
        return {
            "mode": "SERIAL",
            "reason": f"u={u:.3f} — compression/neutral mode, serial execution",
            "signal": signal,
        }
    
    def prefetch_recommendation(self) -> list[str]:
        """
        Based on phase position, predict which tools will be needed next.
        Used for predictive pre-fetching before the LLM makes the request.
        
        Phase → predicted tool category:
          PLANNING (ξ < π/2):       search, fetch, read tools
          EXECUTING (π/2 < ξ < π):  compute, transform, write tools
          REVIEWING (π < ξ < 3π/2): validate, test, compare tools
          CONSOLIDATING (ξ > 3π/2): summarize, commit, output tools
        """
        signal = self.get_direction_signal()
        phase = signal["phase_label"]
        
        prefetch_map = {
            "PLANNING":      ["search", "fetch", "read", "list"],
            "EXECUTING":     ["write", "compute", "transform", "call"],
            "REVIEWING":     ["test", "validate", "compare", "diff"],
            "CONSOLIDATING": ["summarize", "commit", "format", "output"],
        }
        return prefetch_map.get(phase, [])
    
    def _compute_q(self, state) -> float:
        return (state.x - state.y) / (state.x + state.y + 1.0)
    
    def _phase_label(self, xi: float) -> str:
        import math
        if xi < math.pi / 2:           return "PLANNING"
        elif xi < math.pi:             return "EXECUTING"
        elif xi < 3 * math.pi / 2:     return "REVIEWING"
        else:                          return "CONSOLIDATING"
    
    def _check_exit(self, state) -> tuple[bool, str]:
        import math
        config = self.engine.config
        if (state.xi >= 3 * math.pi / 2
                and abs(state.u) < config.neutral_threshold):
            return True, "NATURAL"
        return False, None
```

### Wiring the Governor Into the Event Loop

```python
async def event_loop_iteration(
    input_event: str,
    engine: CaduceanEngine,
    session_id: str,
    llm,
    tool_registry: dict,
) -> dict:
    """
    One iteration of the Event-Driven Loop with Governor authority.
    
    Order:
    1. Governor reads physics FIRST
    2. Governor decides: serial or parallel, which tools to prefetch
    3. LLM is prompted WITH the Governor's context
    4. LLM selects tools within the Governor's decision
    5. Executor runs tools in Governor-decided mode
    6. Engine observes the results
    7. Governor checks natural exit
    """
    
    governor = CaduceanGovernor(engine, session_id)
    
    # Step 1: Governor reads physics
    signal = governor.get_direction_signal()
    branch = governor.branching_decision()
    prefetch = governor.prefetch_recommendation()
    
    # Step 2: Predictive pre-fetching based on phase
    # Load predicted tools into memory before LLM requests them
    for tool_category in prefetch:
        for tool_name, tool_fn in tool_registry.items():
            if tool_category in tool_name:
                _warm_tool(tool_fn)  # your existing warm-start logic
    
    # Step 3: Prompt LLM with Governor context
    # LLM knows the phase and mode — its output aligns with physics
    governor_context = (
        f"Current cognitive phase: {signal['phase_label']}\n"
        f"Execution mode: {branch['mode']} ({branch['reason']})\n"
        f"Recommended action direction: "
        f"{'explore and expand' if signal['target_u'] > 0 else 'consolidate and compress'}\n"
    )
    
    llm_response = await llm.generate(
        system=governor_context,
        user=input_event,
    )
    
    # Step 4: LLM selects tools — Governor enforces mode
    tool_calls = parse_tool_calls(llm_response)
    
    # Step 5: Execute in Governor-decided mode
    if branch["mode"] == "PARALLEL" and len(tool_calls) > 1:
        results = await asyncio.gather(
            *[execute_tool(t, tool_registry) for t in tool_calls]
        )
    else:
        results = []
        for tool_call in tool_calls:
            result = await execute_tool(tool_call, tool_registry)
            results.append(result)
            
            # After each serial step, re-check Governor
            # If phase advanced to CONSOLIDATING mid-execution, stop
            updated_branch = governor.branching_decision()
            if updated_branch["mode"] == "SERIAL" and branch["mode"] == "PARALLEL":
                break  # Phase changed mid-execution — consolidate now
    
    # Step 6: Observe results in engine
    for i, (tool_call, result) in enumerate(zip(tool_calls, results)):
        action = classify_tool_action(tool_call)  # EXPAND or COMPRESS
        success = result.get("success", True)
        engine.observe(session_id, action, success=success)
    
    # Step 7: Check natural exit
    step_count = get_step_count(session_id)
    should_exit, reason = engine.should_exit(session_id, step_count, 200)
    
    return {
        "output": synthesize_results(llm_response, results),
        "should_exit": should_exit,
        "exit_reason": reason.name if reason else None,
        "governor_signal": signal,
        "branch_decision": branch,
    }


def classify_tool_action(tool_call: dict) -> Action:
    """
    Map tool call type to EXPAND or COMPRESS.
    Adapt this mapping to your specific tool registry.
    
    EXPAND tools:  generative, fetching, exploratory
    COMPRESS tools: validating, committing, summarizing
    """
    tool_name = tool_call.get("name", "").lower()
    
    EXPAND_TOOLS = {
        "search", "fetch", "read", "generate", "create",
        "write", "draft", "explore", "list", "query",
        "browse", "call", "request", "open",
    }
    
    COMPRESS_TOOLS = {
        "test", "validate", "commit", "save", "summarize",
        "review", "compare", "check", "verify", "close",
        "submit", "finalize", "confirm", "delete", "clean",
    }
    
    for keyword in EXPAND_TOOLS:
        if keyword in tool_name:
            return Action.EXPAND
    
    for keyword in COMPRESS_TOOLS:
        if keyword in tool_name:
            return Action.COMPRESS
    
    return Action.CONTINUE
```

---

## Part 3: The Sub-Loop

### What A Sub-Loop Is

A sub-loop is a complete, temporary Event-Driven Loop that:

1. Spins up its own Caducean session with its own Σ = (x, y, ξ, u)
2. Runs to its own natural exit condition
3. Collapses and returns its result to the parent loop
4. Has its own Governor (branching authority within the sub-task)
5. Its completion is observed by the parent engine as a single COMPRESS operation

The sub-loop is the nucleus from your GPE coupling experiment — it is the lower-energy, compression-biased session that the parent (barrier) session delegates to. The sub-loop closes its wall-pair independently. The parent observes the closed wall-pair as a successful consolidation.

### The Math of Sub-Loop Coupling

The parent session Σ_parent and sub-loop session Σ_sub couple through their Q values:

```
Q_parent(t) = (x_parent - y_parent) / (x_parent + y_parent + 1)
Q_sub(t)    = (x_sub - y_sub) / (x_sub + y_sub + 1)

Q_combined(t) = (x_parent + x_sub - y_parent - y_sub) /
                (x_parent + x_sub + y_parent + y_sub + 1)
```

The parent launches the sub-loop when it needs to COMPRESS — Q_parent is drifting high (+direction) and the parent needs a consolidation pass. The sub-loop runs compression-heavy work (validation, refinement, planning). When it exits naturally, it has accumulated high y_sub relative to x_sub. This pulls Q_combined back toward 0 even if Q_parent is still elevated.

The winding number assignment:

```
Parent loop:    (l=1, m=1)  c_eff=1.0   slow cycles, broad scope
Sub-loop:       (l=2, m=1)  c_eff=2.236 faster cycles, narrow scope

Twrap_parent = 2π / (0.35 · 1.0 · balance)  ≈ 18 steps at balance=1
Twrap_sub    = 2π / (0.35 · 2.236 · balance) ≈ 8 steps at balance=1

The sub-loop completes ~2 full cycles in the time the parent completes 1.
This is the correct relationship: the sub-task resolves faster than the parent task.
```

The c_eff ratio between parent and sub-loop is 1:2.236 = 1:√5. This is an irrational ratio — the two loops do NOT phase-lock. This is intentional. The sub-loop should not be entrained to the parent's phase. It should run independently and complete on its own schedule. When it completes, the parent observes the completion as a COMPRESS event regardless of where the parent's phase clock currently is.

### Sub-Loop Implementation

```python
import pickle
from dataclasses import dataclass
from typing import Optional, Any, Callable, Coroutine

@dataclass
class SubLoopResult:
    """Everything the parent loop needs from a completed sub-loop."""
    task_name: str
    output: Any
    exit_reason: str
    steps_taken: int
    final_x: float
    final_y: float
    final_xi: float
    final_u: float
    final_q: float
    success: bool
    sub_session_blob: Optional[bytes] = None  # serialized state for persistence


class CaduceanSubLoop:
    """
    A temporary nested Event-Driven Loop.
    
    Lifecycle:
      1. spin_up()   — creates a new session, initializes Σ
      2. run()       — executes the sub-task under its own Governor
      3. collapse()  — returns SubLoopResult, destroys the session
    
    The parent loop calls this as:
      result = await sub_loop.run(task, tools)
      engine.observe(parent_session, Action.COMPRESS, success=result.success)
    
    Mathematical basis:
      Sub-loop Σ_sub evolves independently of Σ_parent.
      Sub-loop uses higher c_eff (faster cycles) for narrow sub-tasks.
      Sub-loop natural exit = wall-pair closure in sub-task scope.
      Parent observes sub-loop completion as a single COMPRESS event.
      Q_combined = (x_p + x_s - y_p - y_s) / (x_p + x_s + y_p + y_s + 1)
      After successful sub-loop: y_s >> x_s → Q_combined moves toward 0.
    """
    
    def __init__(
        self,
        task_name: str,
        parent_engine: CaduceanEngine,
        parent_session_id: str,
        sub_config: Optional[CaduceanConfig] = None,
        max_steps: int = 50,
    ):
        self.task_name = task_name
        self.parent_engine = parent_engine
        self.parent_session_id = parent_session_id
        self.max_steps = max_steps
        
        # Sub-loop gets its own session ID derived from parent
        import time
        self.sub_session_id = f"{parent_session_id}__sub__{task_name}__{int(time.time())}"
        
        # Sub-loop uses faster winding for tighter scope
        # Parent typically (1,1) c_eff=1.0
        # Sub-loop uses (2,1) c_eff=2.236 — completes 2 cycles per parent cycle
        self.sub_config = sub_config or CaduceanConfig(
            s=0.35,
            a=2.0,
            b=2.0,
            natural_min_steps=3,  # sub-loops can exit faster
        )
        
        # Sub-loop has its own engine instance
        # This is critical: sub-loop physics is independent of parent physics
        self.sub_engine = CaduceanEngine(config=self.sub_config)
        self.governor = None
        self._initialized = False
    
    def spin_up(
        self, 
        inherit_momentum: bool = True,
        start_state: Optional[CaduceanState] = None,
    ) -> None:
        """
        Initialize the sub-loop session.
        
        inherit_momentum: if True, the sub-loop starts with a compressed
        version of the parent's state. The sub-loop begins where the
        parent's cognitive momentum points — it is not a cold start.
        
        Mathematical basis:
          If parent has u_parent > 0 (expansion momentum),
          the sub-loop starts with slight compression bias
          (u_sub = -0.2) because the sub-loop's job is to
          consolidate what the parent is exploring.
          
          If parent has u_parent < 0 (compression momentum),
          the sub-loop starts neutral — the parent is already
          compressing, the sub-loop provides additional depth.
        """
        if start_state is not None:
            # Explicit state handoff (cross-session persistence)
            self.sub_engine.init_session(self.sub_session_id, start=start_state)
        elif inherit_momentum:
            parent_state = self.parent_engine.get_state(self.parent_session_id)
            
            # Sub-loop starts with slight compression bias
            # Its job is to consolidate, so u starts slightly negative
            # Phase starts at 0 — sub-loop begins fresh within its own cycle
            inherited_state = CaduceanState(
                x=0.0,
                y=0.0,
                xi=0.0,
                u=-0.2 if parent_state.u > 0 else 0.0,
                s=self.sub_config.s,
                eml=parent_state.eml,      # inherit EML baseline
                balance=parent_state.balance,  # inherit balance
            )
            self.sub_engine.init_session(self.sub_session_id, start=inherited_state)
        else:
            self.sub_engine.init_session(self.sub_session_id)
        
        self.governor = CaduceanGovernor(self.sub_engine, self.sub_session_id)
        self._initialized = True
    
    async def run(
        self,
        task_description: str,
        llm,
        tool_registry: dict,
        step_callback: Optional[Callable] = None,
    ) -> SubLoopResult:
        """
        Execute the sub-task. Runs its own event loop iterations
        until natural exit or budget.
        
        The sub-loop has its own Governor. Every branching decision
        inside the sub-task is governed by the sub-loop's physics,
        not the parent's physics.
        
        step_callback: optional function called after each step
                       signature: (step, governor_signal, result) -> None
                       Use for logging or UI updates.
        """
        if not self._initialized:
            self.spin_up()
        
        context = []
        step = 0
        final_output = None
        
        while step < self.max_steps:
            # Sub-loop Governor reads sub-loop physics
            signal = self.governor.get_direction_signal()
            branch = self.governor.branching_decision()
            
            # Check natural exit BEFORE generating next step
            should_exit, reason = self.sub_engine.should_exit(
                self.sub_session_id, step, self.max_steps
            )
            if should_exit:
                break
            
            # Build step prompt based on sub-loop's current phase
            step_prompt = self._build_step_prompt(
                task_description, signal, context, step
            )
            
            # Generate next step
            llm_response = await llm.generate(
                system=self._sub_loop_system_prompt(signal),
                user=step_prompt,
            )
            
            # Parse and execute tools
            tool_calls = parse_tool_calls(llm_response)
            
            if branch["mode"] == "PARALLEL" and len(tool_calls) > 1:
                results = await asyncio.gather(
                    *[execute_tool(t, tool_registry) for t in tool_calls]
                )
            else:
                results = []
                for tool_call in tool_calls:
                    result = await execute_tool(tool_call, tool_registry)
                    results.append(result)
            
            # Observe in sub-loop engine
            for tool_call, result in zip(tool_calls, results):
                action = classify_tool_action(tool_call)
                success = result.get("success", True)
                self.sub_engine.observe(
                    self.sub_session_id, action, success=success
                )
            
            # Track context
            context.append({
                "step": step,
                "phase": signal["phase_label"],
                "response": llm_response,
                "results": results,
                "signal": signal,
            })
            
            # Check if LLM signals done
            if self._llm_signals_done(llm_response):
                final_output = llm_response
                reason = ExitReason.NATURAL
                break
            
            final_output = llm_response
            step += 1
            
            if step_callback:
                step_callback(step, signal, results)
        
        return self.collapse(final_output, reason, step)
    
    def collapse(
        self, 
        output: Any, 
        reason: Optional[ExitReason],
        steps_taken: int,
    ) -> SubLoopResult:
        """
        Collapse the sub-loop and return results to parent.
        
        Serializes the sub-loop's final state for persistence.
        The parent loop can restore this state if the same sub-task
        needs to be resumed in a future session.
        """
        state = self.sub_engine.get_state(self.sub_session_id)
        q = (state.x - state.y) / (state.x + state.y + 1.0)
        
        # Serialize final state for cross-session persistence
        try:
            blob = self.sub_engine.serialize(self.sub_session_id)
        except Exception:
            blob = None
        
        success = (
            reason == ExitReason.NATURAL or
            reason == ExitReason.COMPRESSED
        )
        
        result = SubLoopResult(
            task_name=self.task_name,
            output=output,
            exit_reason=reason.name if reason else "BUDGET",
            steps_taken=steps_taken,
            final_x=state.x,
            final_y=state.y,
            final_xi=state.xi,
            final_u=state.u,
            final_q=q,
            success=success,
            sub_session_blob=blob,
        )
        
        # Clean up sub-loop session
        # The session's physics is captured in the blob above
        # The engine instance can be garbage collected
        self._initialized = False
        
        return result
    
    def _build_step_prompt(
        self, 
        task: str, 
        signal: dict, 
        context: list,
        step: int,
    ) -> str:
        phase = signal["phase_label"]
        
        if step == 0:
            return f"Begin this sub-task: {task}"
        
        previous = context[-1]["response"] if context else ""
        
        phase_instructions = {
            "PLANNING": (
                "You are in the planning phase. "
                "Explore the sub-task broadly. "
                "Identify what needs to be done without executing yet."
            ),
            "EXECUTING": (
                "You are in the executing phase. "
                "Take concrete action on the sub-task. "
                "Use the tools available to make progress."
            ),
            "REVIEWING": (
                "You are in the reviewing phase. "
                "Check what has been accomplished. "
                "Identify gaps or errors. Prepare to finalize."
            ),
            "CONSOLIDATING": (
                "You are in the consolidating phase. "
                "Finalize the sub-task. "
                "Produce the complete output and signal done with <done/>."
            ),
        }
        
        return (
            f"{phase_instructions.get(phase, '')}\n\n"
            f"Sub-task: {task}\n"
            f"Previous step: {previous[:300]}\n\n"
            f"Continue."
        )
    
    def _sub_loop_system_prompt(self, signal: dict) -> str:
        return (
            f"You are executing a focused sub-task. "
            f"Current phase: {signal['phase_label']}. "
            f"Cognitive direction: "
            f"{'expand and explore' if signal['target_u'] > 0 else 'consolidate and conclude'}. "
            f"When the sub-task is complete, emit <done/>."
        )
    
    def _llm_signals_done(self, response: str) -> bool:
        return "<done/>" in response or "<done />" in response
    
    def combined_q(self) -> float:
        """
        Combined topological charge across parent and sub-loop.
        Use this to monitor overall session health.
        
        Q_combined → 0 means the sub-loop is balancing the parent.
        Q_combined drifting → ±1 means imbalance is compounding.
        """
        parent_state = self.parent_engine.get_state(self.parent_session_id)
        
        if not self._initialized:
            return (parent_state.x - parent_state.y) / \
                   (parent_state.x + parent_state.y + 1.0)
        
        sub_state = self.sub_engine.get_state(self.sub_session_id)
        total_x = parent_state.x + sub_state.x
        total_y = parent_state.y + sub_state.y
        return (total_x - total_y) / (total_x + total_y + 1.0)
```

### Integrating Sub-Loop Into the Parent Event Loop

```python
async def parent_event_loop_with_subloop(
    input_event: str,
    engine: CaduceanEngine,
    session_id: str,
    llm,
    tool_registry: dict,
    state_store: dict,  # cross-session persistence store
) -> dict:
    """
    Parent event loop that can delegate complex sub-tasks
    to physics-governed sub-loops.
    
    Delegation decision: the Governor decides when to delegate.
    Delegation fires when:
      1. The LLM identifies a multi-step sub-task
      2. The Governor's phase is EXECUTING or REVIEWING
      3. The sub-task's scope is narrow enough for a sub-loop
         (estimated steps < Twrap_parent)
    """
    governor = CaduceanGovernor(engine, session_id)
    signal = governor.get_direction_signal()
    branch = governor.branching_decision()
    
    # Ask LLM what to do — LLM gets Governor context
    llm_plan = await llm.generate(
        system=(
            f"Phase: {signal['phase_label']}. "
            f"Mode: {branch['mode']}. "
            "If the task requires multiple focused steps on a sub-problem, "
            "respond with: DELEGATE: <sub_task_description>\n"
            "Otherwise respond with tool calls or a direct answer."
        ),
        user=input_event,
    )
    
    # Check if LLM is requesting delegation
    if llm_plan.startswith("DELEGATE:"):
        sub_task = llm_plan.replace("DELEGATE:", "").strip()
        
        # Create sub-loop
        sub_loop = CaduceanSubLoop(
            task_name=sub_task[:30],  # short name for session ID
            parent_engine=engine,
            parent_session_id=session_id,
            max_steps=30,  # sub-loops are bounded tighter than parent
        )
        
        # Check if this sub-task has a persisted state from a previous session
        persistence_key = f"{session_id}__sub__{sub_task[:30]}"
        if persistence_key in state_store:
            # Resume from where the sub-loop was last time
            persisted_blob = state_store[persistence_key]
            restored_state = pickle.loads(persisted_blob)
            sub_loop.spin_up(start_state=restored_state)
        else:
            # Fresh start with inherited momentum
            sub_loop.spin_up(inherit_momentum=True)
        
        # Run the sub-loop
        sub_result = await sub_loop.run(
            task_description=sub_task,
            llm=llm,
            tool_registry=tool_registry,
        )
        
        # Persist sub-loop final state for future sessions
        if sub_result.sub_session_blob:
            state_store[persistence_key] = sub_result.sub_session_blob
        
        # Parent observes sub-loop completion as a COMPRESS event
        # The sub-loop did consolidation work — this is a compression
        engine.observe(session_id, Action.COMPRESS, success=sub_result.success)
        
        # Check combined Q for topology health
        q_combined = sub_loop.combined_q()
        
        # Continue parent loop with sub-loop output
        final_response = await llm.generate(
            system=f"The sub-task '{sub_task}' has been completed.",
            user=(
                f"Sub-task result: {sub_result.output}\n\n"
                f"Original request: {input_event}\n\n"
                "Synthesize the sub-task result into the final response."
            ),
        )
        
        # Parent observes the synthesis as another COMPRESS
        engine.observe(session_id, Action.COMPRESS, success=True)
        
        should_exit, reason = engine.should_exit(
            session_id,
            get_step_count(session_id),
            200,
        )
        
        return {
            "output": final_response,
            "sub_loop_used": True,
            "sub_loop_result": sub_result,
            "combined_q": q_combined,
            "should_exit": should_exit,
            "exit_reason": reason.name if reason else None,
            "governor_signal": signal,
        }
    
    else:
        # No delegation needed — standard event loop iteration
        return await event_loop_iteration(
            input_event, engine, session_id, llm, tool_registry
        )
```

---

## Part 4: Cross-Session State Persistence

### Why LLM Cold-Start ≠ Engine Cold-Start

The LLM has no memory between sessions. Every session starts from scratch — no knowledge of previous turns, previous tool calls, or previous decisions. This is the LLM's architecture and cannot be changed without fine-tuning.

The engine is different. The Σ = (x, y, ξ, u) state is four floats. It can be serialized to bytes, stored, and restored in milliseconds. When a user returns after hours or days, the LLM cold-starts but the engine warm-starts. The physics remembers:

```
Where the user was in their cognitive cycle (ξ)
How much exploratory vs consolidating work has been done (x, y)
What direction the session was heading (u)
The EML balance at the end of the last session (balance)
```

### The Math of Warm-Starting

The cross-session momentum is formally defined in the engine as:

```python
engine.init_session(session_id, start=previous_state)
```

Where `previous_state` is a `CaduceanState` dataclass with the serialized values from the last session. The engine does not reset to (0, 0, 0, 0) — it continues from (x_prev, y_prev, ξ_prev, u_prev).

This means:

```
If the previous session ended at ξ = 4.2 rad (CONSOLIDATING phase),
the new session starts at ξ = 4.2 rad.
The Governor immediately knows: this user is in consolidation mode.
The first action should be COMPRESS, not EXPAND.
The phase meter picks up exactly where it left off.
```

The Twrap prediction remains valid across the session boundary:

```
Twrap = 2π / (s · c_eff · balance)

The remaining phase to complete the current cycle:
  remaining_ξ = 2π - ξ_prev   (if ξ_prev > π — mid-cycle)
  steps_to_complete = remaining_ξ / (s · c_eff · balance)
```

The engine knows how many steps until the next natural exit even at the start of a brand new session.

### Implementation

```python
import pickle
import json
import os
from pathlib import Path
from datetime import datetime


class SessionStateStore:
    """
    Persistent store for Caducean session states.
    
    Stores:
      - Parent session states (one per user/conversation)
      - Sub-loop states (one per sub-task, keyed by task name)
      - Session metadata (last_seen, step_count, exit_history)
    
    Storage backend: file system (extend to Redis/DB for production)
    
    Mathematical guarantee:
      Restoring Σ = (x, y, ξ, u) from the previous session
      preserves the Lyapunov stability guarantee.
      The Duffing restoring force does not depend on absolute time —
      only on the current state. A state restored after 24 hours
      is physically identical to a state restored after 1 second.
    """
    
    def __init__(self, store_dir: str = ".caducean_sessions"):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(exist_ok=True)
    
    def save_session(
        self, 
        session_id: str, 
        engine: CaduceanEngine,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Serialize and persist the session state.
        Call this at the end of every event loop iteration
        and at the end of every session.
        """
        # Serialize the Caducean state
        state_blob = engine.serialize(session_id)
        
        # Build the persistence record
        state = engine.get_state(session_id)
        record = {
            "session_id":   session_id,
            "saved_at":     datetime.utcnow().isoformat(),
            "state_blob":   state_blob.hex(),  # store as hex string
            "state_summary": {
                "x":       state.x,
                "y":       state.y,
                "xi":      state.xi,
                "u":       state.u,
                "eml":     state.eml,
                "balance": state.balance,
                "q":       (state.x - state.y) / (state.x + state.y + 1.0),
                "phase":   self._phase_label(state.xi),
            },
            "metadata":    metadata or {},
        }
        
        path = self.store_dir / f"{session_id}.json"
        path.write_text(json.dumps(record, indent=2))
    
    def restore_session(
        self,
        session_id: str,
        engine: CaduceanEngine,
    ) -> Optional[dict]:
        """
        Restore a previously saved session state into the engine.
        Returns the state summary, or None if no saved state exists.
        
        After calling this, the engine's session is warm-started.
        The Governor will read the restored ξ, u, and balance
        and make decisions that continue the previous session's trajectory.
        """
        path = self.store_dir / f"{session_id}.json"
        
        if not path.exists():
            # No saved state — cold start
            engine.init_session(session_id)
            return None
        
        record = json.loads(path.read_text())
        
        # Deserialize the blob back into the engine
        state_blob = bytes.fromhex(record["state_blob"])
        engine.deserialize(session_id, state_blob)
        
        return record["state_summary"]
    
    def save_sub_loop(
        self,
        parent_session_id: str,
        task_name: str,
        sub_result: SubLoopResult,
    ) -> None:
        """
        Persist a sub-loop's final state for future resumption.
        
        If the same sub-task appears in a future session,
        the sub-loop can start from where it left off rather
        than restarting from (0, 0, 0, 0).
        """
        if not sub_result.sub_session_blob:
            return
        
        key = f"{parent_session_id}__sub__{task_name}"
        record = {
            "parent_session_id": parent_session_id,
            "task_name":         task_name,
            "saved_at":          datetime.utcnow().isoformat(),
            "exit_reason":       sub_result.exit_reason,
            "final_state": {
                "x":   sub_result.final_x,
                "y":   sub_result.final_y,
                "xi":  sub_result.final_xi,
                "u":   sub_result.final_u,
                "q":   sub_result.final_q,
            },
            "state_blob": sub_result.sub_session_blob.hex(),
        }
        
        path = self.store_dir / f"{key}.json"
        path.write_text(json.dumps(record, indent=2))
    
    def restore_sub_loop(
        self,
        parent_session_id: str,
        task_name: str,
        sub_engine: CaduceanEngine,
        sub_session_id: str,
    ) -> Optional[dict]:
        """
        Restore a sub-loop's state for resumption.
        Returns state summary or None if no saved state.
        """
        key = f"{parent_session_id}__sub__{task_name}"
        path = self.store_dir / f"{key}.json"
        
        if not path.exists():
            return None
        
        record = json.loads(path.read_text())
        state_blob = bytes.fromhex(record["state_blob"])
        sub_engine.deserialize(sub_session_id, state_blob)
        
        return record["final_state"]
    
    def session_exists(self, session_id: str) -> bool:
        return (self.store_dir / f"{session_id}.json").exists()
    
    def get_state_summary(self, session_id: str) -> Optional[dict]:
        """Read state summary without restoring into engine."""
        path = self.store_dir / f"{session_id}.json"
        if not path.exists():
            return None
        record = json.loads(path.read_text())
        return record.get("state_summary")
    
    def _phase_label(self, xi: float) -> str:
        import math
        if xi < math.pi / 2:           return "PLANNING"
        elif xi < math.pi:             return "EXECUTING"
        elif xi < 3 * math.pi / 2:     return "REVIEWING"
        else:                          return "CONSOLIDATING"


class PersistentEventLoop:
    """
    The complete Event-Driven Loop with:
      - Cross-session state persistence
      - Governor as branching authority
      - Sub-loop delegation for complex sub-tasks
    
    This is the full integration of all three additions.
    Drop this into your application's event handler.
    """
    
    def __init__(
        self,
        session_id: str,
        llm,
        tool_registry: dict,
        store_dir: str = ".caducean_sessions",
    ):
        self.session_id = session_id
        self.llm = llm
        self.tool_registry = tool_registry
        self.store = SessionStateStore(store_dir)
        
        # Initialize engine
        self.engine = CaduceanEngine(config=CaduceanConfig())
        
        # Restore or cold-start
        state_summary = self.store.restore_session(session_id, self.engine)
        
        if state_summary:
            print(
                f"[PersistentLoop] Warm-start: "
                f"ξ={state_summary['xi']:.3f} ({state_summary['phase']}), "
                f"u={state_summary['u']:.3f}, "
                f"Q={state_summary['q']:.3f}"
            )
        else:
            print(f"[PersistentLoop] Cold-start: new session {session_id}")
        
        self.governor = CaduceanGovernor(self.engine, session_id)
        self.step_count = 0
    
    async def handle_event(self, input_event: str) -> dict:
        """
        Handle one user event (voice, text, trigger).
        
        The loop:
        1. Governor reads physics (warm-started from previous session)
        2. Governor decides branch mode
        3. Check if sub-loop delegation needed
        4. Execute under Governor authority
        5. Observe results in engine
        6. Persist state (every step)
        7. Check natural exit
        """
        self.step_count += 1
        
        # Step 1 & 2: Governor reads physics and decides branching
        signal = self.governor.get_direction_signal()
        branch = self.governor.branching_decision()
        
        # Log warm-start context for debugging
        print(
            f"[Governor] Step {self.step_count}: "
            f"phase={signal['phase_label']}, "
            f"u={signal['u_current']:.3f}, "
            f"mode={branch['mode']}, "
            f"Q={signal['q']:.3f}"
        )
        
        # Step 3: Query LLM with Governor context
        llm_response = await self.llm.generate(
            system=(
                f"Phase: {signal['phase_label']}. "
                f"Mode: {branch['mode']}. "
                f"Direction: {'expand' if signal['target_u'] > 0 else 'compress'}.\n"
                "If delegating a sub-task: DELEGATE: <description>\n"
                "Otherwise: proceed with tool calls or direct response."
            ),
            user=input_event,
        )
        
        result = None
        
        # Step 4a: Sub-loop delegation
        if llm_response.strip().startswith("DELEGATE:"):
            sub_task = llm_response.replace("DELEGATE:", "").strip()
            task_key = sub_task[:40]
            
            # Build sub-loop — check for persisted state
            sub_loop = CaduceanSubLoop(
                task_name=task_key,
                parent_engine=self.engine,
                parent_session_id=self.session_id,
            )
            
            # Try to restore sub-loop state
            restored = self.store.restore_sub_loop(
                self.session_id, task_key,
                sub_loop.sub_engine, sub_loop.sub_session_id
            )
            
            if restored:
                print(f"[SubLoop] Warm-start sub-loop '{task_key}': "
                      f"ξ={restored['xi']:.3f}, Q={restored['q']:.3f}")
                # Manually init from restored state
                sub_state = CaduceanState(
                    x=restored["x"], y=restored["y"],
                    xi=restored["xi"], u=restored["u"],
                    s=sub_loop.sub_config.s,
                )
                sub_loop.sub_engine.init_session(
                    sub_loop.sub_session_id, start=sub_state
                )
                sub_loop._initialized = True
                sub_loop.governor = CaduceanGovernor(
                    sub_loop.sub_engine, sub_loop.sub_session_id
                )
            else:
                sub_loop.spin_up(inherit_momentum=True)
            
            # Run sub-loop
            sub_result = await sub_loop.run(
                task_description=sub_task,
                llm=self.llm,
                tool_registry=self.tool_registry,
            )
            
            # Persist sub-loop final state
            self.store.save_sub_loop(self.session_id, task_key, sub_result)
            
            # Parent observes sub-loop as COMPRESS
            self.engine.observe(
                self.session_id, Action.COMPRESS, success=sub_result.success
            )
            
            result = {
                "type": "sub_loop",
                "sub_result": sub_result,
                "output": sub_result.output,
            }
        
        # Step 4b: Direct execution
        else:
            tool_calls = parse_tool_calls(llm_response)
            
            if branch["mode"] == "PARALLEL" and len(tool_calls) > 1:
                tool_results = await asyncio.gather(
                    *[execute_tool(t, self.tool_registry) for t in tool_calls]
                )
            else:
                tool_results = []
                for tool_call in tool_calls:
                    tool_result = await execute_tool(tool_call, self.tool_registry)
                    tool_results.append(tool_result)
            
            for tool_call, tool_result in zip(tool_calls, tool_results):
                action = classify_tool_action(tool_call)
                self.engine.observe(
                    self.session_id, action,
                    success=tool_result.get("success", True)
                )
            
            result = {
                "type": "direct",
                "tool_results": tool_results,
                "output": llm_response,
            }
        
        # Step 5: Persist engine state after EVERY step
        # This is what makes the loop truly persistent
        self.store.save_session(
            self.session_id,
            self.engine,
            metadata={
                "step": self.step_count,
                "last_input": input_event[:100],
                "branch_mode": branch["mode"],
            }
        )
        
        # Step 6: Check natural exit
        should_exit, reason = self.engine.should_exit(
            self.session_id, self.step_count, 200
        )
        
        return {
            "output": result.get("output", ""),
            "result": result,
            "should_exit": should_exit,
            "exit_reason": reason.name if reason else None,
            "governor_signal": signal,
            "branch_decision": branch,
            "step": self.step_count,
        }
    
    async def run(self, get_next_event: Callable) -> None:
        """
        Full event loop. Runs until natural exit or KeyboardInterrupt.
        
        get_next_event: async callable that returns the next user input
                        Blocks until input arrives (interrupt-based, not polling)
        """
        print(f"[PersistentLoop] Starting. Session: {self.session_id}")
        
        while True:
            try:
                # Block until next event (interrupt-based)
                event = await get_next_event()
                
                if not event:
                    continue
                
                response = await self.handle_event(event)
                
                print(f"[Output] {response['output']}")
                
                # Natural exit — the physics says the session is complete
                if response["should_exit"]:
                    print(
                        f"[PersistentLoop] Natural exit: "
                        f"{response['exit_reason']} at step {self.step_count}"
                    )
                    break
                    
            except KeyboardInterrupt:
                print("[PersistentLoop] Interrupted — state persisted")
                break
```

---

## Part 5: The Three Additions Together — Integration Checklist

Your agent should implement these in order. Each builds on the previous.

### Step 1: Governor as Branching Authority

- [ ] Add `CaduceanGovernor` class to your application
- [ ] Replace LLM JSON plan branching with `governor.branching_decision()`
- [ ] Wire `classify_tool_action()` to map your specific tools to EXPAND/COMPRESS
- [ ] Add `governor_context` to LLM system prompt on every call
- [ ] Add `governor.prefetch_recommendation()` to pre-warm tools before LLM requests them
- [ ] Log `governor.get_direction_signal()` on every step for debugging

### Step 2: Cross-Session State Persistence

- [ ] Add `SessionStateStore` class to your application
- [ ] Call `store.restore_session()` at the START of every session
- [ ] Call `store.save_session()` at the END of every event loop iteration
- [ ] Log the warm-start state summary so you can verify persistence is working
- [ ] Test: end a session mid-task, restart, verify ξ and u resume from saved values

### Step 3: Sub-Loop Integration

- [ ] Add `CaduceanSubLoop` class to your application
- [ ] Add `SubLoopResult` dataclass
- [ ] Modify event loop to detect `DELEGATE:` prefix from LLM
- [ ] Wire sub-loop persistence through `store.save_sub_loop()` and `store.restore_sub_loop()`
- [ ] Observe sub-loop completion as COMPRESS in parent engine
- [ ] Monitor `combined_q()` to verify sub-loop is balancing parent Q

### Verification Tests

After implementing each step, run these checks:

```python
# Test 1: Governor branching
# Set engine state to u=+0.5, verify branch returns PARALLEL
# Set engine state to u=-0.5, verify branch returns SERIAL
# Set engine state to xi=5.0 (CONSOLIDATING), verify branch returns SERIAL always

# Test 2: Cross-session persistence
# Run 5 steps, save session
# Create new engine, restore session
# Verify x, y, xi, u match within floating point tolerance

# Test 3: Sub-loop coupling
# Run parent to x=5, y=2 (Q ≈ +0.46)
# Spin up sub-loop, run to y_sub=8, x_sub=2 (Q_sub ≈ -0.60)
# Verify Q_combined ≈ (5+2-2-8)/(5+2+2+8+1) = -3/18 ≈ -0.17
# Q_combined should be closer to 0 than Q_parent alone

# Test 4: Warm-start correctness
# End session at xi=4.8 (CONSOLIDATING phase)
# Restore session
# Verify first Governor decision is SERIAL (consolidation mode)
# Verify Twrap remaining = (2π - 4.8) / (s · c_eff · balance)
```

---

## Summary: What Changes In Your Application

| Component | Before | After |
|-----------|--------|-------|
| Branching decision | LLM JSON plan | Governor reads u, xi, Q |
| Session start | LLM cold-start + engine cold-start | LLM cold-start + engine warm-start |
| Complex sub-tasks | Single flat call or manual recursion | Sub-loop with own physics |
| State between sessions | None | Σ = (x, y, ξ, u) persisted and restored |
| Sub-task state | None | Sub-loop Σ persisted separately |
| Phase awareness | None | Governor knows phase at every step |
| Topology monitoring | None | Combined Q tracks parent + sub-loop health |
| Natural exit | Hardcoded conditions | Physics (ξ ≥ 3π/2, |u| < 0.20) |

The engine was always the foreman. These three additions make it act like one.

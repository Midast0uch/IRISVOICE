# Caducean Live Test Plan

**Purpose:** prove the six unverified components actually work by driving the real app by hand.
Written to be executed by an agent watching the backend while a human uses the UI.

**Why this exists.** Four components ship **disabled** and two are **unproven**. A default app run
verifies nothing about any of them — every suite and harness is green, and green has twice been
compatible with a completely inert mechanism. Only a live run with the flags on settles it.

| # | Component | Status going in | What would prove it |
|---|---|---|---|
| T1 | Phase scheduler | FLAG-OFF | a non-zero wait for background work |
| T2 | Priority lane | FLAG-OFF | user turn waits **0** while background waits |
| T3 | Sub-Loop batching | FLAG-OFF | N children → **1** LLM call |
| T4 | Multi-session coupling | FLAG-OFF | **one** nucleus + **one** barrier |
| T5 | Coordinate recall | **UNEXERCISED** | `coords_from` count 0 → non-zero, query returns a doc |
| T6 | Outer loop | **PARTIAL** | confirm 2 of 3 guards are dead (negative test) |

---

## Setup

### 1. Start with both flags ON

```bash
export IRIS_PHASE_SCHEDULER=1
export IRIS_COUPLING_ENABLED=1
```

PowerShell:

```powershell
$env:IRIS_PHASE_SCHEDULER="1"; $env:IRIS_COUPLING_ENABLED="1"
```

### 2. Confirm they took effect before testing anything

```bash
curl -s localhost:8090/api/debug/caducean | python -m json.tool
```

`flags.*.effective` must be `true` for both. **If either is `false`, stop** — everything below
will silently pass for the wrong reason (`reason=flag_off`).

### 3. The two observation channels

```bash
# A. live log stream — the primary channel
tail -f backend/logs/irisvoice.log | grep -E "GATE_DECISION|CoupledRegistry|SubLoopBatcher"

# B. state snapshot — read-only, safe to poll as often as you like
watch -n 2 'curl -s localhost:8090/api/debug/caducean | python -m json.tool'
```

The endpoint is strictly side-effect free — it advances no phase and records no request, so
polling cannot perturb what you are measuring.

---

## T1 — Phase scheduler engages

**Prove:** background work receives a real, non-zero wait.

**Prompt** (multi-step, forces several sequential LLM calls):

> *"Search the web for the three most recent Python 3.13 features, then summarize each one, then
> tell me which is most useful for a voice assistant."*

**Watch for:**

```
[phase_manager] GATE_DECISION osc=... quota=... wait=0   reason=priority cls=user_turn
[phase_manager] GATE_DECISION osc=... quota=... wait=0.4 reason=gated  cls=reason
[phase_manager] GATE_DECISION osc=... quota=... wait=0   reason=admit  theta=... amp=...
```

**PASS** — at least one `reason=gated` with `wait > 0`.
**FAIL** — every line is `wait=0`. Check the `reason`:

| reason | Meaning |
|---|---|
| `flag_off` | flag not actually set — fix setup |
| `unmetered` | provider is local (LM Studio/Ollama). **Switch to a cloud provider** — local is never gated by design |
| `priority` | every call is being classified user-facing — a real bug, report it |
| `admit` only | scheduler is running but never gating; note `theta` and `amp` and report |

**Also check** `scheduler.quotas.*.gap_stats.stddev_gap_s` in the endpoint. Run the same prompt
with `IRIS_PHASE_SCHEDULER=0` and compare — **flag-on stddev should be lower**. That is the
"stream, not a firework" property, and it is the single most meaningful measurement in this plan.

---

## T2 — Priority lane never waits

**Prove:** the user's turn is never delayed, even while background work is being gated.

**Method:** while T1's multi-step task is still running, **send a second short message**:

> *"what time is it"*

**Watch for:** that turn's gate line must be `wait=0 reason=priority cls=user_turn`.

**PASS** — priority line present with `wait=0`, and the reply feels as fast as with the flag off.
**FAIL** — a `reason=gated` line for `cls=user_turn` or `cls=speak`. That is a Decision-Locked
violation; stop and report.

**Voice check (the one that actually matters):** speak a wake-word request while a background task
runs. Spoken replies must not stutter or lag. If they do, the priority lane is not reaching the
TTS path — report it regardless of what the logs say. The felt experience is the requirement here;
the log is only evidence.

---

## T3 — Sub-Loop batching

**Prove:** independent Sub-Loop children dispatch as **one** call, not N.

Batching only triggers when the DER loop **splits**, which happens when `|u| < U_SPLIT (0.5)` —
i.e. the agent is genuinely unresolved. Ambiguous, multi-part research prompts induce this;
crisp single-answer prompts will not.

**Prompt:**

> *"I'm not sure what's causing my app to feel slow — investigate the audio pipeline, the model
> loading path, and the websocket layer, and tell me which is most likely."*

**Watch for:**

```
[DER] _split_step trigger=unresolved_u u=0.3x width=3 depth=1
[SubLoopBatcher] BATCH_READY join=step_2 children=3 ids=[...] reason=full
```

**PASS** — a `BATCH_READY` with `children >= 2` following a split.
**Acceptable** — `BATCH_REJECT ... reason=not_independent` (children genuinely depend on each
other; the guard is working).
**FAIL** — a split occurs, children are independent, and no `BATCH_READY` ever appears.

Check `batching.pending_groups` in the endpoint mid-run to see groups forming.

⚠️ **If no split occurs at all**, the test is inconclusive, not passed. Try a vaguer prompt; if
`|u|` never drops below 0.5, note that and move on — you cannot force the physics.

---

## T4 — Multi-session coupling

**Prove:** two concurrent sessions produce **exactly one nucleus and one barrier** — the original
bug made both become barriers.

**Method:** run **two sessions concurrently** — this is the whole point, one session cannot couple.

1. Start a long task in the **voice** session (wake word → a research question)
2. While it runs, start a task in a **text/coding** conversation

**Confirm first:** `coupling.session_count >= 2` and `differentiation_possible: true`. If
`session_count` is 1, the two sessions are sharing a kernel session id — coupling cannot occur and
the test is inconclusive.

**Watch for:**

```
[CoupledRegistry] coupled voice_x (c_eff=1.581, nucleus) <-> der_y (c_eff=1.000, barrier):
    rational=True phase_diff=0.4211 nudge=-0.0240
```

**PASS** — one side `nucleus`, the other `barrier`, in the same line.
**FAIL** — both sides show the same role. That is the original F4 bug returning; report immediately.

**Also check** `coupling.distinct_c_eff` — expect at least two values from
`der 1.0 / voice 1.5811 / research 3.0`. A single value means the winding degeneracy is back.

**Bonus:** if you can get a `research`-domain session running alongside `voice`, that pair is
irrational (√5 : √18) and should log `rational=False` with damping instead of differentiation.

---

## T5 — Coordinate-addressed recall ⭐ highest value

**Prove:** `coords_from` goes from **zero rows** to populated, and a proximity query returns a
document. This is the only test here for a capability that has *never once worked*.

**Baseline first:**

```bash
curl -s localhost:8090/api/debug/caducean | python -c "import json,sys; m=json.load(sys.stdin)['memory']; print(m['status'], m['total_populated_coords_from'])"
```

Expect `UNEXERCISED (no coords_from written yet) 0`.

**Then drive the document path** — this must be a real save, not a chat reply:

> *"Search the web for how WAL mode works in SQLite and save the findings as a markdown document."*

**Re-read the endpoint.** `memory.total_populated_coords_from` must now be **> 0**, and
`coordinate_tables[].sample` should show canonical 2-decimal coordinates like
`"0.12,0.34,0.50,0.70"`.

**PASS (step 1)** — count moved from 0.
**FAIL** — still 0. The write path never fires; capture which tool ran and report. This is the
most likely failure in the entire plan and the most valuable one to find.

**Then the retrieval half:** in the **same conversation**, ask something that should surface it:

> *"What did we find out earlier about SQLite?"*

**PASS (step 2)** — the saved document is recalled. Only then does T5 graduate to PROVEN.

⚠️ Step 1 passing without step 2 means documents are being *filed* but not *found* — a different
defect from the one that has been blocking this, and worth reporting separately.

---

## T6 — Outer loop (negative test)

**Prove the gap is real.** This one is different: you are confirming a *known defect exists*, not
that a feature works. Do not try to make it pass.

**Method:** drive at least 4–5 conversations to completion (so session-exit rows accumulate), then:

```bash
curl -s localhost:8090/api/debug/caducean | python -c "import json,sys; print(json.dumps(json.load(sys.stdin)['outer_loop'], indent=2))"
```

**Expected — this is the correct result:**

```json
{
  "held_out_score": {
    "natural_exit_rate": 0.66,
    "verified_fraction": 1.0,      // constant — guard dead
    "tokens_per_verified": 0.0     // never populated — guard dead
  },
  "live_guards": 1,
  "dead_guards": ["verified_fraction == 1.0 ...", "tokens_per_verified == 0.0 ..."]
}
```

**CONFIRMED** — `live_guards: 1` with both dead guards listed. The compound gate has one working
signal, so the outer loop currently accepts any proposal that raises natural-exit rate — exactly
the single-metric reward-hacking it was written to prevent.

**Surprising result** — if `verified_fraction` is anything other than exactly `1.0`, something has
changed since the audit. Report it; that would be good news worth verifying.

Repair is specified: `specs/der-loop-integrity-display/` **REQ-13 / Wave 10**. Not started.

---

## T7 — Flags-off regression (do this last)

**Prove:** the safe default is unchanged. This is what you actually ship.

```bash
unset IRIS_PHASE_SCHEDULER IRIS_COUPLING_ENABLED
```

Re-run T1's prompt and a voice request.

**PASS** — behavior indistinguishable from before this work. Gate lines either absent or
`reason=flag_off`. No `CoupledRegistry` lines at all.
**FAIL** — any behavioral difference with both flags off. That is the most serious possible
finding in this plan, because it affects the default configuration everyone runs.

---

## Reporting

For each test record: **PASS / FAIL / INCONCLUSIVE**, the log lines observed, and the endpoint
snapshot. Then update `bootstrap/GOALS.md` Domain 21:

- `[21.5]` graduates on **T1 + T2 + T7**
- `[21.4]` graduates on **T4**
- `[21.6]` graduates on **T5 both steps** — and only then is a landmark crystallized for it
- **T6 confirms** the known gap; it does not graduate anything

**INCONCLUSIVE is a valid and useful result.** T3 needs a split to occur and T4 needs two genuine
concurrent sessions; neither can be forced. Record the reason rather than retrying until the
outcome looks green — an inconclusive result honestly reported is worth more than a pass obtained
by reshaping the test.

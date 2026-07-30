# Caducean Live Test Plan

**Purpose:** prove the six unverified Caducean components AND all six execution-ordered phases
(`specs/PHASES.md`, Phase 1 Foundation → Phase 6 DER Integrity) actually work by driving the real
app by hand. Written to be executed by an agent watching the backend while a human uses the UI.

**Why this exists — what only a human can catch.** Six standing CDD harnesses
(`scripts/validate_phase1_foundation.py`, `validate_display_coherence.py`, `validate_local_model_path.py`,
`validate_encoder_path.py`, `validate_switcher.py`, `validate_outer_loop.py`) already pin every
contract and behavioral effect in this programme, and they are green. A green harness proves the
*shape* of the fix — the right event fired, the right field changed, the right value round-tripped.
It cannot prove:

- **Audio is actually audible** — a `speak()` call that returns `status=ok` and emits
  `UTTERANCE_START` says nothing about whether TTS played, stuttered, or lagged behind the task.
- **Text does not shift** — a step going `pending → working` must not nudge sibling rows
  horizontally; no harness renders layout.
- **One indicator, not two** — a thinking spinner rendered *simultaneously* with a task card is a
  visual double, not a contract violation any assertion catches.
- **The card feels alive** — rotating detail beside a static tool name vs. a card that visibly sits
  still while real work happens.
- **The app is not slower** — a correct derivation that adds 400ms of synchronous work per turn
  passes every unit test and ruins the product.

This document exists to catch exactly that class of gap. It also carries the six flag-off Caducean
mechanisms (T1–T7) that ship disabled and are otherwise unreachable without a debugger.

**This plan produces evidence; it does not itself graduate anything.** `bootstrap/GOALS.md` is
updated only after a separate pass reviews the evidence gathered here — do not treat a PASS recorded
in this document as a graduation event.

| # | Component | Status going in | What would prove it |
|---|---|---|---|
| T1 | Phase scheduler | FLAG-OFF | a non-zero wait for background work |
| T2 | Priority lane | FLAG-OFF | user turn waits **0** while background waits |
| T3 | Sub-Loop batching | FLAG-OFF | N children → **1** LLM call |
| T4 | Multi-session coupling | FLAG-OFF | **one** nucleus + **one** barrier |
| T5 | Coordinate recall | **UNEXERCISED** | `coords_from` count 0 → non-zero, query returns a doc |
| T6 | Outer loop | **REPAIRED (16de4b3e)** | `live_guards: 3`, no dead guards, a genuinely varying `verified_fraction` |
| T7 | Flags-off regression | — | no behavioral change with both flags off |
| P1.x | Phase 1 — Foundation | Landed, unverified live | real window, two providers, no leaked credential |
| P2.x | Phase 2 — The Instrument | Landed, unverified live | card moves without a page fetch, narration audible |
| P3.x | Phase 3 — Local Model Loader | Landed, unverified live | derive → cache, VRAM degradation, correction loop |
| P4.x | Phase 4 — Encoder | **BLOCKED** (weights absent) | install section below |
| P5.x | Phase 5 — Switcher + ContextPill | Landed, unverified live | switcher in input row, guards preserved, live on every turn |
| P6.x | Phase 6 — DER Integrity | Repaired, unverified live | 3 live guards, failures committed, per-domain gating |

---

## Setup

### 1. Start with both flags ON (for T1–T4, T7)

```bash
export IRIS_PHASE_SCHEDULER=1
export IRIS_COUPLING_ENABLED=1
```

PowerShell:

```powershell
$env:IRIS_PHASE_SCHEDULER="1"; $env:IRIS_COUPLING_ENABLED="1"
```

The Phase 1–6 tests below do **not** require either flag — they exercise the six-phase programme,
which ships flag-**on** by default. Run T1–T4 and P1.x–P6.x in the same session; only T7 needs the
flags removed, so do it last.

### 2. Confirm the flags took effect before testing T1–T4

```bash
curl -s localhost:8090/api/debug/caducean | python -m json.tool
```

`flags.*.effective` must be `true` for both. **If either is `false`, stop** — T1–T4 below will
silently pass for the wrong reason (`reason=flag_off`).

### 3. The two observation channels

```bash
# A. live log stream — the primary channel
tail -f backend/logs/irisvoice.log | grep -E "GATE_DECISION|CoupledRegistry|SubLoopBatcher|EmbeddingService|LocalModelManager|OuterTuner|resolve_context_window"

# B. state snapshot — read-only, safe to poll as often as you like
watch -n 2 'curl -s localhost:8090/api/debug/caducean | python -m json.tool'
```

The endpoint (`backend/api/caducean_debug.py:416`) is strictly side-effect free — it advances no
phase and records no request, so polling cannot perturb what you are measuring. It returns eight
top-level sections; the ones this plan uses beyond `flags`/`scheduler`/`coupling`/`batching`/`memory`
are:

| Section | Function | Fields used below |
|---|---|---|
| `context_window` | `_context_window()` (`caducean_debug.py:203`) | `window_tokens`, `window_source`, `providers[].{id,kind,model,purpose,loaded,loading}` |
| `loader_state` | `_loader_state()` (`caducean_debug.py:311`) | `status`, `active_config`, `current_purpose`, `device_policy`, `config_cache` |
| `encoder_state` | `_encoder_state()` (`caducean_debug.py:371`) | `embedding_backend`, `embedding_available_backends`, `reindex`, `encoder_350m_loaded` |
| `outer_loop` | `_outer_loop()` (`caducean_debug.py:252`) | `live_guards`, `dead_guards`, `held_out_score`, `live_by_metric`, `params` |

Every field name above is quoted directly from `caducean_debug.py` — if a field is missing from your
response, the endpoint has drifted from this plan; report the mismatch rather than guessing a
replacement field.

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
"stream, not a firework" property, and it is one of the more meaningful measurements in this plan.

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

## T6 — Outer loop — REPAIRED, now a POSITIVE test

**The repair landed in `16de4b3e` and is committed.** Before that commit this section was a
*negative* test instructing the tester to confirm two of three guards were dead
(`live_guards: 1`, `verified_fraction` pinned to a constant `1.0`, `tokens_per_verified` pinned to
`0.0`, repair "not started"). **All of that is now wrong and must not be re-run as written** — the
gate has all three guards live (`GuardResult` keeps `live` and `passed` distinct — see
`backend/agent/outer_loop.py`), each guard has an independent rejection test
(`scripts/validate_outer_loop.py` assertion 4), and the "never split" hack (`U_SPLIT=0.0`) is in
`_PROPOSALS["U_SPLIT"]` and rejected by the compound gate (assertion 5). The stale pointer to
`specs/der-loop-integrity-display/` REQ-13 / Wave 10 is also gone — that spec was folded into the
Phase 6 re-cut (`specs/phase-6-der-integrity/`) and the original file deleted; if you find that
pointer anywhere else, it is dead and should be removed.

**Prove:** the compound gate is now three genuinely independent live measurements.

**Method:** drive at least 4–5 conversations to completion (so session-exit rows accumulate — mix
outcomes: some tasks that finish naturally, some that fail a step, some UNVERIFIED), then:

```bash
curl -s localhost:8090/api/debug/caducean | python -c "import json,sys; print(json.dumps(json.load(sys.stdin)['outer_loop'], indent=2))"
```

**Expected — this is the correct result now:**

```json
{
  "held_out_score": {
    "natural_exit_rate": 0.66,
    "verified_fraction": 0.83,
    "tokens_per_verified": 941.2
  },
  "live_by_metric": {
    "natural_exit_rate": true,
    "verified_fraction": true,
    "tokens_per_verified": true
  },
  "live_guards": 3,
  "dead_guards": []
}
```

**PASS** — `live_guards: 3`, `dead_guards: []`, `tokens_per_verified > 0`, and — across two separate
runs with genuinely different session mixes (e.g. one batch with more failures) —
`verified_fraction` takes **different** values. A `verified_fraction` that is exactly `1.0` in one
reading is not automatically wrong (a session where every step verified is `1.0` legitimately —
`scripts/validate_outer_loop.py` assertion 8 proves the endpoint distinguishes a *live* 1.0 from a
*dead* 1.0 via `GuardResult.live`, not the value), but if it is **always** exactly `1.0` no matter
what mix of sessions you drive, or if `dead_guards` is non-empty, that is suspicious — capture the
raw sessions you drove and report it as a regression.

**REGRESSION TO REPORT IMMEDIATELY** — any of the following means the repair has come undone:
- `live_guards: 1` (the exact old value)
- `dead_guards` non-empty
- `tokens_per_verified` reads exactly `0.0` across multiple runs with real token usage
- `verified_fraction` never varies no matter what session mix you drive

**Also check** (optional, deeper verification): run `python scripts/validate_outer_loop.py` — it
holds all 9 assertions from `specs/phase-6-der-integrity/design.md` and, uniquely among the six
harnesses, proves each assertion is *proven-failable* by re-running it against a deliberately-bugged
stand-in mirroring the historical defect and showing that stand-in fails. This is a standing CDD
harness, not a substitute for driving the live app — the live session-exit rows it reads in this
section come only from real conversations you ran.

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

# Phase 1 — Foundation

Covers: DER budget from the real window; context-window resolution + source tagging; provider
registry/persistence; credential handling. Automated coverage: `scripts/validate_phase1_foundation.py`
(11 CT-F contracts + 11 assertions, all pytest-level — no live app). What only a live run adds:
the ContextPill actually reading a real number in the browser, a real restart with real keys in the
real OS keyring, and actually opening `iris_config.json` to look for a credential no test fixture
would think to check for it.

### P1.1 — ContextPill shows the REAL window, with source

**Prove:** the denominator is the model's actual context window, not the `8.2k` placeholder, and its
`source` is one of `override | authoritative | table | default`.

**Method:** load the chat UI with a provider/model whose window is in
`AgentKernel._KNOWN_CONTEXT_WINDOWS` (e.g. a Cerebras `gemma-4-31b` model — confirmed
`256_000` entry), send one message, and read the pill.

**Watch for:** `GET /api/debug/caducean` → `context_window.window_tokens` and
`context_window.window_source` (`backend/api/caducean_debug.py:219-221`, sourced from
`kernel.resolve_context_window_with_source()`).

**PASS** — `window_tokens` matches the model's real window (256,000 for the example above, not
8,192), and `window_source` is `authoritative` or `table`, never silently `default` for a model that
has a table entry.
**FAIL** — `window_tokens == 8192` for a model with a known window, or `window_source` missing.

### P1.2 — Two API providers with different keys survive a restart

**Prove:** REQ-6 AC2/AC1 — two providers, two credentials, both alive after a real process restart.

**Method:** in Settings, add two API providers (e.g. Cerebras and OpenAI) with two **different**
keys. Confirm both appear bound. **Restart the backend process** (not just reload the page).

**Watch for:** `context_window.providers[]` in the debug endpoint — each entry has its own `id`,
`kind`, `model`, `purpose`. Log line at provider write time (REQ-10 AC3): provider id + outcome,
never the credential.

**PASS** — both provider ids present after restart, each still bound to its own role, and swapping
one provider's model does not touch the other's key (confirm by using each — a wrong-vendor 401
means keys got crossed).
**FAIL** — one provider vanishes, or a request to provider B succeeds using provider A's key (that
would show as a request to B's endpoint succeeding without B's own key ever having been entered).

### P1.3 — NO credential in `iris_config.json`

**Prove:** REQ-6 AC4 / REQ-10 AC3 — this had been leaking in plaintext. This is the one item on this
list that a human must do by hand; no fixture can stand in for actually opening the file.

**Method:** after configuring at least one API provider with a real key, **open the file yourself**:

```bash
# path: backend/iris_config.py:109-110 -> <repo_root>/data/iris_config.json
grep -i "sk-\|api_key\|bearer" data/iris_config.json
```

Also open it in an editor and read it, not just grep — a key can be present under a field name grep
doesn't expect.

**PASS** — no match, and manual read confirms only a `cred_ref` (the keyring key, e.g. `"cerebras"`)
appears, never the credential value itself.
**FAIL** — any credential or fragment of one appears in the file. This is a P0 finding — report
immediately with the exact field name it appeared under.

### P1.4 — `lm_studio` routes as LOCAL_OPENAI, not the API catch-all

**Prove:** REQ-9 AC3 — routing mode is frozen and each of the four `provider` values resolves to its
documented kind.

**Method:** set `provider=lm_studio` in Settings (pointing at a real or stub LM Studio endpoint) and
send one message.

**Watch for:** the request path taken — LM Studio's OpenAI-compatible local endpoint, not the
`ProviderKind.API` cloud path. `scripts/validate_phase1_foundation.py` Assertion 10 pins
`lm_studio -> ProviderKind.LOCAL_OPENAI` at the unit level; this test confirms it live.

**PASS** — the request actually reaches the configured LM Studio URL.
**FAIL** — the request goes to a cloud API endpoint instead.

### P1.5 — An unlisted OpenRouter model resolves to 8192, tagged `source=default`

**Prove:** REQ-2 AC6 (Decision Locked, OQ-4) — the old blanket `("openrouter", "", 32_000)` table
entry was **removed** because it over-provisioned every OpenRouter model below 32k. This is a
correctness check, not a bug report: seeing `8192`/`source=default` here is the CORRECT outcome.

**Method:** configure an OpenRouter model that is not in `_KNOWN_CONTEXT_WINDOWS`
(`backend/agent/agent_kernel.py:884-932`) — anything obscure — and send one message.

**Watch for:** `context_window.window_tokens == 8192` and `window_source == "default"`.

**PASS** — exactly that. **Do not report this as a bug** — the fallback is intentionally
conservative (Decision Locked #7: "a too-high default is worse than a too-low one").
**Escape hatch:** if you need this model sized correctly right now, use the per-model override
(`_context_window_overrides`, highest precedence per REQ-2 AC3) rather than waiting on the OpenRouter
`/models` metadata lookup (OQ-4, not yet implemented).
**FAIL** — only if the resolved window is silently **wrong and unlabeled** (i.e. `window_source`
missing entirely, hiding that a guess occurred).

---

# Phase 2 — The Instrument

Covers: real task-card driven by execution records; plan immutable while progress rotates; phase
transitions on long tool calls; sub-loop steps append; agent-driven narration; frontend suite
running. Automated coverage: `scripts/validate_display_coherence.py` (7 CT-I contracts + 8
assertions, including a real Jest replay of `useTaskProgress`). What only a live run adds: whether
the card **feels** alive during a real multi-minute websearch, and whether narration is actually
**audible**, neither of which any harness can assert.

### P2.1 — The task card moves during a real websearch

**Prove:** REQ-2 AC1/AC2 and REQ-4 AC1 together — plan text stays byte-identical while live detail
rotates beside the tool name, and the card advances during page-less phases (searching / extracting
/ citing), not only on page fetches.

**Prompt:**

> *"Search the web for the current best practices for React Server Components and summarize them."*

**Watch for:** in the UI, the step's **description** (the dropdown plan text) must never change
while the task runs, while the text **beside the tool name** rotates through hosts/titles/phase
names. Open the dropdown mid-run and confirm the plan reads exactly as it did when the task started.

**PASS** — plan text unchanged throughout; live detail visibly rotates; the card visibly advances
during phases where you can tell (from the log) no page has been fetched yet.
**FAIL** — plan text changes mid-run (the REQ-2 AC1 regression — this exact bug shipped once), or
the card sits frozen during a phase you can confirm from the log is actively running (search/
rerank/extract/cite).

**Historical note — read this before concluding PASS:** this exact feature was broken in production
by **two missing imports** (`time` and `urlparse`) in the phase-emission path, which a green unit
suite did not catch because nothing exercised the import at runtime under test. The whole reason
this live test exists is that class of bug — an import-time `NameError` only a real run surfaces.
If the card sits at `0/N` while the log shows real crawl activity, check
`backend/logs/irisvoice.log` for any exception in the phase-emission path before concluding the
feature itself is intact.

### P2.2 — Narration is audible

**Prove:** REQ-7 AC1/AC2 — the agent speaks progress during long-horizon work, using real content,
without a timer forcing it.

**Method:** run P2.1's prompt with speakers on. Listen.

**PASS** — you actually **hear** IRIS narrate something about the in-progress search, in real
content (not "Still researching the web."), at a moment that makes sense — not a fixed heartbeat
interval.
**FAIL** — silence throughout a multi-minute task, or a swallowed-exception log line
(`backend/agent/tools/speak_tool.py`) with no audio. Check for `[SpeakTool] SPEAK intent` in the log
— if it's present but nothing played, the narration decision fired but TTS itself failed; report
both facts separately.

### P2.3 — Sub-loop steps append to the same card

**Prove:** REQ-5 AC1/AC2 — steps DER discovers mid-task append to the existing card; no second card
appears.

**Method:** use T3's ambiguous multi-part prompt (it induces a DER split) and watch the card.

**PASS** — one card throughout, its step count growing as sub-loop children are discovered.
**FAIL** — a second card appears, or the step counter does not grow with the appended steps.

---

# Phase 3 — Local Model Loader

Covers: config derived from parsed model metadata + hardware; GPU-only ctx→batch degradation ladder;
per-model config cache; symlink-aware discovery; measured-throughput feedback. Automated coverage:
`scripts/validate_local_model_path.py` (7 CT-L contracts + 9 assertions). What only a live run adds:
this is measured against **real hardware** (RTX 3070 / 8GB) and **real model files**, which every
harness assertion above stubs out.

### P3.1 — First load derives; second load uses the cache

**Prove:** REQ-1 AC1/AC2 and REQ-5 AC1/AC3 — the loader parses metadata + hardware on first load, and
reuses the cached config on the next load of the **same** model.

**Method:** load a local GGUF model you have not loaded before. Unload it. Load it again.

**Watch for:** `GET /api/debug/caducean` → `loader_state.active_config` and
`loader_state.config_cache[<model>]` (`backend/api/caducean_debug.py:311-368`). Also the load log
line (REQ-7 AC1): model, config source, chosen `n_ctx`/`n_gpu_layers`/`n_batch`, estimated VRAM,
expected throughput.

**PASS** — first load logs `config_source=derived`; second load of the same model logs
`config_source=cache`; the cached entry in `config_cache` carries a `hw_fingerprint` and
`measured_tps`.
**FAIL** — second load re-derives from scratch (no cache hit), or the cache entry is missing
`hw_fingerprint`/`fingerprint`.

### P3.2 — VRAM pressure degrades context, then batch — never CPU offload

**Prove:** REQ-2 AC1/AC2 — an oversized chat model reduces context first, then batch size, and
`n_gpu_layers` never leaves `-1`.

**Method:** load a model sized to just barely not fit at its natural context on your 8GB card (or
force this by lowering the available-VRAM estimate if the loader exposes a test knob).

**Watch for:** `loader_state.active_config.n_gpu_layers == -1` throughout, and the degradation log
line (REQ-7 AC2) naming context reduction before batch reduction, with a reason and expected
throughput per step.

**PASS** — `n_gpu_layers` stays `-1` through every degradation step; context shrinks before batch;
the model loads (never silently fails onto CPU).
**FAIL** — any degradation step reduces `n_gpu_layers`, or the model silently falls back to CPU
offload — Decision Locked #4 forbids this outright; this machine cannot absorb the memory spike.

### P3.3 — A sustained sub-target run corrects the NEXT load

**Prove:** REQ-4 AC1-AC3 — measured throughput below `TARGET_TPS` (25, env-overridable) writes a
reduced-context correction to `.mcm/local_model_configs.json` that changes the **next** load, and
does **not** reconfigure the currently-running model.

**Method:** run a sustained generation that measures well below 25 tok/s (a large model, or a
deliberately throttled one). Let several generations complete so the measurement is "sustained," not
a single anomalous sample (REQ-4 AC5 deadband). Then unload and reload the same model.

**Watch for:** open `.mcm/local_model_configs.json` directly and confirm the entry for that model's
`config` changed after the slow run. Also check the throughput log line (REQ-7 AC3): measured tok/s
with the correction it produced, or that it fell in the deadband.

**PASS** — the config file's entry for that model changes after the sustained slow run, and the
**next** load uses the corrected (smaller) context — never the model that was already running.
**FAIL** — the file never changes despite a clearly sustained sub-target run, or the running model's
context changes mid-session (that would violate REQ-4 AC4).

---

# Phase 4 — Encoder (THE INSTALL)

**Status going in: BLOCKED, and the block is legitimate.** `sentence_transformers` is not installed
and the `LFM2.5-Embedding-350M` / `Encoder-350M` weights are absent from the model folder. Both
neural backends therefore fall back to hash/substring. `specs/phase-4-encoder/requirements.md`
REQ-7 AC2 explicitly forbids a silent download — acquiring these artifacts is a deliberate human
action, not something the agent should do on its own. This section is written as that action.

### P4.1 — Install `sentence-transformers` and fetch the two model artifacts

**Where the code looks (read, do not guess):**

- `backend/memory/embedding.py:370-394` (`_resolve_gguf_path` / `_discover_gguf`) — for
  **Embedding-350M**: checks `config.embedding.model_path` first, then scans
  `IRIS_MODEL_DIR`, `~/.lmstudio/models`, `~/Library/Application Support/LM Studio/models`, and the
  hardcoded `C:/Users/midas/.lmstudio/models`. It globs (case-insensitive) for a filename containing
  **both** `"embedding"` and `"350m"` and ending in `.gguf` — the code's own logged expectation is
  `'*embedding*350m*.gguf'` (`embedding.py:391`).
- `backend/agent/verifier.py:41-87` (`_load_default_encoder`) — for **Encoder-350M**: requires
  `transformers` **and** `torch` importable, then looks for
  `LFM-Korea/LFM2.5-Embedding-350M`* under the standard HF cache
  (`$HF_HOME/hub/models--LFM-Korea--LFM2.5-Embedding-350M`, default `~/.cache/huggingface`) with at
  least one non-empty `snapshots/` directory. It calls `AutoTokenizer.from_pretrained(...,
  local_files_only=True)` — **it will not download**.

  *(the literal model id string in the current code is
  `"LFM-Korea/LFM2.5-Embedding-350M"` at `verifier.py:66` — despite the variable/log naming saying
  Encoder-350M throughout; if you find the artifact under a different published repo id, use that
  id and note the mismatch in your report rather than silently reconciling it.)*

**Commands** (adjust the model source to wherever you obtain the actual weights — this plan does not
invent a download URL the code itself does not reference):

```bash
pip install sentence-transformers
```

Then place:
- The Embedding-350M **GGUF** file so its filename matches `*embedding*350m*.gguf`, into
  `C:\Users\midas\.lmstudio\models` (the user's symlinked HF cache — already a scan root per
  `embedding.py:403`) — or set `config.embedding.model_path` explicitly to its full path.
- The Encoder-350M **safetensors** model into the standard HF hub cache layout under
  `~/.cache/huggingface/hub/models--LFM-Korea--LFM2.5-Embedding-350M/snapshots/<rev>/` (or set
  `HF_HOME` to point at wherever the symlinked cache actually resolves it), so `local_files_only=True`
  can find it without a network call.

### P4.2 — Confirm the install took

**Watch for:** `GET /api/debug/caducean` → `encoder_state` (`caducean_debug.py:371-413`):
- `encoder_state.embedding_backend` should stop reporting `"hash"` and report `"lfm25-emb-350m"` (or
  `"bge-m3"` if you're only confirming the migration path still works) — **not** `hash`.
- `encoder_state.encoder_350m_loaded` should flip from `false` to `true`
  (`backend/agent/verifier.py:30`, set at `verifier.py:120` only on a successful load).

**Then run the currently-failing behavioral test:**

```bash
python -m pytest backend/tests/behavioral/test_long_pin_retrievable_by_tail.py -v
```

**PASS** — `encoder_state.embedding_backend != "hash"`, `encoder_state.encoder_350m_loaded == true`,
and `test_long_pin_retrievable_by_tail.py` passes (it currently fails **purely** because the models
are missing — this is the expected, disclosed reason, per REQ-2's chunking requirement needing a
real neural backend to be meaningful).
**FAIL** — either state field stays at its fallback value after the install, or the test still fails
with a **different** error than "model unavailable" — that would be a real regression, not the known
gap.

### P4.3 — Re-run the three measurement gates now unblocked

Once the models are confirmed loaded (P4.2 PASS), re-run the REQ-8 measurement gates that were
blocked on their absence. **Do not skip these** — REQ-8 is the phase's own gate: "every other
requirement replaces a working component with a smaller one; without measurement a regression is
invisible until a user cannot find their document."

1. **BGE-M3 baseline (tasks.md T0.3).** Record recall@k, latency, and resident memory for the
   **current** default backend (`bge-m3`) before comparing — this is the "before" number
   `eval_embedding_quality.py`'s report explicitly separates from the "after" (T2.5).
2. **recall@k via the eval tool:**
   ```bash
   python scripts/eval_embedding_quality.py --backend lfm25-emb-350m --out backend/tests/data/eval_results.json
   ```
   This scores `backend/tests/data/retrieval_probe.json` for recall@1/5/10, latency, and — if the
   Encoder-350M loaded — the semantic verification scorer against
   `backend/tests/data/verification_probe.json`, reporting **both** error directions separately
   (false-FAILED vs false-VERIFIED, REQ-8 AC3) rather than one blended accuracy number. If the tool
   reports `STATUS: BLOCKED_MODEL_UNAVAILABLE`, the install did not take — go back to P4.1/P4.2.
3. **ColBERT deferral decision (tasks.md T5.4).** The decision rule is REQ-7 (Decision Locked #7) +
   REQ-8 AC6: ColBERT-350M stays deferred — **not built** — until Embedding-350M's measured recall
   is known and passes the gate. There is no separate numeric threshold to invent here; the rule is
   "measure first, build only if the measurement clears REQ-8 AC5's bar" (recall not materially below
   the BGE-M3 baseline from step 1). Record whichever decision the numbers produce in
   `specs/phase-4-encoder/tasks.md` next to T5.4 — do not adjust the probe set to manufacture a pass
   (REQ-8 AC5 forbids exactly that).

**PASS** — all three gates produce a recorded number (or an honest "inconclusive, probe set too
small" per REQ-8's own edge case) and a written decision on ColBERT.
**FAIL** — a gate is skipped, or a number is massaged to clear the bar rather than reported as-is.

### P4.4 — Do NOT flip the default; the cross-space refusal is your safety net

**Loud warning, not a test to pass/fail so much as a rule to enforce while running the above:** the
default embedding backend stays `bge-m3` (`backend/memory/embedding.py:245,279-289`) and is
reversible via `config.embedding.backend`. **Do not flip the default to `lfm25-emb-350m`** until
P4.3's recall@k gate is measured and clears REQ-8 AC5. Both backends are 1024-dim
(`EMBEDDING_DIM = 1024`, `embedding.py:246`), so a cross-space comparison would otherwise return a
plausible-looking, silently-wrong number rather than crashing. If at any point during this testing
you see a `CrossSpaceComparisonError` (`embedding.py:54-60`) raised, **that is the guard working
correctly** — do not treat it as a bug; report which code path triggered it so the dual-read logic
around it can be checked.

---

# Phase 5 — Switcher + ContextPill

Covers: Send pill removed with its guards moved into the send path; model switcher in the chat input
row; non-chat providers excluded from Brain/Tool; ContextPill live on every response. Automated
coverage: `scripts/validate_switcher.py` (5 CT-S contracts + 7 assertions, including a live-DOM Jest
check of the InputRow guards). What only a live run adds: does the switcher **feel** integrated in
the row, and does the pill actually update on a plain non-DER reply in the browser.

### P5.1 — Switcher is in the input row; Send pill is gone; Enter still guarded

**Prove:** REQ-1 AC1-AC3 and REQ-2 AC1 — `<ModelSwitcher>` renders as a sibling of `<ContextPill>`
in the chat input row (`components/chat-view.tsx:3551-3561`), no Send button exists, and every guard
the button used to carry (`!inputText.trim() || isTyping || voiceState === 'listening'`,
`chat-view.tsx:1137`) still blocks a send from `Enter`.

**Method:** open the chat UI. Confirm no Send button. Type a message and press Enter while:
(a) input is empty, (b) a response is currently streaming (`isTyping`), (c) voice is actively
listening.

**PASS** — no Send button anywhere in the row; Enter sends normally when none of the guards apply;
Enter is a no-op in all three guarded states.
**FAIL** — Enter sends a message while a response is streaming or voice is listening — this is the
"guard deleted with the button" failure REQ-1 AC3 exists specifically to prevent, and it produces
**no error**, only a mid-response message injected silently.

### P5.2 — Non-chat providers never appear as Brain or Tool

**Prove:** REQ-2 AC4 and the Phase 4 REQ-6 AC3 fix to `ModelInferenceSection.tsx:82-84` — an
embedding or rerank provider must not be selectable for `reasoning` or `tool_execution`, in **both**
the chat-row switcher and the Settings panel's Brain/Tool selectors.

**Method:** with Embedding-350M or Encoder-350M registered (from Phase 4, or even hash-fallback
registration if the model isn't installed — `purpose` is set regardless of load success), open both
the chat-row switcher dropdown and the Settings panel's model selectors.

**PASS** — neither surface lists the embedding/rerank provider as a Brain or Tool option.
**FAIL** — it appears in either place.

### P5.3 — ContextPill is live on EVERY response, not just DER turns

**Prove:** REQ-6 AC1 — `context:usage` fires at the completion of every non-DER (direct) reply too,
with the same denominator as the DER path.

**Method:** send a short message that resolves without triggering the DER loop (a simple direct
reply) and watch the pill update. Then send a message that does trigger DER and confirm the pill
updates there too, with the same `max_tokens`.

**PASS** — the pill's token count visibly updates after the plain direct reply, not just after DER
turns, and the denominator is identical in both cases.
**FAIL** — the pill stays stale after a direct (non-DER) reply — the exact REQ-6 gap this phase
closes.

### P5.4 — Two UI fixes: one thinking indicator, no horizontal step-text shift

**Prove:** the two UI polish items folded into Phase 5's execution — a task card and a "thinking…"
spinner must not both render at once, and a step's text must not visibly jump sideways when it goes
active.

**Method:** trigger a task with at least one plan step and watch the transition from "no card yet" to
"card with steps" closely, and watch a step go from `pending` to `working`.

**PASS** — exactly one thinking/progress indicator visible at any time; step label position does not
shift horizontally when a step activates (only its icon/animation state changes).
**FAIL** — a spinner and a task card both visible simultaneously, or text visibly reflows sideways on
step activation.

---

# Phase 6 — DER Integrity + Self-Tuning

Covers: T6 above (the compound gate). Additionally:

### P6.1 — Every executed action commits a labeled outcome, including failures

**Prove:** REQ-1 AC1 — VERIFIED, UNVERIFIED, and FAILED steps all write a ledger row; a vetoed
action that never executed writes **none** (Decision Locked #1 — that omission is honesty, not a
bug).

**Method:** drive a task with at least one step you can force to fail (a bad tool argument, an
unreachable URL) alongside steps that succeed normally.

**Watch for:** `der_commits` rows for the session — there is no debug-endpoint surface for this
directly, so confirm via the same mechanism `scripts/validate_outer_loop.py` assertion 9 uses:
after the task completes, the failed step's outcome must be visible in the UI as failed (Phase 2
REQ-1 AC4 — never success-styled), and the outer loop's next `held_out_score.verified_fraction`
reading (T6 above) should move if you drive enough sessions with a different failure mix.

**PASS** — the failed step renders as failed in the UI (not silently dropped, not success-styled),
and a vetoed step (if you can trigger one — e.g. a step blocked by a safety guard) shows as
"vetoed / not executed" with no result preview.
**FAIL** — a failed step renders as if it succeeded, or a vetoed step shows a fabricated result.

### P6.2 — Per-domain gating

**Prove:** REQ-3 AC1/AC2 — the compound gate applies per-domain when ≥2 held-out sessions exist per
domain, falling back to the pooled gate otherwise (AC3).

**Note:** this is the hardest item in this plan to observe live — it requires driving enough sessions
in at least two distinct domains (e.g. `research` and `general`) for the per-domain path to engage
at all, and the debug endpoint does not currently expose a per-domain breakdown (only the pooled
`held_out_score`). Treat a full live confirmation of this one as **best-effort**; if you cannot
accumulate enough same-domain sessions in a single sitting, record that as INCONCLUSIVE with the
session counts you did achieve, rather than forcing a conclusion.

**PASS** — if you can get ≥2 sessions in two domains, and independently confirm via
`scripts/validate_outer_loop.py` (which does assert this at the unit level) that per-domain gating
is exercised.
**INCONCLUSIVE** — insufficient same-domain session volume in one sitting. This is an honest,
acceptable outcome — do not force it.

---

## Regression section — known-failing suites, do not chase these

Three Jest suites in `tests/bugfix/` are **known-failing** and unrelated to this programme. Do not
spend time "fixing" them as part of executing this plan:

| File | Why it fails |
|---|---|
| `tests/bugfix/tauri-dev-compilation-bug-exploration.test.js` | Self-declared: *"This test is designed to FAIL on unfixed code to confirm the bug exists... DO NOT attempt to fix the test or the code when it fails."* (file header, lines 6-13). |
| `tests/bugfix/iris-widget-tilt-transform-bug-exploration.test.js` | Same pattern: *"This test MUST FAIL on unfixed code — failure confirms the bug exists... DO NOT attempt to fix the test or the code when it fails."* (file header, lines 4-5). |
| `tests/bugfix/tauri-dev-compilation-preservation.test.js` | Asserts `packageJson.scripts.dev === 'next dev'` (line 469) and `packageJson.scripts['dev:frontend'] === 'next dev'` (line 470). The real `package.json` now has `"dev": "node node_modules/next/dist/bin/next dev -H 0.0.0.0"` and `"dev:frontend": "node node_modules/next/dist/bin/next dev --webpack"` — the assertion has drifted from the actual dev scripts; this is a stale test, not a live regression. |

If you run `npx jest` as part of any phase's checks and these three show up red, that is expected
and out of scope for this plan.

---

## Reporting

For each test record: **PASS / FAIL / INCONCLUSIVE**, the **raw log line or endpoint JSON** observed
— not a prose claim — and, where applicable, the exact prompt used and the wall-clock time of the
run (useful for cross-referencing `backend/logs/irisvoice.log`).

**This plan produces evidence; it does not itself graduate anything.** `bootstrap/GOALS.md` is
updated in a separate pass, only after this evidence exists and has been reviewed — do not edit
`GOALS.md` as part of executing this plan.

Historical graduation mapping (Caducean flag-off items only — Phases 1–6 do not yet have a
corresponding GOALS.md domain entry as of this writing; confirm current domain numbering against
`bootstrap/GOALS.md` before updating it):

- `[21.5]` graduates on **T1 + T2 + T7**
- `[21.4]` graduates on **T4**
- `[21.6]` graduates on **T5 both steps** — and only then is a landmark crystallized for it
- **T6** now graduates on `live_guards: 3` + `dead_guards: []` + a genuinely varying
  `verified_fraction` across session mixes (previously it only confirmed a known gap; it repairs
  that gap now)

**INCONCLUSIVE is a valid and useful result.** T3 needs a split to occur, T4 needs two genuine
concurrent sessions, and P6.2 needs same-domain session volume — none of these can be forced. Record
the reason rather than retrying until the outcome looks green — an inconclusive result honestly
reported is worth more than a pass obtained by reshaping the test.

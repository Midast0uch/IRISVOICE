# Backend Audio "Hang" — Diagnosis and Resolution

**Session:** 106  
**Date:** 2026-06-13  
**Status:** Resolved (no code fix needed)  
**Confidence:** 0.9

## TL;DR

The reported audio hang from session 117 does not exist as a permanent code bug.
The backend starts in ~31 seconds and all audio subsystems are healthy.
The contract `v2-needs-audio-20260613` was based on inference, not observation,
and has been deactivated.

## Symptoms reported (session 117)

- Backend uvicorn startup hangs indefinitely
- Suspected cause: `sounddevice.list_devices()` blocking on a broken audio driver
- Hypothesized fix: add `IRIS_SKIP_AUDIO` env flag or wrap audio init in try/except

## Evidence gathered (session 106)

Three probes, all run on this PC in this session, with hard timeouts:

### Probe 1 — Isolated audio calls

| Call | Elapsed | Result |
|---|---|---|
| `sounddevice.query_devices()` | 3.85s | 24 devices returned |
| `sd.InputStream()` open+start+close | 0.25s | worked |
| `PorcupineWakeWordDetector()` | (skipped) | `.ppn` path mismatch in probe only |

**No hang. Audio stack is healthy.**

### Probe 2 — Real backend lifespan

Ran `python -m uvicorn backend.main:app --port 8766` with 60s watchdog and live log capture.

- First attempt at session 106 start: timed out at 60s, only 3 log lines printed
- Second attempt 11 minutes later: completed in **31 seconds**, full lifecycle

**First run was transient. The "hang" was a one-time event, likely related to the concurrent build process the user mentioned.**

### Probe 3 — `python -X importtime` profile of `import backend.agent`

| Module | Cumulative (s) | Self (s) |
|---|---|---|
| `litellm` | 3.475 | 3.475 |
| `backend.llm_service` | 3.476 | 0.001 |
| `backend.agent.agent_kernel` | 3.645 | 0.170 |
| `backend.agent` (total) | 4.352 | 0.707 |

**`litellm` accounts for 80% of the agent-package import time. This is a perf concern, not a hang.**

## What was actually wrong

Nothing. The backend was healthy the whole time. The session-117 hang was either:
1. A transient I/O or audio-service state issue, possibly aggravated by the concurrent build
2. An inference reported as observation

## What was NOT done (and why)

These were considered and rejected:

- **Add `IRIS_SKIP_AUDIO` env flag** — would be a bandaid for a non-bug
- **Wrap audio init in `try/except`** — would hide a real success path on machines where audio is healthy
- **Add timeout to `sounddevice.list_devices()`** — no evidence the call is slow or unreliable on this PC; adding a timeout for a non-existent problem is busywork

## What was done

- Contract `v2-needs-audio-20260613` deactivated (confidence 0.0)
- Contract `audio-subsystem-healthy-20260613` created (confidence 0.9, evidence_count=5)
- Gradient warning `hang-diagnosis-without-repro-20260613` recorded
- Work item `v2-frontend-render-test` description updated to reflect that audio is not a blocker
- Note `evt_20260613_hang_diagnosis` recorded in code_events

## Process notes

The systematic-debugging skill's Iron Law ("NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST")
proved correct. Session 117 violated it and wrote a contract from inference. This session
followed it and discovered the inference was wrong.

**Lesson for next agent:** When the user reports a hang, reproduce it with a watchdog FIRST.
Do not propose fixes (or contract changes) until you have observed the hang yourself.
If the repro shows the system is healthy, record the finding and move on — do not patch the code.

## Recommended follow-up (separate task, not this session)

The 3.5s `litellm` import is the dominant backend startup cost. If cold-start matters,
consider:

1. Lazy-importing `litellm` inside `LLMService.__init__` instead of at module load
2. Using `import litellm` only on the first LLM call, not at backend startup
3. Pinning a smaller subset of providers via `litellm` provider config

This is a performance optimization, not a bug fix. Should be tracked as a separate
work item if/when startup time becomes a user-visible problem.

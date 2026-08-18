# Requirements: Unified Vision Capability Routing

## Decisions Locked
User-resolved. Do not re-litigate.

1. **Vision is a capability lookup, not a service.** Resolution order is
   BRAIN -> TOOL -> VL fallback. Many API brains are multimodal (GPT-4o, Claude,
   Gemini) and a local model loaded with its projector qualifies too; in those
   cases nothing local loads for vision at all.
2. **The API brain does not need vision to USE vision.** The vision model is a
   TOOL the brain calls. The brain emits the tool call, the vision model answers,
   the answer returns as a tool result.
3. **The VL fallback is SIZE-SELECTED from free VRAM, not hardcoded.** Both roles
   remote -> nothing resident -> LFM2.5-VL-3B (2.36GB). A local brain/tool
   resident -> LFM2.5-VL-450M (0.70GB). The user's stated preference falls out of
   the arithmetic; no special-casing.
4. **No VL model is pinned permanently resident.** Rejected: when brain or tool
   has vision, step 3 never fires and a resident VL model is pure waste.
5. **The existing vision subsystem is KEPT, not deleted.** An earlier plan to
   "remove the vision server" was WRONG. `backend/tools/lfm_vl_provider.py`
   already implements leases, idle-stop, owned-PID tracking and a VRAM reserve.
   It becomes step 3 of the hierarchy.
6. **A local model's projector is attached at LOAD time and costs measurably.**
   gemma-4-E4B: 64.5 tok/s text-only -> 42.1 tok/s with `--mmproj`, +1.2GB VRAM.
   Default to attaching, but SURFACE the cost and allow loading without it.
7. **Priority is speed and context.** A single multimodal brain costs ~5x
   generation speed (224 -> 42 tok/s), so it is a deliberate choice, never a
   default.

## Introduction
Vision today always routes to a dedicated LFM2.5-VL llama-server, even when the
active brain or tool model can already see. On an 8GB card where only one local
model fits, that wastes VRAM and pays a cold start on first vision request. This
feature makes vision resolve to whoever can already serve it, and reserves the
dedicated server for the case where nobody can.

### Success criteria
- A multimodal API brain answers a vision task with **zero** local model loads.
- A local model loaded with its projector answers vision tasks itself.
- When neither can, the largest VL model that FITS current free VRAM is used.
- First vision request via the fallback is not delayed by llama.cpp auto-fit.
- `mmproj-*.gguf` projector files never appear as loadable brains.

## Requirements

### REQ-1: Vision capability detection per provider
**User Story:** As IRIS I want to know whether a bound provider can see, so that
I do not load a vision model that is not needed.

**Verified:** NEW (unverified - implementation pending). Grounded against
`backend/agent/inference/provider.py:16-22` (ProviderKind: API / LOCAL_OPENAI /
INPROCESS / OLLAMA) and `backend/agent/agent_kernel.py:_KNOWN_CONTEXT_WINDOWS`
(the existing table pattern this mirrors).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL expose `supports_vision(instance) -> bool` for any
  `ProviderInstance`.
- AC2: WHEN the instance kind is `API` THEN THE SYSTEM SHALL resolve vision from a
  `(provider_id, model_substring)` table, mirroring `_KNOWN_CONTEXT_WINDOWS`.
- AC3: WHEN the instance kind is `LOCAL_OPENAI` or `INPROCESS` THEN THE SYSTEM
  SHALL report vision only if the running server was launched WITH a projector -
  never merely because a sibling `mmproj-*.gguf` exists on disk.
- AC4: WHEN the instance kind is `OLLAMA` THEN THE SYSTEM SHALL resolve vision
  from the model's advertised capabilities.
- AC5: IF capability cannot be determined THEN THE SYSTEM SHALL report False.

**Edge Cases:**
- Unknown API model id -> False. Falling through to the fallback is recoverable;
  wrongly claiming vision is not.
- Provider registered but not loaded -> False.
- Ollama unreachable -> False, logged, no raise.

### REQ-2: Vision resolution hierarchy
**User Story:** As a user I want vision handled by whatever model can already see,
so that I do not pay VRAM or load time for a capability I already have.

**Verified:** NEW. Bindings traced at
`backend/agent/inference/router.py:resolve()` (role -> ProviderInstance, falls
back to `default_role`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL expose `resolve_vision_provider()` returning the provider
  that will serve vision.
- AC2: WHEN the `reasoning` binding supports vision THEN THE SYSTEM SHALL return
  it and SHALL NOT start or load any vision model.
- AC3: WHEN reasoning cannot see but `tool_execution` can THEN THE SYSTEM SHALL
  return the tool binding.
- AC4: WHEN neither can see THEN THE SYSTEM SHALL return the VL fallback.
- AC5: THE SYSTEM SHALL log which tier answered and why, once per resolution.

**Edge Cases:**
- Role unbound -> treated as no-vision, continue down the hierarchy.
- `resolve()` raises -> treated as no-vision, never propagate.
- Both roles bound to the SAME multimodal provider -> returned once, not twice.

### REQ-3: Size-selected VL fallback
**User Story:** As a user on an 8GB card I want the best vision model that
actually fits right now, so that vision never fails for want of VRAM and never
wastes it.

**Verified:** `backend/tools/lfm_vl_provider.py:277-299` currently prefers
LFM2.5-VL-3B unconditionally when present, with the 450M only as a
"never-downloaded-the-3B" fallback. That preference is NOT VRAM-aware - this
requirement changes it.

**Acceptance Criteria:**
- AC1: WHEN the fallback is required THEN THE SYSTEM SHALL select the largest
  projector-paired VL model whose weights + projector + KV fit current free VRAM.
- AC2: THE SYSTEM SHALL add the projector's own file size to the weights term - it
  is a separate GGUF and is absent from the base model's size.
- AC3: THE SYSTEM SHALL preserve the existing `_VISION_VRAM_RESERVE_GB` margin so
  a later local-model load is still possible.
- AC4: IF no VL model fits THEN THE SYSTEM SHALL fail with a message naming the
  free VRAM and the smallest candidate's requirement - never silently load on CPU.
- AC5: THE SYSTEM SHALL log the chosen model, its estimated footprint and the free
  VRAM figure that decided it.

**Edge Cases:**
- No VL model present on disk -> explicit error naming the expected repos.
- Free VRAM unreadable -> use the most conservative candidate.
- A VL model present without its projector -> skipped, logged.

### REQ-4: Local models load with their projector
**User Story:** As a user I want to choose a multimodal local brain and have it
actually see, so that one resident model serves both text and vision.

**Verified:** REAL GAP. `grep -c mmproj backend/agent/local_model_manager.py` == 0
- the loader never passes a projector today. `-mm/--mmproj FILE` confirmed present
in prismml b9591 `--help`.

**Acceptance Criteria:**
- AC1: WHEN a base model has a sibling `mmproj-*.gguf` THEN `_build_server_cmd`
  SHALL pass `--mmproj <path>` by default.
- AC2: WHERE the caller opts out THE SYSTEM SHALL load without the projector.
- AC3: THE SYSTEM SHALL include the projector's size in the pre-flight VRAM
  estimate and in the load plan.
- AC4: THE SYSTEM SHALL record on the loaded provider whether a projector was
  attached, so REQ-1 AC3 can answer truthfully.
- AC5: THE SYSTEM SHALL surface the measured cost of attaching (~-35% generation,
  +1.2GB on gemma-4-E4B) in the model browser.

**Edge Cases:**
- Multiple projectors in one directory -> prefer exact stem match, else log and
  skip.
- Projector present but VRAM insufficient with it -> offer the text-only load
  rather than failing outright.

### REQ-5: Projectors are not loadable models
**User Story:** As a user I do not want to be offered a projector file as a brain.

**Verified:** REAL GAP. Live `/api/models` returned 18 entries including
`mmproj-Bonsai-27B-BF16.gguf`, `mmproj-gemma-4-E4B-it-BF16.gguf` and
`mmproj-LFM2.5-VL-3B-F16.gguf` as loadable rows with their own load plans.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL exclude `mmproj-*.gguf` from `scan_models` results.
- AC2: THE SYSTEM SHALL attach each projector to its base model as
  `has_vision: true` and `mmproj_path`.
- AC3: WHEN a base model has a projector THEN the browser SHALL indicate vision
  capability.

**Edge Cases:**
- Orphan projector with no base model -> excluded, logged at debug.
- Base model in a different directory from its projector -> matched by stem.

### REQ-6: Fallback cold start is not stalled by auto-fit
**User Story:** As a user I want the first vision request to be fast.

**Verified:** REAL GAP. `--fit on` is llama.cpp b9591's default and was measured
stalling 12-36 minutes on MoE models; fixed for the MAIN loader in commit e9d2fc89
(`local_model_manager.py`, `cmd += ["--fit", "off"]`). The vision server spawn is a
SEPARATE code path and does not yet carry it. This is the likely root cause of the
reported "vision server slow on first request".

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL pass `--fit off` when spawning the vision server.
- AC2: THE SYSTEM SHALL pass explicit `--ctx-size`, `--n-gpu-layers` and
  `--batch-size` rather than relying on auto-fit.
- AC3: THE SYSTEM SHALL log time-to-ready for each vision server start.

**Edge Cases:**
- Server exits during start -> surface the last stderr lines, do not report a
  timeout.

### REQ-7: MODEL STATUS badge reflects reality
**User Story:** As a user I want the badge to tell me the truth about what is
loaded.

**Verified:** REAL GAP, PARTIALLY FIXED. The WS handler wrote only
`fieldValues.local_model` while the field is declared under section id
`local-model-card` (`data/cards.ts:237`) and resolved by SECTION id
(`components/dark-glass-dashboard.tsx:263`). Fixed in e9d2fc89. The REMAINING
cause is unfixed: after a page reload nothing re-sends `local_model_status`, and
initial seeding never maps `inference.local_model_status` from config - the badge
read UNLOADED live while a model was demonstrably resident on the GPU.

**Acceptance Criteria:**
- AC1: WHEN the dashboard mounts THEN THE SYSTEM SHALL seed the badge from the
  backend's persisted `inference.local_model_status`.
- AC2: WHILE a model is loaded THE SYSTEM SHALL display LOADED after any page
  reload.
- AC3: WHEN a load fails THEN THE SYSTEM SHALL display ERROR, not UNLOADED.

**Edge Cases:**
- Config says loaded but no server is listening -> reconcile to UNLOADED.

### REQ-8: Local provider endpoint uses the real port
**User Story:** As a developer I want one source of truth for the local model port.

**Verified:** REAL GAP. `backend/iris_config.py:382` hardcodes
`endpoint="http://127.0.0.1:8081"` for a migrated `LOCAL_OPENAI` ProviderEntry,
while `LocalModelManager.PORT` is `8082` (`local_model_manager.py:662`). A migrated
binding therefore points at the vision port.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL derive that endpoint from `LocalModelManager.PORT`.
- AC2: THE SYSTEM SHALL NOT hardcode a port literal in the migration path.

**Edge Cases:**
- `IRIS_LOCAL_MODEL_PORT` overridden -> migration follows it.

### REQ-9: Observability for vision routing
**User Story:** As the tuner I want to see which tier served each vision task, so
that I can tell whether the hierarchy is behaving and what it costs.

**Verified:** NEW

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log, per vision resolution: the tier
  (brain/tool/fallback), the provider id, whether a model load was required, and
  free VRAM at decision time.
- AC2: WHEN the fallback is chosen THEN THE SYSTEM SHALL log the candidate ladder
  and why each rejected candidate did not fit.
- AC3: THE SYSTEM SHALL log time-to-first-vision-response separately from load
  time, so cold-start cost is measurable against steady state.

**Edge Cases:**
- High-frequency vision calls -> logging stays off the inference path.

### REQ-10: User-configurable, model-agnostic vision fallback ladder
**User Story:** As a user I want to choose which of MY models act as the vision
fallback, from my own models directory, so that IRIS never hardcodes a model I did
not pick.

**Verified:** NEW. Candidate discovery comes free from REQ-5, which already attaches
`has_vision` / `mmproj_path` / `mmproj_size_gb` to every projector-paired base model.
Precedent for the selection shape: `_PROFILE_LADDER` + `recommend_profile` in
`backend/agent/local_model_manager.py` (widest-first, take the first that fits).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL offer every scanned model with `has_vision: true` as a
  candidate for the vision fallback ladder.
- AC2: THE SYSTEM SHALL let the user select and ORDER that ladder from the frontend.
- AC3: THE SYSTEM SHALL persist the chosen ladder in `cfg.inference` so it survives
  a restart.
- AC4: WHEN the user has chosen a ladder THEN REQ-3 size-selection SHALL apply to
  THAT ladder rather than to any built-in list.
- AC5: IF the user has chosen nothing THEN THE SYSTEM SHALL auto-select the widest
  `has_vision` model that fits — never a hardcoded model id.
- AC6: IF a configured model is missing from disk THEN THE SYSTEM SHALL skip it,
  log it, and continue down the ladder.
- AC7: THE SYSTEM SHALL contain no hardcoded GGUF model id in the fallback path.

**Edge Cases:**
- User selects a model whose projector was deleted -> skipped, logged.
- User orders a model first that cannot fit any plausible free VRAM -> skipped at
  selection time with the reason logged, not a hard failure.
- No `has_vision` models at all -> explicit error naming what is required.

**Note for the implementer:** the models named in REQ-3 (LFM2.5-VL-3B, 450M) are
DEFAULTS AND EXAMPLES, not a contract. This requirement is the house style for any
future model ladder — user picks, system size-selects — so nothing in the loader
ever names a specific GGUF again.

## Non-Requirements (Out of Scope)
- Writing CUDA kernels for ternary types (maple - dropped by the user).
- Multi-model concurrent serving; llama-server is one model per process.
- Changing `vision_guided_operator.py` / `automation/vision.py` tool semantics.
- Reducing backend RSS (Pocket-TTS lazy load) - separate work.
- Deleting the vision subsystem (explicitly reversed; see Decisions Locked 5).

## Open Questions
- Is LFM2.5-VL-450M's vision quality sufficient for real browser/desktop control?
  It becomes the DEFAULT whenever a local brain is resident, so this matters more
  than when it was one of two equal options. **Test before shipping.**
- Should a multimodal local brain answering vision itself still take a vision
  LEASE, so idle accounting stays uniform across tiers?

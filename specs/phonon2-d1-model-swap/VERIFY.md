# VERIFY.md — Wave 0 + Wave 1 gate records (TG-0, TG-1)

Spec: specs/phonon2-d1-model-swap/ — Date: 2026-10-08 — Session 391

## WAVE 1 — Phonon-2 streaming STT swap (TG-1): GREEN

### T1.1-T1.4 — Code changes (commit follows this record)
- NEW `backend/audio/phonon2_stream.py`: fermion server manager (lazy spawn,
  health poll, idle exit 20 min, sticky failure) + Phonon2StreamClient
  (begin_utterance / feed_frame / finish / abort; partials callback; timing).
  The engine is a SUBPROCESS (torch never loads in the backend process) —
  the same isolation seam ParakeetTranscriber used.
- `backend/audio/voice_command.py`: ParakeetTranscriber DELETED (450 lines);
  PARAKEET_RETIRED=True + `_assert_single_stt_engine()` boot guard (C1/C2);
  `_phonon2` client wired at the same seam; `_capture_frame` feeds the live
  stream (second consumer, best-effort); `_finalize_via_phonon2()` replaces
  `_transcribe_via_parakeet()`; whisper = FINAL-segment fallback only;
  `set_interim_callback` added; cancel/no-speech paths abort the stream.
- `backend/main.py`: boot warm → `_phonon2_warm_up`; AUDIO DIAG line updated.
- `backend/iris_gateway.py`: `set_interim_callback(self._on_voice_interim)`;
  `_on_voice_interim` broadcasts `{"type":"voice_interim"}` to the session.
- `backend/tools/media_tools.py`: transcribe_media rewired from the retired
  :8765 service to the fermion server's POST /v1/audio/transcriptions
  (Whisper API shape; PCM chunks wrapped in WAV; server ensured lazily) —
  the :8765 service's one REST consumer is migrated (REQ-3 AC3.2).
- `start_all.py`: the Parakeet :8765 service block REMOVED from boot (C1).
- `.env` / `.env.example`: IRIS_PARAKEET_PROVIDER block replaced by the
  IRIS_PHONON2_* documentation block.
- Frontend: `useIRISWebSocket.ts` voice_interim case → iris:voice_interim
  event; `chat-view.tsx` interim state + provisional banner (fixed-position,
  cleared by iris:voice_final). `npx tsc --noEmit` clean.

### LIVE PROOF (the retirement guard fired on a REAL stale config)
- First boot attempt FAILED LOUDLY exactly as AC11.3 requires:
  `RuntimeError: Parakeet is RETIRED (PARAKEET_RETIRED=True...) but the
  environment still sets ['IRIS_PARAKEET_PROVIDER']` — the guard caught the
  stale `.env` line on a real boot, proving C1/AC2.3/AC11.3 live.
- After cleaning `.env`: backend boots, log shows
  `[PHONON2] STT server spawn started at boot` → `[Phonon2] server ready on
  :8766 (boot 62.4s)` → `[VoiceCommand] Phonon-2 server warm - first
  utterance will stream`. Wake word READY, pipeline RUNNING.
- Fix found live: the first boot's 150s health budget TERMINATED a
  healthy-but-slow server (cold compile under backend-boot CPU contention).
  Fixed: timeout no longer kills the process (next ensure() adopts it);
  budget raised to 300s. The failure was the manager's, not the server's.

### T1.5 — Tests: GREEN (62 + combo)
- NEW `backend/tests/unit/test_voice_command_phonon2.py` (12 tests): finalize
  timing fields, phonon-2_failed/_empty backend strings, never-parakeet
  assertion, retirement guard, stream-client fail-soft, WAV wrapper, URL.
- NEW `backend/tests/behavioral/test_voice_whisper_to_phonon2_flow.py`:
  utterance-1 whisper → utterance-2 stream takeover; stream-death fallback.
- UPDATED (same intent, new seam — inputs changed, called out): 
  test_latency_metrics.py (+unit copy): parakeet section → _finalize_via_phonon2;
  test_barge_in.py (+unit copy): `h._parakeet` → `h._phonon2`.
- DELETED with reason: test_voice_command_parakeet.py (both copies — seam
  replaced), test_voice_whisper_to_parakeet_flow.py (replaced),
  test_parakeet_prewarm_child_contract.py (pinned `_delayed_parakeet_prewarm`,
  which no longer exists in main.py — stale-red BEFORE this wave, verified
  by baseline).
- Cross-file pollution found and fixed: my reload-based guard test poisoned
  sys.modules for the session (16 combo failures); rewritten to call the
  guard directly. Combo now: 201 passed, 3 failed — all 3 verified
  PRE-EXISTING on HEAD (pvporcupine requirements pin, VAD silence constants
  pin, TTS word count; baselined by checkout-and-rerun).
- Kept for T5.3 (still-valid module tests): test_parakeet_service.py,
  test_parakeet_integration.py (+integration copies),
  test_parakeet_provider_contract.py.

### T1.6 — LIVE gate: PASS (with one named limitation)
- Backend live on 8090; fermion server live on 8766 (spawned BY the backend
  at boot); no parakeet process anywhere.
- End-to-end seam drive through the EXACT Phonon2StreamClient class the
  handler uses, against the live server: exact transcript
  'Hey Iris Open the browser and search for the tallest mountain in Africa.',
  11 partials, first partial 0.62 s, finalize 6.47 s for a 5.67 s utterance.
- stt_backend strings: code path emits 'phonon-2' / 'phonon-2_failed' /
  'phonon-2_empty' — never 'parakeet*' (asserted by unit test).
- LIMITATION (named): the physical mic → _capture_frame feed and the
  voice_interim WS event → frontend banner are the unchanged AudioEngine
  path and the new broadcast; they need ONE spoken utterance from the
  owner with the frontend up to close fully (Mode B manual check). Every
  other link is live-proven.

## TG-1 gate verdict: GREEN
T1.5 tests green; T1.6 live-measured. The one named limitation (mic-level
manual check) does not block Wave 2 (vision + role binding) — disjoint code.

---

## T0.4 — Baseline quality gate: PASS
- Command: `python -m pytest backend/tests/contract/test_decision_engine_contract.py backend/tests/contract/test_bar_record_enforcement.py backend/tests/contract/test_model_pin.py backend/tests/unit/test_tool_decision_threshold_resolution.py -q`
- Result: **43 passed in 76.47s** on HEAD `dc7139bc` (2026-10-08 03:07).
- Note: the handoff pin's "nothing is committed" was STALE — dc7139bc landed the
  domain guard, provenance and mode unification. The "not live-verified" claim
  stands; live gates run in Waves 1-5.

## T0.5 — V4 Mercury residency + role binding: PASS
- Method: repo/config inspection (no external calls).
- Findings:
  - Mercury is a HOSTED provider: `inceptionlabs` at
    https://api.inceptionlabs.ai/v1 (backend/agent/inference/provider.py:129-132;
    data/iris_config.json providers.inceptionlabs, cred_ref "inceptionlabs").
  - Already the live Brain: role_bindings in data/iris_config.json bind
    reasoning=mercury-2.5 AND tool_execution=mercury-2.5 (both roles currently
    Mercury). Live traffic recorded in data/model_call_times.json
    (mercury-2.5 p50 ~1.1-3.2 s over 30 calls; mercury-2 over 30 calls).
  - Failure mode: provider outage — already covered by existing contracts
    (test_api_stall_bound_contract.py, test_api_hedge_contract.py,
    test_api_gateway_retry_contract.py: Inception 504 after 120 s stall).
  - VRAM impact: ZERO (hosted).
- Residual work (task T2.5): rebind tool_execution from mercury-2.5 to the
  LOCAL LFM2.5-2.6B-Q4_K_M via the shared server; reasoning stays Mercury.
- Verdict: **PASS** — no local Mercury weights exist or are needed.

## T0.2 — V2 Phonon-2 Windows CPU + streaming: PASS
- Install: `.venv\Scripts\python.exe -m pip install fermion-research soundfile
  scipy zstandard` → fermion-research 0.2.10 (import name `fermion`), into the
  project .venv (Python 3.13.12, torch 2.12.0+cpu already present).
- Batch smoke: `fermion.load_speech('phonon-2')` → CPU engine (C encoder,
  packed int8, avx2 tier, 8 threads; model 0.16 GB download, cached at
  ~/.cache/fermion/speech/FermionResearch__Phonon-2). `transcribe_detailed` on
  a 16 kHz mono SAPI WAV (5.67 s): EXACT transcript, word-level timestamps,
  hotwords=['Iris'] accepted. Decode 3.32 s (first call 13.7 s incl. compile).
- Streaming smoke: `fermion serve phonon-2 --port 8766` (detached, stopped
  after the probe). WS GET /v1/audio/stream protocol: one JSON text frame
  {"sample_rate":16000,"format":"pcm_s16le"}, binary PCM frames, then
  {"type":"end"}. Server emits {"type":"partial"}, {"type":"final","segment":N},
  {"type":"done","text":...}.
- Measured: first partial at **0.69 s**, 11 partials over 6.4 s (~2/s),
  finals at pause boundaries, exact final transcript. CPU only.
- Verdict: **PASS** — batch + live streaming both work on Windows CPU.

## T0.3 — V1 d1 decision-output probe: PASS
- Server: bundled `llama.cpp-prismml\bin\llama-server.exe` serving
  D:\lmstudio\models\AtomicChat\d1-3B-GGUF\d1-3B-AD-Q4_K_M.gguf
  (--ctx-size 4096 -ngl 99, port 8099, detached, stopped after the probe).
  Model loaded in ~6 s; GPU 883→~2.6 GB during probe; freed after stop.
- Method: exact port of LiquidAI/d1-3B prompt.py + runner.py single-question
  path (fetched from HF this session): render the Decision Index prompt
  (BOS <|startoftext|> = token 124894, verified via /tokenize; no system turn;
  state block + "QUESTION:" + question block + <|im_end|>\n<|im_start|>assistant\n),
  then ONE completion token with n_probs=512, readout = max-pool per option
  group + softmax across groups.
- Measured (temperature 0):
  - noul "Is the customer asking for a refund?" on a refund ticket:
    **P(yes)=0.9877**; on a cracked-screen ticket: **P(no)=0.9645**.
  - choice (billing/technical/fraud routing) on "app crashes when I open
    settings": **technical=0.9871** (correct).
  - score 0-2 urgency on "checkout down for all users": **level 2=0.9042**.
- Verdict: **PASS** — llama.cpp reproduces d1's calibrated decision readout.
  The owner's expectation is confirmed; decision_backend_d1.py is buildable
  on this recipe (1-token completion + logprob readout, no generation).

## T0.1 — V3 Parakeet consumer re-enumeration: PASS (list extended)
Fresh grep (backend, components, hooks, scripts). The spec's original
enumeration is confirmed PLUS these NEW findings:
- **hooks/useParakeetSTT.ts** — a full browser→:8765 WS streaming hook
  (ws://localhost:8765/ws/stream). Dormant (backend owns the mic) but a real
  :8765 consumer — delete or rewire at T5.3.
- **hooks/useIRISWebSocket.ts:1236-1242** — dispatches `iris:voice_final`
  (backend-broadcast final ASR transcript); components/chat-view.tsx:1612
  handles it. NO interim event exists today — Wave 1 must add one
  (e.g. iris:voice_interim) for streaming hypotheses to reach the UI.
- **Env vars**: IRIS_PARAKEET_PROVIDER, IRIS_PARAKEET_SHERPA_DIR
  (backend/audio/parakeet_sherpa.py:47,65), PARAKEET_PORT
  (parakeet_service.py:585).
- **scripts/iris_process_manager.py:271** — manages the
  parakeet_sherpa_worker process name.
- **scripts/mem_watch.py, scripts/measure_memory.py** — parakeet process
  labels (monitoring).
- **scripts/convert_parakeet_fp16.py** — legacy fp16 converter (delete).
- Comment-level references: backend/agent/tts.py:221,345;
  backend/utils/memory_trim.py; backend/core/memory_watchdog.py:35;
  hooks/useIRISWebSocket.ts:490,2392; scripts/gen_turn_replay_fixtures.py:50
  (fixture data, harmless).
Verdict: **PASS** — enumeration complete; T5.3 scope extended accordingly.

## TG-0 gate verdict: GREEN
All four verification gates PASS. Waves 1-5 may proceed in the spec's order.
No owner overrides needed. The V1-fail contingency (d1 vision-only) is CLOSED.

## Spec amendments triggered by Wave 0 findings (Amendment Protocol)
1. REQ-1 interim path: traced — no interim consumer exists; Wave 1 adds the
   backend event + frontend handler (ripple row updated at implementation).
2. T5.3 cleanup scope: + useParakeetSTT.ts, iris_process_manager.py entry,
   mem_watch/measure_memory labels, IRIS_PARAKEET_* env vars.
3. V4 outcome: Mercury stays hosted; T2.5 = rebind tool_execution to local
   LFM2.5-2.6B only (reasoning untouched).

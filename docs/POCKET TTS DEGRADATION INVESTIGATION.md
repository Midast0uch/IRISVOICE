# Pocket TTS Audio Degradation — Investigation Spec

## Resolution (added 2026-07-02)

**Root cause:** Not actually ASR colocation. The `TTSModel.load_model()` call
in `backend/agent/tts.py` was passing `variant="b6369a24"`, but Pocket-TTS
v2.1.0 (the installed version) renamed that parameter to `language=` and only
accepts `language=`. The call raised `TypeError`, which was caught silently by
`except Exception` in `_load_pocket_tts()`. The model was never actually loaded,
synthesis fell through, and the output was degraded regardless of whether ASR
was in the same process.

The "ASR colocation made it worse" correlation was a red herring — the bug
existed before ASR was moved; ASR simply made the failure mode more visible
under load.

**Fix:** `backend/agent/tts.py` `_load_pocket_tts()` now uses
`language=os.environ.get("POCKET_TTS_LANGUAGE", "english")`.

**Regression test:** `backend/tests/test_tts_pocket_load.py` guards against
re-introducing `variant=` and against upstream re-renames.

The rest of this document is preserved as the systematic-investigation
playbook that was followed; the Steps 2/3/4 hypothesis space turned out to
not be the actual cause, but the methodology still applies for future
audio regressions.

---

## Problem Statement (original)

Pocket TTS (zero-shot voice cloning) audio playback had degraded from clean
to "electric noise / distorted, barely intelligible" audio. The onset
*appeared* to correlate with Parakeet ASR being moved from a separate
client-server host (different port/process) into the same backend process
as Pocket TTS.

### Known facts (confirmed, do not re-litigate these)

1. Text content synthesized by TTS is correct — ASR transcription is accurate,
   correct English, correct grammar. This rules out ASR transcription quality
   as a cause.
2. The chat-view component's TTS playback (used to play back model text
   responses) has **never** been degraded, before or after the ASR migration.
   This playback path uses the same Pocket TTS model/audio stack.
3. Degradation onset correlates exactly with ASR being embedded into the same
   backend process as TTS — not with any change to TTS code itself, as far as
   is currently known.
4. ASR previously ran on a separate host/port, but **still used the same GPU**.
   This means "GPU sharing" alone is not a sufficient explanation — ASR was
   already sharing the GPU before the migration and TTS was not degraded then.
   The relevant change is **process boundary removal**, not GPU sharing itself.
5. GPU appears to have ample VRAM headroom for both models (unconfirmed —
   needs verification under real load, not idle).

### What changed, structurally

| Before | After |
|---|---|
| ASR: separate process, separate host/port | ASR: same process as TTS backend |
| ASR and TTS: separate Python interpreters, separate CUDA contexts, separate memory space | ASR and TTS: same interpreter, same process memory space, possibly same CUDA context |
| Communication: serialized over network (forces explicit format/contract) | Communication: in-process function/object calls (no forced contract) |
| Failure mode over network: usually loud (connection error, deserialization error) | Failure mode in-process: often silent (wrong dtype/shape just produces garbage numbers, no crash) |

The goal of this investigation is to identify **what specifically changed
inside the shared process** that causes TTS-only degradation while ASR output
and chat-view TTS remain correct. Do not assume the answer — work through all
categories below systematically and rule things in/out with evidence.

---

## Step 0 — Establish a clean baseline (do this first, before anything else)

This single test will eliminate roughly half the hypothesis space immediately.

- [ ] Restart the backend process fresh.
- [ ] Call Pocket TTS synthesis **immediately**, before any ASR call has been
      made in that process's lifetime, using the same code path the degraded
      pipeline uses (same function, same cloning settings, same reference
      audio if applicable).
- [ ] Listen to / analyze the raw output buffer (see Step 1 for how).

**Interpretation:**
- **Clean audio when TTS runs first, alone, in the shared process** → the
  degradation is triggered by ASR *executing* (runtime contention, shared
  state pollution, concurrency) — focus on Sections 3, 4, 5 below.
- **Degraded audio even when TTS runs first, alone, right after startup** →
  something in the backend's **import order or initialization** is
  misconfiguring TTS globally before ASR ever runs — focus on Sections 2 and 6
  below.
- **Degraded only after ASR has run at least once** → focus on Sections 3, 4,
  5 (state pollution / contention triggered by ASR execution specifically).
- **Degraded only when ASR runs concurrently with TTS (same moment)** → focus
  on Section 4 (concurrency / shared CUDA stream corruption).

Record which case this is. It should anchor the rest of the investigation —
don't skip sections, but prioritize based on this result.

---

## Step 1 — Capture raw, unprocessed evidence before touching anything else

Before testing hypotheses, get objective artifacts to compare against.

- [ ] Dump the **raw TTS output buffer** (immediately after model inference,
      before any playback stack, resampling, or format conversion touches it)
      directly to a `.wav` file with explicit, logged sample rate and dtype.
      Do this for:
  - [ ] Chat-view TTS call (known-good path)
  - [ ] Pipeline TTS call (degraded path)
- [ ] Compare the two `.wav` files:
  - [ ] Sample rate (from file header vs. what the model actually produced)
  - [ ] Bit depth / dtype (float32 vs int16, actual byte values)
  - [ ] Number of channels
  - [ ] Waveform shape visually (plot both — clipping, NaNs, zero-runs,
        periodic noise patterns, or garbage-value spikes all look different
        and each points to a different root cause)
  - [ ] Check for NaN/Inf values in the raw float buffer before any
        conversion — a model producing NaNs and then converting them to
        int16 will produce exactly this kind of harsh digital noise
- [ ] Log and diff every parameter passed into the TTS synthesis call in both
      paths (sample rate, dtype, chunk size, cloning on/off, reference audio
      path, model instance ID/memory address, device string e.g. `cuda:0`).

This step alone may reveal whether the corruption exists at the raw model
output (points to model/GPU/memory issues) or is introduced afterward (points
to playback/formatting issues) — do not skip it even if a later section seems
more likely.

---

## Step 2 — Process initialization & import order

Even without concurrent execution, importing ASR libraries into the same
process as TTS can silently reconfigure shared global state.

- [ ] Check the import order of ASR-related and TTS-related packages at
      backend startup. Some audio/ML libraries set process-wide global
      defaults (default sample rate, default audio backend, default device,
      default dtype) **at import time**, and last-imported-wins in some
      cases.
- [ ] Check for global/singleton audio session objects (e.g. `sounddevice`
      default device/samplerate, `torchaudio` backend selection
      `sox_io` vs `soundfile`, any custom `AudioConfig` singleton) that either
      ASR or TTS code sets and the other unknowingly inherits.
- [ ] Check whether any library sets a global `torch.set_default_dtype()`,
      global autocast context, or global device context that persists across
      both model calls.
- [ ] Check environment variables that affect audio/CUDA behavior
      (`CUDA_VISIBLE_DEVICES`, `TORCH_CUDNN_V8_API_ENABLED`, any
      sample-rate-related env vars) — confirm nothing ASR-related is now
      being read by TTS code due to shared process environment.
- [ ] Check for monkeypatching — does either library patch shared modules
      (`numpy`, `torch`, `torchaudio`) in a way that could alter the other's
      behavior?

---

## Step 3 — Shared resource / state pollution (non-concurrent)

Even if ASR and TTS never run at the exact same instant, one running before
the other in the same process can leave behind polluted state.

- [ ] Is the Pocket TTS model instance a true singleton, loaded once? If so,
      confirm nothing about its internal state (KV cache, conditioning
      buffers, cloning embeddings, streaming state) persists between calls
      and could be corrupted by unrelated code running in between.
- [ ] Does ASR inference reuse the **same pre-allocated GPU memory buffers**
      pool as TTS (e.g. via a shared memory allocator, `torch.cuda` caching
      allocator fragmentation) such that a later TTS call reads back
      partially-overwritten memory?
- [ ] Check for any shared thread-local or process-global buffer/array that
      both models write into (e.g. a shared `numpy` scratch array, a shared
      audio ring buffer) — this is a common cause of "sounds like the wrong
      audio bytes" style distortion.
- [ ] Check GPU memory fragmentation: run `nvidia-smi` and
      `torch.cuda.memory_summary()` after ASR has run once, then before TTS
      runs. Fragmented (not just insufficient) memory can cause allocation
      failures that some frameworks handle by silently falling back to a
      degraded kernel or reduced precision rather than raising an error.
- [ ] Check whether model loading order matters — does loading TTS before vs.
      after ASR change anything? (Try both orders explicitly as a test.)

---

## Step 4 — Concurrency and CUDA stream safety

This is the highest-priority section if Step 0 showed degradation is
triggered by ASR *executing*, especially if TTS and ASR can run in
overlapping time windows (e.g. transcribing continued speech while also
synthesizing a response).

- [ ] Confirm whether ASR inference and TTS inference can literally execute
      at the same time in the current architecture (check for async
      calls, background threads, or overlapping request handling).
- [ ] If using PyTorch: check whether both models run on the **default CUDA
      stream** with no explicit stream separation. Concurrent kernel launches
      on a shared stream without proper synchronization can interleave and
      corrupt intermediate tensors non-deterministically.
- [ ] Check whether the inference runtime (PyTorch, ONNX Runtime, TensorRT,
      custom CUDA kernels) being used for either model is documented as
      thread-safe for **concurrent inference calls on the same
      session/context**. Many are not, by default, and reused session objects
      under concurrent load are a classic cause of silently corrupted output
      (not crashes).
- [ ] Check for race conditions on shared GPU memory: does ASR's memory
      allocation/deallocation cycle overlap in time with TTS's forward pass in
      a way that could interfere with in-flight tensors?
- [ ] If the backend uses multiprocessing or multithreading for request
      handling, confirm the TTS model instance is not being called
      re-entrantly from multiple threads without a lock, especially if it
      maintains any internal state (streaming/cloning conditioning).
- [ ] Test: deliberately trigger ASR and TTS to run at the exact same moment
      several times in a row and see if degradation severity correlates with
      overlap, versus running them strictly sequentially with a delay.

---

## Step 5 — GPU memory pressure and silent precision/kernel fallback

Even with "plenty of headroom" at idle, verify under actual concurrent load,
not just static `nvidia-smi` snapshots.

- [ ] Monitor `nvidia-smi` **during** actual pipeline execution (both models
      loaded, request in flight), not just after both are loaded at rest.
      Look for spikes, not steady-state.
- [ ] Check for any automatic mixed-precision (AMP) or autocast context that
      might be enabled/disabled differently depending on what else is loaded
      in the process.
- [ ] Check inference framework logs/warnings (often suppressed by default)
      for any silent fallback messages — e.g. ONNX Runtime falling back from
      a GPU execution provider to CPU for a specific op, or a kernel failing
      and being caught internally.
- [ ] Check whether TTS was previously configured (in its standalone
      server config) with an explicit VRAM reservation / memory fraction
      limit that no longer applies now that it's colocated, or vice versa —
      i.e., confirm no memory-limiting config is now under-provisioning TTS
      because it's competing with a memory fraction reserved for ASR.
- [ ] Rule out thermal/power throttling as a red herring by checking GPU
      clocks and temps during the degraded run (unlikely to cause this
      specific artifact, but cheap to check and rule out).

---

## Step 6 — Audio-specific format/library conflicts

Even though this was addressed generally in earlier discussion, verify these
concretely rather than assuming they're fine, especially interaction effects
that only occur with ASR co-resident.

- [ ] Confirm the exact sample rate and dtype **Pocket TTS actually outputs**
      (verify from model docs/source, don't assume) vs. what the playback
      stack is configured to expect, **specifically in the pipeline code
      path** (not the chat-view path, which is known-good).
- [ ] Confirm ASR's expected input format (commonly 16kHz mono int16 or
      float32) is not being applied anywhere in the TTS output path by
      mistake (e.g. a shared "audio preprocessing" utility function
      accidentally being reused for both input and output with
      ASR-appropriate defaults).
- [ ] Check for a shared audio I/O wrapper/utility class used by both ASR
      input handling and TTS output handling — if one function does double
      duty for "load audio for ASR" and "prepare audio for playback," confirm
      its default parameters aren't ASR-biased (16kHz) now that ASR is the
      dominant/more-recently-modified caller.
- [ ] Check whether audio device/stream objects are being shared or
      recreated correctly — e.g. is there one shared output stream object
      whose parameters got reconfigured when ASR's input stream was set up
      in the same process?

---

## Step 7 — Version / dependency conflicts introduced by colocation

- [ ] Check whether embedding ASR into the backend required any dependency
      version changes (e.g. `torch`, `torchaudio`, `numpy`, `onnxruntime`,
      CUDA/cuDNN version) that could have changed TTS's resolved dependency
      versions too, even indirectly via shared `requirements.txt` /
      `pyproject.toml` resolution.
- [ ] Diff the installed package versions in the current shared environment
      against the versions previously used when TTS ran standalone/alongside
      chat-view only.
- [ ] Check if ASR's dependencies pull in a different build of a shared
      library (e.g. a different `libsndfile`, different CUDA toolkit minor
      version) that TTS is now inadvertently linking against.

---

## Step 8 — Rule-out / control tests

Run these regardless of which section looks most promising — they cheaply
narrow the field further.

- [ ] Run TTS on CPU only (temporarily) with ASR still on GPU — if TTS is
      clean on CPU, this strongly implicates GPU-level contention (Sections
      4–5) over pure software state issues (Sections 2–3, 6–7).
- [ ] Run TTS in the shared process with ASR imported but never invoked
      (loaded but idle) — isolates "import/load side effects" (Section 2)
      from "execution side effects" (Sections 3–4).
- [ ] Revert to the old two-process architecture temporarily (ASR back on
      separate port) with everything else identical, and confirm TTS quality
      returns to clean — this confirms process boundary removal is
      definitively the trigger and not a coincidental unrelated change made
      around the same time (e.g. a dependency bump that happened to ship in
      the same deploy).
- [ ] Check version control history for the exact commit(s) that migrated
      ASR into the backend — confirm no incidental changes to TTS code,
      config, or dependencies were bundled into the same change, however
      small.

---

## Reporting format for findings

For each section, record:
1. What was checked
2. What was found (concrete values/logs, not impressions)
3. Whether it was ruled in or ruled out as a contributing factor
4. If ruled in: minimal reproduction steps

Do not stop at the first plausible-looking cause — confirm with a
before/after test (fix the suspected issue, reproduce clean audio, then
reintroduce it to confirm the degradation returns) before considering it
solved.

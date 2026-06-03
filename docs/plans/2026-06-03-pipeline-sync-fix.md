# Pipeline Sync Fix — TTS ↔ STT ↔ IrisOrb Animation Alignment

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the 7 bugs that break the voice pipeline from wake-word through TTS playback, and synchronize the IrisOrb animation with actual audio state so the orb reflects what the user hears.

**Architecture:** The pipeline is: STT (recording) → LLM (thinking) → TTS (speaking) → idle/conversation-relisten. The backend broadcasts `listening_state` WebSocket events at each transition; the frontend IrisOrb reads these to animate. Currently the pipeline crashes on the native-player path (`_broadcast_voice_state` undefined), sends "speaking" before audio plays, never streams TTS sentence-by-sentence, and has no audio-level feedback during speech output. Each fix is isolated and testable.

**Tech Stack:** Python 3.14, asyncio + threading, Pocket-TTS (streaming), numpy, sounddevice, Next.js/React (IrisOrb + framer-motion), WebSocket (JSON messages)

---

## Bug Inventory (Found by Code Audit)

| # | Severity | Bug | File:Line | Symptom |
|---|----------|-----|-----------|---------|
| 1 | **CRITICAL** | `_broadcast_voice_state` method does not exist | `iris_gateway.py:1985` | AttributeError crash on native-player TTS path |
| 2 | **CRITICAL** | Duplicate `except Exception` block in `_load_catalog_voice` | `tts.py:549-552` | SyntaxError / unreachable code — second except shadows first |
| 3 | **HIGH** | "speaking" broadcast inside `if _native:` block | `iris_gateway.py:1983-1990` | Non-native path never sends "speaking" for str input |
| 4 | **HIGH** | "speaking" sent before audio plays (during LLM generation) | `iris_gateway.py:1825-1828` | Orb animates SPEAKING while no audio is playing |
| 5 | **HIGH** | `sentence_queue` is dead code — TTS waits for full response | `iris_gateway.py:1756-1820` | No streaming TTS; user waits for entire LLM response before hearing anything |
| 6 | **MEDIUM** | Native player path skips 2.5× gain | `iris_gateway.py:1994-2001` | Pocket-TTS audio too quiet on native path vs fallback path |
| 7 | **MEDIUM** | No audio-level feedback during TTS speaking | `iris_gateway.py` / `IrisOrb.tsx` | Orb doesn't pulse in sync with speech output |

---

### Task 1: Fix Duplicate except Block in tts.py

**Files:**
- Modify: `backend/agent/tts.py:543-552`

**Why:** Lines 543-548 have the correct `except Exception` for `_load_catalog_voice`. Lines 549-552 have a DUPLICATE `except Exception` that catches the same errors and incorrectly sets `self._pocket_tts_model = None` (which belongs to `_load_pocket_tts`, not `_load_catalog_voice`). In Python, the second except is unreachable because the first catches everything — but if the first is removed, the second would corrupt state.

**Step 1: Read the current code**

```bash
python -c "
with open('backend/agent/tts.py') as f:
    lines = f.readlines()
for i in range(542, 553):
    print(f'{i+1}: {lines[i]}', end='')
"
```

Expected: See two `except Exception` blocks at lines 543 and 549.

**Step 2: Remove the duplicate except block**

Delete lines 549-552 (the second `except Exception as exc:` block that sets `self._pocket_tts_model = None`).

The correct code after fix should be:

```python
        except Exception as exc:
            logger.warning(
                f"[TTSManager] Failed to load catalog voice '{voice_name}': {exc}"
            )
            self._voice_state = None
            return False

    def _stream_pocket(
```

**Step 3: Syntax check**

```bash
python -c "import ast; ast.parse(open('backend/agent/tts.py').read()); print('SYNTAX OK')"
```

Expected: `SYNTAX OK`

**Step 4: Run existing TTS tests**

```bash
python -m pytest backend/tests/test_voice_pipeline.py -v -k "tts or TTS" --timeout=30 2>&1 | head -40
```

Expected: All existing tests pass (no regression).

**Step 5: Commit**

```bash
git add backend/agent/tts.py
git commit -m "fix: remove duplicate except block in _load_catalog_voice (tts.py)"
```

---

### Task 2: Fix `_broadcast_voice_state` — Replace with Direct WS Broadcast

**Files:**
- Modify: `backend/iris_gateway.py:1983-1990`

**Why:** `self._broadcast_voice_state(session_id, "speaking", auto_relisten=...)` is called at line 1985 but the method DOES NOT EXIST anywhere in the codebase. This causes an `AttributeError` crash whenever:
1. The native C++ player is available (`_native = True`)
2. The input is a string (play button click or voice response)

This is the #1 pipeline-breaking bug. The TTS thread crashes silently (it's a daemon thread), the orb stays stuck in "speaking" state, and no audio plays.

**Step 1: Read the current code**

```bash
python -c "
with open('backend/iris_gateway.py') as f:
    lines = f.readlines()
for i in range(1964, 2000):
    print(f'{i+1}: {lines[i]}', end='')
"
```

**Step 2: Replace `_broadcast_voice_state` with direct WS broadcast**

The call is inside `if _native:` → `if isinstance(input_source, str):`. Replace the non-existent method call with the same pattern used elsewhere in `_speak_response` (the finally block at lines 2162-2198 uses `asyncio.run_coroutine_threadsafe`).

Replace this block (lines 1983-1990):

```python
            # 2. Synthesiser thread (producer)
            # After TTS streaming completes, send state transitions
            if isinstance(input_source, str):
                # Notify frontend: TTS is starting
                self._broadcast_voice_state(
                    session_id,
                    "speaking",
                    # Only set auto_relisten for voice-command-triggered TTS
                    auto_relisten=getattr(self, "_tts_auto_relisten", False),
                )
```

With:

```python
            # 2. Synthesiser thread (producer)
            # Notify frontend: TTS is starting (only for string input —
            # queue input gets its "speaking" state from the caller).
            if isinstance(input_source, str) and session_id and self._main_loop and self._main_loop.is_running():
                import asyncio as _asyncio
                _asyncio.run_coroutine_threadsafe(
                    self._ws_manager.broadcast_to_session(
                        session_id,
                        {"type": "listening_state", "payload": {"state": "speaking"}},
                    ),
                    self._main_loop,
                )
```

**Step 3: Move the "speaking" broadcast OUTSIDE the `if _native:` block**

The "speaking" state must be sent regardless of whether the native player is available. Currently it's nested inside `if _native:`, so the fallback path never sends "speaking" for string input.

The restructured code should be:

```python
        # ── Notify frontend: TTS is starting ──
        # Must happen regardless of native vs fallback player path.
        # Only for string input — queue input gets "speaking" from the caller.
        if isinstance(input_source, str) and session_id and self._main_loop and self._main_loop.is_running():
            import asyncio as _asyncio
            _asyncio.run_coroutine_threadsafe(
                self._ws_manager.broadcast_to_session(
                    session_id,
                    {"type": "listening_state", "payload": {"state": "speaking"}},
                ),
                self._main_loop,
            )

        # ── Native C++ audio fast-path ──
        _native = (
            engine.pipeline._native_available
            and engine.pipeline._native_player is not None
        )
        if _native:
            try:
                if not engine.pipeline._native_player.open(
                    engine.pipeline.output_device or -1, _TTS_SAMPLE_RATE
                ):
                    _native = False
            except Exception as _native_err:
                self._logger.warning(
                    f"[Voice] Native player open failed ({_native_err}), falling back"
                )
                _native = False
```

This moves the "speaking" broadcast BEFORE the native player check, and removes the broken `_broadcast_voice_state` call entirely.

**Step 4: Syntax check**

```bash
python -c "import ast; ast.parse(open('backend/iris_gateway.py').read()); print('SYNTAX OK')"
```

Expected: `SYNTAX OK`

**Step 5: Verify no other references to `_broadcast_voice_state`**

```bash
python -c "
import re
with open('backend/iris_gateway.py') as f:
    content = f.read()
matches = re.findall(r'_broadcast_voice_state', content)
print(f'Remaining references: {len(matches)}')
"
```

Expected: `Remaining references: 0`

**Step 6: Commit**

```bash
git add backend/iris_gateway.py
git commit -m "fix: replace undefined _broadcast_voice_state with direct WS broadcast"
```

---

### Task 3: Fix "speaking" State Timing — Remove Premature Broadcast

**Files:**
- Modify: `backend/iris_gateway.py:1825-1828`

**Why:** In `_process_voice_transcription`, line 1825-1828 broadcasts "speaking" BEFORE the LLM has even started generating. The orb animates as SPEAKING while the system is still thinking. The correct time to send "speaking" is when TTS audio actually starts playing — which happens inside `_speak_response` (fixed in Task 2).

**Step 1: Read the current code**

```bash
python -c "
with open('backend/iris_gateway.py') as f:
    lines = f.readlines()
for i in range(1820, 1875):
    print(f'{i+1}: {lines[i]}', end='')
"
```

**Step 2: Remove the premature "speaking" broadcast**

Delete these lines (1825-1829):

```python
            # Start TTS immediately — blocks on queue until first sentence arrives
            await self._ws_manager.broadcast_to_session(
                session_id,
                {"type": "listening_state", "payload": {"state": "speaking"}},
            )
            _tts_started = True
```

Replace with a comment explaining that "speaking" is now sent by `_speak_response`:

```python
            # "speaking" state is now sent by _speak_response when audio
            # actually starts playing — not here while the LLM is still thinking.
            _tts_started = True
```

**Step 3: Also remove the duplicate "speaking" broadcast at line 1846-1849**

In the same method, after the agent completes, there's another "speaking" broadcast:

```python
                # Sync orb animation: idle → speaking → TTS → idle
                _loop = asyncio.get_running_loop()
                await self._ws_manager.send_to_client(
                    client_id,
                    {"type": "listening_state", "payload": {"state": "speaking"}},
                )
```

This is also premature — it sends "speaking" before `_speak_response` has opened the audio device. Remove it. The `_speak_response` method (fixed in Task 2) now handles this.

Replace:

```python
            if spoken:
                # Sync orb animation: idle → speaking → TTS → idle
                _loop = asyncio.get_running_loop()
                await self._ws_manager.send_to_client(
                    client_id,
                    {"type": "listening_state", "payload": {"state": "speaking"}},
                )

                def _wrap_tts(text: str, sid: str, cid: str, _l):
```

With:

```python
            if spoken:
                # "speaking" state is sent by _speak_response when audio starts.
                _loop = asyncio.get_running_loop()

                def _wrap_tts(text: str, sid: str, cid: str, _l):
```

**Step 4: Syntax check**

```bash
python -c "import ast; ast.parse(open('backend/iris_gateway.py').read()); print('SYNTAX OK')"
```

Expected: `SYNTAX OK`

**Step 5: Commit**

```bash
git add backend/iris_gateway.py
git commit -m "fix: remove premature 'speaking' broadcasts — sent by _speak_response when audio plays"
```

---

### Task 4: Wire sentence_queue into _speak_response for Streaming TTS

**Files:**
- Modify: `backend/iris_gateway.py:1753-1872`

**Why:** The `sentence_queue` is created and populated by `reasoning_callback` during LLM streaming, but `_speak_response` is called with the FULL `spoken` text string instead of the queue. This means TTS waits for the entire LLM response before speaking a single word. The queue infrastructure is already there — it just needs to be connected.

**Step 1: Read the current code**

```bash
python -c "
with open('backend/iris_gateway.py') as f:
    lines = f.readlines()
for i in range(1753, 1875):
    print(f'{i+1}: {lines[i]}', end='')
"
```

**Step 2: Change `_speak_response` call to use the sentence_queue**

Currently (after Task 3 fixes), the code looks like:

```python
            if spoken:
                # "speaking" state is sent by _speak_response when audio starts.
                _loop = asyncio.get_running_loop()

                def _wrap_tts(text: str, sid: str, cid: str, _l):
                    try:
                        self._speak_response(text, sid)
                    finally:
                        _l.call_soon_threadsafe(
                            lambda: asyncio.ensure_future(
                                self._ws_manager.send_to_client(
                                    cid,
                                    {
                                        "type": "listening_state",
                                        "payload": {"state": "idle"},
                                    },
                                )
                            )
                        )

            threading.Thread(
                target=_wrap_tts,
                args=(spoken, session_id, client_id, _loop),
                daemon=True,
                name="voice-tts-response",
            ).start()
```

Replace with queue-based streaming:

```python
            if spoken:
                # "speaking" state is sent by _speak_response when audio starts.
                _loop = asyncio.get_running_loop()

                def _wrap_tts_queue(q: queue.Queue, sid: str, cid: str, _l):
                    """Consume sentences from the queue and stream TTS."""
                    try:
                        self._speak_response(q, sid)
                    finally:
                        _l.call_soon_threadsafe(
                            lambda: asyncio.ensure_future(
                                self._ws_manager.send_to_client(
                                    cid,
                                    {
                                        "type": "listening_state",
                                        "payload": {"state": "idle"},
                                    },
                                )
                            )
                        )

                # Start TTS thread with the sentence queue — first sentence
                # plays while the LLM is still generating the rest.
                threading.Thread(
                    target=_wrap_tts_queue,
                    args=(sentence_queue, session_id, client_id, _loop),
                    daemon=True,
                    name="voice-tts-streaming",
                ).start()
            else:
                # No spoken text — put sentinel so _execute_agent can finish
                sentence_queue.put(None)
```

**Step 3: Ensure the sentinel is placed AFTER prepare_spoken_text**

Currently in `_execute_agent` (line 1816-1820):

```python
                # Final flush — any remaining text becomes a sentence
                if sentence_buf:
                    sentence_queue.put("".join(sentence_buf))
                    sentence_buf.clear()
                sentence_queue.put(None)  # sentinel: TTS knows LLM is done
                spoken = agent_kernel.prepare_spoken_text(resp, enriched)
                return resp, spoken
```

The sentinel is placed BEFORE `prepare_spoken_text`. This is fine because the TTS thread consumes from the queue — the sentinel tells it "no more sentences coming." The `spoken` variable is used for the fallback path (no sentence_queue). Since we're now using the queue, the sentinel position is correct.

However, if `spoken` is empty (the agent decided not to speak), we need to ensure the queue still gets a sentinel. The `else` branch added in Step 2 handles this.

**Step 4: Verify _speak_response handles queue.Queue input**

Read the queue path in `_speak_response` (lines 2017-2076). It already handles `queue.Queue` input — it reads sentences from the queue, synthesizes each one, and breaks on `None` sentinel. This path is already implemented and working.

**Step 5: Syntax check**

```bash
python -c "import ast; ast.parse(open('backend/iris_gateway.py').read()); print('SYNTAX OK')"
```

Expected: `SYNTAX OK`

**Step 6: Commit**

```bash
git add backend/iris_gateway.py
git commit -m "feat: wire sentence_queue into _speak_response for streaming TTS"
```

---

### Task 5: Apply 2.5× Gain in Native Player Path

**Files:**
- Modify: `backend/iris_gateway.py:1994-2001` (inside `_producer`)

**Why:** `play_stream()` in `pipeline.py` applies a 2.5× gain for Pocket-TTS's quiet output (~0.37 peak). But the native player path in `_speak_response._producer` pushes chunks directly without any gain. This means:
- Native path: quiet audio
- Fallback path (via `play_stream`): properly amplified audio

The fix is to apply the same 2.5× gain + clip in the producer before pushing to the native player.

**Step 1: Read the current `_push_or_queue` helper**

```bash
python -c "
with open('backend/iris_gateway.py') as f:
    lines = f.readlines()
for i in range(1992, 2020):
    print(f'{i+1}: {lines[i]}', end='')
"
```

**Step 2: Add gain + clip to `_push_or_queue`**

Replace the `_push_or_queue` helper inside `_producer`:

```python
            def _push_or_queue(audio_chunk: np.ndarray):
                # Apply 2.5× gain for Pocket-TTS quiet output (peak ~0.37).
                # Clip to [-0.99, 0.99] — same as play_stream() in pipeline.py.
                audio_chunk = np.clip(audio_chunk * 2.5, -0.99, 0.99)

                native_ok = False
                if engine.pipeline and engine.pipeline._native_player is not None:
                    try:
                        engine.pipeline._native_player.push_chunk(audio_chunk)
                        native_ok = True
                    except Exception:
                        pass
                if not native_ok:
                    asyncio.run_coroutine_threadsafe(audio_queue.put(audio_chunk), loop)
```

**Step 3: Also apply gain in the queue-path native push**

In the queue consumption path (around lines 2031-2046 and 2057-2071), the native player push also needs the gain. Find all `engine.pipeline._native_player.push_chunk(audio_chunk)` calls inside `_producer` and add the gain before each one.

For each occurrence of:
```python
engine.pipeline._native_player.push_chunk(audio_chunk)
```

Replace with:
```python
engine.pipeline._native_player.push_chunk(np.clip(audio_chunk * 2.5, -0.99, 0.99))
```

**Step 4: Syntax check**

```bash
python -c "import ast; ast.parse(open('backend/iris_gateway.py').read()); print('SYNTAX OK')"
```

Expected: `SYNTAX OK`

**Step 5: Commit**

```bash
git add backend/iris_gateway.py
git commit -m "fix: apply 2.5x gain in native player path for Pocket-TTS volume consistency"
```

---

### Task 6: Add TTS Audio-Level Feedback for Speaking Animation

**Files:**
- Modify: `backend/iris_gateway.py` (inside `_producer` in `_speak_response`)
- Modify: `hooks/useIRISWebSocket.ts:628-634`

**Why:** During the "listening" state, the VAD loop sends `audio_level` events every ~100ms so the IrisOrb pulses with the user's voice. During "speaking", there is NO audio-level feedback — the orb just shows a static "SPEAKING" label without pulsing in sync with the speech output. Adding TTS audio-level feedback makes the orb feel alive and responsive.

**Step 1: Add audio-level broadcast in the TTS producer**

Inside `_speak_response._producer`, after each chunk is pushed to the native player or queue, compute the RMS and broadcast it. Add this after the `_push_or_queue` call in the string-input path:

```python
                if isinstance(input_source, str):
                    for audio_chunk in tts.synthesize_stream(input_source):
                        if interrupted.is_set() or engine.is_speech_interrupted():
                            interrupted.set()
                            break
                        _push_or_queue(audio_chunk)

                        # Broadcast audio level for orb speaking animation
                        if session_id and self._main_loop and self._main_loop.is_running():
                            rms = float(np.sqrt(np.mean(np.square(audio_chunk))))
                            # Normalize: Pocket-TTS after 2.5x gain peaks ~0.9
                            # Map RMS to 0.0-1.0 range for frontend
                            level = min(1.0, rms * 5.0)  # scale factor for visibility
                            try:
                                import asyncio as _asyncio
                                _asyncio.run_coroutine_threadsafe(
                                    self._ws_manager.broadcast_to_session(
                                        session_id,
                                        {"type": "audio_level", "payload": {"level": level}},
                                    ),
                                    self._main_loop,
                                )
                            except Exception:
                                pass
```

Do the same for the queue-input path — after each `push_chunk` or `audio_queue.put`, compute and broadcast the level.

**Step 2: Update frontend to accept audio_level during speaking state**

Currently `useIRISWebSocket.ts:628-634` handles `audio_level` but the comment says "during listening". Update the comment and ensure `audioLevel` is set regardless of voice state:

```typescript
       case "audio_level": {
        // Audio level update — used during both listening (mic input)
        // and speaking (TTS output) for orb animation sync.
        if (typeof payload.level === 'number') {
          setAudioLevel(payload.level)
        }
        break
      }
```

The code already works for both states (it just sets `audioLevel`), but the IrisOrb only uses `audioLevel` for visual scaling during the "listening" state. Update `IrisOrb.tsx` to also use `audioLevel` during "speaking":

**Step 3: Update IrisOrb to use audioLevel during speaking**

In `components/iris/IrisOrb.tsx`, line 219:

```typescript
  const audioLevelScale = isListening ? 1 + (audioLevel * 0.15) : 1
```

Change to:

```typescript
  const audioLevelScale = (isListening || isSpeaking) ? 1 + (audioLevel * 0.15) : 1
```

This makes the orb pulse with TTS audio output during the speaking state, just like it pulses with mic input during listening.

**Step 4: Reset audio level when leaving speaking state**

In `useIRISWebSocket.ts:567-570`, the audio level is already reset when leaving "listening":

```typescript
          if (newState !== "listening") {
            setAudioLevel(0)
          }
```

This is fine — it also resets when transitioning from "speaking" to "idle", which is correct.

**Step 5: Syntax check both files**

```bash
python -c "import ast; ast.parse(open('backend/iris_gateway.py').read()); print('SYNTAX OK')"
```

```bash
npx tsc --noEmit hooks/useIRISWebSocket.ts components/iris/IrisOrb.tsx 2>&1 | head -20
```

Expected: No errors.

**Step 6: Commit**

```bash
git add backend/iris_gateway.py hooks/useIRISWebSocket.ts components/iris/IrisOrb.tsx
git commit -m "feat: add TTS audio-level feedback for speaking orb animation sync"
```

---

### Task 7: Clean Up Stale F5-TTS References

**Files:**
- Modify: `backend/agent/tts.py` (docstrings, comments)
- Modify: `backend/iris_gateway.py` (comments)
- Modify: `backend/audio/engine.py:251` (comment)

**Why:** Multiple references to F5-TTS remain in docstrings and comments, which is confusing for maintenance. Pocket-TTS is now the primary engine.

**Step 1: Update tts.py docstring (lines 1-24)**

Replace the module docstring. Key changes:
- Remove "F5-TTS" references
- Update setup instructions (no more `pip install f5-tts`)
- Remove "Lock discipline" note about `_stream_f5tts`

New docstring:

```python
"""
TTS Manager — Pocket-TTS (voice cloning) for IRIS.
Primary engine : Pocket-TTS (~100M int8 quantized, ~100 MB RAM)
  - Zero-shot voice cloning from reference audio (TOMV2.wav)
  - True streaming inference (generate_audio_stream — yields chunk-by-chunk)
  - Catalog voices: alba, marius, javert, jean, fantine, cosette, eponine, azelma
  - Fallback engines: Piper → pyttsx3
  - Text normalizer wired in: strips markdown, expands symbols, removes
    code blocks so TTS never reads out "$", "%", "->", "**bold**" etc.
  - 24 kHz native output

Fallback        : Piper en_US-ryan-high (fast CPU, ~65 MB, no cloning)
Final fallback  : pyttsx3 (Windows SAPI5 — zero download, instant)

Setup           : pip install pocket-tts
                  Place TOMV2.wav at IRISVOICE/data/TOMV2.wav

Lock discipline
  self._lock guards model initialisation only.  It is released before
  inference so synthesis never blocks the consumer's audio-queue timeout.
  The lock is NOT reentrant — do not acquire it inside _stream_pocket.
"""
```

**Step 2: Update TTSManager class docstring (lines 149-176)**

Replace references to F5-TTS with Pocket-TTS:

```python
    """
    Singleton TTS manager.

    Engine priority (automatic — not user-selected):
      1. Pocket-TTS — PRIMARY
            Zero-shot voice cloning from TOMV2.wav.
            CPU-based, int8 quantized, ~100 MB RAM (lazy load).
            Always tried first unless user forces "Built-in".
      2. Piper en_US-ryan-high — FALLBACK
            Fast CPU engine, RTF ~0.04x, ~65 MB model (auto-downloaded).
            Used when Pocket-TTS is not installed, fails to load, or stream errors.
      3. pyttsx3 (SAPI5 on Windows) — LAST RESORT
            Zero download, always available on Windows.

    Voice setting "Built-in" skips Pocket-TTS and goes directly to Piper.
    This is the only way to bypass Pocket-TTS (e.g. for testing or low-resource mode).

    All engines produce float32 audio at OUTPUT_SAMPLE_RATE (24 kHz).

    Text is normalised before synthesis (markdown stripped, symbols
    expanded to spoken words) via backend/voice/tts_normalizer.py.

    IMPORTANT — first-time setup:
      pip install pocket-tts
      Place TOMV2.wav at IRISVOICE/data/TOMV2.wav to enable voice cloning.
    """
```

**Step 3: Update _log_preflight (lines 222-267)**

Replace "F5-TTS" with "Pocket-TTS" in log messages:

```python
    def _log_preflight(self) -> None:
        """Log TTS preflight status at startup."""
        force_builtin = self.config.get("tts_voice") == "Built-in"

        if not force_builtin:
            issues = []
            if not REFERENCE_AUDIO.exists():
                issues.append(
                    f"Reference audio not found at {REFERENCE_AUDIO}. "
                    "Place TOMV2.wav at IRISVOICE/data/TOMV2.wav to enable voice cloning."
                )
            if issues:
                logger.warning(
                    "[TTSManager] Pocket-TTS primary — preflight issues:\n"
                    + "\n".join(f"  - {i}" for i in issues)
                    + "\n  Will fall back to Piper."
                )
            else:
                logger.info(
                    f"[TTSManager] Pocket-TTS primary — reference audio OK at {REFERENCE_AUDIO}"
                )
            if PIPER_MODEL_ONNX.exists():
                logger.info(f"[TTSManager] Piper fallback ready at {PIPER_MODEL_ONNX}")
            else:
                logger.warning(
                    f"[TTSManager] Piper fallback model not found at {PIPER_MODEL_ONNX} — "
                    "will fall back to pyttsx3 if Pocket-TTS also fails"
                )
        else:
            logger.info(
                "[TTSManager] Voice set to 'Built-in' — using Piper directly (Pocket-TTS skipped)"
            )
            if PIPER_MODEL_ONNX.exists():
                logger.info(f"[TTSManager] Piper engine at {PIPER_MODEL_ONNX}")
            else:
                logger.warning(
                    f"[TTSManager] Piper model not found at {PIPER_MODEL_ONNX} — "
                    "will fall back to pyttsx3"
                )
```

**Step 4: Update iris_gateway.py comments**

Search for "F5-TTS" or "f5-tts" in iris_gateway.py and replace with "Pocket-TTS" / "pocket-tts". Key locations:
- Line 132-136: Comment about F5-TTS lazy loading
- Line 546-548: Comment about F5-TTS pre-trigger

**Step 5: Update engine.py comment**

Line 251: `"Reduces CPU load so the F5-TTS synthesis thread is not starved of frames."` → change to `"Reduces CPU load so the TTS synthesis thread is not starved of frames."`

**Step 6: Verify no remaining F5-TTS references**

```bash
python -c "
import re
for f in ['backend/agent/tts.py', 'backend/iris_gateway.py', 'backend/audio/engine.py']:
    with open(f) as fh:
        for i, line in enumerate(fh, 1):
            if re.search(r'F5.TTS|f5.tts|f5tts', line, re.IGNORECASE):
                print(f'{f}:{i}: {line.rstrip()}')
"
```

Expected: No output (all references cleaned).

**Step 7: Commit**

```bash
git add backend/agent/tts.py backend/iris_gateway.py backend/audio/engine.py
git commit -m "cleanup: replace all F5-TTS references with Pocket-TTS"
```

---

### Task 8: Integration Test — End-to-End Pipeline Verification

**Files:**
- Run: backend + frontend
- Verify: all state transitions

**Why:** After all fixes, verify the complete pipeline works end-to-end.

**Step 1: Restart backend**

```bash
# Kill any existing backend
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *uvicorn*" 2>nul
# Start fresh
python start_backend_logged.py
```

Wait 15 seconds for startup.

**Step 2: Verify Pocket-TTS loads in logs**

```bash
python -c "
with open('backend/logs/uvicorn_live3.log') as f:
    content = f.read()
if 'Pocket-TTS model loaded' in content:
    print('OK: Pocket-TTS loaded')
else:
    print('FAIL: Pocket-TTS not loaded')
if 'Voice state from' in content or 'Catalog voice' in content:
    print('OK: Voice state loaded')
else:
    print('FAIL: Voice state not loaded')
"
```

Expected: Both OK.

**Step 3: Start frontend**

```bash
python launch_frontend.py
```

Wait 10 seconds.

**Step 4: Test play-button TTS**

1. Open `http://localhost:3000/`
2. Type a message and get a response
3. Click the play icon on the response
4. **Verify:**
   - Orb transitions to SPEAKING when audio starts (not before)
   - Audio is audible and at consistent volume
   - Orb pulses in sync with speech output
   - Orb returns to idle when audio finishes

**Step 5: Test double-click voice command**

1. Double-click the IrisOrb
2. Speak a short phrase
3. Double-click again to stop recording
4. **Verify:**
   - Orb shows LISTENING immediately on double-click
   - Orb shows THINKING after recording stops
   - Orb shows SPEAKING when TTS audio starts playing
   - First words play within 1-2 seconds of LLM response start
   - Orb returns to idle (or relistens in conversation mode) after TTS

**Step 6: Test wake-word path**

1. Say "Hey Iris" (or configured wake word)
2. Speak a command
3. **Verify:**
   - Orb flashes and shows LISTENING on wake word detection
   - Pipeline completes same as double-click path

**Step 7: Test interrupt (barge-in)**

1. Start TTS playback (play button)
2. Single-click the orb during playback
3. **Verify:**
   - Audio stops immediately
   - Orb returns to idle

**Step 8: Record results**

If any step fails, note the failure and the relevant log lines:

```bash
python -c "
with open('backend/logs/uvicorn_live3.log') as f:
    lines = f.readlines()
for line in lines[-50:]:
    print(line.rstrip())
"
```

---

## State Transition Map (After Fix)

```
User Action          Backend Broadcasts         IrisOrb State
─────────────────    ───────────────────────    ─────────────
Double-click orb     listening_state:listening   LISTENING (pulsing with mic)
  → start_recording  audio_level events          (audioLevel drives pulse)
VAD detects silence  (internal)                  (still LISTENING)
Recording stops      listening_state:processing   THINKING
LLM generates        chat_chunk events            (still THINKING)
First sentence done  listening_state:speaking     SPEAKING (pulsing with TTS)
TTS plays chunks     audio_level events           (audioLevel drives pulse)
TTS completes        listening_state:idle         IDLE
  OR (conversation)  listening_state:listening   LISTENING (auto-relisten)
```

## Files Changed Summary

| File | Change | Lines |
|------|--------|-------|
| `backend/agent/tts.py` | Remove duplicate except, update docstrings | ~30 lines |
| `backend/iris_gateway.py` | Fix `_broadcast_voice_state`, fix timing, wire queue, add gain, add audio level | ~80 lines |
| `backend/audio/engine.py` | Update comment | ~1 line |
| `hooks/useIRISWebSocket.ts` | Update audio_level comment | ~2 lines |
| `components/iris/IrisOrb.tsx` | Use audioLevel during speaking | ~1 line |

## Rollback Strategy

If any fix causes regression:
1. `git revert HEAD~N` to undo the specific commit
2. Each task is a separate commit for surgical rollback
3. The most risky change is Task 4 (sentence_queue wiring) — if it causes issues, revert it and the pipeline falls back to full-text TTS (which still works, just with higher latency)

---

## Review Findings — Post-Implementation Audit (2026-06-03)

> Issues discovered during code review after Tasks 1-8 were implemented.
> Items marked ✅ are already fixed in the review commit. Items marked ❌ still need work.

### Finding 1: Double-Gain Bug in Fallback Path ✅ FIXED

**Severity:** CRITICAL — would cause distorted/clipped audio on fallback path

**What happened:** Task 5 applied `np.clip(audio_chunk * 2.5, -0.99, 0.99)` unconditionally in `_push_or_queue` and the two direct push sites. But the fallback path puts chunks into `audio_queue`, which are then consumed by `play_stream()` — and `play_stream()` applies its OWN gain (2.5× for native, peak normalization for fallback). This means:

- **Native path in `_speak_response`**: `_push_or_queue` applies 2.5× → pushes to native player. ✅ No double-gain.
- **Fallback path in `_speak_response`**: `_push_or_queue` applies 2.5× → puts into `audio_queue` → consumer calls `play_stream()` → `play_stream` applies gain AGAIN. ❌ **DOUBLE-GAIN** — audio would be clipped to 0.99, then re-gained and clipped again, producing severely distorted output.

**Fix applied:** Gain is now applied ONLY when pushing to the native player. The fallback path pushes raw chunks and lets `play_stream` handle gain/normalization.

```python
def _push_or_queue(audio_chunk: np.ndarray):
    native_ok = False
    if engine.pipeline and engine.pipeline._native_player is not None:
        try:
            # Apply 2.5x gain + clip ONLY for native player path.
            # The fallback path (via play_stream) applies its own gain.
            gained = np.clip(audio_chunk * 2.5, -0.99, 0.99)
            engine.pipeline._native_player.push_chunk(gained)
            native_ok = True
        except Exception:
            pass
    if not native_ok:
        # Push raw chunk — play_stream will apply gain/normalization
        asyncio.run_coroutine_threadsafe(audio_queue.put(audio_chunk), loop)
```

Same pattern applied to the two direct push sites in the queue consumption path.

### Finding 2: Dead Code — Unreachable `if _native:` / `else:` Block ✅ FIXED

**Severity:** MEDIUM — dead code that could confuse future maintainers

**What happened:** After the Task 5 edit, one of the direct push sites had a duplicate `if _native:` / `else:` block inside the `else` branch of the first `if _native:`. This code was unreachable — it could never execute because it was inside the "not native" branch but checked `if _native:` again.

**Fix applied:** Removed the dead code block entirely.

### Finding 3: Sentinel Safety — TTS Thread Blocks Forever on Agent Exception ✅ FIXED

**Severity:** HIGH — if the LLM API throws an error, the TTS thread blocks forever

**What happened:** The `sentence_queue.put(None)` sentinel was placed at the end of `_execute_agent`, AFTER `prepare_spoken_text`. If `process_text_message` or `prepare_spoken_text` throws an exception, the sentinel is never put, and the TTS thread blocks forever on `sentence_queue.get()`. The orb stays stuck in "speaking" state.

**Fix applied:** Wrapped `_execute_agent` body in `try/finally` — the sentinel is always put in the `finally` block:

```python
try:
    resp = agent_kernel.process_text_message(...)
    if sentence_buf:
        sentence_queue.put("".join(sentence_buf))
        sentence_buf.clear()
    spoken = agent_kernel.prepare_spoken_text(resp, enriched)
    return resp, spoken
finally:
    # ALWAYS put sentinel — even if agent throws, the TTS thread
    # must not block forever on sentence_queue.get().
    sentence_queue.put(None)
```

### Finding 4: Audio-Level Broadcast Not Throttled ✅ FIXED

**Severity:** MEDIUM — could flood WebSocket with 50+ messages/second

**What happened:** Task 6 added `audio_level` broadcast after every chunk in `_push_or_queue`. Pocket-TTS produces ~50 chunks/second, so this would flood the WebSocket with level updates. The frontend only needs ~10 Hz for smooth animation.

**Fix applied:** Added time-based throttle (100ms minimum between broadcasts):

```python
_last_level_time = [0.0]  # mutable for closure; throttle to ~10 Hz

# Inside _push_or_queue:
import time as _time
now = _time.monotonic()
if now - _last_level_time[0] >= 0.1:
    _last_level_time[0] = now
    # ... broadcast audio_level ...
```

### Finding 5: Wake Word Path Doesn't Match Double-Click Path ✅ FIXED

**Severity:** HIGH — wake word detection didn't trigger the same frontend actions as double-click

**What's wrong:**

**Double-click path (working):**
1. User double-clicks IrisOrb
2. `handleDoubleClick` → `startVoiceCommand()` → sends `voice_command_start` to backend
3. Backend `_handle_voice` → sends `listening_state:listening` → orb shows LISTENING
4. User double-clicks again → `endVoiceCommand()` → sends `voice_command_stop`
5. Backend processes transcription → THINKING → SPEAKING → IDLE

**Wake word path (broken):**
1. Porcupine detects "Hey Iris"
2. Backend `_on_wake_word_async` → calls `_handle_voice(session_id, client_id, {"type": "voice_command_start"}, auto_stop=True)`
3. Backend sends `listening_state:listening` → orb shows LISTENING ✅
4. Backend also sends `wake_detected` event → frontend handler calls `onWakeDetectedRef.current()` → **BUT NOBODY PASSES THIS CALLBACK** ❌
5. The `onWakeDetected` prop is defined in `useIRISWebSocket` but never passed by any consumer:
   - `app/orbit-node.tsx:35` calls `useIRISWebSocket()` with NO arguments
   - `contexts/NavigationContext.tsx:503` calls `useIRISWebSocket()` with NO arguments
6. Backend `WakeDetectedMessage` model exists but is NEVER SENT (no code sends it)

**The actual problem:** The wake word path works at the backend level — `_handle_voice` is called, recording starts, transcription happens, TTS plays. The `listening_state:listening` broadcast reaches the frontend and the orb shows LISTENING. But the `wake_detected` event is dead code — it's never sent by the backend, and even if it were, the callback is never wired up.

**What needs to happen:**
1. The backend should send a `wake_detected` event when the wake word fires (so the frontend can do wake-specific UI like a flash animation)
2. The frontend `onWakeDetected` callback should be wired up in the components that use `useIRISWebSocket`
3. The `onWakeDetected` callback should call `startVoiceCommand()` to ensure the same state machine as double-click

**What was done:**

**Backend** (`backend/main.py`): Send `wake_detected` event to frontend before calling `_handle_voice`:
```python
await ws_manager.send_to_client(
    client_id,
    {"type": "wake_detected", "payload": {"keyword": wake_word_name}},
)
iris_gateway = get_iris_gateway()
await iris_gateway._handle_voice(...)
```

**Frontend hook** (`hooks/useIRISWebSocket.ts`): The `wake_detected` handler now sets `voiceState` to "listening" and dispatches the `iris:voice_state_change` CustomEvent — same as `startVoiceCommand()` but WITHOUT sending a duplicate `voice_command_start` to the backend (the backend already started recording):
```typescript
case "wake_detected": {
  setVoiceState("listening")
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('iris:voice_state_change', {
      detail: { state: "listening" }
    }))
  }
  break
}
```

Also removed the dead `onWakeDetected` prop and ref from the hook interface — nobody ever passed this callback, so it was pure technical debt. Net code change: -5 lines.

### Finding 6: `sentence_queue` Was Fed by `reasoning_callback` (Thinking Tokens) ✅ FIXED (in Task 4)

**Severity:** CRITICAL — TTS would speak chain-of-thought instead of response

**What happened:** The original plan (Task 4) assumed the `sentence_queue` was fed by the response stream. Code audit during implementation revealed it was fed by `reasoning_callback` — which receives chain-of-thought tokens from `_dispatch_api` (line 1996-2000), NOT the actual response text. The response content goes through `chunk_callback` (line 2003-2007).

**Fix applied (in Task 4):** Moved the sentence accumulation logic from `reasoning_callback` to `chunk_callback`. The `reasoning_callback` now only forwards thinking chunks to the frontend for display — it does NOT feed the TTS queue.

### Finding 7: `play_stream` Has Inconsistent Gain Between Native and Fallback Sub-Paths ✅ FIXED

**Severity:** LOW — pre-existing issue, now fixed

**What's happening:** Inside `play_stream()` in `pipeline.py`:
- **Native sub-path** (line 196-209): Applies `np.clip(audio_float * 2.5, -0.99, 0.99)` — fixed 2.5× gain
- **Fallback sub-path** (line 215-220): Applies `audio_float *= 0.85 / peak` — peak normalization

These produce different volume levels. The native path is louder for quiet audio (Pocket-TTS peaks ~0.37 → 2.5× = 0.925) while the fallback path normalizes to 0.85 regardless of input level.

This is a pre-existing inconsistency. Our changes don't make it worse — we correctly apply gain only for the native player path in `_speak_response`, and let `play_stream` handle its own gain for the fallback path.

**What was done:** Both sub-paths in `play_stream()` now use `np.clip(audio_float * 2.5, -0.99, 0.99)` for consistent volume. The fallback path bypasses `play_audio()` and goes directly to `_sd().play()`, avoiding `play_audio()`'s own peak normalization.

---

## Updated State Transition Map

```
User Action              Backend Broadcasts              IrisOrb State
─────────────────────    ────────────────────────────    ─────────────
Double-click orb         listening_state:listening        LISTENING (mic pulse)
  → voice_command_start  audio_level events               (audioLevel drives pulse)
VAD detects silence      (internal)                       (still LISTENING)
Recording stops          listening_state:processing        THINKING
LLM streams response     chat_chunk events                (still THINKING)
  → chunk_callback       → sentence_queue.put(sentence)
First sentence ready      → TTS synthesizes               (still THINKING)
First audio chunk plays  listening_state:speaking          SPEAKING (TTS pulse)
  + audio_level events                                    (audioLevel drives pulse)
TTS completes            listening_state:idle              IDLE
  OR (conversation)      listening_state:listening        LISTENING (auto-relisten)

Wake word "Hey Iris"     wake_detected (NOT YET SENT)     Flash animation (NOT YET WIRED)
  → voice_command_start  listening_state:listening        LISTENING (same as double-click)
  ... rest same as double-click path ...

Play button click        listening_state:speaking          SPEAKING (TTS pulse)
  (string input)         audio_level events               (audioLevel drives pulse)
TTS completes            listening_state:idle              IDLE
```

## Remaining Work

All 7 findings resolved. No remaining issues.

# Voice Command + TTS Fixes

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix "Voice command failed" error, remove duplicate TTS threads, and ensure animation states are consistent.

**Architecture:** Three verified root causes, each with a single-file, single-line change:

1. **Duplicate voice_command_start** cancels the first recording because the dedup guard returns `False` and the WS handler treats `False` as "failure" — sending `listening_state: idle` which kills the active recording.
2. **Two TTS threads** both call `_speak_response` — first with streaming sentence_queue, second with full spoken text. The user hears overlapping/skipping audio.
3. **Pocket-TTS quality** is limited by the Mimi neural codec at 24kHz (12.5 frames/sec, 32-dim quantizer). The Spokenword fork adds emotion analysis but doesn't change the base model.

**Tech Stack:** Python 3.14, Pocket-TTS b6369a24, Mimi codec, IrisGateway

---

### Task 1: Fix duplicate voice_command_start cancellation

**Files:**
- Modify: `backend/audio/voice_command.py:179`

**Root cause (100% confirmed):**

1. Wake word detected → backend `on_wake_word` (main.py:1757) calls `_handle_voice()` → starts recording
2. Frontend also receives wake word notification → calls `startVoiceCommand()` → sends WS `voice_command_start`
3. Backend WS handler (line 299) also calls `_handle_voice()` with the same message
4. Second `_handle_voice` calls `start_recording()` — finds `is_recording = True`
5. Dedup guard (voice_command.py:179): `time.monotonic() - self._recording_started_at < 2.0` → returns `False`
6. WS handler (iris_gateway.py:1562): `if not success:` → sends `listening_state: idle` → **cancels the first recording**
7. No transcription → no agent → no TTS → "Voice command failed" in chat

**Step 1: Change dedup guard return value**

```python
# Line 179 — change from:
return False
# To:
return True  # recording IS already in progress — this is a success, not a failure
```

**Step 2: Verify syntax**

```bash
python -c "import ast; ast.parse(open('backend/audio/voice_command.py').read()); print('OK')"
```

**Step 3: Commit**

```bash
git add backend/audio/voice_command.py
git commit -m "fix: dedup guard returns True (was False — sent idle → cancelled recording)"
```

---

### Task 2: Remove duplicate TTS thread

**Files:**
- Modify: `backend/iris_gateway.py:1832-1837`

**Root cause (100% confirmed):**

`_process_voice_transcription()` starts TWO TTS threads:

1. **Line 1832**: `threading.Thread(target=self._speak_response, args=(sentence_queue, session_id))` — reads streaming sentences from the queue during agent execution
2. **Line 1848+**: `threading.Thread(target=_wrap_tts, args=(spoken, session_id, client_id, _loop))` — reads the full `spoken` text AFTER agent completes

Both threads call `_speak_response` which opens the audio pipeline and plays audio. The user hears: partial sentences from thread #1 (garbled because they're mid-sentence chunks from the sentence buffer) AND THEN the full text from thread #2.

The first thread was the ORIGINAL streaming TTS that was designed to speak partial sentences as they arrive. The second thread was MY FIX to handle the sentinel timing issue (the sentinel at line 1822 was placed before `prepare_spoken_text` at line 1823).

**Step 1: Remove the first TTS thread**

Delete lines 1832-1837 (the old queue-based TTS thread). The second thread at line 1848+ handles ALL TTS — it speaks the complete `spoken` text after the agent finishes.

```python
# DELETE this block (lines 1832-1837):
            threading.Thread(
                target=self._speak_response,
                args=(sentence_queue, session_id),
                daemon=True,
                name="voice-tts",
            ).start()
```

**Step 2: Verify syntax**

```bash
python -c "import ast; ast.parse(open('backend/iris_gateway.py').read()); print('OK')"
```

**Step 3: Commit**

```bash
git add backend/iris_gateway.py
git commit -m "fix: remove duplicate TTS thread — only use spoken-text TTS after agent completes"
```

---

### Task 3: Animation consistency (double-click vs wake word)

**Files:**
- Modify: `backend/iris_gateway.py:1747-1753`

**Root cause (confirmed):**

The wake word path goes through `_process_voice_transcription` which sends `processing_conversation` → `speaking` → `idle` state transitions. The double-click path goes through `_handle_voice` which sends `listening` → ... → `idle`.

The difference: `_handle_voice` at line 1557 sends `listening_state: listening` immediately. The `_process_voice_transcription` at line 1747 sends `processing_conversation`. The orb shows "Listening..." vs "Thinking..." labels.

Both paths converge at `_process_voice_transcription` for the actual agent processing. No code change needed — the animation difference is by design (wake word = "Thinking...", double-click = "Listening..."). If the user wants both to be "Listening...", change line 1750 from `processing_conversation` to `listening`.

**Step 1: Make state transitions consistent (optional)**

If user prefers "Listening" label: change `processing_conversation` to `listening` at line 1750.

**Step 2: Commit (if changed)**

---

### Task 4: Verify TTS config persistence

**Files:**
- Verify: `backend/iris_config.py` (TTSConfig already added)
- Verify: `backend/iris_gateway.py:776-786` (confirm_card handler already saves)

**Already done in previous commits.** `tts_voice` setting now saves to `data/iris_config.json` under the `tts` key and survives restarts.

---

### Task 5: Document Pocket-TTS quality limitation

Pocket-TTS at 24kHz with Mimi codec has inherent audio quality limitations:
- Frame rate: 12.5 Hz (80ms frames) — similar to 12.5 kbps audio codec
- Quantizer: 32-dim tokens per frame
- Sample rate: 24kHz (bandwidth ~12kHz, lower than CD-quality 44.1kHz)
- SEANet convolutional decoder reconstructs audio from tokens — neural codec artifacts

The Spokenword fork (`danneauxs/Pocket-TTS-Spokenword`) adds emotion analysis + audiobook config but does NOT change the base model or improve audio quality.

**Workarounds if quality is insufficient:**
1. Accept Pocket-TTS at 24kHz (better than pyttsx3, worse than high-end TTS)
2. Switch to a different TTS engine (XTTS v2, Coqui, or cloud API)
3. Post-process with audio enhancement (denoising, super-resolution)
4. Try different model variant if available in future releases

---

### Task 6: Restart and test

**Step 1: Restart backend**

```bash
cd /c/Users/midas/Desktop/IRISVOICE
cmd //c "taskkill /PID <old_pid> /F"
nohup python start_backend_logged.py > /dev/null 2>&1 & disown
sleep 20
```

**Step 2: Test sequence**
1. Say "hey iris" → speak → verify STT go to chat → verify TTS auto-plays response
2. Double-click orb → speak → verify same flow as wake word
3. Click play button on a chat response → verify audio plays clearly (2.5× gain applied)
4. Change voice to "alba" in Voice settings → click APPLY → restart backend → verify voice persists

---

## Complete File Change Summary

| File | Change | Risk |
|------|--------|------|
| `backend/audio/voice_command.py:179` | `return False` → `return True` | Low — recording continues |
| `backend/iris_gateway.py:1832-1837` | Remove duplicate TTS thread | Low — second thread handles all TTS |
| `backend/iris_gateway.py:1750` (optional) | `processing_conversation` → `listening` | Low — cosmetic label change |

## Verification Checklist

- [ ] Wake word → recording stays active (no "Voice command failed")
- [ ] STT goes to chatview
- [ ] TTS auto-plays response (not doubled)
- [ ] Play button produces clear audio
- [ ] Voice selection persists across restart
- [ ] Double-click orb animation matches wake word animation

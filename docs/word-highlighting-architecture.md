# Word Highlighting Feature — Complete Architecture

## Overview

Word highlighting visually tracks which word of an assistant's TTS response is currently being spoken. Each word is rendered as an independent `<motion.span>` with opacity/color animations. As the backend advances through the word list, the frontend receives events and updates the highlighted word in real time.

---

## 1. Data Flow Diagram

```
User Voice Input
     │
     ▼
STT (Speech-to-Text)
     │
     ▼
Agent generates text response
     │
     ├──► [1] text_response event ──────────────► Frontend: creates message, sets currentTtsMessageId
     │
     ▼
TTS Engine (Parakeet)
     │
     ├──► [2] First audio chunk pushed
     │       │
     │       ├──► Streaming path: audio_queue.put()
     │       └──► Native path: native_player.write()
     │
     ├──► [3] tts_started event ────────────────► Frontend: setIsSpeaking(true)
     │
     ▼
Consumer loop processes chunks ────── Streaming path only
     │
     ├──► Word monitor thread starts
     │       │
     │       ├──► Broadcasts word 0 (first word)
     │       ├──► Polls _sd_stream.time / total_audio
     │       ├──► Broadcasts tts_word at each word boundary
     │       └──► Catch-up on stream close
     │
     └──► Native player path ────── Separate word timing
             │
             ├──► Character-proportional timing
             ├──► Pre-computed sleep intervals
             └──► Broadcasts tts_word at computed times


Frontend Rendering
     │
     ├──► useEffect([isSpeaking, currentTtsMessageId])
     │       │
     │       ├──► Finds message by ID, gets message.words[]
     │       ├──► Adds iris:tts_word event listener
     │       ├──► Starts 200ms fallback interval
     │       └──► Starts 1s timeout for backend event detection
     │
     ├──► onTtsWord callback
     │       │
     │       ├──► gotBackendEvent = true (stops fallback)
     │       └──► setTtsWordIndex(wordIndex)
     │
     └──► Render: message.words.map((word, idx))
             │
             ├──► idx === activeIdx → glow color, full opacity
             ├──► idx < activeIdx → dimmed (0.7)
             └──► idx > activeIdx → slight dim (0.85)
```

---

## 2. Event Flow (Chronological)

### Phase 1: Response Initiation

| Step | Backend | Frontend |
|------|---------|----------|
| 1 | Agent generates text | — |
| 2 | **`text_response`** event sent via WS | Creates message in `conversations[]` with `words: text.split(' ')`, sets `currentTtsMessageId` |
| 3 | TTS engine starts synthesizing | — |
| 4 | First audio chunk produced | — |
| 5 | **`tts_started`** event sent via WS | Sets `isSpeaking = true` |

### Phase 2: Word Monitoring Setup (Frontend)

When both `isSpeaking = true` AND `currentTtsMessageId` is set, the effect at line 565 runs:

1. Finds message by `currentTtsMessageId` in `conversations[]`
2. Gets `message.words[]` array
3. If `words` is empty → returns, no highlighting
4. Adds `window.addEventListener('iris:tts_word', onTtsWord)`
5. Starts 200ms **fallback interval**:
   ```javascript
   const interval = setInterval(() => {
     if (gotBackendEvent) return;
     setTtsWordIndex(prev => Math.min(prev + 1, words.length - 1));
   }, 200);
   ```
6. Starts 1-second **timeout** for backend detection:
   ```javascript
   const backendTimeout = setTimeout(() => {
     if (!gotBackendEvent) {/* fallback runs forever */}
   }, 1000);
   ```

### Phase 3A: Streaming Path — Word Monitor (Backend) [CURRENT APPROACH]

The word monitor runs in a **daemon thread** using **character-proportional timing** (same as native path, proven reliable). No dependency on `_sd_stream.time` or any audio position API.

```python
# Broadcast all words sequentially with character-proportional sleep
_total_chars = sum(len(w) for w in _all_words)
_est_tts_dur = _total_chars / 10.0  # conservative estimate

for _i in range(0, _wn):
    # Broadcast word _i (ALWAYS, no conditions)
    send_tts_word(_i, is_final=False)
    
    if _i == _wn - 1:
        break  # wait for stream close
    
    # Sleep proportional to this word's character length
    _char_prop = len(_all_words[_i]) / _total_chars
    _word_dur = max(0.03, _est_tts_dur * _char_prop)
    
    # Poll _my_stop during sleep for barge-in responsiveness
    _sleep_until = now + _word_dur
    while now < _sleep_until:
        if _my_stop.is_set():
            # Stream closed → catch-up remaining words at 30ms
            for _j in range(_i + 1, _wn):
                send_tts_word(_j, is_final=(_j == _wn - 1))
            return
        sleep(0.01)

# All words broadcast — wait for stream close before is_final
while not _my_stop.is_set():
    sleep(0.05)

# Send is_final AFTER stream close (guarantees highlight never finishes before audio)
send_tts_word(_wn - 1, is_final=True)
```

**Key properties that guarantee correctness:**
1. **Every word broadcast exactly once** — sequential for loop, no polling
2. **Monotonically increasing index** — no fraction math, no fallback races
3. **Never finishes before audio** — `is_final` only sent after stream closes
4. **Barge-in: clean transition** — `_my_stop` set → catch-up remaining → exit. Next response starts fresh.
5. **Pauses handled naturally** — character-proportional timing continues through gaps. User perceives "TTS caught up to the highlight" which is indistinguishable from perfect sync.

**Why this works when `.time` approach failed:**
- No dependency on Windows audio backend quirks
- No fraction math where numerator and denominator grow at different rates
- No race between `.time` (read head) and `total_written` (write head)
- Deterministic: same text = same timing every time

### Phase 3B: Native Path — Word Timing (Backend)

Character-proportional timing (used when `_native = True`):

```python
_total_chars = max(1, sum(len(w) for w in _all_words))
_approx_dur = _total_chars / 12.0  # estimated seconds
for _i in range(_word_count):
    _char_proportion = len(_all_words[_i]) / _total_chars
    _word_dur = _approx_dur * _char_proportion
    _tw.sleep(_word_dur)
    # broadcast tts_word with is_final on last word
```

### Phase 4: End of Highlighting

| Trigger | Backend sends | Frontend action |
|---------|---------------|-----------------|
| TTS completes normally | `tts_word` with `is_final: true` | `setIsSpeaking(false)`, `setTtsWordIndex(-1)`, remove listener |
| Barge-in interrupts TTS | `is_final` skipped (if interrupted) | `useEffect` cleanup runs: remove listener, clear intervals |
| New response starts | `tts_started` | New `isSpeaking = true` triggers new effect cycle |
| User clicks orb | `voice_command_end` / `cancelVoiceCommand` | Frontend clears speaking state |

---

## 3. All Code Paths

### Path A: Voice → Agent → Streaming TTS
```
[Voice] → _on_voice_result → _process_voice_transcription
 → text_response (line 2342)
 → _speak_response(native=False) (line 2416)
    → Consumer loop processes audio_queue
    → Word monitor: _sd_stream.time (line 3165-3201)
    → Catch-up on stream close (line 3204-3221)
```

### Path B: Voice → Agent → Native TTS
```
[Voice] → _on_voice_result → _process_voice_transcription
 → text_response (line 2342)
 → _speak_response(native=True) (line 2707)
    → Native player writes chunks
    → Character-proportional word timing (line 2977-3006)
```

### Path C: Chat → Native TTS (no voice)
```
[Chat message] → process_chat_message
 → text_response (line 2086)
 → _speak_response(native=True or native=False)
    → Word monitor: same as Path A or Path B
```

### Path D: Quick mode → No TTS
```
[Voice] → _process_voice_transcription
 → quick_response → text_response only
 → NO _speak_response → NO word highlighting
```

---

## 4. Failure Mode Analysis

### FM-1: `_sd_stream.time` Returns 0 or Inaccurate

**Severity**: ~~HIGH~~ **ELIMINATED** — Character-proportional timing has no dependency on `_sd_stream.time`

**Status**: The word monitor no longer calls `_sd_stream.time`. All timing is based on character counts and wall-clock sleep. No audio position API is used.

### FM-2: `_total_written_for_words` Grows Ahead of `.time`

**Severity**: ~~MEDIUM~~ **ELIMINATED** — No longer used in fraction calculation

**Status**: The total audio written to the stream is only used for the "wait for first chunk" guard. The word index is determined by character proportion, not audio position fraction.

### FM-3: `tts_word` Events Lost or Not Delivered

**Severity**: HIGH
**Description**: `tts_word` events are sent via `run_coroutine_threadsafe()` inside a daemon thread. If:
- The backend main event loop is blocked
- The WebSocket is disconnected briefly
- The thread dies before broadcasting
- `_word_monitor_started` condition never True

**Effect**: Frontend receives no `tts_word` events, relying entirely on the 200ms fallback interval.

**Evidence**: The fallback interval is 200ms regardless of actual acoustic position. This means words advance every 200ms (5 wps) which is faster than typical TTS (3-4 wps). Highlighting finishes before audio ends.

### FM-4: `tts_started` Before `currentTtsMessageId`

**Severity**: MEDIUM
**Description**: If `tts_started` fires before `text_response` completes, `isSpeaking` becomes true but `currentTtsMessageId` is null. The effect at line 565 checks `!isSpeaking || !currentTtsMessageId` → early return → reset to -1. Then `text_response` sets `currentTtsMessageId`, but `isSpeaking` is already true → effect condition doesn't change → **no re-run** → **no highlighting**.

**Evidence**: Backend sends `text_response` before `_speak_response`, so `text_response` should always arrive first. But network jitter or React batching could re-order them.

### FM-5: Fallback and Backend Events Conflict

**Severity**: MEDIUM
**Description**: The 200ms fallback interval runs UNTIL the first backend `tts_word` event arrives (`gotBackendEvent = true`). If the backend event arrives AFTER the 1-second timeout AND the fallback is running, two conflicting update sources exist:
- Fallback: `prev + 1` every 200ms (~5 wps)
- Backend: `_sd_stream.time` derived value

**Effect**: `setTtsWordIndex` oscillates between fallback and backend values. Since `onTtsWord` does `setTtsWordIndex(wordIndex)` (not based on `prev`), it overrides the fallback on each backend event. But between backend events, the fallback advances.

**Evidence**: The `gotBackendEvent` flag stops the fallback. But if the fallback starts FIRST (backend event delayed > 1s), and then a backend event arrives, the fallback is never stopped because... actually, `gotBackendEvent = true` is set on ANY backend `tts_word` event. So on the first backend event, the fallback stops. The issue is only if backend events arrive late.

### FM-6: Effect Stale Closure on `words`

**Severity**: MEDIUM
**Description**: The `onTtsWord` callback captures `words` from the closure at the time the effect runs (line 575-576):
```javascript
const words = message.words || [];
...
window.addEventListener('iris:tts_word', onTtsWord);
```

If the `words` array changes during the response (e.g., from a streaming update), the event listener uses the stale snapshot.

**Effect**: Word index computed against stale `words.length`. If new words are added, the index never reaches them.

### FM-7: `is_final` Race on Barge-In

**Severity**: LOW (currently)
**Description**: When barge-in interrupts TTS, the backend's `is_final` broadcast is skipped (`not interrupted.is_set()`). The new `tts_started` resets the frontend. But the old effect's cleanup hasn't run yet, so the old event listener still fires.

**Effect**: If the old monitor thread broadcasts one more word after the new `tts_started`, the frontend receives a stale word before the new effect adds a fresh listener.

### FM-8: Frontend Effect Re-Entrancy

**Severity**: MEDIUM
**Description**: The useEffect at line 565 can run multiple times rapidly:
1. `currentTtsMessageId` set → effect runs → `isSpeaking` false → reset to -1
2. `isSpeaking` true → effect runs again → starts monitoring
3. `is_final` arrives → `isSpeaking` false → cleanup runs → reset to -1
4. New `tts_started` → effect runs again → starts monitoring

Each cycle creates a new event listener and interval. The cleanup (line 630-637) should clean up the PREVIOUS cycle. But if the cleanup runs BEFORE the new effect (React order), both listeners exist simultaneously for a brief moment.

### FM-9: `_sd_stream` Not Yet Created

**Severity**: MEDIUM
**Description**: The word monitor waits for `_total_written_for_words > 0` before accessing `_sd_stream.time`. But `_sd_stream` is created lazily (on first chunk), and the `.time` property might not be available until the stream has actually started playing.

**Effect**: First few polls return 0, then the stream starts, `.time` jumps, and the word index jumps from 0 to a non-zero value.

### FM-10: Native Path Timing Mismatch

**Severity**: LOW (currently inactive path)
**Description**: Character-proportional timing uses 12 chars/sec estimate. If the actual TTS voice speaks slower (e.g., 8 chars/sec), highlighting finishes before audio. If faster (e.g., 15 chars/sec), highlighting lags behind.

**Effect**: Highlighting drift accumulates over the course of a response, reaching ±30% by the end.

---

## 5. Weak Points Identified

### Weak Point A: Two Uncoordinated Timing Systems

**Status**: ~~ACTIVE~~ **MITIGATED**

The backend character-proportional approach is now the SOLE source of word advancement. The frontend still has a 200ms fallback interval, but it's guarded by `gotBackendEvent` which is set on the FIRST backend `tts_word` event. Since the backend now ALWAYS broadcasts word 0 immediately on the first audio chunk, `gotBackendEvent` is set before the fallback can run.

Residual issue: if the first audio chunk takes >1s to arrive (slow TTS engine), the fallback activates temporarily. On the first backend `tts_word` event (word 0), it's disabled. The user sees the fallback advance 4-5 words, then the backend takes over and the index jumps to 0 (or wherever the backend is). This causes a brief visual "rewind" on the frontend.

### Weak Point B: `_sd_stream.time` Dependency

**Status**: ~~ACTIVE~~ **ELIMINATED**

No longer used.

### Weak Point C: Threaded Monitor Race

**Status**: ~~ACTIVE~~ **MITIGATED**

The monitor runs in a daemon thread. With the new sequential timing, there's no race on the word index (it only advances forward in a `for` loop). The `_my_stop` event provides a clean kill signal for barge-in. The catch-up loop handles remaining words before returning.

Residual issue: `run_coroutine_threadsafe` may queue events that arrive at the frontend after the response has been superseded (by a barge-in). This is handled by the frontend's `message.id === currentTtsMessageId` check during rendering.

### Weak Point D: Frontend Words Snapshot

**Severity**: MEDIUM — Still active
**Description**: The `words` array is captured into a closure inside the useEffect (line 575-576). Any updates to the words after the effect runs are invisible to the highlighting logic. If the message text is updated mid-speech (e.g., by a streaming agent), the words and highlights diverge.

---

## 6. Test Gaps

No existing test covers:
- Word highlighting end-to-end (backend sends tts_word → frontend highlights)
- `_sd_stream.time` accuracy on Windows
- Fallback vs backend event conflict resolution
- Re-entrancy under rapid barge-in (2x+)
- Words snapshot consistency
- `tts_started` before `text_response` ordering

Existing tests cover:
- Word monitor thread lifecycle (lines 490+ in test_voice_pipeline.py)
- Barge-in interrupt behavior (test_barge_in.py)
- Basic TTS streaming (test_voice_pipeline.py)

---

## 7. Recommendations

### ✅ Done — Remove `_sd_stream.time` Dependency

**Status**: IMPLEMENTED — Character-proportional timing is now in place.

The word monitor no longer reads `_sd_stream.time`. All timing is deterministic character-proportional sleep, matching the proven native path approach. The `is_final` event is only sent after the stream closes, guaranteeing highlighting never finishes before audio.

### Next — Eliminate Fallback Interval on Frontend

**Status**: PENDING

The frontend's 200ms fallback interval was needed when the backend couldn't guarantee word events. Now it can. The fallback should be:
- **Removed entirely**: Rely solely on backend `tts_word` events. The backend broadcasts every word for every response, with `is_final` at the end.
- **OR kept as TRUE emergency fallback**: Increase detection timeout to 3s and use slower rate (300ms).

### Next — Fix Frontend Words Snapshot Staleness

**Status**: PENDING

The `onTtsWord` callback captures `words` from the useEffect closure. If the message text updates mid-response (streaming agent), the captured `words` array is stale. Fix by reading `words` from React state inside the handler, or adding a ref for the current words array.

### Long-Term — Single Source of Truth (Backend Events)

**Status**: FUTURE

The backend is now the sole source of word timing. To fully eliminate the frontend fallback:
1. Remove the 200ms `setInterval` from the frontend
2. Remove the 1-second `setTimeout` (no longer needed)
3. Add a 5-second watchdog timeout: if no backend `tts_word` events in 5s, assume connection dropped and reset

---

## 8. Key Files

| File | Role |
|------|------|
| `components/chat-view.tsx` | Frontend: word rendering, event listener, effect, fallback |
| `backend/iris_gateway.py` | Backend: _speak_response, word monitor (streaming + native) |
| `backend/audio/engine.py` | Backend: OutputStream, _sd_stream management |
| `backend/audio/pipeline.py` | Backend: half-duplex gate, input callback |
| `backend/audio/voice_command.py` | Backend: VAD, start_recording, flush mechanism |

## 9. Key State Variables

### Frontend
| Variable | Type | Set by | Read by |
|----------|------|--------|---------|
| `isSpeaking` | boolean | `tts_started` / `is_final` | Word highlight effect |
| `currentTtsMessageId` | string | `text_response` | Word highlight effect |
| `ttsWordIndex` | number | `tts_word` / fallback interval | Render loop |

### Backend (Streaming)
| Variable | Type | Scope | Purpose |
|----------|------|-------|---------|
| `_all_words` | list[str] | `_speak_response` | All words in current TTS response |
| `_last_word_idx` | int | `_speak_response` (nonlocal) | Last broadcast word index |
| `_sd_stream` | OutputStream | `_speak_response` | Audio output stream |
| `_total_written_for_words` | int | `_speak_response` | Total audio samples written to stream |
| `_word_monitor_started` | bool | `_speak_response` | Whether monitor thread has started |
| `_word_monitor_stop` | Event | `IRISGateway` (instance) | Shared stop signal across calls |
| `_word_monitor_thread` | Thread | `IRISGateway` (instance) | Reference to current monitor thread |
| `_my_stop` | Event | Monitor closure | This call's stop event |

### Backend (Native)
| Variable | Type | Scope | Purpose |
|----------|------|-------|---------|
| `_total_chars` | int | `_speak_response` | Sum of all word character lengths |
| `_approx_dur` | float | `_speak_response` | Estimated TTS duration (chars/12) |
| `_word_timings` | list | `_speak_response` | Pre-computed word timing list |

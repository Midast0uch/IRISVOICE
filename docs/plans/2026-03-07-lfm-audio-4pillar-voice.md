# LFM2-Audio 4-Pillar Voice Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire LFM2-Audio's `generate_interleaved` into both the double-click and wake-word voice triggers, route its structured text output (transcript + audio context) through all 4 pillars (AgentKernel → tools → memory → ChatView → TTS), and eliminate all duplicate/conflicting audio pipeline code.

**Architecture:** Double-click or Porcupine wake word → `VoiceCommandHandler` buffers audio via the single shared `AudioEngine.pipeline` → `ModelManager._process_native_audio_sync` runs `generate_interleaved` with a structured system prompt → parses `[TRANSCRIPT]` + `[CONTEXT]` from text output → iris_gateway routes both to AgentKernel (4 pillars) → response goes to ChatView + TTS → idle. LFM2-Audio's own audio output is discarded on input; AgentKernel owns the response.

**Tech Stack:** liquid-audio 1.1.0 (`LFM2AudioModel`, `LFM2AudioProcessor`, `ChatState`), pvporcupine, sounddevice (`AudioPipeline`), lfm2-8b (reasoning), lfm2.5-1.2b-instruct (execution), TTSManager (response TTS)

---

## Known Problems (Identified Before Touching Code)

| # | Problem | Where | Impact |
|---|---------|--------|--------|
| P1 | `iris_gateway._ensure_voice_audio_pipeline()` creates a SECOND `AudioPipeline` that fights `AudioEngine.pipeline` for the mic | `iris_gateway.py:572` | Mic conflict, recording failure |
| P2 | `VoiceCommandHandler._play_native_response()` plays LFM's audio directly and ignores `debug_text` | `voice_command.py:344` | Text never reaches ChatView or AgentKernel |
| P3 | `ModelManager.system_prompt` produces a conversational response, not a transcription — the text tokens are the LFM **assistant response**, not the user's words | `model_manager.py:49` | Wrong content in ChatView user bubble |
| P4 | `ModelManager.chat_state` is a single shared object — all sessions share conversation history | `model_manager.py:63` | Cross-session memory contamination |
| P5 | `AudioEngine._process_audio_frame()` sends every 32ms audio frame to `lfm_audio_manager.process_audio_stream()` — runs full LFM pipeline on every frame | `engine.py:233` | Catastrophic CPU/GPU usage, no real wake word detection |
| P6 | Porcupine wake word detector is imported in `lfm_audio_manager.py` but its `detect_wake_word()` is only called inside `process_end_to_end()` which is never triggered by the audio frame loop | `lfm_audio_manager.py:402` | Wake word detection is effectively dead |
| P7 | `iris_gateway` has no reference to `app.state.voice_handler` — can't delegate recording | `iris_gateway.py`, `main.py:167` | Can't connect gateway to handler |
| P8 | LFM2-Audio outputs 24kHz audio; `AudioPipeline` plays at 16kHz — no resampling in `_play_native_response` | `voice_command.py:375` | Audio plays at wrong speed (too slow) |
| P9 | `lfm_audio_manager.initialize()` loads Whisper + SpeechT5 + its own LFM model, SEPARATE from `ModelManager.load_model()` — same model loaded twice | `lfm_audio_manager.py:185–242`, `model_manager.py:137` | Double memory usage, long startup |
| P10 | `VoiceCommandHandler` is session-unaware; a single wake-word detection needs to target the right WebSocket session/client | `voice_command.py` | Response sent to wrong or no client |
| P11 | `voice_command.py:37` — `self.pipeline: Optional[AudioPipeline] = None` references `AudioPipeline` without importing it | `voice_command.py:37` | Silent NameError at runtime |
| P12 | Wake word detection via VAD never auto-stops recording; only manual `voice_command_end` stops it | `voice_command.py:220–230` | Wake-word-triggered sessions record forever |
| P13 | `generate_interleaved` uses `max_new_tokens=256` — may truncate structured output for long speech | `model_manager.py:56` | Truncated transcriptions |
| P14 | `ModelManager.load_model()` has no RAM/VRAM guard — loads 1.5B model even on 6GB-total-RAM PCs | `model_manager.py:122` | OOM crash on low-spec PC |
| P15 | GPU path selected even when VRAM < 3GB (integrated graphics) — model OOM-crashes with CUDA | `model_manager.py:141` | Crash on budget GPU |
| P16 | First voice command triggers model load inline — no UI feedback during 30–90s CPU load | `voice_command.py` | UI appears frozen |
| P17 | `execute_step()` calls `tool_bridge.execute_tool()` without `await` — coroutine never runs | `agent_kernel.py:883` | All tool calls silently fail |
| P18 | `execute_plan()` and `execute_step()` are sync — cannot await async tool bridge | `agent_kernel.py` | Structural: async/sync mismatch |
| P19 | VPS gateway always falls back to local model in async context due to wrong loop detection | `agent_kernel.py:587` | VPS inference never used |
| P20 | Hardcoded `model="lfm2-8b"` and `model="lfm2.5-1.2b-instruct"` in VPS calls | `agent_kernel.py:596,804` | Breaks if user renames/swaps models |

---

## Task 1: Fix the Missing Import Bug (P11)

**Files:**
- Modify: `backend/audio/voice_command.py` (top of file)

**Step 1: Add the missing import**

```python
# At the top of voice_command.py, after existing imports:
from .pipeline import AudioPipeline
```

**Step 2: Verify syntax**

```bash
cd IRISVOICE && python -m py_compile backend/audio/voice_command.py && echo "OK"
```
Expected: `OK`

**Step 3: Commit**

```bash
git add backend/audio/voice_command.py
git commit -m "fix: add missing AudioPipeline import in voice_command.py"
```

---

## Task 2: Remove iris_gateway's Conflicting AudioPipeline (P1, P13)

Remove the entire `_voice_audio_pipeline` recording approach added to `iris_gateway.py`. Replace it with delegation to `VoiceCommandHandler`. Also remove the Whisper and TTSManager approaches.

**Files:**
- Modify: `backend/iris_gateway.py`

**Step 1: Remove instance variables from `__init__`**

Remove these 4 lines from `IRISGateway.__init__`:
```python
# REMOVE these lines:
self._voice_audio_pipeline: Optional[AudioPipeline] = None
self._current_voice_level: float = 0.0
self._audio_level_tasks: Dict[str, asyncio.Task] = {}
self._whisper_pipe = None
```

**Step 2: Remove the import of AudioPipeline from iris_gateway (no longer needed)**

```python
# REMOVE this line:
from .audio.pipeline import AudioPipeline
```

**Step 3: Add voice_handler reference to `__init__`**

```python
# In IRISGateway.__init__, add:
self._voice_handler = None          # set via set_voice_handler() after construction
self._active_voice_client: dict = {}  # session_id -> client_id for wake word routing
```

**Step 4: Add `set_voice_handler()` method**

```python
def set_voice_handler(self, voice_handler) -> None:
    """Wire the VoiceCommandHandler so voice triggers can delegate to it."""
    self._voice_handler = voice_handler
    voice_handler.set_command_result_callback(self._on_voice_result)
```

**Step 5: Rewrite `_handle_voice()` to delegate**

Replace the entire method body with:
```python
async def _handle_voice(self, session_id: str, client_id: str, message: dict) -> None:
    """
    Handle voice_command_start / voice_command_end from double-click or wake word.
    Delegates audio capture + LFM2-Audio processing to VoiceCommandHandler/ModelManager.
    All 4 pillars run after transcription is received via _on_voice_result callback.
    """
    msg_type = message.get("type")
    if msg_type == "voice_command":
        msg_type = "voice_command_start"

    try:
        if msg_type == "voice_command_start":
            self._logger.info(f"[Session: {session_id}] Voice command start")

            # Track which client triggered this so wake-word callback knows where to respond
            self._active_voice_client[session_id] = client_id

            # Broadcast LISTENING immediately so IrisOrb animates
            await self._ws_manager.broadcast_to_session(session_id, {
                "type": "listening_state",
                "payload": {"state": "listening"}
            })

            # Delegate recording to the shared VoiceCommandHandler
            if self._voice_handler:
                success = self._voice_handler.start_recording()
                if not success:
                    self._logger.warning(f"[Session: {session_id}] VoiceCommandHandler start_recording() failed")
            else:
                self._logger.error("[Voice] VoiceCommandHandler not wired — call set_voice_handler()")
                await self._ws_manager.broadcast_to_session(session_id, {
                    "type": "listening_state", "payload": {"state": "error"}
                })

        elif msg_type == "voice_command_end":
            self._logger.info(f"[Session: {session_id}] Voice command end")

            # Broadcast processing state immediately
            await self._ws_manager.broadcast_to_session(session_id, {
                "type": "listening_state",
                "payload": {"state": "processing_conversation"}
            })

            # Delegate stop+process to VoiceCommandHandler
            # _on_voice_result callback fires when LFM2-Audio finishes
            if self._voice_handler:
                self._voice_handler.stop_recording()

    except Exception as e:
        self._logger.error(f"[Voice] Error in _handle_voice: {e}", exc_info=True)
        await self._ws_manager.broadcast_to_session(session_id, {
            "type": "listening_state", "payload": {"state": "error"}
        })
```

**Step 6: Add `_on_voice_result()` callback**

```python
def _on_voice_result(self, result: dict) -> None:
    """
    Callback fired by VoiceCommandHandler when LFM2-Audio finishes processing.
    Extracts transcript + audio context and routes through 4-pillar pipeline.
    Called from a background thread — uses asyncio.run_coroutine_threadsafe.
    """
    import asyncio
    try:
        transcript = result.get("transcript", "").strip()
        audio_context = result.get("audio_context", "").strip()
        session_id = result.get("session_id", "default")
        client_id = self._active_voice_client.get(session_id)

        if not transcript or not client_id:
            self._logger.warning(f"[Voice] Empty transcript or unknown client for session {session_id}")
            # Return to idle
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(
                self._ws_manager.broadcast_to_session(session_id, {
                    "type": "listening_state", "payload": {"state": "idle"}
                }),
                loop
            )
            return

        loop = asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(
            self._process_voice_transcription(session_id, client_id, transcript, audio_context),
            loop
        )
    except Exception as e:
        self._logger.error(f"[Voice] _on_voice_result error: {e}", exc_info=True)
```

**Step 7: Add `_process_voice_transcription()` — the 4-pillar pipeline**

```python
async def _process_voice_transcription(
    self, session_id: str, client_id: str, transcript: str, audio_context: str
) -> None:
    """
    Full 4-pillar pipeline after LFM2-Audio transcription:
      Pillar 1 — ChatView: show user bubble (transcript) + assistant bubble (response)
      Pillar 2 — Agent: lfm2-8b reasons, lfm2.5 executes (model-agnostic)
      Pillar 3 — Tools: tool_bridge wired in process_text_message
      Pillar 4 — Memory: injected via _get_memory_context in plan_task
    """
    loop = asyncio.get_event_loop()
    try:
        # Pillar 1A: Send transcript as user bubble in ChatView
        await self._ws_manager.send_to_client(client_id, {
            "type": "text_response",
            "payload": {"text": transcript, "sender": "user"}
        })

        # Pillar 2+3+4: Route through AgentKernel
        # Build enriched message: transcript + what LFM2-Audio understood about the audio
        enriched = transcript
        if audio_context:
            enriched = f"{transcript}\n\n[Audio context: {audio_context}]"

        agent_kernel = get_agent_kernel(session_id)

        # Ensure tool bridge is wired (Pillar 3)
        if agent_kernel._tool_bridge is None:
            from .agent.tool_bridge import get_agent_tool_bridge
            agent_kernel._tool_bridge = get_agent_tool_bridge()

        # Run agent in executor (sync method)
        response = await loop.run_in_executor(
            None,
            agent_kernel.process_text_message,
            enriched,
            session_id
        )

        # Pillar 1B: Speaking state + send response to ChatView
        await self._ws_manager.broadcast_to_session(session_id, {
            "type": "listening_state",
            "payload": {"state": "speaking"}
        })
        await self._ws_manager.send_to_client(client_id, {
            "type": "text_response",
            "payload": {"text": response, "sender": "assistant"}
        })

        # Pillar 1C: TTS playback
        await loop.run_in_executor(None, self._speak_response, response)

        # Done
        await self._ws_manager.broadcast_to_session(session_id, {
            "type": "listening_state",
            "payload": {"state": "idle"}
        })

    except Exception as e:
        self._logger.error(f"[Voice] Pipeline error for session {session_id}: {e}", exc_info=True)
        await self._ws_manager.broadcast_to_session(session_id, {
            "type": "listening_state", "payload": {"state": "error"}
        })

def _speak_response(self, text: str) -> None:
    """TTS + audio playback via TTSManager. Sync — call via run_in_executor."""
    try:
        from .agent.tts import get_tts_manager
        from .audio.engine import get_audio_engine
        tts = get_tts_manager()
        audio_np = tts.synthesize(text)
        if audio_np is not None and len(audio_np) > 0:
            engine = get_audio_engine()
            if engine.pipeline:
                engine.pipeline.play_audio(audio_np)
    except Exception as e:
        self._logger.error(f"[Voice] TTS error: {e}")
```

**Step 8: Remove the now-dead methods**

Delete these methods entirely from `iris_gateway.py`:
- `_ensure_voice_audio_pipeline()`
- `_voice_frame_level_callback()`
- `_start_voice_recording()`
- `_stop_voice_recording()`
- `_audio_level_broadcast_loop()`
- `_process_voice_input()`
- `_transcribe_audio()`
- `_on_voice_state_change()` (orphaned callback)
- `_on_audio_level_update()` (orphaned callback)

**Step 9: Python syntax check**

```bash
python -m py_compile backend/iris_gateway.py && echo "OK"
```
Expected: `OK`

**Step 10: Commit**

```bash
git add backend/iris_gateway.py
git commit -m "refactor: remove conflicting AudioPipeline from iris_gateway, delegate to VoiceCommandHandler"
```

---

## Task 3: Wire iris_gateway to VoiceCommandHandler in main.py (P7)

**Files:**
- Modify: `backend/main.py`

**Step 1: After creating iris_gateway, call set_voice_handler**

Find this block in `lifespan()`:
```python
iris_gateway = get_iris_gateway()
app.state.iris_gateway = iris_gateway
```

Add immediately after:
```python
# Wire VoiceCommandHandler → iris_gateway for 4-pillar voice processing
iris_gateway.set_voice_handler(voice_handler)
logger.info("  - Voice handler wired to IRIS Gateway.")
```

**Step 2: Verify syntax**

```bash
python -m py_compile backend/main.py && echo "OK"
```

**Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: wire VoiceCommandHandler into iris_gateway on startup"
```

---

## Task 4: Fix ModelManager — Per-Session ChatState + Structured System Prompt (P3, P4, P13)

**Files:**
- Modify: `backend/audio/model_manager.py`

**Step 1: Change the structured system prompt**

Replace:
```python
self.system_prompt = "You are a helpful voice assistant. Respond naturally with audio."
```
With:
```python
self.system_prompt = (
    "You are an audio analysis assistant. When given audio input, respond in this EXACT format:\n"
    "[TRANSCRIPT]: <exact word-for-word transcription of what was spoken>\n"
    "[CONTEXT]: <one sentence about the speaker's tone, urgency, and intent>\n"
    "Output only these two lines. Do not add any other text."
)
```

**Step 2: Add per-session ChatState tracking**

Replace the single `self.chat_state = None` with a dict:
```python
# REMOVE:
self.chat_state = None
# ADD:
self._session_chat_states: dict = {}   # session_id -> ChatState
```

**Step 3: Add `_get_or_create_chat_state(session_id)`**

```python
def _get_or_create_chat_state(self, session_id: str = "default") -> "ChatState":
    """Get or create a per-session ChatState with the structured system prompt."""
    if session_id not in self._session_chat_states:
        cs = ChatState(self.processor)
        cs.new_turn("system")
        cs.add_text(self.system_prompt)
        cs.end_turn()
        self._session_chat_states[session_id] = cs
        print(f"[ModelManager] New ChatState created for session {session_id}")
    return self._session_chat_states[session_id]
```

**Step 4: Update `_process_native_audio_sync` signature and ChatState usage**

Change signature to accept session_id:
```python
def _process_native_audio_sync(
    self, audio_input: np.ndarray, sample_rate: int, session_id: str = "default"
) -> Tuple[Optional[np.ndarray], Optional[str]]:
```

Replace:
```python
# OLD: uses shared self.chat_state
if len(self.chat_state.conversation_history) > self._conversation_turns_limit * 2:
    self.chat_state.conversation_history = ...
self.chat_state.new_turn("user")
...
```
With:
```python
# NEW: per-session chat state
chat_state = self._get_or_create_chat_state(session_id)
if len(chat_state.conversation_history) > self._conversation_turns_limit * 2:
    # Preserve system prompt turn, drop oldest conversation turns
    system_turn = chat_state.conversation_history[:1]
    recent = chat_state.conversation_history[-(self._conversation_turns_limit * 2):]
    chat_state.conversation_history = system_turn + recent
chat_state.new_turn("user")
chat_state.add_audio(audio_tensor, sampling_rate=sample_rate)
chat_state.end_turn()
chat_state.new_turn("assistant")
audio_tokens, text_tokens = [], []
for token in self.model.generate_interleaved(**chat_state, max_new_tokens=512):
    if token.numel() > 1: audio_tokens.append(token)
    else: text_tokens.append(token)
chat_state.end_turn()
```

**Step 5: Update `process_native_audio_async` to accept and pass session_id**

```python
async def process_native_audio_async(
    self, audio_input: np.ndarray, sample_rate: int = 16000, session_id: str = "default"
) -> Tuple[Optional[np.ndarray], Optional[str]]:
    ...
    result = await loop.run_in_executor(
        self._thread_pool,
        self._process_native_audio_sync,
        audio_input,
        sample_rate,
        session_id      # <-- add this
    )
```

**Step 6: Add `reset_session(session_id)` for session cleanup**

```python
def reset_session(self, session_id: str) -> None:
    """Remove ChatState for a session (called on WebSocket disconnect)."""
    self._session_chat_states.pop(session_id, None)
    print(f"[ModelManager] ChatState removed for session {session_id}")
```

**Step 7: Increase max_new_tokens**

```python
self._max_tokens = 512  # was 256 — structured output needs room
```

**Step 8: Python syntax check**

```bash
python -m py_compile backend/audio/model_manager.py && echo "OK"
```

**Step 9: Commit**

```bash
git add backend/audio/model_manager.py
git commit -m "feat: per-session ChatState, structured transcription prompt, 512 max_new_tokens"
```

---

## Task 5: Fix VoiceCommandHandler — Parse LFM Text Output, Route to Callback (P2, P8, P10)

**Files:**
- Modify: `backend/audio/voice_command.py`

**Step 1: Add session/client tracking to VoiceCommandHandler**

In `__init__`, add:
```python
self._active_session_id: str = "default"   # set by iris_gateway before start_recording()
self._on_voice_transcription = None         # callback: (result_dict) -> None
```

**Step 2: Add `set_active_session()` and `set_command_result_callback()`**

```python
def set_active_session(self, session_id: str) -> None:
    """Set the session_id that owns the current recording."""
    self._active_session_id = session_id

def set_command_result_callback(self, callback) -> None:
    """Set callback fired when voice processing completes. Receives result dict."""
    self._on_command_result = callback
```

**Step 3: Update `_process_native_audio` to pass session_id**

```python
# In _process_native_audio, update the async call:
future = asyncio.run_coroutine_threadsafe(
    self.audio_engine.model_manager.process_native_audio_async(
        audio_tensor,
        sample_rate=self.sample_rate,
        session_id=self._active_session_id      # <-- add this
    ),
    self.audio_engine.get_main_loop()
)
```

**Step 4: Rewrite `_play_native_response` to parse and callback instead of playing audio**

```python
def _play_native_response(self, audio_response: np.ndarray, debug_text: Optional[str] = None):
    """
    Parse LFM2-Audio structured text output and fire result callback.
    Does NOT play audio directly — the 4-pillar pipeline handles TTS response.
    """
    transcript = ""
    audio_context = ""

    if debug_text:
        # Parse structured output from ModelManager:
        # [TRANSCRIPT]: <text>
        # [CONTEXT]: <text>
        for line in debug_text.splitlines():
            if line.startswith("[TRANSCRIPT]:"):
                transcript = line.replace("[TRANSCRIPT]:", "").strip()
            elif line.startswith("[CONTEXT]:"):
                audio_context = line.replace("[CONTEXT]:", "").strip()

        # Fallback: if model didn't follow format, use full text as transcript
        if not transcript and debug_text.strip():
            transcript = debug_text.strip()
            print(f"[VoiceCommand] Warning: LFM output not in expected format, using raw: '{transcript[:80]}'")

    result = {
        "type":          "voice_transcription",
        "transcript":    transcript,
        "audio_context": audio_context,
        "session_id":    self._active_session_id,
        "status":        "success" if transcript else "empty",
    }

    print(f"[VoiceCommand] Transcript: '{transcript[:80]}' | Context: '{audio_context[:60]}'")
    self._send_result(result)
    self._set_state(VoiceState.SUCCESS, "Transcription complete")
    self._reset_state()
```

**Step 5: Update iris_gateway._handle_voice() to call set_active_session before start_recording**

In `_handle_voice()` `voice_command_start` branch, add before `start_recording()`:
```python
if self._voice_handler:
    self._voice_handler.set_active_session(session_id)
    success = self._voice_handler.start_recording()
```

**Step 6: Python syntax check**

```bash
python -m py_compile backend/audio/voice_command.py && echo "OK"
```

**Step 7: Commit**

```bash
git add backend/audio/voice_command.py backend/iris_gateway.py
git commit -m "feat: VoiceCommandHandler parses LFM2-Audio structured output and routes to 4-pillar callback"
```

---

## Task 6: Fix AudioEngine Frame Callback — Replace LFM Streaming with Porcupine (P5, P6)

Currently `_process_audio_frame` sends EVERY 32ms audio frame to `lfm_audio_manager.process_audio_stream()` — this runs a full LFM inference pipeline on every frame, which is catastrophically expensive and never actually triggers the voice command flow correctly. Replace with lightweight Porcupine wake word detection.

**Files:**
- Modify: `backend/audio/engine.py`

**Step 1: Import Porcupine detector at top of engine.py**

```python
from backend.voice.porcupine_detector import PorcupineWakeWordDetector
```

**Step 2: Add Porcupine instance and wake callback to `__init__`**

```python
# In AudioEngine.__init__, add:
self._porcupine: Optional[PorcupineWakeWordDetector] = None
self._porcupine_initialized: bool = False
self._on_wake_word_detected = None   # callback: (wake_word_name: str) -> None
```

**Step 3: Add `initialize_porcupine()` method**

> ⚠️ **Amendment 1:** Wake phrase is NEVER hardcoded. Always read from `WakeConfig` singleton (user's chosen phrase from settings UI). `wake_config.get_wake_phrase()` returns the current selection; `wake_config.get_sensitivity()` returns the slider value (0–1 float).

```python
def initialize_porcupine(self, wake_phrase: Optional[str] = None, sensitivity: Optional[float] = None) -> bool:
    """
    Initialize Porcupine wake word detector using the user's chosen wake phrase.
    wake_phrase defaults to WakeConfig setting (set via Voice > Wake Word in UI).
    Called lazily — NOT at startup (avoids delay on low-spec PCs).
    """
    try:
        from backend.agent.wake_config import get_wake_config
        wake_config = get_wake_config()

        # Read from user settings if not overridden
        if wake_phrase is None:
            wake_phrase = wake_config.get_wake_phrase()   # e.g. "jarvis", "hey computer"
        if sensitivity is None:
            sensitivity = wake_config.get_sensitivity()   # float 0–1 from UI slider

        # Map user-friendly phrase to pvporcupine built-in keyword name
        keyword = wake_phrase.lower().replace(" ", "_")   # "hey computer" -> "hey_computer"

        self._porcupine = PorcupineWakeWordDetector(
            builtin_keywords=[keyword],
            sensitivities=[sensitivity]
        )
        self._porcupine_initialized = True
        logger.info(f"[AudioEngine] Porcupine initialized — listening for '{wake_phrase}' (sensitivity={sensitivity:.2f})")
        return True
    except Exception as e:
        logger.error(f"[AudioEngine] Porcupine init failed: {e}")
        self._porcupine_initialized = False
        return False

def reinitialize_porcupine(self) -> bool:
    """
    Reinitialize Porcupine after user changes wake phrase in settings.
    Called by WakeConfig.on_change_callback — registered in main.py.
    """
    if self._porcupine:
        self._porcupine.cleanup()
        self._porcupine = None
        self._porcupine_initialized = False
    return self.initialize_porcupine()   # reads fresh values from WakeConfig

def set_wake_word_callback(self, callback) -> None:
    """Set callback fired when wake word is detected. callback(wake_word_name: str) -> None"""
    self._on_wake_word_detected = callback
```

**Step 4: Rewrite `_process_audio_frame` — remove LFM streaming, add Porcupine**

```python
def _process_audio_frame(self, audio_frame: np.ndarray):
    """
    Process incoming audio frame.
    - Porcupine wake word detection (lightweight, <1ms per frame)
    - Notifies registered frame listeners (used by VoiceCommandHandler for buffering)
    No longer streams every frame to lfm_audio_manager.
    """
    try:
        # Wake word detection (only when Porcupine is initialized)
        if self._porcupine_initialized and self._porcupine:
            # Convert float32 [-1,1] → int16 PCM for Porcupine
            pcm_int16 = (np.clip(audio_frame, -1.0, 1.0) * 32767).astype(np.int16).tolist()
            frame_len = self._porcupine.frame_length
            # Process in Porcupine-sized chunks
            for i in range(0, len(pcm_int16) - frame_len + 1, frame_len):
                chunk = pcm_int16[i:i + frame_len]
                detected, word = self._porcupine.process_frame(chunk)
                if detected:
                    logger.info(f"[AudioEngine] Wake word detected: '{word}'")
                    if self._on_wake_word_detected:
                        self._on_wake_word_detected(word)

    except Exception as e:
        logger.error(f"[AudioEngine] Frame processing error: {e}")
```

**Step 5: Remove the old LFM-related callbacks from AudioEngine** (`_handle_lfm_status_change`, `_handle_lfm_transcription`, `_handle_lfm_audio_response`, `_return_to_listening_after_audio`) — these were callbacks for the "send every frame to LFM" approach which is now gone.

**Step 6: Remove `self.lfm_audio_manager` from AudioEngine** — it's no longer needed in the engine since we're not streaming frames to it. The ModelManager (via VoiceCommandHandler) handles LFM calls directly.

```python
# In __init__, REMOVE:
from backend.agent import get_lfm_audio_manager
self.lfm_audio_manager = get_lfm_audio_manager()
```

**Step 7: Add `get_main_loop()` if missing** (used by VoiceCommandHandler):

```python
def get_main_loop(self) -> Optional[asyncio.AbstractEventLoop]:
    """Return the main event loop stored during initialization."""
    return self._main_loop
```

**Step 8: Python syntax check**

```bash
python -m py_compile backend/audio/engine.py && echo "OK"
```

**Step 9: Commit**

```bash
git add backend/audio/engine.py
git commit -m "refactor: replace LFM frame streaming with Porcupine wake word detection in AudioEngine"
```

---

## Task 7: Wire Wake Word → iris_gateway Voice Flow in main.py (P6, P12)

**Files:**
- Modify: `backend/main.py`

**Step 1: After wiring voice_handler to iris_gateway, wire wake word callback**

> ⚠️ **Amendment 1 (continued):** Wake phrase comes from `get_wake_config()`, never hardcoded. Also register `reinitialize_porcupine` as WakeConfig's change callback so the user changing their wake word in settings instantly updates Porcupine without restarting the backend.

```python
# After iris_gateway.set_voice_handler(voice_handler):

# Wire Porcupine wake word → auto-trigger voice command
async def on_wake_word(wake_word_name: str):
    """
    Called from AudioEngine when Porcupine detects the wake word.
    Simulates a voice_command_start on the most-recently-active session.
    """
    try:
        ws_manager = get_websocket_manager()
        # Broadcast to ALL sessions — the user can only be in one session
        active_sessions = ws_manager.get_active_session_ids()
        if not active_sessions:
            logger.warning("[WakeWord] Wake word detected but no active sessions")
            return
        # Use first active session (or implement last-active tracking for multi-session)
        session_id = active_sessions[0]
        client_ids = ws_manager.get_clients_for_session(session_id)
        client_id = client_ids[0] if client_ids else None
        if client_id:
            logger.info(f"[WakeWord] '{wake_word_name}' → triggering voice for session {session_id}")
            await iris_gateway._handle_voice(
                session_id, client_id,
                {"type": "voice_command_start"}
            )
    except Exception as e:
        logger.error(f"[WakeWord] Error routing wake word: {e}")

# Register wake word callback on AudioEngine
audio_engine.set_wake_word_callback(
    lambda word: asyncio.run_coroutine_threadsafe(
        on_wake_word(word),
        asyncio.get_event_loop()
    )
)

# Initialize Porcupine from user's WakeConfig setting (Amendment 1: NOT hardcoded)
# get_wake_config().get_wake_phrase() returns user's chosen phrase from Voice > Wake Word UI
audio_engine.initialize_porcupine()   # reads phrase + sensitivity from WakeConfig

# Register live-update callback: when user changes wake word in settings, reinit Porcupine instantly
from backend.agent.wake_config import get_wake_config
get_wake_config().register_change_callback(audio_engine.reinitialize_porcupine)
logger.info("  - Porcupine live wake-word updates registered")

# Start the AudioEngine so Porcupine frame detection runs
if not audio_engine.start():
    logger.warning("  - AudioEngine failed to start (mic may be unavailable)")
else:
    logger.info("  - AudioEngine started — Porcupine wake word detection active")
```

**Step 2a: Check `WakeConfig` has `register_change_callback()`**

Run:
```bash
grep -n "register_change_callback\|_change_callbacks" backend/agent/wake_config.py
```

If missing, add to `WakeConfig` class:
```python
def __init__(self):
    ...
    self._change_callbacks = []   # list of callables to fire when config changes

def register_change_callback(self, callback) -> None:
    """Register a callback to fire when wake phrase or sensitivity changes."""
    if callback not in self._change_callbacks:
        self._change_callbacks.append(callback)

def update_config(self, **kwargs):
    # ... existing update logic ...
    # After updating, fire all registered callbacks
    for cb in self._change_callbacks:
        try:
            cb()
        except Exception as e:
            logger.warning(f"[WakeConfig] Change callback error: {e}")
```

**Step 2b: Check ws_manager has `get_active_session_ids()` and `get_clients_for_session()`**

Run:
```bash
grep -n "get_active_session_ids\|get_clients_for_session" backend/ws_manager.py
```

If missing, add them to `WebSocketManager`:
```python
def get_active_session_ids(self) -> list:
    """Return list of session IDs with at least one connected client."""
    return list(self._session_clients.keys())

def get_clients_for_session(self, session_id: str) -> list:
    """Return list of client_ids in a session."""
    return list(self._session_clients.get(session_id, {}).keys())
```

**Step 3: Verify syntax**

```bash
python -m py_compile backend/main.py && echo "OK"
python -m py_compile backend/ws_manager.py && echo "OK"
```

**Step 4: Commit**

```bash
git add backend/main.py backend/ws_manager.py
git commit -m "feat: wire Porcupine wake word detection to auto-trigger voice pipeline via iris_gateway"
```

---

## Task 8: Fix Audio Playback Sample Rate Mismatch (P8)

LFM2-Audio outputs 24kHz waveform. `AudioPipeline` runs at 16kHz. Resampling is required.

**Files:**
- Modify: `backend/audio/model_manager.py`

**Step 1: Add resampling to `_process_native_audio_sync` before returning**

After `waveform = self.processor.decode(...)`:
```python
# Resample from LFM2-Audio output rate (24kHz) to AudioPipeline rate (16kHz)
import torchaudio
waveform_tensor = torch.from_numpy(waveform).float()
if waveform_tensor.dim() == 1:
    waveform_tensor = waveform_tensor.unsqueeze(0)
waveform_resampled = torchaudio.functional.resample(waveform_tensor, orig_freq=24000, new_freq=16000)
waveform = waveform_resampled.cpu().numpy()
```

Note: This fixes the existing `_play_native_response` audio-speed bug even for any remaining direct playback paths.

**Step 2: Verify syntax**

```bash
python -m py_compile backend/audio/model_manager.py && echo "OK"
```

**Step 3: Commit**

```bash
git add backend/audio/model_manager.py
git commit -m "fix: resample LFM2-Audio 24kHz output to 16kHz for AudioPipeline playback"
```

---

## Task 9: Fix VAD Auto-Stop for Wake Word Mode (P12)

When wake word triggers recording (no user double-click to end it), VAD must auto-stop after sustained silence. Currently VoiceCommandHandler just logs a warning and keeps recording.

**Files:**
- Modify: `backend/audio/voice_command.py`

**Step 1: Add `_auto_stop_mode` flag to `__init__`**

```python
self._auto_stop_mode: bool = False   # True when triggered by wake word (not double-click)
```

**Step 2: Add `start_recording(auto_stop=False)` parameter**

```python
def start_recording(self, auto_stop: bool = False) -> bool:
    self._auto_stop_mode = auto_stop
    # ... rest of existing method unchanged ...
```

**Step 3: Update `_capture_frame` to auto-stop when VAD detects sustained silence in wake-word mode**

In the `if self.speech_started:` block where silence is counted:
```python
if self.silence_counter >= self.silence_threshold:
    if self._auto_stop_mode:
        # Wake word mode: auto-stop on sustained silence
        print("[VoiceCommand] Auto-stopping on silence (wake word mode)")
        self._overflow_stop_requested = True   # triggers stop_recording on next frame
    else:
        print(f"[VoiceCommand] Speech paused, waiting for user to stop")
```

**Step 4: Update wake word handler in main.py to pass `auto_stop=True`**

```python
# In the voice_handler.start_recording() call inside _handle_voice when triggered by wake word:
# Pass auto_stop via the session message or via a flag set before calling
```

Simplest approach: set a flag in VoiceCommandHandler before start_recording:
```python
# In on_wake_word callback in main.py:
voice_handler.set_active_session(session_id)
voice_handler.start_recording(auto_stop=True)   # auto_stop for wake word mode
```

But `_handle_voice` currently calls `voice_handler.start_recording()` — add an `auto_stop` kwarg to `_handle_voice`:
```python
async def _handle_voice(self, session_id: str, client_id: str, message: dict, auto_stop: bool = False):
    ...
    success = self._voice_handler.start_recording(auto_stop=auto_stop)
```

And in on_wake_word:
```python
await iris_gateway._handle_voice(
    session_id, client_id,
    {"type": "voice_command_start"},
    auto_stop=True
)
```

**Step 5: Python syntax check**

```bash
python -m py_compile backend/audio/voice_command.py && echo "OK"
python -m py_compile backend/iris_gateway.py && echo "OK"
```

**Step 6: Commit**

```bash
git add backend/audio/voice_command.py backend/iris_gateway.py
git commit -m "feat: auto-stop recording after silence when triggered by wake word"
```

---

## Task 10: Clean Up lfm_audio_manager.py (P9)

`lfm_audio_manager.py` duplicates Whisper, SpeechT5, and LFM model loading alongside `ModelManager`. Since `ModelManager` handles LFM2-Audio correctly and AudioEngine no longer streams frames to lfm_audio_manager, the Whisper/SpeechT5/LFM loading in lfm_audio_manager is dead weight.

**Files:**
- Modify: `backend/agent/lfm_audio_manager.py`
- Modify: `backend/main.py` (remove `audio_engine.lfm_audio_manager.initialize()` background call)

**Step 1: Gut lfm_audio_manager.py — keep only wake config and Porcupine**

The file shrinks to just wake word config management (Porcupine is now owned by AudioEngine, but the config logic is still useful):

```python
"""
LFMAudioManager — Wake word configuration adapter.
Audio processing (LFM2-Audio) is handled by backend/audio/model_manager.py.
Porcupine detection is handled by backend/audio/engine.py.
This class now only holds wake phrase / TTS voice configuration state.
"""
import logging
from typing import Any, Dict, Optional
from backend.voice.porcupine_detector import PorcupineWakeWordDetector

logger = logging.getLogger(__name__)


class LFMAudioManager:
    """
    Lightweight configuration holder for voice/wake settings.
    Previously handled LFM model loading — now delegated to ModelManager.
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.wake_phrase = config.get("wake_phrase", "jarvis")
        self.detection_sensitivity = config.get("detection_sensitivity", 50)
        self.tts_voice = config.get("tts_voice", "Nova")
        self.speaking_rate = config.get("speaking_rate", 1.0)
        self.is_initialized = True   # No longer needs heavy initialization
        self.callbacks = {}

    def set_callbacks(self, **kwargs):
        self.callbacks.update({k: v for k, v in kwargs.items() if v})

    def update_wake_config(self, wake_phrase=None, detection_sensitivity=None, activation_sound=None):
        if wake_phrase is not None:
            self.wake_phrase = wake_phrase
        if detection_sensitivity is not None:
            self.detection_sensitivity = detection_sensitivity

    def update_voice_config(self, tts_voice=None, speaking_rate=None):
        if tts_voice is not None:
            self.tts_voice = tts_voice
        if speaking_rate is not None:
            self.speaking_rate = speaking_rate

    async def initialize(self):
        """No-op — model loading delegated to ModelManager (lazy, on first voice command)."""
        logger.info("[LFMAudioManager] Lightweight config-only mode. LFM model loaded on first voice use.")

    async def cleanup(self):
        pass


_lfm_audio_manager_instance = None

def get_lfm_audio_manager() -> "LFMAudioManager":
    global _lfm_audio_manager_instance
    if _lfm_audio_manager_instance is None:
        _lfm_audio_manager_instance = LFMAudioManager({})
    return _lfm_audio_manager_instance
```

**Step 2: Remove the background model initialization in main.py**

Find:
```python
async def initialize_models_in_background():
    audio_engine = get_audio_engine()
    await audio_engine.lfm_audio_manager.initialize()
```

Since `lfm_audio_manager.initialize()` is now a no-op, and `ModelManager` loads lazily on first voice command, this background task can be removed entirely. Delete `initialize_models_in_background()` and any call to `asyncio.create_task(initialize_models_in_background())` if it exists.

**Step 3: Python syntax checks**

```bash
python -m py_compile backend/agent/lfm_audio_manager.py && echo "OK"
python -m py_compile backend/main.py && echo "OK"
```

**Step 4: Commit**

```bash
git add backend/agent/lfm_audio_manager.py backend/main.py
git commit -m "refactor: strip lfm_audio_manager to config-only, remove duplicate model loading"
```

---

## Task 11: Delete OpenWakeWord (backend/audio/wake_word.py)

User confirmed: Porcupine only. OpenWakeWord file is dead.

**Files:**
- Delete: `backend/audio/wake_word.py`
- Modify: `backend/audio/__init__.py` (remove exports if present)

**Step 1: Check for any imports of wake_word.py**

```bash
grep -rn "from .wake_word\|from backend.audio.wake_word\|import wake_word" backend/ --include="*.py"
```

**Step 2: Remove any imports found, then delete the file**

```bash
rm backend/audio/wake_word.py
```

**Step 3: Verify no broken imports**

```bash
python -c "from backend.audio import get_audio_engine; print('OK')"
```

**Step 4: Commit**

```bash
git add -A
git commit -m "remove: delete OpenWakeWord (backend/audio/wake_word.py) — Porcupine only"
```

---

## Task 12: Session Cleanup — Reset ModelManager ChatState on Disconnect

When a WebSocket disconnects, clear the per-session ChatState so memory doesn't accumulate.

**Files:**
- Modify: `backend/iris_gateway.py` — `cleanup_session()`

**Step 1: Update `cleanup_session()`**

```python
async def cleanup_session(self, session_id: str) -> None:
    try:
        self._logger.info(f"[Session: {session_id}] Cleaning up session resources")

        # Cancel any audio level broadcast tasks
        task = self._audio_level_tasks.pop(session_id, None) if hasattr(self, '_audio_level_tasks') else None
        if task:
            task.cancel()

        # Remove active voice client tracking
        self._active_voice_client.pop(session_id, None)

        # Reset per-session LFM ChatState
        try:
            from .audio.engine import get_audio_engine
            engine = get_audio_engine()
            if engine.model_manager and engine.model_manager.is_loaded:
                engine.model_manager.reset_session(session_id)
        except Exception:
            pass

        self._logger.info(f"[Session: {session_id}] Session cleanup completed")

    except Exception as e:
        self._logger.error(f"[Session: {session_id}] Error during cleanup: {e}", exc_info=True)
```

**Step 2: Verify syntax**

```bash
python -m py_compile backend/iris_gateway.py && echo "OK"
```

**Step 3: Commit**

```bash
git add backend/iris_gateway.py
git commit -m "feat: reset per-session LFM ChatState on WebSocket disconnect"
```

---

## Task 13: End-to-End Verification

These steps PROVE the entire flow works before claiming completion. Do not skip any.

### 13A: Python Syntax — All Modified Files

```bash
cd IRISVOICE
python -m py_compile backend/iris_gateway.py && echo "iris_gateway OK"
python -m py_compile backend/main.py && echo "main OK"
python -m py_compile backend/audio/engine.py && echo "engine OK"
python -m py_compile backend/audio/voice_command.py && echo "voice_command OK"
python -m py_compile backend/audio/model_manager.py && echo "model_manager OK"
python -m py_compile backend/agent/lfm_audio_manager.py && echo "lfm_audio_manager OK"
python -m py_compile backend/ws_manager.py && echo "ws_manager OK"
```

All must print `OK`. Fix any errors before continuing.

### 13B: TypeScript Compilation

```bash
cd IRISVOICE && npx tsc --noEmit 2>&1 | head -30
```

Expected: 0 errors. Fix any TypeScript errors (voice flow changes are backend-only, frontend should be clean from previous session).

### 13C: Backend Startup Check

```bash
cd IRISVOICE && uvicorn backend.main:app --host 0.0.0.0 --port 8000 --log-level info 2>&1 | head -40
```

Check the startup log for:
- ✅ `Audio engine created (models NOT loaded - lazy initialization active)`
- ✅ `Voice handler wired to IRIS Gateway`
- ✅ `Porcupine wake word detection active` OR Porcupine init warning (acceptable if pvporcupine not found)
- ✅ `IRIS Backend startup completed successfully!`
- ❌ No `ImportError`, `AttributeError`, or `RuntimeError`

### 13D: Double-Click Voice Flow Test

1. Start backend + frontend (`npm run dev`)
2. Open browser DevTools console
3. Double-click IrisOrb (or WheelView center)
4. Verify in backend logs: `[Session: ...] Voice command start` + `Recording started`
5. Say a sentence clearly
6. Double-click again to end
7. Verify in backend logs: `[ModelManager] ...` inference running
8. Verify in frontend: user bubble appears in ChatView with your words
9. Verify in frontend: assistant bubble appears with agent response
10. Verify you hear TTS audio playback
11. Verify IrisOrb returns to idle animation

### 13E: Wake Word Flow Test

1. Backend running, frontend open
2. Say "Jarvis" clearly
3. Verify in backend logs: `[AudioEngine] Wake word detected: 'jarvis'`
4. Verify IrisOrb transitions to listening animation
5. Say a sentence
6. Wait ~1.5s of silence
7. Verify recording auto-stops (VAD, `auto_stop=True` mode)
8. Verify same ChatView + TTS flow as double-click

### 13F: Memory Persistence Test (Pillar 4)

1. Complete one voice exchange: say "My name is [name]"
2. Complete a second voice exchange: say "What is my name?"
3. Verify agent's response references the name from the first exchange
4. This proves ChatState (conversation memory) AND AgentKernel memory (episodic) both work

### 13G: Tool Call Test (Pillar 3)

1. Via voice: say "What time is it?" or "Open Notepad" or another tool-triggerable phrase
2. Verify in backend logs: `[AgentKernel]` tool call executed
3. Verify response reflects the tool result

### 13H: Concurrent Session Safety

1. Open two browser tabs (two WebSocket sessions)
2. Double-click IrisOrb in tab 1
3. Verify tab 2 does NOT get the voice command or its response
4. Verify tab 1 gets user + assistant bubbles correctly

---

---

## Amendment 2: Low-Spec PC Performance Strategy

> **Context:** LFM2.5-Audio-1.5B requires ~3–4GB VRAM (GPU) or ~6–8GB RAM (CPU inference). On a budget PC (8GB total RAM, integrated GPU), loading the model can crash or freeze the OS. The following guards prevent this.

### P14: No RAM/VRAM Guard Before LFM Model Load

**Problem:** `ModelManager.load_model()` loads a 1.5B parameter model without checking if the system has enough memory. On a low-spec PC this causes the OS to page-thrash or OOM-kill the process.

**Fix — Add in `ModelManager.load_model()` before loading:**

```python
def _check_system_resources(self) -> dict:
    """Check available RAM and VRAM before loading model."""
    import psutil
    result = {"ram_gb": 0.0, "vram_gb": 0.0, "sufficient": False}
    try:
        vm = psutil.virtual_memory()
        result["ram_gb"] = vm.available / (1024 ** 3)
    except Exception:
        result["ram_gb"] = 4.0  # assume enough if psutil fails

    if torch.cuda.is_available():
        try:
            props = torch.cuda.get_device_properties(0)
            total_vram = props.total_memory / (1024 ** 3)
            reserved = torch.cuda.memory_reserved(0) / (1024 ** 3)
            result["vram_gb"] = total_vram - reserved
        except Exception:
            pass

    # LFM2.5-Audio-1.5B needs ~4GB RAM (CPU) or ~3GB VRAM (GPU)
    if torch.cuda.is_available():
        result["sufficient"] = result["vram_gb"] >= 3.0
    else:
        result["sufficient"] = result["ram_gb"] >= 4.0

    return result

def load_model(self) -> bool:
    # ADD at the top of load_model():
    resources = self._check_system_resources()
    if not resources["sufficient"]:
        if torch.cuda.is_available():
            print(f"[ModelManager] Insufficient VRAM ({resources['vram_gb']:.1f}GB free, need 3GB). Cannot load LFM2-Audio.")
        else:
            print(f"[ModelManager] Insufficient RAM ({resources['ram_gb']:.1f}GB free, need 4GB). Cannot load LFM2-Audio.")
        return False
    # ... rest of existing load_model() unchanged ...
```

**Add `psutil` install note to Task 4 (if not already in requirements.txt):**

```bash
pip install psutil
grep -q "psutil" requirements.txt || echo "psutil" >> requirements.txt
```

### P15: LFM Model Always Loads GPU — No CPU Fallback Path

**Problem:** `device = "cuda" if torch.cuda.is_available() else "cpu"`. On integrated graphics with 1–2GB shared VRAM, CUDA is available but the model OOM-crashes. The fix allows graceful CPU fallback.

**Fix — In `ModelManager.load_model()`:**

```python
device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.float16 if device == "cuda" else torch.float32

# CPU-only override for low-spec: if VRAM < 3GB but CUDA available, use CPU
if device == "cuda" and resources.get("vram_gb", 0) < 3.0:
    print("[ModelManager] Low VRAM detected — using CPU inference (slower but safe)")
    device = "cpu"
    dtype = torch.float32
```

### P16: No Lazy Load Guard on Voice Command

**Problem:** First voice command after app start triggers `ModelManager.load_model()` inline. On a slow CPU this takes 30–90 seconds, freezing the audio pipeline.

**Fix — `VoiceCommandHandler._process_native_audio()` should warn the user before loading:**

```python
# In _process_native_audio, before calling model_manager.process_native_audio_async():
if not self.audio_engine.model_manager.is_loaded:
    # Broadcast a "loading model" state so UI shows a spinner
    asyncio.run_coroutine_threadsafe(
        ws_manager.broadcast({
            "type": "listening_state",
            "payload": {"state": "processing_conversation", "detail": "Loading voice model for first use..."}
        }),
        self.audio_engine.get_main_loop()
    )
    # load_model() will run in the thread pool (via process_native_audio_async's executor)
    # No change needed — the executor handles the sync load
```

### Performance Summary by PC Tier

| Tier | RAM | GPU | Expected behavior |
|------|-----|-----|------------------|
| High-spec | 16GB+ | 6GB+ VRAM | GPU inference, ~2–4s per voice turn |
| Mid-spec | 16GB | Integrated | CPU inference, ~8–15s per voice turn |
| Low-spec | 8GB | Integrated | Load guard warns user, falls back gracefully |
| Minimum | <6GB free | None | `load_model()` returns False, logs clear error |

**Add these tasks to Task 4 (ModelManager fixes) in the implementation:**

- Add `_check_system_resources()` method
- Add VRAM-aware CPU fallback in `load_model()`
- Add psutil to requirements.txt

---

## Task 14: Fix Agent Tool Calling — Critical Bugs vs Anthropic Standards

> **Evaluation Result:** The current AgentKernel tool calling system has **4 critical bugs** that prevent tools from executing correctly. These are NOT about format (the custom JSON plan format is acceptable for local models that don't support Anthropic's `tool_use` blocks). The bugs are runtime errors that silently swallow tool calls.

### Findings: Current Architecture vs Anthropic Standards

| Criterion | Anthropic Standard | IRISVOICE Current | Status |
|-----------|-------------------|-------------------|--------|
| Tool definition format | `tools` list with `input_schema` | `get_available_tools()` returns custom dict | ✅ Acceptable for local models |
| Model selects tool | Model returns `tool_use` block | Kernel parses JSON plan from model | ✅ Acceptable — local models don't support `tool_use` |
| Tool execution | App executes tool, sends `tool_result` back | `tool_bridge.execute_tool()` called | ❌ Bug: never awaited |
| Model sees result | Via `tool_result` message | Via `_synthesize_response()` | ✅ Good — brain sees results |
| Parallel tool calls | Supported | Sequential only | ⚠️ Not a bug, limitation |
| Error handling | Tool errors in `tool_result` | Dict with `"error"` key | ✅ Acceptable |

### Critical Bug 1: `execute_tool()` Called Without `await` — Tools Never Execute

**File:** `backend/agent/agent_kernel.py:883`

**Problem:** `execute_tool()` is `async def`, but `execute_step()` calls it without `await`:
```python
# BROKEN — execute_tool is a coroutine, calling without await returns a coroutine object
tool_result = self._tool_bridge.execute_tool(tool_name, parameters)
```
The tool never actually runs. `tool_result` is just an unawaited coroutine object, not a result dict. The check `if "error" in tool_result` then silently passes because coroutines don't raise `TypeError` on `in` checks.

**Fix:** `execute_step()` must be `async def` and must `await` the tool call.

**File:** `backend/agent/agent_kernel.py`

**Step 1: Change `execute_step` to async**

```python
# CHANGE:
def execute_step(self, step: dict, task: TaskContext, timeout_seconds: float = 30.0) -> dict:
# TO:
async def execute_step(self, step: dict, task: TaskContext, timeout_seconds: float = 30.0) -> dict:
```

**Step 2: Add `await` to the tool call (line ~883)**

```python
# CHANGE:
tool_result = self._tool_bridge.execute_tool(tool_name, parameters)
# TO:
tool_result = await self._tool_bridge.execute_tool(tool_name, parameters)
```

### Critical Bug 2: `execute_plan()` Must Be Async To Await `execute_step()`

**File:** `backend/agent/agent_kernel.py`

`execute_plan()` calls `execute_step()` — it must also be async:

```python
# CHANGE:
def execute_plan(self, plan: dict, task: TaskContext, ...) -> list:
# TO:
async def execute_plan(self, plan: dict, task: TaskContext, ...) -> list:

# AND update the call inside:
result = await self.execute_step(step, task, ...)
```

### Critical Bug 3: `process_text_message()` Cannot `await` Async Methods — Must Use `asyncio.run()`

**File:** `backend/agent/agent_kernel.py` — `process_text_message()`

`process_text_message` is sync (called via `run_in_executor` from iris_gateway). It calls `execute_plan()` which is now async. Fix with `asyncio.run()`:

```python
# In process_text_message, replace:
execution_results = self.execute_plan(plan, task)
# WITH:
execution_results = asyncio.run(self.execute_plan(plan, task))
```

Note: This is safe because `process_text_message` runs in a thread pool executor (not the main async loop), so `asyncio.run()` creates a new event loop for the thread.

### Critical Bug 4: VPS Gateway Always Falls Back — `plan_task()` Always Uses Local Model

**File:** `backend/agent/agent_kernel.py:587-591`

```python
try:
    loop = asyncio.get_running_loop()
    # We're in an async context, cannot use run_until_complete
    logger.warning("[AgentKernel] Cannot use VPS Gateway in sync method from async context...")
    plan_response = None  # <-- always falls back to local model!
```

**Fix:** Since `process_text_message` runs in a thread (no running loop), change to:

```python
# In plan_task() VPS gateway section:
try:
    plan_response = asyncio.run(
        self._vps_gateway.infer(
            model=self._model_router.get_reasoning_model_id() or "lfm2-8b",  # not hardcoded
            prompt=planning_prompt,
            context={"conversation_history": context} if context else {},
            params={"max_tokens": 1024, "temperature": 0.7},
            session_id=self.session_id
        )
    )
except RuntimeError as e:
    if "already running" in str(e):
        logger.warning("[AgentKernel] Event loop conflict — falling back to local model")
        plan_response = None
    else:
        raise
```

Also fix the hardcoded model names — add `get_reasoning_model_id()` and `get_execution_model_id()` to ModelRouter:

```python
# In ModelRouter (backend/agent/model_router.py):
def get_reasoning_model_id(self) -> Optional[str]:
    """Return the ID string of the current reasoning model."""
    return self._selected_reasoning_model or (list(self.models.keys())[0] if self.models else None)

def get_execution_model_id(self) -> Optional[str]:
    """Return the ID string of the current execution model."""
    return self._selected_execution_model or (list(self.models.keys())[-1] if self.models else None)
```

Then replace in agent_kernel.py:
```python
# REPLACE:
model="lfm2-8b"         # line 596
model="lfm2.5-1.2b-instruct"   # line 804
# WITH:
model=self._model_router.get_reasoning_model_id() or "lfm2-8b"
model=self._model_router.get_execution_model_id() or "lfm2.5-1.2b-instruct"
```

### Implementation Steps

**Files to modify:**
- `backend/agent/agent_kernel.py` — Bugs 1, 2, 3, 4
- `backend/agent/model_router.py` — Bug 4 (add model ID getters)

**Step 1: Make `execute_step` async and add await**

```bash
# After editing:
python -m py_compile backend/agent/agent_kernel.py && echo "OK"
```

**Step 2: Make `execute_plan` async and add await to execute_step call**

```bash
python -m py_compile backend/agent/agent_kernel.py && echo "OK"
```

**Step 3: Fix `process_text_message` to use `asyncio.run(execute_plan(...))`**

```bash
python -m py_compile backend/agent/agent_kernel.py && echo "OK"
```

**Step 4: Fix VPS gateway async context detection + replace hardcoded model names**

```bash
python -m py_compile backend/agent/agent_kernel.py && echo "OK"
python -m py_compile backend/agent/model_router.py && echo "OK"
```

**Step 5: Commit**

```bash
git add backend/agent/agent_kernel.py backend/agent/model_router.py
git commit -m "fix: make execute_step/execute_plan async, await tool calls, fix VPS gateway async detection"
```

**Step 6: Verify Tool Call Test (adds to Task 13G)**

After this fix, re-run the tool call test:
1. Via voice or text: "What files are in my Downloads folder?"
2. Backend log must show: `[AgentToolBridge] MCP Servers` called + result
3. Verify response includes actual file names (not placeholder text)

---

## Rollback Notes

If any task breaks the backend startup:
```bash
git log --oneline -15   # find the last good commit
git revert HEAD          # revert the last commit safely (creates new commit)
```

Never use `git reset --hard` — always revert to preserve history.

---

## Files Changed Summary

| File | Change Type | Purpose |
|------|------------|---------|
| `backend/iris_gateway.py` | Rewrite voice methods | Remove conflicting AudioPipeline, add delegation + 4-pillar pipeline |
| `backend/main.py` | Add wiring | Set voice_handler + wake word callback (dynamic from WakeConfig) + AudioEngine.start() |
| `backend/audio/engine.py` | Rewrite frame callback | Replace LFM streaming with Porcupine; dynamic wake phrase from WakeConfig; `reinitialize_porcupine()` for live updates |
| `backend/audio/voice_command.py` | Rewrite response handler | Parse LFM structured output, route to callback |
| `backend/audio/model_manager.py` | Update session + prompt | Per-session ChatState, structured transcription prompt, resample, RAM/VRAM guard |
| `backend/agent/lfm_audio_manager.py` | Strip to config-only | Remove duplicate Whisper/SpeechT5/LFM loading |
| `backend/agent/wake_config.py` | Add callback support | `register_change_callback()` for live wake-word updates |
| `backend/agent/agent_kernel.py` | Fix async tool calling | Make `execute_step`/`execute_plan` async, await tool bridge, fix VPS gateway |
| `backend/agent/model_router.py` | Add ID getters | `get_reasoning_model_id()`, `get_execution_model_id()` — remove hardcoded names |
| `backend/ws_manager.py` | Add 2 methods | `get_active_session_ids()`, `get_clients_for_session()` |
| `backend/audio/wake_word.py` | **DELETE** | OpenWakeWord replaced by Porcupine |
| `requirements.txt` | Add psutil | RAM/VRAM guard for low-spec PC detection |

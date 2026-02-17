# Phase 1 Testing Guide - LFM2-Audio Native Pipeline

## 🎯 Native Audio Architecture

Phase 1 now implements **Native End-to-End Audio** processing using LFM2-Audio-1.5B:

**NEW FLOW:** Wake Word → Double Click → [LFM2-Audio Native Audio] → Audio Output

**REMOVED:** STT → LLM → TTS pipeline (text conversion eliminated)

**KEY FEATURES:**
- Raw audio input (16kHz) → Raw audio output (24kHz)
- Conversation memory via ChatState
- No text conversion in pipeline
- LiquidAI LFM2-Audio-1.5B model

---

## Testing Order

Follow these tests in order to verify Phase 1 is working correctly.

---

## 1. Prerequisites Check

### Install Dependencies
```bash
cd IRISVOICE

# Python dependencies (Native Audio)
pip install liquid-audio torch torchaudio sounddevice numpy

# Wake word detection
pip install pvporcupine pyaudio

# Node dependencies (choose one)
npm install
# OR
pnpm install
```

### Verify Audio Devices
```bash
python check_devices.py
```

**Expected Output:**
- List of input devices (microphones)
- List of output devices (speakers)
- No errors

---

## 2. Backend Tests

### Test 2.1: Audio Pipeline
```bash
python test_audio_pipeline.py
```

**What to look for:**
- ✅ Audio devices listed
- ✅ Audio capture starts
- ✅ Audio frames captured
- ✅ No errors

**If it fails:**
- Check microphone permissions
- Try different audio device
- Check `requirements.txt` installed

---

### Test 2.2: LFM2-Audio Model
```bash
python test_lfm2_audio.py
```

**What to look for:**
- ✅ LFM2-Audio model loading (may take time on first run)
- ✅ ChatState initialized with system prompt
- ✅ Audio tensor processing works
- ✅ Native audio generation works

**If it fails:**
- Check internet connection (model download ~3GB)
- Check disk space (models are large)
- Wait for model download to complete
- Check CUDA memory if using GPU

---

### Test 2.3: Start Backend Server
```bash
python backend/main.py
```

**Expected Console Output:**
```
[OK] Initializing Voice Command Handler...
[OK] Voice Command Handler initialized
[OK] Backend ready signal sent
[OK] Audio Engine is now LISTENING
╔══════════════════════════════════════════╗
║            IRIS Backend Server           ║
╠══════════════════════════════════════════╣
║  WebSocket: ws://127.0.0.1:8000/ws/iris  ║
║  HTTP API:  http://127.0.0.1:8000/       ║
╚══════════════════════════════════════════╝
```

**What to look for:**
- ✅ No errors during startup
- ✅ Voice Command Handler initialized
- ✅ Audio Engine listening
- ✅ Server running on port 8000

**If it fails:**
- Check port 8000 is not in use
- Check all dependencies installed
- Check audio devices available

**Keep this terminal open** - you'll need to watch the console output during frontend tests.

---

## 3. Frontend Tests

### Test 3.1: Start Frontend
Open a **new terminal** (keep backend running):

```bash
cd IRISVOICE

# Start frontend (choose one)
npm run dev
# OR
pnpm dev
```

**Expected Output:**
```
> next dev
ready - started server on 0.0.0.0:3000, url: http://localhost:3000
```

Open browser to: **http://localhost:3000**

---

### Test 3.2: WebSocket Connection
1. Open browser to `http://localhost:3000`
2. Open browser console (F12 → Console tab)

**What to look for in console:**
- ✅ `WebSocket connected` or similar message
- ✅ `Initial state received` or similar
- ✅ No connection errors
- ✅ No red error messages

**What to look for in backend console:**
- ✅ `New WebSocket connection: <client_id>`
- ✅ `Sending initial state to <client_id>`

**If it fails:**
- Check backend is running
- Check no CORS errors in browser console
- Check WebSocket URL is correct
- Try refreshing the page

---

### Test 3.3: Orb Click-and-Hold (MAIN TEST)

This is the **primary test** for Phase 1 functionality.

**Steps:**
1. Navigate to IRIS interface (should see orbit nodes)
2. Find any orbit node
3. **Click and HOLD** for at least 200ms
4. **Speak clearly:** "Hello, can you hear me?"
5. **Release** mouse button
6. Wait for processing

**Expected Visual Behavior:**

**While Holding (RECORDING):**
- ✅ Node turns **RED**
- ✅ "Listening..." message appears above node
- ✅ Pulsing ring around node (audio level visualization)
- ✅ Node slightly larger (scale 1.1)

**After Release (PROCESSING):**
- ✅ Node turns **BLUE**
- ✅ "Processing..." message appears
- ✅ Node returns to normal size

**After Processing (IDLE):**
- ✅ Node returns to original color
- ✅ Message disappears
- ✅ Response may appear (if conversation works)

**Expected Backend Console Output:**
```
[VoiceCommand] Starting recording from client <id>
[VoiceCommand] Recording started
[VoiceCommand] Audio captured: 76800 samples @ 16kHz
[VoiceCommand] Processing audio tensor...
[VoiceCommand] ChatState: Adding user audio (16kHz)
[VoiceCommand] LFM2-Audio generating response...
[VoiceCommand] Audio response: 48000 samples @ 24kHz
[VoiceCommand] Playing native audio response
[VoiceCommand] State: PROCESSING -> SUCCESS
```

**If it fails:**
- Check microphone permissions in browser
- Check backend console for errors
- Try speaking louder/clearer
- Try holding longer (2-3 seconds)
- Check audio device is working

---

### Test 3.4: Short Click (Recall)

Verify existing functionality still works.

**Steps:**
1. **Click** orbit node quickly (< 200ms)
2. **Release** immediately

**Expected Behavior:**
- ✅ Node recall triggered (existing navigation)
- ✅ NO voice recording starts
- ✅ NO red color change
- ✅ Normal navigation behavior

**If it fails:**
- Check if hold timer is too short
- Check if recall function is broken

---

## 4. Integration Tests

### Test 4.1: Native Audio Conversation

Test various conversation commands:

**Test Commands:**
1. "What time is it?"
2. "Tell me a joke"
3. "What's the weather like?"
4. "How are you today?"

**For each command:**
1. Click and hold orbit node
2. Speak the command clearly
3. Release mouse button
4. Wait for native audio response

**Expected Behavior:**
- ✅ Audio tensor processed in backend console
- ✅ Native audio response generated
- ✅ Audio response played through speakers
- ✅ Visual feedback in UI (state changes)
- ✅ Conversation memory maintained

**Backend Console Should Show:**
```
[VoiceCommand] Audio tensor: 76800 samples @ 16kHz
[VoiceCommand] ChatState: Processing user audio
[VoiceCommand] LFM2-Audio generating native response...
[VoiceCommand] Native audio generated: 48000 samples @ 24kHz
[VoiceCommand] Playing audio response
[VoiceCommand] State: PROCESSING -> SUCCESS
```

---

### Test 4.2: Visual Query Commands (Placeholder)

Test visual query routing:

**Test Commands:**
1. "What's on my screen?"
2. "Read this dialog box"
3. "Describe what you see"

**Expected Behavior:**
- ✅ Command recognized as visual query
- ✅ Response generated (may be generic without LFM2-Audio)
- ✅ Backend console shows: `[VoiceCommand] Visual query: '...'`

**Note:** Full visual understanding requires Phase 2 (LFM2-Audio)

---

### Test 4.3: GUI Action Commands (Placeholder)

Test GUI action routing:

**Test Commands:**
1. "Click the submit button"
2. "Type hello world"
3. "Scroll down"

**Expected Behavior:**
- ✅ Command recognized as GUI action
- ✅ Error message: "GUI actions require LFM2-Audio integration (coming in Phase 2)"
- ✅ Suggestion to try questions instead
- ✅ Backend console shows: `[VoiceCommand] GUI action: '...'`

**Note:** GUI automation requires Phase 2 (LFM2-Audio)

---

## 5. Edge Case Tests

### Test 5.1: No Speech
1. Click and hold orbit node
2. **Don't speak** (stay silent)
3. Wait 2-3 seconds
4. Release

**Expected Behavior:**
- ✅ Recording stops automatically after ~2 seconds
- ✅ Error message: "No speech detected"
- ✅ Node returns to idle state

---

### Test 5.2: Very Short Speech
1. Click and hold orbit node
2. Say just "Hi" (very quick)
3. Release immediately

**Expected Behavior:**
- ✅ May show "Audio too short" error
- ✅ Or may transcribe successfully
- ✅ Node returns to idle state

---

### Test 5.3: Mouse Leave During Recording
1. Click and hold orbit node
2. Start speaking
3. **Move mouse away** from node (while still holding)
4. Release mouse button

**Expected Behavior:**
- ✅ Recording cancels when mouse leaves
- ✅ Node returns to idle state
- ✅ No processing occurs

---

### Test 5.4: Multiple Rapid Commands
1. Click and hold orbit node
2. Say "Hello"
3. Release
4. **Immediately** click and hold again
5. Say "How are you"
6. Release

**Expected Behavior:**
- ✅ First command processes
- ✅ Second command waits or queues
- ✅ Both commands eventually process
- ✅ No crashes or errors

---

## 6. Success Criteria

Phase 1 is **COMPLETE** if:

### Core Functionality
- [x] Orb click-and-hold detection works (200ms threshold)
- [x] Visual state changes work (red → blue → normal)
- [x] WebSocket communication works
- [x] Audio capture works (16kHz tensor)
- [x] LFM2-Audio model loads and processes
- [x] ChatState maintains conversation memory
- [x] Native audio generation works (24kHz output)
- [x] Audio playback through speakers
- [x] Command routing works (conversation/visual/GUI)
- [x] Conversation commands work with native audio responses

### Visual Feedback
- [x] Red glow during recording
- [x] Blue glow during processing
- [x] Audio level visualization (pulsing ring)
- [x] Status messages ("Listening...", "Processing...")
- [x] Smooth state transitions

### Error Handling
- [x] No crashes on invalid input
- [x] Graceful handling of no speech
- [x] Graceful handling of short audio
- [x] Clear error messages to user

### Existing Functionality
- [x] Short click still triggers recall
- [x] Navigation still works
- [x] No regression in other features

---

## 7. Common Issues and Solutions

### Issue: "Voice handler not available"
**Solution:** 
- Check backend console for initialization errors
- Verify `voice_handler` is initialized in lifespan
- Restart backend server

### Issue: No audio captured
**Solution:**
- Check microphone permissions in browser
- Check audio device in `check_devices.py`
- Try different browser (Chrome recommended)
- Check system audio settings

### Issue: LFM2-Audio model not loading
**Solution:**
- Check internet connection (first download ~3GB)
- Check disk space (models are ~3GB)
- Wait for download to complete
- Check CUDA memory if using GPU
- Clear cache: `rm -rf ~/.cache/huggingface/hub/models--LiquidAI*`

### Issue: No response generated
**Solution:**
- Check conversation manager is initialized
- Check LLM model is loaded
- Check backend console for errors
- Try simpler commands first

### Issue: WebSocket connection fails
**Solution:**
- Check backend is running on port 8000
- Check no firewall blocking
- Check CORS settings in `main.py`
- Try refreshing browser page

---

## 8. Performance Benchmarks

### Expected Timings
- **Click-and-hold detection:** < 200ms
- **Audio capture start:** < 100ms
- **VAD speech detection:** Real-time (< 50ms per frame)
- **STT transcription:** 1-3 seconds (depends on audio length)
- **Command routing:** < 100ms
- **Response generation:** 1-5 seconds (depends on LLM)
- **TTS synthesis:** 1-2 seconds
- **Total end-to-end:** 3-10 seconds

### Resource Usage
- **CPU:** Moderate during transcription, low otherwise
- **Memory:** ~500MB-1GB (models loaded)
- **Network:** Only for model downloads (first run)
- **Disk:** ~2GB for models

---

## 9. Next Steps After Testing

### If All Tests Pass ✅
**Phase 1 is COMPLETE!**

You can now proceed to **Phase 2**:
- LFM2-Audio integration
- Visual grounding for GUI elements
- Screen capture and analysis
- Visual question answering
- GUI automation with vision

### If Tests Fail ❌
1. Note which test failed
2. Check backend console for errors
3. Check browser console for errors
4. Review error messages
5. Try solutions in "Common Issues" section
6. If still failing, provide error details for debugging

---

## 10. Testing Checklist

Print this checklist and check off as you test:

### Prerequisites
- [ ] Python dependencies installed
- [ ] Node dependencies installed
- [ ] Audio devices verified

### Backend Tests
- [ ] Audio pipeline test passed
- [ ] LFM2-Audio model test passed
- [ ] Backend server starts without errors

### Frontend Tests
- [ ] Frontend starts without errors
- [ ] WebSocket connection established
- [ ] Orb click-and-hold works
- [ ] Visual states work (red/blue/normal)
- [ ] Audio level visualization works
- [ ] Short click still works (recall)

### Integration Tests
- [ ] Conversation commands work
- [ ] Visual query routing works
- [ ] GUI action routing works (placeholder)
- [ ] Native audio responses play

### Edge Cases
- [ ] No speech handled gracefully
- [ ] Short speech handled
- [ ] Mouse leave cancels recording
- [ ] Multiple rapid commands work

### Final Check
- [ ] No crashes or errors
- [ ] All console output looks correct
- [ ] User experience is smooth
- [ ] Ready for Phase 2

---

## Support

If you encounter issues during testing:
1. Check backend console output
2. Check browser console output
3. Review error messages carefully
4. Try solutions in "Common Issues" section
5. Provide detailed error information for debugging

**Phase 1 is ready for testing!** 🚀
# IRIS Native Audio Finalization and Debug Plan

## Current Status
- Backend running on port 8000 (PID 22064)
- AudioEngine.start() is called in main.py with debug logging
- Enhanced logging added to AudioPipeline for diagnosis
- Wake word buffer logging restored

## Phase 1: Restore Core Audio Functionality (CRITICAL)

### Task 1: Enhanced Logging (COMPLETED)
- [x] Added detailed logging to AudioPipeline.start()
- [x] Added error handling in _input_loop with try/catch blocks
- [x] Added logging for callback execution
- [x] Added logging for stream initialization parameters

### Task 2: Diagnose AudioEngine.start() (IN PROGRESS)
- [x] Confirmed AudioEngine.start() is called in main.py line 374
- [x] Debug prints added to show engine state after startup
- [ ] Verify debug output appears in terminal
- [ ] Check if AudioPipeline.start() is actually invoked
- [ ] Verify wake_detector initialization status

### Task 3: Verify Wake Word Detection
- [ ] Test wake word "Jarvis" with enhanced logging
- [ ] Confirm wake word buffer appears in terminal
- [ ] Verify UI glow effect triggers on wake word
- [ ] Test audio capture and processing pipeline

## Phase 2: Fix UI Wake Phrase Configuration

### Task 1: Backend State Management
- [ ] Verify wake phrase options are properly loaded in state
- [ ] Check if wake_config is properly initialized
- [ ] Ensure wake phrase choices are sent via WebSocket

### Task 2: Frontend State Management  
- [ ] Verify fieldValues contains wake phrase options
- [ ] Check DarkGlassDashboard receives proper props
- [ ] Ensure FieldRow renders wake phrase dropdown correctly

### Task 3: UI Component Refactor
- [ ] Update wake phrase field to show dropdown options
- [ ] Ensure updateField properly updates backend state
- [ ] Test wake phrase selection and persistence

## Phase 3: Final Validation

### Task 1: End-to-End Test
- [ ] Test complete wake word → recording → processing → response cycle
- [ ] Verify UI glow effect on both wake word and double-click
- [ ] Confirm audio is captured and processed without lag
- [ ] Validate response playback works

### Task 2: Performance Verification
- [ ] Confirm no system freezing during processing
- [ ] Verify GPU memory management is working
- [ ] Check CPU usage is within acceptable limits
- [ ] Ensure conversation state limiting prevents memory leaks

## Next Steps
1. Check terminal output for AudioEngine debug messages
2. Verify AudioPipeline logging appears
3. Test wake word detection with current logging
4. Fix wake phrase UI configuration
5. Complete end-to-end validation

## Notes
- All optimizations from native-audio-performance-optimization-plan.md remain in place
- Backend consolidated to single port 8000
- UI synchronization between hexagonal-control-center and dark-glass-dashboard maintained
"""
Voice Command Handler - Native Audio processing for IRIS
Handles audio capture and native audio-to-audio conversation
"""
import asyncio
import threading
import os
import numpy as np
import torch
from typing import Optional, Callable, Dict, Any
from enum import Enum

from .vad import VADProcessor
from .engine import AudioEngine


class VoiceState(str, Enum):
    """Voice command states"""
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"


class VoiceCommandHandler:
    """
    Handles native audio conversation:
    1. Audio capture on orb hold/double-click
    2. VAD for speech detection (optional)
    3. Native audio processing (16kHz -> 24kHz)
    4. Audio response playback
    """
    
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.pipeline: Optional[AudioPipeline] = None
        self.vad_processor: Optional[VADProcessor] = None
        
        # State
        self.state = VoiceState.IDLE
        self.is_recording = False
        self.audio_buffer = []
        self.silence_counter = 0
        self.speech_started = False
        self._overflow_stop_requested = False  # Flag for buffer overflow
        
        # Audio frame listener registration
        self._frame_listener_registered = False
        
        # Configuration
        self.silence_threshold = 30  # ~1 second of silence
        self.min_speech_frames = 10  # ~0.3 seconds minimum speech
        self.sample_rate = 16000  # Input sample rate (microphone)
        self.frame_length = 512
        self.max_buffer_frames = 3000  # ~2 minutes max recording (prevents memory overflow)
        
        # Callbacks
        self._on_state_change: Optional[Callable[[VoiceState, str], None]] = None
        self._on_command_result: Optional[Callable[[Dict[str, Any]], None]] = None
        
        # Preload the native audio model to avoid delays
        self.preload_model()
        
    def preload_model(self):
        """Preload the native audio model to avoid delays during first use"""
        def _load():
            try:
                print("[VoiceCommand] Preloading native audio model...")
                if not self.audio_engine.model_manager.is_loaded:
                    if self.audio_engine.model_manager.load_model():
                        print("[VoiceCommand] Native audio model preloaded successfully")
                    else:
                        print("[VoiceCommand] Failed to preload native audio model")
                else:
                    print("[VoiceCommand] Native audio model already loaded")
            except Exception as e:
                print(f"[VoiceCommand] Error preloading model: {e}")
        
        # Run in background thread to not block startup
        threading.Thread(target=_load, daemon=True).start()
    
    def _play_activation_beep(self):
        """Play activation beep using AudioEngine's pipeline"""
        try:
            print("[VoiceCommand] Playing activation beep...")
            
            # Generate beep sound
            sample_rate = 24000
            duration = 0.1
            frequency = 880
            t = np.linspace(0, duration, int(sample_rate * duration))
            beep_wave = 0.3 * np.sin(2 * np.pi * frequency * t)
            
            # Convert to int16
            beep_wave = (beep_wave * 32767).astype(np.int16)
            
            # Use AudioEngine's pipeline for beep
            if self.audio_engine.pipeline:
                self.audio_engine.pipeline.play_audio(beep_wave)
                print("[VoiceCommand] Activation beep played")
            else:
                print("[VoiceCommand] ERROR: AudioEngine pipeline not available for beep")
                
        except Exception as e:
            print(f"[VoiceCommand] Failed to play activation beep: {e}")
            
    def set_state_callback(self, callback: Callable[[VoiceState, str], None]):
        """Set callback for state changes"""
        self._on_state_change = callback
        
    def set_command_result_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Set callback for command results"""
        self._on_command_result = callback
        
    def _set_state(self, new_state: VoiceState, message: str = ""):
        """Update state and notify callbacks"""
        if self.state != new_state:
            old_state = self.state
            self.state = new_state
            print(f"[VoiceCommand] State: {old_state} -> {new_state}")
            
            if self._on_state_change:
                try:
                    self._on_state_change(new_state, message)
                except Exception as e:
                    print(f"[VoiceCommand] State callback error: {e}")
    
    def on_speech_ended(self):
        """Handle speech ended notification from AudioEngine"""
        if self.is_recording:
            print("[VoiceCommand] Speech ended notification received from AudioEngine")
            # Stop recording and process the captured audio
            self.stop_recording()
        else:
            print("[VoiceCommand] Speech ended notification received but not recording")
                    
    def start_recording(self) -> bool:
        """Start voice recording using unified audio stream"""
        if self.is_recording:
            return True
            
        try:
            print("[VoiceCommand] Starting recording...")
            
            # Play activation beep using AudioEngine's pipeline
            self._play_activation_beep()
            
            # Initialize VAD if not already done (optional for native audio)
            if not self.vad_processor:
                self.vad_processor = VADProcessor(enabled=True)
            
            # Reset state
            self.is_recording = True
            self.audio_buffer = []
            self.silence_counter = 0
            self.speech_started = False
            self._overflow_stop_requested = False
            
            # Register frame listener with AudioEngine's unified pipeline
            if not self._frame_listener_registered:
                if self.audio_engine.pipeline:
                    self.audio_engine.register_frame_listener(self._capture_frame)
                    self._frame_listener_registered = True
                    print("[VoiceCommand] Registered frame listener with AudioEngine")
                else:
                    print("[VoiceCommand] ERROR: AudioEngine pipeline not available for frame listener registration")
                    self._set_state(VoiceState.ERROR, "Audio pipeline not ready")
                    return False
            
            self._set_state(VoiceState.RECORDING, "Listening...")
            print("[VoiceCommand] Recording started using unified audio stream")
            return True
            
        except Exception as e:
            print(f"[VoiceCommand] Failed to start recording: {e}")
            self._set_state(VoiceState.ERROR, f"Recording failed: {e}")
            return False
            
    def _capture_frame(self, audio_frame: np.ndarray):
        """Capture audio frame during recording"""
        if not self.is_recording:
            return
            
        # Check for overflow stop request (set by buffer overflow)
        if self._overflow_stop_requested:
            self._overflow_stop_requested = False
            self.stop_recording()
            return
            
        # Add to buffer with overflow protection
        if len(self.audio_buffer) < self.max_buffer_frames:
            self.audio_buffer.append(audio_frame)
            # Only log every 100 frames to reduce spam
            if len(self.audio_buffer) % 100 == 0:
                print(f"[VoiceCommand] Buffer: {len(self.audio_buffer)} frames")
        else:
            # Buffer full - mark for auto-stop (don't call stop_recording from audio thread)
            print(f"[VoiceCommand] Buffer full ({len(self.audio_buffer)} frames) - will auto-stop")
            self._overflow_stop_requested = True
        
        # Check for speech using VAD (optional for native audio)
        if self.vad_processor:
            is_speech = self.vad_processor.process(audio_frame)
            
            if is_speech:
                # Speech detected
                if not self.speech_started:
                    self.speech_started = True
                    print("[VoiceCommand] Speech started")
                self.silence_counter = 0
            else:
                # Silence detected
                if self.speech_started:
                    # Speech was happening, now silence
                    self.silence_counter += 1
                    
                    # If sustained silence, continue recording (user controls stop)
                    if self.silence_counter >= self.silence_threshold:
                        print(f"[VoiceCommand] Speech paused (silence detected: {self.silence_counter} frames), continuing... (waiting for user to stop)")
                else:
                    # Silence before speech started
                    self.silence_counter += 1
                    
                    # If too much silence before speech, continue recording (user controls stop)
                    if self.silence_counter >= 60:  # ~2 seconds
                        print("[VoiceCommand] No speech detected yet, continuing...")
                        
    def stop_recording(self):
        """Stop recording and process native audio using unified stream"""
        if not self.is_recording:
            return
            
        print("[VoiceCommand] Stopping recording...")
        
        # Add a minimum threshold check for the audio buffer
        # Assuming self.chunk_size is defined elsewhere or derived from frame_length
        # For now, using a placeholder if not explicitly defined
        chunk_size = self.frame_length # Assuming frame_length is the chunk size
        min_audio_frames = int(self.sample_rate * 0.5 / chunk_size) # 0.5 seconds
        if len(self.audio_buffer) < min_audio_frames:
            print(f"[VoiceCommand] Audio too short: {len(self.audio_buffer)} frames, skipping processing")
            self.is_recording = False
            self.audio_buffer = []
            self._set_state(VoiceState.IDLE, "Recording too short")
            return
        
        # Don't stop the unified pipeline - just stop recording state
        self.is_recording = False
        
        # Check if we have audio
        if len(self.audio_buffer) == 0:
            print("[VoiceCommand] No audio captured")
            self._set_state(VoiceState.ERROR, "No audio captured")
            self._reset_state()
            return
            
        # Check minimum speech duration (optional for native audio)
        total_frames = len(self.audio_buffer)
        if total_frames < self.min_speech_frames:
            print(f"[VoiceCommand] Audio too short: {total_frames} frames")
            self._set_state(VoiceState.ERROR, "Audio too short")
            self._reset_state()
            return
            
        # Process the native audio in background thread
        print(f"[VoiceCommand] Processing {total_frames} frames...")
        self._set_state(VoiceState.PROCESSING, "Processing...")
        
        # Combine audio buffer efficiently
        print(f"[VoiceCommand] Concatenating {len(self.audio_buffer)} frames...")
        audio_data = np.concatenate(self.audio_buffer)
        print(f"[VoiceCommand] Audio data shape: {audio_data.shape}, size: {audio_data.nbytes / 1024 / 1024:.2f} MB")
        
        # Convert to torch tensor (required for LFM2-Audio)
        import torch
        audio_tensor = torch.from_numpy(audio_data).float()
        print(f"[VoiceCommand] Converted to torch tensor: {audio_tensor.shape}, dtype: {audio_tensor.dtype}")
        
        # Process in background thread
        process_thread = threading.Thread(
            target=self._process_native_audio,
            args=(audio_tensor,),
            daemon=True
        )
        process_thread.start()
        
    def _process_native_audio(self, audio_tensor: torch.Tensor):
        """Process captured audio using native audio model in background thread"""
        try:
            # Set CPU affinity to limit CPU core usage (max 4 cores)
            if hasattr(os, 'sched_setaffinity'):
                cpu_count = min(4, os.cpu_count() or 4)
                os.sched_setaffinity(0, list(range(cpu_count)))
                print(f"[VoiceCommand] Limited processing to {cpu_count} CPU cores")
            
            # Ensure native audio model is loaded
            if not self.audio_engine.model_manager.is_loaded:
                print("[VoiceCommand] Loading native audio model...")
                if not self.audio_engine.model_manager.load_model():
                    print("[VoiceCommand] Failed to load native audio model")
                    self._set_state(VoiceState.ERROR, "Native audio model not available")
                    self._reset_state()
                    return
            
            # Process native audio (16kHz input -> 24kHz output) using async method
            print(f"[VoiceCommand] Processing native audio: {len(audio_tensor)} samples...")
            
            # Use the main event loop from AudioEngine to run the async method
            future = asyncio.run_coroutine_threadsafe(
                self.audio_engine.model_manager.process_native_audio_async(
                    audio_tensor, 
                    sample_rate=self.sample_rate
                ),
                self.audio_engine.get_main_loop()
            )
            
            # Wait for the result
            response_audio, debug_text = future.result()
            
            if response_audio is None or len(response_audio) == 0:
                print("[VoiceCommand] No audio response generated")
                self._set_state(VoiceState.ERROR, "No audio response")
                self._reset_state()
                return
                
            print(f"[VoiceCommand] Generated audio response: {response_audio.shape} @ 24kHz")
            if debug_text:
                print(f"[VoiceCommand] Debug text: '{debug_text}'")
            
            # Play the native audio response
            self._play_native_response(response_audio, debug_text)
            
        except Exception as e:
            print(f"[VoiceCommand] Native audio processing error: {e}")
            import traceback
            traceback.print_exc()
            self._set_state(VoiceState.ERROR, f"Native audio processing failed: {e}")
            self._reset_state()
            
    def _play_native_response(self, audio_response: np.ndarray, debug_text: Optional[str] = None):
        """Play the native audio response using AudioEngine's pipeline"""
        try:
            print("[VoiceCommand] Playing native audio response...")
            
            # Check audio format and shape
            print(f"[VoiceCommand] Audio input shape: {audio_response.shape}, ndim: {audio_response.ndim}")
            
            # Ensure we have a 1D mono audio array for playback
            if audio_response.ndim > 1:
                # If multi-dimensional, take the first channel or flatten
                if audio_response.shape[0] == 1:
                    audio_response = audio_response[0]  # Remove single dimension
                else:
                    # Take first channel if multiple channels
                    audio_response = audio_response[0] if audio_response.shape[0] > 1 else audio_response.flatten()
            
            # Check audio levels
            print(f"[VoiceCommand] Audio stats - min: {audio_response.min():.4f}, max: {audio_response.max():.4f}, mean: {audio_response.mean():.4f}")
            
            # Normalize and boost volume if needed
            if audio_response.max() > 0:
                # Normalize to prevent clipping
                audio_response = audio_response / audio_response.max()
                # Apply volume boost (2x amplification)
                audio_response = audio_response * 2.0
                # Clip to prevent distortion
                audio_response = np.clip(audio_response, -1.0, 1.0)
                print(f"[VoiceCommand] Normalized and boosted audio - min: {audio_response.min():.4f}, max: {audio_response.max():.4f}")
            
            # Use AudioEngine's pipeline for playback
            if self.audio_engine.pipeline:
                self.audio_engine.pipeline.play_audio(audio_response)
                print("[VoiceCommand] Native audio response played successfully")
            else:
                print("[VoiceCommand] ERROR: AudioEngine pipeline not available for playback")
                self._set_state(VoiceState.ERROR, "Audio playback failed: pipeline not available")
                return
            
            # Send result callback
            self._send_result({
                "type": "native_audio_response",
                "audio_shape": audio_response.shape,
                "sample_rate": 24000,
                "debug_text": debug_text,
                "status": "success"
            })
            
            self._set_state(VoiceState.SUCCESS, "Native audio response played")
            
        except Exception as e:
            print(f"[VoiceCommand] Failed to play native audio response: {e}")
            self._set_state(VoiceState.ERROR, f"Audio playback failed: {e}")
            
        self._reset_state()
        
    def _send_result(self, result: Dict[str, Any]):
        """Send command result to callback"""
        if self._on_command_result:
            try:
                self._on_command_result(result)
            except Exception as e:
                print(f"[VoiceCommand] Result callback error: {e}")
                
    def _reset_state(self):
        """Reset to idle state"""
        self.audio_buffer = []
        self.silence_counter = 0
        self.speech_started = False
        
        # Return to idle after a delay
        def return_to_idle():
            self._set_state(VoiceState.IDLE, "")
            
        timer = threading.Timer(2.0, return_to_idle)
        timer.start()
        
    def cancel_recording(self):
        """Cancel recording without processing using unified stream"""
        if not self.is_recording:
            return
            
        print("[VoiceCommand] Canceling recording...")
        
        # Don't stop the unified pipeline - just stop recording state
        self.is_recording = False
        self._set_state(VoiceState.IDLE, "Recording canceled")
        self._reset_state()
        
    def get_status(self) -> Dict[str, Any]:
        """Get current status"""
        return {
            "state": self.state.value,
            "is_recording": self.is_recording,
            "buffer_size": len(self.audio_buffer),
            "silence_counter": self.silence_counter,
            "speech_started": self.speech_started,
        }
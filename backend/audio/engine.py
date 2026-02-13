"""
AudioEngine - Singleton audio processing engine for IRIS
Manages voice pipeline, LFM 2.5 Audio inference, and audio I/O
"""
import asyncio
import threading
from enum import Enum
from typing import Optional, Callable, Dict, Any
import numpy as np

from .model_manager import ModelManager
from .wake_word import WakeWordDetector
from .vad import VADProcessor
from .pipeline import AudioPipeline
from backend.ws_manager import get_websocket_manager
from backend.agent import (
    get_tts_manager,
    get_conversation_manager,
)


class VoiceState(str, Enum):
    """Voice processing states matching PRD State 6"""
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING_CONVERSATION = "processing_conversation"
    PROCESSING_TOOL = "processing_tool"
    SPEAKING = "speaking"
    ERROR = "error"


class AudioEngine:
    """
    Singleton audio engine managing the complete voice pipeline:
    1. Wake word detection (Porcupine)
    2. Voice activity detection (Silero VAD)
    3. Audio buffering
    4. LFM 2.5 Audio inference
    5. Audio output
    """
    
    _instance: Optional['AudioEngine'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if AudioEngine._initialized:
            return
            
        # Core components
        self.model_manager = ModelManager()
        self.wake_detector: Optional[WakeWordDetector] = None
        self.vad_processor: Optional[VADProcessor] = None
        self.pipeline: Optional[AudioPipeline] = None
        self.tts_manager = get_tts_manager()
        self.conversation_manager = get_conversation_manager()
        
        # State
        self._state = VoiceState.IDLE
        self._state_callbacks: list[Callable[[VoiceState], None]] = []
        self._wake_callbacks: list[Callable[[str, float], None]] = []
        self._is_running = False
        self._lock = threading.Lock()
        
        # Configuration
        self.config: Dict[str, Any] = {
            "wake_word_sensitivity": 0.7,
            "wake_phrase": "Jarvis",
            "input_device": None,  # Default
            "output_device": None,  # Default
            "input_sensitivity": 1.0,
            "noise_reduction": True,
            "echo_cancellation": True,
            "vad_enabled": True,
            "sample_rate": 16000,
            "frame_length": 512,
            "conversation_endpoint": None,
            "conversation_model": None,
        }
        
        AudioEngine._initialized = True
    
    @property
    def state(self) -> VoiceState:
        return self._state
    
    def on_state_change(self, callback: Callable[[VoiceState], None]):
        """Register state change callback"""
        self._state_callbacks.append(callback)

    def on_wake_detected(self, callback: Callable[[str, float], None]):
        """Register wake word detection callback (phrase, confidence)"""
        self._wake_callbacks.append(callback)
    
    def _set_state(self, new_state: VoiceState):
        """Update state and notify callbacks"""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            print(f"[AudioEngine] State: {old_state.value} -> {new_state.value}")
            for callback in self._state_callbacks:
                try:
                    callback(new_state)
                except Exception as e:
                    print(f"State callback error: {e}")
    
    def initialize(self) -> bool:
        """
        Initialize audio engine components
        Returns True if successful
        """
        try:
            print("[AudioEngine] Initializing...")
            
            # Initialize wake word detector
            if not self.wake_detector:
                self.wake_detector = WakeWordDetector(
                    sensitivity=self.config.get("wake_word_sensitivity", 0.7),
                    wake_phrase=self.config.get("wake_phrase", "Jarvis")
                )
            
            # FORCE SYNC: Ensure detector matches engine config
            self.wake_detector.wake_phrase = self.config.get("wake_phrase", "Jarvis")
            print(f"[AudioEngine] Force-syncing wake phrase to: {self.wake_detector.wake_phrase}")
            
            # Initialize wake word detector
            if not self.wake_detector.initialize():
                print("[AudioEngine] Wake word detector failed to initialize")
                return False
            
            # Initialize VAD
            self.vad_processor = VADProcessor(
                enabled=self.config["vad_enabled"]
            )
            
            # Initialize audio pipeline
            self.pipeline = AudioPipeline(
                input_device=self.config["input_device"],
                output_device=self.config["output_device"],
                sample_rate=self.config["sample_rate"],
                frame_length=self.config["frame_length"]
            )
            
            print("[AudioEngine] Initialization complete")
            return True
            
        except Exception as e:
            print(f"[AudioEngine] Initialization failed: {e}")
            self._set_state(VoiceState.ERROR)
            return False
    
    def start(self) -> bool:
        """Start the audio pipeline"""
        if self._is_running:
            return True
            
        if not self.pipeline:
            if not self.initialize():
                return False
        
        # Initialize wake word detector if not already done
        if self.wake_detector and not self.wake_detector._initialized:
            print("[AudioEngine] Initializing wake word detector...")
            if not self.wake_detector.initialize():
                print("[AudioEngine] Wake word detector failed to initialize")
                self._set_state(VoiceState.ERROR)
                return False
        
        try:
            print("[AudioEngine] Starting audio pipeline...")
            self.pipeline.start(
                on_audio_frame=self._process_audio_frame
            )
            self._is_running = True
            self._set_state(VoiceState.IDLE)
            print("[AudioEngine] Audio pipeline started")
            return True
            
        except Exception as e:
            print(f"[AudioEngine] Failed to start: {e}")
            self._set_state(VoiceState.ERROR)
            return False
    
    def stop(self):
        """Stop the audio pipeline"""
        if self.pipeline:
            self.pipeline.stop()
        self._is_running = False
        self._set_state(VoiceState.IDLE)
        print("[AudioEngine] Audio pipeline stopped")
    
    def _process_audio_frame(self, audio_frame: np.ndarray):
        """
        Process incoming audio frame through the pipeline:
        1. Check for wake word (if idle)
        2. Detect voice activity (if listening)
        3. Buffer audio (if processing)
        4. Run inference (when speech ends)
        """
        try:
            if self._state == VoiceState.IDLE:
                # Check for wake word
                if self.wake_detector and self.wake_detector.process(audio_frame):
                    self._on_wake_word_detected()
                    
            elif self._state == VoiceState.LISTENING:
                # Check for voice activity
                if self.vad_processor:
                    speech_detected = self.vad_processor.process(audio_frame)
                    if speech_detected:
                        self._on_speech_started()
                        
            elif self._state in [VoiceState.PROCESSING_CONVERSATION, VoiceState.PROCESSING_TOOL]:
                # Buffer audio for inference
                # If VAD is enabled, check if speech has ended
                if self.vad_processor:
                    is_speech = self.vad_processor.process(audio_frame)
                    if not is_speech:
                        # Speech ended
                        self._on_speech_ended()
                    else:
                        # Still speaking, buffer the frame
                        # Note: pipeline.get_buffered_audio() clears the buffer, 
                        # so the pipeline must handle the actual accumulation.
                        pass 
                else:
                    # No VAD, just buffer (not ideal for auto-detection)
                    pass
                    
        except Exception as e:
            print(f"[AudioEngine] Frame processing error: {e}")
    
    def _on_wake_word_detected(self):
        """Handle wake word detection"""
        print("[AudioEngine] Wake word detected!")
        wake_phrase = self.config.get("wake_phrase", "Jarvis")
        confidence = 0.85  # Placeholder - could get from wake_detector
        
        # Notify callbacks (for WebSocket broadcast)
        for callback in self._wake_callbacks:
            try:
                callback(wake_phrase, confidence)
            except Exception as e:
                print(f"Wake callback error: {e}")
        
        self._set_state(VoiceState.LISTENING)
        
    def _on_speech_started(self):
        """Handle speech start detection"""
        print("[AudioEngine] Speech started")
        # Clear buffer to start fresh from speech start
        if self.pipeline:
            self.pipeline.clear_buffer()
        # Transition to processing state
        self._set_state(VoiceState.PROCESSING_CONVERSATION)
        
    def _on_speech_ended(self):
        """Handle speech end detection - trigger inference"""
        print("[AudioEngine] Speech ended, processing...")
        
        # Get buffered audio and run inference
        if self.pipeline:
            audio_buffer = self.pipeline.get_buffered_audio()
            self._run_inference(audio_buffer)
    
    def _run_inference(self, audio_buffer: np.ndarray):
        """
        Run LFM 2.5 Audio inference on buffered audio and play response
        """
        try:
            # Ensure we're in processing state
            self._set_state(VoiceState.PROCESSING_CONVERSATION)

            if len(audio_buffer) < self.config["frame_length"] * 5:  # At least 5 frames
                print(f"[AudioEngine] Audio too short ({len(audio_buffer)} samples), ignoring")
                self._set_state(VoiceState.IDLE)
                return

            # Ensure STT model loaded
            if not self.model_manager.is_loaded:
                print("[AudioEngine] Loading LFM model for STT...")
                if not self.model_manager.load_model():
                    print("[AudioEngine] Failed to load STT model")
                    self._set_state(VoiceState.ERROR)
                    return

            try:
                print(f"[AudioEngine] Running STT on {len(audio_buffer)} samples...")
                transcript = self.model_manager.process_stt(audio_buffer)
            except Exception as stt_err:
                print(f"[AudioEngine] STT processing error: {stt_err}")
                transcript = None

            if not transcript:
                print("[AudioEngine] STT returned no transcript")
                self._set_state(VoiceState.IDLE)
                return

            print(f"[AudioEngine] Transcript: {transcript[:100]}...")

            # Broadcast transcript to UI
            ws_manager = get_websocket_manager()
            try:
                # Use a fire-and-forget approach for broadcast if loop is not running
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(ws_manager.broadcast({
                        "type": "stt_transcript",
                        "text": transcript
                    }))
                else:
                    print(f"[AudioEngine] (UI Broadcast skip: loop not running) Transcript: {transcript}")
            except Exception as ws_err:
                print(f"[AudioEngine] WS Broadcast error: {ws_err}")

            # Trigger activation sound (optional - PRD requirement for feedback)
            if self.config.get("activation_sound", True):
                print("[AudioEngine] (Feedback: Beep/Sound would play here)")

            # Update LM Studio config from engine config if available
            conversation_updates = {}
            endpoint = self.config.get("conversation_endpoint") or self.config.get("model_endpoint")
            if endpoint:
                conversation_updates["endpoint"] = endpoint
            conversation_model = self.config.get("conversation_model")
            if conversation_model:
                conversation_updates["model"] = conversation_model
            if conversation_updates:
                self.conversation_manager.update_config(**conversation_updates)

            response_text = self.conversation_manager.generate_response(transcript)
            if not response_text:
                print("[AudioEngine] Conversation model returned no response")
                self._set_state(VoiceState.IDLE)
                return

            print(f"[AudioEngine] Response text: {response_text[:100]}...")

            # Broadcast AI response to UI
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(ws_manager.broadcast({
                        "type": "ai_response",
                        "text": response_text
                    }))
                else:
                    print(f"[AudioEngine] (UI Broadcast skip: loop not running) AI: {response_text}")
            except Exception as ws_err:
                print(f"[AudioEngine] WS Broadcast error: {ws_err}")

            # Synthesize audio
            print(f"[AudioEngine] Starting synthesis for voice: {self.tts_manager.config['tts_voice']}...")
            
            if self.tts_manager.config["tts_voice"] == "LiquidAI":
                # Use LiquidAI local model for synthesis
                print("[AudioEngine] Using LiquidAI for local TTS...")
                synthesized_audio = self.model_manager.generate_response_audio(
                    response_text, 
                    max_tokens=self.config.get("max_tokens", 2048),
                    temperature=self.config.get("temperature", 0.7)
                )
                
                # LiquidAI returns audio at 24kHz, resample to 16kHz if needed
                if synthesized_audio is not None and len(synthesized_audio) > 0:
                    # Resample from 24kHz to 16kHz
                    import torch
                    import torchaudio.transforms as T
                    
                    if isinstance(synthesized_audio, np.ndarray):
                        audio_tensor = torch.from_numpy(synthesized_audio).float()
                    else:
                        audio_tensor = synthesized_audio
                        
                    if audio_tensor.dim() == 1:
                        audio_tensor = audio_tensor.unsqueeze(0)
                        
                    resampler = T.Resample(24000, 16000)
                    audio_tensor = resampler(audio_tensor)
                    synthesized_audio = audio_tensor.squeeze().numpy() # Squeeze to ensure flat array
            else:
                # Use traditional TTSManager (OpenAI or Built-in)
                synthesized_audio = self.tts_manager.synthesize(response_text)
                if synthesized_audio is not None:
                    synthesized_audio = np.squeeze(synthesized_audio) # Squeeze just in case
            
            if synthesized_audio is None:
                print("[AudioEngine] TTS returned None (Check OpenAI API key and pydub/ffmpeg)")
                self._set_state(VoiceState.IDLE)
                return
                
            if len(synthesized_audio) == 0:
                print("[AudioEngine] TTS returned empty audio")
                self._set_state(VoiceState.IDLE)
                return

            print(f"[AudioEngine] Successfully synthesized {len(synthesized_audio)} samples")

            # Switch to speaking state and play
            self._set_state(VoiceState.SPEAKING)
            if self.pipeline:
                print(f"[AudioEngine] Playing synthesized response via AudioPipeline...")
                try:
                    self.pipeline.play_audio(synthesized_audio)
                    print("[AudioEngine] Playback finished")
                except Exception as play_err:
                    print(f"[AudioEngine] Playback error: {play_err}")
            else:
                print("[AudioEngine] No AudioPipeline available for playback")

            # Final transition back to IDLE
            self._set_state(VoiceState.IDLE)

        except Exception as e:
            print(f"[AudioEngine] Inference error: {e}")
            import traceback
            traceback.print_exc()
            self._set_state(VoiceState.ERROR)
            # Try to recover to IDLE after error
            self._set_state(VoiceState.IDLE)
    
    def update_config(self, **kwargs):
        """Update engine configuration"""
        self.config.update(kwargs)

        # Update conversation manager config if relevant values changed
        conversation_updates = {}
        if "conversation_endpoint" in kwargs and kwargs["conversation_endpoint"]:
            conversation_updates["endpoint"] = kwargs["conversation_endpoint"]
        else:
            model_endpoint = kwargs.get("model_endpoint")
            if model_endpoint:
                conversation_updates["endpoint"] = model_endpoint

        if "conversation_model" in kwargs and kwargs["conversation_model"]:
            conversation_updates["model"] = kwargs["conversation_model"]

        if conversation_updates:
            self.conversation_manager.update_config(**conversation_updates)
        
        # Reinitialize if running
        if self._is_running:
            self.stop()
            self.initialize()
            self.start()
    
    def get_status(self) -> Dict[str, Any]:
        """Get current engine status"""
        return {
            "state": self._state.value,
            "is_running": self._is_running,
            "config": self.config,
            "model_loaded": self.model_manager.is_loaded if self.model_manager else False,
        }


def get_audio_engine() -> AudioEngine:
    """Get the singleton AudioEngine instance"""
    return AudioEngine()

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
        
        # State
        self._state = VoiceState.IDLE
        self._state_callbacks: list[Callable[[VoiceState], None]] = []
        self._is_running = False
        self._lock = threading.Lock()
        
        # Configuration
        self.config: Dict[str, Any] = {
            "wake_word_sensitivity": 0.7,
            "wake_phrase": "Hey IRIS",
            "input_device": None,  # Default
            "output_device": None,  # Default
            "input_sensitivity": 1.0,
            "noise_reduction": True,
            "echo_cancellation": True,
            "vad_enabled": True,
            "sample_rate": 16000,
            "frame_length": 512,
        }
        
        AudioEngine._initialized = True
    
    @property
    def state(self) -> VoiceState:
        return self._state
    
    def on_state_change(self, callback: Callable[[VoiceState], None]):
        """Register state change callback"""
        self._state_callbacks.append(callback)
    
    def _set_state(self, new_state: VoiceState):
        """Update state and notify callbacks"""
        if self._state != new_state:
            self._state = new_state
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
            self.wake_detector = WakeWordDetector(
                sensitivity=self.config["wake_word_sensitivity"],
                wake_phrase=self.config["wake_phrase"]
            )
            
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
        3. Buffer audio (if speaking)
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
                if self.vad_processor and not self.vad_processor.process(audio_frame):
                    # Speech ended
                    self._on_speech_ended()
                    
        except Exception as e:
            print(f"[AudioEngine] Frame processing error: {e}")
    
    def _on_wake_word_detected(self):
        """Handle wake word detection"""
        print("[AudioEngine] Wake word detected!")
        self._set_state(VoiceState.LISTENING)
        
    def _on_speech_started(self):
        """Handle speech start detection"""
        print("[AudioEngine] Speech started")
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
        if len(audio_buffer) < self.config["frame_length"] * 10:  # At least 10 frames
            print("[AudioEngine] Audio too short, ignoring")
            self._set_state(VoiceState.IDLE)
            return
        
        try:
            print(f"[AudioEngine] Running LFM 2.5 Audio inference on {len(audio_buffer)} samples...")
            self._set_state(VoiceState.PROCESSING_CONVERSATION)
            
            # Load model if not loaded
            if not self.model_manager.is_loaded:
                print("[AudioEngine] Loading model...")
                if not self.model_manager.load_model():
                    print("[AudioEngine] Failed to load model")
                    self._set_state(VoiceState.ERROR)
                    return
            
            # Run inference
            output_audio, transcript = self.model_manager.inference(
                audio_input=audio_buffer,
                mode="conversation",
                max_tokens=self.config.get("max_tokens", 2048),
                temperature=self.config.get("temperature", 0.7)
            )
            
            if output_audio is not None and len(output_audio) > 0:
                # Switch to speaking state
                self._set_state(VoiceState.SPEAKING)
                
                # Play the response
                print(f"[AudioEngine] Playing response ({len(output_audio)} samples)")
                if self.pipeline:
                    self.pipeline.play_audio(output_audio)
                
                print(f"[AudioEngine] Transcript: {transcript[:100] if transcript else 'N/A'}...")
            else:
                print("[AudioEngine] No audio generated")
            
            # Return to idle
            self._set_state(VoiceState.IDLE)
            
        except Exception as e:
            print(f"[AudioEngine] Inference error: {e}")
            import traceback
            traceback.print_exc()
            self._set_state(VoiceState.ERROR)
    
    def update_config(self, **kwargs):
        """Update engine configuration"""
        self.config.update(kwargs)
        
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

"""
AudioEngine - Singleton audio processing engine for IRIS
Manages voice pipeline, LFM2-Audio native inference, and audio I/O
"""
import asyncio
import threading
import time
from enum import Enum
from typing import Optional, Callable, Dict, Any
import numpy as np

from .model_manager import ModelManager
from .wake_word import WakeWordDetector
from .vad import VADProcessor
from .pipeline import AudioPipeline
from backend.ws_manager import get_websocket_manager


class VoiceState(str, Enum):
    """Voice processing states for native audio flow"""
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING_NATIVE_AUDIO = "processing_native_audio"
    PLAYING_NATIVE_AUDIO = "playing_native_audio"
    ERROR = "error"


class AudioEngine:
    """
    Singleton audio engine managing the native audio pipeline:
    1. Wake word detection (Porcupine)
    2. Voice activity detection (Silero VAD)
    3. Audio buffering
    4. LFM2-Audio native processing (16kHz -> 24kHz)
    5. Native audio output
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
        self._wake_callbacks: list[Callable[[str, float], None]] = []
        self._is_running = False
        self._lock = threading.Lock()
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None  # Store main event loop for cross-thread scheduling
        
        # VAD State Tracking
        self._silence_counter = 0     # Counter for consecutive non-speech frames
        self._speech_started = False  # Flag to track if actual speech has begun
        self._last_state_change_time = 0.0  # For state change debouncing
        
        # Configuration
        self.config: Dict[str, Any] = {
            "wake_word_enabled": True,  # Enabled for testing
            "wake_word_sensitivity": 0.7,
            "wake_phrase": "Jarvis",
            "input_device": None,  # Default
            "output_device": None,  # Default
            "input_sensitivity": 1.0,
            "noise_reduction": True,
            "echo_cancellation": True,
            "vad_enabled": True,
            "sample_rate": 16000,  # Input sample rate (microphone)
            "frame_length": 512,
            "activation_sound": True,
            # Native audio settings
            "native_audio_enabled": True,
            "native_audio_model": "LiquidAI/LFM2.5-Audio-1.5B",
        }
        
        AudioEngine._initialized = True
    
    @property
    def state(self) -> VoiceState:
        return self._state
    
    def on_state_change(self, callback: Callable[[VoiceState], None]):
        """Register state change callback"""
        self._state_callbacks.append(callback)

    def get_main_loop(self):
        """Get the main event loop captured during initialization"""
        return self._main_loop

    def on_wake_detected(self, callback: Callable[[str, float], None]):
        """Register wake word detection callback (phrase, confidence)"""
        self._wake_callbacks.append(callback)

    def register_frame_listener(self, callback: Callable[[np.ndarray], None]):
        """Register a listener for raw audio frames."""
        if self.pipeline:
            self.pipeline.add_frame_listener(callback)
    
    def _set_state(self, new_state: VoiceState):
        """Update state and notify callbacks, with debouncing"""
        now = time.time()
        if self.state == new_state and (now - self._last_state_change_time) < 1.0:
            # Debounce: ignore if same state change within 1 second
            return
            
        if self.state != new_state:
            old_state = self.state
            self._state = new_state  # Set the actual private variable
            self._last_state_change_time = now
            print(f"[AudioEngine] State: {old_state} -> {new_state}")
            
            # Notify callbacks
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
            
            # Capture the main event loop for cross-thread WebSocket broadcasts
            try:
                self._main_loop = asyncio.get_running_loop()
                print("[AudioEngine] Captured main event loop for cross-thread scheduling")
            except RuntimeError:
                try:
                    self._main_loop = asyncio.get_event_loop()
                    print("[AudioEngine] Captured event loop (fallback) for cross-thread scheduling")
                except RuntimeError:
                    print("[AudioEngine] WARNING: No event loop available for WebSocket broadcasts")
                    self._main_loop = None
            
            # Initialize wake word detector (LAZY - only when wake word is enabled)
            if self.config.get("wake_word_enabled", True):
                if not self.wake_detector:
                    self.wake_detector = WakeWordDetector(
                        sensitivity=self.config.get("wake_word_sensitivity", 0.7),  # Use config value
                        wake_phrase=self.config.get("wake_phrase", "Jarvis")
                    )
                
                # FORCE SYNC: Ensure detector matches engine config
                self.wake_detector.wake_phrase = self.config.get("wake_phrase", "Jarvis")
                print(f"[AudioEngine] Force-syncing wake phrase to: {self.wake_detector.wake_phrase}")
                print(f"[AudioEngine] Wake sensitivity: {self.wake_detector.sensitivity}")
                print(f"[AudioEngine] Wake gain: {self.wake_detector.gain}")
                
                # Initialize wake word detector
                if not self.wake_detector.initialize():
                    print("[AudioEngine] Wake word detector failed to initialize")
                    return False
            else:
                print("[AudioEngine] Wake word detection disabled, skipping initialization")
            
            # Initialize VAD (LAZY - only when VAD is enabled)
            if self.config.get("vad_enabled", True):
                self.vad_processor = VADProcessor(
                    enabled=True
                )
                print("[AudioEngine] VAD processor initialized")
            else:
                self.vad_processor = None
                print("[AudioEngine] VAD disabled, skipping initialization")
            
            # Auto-select devices if none configured
            if self.config.get("input_device") is None or self.config.get("output_device") is None:
                try:
                    devices = AudioPipeline.list_devices()
                    if self.config.get("input_device") is None:
                        first_input = next((d for d in devices if d.get("input")), None)
                        if first_input:
                            self.config["input_device"] = first_input.get("index")
                            print(f"[AudioEngine] Auto-selected input device index: {self.config['input_device']} ({first_input.get('name')})")
                    if self.config.get("output_device") is None:
                        first_output = next((d for d in devices if d.get("output")), None)
                        if first_output:
                            self.config["output_device"] = first_output.get("index")
                            print(f"[AudioEngine] Auto-selected output device index: {self.config['output_device']} ({first_output.get('name')})")
                except Exception as device_err:
                    print(f"[AudioEngine] Failed to auto-select devices: {device_err}")

            # Initialize audio pipeline
            print(f"[AudioEngine] Creating pipeline with input_device: {self.config['input_device']}, output_device: {self.config['output_device']}")
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
        Process incoming audio frame through the native audio pipeline:
        1. Check for wake word (if idle)
        2. Detect voice activity (if listening)
        3. Buffer audio (if processing)
        4. Run native audio inference (when speech ends)
        """
        
        try:
            if self._state == VoiceState.IDLE:
                # Check for wake word (only if detector is enabled and initialized)
                if self.wake_detector and self.wake_detector._initialized and self.wake_detector.process(audio_frame):
                    print("[AudioEngine] Wake word detected!")
                    self._on_wake_word_detected()
                    self._set_state(VoiceState.LISTENING)  # Correctly set state
                    
            elif self._state == VoiceState.LISTENING:
                # Check for voice activity
                if self.vad_processor:
                    speech_detected = self.vad_processor.process(audio_frame)
                    if speech_detected:
                        self._on_speech_started()
                        
            # Note: PROCESSING_NATIVE_AUDIO state removed - VoiceCommandHandler handles processing
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
        
        # Reset VAD tracking
        self._silence_counter = 0
        self._speech_started = False
        
        self._set_state(VoiceState.LISTENING)
        
    def _on_speech_started(self):
        """Handle speech start detection"""
        print("[AudioEngine] Speech started")
        # Clear buffer to start fresh from speech start
        if self.pipeline:
            self.pipeline.clear_buffer()
        # Transition to native audio processing state
        self._set_state(VoiceState.PROCESSING_NATIVE_AUDIO)
        
    def _on_speech_ended(self):
        """Handle speech end detection - notify VoiceCommandHandler to process audio"""
        print("[AudioEngine] Speech ended, notifying VoiceCommandHandler...")
        
        # Reset VAD tracking
        self._silence_counter = 0
        self._speech_started = False
        
        # Transition to PROCESSING state to trigger VoiceCommandHandler
        # The VoiceCommandHandler will handle the actual audio processing
        self._set_state(VoiceState.PROCESSING)
    
    def _broadcast_threadsafe(self, message: dict):
        """
        Broadcast a WebSocket message from any thread safely.
        Uses the stored main event loop with call_soon_threadsafe.
        """
        ws_manager = get_websocket_manager()
        
        if self._main_loop and self._main_loop.is_running():
            self._main_loop.call_soon_threadsafe(
                self._main_loop.create_task,
                ws_manager.broadcast(message)
            )
        else:
            # Fallback: try to get a running loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(ws_manager.broadcast(message))
                else:
                    print(f"[AudioEngine] (WS skip: no running loop) {message.get('type', 'unknown')}")
            except Exception as e:
                print(f"[AudioEngine] WS broadcast error: {e}")



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
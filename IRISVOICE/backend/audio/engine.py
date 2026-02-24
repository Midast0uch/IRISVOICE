"""
AudioEngine - Singleton audio processing engine for IRIS
Manages voice pipeline, LFM2-Audio native inference, and audio I/O
"""
import asyncio
import logging
import threading
import time
from enum import Enum
from typing import Optional, Callable, Dict, Any
import numpy as np

logger = logging.getLogger(__name__)

from .model_manager import ModelManager
from .pipeline import AudioPipeline
from backend.ws_manager import get_websocket_manager
from backend.agent import get_unified_conversation_manager, get_lfm_audio_manager


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
        self.pipeline: Optional[AudioPipeline] = None
        self.lfm_audio_manager = get_lfm_audio_manager()
        
        # State
        self._state = VoiceState.IDLE
        self._state_callbacks: list[Callable[[VoiceState], None]] = []
        self._is_running = False
        self._lock = threading.Lock()
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        
        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass  # No running loop
        
        self.config: Dict[str, Any] = {
            "input_device": None,
            "output_device": None,
            "input_sensitivity": 1.0,
            "noise_reduction": True,
            "echo_cancellation": True,
            "sample_rate": 16000,
            "frame_length": 512,
            "activation_sound": True,
            "native_audio_enabled": True,
            "native_audio_model": "./models",
        }
        
        AudioEngine._initialized = True

    @property
    def state(self) -> VoiceState:
        return self._state

    def on_state_change(self, callback: Callable[[VoiceState], None]):
        self._state_callbacks.append(callback)

    def register_frame_listener(self, callback: Callable[[np.ndarray], None]):
        if self.pipeline:
            self.pipeline.add_frame_listener(callback)

    def _handle_lfm_status_change(self, status: str):
        """Handle status updates from LFM Audio Manager"""
        logger.info(f"[AudioEngine] LFM Audio status: {status}")
        if status == "processing":
            self._set_state(VoiceState.PROCESSING_NATIVE_AUDIO)
        elif status == "ready":
            self._set_state(VoiceState.IDLE)
        elif status == "error":
            self._set_state(VoiceState.ERROR)

    def _handle_lfm_transcription(self, text: str):
        """Handle transcription updates from LFM Audio Manager"""
        logger.info(f"[AudioEngine] LFM transcription: {text}")
        # Broadcast transcription to WebSocket
        from backend.ws_manager import get_websocket_manager
        ws_manager = get_websocket_manager()
        asyncio.create_task(ws_manager.broadcast({
            "type": "lfm_transcription",
            "text": text
        }))

    def _handle_lfm_audio_response(self, audio_data: bytes):
        """Handle audio responses from LFM Audio Manager"""
        logger.info(f"[AudioEngine] LFM audio response: {len(audio_data)} bytes")
        # Play the audio response
        if self.pipeline:
            self.pipeline.play_audio(audio_data)
            self._set_state(VoiceState.PLAYING_NATIVE_AUDIO)
            # Return to listening state after playback
            asyncio.create_task(self._return_to_listening_after_audio())

    async def _return_to_listening_after_audio(self):
        """Return to listening state after audio playback"""
        await asyncio.sleep(0.5)  # Small delay
        self._set_state(VoiceState.LISTENING)

    def _set_state(self, new_state: VoiceState):
        if self.state != new_state:
            old_state = self.state
            self._state = new_state
            logger.info(f"[AudioEngine] State: {old_state} -> {new_state}")
            
            for callback in self._state_callbacks:
                try:
                    callback(new_state)
                except Exception as e:
                    logger.error(f"State callback error: {e}")

    def initialize(self) -> bool:
        try:
            logger.info("[AudioEngine] Initializing...")
            
            # IMPORTANT: lfm_audio_manager.initialize() is async and should be
            # called from an async context at application startup (e.g., in main.py),
            # not from here. We will assume it's initialized.
            if self.config.get("native_audio_enabled", True):
                # Only set callbacks if the manager is initialized
                if self.lfm_audio_manager.is_initialized:
                    # Setup callbacks
                    self.lfm_audio_manager.set_callbacks(
                        on_status_change=self._handle_lfm_status_change,
                        on_transcription_update=self._handle_lfm_transcription,
                        on_audio_response=self._handle_lfm_audio_response
                    )
                else:
                    logger.info("[AudioEngine] LFMAudioManager not initialized yet. Callbacks will be set when it initializes.")

            if self.config.get("input_device") is None or self.config.get("output_device") is None:
                try:
                    devices = AudioPipeline.list_devices()
                    if self.config.get("input_device") is None:
                        first_input = next((d for d in devices if d.get("input")), None)
                        if first_input:
                            self.config["input_device"] = first_input.get("index")
                    if self.config.get("output_device") is None:
                        first_output = next((d for d in devices if d.get("output")), None)
                        if first_output:
                            self.config["output_device"] = first_output.get("index")
                except Exception as device_err:
                    logger.error(f"[AudioEngine] Failed to auto-select devices: {device_err}")

            self.pipeline = AudioPipeline(
                input_device=self.config["input_device"],
                output_device=self.config["output_device"],
                sample_rate=self.config["sample_rate"],
                frame_length=self.config["frame_length"]
            )
            
            logger.info("[AudioEngine] Initialization complete")
            return True
            
        except Exception as e:
            logger.error(f"[AudioEngine] Initialization failed: {e}")
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
            logger.info("[AudioEngine] Starting audio pipeline...")
            self.pipeline.start(
                on_audio_frame=self._process_audio_frame
            )
            self._is_running = True
            self._set_state(VoiceState.IDLE)
            logger.info("[AudioEngine] Audio pipeline started")
            return True
            
        except Exception as e:
            logger.error(f"[AudioEngine] Failed to start: {e}")
            self._set_state(VoiceState.ERROR)
            return False
    
    def stop(self):
        """Stop the audio pipeline"""
        if self.pipeline:
            self.pipeline.stop()
        self._is_running = False
        self._set_state(VoiceState.IDLE)
        logger.info("[AudioEngine] Audio pipeline stopped")
    
    def _process_audio_frame(self, audio_frame: np.ndarray):
        """
        Process incoming audio frame through the native audio pipeline:
        1. Stream audio to LFM Audio Manager for processing
        """
        try:
            if self.lfm_audio_manager and self.lfm_audio_manager.is_initialized:
                # Asynchronously stream audio data to the LFM Audio Manager
                asyncio.run_coroutine_threadsafe(
                    self.lfm_audio_manager.process_audio_stream(audio_frame.tobytes()), 
                    self._main_loop
                )
        except Exception as e:
            logger.error(f"[AudioEngine] Frame processing error: {e}")
    

    
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
                    logger.debug(f"[AudioEngine] (WS skip: no running loop) {message.get('type', 'unknown')}")
            except Exception as e:
                logger.error(f"[AudioEngine] WS broadcast error: {e}")



    def update_config(self, **kwargs):
        """Update engine configuration"""
        self.config.update(kwargs)
        
        # Reinitialize if running
        if self._is_running:
            self.stop()
            self.initialize()
            self.start()
    
    def cleanup(self):
        """Clean up resources"""
        try:
            print("[AudioEngine] Cleaning up...")
            self.stop()
            
            # Clean up LFM Audio Manager
            if self.lfm_audio_manager:
                try:
                    # Get the running loop or create a new one for cleanup
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # If loop is running, schedule the task
                        loop.create_task(self.lfm_audio_manager.cleanup())
                    else:
                        # If loop is not running, run the coroutine directly
                        loop.run_until_complete(self.lfm_audio_manager.cleanup())
                except RuntimeError:
                    # No event loop available, try to create one
                    try:
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        new_loop.run_until_complete(self.lfm_audio_manager.cleanup())
                        new_loop.close()
                    except Exception as nested_e:
                        print(f"[AudioEngine] Failed to cleanup LFM Audio Manager: {nested_e}")
            
            print("[AudioEngine] Cleanup complete")
            
        except Exception as e:
            print(f"[AudioEngine] Error during cleanup: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current engine status"""
        return {
            "state": self._state.value,
            "is_running": self._is_running,
            "config": self.config,
            "model_loaded": self.model_manager.is_loaded if self.model_manager else False,
            "lfm_audio_initialized": self.lfm_audio_manager.is_initialized if self.lfm_audio_manager else False,
        }


def get_audio_engine() -> AudioEngine:
    """Get the singleton AudioEngine instance"""
    return AudioEngine()
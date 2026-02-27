"""
VoicePipeline - Orchestrator for LFM 2.5 Audio Model

The VoicePipeline orchestrates the LFM 2.5 audio model (end-to-end audio-to-audio processing).
It manages voice state transitions and coordinates with AudioEngine.

Voice States:
- idle: No voice interaction
- listening: Capturing audio from user
- processing_conversation: Processing user speech and generating response
- processing_tool: Executing tool calls
- speaking: Playing audio response
- error: Error occurred

The LFM 2.5 audio model handles everything internally:
- Audio capture, wake word detection, VAD, STT, conversation, TTS, audio playback
"""
import asyncio
import logging
from typing import Optional, Dict, Any, Callable
from enum import Enum

logger = logging.getLogger(__name__)


class VoiceState(str, Enum):
    """Voice interaction states"""
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING_CONVERSATION = "processing_conversation"
    PROCESSING_TOOL = "processing_tool"
    SPEAKING = "speaking"
    ERROR = "error"


class VoicePipeline:
    """
    Orchestrator for the LFM 2.5 audio model
    
    Manages voice state transitions and coordinates with AudioEngine.
    The LFM 2.5 audio model handles all audio processing internally.
    """
    
    def __init__(self, audio_engine=None):
        """
        Initialize VoicePipeline
        
        Args:
            audio_engine: AudioEngine instance (optional, will be created if not provided)
        """
        self._audio_engine = audio_engine
        self._state = VoiceState.IDLE
        self._session_states: Dict[str, VoiceState] = {}  # session_id -> state
        self._audio_level = 0.0
        self._state_callbacks: Dict[str, list] = {}  # session_id -> list of callbacks
        self._audio_level_callbacks: Dict[str, list] = {}  # session_id -> list of callbacks
        
        # Audio level monitoring task
        self._audio_level_task: Optional[asyncio.Task] = None
        self._monitoring_session: Optional[str] = None
        
        logger.info("[VoicePipeline] Initialized")
    
    async def initialize(self) -> bool:
        """
        Initialize the voice pipeline and audio engine
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if self._audio_engine is None:
                from backend.voice.audio_engine import AudioEngine
                self._audio_engine = AudioEngine()
            
            # Initialize audio engine
            success = await self._audio_engine.initialize()
            if not success:
                logger.error("[VoicePipeline] Failed to initialize audio engine")
                return False
            
            logger.info("[VoicePipeline] Initialized successfully")
            return True
        
        except ImportError as e:
            logger.error(f"[VoicePipeline] Failed to import AudioEngine: {e}")
            return False
        except Exception as e:
            logger.error(f"[VoicePipeline] Initialization failed: {e}", exc_info=True)
            return False
    
    async def start_listening(self, session_id: str) -> bool:
        """
        Start listening for voice input
        
        Activates the LFM 2.5 audio model to begin audio capture and processing.
        
        Args:
            session_id: Session ID
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"[VoicePipeline] Starting listening for session {session_id}")
            
            # Check if audio engine is initialized
            if self._audio_engine is None:
                logger.error("[VoicePipeline] Audio engine not initialized")
                await self._set_state(session_id, VoiceState.ERROR)
                return False
            
            # Start audio interaction
            success = await self._audio_engine.start_audio_interaction()
            if not success:
                logger.error("[VoicePipeline] Failed to start audio interaction")
                await self._set_state(session_id, VoiceState.ERROR)
                return False
            
            # Update state to listening
            await self._set_state(session_id, VoiceState.LISTENING)
            
            # Start audio level monitoring
            await self._start_audio_level_monitoring(session_id)
            
            logger.info(f"[VoicePipeline] Listening started for session {session_id}")
            return True
        
        except Exception as e:
            logger.error(f"[VoicePipeline] Error starting listening: {e}", exc_info=True)
            await self._set_state(session_id, VoiceState.ERROR)
            return False
    
    async def stop_listening(self, session_id: str) -> bool:
        """
        Stop listening and process the captured audio
        
        Deactivates the LFM 2.5 audio model and transitions to processing state.
        
        Args:
            session_id: Session ID
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"[VoicePipeline] Stopping listening for session {session_id}")
            
            # Stop audio level monitoring
            await self._stop_audio_level_monitoring(session_id)
            
            # Update state to processing
            await self._set_state(session_id, VoiceState.PROCESSING_CONVERSATION)
            
            # Stop audio interaction
            if self._audio_engine:
                await self._audio_engine.stop_audio_interaction()
            else:
                logger.warning("[VoicePipeline] Audio engine not available during stop")
            
            logger.info(f"[VoicePipeline] Listening stopped for session {session_id}")
            return True
        
        except Exception as e:
            logger.error(f"[VoicePipeline] Error stopping listening: {e}", exc_info=True)
            await self._set_state(session_id, VoiceState.ERROR)
            return False
    
    async def process_audio(self, audio_data: bytes, session_id: str) -> str:
        """
        Process audio through the LFM 2.5 audio model
        
        The LFM 2.5 model handles all processing: VAD, STT, conversation, TTS.
        
        Args:
            audio_data: Raw audio data
            session_id: Session ID
        
        Returns:
            str: Transcribed text or response
        """
        try:
            logger.info(f"[VoicePipeline] Processing audio for session {session_id}")
            
            # Check if audio engine is initialized
            if self._audio_engine is None:
                logger.error("[VoicePipeline] Audio engine not initialized")
                await self._set_state(session_id, VoiceState.ERROR)
                return ""
            
            # Update state to processing
            await self._set_state(session_id, VoiceState.PROCESSING_CONVERSATION)
            
            # Process audio through LFM 2.5 model
            response_audio = await self._audio_engine.process_audio(audio_data)
            
            # Update state to speaking
            await self._set_state(session_id, VoiceState.SPEAKING)
            
            # LFM 2.5 handles audio playback internally
            # Wait for playback to complete (simulated here)
            await asyncio.sleep(0.5)
            
            # Return to idle state
            await self._set_state(session_id, VoiceState.IDLE)
            
            logger.info(f"[VoicePipeline] Audio processing complete for session {session_id}")
            return "Audio processed successfully"
        
        except Exception as e:
            logger.error(f"[VoicePipeline] Error processing audio: {e}", exc_info=True)
            await self._set_state(session_id, VoiceState.ERROR)
            return ""
    
    def get_audio_level(self) -> float:
        """
        Get current audio level for real-time monitoring
        
        Returns audio level from LFM 2.5 model during listening state.
        
        Returns:
            float: Audio level (0.0 to 1.0)
        """
        # In a real implementation, this would query the LFM 2.5 audio model
        # For now, return the cached value
        return self._audio_level
    
    def get_state(self, session_id: str) -> VoiceState:
        """
        Get current voice state for a session
        
        Args:
            session_id: Session ID
        
        Returns:
            VoiceState: Current voice state
        """
        return self._session_states.get(session_id, VoiceState.IDLE)
    
    def register_state_callback(self, session_id: str, callback: Callable[[VoiceState], None]) -> None:
        """
        Register a callback for state changes
        
        Args:
            session_id: Session ID
            callback: Callback function that receives the new state
        """
        if session_id not in self._state_callbacks:
            self._state_callbacks[session_id] = []
        self._state_callbacks[session_id].append(callback)
    
    def register_audio_level_callback(self, session_id: str, callback: Callable[[float], None]) -> None:
        """
        Register a callback for audio level updates
        
        Args:
            session_id: Session ID
            callback: Callback function that receives the audio level
        """
        if session_id not in self._audio_level_callbacks:
            self._audio_level_callbacks[session_id] = []
        self._audio_level_callbacks[session_id].append(callback)
    
    async def _set_state(self, session_id: str, new_state: VoiceState) -> None:
        """
        Update voice state and notify callbacks
        
        Args:
            session_id: Session ID
            new_state: New voice state
        """
        old_state = self._session_states.get(session_id, VoiceState.IDLE)
        if old_state == new_state:
            return
        
        logger.info(f"[VoicePipeline] State transition for session {session_id}: {old_state} -> {new_state}")
        
        self._session_states[session_id] = new_state
        
        # Notify callbacks
        callbacks = self._state_callbacks.get(session_id, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(new_state)
                else:
                    callback(new_state)
            except Exception as e:
                logger.error(f"[VoicePipeline] Error in state callback: {e}")
    
    async def _start_audio_level_monitoring(self, session_id: str) -> None:
        """
        Start monitoring audio levels during listening state
        
        Args:
            session_id: Session ID
        """
        if self._audio_level_task is not None:
            await self._stop_audio_level_monitoring(session_id)
        
        self._monitoring_session = session_id
        self._audio_level_task = asyncio.create_task(self._audio_level_monitor_loop(session_id))
    
    async def _stop_audio_level_monitoring(self, session_id: str) -> None:
        """
        Stop monitoring audio levels
        
        Args:
            session_id: Session ID
        """
        if self._audio_level_task is not None:
            self._audio_level_task.cancel()
            try:
                await self._audio_level_task
            except asyncio.CancelledError:
                pass
            self._audio_level_task = None
            self._monitoring_session = None
        
        # Reset audio level to 0
        self._audio_level = 0.0
        await self._notify_audio_level(session_id, 0.0)
    
    async def _audio_level_monitor_loop(self, session_id: str) -> None:
        """
        Monitor audio levels and send updates every 100ms
        
        Args:
            session_id: Session ID
        """
        try:
            while True:
                # Get current state
                state = self.get_state(session_id)
                
                # Only monitor during listening state
                if state != VoiceState.LISTENING:
                    break
                
                # Get audio level from LFM 2.5 model
                # In a real implementation, this would query the audio engine
                # For now, simulate with a random value
                import random
                self._audio_level = random.uniform(0.1, 0.8)
                
                # Notify callbacks
                await self._notify_audio_level(session_id, self._audio_level)
                
                # Wait 100ms before next update
                await asyncio.sleep(0.1)
        
        except asyncio.CancelledError:
            logger.info(f"[VoicePipeline] Audio level monitoring cancelled for session {session_id}")
        except Exception as e:
            logger.error(f"[VoicePipeline] Error in audio level monitoring: {e}")
    
    async def _notify_audio_level(self, session_id: str, level: float) -> None:
        """
        Notify callbacks of audio level update
        
        Args:
            session_id: Session ID
            level: Audio level (0.0 to 1.0)
        """
        callbacks = self._audio_level_callbacks.get(session_id, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(level)
                else:
                    callback(level)
            except Exception as e:
                logger.error(f"[VoicePipeline] Error in audio level callback: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get current pipeline status
        
        Returns:
            dict: Status information
        """
        return {
            "audio_engine_status": self._audio_engine.get_status() if self._audio_engine else {},
            "session_states": {sid: state.value for sid, state in self._session_states.items()},
            "audio_level": self._audio_level,
            "monitoring_active": self._audio_level_task is not None
        }


# Global instance
_voice_pipeline: Optional[VoicePipeline] = None


def get_voice_pipeline() -> VoicePipeline:
    """Get or create the singleton VoicePipeline."""
    global _voice_pipeline
    if _voice_pipeline is None:
        _voice_pipeline = VoicePipeline()
    return _voice_pipeline

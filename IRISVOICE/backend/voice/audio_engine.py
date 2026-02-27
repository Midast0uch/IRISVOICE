"""
AudioEngine - Thin wrapper around LFM 2.5 Audio Model

CRITICAL: The LFM 2.5 audio model handles EVERYTHING for audio:
- Raw audio input capture
- Raw audio output playback
- ALL audio processing (noise reduction, echo cancellation, voice enhancement, automatic gain)
- Speech-to-text transcription
- User-agent communication

AudioEngine is just a thin wrapper that:
1. Initializes and manages the LFM 2.5 audio model
2. Provides a simple interface to start/stop audio interaction
3. Passes audio directly to/from the LFM 2.5 model
"""
import asyncio
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class AudioEngine:
    """
    Thin wrapper around LFM 2.5 Audio Model
    
    The LFM 2.5 audio model handles all audio I/O, processing, and transcription.
    AudioEngine just provides a simple interface to start/stop audio interaction.
    """
    
    def __init__(self, lfm_audio_manager=None):
        """
        Initialize AudioEngine with LFM 2.5 audio model
        
        Args:
            lfm_audio_manager: LFMAudioManager instance (optional, will be created if not provided)
        """
        # LFM 2.5 audio model handles everything
        self._lfm_audio_manager = lfm_audio_manager
        
        # State
        self._is_running = False
        self._is_initialized = False
        
        logger.info("[AudioEngine] Initialized as thin wrapper around LFM 2.5 Audio Model")
    
    async def initialize(self) -> bool:
        """
        Initialize the LFM 2.5 audio model
        
        Returns:
            bool: True if successful, False otherwise
        """
        if self._is_initialized:
            logger.info("[AudioEngine] Already initialized")
            return True
        
        try:
            if self._lfm_audio_manager is None:
                # Import here to avoid circular dependency
                from backend.agent import get_lfm_audio_manager
                self._lfm_audio_manager = get_lfm_audio_manager()
            
            # Initialize LFM 2.5 audio model
            logger.info("[AudioEngine] Initializing LFM 2.5 Audio Model...")
            await self._lfm_audio_manager.initialize()
            
            self._is_initialized = True
            logger.info("[AudioEngine] LFM 2.5 Audio Model initialized successfully")
            return True
        
        except Exception as e:
            logger.error(f"[AudioEngine] Failed to initialize LFM 2.5 Audio Model: {e}")
            return False
    
    async def start_audio_interaction(self) -> bool:
        """
        Start audio interaction (listening and responding)
        
        The LFM 2.5 audio model handles all audio I/O and processing.
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._is_initialized:
            logger.error("[AudioEngine] Not initialized. Call initialize() first.")
            return False
        
        if self._is_running:
            logger.warning("[AudioEngine] Already running")
            return True
        
        try:
            logger.info("[AudioEngine] Starting audio interaction...")
            self._is_running = True
            
            # LFM 2.5 audio model handles everything
            # No need to manage streams, devices, or processing
            
            logger.info("[AudioEngine] Audio interaction started")
            return True
        
        except Exception as e:
            logger.error(f"[AudioEngine] Failed to start audio interaction: {e}")
            self._is_running = False
            return False
    
    async def stop_audio_interaction(self):
        """
        Stop audio interaction
        
        The LFM 2.5 audio model handles cleanup.
        """
        if not self._is_running:
            logger.warning("[AudioEngine] Not running")
            return
        
        try:
            logger.info("[AudioEngine] Stopping audio interaction...")
            self._is_running = False
            
            # LFM 2.5 audio model handles cleanup
            
            logger.info("[AudioEngine] Audio interaction stopped")
        
        except Exception as e:
            logger.error(f"[AudioEngine] Error stopping audio interaction: {e}")
    
    async def process_audio(self, audio_data: bytes) -> bytes:
        """
        Process audio through LFM 2.5 audio model
        
        Args:
            audio_data: Raw audio data
        
        Returns:
            bytes: Processed audio response
        """
        if not self._is_initialized:
            logger.error("[AudioEngine] Not initialized")
            return b""
        
        try:
            # LFM 2.5 audio model handles all processing
            response_audio = await self._lfm_audio_manager.process_audio_stream(audio_data)
            return response_audio if response_audio else b""
        
        except Exception as e:
            logger.error(f"[AudioEngine] Error processing audio: {e}")
            return b""
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get current engine status
        
        Returns:
            dict: Status information
        """
        return {
            "is_initialized": self._is_initialized,
            "is_running": self._is_running,
            "lfm_audio_available": self._lfm_audio_manager is not None
        }

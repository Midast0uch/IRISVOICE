#!/usr/bin/env python3
"""
Porcupine Wake Word Detector

This module provides wake word detection using Picovoice's Porcupine engine.
Supports both custom-trained wake word models and built-in Porcupine keywords.
"""

import inspect as _inspect
import os
import logging
from typing import Optional, List, Tuple
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# pvporcupine is imported lazily inside _initialize_porcupine() to avoid loading
# the native Picovoice DLL at backend startup. This shaves ~200 ms off startup
# and means a missing/broken pvporcupine install never crashes the backend on import.
_PORCUPINE_NEEDS_ACCESS_KEY: Optional[bool] = None  # resolved on first use


def _get_porcupine_needs_access_key() -> bool:
    """Lazy check for pvporcupine v2+ access_key requirement. Imports pvporcupine once."""
    global _PORCUPINE_NEEDS_ACCESS_KEY
    if _PORCUPINE_NEEDS_ACCESS_KEY is None:
        import pvporcupine as _pv
        _PORCUPINE_NEEDS_ACCESS_KEY = 'access_key' in _inspect.signature(_pv.create).parameters
    return _PORCUPINE_NEEDS_ACCESS_KEY


class PorcupineWakeWordDetector:
    """
    Wake word detector using Picovoice's Porcupine engine.
    
    Supports:
    - Custom wake word models (.ppn files)
    - Built-in Porcupine keywords (JARVIS, COMPUTER, BUMBLEBEE, PORCUPINE)
    - Configurable sensitivity per wake word
    - 16kHz audio processing at 512 samples per frame
    """
    
    # Built-in Porcupine keywords
    BUILTIN_KEYWORDS = {
        "jarvis": "jarvis",
        "computer": "computer",
        "bumblebee": "bumblebee",
        "porcupine": "porcupine"
    }
    
    def __init__(
        self,
        access_key: Optional[str] = None,
        custom_model_path: Optional[str] = None,
        builtin_keywords: Optional[List[str]] = None,
        sensitivities: Optional[List[float]] = None
    ):
        """
        Initialize Porcupine wake word detector.
        
        Args:
            access_key: Picovoice access key (defaults to PICOVOICE_ACCESS_KEY env var)
            custom_model_path: Path to custom .ppn wake word model file
            builtin_keywords: List of built-in keywords to enable (jarvis, computer, bumblebee, porcupine)
            sensitivities: List of sensitivity values (0.0-1.0) for each wake word
                          Higher values reduce false positives but may increase false negatives
        """
        # _disabled is set to True when Porcupine cannot start (missing key, no wake
        # words, or engine init failure).  All public methods check this and no-op
        # gracefully so the rest of the audio pipeline keeps running.
        self._disabled = False
        self._disabled_reason: str = ""

        # access_key is only required for pvporcupine v2+; v1.x works without one.
        if _get_porcupine_needs_access_key():
            self.access_key = access_key or os.getenv("PICOVOICE_ACCESS_KEY")
            if not self.access_key:
                self._disabled = True
                self._disabled_reason = (
                    "Picovoice access key not set. "
                    "Set PICOVOICE_ACCESS_KEY env var or pass access_key= to enable wake word detection. "
                    "Get a free key at https://console.picovoice.ai/"
                )
                logger.warning(f"[PorcupineDetector] Disabled — {self._disabled_reason}")
                self.porcupine = None
                self.access_key = None
                self.custom_model_path = custom_model_path
                self.builtin_keywords = builtin_keywords or []
                self.keyword_paths = []
                self.wake_word_names = []
                self.sensitivities = []
                return
        else:
            self.access_key = None  # pvporcupine v1.x does not use an access key

        self.custom_model_path = custom_model_path
        self.builtin_keywords = builtin_keywords or []

        # Build keyword paths and model paths
        self.keyword_paths = []
        self.wake_word_names = []

        # Add custom model if provided
        if custom_model_path and os.path.exists(custom_model_path):
            self.keyword_paths.append(custom_model_path)
            # Extract wake word name from filename (e.g., "hey-iris_en_windows_v4_0_0.ppn" -> "hey iris")
            model_name = os.path.basename(custom_model_path).split('_')[0].replace('-', ' ')
            self.wake_word_names.append(model_name)
            logger.info(f"[PorcupineDetector] Added custom wake word: '{model_name}'")
        elif custom_model_path:
            logger.warning(f"[PorcupineDetector] Custom model not found: {custom_model_path}")

        # Add built-in keywords
        for keyword in self.builtin_keywords:
            keyword_lower = keyword.lower()
            if keyword_lower in self.BUILTIN_KEYWORDS:
                # For built-in keywords, just pass the keyword name
                # Porcupine will resolve it internally
                self.keyword_paths.append(keyword_lower)
                self.wake_word_names.append(keyword_lower)
                logger.info(f"[PorcupineDetector] Added built-in keyword: '{keyword_lower}'")
            else:
                logger.warning(f"[PorcupineDetector] Unknown built-in keyword: '{keyword}'")

        if not self.keyword_paths:
            self._disabled = True
            self._disabled_reason = (
                "No wake words configured. "
                "Provide custom_model_path= or builtin_keywords= to enable wake word detection."
            )
            logger.warning(f"[PorcupineDetector] Disabled — {self._disabled_reason}")
            self.porcupine = None
            self.sensitivities = []
            return

        # Set sensitivities (default to 0.5 for each wake word)
        if sensitivities:
            if len(sensitivities) != len(self.keyword_paths):
                logger.warning(
                    f"[PorcupineDetector] Sensitivity count mismatch "
                    f"({len(sensitivities)} vs {len(self.keyword_paths)}); using defaults."
                )
                self.sensitivities = [0.5] * len(self.keyword_paths)
            else:
                self.sensitivities = sensitivities
        else:
            self.sensitivities = [0.5] * len(self.keyword_paths)

        # Initialize Porcupine
        self.porcupine = None
        self._initialize_porcupine()
    
    def _initialize_porcupine(self):
        """Initialize the Porcupine engine."""
        try:
            logger.info("[PorcupineDetector] Initializing Porcupine engine...")
            logger.info(f"[PorcupineDetector] Wake words: {self.wake_word_names}")
            logger.info(f"[PorcupineDetector] Sensitivities: {self.sensitivities}")
            logger.info(f"[PorcupineDetector] Keyword paths: {self.keyword_paths}")
            
            # Separate custom models from built-in keywords
            keywords = []
            keyword_paths = []
            
            for i, path in enumerate(self.keyword_paths):
                if os.path.exists(path):
                    # Custom model file
                    keyword_paths.append(path)
                    logger.info(f"[PorcupineDetector] Custom model: {path}")
                else:
                    # Built-in keyword
                    keywords.append(path)
                    logger.info(f"[PorcupineDetector] Built-in keyword: {path}")
            
            logger.info(f"[PorcupineDetector] Final keyword_paths: {keyword_paths}")
            logger.info(f"[PorcupineDetector] Final keywords: {keywords}")
            logger.info(f"[PorcupineDetector] Total wake words: {len(keyword_paths) + len(keywords)}")
            logger.info(f"[PorcupineDetector] Total sensitivities: {len(self.sensitivities)}")
            
            # Lazy import — pvporcupine DLL is only loaded when Porcupine actually initializes.
            import pvporcupine as _pv

            # Build base kwargs — only include access_key for pvporcupine v2+
            _ak: dict = {"access_key": self.access_key} if _get_porcupine_needs_access_key() else {}

            # Create Porcupine with appropriate parameters
            if keyword_paths and keywords:
                # Mix of custom and built-in
                # When mixing, sensitivities should match keyword_paths + keywords order
                keyword_paths_count = len(keyword_paths)
                sensitivities_for_paths = self.sensitivities[:keyword_paths_count]
                sensitivities_for_keywords = self.sensitivities[keyword_paths_count:]

                logger.info(f"[PorcupineDetector] Sensitivities for paths: {sensitivities_for_paths}")
                logger.info(f"[PorcupineDetector] Sensitivities for keywords: {sensitivities_for_keywords}")

                self.porcupine = _pv.create(
                    **_ak,
                    keyword_paths=keyword_paths,
                    keywords=keywords,
                    sensitivities=self.sensitivities
                )
            elif keyword_paths:
                # Only custom models
                self.porcupine = _pv.create(
                    **_ak,
                    keyword_paths=keyword_paths,
                    sensitivities=self.sensitivities
                )
            else:
                # Only built-in keywords
                self.porcupine = _pv.create(
                    **_ak,
                    keywords=keywords,
                    sensitivities=self.sensitivities
                )
            
            logger.info(
                f"[PorcupineDetector] Porcupine initialized successfully. "
                f"Sample rate: {self.porcupine.sample_rate}Hz, "
                f"Frame length: {self.porcupine.frame_length} samples"
            )
            
        except Exception as e:
            logger.error(f"[PorcupineDetector] Failed to initialize Porcupine: {e}")
            self._disabled = True
            self._disabled_reason = str(e)
            self.porcupine = None
    
    def is_enabled(self) -> bool:
        """Return True if Porcupine initialised successfully and is ready to process frames."""
        return not self._disabled and self.porcupine is not None

    @property
    def sample_rate(self) -> int:
        """Get the required sample rate for audio input."""
        return self.porcupine.sample_rate if self.porcupine else 16000
    
    @property
    def frame_length(self) -> int:
        """Get the required frame length for audio input."""
        return self.porcupine.frame_length if self.porcupine else 512
    
    def process_frame(self, audio_frame: List[int]) -> Tuple[bool, Optional[str]]:
        """
        Process a single audio frame for wake word detection.
        
        Args:
            audio_frame: List of audio samples (must be frame_length samples)
        
        Returns:
            Tuple of (wake_word_detected, wake_word_name)
            - wake_word_detected: True if a wake word was detected
            - wake_word_name: Name of the detected wake word, or None if not detected
        """
        if self._disabled or not self.porcupine:
            return False, None
        
        if len(audio_frame) != self.frame_length:
            logger.error(
                f"[PorcupineDetector] Invalid frame length: {len(audio_frame)} "
                f"(expected {self.frame_length})"
            )
            return False, None
        
        try:
            # Process the frame
            keyword_index = self.porcupine.process(audio_frame)
            
            # Check if a wake word was detected
            if keyword_index >= 0:
                wake_word_name = self.wake_word_names[keyword_index]
                logger.info(f"[PorcupineDetector] Wake word detected: '{wake_word_name}'")
                return True, wake_word_name
            
            return False, None
            
        except Exception as e:
            logger.error(f"[PorcupineDetector] Error processing frame: {e}")
            return False, None
    
    def update_sensitivity(self, wake_word_index: int, sensitivity: float):
        """
        Update sensitivity for a specific wake word.
        
        Note: Requires re-initialization of Porcupine engine.
        
        Args:
            wake_word_index: Index of the wake word (0-based)
            sensitivity: New sensitivity value (0.0-1.0)
        """
        if not 0.0 <= sensitivity <= 1.0:
            logger.warning(
                f"[PorcupineDetector] Invalid sensitivity {sensitivity}, must be 0.0-1.0"
            )
            return
        
        if not 0 <= wake_word_index < len(self.sensitivities):
            logger.warning(
                f"[PorcupineDetector] Invalid wake word index {wake_word_index}"
            )
            return
        
        self.sensitivities[wake_word_index] = sensitivity
        logger.info(
            f"[PorcupineDetector] Updated sensitivity for '{self.wake_word_names[wake_word_index]}' "
            f"to {sensitivity}"
        )
        
        # Re-initialize Porcupine with new sensitivities
        self.cleanup()
        self._initialize_porcupine()
    
    def update_sensitivity_by_name(self, wake_word_name: str, sensitivity: float):
        """
        Update sensitivity for a wake word by name.
        
        Args:
            wake_word_name: Name of the wake word
            sensitivity: New sensitivity value (0.0-1.0)
        """
        try:
            index = self.wake_word_names.index(wake_word_name.lower())
            self.update_sensitivity(index, sensitivity)
        except ValueError:
            logger.warning(
                f"[PorcupineDetector] Wake word '{wake_word_name}' not found"
            )
    
    def cleanup(self):
        """Clean up Porcupine resources."""
        porcupine = getattr(self, "porcupine", None)
        if porcupine:
            logger.info("[PorcupineDetector] Cleaning up Porcupine resources...")
            porcupine.delete()
            self.porcupine = None
    
    def __del__(self):
        """Destructor to ensure cleanup."""
        self.cleanup()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.cleanup()

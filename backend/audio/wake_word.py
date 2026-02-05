"""
WakeWordDetector - Porcupine wake word detection integration
"""
import os
from pathlib import Path
from typing import Optional
import numpy as np


class WakeWordDetector:
    """
    Porcupine wake word detector
    ~50ms detection latency target
    """
    
    # Default wake phrases and their Porcupine keywords
    SUPPORTED_WAKE_PHRASES = {
        "Hey IRIS": "hey_iris",
        "Hey Computer": "hey_computer",
        "Jarvis": "jarvis",
        "Hey Assistant": "hey_assistant",
    }
    
    def __init__(
        self,
        sensitivity: float = 0.7,
        wake_phrase: str = "Hey IRIS",
        access_key: Optional[str] = None
    ):
        self.sensitivity = sensitivity
        self.wake_phrase = wake_phrase
        self.access_key = access_key or os.environ.get("PORCUPINE_ACCESS_KEY")
        
        self._porcupine = None
        self._initialized = False
        
    def initialize(self) -> bool:
        """Initialize Porcupine engine"""
        try:
            import pvporcupine
            
            # Get keyword path for wake phrase
            keyword_path = self._get_keyword_path()
            if not keyword_path:
                print(f"[WakeWordDetector] Unsupported wake phrase: {self.wake_phrase}")
                return False
            
            # Initialize Porcupine
            self._porcupine = pvporcupine.create(
                access_key=self.access_key,
                keyword_paths=[keyword_path],
                sensitivities=[self.sensitivity]
            )
            
            self._initialized = True
            print(f"[WakeWordDetector] Initialized with phrase: {self.wake_phrase}")
            return True
            
        except ImportError:
            print("[WakeWordDetector] pvporcupine not installed")
            return False
        except Exception as e:
            print(f"[WakeWordDetector] Initialization failed: {e}")
            return False
    
    def _get_keyword_path(self) -> Optional[str]:
        """Get keyword file path for wake phrase"""
        # Map wake phrase to built-in Porcupine keyword or custom file
        keyword_map = {
            "Hey IRIS": "hey iris",  # Built-in
            "Jarvis": "jarvis",      # Built-in
        }
        
        keyword = keyword_map.get(self.wake_phrase)
        if keyword:
            return None  # Use built-in keyword name
        
        # Check for custom keyword file
        keyword_file = Path(__file__).parent / "keywords" / f"{self.wake_phrase.lower().replace(' ', '_')}.ppn"
        if keyword_file.exists():
            return str(keyword_file)
        
        return None
    
    def process(self, audio_frame: np.ndarray) -> bool:
        """
        Process audio frame for wake word detection
        Returns True if wake word detected
        """
        if not self._initialized and not self.initialize():
            return False
        
        try:
            # Convert float audio to int16 PCM
            pcm = (audio_frame * 32767).astype(np.int16)
            
            # Porcupine expects specific frame length (usually 512 samples)
            if len(pcm) >= self._porcupine.frame_length:
                pcm = pcm[:self._porcupine.frame_length]
            else:
                # Pad if too short
                pcm = np.pad(pcm, (0, self._porcupine.frame_length - len(pcm)))
            
            # Process with Porcupine
            keyword_index = self._porcupine.process(pcm.tobytes())
            
            return keyword_index >= 0
            
        except Exception as e:
            print(f"[WakeWordDetector] Processing error: {e}")
            return False
    
    def cleanup(self):
        """Release Porcupine resources"""
        if self._porcupine:
            self._porcupine.delete()
            self._porcupine = None
        self._initialized = False

"""
WakeWordDetector - OpenWakeWord local wake word detection
Fully offline, no API keys required
"""
import os
from pathlib import Path
from typing import Optional
import numpy as np


class WakeWordDetector:
    """
    OpenWakeWord detector - runs fully offline
    ~100-200ms detection latency, customizable wake phrases
    """
    
    # Pre-trained models available from OpenWakeWord
    PRETRAINED_MODELS = {
        "Hey Computer": "hey_computer",
        "Jarvis": "jarvis",
        "Alexa": "alexa", 
        "Hey Mycroft": "hey_mycroft",
        "Hey Jarvis": "hey_jarvis",
    }
    
    def __init__(
        self,
        sensitivity: float = 0.7,
        wake_phrase: str = "Hey Computer",
        model_dir: Optional[str] = None
    ):
        self.sensitivity = sensitivity
        self.wake_phrase = wake_phrase
        
        # Model storage
        if model_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            model_dir = base_dir / "models" / "wake_words"
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        self._oww = None
        self._model_path = None
        self._initialized = False
        
    def initialize(self) -> bool:
        """Initialize OpenWakeWord engine"""
        try:
            from openwakeword.model import Model
            
            # Download or get local model path
            model_path = self._get_model_path()
            if not model_path:
                print(f"[WakeWordDetector] Model not available for: {self.wake_phrase}")
                print(f"[WakeWordDetector] Available: {list(self.PRETRAINED_MODELS.keys())}")
                return False
            
            # Initialize OpenWakeWord
            self._oww = Model(wakeword_models=[str(model_path)])
            self._model_path = model_path
            self._initialized = True
            
            print(f"[WakeWordDetector] Initialized with: {self.wake_phrase}")
            print(f"[WakeWordDetector] Model: {model_path}")
            return True
            
        except ImportError:
            print("[WakeWordDetector] openwakeword not installed")
            print("[WakeWordDetector] Run: pip install openwakeword")
            return False
        except Exception as e:
            print(f"[WakeWordDetector] Initialization failed: {e}")
            return False
    
    def _get_model_path(self) -> Optional[str]:
        """Get model file path, download if needed"""
        model_name = self.PRETRAINED_MODELS.get(self.wake_phrase)
        if not model_name:
            # Check for custom trained model
            custom_path = self.model_dir / f"{self.wake_phrase.lower().replace(' ', '_')}.tflite"
            if custom_path.exists():
                return str(custom_path)
            return None
        
        # Check if already downloaded
        model_file = self.model_dir / f"{model_name}.tflite"
        if model_file.exists():
            return str(model_file)
        
        # Download pretrained model
        try:
            import urllib.request
            base_url = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"
            url = f"{base_url}/{model_name}.tflite"
            
            print(f"[WakeWordDetector] Downloading model from {url}...")
            urllib.request.urlretrieve(url, model_file)
            print(f"[WakeWordDetector] Model saved to {model_file}")
            return str(model_file)
            
        except Exception as e:
            print(f"[WakeWordDetector] Failed to download model: {e}")
            return None
    
    def process(self, audio_frame: np.ndarray) -> bool:
        """
        Process audio frame for wake word detection
        Returns True if wake word detected
        """
        if not self._initialized and not self.initialize():
            return False
        
        try:
            # OpenWakeWord expects 16kHz, 16-bit PCM
            # Convert float [-1, 1] to int16
            if audio_frame.dtype == np.float32 or audio_frame.dtype == np.float64:
                pcm = (audio_frame * 32767).astype(np.int16)
            else:
                pcm = audio_frame.astype(np.int16)
            
            # Process with OpenWakeWord
            prediction = self._oww.predict(pcm)
            
            # Check if wake word detected (returns dict with model names as keys)
            if prediction:
                for model_name, score in prediction.items():
                    if score >= self.sensitivity:
                        return True
            
            return False
            
        except Exception as e:
            print(f"[WakeWordDetector] Processing error: {e}")
            return False
    
    def cleanup(self):
        """Release OpenWakeWord resources"""
        if self._oww:
            self._oww = None
        self._initialized = False


# Supported wake phrases getter for UI
def get_supported_wake_phrases():
    """Return list of supported wake phrases"""
    return list(WakeWordDetector.PRETRAINED_MODELS.keys())

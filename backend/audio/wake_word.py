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
    # These names must match the files downloaded by openwakeword.utils.download_models()
    PRETRAINED_MODELS = {
        "Jarvis": "hey_jarvis_v0.1",
        "Alexa": "alexa_v0.1",
        "Hey Mycroft": "hey_mycroft_v0.1",
        "Hey Rhasspy": "hey_rhasspy_v0.1",
        "Hey Computer": "hey_computer_v0.1",
    }
    
    def __init__(
        self,
        sensitivity: float = 0.7,  # Balanced sensitivity for "Hey Jarvis"
        wake_phrase: str = "Jarvis",
        model_dir: Optional[str] = None,
        gain: float = 50.0  # Increased gain to boost low microphone input
    ):
        self.sensitivity = sensitivity
        self.wake_phrase = wake_phrase
        self.gain = gain
        
        # Model storage
        if model_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            model_dir = base_dir / "models" / "wake_words"
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        self._oww = None
        self._model_path = None
        self._initialized = False
        self._audio_buffer = np.array([], dtype=np.float32)

        
    def initialize(self) -> bool:
        """Initialize OpenWakeWord engine"""

        try:
            import openwakeword
            from openwakeword.model import Model
            
            # THE EASY WAY: Use the built-in library downloader
            # print(f"[WakeWordDetector] Ensuring models are downloaded...")
            openwakeword.utils.download_models()
            
            # Try the requested phrase first
            model_key = self.PRETRAINED_MODELS.get(self.wake_phrase)
            
            # If requested phrase not found, try 'Jarvis' as it's the most reliable
            if not model_key:
                print(f"[WakeWordDetector] Phrase '{self.wake_phrase}' not in PRETRAINED_MODELS. Trying Jarvis...")
                model_key = "hey_jarvis_v0.1"
                self.wake_phrase = "Jarvis"

            try:
                # Initialize the model
                self._oww = Model(
                    wakeword_models=[model_key], 
                    inference_framework='onnx'
                )
                self._initialized = True
                print(f"[WakeWordDetector] Successfully initialized with: {self.wake_phrase}")
                return True
            except Exception as e:
                print(f"[WakeWordDetector] Failed to load {model_key}: {e}. Trying fallback to Jarvis...")
                self._oww = Model(
                    wakeword_models=["hey_jarvis_v0.1"],
                    inference_framework='onnx'
                )
                self.wake_phrase = "Jarvis"
                self._initialized = True
                return True
            
        except ImportError:
            print("[WakeWordDetector] openwakeword not installed")
            print("[WakeWordDetector] Run: pip install openwakeword")
            return False
        except Exception as e:
            print(f"[WakeWordDetector] Initialization failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _get_model_path(self) -> Optional[str]:
        """Deprecated: The library handles this now"""
        return "internal"
    
    def process(self, audio_frame: np.ndarray) -> bool:
        """
        Process audio frame for wake word detection
        Returns True if wake word detected
        """
        if not self._initialized and not self.initialize():
            return False
        
        try:
            # Accumulate audio
            self._audio_buffer = np.append(self._audio_buffer, audio_frame)
            # print(f"[WakeWordDetector] Buffer length after append: {len(self._audio_buffer)}")
            
            # OpenWakeWord works best with ~1280 samples (80ms at 16kHz).
            # If we have less than that, wait for more frames.
            if len(self._audio_buffer) < 1280:
                return False
            
            # Get data to process and clear buffer
            # We take all samples collected so far
            to_process = self._audio_buffer
            self._audio_buffer = np.array([], dtype=np.float32)
            # print(f"[WakeWordDetector] Processing buffer with {len(to_process)} samples")

            # OpenWakeWord expects 16kHz, 16-bit PCM
            # Convert float [-1, 1] to int16
            if to_process.dtype == np.float32 or to_process.dtype == np.float64:
                # Log pre-gain audio level
                # max_pre_gain = np.max(np.abs(to_process))
                # print(f"[WakeWordDetector] Max pre-gain audio level: {max_pre_gain:.4f}")

                # Apply gain to boost low volume
                to_process = to_process * self.gain
                # Clamp to [-1, 1]
                to_process = np.clip(to_process, -1.0, 1.0)
                pcm = (to_process * 32767).astype(np.int16)
            else:
                pcm = to_process.astype(np.int16)
            
            # Process with OpenWakeWord
            prediction = self._oww.predict(pcm)
            
            # Log max amplitude and prediction scores occasionally
            # max_amp = np.max(np.abs(pcm))
            # print(f"[WakeWordDetector] Max Amp: {max_amp:.2f}")
            # print(f"[WakeWordDetector] Scores: {prediction}")
            
            # Check if wake word detected (returns dict with model names as keys)
            if prediction:
                for model_name, score in prediction.items():
                    if score >= self.sensitivity:
                        print(f"[WakeWordDetector] Detected {model_name} with score {score:.4f}")
                        return True
            
            return False
            
        except Exception as e:
            print(f"[WakeWordDetector] Processing error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def cleanup(self):
        """Release OpenWakeWord resources"""
        if self._oww:
            self._oww = None
        self._initialized = False
        self._audio_buffer = np.array([], dtype=np.float32)


# Supported wake phrases getter for UI
def get_supported_wake_phrases():
    """Return list of supported wake phrases"""
    return list(WakeWordDetector.PRETRAINED_MODELS.keys())

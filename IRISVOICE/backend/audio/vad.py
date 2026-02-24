"""
VADProcessor - Silero Voice Activity Detection
"""
import numpy as np
import torch
from typing import Optional, List


class VADProcessor:
    """
    Silero VAD for detecting speech start/end
    """
    
    def __init__(
        self,
        enabled: bool = True,
        threshold: float = 0.5,
        min_speech_duration_ms: int = 250,
        max_speech_duration_s: float = float('inf'),
        min_silence_duration_ms: int = 500,
        sample_rate: int = 16000
    ):
        self.enabled = enabled
        self.threshold = threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.max_speech_duration_s = max_speech_duration_s
        self.min_silence_duration_ms = min_silence_duration_ms
        self.sample_rate = sample_rate
        
        self._model = None
        self._utils = None
        self._initialized = False
        
        # State tracking
        self._speech_started = False
        self._speech_buffer: List[np.ndarray] = []
        self._silence_frames = 0
        
    def initialize(self) -> bool:
        """Initialize Silero VAD model"""
        if not self.enabled:
            return True
            
        try:
            # Load Silero VAD
            self._model, self._utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False
            )
            
            self._initialized = True
            print("[VADProcessor] Silero VAD initialized")
            return True
            
        except Exception as e:
            print(f"[VADProcessor] Initialization failed: {e}")
            self.enabled = False
            return False
    
    def process(self, audio_frame: np.ndarray) -> bool:
        """
        Process audio frame for voice activity
        Returns True if speech is detected
        """
        if not self.enabled:
            return True  # Assume speech if VAD disabled
            
        if not self._initialized and not self.initialize():
            return True
        
        try:
            # Convert to torch tensor
            tensor = torch.from_numpy(audio_frame).float()
            
            # Get speech probability
            with torch.no_grad():
                speech_prob = self._model(tensor, self.sample_rate).item()
            
            is_speech = speech_prob > self.threshold
            
            # Track speech state
            if is_speech:
                if not self._speech_started:
                    self._speech_started = True
                    self._silence_frames = 0
                self._speech_buffer.append(audio_frame)
            else:
                if self._speech_started:
                    self._silence_frames += 1
                    
                    # Check if silence duration exceeded
                    silence_ms = (self._silence_frames * len(audio_frame)) / self.sample_rate * 1000
                    if silence_ms > self.min_silence_duration_ms:
                        self._speech_started = False
                        self._silence_frames = 0
            
            return is_speech
            
        except Exception as e:
            print(f"[VADProcessor] Processing error: {e}")
            return False
    
    def get_speech_buffer(self) -> np.ndarray:
        """Get accumulated speech buffer"""
        if not self._speech_buffer:
            return np.array([])
        
        buffer = np.concatenate(self._speech_buffer)
        self._speech_buffer.clear()
        return buffer
    
    def reset(self):
        """Reset VAD state"""
        self._speech_started = False
        self._silence_frames = 0
        self._speech_buffer.clear()

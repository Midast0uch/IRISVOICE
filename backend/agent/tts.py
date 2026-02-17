"""
TTS Manager - Text-to-Speech integration with voice selection and controls
"""
from typing import Optional, Dict, Any
import numpy as np


class TTSManager:
    """
    Manages text-to-speech with voice selection, rate, pitch, and pause controls
    Supports OpenAI TTS voices: Nova, Alloy, Echo, Fable, Onyx, Shimmer
    """
    
    _instance: Optional['TTSManager'] = None
    _initialized: bool = False
    
    # Available voices
    AVAILABLE_VOICES = ["Built-in", "LiquidAI", "Nova", "Alloy", "Echo", "Fable", "Onyx", "Shimmer"]
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if TTSManager._initialized:
            return
        
        # TTS configuration
        self.config = {
            "tts_voice": "LiquidAI",
            "speaking_rate": 1.0,  # 0.5 to 2.0
            "pitch_adjustment": 0,  # -20 to +20 semitones
            "pause_duration": 0.2,  # 0 to 2 seconds
            "voice_cloning_path": None,  # Path to cloned voice sample
        }
        
        # OpenAI client (initialized on demand)
        self._client = None
        
        # Local TTS engine (initialized on demand)
        self._local_engine = None
        
        TTSManager._initialized = True
    
    def update_config(self, **kwargs) -> None:
        """Update TTS configuration"""
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
        print(f"[TTSManager] Updated config: {kwargs}")
    
    def get_config(self) -> Dict[str, Any]:
        """Get current TTS configuration"""
        return self.config.copy()
    
    def _get_client(self):
        """Get or create OpenAI client"""
        if self._client is None:
            try:
                from openai import OpenAI
                # Use environment variable OPENAI_API_KEY
                self._client = OpenAI()
            except ImportError:
                print("[TTSManager] OpenAI package not installed")
                return None
            except Exception as e:
                print(f"[TTSManager] Failed to create OpenAI client: {e}")
                return None
        return self._client
    
    def _get_local_engine(self):
        """Get or create local pyttsx3 engine"""
        if self._local_engine is None:
            try:
                import pyttsx3
                self._local_engine = pyttsx3.init()
                # Configure for faster response
                self._local_engine.setProperty('rate', 175)
                self._local_engine.setProperty('volume', 1.0)
            except Exception as e:
                print(f"[TTSManager] Failed to initialize pyttsx3: {e}")
                return None
        return self._local_engine

    def synthesize(self, text: str) -> Optional[np.ndarray]:
        """
        Synthesize text to audio.
        If voice is "Built-in", uses local pyttsx3 (SAPI5/nsss).
        Otherwise uses OpenAI TTS.
        """
        voice_config = self.config["tts_voice"]
        
        # LOCAL FALLBACK (Built-in)
        if voice_config == "Built-in":
            try:
                print(f"[TTSManager] Using local Built-in voice for: {text[:50]}...")
                engine = self._get_local_engine()
                if not engine:
                    return None
                
                # For local engine, we usually just speak directly, 
                # but to maintain the pipeline we'll try to get the audio data
                # Actually, pyttsx3 doesn't easily return a numpy array without saving to file first
                import tempfile
                import os
                import soundfile as sf
                
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name
                
                engine.save_to_file(text, tmp_path)
                engine.runAndWait()
                
                # Read the saved file
                audio, sample_rate = sf.read(tmp_path)
                os.unlink(tmp_path)
                
                # Resample if needed
                if sample_rate != 16000:
                    import torch
                    import torchaudio.transforms as T
                    audio_tensor = torch.from_numpy(audio).float()
                    if len(audio_tensor.shape) == 1:
                        audio_tensor = audio_tensor.unsqueeze(0)
                    resampler = T.Resample(sample_rate, 16000)
                    audio_tensor = resampler(audio_tensor)
                    audio = audio_tensor.squeeze(0).numpy()
                
                return audio
            except Exception as e:
                print(f"[TTSManager] Local synthesis error: {e}")
                return None

        # OPENAI TTS
        client = self._get_client()
        if not client:
            print("[TTSManager] OpenAI client not available")
            return None
        
        try:
            print(f"[TTSManager] Synthesizing: {text[:50]}...")
            
            # Map our voice names to OpenAI voice names (lowercase)
            voice = self.config["tts_voice"].lower()
            
            # Call OpenAI TTS API
            response = client.audio.speech.create(
                model="tts-1",
                voice=voice,
                input=text,
                speed=self.config["speaking_rate"]
            )
            
            # Get audio data (MP3 format)
            audio_bytes = response.content
            
            # Decode MP3 to numpy array using pydub
            from pydub import AudioSegment
            import io
            
            # Load MP3 from bytes
            audio_segment = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
            
            # Resample to 16kHz to match AudioPipeline
            if audio_segment.frame_rate != 16000:
                print(f"[TTSManager] Resampling from {audio_segment.frame_rate}Hz to 16000Hz")
                audio_segment = audio_segment.set_frame_rate(16000)
            
            # Convert to mono if stereo
            if audio_segment.channels > 1:
                audio_segment = audio_segment.set_channels(1)
            
            # Get raw samples as numpy array (int16)
            samples = np.array(audio_segment.get_array_of_samples(), dtype=np.int16)
            
            # Convert int16 to float32 (-1.0 to 1.0)
            audio = samples.astype(np.float32) / 32768.0
            
            # Apply pitch shift if configured
            if self.config["pitch_adjustment"] != 0:
                audio = self.apply_pitch_shift(audio, self.config["pitch_adjustment"])
            
            print(f"[TTSManager] Generated {len(audio)} samples at {audio_segment.frame_rate}Hz")
            return audio
            
        except ImportError:
            print("[TTSManager] pydub not installed, cannot decode MP3")
            return None
        except Exception as e:
            print(f"[TTSManager] Synthesis error: {e}")
            return None
    
    def synthesize_to_file(self, text: str, output_path: str) -> bool:
        """
        Synthesize text and save to file
        Returns True if successful
        """
        client = self._get_client()
        if not client:
            return False
        
        try:
            voice = self.config["tts_voice"].lower()
            
            response = client.audio.speech.create(
                model="tts-1",
                voice=voice,
                input=text,
                speed=self.config["speaking_rate"]
            )
            
            # Save to file
            response.stream_to_file(output_path)
            print(f"[TTSManager] Saved audio to {output_path}")
            return True
            
        except Exception as e:
            print(f"[TTSManager] Synthesis to file error: {e}")
            return False
    
    def apply_pitch_shift(self, audio: np.ndarray, semitones: int) -> np.ndarray:
        """
        Apply pitch shift to audio
        Uses librosa for pitch shifting
        """
        if semitones == 0:
            return audio
        
        try:
            import librosa
            # Assuming 24kHz sample rate for OpenAI TTS
            return librosa.effects.pitch_shift(
                audio, sr=24000, n_steps=semitones
            )
        except ImportError:
            print("[TTSManager] librosa not installed, pitch shift skipped")
            return audio
        except Exception as e:
            print(f"[TTSManager] Pitch shift error: {e}")
            return audio
    
    def get_voice_info(self) -> Dict[str, Any]:
        """Get information about available voices"""
        return {
            "available_voices": self.AVAILABLE_VOICES,
            "current_voice": self.config["tts_voice"],
            "config": self.config
        }


def get_tts_manager() -> TTSManager:
    """Get the singleton TTSManager instance"""
    return TTSManager()

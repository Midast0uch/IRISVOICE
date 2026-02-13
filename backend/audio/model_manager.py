"""
ModelManager - Manages LFM 2.5 Audio model from HuggingFace
Uses official liquid-audio library for loading and inference
"""
import os
import gc
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import numpy as np
import torch
import torchaudio

try:
    from liquid_audio import LFM2AudioModel, LFM2AudioProcessor, ChatState, LFMModality
    LIQUID_AUDIO_AVAILABLE = True
except ImportError:
    LIQUID_AUDIO_AVAILABLE = False


class ModelManager:
    """
    Manages LFM 2.5 Audio model:
    - Load from HuggingFace (LiquidAI/LFM2.5-Audio-1.5B)
    - Speech-to-Text (ASR)
    - Text-to-Speech (TTS)
    - Speech-to-Speech (Inference)
    """
    
    DEFAULT_MODEL_REPO = "LiquidAI/LFM2.5-Audio-1.5B"
    
    def __init__(self, cache_dir: Optional[str] = None):
        # Model cache directory
        if cache_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            cache_dir = base_dir / "models" / "cache"
        else:
            cache_dir = Path(cache_dir)
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Model components (loaded on demand)
        self.processor = None
        self.model = None
        self._is_loaded = False
        
    @property
    def is_loaded(self) -> bool:
        return self._is_loaded
    
    def get_info(self) -> Dict[str, Any]:
        """Get model status info"""
        return {
            "downloaded": self._check_downloaded(),
            "loaded": self._is_loaded,
            "repo": self.DEFAULT_MODEL_REPO,
            "device": str(self.model.device) if self.model else "not loaded",
            "library": "liquid-audio" if LIQUID_AUDIO_AVAILABLE else "transformers (fallback)"
        }
    
    def _check_downloaded(self) -> bool:
        """Check if model files exist in cache"""
        # Simply check if the directory is not empty for now
        # Official check would be better but let's be pragmatic
        return any(self.cache_dir.iterdir())
    
    def load_model(self) -> bool:
        """
        Load LFM 2.5 Audio model from HuggingFace
        Returns True if successful
        """
        if not LIQUID_AUDIO_AVAILABLE:
            print("[ModelManager] Error: liquid-audio package not found.")
            print("[ModelManager] Run: pip install liquid-audio")
            return self._load_model_transformers_fallback()

        try:
            print(f"[ModelManager] Loading {self.DEFAULT_MODEL_REPO} using liquid-audio...")
            
            # Device selection
            device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if torch.cuda.is_available() else torch.float32
            
            print(f"[ModelManager] Target device: {device}, dtype: {dtype}")
            
            # Load processor and model
            # Note: Explicitly passing device to processor if supported
            try:
                self.processor = LFM2AudioProcessor.from_pretrained(
                    self.DEFAULT_MODEL_REPO,
                    device=device
                )
            except TypeError:
                # Fallback if device is not an argument
                self.processor = LFM2AudioProcessor.from_pretrained(
                    self.DEFAULT_MODEL_REPO
                )
            
            try:
                # Wrap in CPU context just in case
                with torch.device(device):
                    self.model = LFM2AudioModel.from_pretrained(
                        self.DEFAULT_MODEL_REPO,
                        device=device
                    ).eval()
            except TypeError:
                # Fallback if device is not an argument for model
                self.model = LFM2AudioModel.from_pretrained(
                    self.DEFAULT_MODEL_REPO
                ).to(device=device, dtype=dtype).eval()
            
            self._is_loaded = True
            print(f"[ModelManager] Model loaded successfully on {device}")
            return True
            
        except Exception as e:
            import traceback
            print(f"[ModelManager] Failed to load model with liquid-audio: {e}")
            traceback.print_exc()
            return self._load_model_transformers_fallback()

    def _load_model_transformers_fallback(self) -> bool:
        """Fallback to standard transformers if liquid-audio fails"""
        try:
            from transformers import AutoProcessor, AutoModelForCausalLM
            print(f"[ModelManager] Falling back to transformers for {self.DEFAULT_MODEL_REPO}...")
            
            self.processor = AutoProcessor.from_pretrained(
                self.DEFAULT_MODEL_REPO,
                cache_dir=self.cache_dir,
                trust_remote_code=True
            )
            self.model = AutoModelForCausalLM.from_pretrained(
                self.DEFAULT_MODEL_REPO,
                cache_dir=self.cache_dir,
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None,
                trust_remote_code=True
            )
            
            self._is_loaded = True
            print(f"[ModelManager] Model loaded (fallback) successfully")
            return True
        except Exception as e:
            print(f"[ModelManager] Fallback loading failed: {e}")
            return False
    
    def process_stt(self, audio: np.ndarray, sample_rate: int = 16000) -> Optional[str]:
        """
        Speech-to-text (ASR)
        Returns transcribed text or None if failed
        """
        if not self._is_loaded and not self.load_model():
            return None
        
        try:
            if not LIQUID_AUDIO_AVAILABLE:
                return self._process_stt_transformers(audio)

            # Convert to torch tensor
            if isinstance(audio, np.ndarray):
                audio_tensor = torch.from_numpy(audio).float()
            else:
                audio_tensor = audio
                
            # Ensure correct shape (channels, samples)
            if audio_tensor.dim() == 1:
                audio_tensor = audio_tensor.unsqueeze(0)
            
            # Prepare ChatState for ASR
            chat = ChatState(self.processor)
            chat.new_turn("system")
            chat.add_text("Perform ASR.")
            chat.end_turn()
            
            chat.new_turn("user")
            chat.add_audio(audio_tensor, sample_rate)
            chat.end_turn()
            
            chat.new_turn("assistant")
            
            # Generate text
            transcript_parts = []
            for t in self.model.generate_sequential(**chat, max_new_tokens=512):
                if t.numel() == 1:
                    token_text = self.processor.text.decode(t)
                    transcript_parts.append(token_text)
            
            transcript = "".join(transcript_parts).strip()
            return transcript
            
        except Exception as e:
            print(f"[ModelManager] STT failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _process_stt_transformers(self, audio: np.ndarray) -> Optional[str]:
        """STT using transformers (fallback)"""
        try:
            if isinstance(audio, np.ndarray):
                audio = torch.from_numpy(audio)
            if audio.dim() == 1:
                audio = audio.unsqueeze(0)
            
            inputs = self.processor(audio=audio, return_tensors="pt")
            inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
            
            with torch.no_grad():
                output = self.model.generate(**inputs, max_new_tokens=256)
            
            return self.processor.batch_decode(output, skip_special_tokens=True)[0]
        except Exception as e:
            print(f"[ModelManager] Fallback STT failed: {e}")
            return None
    
    def inference(self, audio_input: np.ndarray, mode: str = "conversation", 
                  max_tokens: int = 2048, temperature: float = 0.7) -> Tuple[Optional[np.ndarray], Optional[str]]:
        """
        Run full conversational inference:
        1. Convert speech to text (STT)
        2. Generate response text + audio
        Returns: (output_audio, transcript_text)
        """
        if not self._is_loaded and not self.load_model():
            return None, None
        
        try:
            print(f"[ModelManager] Running inference in {mode} mode...")
            
            # Step 1: Speech-to-text
            transcript = self.process_stt(audio_input)
            if not transcript:
                print("[ModelManager] No transcript from audio")
                return None, None
            
            print(f"[ModelManager] User said: {transcript}")
            
            # Step 2: Generate response audio (Speech-to-Speech style)
            # We can use interleaved for better conversational flow
            response_audio = self.generate_response_audio(transcript, max_tokens, temperature)
            
            return response_audio, transcript
            
        except Exception as e:
            print(f"[ModelManager] Inference error: {e}")
            import traceback
            traceback.print_exc()
            return None, None
    
    def generate_response_audio(self, user_text: str, max_tokens: int = 2048, 
                                temperature: float = 0.7, voice: str = "US male") -> Optional[np.ndarray]:
        """
        Generate conversational audio response to user input (TTS)
        """
        if not self._is_loaded and not self.load_model():
            return None
        
        try:
            if not LIQUID_AUDIO_AVAILABLE:
                return self._generate_audio_transformers(user_text, max_tokens, temperature)

            # Prepare ChatState for TTS
            chat = ChatState(self.processor)
            chat.new_turn("system")
            # Prompts: US male, US female, UK male, UK female
            chat.add_text(f"Perform TTS. Use the {voice} voice.")
            chat.end_turn()
            
            chat.new_turn("user")
            chat.add_text(user_text)
            chat.end_turn()
            
            chat.new_turn("assistant")
            
            # Generate audio tokens
            audio_out = []
            for t in self.model.generate_sequential(
                **chat, 
                max_new_tokens=max_tokens, 
                audio_temperature=temperature, 
                audio_top_k=64
            ):
                if t.numel() > 1:
                    audio_out.append(t)
            
            if not audio_out:
                return None
                
            # Detokenize audio (Mimi returns audio at 24kHz)
            # Remove the last "end-of-audio" codes if any
            audio_codes = torch.stack(audio_out[:-1] if len(audio_out) > 1 else audio_out, 1).unsqueeze(0)
            waveform = self.processor.decode(audio_codes)
            
            # Convert to numpy
            if isinstance(waveform, torch.Tensor):
                waveform = waveform.cpu().numpy()
            
            # Ensure correct shape (1, samples)
            if waveform.ndim == 1:
                waveform = waveform[np.newaxis, :]
            
            print(f"[ModelManager] Generated response audio: {waveform.shape}")
            return waveform
            
        except Exception as e:
            print(f"[ModelManager] Response generation failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _generate_audio_transformers(self, user_text: str, max_tokens: int = 2048, 
                                    temperature: float = 0.7) -> Optional[np.ndarray]:
        """TTS using transformers (fallback)"""
        try:
            conversation_prompt = f"User: {user_text}\nAssistant:"
            inputs = self.processor(text=conversation_prompt, return_tensors="pt")
            inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
            
            with torch.no_grad():
                output = self.model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    do_sample=True
                )
            
            if hasattr(self.processor, 'decode'):
                waveform = self.processor.decode(output)
            else:
                waveform = output.audio_values[0] if hasattr(output, 'audio_values') else output
            
            if isinstance(waveform, torch.Tensor):
                waveform = waveform.cpu().numpy()
            if waveform.ndim == 1:
                waveform = waveform[np.newaxis, :]
            return waveform
        except Exception as e:
            print(f"[ModelManager] Fallback TTS failed: {e}")
            return None
    
    def save_audio(self, audio: np.ndarray, filepath: str, sample_rate: int = 24000):
        """Save audio to file"""
        try:
            if isinstance(audio, np.ndarray):
                audio_tensor = torch.from_numpy(audio)
            else:
                audio_tensor = audio
            
            torchaudio.save(filepath, audio_tensor, sample_rate)
            return True
        except Exception as e:
            print(f"[ModelManager] Failed to save audio: {e}")
            return False
    
    def unload(self):
        """Unload model to free memory"""
        self.processor = None
        self.model = None
        self._is_loaded = False
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print("[ModelManager] Model unloaded")


# ============================================================================
# Download Model Helper
# ============================================================================

async def download_model(repo_id: str = "LiquidAI/LFM2.5-Audio-1.5B", cache_dir: Optional[str] = None) -> bool:
    """
    Download model from HuggingFace without loading it
    Returns True if successful
    """
    try:
        from transformers import AutoProcessor, AutoModel
        
        if cache_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            cache_dir = base_dir / "models" / "cache"
        
        print(f"[ModelManager] Downloading {repo_id}...")
        
        # Download processor and model
        processor = AutoProcessor.from_pretrained(repo_id, cache_dir=cache_dir)
        model = AutoModel.from_pretrained(repo_id, cache_dir=cache_dir)
        
        print(f"[ModelManager] Download complete")
        return True
        
    except Exception as e:
        print(f"[ModelManager] Download failed: {e}")
        return False

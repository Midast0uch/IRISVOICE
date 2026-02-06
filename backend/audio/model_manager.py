"""
ModelManager - Manages LFM 2.5 Audio model from HuggingFace
Uses transformers for loading and inference
"""
import os
from pathlib import Path
from typing import Optional, Dict, Any
import numpy as np
import torch
import torchaudio


class ModelManager:
    """
    Manages LFM 2.5 Audio model:
    - Load from HuggingFace (LiquidAI/LFM2.5-Audio-1.5B)
    - Transformers-based inference
    - Audio tokenization and detokenization
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
            "device": str(self.model.device) if self.model else "not loaded"
        }
    
    def _check_downloaded(self) -> bool:
        """Check if model files exist in cache"""
        try:
            from transformers import AutoProcessor
            processor = AutoProcessor.from_pretrained(
                self.DEFAULT_MODEL_REPO,
                cache_dir=self.cache_dir,
                local_files_only=True
            )
            return processor is not None
        except:
            return False
    
    def load_model(self) -> bool:
        """
        Load LFM 2.5 Audio model from HuggingFace
        Returns True if successful
        """
        try:
            from transformers import AutoProcessor, AutoModel
            
            print(f"[ModelManager] Loading {self.DEFAULT_MODEL_REPO}...")
            
            # Load processor and model
            self.processor = AutoProcessor.from_pretrained(
                self.DEFAULT_MODEL_REPO,
                cache_dir=self.cache_dir
            )
            self.model = AutoModel.from_pretrained(
                self.DEFAULT_MODEL_REPO,
                cache_dir=self.cache_dir,
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None
            )
            
            self._is_loaded = True
            print(f"[ModelManager] Model loaded successfully")
            print(f"[ModelManager] Device: {self.model.device}")
            return True
            
        except ImportError as e:
            print(f"[ModelManager] Missing dependencies: {e}")
            print("[ModelManager] Run: pip install transformers torch torchaudio")
            return False
        except Exception as e:
            print(f"[ModelManager] Failed to load model: {e}")
            return False
    
    def process_stt(self, audio: np.ndarray) -> Optional[str]:
        """
        Speech-to-text (ASR)
        Returns transcribed text or None if failed
        """
        if not self._is_loaded and not self.load_model():
            return None
        
        try:
            # Convert to tensor if needed
            if isinstance(audio, np.ndarray):
                audio = torch.from_numpy(audio)
            
            # Ensure correct shape (batch, samples)
            if audio.dim() == 1:
                audio = audio.unsqueeze(0)
            
            # Process with model for ASR
            inputs = self.processor(audio=audio, return_tensors="pt")
            inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
            
            with torch.no_grad():
                output = self.model.generate(**inputs, max_new_tokens=256)
            
            # Decode text tokens
            text = self.processor.batch_decode(output, skip_special_tokens=True)[0]
            return text
            
        except Exception as e:
            print(f"[ModelManager] STT failed: {e}")
            return None
    
    def inference(self, audio_input: np.ndarray, mode: str = "conversation", 
                  max_tokens: int = 2048, temperature: float = 0.7) -> tuple:
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
            
            # Step 2: Generate response audio
            response_audio = self.generate_response_audio(transcript, max_tokens, temperature)
            
            return response_audio, transcript
            
        except Exception as e:
            print(f"[ModelManager] Inference error: {e}")
            import traceback
            traceback.print_exc()
            return None, None
    
    def generate_response_audio(self, user_text: str, max_tokens: int = 2048, 
                                temperature: float = 0.7) -> Optional[np.ndarray]:
        """
        Generate conversational audio response to user input
        """
        if not self._is_loaded and not self.load_model():
            return None
        
        try:
            # Prepare conversational input
            conversation_prompt = f"User: {user_text}\nAssistant:"
            
            inputs = self.processor(
                text=conversation_prompt, 
                return_tensors="pt"
            )
            inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
            
            # Generate response
            with torch.no_grad():
                output = self.model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    do_sample=True
                )
            
            # Decode audio from response
            if hasattr(self.processor, 'decode'):
                waveform = self.processor.decode(output)
            else:
                # Fallback - try to extract audio from model output
                if hasattr(output, 'audio_values'):
                    waveform = output.audio_values[0]
                else:
                    waveform = output
            
            # Convert to numpy
            if isinstance(waveform, torch.Tensor):
                waveform = waveform.cpu().numpy()
            
            # Ensure correct shape
            if waveform.ndim == 1:
                waveform = waveform[np.newaxis, :]
            
            print(f"[ModelManager] Generated response audio: {waveform.shape}")
            return waveform
            
        except Exception as e:
            print(f"[ModelManager] Response generation failed: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def save_audio(self, audio: np.ndarray, filepath: str, sample_rate: int = 24000):
        """Save audio to file"""
        try:
            if isinstance(audio, np.ndarray):
                audio = torch.from_numpy(audio)
            
            torchaudio.save(filepath, audio, sample_rate)
            return True
        except Exception as e:
            print(f"[ModelManager] Failed to save audio: {e}")
            return False
    
    def unload(self):
        """Unload model to free memory"""
        self.processor = None
        self.model = None
        self._is_loaded = False
        import gc
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

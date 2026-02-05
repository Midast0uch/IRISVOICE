"""
ModelManager - Manages LFM 2.5 Audio model download, loading, and inference
"""
import os
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import httpx
import numpy as np

from .tokenizer import AudioTokenizer, LFM2_5AudioProcessor


class ModelManager:
    """
    Manages LFM 2.5 Audio model:
    - Download from HuggingFace or custom URL
    - GGUF Q4_0 quantization support
    - Model validation and checksums
    - Lazy loading and memory management
    - Audio tokenization and inference
    """
    
    DEFAULT_MODEL_URL = "https://huggingface.co/Lightricks/LFM-2.5-Audio-1.5B-GGUF/resolve/main/lfm-2.5-audio-1.5b-q4_0.gguf"
    DEFAULT_MODEL_FILENAME = "lfm-2.5-audio-1.5b-q4_0.gguf"
    EXPECTED_CHECKSUM = None  # TODO: Add expected SHA256
    
    def __init__(self, model_dir: Optional[str] = None):
        # Model storage directory
        if model_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            model_dir = base_dir / "models"
        else:
            model_dir = Path(model_dir)
        
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        # Model state
        self.model_path: Optional[Path] = None
        self._model = None  # llama_cpp.Llama instance
        self._is_loaded = False
        
        # Audio processing
        self.audio_tokenizer = AudioTokenizer()
        self.audio_processor = LFM2_5AudioProcessor(self.audio_tokenizer)
        
    @property
    def is_loaded(self) -> bool:
        return self._is_loaded
    
    def get_model_path(self) -> Optional[Path]:
        """Get path to downloaded model, or None if not downloaded"""
        model_path = self.model_dir / self.DEFAULT_MODEL_FILENAME
        if model_path.exists():
            return model_path
        return None
    
    async def download_model(
        self,
        url: Optional[str] = None,
        progress_callback: Optional[callable] = None
    ) -> bool:
        """
        Download model from URL
        Returns True if successful
        """
        url = url or self.DEFAULT_MODEL_URL
        model_path = self.model_dir / self.DEFAULT_MODEL_FILENAME
        
        try:
            print(f"[ModelManager] Downloading model from {url}...")
            
            async with httpx.AsyncClient() as client:
                async with client.stream("GET", url, follow_redirects=True) as response:
                    response.raise_for_status()
                    
                    total_size = int(response.headers.get("content-length", 0))
                    downloaded = 0
                    
                    with open(model_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            if progress_callback and total_size > 0:
                                progress = (downloaded / total_size) * 100
                                progress_callback(progress)
            
            print(f"[ModelManager] Model downloaded to {model_path}")
            
            # Validate checksum if available
            if self.EXPECTED_CHECKSUM:
                if not self._validate_checksum(model_path):
                    print("[ModelManager] Checksum validation failed!")
                    model_path.unlink()  # Delete corrupted file
                    return False
            
            return True
            
        except Exception as e:
            print(f"[ModelManager] Download failed: {e}")
            if model_path.exists():
                model_path.unlink()
            return False
    
    def _validate_checksum(self, file_path: Path) -> bool:
        """Validate file SHA256 checksum"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest() == self.EXPECTED_CHECKSUM
    
    def load_model(self, model_path: Optional[str] = None) -> bool:
        """
        Load model into memory using llama-cpp-python
        Returns True if successful
        """
        if self._is_loaded:
            return True
        
        # Find model path
        if model_path:
            model_path = Path(model_path)
        else:
            model_path = self.get_model_path()
        
        if not model_path or not model_path.exists():
            print("[ModelManager] Model not found, please download first")
            return False
        
        try:
            print(f"[ModelManager] Loading model from {model_path}...")
            
            # Import here to avoid dependency if not used
            from llama_cpp import Llama
            
            # Load model with audio-optimized settings
            self._model = Llama(
                model_path=str(model_path),
                n_ctx=4096,  # Context window
                n_threads=os.cpu_count() or 4,
                verbose=False,
            )
            
            self.model_path = model_path
            self._is_loaded = True
            
            print("[ModelManager] Model loaded successfully")
            return True
            
        except ImportError:
            print("[ModelManager] llama-cpp-python not installed")
            return False
        except Exception as e:
            print(f"[ModelManager] Failed to load model: {e}")
            return False
    
    def unload_model(self):
        """Unload model from memory"""
        if self._model:
            del self._model
            self._model = None
        self._is_loaded = False
        print("[ModelManager] Model unloaded")
    
    def inference(
        self,
        audio_input: np.ndarray,
        mode: str = "conversation",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        **kwargs
    ) -> Tuple[Optional[np.ndarray], Optional[str]]:
        """
        Run LFM 2.5 Audio inference on audio input
        
        Args:
            audio_input: Raw audio waveform (numpy array)
            mode: "conversation" or "tool" mode
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            
        Returns:
            - Generated audio (numpy array) or None if error
            - Text transcript of the response or None
        """
        if not self._is_loaded or not self._model:
            print("[ModelManager] Model not loaded")
            return None, None
        
        try:
            print(f"[ModelManager] Running LFM 2.5 Audio inference ({mode} mode)...")
            
            # Step 1: Process audio input
            audio_tokens, gen_kwargs = self.audio_processor.process_audio_input(
                audio=audio_input,
                mode=mode,
                max_tokens=max_tokens,
                temperature=temperature
            )
            
            # Step 2: Format prompt with audio tokens
            prompt = self.audio_processor.format_audio_prompt(
                audio_tokens=audio_tokens,
                mode=mode
            )
            
            # Step 3: Run inference with llama-cpp-python
            response = self._model(
                prompt=prompt,
                max_tokens=gen_kwargs["max_tokens"],
                temperature=gen_kwargs["temperature"],
                stop=gen_kwargs["stop"],
                echo=gen_kwargs["echo"],
            )
            
            # Step 4: Extract generated text
            generated_text = response["choices"][0]["text"]
            print(f"[ModelManager] Generated response (text preview): {generated_text[:100]}...")
            
            # Step 5: Extract audio tokens from response
            output_audio_tokens = self.audio_processor.extract_audio_from_response(generated_text)
            
            if not output_audio_tokens:
                print("[ModelManager] No audio tokens in response")
                return None, generated_text
            
            # Step 6: Decode audio tokens to waveform
            output_audio = self.audio_tokenizer.decode(output_audio_tokens)
            
            print(f"[ModelManager] Inference complete - generated {len(output_audio)} samples")
            return output_audio, generated_text
            
        except Exception as e:
            print(f"[ModelManager] Inference error: {e}")
            import traceback
            traceback.print_exc()
            return None, None
    
    def get_info(self) -> Dict[str, Any]:
        """Get model information"""
        model_path = self.get_model_path()
        
        info = {
            "downloaded": model_path is not None,
            "loaded": self._is_loaded,
            "model_dir": str(self.model_dir),
            "model_path": str(model_path) if model_path else None,
            "filename": self.DEFAULT_MODEL_FILENAME,
        }
        
        if model_path and model_path.exists():
            size_mb = model_path.stat().st_size / (1024 * 1024)
            info["size_mb"] = round(size_mb, 2)
        
        return info

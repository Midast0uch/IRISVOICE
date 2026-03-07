"""
ModelManager - Manages LFM2-Audio native audio processing
Uses official liquid-audio library for end-to-end audio conversation
"""
import os
import gc
import shutil
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import numpy as np
import torch
import torchaudio

try:
    from liquid_audio import LFM2AudioModel, LFM2AudioProcessor, ChatState
    LIQUID_AUDIO_AVAILABLE = True
except ImportError:
    LIQUID_AUDIO_AVAILABLE = False


class ModelManager:
    """
    Manages LFM2-Audio model for native end-to-end audio processing:
    - Load from HuggingFace (LiquidAI/LFM2-Audio-1.5B or LFM2.5-Audio-1.5B)
    - Native audio input/output (no text conversion)
    - ChatState for conversation memory
    - 16kHz input, 24kHz output
    """

    DEFAULT_MODEL_REPO = "LiquidAI/LFM2.5-Audio-1.5B"  # Recommended: faster detokenizer
    # Alternative: "LiquidAI/LFM2-Audio-1.5B" (original)

    def __init__(self, cache_dir: Optional[str] = None, system_prompt: Optional[str] = None):
        # Model cache directory
        if cache_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            cache_dir = base_dir / "models" / "cache"
        else:
            cache_dir = Path(cache_dir)

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # System prompt for ChatState
        if system_prompt is None:
            self.system_prompt = (
                "You are an audio analysis assistant. When given audio input, respond in this EXACT format:\n"
                "[TRANSCRIPT]: <exact word-for-word transcription of what was spoken>\n"
                "[CONTEXT]: <one sentence about the speaker's tone, urgency, and intent>\n"
                "Output only these two lines. Do not add any other text."
            )
        else:
            self.system_prompt = system_prompt

        # Performance optimization parameters
        self._gpu_memory_limit_gb = 8.0  # Limit GPU memory usage
        self._max_tokens = 512  # was 256 — structured output needs room
        self._conversation_turns_limit = 10  # Limit conversation history
        self._processing_lock = threading.Lock()  # Thread safety for model processing
        self._thread_pool = ThreadPoolExecutor(max_workers=2)  # Background processing pool

        # Model components (loaded on demand)
        self.processor = None
        self.model = None
        self._session_chat_states: dict = {}   # session_id -> ChatState
        self._is_loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    def _get_or_create_chat_state(self, session_id: str = "default") -> "ChatState":
        """Get or create a per-session ChatState with the structured system prompt."""
        if session_id not in self._session_chat_states:
            cs = ChatState(self.processor)
            cs.new_turn("system")
            cs.add_text(self.system_prompt)
            cs.end_turn()
            self._session_chat_states[session_id] = cs
            print(f"[ModelManager] New ChatState created for session {session_id}")
        return self._session_chat_states[session_id]

    def _check_system_resources(self) -> dict:
        """Check available RAM and VRAM before loading model."""
        import psutil
        result = {"ram_gb": 0.0, "vram_gb": 0.0, "sufficient": False}
        try:
            vm = psutil.virtual_memory()
            result["ram_gb"] = vm.available / (1024 ** 3)
        except Exception:
            result["ram_gb"] = 4.0  # assume enough if psutil fails

        if torch.cuda.is_available():
            try:
                props = torch.cuda.get_device_properties(0)
                total_vram = props.total_memory / (1024 ** 3)
                reserved = torch.cuda.memory_reserved(0) / (1024 ** 3)
                result["vram_gb"] = total_vram - reserved
            except Exception:
                pass

        # LFM2.5-Audio-1.5B needs ~4GB RAM (CPU) or ~3GB VRAM (GPU)
        if torch.cuda.is_available():
            result["sufficient"] = result["vram_gb"] >= 3.0
        else:
            result["sufficient"] = result["ram_gb"] >= 4.0

        return result

    def get_info(self) -> Dict[str, Any]:
        """Get model status info"""
        return {
            "downloaded": self._check_downloaded(),
            "loaded": self._is_loaded,
            "repo": self.DEFAULT_MODEL_REPO,
            "device": str(self.model.device) if self.model else "not loaded",
            "library": "liquid-audio" if LIQUID_AUDIO_AVAILABLE else "not available",
            "chat_state_active": len(self._session_chat_states) > 0
        }

    def _check_downloaded(self) -> bool:
        """Check if model files exist in cache"""
        # Simply check if the directory is not empty for now
        # Official check would be better but let's be pragmatic
        return any(self.cache_dir.iterdir())

    def _check_for_corrupted_download(self) -> bool:
        """
        Checks if the model cache directory exists but appears to be corrupted
        (e.g., missing essential files like `model.safetensors` or `config.json`).
        """
        if not self.cache_dir.exists() or not any(self.cache_dir.iterdir()):
            return False  # Directory doesn't exist or is empty, not corrupted

        # Look for key files that indicate a successful download
        # These are common for HuggingFace models
        model_files = ["model.safetensors", "pytorch_model.bin", "config.json", "preprocessor_config.json"]

        found_essential_files = False
        for root, _, files in os.walk(self.cache_dir):
            for f in files:
                if f in model_files:
                    found_essential_files = True
                    break
            if found_essential_files:
                break

        # If the directory exists and is not empty, but essential files are missing, it's likely corrupted
        return not found_essential_files

    def _clear_cache(self):
        """Removes the model cache directory."""
        if self.cache_dir.exists():
            print(f"[ModelManager] Clearing cache directory: {self.cache_dir}")
            try:
                shutil.rmtree(self.cache_dir)
                self.cache_dir.mkdir(parents=True, exist_ok=True) # Recreate empty directory
                print("[ModelManager] Cache cleared successfully.")
            except Exception as e:
                print(f"[ModelManager] Error clearing cache: {e}")

    def load_model(self) -> bool:
        """
        Load LFM2-Audio model from HuggingFace
        Returns True if successful
        """
        # Check system resources before loading (low-spec PC guard)
        resources = self._check_system_resources()
        if not resources["sufficient"]:
            if torch.cuda.is_available():
                print(f"[ModelManager] Insufficient VRAM ({resources['vram_gb']:.1f}GB free, need 3GB). Cannot load LFM2-Audio.")
            else:
                print(f"[ModelManager] Insufficient RAM ({resources['ram_gb']:.1f}GB free, need 4GB). Cannot load LFM2-Audio.")
            return False

        # Check if we have a corrupted download (missing model weights)
        if self._check_for_corrupted_download():
            print("[ModelManager] Detected corrupted model download, clearing cache...")
            self._clear_cache()

        if not LIQUID_AUDIO_AVAILABLE:
            print("[ModelManager] Error: liquid-audio package not found.")
            print("[ModelManager] Run: pip install liquid-audio")
            return False

        try:
            print(f"[ModelManager] Loading {self.DEFAULT_MODEL_REPO} using liquid-audio...")

            # Device selection
            device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if device == "cuda" else torch.float32

            # CPU-only override for low-spec: if VRAM < 3GB but CUDA available, use CPU
            if device == "cuda" and resources.get("vram_gb", 0) < 3.0:
                print("[ModelManager] Low VRAM detected — using CPU inference (slower but safe)")
                device = "cpu"
                dtype = torch.float32

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
            print(f"[ModelManager] Per-session ChatState initialized on first use")
            return True

        except Exception as e:
            import traceback
            print(f"[ModelManager] Failed to load model with liquid-audio: {e}")
            traceback.print_exc()
            return False

    async def process_native_audio_async(self, audio_input: np.ndarray, sample_rate: int = 16000, session_id: str = "default") -> Tuple[Optional[np.ndarray], Optional[str]]:
        """
        Asynchronously process native audio input to prevent blocking the main thread.
        Offloads the synchronous, GPU-intensive work to a thread pool.
        """
        if not self.is_loaded:
            print("[ModelManager] Model not loaded, cannot process audio.")
            return None, None

        loop = asyncio.get_running_loop()

        try:
            # Offload the synchronous processing to the thread pool
            result = await loop.run_in_executor(
                self._thread_pool,
                self._process_native_audio_sync,
                audio_input,
                sample_rate,
                session_id
            )
            return result
        except Exception as e:
            print(f"[ModelManager] Async audio processing failed: {e}")
            import traceback
            traceback.print_exc()
            return None, None

    def _process_native_audio_sync(self, audio_input: np.ndarray, sample_rate: int, session_id: str = "default") -> Tuple[Optional[np.ndarray], Optional[str]]:
        """
        Synchronous, thread-safe method for native audio processing.
        Includes GPU memory management, conversation state limiting, and CPU affinity.
        """
        with self._processing_lock:
            if not self._is_loaded:
                return None, None

            try:
                # --- GPU Memory Management & CPU Affinity ---
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    # Limit GPU memory to a fraction to prevent fragmentation
                    torch.cuda.set_per_process_memory_fraction(self._gpu_memory_limit_gb / torch.cuda.get_device_properties(0).total_memory / (1024**3), 0)

                # Get per-session ChatState (replaces shared self.chat_state)
                chat_state = self._get_or_create_chat_state(session_id)

                # --- Conversation History Management ---
                if len(chat_state.conversation_history) > self._conversation_turns_limit * 2:
                    # Preserve system prompt turn, drop oldest conversation turns
                    system_turn = chat_state.conversation_history[:1]
                    recent = chat_state.conversation_history[-(self._conversation_turns_limit * 2):]
                    chat_state.conversation_history = system_turn + recent

                # --- Audio Processing Logic (from original method) ---
                audio_tensor = torch.from_numpy(audio_input).float()
                if audio_tensor.dim() == 1:
                    audio_tensor = audio_tensor.unsqueeze(0)

                chat_state.new_turn("user")
                chat_state.add_audio(audio_tensor, sampling_rate=sample_rate)
                chat_state.end_turn()

                chat_state.new_turn("assistant")

                audio_tokens, text_tokens = [], []
                for token in self.model.generate_interleaved(**chat_state, max_new_tokens=self._max_tokens):
                    if token.numel() > 1: audio_tokens.append(token)
                    else: text_tokens.append(token)

                chat_state.end_turn()

                if not audio_tokens:
                    return None, None

                waveform = self.processor.decode(torch.stack(audio_tokens, 1).unsqueeze(0))
                waveform = waveform.cpu().numpy()
                if waveform.ndim == 1: waveform = waveform[np.newaxis, :]

                # Resample from LFM2-Audio output rate (24kHz) to AudioPipeline rate (16kHz)
                waveform_tensor = torch.from_numpy(waveform).float()
                if waveform_tensor.dim() == 1:
                    waveform_tensor = waveform_tensor.unsqueeze(0)
                waveform_resampled = torchaudio.functional.resample(waveform_tensor, orig_freq=24000, new_freq=16000)
                waveform = waveform_resampled.cpu().numpy()

                debug_text = ""
                if text_tokens:
                    for token in text_tokens:
                        debug_text += self.processor.text.decode(token)

                return waveform, debug_text.strip() if debug_text else None

            except Exception as e:
                print(f"[ModelManager] Sync audio processing failed: {e}")
                import traceback
                traceback.print_exc()
                return None, None
            finally:
                # --- Cleanup ---
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                gc.collect()

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

    def reset_session(self, session_id: str) -> None:
        """Remove ChatState for a session (called on WebSocket disconnect)."""
        self._session_chat_states.pop(session_id, None)
        print(f"[ModelManager] ChatState removed for session {session_id}")

    def reset_conversation(self, session_id: str = "default") -> None:
        """Reset ChatState for a specific session or all sessions."""
        if session_id in self._session_chat_states:
            self._session_chat_states.pop(session_id, None)
            print(f"[ModelManager] ChatState reset for session {session_id}")

    def get_conversation_history(self, session_id: str = "default") -> Optional[str]:
        """Get current conversation history for debugging"""
        cs = self._session_chat_states.get(session_id)
        if cs is not None:
            return f"ChatState active with {len(cs.conversation_history)} turns"
        return None

    def unload(self):
        """Unload model to free memory"""
        self.processor = None
        self.model = None
        self._session_chat_states.clear()
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

#!/usr/bin/env python3
"""
LFM Audio Manager

This module manages the speech-to-speech model using the liquid-audio library.
"""

# Disable symlinks on Windows to avoid permission issues
import os
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"

import io
import logging
import wave
import tempfile
import asyncio
import numpy as np
from typing import Any, Dict, Optional, List
import torch
import torchaudio
import librosa
from liquid_audio.model.lfm2_audio import LFM2AudioModel
from transformers import pipeline

logger = logging.getLogger(__name__)


class LFMAudioManager:
    """
    Manages the liquid-audio speech-to-speech model.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the LFM Audio Manager.

        Args:
            config (Dict[str, Any]): Configuration dictionary.
        """
        self.config = config
        self.model_path = config.get("lfm_model_path", "")
        self.device = config.get("device", "cuda" if torch.cuda.is_available() else "cpu")

        self.stt_pipeline = None
        self.tts_pipeline = None
        self.lfm_model = None
        self.sample_rate = 16000
        self.is_initialized = False
        self.callbacks = {}

    def set_callbacks(self, on_status_change: Any = None, on_transcription_update: Any = None, on_audio_response: Any = None):
        """Set callbacks for status changes, transcription updates, and audio responses."""
        if on_status_change:
            self.callbacks["on_status_change"] = on_status_change
        if on_transcription_update:
            self.callbacks["on_transcription_update"] = on_transcription_update
        if on_audio_response:
            self.callbacks["on_audio_response"] = on_audio_response

    async def initialize(self):
        """Initializes the speech-to-speech model components asynchronously."""
        if self.is_initialized:
            return

        loop = asyncio.get_running_loop()
        try:
            logger.info("[LFMAudioManager] Initializing speech-to-speech models...")
            await loop.run_in_executor(None, self._initialize_models_sync)
            self.is_initialized = True
            logger.info("[LFMAudioManager] All models initialized successfully.")
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error initializing models: {e}")
            raise e

    def _initialize_models_sync(self):
        """Synchronous part of model initialization to be run in an executor."""
        import os
        from huggingface_hub import snapshot_download
        
        # Set up Hugging Face cache directory
        cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
        os.makedirs(cache_dir, exist_ok=True)
        
        # Initialize Speech-to-Text pipeline
        logger.info("[LFMAudioManager] Loading Speech-to-Text model...")
        try:
            # Download model if not cached
            snapshot_download("openai/whisper-base", cache_dir=cache_dir, resume_download=True)
            
            self.stt_pipeline = pipeline(
                "automatic-speech-recognition",
                model="openai/whisper-base",
                device=-1  # Explicitly use CPU
            )
            logger.info("[LFMAudioManager] Speech-to-Text model loaded successfully.")
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error loading Speech-to-Text model: {e}")
            raise e

        # Initialize Text-to-Speech pipeline
        logger.info("[LFMAudioManager] Loading Text-to-Speech model...")
        try:
            # Download model if not cached
            snapshot_download("microsoft/speecht5_tts", cache_dir=cache_dir, resume_download=True)
            snapshot_download("microsoft/speecht5_hifigan", cache_dir=cache_dir, resume_download=True)
            
            self.tts_pipeline = pipeline(
                "text-to-speech",
                model="microsoft/speecht5_tts",
                device=-1  # Explicitly use CPU
            )
            logger.info("[LFMAudioManager] Text-to-Speech model loaded successfully.")
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error loading Text-to-Speech model: {e}")
            raise e

        # Initialize the main LFM model
        logger.info("[LFMAudioManager] Loading Liquid Audio Model...")
        try:
            if self.model_path and self.model_path.strip():
                # Download model if not cached
                snapshot_download(self.model_path, cache_dir=cache_dir, resume_download=True)
                
                self.lfm_model = LFM2AudioModel.from_pretrained(
                    self.model_path,
                    device=self.device
                )
            else:
                logger.info("[LFMAudioManager] No model path provided, using default configuration.")
                # Download model if not cached
                snapshot_download("LiquidAI/LFM2-Audio-1.5B", cache_dir=cache_dir, resume_download=True)
                
                self.lfm_model = LFM2AudioModel.from_pretrained(
                    "LiquidAI/LFM2-Audio-1.5B",
                    device=self.device
                )
            self.lfm_model.to(self.device)
            logger.info("[LFMAudioManager] Liquid Audio Model loaded successfully.")
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error loading Liquid Audio Model: {e}")
            raise e

    def _preprocess_audio(self, audio_data: bytes) -> np.ndarray:
        """
        Preprocesses raw audio data for the STT model.

        Args:
            audio_data (bytes): Raw audio data.

        Returns:
            np.ndarray: Preprocessed audio array.
        """
        try:
            # Convert bytes to numpy array
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # Convert to float32 and normalize
            audio_array = audio_array.astype(np.float32) / 32768.0
            
            # Resample to 16kHz if needed
            if self.sample_rate != 16000:
                audio_array = librosa.resample(
                    audio_array, 
                    orig_sr=self.sample_rate, 
                    target_sr=16000
                )
            
            return audio_array
            
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error preprocessing audio: {e}")
            raise e

    def _postprocess_audio(self, audio_array: np.ndarray) -> bytes:
        """
        Postprocesses audio array for output.

        Args:
            audio_array (np.ndarray): Audio array from TTS.

        Returns:
            bytes: Raw audio data.
        """
        try:
            # Convert to int16
            audio_int16 = (audio_array * 32767).astype(np.int16)
            
            # Create WAV file in memory
            with io.BytesIO() as wav_buffer:
                with wave.open(wav_buffer, 'wb') as wav_file:
                    wav_file.setnchannels(1)  # Mono
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(16000)
                    wav_file.writeframes(audio_int16.tobytes())
                
                return wav_buffer.getvalue()
                
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error postprocessing audio: {e}")
            raise e

    def transcribe_audio(self, audio_data: bytes) -> str:
        """
        Transcribes audio data to text.

        Args:
            audio_data (bytes): Raw audio data.

        Returns:
            str: Transcribed text.
        """
        try:
            # Preprocess audio
            audio_array = self._preprocess_audio(audio_data)
            
            # Transcribe
            result = self.stt_pipeline(audio_array)
            text = result["text"].strip()
            
            logger.info(f"[LFMAudioManager] Transcribed: '{text}'")
            return text
            
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error transcribing audio: {e}")
            raise e

    def generate_response(self, text: str) -> str:
        """
        Generates a response using the LFM model.

        Args:
            text (str): Input text.

        Returns:
            str: Generated response.
        """
        try:
            logger.info(f"[LFMAudioManager] Generating response for: '{text}'")
            
            # For now, use a simple response generation
            # In a full implementation, this would use the LFM model
            response = f"I heard you say: {text}. This is a placeholder response."
            
            logger.info(f"[LFMAudioManager] Generated response: '{response}'")
            return response
            
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error generating response: {e}")
            raise e

    def synthesize_speech(self, text: str) -> bytes:
        """
        Synthesizes text to speech.

        Args:
            text (str): Text to synthesize.

        Returns:
            bytes: Synthesized audio data.
        """
        try:
            logger.info(f"[LFMAudioManager] Synthesizing speech for: '{text}'")
            
            # Synthesize speech
            result = self.tts_pipeline(text)
            audio_array = result["audio"]
            
            # Postprocess
            audio_data = self._postprocess_audio(audio_array)
            
            logger.info("[LFMAudioManager] Speech synthesis complete.")
            return audio_data
            
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error synthesizing speech: {e}")
            raise e

    async def process_audio_stream(self, audio_data: bytes):
        """
        Process audio stream data asynchronously.
        
        Args:
            audio_data (bytes): Raw audio data from the stream.
        """
        try:
            logger.info("[LFMAudioManager] Processing audio stream...")
            
            # Notify status change
            if "on_status_change" in self.callbacks:
                self.callbacks["on_status_change"]("processing")
            
            # Transcribe the audio
            text = self.transcribe_audio(audio_data)
            
            # Notify transcription update
            if "on_transcription_update" in self.callbacks:
                self.callbacks["on_transcription_update"](text)
            
            # Generate response
            response_text = self.generate_response(text)
            
            # Synthesize speech
            response_audio = self.synthesize_speech(response_text)
            
            # Notify audio response
            if "on_audio_response" in self.callbacks:
                self.callbacks["on_audio_response"](response_audio)
            
            # Notify status change back to ready
            if "on_status_change" in self.callbacks:
                self.callbacks["on_status_change"]("ready")
            
            logger.info("[LFMAudioManager] Audio stream processing complete.")
            
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error processing audio stream: {e}")
            if "on_status_change" in self.callbacks:
                self.callbacks["on_status_change"]("error")
            if "on_error" in self.callbacks:
                self.callbacks["on_error"](str(e))

    def process(self, audio_data: bytes) -> bytes:
        """
        Processes incoming audio data through the speech-to-speech pipeline.

        Args:
            audio_data (bytes): Raw audio data from the client.

        Returns:
            bytes: Synthesized audio response.
        """
        try:
            logger.info("[LFMAudioManager] Starting speech-to-speech processing...")
            
            # Step 1: Speech-to-Text
            text = self.transcribe_audio(audio_data)
            
            # Step 2: Generate Response
            response_text = self.generate_response(text)
            
            # Step 3: Text-to-Speech
            response_audio = self.synthesize_speech(response_text)
            
            logger.info("[LFMAudioManager] Speech-to-speech processing complete.")
            return response_audio
            
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error in speech-to-speech processing: {e}")
            # Return empty audio on error
            return b""


_lfm_audio_manager_instance = None

def get_lfm_audio_manager() -> "LFMAudioManager":
    """
    Returns a singleton instance of the LFMAudioManager.
    """
    global _lfm_audio_manager_instance
    if _lfm_audio_manager_instance is None:
        # This is a placeholder for a more robust configuration system
        config = {
            "lfm_model_path": "",  # Will be configured from settings
            "device": "cuda" if torch.cuda.is_available() else "cpu"
        }
        _lfm_audio_manager_instance = LFMAudioManager(config)
    return _lfm_audio_manager_instance
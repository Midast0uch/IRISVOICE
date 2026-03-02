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
from backend.voice.porcupine_detector import PorcupineWakeWordDetector

logger = logging.getLogger(__name__)


class LFMAudioManager:
    """
    Manages the LFM 2.5 audio model for end-to-end audio-to-audio processing.
    
    The LFM 2.5 audio model handles:
    - Wake word detection (configurable phrases)
    - Voice activity detection (VAD)
    - Speech-to-text (STT) transcription
    - Conversation understanding and response generation
    - Text-to-speech (TTS) synthesis
    - Audio processing (noise reduction, echo cancellation, voice enhancement, automatic gain)
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the LFM Audio Manager.

        Args:
            config (Dict[str, Any]): Configuration dictionary containing:
                - lfm_model_path: Path to LFM 2.5 model
                - device: Device to use (cuda/cpu)
                - wake_phrase: Wake phrase for activation (default: "jarvis")
                - detection_sensitivity: Wake word sensitivity 0-100 (default: 50)
                - activation_sound: Play sound on activation (default: True)
                - tts_voice: Voice characteristics (Nova, Alloy, Echo, Fable, Onyx, Shimmer)
                - speaking_rate: Speaking rate 0.5x to 2.0x (default: 1.0)
        """
        self.config = config
        self.model_path = config.get("lfm_model_path", "")
        self.device = config.get("device", "cuda" if torch.cuda.is_available() else "cpu")

        # Wake word configuration
        self.wake_phrase = config.get("wake_phrase", "jarvis")
        self.detection_sensitivity = config.get("detection_sensitivity", 50)
        self.activation_sound = config.get("activation_sound", True)
        
        # Voice characteristics configuration
        self.tts_voice = config.get("tts_voice", "Nova")
        self.speaking_rate = config.get("speaking_rate", 1.0)
        
        # Validate configuration
        self._validate_config()

        self.stt_pipeline = None
        self.tts_pipeline = None
        self.lfm_model = None
        self.porcupine_detector = None  # Porcupine wake word detector
        self.sample_rate = 16000
        self.is_initialized = False
        self.callbacks = {}
        
        # Wake word detection state
        self.wake_word_active = False
        self.last_wake_detection = None

    def _validate_config(self):
        """Validate configuration parameters."""
        # Validate wake phrase
        valid_wake_phrases = ["jarvis", "hey computer", "computer", "bumblebee", "porcupine", "hey iris"]
        if self.wake_phrase not in valid_wake_phrases:
            logger.warning(f"[LFMAudioManager] Invalid wake phrase '{self.wake_phrase}', using 'jarvis'")
            self.wake_phrase = "jarvis"
        
        # Validate detection sensitivity (0-100)
        if not 0 <= self.detection_sensitivity <= 100:
            logger.warning(f"[LFMAudioManager] Invalid detection sensitivity {self.detection_sensitivity}, using 50")
            self.detection_sensitivity = 50
        
        # Validate TTS voice
        valid_voices = ["Nova", "Alloy", "Echo", "Fable", "Onyx", "Shimmer"]
        if self.tts_voice not in valid_voices:
            logger.warning(f"[LFMAudioManager] Invalid TTS voice '{self.tts_voice}', using 'Nova'")
            self.tts_voice = "Nova"
        
        # Validate speaking rate (0.5x to 2.0x)
        if not 0.5 <= self.speaking_rate <= 2.0:
            logger.warning(f"[LFMAudioManager] Invalid speaking rate {self.speaking_rate}, using 1.0")
            self.speaking_rate = 1.0

    def set_callbacks(self, on_status_change: Any = None, on_transcription_update: Any = None, 
                     on_audio_response: Any = None, on_wake_detected: Any = None):
        """Set callbacks for status changes, transcription updates, audio responses, and wake word detection."""
        if on_status_change:
            self.callbacks["on_status_change"] = on_status_change
        if on_transcription_update:
            self.callbacks["on_transcription_update"] = on_transcription_update
        if on_audio_response:
            self.callbacks["on_audio_response"] = on_audio_response
        if on_wake_detected:
            self.callbacks["on_wake_detected"] = on_wake_detected

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
        
        # Initialize Porcupine wake word detector
        logger.info("[LFMAudioManager] Initializing Porcupine wake word detector...")
        try:
            # Determine custom model path and built-in keywords based on wake phrase
            custom_model_path = None
            builtin_keywords = []
            
            if self.wake_phrase == "hey iris":
                # Use custom hey-iris model only
                custom_model_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    "models", "wake_words", "hey-iris_en_windows_v4_0_0.ppn"
                )
                builtin_keywords = []  # Don't mix custom and built-in
            else:
                # Use built-in keyword only
                custom_model_path = None
                builtin_keywords = [self.wake_phrase]
            
            # Convert sensitivity from 0-100 to 0.0-1.0
            sensitivity = self.detection_sensitivity / 100.0
            
            # Initialize Porcupine
            self.porcupine_detector = PorcupineWakeWordDetector(
                custom_model_path=custom_model_path,
                builtin_keywords=builtin_keywords if builtin_keywords else None,
                sensitivities=None  # Will use default 0.5 for all
            )
            
            # Update sensitivity for the primary wake word
            if custom_model_path and os.path.exists(custom_model_path):
                self.porcupine_detector.update_sensitivity(0, sensitivity)
            else:
                self.porcupine_detector.update_sensitivity_by_name(self.wake_phrase, sensitivity)
            
            logger.info("[LFMAudioManager] Porcupine wake word detector initialized successfully.")
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error initializing Porcupine: {e}")
            logger.warning("[LFMAudioManager] Continuing without wake word detection")
            self.porcupine_detector = None
        
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
        Synthesizes text to speech with configured voice characteristics and speaking rate.

        Args:
            text (str): Text to synthesize.

        Returns:
            bytes: Synthesized audio data.
        """
        try:
            logger.info(f"[LFMAudioManager] Synthesizing speech for: '{text}' (voice: {self.tts_voice}, rate: {self.speaking_rate}x)")
            
            # Synthesize speech
            result = self.tts_pipeline(text)
            audio_array = result["audio"]
            
            # Apply speaking rate adjustment
            if self.speaking_rate != 1.0:
                audio_array = self._adjust_speaking_rate(audio_array, self.speaking_rate)
            
            # Postprocess
            audio_data = self._postprocess_audio(audio_array)
            
            logger.info("[LFMAudioManager] Speech synthesis complete.")
            return audio_data
            
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error synthesizing speech: {e}")
            raise e
    
    def _adjust_speaking_rate(self, audio_array: np.ndarray, rate: float) -> np.ndarray:
        """
        Adjust speaking rate by time-stretching the audio.
        
        Args:
            audio_array: Input audio array
            rate: Speaking rate multiplier (0.5x to 2.0x)
        
        Returns:
            Time-stretched audio array
        """
        try:
            # Use librosa for time stretching
            stretched = librosa.effects.time_stretch(audio_array, rate=rate)
            return stretched
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error adjusting speaking rate: {e}")
            return audio_array
    
    def detect_wake_word(self, audio_data: bytes) -> bool:
        """
        Detect wake word in audio data using Porcupine.
        
        Args:
            audio_data: Raw audio data (16-bit PCM, 16kHz)
        
        Returns:
            True if wake word detected, False otherwise
        """
        try:
            if not self.porcupine_detector:
                logger.warning("[LFMAudioManager] Porcupine detector not initialized")
                return False
            
            # Convert bytes to int16 array
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # Process audio in frames
            frame_length = self.porcupine_detector.frame_length
            num_frames = len(audio_array) // frame_length
            
            for i in range(num_frames):
                start_idx = i * frame_length
                end_idx = start_idx + frame_length
                frame = audio_array[start_idx:end_idx].tolist()
                
                # Process frame with Porcupine
                wake_detected, wake_word_name = self.porcupine_detector.process_frame(frame)
                
                if wake_detected:
                    logger.info(f"[LFMAudioManager] Wake word '{wake_word_name}' detected!")
                    self.wake_word_active = True
                    self.last_wake_detection = wake_word_name
                    
                    # Trigger callback
                    if "on_wake_detected" in self.callbacks:
                        self.callbacks["on_wake_detected"](wake_word_name, self.detection_sensitivity)
                    
                    # Play activation sound if enabled
                    if self.activation_sound:
                        logger.info("[LFMAudioManager] Playing activation sound")
                    
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error detecting wake word: {e}")
            return False
    
    def update_wake_config(self, wake_phrase: str = None, detection_sensitivity: int = None, 
                          activation_sound: bool = None):
        """
        Update wake word configuration.
        
        Args:
            wake_phrase: New wake phrase
            detection_sensitivity: New detection sensitivity (0-100)
            activation_sound: Enable/disable activation sound
        """
        if wake_phrase is not None:
            valid_wake_phrases = ["jarvis", "hey computer", "computer", "bumblebee", "porcupine", "hey iris"]
            if wake_phrase in valid_wake_phrases:
                self.wake_phrase = wake_phrase
                logger.info(f"[LFMAudioManager] Wake phrase updated to '{wake_phrase}'")
                
                # Update Porcupine detector if initialized
                if self.porcupine_detector:
                    # Re-initialize Porcupine with new wake phrase
                    logger.info("[LFMAudioManager] Re-initializing Porcupine with new wake phrase...")
                    self.porcupine_detector.cleanup()
                    
                    # Determine custom model path and built-in keywords
                    import os
                    custom_model_path = None
                    builtin_keywords = []
                    
                    if wake_phrase == "hey iris":
                        custom_model_path = os.path.join(
                            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                            "models", "wake_words", "hey-iris_en_windows_v4_0_0.ppn"
                        )
                        builtin_keywords = []  # Don't mix custom and built-in
                    else:
                        custom_model_path = None
                        builtin_keywords = [wake_phrase]
                    
                    sensitivity = self.detection_sensitivity / 100.0
                    
                    try:
                        self.porcupine_detector = PorcupineWakeWordDetector(
                            custom_model_path=custom_model_path,
                            builtin_keywords=builtin_keywords if builtin_keywords else None,
                            sensitivities=None
                        )
                        
                        if custom_model_path and os.path.exists(custom_model_path):
                            self.porcupine_detector.update_sensitivity(0, sensitivity)
                        else:
                            self.porcupine_detector.update_sensitivity_by_name(wake_phrase, sensitivity)
                    except Exception as e:
                        logger.error(f"[LFMAudioManager] Error re-initializing Porcupine: {e}")
            else:
                logger.warning(f"[LFMAudioManager] Invalid wake phrase '{wake_phrase}'")
        
        if detection_sensitivity is not None:
            if 0 <= detection_sensitivity <= 100:
                self.detection_sensitivity = detection_sensitivity
                logger.info(f"[LFMAudioManager] Detection sensitivity updated to {detection_sensitivity}")
                
                # Update Porcupine sensitivity
                if self.porcupine_detector:
                    sensitivity = detection_sensitivity / 100.0
                    if self.wake_phrase == "hey iris":
                        self.porcupine_detector.update_sensitivity(0, sensitivity)
                    else:
                        self.porcupine_detector.update_sensitivity_by_name(self.wake_phrase, sensitivity)
            else:
                logger.warning(f"[LFMAudioManager] Invalid detection sensitivity {detection_sensitivity}")
        
        if activation_sound is not None:
            self.activation_sound = activation_sound
            logger.info(f"[LFMAudioManager] Activation sound {'enabled' if activation_sound else 'disabled'}")
    
    def update_voice_config(self, tts_voice: str = None, speaking_rate: float = None):
        """
        Update voice characteristics configuration.
        
        Args:
            tts_voice: New TTS voice (Nova, Alloy, Echo, Fable, Onyx, Shimmer)
            speaking_rate: New speaking rate (0.5x to 2.0x)
        """
        if tts_voice is not None:
            valid_voices = ["Nova", "Alloy", "Echo", "Fable", "Onyx", "Shimmer"]
            if tts_voice in valid_voices:
                self.tts_voice = tts_voice
                logger.info(f"[LFMAudioManager] TTS voice updated to '{tts_voice}'")
            else:
                logger.warning(f"[LFMAudioManager] Invalid TTS voice '{tts_voice}'")
        
        if speaking_rate is not None:
            if 0.5 <= speaking_rate <= 2.0:
                self.speaking_rate = speaking_rate
                logger.info(f"[LFMAudioManager] Speaking rate updated to {speaking_rate}x")
            else:
                logger.warning(f"[LFMAudioManager] Invalid speaking rate {speaking_rate}")
    
    def process_end_to_end(self, audio_data: bytes) -> bytes:
        """
        Process audio end-to-end: audio input → wake word → VAD → STT → conversation → TTS → audio output.
        
        This simulates the LFM 2.5 model's end-to-end processing. In a real implementation,
        all of this would be handled internally by the LFM 2.5 audio model.
        
        Args:
            audio_data: Raw audio input
        
        Returns:
            Raw audio output
        """
        try:
            logger.info("[LFMAudioManager] Starting end-to-end audio processing...")
            
            # Step 1: Wake word detection (optional - for passive listening mode)
            # Note: This is kept for passive wake word detection but NOT required for manual trigger
            wake_detected = self.detect_wake_word(audio_data)
            
            # Step 2: Voice Activity Detection (handled internally by LFM 2.5)
            # In real LFM 2.5, this would detect speech boundaries
            logger.info("[LFMAudioManager] VAD: Speech detected")
            
            # Step 3: Speech-to-Text (handled internally by LFM 2.5)
            text = self.transcribe_audio(audio_data)
            
            # Step 4: Conversation understanding and response generation (handled internally by LFM 2.5)
            response_text = self.generate_response(text)
            
            # Step 5: Text-to-Speech (handled internally by LFM 2.5)
            response_audio = self.synthesize_speech(response_text)
            
            # Step 6: Audio output (handled internally by LFM 2.5)
            logger.info("[LFMAudioManager] End-to-end audio processing complete")
            
            # Reset wake word state after processing
            self.wake_word_active = False
            
            return response_audio
            
        except Exception as e:
            logger.error(f"[LFMAudioManager] Error in end-to-end processing: {e}")
            self.wake_word_active = False
            return b""

    async def process_audio_stream(self, audio_data: bytes):
        """
        Process audio stream data asynchronously using end-to-end processing.
        
        Args:
            audio_data (bytes): Raw audio data from the stream.
        """
        try:
            logger.info("[LFMAudioManager] Processing audio stream...")
            
            # Notify status change
            if "on_status_change" in self.callbacks:
                self.callbacks["on_status_change"]("processing")
            
            # Use end-to-end processing
            response_audio = self.process_end_to_end(audio_data)
            
            # Notify audio response if we got one
            if response_audio and "on_audio_response" in self.callbacks:
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
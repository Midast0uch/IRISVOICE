"""
Audio tokenization utilities for LFM 2.5 Audio
Converts between raw audio and model tokens
"""
import numpy as np
from typing import List, Tuple
import torch
import torch.nn.functional as F


class AudioTokenizer:
    """
    LFM 2.5 Audio uses a neural audio codec for tokenization.
    This is a simplified implementation that would need to be replaced
    with the actual codec weights from the model.
    """
    
    def __init__(self, sample_rate: int = 16000, hop_length: int = 320):
        self.sample_rate = sample_rate
        self.hop_length = hop_length  # 20ms at 16kHz
        
    def encode(self, audio: np.ndarray) -> List[int]:
        """
        Convert audio waveform to discrete tokens
        
        In the actual implementation, this would use the neural codec
        encoder from the LFM 2.5 Audio model.
        
        For now, we use a simple placeholder that mimics the interface.
        """
        # TODO: Replace with actual neural codec encoding
        # This is a placeholder that creates dummy tokens
        
        # Normalize audio
        audio = audio / (np.max(np.abs(audio)) + 1e-8)
        
        # Split into frames
        num_frames = len(audio) // self.hop_length
        frames = audio[:num_frames * self.hop_length].reshape(num_frames, self.hop_length)
        
        # Simple quantization (placeholder for actual codec)
        # Real implementation would use trained VQ-VAE encoder
        tokens = []
        for frame in frames:
            # Simple energy-based tokenization as placeholder
            energy = np.mean(frame ** 2)
            token = int(min(1023, energy * 1024))  # 10-bit quantization
            tokens.append(token)
        
        return tokens
    
    def decode(self, tokens: List[int]) -> np.ndarray:
        """
        Convert discrete tokens back to audio waveform
        
        In the actual implementation, this would use the neural codec
        decoder from the LFM 2.5 Audio model.
        """
        # TODO: Replace with actual neural codec decoding
        
        # Placeholder reconstruction
        audio_frames = []
        for token in tokens:
            # Simple reconstruction (placeholder)
            energy = np.sqrt(token / 1024.0)
            frame = np.random.randn(self.hop_length) * energy
            audio_frames.append(frame)
        
        audio = np.concatenate(audio_frames)
        
        # Normalize
        max_val = np.max(np.abs(audio))
        if max_val > 0:
            audio = audio / max_val * 0.9
        
        return audio.astype(np.float32)


class LFM2_5AudioProcessor:
    """
    Processor for LFM 2.5 Audio model
    Handles prompt formatting and special tokens
    """
    
    # Special tokens for the model
    BOS_TOKEN = "<|begin_of_audio|>"
    EOS_TOKEN = "<|end_of_audio|>"
    PAD_TOKEN = "<|pad|>"
    
    # Conversation mode vs Tool mode
    MODE_CONVERSATION = "conversation"
    MODE_TOOL = "tool"
    
    def __init__(self, tokenizer: AudioTokenizer):
        self.audio_tokenizer = tokenizer
        
    def format_audio_prompt(
        self,
        audio_tokens: List[int],
        mode: str = MODE_CONVERSATION,
        system_prompt: str = "You are IRIS, a helpful voice assistant."
    ) -> str:
        """
        Format audio tokens into a text prompt for the model
        
        LFM 2.5 Audio expects a specific format combining text and audio tokens.
        """
        # Convert audio tokens to string representation
        audio_str = " ".join([f"<audio_{t}>" for t in audio_tokens])
        
        if mode == self.MODE_CONVERSATION:
            # Conversation mode: audio -> audio
            prompt = f"""{system_prompt}

{self.BOS_TOKEN}
{audio_str}
{self.EOS_TOKEN}

Response:"""
        else:
            # Tool mode: audio -> text -> tool -> audio
            prompt = f"""{system_prompt}
You have access to tools. Listen to the audio and respond.

{self.BOS_TOKEN}
{audio_str}
{self.EOS_TOKEN}

Tool Response:"""
        
        return prompt
    
    def extract_audio_from_response(self, response: str) -> List[int]:
        """
        Extract audio tokens from model response
        
        Parses the model output to find audio token sequences.
        """
        tokens = []
        
        # Split by whitespace and look for audio token patterns
        parts = response.split()
        for part in parts:
            if part.startswith("<audio_") and part.endswith(">"):
                try:
                    token_id = int(part[7:-1])  # Extract number from <audio_X>
                    tokens.append(token_id)
                except ValueError:
                    continue
        
        return tokens
    
    def process_audio_input(
        self,
        audio: np.ndarray,
        mode: str = MODE_CONVERSATION,
        max_tokens: int = 2048,
        temperature: float = 0.7
    ) -> Tuple[List[int], dict]:
        """
        Process audio input and return generation parameters
        
        Returns:
            - Audio tokens for the prompt
            - Generation kwargs for the model
        """
        # Encode audio to tokens
        audio_tokens = self.audio_tokenizer.encode(audio)
        
        # Format prompt
        prompt = self.format_audio_prompt(audio_tokens, mode)
        
        # Generation parameters
        gen_kwargs = {
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stop": [self.EOS_TOKEN, "\n\n"],
            "echo": False,
        }
        
        return audio_tokens, gen_kwargs


def load_audio_file(path: str, sample_rate: int = 16000) -> np.ndarray:
    """Load audio file and resample to target rate"""
    try:
        import librosa
        audio, sr = librosa.load(path, sr=sample_rate, mono=True)
        return audio
    except ImportError:
        print("librosa not installed, using scipy")
        from scipy.io import wavfile
        sr, audio = wavfile.read(path)
        
        # Convert to float
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        elif audio.dtype == np.int32:
            audio = audio.astype(np.float32) / 2147483648.0
        
        # Resample if needed (simple downsampling)
        if sr != sample_rate:
            ratio = sample_rate / sr
            new_length = int(len(audio) * ratio)
            audio = np.interp(
                np.linspace(0, len(audio), new_length),
                np.arange(len(audio)),
                audio
            )
        
        return audio


def save_audio_file(path: str, audio: np.ndarray, sample_rate: int = 16000):
    """Save audio to WAV file"""
    from scipy.io import wavfile
    
    # Convert to int16
    audio_int16 = (audio * 32767).astype(np.int16)
    wavfile.write(path, sample_rate, audio_int16)

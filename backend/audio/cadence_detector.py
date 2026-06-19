"""
CadenceDetector — spectral flux cadence detector for the STT pipeline.

Spectral flux = sum of positive differences between consecutive FFT frames.
High flux = spectral change = speech onset (syllable beat).
Low flux = spectral stability = silence or sustained vowel.

Produces a smoothed 0-1 envelope that tracks speech rhythm,
independent of volume. Whispers produce cadence beats without RMS.

Used by VoiceCommandHandler to send cadence data alongside RMS in the
audio_envelope WS message, so XurOrb can breathe with speech rhythm.
"""

import numpy as np
from collections import deque
import logging

logger = logging.getLogger(__name__)


class CadenceDetector:
    """
    Spectral flux cadence detector.

    Processes raw float32 audio chunks and returns a smoothed 0-1 envelope
    that tracks speech rhythm. The envelope is independent of volume —
    whispers produce cadence beats without RMS.
    """

    def __init__(self, sample_rate: int = 16000, fft_size: int = 512, hop_size: int = 256):
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.hop_size = hop_size
        self.prev_spectrum: np.ndarray | None = None
        self.envelope: float = 0.0          # smoothed output (0-1)
        self.smoothing: float = 0.85        # EMA smoothing factor
        self.flux_history: deque = deque(maxlen=10)  # for normalization

    def process(self, audio_chunk: np.ndarray) -> float:
        """
        Process a chunk of float32 audio samples.
        Returns cadence level 0-1.

        Args:
            audio_chunk: float32 numpy array of audio samples (-1.0 to 1.0)

        Returns:
            Smoothed cadence envelope value (0.0 to 1.0)
        """
        if len(audio_chunk) < self.hop_size:
            return self.envelope

        # Ensure we have enough samples for the FFT window
        if len(audio_chunk) < self.fft_size:
            # Pad with zeros if chunk is smaller than FFT size
            audio_chunk = np.pad(audio_chunk, (0, self.fft_size - len(audio_chunk)))

        # Apply Hann window
        windowed = audio_chunk[:self.fft_size] * np.hanning(self.fft_size)

        # Compute FFT (magnitude spectrum)
        spectrum = np.abs(np.fft.rfft(windowed))

        if self.prev_spectrum is None:
            self.prev_spectrum = spectrum
            return 0.0

        # Spectral flux: sum of positive differences
        diff = spectrum - self.prev_spectrum
        flux = float(np.sum(np.maximum(diff, 0.0)))
        self.prev_spectrum = spectrum.copy()

        # Normalize using rolling history
        self.flux_history.append(flux)
        max_flux = max(self.flux_history) if self.flux_history else 1.0
        normalized = min(flux / (max_flux + 1e-6), 1.0)

        # Smooth with exponential moving average
        self.envelope = self.smoothing * self.envelope + (1 - self.smoothing) * normalized

        return self.envelope

    def reset(self) -> None:
        """Reset state when recording starts/stops."""
        self.prev_spectrum = None
        self.envelope = 0.0
        self.flux_history.clear()

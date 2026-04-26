"""
TTS Speaker Registration Tests

Tests that CosyVoice2-0.5B correctly registers TOMV2.wav as the 'tommv2'
speaker via add_zero_shot_spk so subsequent calls skip WAV re-encoding.
"""
import sys
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add IRISVOICE to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.agent.tts import TTSManager, SPK_ID


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the TTSManager singleton between tests."""
    TTSManager._instance = None
    TTSManager._initialized = False
    yield
    TTSManager._instance = None
    TTSManager._initialized = False


def test_speaker_registered_after_load():
    """After _load_cosyvoice succeeds, _spk_registered should be True."""
    mgr = TTSManager()

    mock_model = MagicMock()
    mock_model.sample_rate = 24000
    mock_model.add_zero_shot_spk.return_value = True

    with patch("backend.agent.tts.MODEL_DIR") as mock_dir, \
         patch("backend.agent.tts.REFERENCE_AUDIO") as mock_ref, \
         patch("backend.agent.tts.AutoModel" if False else "builtins.__import__"):

        # Simulate model dir and reference audio existing
        mock_dir.exists.return_value = True
        mock_ref.exists.return_value = True

        with patch.object(mgr, "_cosyvoice", None), \
             patch("backend.agent.tts.MODEL_DIR") as md, \
             patch("backend.agent.tts.REFERENCE_AUDIO") as ra:

            md.exists.return_value = True
            ra.exists.return_value = True
            ra.__str__ = lambda self: "TOMV2.wav"

            # Inject mock model directly
            mgr._cosyvoice = mock_model
            mgr._register_speaker()

            assert mgr._spk_registered is True
            mock_model.add_zero_shot_spk.assert_called_once_with("", str(ra), SPK_ID)


def test_speaker_not_registered_when_ref_missing():
    """If TOMV2.wav does not exist, _spk_registered stays False."""
    mgr = TTSManager()
    mock_model = MagicMock()
    mgr._cosyvoice = mock_model

    with patch("backend.agent.tts.REFERENCE_AUDIO") as mock_ref:
        mock_ref.exists.return_value = False
        mgr._register_speaker()

    assert mgr._spk_registered is False
    mock_model.add_zero_shot_spk.assert_not_called()


def test_ready_event_set_after_warmup():
    """_ready_event must be set after _warm_vibevoice_pipeline completes."""
    mgr = TTSManager()

    with patch.object(mgr, "_load_cosyvoice", return_value=True):
        mgr._warm_vibevoice_pipeline()
        # Give the daemon thread time to run
        mgr._ready_event.wait(timeout=5)

    assert mgr._ready_event.is_set()


def test_singleton_preserved_across_calls():
    """get_tts_manager() returns the same instance every call."""
    from backend.agent.tts import get_tts_manager
    assert get_tts_manager() is get_tts_manager()

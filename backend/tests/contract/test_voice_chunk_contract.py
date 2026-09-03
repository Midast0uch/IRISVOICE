"""
test_voice_chunk_contract.py — Contract test for TTS chunk size (T3.5 / REQ-12).

CU-?: The chunk size is derived from |u| (abs(sig.u_current)), not force_magnitude.
This is a contract test: it asserts the structural property that
get_tts_chunk_size reads u_current, not force_magnitude.
"""

import pytest


class TestChunkFromUContract:
    """REQ-12 AC: chunk size derives from |u|, not force_magnitude."""

    def test_chunk_size_from_u_is_static(self):
        """_chunk_size_from_u is a static method — callable without instance."""
        from backend.agent.conversation_kernel import ConversationKernel

        _size = ConversationKernel._chunk_size_from_u(0.0)
        assert isinstance(_size, int)
        assert 0 < _size <= 200

    def test_chunk_size_derived_from_u_current(self):
        """get_tts_chunk_size uses sig.u_current (|u|) internally.

        This is a source-code contract check: the method body reads
        sig.u_current (via abs(sig.u_current)), not sig.force_magnitude.
        We verify by inspecting the source rather than running live,
        because the latter requires a C++ engine.
        """
        import inspect
        import textwrap

        from backend.agent import conversation_kernel as _mod

        _src = textwrap.dedent(inspect.getsource(_mod.ConversationKernel.get_tts_chunk_size))
        # The method must reference u_current (not force_magnitude) as the
        # primary signal for chunk sizing.
        assert "u_current" in _src, (
            "get_tts_chunk_size must read u_current (REQ-12); "
            "got source without u_current reference"
        )
        # Ensure force_magnitude is NOT used for chunk sizing
        # (The removed pattern was: raw = int(sig.force_magnitude * TTS_CHUNK_SCALE))
        _removed_pattern = "sig.force_magnitude * TTS_CHUNK_SCALE"
        assert _removed_pattern not in _src, (
            "get_tts_chunk_size must NOT use force_magnitude for chunk sizing; "
            "the removed pattern 'sig.force_magnitude * TTS_CHUNK_SCALE' is still present"
        )

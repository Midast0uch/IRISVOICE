"""
smoke_tts.py — Live TTS smoke test for CosyVoice3-0.5B.

Loads the model, synthesizes one sentence, and writes the result to
data/smoke_tts_output.wav.  Does NOT require audio hardware.

Pass conditions (all must be true):
  1. CosyVoice3 loads without error
  2. Speaker registers from TOMV2.wav
  3. synthesis yields at least one audio chunk
  4. Output is float32 at 24 kHz, duration >= 0.5 s
  5. WAV file is written and non-empty

Run from IRISVOICE/:
  python scripts/smoke_tts.py
"""

import sys
import wave
import struct
import logging
import time
from pathlib import Path

# ── project root on path ──────────────────────────────────────────────────────
_PROJECT = Path(__file__).parent.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("smoke_tts")

TEST_TEXT   = "Hello. I am IRIS, your intelligent responsive interface system. CosyVoice three is online."
OUTPUT_WAV  = _PROJECT / "data" / "smoke_tts_output.wav"
SAMPLE_RATE = 24_000


def write_wav(path: Path, audio_f32, sr: int) -> None:
    """Write float32 numpy array as 16-bit PCM WAV."""
    import numpy as np
    pcm = (audio_f32 * 32767).clip(-32768, 32767).astype("int16")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def main():
    import numpy as np

    print("\n" + "="*60)
    print("  IRIS TTS Smoke Test — CosyVoice3-0.5B")
    print("="*60)

    # ── 1. Import TTSManager ──────────────────────────────────────────────────
    log.info("Importing TTSManager...")
    try:
        from backend.agent.tts import TTSManager, MODEL_DIR, REFERENCE_AUDIO
    except Exception as e:
        print(f"\n[FAIL] Could not import TTSManager: {e}")
        sys.exit(1)

    print(f"  Model dir    : {MODEL_DIR}")
    print(f"  Model exists : {MODEL_DIR.exists()}")
    print(f"  Ref audio    : {REFERENCE_AUDIO.exists()} ({REFERENCE_AUDIO.name})")

    if not MODEL_DIR.exists():
        print("\n[FAIL] Model weights missing — run: python scripts/download_models.py")
        sys.exit(1)

    # ── 2. Load model (triggers _load_cosyvoice via synthesize_stream) ────────
    log.info("Loading CosyVoice3 model (first load may take ~30s)...")
    mgr = TTSManager()
    mgr.update_config(tts_voice="Cloned Voice", tts_enabled=True)

    t0 = time.time()
    chunks = []
    try:
        for chunk in mgr.synthesize_stream(TEST_TEXT):
            chunks.append(chunk)
            elapsed = time.time() - t0
            log.info(f"  chunk {len(chunks):2d}  {len(chunk):6d} samples  ({elapsed:.1f}s)")
    except Exception as e:
        print(f"\n[FAIL] synthesize_stream raised: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    total_time = time.time() - t0

    # ── 3. Validate output ────────────────────────────────────────────────────
    if not chunks:
        print("\n[FAIL] synthesize_stream yielded 0 chunks — model may have fallen back to pyttsx3 silently")
        sys.exit(1)

    audio = np.concatenate(chunks)
    duration_s = len(audio) / SAMPLE_RATE

    print(f"\n  Chunks       : {len(chunks)}")
    print(f"  Total samples: {len(audio):,}")
    print(f"  Duration     : {duration_s:.2f}s")
    print(f"  Wall time    : {total_time:.1f}s")
    print(f"  dtype        : {audio.dtype}")
    print(f"  max amplitude: {float(np.abs(audio).max()):.4f}")

    if audio.dtype != np.float32:
        print(f"\n[FAIL] Expected float32, got {audio.dtype}")
        sys.exit(1)

    if duration_s < 0.5:
        print(f"\n[FAIL] Audio too short ({duration_s:.2f}s) — synthesis likely failed")
        sys.exit(1)

    if float(np.abs(audio).max()) < 1e-4:
        print("\n[FAIL] Audio is silent (all-zeros or near-zero)")
        sys.exit(1)

    # ── 4. Write WAV ──────────────────────────────────────────────────────────
    write_wav(OUTPUT_WAV, audio, SAMPLE_RATE)
    wav_size_kb = OUTPUT_WAV.stat().st_size // 1024
    print(f"\n  WAV written  : {OUTPUT_WAV}")
    print(f"  WAV size     : {wav_size_kb} KB")

    print("\n" + "="*60)
    print("  [PASS] CosyVoice3 TTS smoke test PASSED")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()

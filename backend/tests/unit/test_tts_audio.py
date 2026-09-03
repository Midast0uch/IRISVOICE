"""Quick TTS audio test — plays audio so user can verify quality.

Usage: python -m backend.tests.test_tts_audio
"""
import os, sys, time, tempfile, struct, wave

os.environ.setdefault("IRIS_ENV", "development")

def main():
    print("[1] Loading Pocket-TTS model (language=english)...")
    from pocket_tts import TTSModel
    t0 = time.monotonic()
    model = TTSModel.load_model(language="english", eos_threshold=-1.0)
    dt = time.monotonic() - t0
    print(f"    Model loaded in {dt:.1f}s")
    sr = model.sample_rate

    # Load voice state from reference audio if available
    ref_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "TOMV2.wav")
    voice_state = None
    if os.path.exists(ref_path):
        print(f"[2] Loading voice from {ref_path}...")
        voice_state = model.get_state_for_audio_prompt(ref_path)
        print("    Voice state loaded")
    else:
        print("[2] No reference audio found or no voice cloning — using default voice")

    test_text = "Hello, this is a test of the Pocket TTS audio quality. How does this sound?"
    print(f"[3] Generating speech: '{test_text}'")
    t0 = time.monotonic()
    
    # Collect streaming chunks like the real code does
    import numpy as np
    chunks = []
    for chunk in model.generate_audio_stream(voice_state, test_text, frames_after_eos=0):
        audio = chunk.cpu().numpy().astype(np.float32)
        audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
        if np.max(np.abs(audio)) < 0.01:
            continue
        chunks.append(audio)
    
    dt = time.monotonic() - t0
    total = np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)
    print(f"    Generated in {dt:.1f}s, {len(total)} samples, {len(total)/sr:.1f}s of audio")

    if len(total) == 0:
        print("    ERROR: No audio generated!")
        return

    # Save as WAV
    out_path = os.path.join(tempfile.gettempdir(), "iris_tts_test.wav")
    int16_audio = np.clip(total * 32767, -32768, 32767).astype(np.int16)
    with wave.open(out_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(int16_audio.tobytes())
    print(f"[4] Saved to {out_path}")
    print(f"[5] Playing audio...")
    
    import winsound
    winsound.PlaySound(out_path, winsound.SND_FILENAME)
    print("[6] Done. How was the quality?")

if __name__ == "__main__":
    main()

# Voice Cloning Reference Audio

Pocket-TTS needs a reference audio file for zero-shot voice cloning. This is
the file it clones — put a clean 6–30 second WAV of the voice you want IRIS
to speak with, ideally a single speaker, no background noise, no music.

## Setup

1. Record or export a WAV file of your chosen voice. Tips:
   - Mono, 16-bit or 24-bit PCM
   - 16 kHz or 24 kHz sample rate (Pocket-TTS resamples internally)
   - 6–30 seconds of natural speech
   - No background music, no other speakers, minimal reverb
   - WAV format (not MP3 — Pocket-TTS expects PCM)

2. Save it as one of these filenames (Pocket-TTS checks in this order):
   - `data/TOMV2.wav` (default, matches the original reference name)
   - `data/voice_clone_ref.wav` (alternative name)

3. Restart the backend. Pocket-TTS will detect the file and use it for the
   "Cloned Voice" preset in Settings.

## Important

- **This file is gitignored.** The repository does not include anyone's voice
  reference audio. You must supply your own.
- The file is loaded at first "Cloned Voice" synthesis and cached in memory
  for the lifetime of the backend process.
- If the file is missing, Pocket-TTS falls back to its built-in speaker
  presets (alba, marius, jean, etc.) — you can still use TTS without a
  reference file.

## Sample sources

- Your own recordings (Audacity, OBS, phone voice memos exported as WAV)
- Public domain audiobook readings (check license before redistributing)
- LibriVox speakers (public domain)

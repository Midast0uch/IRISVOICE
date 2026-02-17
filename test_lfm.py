#!/usr/bin/env python3
"""Test LFM model loading to see what's failing"""

import sys
import traceback

# Test 1: Check if liquid-audio is available
print("=== Testing liquid-audio availability ===")
try:
    from liquid_audio import LFM2AudioModel, LFM2AudioProcessor
    print("✅ liquid-audio package FOUND")
    LIQUID_AUDIO_AVAILABLE = True
except ImportError as e:
    print(f"❌ liquid-audio NOT available: {e}")
    LIQUID_AUDIO_AVAILABLE = False

# Test 2: Check transformers (fallback)
print("\n=== Testing transformers availability ===")
try:
    from transformers import AutoProcessor, AutoModelForCausalLM
    print("✅ transformers package FOUND")
    TRANSFORMERS_AVAILABLE = True
except ImportError as e:
    print(f"❌ transformers NOT available: {e}")
    TRANSFORMERS_AVAILABLE = False

# Test 3: Check whisper (you have it in requirements)
print("\n=== Testing whisper availability ===")
try:
    import whisper
    print("✅ whisper package FOUND")
    WHISPER_AVAILABLE = True
except ImportError as e:
    print(f"❌ whisper NOT available: {e}")
    WHISPER_AVAILABLE = False

# Test 4: Check speech_recognition (you have it in requirements)
print("\n=== Testing speech_recognition availability ===")
try:
    import speech_recognition as sr
    print("✅ speech_recognition package FOUND")
    SPEECH_REC_AVAILABLE = True
except ImportError as e:
    print(f"❌ speech_recognition NOT available: {e}")
    SPEECH_REC_AVAILABLE = False

print(f"\n=== Summary ===")
print(f"liquid-audio: {LIQUID_AUDIO_AVAILABLE}")
print(f"transformers: {TRANSFORMERS_AVAILABLE}")
print(f"whisper: {WHISPER_AVAILABLE}")
print(f"speech_recognition: {SPEECH_REC_AVAILABLE}")
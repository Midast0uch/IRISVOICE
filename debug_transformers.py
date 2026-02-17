#!/usr/bin/env python3
"""Debug why transformers import is failing in the fallback"""

import sys
import traceback

print("=== Testing transformers import ===")
try:
    from transformers import AutoProcessor, AutoModelForCausalLM
    print("✅ transformers import SUCCESS")
    
    # Test if the model repo exists
    print("\n=== Testing model repo access ===")
    try:
        # Just test if we can get the processor (this will download if needed)
        from transformers import AutoProcessor
        processor = AutoProcessor.from_pretrained("LiquidAI/LFM2.5-Audio-1.5B", trust_remote_code=True)
        print("✅ Model repo accessible")
    except Exception as e:
        print(f"❌ Model repo failed: {e}")
        
except ImportError as e:
    print(f"❌ transformers import FAILED: {e}")
    traceback.print_exc()

print("\n=== Testing whisper (you have it in requirements) ===")
try:
    import whisper
    print("✅ whisper import SUCCESS")
    
    # Test loading a small model
    model = whisper.load_model("base")
    print("✅ whisper model loading SUCCESS")
    
except Exception as e:
    print(f"❌ whisper failed: {e}")
    traceback.print_exc()
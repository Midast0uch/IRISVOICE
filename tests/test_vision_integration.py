"""
Test script for MiniCPM-o 4.5 Vision Integration.
Run this to verify that the vision pipeline is working correctly.
"""
import sys
import os
import asyncio
import base64
import json
from pathlib import Path

# Add project root to path
project_root = str(Path(__file__).parent.parent)
sys.path.append(project_root)

try:
    from backend.vision import (
        MiniCPMClient, 
        ScreenCapture, 
        ScreenMonitor,
        get_minicpm_client,
        get_screen_capture
    )
    from backend.agent import OmniConversationManager
except ImportError as e:
    print(f"❌ Import failed: {e}")
    print("Make sure you are running from the project root and dependencies are installed.")
    sys.exit(1)


async def test_minicpm_availability():
    print("\n🔍 Testing MiniCPM-o Availability...")
    client = get_minicpm_client()
    
    # Force check
    available = client.check_availability(force=True)
    status = client.get_status()
    
    if available:
        print(f"✅ MiniCPM-o is available at {client.endpoint}")
        print(f"   Model: {client.model}")
    else:
        print(f"❌ MiniCPM-o NOT available at {client.endpoint}")
        print("   Make sure Ollama is running and you have pulled the model:")
        print("   ollama pull openbmb/minicpm-o4.5")
    
    return available


async def test_screen_capture():
    print("\n📸 Testing Screen Capture...")
    try:
        capture = get_screen_capture()
        b64_data, is_new = capture.capture_base64(force=True)
        
        if b64_data and len(b64_data) > 1000:
            print(f"✅ Screenshot captured successfully ({len(b64_data)} bytes)")
            # Decode to verify it's valid
            try:
                img_bytes = base64.b64decode(b64_data)
                print(f"   Decoded size: {len(img_bytes)} bytes")
                return b64_data
            except Exception as e:
                print(f"❌ Failed to decode base64: {e}")
                return None
        else:
            print("❌ Capture failed or data too small")
            return None
    except Exception as e:
        print(f"❌ Capture error: {e}")
        return None


async def test_vision_inference(client, screenshot_b64):
    print("\n🧠 Testing Vision Inference (Describe Screen)...")
    if not screenshot_b64:
        print("⏭️  Skipping inference (no screenshot)")
        return

    print("   Sending request to MiniCPM-o (this may take a moment)...")
    try:
        # Run in thread executor to not block async loop if it was synchronous
        # But our client is synchronous for now, let's just call it
        # Actually, let's wrap in to_thread just to be safe
        description = await asyncio.to_thread(
            client.describe_screen, 
            screenshot_b64, 
            "What is the main color of this screen?"
        )
        
        if description:
            print(f"✅ Inference success!")
            print(f"   Response: {description[:100]}...")
        else:
            print("❌ Inference returned empty response")
            
    except Exception as e:
        print(f"❌ Inference error: {e}")


async def test_omni_conversation(screenshot_b64):
    print("\n💬 Testing Omni Conversation Manager...")
    try:
        manager = OmniConversationManager()
        
        # Test 1: Config check
        status = manager.get_status()
        print(f"   Vision enabled: {status['vision_enabled']}")
        print(f"   Model: {status['model']}")
        
        # Test 2: Generate response (mock)
        # We won't actually call the LLM here to avoid long waits, but valid config is key
        if status['minicpm_available']:
             print("   Manager sees MiniCPM as available.")
        else:
             print("   Manager does NOT see MiniCPM (fallback would trigger).")

    except Exception as e:
        print(f"❌ Conversation manager error: {e}")


async def main():
    print("="*50)
    print("IRIS VISION INTEGRATION TEST")
    print("="*50)
    
    is_available = await test_minicpm_availability()
    screenshot_b64 = await test_screen_capture()
    
    if is_available and screenshot_b64:
        # Get client again
        client = get_minicpm_client()
        await test_vision_inference(client, screenshot_b64)
    else:
        print("\n⚠️  Skipping inference test because model or screen capture is unavailable.")
    
    await test_omni_conversation(screenshot_b64)
    
    print("\n" + "="*50)
    print("TEST COMPLETE")
    print("="*50)


if __name__ == "__main__":
    asyncio.run(main())

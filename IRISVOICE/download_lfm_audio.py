#!/usr/bin/env python3
"""
Simple script to download LFM2.5-Audio model for native voice conversation.
Run: python download_lfm_audio.py
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path

def main():
    print("=" * 60)
    print("LFM2.5-Audio Model Downloader")
    print("=" * 60)
    print()
    print("This will download the LFM2.5-Audio-1.5B model (~3GB)")
    print("for native voice conversation capabilities.")
    print()
    print("Model: LiquidAI/LFM2.5-Audio-1.5B")
    print(f"Location: {os.path.abspath('./models/cache')}")
    print()
    print("-" * 60)
    
    choice = input("Proceed with download? (y/n): ").strip().lower()
    if choice != 'y':
        print("Download cancelled.")
        return
    
    print()
    print("Starting download... This may take a while depending on your internet.")
    print()
    
    try:
        import asyncio
        from backend.audio.model_manager import ModelManager
        
        async def download():
            manager = ModelManager()
            return await manager.download_model()
        
        success = asyncio.run(download())
        
        if success:
            print()
            print("=" * 60)
            print("SUCCESS! Audio model downloaded.")
            print("=" * 60)
            print()
            print("The model will load automatically when you first use voice features.")
        else:
            print()
            print("Download failed. Check the error messages above.")
            
    except Exception as e:
        print(f"Error: {e}")
        print()
        print("Make sure you have:")
        print("  1. Enough disk space (~3GB free)")
        print("  2. Internet connection")
        print("  3. HuggingFace token set (if private model)")

if __name__ == "__main__":
    main()

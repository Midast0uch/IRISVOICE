#!/usr/bin/env python3
"""
LFM Audio Model Downloader - Updated for LFM Audio Integration
Check available files and download the LFM 2.5 Audio model
"""
import os
import sys
from huggingface_hub import list_repo_files, hf_hub_download

def check_available_files():
    """Check available files in the LFM Audio repository"""
    model_id = "LiquidAI/LFM2.5-Audio-1.5B"
    
    print(f"Checking available files in {model_id}...")
    
    try:
        files = list_repo_files(repo_id=model_id)
        print(f"Available files:")
        for file in files:
            print(f"  - {file}")
        return files
    except Exception as e:
        print(f"Error checking files: {e}")
        return []

def download_lfm_audio_model():
    """Download the LFM 2.5 Audio model"""
    model_id = "LiquidAI/LFM2.5-Audio-1.5B"
    
    # Check available files first
    available_files = check_available_files()
    
    if not available_files:
        print("No files found in repository")
        return None
    
    # Try to find the safetensors variant, otherwise use the first model file
    target_file = None
    for file in available_files:
        if "model.safetensors" in file:
            target_file = file
            break
        elif file.endswith(".bin"):
            target_file = file
            break
    
    if not target_file:
        print("No model files found in repository")
        return None
    
    local_dir = "./models"
    
    print(f"Downloading {target_file} from {model_id}...")
    
    try:
        # Create models directory if it doesn't exist
        os.makedirs(local_dir, exist_ok=True)
        
        # Download the model
        downloaded_path = hf_hub_download(
            repo_id=model_id,
            filename=target_file,
            local_dir=local_dir,
            local_dir_use_symlinks=False
        )
        
        print(f"Audio model downloaded successfully to: {downloaded_path}")
        
        # Verify file size
        file_size = os.path.getsize(downloaded_path)
        print(f"File size: {file_size / (1024**3):.2f} GB")
        
        return downloaded_path
        
    except Exception as e:
        print(f"Error downloading audio model: {e}")
        return None

if __name__ == "__main__":
    download_lfm_audio_model()
#!/usr/bin/env python3
"""
LFM Text Model Downloader - For LFM2-8B-A1B Integration
Downloads the LFM2-8B-A1B model for reasoning and planning
"""

import os
import sys
from huggingface_hub import snapshot_download
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

def download_lfm_text_model():
    """Download the LFM2-8B-A1B text generation model"""
    model_id = "LiquidAI/LFM2-8B-A1B"
    local_dir = "./models/LFM2-8B-A1B"
    
    print(f"Downloading LFM text model: {model_id}")
    print("This model has 8B total parameters")
    print("Optimized for tool calling, chat, and on-device deployment")
    
    try:
        # Create models directory if it doesn't exist
        os.makedirs(local_dir, exist_ok=True)
        
        # Download the model using snapshot_download for complete model
        print("Downloading model files...")
        model_path = snapshot_download(
            repo_id=model_id,
            local_dir=local_dir,
            local_dir_use_symlinks=False,
            resume_download=True
        )
        
        print(f"Model downloaded successfully to: {model_path}")
        
        # Verify we can load the tokenizer and model
        print("Verifying model integrity...")
        try:
            tokenizer = AutoTokenizer.from_pretrained(model_path)
            print("✓ Tokenizer loaded successfully")
            
            # Check model files size
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(local_dir):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    total_size += os.path.getsize(filepath)
            
            print(f"Total model size: {total_size / (1024**3):.2f} GB")
            
            # Test tokenization
            test_text = "Hello, this is a test message."
            tokens = tokenizer.encode(test_text)
            print(f"✓ Tokenization test passed: '{test_text}' -> {len(tokens)} tokens")
            
        except Exception as e:
            print(f"⚠ Warning: Model verification failed: {e}")
            print("Model files are downloaded but may need manual verification")
        
        return model_path
        
    except Exception as e:
        print(f"Error downloading text model: {e}")
        print("Please ensure you have sufficient disk space and internet connection")
        return None

def get_model_info():
    """Display information about the LFM2-8B-A1B model"""
    print("\n=== LFM2-8B-A1B Model Information ===")
    print("Total parameters: 8B")
    print("Context length: 32,768 tokens")
    print("Architecture: Hybrid with multiplicative gates and short convolutions")
    print("Optimized for: Tool calling, chat, RAG, creative writing, multi-turn conversations")
    print("\nRecommended generation parameters:")
    print("  temperature=0.3")
    print("  min_p=0.15") 
    print("  repetition_penalty=1.05")
    print("\nSupported languages: English, Arabic, Chinese, French, German, Japanese, Korean, Spanish")
    print("=====================================\n")

if __name__ == "__main__":
    get_model_info()
    
    print("Starting LFM text model download...")
    model_path = download_lfm_text_model()
    
    if model_path:
        print(f"\n✓ Success! LFM text model is ready at: {model_path}")
        print("\nNext steps:")
        print("1. Update your agent_config.yaml to use this model")
        print("2. Configure the chat template and tool calling")
        print("3. Test the model with your chat interface")
    else:
        print("\n✗ Failed to download LFM text model")
        print("Please check your internet connection and disk space")
        sys.exit(1)
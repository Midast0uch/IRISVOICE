#!/bin/bash
# =============================================================================
# LFM2.5-VL Vision Server — macOS/Linux Startup
# Starts llama-server with LFM2.5-VL-450M on port 8081
#
# REQUIREMENTS:
#   1. llama-server installed (brew install llama.cpp on macOS)
#   2. LFM2.5-VL-450M-Q4_0.gguf in ~/models/LFM2.5-VL-450M/
#   3. mmproj-LFM2.5-VL-450m-Q8_0.gguf in same directory (CRITICAL)
#
# Without the mmproj file, server starts but returns blank on all images.
# =============================================================================

MODEL_DIR="$HOME/models/LFM2.5-VL-450M"
MODEL="$MODEL_DIR/LFM2.5-VL-450M-Q4_0.gguf"
MMPROJ="$MODEL_DIR/mmproj-LFM2.5-VL-450m-Q8_0.gguf"

echo "============================================"
echo " LFM2.5-VL-450M Vision Server"
echo " Port: 8081"
echo " Model: $MODEL"
echo "============================================"

# Verify model files exist
if [ ! -f "$MODEL" ]; then
    echo "[ERROR] Model file not found: $MODEL"
    echo "Download with: python -c \"from huggingface_hub import hf_hub_download; hf_hub_download('LiquidAI/LFM2.5-VL-450M-GGUF','LFM2.5-VL-450M-Q4_0.gguf',local_dir='$MODEL_DIR')\""
    exit 1
fi

if [ ! -f "$MMPROJ" ]; then
    echo "[ERROR] mmproj file not found: $MMPROJ"
    echo "This file is REQUIRED. Without it, vision returns blank responses."
    echo "Download with: python -c \"from huggingface_hub import hf_hub_download; hf_hub_download('LiquidAI/LFM2.5-VL-450M-GGUF','mmproj-LFM2.5-VL-450m-Q8_0.gguf',local_dir='$MODEL_DIR')\""
    exit 1
fi

echo "[INFO] Starting llama-server on port 8081..."
llama-server \
  --model "$MODEL" \
  --mmproj "$MMPROJ" \
  --alias lfm2.5-vl \
  --port 8081 \
  --host 127.0.0.1 \
  --n-gpu-layers 1 \
  --ctx-size 4096 \
  --image-max-tokens 256 \
  --verbose

"""
IRIS Backend Startup Script
Uses uvicorn programmatically to avoid subprocess Python path issues
"""
import os
import sys
import signal
import asyncio
from pathlib import Path

# Get the directory containing this script (project root)
base_dir = Path(__file__).parent.resolve()
os.chdir(base_dir)

# Add project root to Python path BEFORE any imports
sys.path.insert(0, str(base_dir))

# Set PYTHONPATH environment variable for subprocesses
os.environ['PYTHONPATH'] = str(base_dir) + os.pathsep + os.environ.get('PYTHONPATH', '')

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(base_dir / ".env")

# Set HF_HUB_DISABLE_SYMLINKS_WARNING for HuggingFace
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')

# Now import and run uvicorn
import uvicorn

# Global flag for graceful shutdown
shutdown_flag = False

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global shutdown_flag
    print(f"\nReceived signal {signum}, shutting down...")
    shutdown_flag = True
    sys.exit(0)

async def run_server():
    """Run the uvicorn server asynchronously"""
    config = uvicorn.Config(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,  # Disabled for Windows compatibility
        log_level="info"
    )
    server = uvicorn.Server(config)
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("Starting uvicorn server...")
    await server.serve()

def main():
    """Start the IRIS backend server"""
    print(">> Starting IRIS Backend...")
    print(f"   Python: {sys.executable}")
    print(f"   Base dir: {base_dir}")
    print(f"   Python path: {sys.path[0]}")
    print(f"   PYTHONPATH: {os.environ.get('PYTHONPATH', 'not set')}")
    print()
    
    try:
        print("Starting async server...")
        asyncio.run(run_server())
        print("Server stopped normally")
    except KeyboardInterrupt:
        print("\n\n[OK] Server stopped by user")
    except Exception as e:
        print(f"\n[ERROR] Error starting server: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

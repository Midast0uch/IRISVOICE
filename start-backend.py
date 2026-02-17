"""
IRIS Backend Startup Script
Uses uvicorn programmatically to avoid subprocess Python path issues
"""
import os
import sys
from pathlib import Path

# Get the directory containing this script (project root)
base_dir = Path(__file__).parent.resolve()
os.chdir(base_dir)

# Add project root to Python path BEFORE any imports
sys.path.insert(0, str(base_dir))

# Set PYTHONPATH environment variable for subprocesses
os.environ['PYTHONPATH'] = str(base_dir) + os.pathsep + os.environ.get('PYTHONPATH', '')

# Now import and run uvicorn
import uvicorn

def main():
    """Start the IRIS backend server"""
    print(">> Starting IRIS Backend...")
    print(f"   Python: {sys.executable}")
    print(f"   Base dir: {base_dir}")
    print(f"   Python path: {sys.path[0]}")
    print(f"   PYTHONPATH: {os.environ.get('PYTHONPATH', 'not set')}")
    print()
    
    try:
        uvicorn.run(
            "backend.main:app",
            host="127.0.0.1",
            port=8000,
            reload=False,  # Disabled for Windows compatibility
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n\n[OK] Server stopped")
    except Exception as e:
        print(f"\n[ERROR] Error starting server: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

"""
IRIS Backend Startup Script
Simple script to start the FastAPI backend server
"""
import os
import sys
import subprocess
from pathlib import Path

def main():
    """Start the IRIS backend server"""
    
    # Get the directory containing this script
    base_dir = Path(__file__).parent
    
    # Change to base directory
    os.chdir(base_dir)
    
    # Check if virtual environment exists
    venv_path = base_dir / "venv"
    if not venv_path.exists():
        print("[ERROR] Virtual environment not found!")
        print("\nPlease set up the environment first:")
        print("  python -m venv venv")
        print("  venv\\Scripts\\activate")
        print("  pip install -r requirements.txt")
        sys.exit(1)
    
    # Start the server
    print(">> Starting IRIS Backend...")
    print()
    
    try:
        # Use the virtual environment Python
        python_exe = venv_path / "Scripts" / "python.exe"
        
        # Run the FastAPI app
        subprocess.run([
            str(python_exe),
            "-m", "uvicorn",
            "backend.main:app",
            "--host", "127.0.0.1",
            "--port", "8000",
            "--reload"
        ], check=True)
        
    except KeyboardInterrupt:
        print("\n\n[OK] Server stopped")
    except Exception as e:
        print(f"\n[ERROR] Error starting server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

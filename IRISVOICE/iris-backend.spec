# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the IRIS backend (start-backend.py → iris-backend.exe)
#
# Build with:
#   cd IRISVOICE
#   pyinstaller iris-backend.spec
#
# Output: dist/iris-backend.exe   (one-file mode — single self-contained executable)
#
# After building, copy/rename to Tauri's expected sidecar path:
#   copy dist\iris-backend.exe src-tauri\binaries\iris-backend-x86_64-pc-windows-msvc.exe
#
# One-file mode: PyInstaller packs all DLLs and Python runtime into the exe.
# On first run it extracts to a temp directory, then subsequent runs use the cache.
# This is required for Tauri sidecars — only the single exe is copied to binaries/,
# so the _internal/ folder approach (one-directory mode) does not work.
#
# NOTE: The .env file, models/ directory, and data/ directory must live
# alongside the exe at runtime — they are NOT bundled inside it.

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# ── Hidden imports ─────────────────────────────────────────────────────────────
# FastAPI, Starlette, and Uvicorn rely heavily on dynamic imports that PyInstaller
# cannot detect statically.

hidden_imports = [
    # ASGI / server
    'uvicorn', 'uvicorn.main', 'uvicorn.config', 'uvicorn.lifespan',
    'uvicorn.lifespan.on', 'uvicorn.lifespan.off',
    'uvicorn.protocols', 'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.protocols.websockets.wsproto_impl',
    'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio',
    'uvicorn.logging', 'uvicorn.middleware', 'uvicorn.middleware.proxy_headers',

    # FastAPI / Starlette
    'fastapi', 'starlette', 'starlette.routing', 'starlette.middleware',
    'starlette.middleware.cors', 'starlette.middleware.base',
    'starlette.staticfiles', 'starlette.responses', 'starlette.requests',
    'starlette.websockets', 'starlette.background', 'starlette.exceptions',

    # Pydantic
    'pydantic', 'pydantic.v1', 'pydantic_core',
    'pydantic.deprecated', 'pydantic.functional_validators',

    # Encoding / HTTP internals
    'h11', 'httptools', 'anyio', 'anyio.abc', 'anyio._backends._asyncio',
    'sniffio', 'idna', 'multipart', 'python_multipart',

    # dotenv
    'dotenv',

    # Audio
    'pvporcupine', 'pyaudio', 'sounddevice', 'numpy', 'scipy',
    'scipy.signal', 'scipy.io', 'scipy.io.wavfile',

    # STT
    'faster_whisper', 'RealtimeSTT',

    # TTS
    'pyttsx3', 'pyttsx3.drivers', 'pyttsx3.drivers.sapi5',

    # Crypto / keyring
    'cryptography', 'keyring', 'keyring.backends',
    'keyring.backends.Windows',

    # OpenAI / Anthropic clients
    'openai', 'anthropic',

    # Memory / DB
    'sqlite3', 'sqlcipher3',

    # Utils
    'requests', 'aiofiles', 'psutil', 'PIL', 'mss', 'pyautogui',
    'websockets', 'websockets.legacy', 'websockets.server',

    # IRIS backend packages — collected as datas below, but list them as
    # hidden imports too so PyInstaller walks them for transitive deps.
    'backend', 'backend.main', 'backend.agent', 'backend.voice',
    'backend.audio', 'backend.memory', 'backend.gateway', 'backend.security',
    'backend.mcp', 'backend.tools', 'backend.utils', 'backend.vision',
    'backend.config', 'backend.core', 'backend.state_manager',
    'backend.ws_manager', 'backend.iris_gateway',
]

# Collect all submodules for packages that use dynamic plugin loading
for pkg in ['uvicorn', 'starlette', 'fastapi', 'pyttsx3', 'keyring']:
    hidden_imports += collect_submodules(pkg)

# ── Data files ─────────────────────────────────────────────────────────────────
datas = []

# The entire backend/ Python package (source files needed at import time)
datas += [('backend', 'backend')]

# Porcupine resources (built-in keyword .ppn files)
try:
    import pvporcupine
    pvp_path = Path(pvporcupine.__file__).parent
    datas += [(str(pvp_path / 'resources'), 'pvporcupine/resources')]
except Exception:
    pass

# Collect pydantic JSON schema data
datas += collect_data_files('pydantic')

# ── Analysis ───────────────────────────────────────────────────────────────────
a = Analysis(
    ['start-backend.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=['pyinstaller_hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy optional deps that aren't needed at runtime in the exe;
        # torch/transformers are huge — if GPU inference is needed, keep them.
        # Comment out these lines to include GPU support in the bundle.
        'torch', 'torchvision', 'torchaudio',
        'transformers',
        'matplotlib', 'IPython', 'notebook', 'jupyter',
        'tkinter', 'wx',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,    # pack all native DLLs + python313.dll into the single exe
    a.zipfiles,
    a.datas,
    exclude_binaries=False,  # one-file mode: no separate _internal/ directory
    name='iris-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # no console window — backend runs silently
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='src-tauri/icons/icon.ico',  # reuse the Tauri app icon
)
# No COLLECT step — one-file mode produces dist/iris-backend.exe directly.

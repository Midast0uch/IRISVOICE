"""The Workbench (CLM-11): a persistent Python execution layer.

Exports only. Nothing here imports another app module at import time;
`worker.py` is a data file for the child process and is never imported.
"""
from .protocol import PROTOCOL_VERSION, ProtocolError, decode, encode
from .client import WorkbenchClient, resolve_interpreter

__all__ = [
    "PROTOCOL_VERSION", "ProtocolError", "decode", "encode",
    "WorkbenchClient", "resolve_interpreter",
]

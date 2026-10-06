"""Throwaway: prove ONE handle per log file (the root-cause fix).

Before: the structured logger AND the root logger each opened the same
pid-stamped log, so a rollover rename could never succeed on Windows.
After: the root logger SHARES the structured logger's handler, so exactly one
handle exists and the rollover can actually happen.
"""
from __future__ import annotations

import logging

from backend.core.logging_config import setup_backend_logging

root = logging.getLogger()
root.handlers = []  # deterministic: drop whatever an import already attached

log = setup_backend_logging(log_level="INFO")

root_file = [
    h for h in root.handlers
    if isinstance(h, logging.handlers.RotatingFileHandler)
]
struct_file = [
    h for h in getattr(log, "logger", log).handlers
    if isinstance(h, logging.handlers.RotatingFileHandler)
]

print(f"root file handlers:       {len(root_file)}")
print(f"structured file handlers: {len(struct_file)}")
shared = bool(root_file) and bool(struct_file) and root_file[0] is struct_file[0]
print(f"the SAME handler object is shared: {shared}")
print(f"distinct handles on this file: "
      f"{len({id(h) for h in root_file + struct_file})}")

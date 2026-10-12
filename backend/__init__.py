"""
IRIS Backend Package

The package names below load on first use (PEP 562), not at import. Every
subprocess that imports any `backend.*` module ran this file: the TTS worker
paid for fastapi + pydantic (4.6 s warm, far more on a cold hard disk) to use
two small helpers, on the path that gates /health at boot.
"""
from importlib import import_module as _import_module

_LAZY = {
    "Category": ".models",
    "FieldType": ".models",
    "InputField": ".models",
    "Section": ".models",
    "ColorTheme": ".models",
    "IRISState": ".models",
    "get_sections_for_category": ".models",
    "SECTION_CONFIGS": ".models",
    "StateManager": ".state_manager",
    "get_state_manager": ".state_manager",
    "WebSocketManager": ".ws_manager",
    "get_websocket_manager": ".ws_manager",
}


def __getattr__(name):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module(module, __name__), name)
    globals()[name] = value
    return value


__all__ = list(_LAZY)

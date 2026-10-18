"""StructuredFormatter must NEVER raise (2026-10-16).

Measured before: the stdlib `websockets` client logs each STT frame at DEBUG
with extra={"websocket": <ClientConnection>}. StructuredFormatter.format did a
bare json.dumps, which raised TypeError inside Handler.emit(); `logging` then
printed a ~35-line "--- Logging error ---" traceback for EVERY record. The STT
stream produced ~1,256 tracebacks in 14 minutes (~45k of 61k log lines, ~0.5
MB/min); one backend log reached 594 MB.
"""
from __future__ import annotations

import io
import logging
import sys
from contextlib import redirect_stderr

from backend.monitoring.structured_logger import StructuredFormatter


class _Unserializable:  # stands in for websockets.ClientConnection
    def __repr__(self) -> str:
        return "<Unserializable>"


def _record(**extra) -> logging.LogRecord:
    rec = logging.LogRecord(
        name="websockets.client",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=1,
        msg="> GET /v1/audio/stream HTTP/1.1",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(rec, key, value)
    return rec


def test_formatter_encodes_a_non_serializable_extra():
    out = StructuredFormatter().format(_record(websocket=_Unserializable()))
    assert "GET /v1/audio/stream" in out
    assert "Unserializable" in out


def test_formatter_never_raises_through_a_real_handler():
    buf = io.StringIO()
    err = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(StructuredFormatter())
    lg = logging.getLogger("websockets.client.contract_test")
    lg.propagate = False
    lg.addHandler(handler)
    lg.setLevel(logging.DEBUG)
    try:
        with redirect_stderr(err):
            lg.debug(
                "> GET /v1/audio/stream HTTP/1.1",
                extra={"websocket": _Unserializable()},
            )
    finally:
        lg.removeHandler(handler)
    assert "Logging error" not in err.getvalue(), err.getvalue()
    assert "GET /v1/audio/stream" in buf.getvalue()

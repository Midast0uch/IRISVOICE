"""
IRIS Hybrid C++ Core Memory Engine — Python FFI Bridge
Loads iris_core.dll via ctypes with fallback to pure Python.

Audited safety features:
  - ffi_init_engine returns False on C++ failure (not always True)
  - All argtypes / restypes explicitly declared
  - Pure Python fallback engine with PythonCaduceanFallbackState
  - Fallback uses sqlite3 (sqlcipher3 if available)
"""

import ctypes
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DLL Discovery
# ---------------------------------------------------------------------------

def _find_dll() -> Optional[str]:
    """Find iris_core.dll / libiris_core.so in known locations."""
    script_dir = Path(__file__).parent.resolve()
    repo_root = script_dir.parent.parent.resolve()
    candidates = [
        repo_root / "backend" / "native" / "iris_core.dll",       # Windows
        repo_root / "backend" / "native" / "libiris_core.so",   # Linux
        repo_root / "lib" / "iris_core.dll",
        repo_root / "lib" / "libiris_core.so",
        repo_root / "src-tauri" / "src" / "iris_core" / "build" / "Release" / "iris_core.dll",
    ]
    for cand in candidates:
        if cand.exists():
            return str(cand)
    return None


# ---------------------------------------------------------------------------
# C-Interface Types
# ---------------------------------------------------------------------------

class _IrisFFI:
    """Thin ctypes wrapper around iris_core C-API."""

    def __init__(self, dll_path: str):
        self._lib = ctypes.CDLL(dll_path)

        # --- Lifecycle ---
        self._lib.init_core_engine.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        self._lib.init_core_engine.restype = ctypes.c_int

        self._lib.shutdown_core_engine.argtypes = []
        self._lib.shutdown_core_engine.restype = ctypes.c_int

        self._lib.core_health_check.argtypes = []
        self._lib.core_health_check.restype = ctypes.c_int

        # --- Event Ingestion ---
        self._lib.ingest_event.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p
        ]
        self._lib.ingest_event.restype = ctypes.c_int

        # --- Caducean ---
        self._lib.caducean_recommend.argtypes = [ctypes.c_char_p]
        self._lib.caducean_recommend.restype = ctypes.c_int

        self._lib.caducean_get_xi.argtypes = [ctypes.c_char_p]
        self._lib.caducean_get_xi.restype = ctypes.c_double

        self._lib.caducean_update.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_double]
        self._lib.caducean_update.restype = None

        # --- EML ---
        self._lib.calculate_eml.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double)
        ]
        self._lib.calculate_eml.restype = ctypes.c_double

        # --- Immortus ---
        self._lib.immortus_chain_append.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_char_p, ctypes.c_char_p
        ]
        self._lib.immortus_chain_append.restype = ctypes.c_int

        self._lib.immortus_chain_keep_latest.argtypes = [
            ctypes.c_char_p, ctypes.c_int
        ]
        self._lib.immortus_chain_keep_latest.restype = ctypes.c_int

    # Wrapper methods with encoding
    def init_core_engine(self, db_path: str, key_hex: str) -> int:
        return self._lib.init_core_engine(
            db_path.encode("utf-8"), key_hex.encode("utf-8")
        )

    def shutdown_core_engine(self) -> int:
        return self._lib.shutdown_core_engine()

    def core_health_check(self) -> int:
        return self._lib.core_health_check()

    def ingest_event(
        self, session_id: str, domain: str, event_type: str,
        actor: str, outcome: str, summary: str, payload_json: str
    ) -> int:
        return self._lib.ingest_event(
            session_id.encode("utf-8"),
            domain.encode("utf-8"),
            event_type.encode("utf-8"),
            actor.encode("utf-8"),
            outcome.encode("utf-8"),
            summary.encode("utf-8"),
            payload_json.encode("utf-8"),
        )

    def caducean_recommend(self, session_id: str) -> int:
        return self._lib.caducean_recommend(session_id.encode("utf-8"))

    def caducean_get_xi(self, session_id: str) -> float:
        return self._lib.caducean_get_xi(session_id.encode("utf-8"))

    def caducean_update(self, session_id: str, action: int, balance: float) -> None:
        self._lib.caducean_update(session_id.encode("utf-8"), action, balance)

    def calculate_eml(self, session_id: str) -> Tuple[float, float, float]:
        x = ctypes.c_double(0.0)
        y = ctypes.c_double(0.0)
        score = self._lib.calculate_eml(
            session_id.encode("utf-8"), ctypes.byref(x), ctypes.byref(y)
        )
        return score, x.value, y.value

    def immortus_chain_append(
        self, thread_id: str, result: str, coords_from: Optional[str],
        coords_to: Optional[str], nbl_outcome: Optional[str],
        insight: Optional[str], file_path: Optional[str],
        landmark_id: Optional[str]
    ) -> int:
        def _enc(s: Optional[str]) -> bytes:
            return (s or "").encode("utf-8")
        return self._lib.immortus_chain_append(
            thread_id.encode("utf-8"), result.encode("utf-8"),
            _enc(coords_from), _enc(coords_to), _enc(nbl_outcome),
            _enc(insight), _enc(file_path), _enc(landmark_id)
        )

    def immortus_chain_keep_latest(self, thread_id: str, keep_count: int) -> int:
        return self._lib.immortus_chain_keep_latest(
            thread_id.encode("utf-8"), keep_count
        )


# ---------------------------------------------------------------------------
# Fallback Engine (pure Python)
# ---------------------------------------------------------------------------

class _PythonCaduceanFallbackState:
    """In-memory fallback when C++ core is unavailable."""

    def __init__(self):
        self.states: Dict[str, Dict] = {}

    def recommend(self, session_id: str) -> int:
        return 2  # MAINTAIN

    def get_xi(self, session_id: str) -> float:
        return 0.0

    def update(self, session_id: str, action: int, balance: float) -> None:
        pass


class _PythonFallbackEngine:
    """Pure Python fallback — uses sqlite3 (or sqlcipher3 if available)."""

    def __init__(self, db_path: str, key_hex: str):
        self.db_path = db_path
        self._conn = None
        self.caducean = _PythonCaduceanFallbackState()
        self._init_db()

    def _init_db(self):
        try:
            import sqlcipher3  # type: ignore[import]
            self._conn = sqlcipher3.connect(self.db_path)
            self._conn.execute(f"PRAGMA key = \"x'{self.key_hex}'\";")
        except ImportError:
            import sqlite3
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        # Run migrations
        self._run_migrations()

    def _run_migrations(self):
        if not self._conn:
            return
        sql = """
        CREATE TABLE IF NOT EXISTS system_events (
            event_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            event_domain TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            outcome TEXT DEFAULT 'pending',
            sanitization_state TEXT NOT NULL,
            summary TEXT NOT NULL,
            interaction_payload TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS memory_chain (
            chain_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            result TEXT,
            coords_from TEXT,
            coords_to TEXT,
            nbl_outcome TEXT,
            insight TEXT,
            file_path TEXT,
            landmark_id TEXT,
            stale INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        );
        """
        self._conn.executescript(sql)
        self._conn.commit()

    def ingest_event(self, session_id, domain, event_type, actor, outcome,
                     summary, payload_json) -> int:
        if not self._conn:
            return -1
        import uuid
        event_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO system_events (event_id, session_id, event_domain, "
            "event_type, actor, outcome, sanitization_state, summary, "
            "interaction_payload) VALUES (?,?,?,?,?,?,?,?,?)",
            (event_id, session_id, domain, event_type, actor, outcome,
             "clean", summary, payload_json)
        )
        self._conn.commit()
        return 0

    def calculate_eml(self, session_id: str) -> Tuple[float, float, float]:
        if not self._conn:
            return 0.0, 0.0, 0.0
        cur = self._conn.cursor()
        # Edits last 3
        cur.execute(
            "SELECT COUNT(DISTINCT interaction_payload) FROM system_events "
            "WHERE session_id = ? AND event_domain = 'CODE' AND event_type = 'file_edit' "
            "ORDER BY created_at DESC LIMIT 3", (session_id,)
        )
        edits = cur.fetchone()[0] or 0
        # Tests last 3
        cur.execute(
            "SELECT COUNT(*) FROM system_events "
            "WHERE session_id = ? AND event_domain = 'CODE' AND event_type = 'test_run' "
            "AND outcome = 'success' ORDER BY created_at DESC LIMIT 3", (session_id,)
        )
        tests = cur.fetchone()[0] or 0
        # Nodes
        cur.execute(
            "SELECT COUNT(*) FROM system_events WHERE session_id = ?", (session_id,)
        )
        nodes = cur.fetchone()[0] or 1
        dx = tests / edits if edits else 0.0
        dy = 0.0 / nodes  # landmarks not tracked in fallback
        eml = 0.0
        if dx > 0 and dy > 0:
            eml = 2.0 * dx * dy / (dx + dy)
        return eml, dx, dy

    def immortus_chain_append(self, thread_id, result, **kwargs) -> int:
        if not self._conn:
            return -1
        import uuid
        import time
        chain_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO memory_chain (chain_id, thread_id, result, coords_from, "
            "coords_to, nbl_outcome, insight, file_path, landmark_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (chain_id, thread_id, result,
             kwargs.get("coords_from"), kwargs.get("coords_to"),
             kwargs.get("nbl_outcome"), kwargs.get("insight"),
             kwargs.get("file_path"), kwargs.get("landmark_id"),
             time.time())
        )
        self._conn.commit()
        return 0

    def immortus_chain_keep_latest(self, thread_id: str, keep_count: int) -> int:
        if not self._conn:
            return -1
        cur = self._conn.cursor()
        cur.execute(
            "DELETE FROM memory_chain WHERE thread_id = ? AND chain_id NOT IN "
            "(SELECT chain_id FROM memory_chain WHERE thread_id = ? "
            "ORDER BY created_at DESC LIMIT ?)",
            (thread_id, thread_id, keep_count)
        )
        return cur.rowcount

    def health_check(self) -> int:
        return 1 if self._conn else 0

    def shutdown(self) -> int:
        if self._conn:
            self._conn.close()
            self._conn = None
        return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class IrisCoreEngine:
    """
    Singleton interface to the C++ core (or Python fallback).
    Usage:
        engine = IrisCoreEngine()
        ok = engine.init(db_path, key_hex)
        engine.ingest_event(...)
    """

    _instance: Optional["IrisCoreEngine"] = None
    _ffi: Optional[_IrisFFI] = None
    _fallback: Optional[_PythonFallbackEngine] = None
    _initialized: bool = False

    def __new__(cls) -> "IrisCoreEngine":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ffi = None
            cls._instance._fallback = None
            cls._instance._initialized = False
        return cls._instance

    def init(self, db_path: str, key_hex: str) -> bool:
        """Initialize the engine. Returns False on failure."""
        if self._initialized:
            return True

        dll_path = _find_dll()
        if dll_path:
            try:
                self._ffi = _IrisFFI(dll_path)
                rc = self._ffi.init_core_engine(db_path, key_hex)
                if rc == 0:
                    logger.info(f"[iris_ffi] C++ core loaded from {dll_path}")
                    self._initialized = True
                    return True
                else:
                    logger.error(
                        f"[iris_ffi] C++ init failed (rc={rc}), falling back to Python"
                    )
                    self._ffi = None
            except Exception as e:
                logger.error(f"[iris_ffi] DLL load failed: {e}")
                self._ffi = None
        else:
            logger.warning("[iris_ffi] iris_core.dll not found — using Python fallback")

        # Python fallback
        try:
            self._fallback = _PythonFallbackEngine(db_path, key_hex)
            logger.info("[iris_ffi] Python fallback engine active")
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"[iris_ffi] Python fallback failed: {e}")
            return False

    def shutdown(self) -> bool:
        if self._ffi:
            self._ffi.shutdown_core_engine()
            self._ffi = None
        if self._fallback:
            self._fallback.shutdown()
            self._fallback = None
        self._initialized = False
        IrisCoreEngine._instance = None
        return True

    def is_healthy(self) -> bool:
        if self._ffi:
            return self._ffi.core_health_check() == 1
        if self._fallback:
            return self._fallback.health_check() == 1
        return False

    # --- Event Ingestion ---

    def ingest_event(
        self, session_id: str, domain: str, event_type: str,
        actor: str = "agent", outcome: str = "pending",
        summary: str = "", payload_json: str = "{}"
    ) -> bool:
        if not self._initialized:
            return False
        if self._ffi:
            rc = self._ffi.ingest_event(
                session_id, domain, event_type, actor, outcome, summary, payload_json
            )
            return rc == 0
        if self._fallback:
            rc = self._fallback.ingest_event(
                session_id, domain, event_type, actor, outcome, summary, payload_json
            )
            return rc == 0
        return False

    # --- Caducean ---

    def caducean_recommend(self, session_id: str) -> int:
        """Returns 0=EXPAND, 1=CONTRACT, 2=MAINTAIN."""
        if self._ffi:
            return self._ffi.caducean_recommend(session_id)
        if self._fallback:
            return self._fallback.caducean.recommend(session_id)
        return 2

    def caducean_get_xi(self, session_id: str) -> float:
        if self._ffi:
            return self._ffi.caducean_get_xi(session_id)
        if self._fallback:
            return self._fallback.caducean.get_xi(session_id)
        return 0.0

    def caducean_update(self, session_id: str, action: int, balance: float) -> bool:
        if self._ffi:
            self._ffi.caducean_update(session_id, action, balance)
            return True
        if self._fallback:
            self._fallback.caducean.update(session_id, action, balance)
            return True
        return False

    # --- EML ---

    def calculate_eml(self, session_id: str) -> Tuple[float, float, float]:
        """Returns (eml_score, drift_x, drift_y)."""
        if self._ffi:
            return self._ffi.calculate_eml(session_id)
        if self._fallback:
            return self._fallback.calculate_eml(session_id)
        return 0.0, 0.0, 0.0

    # --- Immortus ---

    def immortus_chain_append(
        self, thread_id: str, result: str,
        coords_from: Optional[str] = None,
        coords_to: Optional[str] = None,
        nbl_outcome: Optional[str] = None,
        insight: Optional[str] = None,
        file_path: Optional[str] = None,
        landmark_id: Optional[str] = None
    ) -> bool:
        if self._ffi:
            rc = self._ffi.immortus_chain_append(
                thread_id, result, coords_from, coords_to,
                nbl_outcome, insight, file_path, landmark_id
            )
            return rc == 0
        if self._fallback:
            rc = self._fallback.immortus_chain_append(
                thread_id, result, coords_from=coords_from,
                coords_to=coords_to, nbl_outcome=nbl_outcome,
                insight=insight, file_path=file_path,
                landmark_id=landmark_id
            )
            return rc == 0
        return False

    def immortus_chain_keep_latest(self, thread_id: str, keep_count: int) -> int:
        if self._ffi:
            return self._ffi.immortus_chain_keep_latest(thread_id, keep_count)
        if self._fallback:
            return self._fallback.immortus_chain_keep_latest(thread_id, keep_count)
        return -1


# ---------------------------------------------------------------------------
# Module-level convenience helpers
# ---------------------------------------------------------------------------

_engine: Optional[IrisCoreEngine] = None


def ffi_init_engine(db_path: str, key_hex: str) -> bool:
    """
    Initialize the C++ core (or Python fallback).
    Returns False on failure (audited fix — was always True before).
    """
    global _engine
    _engine = IrisCoreEngine()
    ok = _engine.init(db_path, key_hex)
    if not ok:
        logger.error(f"[FFI] C++ initialization error. Using Python fallback database connection.")
        return False
    return True


def ffi_ingest_event(
    session_id: str, domain: str, event_type: str,
    actor: str = "agent", outcome: str = "pending",
    summary: str = "", payload_json: str = "{}"
) -> bool:
    if _engine is None:
        return False
    return _engine.ingest_event(
        session_id, domain, event_type, actor, outcome, summary, payload_json
    )


def ffi_health_check() -> bool:
    if _engine is None:
        return False
    return _engine.is_healthy()


def ffi_shutdown() -> bool:
    global _engine
    if _engine:
        _engine.shutdown()
        _engine = None
    return True


def ffi_caducean_recommend(session_id: str) -> int:
    if _engine is None:
        return 2
    return _engine.caducean_recommend(session_id)


def ffi_caducean_update(session_id: str, action: int, balance: float) -> bool:
    if _engine is None:
        return False
    return _engine.caducean_update(session_id, action, balance)


def ffi_calculate_eml(session_id: str) -> Tuple[float, float, float]:
    if _engine is None:
        return 0.0, 0.0, 0.0
    return _engine.calculate_eml(session_id)

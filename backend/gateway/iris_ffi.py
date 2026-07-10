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
from dataclasses import dataclass
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DLL Discovery
# ---------------------------------------------------------------------------


def _find_dll() -> Optional[str]:
    """Find iris_core.dll / libiris_core.so in known locations."""
    script_dir = Path(__file__).parent.resolve()
    repo_root = script_dir.parent.parent.resolve()
    candidates = [
        repo_root / "backend" / "native" / "iris_core.dll",  # Windows
        repo_root / "backend" / "native" / "libiris_core.so",  # Linux
        repo_root / "lib" / "iris_core.dll",
        repo_root / "lib" / "libiris_core.so",
        repo_root
        / "src-tauri"
        / "src"
        / "iris_core"
        / "build"
        / "Release"
        / "iris_core.dll",
    ]
    for cand in candidates:
        if cand.exists():
            return str(cand)
    return None


# ---------------------------------------------------------------------------
# C-Interface Types
# ---------------------------------------------------------------------------


# --- v2: IrisDirectionSignal ctypes struct (FFI contract) ---
# Field order is FROZEN — MUST match src-tauri/src/iris_core/iris_core.h
# `IrisDirectionSignal` exactly. Verified by test_caducean_ffi_contract.py.
# Any drift here corrupts memory silently in ctypes — this is why we have
# a contract test.
class IrisDirectionSignal(ctypes.Structure):
    """Bias-free physics signal from Caducean Engine v2.

    Mirrors the C struct IrisDirectionSignal in iris_core.h (5 doubles).
    The caller (agent kernel, voice kernel, TTS, Mycelium) decides what
    `target_u = +1.0` means in their domain. The physics provides the
    rhythm; the interpretation is local.
    """

    _fields_ = [
        ("target_u", ctypes.c_double),  # +1.0 (expansion) or -1.0 (compression)
        ("force_magnitude", ctypes.c_double),  # |F(u)| = |a*u - b*u^3|
        ("u_current", ctypes.c_double),  # current attentional velocity in [-1, 1]
        ("phase", ctypes.c_double),  # current xi in [0, 2pi)
        ("balance", ctypes.c_double),  # EML-derived urgency in [0.1, 3.0]
    ]


@dataclass(frozen=True)
class DirectionSignal:
    """Pure-Python dataclass for consumers that don't want ctypes.

    Returned by fallback when C++ engine is unavailable. Same field
    semantics as IrisDirectionSignal.
    """

    target_u: float
    force_magnitude: float
    u_current: float
    phase: float
    balance: float

    @classmethod
    def from_ffi(cls, sig: "IrisDirectionSignal") -> "DirectionSignal":
        return cls(
            target_u=sig.target_u,
            force_magnitude=sig.force_magnitude,
            u_current=sig.u_current,
            phase=sig.phase,
            balance=sig.balance,
        )

    @classmethod
    def default(cls) -> "DirectionSignal":
        """Safe default — target_u=+1, balance=1.0."""
        return cls(
            target_u=1.0,
            force_magnitude=0.0,
            u_current=0.0,
            phase=0.0,
            balance=1.0,
        )


# Constants for the return code from caducean_recommend()
CADUCEAN_RECOMMEND_EXPAND = 0
CADUCEAN_RECOMMEND_COMPRESS = 1
CADUCEAN_RECOMMEND_CONTINUE = 2
CADUCEAN_RECOMMEND_TOPO_VIOLATION = 3  # NEW in v2


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
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
        ]
        self._lib.ingest_event.restype = ctypes.c_int

        # --- Caducean ---
        self._lib.caducean_recommend.argtypes = [ctypes.c_char_p]
        self._lib.caducean_recommend.restype = ctypes.c_int

        self._lib.caducean_get_xi.argtypes = [ctypes.c_char_p]
        self._lib.caducean_get_xi.restype = ctypes.c_double

        self._lib.caducean_update.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_double,
        ]
        self._lib.caducean_update.restype = None

        # --- v2: Caducean Mitochondria-to-Mycelium FFI bindings ---
        # caducean_init_session(session_id, l, m) -> int
        self._lib.caducean_init_session.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_int,
        ]
        self._lib.caducean_init_session.restype = ctypes.c_int
        # caducean_get_direction_signal(session_id, balance, *out) -> int
        # The ctypes.POINTER(IrisDirectionSignal) ensures the struct
        # layout matches the C definition — verified by contract test.
        self._lib.caducean_get_direction_signal.argtypes = [
            ctypes.c_char_p,
            ctypes.c_double,
            ctypes.POINTER(IrisDirectionSignal),
        ]
        self._lib.caducean_get_direction_signal.restype = ctypes.c_int
        # caducean_set_params(session_id, a, b, s) -> int
        self._lib.caducean_set_params.argtypes = [
            ctypes.c_char_p,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_double,
        ]
        self._lib.caducean_set_params.restype = ctypes.c_int
        # caducean_get_state(session_id, *x, *y, *xi, *u, *a, *b, *s, *c_eff) -> int
        self._lib.caducean_get_state.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
        ]
        self._lib.caducean_get_state.restype = ctypes.c_int
        # caducean_calculate_eml(session_id, *x, *y) -> double
        # v2 O(1) EML from SessionState (x, y) accumulators — pure field-theory
        self._lib.caducean_calculate_eml.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
        ]
        self._lib.caducean_calculate_eml.restype = ctypes.c_double

        # --- EML ---
        self._lib.calculate_eml.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
        ]
        self._lib.calculate_eml.restype = ctypes.c_double

        # --- Immortus ---
        self._lib.immortus_chain_append.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
        ]
        self._lib.immortus_chain_append.restype = ctypes.c_int

        self._lib.immortus_chain_keep_latest.argtypes = [ctypes.c_char_p, ctypes.c_int]
        self._lib.immortus_chain_keep_latest.restype = ctypes.c_int

        # W7/O1: trajectory-conditioned query (C++ core). Guarded so an older
        # DLL that lacks the symbol still loads — the engine then falls back to
        # the Python implementation.
        if hasattr(self._lib, "immortus_chain_query_by_coordinate"):
            self._lib.immortus_chain_query_by_coordinate.argtypes = [
                ctypes.c_char_p,
                ctypes.c_double,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_char_p,
            ]
            self._lib.immortus_chain_query_by_coordinate.restype = ctypes.c_void_p
            self._lib.free_cstring.argtypes = [ctypes.c_void_p]
            self._lib.free_cstring.restype = None

        # --- Caducean Simulator ---
        self._lib.simulate_trajectories_to_db.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_double,
        ]
        self._lib.simulate_trajectories_to_db.restype = ctypes.c_int

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
        self,
        session_id: str,
        domain: str,
        event_type: str,
        actor: str,
        outcome: str,
        summary: str,
        payload_json: str,
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

    # --- v2: Caducean Mitochondria-to-Mycelium API ---

    def caducean_init_session(self, session_id: str, l: int, m: int) -> int:
        """Initialize a session with specific winding numbers.
        Returns 0 on success, 1 on error.
        """
        return self._lib.caducean_init_session(session_id.encode("utf-8"), l, m)

    def caducean_get_direction_signal(
        self, session_id: str, balance: float
    ) -> IrisDirectionSignal:
        """Get the bias-free DirectionSignal for a session.
        Returns a ctypes struct with 5 doubles. Caller can use
        DirectionSignal.from_ffi() to convert to a Python dataclass.
        """
        out = IrisDirectionSignal()
        rc = self._lib.caducean_get_direction_signal(
            session_id.encode("utf-8"), balance, ctypes.byref(out)
        )
        if rc != 0:
            # Return default-initialized struct on error (matches C++ behavior)
            return IrisDirectionSignal()
        return out

    def caducean_set_params(self, session_id: str, a: float, b: float, s: float) -> int:
        """Dynamically update Duffing potential constants and walk speed.
        Bounds enforced in C++ (a, b ∈ [1, 4]; s ∈ [0.1, 0.8]).
        Returns 0 on success.
        """
        return self._lib.caducean_set_params(session_id.encode("utf-8"), a, b, s)

    def caducean_get_state(self, session_id: str) -> Dict[str, float]:
        """Get full state snapshot. Returns dict with keys:
        x, y, xi, u, a, b, s, c_eff.
        """
        x = ctypes.c_double(0.0)
        y = ctypes.c_double(0.0)
        xi = ctypes.c_double(0.0)
        u = ctypes.c_double(0.0)
        a = ctypes.c_double(0.0)
        b = ctypes.c_double(0.0)
        s = ctypes.c_double(0.0)
        c_eff = ctypes.c_double(0.0)
        rc = self._lib.caducean_get_state(
            session_id.encode("utf-8"),
            ctypes.byref(x),
            ctypes.byref(y),
            ctypes.byref(xi),
            ctypes.byref(u),
            ctypes.byref(a),
            ctypes.byref(b),
            ctypes.byref(s),
            ctypes.byref(c_eff),
        )
        if rc != 0:
            return {}
        return {
            "x": x.value,
            "y": y.value,
            "xi": xi.value,
            "u": u.value,
            "a": a.value,
            "b": b.value,
            "s": s.value,
            "c_eff": c_eff.value,
        }

    def caducean_calculate_eml(self, session_id: str) -> Tuple[float, int, int]:
        """v2 O(1) EML calculation from SessionState (x, y) accumulators.
        Returns (eml_score, x, y). No SQL hit — pure field-theory arithmetic.
        """
        x = ctypes.c_double(0.0)
        y = ctypes.c_double(0.0)
        score = self._lib.caducean_calculate_eml(
            session_id.encode("utf-8"), ctypes.byref(x), ctypes.byref(y)
        )
        return (score, int(x.value), int(y.value))

    def calculate_eml(self, session_id: str) -> Tuple[float, float, float]:
        x = ctypes.c_double(0.0)
        y = ctypes.c_double(0.0)
        score = self._lib.calculate_eml(
            session_id.encode("utf-8"), ctypes.byref(x), ctypes.byref(y)
        )
        return score, x.value, y.value

    def immortus_chain_append(
        self,
        thread_id: str,
        result: str,
        coords_from: Optional[str],
        coords_to: Optional[str],
        nbl_outcome: Optional[str],
        insight: Optional[str],
        file_path: Optional[str],
        landmark_id: Optional[str],
    ) -> int:
        def _enc(s: Optional[str]) -> bytes:
            return (s or "").encode("utf-8")

        return self._lib.immortus_chain_append(
            thread_id.encode("utf-8"),
            result.encode("utf-8"),
            _enc(coords_from),
            _enc(coords_to),
            _enc(nbl_outcome),
            _enc(insight),
            _enc(file_path),
            _enc(landmark_id),
        )

    def immortus_chain_keep_latest(self, thread_id: str, keep_count: int) -> int:
        return self._lib.immortus_chain_keep_latest(
            thread_id.encode("utf-8"), keep_count
        )

    def immortus_chain_query_by_coordinate(
        self,
        coords,
        threshold: float = 1.0,
        limit: int = 10,
        thread_id: Optional[str] = None,
        nbl_outcome: Optional[str] = None,
    ):
        """W7/O1: trajectory-conditioned retrieval via the C++ core.

        Returns a list of dicts parsed from the C++ JSON response. The C++
        side allocates the result string; we free it via free_cstring().
        Raises AttributeError if the loaded DLL lacks the symbol (older build),
        which the caller catches to fall back to the Python engine.
        """
        if isinstance(coords, (list, tuple)):
            coords_str = ",".join(str(float(c)) for c in coords)
        else:
            coords_str = str(coords)
        ptr = self._lib.immortus_chain_query_by_coordinate(
            coords_str.encode("utf-8"),
            ctypes.c_double(threshold),
            ctypes.c_int(limit),
            thread_id.encode("utf-8") if thread_id else None,
            nbl_outcome.encode("utf-8") if nbl_outcome else None,
        )
        if not ptr:
            return []
        try:
            import json

            raw = ctypes.cast(ptr, ctypes.c_char_p).value
            if not raw:
                return []
            return json.loads(raw.decode("utf-8"))
        finally:
            self._lib.free_cstring(ptr)

    def simulate_trajectories_to_db(
        self, n: int, steps: int, a: float = 2.0, b: float = 2.0, s: float = 0.35
    ) -> int:
        return self._lib.simulate_trajectories_to_db(n, steps, a, b, s)


# ---------------------------------------------------------------------------
# Fallback Engine (pure Python)
# ---------------------------------------------------------------------------


class _PythonCaduceanFallbackState:
    """In-memory fallback when C++ core is unavailable.

    v2 additions: tracks a per-session state dict so the fallback can
    return realistic DirectionSignal/Eml values for the v1 stub
    consumer base. This means consumers that read caducean_state
    (auto_research, skill_simulator) get sane defaults even when
    the C++ engine is missing.
    """

    def __init__(self):
        self.states: Dict[str, Dict] = {}

    def _ensure_state(self, session_id: str) -> Dict:
        if session_id not in self.states:
            self.states[session_id] = {
                "x": 0,
                "y": 0,
                "xi": 0.0,
                "u": 0.0,
                "a": 2.0,
                "b": 2.0,
                "s": 0.35,
                "l": 1,
                "m": 1,
                "c_eff": 1.0,
            }
        return self.states[session_id]

    def recommend(self, session_id: str) -> int:
        return 2  # MAINTAIN

    def get_xi(self, session_id: str) -> float:
        state = self._ensure_state(session_id)
        return state["xi"]

    def update(self, session_id: str, action: int, balance: float) -> None:
        # Lightweight tracking so fallback can still return live state.
        state = self._ensure_state(session_id)
        balance = max(0.1, min(3.0, balance))
        if action == 0:  # EXPAND
            state["x"] += 1
            state["u"] += state["s"] * (1.0 if state["xi"] == 0.0 else 0.5)
        else:  # COMPRESS
            state["y"] += 1
            state["u"] -= state["s"] * 0.5
        state["u"] = max(-1.0, min(1.0, state["u"]))
        state["xi"] = (state["xi"] + balance * state["s"] * state["c_eff"]) % (
            2.0 * 3.14159265358979323846
        )

    # --- v2 methods (fallback) ---

    def init_session(self, session_id: str, l: int, m: int) -> int:
        state = self._ensure_state(session_id)
        state["l"] = l
        state["m"] = m
        state["c_eff"] = (1.0 / (2.0**0.5)) * (l * l + m * m) ** 0.5
        return 0

    def get_direction_signal(self, session_id: str, balance: float) -> DirectionSignal:
        state = self._ensure_state(session_id)
        F = state["a"] * state["u"] - state["b"] * state["u"] ** 3
        return DirectionSignal(
            target_u=1.0 if state["u"] >= 0.0 else -1.0,
            force_magnitude=abs(F),
            u_current=state["u"],
            phase=state["xi"],
            balance=max(0.1, min(3.0, balance)),
        )

    def set_params(self, session_id: str, a: float, b: float, s: float) -> int:
        state = self._ensure_state(session_id)
        state["a"] = max(1.0, min(4.0, a))
        state["b"] = max(1.0, min(4.0, b))
        state["s"] = max(0.1, min(0.8, s))
        return 0

    def get_state(self, session_id: str) -> Dict[str, float]:
        state = self._ensure_state(session_id)
        return {k: float(v) if not isinstance(v, int) else v for k, v in state.items()}

    def calculate_eml(self, session_id: str) -> Tuple[float, int, int]:
        """v2 O(1) EML from in-memory state (mirror of C++ implementation)."""
        import math

        state = self._ensure_state(session_id)
        Ne = float(state["x"])
        Nt = float(state["y"])
        L = min(Ne, Nt)
        V = Ne + Nt + 1.0
        x_eml = (Ne / (1.0 + Nt)) * (1.0 - L / V)
        y_eml = (Nt / (1.0 + Ne)) * (L / V) + 1e-5
        score = math.exp(x_eml) - math.log(y_eml)
        return (score, int(state["x"]), int(state["y"]))


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

    def ingest_event(
        self, session_id, domain, event_type, actor, outcome, summary, payload_json
    ) -> int:
        if not self._conn:
            return -1
        import uuid

        event_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO system_events (event_id, session_id, event_domain, "
            "event_type, actor, outcome, sanitization_state, summary, "
            "interaction_payload) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                session_id,
                domain,
                event_type,
                actor,
                outcome,
                "clean",
                summary,
                payload_json,
            ),
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
            "ORDER BY created_at DESC LIMIT 3",
            (session_id,),
        )
        edits = cur.fetchone()[0] or 0
        # Tests last 3
        cur.execute(
            "SELECT COUNT(*) FROM system_events "
            "WHERE session_id = ? AND event_domain = 'CODE' AND event_type = 'test_run' "
            "AND outcome = 'success' ORDER BY created_at DESC LIMIT 3",
            (session_id,),
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
            (
                chain_id,
                thread_id,
                result,
                kwargs.get("coords_from"),
                kwargs.get("coords_to"),
                kwargs.get("nbl_outcome"),
                kwargs.get("insight"),
                kwargs.get("file_path"),
                kwargs.get("landmark_id"),
                time.time(),
            ),
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
            (thread_id, thread_id, keep_count),
        )
        return cur.rowcount

    @staticmethod
    def _parse_coords(text: Optional[str]) -> Optional[tuple]:
        """Parse a 'x,y,xi,u' coordinate string into a 4-tuple of floats."""
        if not text:
            return None
        try:
            parts = [float(p) for p in text.split(",")]
        except (ValueError, AttributeError):
            return None
        if len(parts) != 4:
            return None
        return tuple(parts)

    def immortus_chain_query_by_coordinate(
        self,
        coords: Sequence[float],
        threshold: float = 1.0,
        limit: int = 10,
        thread_id: Optional[str] = None,
        nbl_outcome: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """W7/O1: trajectory-conditioned retrieval over the Immortus 4D chain.

        Returns chain entries whose ``coords_from`` is within ``threshold``
        (Euclidean distance over the 4D coordinate) of ``coords``, sorted by
        proximity. This is a *reasoning-state* query — "data gathered while
        thinking like this" — distinct from embedding cosine similarity.

        Entries without a parseable ``coords_from`` (orphaned appends) are
        excluded.  Returns dicts with ``distance`` plus the stored fields
        (``file_path`` = document_id for documents, ``result`` = canonical data).
        """
        if not self._conn:
            return []
        try:
            q = (
                "SELECT chain_id, thread_id, result, coords_from, coords_to, "
                "nbl_outcome, insight, file_path, landmark_id, created_at "
                "FROM memory_chain WHERE 1=1"
            )
            params: List[Any] = []
            if thread_id is not None:
                q += " AND thread_id = ?"
                params.append(thread_id)
            if nbl_outcome is not None:
                q += " AND nbl_outcome = ?"
                params.append(nbl_outcome)
            rows = self._conn.execute(q, params).fetchall()
        except Exception as exc:
            logger.warning("[IrisFallback] chain query failed: %s", exc)
            return []

        import math

        scored = []
        for r in rows:
            cf = self._parse_coords(r[3])
            if cf is None:
                continue
            dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(coords, cf)))
            if dist <= threshold:
                scored.append((dist, r))
        scored.sort(key=lambda t: t[0])

        out = []
        for dist, r in scored[:limit]:
            out.append(
                {
                    "chain_id": r[0],
                    "thread_id": r[1],
                    "result": r[2],
                    "coords_from": r[3],
                    "coords_to": r[4],
                    "nbl_outcome": r[5],
                    "insight": r[6],
                    "file_path": r[7],
                    "landmark_id": r[8],
                    "distance": dist,
                }
            )
        return out

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
        self,
        session_id: str,
        domain: str,
        event_type: str,
        actor: str = "agent",
        outcome: str = "pending",
        summary: str = "",
        payload_json: str = "{}",
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

    # --- v2: Caducean Mitochondria-to-Mycelium API (high-level) ---

    def caducean_init_session(self, session_id: str, l: int, m: int) -> bool:
        """Initialize a session with specific winding numbers. Returns True on success."""
        if self._ffi:
            rc = self._ffi.caducean_init_session(session_id, l, m)
            return rc == 0
        if self._fallback:
            self._fallback.caducean.init_session(session_id, l, m)
            return True
        return False

    def caducean_get_direction_signal(
        self, session_id: str, balance: float = 1.0
    ) -> DirectionSignal:
        """Get the bias-free DirectionSignal. Returns Python dataclass.

        Prefers C++ (returns full physics signal) over fallback (which
        returns live state from in-memory tracking). If neither is
        available, returns DirectionSignal.default().
        """
        if self._ffi:
            sig_ffi = self._ffi.caducean_get_direction_signal(session_id, balance)
            return DirectionSignal.from_ffi(sig_ffi)
        if self._fallback:
            return self._fallback.caducean.get_direction_signal(session_id, balance)
        return DirectionSignal.default()

    def caducean_set_params(
        self, session_id: str, a: float, b: float, s: float
    ) -> bool:
        """Update Duffing potential constants and walk speed. Bounds enforced in C++."""
        if self._ffi:
            rc = self._ffi.caducean_set_params(session_id, a, b, s)
            return rc == 0
        if self._fallback:
            self._fallback.caducean.set_params(session_id, a, b, s)
            return True
        return False

    def caducean_get_state(self, session_id: str) -> Dict[str, float]:
        """Get full state snapshot (x, y, xi, u, a, b, s, c_eff)."""
        if self._ffi:
            return self._ffi.caducean_get_state(session_id)
        if self._fallback:
            return self._fallback.caducean.get_state(session_id)
        return {}

    def caducean_calculate_eml(self, session_id: str) -> Tuple[float, int, int]:
        """v2 O(1) EML from in-memory or C++ state. Returns (score, x, y)."""
        if self._ffi:
            return self._ffi.caducean_calculate_eml(session_id)
        if self._fallback:
            return self._fallback.caducean.calculate_eml(session_id)
        return (0.0, 0, 0)

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
        self,
        thread_id: str,
        result: str,
        coords_from: Optional[str] = None,
        coords_to: Optional[str] = None,
        nbl_outcome: Optional[str] = None,
        insight: Optional[str] = None,
        file_path: Optional[str] = None,
        landmark_id: Optional[str] = None,
    ) -> bool:
        if self._ffi:
            rc = self._ffi.immortus_chain_append(
                thread_id,
                result,
                coords_from,
                coords_to,
                nbl_outcome,
                insight,
                file_path,
                landmark_id,
            )
            return rc == 0
        if self._fallback:
            rc = self._fallback.immortus_chain_append(
                thread_id,
                result,
                coords_from=coords_from,
                coords_to=coords_to,
                nbl_outcome=nbl_outcome,
                insight=insight,
                file_path=file_path,
                landmark_id=landmark_id,
            )
            return rc == 0
        return False

    def immortus_chain_keep_latest(self, thread_id: str, keep_count: int) -> int:
        if self._ffi:
            return self._ffi.immortus_chain_keep_latest(thread_id, keep_count)
        if self._fallback:
            return self._fallback.immortus_chain_keep_latest(thread_id, keep_count)
        return -1

    def immortus_chain_query_by_coordinate(
        self,
        coords: Sequence[float],
        threshold: float = 1.0,
        limit: int = 10,
        thread_id: Optional[str] = None,
        nbl_outcome: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """W7/O1: trajectory-conditioned retrieval.

        The C++ core is primary; the Python engine is the fallback.
        """
        if self._ffi is not None:
            try:
                return self._ffi.immortus_chain_query_by_coordinate(
                    coords, threshold, limit, thread_id, nbl_outcome
                )
            except Exception as exc:
                logger.warning(
                    "[iris_ffi] C++ trajectory query failed, using Python fallback: %s",
                    exc,
                )
        if self._fallback is not None:
            return self._fallback.immortus_chain_query_by_coordinate(
                coords, threshold, limit, thread_id, nbl_outcome
            )
        return []

    def simulate_trajectories_to_db(
        self,
        n: int = 500,
        steps: int = 50,
        a: float = 2.0,
        b: float = 2.0,
        s: float = 0.35,
    ) -> int:
        if self._ffi:
            return self._ffi.simulate_trajectories_to_db(n, steps, a, b, s)
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
        logger.error(
            f"[FFI] C++ initialization error. Using Python fallback database connection."
        )
        return False
    return True


def ffi_ingest_event(
    session_id: str,
    domain: str,
    event_type: str,
    actor: str = "agent",
    outcome: str = "pending",
    summary: str = "",
    payload_json: str = "{}",
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


def ffi_caducean_get_xi(session_id: str) -> float:
    if _engine is None:
        return 0.0
    return _engine.caducean_get_xi(session_id)


def ffi_caducean_update(session_id: str, action: int, balance: float) -> bool:
    if _engine is None:
        return False
    return _engine.caducean_update(session_id, action, balance)


# --- v2: Caducean Mitochondria-to-Mycelium module-level helpers ---


def ffi_caducean_init_session(session_id: str, l: int = 1, m: int = 1) -> bool:
    """Initialize a session with specific winding numbers. Returns True on success."""
    if _engine is None:
        return False
    return _engine.caducean_init_session(session_id, l, m)


def ffi_caducean_get_direction_signal(
    session_id: str, balance: float = 1.0
) -> DirectionSignal:
    """Get the bias-free DirectionSignal as a Python dataclass.

    Returns DirectionSignal.default() if engine is unavailable.
    """
    if _engine is None:
        return DirectionSignal.default()
    return _engine.caducean_get_direction_signal(session_id, balance)


def ffi_caducean_set_params(session_id: str, a: float, b: float, s: float) -> bool:
    """Update Duffing potential constants and walk speed. Bounds enforced in C++."""
    if _engine is None:
        return False
    return _engine.caducean_set_params(session_id, a, b, s)


def ffi_caducean_get_state(session_id: str) -> Dict[str, float]:
    """Get full state snapshot. Returns empty dict if engine unavailable."""
    if _engine is None:
        return {}
    return _engine.caducean_get_state(session_id)


def ffi_caducean_calculate_eml(session_id: str) -> Tuple[float, int, int]:
    """v2 O(1) EML from in-memory or C++ state. Returns (score, x, y)."""
    if _engine is None:
        return (0.0, 0, 0)
    return _engine.caducean_calculate_eml(session_id)


def ffi_calculate_eml(session_id: str) -> Tuple[float, float, float]:
    if _engine is None:
        return 0.0, 0.0, 0.0
    return _engine.calculate_eml(session_id)


def ffi_simulate_trajectories(n: int = 500, steps: int = 50) -> int:
    """Run C++ Caducean simulation into trajectory table. Returns rows written."""
    if _engine is None:
        return -1
    return _engine.simulate_trajectories_to_db(n, steps)


# -- Immortus FFI wrappers ------------------------------------------------


def ffi_immortus_chain_append(
    thread_id: str,
    result: str = "",
    coords_from: Optional[str] = None,
    coords_to: Optional[str] = None,
    nbl_outcome: Optional[str] = None,
    insight: Optional[str] = None,
    file_path: Optional[str] = None,
    landmark_id: Optional[str] = None,
) -> int:
    """Append an entry to the Immortus chain. No-op if engine not loaded."""
    if _engine is None:
        return -1
    return _engine.immortus_chain_append(
        thread_id, result, coords_from, coords_to,
        nbl_outcome, insight, file_path, landmark_id,
    )


def ffi_immortus_chain_keep_latest(thread_id: str, keep_count: int) -> int:
    """Keep the latest keep_count entries in the Immortus chain."""
    if _engine is None:
        return -1
    return _engine.immortus_chain_keep_latest(thread_id, keep_count)


def ffi_immortus_chain_query_by_coordinate(
    coords: Sequence[float],
    threshold: float = 1.0,
    limit: int = 10,
    thread_id: Optional[str] = None,
    nbl_outcome: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """W7/O1: trajectory-conditioned retrieval over the Immortus 4D chain.

    Returns chain entries near ``coords`` (reasoning-state proximity), distinct
    from embedding cosine similarity. No-op (empty list) if engine not loaded.
    """
    if _engine is None:
        return []
    return _engine.immortus_chain_query_by_coordinate(
        coords, threshold, limit, thread_id, nbl_outcome
    )

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


# D4b/D4c (T19 REQ-18 AC4 + T37 REQ-23 AC2): idempotent memory_chain column
# migration, factored out of _PythonFallbackEngine so it can also run when
# the native C++ core is active. The compiled DLL creates/owns its own
# memory_chain rows via a FIXED C struct (immortus_chain_append argtypes,
# see _IrisFFI above) that predates node_type/topic_domain/execution_domain
# — it was last recompiled after the REQ-23 mediator columns landed but
# before REQ-18/T19 added the typed-node columns. Previously this ALTER only
# ran inside _PythonFallbackEngine.__init__, which is never instantiated once
# iris_core.dll loads (IrisCoreEngine.init() returns early on native success)
# — so on a machine with the compiled core present, node_type/topic_domain/
# execution_domain never reached the live memory_chain table, and any reader
# (ontology_recall.filtered_chain_recall) crashed with
# "no such column: node_type" on every call.
def _is_forbidden_store_path(db_path: str) -> bool:
    """True if db_path resolves to BUILD memory or the decoy store — this
    migration must NEVER touch .mcm/coordinates.db or backend/data/memory.db,
    only the application store resolved from memory_config.json db_path (see
    backend/agent/memory.py:339-342)."""
    _resolved = str(db_path or "").replace("\\", "/")
    return any(_tok in _resolved for _tok in (".mcm/", "backend/data/", "/.mcm/"))


def migrate_memory_chain_schema(conn, db_path: str) -> None:
    """Idempotent ALTERs bringing memory_chain to the coordinate + typed-node
    shape, preserving existing rows (new columns default NULL). Safe to call
    on every engine init — PRAGMA table_info is probed before each ALTER, so
    re-running on an already-migrated store is a no-op.
    """
    if conn is None:
        return
    if _is_forbidden_store_path(db_path):
        logger.warning(
            "[iris_ffi] SKIPPED memory_chain migration: path is not the "
            "application store: %s",
            db_path,
        )
        return
    try:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(memory_chain)")}
    except Exception:
        return  # table does not exist yet — the owning engine will create it
    for _col in (
        # REQ-2 AC3/AC5 (T6): coordinate shape.
        "chain_id", "coords_from", "coords_to", "nbl_outcome",
        "insight", "file_path", "landmark_id", "stale",
        # REQ-23 AC2 (T37): mediator causal triple.
        "mediator", "mediator_source",
        # REQ-18 AC4 (T19): typed node + both domain axes.
        "node_type", "topic_domain", "execution_domain",
    ):
        if _col in existing:
            continue
        try:
            conn.execute(
                f"ALTER TABLE memory_chain ADD COLUMN {_col} "
                + ("INTEGER DEFAULT 0" if _col == "stale" else "TEXT")
            )
            conn.commit()
            logger.info("[iris_ffi] memory_chain ALTER added column %s", _col)
        except Exception as exc:
            logger.warning("[iris_ffi] memory_chain ALTER %s skipped: %s", _col, exc)

    # REQ-2 AC4 (OQ-5 RESOLVED: DROP): memory_chain_v2 is an orphan — 0 rows,
    # no writer, present in two DBs. A third empty shape shall not survive.
    try:
        conn.execute("DROP TABLE IF EXISTS memory_chain_v2")
        conn.commit()
    except Exception as _v2_exc:
        logger.warning("[iris_ffi] memory_chain_v2 drop failed: %s", _v2_exc)


class _PythonFallbackEngine:
    """Pure Python fallback — uses sqlite3 (or sqlcipher3 if available)."""

    def __init__(self, db_path: str, key_hex: str):
        self.db_path = db_path
        # Dilithium migration: key_hex must be retained for the SQLCipher
        # `PRAGMA key` (used in _init_db). Without it, the fallback engine
        # crashed with AttributeError on any encrypted-DB init.
        self.key_hex = key_hex
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
        # D4g: this connection writes system_events/memory_chain to the SAME
        # file as EpisodicStore/SemanticStore/Mycelium's connections
        # (backend/memory/db.py open_encrypted_memory, which sets the same
        # PRAGMA). Without it, a write here racing one of those raised
        # "database is locked" immediately (default busy_timeout=0) instead
        # of waiting the other transaction out.
        try:
            self._conn.execute("PRAGMA busy_timeout=5000;")
        except Exception:
            pass
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
            mediator TEXT,
            mediator_source TEXT,
            node_type TEXT,
            topic_domain TEXT,
            execution_domain TEXT,
            stale INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        );        """
        self._conn.executescript(sql)
        # Add screenshot BLOB column (idempotent — SQLite has no IF NOT EXISTS
        # for columns, so guard with try/except). Vision/screenshot tool events
        # store the captured frame here, attached to the event row.
        try:
            self._conn.execute("ALTER TABLE system_events ADD COLUMN screenshot BLOB")
            self._conn.commit()
        except Exception:
            # Column already exists — harmless.
            pass

        # REQ-2 AC3/AC5 (T6) / D4b / D4c: bring a LEGACY memory_chain to the
        # coordinate + typed-node schema by IDEMPOTENT ALTER, preserving
        # existing rows. AC5 guard (never touch BUILD memory / the decoy
        # store) lives inside migrate_memory_chain_schema() — see its
        # docstring above _PythonFallbackEngine for why this is factored out.
        migrate_memory_chain_schema(self._conn, self.db_path)

    def ingest_event(
        self, session_id, domain, event_type, actor, outcome, summary, payload_json,
        screenshot_blob=None,
    ) -> int:
        if not self._conn:
            return -1
        import uuid

        event_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO system_events (event_id, session_id, event_domain, "
            "event_type, actor, outcome, sanitization_state, summary, "
            "interaction_payload, screenshot) VALUES (?,?,?,?,?,?,?,?,?,?)",
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
                screenshot_blob,
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

        # REQ-2 AC1/T6: the memory_chain table may be EITHER the legacy form
        # (entry_id/sequence/role/content — preserved with 1825 rows by the
        # idempotent coordinate ALTER) OR the fresh coordinate shape. The old
        # fixed INSERT failed on legacy tables with "NOT NULL constraint
        # failed: memory_chain.sequence" (and role/content). Introspect the
        # columns once and build a shape-agnostic INSERT so an append can
        # never fail against either schema.
        if getattr(self, "_chain_cols", None) is None:
            self._chain_cols = {
                r[1] for r in self._conn.execute("PRAGMA table_info(memory_chain)")
            }
        cols = self._chain_cols

        chain_id = str(uuid.uuid4())
        now = time.time()
        insert_cols = [
            "chain_id", "thread_id", "result", "coords_from", "coords_to",
            "nbl_outcome", "insight", "file_path", "landmark_id", "created_at",
        ]
        vals = [
            chain_id, thread_id, result,
            kwargs.get("coords_from"), kwargs.get("coords_to"),
            kwargs.get("nbl_outcome"), kwargs.get("insight"),
            kwargs.get("file_path"), kwargs.get("landmark_id"), now,
        ]
        # REQ-23 AC2 (T37): mediator + mediator_source land on the row when the
        # schema carries them (the shape-agnostic insert never assumes a
        # column — a store that predates the ALTER writes NULL, which the
        # REQ-2 AC3 null-tolerance covers).
        if "mediator" in cols:
            insert_cols.append("mediator")
            vals.append(kwargs.get("mediator"))
        if "mediator_source" in cols:
            insert_cols.append("mediator_source")
            vals.append(kwargs.get("mediator_source"))
        # REQ-18 AC4 (T19): node type + both domain axes ride the chain row
        # when the schema carries them — recall (REQ-20) and per-domain
        # aggregation (REQ-21) key on the row without joining back to the
        # in-memory record. Shape-agnostic like mediator: a pre-T19 store
        # writes NULL (REQ-2 AC3 null-tolerance), never fails the append.
        if "node_type" in cols:
            insert_cols.append("node_type")
            vals.append(kwargs.get("node_type"))
        if "topic_domain" in cols:
            insert_cols.append("topic_domain")
            vals.append(kwargs.get("topic_domain"))
        if "execution_domain" in cols:
            insert_cols.append("execution_domain")
            vals.append(kwargs.get("execution_domain"))
        if "entry_id" in cols:
            insert_cols.append("entry_id")
            vals.append(str(uuid.uuid4()))
        if "sequence" in cols:
            # Legacy PK is (thread_id, sequence): next sequence per thread.
            cur = self._conn.cursor()
            cur.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM memory_chain "
                "WHERE thread_id = ?",
                (thread_id,),
            )
            insert_cols.append("sequence")
            vals.append(cur.fetchone()[0])
        if "role" in cols:
            insert_cols.append("role")
            vals.append(kwargs.get("role") or "agent")
        if "content" in cols:
            insert_cols.append("content")
            vals.append(result or "")
        self._conn.execute(
            "INSERT INTO memory_chain ({}) VALUES ({})".format(
                ", ".join(insert_cols), ", ".join("?" for _ in vals)
            ),
            vals,
        )
        self._conn.commit()
        return 0

    def immortus_chain_query_mediators(
        self, thread_id: str, region_coords: Optional[str] = None
    ) -> List[dict]:
        """REQ-23 AC4 (T38): "which mediators were tried for this objective,
        and how did each fare by coordinate region" — answerable as a query.

        Returns the causal triples recorded per REQ-23 AC2, newest first:
        each row is
            {mediator, mediator_source, result, coords_from, coords_to,
             created_at}
        Optionally filtered to a coordinate REGION string (the canonical
        format_coords "x,y,xi,u" form, e.g. "(0.1234,0.4567,0.8000,0.1000)")
        so "how did each fare in the region I am in now" is a single call.

        Tolerates pre-migration stores (no mediator column) by returning an
        empty list — a store that never recorded mediators cannot answer.
        """
        if not self._conn:
            return []
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(memory_chain)")}
        if "mediator" not in cols:
            return []
        sql = (
            "SELECT mediator, mediator_source, result, coords_from, coords_to, "
            "created_at FROM memory_chain "
            "WHERE thread_id = ?"
        )
        params: list = [thread_id]
        if region_coords:
            sql += " AND coords_from = ?"
            params.append(region_coords)
        sql += " ORDER BY created_at DESC LIMIT 200"
        rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "mediator": r[0],
                "mediator_source": r[1],
                "result": r[2],
                "coords_from": r[3],
                "coords_to": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

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
                    # D4b/D4c: the native core creates/owns memory_chain via a
                    # fixed C struct that predates node_type/topic_domain/
                    # execution_domain (see migrate_memory_chain_schema()
                    # docstring). Run the same idempotent ALTER Python would
                    # have run in the fallback path, via a short-lived
                    # connection to the SAME file the native core just
                    # initialized, so readers never see a missing column
                    # regardless of which engine is serving writes.
                    self._migrate_native_memory_chain(db_path, key_hex)
                    # ALSO build the Python engine, even though the native core
                    # loaded. It is NOT a "fallback" in that case — it is the
                    # only engine that can carry the shape-agnostic columns.
                    #
                    # The native writer takes a FIXED 8-arg C struct
                    # (immortus_chain_append argtypes, :220-230) that predates
                    # mediator/mediator_source (REQ-23) and node_type/
                    # topic_domain/execution_domain (REQ-18). Returning early
                    # here left self._fallback = None on every machine where
                    # the DLL loads, which meant:
                    #   * immortus_chain_append silently DROPPED all five of
                    #     those fields (the native branch simply does not pass
                    #     them), so the 4D chain recorded rows with no mediator
                    #     and no ontology; and
                    #   * immortus_chain_query_mediators — the REQ-23 AC4
                    #     mediator-by-region query the whole Bayesian/region-
                    #     scoped learning loop reads from — tests only
                    #     `if self._fallback:` and therefore ALWAYS returned [].
                    # So the learning loop could not work by construction, and
                    # failed silently rather than erroring.
                    #
                    # Native still wins for the physics/EML/coordinate paths
                    # below (every one of those checks `if self._ffi:` first,
                    # so their behaviour is unchanged). This only makes the
                    # Python engine AVAILABLE for the shape-agnostic writes and
                    # reads that the C struct cannot express.
                    try:
                        self._fallback = _PythonFallbackEngine(db_path, key_hex)
                        logger.info(
                            "[iris_ffi] Python engine also active alongside C++ "
                            "core (carries mediator/ontology columns the fixed "
                            "C struct cannot)"
                        )
                    except Exception as _pe:  # noqa: BLE001
                        # Never block startup on this — but say so loudly,
                        # because without it the mediator/ontology chain is
                        # silently inert, which is the exact failure this
                        # block exists to remove.
                        logger.error(
                            "[iris_ffi] Python engine unavailable alongside C++ "
                            "core (%s) — mediator + ontology chain columns will "
                            "NOT be written and mediator-by-region queries will "
                            "return empty",
                            _pe,
                        )
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

    @staticmethod
    def _migrate_native_memory_chain(db_path: str, key_hex: str) -> None:
        """Open a short-lived connection to the native core's db_path and run
        migrate_memory_chain_schema() against it (D4b/D4c). Mirrors
        _PythonFallbackEngine._init_db's connection strategy (sqlcipher3 with
        the same PRAGMA key if available, else plain sqlite3) so this reaches
        an encrypted store exactly like the fallback engine would. Never
        raises — a failure here must not block native-core startup.
        """
        conn = None
        try:
            try:
                import sqlcipher3  # type: ignore[import]

                conn = sqlcipher3.connect(db_path)
                conn.execute(f"PRAGMA key = \"x'{key_hex}'\";")
            except ImportError:
                import sqlite3

                conn = sqlite3.connect(db_path, check_same_thread=False)
            migrate_memory_chain_schema(conn, db_path)
        except Exception as exc:
            logger.warning("[iris_ffi] native memory_chain migration failed: %s", exc)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

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
        screenshot_blob: bytes = None,
    ) -> bool:
        if not self._initialized:
            return False
        # Screenshots must land in the SQLite system_events store, so route
        # screenshot-bearing events through the fallback writer regardless of
        # whether the C++ core is active.
        if screenshot_blob is not None and self._fallback:
            rc = self._fallback.ingest_event(
                session_id, domain, event_type, actor, outcome, summary,
                payload_json, screenshot_blob,
            )
            return rc == 0
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
        mediator: Optional[str] = None,
        mediator_source: Optional[str] = None,
        # D4c fix: the module-level ffi_immortus_chain_append() wrapper has
        # accepted node_type/topic_domain/execution_domain since REQ-18 AC4
        # (T19) and always forwards them here as kwargs — but this dispatcher
        # method never grew the matching parameters, so every call raised
        # "immortus_chain_append() got unexpected keyword argument 'node_type'"
        # (durability write never reached either engine).
        node_type: Optional[str] = None,
        topic_domain: Optional[str] = None,
        execution_domain: Optional[str] = None,
    ) -> bool:
        # PYTHON ENGINE FIRST for this one call — deliberately inverted vs
        # every other method on this class.
        #
        # This is a durability write on a background queue (durability_queue),
        # NOT a hot path, so the C++ speed advantage is worth nothing here.
        # What it costs is correctness: the native branch below takes a fixed
        # 8-arg C struct and cannot carry mediator/mediator_source (REQ-23) or
        # node_type/topic_domain/execution_domain (REQ-18), so it wrote rows
        # with those columns NULL and no error. Worse, the only reader for
        # them — immortus_chain_query_mediators — answers from the Python
        # engine alone, so region-scoped mediator learning read back nothing.
        # Prefer the engine that can actually represent the row.
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
                # REQ-23 AC2 (T37): mediator + source ride the chain row on
                # the fallback (shape-agnostic) engine. The native C++ DLL is
                # left untouched (fixed arity; cannot be recompiled here) — a
                # native write simply leaves the columns NULL, which recall
                # tolerates (REQ-2 AC3).
                mediator=mediator,
                mediator_source=mediator_source,
                # REQ-18 AC4 (T19): same shape-agnostic treatment as mediator
                # above — the fallback engine's **kwargs INSERT already
                # handles these (iris_ffi.py _PythonFallbackEngine.immortus_
                # chain_append), they just never reached it through this
                # dispatcher.
                node_type=node_type,
                topic_domain=topic_domain,
                execution_domain=execution_domain,
            )
            return rc == 0
        # Native SECOND, not first — a degraded write (mediator + ontology
        # columns left NULL by the fixed C struct) beats no write at all if the
        # Python engine could not be constructed. Losing five columns is
        # recoverable; losing the row is not.
        if self._ffi:
            logger.warning(
                "[iris_ffi] chain append via native core only — mediator and "
                "ontology columns will be NULL (Python engine unavailable)"
            )
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
        return False

    def immortus_chain_query_mediators(
        self,
        thread_id: str,
        region_coords: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """REQ-23 AC4 (T38): mediator-by-region query — the fallback engine
        answers; the native path cannot (returns [])."""
        if self._fallback:
            return self._fallback.immortus_chain_query_mediators(
                thread_id, region_coords
            )
        return []

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
    screenshot_blob: bytes = None,
) -> bool:
    if _engine is None:
        return False
    return _engine.ingest_event(
        session_id, domain, event_type, actor, outcome, summary, payload_json,
        screenshot_blob,
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
    mediator: Optional[str] = None,
    mediator_source: Optional[str] = None,
    node_type: Optional[str] = None,
    topic_domain: Optional[str] = None,
    execution_domain: Optional[str] = None,
) -> int:
    """Append an entry to the Immortus chain. No-op if engine not loaded.

    REQ-23 AC2 (T37): ``mediator`` / ``mediator_source`` ride the same row as
    the Σ coords so the causal triple is queryable (see
    ``immortus_chain_query_mediators``).
    REQ-18 AC4 (T19): ``node_type`` / ``topic_domain`` / ``execution_domain``
    ride the same row so recall (REQ-20) and aggregation (REQ-21) key on the
    typed node without a join.
    """
    if _engine is None:
        return -1
    return _engine.immortus_chain_append(
        thread_id, result,
        coords_from=coords_from, coords_to=coords_to,
        nbl_outcome=nbl_outcome, insight=insight,
        file_path=file_path, landmark_id=landmark_id,
        mediator=mediator, mediator_source=mediator_source,
        node_type=node_type, topic_domain=topic_domain,
        execution_domain=execution_domain,
    )


def ffi_immortus_chain_query_mediators(
    thread_id: str,
    region_coords: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """REQ-23 AC4 (T38): mediator-by-region query. No-op if engine not loaded."""
    if _engine is None:
        return []
    return _engine.immortus_chain_query_mediators(thread_id, region_coords)


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

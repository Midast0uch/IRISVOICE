"""
MyceliumInterface — the single public access boundary for the Mycelium coordinate layer.

ONLY import from this module in external code.  All other mycelium/*.py files are
package-internal implementation details.

Orchestrates:
  - Graph traversal and context path generation
  - Coordinate extraction (hardware, text, session, tool calls)
  - Landmark crystallisation, merging, and lifecycle
  - Resonance-augmented episode retrieval
  - Profile rendering
  - Maintenance (decay, condense, expand, landmark decay, profile render)
"""

import json
import logging
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.memory.db import app_flush, app_write
from .encoder import PathEncoder
from .extractor import CoordinateExtractor
from .landmark import Landmark, LandmarkCondenser, LandmarkIndex
from .navigator import CoordinateNavigator, SessionRegistry
from .profile import LandmarkMerger, ProfileRenderer
from .resonance import EpisodeIndexer, ResonanceScorer
from .scorer import EdgeScorer, MapManager
from .store import CoordinateStore, MemoryPath
from .registry import SpaceRegistry

logger = logging.getLogger(__name__)

# Kyudo HyphaChannel.USER - statements, session history and project context
# are the user's own signal (Kyudo Layer Guide, Part 1).
_USER_CHANNEL = 3


# ---------------------------------------------------------------------------
# ContextPackage — DER Director context (Req 14.1)
# ---------------------------------------------------------------------------

# Cap on the system-zone text a package contributes to a step prompt. 1,600
# chars is ~400 tokens: the zone header + coordinate path + partial profile
# measure a few hundred chars on real stores, and every DER step prompt already
# carries a ~300-token evidence block plus the working memory (6,000-char cap) -
# the memory stays a hint on the prompt and must not grow it.
CONTEXT_PACKAGE_MAX_CHARS: int = 1600
_CAP_MARKER = "\n...[context capped]"

# Time budget for building a package (seconds). The walk and the encode are
# required; topology, predictions and failures are optional and are skipped once
# the budget is spent - the package degrades, the turn is never delayed.
CONTEXT_PACKAGE_BUDGET_S: float = 0.15


def context_package_enabled() -> bool:
    """IRIS_MEMORY_CONTEXT_PACKAGE: default ON; "0" restores the string path."""
    return os.environ.get("IRIS_MEMORY_CONTEXT_PACKAGE", "1").strip() != "0"


@dataclass
class ContextPackage:
    """
    Assembled Mycelium context delivered to the Director before every cycle.
    All fields are strings — None-safe (empty string on missing data).
    """

    mycelium_path: str
    topology_path: str
    manifest: Dict[str, Any]
    tier1_directives: str
    tier2_predictions: str
    tier3_failures: str
    active_contracts: str
    gradient_warnings: str
    causal_context: str
    ambient_signals: str
    topology_position: str
    task_class: str
    _registered_addresses: List[str] = field(default_factory=list)

    def get_system_zone_content(self) -> str:
        parts = [
            self.active_contracts,
            self.gradient_warnings,
            self.causal_context,
            self.tier1_directives,
            self.mycelium_path,
            self.topology_path,
            self.ambient_signals,
        ]
        content = "\n".join(p for p in parts if p)
        if len(content) <= CONTEXT_PACKAGE_MAX_CHARS:
            return content
        # Over the cap: drop whole trailing lines (never half a line) and say so.
        room = CONTEXT_PACKAGE_MAX_CHARS - len(_CAP_MARKER)
        cut = content.rfind("\n", 0, room)
        return content[: cut if cut > 0 else room] + _CAP_MARKER

    def get_tier2_predictions(self) -> str:
        return self.tier2_predictions or ""

    def get_tier3_failures(self) -> str:
        return self.tier3_failures or ""

    def register_address(self, url: str, token_count: int, summary: str) -> None:
        self.manifest[url] = {"token_count": token_count, "summary": summary}
        self._registered_addresses.append(url)

    @property
    def topology_primitive(self) -> str:
        if not self.topology_path:
            return "unknown"
        # "primitives:[x]" is the documented form; the one producer,
        # TopologyLayer.encode_topology_context, writes "TOPOLOGY: prim:x z:+0.10".
        m = re.search(r"primitives:\[([a-z_]+)\]|\bprim:([a-z_]+)", self.topology_path)
        return (m.group(1) or m.group(2)) if m else "unknown"


@dataclass
class _ContextParts:
    """The pieces one context-path walk produces. get_context_path joins them
    into the string; build_context_package maps them onto ContextPackage."""

    task_class: str
    zone_header: str
    encoding: str
    partial_profile: str
    topology_suffix: str
    trajectory_label: str
    topology_skipped: bool = False


# ---------------------------------------------------------------------------
# Module-level constants (Req 12.1)
# ---------------------------------------------------------------------------

GRAPH_MATURITY_THRESHOLD: int = 3  # distinct spaces with ≥ 1 confident node
DISTILLATION_IDLE_THRESHOLD: int = 600  # seconds idle before maintenance is allowed
DISTILLATION_MAX_INTERVAL: int = 14400  # seconds max between forced maintenance passes


# ---------------------------------------------------------------------------
# MyceliumInterface
# ---------------------------------------------------------------------------


class MyceliumInterface:
    """
    Single public access boundary for the Mycelium coordinate memory layer (Req 12.1–12.11).

    External code (memory/interface.py, distillation.py, episodic.py, semantic.py)
    MUST interact with Mycelium only through this class.

    One instance per process — shares the encrypted SQLCipher connection.
    """

    def __init__(
        self,
        conn: "sqlcipher3.Connection",
        dev_mode: bool = False,
        graph_maturity_threshold: int = GRAPH_MATURITY_THRESHOLD,
        distillation_idle_threshold: int = DISTILLATION_IDLE_THRESHOLD,
    ) -> None:
        """
        Initialise the full Mycelium component stack.

        Args:
            conn:                        Open, authenticated SQLCipher connection.
                                         MUST be the shared process connection.
            dev_mode:                    Enables dev_dump().  False in production.
            graph_maturity_threshold:    Spaces needed to declare maturity.
            distillation_idle_threshold: Idle seconds before maintenance is allowed.
        """
        self._conn = conn
        self._dev_mode = dev_mode
        self._maturity_threshold = graph_maturity_threshold
        self._idle_threshold = distillation_idle_threshold

        # The coordinate spaces: seeded where a row is missing, then read ONCE.
        # Every list of spaces and every Kyudo term below derives from it.
        self._spaces: SpaceRegistry = SpaceRegistry.load(conn)
        # Writes the spaces' locks refused: (space_id, channel name) -> count.
        self.refused_writes: Dict[Tuple[str, str], int] = {}

        # Core components
        self._store = CoordinateStore(conn, self._spaces)
        self._registry = SessionRegistry()
        self._navigator = CoordinateNavigator(self._store, self._registry)
        self._encoder = PathEncoder()
        self._scorer = EdgeScorer(self._store)
        self._map_manager = MapManager(self._store)
        self._extractor = CoordinateExtractor(self._store)
        self._condenser = LandmarkCondenser(self._store)
        self._lm_index = LandmarkIndex(conn)
        self._merger = LandmarkMerger(self._lm_index)
        self._renderer = ProfileRenderer(self._store, self._lm_index)
        self._ep_indexer = EpisodeIndexer(conn, active_state=self._active_node_state)
        self._resonance = ResonanceScorer(conn, self._store)

        # Convenience public references for callers that need direct access
        self.episode_indexer: EpisodeIndexer = self._ep_indexer
        self.resonance_scorer: ResonanceScorer = self._resonance

        # State
        self._last_distillation_at: Optional[float] = None
        self._is_mature_cached: Optional[bool] = None
        self._is_mature_logged: bool = False
        self._maintenance_needed: bool = False
        self._last_task_class: Optional[str] = None
        # session -> (task text, task class) of its last context walk: what the
        # predictive pre-warm re-walks at the session boundary. Bounded.
        self._last_task: "OrderedDict[str, Tuple[str, str]]" = OrderedDict()
        self._crystallisation_suspended: bool = (
            False  # set True during QuorumReorganization, lifted at clear_session
        )
        # Sessions that recorded a threat signal (bounded): a session NOT in it
        # is clean, and the threat level fades at its end (Kyudo Part 4).
        self._signalled_sessions: "OrderedDict[str, None]" = OrderedDict()
        # Durable immune memory (mycelium_quorum_log): write counter drives the
        # retention trim; errors are counted (a store without the table must
        # keep working, but never silently).
        self._quorum_log_writes: int = 0
        self._quorum_log_errors: int = 0
        # SHADOW velocity signal: node upserts per session (bounded, in memory).
        self._session_upserts: "OrderedDict[str, int]" = OrderedDict()

        # Topology layer (Task 11.3) — eagerly instantiated
        from .topology import TopologyLayer  # noqa: PLC0415

        self._topology_layer: TopologyLayer = TopologyLayer(conn, self._store)

        # Context token tracking (Task 10.2)
        self._total_context_chars: int = 0
        self._context_task_count: int = 0

        # Kyudo security layer (Task 9.2) — eagerly instantiated
        from .kyudo import (  # noqa: PLC0415
            QuorumSensor,
            RagIngestionBridge,
            CellWall,
            TaskClassifier,
            PredictiveLoader,
            CHANNEL_WEIGHTS,
        )

        self._quorum_sensor: QuorumSensor = QuorumSensor()
        self._lm_index.activation_observer = self._observe_activation
        self._rag_bridge: RagIngestionBridge = RagIngestionBridge()
        self._cell_wall: CellWall = CellWall(self._spaces)
        self._task_classifier: TaskClassifier = TaskClassifier(self._spaces)
        self._predictive_loader: PredictiveLoader = PredictiveLoader(self._spaces)
        self._channel_weights = CHANNEL_WEIGHTS

        # MCP trust registry
        self._mcp_trust_registry: Dict[str, dict] = {}
        # Servers whose identity drifted from their pin: UNTRUSTED until re-pinned.
        self._mcp_untrusted: set = set()
        self._load_mcp_trust_registry()

        # Plan stats table (DER Gate 1 Step 1.8)
        self._ensure_tables()

        # A restart no longer erases the evidence: resume the threat level.
        self._restore_threat_level()

    # ------------------------------------------------------------------
    # Durable immune memory (mycelium_quorum_log)
    # ------------------------------------------------------------------

    def _restore_threat_level(self) -> None:
        """Set the sensor's threat level from the newest live (shadow=0) log row.

        One bounded read (ts index). A store without the table keeps a fresh
        sensor: counted and logged at debug, never raised.
        """
        try:
            row = self._conn.execute(
                "SELECT threat_after FROM mycelium_quorum_log "
                "WHERE shadow = 0 AND threat_after IS NOT NULL "
                "ORDER BY ts DESC, id DESC LIMIT 1"
            ).fetchone()
            if row is not None:
                self._quorum_sensor.threat_level = max(0.0, min(1.0, float(row[0])))
        except Exception as exc:  # noqa: BLE001
            self._quorum_log_errors += 1
            logger.debug("[interface] quorum_log restore failed (n=%d): %s",
                         self._quorum_log_errors, exc)

    def _log_quorum(
        self,
        session_id: str,
        signal_type: str,
        weight: float,
        shadow: bool = False,
        detail: Optional[str] = None,
    ) -> None:
        """Append one row to mycelium_quorum_log and trim to the newest
        QUORUM_LOG_RETAIN rows every QUORUM_LOG_PRUNE_EVERY writes.

        threat_after is the sensor's level AFTER the event (shadow rows leave
        it unchanged). Never raises; a failure is counted.
        """
        from .kyudo import QUORUM_LOG_PRUNE_EVERY, QUORUM_LOG_RETAIN  # noqa: PLC0415

        try:
            app_write(
                self._conn,
                "INSERT INTO mycelium_quorum_log "
                "(ts, session_id, signal_type, weight, threat_after, shadow, detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), session_id, signal_type, weight,
                 self._quorum_sensor.threat_level, 1 if shadow else 0, detail),
            )
            self._quorum_log_writes += 1
            if self._quorum_log_writes % QUORUM_LOG_PRUNE_EVERY == 0:
                app_write(
                    self._conn,
                    "DELETE FROM mycelium_quorum_log WHERE id <= "
                    "(SELECT id FROM mycelium_quorum_log ORDER BY id DESC "
                    "LIMIT 1 OFFSET ?)",
                    (QUORUM_LOG_RETAIN,),
                )
        except Exception as exc:  # noqa: BLE001
            self._quorum_log_errors += 1
            logger.debug("[interface] quorum_log write failed session=%s n=%d: %s",
                         session_id, self._quorum_log_errors, exc)

    def _note_upserts(self, session_id: str, n: int = 1) -> None:
        """SHADOW velocity signal: count node upserts for *session_id*; when
        the count first passes QUORUM_VELOCITY_THRESHOLD, log it once
        (shadow=1). threat_level is never touched. Never raises."""
        from .kyudo import QUORUM_VELOCITY_THRESHOLD  # noqa: PLC0415

        try:
            before = self._session_upserts.get(session_id, 0)
            after = before + n
            self._session_upserts[session_id] = after
            self._session_upserts.move_to_end(session_id)
            while len(self._session_upserts) > 256:
                self._session_upserts.popitem(last=False)
            if before <= QUORUM_VELOCITY_THRESHOLD < after:
                weight = self._quorum_sensor.record_shadow("update_velocity_anomaly")
                self._log_quorum(session_id, "update_velocity_anomaly", weight,
                                 shadow=True, detail=f"upserts={after}")
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] velocity shadow failed session=%s: %s",
                         session_id, exc)

    def _observe_activation(self, landmark_id: str, count: int) -> None:
        """SHADOW landmark_activation_anomaly: called by LandmarkIndex.activate
        with the new count. Logged shadow=1, never added to threat_level."""
        from .kyudo import activation_is_anomalous  # noqa: PLC0415

        try:
            _row = self._conn.execute(
                "SELECT task_class FROM mycelium_landmarks WHERE landmark_id = ?",
                (landmark_id,),
            ).fetchone()
            if _row is None:
                return
            task_class = _row[0]
            sibs = [r[0] for r in self._conn.execute(
                "SELECT activation_count FROM mycelium_landmarks "
                "WHERE task_class = ? AND absorbed IS NULL AND landmark_id != ? "
                "LIMIT 500",
                (task_class, landmark_id),
            ).fetchall()]
            if activation_is_anomalous(sibs, count):
                weight = self._quorum_sensor.record_shadow("landmark_activation_anomaly")
                self._log_quorum("", "landmark_activation_anomaly", weight, shadow=True,
                                 detail=f"landmark={landmark_id} class={task_class} count={count}")
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] activation shadow failed lm=%s: %s", landmark_id, exc)

    # ------------------------------------------------------------------
    # Plan stats table (Gate 1 Step 1.8)
    # ------------------------------------------------------------------

    def _ensure_tables(self) -> None:
        """
        Create mycelium_plan_stats table if it doesn't exist.
        Safe to call on every startup (IF NOT EXISTS).
        Never raises.
        """
        try:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS mycelium_plan_stats (
                    stat_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    task_class TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    total_steps INTEGER NOT NULL,
                    steps_completed INTEGER NOT NULL,
                    tokens_used INTEGER DEFAULT 0,
                    avg_step_duration_ms REAL DEFAULT 0.0,
                    outcome TEXT NOT NULL,
                    graph_mature INTEGER DEFAULT 0,
                    created_at REAL NOT NULL
                )
            """)
            self._conn.commit()
        except Exception:
            pass

    def record_plan_stats(
        self,
        session_id: str,
        task_class: str,
        strategy: str,
        total_steps: int,
        steps_completed: int,
        tokens_used: int,
        avg_step_duration_ms: float,
        outcome: str,
        graph_mature: bool,
    ) -> None:
        """
        Insert a plan execution record into mycelium_plan_stats.
        Never raises.
        """
        try:
            import uuid
            import time as _time

            app_write(
                self._conn,
                "INSERT INTO mycelium_plan_stats VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4())[:12],
                    session_id,
                    task_class,
                    strategy,
                    total_steps,
                    steps_completed,
                    tokens_used,
                    avg_step_duration_ms,
                    outcome,
                    1 if graph_mature else 0,
                    _time.time(),
                ),
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Space registration
    # ------------------------------------------------------------------

    # The rows of `mycelium_spaces` are seeded and read once in __init__
    # (registry.SpaceRegistry.load, Req 12.2): a row that exists is never rewritten.

    def _write_allowed(self, channel: Any, space_id: str, source: str) -> bool:
        """The CellWall write lock of ``space_id`` for ``channel``. A refusal is
        logged and counted (``refused_writes``); it is a normal boundary, not a
        threat signal, so the QuorumSensor is not told (Kyudo Guide, Part 5)."""
        if self._cell_wall.can_write_space(channel, space_id):
            return True
        name = getattr(channel, "name", str(channel))
        key = (space_id, name)
        self.refused_writes[key] = self.refused_writes.get(key, 0) + 1
        logger.info(
            "[interface] write refused by lock: channel=%s space=%s lock=%d source=%s total=%d",
            name, space_id, self._spaces.write_lock(space_id), source,
            self.refused_writes[key],
        )
        return False

    # ------------------------------------------------------------------
    # MCP registry
    # ------------------------------------------------------------------

    def _load_mcp_trust_registry(self) -> None:
        """Load the MCP server trust registry from the database into memory."""
        try:
            cursor = self._conn.execute(
                "SELECT server_id, url, content_hash FROM mycelium_mcp_registry"
            )
            for row in cursor.fetchall():
                self._mcp_trust_registry[row[0]] = {
                    "url": row[1],
                    "content_hash": row[2],
                }
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] failed to load MCP registry: %s", exc)

    def register_mcp(self, server_id: str, url: str, content_hash: str) -> None:
        """
        Register an MCP server in both the DB and the in-memory trust registry (Req 15.29).

        Atomic: both writes succeed or neither is committed.
        """
        now = time.time()
        app_write(
            self._conn,
            """
            INSERT OR REPLACE INTO mycelium_mcp_registry
                (server_id, url, content_hash, registered_at)
            VALUES (?, ?, ?, ?)
            """,
            (server_id, url, content_hash, now),
        )
        self._mcp_trust_registry[server_id] = {"url": url, "content_hash": content_hash}
        # A fresh pin is the owner's decision to trust the current identity.
        self._mcp_untrusted.discard(server_id)

    def check_mcp_identity(
        self, server_id: str, identity_hash: str, session_id: str = "mcp"
    ) -> "HyphaChannel":
        """
        Compare a connected MCP server's runtime identity with its pin (Kyudo Part 1).

          pin matches  -> VERIFIED
          no pin       -> EXTERNAL   (never auto-pinned; see register_mcp)
          pin differs  -> UNTRUSTED  for the rest of the session: WARNING log, one
                          mycelium_conflicts row, and a channel_trust_violation
                          signal. A later match does not restore it (only a new
                          register_mcp does), and the signal fires once per drift.
        Never raises: on error the answer is the conservative UNTRUSTED/EXTERNAL.
        """
        from .kyudo import HyphaChannel  # noqa: PLC0415

        pin = self._mcp_trust_registry.get(server_id)
        if pin is None:
            logger.debug("[interface] mcp=%s has no pin -> EXTERNAL", server_id)
            return HyphaChannel.EXTERNAL
        if server_id in self._mcp_untrusted:
            return HyphaChannel.UNTRUSTED
        if pin["content_hash"] == identity_hash:
            return HyphaChannel.VERIFIED

        self._mcp_untrusted.add(server_id)
        logger.warning(
            "[interface] mcp=%s identity drifted from its pin (pinned=%s seen=%s) "
            "-> UNTRUSTED for this session session=%s",
            server_id, pin["content_hash"], identity_hash, session_id,
        )
        try:
            import uuid  # noqa: PLC0415

            app_write(
                self._conn,
                """INSERT OR IGNORE INTO mycelium_conflicts
                   (conflict_id, space_id, axis, value_a, source_a,
                    value_b, source_b, resolved_value, resolution_basis,
                    created_at)
                   VALUES (?, 'mcp', 'identity', ?, ?, ?, ?, ?, 'mcp_pin_mismatch', ?)""",
                (
                    f"mcp_{uuid.uuid4().hex[:12]}",
                    float(HyphaChannel.VERIFIED), f"pin:{server_id}:{pin['content_hash']}",
                    float(HyphaChannel.UNTRUSTED), f"runtime:{server_id}:{identity_hash}",
                    float(HyphaChannel.UNTRUSTED),
                    time.time(),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("[interface] mcp=%s conflict row failed: %s", server_id, exc)
        self.record_anomaly(session_id, "channel_trust_violation")
        return HyphaChannel.UNTRUSTED

    # ------------------------------------------------------------------
    # Maturity gate
    # ------------------------------------------------------------------

    def is_mature(self) -> bool:
        """
        Return True when the graph has ≥ GRAPH_MATURITY_THRESHOLD (3) distinct spaces
        each containing ≥ 1 node with confidence ≥ 0.6 (Req 12.3).

        Caches the True result indefinitely — once mature, always mature.
        Logs an INFO message on first maturity (Req 12.4).
        """
        if self._is_mature_cached:
            return True

        mature_spaces = 0
        for space_id in self._spaces.ids:
            nodes = self._store.get_nodes_by_space(space_id)
            if any(n.confidence >= 0.6 for n in nodes):
                mature_spaces += 1

        result = mature_spaces >= self._maturity_threshold

        if result:
            self._is_mature_cached = True
            if not self._is_mature_logged:
                mature_space_list = [
                    s
                    for s in self._spaces.ids
                    if any(
                        n.confidence >= 0.6 for n in self._store.get_nodes_by_space(s)
                    )
                ]
                logger.info(
                    "[interface] Graph mature: %d spaces qualified: %s",
                    mature_spaces,
                    mature_space_list,
                )
                self._is_mature_logged = True

        return result

    # ------------------------------------------------------------------
    # Context path generation
    # ------------------------------------------------------------------

    # Bound on the node ids one episode-index row carries (the session's active
    # set only grows during a session).
    _MAX_INDEXED_NODES = 32

    def _active_node_state(self, session_id: str) -> Tuple[List[str], List[str]]:
        """The session's region node ids (the nodes its context paths walked
        and the nodes it wrote) and their spaces, for the episode index.
        Never raises."""
        try:
            # The turn ends the session (clear_session, answer path) BEFORE the
            # turn-end job stores the episode (memory lane), so the live region
            # is already empty here: read the one the session had when cleared.
            # (All 2,857 live index rows carry '[]' for this reason.)
            region = (self._registry.get_region(session_id)
                      or self._registry.get_last_region(session_id))
            ids = sorted(region)[: self._MAX_INDEXED_NODES]
            spaces = sorted({
                n.space_id for n in (self._store.get_node_by_id(i) for i in ids) if n
            })
            return ids, spaces
        except Exception as exc:  # noqa: BLE001 - an empty state still indexes
            logger.debug("[interface] active node state failed: %s", exc)
            return [], []

    def get_context_path(
        self, task_text: str, session_id: str, minimal: bool = False
    ) -> str:
        """
        Return a compact coordinate path string for context injection (Req 12.5).

        Returns "" when the graph is immature — caller falls back to prose header.
        The walk itself is _context_parts (shared with build_context_package).
        """
        parts = self._context_parts(task_text, session_id, minimal)
        if parts is None:
            return ""
        coordinate_path = (
            f"{parts.encoding} | {parts.topology_suffix}"
            if parts.topology_suffix
            else parts.encoding
        )
        if parts.partial_profile:
            return f"{parts.zone_header}\n{coordinate_path}\n{parts.partial_profile}"
        return f"{parts.zone_header}\n{coordinate_path}"

    def build_context_package(
        self,
        task_text: str,
        session_id: str,
        task_class: Optional[str] = None,
        budget_s: float = CONTEXT_PACKAGE_BUDGET_S,
    ) -> Optional[ContextPackage]:
        """
        Assemble the ContextPackage the DER loop reads, from existing producers.

        Returns None when the graph is immature, the walk found no nodes or the
        build failed - the caller falls back to the string path. Never raises.

        Field -> producer (a field with no producer stays ""):
          mycelium_path       zone header + PathEncoder path + partial profile
                              (the same walk get_context_path does)
          topology_path       TopologyLayer.encode_topology_context
          topology_position   TopologyContext.trajectory_label
          tier2_predictions   BehavioralPredictor.predict on the walked region
          tier3_failures      evidence._avoid_list (episodes outcome 'miss')
          task_class          the caller's TaskClassifier label (no 2nd classify)
          tier1_directives, active_contracts, gradient_warnings, causal_context,
          ambient_signals     no producer exists yet -> "" (LiveContextPackage
                              refreshes predictions, warnings and contracts)
        Optional parts are skipped once ``budget_s`` is spent.
        """
        t0 = time.monotonic()
        deadline = t0 + budget_s
        skipped: List[str] = []
        try:
            parts = self._context_parts(
                task_text, session_id, task_class=task_class, deadline=deadline
            )
            if parts is None:
                return None
            if parts.topology_skipped:
                skipped.append("topology")

            tier2 = ""
            if time.monotonic() < deadline:
                try:
                    from .interpreter import BehavioralPredictor  # noqa: PLC0415

                    # A steering read: last settled edges, no wait on the writer.
                    preds = BehavioralPredictor(self).predict(
                        session_id,
                        sorted(self._registry.get_region(session_id)),
                        parts.task_class,
                        [],
                        settle=False,
                    )
                    tier2 = ", ".join(preds)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[interface] package predictions failed: %s", exc)
            else:
                skipped.append("tier2")

            tier3 = ""
            if time.monotonic() < deadline:
                try:
                    from backend.agent.evidence import _avoid_list  # noqa: PLC0415

                    tier3 = "\n".join(_avoid_list(self))
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[interface] package failures failed: %s", exc)
            else:
                skipped.append("tier3")

            path_text = "\n".join(
                p for p in (parts.zone_header, parts.encoding, parts.partial_profile) if p
            )
            pkg = ContextPackage(
                mycelium_path=path_text,
                topology_path=parts.topology_suffix,
                manifest={},
                tier1_directives="",
                tier2_predictions=tier2,
                tier3_failures=tier3,
                active_contracts="",
                gradient_warnings="",
                causal_context="",
                ambient_signals="",
                topology_position=parts.trajectory_label,
                task_class=parts.task_class,
            )
            logger.info(
                "[interface] context_package session=%s build_ms=%.1f zone_chars=%d "
                "skipped=%s",
                session_id[:8], (time.monotonic() - t0) * 1000.0,
                len(pkg.get_system_zone_content()), ",".join(skipped) or "-",
            )
            return pkg
        except Exception as exc:  # noqa: BLE001 - the string path answers instead
            logger.warning(
                "[interface] context_package build failed session=%s: %s",
                session_id[:8], exc,
            )
            return None

    def _context_parts(
        self,
        task_text: str,
        session_id: str,
        minimal: bool = False,
        task_class: Optional[str] = None,
        deadline: Optional[float] = None,
    ) -> Optional[_ContextParts]:
        """
        Walk the graph for a task and return the pieces of its context path, or
        None when the graph is immature or the walk found no nodes.

        Pipeline:
          1. Maturity gate.
          2. Space subset: the caller's ``task_class`` (no second classify), else
             TaskClassifier.classify() (lazy import from kyudo).
          3. PredictiveLoader.get_cached() - a cached path replaces the walk.
          4. Navigate from task text.
          5. Encode with PathEncoder.
          6. Topology context if TopologyLayer is available - skipped when
             ``deadline`` (a time.monotonic() value) has passed.
        """
        if not self.is_mature():
            return None

        # Step 2 — space subset for the task class
        space_subset: Optional[List[str]] = None
        try:
            if task_class:
                space_subset = self._spaces.spaces_for_class(task_class)
            else:
                task_class, space_subset = self._task_classifier.classify(task_text)
            self._last_task_class = task_class
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] TaskClassifier failed: %s", exc)
        self._last_task[session_id] = (task_text, task_class or "full")
        self._last_task.move_to_end(session_id)
        while len(self._last_task) > 64:
            self._last_task.popitem(last=False)

        # Step 3 — check predictive cache (the hit is a MemoryPath, not a string)
        path: Optional[MemoryPath] = None
        try:
            cached = self._predictive_loader.get_cached(session_id, task_text)
            if cached is not None and getattr(cached, "nodes", None):
                path = cached
                # what navigate_from_task would have done for these nodes
                ids = [n.node_id for n in path.nodes]
                self._registry.register(session_id, ids)
                for node_id in ids:
                    self._store.record_access(node_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] PredictiveLoader failed: %s", exc)

        # Step 4 — navigate
        if path is None:
            path = self._navigator.navigate_from_task(
                task_text=task_text,
                session_id=session_id,
                spaces=space_subset,
            )

        if not path.nodes:
            return None

        # Step 5 — encode
        if minimal:
            encoding = PathEncoder.encode_minimal(path.nodes)
        else:
            encoding = PathEncoder.encode(path.nodes)

        # Update token_encoding on the path object for later recording
        path = MemoryPath(
            nodes=path.nodes,
            cumulative_score=path.cumulative_score,
            token_encoding=encoding,
            spaces_covered=path.spaces_covered,
            traversal_id=path.traversal_id,
        )

        # Step 5b — partial profile: only the spaces in space_subset, render_order sequence
        partial_profile = ""
        try:
            render_order = self._spaces.render_order

            target_spaces = space_subset if space_subset else list(render_order)
            ordered_spaces = sorted(
                (s for s in target_spaces if s in render_order),
                key=lambda s: render_order[s],
            )
            sections = []
            for space_id in ordered_spaces:
                section = self._renderer.get_profile_section(space_id)
                if section:
                    sections.append(section)
            if sections:
                partial_profile = "\n".join(sections)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] partial profile assembly failed: %s", exc)

        # Track total context tokens (rough estimate: chars / 4)
        self._total_context_chars += len(encoding) + len(partial_profile)
        self._context_task_count += 1
        if self._context_task_count % 50 == 0:
            avg_tokens = (self._total_context_chars / self._context_task_count) / 4
            logger.info(
                "[interface] avg_context_tokens_per_task=%.1f over %d tasks",
                avg_tokens,
                self._context_task_count,
            )

        # Step 6 — topology context (optional: skipped past the deadline)
        topology_suffix = ""
        trajectory_label = ""
        topology_skipped = deadline is not None and time.monotonic() >= deadline
        if not topology_skipped:
            try:
                active_nodes = []
                for space_id in space_subset or []:
                    active_nodes.extend(self._store.get_nodes_by_space(space_id))
                topo_ctx = self._topology_layer.get_topology_context(
                    session_id, active_nodes
                )
                topology_suffix = self._topology_layer.encode_topology_context(topo_ctx)
                trajectory_label = (topo_ctx.trajectory_label or "") if topo_ctx else ""
            except Exception as exc:  # noqa: BLE001
                logger.debug("[interface] TopologyLayer failed: %s", exc)

        return _ContextParts(
            task_class=task_class or "full",
            zone_header=self._cell_wall.render_zone_headers(),
            encoding=encoding,
            partial_profile=partial_profile,
            topology_suffix=topology_suffix,
            trajectory_label=trajectory_label,
            topology_skipped=topology_skipped,
        )

    # ------------------------------------------------------------------
    # Ingestion methods
    # ------------------------------------------------------------------

    def ingest_hardware(self) -> None:
        """Probe hardware capabilities and upsert a capability node (Req 12.6)."""
        result = self._extractor.extract_hardware()
        if result:
            space_id, coords, confidence, label = result
            self._store.upsert_node(space_id, coords, label, confidence)
            self._is_mature_cached = None  # Invalidate cache — new node added

    def ingest_statement(self, text: str) -> None:
        """Extract coordinates from a user statement and upsert resulting nodes."""
        results = self._extractor.extract_from_statement(text)
        for space_id, coords, confidence, label in results:
            self._store.upsert_node(space_id, coords, label, confidence, accumulate=True, channel=_USER_CHANNEL)
        if results:
            self._is_mature_cached = None

    def ingest_statements(self, texts: List[str]) -> None:
        """Batch-ingest multiple statements, invalidating maturity cache once.

        Functionally equivalent to calling ingest_statement() for each text, but
        defers the maturity-cache invalidation until the end of the batch so it
        only happens once rather than N times.
        """
        any_results = False
        for text in texts:
            if not text:
                continue
            results = self._extractor.extract_from_statement(text)
            for space_id, coords, confidence, label in results:
                self._store.upsert_node(space_id, coords, label, confidence, accumulate=True, channel=_USER_CHANNEL)
            if results:
                any_results = True
        if any_results:
            self._is_mature_cached = None

    def ingest_sessions(self, session_timestamps: List[float]) -> None:
        """Derive a chrono node from session timestamp history."""
        result = self._extractor.extract_from_sessions(session_timestamps)
        if result:
            space_id, coords, confidence, label = result
            self._store.upsert_node(space_id, coords, label, confidence, accumulate=True, channel=_USER_CHANNEL)
            self._is_mature_cached = None

    def ingest_conduct_outcomes(self, episodes: List[Any]) -> None:
        """
        Derive behavioural conduct coordinates from completed episodes.

        Episodes are expected to have 'outcome' and optionally 'task_text' fields.
        This is a best-effort pass; failures are silently swallowed.
        """
        try:
            for episode in episodes:
                text = getattr(episode, "task_text", None) or episode.get(
                    "task_text", ""
                )
                outcome = getattr(episode, "outcome", None) or episode.get(
                    "outcome", ""
                )
                if text and outcome in ("hit", "success"):
                    results = self._extractor.extract_from_statement(text)
                    for space_id, coords, confidence, label in results:
                        self._store.upsert_node(space_id, coords, label, confidence)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] ingest_conduct_outcomes failed: %s", exc)

    def ingest_tool_call(
        self,
        tool_name: str,
        success: bool,
        sequence_position: int,
        total_steps: int,
        session_id: str,
    ) -> None:
        """Record a tool call observation; upsert toolpath node once window ≥ 3.
        The node the session wrote becomes part of its region (edge scoring and
        the episode index read it)."""
        node = self._extractor.ingest_tool_call(
            tool_name=tool_name,
            success=success,
            sequence_position=sequence_position,
            total_steps=total_steps,
            session_id=session_id,
        )
        if node is not None:
            self._registry.touch(session_id, node.node_id)
            self._note_upserts(session_id)

    def ingest_context(self, text: str, session_data: dict) -> None:
        """Extract a context-space node from project/stack signals in text + session data."""
        result = self._extractor._extract_context_signals(text, session_data)
        if result:
            space_id, coords, confidence, label = result
            self._store.upsert_node(space_id, coords, label, confidence, accumulate=True, channel=_USER_CHANNEL)
            self._is_mature_cached = None

    # ------------------------------------------------------------------
    # Outcome recording and crystallisation
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        path: MemoryPath,
        outcome: str,
        session_id: str,
        task_summary: str,
    ) -> None:
        """Delegate to CoordinateNavigator.record_path_outcome()."""
        self._navigator.record_path_outcome(
            path=path,
            outcome=outcome,
            session_id=session_id,
            task_summary=task_summary,
        )

    def ingest_rag_content(
        self,
        content: str,
        source_type: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Ingest external content through the RAG security bridge (Req 15.6).

        Assigns a trust channel, extracts coordinates respecting channel limits,
        and records source_channel in the episode index.  All wrapped in
        try/except so RAG ingestion never breaks the caller.
        """
        try:
            from .kyudo import ChannelViolation  # noqa: PLC0415

            ingested = self._rag_bridge.ingest(
                content, source_type, session_id, metadata
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] ingest_rag_content bridge failed: %s", exc)
            return

        try:
            # Extract coordinates — conduct space will be skipped for low-trust channels
            results = self._extractor.extract_from_statement(content)
            for space_id, coords, confidence, label in results:
                # Skip writes the space's lock refuses (conduct from a weak channel, ...)
                if not self._write_allowed(ingested.channel, space_id, "rag"):
                    continue
                self._store.upsert_node(
                    space_id, coords, label, confidence, channel=int(ingested.channel)
                )
                self._note_upserts(session_id)
            if results:
                self._is_mature_cached = None
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] ingest_rag_content extraction failed: %s", exc)

        # Record source_channel in the episode index for this ingestion
        try:
            self._ep_indexer.index_episode(
                episode_id=f"rag_{session_id}_{int(time.time())}",
                session_id=session_id,
                source_channel=ingested.channel.value,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] ingest_rag_content index failed: %s", exc)

    def ingest_document_data(
        self,
        content: str,
        trust: str,
        session_id: str,
        coords: Any = None,
        label: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        W8 (O2): Seed agent document data into the Mycelium coordinate graph as a
        trust-routed context node with proper coordinates, so that trusted,
        frequently-referenced data can crystallize into a permanent landmark at
        PERMANENCE_THRESHOLD (landmark.py:414).

        Trust routing (CellWall-enforced, never bypassed):
          * trust == "trusted"   -> HyphaChannel.VERIFIED -> the context space
                                     (write lock VERIFIED)
          * trust == "untrusted" -> HyphaChannel.EXTERNAL -> the toolpath space
                                     (REFERENCE_ZONE before the write locks).
                                     toolpath is SYSTEM-locked (a behavioural
                                     space), so this node write is REFUSED: it
                                     is logged and counted (``refused_writes``)
                                     and no node is written. The episode index
                                     row (with its channel) is still written.

        The LandmarkCondenser trust-cap (landmark.py:40, kyudo.py:63, 0.30)
        excludes untrusted sessions from crystallization when ``source_channel``
        is supplied at crystallize time — we record the channel here so a future
        crystallize call can honor it. All failures are swallowed: document
        seeding must never block the render.
        """
        try:
            from .kyudo import HyphaChannel  # noqa: PLC0415

            channel = (
                HyphaChannel.VERIFIED if trust == "trusted" else HyphaChannel.EXTERNAL
            )
            space_id = "context" if channel == HyphaChannel.VERIFIED else "toolpath"

            # CellWall guard — never bypass the trust boundary. A refused node
            # write (EXTERNAL into toolpath) still leaves its episode index row.
            if not self._write_allowed(channel, space_id, "document_data"):
                self._index_document_episode(session_id, channel)
                return

            # Normalize coordinates (accept "x,y,xi,u" string or list of floats).
            norm_coords: Optional[List[float]] = None
            if coords:
                if isinstance(coords, str):
                    try:
                        norm_coords = [float(v) for v in coords.split(",") if v.strip()]
                    except (ValueError, TypeError):
                        norm_coords = None
                else:
                    try:
                        norm_coords = [float(v) for v in coords]
                    except (ValueError, TypeError):
                        norm_coords = None

            # Fall back to content-derived coordinates when none supplied.
            if not norm_coords:
                try:
                    extracted = self._extractor.extract_from_statement(content)
                    if extracted:
                        _sp, norm_coords, _conf, _label = extracted[0]
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "[interface] ingest_document_data coord extract failed: %s", exc
                    )

            if not norm_coords:
                return

            # NOTE: ``coords`` here is the agent's reasoning state ("x,y,xi,u" from the
            # caller), not a coordinate in this space's own axes (context: project_id,
            # stack_id, constraint_flags, freshness). Reported, not redesigned.
            self._store.upsert_node(
                space_id, norm_coords, label or "document_data", 0.8, channel=int(channel)
            )
            self._note_upserts(session_id)

            self._index_document_episode(session_id, channel)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] ingest_document_data failed: %s", exc)

    def _index_document_episode(self, session_id: str, channel: Any) -> None:
        """Record source_channel so crystallization can honor the trust-cap."""
        try:
            self._ep_indexer.index_episode(
                episode_id=f"doc_{session_id}_{int(time.time() * 1000)}",
                session_id=session_id,
                source_channel=channel.value,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] ingest_document_data index failed: %s", exc)

    def _check_quorum_and_reorganize(self, session_id: str) -> None:
        """
        Check QuorumSensor threshold and fire QuorumReorganization if breached.

        Called after recording anomaly signals.  All exceptions swallowed.
        """
        try:
            if self._quorum_sensor.check_threshold():
                from .kyudo import QuorumReorganization  # noqa: PLC0415

                QuorumReorganization().fire(self, session_id)
                # fire() reset the level to 0: log it, or a restart would
                # restore the pre-reorganization level from the last signal row.
                self._log_quorum(session_id, "quorum_reorganization_reset", 0.0)
        except Exception as exc:  # noqa: BLE001
            logger.error("[interface] quorum reorganization failed: %s", exc)

    # ═══════════════════════════════════════════════════════════════════════
    # v2: Caducean Mitochondria-to-Mycelium public accessors
    # ═══════════════════════════════════════════════════════════════════════

    def record_anomaly(self, session_id: str, signal_type: str) -> bool:
        """Record a Caducean anomaly to the QuorumSensor.

        v2 entry point — called from agent_kernel when caducean_recommend()
        returns 3 (TOPO_VIOLATION). Delegates to _quorum_sensor.record_signal()
        which writes to the existing quorum_log table. Runs the reorganization
        check afterwards (mirrors the v1 pattern in ingest_conduct_outcomes).

        Returns True on success. All exceptions swallowed — never blocks the
        agent loop. The physics violation has already been raised by the kernel.
        """
        try:
            self._quorum_sensor.record_signal(signal_type=signal_type)
            self._log_quorum(
                session_id, signal_type,
                self._quorum_sensor._SIGNAL_WEIGHTS.get(signal_type, 0.0),
            )
            self._signalled_sessions[session_id] = None
            while len(self._signalled_sessions) > 256:
                self._signalled_sessions.popitem(last=False)
            self._check_quorum_and_reorganize(session_id)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("[interface] record_anomaly failed: %s", exc)
            return False

    def get_latest_u(self, session_id: str) -> Optional[Dict[str, float]]:
        """Read the latest Caducean (x, y, xi, u, recommendation) for a session.

        Returns None if no trajectory rows exist. Used by scorer.py and
        resonance.py to modulate decay/retrieval multipliers based on the
        current attentional velocity. Read once at the start of each pass
        (not per-edge) — no hot-path DB calls.
        """
        try:
            row = self._conn.execute(
                "SELECT x, y, xi, u, recommendation FROM caducean_trajectories "
                "WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "x": float(row[0]),
                "y": float(row[1]),
                "xi": float(row[2]),
                "u": float(row[3]),
                "recommendation": int(row[4]) if row[4] is not None else 2,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("[interface] get_latest_u failed: %s", exc)
            return None

    def crystallize_landmark(
        self,
        session_id: str,
        cumulative_score: float,
        outcome: str,
        task_entry_label: Optional[str] = None,
        source_channel: Optional[str] = None,
        evidence_kinds: Optional[List[str]] = None,
    ) -> Optional[Landmark]:
        """
        ``evidence_kinds``: OUTSIDE evidence this session produced (task_complete,
        test_pass, user_confirm). A crystallized landmark starts as a CANDIDATE and
        is promoted only by evidence (landmark policy, spec D9); a merge with
        another session's landmark adds ``recurrence``.

        Crystallise a Landmark from the current session in causal order (Req 12.7):
          1. condense()
          2. index.save()
          3. merger.try_merge()
          4. indexer.backfill_landmark()

        Returns the surviving Landmark, or None if crystallisation was suppressed.
        """
        # Respect quorum reorganization suspension
        if self._crystallisation_suspended:
            logger.debug(
                "[interface] crystallise skipped — suspended by QuorumReorganization"
            )
            return None

        # The cluster is drawn from the nodes THIS session walked or wrote (the turn
        # ended the session already, so read the region it had when cleared). Without
        # it every landmark took the graph's top nodes by access_count - the same few.
        try:
            region = (self._registry.get_region(session_id)
                      or self._registry.get_last_region(session_id))
        except Exception as exc:  # noqa: BLE001 - no region = the condenser's old default
            logger.warning("[interface] crystallize region unavailable session=%s: %s",
                           session_id, exc)
            region = None
        if not region:
            # A session that walked and wrote no node has no coordinates to anchor
            # a claim. The condenser's fallback (the graph's global top nodes) is the
            # cluster bug: every such landmark looked alike, and the merge rule
            # would then absorb all the legacy look-alikes at once.
            from backend.agent import write_counters  # noqa: PLC0415

            write_counters.bump("landmark.crystallize.skipped_no_region")
            logger.debug("[interface] crystallise skipped — no region session=%s", session_id)
            return None
        landmark = self._condenser.condense(
            session_id=session_id,
            cumulative_score=cumulative_score,
            outcome=outcome,
            task_entry_label=task_entry_label,
            source_channel=source_channel,
            region=region,
        )
        if landmark is None:
            return None

        self._lm_index.save(landmark)
        merged = self._merger.try_merge(landmark)
        surviving = merged or landmark

        self._apply_landmark_policy(session_id, landmark, surviving, evidence_kinds,
                                    absorbed_ids=list(self._merger.last_absorbed))

        self._ep_indexer.backfill_landmark(session_id, surviving.landmark_id)

        # Record session position in topology chart (Task 11.3)
        try:
            active_nodes: List[Any] = []
            for space_id in self._spaces.ids:
                active_nodes.extend(self._store.get_nodes_by_space(space_id))
            self._topology_layer.record_session_position(session_id, active_nodes)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] topology record_session_position failed: %s", exc)

        return surviving

    def _apply_landmark_policy(self, session_id, new_lm, surviving, evidence_kinds,
                               absorbed_ids=None) -> None:
        """Spec D9: event-level route + dependencies, evidence, recurrence. Never raises."""
        try:
            from backend.memory.memory_events import session_evidence
            from backend.memory.mycelium.landmark import (
                add_landmark_evidence,
                set_landmark_falsification,
            )

            conn = self._conn
            # One writer: the landmark and merge rows just saved are read below.
            app_flush()
            ev = session_evidence(conn, session_id)
            set_landmark_falsification(conn, surviving.landmark_id, ev["depends_on"],
                                       ev["verified_steps"])
            recurrence = False
            if surviving is not new_lm:
                # A merge happened: the absorbed landmarks' evidence moves to the
                # survivor, and a merge across sessions is independent recurrence.
                # One crystallization can absorb a whole group (the merger's list).
                if not absorbed_ids:
                    absorbed_ids = [
                        new_lm.landmark_id if surviving.landmark_id != new_lm.landmark_id
                        else (conn.execute(
                            "SELECT absorbed_id FROM mycelium_landmark_merges WHERE survivor_id = ? "
                            "ORDER BY created_at DESC LIMIT 1", (surviving.landmark_id,),
                        ).fetchone() or (None,))[0]
                    ]
                for absorbed_id in absorbed_ids:
                    row = conn.execute(
                        "SELECT evidence, conversation_ref FROM mycelium_landmarks WHERE landmark_id = ?",
                        (absorbed_id,),
                    ).fetchone() if absorbed_id else None
                    if row is None:
                        continue
                    for e in json.loads(row[0] or "[]"):
                        add_landmark_evidence(conn, surviving.landmark_id, e.get("kind", ""),
                                              e.get("ref", ""), e.get("session", ""))
                    refs = {row[1], surviving.conversation_ref}
                    if len({r for r in refs if r}) > 1:
                        recurrence = True
                        add_landmark_evidence(conn, surviving.landmark_id, "recurrence",
                                              f"merged {absorbed_id}", session_id)
            for kind in dict.fromkeys(list(evidence_kinds or []) + ev["kinds"]):
                add_landmark_evidence(conn, surviving.landmark_id, kind, "episode", session_id)
            logger.debug("[interface] landmark policy applied lm=%s recurrence=%s",
                         surviving.landmark_id, recurrence)
        except Exception as exc:  # noqa: BLE001 — policy never blocks crystallization
            logger.warning("[interface] landmark policy failed lm=%s: %s",
                           getattr(surviving, "landmark_id", "?"), exc)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def clear_session(self, session_id: str) -> None:
        """
        End a session in this exact order (Req 12.8):
          1. Clear navigator session state.
          2. Clear extractor observation windows.
          3. Pre-warm predictive loader (only when mature — never during active session).
          4. Flag maintenance if overdue.
          5. Kyudo: a clean session fades the threat level by
             QUORUM_SIGNAL_DECAY (it never faded: isolated anomalies piled up
             for the life of the process); a reorganization's crystallisation
             suspension ends with the session (Kyudo Layer Guide, Part 4).
        """
        self._navigator.clear_session(session_id)
        self._extractor.clear_session(session_id)

        self._session_upserts.pop(session_id, None)
        if self._signalled_sessions.pop(session_id, False) is False:
            _before = self._quorum_sensor.threat_level
            self._quorum_sensor.decay_clean_session()
            if self._quorum_sensor.threat_level != _before:  # a fade at 0 is no event
                self._log_quorum(
                    session_id, "clean_session_fade",
                    self._quorum_sensor.threat_level - _before,
                )
        self._crystallisation_suspended = False

        # Step 3: predictive pre-warm at session boundary (mature only; it
        # serves the context package, so it follows the package switch)
        last_text, last_class = self._last_task.pop(session_id, ("", "full"))
        if context_package_enabled() and self.is_mature():
            try:
                self._predictive_loader.pre_warm(
                    session_id, self._navigator, last_class, last_text
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("[interface] pre_warm failed: %s", exc)

        # Step 4: flag maintenance if overdue
        if self._last_distillation_at is not None:
            elapsed = time.time() - self._last_distillation_at
            if elapsed > DISTILLATION_MAX_INTERVAL:
                self._maintenance_needed = True

    def observe_landmark_use(self, session_id: str, outcome: str) -> List[str]:
        """
        Turn end, before the session's new landmark exists: the landmarks the
        session's region overlaps were used - activate them and let the
        outcome grow the edges among them. The turn ended the session already
        (clear_session), so the region is the one it had when cleared.
        Never raises; returns the activated landmark ids.
        """
        try:
            region = (self._registry.get_region(session_id)
                      or self._registry.get_last_region(session_id))
            return self._lm_index.observe_region(region, outcome)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[interface] observe_landmark_use failed session=%s: %s",
                           session_id, exc)
            return []

    def nullify_conversation(self, session_id: str) -> None:
        """Clear conversation_ref for all landmarks referencing this session."""
        self._lm_index.nullify_conversation(session_id)

    # ------------------------------------------------------------------
    # Profile access
    # ------------------------------------------------------------------

    def get_readable_profile(self) -> str:
        """Return the assembled human-readable profile for all rendered spaces."""
        return self._renderer.get_readable_profile()

    def get_profile_section(self, space_id: str) -> Optional[str]:
        """Return the prose for a single space, or None if not yet rendered."""
        return self._renderer.get_profile_section(space_id)

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def run_maintenance(self, session_id: Optional[str] = None) -> None:
        """
        Full five-step maintenance sequence (Req 12.9):
          1. Edge decay (EdgeScorer.apply_decay) — v2: Caducean-modulated if session_id given
          2. Condense nodes (MapManager.run_condense)
          3. Expand nodes (MapManager.run_expand)
          4. Landmark edge decay (LandmarkIndex.apply_landmark_decay)
          4b. Kyudo integrity pass (integrity.run_integrity_pass)
          5. Profile render (ProfileRenderer.render_dirty_sections)
          6. Topology maintenance

        Sync — callers that need non-blocking execution should use
        asyncio.to_thread(mycelium.run_maintenance).
        Sets _last_distillation_at to now.

        v2: session_id is optional. If provided, edge decay is modulated by
        the Caducean attentional velocity (u). If None, decay uses default
        rate (backward compatible with v1 callers).
        """
        logger.info("[interface] Running Mycelium maintenance pass")
        try:
            pruned = self._scorer.apply_decay(session_id=session_id)
            logger.debug("[interface] maintenance: pruned %d edges", pruned)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[interface] maintenance: apply_decay failed: %s", exc)

        try:
            lowered = self._scorer.apply_node_decay(session_id=session_id)
            logger.debug("[interface] maintenance: node confidence decayed on %d", lowered)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[interface] maintenance: apply_node_decay failed: %s", exc)

        try:
            merged = self._map_manager.run_condense()
            logger.debug("[interface] maintenance: condensed %d nodes", merged)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[interface] maintenance: run_condense failed: %s", exc)

        try:
            split = self._map_manager.run_expand()
            logger.debug("[interface] maintenance: expanded %d nodes", split)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[interface] maintenance: run_expand failed: %s", exc)

        try:
            lm_pruned = self._lm_index.apply_landmark_decay()
            logger.debug(
                "[interface] maintenance: landmark edges pruned: %d", lm_pruned
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[interface] maintenance: apply_landmark_decay failed: %s", exc
            )

        # Step 4b - Kyudo integrity pass: the memory cleans itself (integrity.py).
        # Before the render, which reads the nodes it may remove. While a quorum
        # reorganization holds the graph (crystallisation suspended) this slow pass
        # steps aside: the emergency owns the cleaning until the session ends.
        try:
            from backend.agent import write_counters  # noqa: PLC0415

            if self._crystallisation_suspended:
                write_counters.bump("kyudo.integrity.skipped_quorum")
                logger.info("[interface] maintenance: integrity pass skipped - quorum reorganization active")
            else:
                from .integrity import run_integrity_pass  # noqa: PLC0415

                report = run_integrity_pass(self._conn, self._store, self._merger)
                if report["nodes_removed"]:
                    self._is_mature_cached = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[interface] maintenance: integrity pass failed: %s", exc)

        try:
            rendered = self._renderer.render_dirty_sections()
            logger.debug(
                "[interface] maintenance: rendered %d profile sections", rendered
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[interface] maintenance: render_dirty_sections failed: %s", exc
            )

        # Step 6 — Topology maintenance (v2.0, MUST run after v1.5 sequence)
        try:
            self._topology_layer.run_topology_maintenance()
            logger.debug("[interface] maintenance: topology pass complete")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[interface] maintenance: topology pass failed: %s", exc)

        # (collapse_duplicates runs inside the integrity pass above, AFTER the hub
        # landmarks are dissolved: the 88 live look-alikes of 2026-10-19 shared one
        # cluster only because of the global-top-6 bug, their claims differ - owner
        # decision 2026-10-19, MEMORY-FOUNDATION-ANALYSIS §16.)

        # Step 7 - sectors, SHADOW: computed and logged (SECTOR_* events), read by nothing.
        try:
            from .sectors import run_sector_lifecycle

            run_sector_lifecycle(
                self._conn, can_write=lambda ch: self._spaces.can_write(ch, "domain"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[interface] maintenance: sector lifecycle failed: %s", exc)

        self._last_distillation_at = time.time()
        self._maintenance_needed = False

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """
        Return a snapshot of Mycelium operational statistics (Req 12.10).

        Fields with graceful defaults for kyudo/topology components that
        may not yet be wired.
        """
        try:
            node_cursor = self._conn.execute("SELECT COUNT(*) FROM mycelium_nodes")
            node_count = node_cursor.fetchone()[0]
        except Exception:  # noqa: BLE001
            node_count = 0

        try:
            lm_cursor = self._conn.execute(
                "SELECT COUNT(*) FROM mycelium_landmarks WHERE absorbed IS NULL"
            )
            landmark_count = lm_cursor.fetchone()[0]
        except Exception:  # noqa: BLE001
            landmark_count = 0

        # Kyudo stats
        threat_level: float = 0.0
        prediction_cache_hit_rate: float = 0.0
        whiteboard_broadcast_tokens: int = 0
        failure_warning_tokens: int = 0

        try:
            threat_level = self._quorum_sensor.threat_level
        except Exception:  # noqa: BLE001
            pass

        try:
            prediction_cache_hit_rate = self._predictive_loader.hit_rate
        except Exception:  # noqa: BLE001
            pass

        # Average spaces per traversal from recent traversal log
        avg_spaces_navigated = 0.0
        try:
            cursor = self._conn.execute(
                """
                SELECT AVG(length(path_node_ids) - length(replace(path_node_ids, ',', '')) + 1)
                FROM mycelium_traversals
                ORDER BY created_at DESC LIMIT 50
                """
            )
            row = cursor.fetchone()
            if row and row[0]:
                avg_spaces_navigated = float(row[0])
        except Exception:  # noqa: BLE001
            pass

        return {
            "is_mature": self.is_mature(),
            "node_count": node_count,
            "landmark_count": landmark_count,
            "threat_level": threat_level,
            "prediction_cache_hit_rate": prediction_cache_hit_rate,
            "avg_spaces_navigated": avg_spaces_navigated,
            "whiteboard_broadcast_tokens": whiteboard_broadcast_tokens,
            "failure_warning_tokens": failure_warning_tokens,
            "avg_context_tokens_per_task": (
                (self._total_context_chars / self._context_task_count / 4)
                if self._context_task_count > 0
                else 0.0
            ),
            "last_task_class": self._last_task_class,
        }

    # ------------------------------------------------------------------
    # Dev tools
    # ------------------------------------------------------------------

    def dev_dump(self) -> dict:
        """
        Return a full graph dump for development and testing (Req 12.11).

        Raises PermissionError when dev_mode=False (the production default).
        """
        if not self._dev_mode:
            raise PermissionError(
                "dev_dump() is disabled in production. "
                "Instantiate MyceliumInterface with dev_mode=True to enable."
            )

        nodes_by_space: Dict[str, list] = {}
        for space_id in self._spaces.ids:
            nodes = self._store.get_nodes_by_space(space_id)
            nodes_by_space[space_id] = [
                {
                    "node_id": n.node_id,
                    "coordinates": n.coordinates,
                    "label": n.label,
                    "confidence": n.confidence,
                    "access_count": n.access_count,
                }
                for n in nodes
            ]

        landmarks = [
            {
                "landmark_id": lm.landmark_id,
                "task_class": lm.task_class,
                "cumulative_score": lm.cumulative_score,
                "activation_count": lm.activation_count,
                "is_permanent": lm.is_permanent,
            }
            for lm in self._lm_index.get_all_active()
        ]

        return {
            "is_mature": self.is_mature(),
            "nodes_by_space": nodes_by_space,
            "landmarks": landmarks,
            "mcp_trust_registry": self._mcp_trust_registry,
            "stats": self.get_stats(),
        }

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
import time
from typing import Any, Dict, List, Optional

from .encoder import PathEncoder
from .extractor import CoordinateExtractor
from .landmark import Landmark, LandmarkCondenser, LandmarkIndex
from .navigator import CoordinateNavigator, SessionRegistry
from .profile import LandmarkMerger, ProfileRenderer
from .resonance import EpisodeIndexer, ResonanceScorer
from .scorer import EdgeScorer, MapManager
from .store import CoordinateStore, MemoryPath
from .spaces import RENDER_ORDER, SPACES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants (Req 12.1)
# ---------------------------------------------------------------------------

GRAPH_MATURITY_THRESHOLD: int = 3       # distinct spaces with ≥ 1 confident node
DISTILLATION_IDLE_THRESHOLD: int = 600   # seconds idle before maintenance is allowed
DISTILLATION_MAX_INTERVAL: int = 14400   # seconds max between forced maintenance passes


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

        # Core components
        self._store = CoordinateStore(conn)
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
        self._ep_indexer = EpisodeIndexer(conn)
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
        self._crystallisation_suspended: bool = False  # set True during QuorumReorganization

        # Topology layer (Task 11.3) — eagerly instantiated
        from .topology import TopologyLayer  # noqa: PLC0415
        self._topology_layer: TopologyLayer = TopologyLayer(conn, self._store)

        # Context token tracking (Task 10.2)
        self._total_context_chars: int = 0
        self._context_task_count: int = 0

        # Kyudo security layer (Task 9.2) — eagerly instantiated
        from .kyudo import (  # noqa: PLC0415
            QuorumSensor, RagIngestionBridge, CellWall,
            TaskClassifier, PredictiveLoader,
            CHANNEL_WEIGHTS,
        )
        self._quorum_sensor:     QuorumSensor     = QuorumSensor()
        self._rag_bridge:        RagIngestionBridge = RagIngestionBridge()
        self._cell_wall:         CellWall         = CellWall()
        self._task_classifier:   TaskClassifier   = TaskClassifier()
        self._predictive_loader: PredictiveLoader = PredictiveLoader()
        self._channel_weights = CHANNEL_WEIGHTS

        # MCP trust registry
        self._mcp_trust_registry: Dict[str, dict] = {}
        self._load_mcp_trust_registry()

        # Register all 7 spaces in the DB
        self._ensure_spaces_registered()

    # ------------------------------------------------------------------
    # Space registration
    # ------------------------------------------------------------------

    def _ensure_spaces_registered(self) -> None:
        """
        Upsert all 7 coordinate spaces into `mycelium_spaces` (Req 12.2).

        Sets render_order from RENDER_ORDER constants.
        toolpath has no render_order entry — it never produces a profile section.
        """
        for space_id, space in SPACES.items():
            render_order = RENDER_ORDER.get(space_id, 0)
            axes_json = json.dumps(space.axes)
            value_range_json = json.dumps(list(space.value_range))
            self._conn.execute(
                """
                INSERT OR REPLACE INTO mycelium_spaces
                    (space_id, axes, dtype, value_range, description, active)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (space_id, axes_json, space.dtype, value_range_json, space.description),
            )
        self._conn.commit()

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
        self._conn.execute(
            """
            INSERT OR REPLACE INTO mycelium_mcp_registry
                (server_id, url, content_hash, registered_at)
            VALUES (?, ?, ?, ?)
            """,
            (server_id, url, content_hash, now),
        )
        self._conn.commit()
        self._mcp_trust_registry[server_id] = {"url": url, "content_hash": content_hash}

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
        for space_id in SPACES:
            nodes = self._store.get_nodes_by_space(space_id)
            if any(n.confidence >= 0.6 for n in nodes):
                mature_spaces += 1

        result = mature_spaces >= self._maturity_threshold

        if result:
            self._is_mature_cached = True
            if not self._is_mature_logged:
                mature_space_list = [
                    s for s in SPACES
                    if any(n.confidence >= 0.6 for n in self._store.get_nodes_by_space(s))
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

    def get_context_path(
        self, task_text: str, session_id: str, minimal: bool = False
    ) -> str:
        """
        Return a compact coordinate path string for context injection (Req 12.5).

        Returns "" when the graph is immature — caller falls back to prose header.

        Pipeline:
          1. Maturity gate.
          2. TaskClassifier.classify() to get space_subset (lazy import from kyudo).
          3. PredictiveLoader.get_cached() — return cached path if hit (lazy import).
          4. Navigate from task text.
          5. Encode with PathEncoder.
          6. Append topology context if TopologyLayer is available (lazy import).
        """
        if not self.is_mature():
            return ""

        # Step 2 — classify task to get space subset
        space_subset: Optional[List[str]] = None
        try:
            task_class, space_subset = self._task_classifier.classify(task_text)
            self._last_task_class = task_class
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] TaskClassifier failed: %s", exc)

        # Step 3 — check predictive cache
        try:
            cached = self._predictive_loader.get_cached(session_id, task_text)
            if cached:
                return cached
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] PredictiveLoader failed: %s", exc)

        # Step 4 — navigate
        path: MemoryPath = self._navigator.navigate_from_task(
            task_text=task_text,
            session_id=session_id,
            spaces=space_subset,
        )

        if not path.nodes:
            return ""

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
            from .spaces import RENDER_ORDER  # noqa: PLC0415
            target_spaces = space_subset if space_subset else list(RENDER_ORDER.keys())
            ordered_spaces = sorted(
                (s for s in target_spaces if s in RENDER_ORDER),
                key=lambda s: RENDER_ORDER[s],
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
                avg_tokens, self._context_task_count,
            )

        # Step 6 — append topology context
        topology_suffix = ""
        try:
            active_nodes = []
            for space_id in (space_subset or []):
                active_nodes.extend(self._store.get_nodes_by_space(space_id))
            topo_ctx = self._topology_layer.get_topology_context(session_id, active_nodes)
            topology_suffix = self._topology_layer.encode_topology_context(topo_ctx)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] TopologyLayer failed: %s", exc)

        # Assemble final context: zone header + coordinate path + partial profile
        zone_header = self._cell_wall.render_zone_headers()
        coordinate_path = f"{encoding} | {topology_suffix}" if topology_suffix else encoding
        if partial_profile:
            return f"{zone_header}\n{coordinate_path}\n{partial_profile}"
        return f"{zone_header}\n{coordinate_path}"

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
            self._store.upsert_node(space_id, coords, label, confidence)
        if results:
            self._is_mature_cached = None

    def ingest_sessions(self, session_timestamps: List[float]) -> None:
        """Derive a chrono node from session timestamp history."""
        result = self._extractor.extract_from_sessions(session_timestamps)
        if result:
            space_id, coords, confidence, label = result
            self._store.upsert_node(space_id, coords, label, confidence)
            self._is_mature_cached = None

    def ingest_conduct_outcomes(self, episodes: List[Any]) -> None:
        """
        Derive behavioural conduct coordinates from completed episodes.

        Episodes are expected to have 'outcome' and optionally 'task_text' fields.
        This is a best-effort pass; failures are silently swallowed.
        """
        try:
            for episode in episodes:
                text = getattr(episode, "task_text", None) or episode.get("task_text", "")
                outcome = getattr(episode, "outcome", None) or episode.get("outcome", "")
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
        """Record a tool call observation; upsert toolpath node once window ≥ 3."""
        self._extractor.ingest_tool_call(
            tool_name=tool_name,
            success=success,
            sequence_position=sequence_position,
            total_steps=total_steps,
            session_id=session_id,
        )

    def ingest_context(self, text: str, session_data: dict) -> None:
        """Extract a context-space node from project/stack signals in text + session data."""
        result = self._extractor._extract_context_signals(text, session_data)
        if result:
            space_id, coords, confidence, label = result
            self._store.upsert_node(space_id, coords, label, confidence)
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
            ingested = self._rag_bridge.ingest(content, source_type, session_id, metadata)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] ingest_rag_content bridge failed: %s", exc)
            return

        try:
            # Extract coordinates — conduct space will be skipped for low-trust channels
            results = self._extractor.extract_from_statement(content)
            for space_id, coords, confidence, label in results:
                # Skip conduct writes from non-trusted channels
                if not self._cell_wall.can_write_space(ingested.channel, space_id):
                    logger.debug(
                        "[interface] RAG channel %s blocked from writing space '%s'",
                        ingested.channel.name, space_id,
                    )
                    continue
                self._store.upsert_node(space_id, coords, label, confidence)
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

    def _check_quorum_and_reorganize(self, session_id: str) -> None:
        """
        Check QuorumSensor threshold and fire QuorumReorganization if breached.

        Called after recording anomaly signals.  All exceptions swallowed.
        """
        try:
            if self._quorum_sensor.check_threshold():
                from .kyudo import QuorumReorganization  # noqa: PLC0415
                QuorumReorganization().fire(self, session_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("[interface] quorum reorganization failed: %s", exc)

    def crystallize_landmark(
        self,
        session_id: str,
        cumulative_score: float,
        outcome: str,
        task_entry_label: Optional[str] = None,
    ) -> Optional[Landmark]:
        """
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

        landmark = self._condenser.condense(
            session_id=session_id,
            cumulative_score=cumulative_score,
            outcome=outcome,
            task_entry_label=task_entry_label,
        )
        if landmark is None:
            return None

        self._lm_index.save(landmark)
        merged = self._merger.try_merge(landmark)
        surviving = merged or landmark

        self._ep_indexer.backfill_landmark(session_id, surviving.landmark_id)

        # Record session position in topology chart (Task 11.3)
        try:
            active_nodes: List[Any] = []
            for space_id in SPACES:
                active_nodes.extend(self._store.get_nodes_by_space(space_id))
            self._topology_layer.record_session_position(session_id, active_nodes)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[interface] topology record_session_position failed: %s", exc)

        return surviving

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
        """
        self._navigator.clear_session(session_id)
        self._extractor.clear_session(session_id)

        # Step 3: predictive pre-warm at session boundary (mature only)
        if self.is_mature():
            try:
                self._predictive_loader.pre_warm(
                    session_id, self._navigator, self._last_task_class or "full"
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("[interface] pre_warm failed: %s", exc)

        # Step 4: flag maintenance if overdue
        if self._last_distillation_at is not None:
            elapsed = time.time() - self._last_distillation_at
            if elapsed > DISTILLATION_MAX_INTERVAL:
                self._maintenance_needed = True

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

    def run_maintenance(self) -> None:
        """
        Full five-step maintenance sequence (Req 12.9):
          1. Edge decay (EdgeScorer.apply_decay)
          2. Condense nodes (MapManager.run_condense)
          3. Expand nodes (MapManager.run_expand)
          4. Landmark edge decay (LandmarkIndex.apply_landmark_decay)
          5. Profile render (ProfileRenderer.render_dirty_sections)

        Sets _last_distillation_at to now.
        """
        logger.info("[interface] Running Mycelium maintenance pass")
        try:
            pruned = self._scorer.apply_decay()
            logger.debug("[interface] maintenance: pruned %d edges", pruned)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[interface] maintenance: apply_decay failed: %s", exc)

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
            logger.debug("[interface] maintenance: landmark edges pruned: %d", lm_pruned)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[interface] maintenance: apply_landmark_decay failed: %s", exc)

        try:
            rendered = self._renderer.render_dirty_sections()
            logger.debug("[interface] maintenance: rendered %d profile sections", rendered)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[interface] maintenance: render_dirty_sections failed: %s", exc)

        # Step 6 — Topology maintenance (v2.0, MUST run after v1.5 sequence)
        try:
            self._topology_layer.run_topology_maintenance()
            logger.debug("[interface] maintenance: topology pass complete")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[interface] maintenance: topology pass failed: %s", exc)

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
            "is_mature":                   self.is_mature(),
            "node_count":                  node_count,
            "landmark_count":              landmark_count,
            "threat_level":                threat_level,
            "prediction_cache_hit_rate":   prediction_cache_hit_rate,
            "avg_spaces_navigated":        avg_spaces_navigated,
            "whiteboard_broadcast_tokens": whiteboard_broadcast_tokens,
            "failure_warning_tokens":      failure_warning_tokens,
            "avg_context_tokens_per_task": (
                (self._total_context_chars / self._context_task_count / 4)
                if self._context_task_count > 0 else 0.0
            ),
            "last_task_class":             self._last_task_class,
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
        for space_id in SPACES:
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

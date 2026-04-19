"""
Topology Layer v2.0 — 3D Landmark Geometry for the Mycelium coordinate graph.

Builds a local 3D chart around each crystallized landmark
(activation_count >= CHART_ACTIVATION_THRESHOLD = 12).

Three axes:
  X — Domain Proximity    (0.0 = distant, 1.0 = inside anchor core)
  Y — Operational Similarity (0.0 = different tools/conduct, 1.0 = identical)
  Z — Temporal Convergence   (positive = approaching, negative = diverging)

Five behavioral primitives:
  CORE, EXPLORATION, TRANSFER, ACQUISITION, EVOLUTION, ORBIT

Entirely additive — never touches v1.5 tables.
Designed to be isolated from the main encrypted storage module.
"""

from __future__ import annotations

import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (Req 17.23 — must match design-topology.md exactly)
# ---------------------------------------------------------------------------

CHART_ACTIVATION_THRESHOLD: int   = 12    # activations before landmark becomes a chart origin
CHART_CAPTURE_RADIUS:       float = 0.65  # max X-Y Euclidean distance to receive a chart position
MIN_SESSIONS_FOR_TRAJECTORY: int  = 4    # minimum chart positions before Z is non-zero
MIN_ORBIT_SESSIONS:         int   = 5    # sessions needed to confirm a deficiency signal
STALENESS_SESSION_COUNT:    int   = 8    # consecutive negative-Z sessions before staleness eval
CONVERGENCE_THRESHOLD:      float = 0.08  # Z >= this → ACQUISITION
DIVERGENCE_THRESHOLD:       float = -0.06 # Z <= this → EVOLUTION
ORBIT_RADIUS_INNER:         float = 0.20  # inside this = CORE territory, not orbit
ORBIT_RADIUS_OUTER:         float = 0.55  # outside this = not orbiting (too far)

# Maximum Z values kept per trajectory row
_MAX_Z_HISTORY: int = 20

# Chart positions to retrieve for Z calculation
_Z_LOOKBACK: int = 10

# Days before chart positions are pruned
_CHART_PRUNE_DAYS: int = 90


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class BehavioralPrimitive(str, Enum):
    """Six behavioral primitives derived from (X, Y, Z) position in a landmark chart."""
    CORE        = "core"
    EXPLORATION = "exploration"
    TRANSFER    = "transfer"
    ACQUISITION = "acquisition"
    EVOLUTION   = "evolution"
    ORBIT       = "orbit"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ChartPosition:
    """One row in mycelium_charts — session positioned relative to a landmark."""
    position_id: str
    landmark_id: str
    session_id: str
    x: float
    y: float
    z: float
    primitive: BehavioralPrimitive
    confidence: float
    created_at: float
    stale: bool = False


@dataclass
class AnchorTrajectory:
    """Trajectory record for a single crystallized landmark."""
    trajectory_id: str
    landmark_id: str
    z_values: List[float]
    z_trend: float
    primitive_history: List[str]
    staleness_count: int
    last_updated: float


@dataclass
class DeficiencySignal:
    """
    Knowledge gap identified from orbital session patterns.

    Centroid (centroid_x, centroid_y) indicates where in X-Y space the
    orbit cluster is located relative to the anchor.
    """
    landmark_id: str
    centroid_x: float
    centroid_y: float
    session_count: int
    description: str


@dataclass
class TopologyContext:
    """Assembled topology context for one session ready for encoding."""
    anchor_ids: List[str]
    primitives: List[BehavioralPrimitive]
    z_values: List[float]
    trajectory_label: Optional[str]
    deficiency_signals: List[DeficiencySignal]
    confidence_delta: float


# ---------------------------------------------------------------------------
# ChartRegistry
# ---------------------------------------------------------------------------

class ChartRegistry:
    """
    Manages which landmarks qualify as chart origins (Req 17.1–17.2).

    A landmark becomes a chart origin when its ``activation_count`` reaches
    ``CHART_ACTIVATION_THRESHOLD`` (12).  Chart positions are only recorded
    for sessions within ``CHART_CAPTURE_RADIUS`` (0.65) of an origin.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def get_chart_origins(self) -> List[str]:
        """
        Return landmark_ids for all landmarks with activation_count >=
        CHART_ACTIVATION_THRESHOLD.  Returns [] when none qualify.
        """
        try:
            rows = self._conn.execute(
                """
                SELECT landmark_id FROM mycelium_landmarks
                WHERE activation_count >= ? AND absorbed IS NULL
                """,
                (CHART_ACTIVATION_THRESHOLD,),
            ).fetchall()
            return [row[0] for row in rows]
        except Exception as exc:  # noqa: BLE001
            logger.debug("[ChartRegistry] get_chart_origins failed: %s", exc)
            return []

    def get_nearest_origins(
        self, session_id: str, active_nodes: List[Any]
    ) -> List[str]:
        """
        Return chart origin landmark_ids within CHART_CAPTURE_RADIUS of the
        current session's X-Y position.

        Returns [] when no crystallized anchors exist.
        """
        origins = self.get_chart_origins()
        if not origins:
            return []

        # Build session domain + conduct centroids from active_nodes
        session_domain = _avg_coordinates(
            [n for n in active_nodes if getattr(n, "space_id", "") == "domain"]
        )
        session_conduct = _avg_coordinates(
            [n for n in active_nodes if getattr(n, "space_id", "") == "conduct"]
        )

        nearby: List[str] = []
        for lm_id in origins:
            # Retrieve anchor cluster from landmark coordinate_cluster JSON
            cluster = _load_landmark_cluster(self._conn, lm_id)
            if not cluster:
                continue

            anchor_domain = _avg_cluster_coords(cluster, "domain")
            anchor_conduct = _avg_cluster_coords(cluster, "conduct")

            # Simple Euclidean proxy for X and Y
            x_approx = _coord_similarity(session_domain, anchor_domain)
            y_approx = _coord_similarity(session_conduct, anchor_conduct)
            xy_dist = math.sqrt((1.0 - x_approx) ** 2 + (1.0 - y_approx) ** 2)

            if xy_dist <= CHART_CAPTURE_RADIUS:
                nearby.append(lm_id)

        return nearby


# ---------------------------------------------------------------------------
# AxisCalculator
# ---------------------------------------------------------------------------

class AxisCalculator:
    """
    Stateless — computes X, Y, Z for a session relative to a landmark anchor.
    No __init__ needed.  All methods are static helpers.
    """

    @staticmethod
    def compute_x(active_nodes: List[Any], anchor_cluster: List[dict]) -> float:
        """
        Domain proximity: |session_domain_nodes ∩ anchor_domain_cluster| / |anchor_domain_cluster|.

        Returns 0.0 on empty overlap, 1.0 on exact match.
        """
        anchor_domain = [
            n for n in anchor_cluster
            if n.get("space_id") == "domain"
        ]
        if not anchor_domain:
            return 0.0

        session_domain = [
            n for n in active_nodes
            if getattr(n, "space_id", "") == "domain"
        ]
        if not session_domain:
            return 0.0

        # Count anchor domain nodes that are "matched" by session nodes
        # (within 0.10 Euclidean distance in coordinate space)
        matched = 0
        for anchor_node in anchor_domain:
            anchor_coords = anchor_node.get("coordinates", [])
            for sess_node in session_domain:
                sess_coords = getattr(sess_node, "coordinates", [])
                if _euclidean(anchor_coords, sess_coords) <= 0.10:
                    matched += 1
                    break

        return min(1.0, matched / len(anchor_domain))

    @staticmethod
    def compute_y(active_nodes: List[Any], anchor_cluster: List[dict]) -> float:
        """
        Operational similarity: 0.60 × conduct_similarity + 0.40 × toolpath_similarity.

        similarity = 1 - euclidean_distance, clipped to [0.0, 1.0].
        Returns 0.0 on empty nodes.
        """
        conduct_sim  = _space_similarity(active_nodes, anchor_cluster, "conduct")
        toolpath_sim = _space_similarity(active_nodes, anchor_cluster, "toolpath")
        return min(1.0, max(0.0, 0.60 * conduct_sim + 0.40 * toolpath_sim))

    @staticmethod
    def compute_z(session_id: str, anchor_id: str, conn: Any) -> float:
        """
        Temporal convergence — least-squares regression over recent X-Y distances.

        Steps:
          1. Retrieve last min(N, 10) chart positions for this (session, anchor) pair,
             ordered oldest first.
          2. Return 0.0 immediately if fewer than MIN_SESSIONS_FOR_TRAJECTORY positions.
          3. Compute Euclidean distance from each position to the anchor origin (0, 0).
          4. Apply least-squares linear regression:
               slope = (n·Σ(xᵢ·dᵢ) − Σxᵢ·Σdᵢ) / (n·Σ(xᵢ²) − (Σxᵢ)²)
             where xᵢ = i (0-based integer index).
          5. Normalise and negate: z = −(slope / CHART_CAPTURE_RADIUS).
          6. Clamp to [−1.0, +1.0].

        Positive Z = converging (distances decreasing over time).
        Negative Z = diverging.
        Near-zero  = stable.
        """
        try:
            rows = conn.execute(
                """
                SELECT x, y FROM mycelium_charts
                WHERE landmark_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (anchor_id, _Z_LOOKBACK),
            ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[AxisCalculator] compute_z DB query failed: %s", exc)
            return 0.0

        if len(rows) < MIN_SESSIONS_FOR_TRAJECTORY:
            return 0.0

        # Distances from anchor origin (0, 0)
        distances = [math.sqrt(x ** 2 + y ** 2) for (x, y) in rows]
        n = len(distances)

        # Least-squares linear regression
        xs = list(range(n))
        sum_x  = sum(xs)
        sum_d  = sum(distances)
        sum_xd = sum(x * d for x, d in zip(xs, distances))
        sum_x2 = sum(x * x for x in xs)

        denom = n * sum_x2 - sum_x ** 2
        if abs(denom) < 1e-9:
            return 0.0

        slope = (n * sum_xd - sum_x * sum_d) / denom

        # Normalise and negate (decreasing distance = positive Z = convergence)
        z = -(slope / CHART_CAPTURE_RADIUS)
        return max(-1.0, min(1.0, z))


# ---------------------------------------------------------------------------
# PrimitiveClassifier
# ---------------------------------------------------------------------------

class PrimitiveClassifier:
    """
    Stateless — maps (X, Y, Z) to one of the six behavioral primitives.

    Classification rules (first match wins, from design-topology.md):
      1.  x >= 0.8 AND y >= 0.8                              → CORE
      2.  x >= 0.7 AND y < 0.5                               → EXPLORATION
      3.  x < 0.5  AND y >= 0.7                              → TRANSFER
      4.  z > CONVERGENCE_THRESHOLD (0.08)                   → ACQUISITION
      5.  z < DIVERGENCE_THRESHOLD (-0.06) AND x >= 0.5
          AND y >= 0.5                                        → EVOLUTION
      6.  ORBIT_RADIUS_INNER < euclidean(x, y, 0) < ORBIT_RADIUS_OUTER
          AND |z| < CONVERGENCE_THRESHOLD                     → ORBIT
      7.  Otherwise                                           → ORBIT
    """

    @staticmethod
    def classify(x: float, y: float, z: float) -> BehavioralPrimitive:
        """Return the behavioral primitive for position (x, y, z)."""
        # Rule 1
        if x >= 0.8 and y >= 0.8:
            return BehavioralPrimitive.CORE
        # Rule 2
        if x >= 0.7 and y < 0.5:
            return BehavioralPrimitive.EXPLORATION
        # Rule 3
        if x < 0.5 and y >= 0.7:
            return BehavioralPrimitive.TRANSFER
        # Rule 4
        if z > CONVERGENCE_THRESHOLD:
            return BehavioralPrimitive.ACQUISITION
        # Rule 5
        if z < DIVERGENCE_THRESHOLD and x >= 0.5 and y >= 0.5:
            return BehavioralPrimitive.EVOLUTION
        # Rule 6 & 7 — ORBIT is the fallback
        return BehavioralPrimitive.ORBIT


# ---------------------------------------------------------------------------
# DeficiencyDetector
# ---------------------------------------------------------------------------

class DeficiencyDetector:
    """
    Identifies orbital session clusters in a landmark's chart and generates
    ``DeficiencySignal`` objects for each confirmed knowledge gap (Req 17.9–17.12).

    CORE sessions are NEVER counted as orbital regardless of X-Y position.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def detect_orbits(self, landmark_id: str) -> List[DeficiencySignal]:
        """
        Return deficiency signals for orbital clusters around *landmark_id*.

        Returns [] when fewer than MIN_ORBIT_SESSIONS orbit records exist.
        """
        try:
            rows = self._conn.execute(
                """
                SELECT x, y, session_id FROM mycelium_charts
                WHERE landmark_id = ? AND primitive = ? AND stale = 0
                """,
                (landmark_id, BehavioralPrimitive.ORBIT.value),
            ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[DeficiencyDetector] DB query failed: %s", exc)
            return []

        if len(rows) < MIN_ORBIT_SESSIONS:
            return []

        # Simple Euclidean clustering (DBSCAN-lite with radius 0.25)
        CLUSTER_RADIUS = 0.25
        points = [(x, y) for (x, y, _) in rows]
        clusters = _simple_cluster(points, CLUSTER_RADIUS)

        signals: List[DeficiencySignal] = []
        for cluster in clusters:
            if len(cluster) < MIN_ORBIT_SESSIONS:
                continue
            cx = sum(p[0] for p in cluster) / len(cluster)
            cy = sum(p[1] for p in cluster) / len(cluster)
            signals.append(DeficiencySignal(
                landmark_id=landmark_id,
                centroid_x=round(cx, 3),
                centroid_y=round(cy, 3),
                session_count=len(cluster),
                description=(
                    f"orbital pattern at X={cx:.2f},Y={cy:.2f} "
                    f"({len(cluster)} sessions)"
                ),
            ))

        return signals


# ---------------------------------------------------------------------------
# AnchorLifecycle
# ---------------------------------------------------------------------------

class AnchorLifecycle:
    """
    Evaluates and marks landmark chart staleness (Req 17.13–17.17).

    Staleness requires BOTH conditions to be True:
      (1) staleness_count >= STALENESS_SESSION_COUNT (8 consecutive negative-Z sessions)
      (2) A newer landmark of the same task_class has higher activation_count

    Either condition alone is not sufficient.
    The underlying landmark row in mycelium_landmarks is NEVER modified.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def evaluate_staleness(self, landmark_id: str) -> bool:
        """Return True only when BOTH staleness conditions are met."""
        try:
            # Check condition 1: staleness_count threshold
            traj_row = self._conn.execute(
                """
                SELECT staleness_count FROM mycelium_trajectories
                WHERE landmark_id = ?
                """,
                (landmark_id,),
            ).fetchone()
            if traj_row is None:
                return False
            if traj_row[0] < STALENESS_SESSION_COUNT:
                return False

            # Check condition 2: newer landmark of same task_class with higher activation
            lm_row = self._conn.execute(
                """
                SELECT task_class, activation_count, created_at
                FROM mycelium_landmarks WHERE landmark_id = ?
                """,
                (landmark_id,),
            ).fetchone()
            if lm_row is None:
                return False
            task_class, activation_count, created_at = lm_row

            newer = self._conn.execute(
                """
                SELECT COUNT(*) FROM mycelium_landmarks
                WHERE task_class = ?
                  AND activation_count > ?
                  AND created_at > ?
                  AND absorbed IS NULL
                  AND landmark_id != ?
                """,
                (task_class, activation_count, created_at, landmark_id),
            ).fetchone()
            return (newer is not None and newer[0] > 0)

        except Exception as exc:  # noqa: BLE001
            logger.debug("[AnchorLifecycle] evaluate_staleness failed: %s", exc)
            return False

    def mark_stale(self, landmark_id: str) -> None:
        """
        SET stale = 1 on all mycelium_charts rows for *landmark_id*.
        Does NOT modify the mycelium_landmarks row.
        """
        try:
            self._conn.execute(
                "UPDATE mycelium_charts SET stale = 1 WHERE landmark_id = ?",
                (landmark_id,),
            )
            self._conn.commit()
            logger.debug("[AnchorLifecycle] marked stale: %s", landmark_id[:12])
        except Exception as exc:  # noqa: BLE001
            logger.debug("[AnchorLifecycle] mark_stale failed: %s", exc)


# ---------------------------------------------------------------------------
# TopologyLayer — main entry point
# ---------------------------------------------------------------------------

class TopologyLayer:
    """
    Top-level integration class for the v2.0 topology layer (Req 17.18–17.25).

    Responsibilities:
      - Position sessions in 3D chart space relative to nearby anchors
      - Return a ``TopologyContext`` for context injection
      - Encode the context under 25 tokens for the ``TOPOLOGY:`` zone
      - Run topology maintenance (prune, staleness, re-render)

    Never touches v1.5 tables.
    """

    def __init__(
        self,
        conn: Any,
        store: Any,  # CoordinateStore — used to fetch active nodes when needed
    ) -> None:
        self._conn  = conn
        self._store = store
        self._chart_registry     = ChartRegistry(conn)
        self._axis_calc          = AxisCalculator()
        self._prim_classifier    = PrimitiveClassifier()
        self._deficiency         = DeficiencyDetector(conn)
        self._anchor_lifecycle   = AnchorLifecycle(conn)

    def record_session_position(
        self, session_id: str, active_nodes: List[Any]
    ) -> List[ChartPosition]:
        """
        Compute and store a chart position for each nearby anchor (Req 17.18–17.19).

        Returns [] when no crystallized anchors exist.
        Does NOT touch any v1.5 tables.
        """
        origins = self._chart_registry.get_nearest_origins(session_id, active_nodes)
        if not origins:
            return []

        positions: List[ChartPosition] = []
        for lm_id in origins:
            try:
                cluster = _load_landmark_cluster(self._conn, lm_id)
                if not cluster:
                    continue

                x = AxisCalculator.compute_x(active_nodes, cluster)
                y = AxisCalculator.compute_y(active_nodes, cluster)
                z = AxisCalculator.compute_z(session_id, lm_id, self._conn)
                prim = PrimitiveClassifier.classify(x, y, z)
                confidence = min(1.0, (x + y) / 2.0)
                now = time.time()

                pos = ChartPosition(
                    position_id=str(uuid.uuid4()),
                    landmark_id=lm_id,
                    session_id=session_id,
                    x=round(x, 4),
                    y=round(y, 4),
                    z=round(z, 4),
                    primitive=prim,
                    confidence=round(confidence, 4),
                    created_at=now,
                    stale=False,
                )

                # Persist to mycelium_charts
                self._conn.execute(
                    """
                    INSERT INTO mycelium_charts
                        (position_id, landmark_id, session_id, x, y, z,
                         primitive, confidence, created_at, stale)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        pos.position_id, lm_id, session_id,
                        pos.x, pos.y, pos.z,
                        prim.value, pos.confidence, now,
                    ),
                )

                # Update trajectory row
                self._update_trajectory(lm_id, z, prim)

                positions.append(pos)

            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "[TopologyLayer] record_session_position failed for %s: %s",
                    lm_id[:12], exc,
                )

        if positions:
            self._conn.commit()

        return positions

    def get_topology_context(
        self, session_id: str, active_nodes: List[Any]
    ) -> Optional[TopologyContext]:
        """
        Build a TopologyContext for this session (Req 17.20–17.21).

        Returns None when no crystallized anchors exist (fresh install / pre-maturity).
        """
        origins = self._chart_registry.get_nearest_origins(session_id, active_nodes)
        if not origins:
            return None

        anchor_ids: List[str]            = []
        primitives: List[BehavioralPrimitive] = []
        z_values:   List[float]          = []
        deficiency_signals: List[DeficiencySignal] = []

        for lm_id in origins:
            try:
                latest = self._conn.execute(
                    """
                    SELECT x, y, z, primitive FROM mycelium_charts
                    WHERE landmark_id = ? AND session_id = ? AND stale = 0
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (lm_id, session_id),
                ).fetchone()

                if latest is None:
                    continue

                x, y, z, prim_str = latest
                prim = BehavioralPrimitive(prim_str)

                anchor_ids.append(lm_id)
                primitives.append(prim)
                z_values.append(round(z, 4))

                # Deficiency signals from orbit patterns
                deficiency_signals.extend(
                    self._deficiency.detect_orbits(lm_id)
                )

            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "[TopologyLayer] get_topology_context failed for %s: %s",
                    lm_id[:12], exc,
                )

        if not anchor_ids:
            return None

        # Trajectory label from highest-confidence positive-Z anchor
        trajectory_label = self._build_trajectory_label(
            anchor_ids, z_values
        )

        # Confidence delta: each CORE or ACQUISITION boosts by 0.04
        confidence_delta = sum(
            0.04 for p in primitives
            if p in (BehavioralPrimitive.CORE, BehavioralPrimitive.ACQUISITION)
        )

        return TopologyContext(
            anchor_ids=anchor_ids,
            primitives=primitives,
            z_values=z_values,
            trajectory_label=trajectory_label,
            deficiency_signals=deficiency_signals,
            confidence_delta=round(confidence_delta, 3),
        )

    def encode_topology_context(self, ctx: Optional["TopologyContext"]) -> str:
        """
        Produce the ``TOPOLOGY:`` context zone string (Req 17.22).

        Under 25 tokens.  Returns "" when ctx is None.

        Format:
          TOPOLOGY: prim:{prim} z:{z:.2f} [deficiency:{n}]
        """
        if ctx is None:
            return ""

        # Use first (highest-confidence) anchor's values
        prim = ctx.primitives[0].value if ctx.primitives else "unknown"
        z    = ctx.z_values[0] if ctx.z_values else 0.0
        n_def = len(ctx.deficiency_signals)

        parts = [f"TOPOLOGY: prim:{prim} z:{z:+.2f}"]
        if n_def > 0:
            parts.append(f"[deficiency:{n_def}]")
        if ctx.confidence_delta != 0.0:
            parts.append(f"?conf:{ctx.confidence_delta:+.2f}")

        return " ".join(parts)

    def run_topology_maintenance(self) -> None:
        """
        Topology maintenance pass (Req 17.25).

        MUST run after the full v1.5 maintenance pass completes.
        Steps:
          1. Prune mycelium_charts rows older than 90 days.
          2. Re-evaluate staleness for all active trajectories.
          3. mark_stale() on those that qualify.
        """
        try:
            cutoff = time.time() - (_CHART_PRUNE_DAYS * 86400)
            cursor = self._conn.execute(
                "DELETE FROM mycelium_charts WHERE created_at < ?", (cutoff,)
            )
            pruned = cursor.rowcount
            self._conn.commit()
            logger.debug("[TopologyLayer] pruned %d stale chart positions", pruned)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[TopologyLayer] chart prune failed: %s", exc)

        try:
            landmarks = self._chart_registry.get_chart_origins()
            for lm_id in landmarks:
                if self._anchor_lifecycle.evaluate_staleness(lm_id):
                    self._anchor_lifecycle.mark_stale(lm_id)
                    logger.info(
                        "[TopologyLayer] anchor marked stale: %s", lm_id[:12]
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[TopologyLayer] staleness evaluation failed: %s", exc)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _update_trajectory(
        self, landmark_id: str, z: float, primitive: BehavioralPrimitive
    ) -> None:
        """Upsert the trajectory row for *landmark_id* with the new Z value."""
        try:
            now = time.time()
            row = self._conn.execute(
                """
                SELECT trajectory_id, z_values, primitive_history, staleness_count
                FROM mycelium_trajectories WHERE landmark_id = ?
                """,
                (landmark_id,),
            ).fetchone()

            if row is None:
                tid = str(uuid.uuid4())
                z_list = [z]
                prim_hist = [primitive.value]
                staleness = 1 if z < 0 else 0
                self._conn.execute(
                    """
                    INSERT INTO mycelium_trajectories
                        (trajectory_id, landmark_id, z_values, z_trend,
                         primitive_history, staleness_count, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tid, landmark_id,
                        json.dumps(z_list),
                        z,
                        json.dumps(prim_hist),
                        staleness,
                        now,
                    ),
                )
            else:
                tid, z_raw, prim_raw, staleness = row
                z_list = json.loads(z_raw or "[]")
                prim_hist = json.loads(prim_raw or "[]")

                z_list.append(z)
                if len(z_list) > _MAX_Z_HISTORY:
                    z_list = z_list[-_MAX_Z_HISTORY:]
                prim_hist.append(primitive.value)

                # Exponential-decay weighted moving average for z_trend
                z_trend = _ewma(z_list)

                # Staleness counter: reset on positive Z, increment on negative
                staleness = staleness + 1 if z < 0 else 0

                self._conn.execute(
                    """
                    UPDATE mycelium_trajectories
                    SET z_values = ?, z_trend = ?, primitive_history = ?,
                        staleness_count = ?, last_updated = ?
                    WHERE trajectory_id = ?
                    """,
                    (
                        json.dumps(z_list),
                        round(z_trend, 6),
                        json.dumps(prim_hist),
                        staleness,
                        now,
                        tid,
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[TopologyLayer] _update_trajectory failed: %s", exc)

    def _build_trajectory_label(
        self, anchor_ids: List[str], z_values: List[float]
    ) -> Optional[str]:
        """Return a human-readable trajectory label for the highest positive-Z anchor."""
        if not anchor_ids:
            return None
        best_idx = max(range(len(z_values)), key=lambda i: z_values[i])
        best_z = z_values[best_idx]
        if best_z <= CONVERGENCE_THRESHOLD:
            return None
        lm_id = anchor_ids[best_idx]
        try:
            row = self._conn.execute(
                "SELECT label FROM mycelium_landmarks WHERE landmark_id = ?",
                (lm_id,),
            ).fetchone()
            if row and row[0]:
                return f"converging on {row[0]}"
        except Exception:  # noqa: BLE001
            pass
        return f"converging on {lm_id[:8]}"


# ---------------------------------------------------------------------------
# Module-level utility helpers (not part of public API)
# ---------------------------------------------------------------------------

def _euclidean(a: List[float], b: List[float]) -> float:
    """Euclidean distance between two equal-length float lists."""
    if not a or not b or len(a) != len(b):
        return float("inf")
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _avg_coordinates(nodes: List[Any]) -> List[float]:
    """Return the element-wise mean of all node coordinate vectors."""
    if not nodes:
        return []
    coords = [getattr(n, "coordinates", []) for n in nodes if getattr(n, "coordinates", None)]
    if not coords:
        return []
    dim = len(coords[0])
    return [sum(c[i] for c in coords) / len(coords) for i in range(dim)]


def _avg_cluster_coords(cluster: List[dict], space_id: str) -> List[float]:
    """Return mean coordinates of cluster nodes belonging to *space_id*."""
    nodes = [n for n in cluster if n.get("space_id") == space_id]
    if not nodes:
        return []
    all_coords = [n.get("coordinates", []) for n in nodes if n.get("coordinates")]
    if not all_coords:
        return []
    dim = len(all_coords[0])
    return [sum(c[i] for c in all_coords) / len(all_coords) for i in range(dim)]


def _coord_similarity(a: List[float], b: List[float]) -> float:
    """
    Similarity as (1 - normalised Euclidean distance), clipped to [0.0, 1.0].
    Returns 0.0 when either list is empty or dimensions differ.
    """
    if not a or not b:
        return 0.0
    dist = _euclidean(a, b)
    if dist == float("inf"):
        return 0.0
    return max(0.0, 1.0 - dist)


def _space_similarity(
    active_nodes: List[Any], anchor_cluster: List[dict], space_id: str
) -> float:
    """Compute mean pairwise similarity for *space_id* nodes."""
    session = _avg_coordinates(
        [n for n in active_nodes if getattr(n, "space_id", "") == space_id]
    )
    anchor = _avg_cluster_coords(anchor_cluster, space_id)
    return _coord_similarity(session, anchor)


def _load_landmark_cluster(conn: Any, landmark_id: str) -> List[dict]:
    """Load the coordinate_cluster JSON from mycelium_landmarks."""
    try:
        row = conn.execute(
            "SELECT coordinate_cluster FROM mycelium_landmarks WHERE landmark_id = ?",
            (landmark_id,),
        ).fetchone()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as exc:  # noqa: BLE001
        logger.debug("[topology] _load_landmark_cluster failed: %s", exc)
    return []


def _ewma(values: List[float], alpha: float = 0.3) -> float:
    """Exponentially weighted moving average (recent = higher weight)."""
    if not values:
        return 0.0
    result = values[0]
    for v in values[1:]:
        result = alpha * v + (1 - alpha) * result
    return result


def _simple_cluster(
    points: List[Tuple[float, float]], radius: float
) -> List[List[Tuple[float, float]]]:
    """
    Greedy single-linkage clustering.

    Returns a list of clusters where each cluster is a list of points.
    """
    if not points:
        return []

    assigned = [False] * len(points)
    clusters: List[List[Tuple[float, float]]] = []

    for i, p in enumerate(points):
        if assigned[i]:
            continue
        cluster = [p]
        assigned[i] = True
        for j, q in enumerate(points):
            if assigned[j]:
                continue
            if math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) <= radius:
                cluster.append(q)
                assigned[j] = True
        clusters.append(cluster)

    return clusters

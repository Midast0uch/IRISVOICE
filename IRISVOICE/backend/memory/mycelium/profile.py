"""
LandmarkMerger and ProfileRenderer — landmark deduplication and human-readable profile generation.

LandmarkMerger: fires after every Landmark save to merge highly-overlapping landmarks,
keeping the graph clean and preventing duplicate patterns from consuming context tokens.

ProfileRenderer: translates the coordinate graph's node data into natural-language prose
sections that describe the user's working style, preferences, and environment.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from .landmark import Landmark, LandmarkIndex, _jaccard
from .store import CoordNode, CoordinateStore
from .spaces import (
    CLUSTER_MAX_NODES,
    DOMAIN_IDS,
    MERGE_OVERLAP_THRESHOLD,
    RENDER_ORDER,
)

logger = logging.getLogger(__name__)

# Minimum activation_count for absorbed-only nodes to survive a merge (Req 10.3)
_ABSORBED_NODE_MIN_ACTIVATIONS: int = 2


# ---------------------------------------------------------------------------
# LandmarkMerger
# ---------------------------------------------------------------------------

class LandmarkMerger:
    """
    Deduplicates the landmark graph after every crystallisation (Req 10.1–10.5).

    Merges landmarks whose coordinate clusters overlap ≥ MERGE_OVERLAP_THRESHOLD (0.50).
    """

    def __init__(self, index: LandmarkIndex) -> None:
        self._index = index

    def try_merge(self, new_landmark: Landmark) -> Optional[Landmark]:
        """
        Attempt to merge new_landmark into an existing landmark (Req 10.1–10.5).

        Called immediately after every `LandmarkIndex.save()`.

        Merge logic:
          - Candidate: any non-absorbed landmark with cluster overlap ≥ MERGE_OVERLAP_THRESHOLD (0.50).
          - Survivor: higher activation_count; tie → higher cumulative_score.
          - Merged cluster: nodes in both keep higher access_count entry; absorbed-only
            nodes kept only if activation_count ≥ 2; cap at CLUSTER_MAX_NODES (6).
          - Merged cumulative_score: weighted average by activation_count.
          - Absorbed landmark: marked `absorbed = 1` in DB.
          - All `mycelium_landmark_edges` from absorbed re-pointed to survivor.
          - `mycelium_landmark_merges` log row written.
          - `mycelium_profile` rows for affected spaces marked dirty=1.

        Returns:
            The surviving Landmark after merge, or None if no merge occurred.
        """
        all_landmarks = self._index.get_all_active()
        ids_new = {d.get("node_id") for d in new_landmark.coordinate_cluster}

        best_candidate: Optional[Landmark] = None
        best_overlap: float = 0.0

        for lm in all_landmarks:
            if lm.landmark_id == new_landmark.landmark_id:
                continue
            ids_other = {d.get("node_id") for d in lm.coordinate_cluster}
            overlap = _jaccard(ids_new, ids_other)
            if overlap >= MERGE_OVERLAP_THRESHOLD and overlap > best_overlap:
                best_overlap = overlap
                best_candidate = lm

        if best_candidate is None:
            return None

        # Determine survivor
        if best_candidate.activation_count > new_landmark.activation_count:
            survivor, absorbed = best_candidate, new_landmark
        elif new_landmark.activation_count > best_candidate.activation_count:
            survivor, absorbed = new_landmark, best_candidate
        else:
            # Tie: higher cumulative_score wins
            if best_candidate.cumulative_score >= new_landmark.cumulative_score:
                survivor, absorbed = best_candidate, new_landmark
            else:
                survivor, absorbed = new_landmark, best_candidate

        # Build merged cluster
        merged_cluster = self._build_merged_cluster(
            survivor.coordinate_cluster, absorbed.coordinate_cluster
        )

        # Compute merged cumulative_score (weighted average by activation_count)
        total_activations = max(
            1, survivor.activation_count + absorbed.activation_count
        )
        merged_score = (
            survivor.cumulative_score * survivor.activation_count
            + absorbed.cumulative_score * absorbed.activation_count
        ) / total_activations

        # Persist: update survivor, absorb victim, re-point edges, log merge
        self._persist_merge(
            survivor=survivor,
            absorbed=absorbed,
            merged_cluster=merged_cluster,
            merged_score=merged_score,
            overlap_score=best_overlap,
        )

        # Return updated survivor as a new Landmark object
        return Landmark(
            landmark_id=survivor.landmark_id,
            label=survivor.label,
            task_class=survivor.task_class,
            coordinate_cluster=merged_cluster,
            traversal_sequence=survivor.traversal_sequence,
            cumulative_score=merged_score,
            micro_abstract=survivor.micro_abstract,
            micro_abstract_text=survivor.micro_abstract_text,
            activation_count=survivor.activation_count,
            is_permanent=survivor.is_permanent,
            conversation_ref=survivor.conversation_ref,
            created_at=survivor.created_at,
            last_activated=survivor.last_activated,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_merged_cluster(
        cluster_s: List[Dict],
        cluster_a: List[Dict],
    ) -> List[Dict]:
        """
        Build the merged node list.

        - Nodes in both clusters: keep the one with higher access_count.
        - Nodes only in absorbed: include only if access_count ≥ 2.
        - Cap at CLUSTER_MAX_NODES (6) sorted by access_count DESC.
        """
        by_node_id: Dict[str, Dict] = {}

        for entry in cluster_s:
            nid = entry.get("node_id")
            if nid:
                by_node_id[nid] = entry

        for entry in cluster_a:
            nid = entry.get("node_id")
            if not nid:
                continue
            if nid in by_node_id:
                # Keep higher access_count
                if entry.get("access_count", 0) > by_node_id[nid].get("access_count", 0):
                    by_node_id[nid] = entry
            else:
                # Absorbed-only: include only if activation ≥ 2
                if entry.get("access_count", 0) >= _ABSORBED_NODE_MIN_ACTIVATIONS:
                    by_node_id[nid] = entry

        # Sort by access_count DESC, cap
        merged = sorted(
            by_node_id.values(),
            key=lambda e: e.get("access_count", 0),
            reverse=True,
        )
        return merged[:CLUSTER_MAX_NODES]

    def _persist_merge(
        self,
        survivor: Landmark,
        absorbed: Landmark,
        merged_cluster: List[Dict],
        merged_score: float,
        overlap_score: float,
    ) -> None:
        """Write all DB changes for a landmark merge in one transaction."""
        conn = self._index._conn
        now = time.time()

        # Update survivor
        conn.execute(
            """
            UPDATE mycelium_landmarks
            SET coordinate_cluster = ?, cumulative_score = ?
            WHERE landmark_id = ?
            """,
            (json.dumps(merged_cluster), merged_score, survivor.landmark_id),
        )

        # Mark absorbed
        conn.execute(
            "UPDATE mycelium_landmarks SET absorbed = 1 WHERE landmark_id = ?",
            (absorbed.landmark_id,),
        )

        # Re-point all landmark edges from absorbed → survivor (skip self-loops)
        conn.execute(
            """
            UPDATE mycelium_landmark_edges
            SET from_landmark_id = ?
            WHERE from_landmark_id = ? AND to_landmark_id != ?
            """,
            (survivor.landmark_id, absorbed.landmark_id, survivor.landmark_id),
        )
        conn.execute(
            """
            UPDATE mycelium_landmark_edges
            SET to_landmark_id = ?
            WHERE to_landmark_id = ? AND from_landmark_id != ?
            """,
            (survivor.landmark_id, absorbed.landmark_id, survivor.landmark_id),
        )
        # Remove self-loops created by re-point
        conn.execute(
            "DELETE FROM mycelium_landmark_edges WHERE from_landmark_id = to_landmark_id"
        )

        # Log merge
        merge_id = f"mrg_{now:.0f}"
        conn.execute(
            """
            INSERT INTO mycelium_landmark_merges
                (merge_id, survivor_id, absorbed_id, overlap_score,
                 pre_merge_score_s, pre_merge_score_a, post_merge_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                merge_id,
                survivor.landmark_id,
                absorbed.landmark_id,
                overlap_score,
                survivor.cumulative_score,
                absorbed.cumulative_score,
                merged_score,
                now,
            ),
        )

        # Mark affected profile sections dirty
        affected_spaces = {d.get("space_id") for d in merged_cluster}
        for space_id in affected_spaces:
            if space_id:
                conn.execute(
                    "UPDATE mycelium_profile SET dirty = 1 WHERE space_id = ?",
                    (space_id,),
                )

        conn.commit()
        logger.debug(
            "[profile] merged landmark %s into %s (overlap=%.2f)",
            absorbed.landmark_id,
            survivor.landmark_id,
            overlap_score,
        )


# ---------------------------------------------------------------------------
# ProfileRenderer
# ---------------------------------------------------------------------------

class ProfileRenderer:
    """
    Converts the coordinate graph's node data into natural-language prose (Req 10.6–10.12).

    One prose section is generated per space (excluding toolpath — Req 10.9).
    Sections are stored in `mycelium_profile` with a dirty flag for lazy invalidation.
    """

    def __init__(self, store: CoordinateStore, index: LandmarkIndex) -> None:
        self._store = store
        self._index = index
        self._conn = index._conn

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def render_dirty_sections(self) -> int:
        """
        Regenerate all `mycelium_profile` rows where dirty=1, plus any spaces
        that have nodes but no profile section yet (Req 10.10).

        Toolpath MUST NOT produce a profile section.

        Returns:
            Number of sections (re-)generated.
        """
        rendered = 0

        # Collect spaces to render: dirty rows + spaces with nodes but no row
        dirty_cursor = self._conn.execute(
            "SELECT space_id FROM mycelium_profile WHERE dirty = 1"
        )
        dirty_spaces = {row[0] for row in dirty_cursor.fetchall()}

        # Add spaces with nodes but no profile row
        for space_id in RENDER_ORDER:  # toolpath is not in RENDER_ORDER
            if space_id == "toolpath":
                continue
            nodes = self._store.get_nodes_by_space(space_id)
            if nodes:
                dirty_spaces.add(space_id)

        for space_id in dirty_spaces:
            if space_id == "toolpath":
                continue
            nodes = self._store.get_nodes_by_space(space_id)
            prose = self._render_space(space_id, nodes)
            if prose:
                self._upsert_section(space_id, prose, nodes)
                rendered += 1

        return rendered

    def get_profile_section(self, space_id: str) -> Optional[str]:
        """Return the prose string for a single space, or None if not generated."""
        cursor = self._conn.execute(
            "SELECT prose FROM mycelium_profile WHERE space_id = ?", (space_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_readable_profile(self) -> str:
        """
        Assemble all non-dirty profile sections in RENDER_ORDER sequence (Req 10.11).

        Returns an empty string if no sections have been generated.
        """
        cursor = self._conn.execute(
            """
            SELECT space_id, prose, render_order FROM mycelium_profile
            WHERE dirty = 0
            ORDER BY render_order ASC
            """
        )
        rows = cursor.fetchall()
        parts = [row[1] for row in rows if row[1]]
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Space-specific render methods (Req 10.6–10.9)
    # ------------------------------------------------------------------

    def _render_space(self, space_id: str, nodes: List[CoordNode]) -> str:
        if not nodes:
            return ""
        render_fn = {
            "domain":     self._render_domain,
            "conduct":    self._render_conduct,
            "chrono":     self._render_chrono,
            "style":      self._render_style,
            "capability": self._render_capability,
            "context":    self._render_context,
        }.get(space_id)
        if render_fn is None:
            return ""
        return render_fn(nodes)

    def _render_domain(self, nodes: List[CoordNode]) -> str:
        """Describe primary and familiar knowledge domains."""
        # domain axes: domain_id (normalized), proficiency, recency
        # Reverse-map domain_id_val → domain name
        id_to_name = {v / 12.0: k for k, v in DOMAIN_IDS.items()}

        expert: List[str] = []
        familiar: List[str] = []

        for node in nodes:
            if len(node.coordinates) < 2:
                continue
            domain_norm = node.coordinates[0]
            proficiency = node.coordinates[1]

            # Find closest domain name
            closest = min(id_to_name.keys(), key=lambda k: abs(k - domain_norm))
            name = id_to_name[closest]

            if proficiency >= 0.8:
                expert.append(name)
            elif proficiency >= 0.5:
                familiar.append(name)

        parts: List[str] = []
        if expert:
            parts.append(f"Expert in {', '.join(expert)}")
        if familiar:
            parts.append(f"familiar with {', '.join(familiar)}")

        if not parts:
            return ""
        return "Domains: " + "; ".join(parts) + "."

    def _render_conduct(self, nodes: List[CoordNode]) -> str:
        """Describe working style — autonomy, iteration, depth. Never raw floats."""
        # conduct axes: autonomy, iteration_style, session_depth,
        #               confirmation_threshold, correction_rate
        if not nodes:
            return ""
        node = nodes[0]  # highest access_count node
        if len(node.coordinates) < 5:
            return ""

        autonomy = node.coordinates[0]
        session_depth = node.coordinates[2]
        confirm_thresh = node.coordinates[3]

        autonomy_str = (
            "highly autonomous" if autonomy >= 0.75
            else "moderately autonomous" if autonomy >= 0.45
            else "prefers confirmation-driven workflow"
        )
        depth_str = (
            "deep multi-step sessions" if session_depth >= 0.7
            else "medium-length sessions" if session_depth >= 0.4
            else "short focused sessions"
        )
        confirm_str = (
            "minimal confirmation needed" if confirm_thresh <= 0.3
            else "occasional confirmation preferred" if confirm_thresh <= 0.65
            else "frequent confirmation preferred"
        )

        return f"Working style: {autonomy_str}; {depth_str}; {confirm_str}."

    def _render_chrono(self, nodes: List[CoordNode]) -> str:
        """Describe temporal working patterns."""
        if not nodes:
            return ""
        node = nodes[0]
        if len(node.coordinates) < 3:
            return ""

        peak_hour = node.coordinates[0]  # [0, 24)
        avg_len_norm = node.coordinates[1]  # [0, 1] normalized vs 8h
        consistency = node.coordinates[2]  # [0, 1]

        # Convert to human-readable time of day
        if 5 <= peak_hour < 12:
            tod = "morning"
        elif 12 <= peak_hour < 17:
            tod = "afternoon"
        elif 17 <= peak_hour < 21:
            tod = "evening"
        else:
            tod = "night"

        avg_hours = avg_len_norm * 8.0
        len_str = (
            f"~{avg_hours:.1f}h average sessions"
            if avg_hours >= 0.5
            else "short sessions"
        )

        consistency_str = (
            "very consistent schedule" if consistency >= 0.75
            else "moderately consistent schedule" if consistency >= 0.4
            else "flexible schedule"
        )

        return f"Activity pattern: primarily {tod} work; {len_str}; {consistency_str}."

    def _render_style(self, nodes: List[CoordNode]) -> str:
        """Describe communication style preferences."""
        if not nodes:
            return ""
        node = nodes[0]
        if len(node.coordinates) < 3:
            return ""

        formality = node.coordinates[0]
        verbosity = node.coordinates[1]
        directness = node.coordinates[2]

        formality_str = (
            "formal tone" if formality >= 0.7
            else "neutral tone" if formality >= 0.35
            else "casual tone"
        )
        verbosity_str = (
            "detailed responses" if verbosity >= 0.7
            else "moderate detail" if verbosity >= 0.35
            else "concise responses"
        )
        directness_str = (
            "direct communication" if directness >= 0.7
            else "balanced directness" if directness >= 0.35
            else "diplomatic communication"
        )

        return f"Style: {formality_str}; {verbosity_str}; {directness_str}."

    def _render_capability(self, nodes: List[CoordNode]) -> str:
        """Describe hardware and environment as capability level, not raw specs."""
        if not nodes:
            return ""
        node = nodes[0]
        if len(node.coordinates) < 5:
            return ""

        gpu_tier = node.coordinates[0]  # [0, 5]
        ram_norm = node.coordinates[1]  # [0, 1]
        has_docker = node.coordinates[2] >= 0.5
        has_tailscale = node.coordinates[3] >= 0.5
        os_id = node.coordinates[4]

        gpu_str = (
            "no dedicated GPU" if gpu_tier < 1
            else "entry GPU" if gpu_tier < 2
            else "mid-range GPU" if gpu_tier < 3
            else "high-end GPU" if gpu_tier < 4
            else "professional GPU"
        )

        ram_gb = ram_norm * 128
        ram_str = (
            f"~{int(ram_gb)}GB RAM"
            if ram_gb >= 1
            else "limited RAM"
        )

        os_str = (
            "Linux" if os_id < 0.3
            else "macOS" if os_id < 0.7
            else "Windows"
        )

        tools: List[str] = []
        if has_docker:
            tools.append("Docker")
        if has_tailscale:
            tools.append("Tailscale")

        tools_str = f"; tools: {', '.join(tools)}" if tools else ""

        return f"Environment: {os_str}; {gpu_str}; {ram_str}{tools_str}."

    def _render_context(self, nodes: List[CoordNode]) -> str:
        """Describe active projects where freshness > 0.10."""
        # context axes: project_id, stack_id, constraint_flags, freshness
        active = [
            n for n in nodes
            if len(n.coordinates) >= 4 and n.coordinates[3] > 0.10
        ]
        if not active:
            return ""

        primary = active[0]
        secondary = active[1:]

        label = primary.label or "unnamed project"
        constraint = primary.coordinates[2] if len(primary.coordinates) > 2 else 0.0
        constraint_str = (
            "high constraint environment" if constraint >= 0.75
            else "elevated constraints" if constraint >= 0.50
            else "moderate constraints" if constraint >= 0.25
            else "low constraints"
        )

        parts = [f"Active project: {label} ({constraint_str})"]
        if secondary:
            sec_labels = [n.label or "unnamed" for n in secondary[:2]]
            parts.append(f"secondary: {', '.join(sec_labels)}")

        return "; ".join(parts) + "."

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _upsert_section(
        self, space_id: str, prose: str, nodes: List[CoordNode]
    ) -> None:
        """Write or update a mycelium_profile row for the given space."""
        render_order = RENDER_ORDER.get(space_id, 99)
        source_node_ids = json.dumps([n.node_id for n in nodes])
        word_count = len(prose.split())
        now = time.time()

        existing = self._conn.execute(
            "SELECT section_id FROM mycelium_profile WHERE space_id = ?", (space_id,)
        ).fetchone()

        if existing:
            self._conn.execute(
                """
                UPDATE mycelium_profile
                SET prose = ?, source_node_ids = ?, dirty = 0,
                    last_rendered = ?, word_count = ?
                WHERE space_id = ?
                """,
                (prose, source_node_ids, now, word_count, space_id),
            )
        else:
            section_id = f"prof_{space_id}"
            self._conn.execute(
                """
                INSERT INTO mycelium_profile
                    (section_id, space_id, render_order, prose, source_node_ids,
                     source_lm_ids, dirty, last_rendered, word_count)
                VALUES (?, ?, ?, ?, ?, NULL, 0, ?, ?)
                """,
                (section_id, space_id, render_order, prose, source_node_ids, now, word_count),
            )

        self._conn.commit()

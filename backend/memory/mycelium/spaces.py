"""
Coordinate space definitions and all named numeric constants for the Mycelium layer.

This is the root dependency module — it imports nothing from other Mycelium modules.
All constants used across the layer are defined here once and imported elsewhere.
"""

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Coordinate space dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CoordinateSpace:
    """Immutable definition of one of the seven Mycelium coordinate spaces."""

    space_id: str
    axes: List[str]
    dtype: str
    value_range: Tuple[float, float]
    description: str


# ---------------------------------------------------------------------------
# Seven canonical coordinate spaces (Req 1.1 – 1.8)
# ---------------------------------------------------------------------------

SPACES: Dict[str, CoordinateSpace] = {
    "conduct": CoordinateSpace(
        space_id="conduct",
        axes=["autonomy", "iteration_style", "session_depth", "confirmation_threshold", "correction_rate"],
        dtype="float",
        value_range=(0.0, 1.0),
        description="Behavioural profile — how the user prefers to work with an agent",
    ),
    "domain": CoordinateSpace(
        space_id="domain",
        axes=["domain_id", "proficiency", "recency"],
        dtype="float",
        value_range=(0.0, 1.0),
        description="Knowledge domain the user is working in, normalised proficiency, and recency",
    ),
    "style": CoordinateSpace(
        space_id="style",
        axes=["formality", "verbosity", "directness"],
        dtype="float",
        value_range=(0.0, 1.0),
        description="Communication style preferences",
    ),
    "chrono": CoordinateSpace(
        space_id="chrono",
        axes=["peak_activity_hour_utc", "avg_session_length_hours", "consistency"],
        dtype="float",
        value_range=(0.0, 24.0),  # peak_activity_hour_utc spans [0, 24]; others [0, 1]
        description="Temporal patterns — when and how long the user typically works",
    ),
    "context": CoordinateSpace(
        space_id="context",
        axes=["project_id", "stack_id", "constraint_flags", "freshness"],
        dtype="float",
        value_range=(0.0, 1.0),
        description="Active project context — project identity, tech stack, constraints, and freshness",
    ),
    "capability": CoordinateSpace(
        space_id="capability",
        axes=["gpu_tier", "ram_normalized", "has_docker", "has_tailscale", "os_id"],
        dtype="float",
        value_range=(0.0, 5.0),  # gpu_tier spans [0, 5]; others [0, 1]
        description="Hardware and environment capabilities of the user's machine",
    ),
    "toolpath": CoordinateSpace(
        space_id="toolpath",
        axes=["tool_id", "call_frequency_normalized", "success_rate", "avg_sequence_position"],
        dtype="float",
        value_range=(0.0, 1.0),
        description="Per-tool usage patterns — which tools are called, how often, and how successfully",
    ),
}


# ---------------------------------------------------------------------------
# Domain ID mapping — 13 canonical software/knowledge domains (Req 1.3)
# ---------------------------------------------------------------------------

DOMAIN_IDS: Dict[str, int] = {
    "ai":        0,
    "web":       1,
    "data":      2,
    "devops":    3,
    "mobile":    4,
    "systems":   5,
    "security":  6,
    "finance":   7,
    "science":   8,
    "design":    9,
    "hardware":  10,
    "gaming":    11,
    "general":   12,
}


# ---------------------------------------------------------------------------
# OS encoding constants (Req 1.7)
# ---------------------------------------------------------------------------

OS_ID_LINUX:   float = 0.0
OS_ID_MAC:     float = 0.5
OS_ID_WINDOWS: float = 1.0


# ---------------------------------------------------------------------------
# Decay rate constants (Req 1.6, 1.8, 1.9)
# ---------------------------------------------------------------------------

CONDUCT_DECAY_RATE: float = 0.008   # Req 1.9 — slower than toolpath, reflects stable behaviour
TOOLPATH_DECAY_RATE: float = 0.02   # Req 1.8 — tool patterns shift faster than identity
CONTEXT_DECAY_RATE: float = 0.025   # Req 1.6 — freshness axis decays per day


# ---------------------------------------------------------------------------
# Profile render order (fixed — toolpath absent, never rendered) (Req 12.4)
# ---------------------------------------------------------------------------

RENDER_ORDER: Dict[str, int] = {
    "domain":     1,
    "conduct":    2,
    "chrono":     3,
    "style":      4,
    "capability": 5,
    "context":    6,
    # toolpath deliberately absent — never rendered to profile
}


# ---------------------------------------------------------------------------
# Cold-start conduct default (Req 4.26–4.29)
# ---------------------------------------------------------------------------

CONDUCT_COLD_START_DEFAULT: List[float] = [0.5, 0.5, 0.5, 0.5, 0.5]
# All axes at midpoint: moderate autonomy, balanced iteration, medium depth,
# moderate confirmation, low correction. Conservative by design — a user who
# wants more autonomy will correct quickly (3–5 sessions); a comfortable user
# will never trigger a correction signal.


# ---------------------------------------------------------------------------
# Constraint flag weights for context space (Req 4.12)
# Stored as named constants — do NOT hardcode inline in extractor
# ---------------------------------------------------------------------------

CONSTRAINT_WEIGHT_DEADLINE:   float = 0.30
CONSTRAINT_WEIGHT_PRODUCTION: float = 0.25
CONSTRAINT_WEIGHT_PUBLIC:     float = 0.25
CONSTRAINT_WEIGHT_SECURITY:   float = 0.20


# ---------------------------------------------------------------------------
# Maturity and scoring constants (Req 7–11)
# ---------------------------------------------------------------------------

# Landmark lifecycle
PERMANENCE_THRESHOLD: int     = 8     # activation_count at which a landmark becomes permanent
LANDMARK_MIN_SCORE: float     = 0.45  # minimum cumulative score to keep a landmark
LANDMARK_PRUNE_THRESHOLD: float = 0.08  # prune landmark if score falls below this
MERGE_OVERLAP_THRESHOLD: float  = 0.50  # overlap fraction required for landmark merge

# Edge scoring
PRUNE_THRESHOLD: float  = 0.08  # delete edge if score falls below this during decay
HIGHWAY_THRESHOLD: float = 0.85  # bonus applies above this score
HIGHWAY_BONUS: float     = 0.01  # extra delta added for highway edges

# Map management
CONDENSE_THRESHOLD: float = 0.04  # merge nodes within this Euclidean distance
SPLIT_THRESHOLD: float    = 0.40  # split node when hit/miss edge variance exceeds this
CLUSTER_MAX_NODES: int    = 6     # maximum nodes to include in one landmark cluster

# Resonance scoring
RESONANCE_OVERLAP_THRESHOLD: float    = 0.60   # per-space overlap required to count as resonating
RESONANCE_WEIGHT_PER_SPACE: float     = 0.15   # multiplier added per resonating space
LANDMARK_MATCH_BONUS: float           = 0.40   # bonus when current landmark matches episode landmark
SUPPRESSION_COVERAGE_THRESHOLD: float = 0.70   # suppress success episode at this coverage ratio

# Resonance spaces — toolpath explicitly excluded (Req 11.5)
RESONANCE_SPACES: frozenset = frozenset({
    "domain", "conduct", "chrono", "style", "capability", "context"
})
# toolpath is task-local, not session-persistent; including it inflates scores
# for structurally unrelated tasks


# ---------------------------------------------------------------------------
# tool_id() — deterministic hash of a tool name to [0, 1] (Req 1.10)
# ---------------------------------------------------------------------------

def tool_id(name: str) -> float:
    """
    Deterministically hash a tool name to a float in [0.0, 1.0].

    Uses MD5 modulo 10000 — same algorithm as project_id and stack_id hashing.

    Args:
        name: Tool name string (e.g. "read_file", "bash")

    Returns:
        Float in [0.0, 1.0]
    """
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    return int(digest, 16) % 10000 / 10000.0

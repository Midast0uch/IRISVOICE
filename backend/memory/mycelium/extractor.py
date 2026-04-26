"""
CoordinateExtractor — derives coordinate values from every observable signal source.

Extraction sources (all Req 4.x):
  - Explicit user statements  → conduct, style, domain nodes (confidence 0.4)
  - Session timestamp history → chrono node
  - Hardware introspection    → capability node (confidence 0.95)
  - Project/stack context     → context node
  - Live tool call stream     → toolpath node (≥ 3 observations required)

No user configuration is required — every extractor is signal-driven and gracefully
returns None / [] when not enough information is available.
"""

import hashlib
import logging
import math
import re
import shutil
import sys
import time
from typing import Dict, List, Optional, Tuple

from .store import CoordinateStore
from .spaces import (
    CONDUCT_COLD_START_DEFAULT,
    CONSTRAINT_WEIGHT_DEADLINE,
    CONSTRAINT_WEIGHT_PRODUCTION,
    CONSTRAINT_WEIGHT_PUBLIC,
    CONSTRAINT_WEIGHT_SECURITY,
    DOMAIN_IDS,
    OS_ID_LINUX,
    OS_ID_MAC,
    OS_ID_WINDOWS,
    tool_id as _tool_id_hash,
)

logger = logging.getLogger(__name__)

# Type alias — every extractor method returns one or more of these
_ExtractionTuple = Tuple[str, List[float], float, Optional[str]]

# ---------------------------------------------------------------------------
# Keyword pattern tables for extract_from_statement
# ---------------------------------------------------------------------------

# Conduct space patterns
# Format: (axis_index, keyword_pattern, axis_value)
_CONDUCT_PATTERNS: List[Tuple[int, str, float]] = [
    # autonomy (axis 0): high
    (0, r"\b(be autonomous|just do it|handle it yourself|figure it out|without asking|don't ask|do it without|go ahead)\b", 0.85),
    # autonomy (axis 0): low
    (0, r"\b(ask me first|confirm with me|check with me|always confirm|ask before|wait for my|need my approval)\b", 0.15),
    # confirmation_threshold (axis 3): high (ask for confirmation often)
    (3, r"\b(always ask|confirm everything|ask before every|double.?check with me)\b", 0.85),
    # confirmation_threshold (axis 3): low (minimal confirmation needed)
    (3, r"\b(never ask|skip confirmation|no need to confirm|just proceed|don't confirm)\b", 0.15),
    # correction_rate (axis 4): expecting corrections
    (4, r"\b(i'll correct|let me know if wrong|flag mistakes|i may correct)\b", 0.6),
]

# Style space patterns
# Format: (axis_index, pattern, axis_value)
_STYLE_PATTERNS: List[Tuple[int, str, float]] = [
    # formality (axis 0): high
    (0, r"\b(formal|professional|business.?like|academic)\b", 0.85),
    # formality (axis 0): low
    (0, r"\b(casual|informal|conversational|relaxed|chill)\b", 0.15),
    # verbosity (axis 1): high
    (1, r"\b(detailed|thorough|comprehensive|in.?depth|elaborate|verbose|explain fully)\b", 0.85),
    # verbosity (axis 1): low
    (1, r"\b(brief|concise|short|terse|summary|just the key|keep it short|tldr)\b", 0.15),
    # directness (axis 2): high
    (2, r"\b(be direct|straight to the point|blunt|no fluff|cut to the chase|no hedging)\b", 0.85),
    # directness (axis 2): low
    (2, r"\b(gentle|diplomatic|careful with words|soften|tactful|be kind)\b", 0.15),
]

# Domain space: keyword → DOMAIN_IDS key
_DOMAIN_KEYWORDS: List[Tuple[str, str]] = [
    # AI / ML
    (r"\b(machine learning|neural net|llm|deep learning|ai model|transformer|embedding|fine.?tun)\b", "ai"),
    # Web
    (r"\b(react|vue|angular|html|css|javascript|typescript|frontend|backend|rest api|graphql|nextjs|web app)\b", "web"),
    # Data
    (r"\b(sql|database|postgres|mysql|pandas|dataframe|etl|pipeline|spark|analytics|data engineer)\b", "data"),
    # DevOps
    (r"\b(docker|kubernetes|k8s|ci.?cd|github action|terraform|ansible|deploy|devops|helm|pipeline)\b", "devops"),
    # Mobile
    (r"\b(ios|android|swift|kotlin|flutter|react native|mobile app)\b", "mobile"),
    # Systems
    (r"\b(c\+\+|rust|kernel|linux|assembly|embedded|firmware|systems programming|low level)\b", "systems"),
    # Security
    (r"\b(security|pentest|vulnerability|cve|exploit|auth|oauth|jwt|encryption|ssl|tls)\b", "security"),
    # Finance
    (r"\b(finance|trading|stock|crypto|portfolio|quant|financial model|risk model)\b", "finance"),
    # Science
    (r"\b(physics|chemistry|biology|scientific|simulation|numerical|scipy|numpy|matlab|research)\b", "science"),
    # Design
    (r"\b(design|figma|ui|ux|typography|color|branding|sketch|prototype)\b", "design"),
    # Hardware
    (r"\b(hardware|fpga|verilog|pcb|circuit|gpio|arduino|raspberry pi|microcontroller)\b", "hardware"),
    # Gaming
    (r"\b(game dev|unity|unreal|godot|shader|game engine|3d model|blender)\b", "gaming"),
]

# Context space: stack keyword → label
_STACK_KEYWORDS: List[Tuple[str, str]] = [
    (r"\bpython\b", "python"),
    (r"\b(node\.?js|nodejs)\b", "nodejs"),
    (r"\brust\b", "rust"),
    (r"\bgolang\b|\bgo\b", "go"),
    (r"\bjava\b", "java"),
    (r"\bc#\b|\.net\b", "csharp"),
    (r"\bruby\b", "ruby"),
    (r"\bphp\b", "php"),
    (r"\bswift\b", "swift"),
    (r"\bkotlin\b", "kotlin"),
    (r"\breact\b", "react"),
    (r"\bnext\.?js\b", "nextjs"),
]

_CONSTRAINT_PATTERNS: List[Tuple[str, float]] = [
    (r"\b(deadline|due date|urgent|asap|by tomorrow|time constraint|time.?sensitive)\b", CONSTRAINT_WEIGHT_DEADLINE),
    (r"\b(production|prod|live system|customer.?facing|critical system)\b", CONSTRAINT_WEIGHT_PRODUCTION),
    (r"\b(public|open source|published|shared publicly|external)\b", CONSTRAINT_WEIGHT_PUBLIC),
    (r"\b(security.?sensitive|confidential|private data|pii|credentials|secrets)\b", CONSTRAINT_WEIGHT_SECURITY),
]


# ---------------------------------------------------------------------------
# CoordinateExtractor
# ---------------------------------------------------------------------------

class CoordinateExtractor:
    """
    Derives coordinate tuples from text, behaviour, hardware, and tool calls.

    Each extraction method returns either a list of `(space_id, coords, confidence, label)`
    tuples (for multi-value results) or a single Optional tuple.  Callers pass the
    returned tuples to `CoordinateStore.upsert_node()`.
    """

    def __init__(self, store: CoordinateStore) -> None:
        self._store = store
        # Observation windows for toolpath extraction: (session_id, tool_name) → list
        self._observation_windows: Dict[Tuple[str, str], List[dict]] = {}

    # ------------------------------------------------------------------
    # Text-based extraction (Req 4.1–4.8)
    # ------------------------------------------------------------------

    def extract_from_statement(self, text: str) -> List[_ExtractionTuple]:
        """
        Extract conduct, style, and domain coordinates from a user statement (Req 4.1–4.8).

        Uses keyword/pattern matching only — no LLM call.
        Confidence is always 0.4 for stated values (Req 4.4).

        Returns:
            List of (space_id, coords, confidence, label) tuples.
            Returns [] if no signals are found.
        """
        results: List[_ExtractionTuple] = []
        text_lower = text.lower()

        # -- conduct --
        conduct_coords = list(CONDUCT_COLD_START_DEFAULT)  # start at midpoint
        conduct_changed = False
        for axis_idx, pattern, value in _CONDUCT_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                conduct_coords[axis_idx] = value
                conduct_changed = True
        if conduct_changed:
            results.append(("conduct", conduct_coords, 0.4, "stated_conduct"))

        # -- style --
        style_coords = [0.5, 0.5, 0.5]  # formality, verbosity, directness
        style_changed = False
        for axis_idx, pattern, value in _STYLE_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                style_coords[axis_idx] = value
                style_changed = True
        if style_changed:
            results.append(("style", style_coords, 0.4, "stated_style"))

        # -- domain --
        for pattern, domain_key in _DOMAIN_KEYWORDS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                domain_id_val = DOMAIN_IDS[domain_key] / 12.0  # normalize to [0,1]
                # proficiency=0.5 (unknown), recency=1.0 (just mentioned)
                domain_coords = [domain_id_val, 0.5, 1.0]
                results.append(("domain", domain_coords, 0.4, f"domain_{domain_key}"))

        return results

    # ------------------------------------------------------------------
    # Session timing extraction (Req 4.9–4.12)
    # ------------------------------------------------------------------

    def extract_from_sessions(
        self, session_timestamps: List[float]
    ) -> Optional[_ExtractionTuple]:
        """
        Compute chrono coordinates from session start timestamps (Req 4.9–4.12).

        Requires at least 5 timestamps; returns None otherwise.

        Axes: peak_activity_hour_utc (circular mean), avg_session_length_hours,
              consistency (stddev of inter-session gaps, inverted and normalized).

        Args:
            session_timestamps: UNIX timestamps of session starts.

        Returns:
            ("chrono", coords, confidence, label) or None.
        """
        if len(session_timestamps) < 5:
            return None

        # Convert timestamps to local hours (UTC hours of day)
        hours = [
            (t % 86400) / 3600.0  # fractional hour of day [0, 24)
            for t in session_timestamps
        ]

        # Circular mean of hours (avoids midnight wraparound artefact)
        angles = [2.0 * math.pi * h / 24.0 for h in hours]
        mean_sin = sum(math.sin(a) for a in angles) / len(angles)
        mean_cos = sum(math.cos(a) for a in angles) / len(angles)
        peak_hour = math.atan2(mean_sin, mean_cos) * 24.0 / (2.0 * math.pi)
        if peak_hour < 0:
            peak_hour += 24.0  # wrap to [0, 24)

        # Average session length — estimated from inter-session gaps
        # Use inter-session intervals as a proxy for session length (if no end times)
        sorted_ts = sorted(session_timestamps)
        gaps = [sorted_ts[i + 1] - sorted_ts[i] for i in range(len(sorted_ts) - 1)]
        avg_gap_hours = (sum(gaps) / len(gaps)) / 3600.0

        # Clamp avg session length to [0.25, 8] hours as a rough cap
        avg_session_hours = min(max(avg_gap_hours * 0.5, 0.25), 8.0)

        # Consistency: stddev of gaps (in hours), inverted: lower stddev → higher consistency
        if len(gaps) > 1:
            mean_gap = sum(gaps) / len(gaps)
            stddev = math.sqrt(sum((g - mean_gap) ** 2 for g in gaps) / len(gaps))
            stddev_hours = stddev / 3600.0
            # Normalize: 0 stddev → 1.0 (perfectly consistent), high stddev → 0.0
            consistency = 1.0 / (1.0 + stddev_hours)
        else:
            consistency = 0.5

        # Normalize avg_session_hours to [0, 1] vs 8-hour reference
        avg_session_norm = min(avg_session_hours / 8.0, 1.0)

        coords = [peak_hour, avg_session_norm, consistency]
        confidence = min(0.3 + 0.05 * len(session_timestamps), 0.9)  # more samples → higher confidence

        return ("chrono", coords, confidence, "session_pattern")

    # ------------------------------------------------------------------
    # Hardware introspection (Req 4.13–4.18)
    # ------------------------------------------------------------------

    def extract_hardware(self) -> Optional[_ExtractionTuple]:
        """
        Detect hardware and environment capabilities (Req 4.13–4.18).

        Axes: gpu_tier [0–5], ram_normalized [0–1], has_docker [0/1],
              has_tailscale [0/1], os_id [0.0/0.5/1.0].

        Confidence is 0.95 — hardware facts are objective.
        The entire function is wrapped in try/except; returns None on any error.

        Returns:
            ("capability", coords, 0.95, "hardware") or None.
        """
        try:
            gpu_tier = self._detect_gpu_tier()
            ram_norm = self._detect_ram_normalized()
            has_docker = 1.0 if shutil.which("docker") is not None else 0.0
            has_tailscale = 1.0 if shutil.which("tailscale") is not None else 0.0
            os_id = _detect_os_id()

            coords = [gpu_tier, ram_norm, has_docker, has_tailscale, os_id]
            return ("capability", coords, 0.95, "hardware")

        except Exception as exc:  # noqa: BLE001
            logger.debug("[extractor] extract_hardware failed: %s", exc)
            return None

    @staticmethod
    def _detect_gpu_tier() -> float:
        """
        Probe for NVIDIA GPU via nvidia-smi and return a tier in [0.0, 5.0].

        Tier mapping (VRAM in GB):  0 = none, 1 = <4 GB, 2 = 4–8 GB,
                                    3 = 8–16 GB, 4 = 16–40 GB, 5 = ≥40 GB.
        Falls back to 0 if nvidia-smi is unavailable or parsing fails.
        """
        if shutil.which("nvidia-smi") is None:
            return 0.0

        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                vram_mb = int(result.stdout.strip().split("\n")[0].strip())
                vram_gb = vram_mb / 1024.0
                if vram_gb < 4:
                    return 1.0
                elif vram_gb < 8:
                    return 2.0
                elif vram_gb < 16:
                    return 3.0
                elif vram_gb < 40:
                    return 4.0
                else:
                    return 5.0
        except Exception:  # noqa: BLE001
            pass

        return 0.0

    @staticmethod
    def _detect_ram_normalized() -> float:
        """Return system RAM normalized to 128 GB, clamped to [0.0, 1.0]."""
        try:
            import psutil
            total_bytes = psutil.virtual_memory().total
            reference_bytes = 128 * 1024 ** 3
            return min(total_bytes / reference_bytes, 1.0)
        except ImportError:
            pass

        # Fallback: read /proc/meminfo on Linux
        try:
            with open("/proc/meminfo") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return min(kb / (128 * 1024 ** 2), 1.0)
        except Exception:  # noqa: BLE001
            pass

        return 0.25  # Safe default: assume modest RAM

    # ------------------------------------------------------------------
    # Context extraction (Req 4.19–4.25)
    # ------------------------------------------------------------------

    def _extract_context_signals(
        self, text: str, session_data: dict
    ) -> Optional[_ExtractionTuple]:
        """
        Extract context space coordinates from text and session data (Req 4.19–4.25).

        Looks for project name and tech stack signals. Returns None if neither
        project nor stack identifiers can be inferred.

        Axes: project_id, stack_id, constraint_flags, freshness.
        """
        text_lower = text.lower()

        # --- Project label ---
        project_label: Optional[str] = session_data.get("project_name")
        if project_label is None:
            # Try to extract from text: "project <name>", "repo <name>", "@<name>"
            m = re.search(r"\bproject\s+([a-z0-9_\-]+)", text_lower)
            if m:
                project_label = m.group(1)
            else:
                m = re.search(r"\brepo\s+([a-z0-9_\-]+)", text_lower)
                if m:
                    project_label = m.group(1)

        # --- Stack identifier ---
        stack_label: Optional[str] = session_data.get("stack_name")
        if stack_label is None:
            for pattern, label in _STACK_KEYWORDS:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    stack_label = label
                    break

        if project_label is None and stack_label is None:
            return None  # Not enough context to write a context node

        # Hash to [0, 1] via MD5 modulo (Req 4.19)
        proj_id = _md5_to_float(project_label or "unknown_project")
        stack_id = _md5_to_float(stack_label or "unknown_stack")

        # Constraint flags: weighted sum of detected constraint signals
        constraint_flags = 0.0
        for pattern, weight in _CONSTRAINT_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                constraint_flags = min(1.0, constraint_flags + weight)

        freshness = 1.0  # Freshly observed — always starts at 1.0

        coords = [proj_id, stack_id, constraint_flags, freshness]
        label = f"project_{project_label or 'unknown'}"
        return ("context", coords, 0.5, label)

    # ------------------------------------------------------------------
    # Tool call ingestion (Req 4.28–4.29)
    # ------------------------------------------------------------------

    def ingest_tool_call(
        self,
        tool_name: str,
        success: bool,
        sequence_position: int,
        total_steps: int,
        session_id: str,
    ) -> None:
        """
        Record a single tool call observation and upsert a toolpath node when
        the per-session-tool observation window reaches ≥ 3 entries (Req 4.28–4.29).

        Maintains per-session, per-tool observation windows in memory only.
        Windows are cleared by `clear_session()`.

        Args:
            tool_name:         Canonical tool name (e.g. "bash", "read_file").
            success:           Whether the tool call succeeded.
            sequence_position: Position of this call in the current task sequence (1-based).
            total_steps:       Total number of steps in the current task sequence.
            session_id:        Current session identifier.
        """
        key = (session_id, tool_name)
        if key not in self._observation_windows:
            self._observation_windows[key] = []

        self._observation_windows[key].append({
            "success":           success,
            "sequence_position": sequence_position,
            "total_steps":       max(1, total_steps),
            "timestamp":         time.time(),
        })

        window = self._observation_windows[key]
        if len(window) < 3:
            return  # Not enough observations yet

        # Compute toolpath coordinates from the window
        tid = _tool_id_hash(tool_name)

        n = len(window)
        # call_frequency_normalized: fraction of window entries that are this tool
        # (since each window is per-tool, this is always 1.0 within the window —
        # normalized against total_steps instead to reflect real frequency)
        call_frequency = n / max(1, window[-1]["total_steps"])
        call_frequency_normalized = min(call_frequency, 1.0)

        success_rate = sum(1 for obs in window if obs["success"]) / n

        avg_seq_pos = sum(
            obs["sequence_position"] / obs["total_steps"]
            for obs in window
        ) / n

        coords = [tid, call_frequency_normalized, success_rate, avg_seq_pos]
        label = f"tool_{tool_name}"
        confidence = min(0.3 + 0.05 * n, 0.9)

        self._store.upsert_node("toolpath", coords, label, confidence)

    # ------------------------------------------------------------------
    # Session cleanup
    # ------------------------------------------------------------------

    def clear_session(self, session_id: str) -> None:
        """
        Remove all observation window entries for the given session (Req 4.29).

        Called when a session ends or is reset — ensures tool patterns from one
        session do not bleed into the next.
        """
        keys_to_delete = [
            k for k in self._observation_windows if k[0] == session_id
        ]
        for k in keys_to_delete:
            del self._observation_windows[k]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _detect_os_id() -> float:
    """Map sys.platform to OS_ID constant."""
    p = sys.platform
    if p.startswith("linux"):
        return OS_ID_LINUX
    if p == "darwin":
        return OS_ID_MAC
    if p.startswith("win"):
        return OS_ID_WINDOWS
    return OS_ID_LINUX  # Unknown — default to Linux


def _md5_to_float(label: str) -> float:
    """Deterministically hash a string to [0.0, 1.0] via MD5 modulo 10000."""
    digest = hashlib.md5(label.encode("utf-8")).hexdigest()
    return int(digest, 16) % 10000 / 10000.0

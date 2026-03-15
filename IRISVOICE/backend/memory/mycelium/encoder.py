"""
PathEncoder — converts CoordNode lists into compact token strings for context injection.

Full encoding:  MYCELIUM: space(label):c1,c2,...@access | ... | confidence:0.xx
Minimal encoding: MC: space:c1,c2,... | ...

Both formats target ≤ 18 tokens for a 6-space path (Req 6.7).
"""

import re
from typing import List

from .store import CoordNode
from .spaces import SPACES

# Pre-built set of valid space_ids for decode_space_hints filtering
_VALID_SPACE_IDS = frozenset(SPACES.keys())


class PathEncoder:
    """
    Encodes a list of CoordNode objects into a compact string for context injection.

    Stateless — all methods are pure functions of their inputs.
    """

    @staticmethod
    def encode(nodes: List[CoordNode]) -> str:
        """
        Encode a node list as a full MYCELIUM: path string (Req 6.1–6.3, 6.6, 6.7).

        Format per node: {space_id}({label}):{c1},{c2},...@{access_count}
        Coordinates rounded to 3 decimal places.
        Final segment: confidence:{avg_confidence:.2f}

        Returns "" for an empty node list.
        """
        if not nodes:
            return ""

        segments: List[str] = []
        for node in nodes:
            coords_str = ",".join(f"{c:.3f}" for c in node.coordinates)
            label = node.label or node.space_id
            segment = f"{node.space_id}({label}):{coords_str}@{node.access_count}"
            segments.append(segment)

        avg_confidence = sum(n.confidence for n in nodes) / len(nodes)
        segments.append(f"confidence:{avg_confidence:.2f}")

        return "MYCELIUM: " + " | ".join(segments)

    @staticmethod
    def encode_minimal(nodes: List[CoordNode]) -> str:
        """
        Encode a node list as a minimal MC: path string (Req 6.4, 6.6).

        Format per node: {space_id}:{c1},{c2},...
        Coordinates rounded to 2 decimal places. No labels, no access counts.

        Returns "" for an empty node list.
        """
        if not nodes:
            return ""

        segments: List[str] = []
        for node in nodes:
            coords_str = ",".join(f"{c:.2f}" for c in node.coordinates)
            segment = f"{node.space_id}:{coords_str}"
            segments.append(segment)

        return "MC: " + " | ".join(segments)

    @staticmethod
    def decode_space_hints(encoding: str) -> List[str]:
        """
        Extract space_ids from any MYCELIUM: or MC: encoded string (Req 6.5).

        Parses both full and minimal formats. Returns [] for empty or
        unrecognised strings.
        """
        if not encoding:
            return []

        encoding = encoding.strip()

        if encoding.startswith("MYCELIUM:"):
            # Full format: space_id(label):coords@count
            body = encoding[len("MYCELIUM:"):].strip()
            candidates = re.findall(r"([a-z_]+)(?:\(|\:)", body)
            return [c for c in candidates if c in _VALID_SPACE_IDS]

        if encoding.startswith("MC:"):
            # Minimal format: space_id:coords
            body = encoding[len("MC:"):].strip()
            candidates = re.findall(r"([a-z_]+):", body)
            return [c for c in candidates if c in _VALID_SPACE_IDS]

        return []

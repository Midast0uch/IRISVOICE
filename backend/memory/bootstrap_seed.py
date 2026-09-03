"""
bootstrap_seed.py — Seed the runtime Mycelium DB with permanent build landmarks.

On first app launch (or when mycelium_landmarks is empty), reads permanent
landmarks from bootstrap/coordinates.db and inserts them into
data/memory.db's mycelium_landmarks table.

This gives the runtime Mycelium graph knowledge of the build history —
what was verified, what failed, what patterns emerged during development.

Called once from main.py lifespan startup, after memory system initializes.
Never raises — all errors are logged and swallowed.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

# ── Path resolution ────────────────────────────────────────────────────────────

def _find_bootstrap_db() -> Optional[str]:
    """
    Find bootstrap/coordinates.db relative to the project root.
    Tries several candidate paths so this works both in dev and Tauri bundle.
    """
    candidates = [
        # Dev: running from IRISVOICE/
        os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "coordinates.db"),
        # Dev: running from repo root
        os.path.join("IRISVOICE", "bootstrap", "coordinates.db"),
        # Tauri bundle: resources adjacent
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "bootstrap", "coordinates.db"),
    ]
    for p in candidates:
        norm = os.path.normpath(p)
        if os.path.isfile(norm):
            return norm
    return None


def _find_memory_db() -> Optional[str]:
    """
    Find data/memory.db relative to the project root.
    """
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "memory.db"),
        os.path.join("IRISVOICE", "data", "memory.db"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "memory.db"),
    ]
    for p in candidates:
        norm = os.path.normpath(p)
        if os.path.isfile(norm):
            return norm
    return None


# ── Seeding logic ──────────────────────────────────────────────────────────────

def seed_mycelium_from_bootstrap(
    bootstrap_db_path: Optional[str] = None,
    memory_db_path: Optional[str] = None,
) -> int:
    """
    Copy permanent landmarks from bootstrap/coordinates.db into
    data/memory.db's mycelium_landmarks table.

    Returns the number of landmarks inserted (0 if already seeded or on error).
    Never raises.
    """
    try:
        bootstrap_path = bootstrap_db_path or _find_bootstrap_db()
        memory_path = memory_db_path or _find_memory_db()

        if not bootstrap_path:
            logger.debug("[BootstrapSeed] bootstrap/coordinates.db not found — skipping seed")
            return 0
        if not memory_path:
            logger.debug("[BootstrapSeed] data/memory.db not found — skipping seed")
            return 0

        with sqlite3.connect(bootstrap_path) as src:
            src.row_factory = sqlite3.Row
            landmarks = src.execute(
                "SELECT name, description, feature_path, test_command, "
                "       pass_count, session_number, created_at "
                "FROM landmarks WHERE is_permanent = 1"
            ).fetchall()

        if not landmarks:
            logger.debug("[BootstrapSeed] No permanent bootstrap landmarks found")
            return 0

        with sqlite3.connect(memory_db_path or memory_path) as dst:
            dst.row_factory = sqlite3.Row

            # Check if already seeded — skip if any bootstrap landmarks present
            existing = dst.execute(
                "SELECT COUNT(*) FROM mycelium_landmarks "
                "WHERE task_class = 'bootstrap'"
            ).fetchone()[0]

            if existing > 0:
                logger.debug(
                    f"[BootstrapSeed] Already seeded ({existing} bootstrap landmarks present)"
                )
                return 0

            now = time.time()
            inserted = 0
            for lm in landmarks:
                try:
                    lm_id = f"bseed_{lm['name'][:20].replace(' ', '_')}"
                    coordinate_cluster = json.dumps({
                        "feature_path": lm["feature_path"] or "",
                        "test_command": lm["test_command"] or "",
                        "source": "bootstrap",
                    })
                    micro_abstract = json.dumps({
                        "name": lm["name"],
                        "session": lm["session_number"],
                    })

                    dst.execute(
                        """
                        INSERT OR IGNORE INTO mycelium_landmarks (
                            landmark_id, label, task_class,
                            coordinate_cluster, traversal_sequence,
                            cumulative_score, micro_abstract, micro_abstract_text,
                            activation_count, is_permanent,
                            conversation_ref, absorbed,
                            created_at, last_activated
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            lm_id,
                            lm["name"],
                            "bootstrap",
                            coordinate_cluster,
                            json.dumps([]),          # traversal_sequence
                            1.0,                     # cumulative_score — verified
                            micro_abstract,
                            lm["description"] or "",
                            lm["pass_count"] or 1,
                            1,                       # is_permanent
                            "bootstrap_seed",
                            0,                       # not absorbed
                            lm["created_at"] or now,
                            now,
                        ),
                    )
                    inserted += 1
                except Exception as _row_err:
                    logger.debug(f"[BootstrapSeed] Row error for {lm['name']}: {_row_err}")

            dst.commit()

        logger.info(f"[BootstrapSeed] Seeded {inserted} permanent bootstrap landmarks into Mycelium runtime DB")
        return inserted

    except Exception as e:
        logger.warning(f"[BootstrapSeed] Seeding skipped due to error: {e}")
        return 0

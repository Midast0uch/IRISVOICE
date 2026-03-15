"""
Semantic Memory Store for IRIS.

Stores distilled user model, preferences, and learned patterns.
Uses versioned entries for delta-sync across devices (Torus-ready).
"""

import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

# TYPE_CHECKING guard avoids circular import at runtime
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from backend.memory.mycelium.interface import MyceliumInterface

from backend.memory.db import open_encrypted_memory, Connection

logger = logging.getLogger(__name__)


@dataclass
class SemanticEntry:
    """A semantic memory entry."""
    category: str
    key: str
    value: str
    version: int = 1
    confidence: float = 1.0
    source: str = "distillation"
    updated: Optional[str] = None


class SemanticStore:
    """
    Persistent store for semantic/user model data.
    
    Stores:
    - user_preferences: User's stated preferences
    - cognitive_model: How user thinks/works
    - tool_proficiency: User's skill levels with tools
    - domain_knowledge: Topics user knows well
    - named_skills: Crystallised skill patterns
    - failure_patterns: Common failure modes to avoid
    
    All entries are versioned for delta-sync across devices.
    """
    
    # Categories that appear in the startup header
    HEADER_CATEGORIES = [
        "user_preferences",
        "cognitive_model", 
        "tool_proficiency",
        "domain_knowledge",
        "named_skills"
    ]
    
    def __init__(self, db_path: str, biometric_key: bytes):
        """
        Initialize SemanticStore.
        
        Args:
            db_path: Path to the SQLite database file
            biometric_key: 32-byte encryption key
        """
        self.db_path = db_path
        self.biometric_key = biometric_key
        self._db: Optional[Connection] = None

        # Injected by MemoryInterface after both stores are initialized (Task 8.4)
        self._mycelium: Optional[Any] = None

        # Initialize schema on first access
        self._init_schema()
        logger.info("[SemanticStore] Initialized")
    
    @property
    def db(self) -> Connection:
        """Get database connection (lazy initialization)."""
        if self._db is None:
            self._db = open_encrypted_memory(self.db_path, self.biometric_key)
        return self._db
    
    def _init_schema(self) -> None:
        """Initialize database schema for semantic memory."""
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS semantic_entries (
                category   TEXT NOT NULL,
                key        TEXT NOT NULL,
                value      TEXT NOT NULL,
                version    INTEGER DEFAULT 1,
                confidence REAL DEFAULT 1.0,
                source     TEXT DEFAULT 'distillation',
                updated    TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (category, key)
            );
            
            CREATE INDEX IF NOT EXISTS idx_sem_version  ON semantic_entries(version);
            CREATE INDEX IF NOT EXISTS idx_sem_category ON semantic_entries(category);
            CREATE INDEX IF NOT EXISTS idx_sem_source   ON semantic_entries(source);
            
            CREATE TABLE IF NOT EXISTS user_display_memory (
                display_key   TEXT PRIMARY KEY,
                display_name  TEXT NOT NULL,
                internal_ref  TEXT,
                source        TEXT DEFAULT 'auto_learned',
                confidence    REAL DEFAULT 1.0,
                editable      INTEGER DEFAULT 1,
                created       TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self.db.commit()
        logger.debug("[SemanticStore] Schema initialized")
    
    def update(
        self,
        category: str,
        key: str,
        value: str,
        confidence: float = 1.0,
        source: str = "distillation"
    ) -> int:
        """
        Upsert a semantic entry with version increment on conflict.
        
        Args:
            category: Entry category (user_preferences, cognitive_model, etc.)
            key: Entry key
            value: Entry value
            confidence: Confidence level (0.0-1.0)
            source: Source of the entry (distillation, crystallisation, direct)
        
        Returns:
            New version number
        """
        cursor = self.db.execute("""
            INSERT INTO semantic_entries (category, key, value, version, confidence, source)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(category, key) DO UPDATE SET
                value = excluded.value,
                version = semantic_entries.version + 1,
                confidence = excluded.confidence,
                source = excluded.source,
                updated = CURRENT_TIMESTAMP
            RETURNING version
        """, (category, key, value, confidence, source))
        
        row = cursor.fetchone()
        self.db.commit()

        new_version = row[0] if row else 1
        logger.debug(f"[SemanticStore] Updated {category}.{key} -> v{new_version}")

        # Fire-and-forget: flow the updated fact into the coordinate graph (Task 8.4).
        # NEVER let Mycelium errors block a semantic write.
        if self._mycelium is not None:
            try:
                fact_text = f"{category} {key}: {value}"
                self._mycelium.ingest_statement(fact_text)
            except Exception as _exc:  # noqa: BLE001
                logger.debug("[SemanticStore] ingest_statement failed (non-fatal): %s", _exc)

        return new_version
    
    def get(self, category: str, key: str) -> Optional[SemanticEntry]:
        """
        Retrieve a semantic entry.
        
        Args:
            category: Entry category
            key: Entry key
        
        Returns:
            SemanticEntry or None if not found
        """
        row = self.db.execute("""
            SELECT category, key, value, version, confidence, source, updated
            FROM semantic_entries
            WHERE category = ? AND key = ?
        """, (category, key)).fetchone()
        
        if row is None:
            return None
        
        return SemanticEntry(
            category=row[0],
            key=row[1],
            value=row[2],
            version=row[3],
            confidence=row[4],
            source=row[5],
            updated=row[6]
        )
    
    def delete(self, category: str, key: str) -> bool:
        """
        Delete a semantic entry.
        
        Args:
            category: Entry category
            key: Entry key
        
        Returns:
            True if deleted, False if not found
        """
        cursor = self.db.execute("""
            DELETE FROM semantic_entries
            WHERE category = ? AND key = ?
        """, (category, key))
        
        self.db.commit()
        deleted = cursor.rowcount > 0
        
        if deleted:
            logger.debug(f"[SemanticStore] Deleted {category}.{key}")
        
        return deleted
    
    def get_by_category(self, category: str) -> List[SemanticEntry]:
        """
        Retrieve all entries in a category.
        
        Args:
            category: Entry category
        
        Returns:
            List of SemanticEntry objects
        """
        rows = self.db.execute("""
            SELECT category, key, value, version, confidence, source, updated
            FROM semantic_entries
            WHERE category = ?
            ORDER BY key
        """, (category,)).fetchall()
        
        return [
            SemanticEntry(
                category=row[0],
                key=row[1],
                value=row[2],
                version=row[3],
                confidence=row[4],
                source=row[5],
                updated=row[6]
            )
            for row in rows
        ]
    
    def get_startup_header(self) -> str:
        """
        Assemble semantic header for prompt injection.
        
        Returns:
            Formatted header string with user model data
        """
        parts = ["USER PROFILE:"]
        
        for category in self.HEADER_CATEGORIES:
            entries = self.get_by_category(category)
            if entries:
                # Format category name
                category_display = category.replace('_', ' ').title()
                parts.append(f"\n{category_display}:")
                
                for entry in entries:
                    # Only include high-confidence entries in header
                    if entry.confidence >= 0.5:
                        parts.append(f"  - {entry.key}: {entry.value}")
        
        header = "\n".join(parts)
        logger.debug(f"[SemanticStore] Generated header ({len(header)} chars)")
        return header
    
    def get_delta_since_version(self, since_version: int) -> List[Dict[str, Any]]:
        """
        Get all entries with version > since_version for device sync.
        
        TORUS: Used for delta-sync across user's devices.
        
        Args:
            since_version: Version number to sync from
        
        Returns:
            List of entry dictionaries ordered by version
        """
        rows = self.db.execute("""
            SELECT category, key, value, version, confidence, source, updated
            FROM semantic_entries
            WHERE version > ?
            ORDER BY version ASC
        """, (since_version,)).fetchall()
        
        return [
            {
                "category": row[0],
                "key": row[1],
                "value": row[2],
                "version": row[3],
                "confidence": row[4],
                "source": row[5],
                "updated": row[6]
            }
            for row in rows
        ]
    
    def get_max_version(self) -> int:
        """
        Get the highest version number for sync checkpoint.
        
        Returns:
            Maximum version number (0 if no entries)
        """
        row = self.db.execute("""
            SELECT COALESCE(MAX(version), 0) FROM semantic_entries
        """).fetchone()
        
        return row[0] if row else 0
    
    def update_user_display(
        self,
        key: str,
        display_name: str,
        source: str = "auto_learned",
        editable: bool = True
    ) -> None:
        """
        Update a user-facing memory entry.
        
        These are the entries shown in the "IRIS remembers" UI panel.
        
        Args:
            key: Internal reference key (e.g., "user_preferences.response_length")
            display_name: Human-readable description (e.g., "Prefers concise answers")
            source: Source of the entry (auto_learned, user_set)
            editable: Whether user can edit this entry
        """
        self.db.execute("""
            INSERT INTO user_display_memory (display_key, display_name, internal_ref, source, editable)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(display_key) DO UPDATE SET
                display_name = excluded.display_name,
                source = excluded.source,
                editable = excluded.editable
        """, (key, display_name, key, source, int(editable)))
        
        self.db.commit()
        logger.debug(f"[SemanticStore] Updated display entry: {key}")
    
    def get_display_entries(self) -> List[Dict[str, Any]]:
        """
        Get all user-facing memory entries for UI display.
        
        Returns:
            List of display entry dictionaries
        """
        rows = self.db.execute("""
            SELECT display_key, display_name, internal_ref, source, confidence, editable, created
            FROM user_display_memory
            ORDER BY created DESC
        """).fetchall()
        
        return [
            {
                "key": row[0],
                "display_name": row[1],
                "internal_ref": row[2],
                "source": row[3],
                "confidence": row[4],
                "editable": bool(row[5]),
                "created": row[6]
            }
            for row in rows
        ]
    
    def delete_display_entry(self, key: str) -> bool:
        """
        Delete a user-facing memory entry.
        
        Called from UI 'forget' action.
        
        Args:
            key: Display entry key
        
        Returns:
            True if deleted, False if not found
        """
        cursor = self.db.execute("""
            DELETE FROM user_display_memory
            WHERE display_key = ?
        """, (key,))
        
        self.db.commit()
        deleted = cursor.rowcount > 0
        
        if deleted:
            logger.debug(f"[SemanticStore] Deleted display entry: {key}")
        
        return deleted
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get semantic memory statistics.
        
        Returns:
            Dictionary with statistics
        """
        # Count by category
        cat_rows = self.db.execute("""
            SELECT category, COUNT(*) FROM semantic_entries
            GROUP BY category
        """).fetchall()
        
        category_counts = {row[0]: row[1] for row in cat_rows}
        
        # Total entries and max version
        total_row = self.db.execute("""
            SELECT COUNT(*), COALESCE(MAX(version), 0), AVG(confidence)
            FROM semantic_entries
        """).fetchone()
        
        # Display entries count
        display_row = self.db.execute("""
            SELECT COUNT(*) FROM user_display_memory
        """).fetchone()
        
        return {
            "total_entries": total_row[0],
            "max_version": total_row[1],
            "avg_confidence": round(total_row[2] or 0, 3),
            "category_counts": category_counts,
            "display_entries": display_row[0]
        }

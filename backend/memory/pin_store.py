"""
PinStore — CRUD service for Primordial Information Nodes (PiNs).

A PiN is any knowledge artifact anchored to IRIS memory: a markdown note, a
file/folder reference, an image, a URL, an architectural decision, or a
mid-write checkpoint. Pins act as both:

  1. Wiki-style knowledge anchors (linked via mycelium_pin_links to landmarks,
     episodes, other pins) — the agent and user can navigate them as a graph.

  2. Recall anchors — surfaced by the recall decoder via <recall pin .../> ops
     when the agent reasons over a related task.

  3. Checkpoints — special pin_type='checkpoint' anchors written mid-file-write
     when context pressure rises, so the agent can reconstruct its work on a
     subsequent turn even after the original context is pruned.

The store reads/writes the mycelium_pins and mycelium_pin_links tables that
already exist in coordinates.db (defined in backend/memory/db.py:308).
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.memory.db import Connection

logger = logging.getLogger(__name__)


# Search-ranking weights — defaults from mcm/actions/search.json.
# Override per-store-instance via constructor or per-call via search(weights=...).
DEFAULT_SEARCH_WEIGHTS: Dict[str, float] = {
    "title":         50.0,
    "content":       30.0,
    "tags":          20.0,
    "file_refs":     15.0,
    "context_overlap": 10.0,
}


# Pin types — informal vocabulary, not enforced by the SQL schema.
PIN_TYPES = (
    "note", "file", "folder", "image", "doc", "url",
    "decision", "fragment", "checkpoint",
)


@dataclass
class Pin:
    """A primordial information node."""
    pin_id:       str
    title:        str
    pin_type:     str = "note"
    content:      str = ""
    tags:         List[str] = field(default_factory=list)
    file_refs:    List[str] = field(default_factory=list)
    image_refs:   List[str] = field(default_factory=list)
    url_refs:     List[str] = field(default_factory=list)
    project_id:   Optional[str] = None
    origin_id:    Optional[str] = None
    created_at:   float = 0.0
    updated_at:   float = 0.0
    is_permanent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pin_id": self.pin_id, "title": self.title, "pin_type": self.pin_type,
            "content": self.content, "tags": list(self.tags),
            "file_refs": list(self.file_refs), "image_refs": list(self.image_refs),
            "url_refs": list(self.url_refs),
            "project_id": self.project_id, "origin_id": self.origin_id,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "is_permanent": bool(self.is_permanent),
        }

    def to_markdown(self) -> str:
        """Render the pin as a self-contained Markdown block."""
        lines = [f"## {self.title}", ""]
        if self.pin_type != "note":
            lines.append(f"_type: `{self.pin_type}`_")
        if self.tags:
            lines.append(f"_tags: {', '.join(f'`{t}`' for t in self.tags)}_")
        if self.file_refs:
            lines.append(f"_files: {', '.join(f'`{f}`' for f in self.file_refs)}_")
        if self.image_refs:
            lines.append(f"_images: {', '.join(self.image_refs)}_")
        if self.url_refs:
            lines.append(f"_urls: {', '.join(self.url_refs)}_")
        if any([self.tags, self.file_refs, self.image_refs, self.url_refs,
                self.pin_type != "note"]):
            lines.append("")
        if self.content:
            lines.append(self.content)
        return "\n".join(lines)


def _row_to_pin(row: Sequence[Any]) -> Pin:
    """Convert a SELECT * row from mycelium_pins into a Pin dataclass."""
    return Pin(
        pin_id=row[0], title=row[1], pin_type=row[2] or "note",
        content=row[3] or "",
        tags=json.loads(row[4] or "[]"),
        file_refs=json.loads(row[5] or "[]"),
        image_refs=json.loads(row[6] or "[]"),
        url_refs=json.loads(row[7] or "[]"),
        project_id=row[8], origin_id=row[9],
        created_at=row[10] or 0.0, updated_at=row[11] or 0.0,
        is_permanent=bool(row[12] or 0),
    )


_PIN_COLS = (
    "pin_id, title, pin_type, content, tags, file_refs, image_refs, url_refs, "
    "project_id, origin_id, created_at, updated_at, is_permanent"
)


class PinStore:
    """
    CRUD operations on the mycelium_pins table.

    Args:
        conn:          sqlite3 connection (or sqlcipher3) — usually shared with
                       the rest of the memory layer via backend.memory.db.
        origin_id:     UUID of the local instance — stamped onto every pin we create.
        search_weights: override DEFAULT_SEARCH_WEIGHTS for ranked search.
        on_write:      optional callback invoked after every successful add/update/delete
                       — used by the recall decoder to clear its cache.
    """

    def __init__(
        self,
        conn: Connection,
        origin_id: Optional[str] = None,
        search_weights: Optional[Dict[str, float]] = None,
        on_write: Optional[Any] = None,
    ) -> None:
        self._conn = conn
        self._origin_id = origin_id
        self._weights = dict(DEFAULT_SEARCH_WEIGHTS)
        if search_weights:
            self._weights.update(search_weights)
        self._on_write = on_write

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def add(
        self,
        title: str,
        content: str = "",
        pin_type: str = "note",
        tags: Optional[Sequence[str]] = None,
        file_refs: Optional[Sequence[str]] = None,
        image_refs: Optional[Sequence[str]] = None,
        url_refs: Optional[Sequence[str]] = None,
        project_id: Optional[str] = None,
        is_permanent: bool = False,
    ) -> str:
        """Create a new pin. Returns pin_id."""
        pin_id = str(uuid.uuid4())
        now = time.time()
        self._conn.execute(
            f"INSERT INTO mycelium_pins ({_PIN_COLS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pin_id, title, pin_type, content,
                json.dumps(list(tags or [])),
                json.dumps(list(file_refs or [])),
                json.dumps(list(image_refs or [])),
                json.dumps(list(url_refs or [])),
                project_id, self._origin_id, now, now, 1 if is_permanent else 0,
            ),
        )
        self._conn.commit()
        self._notify_write()
        logger.debug("[PinStore] add pin_id=%s title=%r type=%s", pin_id, title, pin_type)
        return pin_id

    def update(self, pin_id: str, **fields: Any) -> bool:
        """Update an existing pin by ID. Returns True if a row was updated."""
        if not fields:
            return False

        json_cols = {"tags", "file_refs", "image_refs", "url_refs"}
        allowed = {
            "title", "pin_type", "content", "tags", "file_refs", "image_refs",
            "url_refs", "project_id", "is_permanent",
        }
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k} = ?")
            if k in json_cols:
                vals.append(json.dumps(list(v or [])))
            elif k == "is_permanent":
                vals.append(1 if v else 0)
            else:
                vals.append(v)
        if not sets:
            return False

        sets.append("updated_at = ?")
        vals.append(time.time())
        vals.append(pin_id)

        cur = self._conn.execute(
            f"UPDATE mycelium_pins SET {', '.join(sets)} WHERE pin_id = ?", vals,
        )
        self._conn.commit()
        if cur.rowcount > 0:
            self._notify_write()
            return True
        return False

    def delete(self, pin_id: str) -> bool:
        """Delete a pin and all of its links. Returns True if a row was removed."""
        cur = self._conn.execute("DELETE FROM mycelium_pins WHERE pin_id = ?", (pin_id,))
        self._conn.execute(
            "DELETE FROM mycelium_pin_links "
            "WHERE (source_type='pin' AND source_id=?) "
            "OR (target_type='pin' AND target_id=?)",
            (pin_id, pin_id),
        )
        self._conn.commit()
        if cur.rowcount > 0:
            self._notify_write()
            return True
        return False

    def link(
        self,
        source_id: str,
        target_id: str,
        relationship: str = "related_to",
        source_type: str = "pin",
        target_type: str = "pin",
        weight: float = 1.0,
    ) -> int:
        """Link a pin to another pin/landmark/episode/node. Returns link_id."""
        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO mycelium_pin_links "
            "(source_type, source_id, target_type, target_id, relationship, weight, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source_type, source_id, target_type, target_id, relationship, weight, now),
        )
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def checkpoint(
        self,
        file_path: str,
        offset: int,
        summary_md: str,
        content_snapshot: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> str:
        """
        Create a mid-file-write checkpoint pin.

        Writes pin_type='checkpoint' with:
          - title: 'checkpoint:<file_path>@<offset>'
          - content: markdown summary + optional fenced snapshot
          - file_refs: [file_path]
          - tags: ['checkpoint', 'auto']

        The next session can recover the in-progress write by emitting
        <recall pin file='<file_path>'/> — the decoder returns all checkpoints
        for that file in chronological order.
        """
        title = f"checkpoint:{file_path}@{offset}"
        body_parts = [f"**Checkpoint summary**\n\n{summary_md.strip()}"]
        if content_snapshot:
            # Truncate snapshots to keep the table light; the agent rarely needs
            # more than the tail to re-derive context.
            snip = content_snapshot[-2048:]
            body_parts.append(f"\n**Last bytes ({len(snip)} chars):**\n\n```\n{snip}\n```")
        content = "\n".join(body_parts)
        return self.add(
            title=title,
            content=content,
            pin_type="checkpoint",
            tags=["checkpoint", "auto"],
            file_refs=[file_path],
            project_id=project_id,
        )

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get(self, pin_id: str) -> Optional[Pin]:
        row = self._conn.execute(
            f"SELECT {_PIN_COLS} FROM mycelium_pins WHERE pin_id = ?", (pin_id,),
        ).fetchone()
        return _row_to_pin(row) if row else None

    def get_by_title(self, title: str) -> Optional[Pin]:
        """Exact-title lookup — used by <recall pin='Title'/> form."""
        row = self._conn.execute(
            f"SELECT {_PIN_COLS} FROM mycelium_pins WHERE title = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (title,),
        ).fetchone()
        return _row_to_pin(row) if row else None

    def list(
        self,
        project_id: Optional[str] = None,
        pin_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Pin]:
        clauses, vals = [], []
        if project_id is not None:
            clauses.append("project_id = ?")
            vals.append(project_id)
        if pin_type is not None:
            clauses.append("pin_type = ?")
            vals.append(pin_type)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        vals.append(limit)
        rows = self._conn.execute(
            f"SELECT {_PIN_COLS} FROM mycelium_pins{where} "
            "ORDER BY updated_at DESC LIMIT ?",
            vals,
        ).fetchall()
        return [_row_to_pin(r) for r in rows]

    def list_checkpoints_for_file(self, file_path: str, limit: int = 20) -> List[Pin]:
        """Return all checkpoint pins for a given file path in chronological order."""
        rows = self._conn.execute(
            f"SELECT {_PIN_COLS} FROM mycelium_pins "
            "WHERE pin_type = 'checkpoint' "
            "AND file_refs LIKE ? "
            "ORDER BY created_at ASC LIMIT ?",
            (f'%"{file_path}"%', limit),
        ).fetchall()
        return [_row_to_pin(r) for r in rows]

    def search(
        self,
        query: str,
        limit: int = 10,
        types: Optional[Sequence[str]] = None,
        project_id: Optional[str] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> List[Tuple[Pin, float]]:
        """
        Ranked search across pin title/content/tags/file_refs.

        Returns a list of (Pin, score) tuples ordered by descending score.
        Scoring weights are tunable; defaults from DEFAULT_SEARCH_WEIGHTS.
        Search is case-insensitive substring matching — fast on small/medium DBs,
        no FTS dependency. Upgrade to FTS5 only if pin counts exceed ~10k.
        """
        if not query:
            return []
        q = query.lower().strip()
        active_weights = dict(self._weights)
        if weights:
            active_weights.update(weights)

        clauses, vals = [], []
        if types:
            placeholders = ",".join("?" * len(types))
            clauses.append(f"pin_type IN ({placeholders})")
            vals.extend(types)
        if project_id is not None:
            clauses.append("project_id = ?")
            vals.append(project_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

        rows = self._conn.execute(
            f"SELECT {_PIN_COLS} FROM mycelium_pins{where}", vals,
        ).fetchall()

        scored: List[Tuple[Pin, float]] = []
        for row in rows:
            pin = _row_to_pin(row)
            score = self._score_pin(pin, q, active_weights)
            if score > 0:
                scored.append((pin, score))

        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:limit]

    @staticmethod
    def _score_pin(pin: Pin, q_lower: str, weights: Dict[str, float]) -> float:
        score = 0.0
        if q_lower in pin.title.lower():
            score += weights.get("title", 0.0)
        if q_lower in (pin.content or "").lower():
            score += weights.get("content", 0.0)
        if any(q_lower in t.lower() for t in pin.tags):
            score += weights.get("tags", 0.0)
        if any(q_lower in f.lower() for f in pin.file_refs):
            score += weights.get("file_refs", 0.0)
        return score

    def linked(
        self,
        pin_id: str,
        relationship: Optional[str] = None,
        depth: int = 1,
    ) -> List[Pin]:
        """
        Return pins reachable from this pin via mycelium_pin_links.

        depth=1 returns direct neighbours; higher values traverse transitively.
        """
        seen, frontier, results = {pin_id}, [pin_id], []
        for _ in range(max(1, depth)):
            if not frontier:
                break
            placeholders = ",".join("?" * len(frontier))
            clauses = [
                f"((source_type='pin' AND source_id IN ({placeholders})) "
                f"OR (target_type='pin' AND target_id IN ({placeholders})))",
            ]
            vals = list(frontier) + list(frontier)
            if relationship:
                clauses.append("relationship = ?")
                vals.append(relationship)
            link_rows = self._conn.execute(
                "SELECT source_id, target_id FROM mycelium_pin_links "
                f"WHERE {' AND '.join(clauses)}",
                vals,
            ).fetchall()
            next_frontier = []
            for src, tgt in link_rows:
                for cand in (src, tgt):
                    if cand not in seen:
                        seen.add(cand)
                        next_frontier.append(cand)
            for nid in next_frontier:
                pin = self.get(nid)
                if pin is not None:
                    results.append(pin)
            frontier = next_frontier
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _notify_write(self) -> None:
        if self._on_write is not None:
            try:
                self._on_write()
            except Exception as exc:
                logger.debug("[PinStore] on_write callback failed: %s", exc)

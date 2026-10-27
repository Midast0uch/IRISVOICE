"""
SpaceRegistry — the coordinate spaces as an OPEN registry (W10, Kyudo proposal 6).

MEMORY-INTERFACE Part II §5.2, §10 (W10), §12.2 #6, §12.3. The
``mycelium_spaces`` table is the source of truth. Each row declares the terms
of one space: its WRITE LOCK (the lowest HyphaChannel allowed to write it —
separate from the context-window zones that decide where a profile section
enters the prompt), decay rate, confidence floor, render order, resonance,
task classes and subagent writers. Everything that was a hard-coded list of the
seven spaces (condense/expand order, render order, resonance spaces, task
classes, the CellWall write permissions) is DERIVED from one registry object,
loaded once when MyceliumInterface starts.

Seeding: the definitions in spaces.SPACES create rows that do not exist yet
(INSERT OR IGNORE). A row that exists is never overwritten — a human edit of
the table survives a restart. The only write to an existing row is the one-time
fill of a row that PREDATES these columns (write_lock IS NULL), and a NULL
description. axes / dtype / value_range are never rewritten: stored node
coordinates are bound to that geometry.

FAIL CLOSED: a space the registry does not know needs SYSTEM to write; a NULL
write lock is SYSTEM; a channel that is None or not a HyphaChannel value counts
as UNTRUSTED.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

from backend.memory.db import app_flush, app_write
from .spaces import (
    DEFAULT_CONFIDENCE_FLOOR,
    DEFAULT_DECAY_RATE,
    SPACES,
    CoordinateSpace,
)

logger = logging.getLogger(__name__)

# HyphaChannel bounds (kyudo.HyphaChannel: UNTRUSTED 0 .. SYSTEM 4).
_UNTRUSTED = 0
_SYSTEM = 4

_COLUMNS = (
    ("write_lock", "INTEGER"),
    ("decay_rate", "REAL"),
    ("confidence_floor", "REAL"),
    ("render_order", "INTEGER"),
    ("position", "INTEGER"),
    ("resonance", "INTEGER"),
    ("task_classes", "TEXT"),
    ("writers", "TEXT"),
)
_TERM_NAMES = tuple(name for name, _ in _COLUMNS)


def ensure_space_columns(conn: Any) -> None:
    """Idempotent ALTERs for the Kyudo terms. Run by db.py Block 5 on the
    application store, and by seed_spaces for a store built from an older
    schema copy."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mycelium_spaces)")}
    if not cols:
        return
    for column, sql_type in _COLUMNS:
        if column not in cols:
            conn.execute(f"ALTER TABLE mycelium_spaces ADD COLUMN {column} {sql_type}")
            logger.info("[spaces] mycelium_spaces ALTER added column %s", column)


def _terms(space: CoordinateSpace) -> tuple:
    """The Kyudo terms of a definition, in _COLUMNS order, as table values."""
    return (
        int(space.write_lock),
        float(space.decay_rate),
        float(space.confidence_floor),
        space.render_order,
        space.position,
        1 if space.resonance else 0,
        json.dumps(list(space.task_classes)),
        json.dumps(list(space.writers)),
    )


def seed_spaces(conn: Any) -> None:
    """Create the rows of the code definitions that do not exist yet. Never
    overwrites a row that exists (see the module docstring)."""
    ensure_space_columns(conn)
    app_flush()
    existing = {
        r[0]: (r[1], r[2])
        for r in conn.execute("SELECT space_id, write_lock, description FROM mycelium_spaces")
    }
    for space_id, space in SPACES.items():
        if space_id not in existing:
            app_write(
                conn,
                "INSERT OR IGNORE INTO mycelium_spaces "
                "(space_id, axes, dtype, value_range, description, active, "
                + ", ".join(_TERM_NAMES) + ") VALUES (?, ?, ?, ?, ?, 1, "
                + ", ".join("?" for _ in _TERM_NAMES) + ")",
                (
                    space_id, json.dumps(space.axes), space.dtype,
                    json.dumps(list(space.value_range)), space.description, *_terms(space),
                ),
            )
            continue
        write_lock, description = existing[space_id]
        if write_lock is None:
            # The row predates the columns (a declared lock is never NULL): give
            # it the seed terms once. After this it is a normal row.
            app_write(
                conn,
                "UPDATE mycelium_spaces SET "
                + ", ".join(f"{n} = ?" for n in _TERM_NAMES)
                + " WHERE space_id = ? AND write_lock IS NULL",
                (*_terms(space), space_id),
            )
        if not description:
            app_write(
                conn,
                "UPDATE mycelium_spaces SET description = ? "
                "WHERE space_id = ? AND (description IS NULL OR description = '')",
                (space.description, space_id),
            )


def _json_list(raw: Any, space_id: str, column: str) -> Tuple[str, ...]:
    if raw is None or raw == "":
        return ()
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return tuple(str(v) for v in value)
    except (TypeError, ValueError):
        pass
    logger.warning("[spaces] space=%s column=%s is not a JSON list: %r", space_id, column, raw)
    return ()


def _row_to_space(row: Mapping[str, Any]) -> CoordinateSpace:
    """One table row as a definition. A NULL / unreadable term takes the FAIL
    CLOSED default (SYSTEM lock, never rendered, no resonance, no task class)."""
    space_id = row["space_id"]
    try:
        axes = list(json.loads(row["axes"]))
    except (TypeError, ValueError):
        axes = []
    try:
        lo, hi = json.loads(row["value_range"])
        value_range = (float(lo), float(hi))
    except (TypeError, ValueError):
        value_range = (0.0, 1.0)
    kwargs: Dict[str, Any] = {}
    if row["write_lock"] is not None:
        kwargs["write_lock"] = int(row["write_lock"])
    if row["decay_rate"] is not None:
        kwargs["decay_rate"] = float(row["decay_rate"])
    if row["confidence_floor"] is not None:
        kwargs["confidence_floor"] = float(row["confidence_floor"])
    return CoordinateSpace(
        space_id=space_id,
        axes=axes,
        dtype=row["dtype"] or "float",
        value_range=value_range,
        description=row["description"] or "",
        render_order=row["render_order"],
        position=row["position"],
        resonance=bool(row["resonance"]),
        task_classes=_json_list(row["task_classes"], space_id, "task_classes"),
        writers=_json_list(row["writers"], space_id, "writers"),
        **kwargs,
    )


def _channel_value(channel: Any) -> int:
    """A channel as a HyphaChannel value; None or an unknown value is UNTRUSTED."""
    try:
        value = int(channel)
    except (TypeError, ValueError):
        return _UNTRUSTED
    return value if _UNTRUSTED <= value <= _SYSTEM else _UNTRUSTED


class SpaceRegistry:
    """The spaces and their Kyudo terms, immutable once built. The order of
    ``ids`` is the fixed order of the condense and expand passes (Req 7.10):
    by ``position``, then row order; a space with no position goes last."""

    def __init__(self, spaces: Iterable[CoordinateSpace]) -> None:
        ordered = sorted(spaces, key=lambda s: (s.position is None, s.position or 0))
        self._spaces: Dict[str, CoordinateSpace] = {s.space_id: s for s in ordered}
        # Derived once: callers read these inside loops. Read-only by contract.
        self._render_order: Dict[str, int] = {
            s.space_id: s.render_order for s in self._spaces.values()
            if s.render_order is not None
        }
        self._resonance: FrozenSet[str] = frozenset(
            s.space_id for s in self._spaces.values() if s.resonance
        )

    # -- construction --------------------------------------------------------

    @classmethod
    def from_seed(cls) -> "SpaceRegistry":
        """The code definitions only: for a store that is not backed by the table."""
        return cls(SPACES.values())

    @classmethod
    def load(cls, conn: Any) -> "SpaceRegistry":
        """Seed what is missing, then read the table. A table that cannot be read
        degrades to the code definitions and says so (never silently)."""
        try:
            seed_spaces(conn)
            app_flush()
            cur = conn.execute(
                "SELECT space_id, axes, dtype, value_range, description, "
                + ", ".join(_TERM_NAMES) + " FROM mycelium_spaces ORDER BY rowid"
            )
            names = [d[0] for d in cur.description]
            spaces = [_row_to_space(dict(zip(names, r))) for r in cur.fetchall()]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[spaces] registry load failed, using the code definitions: %s", exc)
            return cls.from_seed()
        if not spaces:
            logger.warning("[spaces] mycelium_spaces is empty, using the code definitions")
            return cls.from_seed()
        return cls(spaces)

    # -- the spaces ----------------------------------------------------------

    @property
    def ids(self) -> Tuple[str, ...]:
        return tuple(self._spaces)

    def __contains__(self, space_id: object) -> bool:
        return space_id in self._spaces

    def __iter__(self):
        return iter(self._spaces)

    def get(self, space_id: str) -> Optional[CoordinateSpace]:
        return self._spaces.get(space_id)

    # -- Kyudo: the write lock ----------------------------------------------

    def write_lock(self, space_id: str) -> int:
        """Lowest HyphaChannel value that may write ``space_id``; SYSTEM when the
        space is unknown (fail closed)."""
        space = self._spaces.get(space_id)
        return _SYSTEM if space is None else space.write_lock

    def can_write(self, channel: Any, space_id: str) -> bool:
        return _channel_value(channel) >= self.write_lock(space_id)

    def writers(self, space_id: str) -> Tuple[str, ...]:
        """Subagent profiles that may write ``space_id`` (declared; the write
        path does not enforce them yet — MEMORY-INTERFACE Part II §12.2 #5)."""
        space = self._spaces.get(space_id)
        return () if space is None else space.writers

    # -- the law: decay ------------------------------------------------------

    def decay_rate(self, space_id: str) -> float:
        space = self._spaces.get(space_id)
        return DEFAULT_DECAY_RATE if space is None else space.decay_rate

    def confidence_floor(self, space_id: str) -> float:
        space = self._spaces.get(space_id)
        return DEFAULT_CONFIDENCE_FLOOR if space is None else space.confidence_floor

    def edge_rate_override(self, space_id: str) -> Optional[float]:
        """The rate at which the EDGES out of ``space_id`` decay, or None when
        they keep their stored per-edge rate. A space that is never rendered is
        behavioural (what the tools did): its edges follow the space's rate, as
        toolpath's always did. Every other space keeps the stored rate."""
        space = self._spaces.get(space_id)
        if space is None or space.render_order is not None:
            return None
        return space.decay_rate

    # -- derived lists -------------------------------------------------------

    @property
    def render_order(self) -> Dict[str, int]:
        """space_id -> position in the profile; a space with no position is never rendered."""
        return self._render_order

    @property
    def resonance_spaces(self) -> FrozenSet[str]:
        return self._resonance

    def spaces_for_class(self, task_class: str) -> List[str]:
        """The spaces a task class navigates, in registry order."""
        return [s.space_id for s in self._spaces.values() if task_class in s.task_classes]

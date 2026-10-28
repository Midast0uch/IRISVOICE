"""Exact words in memory: an FTS5 index over chunk text (REQ-3, Wave 3).

Recall was meaning-only: a file path, an error string or a name was found only
if the embedding happened to place it near the query. Measured 2026-10-27:
``sqlite_master`` held no FTS or virtual table; keyword lookup was a B-tree scan
plus Python token overlap.

The index uses SQLite's own FTS5 (no new dependency, owner rule) as an EXTERNAL
CONTENT table: the text is not copied, the index points at ``context_chunks``
by rowid. Triggers keep it in step with every write, including the native
one-writer path, so there is no second writer to forget. A store that predates
the index is backfilled with one ``'rebuild'`` command on a lane at first open.

Failure is never fatal (AC4): a missing or broken index makes ``search`` return
an empty list, and the caller recalls by meaning alone. Every miss is counted.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from backend.memory.db import app_write

logger = logging.getLogger(__name__)

COUNTERS: Dict[str, int] = {
    "queries": 0,        # FTS recalls attempted
    "hits": 0,           # FTS recalls that returned at least one row
    "missing": 0,        # index absent (the store predates it or the build failed)
    "error": 0,          # MATCH/IO error - recall continued by meaning
    "literal_queries": 0,  # queries that carried a literal (path/name/flag)
    "backfill_started": 0,
    "backfill_done": 0,
}

# Candidate rows the keyword rank may add to the union (T11). Small on purpose:
# the exact scorer is still the judge, and the token cap is downstream.
KEYWORD_CANDIDATES = 50
RRF_K = 60               # standard reciprocal-rank constant

# ── HOW A QUERY BECOMES A MATCH (measured 2026-10-28) ────────────────────────
# bm25 cannot rank a chunk that carries a term ONCE against thousands that carry
# it many times: tf is identical for every carrier of the query's own token, the
# length penalty leans towards short rows, and the source row settled around the
# 90th percentile of its carrier list (measured: 1604 of 1708 for "test_roman.py",
# 2257 of 2494 for "main.py"). Two strategies were measured on the live store and
# REJECTED: per-term candidate budgets (strict 0.475 -> 0.400/0.500, 12x the
# queries) and bm25 with b=0 (0.525 at a 500-row pool). The fetch changed instead:
# a literal ("main.py", "IRIS_TURN_START_RECALL=0") is matched as a PHRASE, which
# cuts the carrier set from ~32,000 ("py" alone) to 2,494 and is 10x faster
# (0.65 ms vs 8.3 ms). Plain words still OR together.
_ATOM = re.compile(r"\w{2,}", re.UNICODE)
# The literal DECISION uses 1-char runs too: "IRIS_TURN_START_RECALL=0" splits
# into iris..recall + "0", and "v2.0" into v2 + "0". Dropping the short run would
# hide the very punctuation that makes those spans literals.
_SPAN_ATOM = re.compile(r"\w+", re.UNICODE)

# Function words carry no recall signal and they DOMINATE the cost: "the" alone
# is in 93,695 of 108,314 rows (86%), so a 12-atom OR spends most of its time
# scoring rows that merely say "the". Measured 2026-10-28 on the live store:
# dropping this set took the keyword leg 179 -> 6.7 ms, 147 -> 9.5 ms,
# 90.7 -> 2.5 ms on prose queries. A cap on the remaining CONTENT atoms was
# measured and is NOT needed (7-8 content atoms cost 11-17 ms) and it lost up
# to 34% of the result set, so there is no cap here. Literal phrases never pass
# through this set: a phrase must keep every atom its span had.
_STOPWORDS = frozenset("""
a an the and or but if then than that this these those of in on at to for from by with without
is are was were be been being do does did doing have has had having i you he she it we they me my your
our their what which who whom why how when where there here not no yes so such as into about over under
again further can could should would will shall may might must just also very more most other some any
each every
""".split())
# Punctuation that makes one whitespace-free span a LITERAL candidate.
_LITERAL_PUNCT = re.compile(r"[._/\\:\-=@#$%~^&*+!?;,'\"()\[\]{}<>|]")

MAX_QUERY_CHARS = 2000   # a 10k query must not reach the parser
MAX_ATOMS = 12           # terms per MATCH expression
MAX_LITERALS = 4         # phrases per MATCH expression


def _atoms(text: str, limit: int = MAX_ATOMS) -> List[str]:
    """Word runs, lowercased, deduped, capped. ``\\w`` is unicode-aware.

    The previous ASCII pattern ``[A-Za-z0-9_]{2,}`` cut "café" into "caf" and
    "naïve" into "na" + "ve" - terms that match thousands of unrelated rows and
    never match the diacritic-folded text the index actually holds.
    """
    out: List[str] = []
    for m in _ATOM.finditer((text or "")[:MAX_QUERY_CHARS]):
        a = m.group(0).lower()
        if a not in out:
            out.append(a)
            if len(out) >= limit:
                break
    return out


def _terms(text: str, limit: int = MAX_ATOMS) -> List[str]:
    """Query terms for MATCH. Kept under this name: callers and benches use it."""
    return _atoms(text, limit)


def _content_atoms(text: str, limit: int = MAX_ATOMS) -> List[str]:
    """Atoms for the broad pass: stopwords removed, but never empty.

    A query made only of function words ("what is it") keeps them, because an
    empty MATCH would turn a question into no keyword candidates at all.
    """
    atoms = _atoms(text, limit)
    kept = [a for a in atoms if a not in _STOPWORDS]
    return kept or atoms


def _plan(query: str) -> tuple[List[str], List[str]]:
    """(literal phrases, atoms) for one query.

    A literal is one whitespace-free span that carries punctuation AND still
    splits into two or more atoms ("main.py" -> "main py"; a trailing "." on a
    plain word leaves one atom and is NOT a literal). Every piece is quoted and
    built from unicode word runs only, so quotes, ``*``, NEAR, OR, AND, ``^``,
    ``:`` and SQL fragments cannot reach the FTS parser as operators.

    The returned atoms are the BROAD pass's atoms: stopwords already removed.
    """
    q = (query or "")[:MAX_QUERY_CHARS]
    phrases: List[str] = []
    for span in q.split():
        if not _LITERAL_PUNCT.search(span):
            continue
        parts: List[str] = []
        for m in _SPAN_ATOM.finditer(span):
            a = m.group(0).lower()
            if a not in parts:
                parts.append(a)
        if len(parts) < 2:
            continue
        phrase = '"%s"' % " ".join(parts)
        if phrase not in phrases:
            phrases.append(phrase)
        if len(phrases) >= MAX_LITERALS:
            break
    return phrases, _content_atoms(q)


def _where(conn, session_id, chunk_types, zones) -> tuple[str, List[object]]:
    """The shared filter tail for both matches, plus its params."""
    sql: List[str] = []
    params: List[object] = []
    # REQ-4 AC2: a folded near-duplicate is not a candidate. The probe keeps a
    # store that predates the column working (meaning only, no error counted).
    try:
        if "folded_into" in {r[1] for r in conn.execute("PRAGMA table_info(context_chunks)")}:
            sql.append("AND context_chunks.folded_into IS NULL")
    except Exception:  # noqa: BLE001 - the filter is an optimisation, not a gate
        pass
    if session_id:
        sql.append("AND context_chunks.session_id = ?")
        params.append(session_id)
    if chunk_types:
        sql.append("AND context_chunks.chunk_type IN (%s)" % ",".join("?" * len(chunk_types)))
        params.extend(chunk_types)
    if zones:
        sql.append("AND context_chunks.zone IN (%s)" % ",".join("?" * len(zones)))
        params.extend(zones)
    return " ".join(sql), params


def _rows(conn, match: str, where: str, params: List[object], limit: int) -> List[int]:
    sql = (
        "SELECT context_chunks_fts.rowid FROM context_chunks_fts "
        "JOIN context_chunks ON context_chunks.rowid = context_chunks_fts.rowid "
        "WHERE context_chunks_fts MATCH ? %s "
        "ORDER BY bm25(context_chunks_fts) LIMIT ?" % where
    )
    return [int(r[0]) for r in conn.execute(sql, [match] + params + [int(limit)]).fetchall()]


def ensure_schema(conn) -> bool:
    """Create the index and its triggers when absent. False = FTS unavailable.

    Cheap on an existing store (``IF NOT EXISTS``). Never raises: a store
    without FTS must still open and recall by meaning (AC4).
    """
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS context_chunks_fts USING fts5("
            "content, content='context_chunks', content_rowid='rowid')"
        )
        conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS context_chunks_fts_ai
            AFTER INSERT ON context_chunks BEGIN
                INSERT INTO context_chunks_fts(rowid, content)
                VALUES (new.rowid, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS context_chunks_fts_ad
            AFTER DELETE ON context_chunks BEGIN
                INSERT INTO context_chunks_fts(context_chunks_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
            END;
            CREATE TRIGGER IF NOT EXISTS context_chunks_fts_au
            AFTER UPDATE OF content ON context_chunks BEGIN
                INSERT INTO context_chunks_fts(context_chunks_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
                INSERT INTO context_chunks_fts(rowid, content)
                VALUES (new.rowid, new.content);
            END;
            """
        )
        return True
    except Exception as exc:  # noqa: BLE001 - a broken FTS must not block recall
        logger.warning("[chunk_fts] schema unavailable: %s", exc)
        return False


def counts(conn) -> tuple[int, int]:
    """(indexed rows, chunk rows). Never raises; (-1, -1) on failure.

    ``SELECT count(*) FROM context_chunks_fts`` is served by the CONTENT table
    for an external-content table, so it reports every chunk even when the
    index is EMPTY (measured 2026-10-27: a brand-new index read as 146,973,
    which would have told the boot path "no backfill needed" forever). The
    ``_docsize`` shadow table holds one row per INDEXED document - that is the
    number that decides whether a backfill is needed.
    """
    try:
        return (
            int(conn.execute(
                "SELECT count(*) FROM context_chunks_fts_docsize").fetchone()[0]),
            int(conn.execute("SELECT count(*) FROM context_chunks").fetchone()[0]),
        )
    except Exception:
        return -1, -1


def backfill(conn) -> int:
    """Fill the index from the content table with ONE rebuild command.

    Runs on a lane at first open. The command is transactional: an interrupted
    rebuild leaves the index empty, and the next open tries again.
    """
    COUNTERS["backfill_started"] += 1
    try:
        from backend.memory.db import app_flush

        app_write(conn, "INSERT INTO context_chunks_fts(context_chunks_fts) VALUES('rebuild')")
        # The rebuild is queued on the one writer: read it back only after it
        # lands, or the count reports the index BEFORE the rebuild.
        drained = app_flush(60.0)
        indexed, total = counts(conn) if drained else (-1, -1)
        COUNTERS["backfill_done"] += 1
        logger.info("[chunk_fts] backfilled rows=%d of %d drained=%s", indexed, total, drained)
        return max(indexed, 0)
    except Exception as exc:  # noqa: BLE001 - recall stays meaning-only
        COUNTERS["error"] += 1
        logger.warning("[chunk_fts] backfill failed (recall stays meaning-only): %s", exc)
        return 0


def search(conn, query: str, *, session_id: Optional[str] = None,
           chunk_types: Optional[List[str]] = None, zones: Optional[List[str]] = None,
           limit: int = KEYWORD_CANDIDATES) -> List[int]:
    """Rowids ranked by FTS5 bm25 within the same filter. [] when unavailable.

    The literal pass runs first: if the query names a path, a file or a flag, the
    rows that carry that literal fill the candidate budget before any plain word
    is allowed to flood it. The plain-word pass tops up only when the literal pass
    did not fill the budget, so a query with no literal pays for one query and a
    query whose literal is rare keeps its precision.
    """
    phrases, atoms = _plan(query)
    if not phrases and not atoms:
        return []
    COUNTERS["queries"] += 1
    try:
        where, params = _where(conn, session_id, chunk_types, zones)
        rows: List[int] = []
        if phrases:
            COUNTERS["literal_queries"] += 1
            rows = _rows(conn, " OR ".join(phrases), where, params, limit)
        if len(rows) < limit and atoms:
            seen = set(rows)
            for rid in _rows(conn, " OR ".join('"%s"' % a for a in atoms), where, params, limit):
                if rid not in seen:
                    seen.add(rid)
                    rows.append(rid)
                if len(rows) >= limit:
                    break
    except Exception as exc:  # noqa: BLE001 - AC4: meaning only, counted
        COUNTERS["missing" if "no such table" in str(exc).lower() else "error"] += 1
        logger.debug("[chunk_fts] keyword recall skipped: %s", exc)
        return []
    if rows:
        COUNTERS["hits"] += 1
    return rows


def fuse_by_rank(meaning: List[int], keyword: List[int], k: int = RRF_K) -> List[int]:
    """Reciprocal rank fusion of the two candidate lists (AC2).

    Fuses RANK, never raw score: bm25 and cosine are not comparable. The result
    is the union ordered by fused rank; the caller still scores every row
    exactly, so this changes WHICH rows are considered, not how they rank.
    """
    if not keyword:
        return list(meaning)
    if not meaning:
        return list(keyword)
    score: Dict[int, float] = {}
    for rows in (meaning, keyword):
        for rank, rid in enumerate(rows, 1):
            score[rid] = score.get(rid, 0.0) + 1.0 / (k + rank)
    return sorted(score, key=score.get, reverse=True)

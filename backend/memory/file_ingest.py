"""File recall (REQ-9): a file becomes a node in the graph plus chunks in the store.

Why this shape (see design.md "File recall (REQ-9)"):
  * identity  -> `file_nodes` (file_path UNIQUE already dedups by path)
  * payload   -> `context_chunks` through `EpisodicStore.fragment_and_store`, so the
                 chunking, the 0.92 dedup, the int8 + fingerprint compression and the
                 FTS triggers all apply with no second write path
  * change    -> new chunks, old ones FOLDED (`folded_into`), never deleted
  * failure   -> the node is still written (reference-only) and the reason is counted

W1 extracts UTF-8 text with the standard library only. PDF/DOCX/XLSX, OCR and
transcription plug into `_EXTRACTORS` as named extractors later (REQ-9 Waves).
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from backend.memory.db import app_write, owns_store

logger = logging.getLogger(__name__)

CHUNK_TYPE = "file"
ZONE_DEFAULT = "trusted"          # the user handed us the file: the user's own channel
PER_FILE_CAP = 5 * 1024 * 1024    # owner, 2026-10-28: 5 MB per file
TOTAL_BUDGET = 100 * 1024 * 1024  # owner, 2026-10-28: ~100 MB of file text

# Counters are read by the bench (REQ-9 AC8); nothing here is silent.
COUNTERS: Dict[str, int] = {
    "ingested": 0, "unchanged": 0, "failed": 0, "truncated": 0, "chunks": 0, "folded": 0,
    "evicted": 0, "too_short": 0,
}

_LANGUAGE = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".jsx": "jsx", ".rs": "rust", ".go": "go", ".java": "java", ".c": "c",
    ".h": "c", ".cpp": "cpp", ".cs": "csharp", ".rb": "ruby", ".php": "php",
    ".sh": "shell", ".ps1": "powershell", ".sql": "sql", ".md": "markdown",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".csv": "csv", ".txt": "text", ".log": "text", ".html": "html", ".css": "css",
}

# Extensions that are certainly binary and have no extractor in W1. Listing them
# (instead of refusing every unknown extension) lets a `.env` or `Makefile` in.
_BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff",
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".mp4", ".mov", ".mkv", ".webm",
    ".zip", ".gz", ".7z", ".rar", ".tar", ".exe", ".dll", ".so", ".dylib",
    ".db", ".sqlite", ".bin", ".pyc", ".woff", ".woff2", ".ttf",
}


class ExtractionError(Exception):
    """A file whose text cannot be produced in this wave."""


def ensure_schema(conn) -> None:
    """Make the node table usable, then add REQ-9's two columns (idempotent).

    The live app store already carries `file_nodes` (inherited from the build
    graph, 5,246 rows), so both steps are no-ops there. A FRESH store (tests,
    a new install) has no such table, and the module must not depend on one
    existing: this creates only the columns this module reads and writes.
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS file_nodes (
             file_id     TEXT PRIMARY KEY,
             file_path   TEXT UNIQUE NOT NULL,
             language    TEXT,
             last_edited REAL,
             created_at  REAL NOT NULL,
             content_hash TEXT,
             file_size   INTEGER
           )"""
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(file_nodes)").fetchall()}
    for name, decl in (("content_hash", "TEXT"), ("file_size", "INTEGER")):
        if name not in cols:
            conn.execute(f"ALTER TABLE file_nodes ADD COLUMN {name} {decl}")


def extract_text(data: bytes, path: str) -> Tuple[str, bool]:
    """Decoded text and whether the source was cut. Raises `ExtractionError`."""
    ext = Path(path).suffix.lower()
    extractor = _EXT_EXTRACTORS.get(ext)
    if extractor is not None:
        try:
            return extractor(data, path)
        except Exception as exc:  # noqa: BLE001 - a bad file is a counted failure
            raise ExtractionError(f"{ext} extraction failed: {exc}") from exc
    if ext in _BINARY_EXT:
        raise ExtractionError(f"no extractor for {ext}")
    if b"\x00" in data[:8192]:
        raise ExtractionError("binary content")
    try:
        return data.decode("utf-8-sig"), False
    except UnicodeDecodeError:
        # A text file in another encoding is still text: replace, don't refuse.
        return data.decode("utf-8", errors="replace"), False


def _extract_pdf(data: bytes, path: str) -> Tuple[str, bool]:
    import io

    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(data))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(p.strip() for p in pages if p.strip()), False


def _extract_docx(data: bytes, path: str) -> Tuple[str, bool]:
    import io

    import docx

    document = docx.Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts), False


def _extract_xlsx(data: bytes, path: str) -> Tuple[str, bool]:
    import io

    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts = []
    try:
        for sheet in book.worksheets:
            parts.append(f"# sheet: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    parts.append(" | ".join(cells))
    finally:
        book.close()
    return "\n".join(parts), False


# extension -> extractor(data, path) -> text. One entry per format; no registry class.
_EXT_EXTRACTORS: Dict[str, Callable[[bytes, str], Tuple[str, bool]]] = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".xlsx": _extract_xlsx,
}

# REQ-9 W4 (2026-10-31): audio and video become text through ffmpeg + faster-whisper.
# Both are checked on first use: a missing binary or model is a counted
# ExtractionError (the node is still written as a reference), never a crash.
_MEDIA_EXT = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
    ".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v",
}
_WHISPER_MODEL = None


def _whisper():
    """The process-wide Whisper model (loaded once; downloads on first use)."""
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        from faster_whisper import WhisperModel

        _WHISPER_MODEL = WhisperModel(
            os.environ.get("IRIS_WHISPER_MODEL", "base"),
            device="cpu",
            compute_type="int8",
        )
        logger.info("[file_ingest] Whisper model loaded (%s)",
                    os.environ.get("IRIS_WHISPER_MODEL", "base"))
    return _WHISPER_MODEL


def _extract_media(data: bytes, path: str) -> Tuple[str, bool]:
    """Decode to 16 kHz mono with ffmpeg, then transcribe with faster-whisper."""
    import subprocess
    import tempfile

    suffix = Path(path).suffix.lower() or ".bin"
    with tempfile.TemporaryDirectory(prefix="iris-media-") as tmp:
        src = os.path.join(tmp, "source" + suffix)
        wav = os.path.join(tmp, "audio.wav")
        with open(src, "wb") as handle:
            handle.write(data)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                 "-ac", "1", "-ar", "16000", wav],
                check=True, capture_output=True, timeout=900,
            )
        except FileNotFoundError as exc:
            raise ExtractionError("ffmpeg is not installed") from exc
        except subprocess.CalledProcessError as exc:
            raise ExtractionError(f"ffmpeg could not decode {suffix}") from exc
        segments, _info = _whisper().transcribe(wav, vad_filter=True, beam_size=1)
        text = " ".join(s.text.strip() for s in segments if s.text.strip())
    return text, False


for _ext in _MEDIA_EXT:
    _EXT_EXTRACTORS[_ext] = _extract_media

# REQ-9 W3 (2026-10-31): images (screenshots, scans) become text. RapidOCR runs
# on the onnxruntime already installed for the decision engine, so there is no
# system binary and no extra service. A missing/broken engine is a counted
# ExtractionError like every other extractor.
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
_OCR_ENGINE = None


def _ocr():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
        logger.info("[file_ingest] OCR engine loaded (RapidOCR)")
    return _OCR_ENGINE


def _extract_image(data: bytes, path: str) -> Tuple[str, bool]:
    import io

    import numpy as np
    from PIL import Image

    image = Image.open(io.BytesIO(data)).convert("RGB")
    result, _elapsed = _ocr()(np.array(image))
    lines = [str(line[1]) for line in (result or []) if len(line) > 1]
    return "\n".join(line.strip() for line in lines if line.strip()), False


for _ext in _IMAGE_EXT:
    _EXT_EXTRACTORS[_ext] = _extract_image


def _write(conn, sql: str, params=()) -> None:
    """One writer (REQ-9 AC2): the native writer when we own the store."""
    if owns_store(conn):
        app_write(conn, sql, params)
    else:
        conn.execute(sql, params)


def ingest(store, path: str, *, session_id: Optional[str] = None,
           zone: str = ZONE_DEFAULT, force: bool = False) -> dict:
    """Ingest one file. Returns a report dict; never raises for a bad file.

    `store` is an EpisodicStore (it owns the chunk writer and the connection).
    """
    conn = store.db
    resolved = str(Path(path).expanduser().resolve())
    report = {"path": resolved, "chunks": 0, "folded": 0, "bytes": 0,
              "truncated": False, "status": "ok", "reason": ""}

    try:
        st = os.stat(resolved)
        if not os.path.isfile(resolved):
            raise ExtractionError("not a regular file")
    except (OSError, ExtractionError) as exc:
        COUNTERS["failed"] += 1
        logger.warning("[file_ingest] stat failed path=%s err=%r", resolved, exc)
        report.update(status="failed", reason=f"stat: {exc}")
        return report

    try:
        with open(resolved, "rb") as fh:
            raw = fh.read(PER_FILE_CAP + 1)
    except OSError as exc:
        COUNTERS["failed"] += 1
        logger.warning("[file_ingest] read failed path=%s err=%r", resolved, exc)
        report.update(status="failed", reason=f"read: {exc}")
        return report

    truncated = len(raw) > PER_FILE_CAP
    if truncated:
        raw = raw[:PER_FILE_CAP]
        COUNTERS["truncated"] += 1
        logger.warning("[file_ingest] truncated path=%s cap=%d", resolved, PER_FILE_CAP)
    report.update(bytes=len(raw), truncated=truncated)

    digest = hashlib.sha256(raw).hexdigest()
    try:
        ensure_schema(conn)
    except Exception as exc:  # DDL failure must not lose the text
        logger.warning("[file_ingest] ensure_schema failed err=%r", exc)

    row = conn.execute(
        "SELECT content_hash, file_size FROM file_nodes WHERE file_path = ?", (resolved,)
    ).fetchone()
    if not force and row and row[0] == digest and row[1] == st.st_size:
        COUNTERS["unchanged"] += 1
        report["status"] = "unchanged"
        return report

    try:
        text, _ = extract_text(raw, resolved)
    except ExtractionError as exc:
        # REQ-9 AC5: reference-only node, counted, never silent.
        _upsert_node(conn, resolved, digest, st.st_size, st.st_mtime)
        COUNTERS["failed"] += 1
        logger.warning("[file_ingest] extraction failed path=%s reason=%s", resolved, exc)
        report.update(status="failed", reason=str(exc))
        return report

    _upsert_node(conn, resolved, digest, st.st_size, st.st_mtime)

    if not text.strip():
        COUNTERS["failed"] += 1
        report.update(status="failed", reason="empty text")
        return report

    # REQ-9 AC6: int8 + fingerprint only; the bench proves delta 0.0 for every type.
    ids = store.fragment_and_store(
        text,
        session_id or f"file:{digest[:16]}",
        chunk_type=CHUNK_TYPE,
        zone=zone,
        tool_name=resolved,
        keep_float=False,
    )
    report["chunks"] = len(ids)
    COUNTERS["chunks"] += len(ids)

    if not ids:
        # A file whose text is under the chunk floor stores no row. Never report
        # that as a quiet success: name it and count it (REQ-9 AC5 spirit).
        COUNTERS["too_short"] += 1
        report.update(status="too_short", reason="text below the chunk floor")
        logger.info("[file_ingest] too_short path=%s chars=%d", resolved, len(text))
        return report

    if ids:
        report["folded"] = _fold_previous(conn, resolved, ids[0], ids)
        COUNTERS["folded"] += report["folded"]
    COUNTERS["ingested"] += 1
    logger.info("[file_ingest] path=%s chunks=%d folded=%d bytes=%d truncated=%s",
                resolved, len(ids), report["folded"], len(raw), truncated)
    return report


def _upsert_node(conn, resolved: str, digest: str, size: int, mtime: float) -> None:
    lang = _LANGUAGE.get(Path(resolved).suffix.lower())
    _write(
        conn,
        """INSERT INTO file_nodes
             (file_id, file_path, language, last_edited, created_at, content_hash, file_size)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(file_path) DO UPDATE SET
             last_edited = excluded.last_edited,
             content_hash = excluded.content_hash,
             file_size = excluded.file_size,
             language = COALESCE(file_nodes.language, excluded.language)""",
        (uuid.uuid4().hex, resolved, lang, mtime, time.time(), digest, size),
    )


def _fold_previous(conn, resolved: str, head_id: str, keep_ids: list) -> int:
    """Fold the chunks of the superseded version into the new head (REQ-9 AC3).

    `keep_ids` are the rows this ingest JUST wrote. They must be excluded, or the
    fold eats its own version - found on the live store 2026-10-28: a 26-chunk
    ingest folded 25 of its own chunks and only one stayed reachable.
    """
    marks = ",".join("?" for _ in keep_ids)
    stale = conn.execute(
        f"""SELECT id FROM context_chunks
            WHERE chunk_type = ? AND tool_name = ? AND folded_into IS NULL
              AND id NOT IN ({marks})""",
        (CHUNK_TYPE, resolved, *keep_ids),
    ).fetchall()
    if not stale:
        return 0
    old_marks = ",".join("?" for _ in stale)
    _write(
        conn,
        f"""UPDATE context_chunks SET folded_into = ?
            WHERE chunk_type = ? AND tool_name = ? AND folded_into IS NULL
              AND id IN ({old_marks})""",
        (head_id, CHUNK_TYPE, resolved, *[r[0] for r in stale]),
    )
    return len(stale)


def stored_text_bytes(conn) -> int:
    """Bytes of file text currently live (REQ-9 AC7 budget read, bench-facing)."""
    row = conn.execute(
        """SELECT COALESCE(SUM(LENGTH(content)), 0) FROM context_chunks
           WHERE chunk_type = ? AND folded_into IS NULL""",
        (CHUNK_TYPE,),
    ).fetchone()
    return int(row[0] or 0)


def prune_to_budget(conn, keep_bytes: Optional[int] = None) -> int:
    """REQ-9 AC7 cold tier: the filesystem is the storage for file text.

    A file's chunks can be REBUILT from disk while the file's hash still matches,
    so they are a cache, not an archive. Over the budget, evict whole files,
    least-recently-touched first, and let `ensure()` bring one back on demand.
    """
    keep = TOTAL_BUDGET if keep_bytes is None else keep_bytes
    total = stored_text_bytes(conn)
    if total <= keep:
        return 0
    removed = 0
    rows = conn.execute(
        """SELECT tool_name, COALESCE(SUM(LENGTH(content)), 0), MAX(timestamp)
           FROM context_chunks WHERE chunk_type = ? AND folded_into IS NULL
           GROUP BY tool_name ORDER BY 3 ASC""", (CHUNK_TYPE,)).fetchall()
    for path, nbytes, _ts in rows:
        if total <= keep:
            break
        if not path:
            continue
        n = conn.execute(
            "SELECT COUNT(*) FROM context_chunks WHERE chunk_type = ? AND tool_name = ?",
            (CHUNK_TYPE, path)).fetchone()[0]
        _write(conn, "DELETE FROM context_chunks WHERE chunk_type = ? AND tool_name = ?",
               (CHUNK_TYPE, path))
        total -= int(nbytes)
        removed += int(n)
        COUNTERS["evicted"] += int(n)
        logger.info("[file_ingest] evicted path=%s chunks=%d (cold tier)", path, n)
    return removed


def ensure(store, path: str, **kwargs) -> dict:
    """Bring a file back from the cold tier: re-ingest when its chunks are gone."""
    resolved = str(Path(path).expanduser().resolve())
    live = store.db.execute(
        """SELECT 1 FROM context_chunks WHERE chunk_type = ? AND tool_name = ?
           AND folded_into IS NULL LIMIT 1""", (CHUNK_TYPE, resolved)).fetchone()
    if live:
        return {"path": resolved, "status": "present", "chunks": 0, "folded": 0}
    return ingest(store, path, force=True, **kwargs)


def report(conn) -> dict:
    """The bench's `files` section (REQ-9 AC8)."""
    rows = conn.execute(
        """SELECT COUNT(*), COALESCE(SUM(folded_into IS NULL), 0) FROM context_chunks
           WHERE chunk_type = ?""",
        (CHUNK_TYPE,),
    ).fetchone()
    nodes = conn.execute("SELECT COUNT(*) FROM file_nodes").fetchone()[0]
    return {
        "nodes": int(nodes),
        "chunks": int(rows[0] or 0),
        "chunks_live": int(rows[1] or 0),
        "text_bytes": stored_text_bytes(conn),
        "budget_bytes": TOTAL_BUDGET,
        "counters": dict(COUNTERS),
    }

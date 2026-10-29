"""REQ-9 W2 (PDF/DOCX/XLSX) and the cold tier (AC7).

  CT-F8   a .docx becomes recallable chunks (paragraphs + table cells)
  CT-F9   an .xlsx becomes recallable chunks (sheet name + rows)
  CT-F10  a corrupt PDF is a COUNTED failure, not a silent empty ingest
  CT-F11  over budget, whole files are evicted and `ensure` rebuilds them
"""
import time

import numpy as np
import pytest

BACKEND = "lfm25-emb-350m"
TEXT = ("Quarterly operations review covering the zebraquux migration window and "
        "the quokka scheduling policy. Every worker holds exactly one lease.")


@pytest.fixture()
def store(tmp_path):
    from backend.memory.embedding import Embedding
    from backend.memory.episodic import EpisodicStore
    from backend.memory import memory_events

    st = EpisodicStore(db_path=str(tmp_path / "memory.db"), biometric_key=b"\0" * 32)
    memory_events.ensure_schema(st.db)

    class _Stub:
        @staticmethod
        def encode_with_meta(text):
            v = np.zeros(1024, dtype=np.float32)
            for i, ch in enumerate(text[:128]):
                v[i % 1024] += (ord(ch) % 89) / 89.0
            n = float(np.linalg.norm(v)) or 1.0
            return Embedding(vector=(v / n).tolist(), backend=BACKEND,
                             chunk_count=1, truncated=False)

    st._embed = _Stub()
    yield st


def _file_chunks(store, path):
    return store.db.execute(
        "SELECT COUNT(*) FROM context_chunks WHERE chunk_type='file' AND tool_name=?",
        (str(path.resolve()),)).fetchone()[0]


def test_ct_f8_docx_is_extracted(store, tmp_path):
    import docx

    from backend.memory import file_ingest

    d = docx.Document()
    d.add_paragraph(TEXT)
    table = d.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "owner"
    table.cell(0, 1).text = "quokka-team"
    f = tmp_path / "report.docx"
    d.save(str(f))

    rep = file_ingest.ingest(store, str(f))
    assert rep["status"] == "ok" and rep["chunks"] >= 1
    body = store.db.execute(
        "SELECT content FROM context_chunks WHERE tool_name=?",
        (str(f.resolve()),)).fetchall()
    assert any("quokka-team" in (r[0] or "") for r in body)


def test_ct_f9_xlsx_is_extracted(store, tmp_path):
    import openpyxl

    from backend.memory import file_ingest

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "budget"
    ws.append(["line", "amount"])
    ws.append(["zebraquux", 42])
    ws.append(["quokka lease renewal", 17])
    ws.append(["migration window closes at the end of the quarter", 9])
    ws.append(["owner", "quokka-team"])
    f = tmp_path / "sheet.xlsx"
    wb.save(str(f))

    rep = file_ingest.ingest(store, str(f))
    assert rep["status"] == "ok" and rep["chunks"] >= 1
    body = store.db.execute(
        "SELECT content FROM context_chunks WHERE tool_name=?",
        (str(f.resolve()),)).fetchall()
    assert any("zebraquux" in (r[0] or "") for r in body)


def test_ct_f10_corrupt_pdf_is_a_counted_failure(store, tmp_path):
    from backend.memory import file_ingest

    f = tmp_path / "broken.pdf"
    f.write_bytes(b"%PDF-1.4 not really a pdf" + b"\x00" * 32)
    before = file_ingest.COUNTERS["failed"]
    rep = file_ingest.ingest(store, str(f))

    assert rep["status"] == "failed" and rep["chunks"] == 0
    assert file_ingest.COUNTERS["failed"] == before + 1
    node = store.db.execute(
        "SELECT content_hash FROM file_nodes WHERE file_path=?",
        (str(f.resolve()),)).fetchone()
    assert node is not None and node[0], "reference-only node must still exist"


def test_ct_f11_cold_tier_evicts_and_ensure_rebuilds(store, tmp_path, monkeypatch):
    from backend.memory import file_ingest

    a = tmp_path / "a.txt"
    a.write_text(TEXT, encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text(TEXT + " second file, same shape, different bytes.", encoding="utf-8")
    file_ingest.ingest(store, str(a))
    file_ingest.ingest(store, str(b))
    total = file_ingest.stored_text_bytes(store.db)
    assert total > 0

    # Budget far below what is stored: everything is evictable, file text is a cache.
    evicted = file_ingest.prune_to_budget(store.db, keep_bytes=1)
    assert evicted > 0
    assert file_ingest.stored_text_bytes(store.db) <= total

    # The node survives (the reference-only record), and ensure() rebuilds the text
    # from disk because the hash still matches.
    back = file_ingest.ensure(store, str(a))
    assert back["status"] == "ok" and back["chunks"] >= 1
    assert _file_chunks(store, a) >= 1

import sqlite3
from pathlib import Path

import fitz

from scripts.literature_inventory import (
    exact_duplicate_groups,
    scan_pdfs,
    write_report,
    write_sqlite,
)


def _make_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 96), text)
    doc.save(str(path))
    doc.close()


def test_inventory_scans_pdfs_and_writes_outputs(tmp_path):
    source = tmp_path / "literature_read"
    output = tmp_path / "literature_library"
    source.mkdir()

    pdf_a = source / "arXiv-2501.17805_Test Paper.pdf"
    pdf_b = source / "duplicate-copy.pdf"
    pdf_c = source / "unique.pdf"
    md = source / "I1.md"

    _make_pdf(pdf_a, "same content")
    pdf_b.write_bytes(pdf_a.read_bytes())
    _make_pdf(pdf_c, "different content")
    md.write_text("# Template extract", encoding="utf-8")

    records = scan_pdfs(source)
    assert len(records) == 3
    assert any(record.arxiv_id == "2501.17805" for record in records)

    duplicate_groups = exact_duplicate_groups(records)
    assert len(duplicate_groups) == 1
    assert len(duplicate_groups[0]["records"]) == 2

    db_path = output / "literature.sqlite"
    report_path = output / "literature_report.md"
    write_sqlite(db_path, source, records)
    write_report(report_path, source, db_path, records)

    assert db_path.exists()
    assert report_path.exists()
    assert "Exact Duplicates" in report_path.read_text(encoding="utf-8")

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM duplicate_groups").fetchone()[0] == 1
    finally:
        conn.close()

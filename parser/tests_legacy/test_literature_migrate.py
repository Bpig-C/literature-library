import sqlite3
from pathlib import Path

import fitz

from scripts.literature_inventory import scan_pdfs, write_sqlite
from scripts.literature_migrate import build_migration_plan, execute_plan


def _make_pdf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 96), text)
    doc.save(str(path))
    doc.close()


def test_migration_plan_copies_canonical_and_skips_template_extracts(tmp_path):
    source = tmp_path / "literature_read"
    library = tmp_path / "literature_library"
    source.mkdir()

    root_pdf = source / "[E1]_Measuring_AI_Ability_Long_Tasks.pdf"
    duplicate_pdf = source / "nested" / "E1.pdf"
    md = source / "[E1]_Measuring_AI_Ability_Long_Tasks.md"

    _make_pdf(root_pdf, "same content")
    duplicate_pdf.parent.mkdir()
    duplicate_pdf.write_bytes(root_pdf.read_bytes())
    md.write_text("# Existing template extract", encoding="utf-8")

    records = scan_pdfs(source)
    db_path = library / "literature.sqlite"
    write_sqlite(db_path, source, records)

    plan = build_migration_plan(db_path, source, library, strict_decisions=False)

    assert plan.summary()["works"] == 1
    assert plan.summary()["source_pdfs_to_copy"] == 1
    assert plan.summary()["exact_duplicates_to_archive"] == 1
    assert plan.summary()["template_extracts_to_skip"] >= 1
    assert plan.copied_sources[0]["original_name"] == root_pdf.name
    assert plan.duplicate_sources[0]["original_name"] == duplicate_pdf.name

    execute_plan(plan, db_path, library)

    copied = Path(plan.copied_sources[0]["library_path"])
    archived = Path(plan.duplicate_sources[0]["archive_path"])
    assert copied.exists()
    assert archived.exists()
    assert not any((library / "works").rglob("parsed/template_extracts/*.md"))
    assert (library / "index.json").exists()
    assert (library / "migration_report.md").exists()


def test_migration_records_code_overrides_and_relations(tmp_path):
    source = tmp_path / "literature_read"
    library = tmp_path / "literature_library"
    source.mkdir()

    _make_pdf(source / "[I4j]_Agentic_Misalignment_Appendix.pdf", "appendix")
    _make_pdf(source / "[I4j]_Alignment_Evaluation_OpenAI_Findings.pdf", "primary")
    _make_pdf(source / "X2_Grok_4_Fast_Model_Card.pdf", "x2 fast")
    _make_pdf(source / "X2_Grok_4_Model_Card.pdf", "x2")
    _make_pdf(source / "X2_Grok_Code_Fast_1_Model_Card.pdf", "x2 code")

    records = scan_pdfs(source)
    db_path = library / "literature.sqlite"
    write_sqlite(db_path, source, records)

    plan = build_migration_plan(db_path, source, library)

    codes = {item["code"] for item in plan.code_overrides}
    assert {"I4j-a", "I4j", "X2a", "X2b", "X2c"} == codes
    assert len(plan.relations) == 1
    assert plan.relations[0]["relation_type"] == "part_of"

    execute_plan(plan, db_path, library)

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM work_codes").fetchone()[0] == 5
        assert conn.execute("SELECT COUNT(*) FROM work_relations").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM library_migration_files").fetchone()[0] == 5
    finally:
        conn.close()

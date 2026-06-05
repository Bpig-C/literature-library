from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.literature_ingest import (
    build_ingest_plan,
    ensure_core_schema,
    execute_plan,
    sha256_file,
)


class LiteratureIngestTests(unittest.TestCase):
    def make_library(self) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "_inbox").mkdir()
        (root / "_duplicates").mkdir()
        (root / "_archive").mkdir()
        (root / "works").mkdir()
        with sqlite3.connect(root / "literature.sqlite") as conn:
            ensure_core_schema(conn)
            conn.commit()
        (root / "index.json").write_text(
            json.dumps(
                {
                    "migration_version": "literature_phase2_v1",
                    "generated_at": "2026-06-04T00:00:00+00:00",
                    "library_root": str(root),
                    "summary": {"works": 0, "active_source_pdfs": 0},
                    "works": [],
                    "relations": [],
                    "title_duplicate_groups": [],
                    "warnings": [],
                }
            ),
            encoding="utf-8",
        )
        (root / "parse_ledger.json").write_text(
            json.dumps({"version": "literature_batch_parse_v1", "runs": {}}),
            encoding="utf-8",
        )
        return root

    def test_execute_ingests_new_pdf_as_pending(self) -> None:
        root = self.make_library()
        pdf = root / "_inbox" / "arXiv-2501.12345-Test Paper 2025.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        plan = build_ingest_plan(root)
        self.assertEqual(plan.summary()["ingests"], 1)
        self.assertEqual(plan.ingests[0].work_id, "W-arxiv-2501.12345")

        execute_plan(plan, no_backup=True)

        library_path = Path(plan.ingests[0].library_path)
        self.assertTrue(library_path.exists())
        self.assertFalse(pdf.exists())
        self.assertTrue(Path(plan.ingests[0].archive_path).exists())

        with sqlite3.connect(root / "literature.sqlite") as conn:
            work = conn.execute("SELECT parse_status FROM works").fetchone()
            source = conn.execute("SELECT content_sha256 FROM source_files").fetchone()
            run = conn.execute("SELECT status FROM literature_parse_runs").fetchone()
        self.assertEqual(work[0], "pending")
        self.assertEqual(source[0], sha256_file(library_path))
        self.assertEqual(run[0], "pending")

        ledger = json.loads((root / "parse_ledger.json").read_text(encoding="utf-8"))
        self.assertEqual(next(iter(ledger["runs"].values()))["status"], "pending")

    def test_exact_duplicate_is_archived_without_new_source(self) -> None:
        root = self.make_library()
        existing = root / "works" / "W-sha-existing" / "source" / "paper.pdf"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"%PDF same")
        digest = sha256_file(existing)
        with sqlite3.connect(root / "literature.sqlite") as conn:
            ensure_core_schema(conn)
            conn.execute(
                """
                INSERT INTO works (id, title, authors, parse_status)
                VALUES (?, ?, ?, ?)
                """,
                ("W-sha-existing", "Paper", "[]", "succeeded"),
            )
            conn.execute(
                """
                INSERT INTO source_files (
                    id, work_id, content_sha256, original_name, source_path,
                    relative_source_path, file_size, file_ext
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "SF-abcabcabcabc-00001",
                    "W-sha-existing",
                    digest,
                    "paper.pdf",
                    str(existing),
                    "works/W-sha-existing/source/paper.pdf",
                    existing.stat().st_size,
                    ".pdf",
                ),
            )
            conn.commit()

        duplicate = root / "_inbox" / "copy.pdf"
        duplicate.write_bytes(b"%PDF same")
        plan = build_ingest_plan(root)
        self.assertEqual(plan.summary()["ingests"], 0)
        self.assertEqual(plan.summary()["exact_duplicates"], 1)

        execute_plan(plan, no_backup=True)
        self.assertFalse(duplicate.exists())
        self.assertTrue(Path(plan.exact_duplicates[0].archive_path).exists())

        with sqlite3.connect(root / "literature.sqlite") as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM source_files").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()

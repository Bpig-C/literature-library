# collector/replace_source.py
"""needs_better_copy: replace a quarantined work's bad source with a good copy.
Net-new (existing restore assumes files still in _quarantine/). Reuses quarantine data
representation: works.read_status + work_codes(code='bad_source'). Does NOT create a new work.
Boundary: may UPDATE works.read_status only (restore); never INSERT/CREATE works.
"""
from __future__ import annotations
import shutil, secrets
from pathlib import Path
from api.db import get_conn
from scripts.literature_ingest import sha256_file

def replace_quarantined_source(work_id: str, good_pdf: Path, *, library_root: Path) -> str:
    """Drop good copy into works/{work_id}/source/, update source_files, restore read_status,
    clear bad_source code, archive old source. Returns new source_file_id."""
    digest = sha256_file(Path(good_pdf))
    dest_dir = Path(library_root) / "works" / work_id / "source"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(good_pdf).name
    shutil.copy2(good_pdf, dest)

    conn = get_conn()
    try:
        # 归档旧 source_files
        conn.execute("UPDATE source_files SET status='archived' WHERE work_id=? AND status='active'",
                     (work_id,))
        # 插入新 source_file
        sf_id = f"SF-{digest[:12]}-{secrets.token_hex(2)}"
        conn.execute(
            """INSERT INTO source_files (id, work_id, content_sha256, source_path,
               relative_source_path, status) VALUES (?,?,?,?,?, 'active')""",
            (sf_id, work_id, digest, str(dest), str(dest.relative_to(library_root))))
        # 恢复 read_status
        conn.execute("UPDATE works SET read_status='unread' WHERE id=?", (work_id,))
        # 清 bad_source code
        conn.execute("DELETE FROM work_codes WHERE work_id=? AND code='bad_source'", (work_id,))
        conn.commit()
    finally:
        conn.close()
    return sf_id

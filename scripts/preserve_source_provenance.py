"""Explicit offline preservation of legacy provenance; never merges old records."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.source_provenance import preserve_legacy


def preserve(database: Path, backup: Path) -> int:
    """Reserve a fresh backup and preserve original rows in one write transaction."""
    database, backup = database.resolve(), backup.resolve()
    if not database.is_file():
        raise ValueError('existing offline catalog required')
    if backup == database:
        raise ValueError('backup must differ from catalog')
    # BEGIN IMMEDIATE blocks writers while the independent reader makes a backup.
    with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            with backup.open('xb'):
                pass
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(backup.as_uri() + '?mode=rw', uri=True)) as target:
                    source.backup(target)
                    if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise ValueError('backup failed quick_check')
            count = preserve_legacy(conn)
            conn.commit()
            return count
        except BaseException:
            conn.rollback()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--backup', type=Path, required=True, help='new backup file; never overwritten')
    parser.add_argument('--apply', action='store_true', help='required; run only against an offline maintenance catalog')
    args = parser.parse_args()
    if not args.apply:
        parser.error('explicit --apply required; stop writers/use authorized maintenance first')
    print(json.dumps({'preserved': preserve(args.database, args.backup), 'backup': str(args.backup.resolve())}))


if __name__ == '__main__':
    main()

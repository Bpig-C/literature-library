"""Preserve committed SQLite state, including WAL, without changing source data.

These are individual database recovery images, NOT a coherent application release.
Use the stopped-writer release workflow for cross-database/filesystem consistency.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def preserve(sources, destination):
    destination = Path(destination).resolve()
    sources = {name: Path(path).resolve(strict=True) for name, path in sources.items()}
    if not sources or any(Path(name).name != name or name in {'.', '..', 'receipt.json'} for name in sources):
        raise ValueError('Distinct plain database filenames required')
    destination.mkdir(parents=True, exist_ok=False)
    receipt = {'format': 'litlib-database-preservation-v1', 'started_at': datetime.now(timezone.utc).isoformat(),
               'scope': 'individual SQLite recovery images; not a full application backup', 'databases': {}}
    for name, source in sources.items():
        target = destination / name
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
            src.execute('PRAGMA query_only=ON')
            src.execute('BEGIN')
            src.execute('SELECT count(*) FROM sqlite_master').fetchone()
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise ValueError('Preservation integrity check failed')
                counts = {}
                for (table,) in dst.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                    quoted = '"' + table.replace('"', '""') + '"'
                    counts[table] = dst.execute('SELECT count(*) FROM ' + quoted).fetchone()[0]
                dst.execute('PRAGMA journal_mode=DELETE')
        receipt['databases'][name] = {'source': str(source), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                                      'bytes': target.stat().st_size, 'counts': counts, 'quick_check': 'ok'}
    receipt['completed_at'] = datetime.now(timezone.utc).isoformat()
    (destination / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--research', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    print(json.dumps(preserve({'literature.sqlite': args.catalog, 'research.sqlite': args.research}, args.destination)))

import json
import sqlite3
from contextlib import closing

import pytest

from api.storage.backup_catalog import run_due, read_catalog
from api.storage.core import Namespace, StorageError
from api.storage.release_control import validate_source, write
from scripts.preserve_databases import preserve
from scripts.snapshot_inputs import refresh


def version(identity, at):
    ns = Namespace('research/agent-loss-of-control/literature/test/manual/')
    sha = identity * 64
    return dict(id=identity, state='verified', verified_at=at, namespace=ns.root,
                manifest_sha256=sha, manifest_key=ns.key(sha), asset_keys=[])


def test_force_bypasses_interval_only_and_still_requires_new_verified_version(tmp_path):
    catalog = tmp_path / 'backups.json'
    old = version('a', '2026-10-22T00:00:00Z')
    write(catalog, dict(format='litlib-backup-catalog-v1', versions=[old], attempts=[]))
    now = '2026-10-22T01:00:00Z'
    assert run_due(catalog, [], lambda: pytest.fail('not due'), now=now)['state'] == 'not_due'
    with pytest.raises(StorageError, match='newly verified'):
        run_due(catalog, [], lambda: old, now=now, force=True)
    def backup():
        new = version('b', now)
        c = read_catalog(catalog)
        c['versions'].append(new)
        write(catalog, c)
        return new
    result = run_due(catalog, [], backup, now=now, force=True)
    assert result['state'] == 'backed_up'
    assert len(read_catalog(catalog)['versions']) == 2
    assert result['retention']['deletion_performed'] is False


def slot(tmp_path):
    root = tmp_path / 'current'
    root.mkdir()
    ns = 'research/agent-loss-of-control/literature/prod/'
    env = {'LITLIB_STORAGE_ROOT': ns, 'LITLIB_DB_PATH': str(root/'data/library/literature.sqlite'),
           'LITLIB_RESEARCH_DB': str(root/'data/research/research.sqlite')}
    (root/'environment.json').write_text(json.dumps(env))
    inputs = dict(namespace=ns, source_root=str(root), catalog=env['LITLIB_DB_PATH'],
                  research=env['LITLIB_RESEARCH_DB'], files={})
    return root, inputs


def test_production_source_guard_rejects_stale_and_mixed_slots(tmp_path, monkeypatch):
    root, inputs = slot(tmp_path)
    for key in ('LITLIB_DB_PATH', 'LITLIB_RESEARCH_DB'):
        monkeypatch.delenv(key, raising=False)
    validate_source(inputs)
    with pytest.raises(StorageError, match='explicit source_root'):
        validate_source({k:v for k,v in inputs.items() if k!='source_root'})
    with pytest.raises(StorageError, match='database differs'):
        validate_source(dict(inputs, catalog=str(tmp_path/'old/literature.sqlite')))
    with pytest.raises(StorageError, match='working file differs'):
        validate_source(dict(inputs, files={'library/docs/USER_ISSUES.md': {'source': str(tmp_path/'old/USER_ISSUES.md')}}))
    monkeypatch.setenv('LITLIB_RESEARCH_DB', str(tmp_path/'actually-running/research.sqlite'))
    with pytest.raises(StorageError, match='applied runtime'):
        validate_source(inputs)


def test_refresh_rehashes_current_material_instead_of_reusing_old_template(tmp_path):
    root, inputs = slot(tmp_path)
    doc = root/'data/library/docs/USER_ISSUES.md'
    doc.parent.mkdir(parents=True)
    doc.write_text('new incident')
    inputs['files'] = {'library/docs/USER_ISSUES.md': {'source': 'stale', 'sha256': 'old', 'bytes': 0}}
    updated = refresh(inputs, root)
    assert updated['files']['library/docs/USER_ISSUES.md']['bytes'] == len('new incident')
    assert updated['files']['library/docs/USER_ISSUES.md']['source'] == str(doc)


def test_preservation_includes_committed_wal_and_refuses_overwrite(tmp_path):
    source = tmp_path/'live.sqlite'
    with closing(sqlite3.connect(source)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE records(id INTEGER PRIMARY KEY)')
        writer.commit()
        writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        writer.execute('INSERT INTO records VALUES (22)')
        writer.commit()
        assert source.with_name(source.name+'-wal').stat().st_size > 0
        receipt = preserve({'research.sqlite': source}, tmp_path/'preserved')
        assert receipt['databases']['research.sqlite']['counts']['records'] == 1
        with closing(sqlite3.connect(tmp_path/'preserved/research.sqlite')) as restored:
            assert restored.execute('SELECT * FROM records').fetchall() == [(22,)]
        with pytest.raises(FileExistsError):
            preserve({'research.sqlite': source}, tmp_path/'preserved')
        assert writer.execute('SELECT * FROM records').fetchall() == [(22,)]

import pytest
from api.storage.backup_catalog import run_due,read_catalog,select
from api.storage.core import StorageError

def test_failed_backup_preserves_successful_catalog(tmp_path):
    catalog=tmp_path/'backups.json'
    def fail():raise StorageError('network_unavailable','synthetic upload failure')
    with pytest.raises(StorageError):run_due(catalog,[],fail,now='2026-10-08T00:00:00Z')
    c=read_catalog(catalog);assert not c['versions'] and c['attempts'][0]['state']=='failed'
    with pytest.raises(StorageError):select(catalog,'unknown')

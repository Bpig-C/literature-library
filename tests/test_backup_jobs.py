import json
import pytest

from api import backup_jobs as jobs
from api.storage.core import StorageError
from api.storage.release_control import write


@pytest.fixture
def controller(tmp_path,monkeypatch):
    monkeypatch.setenv('LITLIB_BACKUP_CONTROL',str(tmp_path))
    monkeypatch.setenv('LITLIB_BACKUP_ADMIN_TOKEN','a'*40)
    return tmp_path


def verified(root):
    value={'id':'fresh','state':'verified','verified_at':jobs.now(),'code_commit':'c'*40,'manifest_sha256':'d'*64}
    write(root/'backup-catalog.json',{'format':'litlib-backup-catalog-v1','versions':[value],'attempts':[]})
    return value


def test_permission_idempotent_request_and_verified_receipt(controller):
    with pytest.raises(StorageError):jobs.authorize('ordinary-user-token')
    jobs.authorize('a'*40)
    first=jobs.enqueue('backup1');assert jobs.enqueue('backup1')==first
    result=jobs.run_one(lambda jid:verified(controller))
    assert result['state']=='succeeded'
    assert jobs.get_job(first['job_id'])['version']['manifest_sha256']=='d'*64
    assert jobs.run_one(lambda jid:pytest.fail('rerun'))['state']=='idle'
    assert jobs.describe()['scheduler_state']=='not_managed'


def test_crash_and_failure_block_automatic_retry(controller):
    first=jobs.enqueue('backup1');first['state']='running';write(jobs.job_path(first['job_id']),first)
    jobs.enqueue('backup2')
    assert jobs.run_one(lambda jid:pytest.fail('unsafe restart'))['state']=='needs_attention'
    with pytest.raises(StorageError):jobs.resolve(first['job_id'],verified_service=False)
    assert jobs.resolve(first['job_id'],verified_service=True)['state']=='failed'
    def fail(jid):raise RuntimeError('private diagnostic secret')
    result=jobs.run_one(fail)
    assert result['state']=='needs_attention' and 'secret' not in json.dumps(result)


def test_unverified_executor_cannot_report_success(controller):
    jobs.enqueue('backup')
    assert jobs.run_one(lambda jid:{'id':'not-in-catalog'})['state']=='needs_attention'
    assert jobs.describe()['latest_verified'] is None


def test_unconfigured_status_does_not_claim_schedule(monkeypatch):
    monkeypatch.delenv('LITLIB_BACKUP_CONTROL',raising=False)
    assert jobs.describe()=={'configured':False,'scheduler_state':'unknown','worker_last_seen':None}

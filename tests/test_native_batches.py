import base64
import json
from dataclasses import replace
from pathlib import Path
import pytest

from api import parse_plans
from api.parse_queue import Queue
from api.storage.core import StorageError,hash_file
from test_async_parse import queue,accept,Driver,run_all
from test_foundation_plans import service


class Native(Driver):
    def __init__(self):
        super().__init__();self.batches={};self.posts=[];self.puts=[];self.queries=[];self.results={};self.interrupt_upload=False
    def create_batch(self,files,language,remember):
        batch='native-'+str(len(self.posts)+1)
        entries=[{'data_id':f['data_id'],'file_name':f['name'],'uploaded':False} for f in files]
        self.batches[batch]=entries;self.posts.append([dict(f) for f in files])
        urls=[f'https://upload.invalid/{batch}/{e["data_id"]}?signature=secret' for e in entries]
        remember(batch,urls)
        return batch
    def upload_file(self,url,pdf):
        batch,data_id=url.split('?')[0].split('/')[-2:]
        entry=next(e for e in self.batches[batch] if e['data_id']==data_id)
        entry['uploaded']=True;self.puts.append(data_id)
        if self.interrupt_upload:self.interrupt_upload=False;raise KeyboardInterrupt('PUT succeeded but response lost')
    def query_batch(self,batch):
        self.queries.append(batch)
        return [dict(data_id=e['data_id'],file_name=e['file_name'],state=self.results.get(e['data_id'],'done') if e['uploaded'] else 'waiting-file',
                     full_zip_url=f'https://result.invalid/{batch}/{e["data_id"]}?signature=private') for e in self.batches[batch]]
    def download_url(self,pdf,out,url,event,maximum):
        data_id=url.split('?')[0].split('/')[-1];self.downloads.append(data_id)
        (out/'content.md').write_text('native fixed result '+data_id,'utf-8')


@pytest.fixture
def native(queue,monkeypatch):
    monkeypatch.setenv('LITLIB_PARSE_UPLOAD_KEY',base64.urlsafe_b64encode(b's'*32).decode())
    queue.initial_limits=replace(queue.initial_limits,upstream=4,batch_size=4)
    return queue


def third_source(q):
    pdf=q.registry.catalog.parent/'3.pdf';pdf.write_bytes(b'%PDF synthetic 3');sha,size=hash_file(pdf)
    with q.registry.conn(write=True) as conn:
        conn.execute("INSERT INTO works VALUES('W3','en','2026-10-22T00:00:00Z','unread','pending','')")
        conn.execute("INSERT INTO source_files VALUES('SF3','W3',?,?,?,'active','2026-10-22T00:00:00Z')",(str(pdf),sha,size))
        conn.execute("INSERT INTO ingest_notes VALUES('R3','W3','SF3','deception','2026-10-22T00:00:00Z')")
    q.service.publish(pdf,identity='SF3',role='pdf',version=1,operation_id='native-pdf3')


def until(q,driver,condition,steps=80):
    for _ in range(steps):
        q.run_one(driver);q.clock.tick()
        if condition():return
    pytest.fail('native scheduler did not reach checkpoint')


def test_true_multifile_batch_partial_results_and_retry_only_failed_file(native):
    q=native;third_source(q);pid=accept(q,items=3,submissions=4);tasks=q.enqueue(pid)['tasks'];driver=Native()
    driver.results[tasks[1]['id']]='running';driver.results[tasks[2]['id']]='failed'
    until(q,driver,lambda:bool(driver.posts))
    assert len(driver.posts)==1 and len(driver.posts[0])==3 and driver.puts==[]
    statuses=[q.status(t['id']) for t in tasks]
    assert {s['producer']['task_id'] for s in statuses}=={'native-1'}
    assert all(s['phase']=='upload' and s['upstream_state']=='waiting-file' for s in statuses)
    assert 'signature' not in json.dumps(statuses)
    with q.registry.conn(read_only=True) as conn:
        mappings=[dict(r) for r in conn.execute('SELECT * FROM parse_cloud_members')]
        assert len(mappings)==3 and all('https://' not in m['upload_cipher'] for m in mappings)
        assert {m['source_file_id'] for m in mappings}=={'SF1','SF2','SF3'}
    until(q,driver,lambda:q.status(tasks[0]['id'])['state']=='succeeded' and q.status(tasks[2]['id'])['state']=='failed')
    assert q.status(tasks[1]['id'])['state']=='waiting'
    assert driver.downloads==[tasks[0]['id']]
    assert set(driver.queries)=={'native-1'}
    q.action(tasks[2]['id'],'resume','Retry only the provider-confirmed failed file')
    driver.results[tasks[2]['id']]='done';driver.results[tasks[1]['id']]='done'
    completed=run_all(q,driver,pid)
    assert completed['action']=='complete' and completed['budget']['reserved_submissions']==4
    assert [len(files) for files in driver.posts]==[3,1]
    assert driver.posts[1][0]['data_id']==tasks[2]['id']
    assert len(q.status(tasks[2]['id'])['cloud_history'])==2
    assert all(q.status(t['id'])['producer']['version']==1 for t in tasks)


def test_restart_after_batch_id_reuses_encrypted_links_without_another_post(native):
    q=native;pid=accept(q);tasks=q.enqueue(pid)['tasks'];driver=Native()
    until(q,driver,lambda:bool(driver.posts))
    restarted=Queue(q.service,q.authority,clock=q.clock)
    assert run_all(restarted,driver,pid)['action']=='complete'
    assert len(driver.posts)==1 and sorted(driver.puts)==sorted(t['id'] for t in tasks)


def test_interrupted_put_is_queried_before_uploading_again(native):
    q=native;pid=accept(q);tasks=q.enqueue(pid)['tasks'];driver=Native()
    until(q,driver,lambda:bool(driver.posts));driver.interrupt_upload=True
    with pytest.raises(KeyboardInterrupt):q.run_one(driver)
    q.clock.tick(20)
    assert run_all(q,driver,pid)['action']=='complete'
    assert len(driver.posts)==1 and len(driver.puts)==len(set(driver.puts))==2


def test_wrong_upload_key_preserves_batch_and_never_resubmits(native,monkeypatch):
    q=native;pid=accept(q,source_ids=['SF1']);task=q.enqueue(pid)['tasks'][0];driver=Native()
    until(q,driver,lambda:bool(driver.posts))
    monkeypatch.setenv('LITLIB_PARSE_UPLOAD_KEY',base64.urlsafe_b64encode(b'other-key'.ljust(32,b'x')).decode())
    assert q.run_one(driver)['state']=='inspection_required'
    assert len(driver.posts)==1 and driver.puts==[]
    monkeypatch.setenv('LITLIB_PARSE_UPLOAD_KEY',base64.urlsafe_b64encode(b's'*32).decode())
    q.action(task['id'],'resume','Correct upload key restored; query original batch')
    assert run_all(q,driver,pid)['action']=='complete' and len(driver.posts)==1


def test_language_compatibility_and_short_tail_batches(native):
    q=native
    with q.registry.conn(write=True) as conn:conn.execute("UPDATE works SET language='zh' WHERE id='W2'")
    pid=accept(q);q.enqueue(pid);driver=Native()
    assert run_all(q,driver,pid)['action']=='complete'
    assert [len(files) for files in driver.posts]==[1,1]  # no waiting to fill a batch


def test_native_mapping_rejects_wrong_file_without_failing_other_members(native):
    q=native;pid=accept(q);tasks=q.enqueue(pid)['tasks']
    class WrongFile(Native):
        def query_batch(self,batch):
            entries=super().query_batch(batch)
            for entry in entries:
                if entry['data_id']==tasks[0]['id']:entry['file_name']='other-source.pdf'
            return entries
    driver=WrongFile()
    result=run_all(q,driver,pid)
    assert {t['state'] for t in result['tasks']}=={'inspection_required','succeeded'}
    assert driver.downloads==[tasks[1]['id']]


def test_successful_put_can_remain_waiting_file_without_duplicate_upload(native):
    q=native;pid=accept(q,source_ids=['SF1']);task=q.enqueue(pid)['tasks'][0]
    class Lagging(Native):
        def query_batch(self,batch):
            entries=super().query_batch(batch)
            if len(self.queries)==1:
                for e in entries:e['state']='waiting-file'
            return entries
    driver=Lagging()
    assert run_all(q,driver,pid)['action']=='complete'
    assert len(driver.posts)==len(driver.puts)==1 and len(driver.queries)>=2


def test_archiving_one_source_during_post_preserves_other_members_batch_ids(native):
    q=native;pid=accept(q);tasks=q.enqueue(pid)['tasks']
    class ArchiveDuringPost(Native):
        def create_batch(self,files,language,remember):
            with q.tx() as conn:conn.execute("UPDATE works SET read_status='archived' WHERE id='W1'")
            return super().create_batch(files,language,remember)
    driver=ArchiveDuringPost();result=run_all(q,driver,pid)
    assert {t['state'] for t in result['tasks']}=={'inspection_required','succeeded'}
    assert {q.status(t['id'])['producer']['task_id'] for t in tasks}=={'native-1'}
    assert driver.puts==[tasks[1]['id']]

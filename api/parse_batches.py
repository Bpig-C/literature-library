"""Native MinerU batches over existing per-Source jobs and fenced leases.

Batch creation and querying are grouped; upload/download/registration stay
independent per file. Signed URLs are authenticated ciphertext, never API data.
"""
from contextlib import ExitStack
import json
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit

from . import upload_secrets
from .storage.core import StorageError


SCHEMA='''CREATE TABLE IF NOT EXISTS parse_cloud_batches(
 id TEXT PRIMARY KEY, provider_id TEXT, language TEXT NOT NULL,
 state TEXT NOT NULL, created_at REAL NOT NULL, key_id TEXT);
 CREATE TABLE IF NOT EXISTS parse_cloud_members(
 batch_id TEXT NOT NULL, task_id TEXT NOT NULL, data_id TEXT NOT NULL,
 file_name TEXT NOT NULL, source_file_id TEXT NOT NULL, producer_id TEXT NOT NULL,
 sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, version INTEGER NOT NULL,
 upload_state TEXT NOT NULL, upstream_state TEXT,
 upload_cipher TEXT, result_cipher TEXT, link_expires REAL,
 PRIMARY KEY(batch_id,task_id),UNIQUE(batch_id,data_id));'''


def initialize(conn):
    if 'current_batch' not in {r[1] for r in conn.execute('PRAGMA table_info(parse_queue_jobs)')}:
        conn.execute('ALTER TABLE parse_queue_jobs ADD COLUMN current_batch TEXT')
    for statement in SCHEMA.split(';'):
        if statement.strip():conn.execute(statement)


def context(q,batch,task,purpose):return '|'.join((q.service.ns.root,batch,task,purpose))


def checked_url(value):
    if not isinstance(value,str):return None
    try:
        parsed=urlsplit(value)
        if parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password:return value
    except ValueError:pass
    return None


def active_files(conn,stamp):
    return conn.execute('''SELECT count(*) FROM parse_queue_jobs q
        LEFT JOIN producer_recovery r ON r.job_id=q.producer_id
        LEFT JOIN storage_producer_jobs p ON p.id=q.producer_id WHERE q.backend='vlm' AND (
        (q.phase='submit' AND q.lease_token IS NOT NULL AND q.lease_until>?) OR
        ((r.submission IN ('unknown','known') OR COALESCE(p.task_id,'')!='')
          AND COALESCE(q.upstream_state,'unknown') NOT IN ('done','failed','rejected')))''',(stamp,)).fetchone()[0]


def claim(q,conn,leader,candidates,control,limits,stamp):
    from .parse_queue import submission_usage
    phase=leader['phase'];selected=[]
    if phase=='submit':
        if control['submit_paused'] or control['submit_after']>stamp:return None
        available=min(limits.batch_size,limits.upstream-active_files(conn,stamp))
        if available<1:return None
        total=0
        for candidate in candidates:
            row=dict(conn.execute('SELECT * FROM parse_queue_jobs WHERE id=?',(candidate['id'],)).fetchone())
            if row['phase']!='submit' or row['language']!=leader['language'] or row['current_batch'] or row['lease_token'] or row['state'] not in ('runnable','waiting'):continue
            if row['cancel_requested']:continue
            try:q._assert_current(conn,row)
            except StorageError:continue
            receipt=conn.execute('SELECT bytes FROM producer_recovery WHERE job_id=?',(row['producer_id'],)).fetchone()
            if not receipt:continue
            if total+receipt[0]>limits.batch_input_bytes:
                if not selected:q._park(conn,row,'inspection_required','batch_input_budget_exceeded')
                continue
            budget=conn.execute('SELECT max_submissions FROM parse_plans WHERE id=?',(row['plan_id'],)).fetchone()[0]
            # Reserve each file attempt; RPM reserves one HTTP POST per group.
            if submission_usage(conn,row['plan_id'])>=budget:
                q._park(conn,row,'blocked_budget','budget_exhausted');continue
            conn.execute("UPDATE parse_queue_jobs SET submissions=submissions+1,upstream_state='unknown' WHERE id=?",(row['id'],))
            selected.append(row);total+=receipt[0]
            if len(selected)>=available:break
        if not selected:return None
        batch='CB-'+uuid.uuid4().hex
        conn.execute("INSERT INTO parse_cloud_batches VALUES(?,NULL,?,'submitting',?,NULL)",(batch,leader['language'],stamp))
        for row in selected:
            receipt=conn.execute('SELECT * FROM producer_recovery WHERE job_id=?',(row['producer_id'],)).fetchone()
            conn.execute('''INSERT INTO parse_cloud_members(batch_id,task_id,data_id,file_name,source_file_id,producer_id,sha256,bytes,version,upload_state)
                VALUES(?,?,?,?,?,?,?,?,?,'not_requested')''',(batch,row['id'],row['id'],row['id']+'.pdf',row['source_file_id'],row['producer_id'],receipt['sha256'],receipt['bytes'],receipt['version']))
            conn.execute('UPDATE parse_queue_jobs SET current_batch=? WHERE id=?',(batch,row['id']))
        conn.execute('UPDATE parse_queue_control SET submit_after=?',(stamp+60/limits.submit_per_minute,))
    else:
        batch=leader['current_batch']
        if control['poll_after']>stamp:return None
        if conn.execute("SELECT 1 FROM parse_queue_jobs WHERE current_batch=? AND phase='poll' AND lease_token IS NOT NULL AND lease_until>?",(batch,stamp)).fetchone():return None
        for candidate in candidates:
            row=dict(candidate)
            if row['phase']=='poll' and row['current_batch']==batch and not row['lease_token']:
                try:q._assert_current(conn,row)
                except StorageError:continue
                selected.append(row)
        if not selected:return None
        conn.execute('UPDATE parse_queue_control SET poll_after=?',(stamp+60/limits.poll_per_minute,))
    leases=[]
    for row in selected:
        token=uuid.uuid4().hex
        conn.execute("UPDATE parse_queue_jobs SET state='active',epoch=?,worker=?,lease_token=?,lease_until=?,generation=generation+1,updated_at=? WHERE id=?",
            (q.authority.epoch,q.worker,token,stamp+limits.lease_seconds,stamp,row['id']))
        q.event(conn,row['id'],'claimed',phase=phase,native_batch=batch)
        leases.append(dict(conn.execute('SELECT * FROM parse_queue_jobs WHERE id=?',(row['id'],)).fetchone()))
    result=dict(leases[0]);result['_members']=leases
    return result


def remember(q,rows,batch,urls):
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',batch):raise StorageError('submission_unknown','provider batch identity invalid')
    local=rows[0]['current_batch']
    with q.tx() as conn:
        # This is a paid upstream identity checkpoint, not a publication. An
        # archived Source must not make other members lose their returned IDs.
        # Epoch, generation and lease remain mandatory for every member.
        for row in rows:q.validate(conn,row,source=False)
        conn.execute("UPDATE parse_cloud_batches SET provider_id=?,state='waiting-file',key_id=? WHERE id=?",(batch,upload_secrets.key_id(),local))
        for index,row in enumerate(rows):
            url=checked_url(urls[index]) if index<len(urls) else None
            envelope=upload_secrets.seal(url,context(q,local,row['id'],'upload')) if url else None
            conn.execute("UPDATE parse_cloud_members SET upload_state=?,upstream_state='waiting-file',upload_cipher=?,link_expires=? WHERE batch_id=? AND task_id=?",
                ('waiting-file' if url else 'missing_link',envelope,q.clock()+86400,local,row['id']))
            conn.execute("UPDATE storage_producer_jobs SET task_id=?,backend='vlm' WHERE id=?",(batch,row['producer_id']))
            conn.execute("UPDATE producer_recovery SET submission='known' WHERE job_id=?",(row['producer_id'],))
            conn.execute("UPDATE parse_queue_jobs SET upstream_state='waiting-file' WHERE id=?",(row['id'],))
            q.event(conn,row['id'],'upstream_batch_created',batch_id=batch,data_id=row['id'])


def submit(q,rows,driver):
    upload_secrets.key()  # validate runtime secret before the task-creating POST
    from Crypto.Cipher import AES  # dependency check before POST, not in callback
    active=[]
    with q.tx() as conn:
        for row in rows:
            q.validate(conn,row)
            flag=conn.execute('SELECT cancel_requested FROM parse_queue_jobs WHERE id=?',(row['id'],)).fetchone()[0]
            if flag:
                q._stop(conn,row,'cancel' if flag==2 else 'pause')
                conn.execute('UPDATE parse_queue_jobs SET current_batch=NULL WHERE id=?',(row['id'],))
                conn.execute("UPDATE parse_cloud_members SET upload_state='cancelled' WHERE batch_id=? AND task_id=?",(row['current_batch'],row['id']))
            else:active.append(row)
    if not active:return
    with ExitStack() as stack:
        files=[]
        for row in active:
            pdf=stack.enter_context(q.service.read(row['source_file_id'],'pdf',1))
            files.append({'path':pdf,'data_id':row['id'],'name':row['id']+'.pdf'})
        with q.tx() as conn:
            for row in active:
                q.validate(conn,row)
                conn.execute("UPDATE producer_recovery SET submission='unknown' WHERE job_id=?",(row['producer_id'],))
                q.event(conn,row['id'],'submitting',native_files=len(active))
        try:driver.create_batch(files,active[0]['language'],lambda batch,urls:remember(q,active,batch,urls))
        except Exception as error:
            if getattr(error,'code',None)=='submission_rejected':
                with q.tx() as conn:
                    for row in active:
                        q.validate(conn,row);conn.execute("UPDATE producer_recovery SET submission='rejected' WHERE job_id=?",(row['producer_id'],))
            raise
    for row in active:
        try:q.finish(row,phase='upload',upstream='waiting-file')
        except StorageError as error:
            if error.code!='revision_conflict':raise
            q._failure(row,error)


def member(q,row):
    with q.registry.conn(read_only=True) as conn:
        found=conn.execute('SELECT m.*,b.provider_id FROM parse_cloud_members m JOIN parse_cloud_batches b ON b.id=m.batch_id WHERE m.batch_id=? AND m.task_id=?',(row['current_batch'],row['id'])).fetchone()
        if not found:raise StorageError('producer_incomplete','native file mapping unavailable')
        return dict(found)


def match(entries,mapping):
    if any(e.get('file_name')==mapping['file_name'] and e.get('data_id') and e['data_id']!=mapping['data_id'] for e in entries):
        raise StorageError('provider_identity_mismatch','native data_id differs')
    exact=[e for e in entries if e.get('data_id')==mapping['data_id']]
    if not exact:exact=[e for e in entries if not e.get('data_id') and e.get('file_name')==mapping['file_name']]
    if len(exact)>1:raise StorageError('provider_identity_mismatch','duplicate native result identity')
    if not exact:return None
    result=exact[0]
    if result.get('file_name') and result['file_name']!=mapping['file_name']:raise StorageError('provider_identity_mismatch','native filename differs')
    state=result.get('state')
    if not isinstance(state,str) or not re.fullmatch(r'[a-z][a-z-]{0,30}',state):raise StorageError('provider_response_invalid','native result state invalid')
    return result


def poll(q,rows,driver):
    first=member(q,rows[0])
    if not first['provider_id']:raise StorageError('producer_incomplete','provider batch ID unavailable; inspect submission')
    entries=driver.query_batch(first['provider_id'])  # one GET for the group
    for row in rows:
        mapping=member(q,row)
        try:result=match(entries,mapping)
        except StorageError as error:q.finish(row,state='inspection_required',error=error.code);continue
        if result is None:
            q._failure(row,StorageError('provider_member_not_reported','provider did not report this data_id'));continue
        state=result['state']
        with q.tx() as conn:
            q.validate(conn,row)
            flag=conn.execute('SELECT cancel_requested FROM parse_queue_jobs WHERE id=?',(row['id'],)).fetchone()[0]
            if flag:q._stop_records(conn,row,'cancel' if flag==2 else 'pause')
            conn.execute('UPDATE parse_cloud_members SET upstream_state=? WHERE batch_id=? AND task_id=?',(state,row['current_batch'],row['id']))
            if state=='done' and not flag:
                url=checked_url(result.get('full_zip_url'))
                if url:
                    conn.execute('UPDATE parse_cloud_members SET result_cipher=?,upload_cipher=NULL,upload_state=\'uploaded\' WHERE batch_id=? AND task_id=?',
                                 (upload_secrets.seal(url,context(q,row['current_batch'],row['id'],'result')),row['current_batch'],row['id']))
            if state=='failed':
                conn.execute("UPDATE producer_recovery SET submission='terminal_failed' WHERE job_id=?",(row['producer_id'],))
            unfinished=conn.execute("SELECT 1 FROM parse_cloud_members WHERE batch_id=? AND upload_state!='cancelled' AND COALESCE(upstream_state,'') NOT IN ('done','failed') LIMIT 1",(row['current_batch'],)).fetchone()
            conn.execute('UPDATE parse_cloud_batches SET state=? WHERE id=?',('active' if unfinished else 'terminal',row['current_batch']))
        if flag:
            q.finish(row,phase='poll',state=('cancelled' if flag==2 else 'paused') if state in ('done','failed') else 'tracking',delay=q._limits().poll_seconds,upstream=state)
        elif state=='done':
            q.finish(row,phase='download',state='runnable' if checked_url(result.get('full_zip_url')) else 'inspection_required',error=None if checked_url(result.get('full_zip_url')) else 'result_link_missing',upstream='done')
        elif state=='failed':q.finish(row,state='failed',error='upstream_failed',upstream='failed')
        elif state=='waiting-file':
            if mapping['upload_state']=='uploaded':
                q.finish(row,phase='poll',state='waiting',delay=q._limits().poll_seconds,upstream=state)
            else:q.finish(row,phase='upload',state='runnable' if mapping['upload_cipher'] else 'inspection_required',error=None if mapping['upload_cipher'] else 'upload_link_missing',upstream=state)
        else:q.finish(row,phase='poll',state='waiting',delay=q._limits().poll_seconds,upstream=state)


def upload(q,row,driver):
    mapping=member(q,row)
    # An interrupted PUT is reconciled first. A known pending/running/done file
    # is never uploaded again, and no new task-creating POST is used here.
    if mapping['upload_state'] in ('uploading','unknown'):
        result=match(driver.query_batch(mapping['provider_id']),mapping)
        if not result:raise StorageError('upload_outcome_unknown','provider has not reported this file')
        if result['state']!='waiting-file':
            with q.tx() as conn:
                q.validate(conn,row)
                conn.execute("UPDATE parse_cloud_members SET upload_state='uploaded',upload_cipher=NULL WHERE batch_id=? AND task_id=?",(row['current_batch'],row['id']))
            q.finish(row,phase='poll',state='waiting',upstream=result['state']);return
    if not mapping['upload_cipher']:raise StorageError('upload_link_missing','signed upload link unavailable; preserve batch mapping')
    if mapping['link_expires']<=q.clock():raise StorageError('upload_link_expired','signed link expired; inspect existing file before a new intent')
    url=upload_secrets.open_secret(mapping['upload_cipher'],context(q,row['current_batch'],row['id'],'upload'))
    with q.tx() as conn:
        q.validate(conn,row);conn.execute("UPDATE parse_cloud_members SET upload_state='uploading' WHERE batch_id=? AND task_id=?",(row['current_batch'],row['id']))
    with q.service.read(row['source_file_id'],'pdf',1) as pdf:driver.upload_file(url,pdf)
    with q.tx() as conn:
        q.validate(conn,row)
        conn.execute("UPDATE parse_cloud_members SET upload_state='uploaded',upload_cipher=NULL,upstream_state='pending' WHERE batch_id=? AND task_id=?",(row['current_batch'],row['id']))
    q.finish(row,phase='poll',state='waiting',delay=q._limits().poll_seconds,upstream='pending')


def download(q,row,driver,pdf,out,event,maximum):
    mapping=member(q,row)
    if not mapping['result_cipher']:raise StorageError('result_link_missing','query existing batch before download')
    url=upload_secrets.open_secret(mapping['result_cipher'],context(q,row['current_batch'],row['id'],'result'))
    driver.download_url(pdf,out,url,event,maximum)

"""Versioned host executor; trusted configuration, environment-only credentials.

Independent of uvicorn. No epoch changes. Backup scope comes from authenticated
runtime and is revalidated after maintenance; no raw SQLite file copying.
"""
import json
import os
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler

from .core import StorageError, Namespace, hash_file
from .authority import Authority
from .backends import oss_from_environment
from .release_control import prepare, stage, publish, digest, write, bindings
from .backup_catalog import run_due, record_verified
from ..backup_jobs import BackupPreflightError, now, root as control_root


def require(condition, message):
    if not condition: raise StorageError('configuration_error', message)


def execute(config, job_id, *, preview=False):
    phase = {'entered': False}
    try:
        return _execute(config, job_id, preview=preview, phase=phase)
    except Exception as error:
        if not phase['entered']:
            raise BackupPreflightError(getattr(error, 'code', 'backup_preflight_failed'),
                                       'backup preflight failed before maintenance') from error
        raise


def _execute(config, job_id, *, preview, phase):
    from scripts.snapshot_inputs import refresh
    from scripts.litlib_remote import base_url, NoRedirect, tls_context
    from urllib.request import HTTPSHandler
    code = Path(__file__).resolve().parents[2]
    server = base_url(config['server'])
    opener = build_opener(ProxyHandler({}), NoRedirect, HTTPSHandler(context=tls_context(config.get('ca_file'))))
    def schema():
        token = os.environ.get('LITLIB_REMOTE_TOKEN','')
        require(len(token)>=32, 'remote credential required in environment')
        with opener.open(Request(server+'/api/research/schema',headers={'Authorization':'Bearer '+token}),timeout=30) as response:
            return json.loads(response.read(1024*1024))
    live = schema(); slot = Path(live['code_root']).resolve().parent
    require(slot.is_relative_to(Path(config['releases_root']).resolve()), 'runtime outside managed releases')
    require(not control_root().is_relative_to(Path(config['releases_root']).resolve()), 'backup controller must survive slot retirement')
    require(live['verify']['ok'] and not live['read_only'] and live['remote_writes_enabled'], 'runtime not a verified writer')
    require(subprocess.check_output(['git','rev-parse','HEAD'],cwd=code).decode().strip()==live['code_commit'], 'executor commit differs from live code')
    manifest=json.loads((slot/'release-manifest.json').read_text('utf-8'))
    environment=json.loads((slot/'environment.json').read_text('utf-8'))
    require(hash_file(slot/'release-manifest.json')[0]==live['manifest_sha256'], 'runtime manifest differs')
    require(Path(live['plan']['db_path']).resolve()==Path(environment['LITLIB_RESEARCH_DB']).resolve(), 'runtime research database differs')
    require(Path(environment['LITLIB_DB_PATH']).resolve().is_relative_to(slot), 'catalog outside runtime slot')
    # Epoch supplied by host config must match the active authority record and
    # launch configuration; check_remote rejects stale or wrong-release epochs.
    epoch=int(config['epoch']); backend=oss_from_environment()
    authority=Authority(backend,environment['LITLIB_STORAGE_ROOT'],os.environ['LITLIB_AUTHORITY_TOKEN'],epoch,slot/'data/.authority',live['manifest_sha256'])
    authority.check_remote(); require(not authority.marker.exists(), 'writer frozen')
    budget=int(config['max_snapshot_bytes']); require(budget>0,'positive snapshot budget required')
    template={'format':'litlib-snapshot-input-v1','namespace':manifest['namespace'],'source_root':str(slot),
              'configuration':manifest['configuration'],'code_url':manifest['code']['url'],
              'files':{name:{} for name in manifest['essentials'] if name not in ('library/literature.sqlite','research/research.sqlite')},
              'frontend':{**manifest['frontend'],'source':str(Path(config['frontend_zip']).resolve())}}
    previous={k:os.environ.get(k) for k in environment}
    os.environ.update(environment)
    try:
        ticket=prepare(refresh(template,slot),budget)
        if preview: return {'executed':False,'code_commit':live['code_commit'],'epoch':epoch,'payload_bytes_estimate':ticket['payload_bytes_estimate']}
        destination=control_root()/'receipts'/job_id
        require(not destination.exists(),'receipt destination already exists; inspect before another attempt')
        destination.mkdir(parents=True)
        write(destination/'preflight.json',{'code_commit':live['code_commit'],'manifest_sha256':live['manifest_sha256'],'epoch':epoch})
        def quiet():
            with closing(sqlite3.connect(Path(environment['LITLIB_DB_PATH']).as_uri()+'?mode=ro',uri=True)) as conn:
                conn.execute('PRAGMA query_only=ON')
                for query in ("SELECT count(*) FROM literature_parse_runs WHERE status='running'",
                              "SELECT count(*) FROM storage_operations WHERE state!='registered'",
                              "SELECT count(*) FROM storage_producer_jobs WHERE state NOT IN ('registered','failed')"):
                    require(conn.execute(query).fetchone()[0]==0,'active work; complete or reconcile before maintenance')
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='parse_plan_items'").fetchone():
                    require(conn.execute("SELECT count(*) FROM parse_plan_items WHERE state='running'").fetchone()[0]==0,'interrupted parse plan requires inspection')
                # Legacy failed cloud jobs have no portable output ownership.
                # Do not call their snapshot recoverable until coordinated.
                from ..producer_recovery import read
                conn.row_factory=sqlite3.Row
                for job in conn.execute("SELECT id FROM storage_producer_jobs WHERE kind='parse' AND state='failed' AND backend='vlm' AND task_id IS NOT NULL AND task_id!=''"):
                    require(read(conn,job['id']) is not None,'legacy cloud job requires recovery before snapshot')
        def command(name):
            argv=config[name]
            require(isinstance(argv,list) and argv and all(isinstance(v,str) for v in argv),'maintenance argv required')
            # Trusted host configuration only; neither request ID nor remote
            # payload is interpolated into shell commands.
            subprocess.run(argv,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        quiet(); entered=False
        try:
            with authority.write_guard():
                quiet(); require(schema()['manifest_sha256']==live['manifest_sha256'],'runtime changed')
                # Mark before invoking: a command may stop the service and then fail.
                entered=True; phase['entered']=True; command('maintenance_enter')
            command('maintenance_verify_stopped')
            quiet(); authority.check_remote()
            final_inputs=refresh(template,slot)
            def backup():
                final=prepare(final_inputs,budget); write(destination/'ticket.json',final)
                staged=stage(final,digest(final),destination/'stage',True)
                published=publish(destination/'stage',staged['manifest_sha256'],backend,staged['maximum_upload_bytes'])
                write(destination/'published.json',published)
                return record_verified(control_root()/'backup-catalog.json',destination/'stage',published,backend,now())
            ns=Namespace(final_inputs['namespace'])
            active={ns.key(b['parent_sha256'] or b['sha256']) for b in bindings(final_inputs['catalog'])}
            result=run_due(control_root()/'backup-catalog.json',active,backup,force=True)
            write(destination/'result.json',result)
        finally:
            if entered:
                # This backup never freezes or hands over authority. Verify
                # that ownership is unchanged before restarting the same writer.
                authority.check_remote(); command('maintenance_exit')
                after=schema()
                require(after['manifest_sha256']==live['manifest_sha256'] and after['remote_writes_enabled'] and not after['read_only'], 'writer did not recover')
                write(destination/'service-restored.json',{'at':now(),'manifest_sha256':after['manifest_sha256']})
        return result['version']
    finally:
        for key,value in previous.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key]=value

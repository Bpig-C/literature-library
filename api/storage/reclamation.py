"""Exact production GC planning/revalidation. Deletion is local-test-only.

The host must quiesce external writers and inventory every snapshot stage/pin.
Supported authority/producer/scheduler locks remain held through validation.
"""
import base64,hashlib,json,re,sqlite3,tempfile
from contextlib import contextmanager,ExitStack
from datetime import timedelta
from pathlib import Path
from .core import StorageError,Namespace,checked_sha,hash_file,file_lock,relative_key
from .backends import LocalObjectBackend,OSSBackend
from .release_control import digest,read,write,REQUIRED_ASSETS,staged
from .snapshot_policy import timestamp
from .unified_release import CONFIG_KEYS

ROOT_FIELDS={'format','namespace','runtime_release','handover_releases','pins','stage_parent','snapshot_stages','writers_quiescent'}
STATES={'storage_operations':{'staged','uploaded_verified','registered'},'storage_staging_files':{'reserved','ready','releasing','released'},'storage_producer_jobs':{'preparing','artifacts_ready','registered','failed'}}

def require(ok,message,code='configuration_error'):
    if not ok:raise StorageError(code,message)

class ReclamationPlanner:
    def __init__(self,service,catalog,roots,authority,*,max_verify_bytes,max_manifests=1000):
        self.s=service;self.backend=service.backend;self.ns=service.ns;self.catalog=Path(catalog);self.roots=Path(roots);self.authority=authority
        require(self.catalog.is_absolute() and self.roots.is_absolute(),'Explicit absolute catalog/roots required')
        require(type(max_verify_bytes) is int and max_verify_bytes>0 and type(max_manifests) is int and max_manifests>0,'Explicit positive verification budgets required')
        require(authority.ns.root==self.ns.root,'Authority namespace differs')
        self.budget=max_verify_bytes;self.max_manifests=max_manifests
        if isinstance(self.backend,LocalObjectBackend):self.target={'kind':'local','root':str(self.backend.root),'namespace':self.ns.root}
        elif isinstance(self.backend,OSSBackend):self.target={'kind':'oss','bucket':self.backend.bucket,'namespace':self.ns.root}
        else:raise StorageError('configuration_error','Supported exact backend required')

    @contextmanager
    def guard(self):
        # Match supported business entrypoint -> producer order; administrative
        # backup tick also holds the same scheduler lock. No SQLite write/DDL.
        with self.authority.write_guard(),file_lock(self.s.registry.catalog.with_suffix('.producer.lock'),timeout=0),file_lock(self.catalog.with_suffix('.scheduler.lock'),timeout=0),file_lock(self.catalog.with_suffix('.lock'),timeout=0):yield

    def descriptor(self,e):
        require(isinstance(e,dict) and {'key','sha256','bytes'}<=set(e),'Complete object descriptor required')
        sha=checked_sha(e['sha256']);size=e['bytes']
        require(type(size) is int and size>=0 and e['key']==self.ns.key(sha),'Exact namespace SHA/bytes required')
        return {'key':e['key'],'sha256':sha,'bytes':size}

    def binding(self,b):
        checked_sha(b['sha256']);require(type(b['bytes']) is int and b['bytes']>=0,'Binding size unknown')
        require(b.get('identity') and b.get('role') and type(b.get('version')) is int and b['version']>0,'Binding identity/version unknown')
        if b.get('member') is not None:
            relative_key(b['member']);sha=checked_sha(b['parent_sha256']);size=b['parent_bytes']
        else:
            require(not b.get('parent_sha256') and b.get('parent_bytes') is None,'Ambiguous binding parent')
            sha=b['sha256'];size=b['bytes']
        return self.descriptor({'key':self.ns.key(sha),'sha256':sha,'bytes':size})

    def capture(self,*,cached=None,deleted=()):
        cached=dict(cached or {});deleted=set(deleted);docs={};entries={};protected={};origins={};verified_keys=set()
        require(self.roots.stat().st_size<=self.budget and self.catalog.stat().st_size<=self.budget,'Root metadata budget exceeded','quota_exceeded')
        root_raw=self.roots.read_bytes();catalog_raw=self.catalog.read_bytes()
        roots=json.loads(root_raw);require(set(roots)==ROOT_FIELDS and roots['format']=='litlib-gc-roots-v1' and roots['namespace']==self.ns.root and roots['writers_quiescent'] is True,'Complete explicit quiescent roots inventory required')
        for name in ('pins','handover_releases','snapshot_stages'):require(isinstance(roots[name],list),'Complete root lists required')
        cat=json.loads(catalog_raw);require({'format','versions','attempts'}<=set(cat)<={'format','versions','attempts','reclamations'} and cat['format']=='litlib-backup-catalog-v1','Backup catalog unavailable/unknown')
        from .reclamation_execution import ledger
        archived,historical_deleted,reclaimed_versions,receipt_proofs=ledger(cat,self.target,self.budget)
        for key,value in archived.items():require(key not in cached or cached[key]==value,'Plan/receipt manifest archive differs');cached[key]=value
        ongoing_deleted=set(deleted);deleted|=historical_deleted
        require(all(a.get('state')=='failed' and a.get('at') and a.get('code') for a in cat['attempts']),'Unknown backup attempt state')
        versions=cat['versions'];require(isinstance(versions,list) and len({v['id'] for v in versions})==len(versions),'Unknown or duplicate snapshot state')
        require(all(v.get('state') in {'verified','retired','reclaimed'} and v.get('namespace')==self.ns.root for v in versions),'Unknown snapshot state/namespace')
        require(set(reclaimed_versions)<={v['id'] for v in versions} and all((v['state']=='reclaimed')==(v['id'] in reclaimed_versions) for v in versions),'Reclaimed metadata lacks trusted receipt')
        require(all(v.get('reclamation_sha256') in reclaimed_versions[v['id']] for v in versions if v['state']=='reclaimed'),'Reclaimed version receipt anchor differs')
        successes=sorted((v for v in versions if v['state']=='verified'),key=lambda v:(timestamp(v['verified_at']),v['id']),reverse=True)
        require(bool(successes),'At least one verified backup required')
        keep={v['id'] for v in successes[:3]};extra_verified=[v['id'] for v in successes[3:]]
        def add(e,reason=None,origin=None):
            e=self.descriptor(e);key=e['key']
            require(key not in entries or entries[key]==e,'Conflicting descriptor for shared object','checksum_mismatch');entries[key]=e
            if reason:protected.setdefault(key,set()).add(reason)
            if origin:origins.setdefault(key,set()).add(origin)
            return e
        def load(e):
            e=self.descriptor(e);key=e['key']
            if key in docs:return json.loads(base64.b64decode(docs[key]))
            require(len(docs)<self.max_manifests,'Manifest count budget exceeded','quota_exceeded')
            require(e['bytes']<=16*1024**2,'Manifest byte budget exceeded','quota_exceeded')
            with tempfile.TemporaryDirectory(prefix='litlib-gc-manifest-') as t:
                p=Path(t)/'manifest'
                try:self.backend.download(key,p,max_bytes=e['bytes']);raw=p.read_bytes()
                except StorageError as error:
                    if error.code!='not_found' or key not in deleted or key not in cached:raise
                    raw=base64.b64decode(cached[key],validate=True)
                require((hashlib.sha256(raw).hexdigest(),len(raw))==(e['sha256'],e['bytes']),'Manifest SHA/size differs','checksum_mismatch')
            require(sum(len(base64.b64decode(v)) for v in docs.values())+len(raw)<=self.budget,'Manifest closure verification budget exceeded','quota_exceeded')
            docs[key]=base64.b64encode(raw).decode('ascii');return json.loads(raw)
        def closure(e,reason=None,origin=None,local_manifest=None,archived_only=False):
            e=add(e,reason,origin)
            if local_manifest:
                raw=local_manifest.read_bytes();require(hash_file(local_manifest)==(e['sha256'],e['bytes']),'Frozen stage changed','revision_conflict')
                require(sum(len(base64.b64decode(v)) for k,v in docs.items() if k!=e['key'])+len(raw)<=self.budget,'Manifest closure verification budget exceeded','quota_exceeded')
                docs[e['key']]=base64.b64encode(raw).decode('ascii');m=json.loads(raw)
            else:m=load(e)
            require(m.get('format')=='litlib-unified-release-v1' and m.get('namespace')==self.ns.root and m.get('configuration',{}).get('storage_namespace')==self.ns.root,'Unknown snapshot manifest')
            require(set(m)<={'format','release_id','code','frontend','essentials','configuration','credential_environment_names','namespace','original_roots','asset_index','default_fetch','snapshot_window'} and set(m['asset_index'])=={'bindings'} and set(m['configuration'])<=CONFIG_KEYS,'Unknown manifest reference fields')
            require(re.fullmatch('[0-9a-f]{40}',m['code']['commit']) and REQUIRED_ASSETS|{'library/literature.sqlite','research/research.sqlite'}<=set(m['essentials']),'Incomplete release closure')
            keys={e['key']}
            for name in m['essentials']:
                relative_key(name);require(name in {'library/literature.sqlite','research/research.sqlite'} or name.startswith(('research/assets/','research/editing/','library/templates/','library/docs/')),'Unknown essential reference path')
            for item in [*m['essentials'].values(),m['frontend']]:keys.add(add(item,reason,origin)['key'])
            for b in m['asset_index']['bindings']:keys.add(add(self.binding(b),reason,origin)['key'])
            if not local_manifest and not archived_only:verified_keys.update(keys)
            return m,keys
        version_keys={};fresh_origins=set()
        for v in versions:
            e={'key':v['manifest_key'],'sha256':v['manifest_sha256'],'bytes':self.backend_size(v['manifest_key'],cached,deleted)}
            reason='retained:'+v['id'] if v['id'] in keep else 'rotation_pending:'+v['id'] if v['state']=='verified' else None
            m,keys=closure(e,reason,v['id'] if v['state'] in {'retired','reclaimed'} else None,archived_only=v['state']=='reclaimed')
            require(m['release_id']==v['id'] and m['code']['commit']==v['code_commit'] and set(v['asset_keys'])==keys-{v['manifest_key']},'Catalog/manifest closure differs','checksum_mismatch')
            version_keys[v['id']]=keys
            if v['state']=='retired':fresh_origins|=keys
        closure(roots['runtime_release'],'current_runtime')
        authority=self.authority.check_remote()
        if authority['release']:
            a=authority['release'];closure({'key':a['manifest_key'],'sha256':a['manifest_sha256'],'bytes':self.backend.size(a['manifest_key'])},'authority_release')
        for e in roots['handover_releases']:closure(e,'pending_handover')
        pins=set()
        for p in roots['pins']:
            require(set(p)=={'id','reason','release'} and p['id'] and p['reason'] and p['id'] not in pins,'Unknown/duplicate explicit pin');pins.add(p['id']);closure(p['release'],'pin:'+p['id']+':'+p['reason'])
        tables={}
        try:
            with sqlite3.connect(self.s.registry.catalog.as_uri()+'?mode=ro',uri=True) as c:
                c.row_factory=sqlite3.Row;c.execute('BEGIN')
                require(c.execute('SELECT root FROM storage_settings WHERE id=1').fetchone()[0]==self.ns.root,'Registry namespace differs')
                for name in ('storage_bindings',*STATES):tables[name]=sorted((dict(r) for r in c.execute('SELECT * FROM '+name)),key=digest)
        except (sqlite3.Error,TypeError,IndexError):raise StorageError('configuration_error','Complete storage registry required') from None
        for b in tables['storage_bindings']:verified_keys.add(add(self.binding(b),'active_registry')['key'])
        for table,allowed in STATES.items():require(all(r['state'] in allowed for r in tables[table]),'Unknown pending job/staging state')
        for op in tables['storage_operations']:
            request=json.loads(op['request']);entry=self.binding(request)
            if op['state']!='registered':add(entry,'operation:'+op['operation_id'])
            else:require(any(all(b[k]==request[k] for k in ('identity','role','version','sha256','bytes','parent_sha256','parent_bytes','member')) for b in tables['storage_bindings']),'Registered operation lacks exact binding')
        pending_paths={};local_artifacts={}
        for row in tables['storage_staging_files']:
            e={'key':self.ns.key(row['sha256']),'sha256':row['sha256'],'bytes':row['bytes']}
            expected=self.s.staging/(row['sha256']+'.pending');require(row['pending']==str(expected),'Unowned pending locator')
            pending_paths[expected.name]=row
            if row['state']!='released':add(e,'staging:'+row['state'])
            require(row['state']!='ready' or expected.is_file(),'Ready pending bytes missing')
        for f in self.s.staging.iterdir():
            if f.name=='locks':require(f.is_dir() and not f.is_symlink(),'Unknown staging lock directory');continue
            if f.name in {'.litlib-storage-owner.json','.ownership.lock'}:continue
            require(f.name in pending_paths and f.is_file() and not f.is_symlink(),'Uninventoried staging/partial file')
            require(sum(v[1] for v in local_artifacts.values())+f.stat().st_size<=self.budget,'Pending byte verification budget exceeded','quota_exceeded')
            row=pending_paths[f.name];actual=hash_file(f);require(actual==(row['sha256'],row['bytes']),'Pending bytes changed','revision_conflict');local_artifacts[str(f)]=list(actual)
        for job in tables['storage_producer_jobs']:
            assets=json.loads(job['artifacts'])
            if job['state']=='registered':
                require(isinstance(assets,list) and assets and all(any(all(b[k]==a[k] for k in ('identity','role','version')) for b in tables['storage_bindings']) for a in assets),'Registered producer lacks fixed bindings');continue
            require(job['state']=='artifacts_ready' and assets,'Incomplete/failed producer has unknown reference closure')
            for a in assets:
                source=Path(a['source']);require(source.is_absolute() and source.is_file() and not source.is_symlink(),'Unfinished producer bytes unavailable')
                if str(source) not in local_artifacts:
                    require(sum(v[1] for v in local_artifacts.values())+source.stat().st_size<=self.budget,'Pending byte verification budget exceeded','quota_exceeded')
                    local_artifacts[str(source)]=list(hash_file(source))
                sha,size=local_artifacts[str(source)];add({'key':self.ns.key(sha),'sha256':sha,'bytes':size},'producer:'+job['id'])
        parent=Path(roots['stage_parent']);require(parent.is_absolute() and parent.is_dir() and not parent.is_symlink(),'Explicit snapshot stage inventory directory required')
        stage_paths={};stage_fingerprints={}
        for item in roots['snapshot_stages']:
            require(set(item)=={'id','state','path'} and item['state'] in {'staged','publishing','failed','completed'},'Unknown snapshot stage state')
            p=Path(item['path']);require(p.is_absolute() and p.parent.resolve()==parent.resolve() and not p.is_symlink() and p.is_dir() and p.name not in stage_paths,'Uninventoried stage location')
            stage_paths[p.name]=item
            require((p/'release.json').stat().st_size<=16*1024**2,'Stage manifest budget exceeded','quota_exceeded')
            preliminary=read(p/'release.json');total=0
            for name,entry in [*preliminary['essentials'].items(),('frontend.zip',preliminary['frontend'])]:
                relative_key(name);entry=self.descriptor(entry);require((p/name).stat().st_size==entry['bytes'],'Stage object size differs','revision_conflict');total+=entry['bytes']
            require(total<=self.budget,'Stage cold verification budget exceeded','quota_exceeded')
            _,receipt,m=staged(p);e={'key':self.ns.key(receipt['manifest_sha256']),'sha256':receipt['manifest_sha256'],'bytes':(p/'release.json').stat().st_size}
            require(item['id']==m['release_id'],'Stage identity differs');journal=read(p/'upload-journal.json')
            require(journal['state'] in {'staged','publishing','published'} and journal['manifest_sha256']==e['sha256'],'Unknown snapshot retry state')
            require(item['state']!='completed' or (journal['state']=='published' and any(v['id']==item['id'] for v in versions)),'Unregistered completed snapshot stage')
            stage_fingerprints[str(p)]={'manifest':hash_file(p/'release.json')[0],'receipt':hash_file(p/'stage-receipt.json')[0],'journal':hash_file(p/'upload-journal.json')[0]}
            closure(e,None if item['state']=='completed' else 'snapshot_retry:'+item['id'],local_manifest=p/'release.json')
        require({p.name for p in parent.iterdir()}==set(stage_paths),'Snapshot stage inventory incomplete')
        require(len(docs)<=self.max_manifests,'Manifest count budget exceeded','quota_exceeded')
        for key in verified_keys-ongoing_deleted:require(self.backend.size(key)==entries[key]['bytes'],'Referenced object missing/size differs','revision_conflict')
        known_absent=set()
        for key in historical_deleted:
            try:self.backend.size(key)
            except StorageError as error:
                if error.code!='not_found':raise
                known_absent.add(key);continue
            require(key in protected or key in fresh_origins,'Reclaimed object reappeared without fresh ownership','revision_conflict')
        fingerprint=digest({'roots':hashlib.sha256(root_raw).hexdigest(),'catalog':hashlib.sha256(catalog_raw).hexdigest(),'registry':tables,'authority':authority,'local_artifacts':local_artifacts,'snapshot_stages':stage_fingerprints,'reclamation_receipts':receipt_proofs})
        return {'fingerprint':fingerprint,'entries':entries,'protected':{k:sorted(v) for k,v in protected.items()},'origins':{k:sorted(v) for k,v in origins.items() if k not in known_absent},'manifest_cache':docs,'keep':sorted(keep),'rotation_pending':extra_verified,'blockers':[{'version':v['id'],'manifest_key':v['manifest_key'],'reasons':sorted(protected[v['manifest_key']])} for v in versions if v['state']=='retired' and v['manifest_key'] in protected]}

    def backend_size(self,key,cached,deleted):
        if key in deleted and key in cached:return len(base64.b64decode(cached[key],validate=True))
        return self.backend.size(key)

    def verify_objects(self,entries,deleted=()):
        require(sum(e['bytes'] for e in entries)<=self.budget,'Candidate cold verification exceeds explicit budget','quota_exceeded')
        for e in entries:
            if e['key'] in deleted:
                try:self.backend.size(e['key'])
                except StorageError as error:
                    if error.code=='not_found':continue
                    raise
                raise StorageError('revision_conflict','Previously deleted object reappeared')
            with tempfile.TemporaryDirectory(prefix='litlib-gc-verify-') as t:
                p=Path(t)/'object';self.backend.download(e['key'],p,max_bytes=e['bytes'])
                require(hash_file(p)==(e['sha256'],e['bytes']),'Candidate object SHA/size changed','revision_conflict')

    def plan(self,*,now,valid_minutes=30):
        require(type(valid_minutes) is int and 0<valid_minutes<=60,'Plan lifetime must be 1..60 minutes')
        with self.guard():
            before=self.capture();candidates=[dict(before['entries'][k],retired_versions=v,reason='Retired closure; absent from every protected root') for k,v in sorted(before['origins'].items()) if k not in before['protected']]
            self.verify_objects(candidates)
            require(self.capture()['fingerprint']==before['fingerprint'],'Roots changed during planning','revision_conflict')
            result={'format':'litlib-gc-plan-v1','target':self.target,'created_at':now,'expires_at':(timestamp(now)+timedelta(minutes=valid_minutes)).isoformat(),'root_fingerprint':before['fingerprint'],'keep_successful':before['keep'],'rotation_pending':before['rotation_pending'],'physical_limit_blockers':before['blockers'],'protected':before['protected'],'candidates':candidates,'total_unique_bytes':sum(e['bytes'] for e in candidates),'manifest_cache':before['manifest_cache'],'deletion_performed':False,'production_delete_supported':False}
            result['plan_sha256']=digest(result);return result

    def validate(self,plan,*,now,deleted=()):
        value=dict(plan);sha=value.pop('plan_sha256',None);require(sha==digest(value),'Frozen plan digest differs','checksum_mismatch')
        require(plan['target']==self.target and timestamp(plan['created_at'])<=timestamp(now)<=timestamp(plan['expires_at']),'Plan expired/not yet valid or backend differs','revision_conflict')
        current=self.capture(cached=plan['manifest_cache'],deleted=deleted)
        require(current['fingerprint']==plan['root_fingerprint'],'Protected roots changed; regenerate plan','revision_conflict')
        expected=[dict(current['entries'][k],retired_versions=v,reason='Retired closure; absent from every protected root') for k,v in sorted(current['origins'].items()) if k not in current['protected']]
        require(expected==plan['candidates'] and current['protected']==plan['protected'],'Plan no longer matches exact reference closure','revision_conflict')
        self.verify_objects(expected,deleted)
        require(self.capture(cached=plan['manifest_cache'],deleted=deleted)['fingerprint']==plan['root_fingerprint'],'Roots changed during revalidation','revision_conflict')
        return {'ok':True,'dry_run':True,'plan_sha256':sha,'deletion_performed':False}

    def execute_local(self,plan,journal_path,*,now,fail_after_delete=False):
        require(isinstance(self.backend,LocalObjectBackend) and '/test/' in self.ns.root,'No production/OSS deletion implementation','permission_denied')
        path=Path(journal_path);require(path.is_absolute(),'Explicit local simulation journal required')
        with self.guard(),file_lock(path.with_suffix('.lock'),timeout=0):
            journal=read(path) if path.exists() else {'format':'litlib-gc-test-journal-v1','plan_sha256':plan['plan_sha256'],'deleted':[],'pending':None,'state':'running'}
            require(journal.get('format')=='litlib-gc-test-journal-v1' and journal.get('plan_sha256')==plan['plan_sha256'],'Journal belongs to another plan','revision_conflict')
            require(set(journal)=={'format','plan_sha256','deleted','pending','state'} and journal['state'] in {'running','completed'} and isinstance(journal['deleted'],list) and len(set(journal['deleted']))==len(journal['deleted']),'Unknown simulation journal state')
            keys={e['key'] for e in plan['candidates']};require(set(journal['deleted'])<=keys and (journal['pending'] is None or journal['pending'] in keys),'Unknown journal object')
            missing=list(journal['deleted'])
            if journal['pending']:
                try:self.backend.size(journal['pending'])
                except StorageError as e:
                    if e.code!='not_found':raise
                    missing.append(journal['pending'])
            self.validate(plan,now=now,deleted=missing)
            if journal['pending'] in missing and journal['pending'] not in journal['deleted']:journal['deleted'].append(journal['pending'])
            # Manifests last, so partial failure retains remote closure evidence.
            order=sorted(plan['candidates'],key=lambda e:(e['key'] in plan['manifest_cache'],e['key']))
            for e in order:
                if e['key'] in journal['deleted']:continue
                require(self.capture(cached=plan['manifest_cache'],deleted=journal['deleted'])['fingerprint']==plan['root_fingerprint'],'Roots changed before simulated deletion','revision_conflict')
                journal.update(pending=e['key'],state='running');write(path,journal)
                p=self.backend.root/e['key']
                require(p.resolve().is_relative_to(self.backend.root) and not any(q.is_symlink() or (hasattr(q,'is_junction') and q.is_junction()) for q in [p,*p.parents]),'Linked test object preserved')
                with file_lock(p.with_suffix('.lock'),timeout=0):
                    require(p.is_file() and hash_file(p)==(e['sha256'],e['bytes']),'Candidate changed immediately before simulation','revision_conflict');p.unlink()
                if fail_after_delete:raise StorageError('network_unavailable','Synthetic interruption after unlink; durable intent retained')
                journal['deleted'].append(e['key']);journal['pending']=None;write(path,journal)
            journal.update(state='completed',pending=None);write(path,journal);return journal

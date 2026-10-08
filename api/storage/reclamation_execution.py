"""Runnable exact execution/receipt/reconciliation; production adapter disabled."""
import base64,json,os
from pathlib import Path
from .core import StorageError,hash_file,file_lock
from .backends import LocalObjectBackend
from .release_control import read,write,digest,canonical
from .snapshot_policy import timestamp
from .reclamation import require

def verify_plan(plan):
    body=dict(plan);sha=body.pop('plan_sha256');require(digest(body)==sha,'Frozen plan digest differs','checksum_mismatch');return sha

def authorize(plan,approval,now):
    require(set(approval)=={'format','execute','target','plan_sha256','max_objects','max_bytes','approved_by','approved_at','expires_at'},'Exact explicit execution approval required','permission_denied')
    require(approval['format']=='litlib-gc-authorization-v1' and approval['execute'] is True and approval['approved_by'],'Execution not authorized','permission_denied')
    require(approval['plan_sha256']==verify_plan(plan) and approval['target']==plan['target'],'Approval does not bind exact plan/target','permission_denied')
    require(type(approval['max_objects']) is int and type(approval['max_bytes']) is int and approval['max_objects']==len(plan['candidates']) and approval['max_bytes']==plan['total_unique_bytes'],'Approval object/byte summary differs','permission_denied')
    require(timestamp(approval['approved_at'])<=timestamp(now)<=timestamp(approval['expires_at']),'Execution approval expired','permission_denied')

def persist(path,value):
    """Atomic replace, fsync before publication; lock files are never removed."""
    p=Path(path);temp=p.with_name(p.name+'.next')
    with temp.open('w',encoding='utf-8',newline='\n') as f:f.write(canonical(value));f.flush();os.fsync(f.fileno())
    os.replace(temp,p)

def frozen(path,value):
    p=Path(path)
    if p.exists():require(read(p)==value,'Immutable receipt differs','revision_conflict');return
    with p.open('x',encoding='utf-8') as f:f.write(canonical(value));f.flush();os.fsync(f.fileno())

def verify_journal(journal,plan,approval):
    require(set(journal)=={'format','plan_sha256','authorization_sha256','events','state','completed_at'} and journal['format']=='litlib-gc-execution-journal-v1','Unknown execution journal')
    require(journal['plan_sha256']==verify_plan(plan) and journal['authorization_sha256']==digest(approval) and journal['state'] in {'running','completed'},'Journal binding differs','revision_conflict')
    keys={e['key'] for e in plan['candidates']};previous='0'*64;done=[];pending=None
    for index,event in enumerate(journal['events']):
        body=dict(event);sha=body.pop('sha256')
        require(set(body)=={'sequence','previous','key','phase','at'} and body['sequence']==index and body['previous']==previous and digest(body)==sha,'Execution journal chain corrupt','checksum_mismatch')
        timestamp(body['at']);key=body['key'];require(key in keys,'Journal object outside frozen plan');phase=body['phase']
        if phase=='intent':require(pending is None and key not in done,'Duplicate or unresolved delete intent');pending=key
        elif phase in {'deleted','recovered_absent'}:require(pending==key,'Outcome lacks exact prior intent');done.append(key);pending=None
        else:raise StorageError('configuration_error','Unknown execution event phase')
        previous=sha
    if journal['state']=='completed':require(pending is None and set(done)==keys and journal['completed_at'],'Incomplete completed journal')
    return done,pending

def verify_receipt(receipt):
    require(set(receipt)=={'format','adapter','completed_at','plan','authorization','journal','reclaimed_versions'} and receipt['format']=='litlib-gc-receipt-v1' and receipt['adapter']=='local-test-exact-v1','Unknown trusted reclamation receipt')
    plan=receipt['plan'];authorize(plan,receipt['authorization'],receipt['completed_at']);done,pending=verify_journal(receipt['journal'],plan,receipt['authorization'])
    require(plan['target']['kind']=='local' and '/test/' in plan['target']['namespace'],'Production receipt adapter is disabled','permission_denied')
    require(receipt['journal']['state']=='completed' and receipt['journal']['completed_at']==receipt['completed_at'] and pending is None and set(done)=={e['key'] for e in plan['candidates']},'Receipt incomplete')
    expected=sorted({json.loads(base64.b64decode(plan['manifest_cache'][e['key']]))['release_id'] for e in plan['candidates'] if e['key'] in plan['manifest_cache']})
    require(receipt['reclaimed_versions']==expected,'Receipt version closure differs');return receipt

def ledger(catalog,target,budget):
    """Catalog-anchored immutable receipt hashes, not a claim of human approval."""
    cached={};deleted=set();versions={};proofs=[];seen=set()
    for entry in catalog.get('reclamations',[]):
        require(set(entry)=={'path','sha256'} and entry['sha256'] not in seen,'Duplicate/unknown receipt anchor');seen.add(entry['sha256'])
        p=Path(entry['path']);require(p.is_absolute() and p.is_file() and not p.is_symlink() and p.stat().st_size<=budget,'Receipt archive unavailable/budget exceeded')
        require(hash_file(p)[0]==entry['sha256'],'Anchored reclamation receipt changed','checksum_mismatch');receipt=verify_receipt(read(p));plan=receipt['plan']
        require(plan['target']==target,'Receipt belongs to another backend')
        for key,value in plan['manifest_cache'].items():require(key not in cached or cached[key]==value,'Manifest archive conflict');cached[key]=value
        deleted.update(e['key'] for e in plan['candidates'])
        for version in receipt['reclaimed_versions']:versions.setdefault(version,set()).add(entry['sha256'])
        proofs.append(entry)
    return cached,deleted,versions,proofs

class DisabledProductionDeletion:
    def delete_exact(self,entry):raise StorageError('permission_denied','Production deletion is disabled; no OSS request made')

class LocalExactDeletion:
    def __init__(self,planner):
        require(isinstance(planner.backend,LocalObjectBackend) and '/test/' in planner.ns.root,'Production deletion is disabled; no OSS request made','permission_denied');self.backend=planner.backend
    def delete_exact(self,entry):
        p=self.backend.root/entry['key']
        require(p.resolve().is_relative_to(self.backend.root) and not any(q.is_symlink() or (hasattr(q,'is_junction') and q.is_junction()) for q in [p,*p.parents]),'Linked object preserved')
        with file_lock(p.with_suffix('.lock'),timeout=0):
            require(p.is_file() and hash_file(p)==(entry['sha256'],entry['bytes']),'Object drift before exact delete','revision_conflict');p.unlink()

class ReclamationExecution:
    def __init__(self,planner):self.planner=planner
    def execute(self,plan,approval,journal_path,receipt_path,*,now,simulate_local=False,fault=None):
        # No environment flag can enable production. Check before any guard/read.
        require(simulate_local,'Explicit local simulation required; production deletion disabled','permission_denied');adapter=LocalExactDeletion(self.planner)
        authorize(plan,approval,now);journal_path=Path(journal_path);receipt_path=Path(receipt_path)
        require(journal_path.is_absolute() and receipt_path.is_absolute() and journal_path!=receipt_path,'Explicit distinct durable control paths required')
        with self.planner.guard(),file_lock(journal_path.with_suffix('.lock'),timeout=0):
            journal=read(journal_path) if journal_path.exists() else {'format':'litlib-gc-execution-journal-v1','plan_sha256':plan['plan_sha256'],'authorization_sha256':digest(approval),'events':[],'state':'running','completed_at':None}
            done,pending=verify_journal(journal,plan,approval);missing=list(done)
            if pending:
                try:self.planner.backend.size(pending)
                except StorageError as error:
                    if error.code!='not_found':raise
                    missing.append(pending)
            self.planner.validate(plan,now=now,deleted=missing)
            def event(key,phase):
                body={'sequence':len(journal['events']),'previous':journal['events'][-1]['sha256'] if journal['events'] else '0'*64,'key':key,'phase':phase,'at':now};journal['events'].append(dict(body,sha256=digest(body)));persist(journal_path,journal)
            if pending and pending in missing:event(pending,'recovered_absent');done.append(pending);pending=None
            for entry in sorted(plan['candidates'],key=lambda e:(e['key'] in plan['manifest_cache'],e['key'])):
                if entry['key'] in done:continue
                require(self.planner.capture(cached=plan['manifest_cache'],deleted=done)['fingerprint']==plan['root_fingerprint'],'Roots drift before delete','revision_conflict')
                if pending!=entry['key']:event(entry['key'],'intent')
                adapter.delete_exact(entry)
                if fault:fault('after_delete',entry)
                event(entry['key'],'deleted');done.append(entry['key']);pending=None
            if journal['state']!='completed':journal.update(state='completed',completed_at=now);persist(journal_path,journal)
            receipt={'format':'litlib-gc-receipt-v1','adapter':'local-test-exact-v1','completed_at':journal['completed_at'],'plan':plan,'authorization':approval,'journal':journal,'reclaimed_versions':sorted({json.loads(base64.b64decode(plan['manifest_cache'][e['key']]))['release_id'] for e in plan['candidates'] if e['key'] in plan['manifest_cache']})}
            verify_receipt(receipt);frozen(receipt_path,receipt);return receipt

    def reconcile(self,receipt_path,*,fault=None):
        LocalExactDeletion(self.planner) # no production metadata reconciliation
        path=Path(receipt_path);require(path.is_absolute() and path.is_file(),'Exact receipt archive required');receipt=verify_receipt(read(path));plan=receipt['plan']
        require(plan['target']==self.planner.target,'Receipt target differs');anchor={'path':str(path),'sha256':hash_file(path)[0]}
        with self.planner.guard():
            catalog=read(self.planner.catalog);anchors=catalog.get('reclamations',[])
            if anchor in anchors:
                ledger(catalog,self.planner.target,self.planner.budget);return {'state':'reconciled','receipt_sha256':anchor['sha256'],'idempotent':True}
            require(self.planner.capture(cached=plan['manifest_cache'],deleted=[e['key'] for e in plan['candidates']])['fingerprint']==plan['root_fingerprint'],'Catalog/root drift before reconciliation','revision_conflict')
            for e in plan['candidates']:
                try:self.planner.backend.size(e['key'])
                except StorageError as error:
                    if error.code=='not_found':continue
                    raise
                raise StorageError('revision_conflict','Deleted object reappeared before reconciliation')
            for v in catalog['versions']:
                if v['id'] in receipt['reclaimed_versions']:
                    require(v['state']=='retired' and v['manifest_key'] in {e['key'] for e in plan['candidates']},'Only exact retired manifest can be reconciled');v.update(state='reclaimed',reclamation_sha256=anchor['sha256'])
            catalog['reclamations']=[*anchors,anchor]
            if fault:fault('before_catalog_commit',None)
            persist(self.planner.catalog,catalog)
            return {'state':'reconciled','receipt_sha256':anchor['sha256'],'idempotent':False}

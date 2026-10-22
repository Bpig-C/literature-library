"""Thin authenticated HTTP CLI; no local SQLite or service implementation."""
import argparse,hashlib,json,os,sys,tempfile,ssl
from pathlib import Path
from urllib.parse import urlsplit,quote,urlencode
from urllib.request import Request,urlopen,HTTPRedirectHandler,HTTPSHandler,build_opener
from urllib.error import HTTPError

CLIENT_PROTOCOL_VERSION = 1


def check_version(opener, base, headers, timeout, *, expected_commit=None, required=()):
    try:
        with opener.open(Request(base+'/api/remote/version',headers=headers),timeout=timeout) as response:
            body=response.read(65537)
            if len(body)>65536:raise ValueError('Version response exceeds client budget')
            server=json.loads(body)
    except HTTPError as error:
        if error.code!=404:raise
        return {'compatible':False,'reason':'Server does not publish capabilities; update the server or inspect /api/research/schema','client_protocol_version':CLIENT_PROTOCOL_VERSION},2
    compatible=(server.get('format')=='litlib-client-capabilities-v1' and server.get('protocol_version')==CLIENT_PROTOCOL_VERSION)
    missing=[name for name in required if name not in server.get('capabilities',{})]
    matches=expected_commit is None or server.get('code_commit')==expected_commit
    ok=compatible and not missing and matches
    return {'compatible':ok,'client_protocol_version':CLIENT_PROTOCOL_VERSION,'server':server,
            'missing_capabilities':missing,'expected_commit':expected_commit,'commit_matches':matches},0 if ok else 2

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('Redirect refused; authentication stays at the configured authority')

def base_url(value):
    u=urlsplit(value)
    if u.username or u.password or u.query or u.fragment or u.path not in ('','/') or not u.hostname:
        raise ValueError('Explicit authority URL required')
    if u.scheme!='https' and not (u.scheme=='http' and u.hostname in ('127.0.0.1','localhost','::1')):
        raise ValueError('HTTPS required except isolated loopback')
    return value.rstrip('/')


def tls_context(ca_file=None):
    path=Path(ca_file).expanduser() if ca_file else Path(__file__).resolve().with_name('ca.crt')
    if ca_file or path.exists():
        if not path.is_file():raise ValueError('CA certificate file is missing: '+str(path))
        return ssl.create_default_context(cafile=str(path))
    return ssl.create_default_context()

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--server',required=True);p.add_argument('--timeout',type=float,default=30)
    p.add_argument('--ca-file',help='Private CA file; defaults to ca.crt beside this script, otherwise system trust')
    s=p.add_subparsers(dest='command',required=True)
    q=s.add_parser('check-version',help='Read server commit and capabilities; exit 2 if incompatible')
    q.add_argument('--expected-commit');q.add_argument('--require-capability',action='append',default=[])
    q=s.add_parser('request');q.add_argument('path');q.add_argument('--method',choices=['GET','POST','PUT','PATCH','DELETE'],default='GET');q.add_argument('--json-file');q.add_argument('--allow-write',action='store_true')
    q=s.add_parser('asset');q.add_argument('identity');q.add_argument('--role',required=True);q.add_argument('--version',required=True,type=int);q.add_argument('--output');q.add_argument('--max-bytes',required=True,type=int)
    q=s.add_parser('lookup',help='Check if a local PDF is already ingested (pure query, no upload)')
    q.add_argument('--file',type=Path,help='Local PDF to hash and look up')
    q.add_argument('--sha256',help='Pre-computed SHA256 hex')
    q.add_argument('--doi');q.add_argument('--arxiv-id');q.add_argument('--title')
    q.add_argument('--limit',type=int,default=10)
    q=s.add_parser('guide',help='Read the versioned foundation client guide')
    q=s.add_parser('intake');sub=q.add_subparsers(dest='action',required=True)
    r=sub.add_parser('reconcile');r.add_argument('--manifest',type=Path,required=True)
    q=s.add_parser('backup');sub=q.add_subparsers(dest='action',required=True)
    sub.add_parser('status')
    r=sub.add_parser('request');r.add_argument('--request-id',required=True);r.add_argument('--execute',action='store_true')
    r=sub.add_parser('job');r.add_argument('--job-id',required=True)
    q=s.add_parser('parse');sub=q.add_subparsers(dest='action',required=True)
    r=sub.add_parser('plan');r.add_argument('--backend',choices=['vlm','pymupdf'],required=True)
    r.add_argument('--work-id',action='append',default=[]);r.add_argument('--source-file-id',action='append',default=[])
    r.add_argument('--request-id',action='append',default=[]);r.add_argument('--purpose')
    r.add_argument('--from-time');r.add_argument('--to-time')
    r.add_argument('--time-field',choices=['work_created','source_imported','purpose_created'],default='source_imported')
    r.add_argument('--source-policy',choices=['single','all'],default='single')
    r.add_argument('--reparse-completed',action='store_true');r.add_argument('--output',type=Path,required=True)
    r=sub.add_parser('run');r.add_argument('--plan',type=Path,required=True);r.add_argument('--request-id',required=True)
    r.add_argument('--max-items',type=int,required=True);r.add_argument('--max-submissions',type=int,required=True)
    r.add_argument('--max-pages',type=int);r.add_argument('--execute',action='store_true')
    r=sub.add_parser('continue');r.add_argument('--plan-id',required=True);r.add_argument('--steps',type=int,default=1);r.add_argument('--execute',action='store_true')
    r=sub.add_parser('status');g=r.add_mutually_exclusive_group(required=True);g.add_argument('--plan-id');g.add_argument('--job-id')
    r=sub.add_parser('resume');r.add_argument('--job-id',required=True);r.add_argument('--execute',action='store_true')
    r=sub.add_parser('recover');r.add_argument('--job-id',required=True);r.add_argument('--execute',action='store_true')
    r=sub.add_parser('abandon');r.add_argument('--plan-id',required=True);r.add_argument('--position',type=int,required=True)
    r.add_argument('--reason',required=True);r.add_argument('--job-id');r.add_argument('--execute',action='store_true')
    a=p.parse_args(argv);base=base_url(a.server);token=os.environ.get('LITLIB_REMOTE_TOKEN','')
    if len(token)<32:raise ValueError('LITLIB_REMOTE_TOKEN must be supplied in process environment')
    headers={'Authorization':'Bearer '+token};opener=build_opener(NoRedirect,HTTPSHandler(context=tls_context(a.ca_file)))
    if a.command in ('parse','backup','intake','guide'):
        def request(path,body=None,*,extra=None):
            h={**headers,**(extra or {})}
            if body is not None:h['Content-Type']='application/json'
            with opener.open(Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=h),timeout=a.timeout) as response:
                data=response.read(8*1024*1024+1)
                if len(data)>8*1024*1024:raise ValueError('response exceeds client budget')
                return json.loads(data)
        needed={'parse':'parse_plans_v1','intake':'intake_reconcile_v1','backup':'backup_jobs_v1','guide':'foundation_guide_v1'}[a.command]
        if a.command=='parse' and a.action=='abandon':needed='parse_resolution_v1'
        version,code=check_version(opener,base,headers,a.timeout,required=[needed])
        if code:print(json.dumps(version,ensure_ascii=False));return code
        def output(value):print(json.dumps(value,ensure_ascii=False,indent=2),flush=True)
        if a.command=='guide':
            result=request('/api/remote/foundation-guide')
            if hashlib.sha256(result['text'].encode()).hexdigest()!=result['sha256']:raise ValueError('guide SHA differs')
            print(result['text']);return 0
        if a.command=='intake':output(request('/api/intake/reconcile',json.loads(a.manifest.read_text('utf-8-sig'))));return 0
        if a.command=='backup':
            if a.action=='status':result=request('/api/remote/backup-status')
            elif a.action=='job':result=request('/api/remote/backup-jobs/'+quote(a.job_id,safe=''))
            else:
                if not a.execute:raise ValueError('backup request requires --execute; host worker performs maintenance')
                admin=os.environ.get('LITLIB_BACKUP_ADMIN_TOKEN','')
                if len(admin)<32:raise ValueError('dedicated LITLIB_BACKUP_ADMIN_TOKEN required')
                result=request('/api/remote/backup-jobs',{'request_id':a.request_id},extra={'X-Litlib-Backup-Token':admin})
            output(result);return 0
        if a.action=='plan':
            if a.output.exists():raise ValueError('output already exists; refusing overwrite')
            result=request('/api/parse/plan',dict(backend=a.backend,work_ids=a.work_id,source_file_ids=a.source_file_id,
                request_ids=a.request_id,purpose=a.purpose,from_time=a.from_time,to_time=a.to_time,time_field=a.time_field,
                source_policy=a.source_policy,reparse_completed=a.reparse_completed))
            with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
            output({'plan_file':str(a.output),'sha256':result['sha256'],'counts':result['counts'],'excluded':result['excluded']});return 0
        if a.action=='status':
            path='/api/parse/plans/'+quote(a.plan_id,safe='') if a.plan_id else '/api/parse/jobs?'+urlencode({'job_id':a.job_id})
            output(request(path));return 0
        if not a.execute:raise ValueError('explicit --execute required')
        if a.action=='abandon':
            output(request('/api/parse/plans/'+quote(a.plan_id,safe='')+'/abandon',
                           dict(position=a.position,reason=a.reason,job_id=a.job_id,force=True)));return 0
        if a.action in ('resume','recover'):output(request('/api/parse/'+a.action,{'job_id':a.job_id,'force':True}));return 0
        if a.action=='run':
            result=request('/api/parse/plans',dict(plan=json.loads(a.plan.read_text('utf-8-sig')),request_id=a.request_id,
                           max_items=a.max_items,max_submissions=a.max_submissions,max_pages=a.max_pages))
            pid=result['plan_id'];steps=a.max_items
            output(result)  # Durable plan ID is printed before any long parse request.
        else:pid=a.plan_id;steps=a.steps
        if not 1<=steps<=1000:raise ValueError('steps must be 1..1000')
        for _ in range(steps):
            result=request('/api/parse/plans/'+quote(pid,safe='')+'/step',{})
            output(result)
            if result['action']!='progress':return 0 if result['action']=='complete' else 3
        return 0
    if a.command=='check-version':
        result,status=check_version(opener,base,headers,a.timeout,expected_commit=a.expected_commit,required=a.require_capability)
        print(json.dumps(result,ensure_ascii=False))
        return status
    if a.command=='request':
        if not a.path.startswith('/api/') or '\\' in a.path or '..' in a.path or urlsplit(a.path).netloc:raise ValueError('Existing /api/ relative endpoint required')
        if a.method!='GET' and not a.allow_write:raise ValueError('Explicit --allow-write required; business gates still apply')
        if a.json_file and a.method=='GET':raise ValueError('GET body refused')
        data=None
        if a.json_file:data=json.dumps(json.loads(Path(a.json_file).read_text('utf-8'))).encode();headers['Content-Type']='application/json'
        with opener.open(Request(base+a.path,data=data,headers=headers,method=a.method),timeout=a.timeout) as r:
            body=r.read(8*1024*1024+1)
            if len(body)>8*1024*1024:raise ValueError('JSON response exceeds client budget')
            sys.stdout.buffer.write(body)
        return 0
    if a.command=='lookup':
        payload={}
        if a.file:
            if not a.file.is_file():raise ValueError(f'file not found: {a.file}')
            h=hashlib.sha256()
            with a.file.open('rb') as f:
                while b:=f.read(1<<20):h.update(b)
            payload['content_sha256']=h.hexdigest()
        elif a.sha256:
            payload['content_sha256']=a.sha256.strip().lower()
        if a.doi:payload['doi']=a.doi.strip()
        if a.arxiv_id:payload['arxiv_id']=a.arxiv_id.strip()
        if a.title:payload['title']=a.title.strip()
        payload['limit']=a.limit
        if not any(k in payload for k in ('content_sha256','doi','arxiv_id','title')):
            raise ValueError('provide --file, --sha256, --doi, --arxiv-id, or --title')
        data=json.dumps(payload).encode();headers['Content-Type']='application/json'
        req=Request(base+'/api/duplicates/lookup',data=data,headers=headers,method='POST')
        with opener.open(req,timeout=a.timeout) as r:
            result=json.loads(r.read(1*1024*1024))
        print(json.dumps(result,ensure_ascii=False,indent=2))
        # exit code: 0=found (any tier), 1=not found, 2=error
        if result.get('status')=='not_found':return 1
        return 0
    if a.version<1 or a.max_bytes<1:raise ValueError('Positive fixed version and explicit transfer budget required')
    path='/api/remote/assets/'+quote(a.identity,safe='')+'?'+urlencode({'role':a.role,'version':a.version})
    with opener.open(Request(base+path+'&metadata=true',headers=headers),timeout=a.timeout) as r:m=json.loads(r.read(8192))
    if m['bytes']>a.max_bytes:raise ValueError('Asset exceeds transfer budget')
    out=Path(a.output).resolve() if a.output else None
    if out and out.exists():raise ValueError('Output exists; refusing overwrite')
    # Spool before returning bytes/path so consumers never receive unverified content.
    with tempfile.TemporaryFile() as f:
        h=hashlib.sha256();size=0
        with opener.open(Request(base+path,headers=headers),timeout=a.timeout) as r:
            while b:=r.read(1024*1024):
                size+=len(b)
                if size>min(a.max_bytes,m['bytes']):raise ValueError('Transfer exceeds pinned size')
                h.update(b);f.write(b)
        if size!=m['bytes'] or h.hexdigest()!=m['sha256']:raise ValueError('Fixed asset SHA or size mismatch')
        f.seek(0)
        if out:
            with out.open('xb') as target:
                while b:=f.read(1024*1024):target.write(b)
            print(json.dumps({'path':str(out),'sha256':m['sha256'],'bytes':size,'version':a.version}))
        else:
            while b:=f.read(1024*1024):sys.stdout.buffer.write(b)
    return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:print(json.dumps({'ok':False,'error':str(e)}),file=sys.stderr);raise SystemExit(1)

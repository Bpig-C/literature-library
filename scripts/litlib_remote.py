"""Thin authenticated HTTP CLI; no local SQLite or service implementation."""
import argparse,hashlib,json,os,sys,tempfile
from pathlib import Path
from urllib.parse import urlsplit,quote,urlencode
from urllib.request import Request,urlopen,HTTPRedirectHandler,build_opener

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('Redirect refused; authentication stays at the configured authority')

def base_url(value):
    u=urlsplit(value)
    if u.username or u.password or u.query or u.fragment or u.path not in ('','/') or not u.hostname:
        raise ValueError('Explicit authority URL required')
    if u.scheme!='https' and not (u.scheme=='http' and u.hostname in ('127.0.0.1','localhost','::1')):
        raise ValueError('HTTPS required except isolated loopback')
    return value.rstrip('/')

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--server',required=True);p.add_argument('--timeout',type=float,default=30)
    s=p.add_subparsers(dest='command',required=True)
    q=s.add_parser('request');q.add_argument('path');q.add_argument('--method',choices=['GET','POST','PUT','PATCH','DELETE'],default='GET');q.add_argument('--json-file');q.add_argument('--allow-write',action='store_true')
    q=s.add_parser('asset');q.add_argument('identity');q.add_argument('--role',required=True);q.add_argument('--version',required=True,type=int);q.add_argument('--output');q.add_argument('--max-bytes',required=True,type=int)
    a=p.parse_args(argv);base=base_url(a.server);token=os.environ.get('LITLIB_REMOTE_TOKEN','')
    if len(token)<32:raise ValueError('LITLIB_REMOTE_TOKEN must be supplied in process environment')
    headers={'Authorization':'Bearer '+token};opener=build_opener(NoRedirect)
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

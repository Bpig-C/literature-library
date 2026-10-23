"""Independent, bounded parse worker; never launched by an HTTP request."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import subprocess
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.parse_queue import Queue, Limits, enabled
from api.storage.authority import configured_authority
from api.storage.runtime import configured_service,required_path


def verify_executor():
    code=Path(__file__).resolve().parents[1]
    manifest=required_path('LITLIB_LIBRARY_ROOT').parent.parent/'release-manifest.json'
    if not manifest.is_file():raise ValueError('restored runtime manifest required')
    expected=json.loads(manifest.read_text('utf-8'))['code']['commit']
    actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=code).decode().strip()
    if actual!=expected or subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=code).strip():
        raise ValueError('worker must use clean code at the exact restored runtime commit')


class Driver:
    def cloud(self,event):
        from api.routes.parse import _load_env_file
        _load_env_file()
        from core.mineru.cloud_client import CloudClient
        client=CloudClient();client.on_progress=event;return client

    def request(self,pdf,out,language=''):
        from api.routes import parse  # initializes parser import path
        from core.mineru.base_client import ParseRequest
        from core.mineru.router import map_mineru_language
        return ParseRequest(pdf_path=Path(pdf),output_dir=Path(out),backend='vlm',lang_list=map_mineru_language(language))

    def pages(self,pdf):
        import fitz
        with fitz.open(str(pdf)) as doc:return doc.page_count

    def create_batch(self,files,language,remember):
        from api.routes import parse
        from core.mineru.router import map_mineru_language
        return self.cloud(lambda *a,**k:None).create_upload_batch(files,map_mineru_language(language),remember)

    def query_batch(self,batch):return self.cloud(lambda *a,**k:None).query_batch(batch)

    def upload_file(self,url,pdf):return self.cloud(lambda *a,**k:None)._upload_file(url,Path(pdf))

    def download_url(self,pdf,out,url,event,maximum):
        client=self.cloud(event)
        client._materialize(url,Path(out),Path(pdf).stem,max_bytes=maximum)
        from core.mineru.router import _maybe_build_detail_assets
        _maybe_build_detail_assets(Path(pdf),Path(out))

    def submit(self,pdf,out,event,*,language=''):return self.cloud(event).submit_pdf(self.request(pdf,out,language))

    def poll(self,pdf,task,event):return self.cloud(event).poll_once(task,Path(pdf).with_suffix('.pdf').name)

    def download(self,pdf,out,task,event,maximum):
        self.cloud(event).download_existing(self.request(pdf,out),task,max_bytes=maximum)
        from core.mineru.router import _maybe_build_detail_assets
        _maybe_build_detail_assets(Path(pdf),Path(out))

    def local(self,pdf,out,event,*,language=''):
        from api.routes.parse import _run_parse
        ok,msg,backend,task=_run_parse(str(pdf),out,language,backend='pymupdf')
        if not ok:
            from api.storage.core import StorageError
            raise StorageError('local_parse_failed','local parse failed; inspect task')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workers',type=int,default=1)
    p.add_argument('--once',action='store_true')
    p.add_argument('--configure',type=Path,help='Trusted host JSON: Limits fields only')
    p.add_argument('--maintenance',choices=['drain','snapshot','resume'])
    p.add_argument('--owner',default='host-operator')
    args=p.parse_args(argv)
    if not enabled():raise ValueError('LITLIB_ASYNC_PARSE_ENABLED=1 required')
    verify_executor()
    if not 1<=args.workers<=32:raise ValueError('workers must be 1..32')
    q=Queue(configured_service(),configured_authority())
    if args.configure:q.configure(Limits(**json.loads(args.configure.read_text('utf-8-sig'))));print(json.dumps(q.overview()));return
    if args.maintenance:print(json.dumps(q.maintenance(args.maintenance,args.owner)));return
    from api.upload_secrets import key
    key()  # independently provisioned; never embedded in snapshots
    from Crypto.Cipher import AES  # fail before claiming/POST if parser extra absent
    driver=Driver()
    def work():
        while True:
            try:result=q.run_one(driver)
            except Exception as error:
                print(json.dumps({'code':getattr(error,'code','worker_error')}),flush=True)
                if getattr(error,'code',None) in ('permission_denied','revision_conflict'):return
                if args.once:raise
                time.sleep(1);continue
            print(json.dumps(result,ensure_ascii=False),flush=True)
            if args.once:return
            if result['state']=='idle':time.sleep(1)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in [pool.submit(work) for _ in range(args.workers)]:future.result()


if __name__=='__main__':main()

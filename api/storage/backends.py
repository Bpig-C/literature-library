from __future__ import annotations
import os, uuid
from pathlib import Path
from .core import CHUNK, StorageError, copy_stream, file_lock, hash_file, relative_key

class LocalObjectBackend:
    """Offline backend with cooperative immutable publication, for isolated tests."""
    def __init__(self, root: Path): self.root=Path(root).resolve(); self.root.mkdir(parents=True,exist_ok=True)
    def path(self,key):
        relative_key(key); p=(self.root/key).resolve()
        if not p.is_relative_to(self.root): raise StorageError('invalid_request','object outside root')
        return p
    def download(self,key,destination,max_bytes=None):
        p=self.path(key)
        if not p.is_file(): raise StorageError('not_found','object absent')
        with p.open('rb') as source, open(destination,'wb') as target: copy_stream(source,target,max_bytes)
    def size(self,key):
        p=self.path(key)
        if not p.is_file(): raise StorageError('not_found','object absent')
        return p.stat().st_size
    def put_immutable(self,key,source):
        p=self.path(key); p.parent.mkdir(parents=True,exist_ok=True)
        with file_lock(p.with_suffix('.lock')):
            if p.exists(): raise StorageError('object_exists','object already exists')
            temp=p.with_name(p.name+'.'+uuid.uuid4().hex+'.part')
            try:
                with open(source,'rb') as src,temp.open('xb') as dst: copy_stream(src,dst); dst.flush(); os.fsync(dst.fileno())
                os.replace(temp,p)
            finally: temp.unlink(missing_ok=True)

class OSSBackend:
    """SDK v2 adapter: no catch-all absence, no credentials in errors/logs."""
    def __init__(self,client,bucket): self.client=client; self.bucket=bucket
    @staticmethod
    def translated(exc):
        # SDK v2 wraps service/transport errors in OperationError.
        seen=set()
        while type(exc).__name__ in {'OperationError','RequestError','ResponseError'} and id(exc) not in seen:
            seen.add(id(exc))
            inner=exc.unwrap()
            if not isinstance(inner,Exception):break
            exc=inner
        status=getattr(exc,'status_code',None); code=getattr(exc,'code','')
        if type(exc).__name__ in {'CredentialsEmptyError','CredentialsFetchError'}: return StorageError('permission_denied','object credentials unavailable')
        if status==404 or code=='NoSuchKey': return StorageError('not_found','object absent')
        if status in {401,403} or code in {'AccessDenied','InvalidAccessKeyId','SignatureDoesNotMatch'}: return StorageError('permission_denied','object access denied')
        if status==409 or code=='FileAlreadyExists': return StorageError('object_exists','immutable object exists')
        return StorageError('network_unavailable','object request failed; local pending preserved')
    def size(self,key):
        import alibabacloud_oss_v2 as oss
        try: return self.client.head_object(oss.HeadObjectRequest(bucket=self.bucket,key=key)).content_length
        except Exception as exc: raise self.translated(exc) from None
    def download(self,key,destination,max_bytes=None):
        import alibabacloud_oss_v2 as oss
        try:
            response=self.client.get_object(oss.GetObjectRequest(bucket=self.bucket,key=key))
            with open(destination,'wb') as dst:
                body=response.body
                try:
                    size=0
                    for chunk in body.iter_bytes(block_size=CHUNK):
                        size+=len(chunk)
                        if max_bytes is not None and size>max_bytes:raise StorageError('quota_exceeded','download exceeds reservation')
                        dst.write(chunk)
                finally: body.close()
        except StorageError: raise
        except Exception as exc: raise self.translated(exc) from None
    def put_immutable(self,key,source):
        import alibabacloud_oss_v2 as oss
        try:
            with open(source,'rb') as stream:
                self.client.put_object(oss.PutObjectRequest(bucket=self.bucket,key=key,body=stream,forbid_overwrite=True,acl='private'))
        except Exception as exc: raise self.translated(exc) from None

def oss_from_environment():
    import alibabacloud_oss_v2 as oss
    config=oss.config.load_default(); config.region=os.environ.get('LITLIB_OSS_REGION','cn-shanghai')
    config.connect_timeout=5;config.readwrite_timeout=15;config.retry_max_attempts=2
    config.credentials_provider=oss.credentials.EnvironmentVariableCredentialsProvider()
    # Credentials stay in process environment; no guide parsing or logging.
    return OSSBackend(oss.Client(config),os.environ['LITLIB_OSS_BUCKET'])

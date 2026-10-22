"""Authenticated transport over existing business routes and storage bindings."""
import hmac,os
from fastapi import APIRouter,HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from .storage.runtime import configured_service
from .storage.response import PinnedFileResponse

# Issue #9 and foundation pure queries bypass the write gate and
# authority write_guard. Only exact paths are exempted; query params and
# trailing slashes are normalised before matching.
_READ_ONLY_POST_PATHS = frozenset({'/api/duplicates/lookup', '/api/parse/plan', '/api/intake/reconcile'})

class RemoteAuthentication(BaseHTTPMiddleware):
    async def dispatch(self,request,call_next):
        token=os.environ.get('LITLIB_REMOTE_TOKEN')
        path=request.url.path.rstrip('/') or request.url.path
        is_read_only_post = request.method=='POST' and path in _READ_ONLY_POST_PATHS
        if os.environ.get('LITLIB_REMOTE_ENABLED')=='1':
            if not token or len(token)<32:
                return JSONResponse({'detail':'Remote authentication unavailable'},status_code=503)
            supplied=request.headers.get('Authorization','')
            if not hmac.compare_digest(supplied,'Bearer '+token):
                return JSONResponse({'detail':'Authentication required'},status_code=401)
            if request.method not in {'GET','HEAD','OPTIONS'} and not is_read_only_post and os.environ.get('LITLIB_REMOTE_WRITE_ENABLED')!='1':
                return JSONResponse({'detail':'Remote writes disabled on this runtime'},status_code=403)
        elif request.url.path.startswith('/api/remote/'):
            return JSONResponse({'detail':'Remote access disabled'},status_code=503)
        if request.method not in {'GET','HEAD','OPTIONS'} and not is_read_only_post and os.environ.get('LITLIB_STORAGE_MODE')=='immutable':
            from .storage.authority import configured_authority
            from .storage.core import StorageError
            try:
                with configured_authority().write_guard():return await call_next(request)
            except StorageError as e:
                if e.code=='busy':
                    return JSONResponse(
                        {'code':'busy','detail':str(e),'retry_after':5},
                        status_code=409,
                        headers={'Retry-After':'5'})
                return JSONResponse({'code':e.code,'detail':str(e)},status_code=409 if e.code=='revision_conflict' else 503)
        return await call_next(request)

router=APIRouter()
@router.get('/remote/version')
def remote_version():
    from .remote_version import version_info
    return JSONResponse(version_info(),headers={'Cache-Control':'no-store'})

@router.get('/remote/backups')
def backup_versions():
    from .storage.backup_discovery import discover_remote
    service=configured_service();return discover_remote(service.backend,service.ns.root)
@router.get('/remote/assets/{identity}')
def asset(identity:str,role:str,version:int,metadata:bool=False):
    if version<1:raise HTTPException(400,'Positive fixed version required')
    service=configured_service();binding=service.registry.binding(identity,role,version)
    if metadata:return {k:binding[k] for k in ('identity','role','version','sha256','bytes')}
    return PinnedFileResponse(service.read(identity,role,version),'application/octet-stream',
        headers={'X-Litlib-SHA256':binding['sha256'],'X-Litlib-Bytes':str(binding['bytes']),'Cache-Control':'no-store'})

"""Authenticated transport over existing business routes and storage bindings."""
import hmac,os
from fastapi import APIRouter,HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from .storage.runtime import configured_service
from .storage.response import PinnedFileResponse

class RemoteAuthentication(BaseHTTPMiddleware):
    async def dispatch(self,request,call_next):
        token=os.environ.get('LITLIB_REMOTE_TOKEN')
        if os.environ.get('LITLIB_REMOTE_ENABLED')=='1':
            if not token or len(token)<32:
                return JSONResponse({'detail':'Remote authentication unavailable'},status_code=503)
            supplied=request.headers.get('Authorization','')
            if not hmac.compare_digest(supplied,'Bearer '+token):
                return JSONResponse({'detail':'Authentication required'},status_code=401)
            if request.method not in {'GET','HEAD','OPTIONS'} and os.environ.get('LITLIB_REMOTE_WRITE_ENABLED')!='1':
                return JSONResponse({'detail':'Remote writes disabled on this runtime'},status_code=403)
        elif request.url.path.startswith('/api/remote/'):
            return JSONResponse({'detail':'Remote access disabled'},status_code=503)
        return await call_next(request)

router=APIRouter()
@router.get('/remote/assets/{identity}')
def asset(identity:str,role:str,version:int,metadata:bool=False):
    if version<1:raise HTTPException(400,'Positive fixed version required')
    service=configured_service();binding=service.registry.binding(identity,role,version)
    if metadata:return {k:binding[k] for k in ('identity','role','version','sha256','bytes')}
    return PinnedFileResponse(service.read(identity,role,version),'application/octet-stream',
        headers={'X-Litlib-SHA256':binding['sha256'],'X-Litlib-Bytes':str(binding['bytes']),'Cache-Control':'no-store'})

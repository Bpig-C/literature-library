from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
import anyio

class PinnedFileResponse(FileResponse):
    """Acquire before headers; release pin on success, exception or disconnect."""
    def __init__(self,context,media_type,headers=None):
        self.context=context
        super().__init__('registered-asset',media_type=media_type,headers=headers,content_disposition_type='inline')
    async def __call__(self,scope,receive,send):
        entered=False
        try:
            with anyio.CancelScope(shield=True):
                path=await run_in_threadpool(self.context.__enter__);entered=True;self.path=str(path)
            await super().__call__(scope,receive,send)
        finally:
            if entered:self.context.__exit__(None,None,None)

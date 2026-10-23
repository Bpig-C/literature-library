"""Short authority transactions for background producers.

Network/CPU work runs outside the guard. Every catalog mutation, including
storage staging/operation bookkeeping, checks the current lease inside the
same transaction. Unreferenced immutable uploads from a stale worker are safe.
"""
from contextlib import contextmanager,ExitStack
import time
from .core import StorageError


@contextmanager
def short_guard(authority,timeout=5):
    """Retry brief write contention outside the guard, never replay a body."""
    deadline=time.monotonic()+timeout
    with ExitStack() as stack:
        while True:
            try:
                stack.enter_context(authority.write_guard());break
            except StorageError as error:
                if error.code!='busy' or time.monotonic()>=deadline:raise
                time.sleep(.01)
        yield


class FencedRegistry:
    def __init__(self, registry, authority, validate):
        self.base=registry;self.authority=authority;self.validate=validate

    def __getattr__(self,name):return getattr(self.base,name)

    @contextmanager
    def conn(self, write=False, *, read_only=False):
        if not write:
            with self.base.conn(read_only=True) as conn:yield conn
            return
        with short_guard(self.authority), self.base.conn(write=True) as conn:
            self.validate(conn)
            yield conn

"""Independent cookies on one application loop and one owned ASGI lifespan.

Nested clients borrow the owner portal, just like concurrent network clients
use one server. A distinct application still owns a distinct lifespan/loop.
"""
from fastapi.testclient import TestClient as BaseClient


class TestClient(BaseClient):
    def __enter__(self):
        owner = getattr(self.app,'_test_lifespan_client',None)
        self._owns_lifespan = owner is None
        if self._owns_lifespan:
            super().__enter__()
            self.app._test_lifespan_client = self
        else:
            self.portal = owner.portal
        return self

    def __exit__(self,*args):
        if self._owns_lifespan:
            try:
                return super().__exit__(*args)
            finally:
                del self.app._test_lifespan_client
        try:
            self.close()
        finally:
            self.portal = None

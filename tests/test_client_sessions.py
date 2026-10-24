"""Nested accounts behave as network clients of one server lifecycle."""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI,Request
from client_sessions import TestClient


def test_borrowed_clients_share_service_loop_but_not_identity_or_lifespan():
    counters = dict(start=0,stop=0)
    @asynccontextmanager
    async def lifecycle(app):
        counters['start'] += 1
        try:yield
        finally:counters['stop'] += 1
    app = FastAPI(lifespan=lifecycle)
    @app.get('/')
    async def info(request:Request):
        return dict(loop=id(asyncio.get_running_loop()),identity=request.cookies.get('identity'))
    with TestClient(app) as first:
        first.cookies.set('identity','first')
        with TestClient(app) as second:
            second.cookies.set('identity','second')
            a,b = first.get('/').json(),second.get('/').json()
            assert a['loop']==b['loop']
            assert a['identity']=='first' and b['identity']=='second'
            assert counters==dict(start=1,stop=0)
        assert first.get('/').json()==a
        assert counters==dict(start=1,stop=0)
    assert counters==dict(start=1,stop=1)
    with TestClient(app) as restarted:
        assert restarted.get('/').json()['identity'] is None
    assert counters==dict(start=2,stop=2)

"""A35: revoke a prepared private HTTP response before it leaves middleware."""
import asyncio
import uuid
import httpx
import pytest
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from backend import session_scope
from test_core_integration import env
from test_scene_groups import setup, scope, send


@pytest.mark.parametrize('kind',['events','room','character','replay','my-rooms'])
def test_delayed_old_scope_response_is_rejected_after_public_split(env,kind):
    a,b,store,rid,host,guest=setup(env)
    state=store.get(rid)
    previous=state['version']
    item={'id':len(state['events'])+1,'kind':'dm','text':'OLD_SCOPE_TOKEN'}
    session_scope.stamp_event(state,item,audience={guest})
    state['events'].append(item)
    state['version']+=1
    store.save(state,previous)
    own=a.get(f'/api/rooms/{rid}').json()
    replay_body=None
    if kind=='replay':
        frame=b.get(f'/api/rooms/{rid}').json()
        replay_body={'command_id':uuid.uuid4().hex,'type':'chat','payload':{'text':'Prior action'},'expected_version':frame['version'],
                     'expected_action_revision':frame['action_revision'],'expected_scene_instance_id':frame['scene_instance_id'],'expected_membership_epoch':frame['membership_epoch']}
        assert b.post(f'/api/rooms/{rid}/commands',json=replay_body).status_code==200
    path={'events':f'/api/rooms/{rid}/events','room':f'/api/rooms/{rid}',
          'character':f'/api/rooms/{rid}/characters/{host}','replay':f'/api/rooms/{rid}/commands','my-rooms':'/api/my/rooms'}[kind]
    app=a.app
    async def run():
        reached,release=asyncio.Event(),asyncio.Event()
        held={'used':False}
        async def gate(request,call_next):
            response=await call_next(request)
            if request.url.path==path and not held['used']:
                held['used']=True
                assert response.status_code==200
                reached.set()
                await release.wait()
            return response
        index=next(n for n,middleware in enumerate(app.user_middleware) if middleware.kwargs.get('dispatch').__name__=='headers')
        app.user_middleware.insert(index+1,Middleware(BaseHTTPMiddleware,dispatch=gate))
        app.middleware_stack=None
        transport=httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,base_url='http://testserver',cookies=a.cookies,headers={'X-CSRF-Token':a.headers['X-CSRF-Token']}) as first, httpx.AsyncClient(transport=transport,base_url='http://testserver',cookies=b.cookies,headers={'X-CSRF-Token':b.headers['X-CSRF-Token']}) as second:
            delayed=asyncio.create_task(second.post(path,json=replay_body) if replay_body else second.get(path))
            await asyncio.wait_for(reached.wait(),5)
            plan=await first.post(f'/api/rooms/{rid}/groups/prepare',json={'operation':'split','members':[guest],'expected_scope':scope(own)})
            assert plan.status_code==200,plan.text
            moved=await first.post(f'/api/rooms/{rid}/groups/commit',json={'plan_id':plan.json()['plan_id'],'command_id':uuid.uuid4().hex})
            assert moved.status_code==200,moved.text
            release.set()
            result=await asyncio.wait_for(delayed,5)
            assert result.status_code==409,result.text
            assert result.json()['retry_same_command'] is True
            assert 'OLD_SCOPE_TOKEN' not in result.text
            assert result.headers['Cache-Control']=='no-store'
            if replay_body:
                retried=await second.post(path,json=replay_body)
                assert retried.status_code==200 and retried.json()['replayed']
                assert 'OLD_SCOPE_TOKEN' not in retried.text
            assert 'OLD_SCOPE_TOKEN' not in (await second.get(f'/api/rooms/{rid}/events')).text
    asyncio.run(run())

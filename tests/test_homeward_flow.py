"""No state injection: account, build, public scene commands, ending and reuse."""
import uuid
import pytest

from backend import rules, progression
from backend.homeward import BOOK_ID
from test_character_setup_api import app, account, build, command


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()['room']


def settle(client, rid, action, skill=None):
    payload = dict(action_id=action)
    if skill: payload['skill_id'] = skill
    frame = ok(command(client,rid,'capability_propose',payload))
    proposal = frame['director_proposals'][0]
    cid = uuid.uuid4().hex
    response = command(client,rid,'director_resolve',dict(proposal_id=proposal['id']),command_id=cid)
    frame = ok(response)
    replay = command(client,rid,'director_resolve',dict(proposal_id=proposal['id']),command_id=cid)
    assert replay.status_code == 200 and replay.json()['replayed']
    return frame


def check(client,rid,node,skill):
    return settle(client,rid,'story-check:resolve-'+node,skill)


def route(client,rid,id):
    return settle(client,rid,'story-route:'+id)


@pytest.mark.parametrize('players,success,final,mode',[(1,True,'light','xp'),(4,True,'oath','xp'),
    (2,False,'light','xp'),(1,False,'oath','milestone'),(1,False,'evacuation','xp')])
def test_normal_accounts_complete_first_adventure(app,monkeypatch,players,success,final,mode):
    clients = [account(app,'homeward_'+str(i)) for i in range(players)]
    host = clients[0]
    catalog = host.get('/api/content?kind=scenario').json()['items']
    assert any(b['id']==BOOK_ID for b in catalog)
    created = host.post('/api/rooms',json=dict(player_name='引航者',scenario_id=BOOK_ID,progression_mode=mode))
    assert created.status_code == 201,created.text
    session = created.json()
    rid = session['room']['id']
    for i,client in enumerate(clients):
        if i:
            joined = client.post('/api/rooms/join',json=dict(invite_code=session['invite_code'],player_name='同伴'+str(i)))
            assert joined.status_code == 200,joined.text
        ok(command(client,rid,'configure_character',dict(build=build())))
    assert len(ok(command(host,rid,'start'))['party'])==players
    # Deterministic dice exercise both valid result paths; no model or DB edits.
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:n-1 if success else 0)
    for node,skill,next_route in [('dock','perception','dock-market'),('market','investigation','market-customs'),
        ('customs','investigation','customs-lens'),('lens','investigation','lens-council')]:
        before = host.get('/api/rooms/'+rid).json()
        ok(command(clients[-1],rid,'chat',dict(text='先商量方法，再提交行动。')))
        assert host.get('/api/rooms/'+rid).json()['action_revision']==before['action_revision']
        check(clients[-1],rid,node,skill)
        route(host,rid,next_route)
    if players==4:
        route(host,rid,'choose-saltpath')
        check(clients[-1],rid,'saltpath','perception')
        battle = route(host,rid,'saltpath-guard')
        assert battle['combat']['active']
        # Public turn ownership, attack and end-turn until the authored foe falls.
        seats = {p['id']:c for p,c in zip(battle['party'],clients)}
        for _ in range(40):
            battle = host.get('/api/rooms/'+rid).json()
            if not battle['combat']['active']:break
            actor = battle['combat']['turn_actor_id']
            actor_client = seats[actor]
            if not battle['combat']['action_used']:
                target = next(e['id'] for e in battle['combat']['enemies'] if e['hp']>0)
                response = command(actor_client,rid,'action',dict(action_id='attack',target_id=target))
                proposal = ok(response)['director_proposals'][0]
                ok(command(actor_client,rid,'director_resolve',dict(proposal_id=proposal['id'])))
            if host.get('/api/rooms/'+rid).json()['combat']['active']:
                ok(command(actor_client,rid,'end_turn'))
        assert not host.get('/api/rooms/'+rid).json()['combat']['active']
        route(host,rid,'guard-bridge')
    else:
        route(host,rid,'choose-winch')
        check(host,rid,'winch','athletics')
        route(host,rid,'winch-bridge')
    check(host,rid,'bridge','perception')
    route(host,rid,'bridge-shelter')
    # A new storage reader sees exactly the committed cursor and check receipts.
    from backend.store import Store
    restored = Store(app.state.store.path).get(rid)
    assert restored['campaign']['node_id']=='shelter'
    assert len(restored['campaign']['story_state']['effect_receipts'])==6
    route(host,rid,'shelter-tower')
    check(clients[-1],rid,'tower','persuasion')
    route(host,rid,'tower-decision')
    route(host,rid,'choose-'+final)
    if final!='evacuation':
        check(host,rid,final,'arcana')
        ending = 'dawn' if success else 'vigil'
        ended = route(host,rid,final+'-'+ending)
    else:
        ending,ended='evacuation',host.get('/api/rooms/'+rid).json()
    assert ended['status']=='finished' and ended['scene']['id']==ending
    saved = app.state.store.get(rid)
    reward_id = 'objective:ending:'+BOOK_ID
    assert saved['reward_ledger'].count(reward_id)==1
    assert progression.award(saved,restored)==[]  # ledger, even with old before-state
    heroes = host.get('/api/my/characters').json()['items']
    hero = heroes[0]
    if mode=='milestone':assert hero['character']['milestone_credits']==1
    else:assert hero['character']['xp']>=1200  # starting level 3 = 900, ending +300
    reused = host.post('/api/rooms',json=dict(player_name='再次出发',hero_id=hero['id'],scenario_id=BOOK_ID))
    assert reused.status_code==201,reused.text


def test_offline_optional_branch_survives_restart_and_can_be_skipped(app,monkeypatch):
    host = account(app,'restart_traveler')
    created = host.post('/api/rooms',json=dict(player_name='归客',scenario_id=BOOK_ID)).json()
    rid = created['room']['id']
    ok(command(host,rid,'configure_character',dict(build=build())))
    ok(command(host,rid,'start'))
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:n-1)
    check(host,rid,'dock','perception'); route(host,rid,'dock-market')
    check(host,rid,'market','investigation'); route(host,rid,'market-customs')
    check(host,rid,'customs','investigation')
    waiting = route(host,rid,'follow-courier')
    assert waiting['route_wait']['status']=='unavailable' and waiting['scene']['id']=='customs'
    before = app.state.store.get(rid)
    cookies = dict(host.cookies)
    path = app.state.store.path
    app.state.test_clients.close()  # real lifespan shutdown before reopening DB
    from backend.app import create_app
    from client_sessions import TestClient
    with TestClient(create_app(path)) as restored:
        restored.cookies.update(cookies)
        restored.headers['X-CSRF-Token'] = restored.get('/api/auth/me').json()['csrf_token']
        frame = restored.get('/api/rooms/'+rid).json()
        assert frame['route_wait']['status']=='unavailable' and frame['scene']['id']=='customs'
        assert restored.app.state.store.get(rid)['campaign']['story_state']==before['campaign']['story_state']
        ok(command(restored,rid,'chat',dict(text='先继续预写主线。')))
        settle(restored,rid,'story-cancel')
        frame = route(restored,rid,'customs-lens')
        assert frame['scene']['id']=='lens' and frame['route_wait'] is None
        assert not restored.app.state.store.get(rid)['reward_ledger']

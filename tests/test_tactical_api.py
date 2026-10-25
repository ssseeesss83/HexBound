from copy import deepcopy
import uuid
from test_v09_release import release_setup,setup
from test_product_flow import publish,room,command


def test_real_grid_entry_confirm_replay_restart_and_enemy_turn(release_setup,monkeypatch):
    app,client,admin=release_setup
    monkeypatch.setattr('backend.rules.secrets.randbelow',lambda n:n-1)
    publish(client,admin,'scenario',dict(id='grid-api',name='战棋验收',entry_node_id='field',monster_ids=['salt-warden'],nodes=[
        dict(id='field',title='战场',text='穿过石柱，击败守卫。',battlefield=dict(walls=[dict(x=5,y=4)]),monster_ids=['salt-warden'],actions=[dict(id='exit',label='离开',next_node_id='end')]),
        dict(id='end',title='结束',text='安全抵达。',ending=True)]))
    session=room(client,scenario_id='grid-api');rid=session['room']['id'];actor=session['member_id']
    start=command(client,session,'start');assert start.status_code==200,start.text
    b=start.json()['room']['battlefield'];assert b['cell_feet']==5 and b['positions'][actor]==dict(x=1,y=1)
    bad=command(client,session,'capability_propose',dict(action_id='attack',target_id='enemy:0:salt-warden'))
    assert bad.status_code==422
    response=command(client,session,'capability_propose',dict(action_id='grid:move',destination=dict(x=4,y=1)))
    assert response.status_code==200,response.text
    proposal=response.json()['room']['director_proposals'][0]
    before=deepcopy(app.state.store.get(rid)['combat']['board'])
    assert before['positions'][actor]==dict(x=1,y=1)
    current=response.json()['room'];cid=uuid.uuid4().hex
    body=dict(type='director_resolve',payload=dict(proposal_id=proposal['id']),command_id=cid,expected_version=current['version'])
    headers=dict(Authorization='Bearer '+session['token'])
    response=client.post('/api/rooms/'+rid+'/commands',headers=headers,json=body);assert response.status_code==200,response.text
    settled=app.state.store.get(rid)['combat']['board']
    assert settled['positions'][actor]==dict(x=4,y=1)
    replay=client.post('/api/rooms/'+rid+'/commands',headers=headers,json=body)
    assert replay.status_code==200 and replay.json()['replayed']
    from backend.store import Store
    assert Store(app.state.store.path).get(rid)['combat']['board']==settled
    ended=command(client,session,'end_turn');assert ended.status_code==200,ended.text
    assert ended.json()['room']['battlefield']['positions'][actor]==settled['positions'][actor]
    assert any(e['text'].startswith('DM：') for e in ended.json()['room']['events'])


def test_default_campaign_puzzle_to_grid_uses_public_commands(release_setup,monkeypatch):
    app,client,admin=release_setup
    monkeypatch.setattr('backend.rules.secrets.randbelow',lambda n:n-1)
    session=room(client,scenario_id='book-eight-beacons');rid=session['room']['id']
    assert command(client,session,'start').status_code==200
    def enact(action,**options):
        response=command(client,session,'capability_propose',dict(action_id=action,**options))
        assert response.status_code==200,response.text
        p=response.json()['room']['director_proposals'][0]
        resolved=command(client,session,'director_resolve',dict(proposal_id=p['id']))
        assert resolved.status_code==200,resolved.text
        return resolved.json()['room']
    enact('story-route:next-chapter-1')
    view=enact('story-puzzle:puzzle-1:medicine')
    assert view['scene']['id']=='chapter-1'
    view=enact('story-route:enter-1-1')
    assert view['scene']['id']=='encounter-1-1' and view['battlefield']
    assert len(view['combat']['enemies'])==2
    assert all(e['source_id'] for e in view['combat']['enemies'])
    view=enact('grid:move',destination=dict(x=4,y=1))
    assert view['battlefield']['positions'][session['member_id']]==dict(x=4,y=1)
    from backend.store import Store
    assert Store(app.state.store.path).get(rid)['combat']['board']['positions'][session['member_id']]==dict(x=4,y=1)

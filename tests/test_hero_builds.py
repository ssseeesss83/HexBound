import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend import characters as c
from backend.character_builds import prepare_level


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('HEXBOUND_ALLOW_GUESTS', raising=False)
    app = create_app(str(tmp_path / 'builds.sqlite3'))
    with TestClient(app) as client:
        result = client.post('/api/auth/register', json={'username':'builder', 'password':'Correct-Horse-Secret-123!', 'display_name':'造物者'})
        assert result.status_code in (200,201)
        client.headers['X-CSRF-Token'] = client.get('/api/auth/me').json()['csrf_token']
        yield client, app.state.store


def build(level=3):
    return {'class_id':'fighter','name':'夜卫','choices':{'skills':['athletics','history']},
            'levels':[{'choices':{}}, {'choices':{'subclass_id':'champion'}}][:level-1]}


def test_create_rebuild_high_level_and_version(client):
    api,_ = client
    result=api.post('/api/my/characters',json={'build':build(),'starting_level':3})
    assert result.status_code==201, result.text
    hero=result.json()
    assert hero['can_rebuild'] and hero['build']==build()
    assert hero['character']['level']==3
    patch={'expected_version':hero['version'],'operation':'rebuild','build':build(1),'starting_level':1}
    result=api.patch('/api/my/characters/'+hero['id'],json=patch)
    assert result.status_code==200, result.text
    assert result.json()['character']['level']==1
    assert api.patch('/api/my/characters/'+hero['id'],json=patch).status_code==409


def test_bound_or_used_hero_cannot_reset(client):
    api,store=client
    hero=api.post('/api/my/characters',json={'build':build(1)}).json()
    with store.connect() as db:
        payload=json.loads(db.execute('SELECT payload FROM heroes WHERE id=?',(hero['id'],)).fetchone()['payload'])
        payload['hp']-=1
        db.execute('UPDATE heroes SET payload=? WHERE id=?',(json.dumps(payload),hero['id']))
    assert not api.get('/api/my/characters/'+hero['id']).json()['can_rebuild']
    patch={'expected_version':hero['version'],'operation':'rebuild','build':build(1)}
    assert api.patch('/api/my/characters/'+hero['id'],json=patch).status_code==409
    with store.connect() as db:
        db.execute('UPDATE heroes SET active_room_id=? WHERE id=?',('room-history',hero['id']))
    assert api.patch('/api/my/characters/'+hero['id'],json=patch).status_code==409


def test_legacy_creation_and_build_rejections(client):
    api,_=client
    hero=api.post('/api/my/characters',json={'class_id':'fighter','name':'旧入口'})
    assert hero.status_code==201 and hero.json()['can_rebuild']
    for payload in ({'build':build(1),'starting_level':3}, {'class_id':'fighter','name':'缺升级','starting_level':3}, {'build':{**build(1),'xp':999}}, {'build':build(1),'class_id':'wizard'}):
        assert api.post('/api/my/characters',json=payload).status_code==422


def test_prepare_level_preserves_spent_resources_injuries_and_credits():
    character=c.create_character('fighter')
    character['hp']-=3
    character['resources']['second-wind']['current']=0
    character['milestone_credits']=7
    original=deepcopy(character)
    result=prepare_level(character,{})
    assert character==original
    assert result['level']==2 and result['xp']==300
    assert result['max_hp']-result['hp']==3
    assert result['resources']['second-wind']['current']==0
    assert result['milestone_credits']==7
    with pytest.raises(ValueError,match='显式选择'):
        prepare_level(result,{})
    with pytest.raises(ValueError):
        prepare_level(result,{'xp':900})


def test_historical_adventure_prevents_unbound_rebuild(client):
    api,store=client
    hero=api.post('/api/my/characters',json={'build':build(1)}).json()
    with store.connect() as db:
        state={'status':'finished','members':[{'hero_id':hero['id']}]}
        db.execute('INSERT INTO rooms VALUES(?,?,?,?)',('old-room','OLD123',1,json.dumps(state)))
    assert not api.get('/api/my/characters/'+hero['id']).json()['can_rebuild']
    result=api.patch('/api/my/characters/'+hero['id'],json={'operation':'rebuild','expected_version':hero['version'],'build':build(1)})
    assert result.status_code==409

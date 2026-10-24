import copy
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.dm import DM
from backend.schemas import parse_card
from backend.store import Store
from backend.studio import ContentService, FORMAT, compile_scenario, create_studio_router


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXBOUND_ADMIN_TOKEN", "studio-test-secret")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    store = Store(str(tmp_path / "studio.sqlite3"))
    from backend.rules_packages import install_package, build_legacy_package
    install_package(store, build_legacy_package())
    dm = DM()
    app = FastAPI()
    app.include_router(create_studio_router(store, dm))
    with TestClient(app) as client:
        yield client, store, dm


AUTH = {"Authorization": "Bearer studio-test-secret"}


def test_graph_draft_is_separate_revision_checked_and_can_publish(setup):
    client, store, _ = setup
    original = client.get('/api/studio/items/book-last-lantern', headers=AUTH).json()
    package = compile_scenario(store, original['id'])
    body = {'expected_revision': original['revision'], 'id': 'graph-copy'}
    assert client.post(f"/api/studio/items/{original['id']}/graph-draft", json=body).status_code == 401
    stale = {**body, 'expected_revision': original['revision']+1}
    assert client.post(f"/api/studio/items/{original['id']}/graph-draft", headers=AUTH, json=stale).status_code == 409
    response = client.post(f"/api/studio/items/{original['id']}/graph-draft", headers=AUTH, json=body)
    assert response.status_code == 201, response.text
    graph = response.json()
    assert graph['draft']['schema_version'] == 2 and graph['published'] is None
    assert graph['revision'] == 1 and graph['id'] == 'graph-copy'
    assert client.get(f"/api/studio/items/{original['id']}", headers=AUTH).json() == original
    assert compile_scenario(store, original['id']) == package
    result = client.post('/api/studio/items/graph-copy/validate', headers=AUTH).json()
    assert result['valid'] and not result['warnings']
    assert publish(client, graph).status_code == 200
    assert any(x['id'] == 'graph-copy' for x in client.get('/api/content').json()['items'])
    assert client.post(f"/api/studio/items/{original['id']}/graph-draft", headers=AUTH, json=body).status_code == 409
    # Defense in depth checks the full frozen dependency package.
    from backend.campaign import validate_package
    with pytest.raises(ValueError, match='规则包'):
        validate_package({'scenario': graph['draft'], 'skills': {}, 'monsters': {}})
    validate_package(compile_scenario(store, 'graph-copy'))


def test_graph_drafts_can_save_incomplete_topology_validate_and_round_trip(setup):
    client, _, _ = setup
    original = client.get('/api/studio/items/book-last-lantern', headers=AUTH).json()
    graph = client.post('/api/studio/items/book-last-lantern/graph-draft', headers=AUTH,
        json={'expected_revision': original['revision'], 'id': 'graph-edit'}).json()
    changed = copy.deepcopy(graph['draft'])
    changed['outline'] = 'New outline'
    changed['edges'][0]['to'] = 'not-written-yet'
    edited = client.put('/api/studio/items/graph-edit', headers=AUTH,
                       json={'expected_revision': 1, 'data': changed})
    assert edited.status_code == 200, edited.text
    result = client.post('/api/studio/items/graph-edit/validate', headers=AUTH).json()
    assert not result['valid'] and any('不存在' in issue or '旧行动' in issue for issue in result['issues'])
    exported = client.post('/api/studio/export', headers=AUTH, json={'ids': ['graph-edit']}).json()
    graph_row = next(row for row in exported['items'] if row['data']['id'] == 'graph-edit')
    assert graph_row['data'] == edited.json()['draft']
    graph_row['data']['id'] = 'graph-imported'
    # Dependencies already exist: import only the independent graph draft.
    imported = client.post('/api/studio/import', headers=AUTH,
                          json={'package': {'format': FORMAT, 'items': [graph_row]}})
    assert imported.status_code == 422
    graph_row['data']['edges'] = graph['draft']['edges']
    imported = client.post('/api/studio/import', headers=AUTH,
                          json={'package': {'format': FORMAT, 'items': [graph_row]}})
    assert imported.status_code == 201, imported.text
    schema = client.get('/api/studio/schema/scenario?schema_version=2', headers=AUTH).json()
    assert schema['properties']['schema_version']['const'] == 2
    assert client.get('/api/studio/schema/skill?schema_version=2', headers=AUTH).status_code == 422


def test_graph_draft_rejects_wrong_kind_and_unsafe_conditions_without_partial_write(setup):
    client, _, _ = setup
    skill_item = create(client, 'skill', skill())
    assert client.post('/api/studio/items/new-check/graph-draft', headers=AUTH,
        json={'expected_revision': skill_item['revision'], 'id': 'bad-graph'}).status_code == 422
    from test_story_graph import sparse
    draft = sparse()
    draft['edges'][0]['condition'] = {'op': 'eval', 'code': 'execute()'}
    assert client.post('/api/studio/items', headers=AUTH,
                       json={'kind': 'scenario', 'data': draft}).status_code == 422
    assert client.get('/api/studio/items/sparse', headers=AUTH).status_code == 404


def skill(id="new-check", **kwargs):
    return {"id": id, "name": "调查", "description": "调查场景", "tags": ["调查"], "effect": "check", "ability": "wis", "dice": "1d20", "bonus": 0, "dc": 12, "uses": None, "target": "scene", **kwargs}


def book(id="new-book", skill_id="new-check"):
    return {"id": id, "name": "新故事", "description": "公开摘要", "tags": ["测试"], "entry_node_id": "start", "skill_ids": [skill_id], "monster_ids": [], "nodes": [
        {"id": "start", "title": "入口", "text": "秘密正文不应公开", "actions": [{"id": "look", "label": "调查", "skill_id": skill_id, "success_node_id": "end", "failure_node_id": "end"}]},
        {"id": "end", "title": "终点", "text": "故事结局", "ending": True}]}


def create(client, kind, data):
    response = client.post("/api/studio/items", headers=AUTH, json={"kind": kind, "data": data})
    assert response.status_code == 201, response.text
    return response.json()


def publish(client, item):
    return client.post(f"/api/studio/items/{item['id']}/publish", headers=AUTH, json={"expected_revision": item["revision"]})


def test_admin_auth_and_public_secrecy(setup, monkeypatch):
    client, _, _ = setup
    assert client.get("/api/studio/items").status_code == 401
    assert client.get("/api/studio/items", headers={"Authorization": "Bearer room-member"}).status_code == 401
    public = client.get("/api/content?kind=scenario").json()
    assert public["items"] and "nodes" not in str(public)
    assert "published_revision" in public["items"][0]
    create(client, "skill", skill())
    assert all(item["id"] != "new-check" for item in client.get("/api/content?q=调查").json()["items"])
    monkeypatch.delenv("HEXBOUND_ADMIN_TOKEN")
    assert client.get("/api/studio/status").json()["legacy_write_enabled"] is False
    assert client.post("/api/studio/items", headers=AUTH, json={"kind": "skill", "data": skill("disabled")}).status_code == 503


def test_draft_publish_revision_and_history_restore(setup):
    client, _, _ = setup
    draft = create(client, "skill", skill())
    published = publish(client, draft).json()
    assert published["revision"] == 2 and published["published_revision"] == 2
    changed = {**draft["draft"], "name": "尚未发布的新名称"}
    edited = client.put("/api/studio/items/new-check", headers=AUTH, json={"expected_revision": 2, "data": changed}).json()
    assert edited["revision"] == 3 and edited["published"]["name"] == "调查"
    public = client.get("/api/content?tag=调查").json()["items"]
    assert next(item for item in public if item['id']=='new-check')["name"] == "调查"
    assert client.put("/api/studio/items/new-check", headers=AUTH, json={"expected_revision": 2, "data": changed}).status_code == 409
    history = client.get("/api/studio/items/new-check/history", headers=AUTH).json()["items"]
    assert [row["action"] for row in history] == ["update", "publish", "create"]
    restored = client.post("/api/studio/items/new-check/restore", headers=AUTH, json={"expected_revision": 3, "revision": 1}).json()
    assert restored["draft"]["name"] == "调查" and restored["published_revision"] == 2


def test_duplicate_is_unpublished_and_archive_preserves_history(setup):
    client, _, _ = setup
    copied = client.post("/api/studio/items/blade-strike/duplicate", headers=AUTH, json={"id": "blade-copy", "name": "副本"}).json()
    assert copied["published"] is None and copied["revision"] == 1
    archived = client.post("/api/studio/items/blade-copy/archive", headers=AUTH, json={"expected_revision": 1}).json()
    assert archived["archived"] and archived["revision"] == 2
    assert client.get("/api/studio/items?archived=true", headers=AUTH).json()["items"][0]["id"] == "blade-copy"
    assert publish(client, archived).status_code == 409
    assert client.get("/api/studio/items/blade-copy/history", headers=AUTH).status_code == 200


def test_publish_requires_published_references_and_valid_graph(setup):
    client, _, _ = setup
    dependency = create(client, "skill", skill())
    scenario = create(client, "scenario", book())
    result = client.post("/api/studio/items/new-book/validate", headers=AUTH).json()
    assert not result["valid"] and "new-check" in str(result["issues"])
    assert publish(client, scenario).status_code == 422
    assert publish(client, dependency).status_code == 200
    assert publish(client, scenario).status_code == 200
    broken = book("broken-book")
    broken["nodes"][0]["actions"][0]["success_node_id"] = "missing-node"
    broken["nodes"].append({"id": "unreachable", "title": "无路可达", "text": "秘密", "ending": True})
    item = create(client, "scenario", broken)
    validation = client.post("/api/studio/items/broken-book/validate", headers=AUTH).json()
    assert not validation["valid"] and "missing-node" in str(validation["issues"])
    assert publish(client, item).status_code == 422


def test_snapshot_is_immutable_and_dependency_archive_blocked(setup):
    client, store, _ = setup
    snapshot = compile_scenario(store, "book-last-lantern")
    snapshot["skills"]["blade-strike"]["bonus"] = 19
    fresh = compile_scenario(store, "book-last-lantern")
    assert fresh["skills"]["blade-strike"]["bonus"] == 0
    assert client.post("/api/studio/items/blade-strike/archive", headers=AUTH, json={"expected_revision": 1}).status_code == 409
    original = client.get("/api/studio/items/blade-strike", headers=AUTH).json()
    changed = {**original["draft"], "bonus": 5}
    updated = client.put("/api/studio/items/blade-strike", headers=AUTH, json={"expected_revision": 1, "data": changed}).json()
    assert publish(client, updated).status_code == 200
    assert fresh["skills"]["blade-strike"]["bonus"] == 0
    assert compile_scenario(store, "book-last-lantern")["skills"]["blade-strike"]["bonus"] == 5


def test_skill_changes_cannot_break_published_books(setup):
    client, _, _ = setup
    original = client.get("/api/studio/items/read-traces", headers=AUTH).json()
    changed = {**original["draft"], "effect": "attack", "target": "enemy"}
    updated = client.put("/api/studio/items/read-traces", headers=AUTH, json={"expected_revision": 1, "data": changed}).json()
    response = publish(client, updated)
    assert response.status_code == 422 and "check" in response.text


def test_limited_skill_only_exit_rejected(setup):
    client, _, _ = setup
    limited = create(client, "skill", skill(uses=1))
    assert publish(client, limited).status_code == 200
    scenario = create(client, "scenario", book())
    response = publish(client, scenario)
    assert response.status_code == 422 and "耗尽" in response.text


def test_import_export_dependencies_atomic_and_default_conflict_reject(setup):
    client, store, _ = setup
    package = {"format": FORMAT, "items": [{"kind": "scenario", "data": book()}, {"kind": "skill", "data": skill()}]}
    imported = client.post("/api/studio/import", headers=AUTH, json={"package": package})
    assert imported.status_code == 201 and imported.json()["total"] == 2
    assert all(item["published"] is None for item in imported.json()["items"])
    exported = client.post("/api/studio/export", headers=AUTH, json={"ids": ["new-book"]}).json()
    assert exported["format"] == FORMAT and len(exported["items"]) == 2
    conflict_package = copy.deepcopy(package)
    conflict_package["items"].append({"kind": "skill", "data": skill("must-not-exist")})
    assert client.post("/api/studio/import", headers=AUTH, json={"package": conflict_package}).status_code == 409
    assert client.get("/api/studio/items/must-not-exist", headers=AUTH).status_code == 404
    missing = {"format": FORMAT, "items": [{"kind": "skill", "data": skill("atomic-skill")}, {"kind": "scenario", "data": book("invalid-book", "absent-skill")}]}
    assert client.post("/api/studio/import", headers=AUTH, json={"package": missing}).status_code == 422
    assert client.get("/api/studio/items/atomic-skill", headers=AUTH).status_code == 404


def test_schema_rejects_code_invalid_dice_target_and_duplicate_nodes(setup):
    client, _, _ = setup
    for extra in ({"python": "import os"}, {"dice": "100d100"}, {"target": "enemy"}, {"uses": 0}):
        response = client.post("/api/studio/items", headers=AUTH, json={"kind": "skill", "data": skill(**extra)})
        assert response.status_code == 422, response.text
    invalid = book()
    invalid["nodes"].append(copy.deepcopy(invalid["nodes"][0]))
    assert client.post("/api/studio/items", headers=AUTH, json={"kind": "scenario", "data": invalid}).status_code == 422


def test_llm_draft_is_never_saved_or_published(setup):
    client, _, dm = setup
    assert client.post("/api/studio/generate", headers=AUTH, json={"kind": "skill", "prompt": "治疗技能"}).status_code == 503
    dm.configured = True
    async def generated(*args, **kwargs):
        return json.dumps(skill("llm-draft"))
    dm._complete = generated
    response = client.post("/api/studio/generate", headers=AUTH, json={"kind": "skill", "prompt": "新的调查技能"})
    assert response.status_code == 200
    assert response.json()["saved"] is False and response.json()["published"] is False
    assert client.get("/api/studio/items/llm-draft", headers=AUTH).status_code == 404


def test_sparse_graph_generation_validates_before_return_and_does_not_save(setup):
    client, _, dm = setup
    template = client.get('/api/studio/status').json()['author_graph_template']
    template['id'] = 'generated-sparse'
    dm.configured = True
    async def generated(system, data, json_mode, **kwargs):
        assert json_mode and kwargs['max_tokens'] == 4000
        assert data['schema']['properties']['rules_package_version']['const'] == template['rules_package_version']
        assert data['schema']['properties']['nodes']['maxItems'] == 12
        assert data['schema']['properties']['edges']['maxItems'] == 24
        assert '不穷举分支' in system
        return json.dumps(template)
    dm._complete = generated
    response = client.post('/api/studio/generate', headers=AUTH,
                           json={'kind':'scenario','schema_version':2,'prompt':'主线与续写出口'})
    assert response.status_code == 200, response.text
    assert response.json()['data'] == template
    assert response.json()['issues'] == [] and response.json()['saved'] is False
    assert client.get('/api/studio/items/generated-sparse', headers=AUTH).status_code == 404
    assert client.post('/api/studio/generate', headers=AUTH,
                       json={'kind':'skill','schema_version':2,'prompt':'invalid'}).status_code == 422


@pytest.mark.parametrize('failure', ['package','edition','fallback','mechanical_write','reference','condition','nodes','edges','frontier','legacy_action','legacy_attack'])
def test_invalid_generated_graph_never_becomes_an_author_draft(setup, failure):
    client, _, dm = setup
    template = client.get('/api/studio/status').json()['author_graph_template']
    template['id'] = 'bad-model-graph'
    if failure == 'package': template['rules_package_version'] = 'uninstalled-version'
    elif failure == 'edition': template['ruleset_id'] = 'dnd5e-2024'
    elif failure == 'fallback': template['nodes'][1]['continuation']['fallback_scene_id'] = 'missing'
    elif failure == 'mechanical_write': template['hp'] = 99
    elif failure == 'reference':
        template['monster_ids'] = ['unpublished-dragon']
        template['nodes'][0]['monster_ids'] = ['unpublished-dragon']
    elif failure == 'condition': template['edges'][0]['condition'] = {'op':'eval','code':'set_hp(99)'}
    elif failure == 'nodes':
        for index in range(11):
            template['nodes'].append({'id':f's{index}','kind':'scene','title':'Scene','text':'Scene'})
            template['edges'].append({'id':f'e{index}','from':'opening','to':f's{index}'})
            template['edges'].append({'id':f'exit{index}','from':f's{index}','to':'continuation'})
    elif failure == 'edges':
        template['edges'] += [{'id':f'e{i}','from':'opening','to':'continuation'} for i in range(24)]
    elif failure == 'frontier':
        template['nodes'][1] = {'id':'continuation','kind':'ending','title':'End','text':'Dawn'}
    else:
        skill_id = 'blade-strike' if failure == 'legacy_attack' else 'read-traces'
        template['skill_ids'] = [skill_id]
        template['nodes'][0]['legacy_actions'] = [{'id':'try','label':'Try','skill_id':skill_id,
            'success_node_id':'continuation','failure_node_id':'continuation'}]
        template['edges'] = [{'id':result,'from':'opening','to':'continuation',
            'legacy_action_id':'try','legacy_result':result} for result in ['success','failure']]
    dm.configured = True
    async def generated(*args, **kwargs): return json.dumps(template)
    dm._complete = generated
    response = client.post('/api/studio/generate', headers=AUTH,
                           json={'kind':'scenario','schema_version':2,'prompt':'不可信素材'})
    assert response.status_code == 502
    assert 'data' not in response.json()
    assert client.get('/api/studio/items/bad-model-graph', headers=AUTH).status_code == 404


def test_graph_author_legacy_checks_do_not_accept_attack_cards(setup):
    client, _, _ = setup
    template = client.get('/api/studio/status').json()['author_graph_template']
    template['id'] = 'author-wrong-check'
    template['skill_ids'] = ['blade-strike']
    template['nodes'][0]['legacy_actions'] = [{'id':'try','label':'Try','skill_id':'blade-strike',
        'success_node_id':'continuation','failure_node_id':'continuation'}]
    template['edges'] = [{'id':result,'from':'opening','to':'continuation',
        'legacy_action_id':'try','legacy_result':result} for result in ['success','failure']]
    assert client.post('/api/studio/items', headers=AUTH,json={'kind':'scenario','data':template}).status_code == 201
    result=client.post('/api/studio/items/author-wrong-check/validate',headers=AUTH).json()
    assert not result['valid'] and any('check 类型技能' in issue for issue in result['issues'])


def test_graph_generation_rechecks_auth_and_dependencies_after_model_returns(setup, monkeypatch):
    client, store, dm = setup
    template = client.get('/api/studio/status').json()['author_graph_template']
    dm.configured = True
    async def revoke(*args, **kwargs):
        monkeypatch.setenv('HEXBOUND_ADMIN_TOKEN','changed-during-generation')
        return json.dumps(template)
    dm._complete = revoke
    body = {'kind':'scenario','schema_version':2,'prompt':'主线'}
    assert client.post('/api/studio/generate', headers=AUTH,json=body).status_code == 401
    monkeypatch.setenv('HEXBOUND_ADMIN_TOKEN','studio-test-secret')
    template['monster_ids'] = ['salt-warden']
    template['nodes'][0]['monster_ids'] = ['salt-warden']
    async def archive_dependency(*args, **kwargs):
        with store.connect() as db:
            db.execute("UPDATE content_items SET archived=1 WHERE id='salt-warden'")
        return json.dumps(template)
    dm._complete = archive_dependency
    assert client.post('/api/studio/generate', headers=AUTH,json=body).status_code == 502


def test_seed_idempotent_and_graph_playable(setup):
    client, store, _ = setup
    before = client.get("/api/studio/items", headers=AUTH).json()["total"]
    ContentService(store)
    assert client.get("/api/studio/items", headers=AUTH).json()["total"] == before
    assert client.post("/api/studio/items/book-last-lantern/validate", headers=AUTH).json()["valid"]


def test_import_size_limit_before_any_write(setup):
    client, _, _ = setup
    huge = {"format": FORMAT, "items": [{"kind": "skill", "data": skill("oversized", description="x" * 2_000_001)}]}
    assert client.post("/api/studio/import", headers=AUTH, json={"package": huge}).status_code == 413
    assert client.get("/api/studio/items/oversized", headers=AUTH).status_code == 404


def test_seed_published_snapshot_runs_to_real_ending(setup, monkeypatch):
    from backend import campaign, content
    _, store, _ = setup
    monkeypatch.setattr(campaign.secrets, "randbelow", lambda n: n - 1)
    state = {**content.initialize_state(), "host_id": "hero", "members": [{"id": "hero", "name": "旅人", "character": content.new_character("fighter")}]}
    campaign.start_campaign(state, compile_scenario(store, "book-last-lantern"))
    for action in ("follow-traces", "read-ledger", "promise"):
        campaign.apply_action(state, "hero", "node:" + action)
    assert state["completed"] and state["scene"]["id"] == "dawn"

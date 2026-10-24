"""Release paths enter through published content and ordinary HTTP commands."""
from copy import deepcopy
import pytest

from backend.story_graph import migrate_legacy
from backend.rules_identity import LEGACY_PACKAGE
from test_product_flow import setup, publish, room, command


@pytest.fixture
def release_setup(setup, monkeypatch):
    monkeypatch.setenv('HEXBOUND_LEGACY_ADMIN_TOKEN', '1')
    monkeypatch.setenv('HEXBOUND_ALLOW_GUESTS', '1')
    return setup


def native_book(client, admin):
    original = client.get('/api/studio/items/book-last-lantern', headers=admin).json()['published']
    book = migrate_legacy(original)
    book['id'] = 'release-native'
    return book


def test_native_publish_compile_normal_start_and_routes(release_setup):
    app, client, admin = release_setup
    book = native_book(client, admin)
    publish(client, admin, 'scenario', book)
    session = room(client, scenario_id=book['id'])
    response = command(client, session, 'start')
    assert response.status_code == 200, response.text
    state = app.state.store.get(session['room']['id'])
    assert state['campaign']['runtime_graph']['graph_revision'] == 0
    assert state['campaign']['story_state']['facts'] == {}
    assert state['rules_package_version'] == LEGACY_PACKAGE
    assert state['campaign']['package']['rules_package_version'] == LEGACY_PACKAGE
    assert response.json()['room']['scene']['id'] == 'dock'
    assert 'runtime_graph' not in response.text


def test_native_unknown_rules_cannot_publish(release_setup):
    _, client, admin = release_setup
    book = native_book(client, admin)
    book['rules_package_version'] = 'uninstalled'
    created = client.post('/api/studio/items', headers=admin, json=dict(kind='scenario', data=book))
    assert created.status_code == 201
    result = client.post('/api/studio/items/release-native/publish', headers=admin,
                         json=dict(expected_revision=created.json()['revision']))
    assert result.status_code == 422 and '规则包未安装' in result.text



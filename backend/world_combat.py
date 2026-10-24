"""Creature authority adapter. Runtime hooks are admitted separately.

Pure migration does not execute initiative or enemy turns. Combat actor IDs stay
local, while physical state has one world entity owner.
"""
from copy import deepcopy
from . import world_state as world, world_environment as environment

META = {'entity_id', 'entity_revision'}


def _state(card):
    return {key: deepcopy(value) for key, value in card.items() if key not in META | {'id'}}


def _eid(pid, node_id, actor_id):
    return 'creature:' + pid + ':' + str(node_id) + ':' + actor_id


def _cards(combat):
    enemies = combat.get('enemies')
    if enemies is None:
        enemies = [combat['enemy']] if combat.get('enemy') else []
    if combat.get('enemy'):
        match = next((row for row in enemies if row['id'] == combat['enemy']['id']), None)
        if match != combat['enemy']:
            raise world.WorldConflict('旧战斗 enemy 与 enemies 状态冲突，需先核对')
    if len({row['id'] for row in enemies}) != len(enemies):
        raise world.WorldConflict('战斗参与者 ID 重复')
    return enemies


def migrate(canonical):
    room = deepcopy(canonical)
    world.initialize(room)
    observed = {}
    for sid, instance in room.get('scene_instances', {}).items():
        local = instance['local']
        combat = local.get('combat')
        if not combat or 'enemy_refs' in combat:
            continue
        pid = instance.get('place_id')
        if not pid:
            raise world.WorldConflict('战斗迁移缺少物理地点')
        cards = _cards(combat)
        if not cards and not combat.get('active'):
            continue
        refs = {}
        node_id = local.get('scene_id', combat.get('scene_id', 'legacy'))
        for card in cards:
            eid = _eid(pid, node_id, card['id'])
            state = _state(card)
            if eid in observed and observed[eid] != state:
                raise world.WorldConflict('旧战斗同一生物存在冲突副本：' + eid)
            observed[eid] = state
            if eid not in room['world_entities']:
                world.add_entity(room, eid, pid, 'creature', state,
                    {'node_id': node_id, 'actor_id': card['id'], 'monster_id': card.get('card_id'), 'migration': 'legacy_current_state'})
            elif room['world_entities'][eid]['state'] != state:
                raise world.WorldConflict('旧战斗与权威生物状态冲突：' + eid)
            refs[card['id']] = eid
        encounter = combat.get('encounter_id') or 'legacy:' + str(room.get('id')) + ':' + sid
        if combat.get('active'):
            actor = next((m['id'] for m in room.get('members', []) if room['member_contexts'][m['id']]['scene_instance_id'] == sid), None)
            living = [eid for eid in refs.values() if room['world_entities'][eid]['state'].get('hp', 0) > 0]
            if actor is None or not living:
                raise world.WorldConflict('活动旧战斗缺少合法成员或存活敌人')
            world.claim_encounter(room, actor, living, encounter, {eid: room['world_entities'][eid]['revision'] for eid in living})
        combat['encounter_id'] = encounter
        combat['enemy_refs'] = refs
        if combat.get('enemy'):
            combat['legacy_enemy_alias_id'] = combat['enemy']['id']
        combat.pop('enemy', None)
        combat.pop('enemies', None)
    room['world_combat_version'] = 1
    return room


def materialize(view):
    if view.get('world_combat_version') != 1:
        return view
    combat = view.get('combat') or {}
    read_set = {}
    if 'enemy_refs' in combat:
        enemies = []
        for actor_id, eid in combat['enemy_refs'].items():
            entity = view['world_entities'].get(eid)
            if not entity or entity['kind'] != 'creature':
                raise world.WorldConflict('战斗生物实体引用不存在')
            enemies.append({**deepcopy(entity['state']), 'id': actor_id, 'entity_id': eid, 'entity_revision': entity['revision']})
            read_set[eid] = entity['revision']
        combat['enemies'] = enemies
        if combat.get('legacy_enemy_alias_id'):
            combat['enemy'] = next(row for row in enemies if row['id'] == combat['legacy_enemy_alias_id'])
    view['_creature_read_set'] = read_set
    return view


def validate_read_set(view):
    if view.get('world_combat_version') != 1:
        return
    combat = view.get('combat') or {}
    sid = view.get('_scene_execution_view', 'scene-main')
    instance = view['scene_instances'][sid]
    place = view['world_places'][instance['place_id']]
    if place['active_encounter_id'] and place['encounter_owner_scene_id'] != sid:
        raise world.WorldConflict('当前地点已有另一队的活动遭遇；未执行随机检定或消耗')
    environment.validate_read_set(view)
    for eid in combat.get('enemy_refs', {}).values():
        entity = view['world_entities'].get(eid)
        if not entity or entity['revision'] != view.get('_creature_read_set', {}).get(eid):
            raise world.WorldConflict('战斗实体版本已变化；未执行随机检定或消耗')
        if entity['place_id'] != instance.get('place_id'):
            raise world.WorldConflict('战斗实体不属于当前地点')
    if combat.get('active'):
        place = view['world_places'][instance['place_id']]
        if place['active_encounter_id'] != combat.get('encounter_id') or place['encounter_owner_scene_id'] != sid:
            raise world.WorldConflict('当前场景没有该遭遇的执行权')


def commit_view(view):
    if view.get('world_combat_version') != 1:
        return view
    combat = view.get('combat') or {}
    if 'enemy_refs' not in combat:
        return view
    cards = _cards(combat)
    if {row['id'] for row in cards} != set(combat['enemy_refs']):
        raise world.WorldConflict('战斗参与者与实体清单不一致')
    sid = view.get('_scene_execution_view', 'scene-main')
    changes = {combat['enemy_refs'][row['id']]: _state(row) for row in cards
               if _state(row) != view['world_entities'][combat['enemy_refs'][row['id']]]['state']}
    place = view['world_places'][view['scene_instances'][sid]['place_id']]
    needs_release = not combat.get('active') and place['active_encounter_id'] == combat.get('encounter_id')
    if not changes and not needs_release:
        return view
    validate_read_set(view)
    actor = next((m['id'] for m in view.get('members', [])
                  if view['member_contexts'].get(m['id'], {}).get('scene_instance_id') == sid), None)
    if actor is None:
        raise world.WorldConflict('没有合法战斗成员')
    expected = {eid: view['_creature_read_set'][eid] for eid in changes}
    if changes:
        world.write_entities(view, actor, changes, expected, encounter_id=combat.get('encounter_id'))
    if needs_release:
        world.release_encounter(view, actor, combat['encounter_id'])
    for eid in combat['enemy_refs'].values():
        view['_creature_read_set'][eid] = view['world_entities'][eid]['revision']
    return view


def freeze(view):
    if view.get('world_combat_version') != 1:
        return view
    combat = view.get('combat') or {}
    if 'enemy_refs' in combat:
        cards = _cards(combat)
        if ('_creature_read_set' in view or 'enemies' in combat or 'enemy' in combat) and {row['id'] for row in cards} != set(combat['enemy_refs']):
            raise world.WorldConflict('战斗参与者与实体清单不一致')
        sid = view.get('_scene_execution_view', 'scene-main')
        place = view['world_places'][view['scene_instances'][sid]['place_id']]
        owns_lock = place['active_encounter_id'] == combat.get('encounter_id') and place['encounter_owner_scene_id'] == sid
        if bool(combat.get('active')) != owns_lock:
            raise world.WorldConflict('战斗活动状态与地点遭遇锁不一致，请先提交结算')
        for row in cards:
            eid = combat['enemy_refs'].get(row['id'])
            if not eid or _state(row) != view['world_entities'][eid]['state']:
                raise world.WorldConflict('战斗实体变更尚未按读取版本提交')
        combat.pop('enemies', None)
        combat.pop('enemy', None)
    view.pop('_creature_read_set', None)
    return view


def preflight_place(view, node_id):
    """Check a possible destination on a disposable copy before any roll."""
    if view.get('world_combat_version') != 1:
        return
    staged = deepcopy(view)
    sid = staged.get('_scene_execution_view', 'scene-main')
    instance = staged['scene_instances'][sid]
    # The execution view is current; the canonical local cache is not.
    instance['local']['combat'] = staged.get('combat')
    instance['local']['completed'] = staged.get('completed', False)
    instance['local']['action_revision'] = staged.get('action_revision', 0)
    pid = environment.place_id(staged, node_id)
    if pid not in staged['world_places']:
        world.add_place(staged, pid)
    actor = next((m['id'] for m in staged.get('members', [])), None)
    if actor is None:
        raise world.WorldConflict('场景没有合法成员')
    world.prepare_enter(staged, actor, pid)


def enter_place(view, node_id):
    if view.get('world_combat_version') != 1:
        return
    preflight_place(view, node_id)
    # Flush the old location before changing its identity or clearing combat.
    environment.commit_view(view)
    commit_view(view)
    sid = view.get('_scene_execution_view', 'scene-main')
    instance = view['scene_instances'][sid]
    instance['local']['combat'] = view.get('combat')
    instance['local']['completed'] = view.get('completed', False)
    instance['local']['action_revision'] = view.get('action_revision', 0)
    pid = environment.place_id(view, node_id)
    if pid not in view['world_places']:
        world.add_place(view, pid)
    actor = view['members'][0]['id']
    world.commit_enter(view, world.prepare_enter(view, actor, pid))


def begin(view, cards, *, spawn_key=None):
    """Reserve living physical spawns before the caller rolls initiative."""
    if view.get('world_combat_version') != 1:
        return deepcopy(cards), None
    import uuid
    if (view.get('combat') or {}).get('active'):
        raise world.WorldConflict('当前已有活动遭遇，不能重建先攻')
    sid = view.get('_scene_execution_view', 'scene-main')
    node_id = view.get('scene_id') or view.get('scene', {}).get('id', 'legacy')
    enter_place(view, node_id)
    pid = view['scene_instances'][sid]['place_id']
    living = []
    for card in cards:
        eid = _eid(pid, spawn_key or node_id, card['id'])
        if eid not in view['world_entities']:
            world.add_entity(view, eid, pid, 'creature', _state(card),
                {'node_id': node_id, 'spawn_key': spawn_key or node_id, 'actor_id': card['id'], 'monster_id': card.get('card_id')})
        entity = view['world_entities'][eid]
        if entity['state'].get('hp', 0) > 0:
            living.append({**deepcopy(entity['state']), 'id': card['id'], 'entity_id': eid, 'entity_revision': entity['revision']})
    if not living:
        return [], None
    encounter_id = uuid.uuid4().hex
    versions = {row['entity_id']: row['entity_revision'] for row in living}
    world.claim_encounter(view, view['members'][0]['id'], list(versions), encounter_id, versions)
    return living, encounter_id


def bind(view, encounter_id):
    if view.get('world_combat_version') != 1 or encounter_id is None:
        return
    combat = view['combat']
    combat['encounter_id'] = encounter_id
    combat['enemy_refs'] = {row['id']: row['entity_id'] for row in combat['enemies']}
    if combat.get('enemy'):
        combat['legacy_enemy_alias_id'] = combat['enemy']['id']
    view['_creature_read_set'] = {eid: view['world_entities'][eid]['revision'] for eid in combat['enemy_refs'].values()}

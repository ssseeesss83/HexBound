from copy import deepcopy
import pytest
from backend import beacons,story_graph,story_runtime,story_puzzles,story_transitions,campaign,progression,tactical,abilities,characters,director,enemy_dm,rules
from backend.schemas import parse_card
from backend.character_builds import build_character
from backend.rules_identity import LEGACY_PACKAGE,RULESET_ID
from test_character_setup_api import build
from test_scenario_plans import room
from backend.studio import seed_items


def package():
    return dict(scenario=beacons.book(),rules_package_version=LEGACY_PACKAGE,
        skills={c['id']:parse_card(k,c) for k,c in seed_items() if k=='skill'},
        monsters={c['id']:parse_card('monster',c) for c in beacons.presets()})


def test_content_counts_unique_sources_all_encounters_puzzles_and_bosses():
    p=package();book=p['scenario'];campaign.validate_package(p)
    fights=[n for n in book['nodes'] if n['monster_ids']]
    assert len(fights)==32 and len(p['monsters'])==36
    assert len({m['source_id'] for m in p['monsters'].values()})==36
    assert {id for n in fights for id in n['monster_ids']}==set(p['monsters'])
    assert len([n for n in fights if 'Boss' in n['title']])==8
    assert {n['battlefield']['mechanic'] for n in fights}>={'anchors','storm','drain','crossfire'}
    assert sum(len(n.get('puzzles',[])) for n in book['nodes'])==8
    assert story_graph.graph_issues(book)==[]


def state(players=1):
    s=room();s.update(rules_package_version=LEGACY_PACKAGE,ruleset_id=RULESET_ID)
    s['members']=[dict(id='p' if i==0 else 'p'+str(i),name='旅人'+str(i),character=build_character(build(),3)) for i in range(players)]
    for m in s['members']:m['character']['custom_skill_ids']=['blade-strike','field-mending','take-cover','beacon-hammer']
    campaign.start_campaign(s,package());return s


def enact(s,actor,action,options=None,target=None):
    before=deepcopy(s)
    proposal=director.propose_selected(s,actor,action,target,options)['proposal']
    director.resolve(s,actor,proposal)
    progression.award(s,before)


def test_reasoned_puzzle_success_no_roll_wrong_attempt_once(monkeypatch):
    s=state();enact(s,'p','story-route:next-chapter-1')
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('puzzle rolled'))
    before=s['members'][0]['character']['hp']
    enact(s,'p','story-puzzle:puzzle-1:grain')
    assert s['members'][0]['character']['hp']==before-2
    with pytest.raises(ValueError):enact(s,'p','story-puzzle:puzzle-1:grain')
    enact(s,'p','story-puzzle:puzzle-1:medicine')
    assert s['campaign']['story_state']['facts']['gate-1']['value'] is True
    with pytest.raises(ValueError):enact(s,'p','story-puzzle:puzzle-1:medicine')


@pytest.mark.parametrize('source',[row[0] for row in beacons.SPECIES])
def test_every_source_preset_executes_a_legal_dm_turn(source,monkeypatch):
    from test_tactical import battle
    s=battle();card=next(c for c in beacons.presets() if c['source_id']==source)
    enemy={**parse_card('monster',card), 'id':'foe','max_hp':card['hp']}
    s['combat']['enemies']=[enemy];s['combat']['turn_actor_id']='foe'
    before=deepcopy(tactical.board(s)['positions']['p']);events=[]
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:0)
    enemy_dm.turn(s,enemy,events)
    assert tactical.board(s)['positions']['p']==before
    assert s['combat']['movement_spent']<=30 and events


@pytest.mark.parametrize('players',[1,4])
def test_complete_campaign_all_32_battles_and_chapter_growth(players,monkeypatch):
    enemy_phase=[False];original=enemy_dm.turn
    def controlled(s,e,events):
        enemy_phase[0]=True
        try:return original(s,e,events)
        finally:enemy_phase[0]=False
    monkeypatch.setattr(enemy_dm,'turn',controlled)
    # Deterministic high player dice / low enemy dice verify flow, not balance.
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:0 if enemy_phase[0] else n-1)
    s=state(players);battles=set();iterations=0
    while not s.get('completed'):
        iterations+=1;assert iterations<2500,(s['scene_id'],s.get('combat'))
        combat=s.get('combat')
        if combat and combat.get('active'):
            actor=combat['turn_actor_id'];member=next(m for m in s['members'] if m['id']==actor)
            if member['character']['hp']<=0:
                before=deepcopy(s);campaign.apply_action(s,actor,'end_turn');progression.award(s,before);continue
            targets=[e for e in combat['enemies'] if e['hp']>0]
            b=tactical.board(s);pos=b['positions'][actor]
            foe=min(targets,key=lambda e:tactical.distance(pos,b['positions'][e['id']]))
            try:tactical.target(s,actor,foe['id'],5);in_range=True
            except ValueError:in_range=False
            if not in_range and tactical.movement_remaining(s,actor):
                paths=tactical.paths(s,actor,tactical.movement_remaining(s,actor))
                p=min(paths,key=lambda p:(tactical.distance(dict(x=p[0],y=p[1]),b['positions'][foe['id']]),paths[p]['cost']))
                if paths[p]['cost']:
                    enact(s,actor,'grid:move',dict(destination=dict(x=p[0],y=p[1])));continue
            if in_range and (not combat.get('action_used') or combat.get('attacks_remaining',0)>0):
                if 'slashing' in foe.get('damage_immunities',[]) and not combat.get('action_used'):
                    enact(s,actor,'skill:beacon-hammer',target=foe['id'])
                elif not ('slashing' in foe.get('damage_immunities',[])):
                    enact(s,actor,'attack',target=foe['id']);continue
                else:
                    before=deepcopy(s);campaign.apply_action(s,actor,'end_turn');progression.award(s,before)
                continue
            before=deepcopy(s);campaign.apply_action(s,actor,'end_turn');progression.award(s,before)
            continue
        if combat:
            assert all(e['hp']==0 for e in combat['enemies'])
            battles.add(s['scene_id'])
        node=story_runtime.node(s,s['campaign']['node_id'])
        if node.get('puzzles') and not s['campaign']['story_state']['facts'][node['puzzles'][0]['solved_fact']]['value']:
            puzzle=node['puzzles'][0];enact(s,'p','story-puzzle:'+puzzle['id']+':'+puzzle['correct']);continue
        for member in s['members']:
            c=member['character']
            while characters.level_up_preview(c)['eligible']:
                preview=characters.level_up_preview(c);choices={}
                if preview['required_choices']['subclass']:choices['subclass_id']='champion'
                if preview['required_choices']['asi']:
                    ability=next(a for a in ['str','con','dex'] if c['abilities'][a]<=18);choices['asi']={ability:2}
                c=characters.level_up(c,choices)
            member['character']=c
        options=story_transitions.menu(s,'p');assert options,s['scene_id']
        enact(s,'p',options[0]['id'])
    assert len(battles)==32
    assert s['scene_id'] in {'restored','sealed'}
    assert all(m['character']['level']>=9 for m in s['members'])
    assert len([key for key in s['reward_ledger'] if key.startswith('checkpoint:')])==16


def test_dead_leader_survivor_can_solve_and_continue_without_resurrection():
    s=state(2);enact(s,'p','story-route:next-chapter-1')
    s['members'][0]['character'].update(dead=True,hp=0)
    enact(s,'p1','story-puzzle:puzzle-1:medicine')
    assert story_transitions.prepare(s,'p1','enter-1-1')['edge_id']=='enter-1-1'
    assert s['members'][0]['character']['dead']


def test_all_eight_chapters_have_distinct_map_layouts():
    fights=[n for n in beacons.book()['nodes'] if n['monster_ids']]
    layouts={tuple((p['x'],p['y']) for p in n['battlefield']['walls']) for n in fights if n['id'].endswith('-1')}
    assert len(layouts)==8

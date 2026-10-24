"""Validate reviewed source-stage references; these are not executable recipes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

DATA = Path(__file__).parent / 'data'
REVIEWED_IDS = {'acid-arrow','fire-shield','wall-of-ice','wall-of-thorns','storm-of-vengeance','spirit-guardians'}
TRIGGERS = {'spell_cast','target_next_turn_end','melee_attack_hits_caster','wall_appears_over_occupied_space',
            'wall_section_reaches_zero_hp','creature_moves_through_frigid_air','wall_appears','creature_enters_wall',
            'creature_ends_own_turn_in_wall','cloud_appears','caster_turn_in_spell_round','creature_in_aura',
            'creature_enters_aura','creature_starts_own_turn_in_aura'}


def load_structures(collections, *, path=None):
    payload=json.loads((path or DATA / 'spell-effect-structures.json').read_text(encoding='utf-8'))
    blocks=json.loads((DATA / 'official/spell-blocks.json').read_text(encoding='utf-8'))
    official={row['official_title']:row for row in blocks}
    digest=blocks[0]['source_document_sha256']
    if payload.get('schema_version') != 1 or payload.get('ruleset_id') != 'dnd5e-2014-srd5.1' or payload.get('source_document_sha256') != digest:
        raise ValueError('Spell stage source/schema identity mismatch')
    errors=[]
    if set(payload.get('records',{})) != REVIEWED_IDS:
        errors.append('Reviewed stage inventory mismatch')
    def fail(sid,message):errors.append(sid+': '+message)
    for sid,record in payload.get('records',{}).items():
        spell=collections['spells'].get(sid)
        if not spell or record.get('spell_id') != sid:
            fail(sid,'unknown or mismatched spell ID');continue
        if record.get('status') != 'reference_pending_execution' or record.get('runtime_verified') is not False:
            fail(sid,'source stages cannot claim executable coverage')
        source=record.get('source',{})
        block=official.get(source.get('heading'))
        if not block or source.get('document_sha256') != digest or source.get('printed_pages') != block['printed_pages'] or source.get('spell_block_sha256') != hashlib.sha256(block['official_text'].encode()).hexdigest():
            fail(sid,'official spell block provenance mismatch')
        if block and block['official_title'].replace(' ','-').lower() != sid:
            fail(sid,'source heading belongs to another spell')
        stages=record.get('stages',[])
        if not stages or len({stage.get('id') for stage in stages}) != len(stages):
            fail(sid,'missing or duplicate stage ID')
        for stage in stages:
            if stage.get('trigger',{}).get('event') not in TRIGGERS or not stage.get('targets') or not stage.get('resolution'):
                fail(sid,'unknown trigger or incomplete stage')
        for choice in record.get('choices',[]):
            if choice.get('choose') != 1 or len(choice.get('options',{})) < 2:
                fail(sid,'exclusive source choices require exactly one option')
        def walk(value):
            if isinstance(value,dict):
                if 'damage_type' in value and value['damage_type'] not in collections['damage-types']:
                    if value['damage_type'] != 'alignment_selected' or not record.get('damage_type_by_alignment'):
                        fail(sid,'unknown damage type')
                if 'saving_throw' in value:
                    save=value['saving_throw']
                    if save.get('ability') not in collections['ability-scores'] or save.get('dc_source') != 'caster_spell_save_dc' or save.get('on_success') not in {'half','none'}:
                        fail(sid,'invalid save definition')
                if 'damage_at_slot_level' in value:
                    table=value['damage_at_slot_level']
                    if set(table) != {str(n) for n in range(max(1,spell['level']),10)} or any(not re.fullmatch(r'[1-9][0-9]*d(?:4|6|8|10|12|20|100)',str(dice)) for dice in table.values()):
                        fail(sid,'incomplete or malformed damage slot table')
                condition=value.get('on_failed_save_condition')
                if condition and condition.get('id') not in collections['conditions']:
                    fail(sid,'unknown condition')
                for child in value.values():walk(child)
            elif isinstance(value,list):
                for child in value:walk(child)
        walk(record)
        for damage_type in record.get('damage_type_by_alignment',{}).values():
            if damage_type not in collections['damage-types']:fail(sid,'unknown alignment damage type')
        if not isinstance(record.get('interpretation_pending'),list) or not record['interpretation_pending']:
            fail(sid,'pending interpretation boundaries must remain explicit')
    if errors:raise ValueError('Spell stage validation failed: '+'; '.join(errors))
    return deepcopy(payload['records'])


def attach_structures(collections):
    records=load_structures(collections)
    for sid,record in records.items():
        collections['spells'][sid]['effect_structure']=record
    return records

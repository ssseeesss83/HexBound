"""Direct attack bonuses and source-bound numeric damage summaries.

All explicit typed damage literals are retained, including branches absent from
legacy summaries. This is not a trigger/target/conditional-effect executor.
"""
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import re

from .monster_action_bodies import expected as action_bodies
from .monster_bodies import BLOCKS_SHA
from .monster_legendary import same

RAW_SHA='cbf1b6d0a94f6e13afd1480d647d288c61ba0ddc3d3a7842d1501852dc954237'
TYPES='acid|bludgeoning|cold|fire|force|lightning|necrotic|piercing|poison|psychic|radiant|slashing|thunder'
ROLL=r'\d+d\d+(?:\s*[+−–-]\s*\d+)?'
LITERALS=re.compile(r'(?<![\w+−–-])(?P<amount>'+ROLL+r'|\d+)\s*'
    r'(?:\((?P<roll>'+ROLL+r')\)\s*)?(?P<type>'+TYPES+r')'
    r'(?: (?P<type_operator>or|and) (?P<other>'+TYPES+r'))? damage')
ATTACK=re.compile(r'(?:Melee or Ranged|Melee|Ranged) (?:Weapon|Spell) Attack: ([+−–-]\d+) to hit')
ADDED_SOURCE_ACTIONS={(rid,'actions','Change Shape') for rid in ['adult-bronze-dragon','adult-gold-dragon','adult-silver-dragon']}


def dice(text):
    return re.sub(r'\s+','',text).replace('−','-').replace('–','-')


def damage_fields(value,path=()):
    if isinstance(value,dict):
        if 'damage_dice' in value:yield list(path),value
        for key,child in value.items():
            if not key.startswith('official_'):yield from damage_fields(child,(*path,key))
    elif isinstance(value,list):
        for index,child in enumerate(value):yield from damage_fields(child,(*path,index))


def raw_templates():
    raw=(Path(__file__).parent/'data/srd2014/5e-SRD-Monsters.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=RAW_SHA:
        raise ValueError('Monster numeric summary binding archive hash mismatch')
    return {r['index']:r for r in json.loads(raw)}


def parse_literals(text):
    result=[]
    for match in LITERALS.finditer(text):
        amount=match['amount']
        roll=match['roll'] or (amount if 'd' in amount else None)
        # Retain a readable excerpt plus an exact location in the full official
        # body. The excerpt alone is not a complete trigger predicate.
        begin=text.rfind('. ',0,match.start())+2
        if begin==1:begin=0
        end=text.find('. ',match.end())
        end=len(text) if end<0 else end+1
        result.append(dict(source_phrase=match.group(),start=match.start(),end=match.end(),
            amount=int(amount) if 'd' not in amount else None,damage_dice=dice(roll) if roll else dice(amount),
            amount_kind='average_and_roll' if match['roll'] else 'roll_only' if roll else 'fixed',
            damage_types=[match['type']]+([match['other']] if match['other'] else []),
            damage_type_relation=match['type_operator'] or 'single',
            source_context=text[begin:end]))
    return result


def expected(source_dir=None):
    bodies,_=action_bodies(source_dir)
    templates=raw_templates()
    rows=[]; totals=Counter()
    for rid,sections in bodies.items():
        for section,entries in sections.items():
            raw_actions={a['name']:a for a in templates[rid].get(section,[])}
            for entry in entries:
                name=entry['name']; text=entry['desc']; template=raw_actions.get(name)
                if template is None and (rid,section,name) not in ADDED_SOURCE_ACTIONS:
                    raise ValueError('Unclassified parameter binding: '+rid+'/'+name)
                template=template or {}
                bonuses={int(v.replace('−','-').replace('–','-')) for v in ATTACK.findall(text)}
                if len(bonuses)>1:raise ValueError('Multiple direct attack bonuses need scoped representation')
                bonus=next(iter(bonuses)) if bonuses else None
                literals=parse_literals(text)
                by_type=defaultdict(list)
                for index,literal in enumerate(literals):
                    for dtype in literal['damage_types']:by_type[dtype].append((index,literal))
                used=Counter(); bindings=[]
                for path,field in damage_fields(template):
                    dtype=field.get('damage_type',{}).get('index')
                    position=used[dtype]; used[dtype]+=1
                    if position>=len(by_type[dtype]):raise ValueError('Damage summary path has no official literal: '+rid+'/'+name)
                    index,literal=by_type[dtype][position]
                    bindings.append(dict(path=path,literal_index=index,damage_dice=literal['damage_dice'],
                        damage_type=dict(index=dtype,name=dtype.capitalize(),url='/api/2014/damage-types/'+dtype)))
                unprojected=[]
                for dtype,values in by_type.items():
                    unprojected.extend(dict(literal_index=index,damage_type=dtype) for index,_ in values[used[dtype]:])
                reference=dict(source_blocks_sha256=BLOCKS_SHA,source_label=entry['official_action_reference']['source_label'],
                    attack_bonus_basis='explicit_attack_sentence' if bonuses else 'no_standalone_attack_sentence',
                    attack_bonus=bonus,damage_literals=literals,summary_bindings=bindings,
                    unprojected_literal_components=unprojected,summary_binding_archive_sha256=RAW_SHA,
                    binding_basis='Archive paths and damage-type identities are bindings only; numeric values come from official literals in source order within each type.',
                    literal_offset_basis='Normalized official body excluding its source label; offsets do not refer to arbitrary candidate formatting.',
                    complete_body_reference='official_action_reference.source_text; includes the printed label and all nested choices',
                    status='reference_pending_execution',runtime_verified=False,conditional_branch_execution_verified=False,
                    limitation='Explicit typed damage amounts and accurate numeric base summaries only. Context excerpts are not complete predicates. Unprojected literals, alternatives, targets, delays, included bonuses, multipliers, healing and conditional triggers require separate scoped adjudication; literal presence does not authorize applying damage.')
                rows.append(dict(record=rid,section=section,name=name,attack_bonus=bonus,bindings=bindings,reference=reference))
                totals.update(entries=1,direct_attacks=int(bonus is not None),damage_fields=len(bindings),
                    damage_literal_mentions=len(literals),unprojected_components=len(unprojected))
    if totals['entries']!=1505 or totals['direct_attacks']!=533 or totals['damage_fields']!=709:
        raise ValueError('Incomplete monster attack/damage source inventory')
    return rows,dict(totals)


def at(value,path):
    try:
        for part in path:value=value[part]
        return value
    except (KeyError,IndexError,TypeError):return None


def audit(records,source_dir=None):
    rows,totals=expected(source_dir)
    monsters=records.get('monsters',{}) if isinstance(records,dict) else {}
    monsters=monsters if isinstance(monsters,dict) else {}
    checks=[]
    def check(row,path,want,got,position):
        checks.append(dict(record=row['record'],section=row['section'],action=row['name'],position=position,
            path=path,expected=want,actual=got,match=same(want,got)))
    for row in rows:
        record=monsters.get(row['record'],{})
        actions=record.get(row['section'],[]) if isinstance(record,dict) else []
        actions=actions if isinstance(actions,list) else []
        positions=[i for i,a in enumerate(actions) if isinstance(a,dict) and a.get('name')==row['name']]
        position=positions[0] if len(positions)==1 else None
        action=actions[position] if position is not None else {}
        check(row,['attack_bonus'],row['attack_bonus'],action.get('attack_bonus'),position)
        check(row,['official_attack_damage_reference'],row['reference'],action.get('official_attack_damage_reference'),position)
        wanted_paths=[b['path'] for b in row['bindings']]
        actual_paths=[p for p,_ in damage_fields(action)]
        check(row,['damage_field_paths'],wanted_paths,actual_paths,position)
        for binding in row['bindings']:
            for field in ['damage_dice','damage_type']:
                path=[*binding['path'],field]
                check(row,path,binding[field],at(action,path),position)
    return dict(profile='official-monster-attack-damage-summaries-v1',source_inventory=totals,
        checks=checks,differences=[r for r in checks if not r['match']],limitations=[
            '533 direct base attack bonuses and 709 damage numeric/type summaries only; conditional branch completeness and execution are not certified.',
            'Every explicit typed damage literal is retained with source context; unprojected components remain explicit model work, not silently discarded.',
            'No standalone attack sentence means no standalone attack bonus; delegation is resolved separately, never as a fabricated +0 attack.'])


def issues(records):
    return ['Official monster attack/damage summary differs: '+r['record']+'/'+r['action']+'/'+'.'.join(map(str,r['path']))
        for r in audit(records)['differences']]

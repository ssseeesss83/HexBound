"""Source labels and 2014 limited-use recovery, distinct from runtime resources."""
import re

from .armor_source import source, PDF_SHA
from .equipment_source import normalize,identifier
from .monster_action_bodies import expected as action_bodies
from .monster_bodies import BLOCKS_SHA
from .monster_legendary import same

MEPHITS={'dust-mephit','ice-mephit','magma-mephit','steam-mephit'}


def general_rules(pages):
    text=normalize(' '.join(pages[258]['columns']))
    text=text.split('Limited Usage ',1)[1].split(' Grapple Rules for Monsters',1)[0]
    if ("must finish a long rest to regain expended uses" not in text
            or "At the start of each of the monster's turns, roll a d6" not in text
            or 'also recharges when the monster finishes a short or long rest' not in text):
        raise ValueError('Official limited-use recovery rules incomplete')
    return dict(page=259,heading='Limited Usage',text=text,source_document_sha256=PDF_SHA)


def parse_label(label):
    daily=re.search(r'\((\d+)/Day\)$',label)
    rolled=re.search(r'\(Recharge (\d)(?:[–-](\d))?\)$',label)
    rest=label.endswith('(Recharges after a Short or Long Rest)')
    if daily:
        maximum=int(daily[1])
        if maximum<1:raise ValueError('Nonpositive source daily uses')
        usage=dict(type='per day',times=maximum)
        normalized=dict(maximum_uses=maximum,rest_recharge=['long'],recharge_roll=None,
            recovery_amount='all_expended_uses',calendar_reset=False)
    elif rolled:
        low=int(rolled[1]); high=int(rolled[2] or rolled[1])
        if not 1<=low<=high<=6:raise ValueError('Source recharge range outside d6')
        # The legacy min_value projection is faithful to this corpus because
        # every range ends at 6. The normalized rule retains the exact faces.
        if high!=6:raise ValueError('Legacy recharge summary needs explicit upper-bound migration')
        usage=dict(type='recharge on roll',dice='1d6',min_value=low)
        normalized=dict(maximum_uses=1,rest_recharge=['short','long'],recharge_roll=dict(
            dice='1d6',successful_results=list(range(low,high+1)),timing='start_of_own_turn',context='combat',
            purpose='recover_expended_use'),recovery_amount='all_expended_uses',calendar_reset=False)
    elif rest:
        usage=dict(type='recharge after rest',rest_types=['short','long'])
        normalized=dict(maximum_uses=1,rest_recharge=['short','long'],recharge_roll=None,
            recovery_amount='all_expended_uses',calendar_reset=False)
    else:
        if re.search(r'\([^()]*(?:Recharge|Recharges|/Day)[^()]*\)$',label):
            raise ValueError('Unclassified limited-use marker')
        return None,None
    return usage,normalized


def expected(source_dir=None):
    rules=general_rules(source(source_dir))
    bodies,_=action_bodies(source_dir)
    rows=[]
    for rid,sections in bodies.items():
        for section,entries in sections.items():
            for entry in entries:
                action_ref=entry['official_action_reference']
                label=action_ref['source_label']
                usage,normalized=parse_label(label)
                reference=None
                if usage:
                    owner=action_ref['heading']
                    pool_key='dnd5e-2014-srd5.1/monsters/'+identifier(owner)+'/'+section+'/'+identifier(entry['name'])
                    mirrored=None
                    if rid in MEPHITS and entry['name']=='Innate Spellcasting':
                        spell=re.search(r'can innately cast ([a-z ]+)(?: \(|,)',entry['desc'])
                        if not spell:raise ValueError('Missing single mephit innate-spell source')
                        mirrored=dict(spell_id=identifier(spell[1].strip()),relationship='same_source_use',
                            charge_policy='one_cast_spends_one_use_not_outer_plus_inner',
                            spell_structure_status='pending_spellcasting_audit')
                    reference=dict(source_label=label,source_blocks_sha256=BLOCKS_SHA,
                        general_rules=rules,normalized_recovery=normalized,
                        resource_binding=dict(owner_scope='authoritative_world_entity_instance',source_pool_key=pool_key,
                            form_policy='same_entity_and_source_ability_share_one_pool',
                            species_policy='different_world_entities_do_not_share_a_pool',mirrored_nested_usage=mirrored),
                        recovery_precedence='Normalized source recovery governs; legacy per day is not a calendar-midnight reset.',
                        status='reference_pending_execution',runtime_verified=False,
                        limitation='Outer ability label and general recovery only; body-specific conditions, shared runtime state, nested spell structure and recovery execution require separate verification. Form selection never refills a pool.')
                rows.append(dict(record=rid,section=section,name=entry['name'],usage=usage,reference=reference))
    used=[r for r in rows if r['usage']]
    if len(rows)!=1505 or len(used)!=122 or len({r['reference']['resource_binding']['source_pool_key'] for r in used})!=117:
        raise ValueError('Incomplete source limited-use inventory')
    return rows


def audit(records,source_dir=None):
    rows=expected(source_dir)
    monsters=records.get('monsters',{}) if isinstance(records,dict) else {}
    monsters=monsters if isinstance(monsters,dict) else {}
    checks=[]
    for row in rows:
        record=monsters.get(row['record'],{})
        actions=record.get(row['section'],[]) if isinstance(record,dict) else []
        actions=actions if isinstance(actions,list) else []
        positions=[i for i,a in enumerate(actions) if isinstance(a,dict) and a.get('name')==row['name']]
        position=positions[0] if len(positions)==1 else None
        action=actions[position] if position is not None else {}
        for field,want in [('usage',row['usage']),('official_usage_reference',row['reference'])]:
            got=action.get(field)
            checks.append(dict(record=row['record'],section=row['section'],action=row['name'],position=position,
                field=field,expected=want,actual=got,match=same(want,got)))
    return dict(profile='official-monster-limited-usage-v1',normalized_entries=1505,limited_use_labels=122,
        source_ability_pool_templates=117,checks=checks,differences=[r for r in checks if not r['match']],limitations=[
            '122 labels are catalog occurrences, not 122 independent runtime pools. Entity identity and source ability own resources.',
            'Only outer label parameters/general recovery are certified; nested spell pools, specific conditions and execution remain separate.'])


def issues(records):
    return ['Official monster usage differs: '+r['record']+'/'+r['action']+'/'+r['field'] for r in audit(records)['differences']]

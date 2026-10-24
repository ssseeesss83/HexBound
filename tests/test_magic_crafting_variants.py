"""Carrying, crafting and horn requirements cannot disappear in variants."""
from copy import deepcopy
import pytest

from backend import compendium, magic_crafting_variants as variants, rules_packages


def test_complete_tables_and_candidate_agree():
    rows=variants.expected()
    assert len(rows)==12
    report=variants.audit(compendium.COLLECTIONS)
    assert len(report['checks'])==96 and not report['differences']
    assert all(row['official_variant_reference']['runtime_verified'] is False for row in rows.values())


def test_carpet_sizes_capacities_and_half_speeds_are_source_derivations():
    rows=variants.expected()
    for size,capacity,speed in [((3,5),200,80),((4,6),400,60),((5,7),600,40),((6,9),800,30)]:
        row=rows['carpet-of-flying-'+str(size[0])+'x'+str(size[1])]
        selection=row['official_variant_reference']['selection']
        assert selection['size_feet']==list(size) and selection['normal_capacity_lb']==capacity
        assert selection['max_capacity_lb']==capacity*2 and selection['flying_speed_ft']==speed
        assert selection['overloaded_flying_speed_ft']==speed//2
        text=' '.join(row['desc'])
        assert 'command word as an action' in text and 'within 30 feet' in text


def test_manuals_preserve_eligibility_work_cost_damage_and_consumption():
    rows=variants.expected()
    for kind,days,cost in [('clay',30,65000),('flesh',60,50000),('iron',120,100000),('stone',90,80000)]:
        row=rows['manual-of-golems-'+kind]
        selection=row['official_variant_reference']['selection']
        assert selection['time_days']==days and selection['cost_gp']==cost
        text=' '.join(row['desc'])
        for part in ('at least two 5th-level spell slots','6d6 psychic damage','working without interruption',
                     'resting no more than 8 hours per day','book is consumed in eldritch flames',
                     'ashes of the manual are sprinkled','under your control','obeys your spoken commands'):
            assert part in text
    assert 'an iron golem' in ' '.join(rows['manual-of-golems-iron']['desc'])


def test_horn_dice_rarities_requirements_and_zero_as_hundred_are_preserved():
    rows=variants.expected()
    for metal,dice,bonus,rarity,requirement in [('silver','2d4',2,'Rare',None),
        ('brass','3d4',3,'Rare','Proficiency with all simple weapons'),
        ('bronze','4d4',4,'Very Rare','Proficiency with all medium armor'),
        ('iron','5d4',5,'Legendary','Proficiency with all martial weapons')]:
        row=rows['horn-of-valhalla-'+metal]
        selection=row['official_variant_reference']['selection']
        assert selection['berserker_dice']==dice and selection['berserker_bonus']==bonus
        assert selection['requirement']==requirement and row['rarity']==dict(name=rarity)
        text=' '.join(row['desc'])
        for part in ('use an action','within 60 feet','statistics of a berserker','after 1 hour',
                     'drop to 0 hit points','until 7 days have passed','friendly to you and your companions'):
            assert part in text
        if requirement:assert 'attack you' in text and requirement.lower() in text
        else:assert 'attack you' not in text
    iron=rows['horn-of-valhalla-iron']['official_variant_reference']
    assert iron['selection']['d100_range']==[91,100] and '91–00' in iron['selection_row']


@pytest.mark.parametrize('change',['capacity','half_speed','command_action','command_range','craft_cost','craft_time',
    'spell_slots','psychic_damage','rest','manual_destruction','horn_requirement','horn_hostility','horn_cooldown',
    'horn_duration','horn_dice','verified','zero','bad_desc','missing_record'])
def test_lost_usage_conditions_or_forged_table_values_are_rejected(change):
    records=deepcopy(compendium.COLLECTIONS)
    row=records['magic-items']['carpet-of-flying-3x5']
    row['desc']=[' '.join(s.split()) for s in row['desc']]
    if change=='capacity':row['official_variant_reference']['selection']['max_capacity_lb']=999
    elif change=='half_speed':row['desc']=[s.replace('becomes 40 feet','becomes 80 feet') for s in row['desc']]
    elif change=='command_action':row['desc']=[s.replace('as an action','as a bonus action') for s in row['desc']]
    elif change=='command_range':row['desc']=[s.replace('30 feet','300 feet') for s in row['desc']]
    elif change in {'craft_cost','craft_time','spell_slots','psychic_damage','rest','manual_destruction'}:
        row=records['magic-items']['manual-of-golems-clay']
        if change=='craft_cost':row['official_variant_reference']['selection']['cost_gp']=0
        elif change=='craft_time':row['official_variant_reference']['selection']['time_days']=0
        else:
            old,new={'spell_slots':('two 5th-level','one 1st-level'),'psychic_damage':('6d6','1d4'),
                     'rest':('8 hours','24 hours'),'manual_destruction':('book is consumed','book is preserved')}[change]
            row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change.startswith('horn_'):
        row=records['magic-items']['horn-of-valhalla-brass']
        if change=='horn_requirement':row['official_variant_reference']['selection']['requirement']=None
        else:
            old,new={'horn_hostility':('attack you','obey you'),'horn_cooldown':('7 days','1 day'),
                     'horn_duration':('1 hour','8 hours'),'horn_dice':('3d4 + 3','5d4 + 5')}[change]
            row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change=='verified':row['official_variant_reference']['runtime_verified']=True
    elif change=='zero':row['official_variant_reference']['runtime_verified']=0
    elif change=='bad_desc':row['desc']=[None]
    else:records['magic-items'].pop('carpet-of-flying-3x5')
    assert variants.issues(records)


def test_candidate_gate_rejects_crafting_cost_drift():
    records=deepcopy(compendium.COLLECTIONS)
    records['magic-items']['manual-of-golems-iron']['official_variant_reference']['selection']['cost_gp']=100
    assert any('Official magic crafting variant differs' in issue for issue in rules_packages.validate_records(records))

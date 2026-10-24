"""Scrying exceptions and elemental unlock gates survive selected prose."""
from copy import deepcopy
import pytest

from backend import compendium, magic_scrying_variants as variants, rules_packages


def test_seven_named_sections_have_complete_source_evidence():
    rows=variants.expected()
    assert len(rows)==7
    report=variants.audit(compendium.COLLECTIONS)
    assert len(report['checks'])==56 and not report['differences']
    assert all(row['rarity']==dict(name='Legendary') and row['official_variant_reference']['runtime_verified'] is False for row in rows.values())


def test_crystals_preserve_shared_scrying_and_specific_duration_exceptions():
    rows=variants.expected()
    for suffix in ('mind-reading','telepathy','true-seeing'):
        text=' '.join(rows['crystal-ball-of-'+suffix]['desc'])
        assert 'requires attunement' in text and 'While touching it' in text and 'scrying spell (save DC 17)' in text
        assert 'very rare item' not in text
    mind=' '.join(rows['crystal-ball-of-mind-reading']['desc'])
    for phrase in ('use an action','detect thoughts spell (save DC 17)','30 feet',"don't need to concentrate",'ends if scrying ends'):
        assert phrase in mind
    telepathy=' '.join(rows['crystal-ball-of-telepathy']['desc'])
    for phrase in ('suggestion spell (save DC 17)',"don't need to concentrate",'ends if scrying ends',"can't be used again until the next dawn"):
        assert phrase in telepathy
    true=' '.join(rows['crystal-ball-of-true-seeing']['desc'])
    assert "truesight with a radius of 120 feet centered on the spell's sensor" in true


def test_ring_common_scope_is_plane_origin_and_all_unlock_gates_remain():
    for element in ('Air','Earth','Fire','Water'):
        row=variants.expected()['ring-of-elemental-command-'+element.lower()]
        text=' '.join(row['desc'])
        for phrase in ('linked to the Elemental Plane of '+element,'elementals from the linked plane',
                       'they have disadvantage on attack rolls against you','5 charges','1d4 + 1',
                       'daily at dawn','save DC of 17','2 of the ring\'s charges','dominate monster',
                       'If you help slay','while attuned to the ring','additional properties:'):
            assert phrase in text
        assert 'attack rolls against '+element.lower()+' elementals' not in text


@pytest.mark.parametrize('change',['narrow_scope','charges','regain','unlock','attuned_unlock','mind_concentration',
    'scrying_end','telepathy_cooldown','true_seeing_center','earth_shunt','fire_immunity','water_swim',
    'rarity','selected_heading','verified','zero','bad_desc','missing_record'])
def test_shared_or_selected_rule_drift_is_rejected(change):
    records=deepcopy(compendium.COLLECTIONS)
    row=records['magic-items']['ring-of-elemental-command-air']
    if change in {'narrow_scope','charges','regain','unlock','attuned_unlock'}:
        old,new={'narrow_scope':('elementals from the linked plane','air elementals'),
            'charges':('5 charges','50 charges'),'regain':('daily at dawn','each turn'),
            'unlock':('If you help slay','Whenever you see'),'attuned_unlock':('while attuned to the ring','while holding the ring')}[change]
        row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change in {'mind_concentration','scrying_end'}:
        row=records['magic-items']['crystal-ball-of-mind-reading']
        old,new=("don't need to concentrate",'must concentrate') if change=='mind_concentration' else ('but it ends if scrying ends','and persists after scrying ends')
        row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change=='telepathy_cooldown':
        row=records['magic-items']['crystal-ball-of-telepathy']; row['desc']=[s.replace('next dawn','next turn') for s in row['desc']]
    elif change=='true_seeing_center':
        row=records['magic-items']['crystal-ball-of-true-seeing']; row['desc']=[s.replace("the spell's sensor",'your head') for s in row['desc']]
    elif change in {'earth_shunt','fire_immunity','water_swim'}:
        element,old,new={'earth_shunt':('earth','you are shunted out','you remain safely inside'),
            'fire_immunity':('fire','immune to fire damage','immune to all damage'),
            'water_swim':('water','swimming speed equal to your walking speed','swimming speed of 300 feet')}[change]
        row=records['magic-items']['ring-of-elemental-command-'+element]; row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change=='rarity':row['rarity']['name']='Very Rare'
    elif change=='selected_heading':row['official_variant_reference']['selected_heading']='Ring of Fire Elemental Command'
    elif change=='verified':row['official_variant_reference']['runtime_verified']=True
    elif change=='zero':row['official_variant_reference']['runtime_verified']=0
    elif change=='bad_desc':row['desc']=[None]
    else:records['magic-items'].pop('ring-of-elemental-command-air')
    assert variants.issues(records)


def test_candidate_gate_rejects_restricted_plane_scope():
    records=deepcopy(compendium.COLLECTIONS)
    row=records['magic-items']['ring-of-elemental-command-water']
    row['desc']=[s.replace('elementals from the linked plane','water elementals') for s in row['desc']]
    assert any('Official magic scrying variant differs' in issue for issue in rules_packages.validate_records(records))

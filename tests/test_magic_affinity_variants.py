"""Complete resistance, dragon and elemental choices retain usage conditions."""
from copy import deepcopy
import pytest

from backend import compendium, magic_affinity_variants as variants, rules_packages


def test_four_source_tables_cover_thirty_four_variants_without_differences():
    rows=variants.expected()
    assert len(rows)==34
    report=variants.audit(compendium.COLLECTIONS)
    assert len(report['checks'])==272 and not report['differences']
    assert all(row['official_variant_reference']['runtime_verified'] is False for row in rows.values())


def test_resistance_choices_consume_all_ten_faces_and_ring_gem_identities():
    rows=variants.expected()
    gems=dict(zip(['acid','cold','fire','force','lightning','necrotic','poison','psychic','radiant','thunder'],
                  ['Pearl','Tourmaline','Garnet','Sapphire','Citrine','Jet','Amethyst','Jade','Topaz','Spinel']))
    for parent in ('potion-of-resistance','ring-of-resistance'):
        refs=[row['official_variant_reference'] for rid,row in rows.items() if rid.startswith(parent+'-')]
        assert {r['selection']['d10_face'] for r in refs}==set(range(1,11))
        assert {r['selection']['damage_type'] for r in refs}=={s.lower() for s in variants.DAMAGE_TYPES}
    for damage,gem in gems.items():
        ring=rows['ring-of-resistance-'+damage]
        assert ring['official_variant_reference']['selection']['gem']==gem
        assert 'requires attunement' in ring['desc'][0]
        assert 'while wearing this '+gem.lower()+' ring' in ' '.join(ring['desc'])
        potion=rows['potion-of-resistance-'+damage]
        assert potion['official_variant_reference']['selection']['duration_wording']=='1 hour'
        assert 'When you drink this potion' in ' '.join(potion['desc'])


def test_dragon_types_resistances_and_all_shared_properties_remain_complete():
    rows=variants.expected()
    expected={'black':'acid','blue':'lightning','brass':'fire','bronze':'lightning','copper':'acid',
              'gold':'fire','green':'poison','red':'fire','silver':'cold','white':'cold'}
    for dragon,damage in expected.items():
        row=rows['dragon-scale-mail-'+dragon]
        assert row['official_variant_reference']['selection']==dict(dragon_type=dragon,damage_type=damage)
        text=' '.join(row['desc'])
        for part in ('requires attunement','While wearing this armor','+1 bonus to AC',
                     'advantage on saving throws against the Frightful Presence and breath weapons of dragons',
                     'resistance to '+damage+' damage','focus your senses as an action',
                     'the closest '+dragon+' dragon within 30 miles of you',"can't be used again until the next dawn"):
            assert part in text


def test_elemental_choices_preserve_action_breaking_spell_and_magic_loss():
    rows=variants.expected()
    for element,gem in [('air','Blue sapphire'),('earth','Yellow diamond'),('fire','Red corundum'),('water','Emerald')]:
        row=rows['elemental-gem-'+element]
        assert row['official_variant_reference']['selection']==dict(gem=gem,elemental_type=element)
        text=' '.join(row['desc'])
        for part in ('This '+gem.lower(),'use an action to break the gem',element+' elemental',
                     'as if you had cast the conjure elemental spell',"the gem's magic is lost"):
            assert part in text


@pytest.mark.parametrize('change',['damage','face_bool','ring_gem','ring_wearing','ring_attunement','potion_duration',
    'potion_drinking','dragon_ac','dragon_saves','dragon_breath','dragon_action','dragon_range','dragon_cooldown',
    'gem_element','gem_action','gem_consumption','gem_spell','parent_text','verified','zero','bad_desc','missing_record'])
def test_semantic_or_table_drift_cannot_be_certified(change):
    records=deepcopy(compendium.COLLECTIONS)
    row=records['magic-items']['potion-of-resistance-acid']
    if change=='damage':row['official_variant_reference']['selection']['damage_type']='fire'
    elif change=='face_bool':row['official_variant_reference']['selection']['d10_face']=True
    elif change.startswith('ring_'):
        row=records['magic-items']['ring-of-resistance-acid']
        if change=='ring_gem':row['official_variant_reference']['selection']['gem']='Sapphire'
        elif change=='ring_wearing':row['desc']=[s.replace('wearing','holding') for s in row['desc']]
        else:row['desc']=[s.replace('(requires attunement)','') for s in row['desc']]
    elif change=='potion_duration':row['desc']=[s.replace('1 hour','8 hours') for s in row['desc']]
    elif change=='potion_drinking':row['desc']=[s.replace('drink','hold') for s in row['desc']]
    elif change.startswith('dragon_'):
        row=records['magic-items']['dragon-scale-mail-black']
        old,new={'dragon_ac':('+1 bonus','+2 bonus'),'dragon_saves':('saving throws','attack rolls'),
            'dragon_breath':('and breath weapons',''),'dragon_action':('as an action','as a bonus action'),
            'dragon_range':('30 miles','300 miles'),'dragon_cooldown':('next dawn','next turn')}[change]
        row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change.startswith('gem_'):
        row=records['magic-items']['elemental-gem-air']
        old,new={'gem_element':('an air elemental','a fire elemental'),'gem_action':('an action','a bonus action'),
            'gem_consumption':("the gem's magic is lost","the gem's magic remains"),
            'gem_spell':('conjure elemental','wish')}[change]
        row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change=='parent_text':row['official_variant_reference']['complete_parent_text']='Potion, uncommon'
    elif change=='verified':row['official_variant_reference']['runtime_verified']=True
    elif change=='zero':row['official_variant_reference']['runtime_verified']=0
    elif change=='bad_desc':row['desc']=[None]
    else:records['magic-items'].pop('potion-of-resistance-acid')
    assert variants.issues(records)


def test_candidate_gate_rejects_damage_choice_drift():
    records=deepcopy(compendium.COLLECTIONS)
    records['magic-items']['ring-of-resistance-cold']['official_variant_reference']['selection']['damage_type']='fire'
    assert any('Official magic affinity variant differs' in issue for issue in rules_packages.validate_records(records))

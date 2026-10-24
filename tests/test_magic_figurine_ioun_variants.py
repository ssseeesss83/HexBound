"""Named section boundaries cannot truncate nested creatures or exceptions."""
from copy import deepcopy
import pytest

from backend import compendium, magic_figurine_ioun_variants as variants, rules_packages


def test_twenty_three_named_variants_match_complete_source_sections():
    rows=variants.expected()
    assert len(rows)==23
    report=variants.audit(compendium.COLLECTIONS)
    assert len(report['checks'])==184 and not report['differences']
    assert all(row['official_variant_reference']['runtime_verified'] is False for row in rows.values())
    assert rows['figurine-of-wondrous-power-silver-raven']['rarity']==dict(name='Uncommon')
    assert rows['figurine-of-wondrous-power-obsidian-steed']['rarity']==dict(name='Very Rare')


def test_figurine_common_activation_failure_command_and_reversion_rules():
    for rid,row in variants.expected().items():
        if not rid.startswith('figurine'):continue
        text=' '.join(row['desc'])
        for part in ('use an action','within 60 feet','occupied by other creatures or objects',
                     "the figurine doesn't become a creature",'defends itself but takes no other actions',
                     'drops to 0 hit points','while touching it',"can't be used again until"):
            assert part in text


def test_fly_nested_stat_block_three_goats_steed_tail_and_raven_end_survive():
    rows=variants.expected()
    fly=' '.join(rows['figurine-of-wondrous-power-ebony-fly']['desc'])
    for part in ('Giant Fly','Large beast','Armor Class 11','Hit Points 19 (3d10 + 3)',
                 'fly 60 ft.','STR DEX CON INT WIS CHA','passive Perception 10','Languages'):
        assert part in fly
    goats=' '.join(rows['figurine-of-wondrous-power-ivory-goats']['desc'])
    for part in ('goat of traveling','goat of travail','goat of terror','24 charges','each hour or portion thereof',
                 '30 days','15 days','+1 lance','+2 longsword','DC 15 Wisdom','immune','next 24 hours'):
        assert part in goats
    steed=' '.join(rows['figurine-of-wondrous-power-obsidian-steed']['desc'])
    for part in ('good alignment','10 percent chance','including a command to revert','Hades','fights only to defend itself'):
        assert part in steed
    raven=' '.join(rows['figurine-of-wondrous-power-silver-raven']['desc'])
    assert raven.endswith('cast the animal messenger spell on it at will.')


def test_ioun_common_physical_rules_and_absorption_whitelist_boundaries():
    rows=variants.expected()
    for rid,row in rows.items():
        if not rid.startswith('ioun'):continue
        text=' '.join(row['desc'])
        for part in ('requires attunement','1d3 feet','attack roll against AC 24','DC 24 Dexterity (Acrobatics)',
                     'seize and stow','10 hit points','resistance to all damage','being worn while it orbits your head'):
            assert part in text
    for key,maximum,total in [('absorption',4,20),('greater-absorption',8,50)]:
        text=' '.join(rows['ioun-stone-of-'+key]['desc'])
        for part in ('use your reaction',str(maximum)+'th level or lower','targeting only you',
                     'canceled '+str(total)+' levels','burns out',"the stone can't cancel it"):
            assert part in text
    assert '8th level' not in ' '.join(rows['ioun-stone-of-absorption']['desc'])
    assert '4th level' not in ' '.join(rows['ioun-stone-of-greater-absorption']['desc'])


def test_reserve_three_paragraphs_and_regeneration_minimum_hp_condition():
    rows=variants.expected()
    text=' '.join(rows['ioun-stone-of-reserve']['desc']).replace('−','-')
    for part in ('up to 3 levels','1d4 - 1','1st through 3rd level',"If the stone can't hold the spell",'expended without effect',
                 'slot level, spell save DC, spell attack bonus, and spellcasting ability of the original caster',
                 'no longer stored in it, freeing up space'):
        assert part in text
    regen=' '.join(rows['ioun-stone-of-regeneration']['desc'])
    assert '15 hit points at the end of each hour' in regen and 'at least 1 hit point' in regen


@pytest.mark.parametrize('change',['fly_statblock','goat_subtype','goat_weapon','steed_tail','raven_tail','activation_failure',
    'absorption_capacity','greater_level','remaining_exception','reserve_tail','reserve_minus','reserve_original_caster',
    'regen_hp_gate','stone_hp','rarity','verified','zero','bad_desc','missing_record'])
def test_nested_and_exception_rule_drift_is_rejected(change):
    records=deepcopy(compendium.COLLECTIONS)
    row=records['magic-items']['figurine-of-wondrous-power-ebony-fly']
    if change=='fly_statblock':row['desc']=[s.split('Giant Fly')[0] for s in row['desc']]
    elif change in {'goat_subtype','goat_weapon'}:
        row=records['magic-items']['figurine-of-wondrous-power-ivory-goats']
        old,new=('goat of travail','goat of traveling') if change=='goat_subtype' else ('+2 longsword','+3 longsword')
        row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change=='steed_tail':
        row=records['magic-items']['figurine-of-wondrous-power-obsidian-steed']; row['desc']=[s.split('If you have a good alignment')[0] for s in row['desc']]
    elif change=='raven_tail':
        row=records['magic-items']['figurine-of-wondrous-power-silver-raven']; row['desc']=[s.split('While in raven form')[0] for s in row['desc']]
    elif change=='activation_failure':row['desc']=[s.replace("doesn't become a creature",'always becomes a creature') for s in row['desc']]
    elif change in {'absorption_capacity','remaining_exception'}:
        row=records['magic-items']['ioun-stone-of-absorption']
        old,new=('canceled 20 levels','canceled 200 levels') if change=='absorption_capacity' else ("can't cancel it",'can cancel it')
        row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change=='greater_level':
        row=records['magic-items']['ioun-stone-of-greater-absorption']; row['desc']=[s.replace('8th level','9th level') for s in row['desc']]
    elif change in {'reserve_tail','reserve_minus','reserve_original_caster'}:
        row=records['magic-items']['ioun-stone-of-reserve']
        if change=='reserve_tail':row['desc']=[s.split('While this stone orbits your head')[0] for s in row['desc']]
        else:
            old,new=('1d4 − 1','1d4 + 1') if change=='reserve_minus' else ('of the original caster','of the current owner')
            row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change in {'regen_hp_gate','stone_hp'}:
        row=records['magic-items']['ioun-stone-of-regeneration']
        old,new=('at least 1 hit point','at least 0 hit points') if change=='regen_hp_gate' else ('10 hit points','100 hit points')
        row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change=='rarity':row['rarity']['name']='Legendary'
    elif change=='verified':row['official_variant_reference']['runtime_verified']=True
    elif change=='zero':row['official_variant_reference']['runtime_verified']=0
    elif change=='bad_desc':row['desc']=[None]
    else:records['magic-items'].pop('figurine-of-wondrous-power-ebony-fly')
    assert variants.issues(records)


def test_candidate_gate_rejects_lost_regeneration_minimum_hp():
    records=deepcopy(compendium.COLLECTIONS)
    row=records['magic-items']['ioun-stone-of-regeneration']
    row['desc']=[s.replace('at least 1 hit point','at least 0 hit points') for s in row['desc']]
    assert any('Official magic figurine/Ioun variant differs' in issue for issue in rules_packages.validate_records(records))


def test_all_variant_transcription_profiles_cover_exactly_the_normalized_inventory():
    from backend import magic_bonus_variants, magic_consumable_variants, magic_giant_variants, magic_affinity_variants
    from backend import magic_crafting_variants, magic_bag_variants, magic_scrying_variants, magic_feather_variants
    profiles=[magic_bonus_variants,magic_consumable_variants,magic_giant_variants,magic_affinity_variants,
              magic_crafting_variants,magic_bag_variants,magic_scrying_variants,magic_feather_variants,variants]
    covered=set()
    for profile in profiles:
        ids=set(profile.expected())
        assert not covered & ids
        covered |= ids
    assert len(covered)==126
    assert covered == {rid for rid,row in compendium.MAGIC_ITEMS.items() if row['variant'] is True}

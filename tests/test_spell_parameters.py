"""Reviewed official spell parameters, independent of runtime completeness."""
from backend import compendium as c
from backend.rules_packages import build_legacy_package


def test_slot_tables_cover_every_legal_slot_and_keep_official_steps():
    expected = {
        'disintegrate': ['10d6 + 40','13d6 + 40','16d6 + 40','19d6 + 40'],
        'freezing-sphere': ['10d6','11d6','12d6','13d6'],
        'phantasmal-killer': ['4d10','5d10','6d10','7d10','8d10','9d10'],
        'wall-of-fire': ['5d8','6d8','7d8','8d8','9d8','10d8'],
        'flame-blade': ['3d6','3d6','4d6','4d6','5d6','5d6','6d6','6d6']}
    for sid, values in expected.items():
        spell = c.SPELLS[sid]
        table = spell['damage'][0]['damage_at_slot_level']
        assert list(table) == [str(n) for n in range(spell['level'],10)]
        assert list(table.values()) == values


def test_sleep_budget_cannot_be_consumed_as_generic_damage():
    spell = c.SPELLS['sleep']
    assert not spell['damage']
    assert spell['effect_kind'] == 'sleep_hit_point_budget'
    assert spell['hit_point_budget_at_slot_level'] == {
        '1':'5d8','2':'7d8','3':'9d8','4':'11d8','5':'13d8','6':'15d8','7':'17d8','8':'19d8','9':'21d8'}
    assert 'hit points' in ' '.join(spell['desc'])
    # Candidate classification must not rewrite a running historical package.
    legacy = build_legacy_package()['records']['spells']['sleep']
    assert legacy['damage'] and 'hit_point_budget_at_slot_level' not in legacy


def test_primary_save_summaries_use_caster_dc_and_keep_escape_as_check():
    for sid, ability, success in [('call-lightning','dex','half'),('flaming-sphere','dex','half'),
                                  ('levitate','con','none'),('spirit-guardians','wis','half'),
                                  ('web','dex','none'),('zone-of-truth','cha','none')]:
        dc = c.SPELLS[sid]['dc']
        assert dc['dc_type']['index'] == ability and dc['dc_success'] == success
        assert 'dc_value' not in dc
    assert 'Strength check' in ' '.join(c.SPELLS['web']['desc'])
    assert c.SPELLS['flame-blade']['attack_type'] == 'melee'
    assert c.SPELLS['scorching-ray']['attack_type'] == 'ranged'

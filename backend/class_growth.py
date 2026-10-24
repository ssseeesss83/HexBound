"""Independent official growth-table audit; no rule execution or data mutation.

Numeric cells are extracted from the fixed official source; explicit formulas
are reviewed transcriptions. Feature grant evidence is not automatic signoff.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

OFFICIAL_PAGES_SHA = 'a3d4be9c2a612c0cba1dcc0bc3ce875f52cef1b4924f743142be600614ade1c6'


def same_value(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(same_value(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(same_value(a,b) for a,b in zip(left,right))
    if isinstance(left, (int,float)) and isinstance(right, (int,float)):
        return left == right
    return type(left) is type(right) and left == right


def audit_growth(records, source_dir=None):
    source = Path(source_dir) if source_dir else Path(__file__).parent / 'data/official'
    expected_pdf_sha = '2504d2a0abb0a4d491a939be4f17910a2dde0312570ab8d208080225ccf0a1f0'
    if hashlib.sha256((source / 'SRD_CC_v5.1.pdf').read_bytes()).hexdigest() != expected_pdf_sha:
        raise ValueError('Official PDF hash mismatch')
    pages_bytes = (source / 'pages.json').read_bytes()
    if hashlib.sha256(pages_bytes).hexdigest() != OFFICIAL_PAGES_SHA:
        raise ValueError('Official page extraction hash mismatch')
    p = json.loads(pages_bytes)
    pm = dict(barbarian=8, bard=11, cleric=15, druid=19, fighter=24, monk=26,
              paladin=30, ranger=35, rogue=39, sorcerer=42, warlock=46, wizard=52)
    checks, diffs, grants = [], [], []
    def test(rid, path, want, src, method):
        missing = object()
        got = records.get('levels', {}).get(rid, missing)
        for key in path:
            got = got.get(key, missing) if isinstance(got, dict) else missing
        matched = got is not missing and same_value(got, want)
        row = dict(record=rid, path=path, expected_official_value=deepcopy(want),
                   actual=None if got is missing else deepcopy(got), field_missing=got is missing,
                   source=src, method=method, match=matched)
        checks.append(row)
        if not matched:
            diffs.append(row)
    for cls, page in pm.items():
        rows = {int(lv): (int(prof), rest) for lv, prof, rest in re.findall(
            r'(?m)^(\d+)(?:st|nd|rd|th) \+(\d) (.*)$', '\n'.join(p[page-1]['columns']))}
        if set(rows) != set(range(1, 21)):
            raise ValueError(f'{cls}: official proficiency rows not exactly 1..20')
        for lv, (prof, rest) in rows.items():
            rid = f'{cls}-{lv}'
            test(rid, ['prof_bonus'], prof, dict(page=page, table_row=lv, official_first_line=rest),
                 'machine_from_official_columns_row')
            grants.append(dict(record=rid, source_page=page, official_table_first_line=rest,
                               actual_grants=deepcopy(records.get('levels', {}).get(rid, {}).get('features', [])),
                               status='evidence_only_prior_human_table_comparison_not_machine_verified',
                               limitations='No programmatic grant equality, feature-body, or subclass-grant approval.'))
        width = dict(bard=11, cleric=10, druid=10, paladin=5, ranger=6,
                     sorcerer=11, warlock=5, wizard=10).get(cls)
        if width:
            lines = [re.sub(r'\s+', ' ', s).strip() for s in p[page-1]['raw_text'].replace('\t\r', '').split('\n')]
            lines = [s for s in lines if re.match(r'^\d+(st|nd|rd|th)\s+\+\d', s)]
            if len(lines) != 20:
                raise ValueError(f'{cls}: official casting rows not exactly twenty')
            for line in lines:
                lv = int(re.match(r'\d+', line)[0])
                # Widths are transcribed from official headers, independently of candidates.
                # U+008A is the PDF extractor's no-slot glyph. Adjacent glyphs are separate cells.
                tail = re.findall(r'\d+(?:st|nd|rd|th)?|\x8a|—', line)[-width:]
                values = [0 if x in ['\x8a', '—'] else int(re.sub(r'\D', '', x)) for x in tail]
                src = dict(page=page, table_row=lv, official_fullwidth_line=line)
                rid = f'{cls}-{lv}'
                if cls == 'warlock':
                    for idx, path in [(0, ['spellcasting', 'cantrips_known']),
                                      (1, ['spellcasting', 'spells_known']),
                                      (4, ['class_specific', 'invocations_known'])]:
                        test(rid, path, values[idx], src, 'machine_from_official_fullwidth_numeric_columns')
                    for sl in range(1, 10):
                        test(rid, ['spellcasting', f'spell_slots_level_{sl}'],
                             values[2] if sl == values[3] else 0, src,
                             'machine_from_official_fullwidth_slot_count_and_level')
                else:
                    names = []
                    if cls in ['bard', 'cleric', 'druid', 'sorcerer', 'wizard']:
                        names.append('cantrips_known')
                    if cls in ['bard', 'ranger', 'sorcerer']:
                        names.append('spells_known')
                    names += [f'spell_slots_level_{i}' for i in range(1, 6 if cls in ['paladin', 'ranger'] else 10)]
                    if len(names) != len(values):
                        raise ValueError('Official column count mismatch')
                    for field, value in zip(names, values):
                        test(rid, ['spellcasting', field], value, src, 'machine_from_official_fullwidth_numeric_columns')
    # Explicit independent transcriptions of official ASI grant levels.
    for cls in pm:
        asi = [4,6,8,12,14,16,19] if cls == 'fighter' else [4,8,10,12,16,19] if cls == 'rogue' else [4,8,12,16,19]
        for lv in range(1, 21):
            test(f'{cls}-{lv}', ['ability_score_bonuses'], sum(x <= lv for x in asi),
                 dict(page=pm[cls], table='Ability Score Improvement grants', transcribed_grant_levels=asi),
                 'explicit_official_table_ASI_levels_cumulative_count')
    def formula(cls, field, fn, pages, evidence):
        for lv in range(1,21):
            test(f'{cls}-{lv}', ['class_specific', field], fn(lv),
                 dict(pages=pages, evidence=evidence),
                 'explicit_official_threshold_or_formula_then_machine_compare')
    # Formulas below are manual transcriptions of the cited official tables/prose.
    # The script compares them mechanically; it does not claim OCR-derived proof of these formulas.
    formula('barbarian','rage_count',lambda l:None if l==20 else 2 if l<3 else 3 if l<6 else 4 if l<12 else 5 if l<17 else 6,[8],'Rages table; level20 Unlimited')
    formula('barbarian','rage_damage_bonus',lambda l:2 if l<9 else 3 if l<16 else 4,[8],'Rage Damage table')
    formula('barbarian','brutal_critical_dice',lambda l:0 if l<9 else 1 if l<13 else 2 if l<17 else 3,[8,9],'Brutal Critical at9/13/17')
    test('barbarian-20',['class_specific','rage_unlimited'],True,dict(page=8),'official_unlimited_marker')
    formula('bard','bardic_inspiration_die',lambda l:6 if l<5 else 8 if l<10 else 10 if l<15 else 12,[11,12],'Bardic Inspiration progression')
    formula('bard','song_of_rest_die',lambda l:0 if l<2 else 6 if l<9 else 8 if l<13 else 10 if l<17 else 12,[11,12],'Song of Rest progression')
    for f, level in [('magical_secrets_max_5',10),('magical_secrets_max_7',14),('magical_secrets_max_9',18)]:
        formula('bard',f,lambda l,level=level:2 if l>=level else 0,[11,13],'two additional spells at10/14/18; ceiling from Bard table at grant, not runtime-list contract')
    formula('cleric','channel_divinity_charges',lambda l:0 if l<2 else 1 if l<6 else 2 if l<18 else 3,[15,16],'1/rest at2,2/rest at6,3/rest at18')
    formula('cleric','destroy_undead_cr',lambda l:0 if l<5 else .5 if l<8 else 1 if l<11 else 2 if l<14 else 3 if l<17 else 4,[15,17],'Destroy Undead progression')
    formula('druid','wild_shape_max_cr',lambda l:0 if l<2 else .25 if l<4 else .5 if l<8 else 1,[20],'Beast Shapes table')
    formula('druid','wild_shape_swim',lambda l:l>=4,[20],'no swimming speed before4')
    formula('druid','wild_shape_fly',lambda l:l>=8,[20],'no flying speed before8')
    formula('fighter','action_surges',lambda l:0 if l<2 else 1 if l<17 else 2,[24,25],'Action Surge progression')
    formula('fighter','extra_attacks',lambda l:0 if l<5 else 1 if l<11 else 2 if l<20 else 3,[24,25],'EXTRA attacks, not total attacks; total1/2/3/4')
    formula('fighter','indomitable_uses',lambda l:0 if l<9 else 1 if l<13 else 2 if l<17 else 3,[24,25],'Indomitable progression')
    formula('monk','ki_points',lambda l:0 if l==1 else l,[26],'Monk table Ki Points')
    formula('monk','martial_arts',lambda l:dict(dice_count=1,dice_value=4 if l<5 else 6 if l<11 else 8 if l<17 else 10),[26],'Monk table Martial Arts')
    formula('monk','unarmored_movement',lambda l:0 if l<2 else 10 if l<6 else 15 if l<10 else 20 if l<14 else 25 if l<18 else 30,[26],'Monk table movement bonus in feet')
    formula('paladin','aura_range',lambda l:0 if l<6 else 10 if l<18 else 30,[30,32],'Aura of Protection / improvements; not every aura exists at6')
    formula('ranger','favored_enemies',lambda l:1 if l<6 else 2 if l<14 else 3,[35,36],'extra choice at6 and14; humanoid-race alternative audited separately')
    formula('ranger','favored_terrain',lambda l:1 if l<6 else 2 if l<10 else 3,[35,36],'extra terrain at6 and10')
    formula('rogue','sneak_attack',lambda l:dict(dice_count=(l+1)//2,dice_value=6),[39],'Rogue table Sneak Attack')
    formula('sorcerer','sorcery_points',lambda l:0 if l==1 else l,[42],'Sorcerer table')
    formula('sorcerer','metamagic_known',lambda l:0 if l<3 else 2 if l<10 else 3 if l<17 else 4,[42,44],'two at3;one additional10 and17')
    costs=[dict(spell_slot_level=a,sorcery_point_cost=b) for a,b in [(1,2),(2,3),(3,5),(4,6),(5,7)]]
    formula('sorcerer','creating_spell_slots',lambda l:[] if l<2 else costs,[43],'Creating Spell Slots table')
    for sl,start in [(6,11),(7,13),(8,15),(9,17)]:
        formula('warlock',f'mystic_arcanum_level_{sl}',lambda l,start=start:1 if l>=start else 0,[46,48],'one arcanum at11/13/15/17;not pact slot')
    formula('wizard','arcane_recovery_levels',lambda l:(l+1)//2,[53],'half wizard level rounded up;each recovered slot below6th')
    report=dict(status='read_only_official_growth_parameter_comparison',corrections=[],diffs=diffs,
                checks=checks,grant_matrix=grants,source_sha256=expected_pdf_sha,
                summary=dict(numeric_field_comparisons=len(checks),base_class_rows=240,
                             prof_bonus_rows=240,caster_table_rows=160,
                             grant_evidence_rows=240,machine_approved_grant_rows=0,
                             prior_human_table_comparison_rows=240,confirmed_new_discrepancies=len(diffs)),
                boundaries=['No feature-grant automatic signoff. Human semantic comparison is separate.',
                            'Explicit formulas are source transcriptions, not copied candidate values.',
                            'No subclass grant interiors / all407 bodies / runtime execution approval.'])

    checked = {(row['record'], tuple(row['path'])) for row in checks}
    unreviewed = []
    for cls in pm:
        for level in range(1, 21):
            rid = f'{cls}-{level}'
            record = records.get('levels', {}).get(rid, {})
            for category in ['spellcasting', 'class_specific']:
                for field in record.get(category, {}):
                    if (rid, (category, field)) not in checked:
                        unreviewed.append({'record': rid, 'path': [category, field]})
    report['unreviewed_fields'] = unreviewed
    report['summary']['unreviewed_fields'] = len(unreviewed)
    report['source_pages_sha256'] = OFFICIAL_PAGES_SHA
    return report


def growth_issues(records):
    """Candidate-only source gate; frozen packages use their own inventory."""
    try:
        report = audit_growth(records)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        return [f'Official class growth source audit failed: {exc}']
    return [
        'Official class growth mismatch: ' + row['record'] + '/' + '/'.join(row['path'])
        for row in report['diffs']
    ] + [
        'Unreviewed class growth field: ' + row['record'] + '/' + '/'.join(row['path'])
        for row in report['unreviewed_fields']
    ]

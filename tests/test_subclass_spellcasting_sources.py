"""Selected official intervals and relations, without execution certification."""
import hashlib
import json
import unicodedata

from backend import compendium as c, rules_packages


def review():
    return json.loads((c.DATA_DIR / 'official/subclass-spellcasting-review.json').read_text(encoding='utf-8'))


def wording(text):
    return ''.join(char for char in unicodedata.normalize('NFKD',text).casefold() if char.isalnum())


def test_spell_relation_intervals_keep_all_eighty_six_official_grants():
    rows = review()['spell_table_relation_checks']
    assert len(rows) == 10
    assert sum(len(row['expected_official_relations']) for row in rows) == 86
    visited = {}
    for row in rows:
        _, sid = row['record'].split('/')
        indices = visited.setdefault(sid, set())
        assert not indices.intersection(row['candidate_array_indices'])
        indices.update(row['candidate_array_indices'])
        relations = []
        for index in row['candidate_array_indices']:
            spell = c.SUBCLASSES[sid]['spells'][index]
            level = next(prerequisite for prerequisite in spell['prerequisites'] if prerequisite['type']=='level')
            terrain = [prerequisite['index'] for prerequisite in spell['prerequisites'] if prerequisite['type']=='feature']
            assert terrain == ([f"circle-of-the-land-{row['terrain']}"] if row['terrain'] else [])
            relations.append([int(level['index'].rsplit('-',1)[1]),spell['spell']['index']])
        assert sorted(relations) == sorted(row['expected_official_relations'])
    for sid, indices in visited.items():
        assert indices == set(range(len(c.SUBCLASSES[sid]['spells'])))


def test_forty_full_spellcasting_subsections_and_eight_references_stay_equal():
    report = review()
    assert len(report['spellcasting_subsection_checks']) == 40
    for row in report['spellcasting_subsection_checks']:
        kind, sid = row['record'].split('/')
        value = c.COLLECTIONS[kind][sid]
        for key in row['path']:
            value = value[key]
        assert wording(' '.join(value)) == wording(row['source_body'])
    assert len(report['spellcasting_feature_reference_checks']) == 8
    for row in report['spellcasting_feature_reference_checks']:
        sid = row['record'].split('/')[1]
        assert c.FEATURES[sid]['reference'] == row['expected']


def test_twelve_subclass_parent_and_grant_snapshots_keep_their_reviewed_scope():
    rows = review()['subclass_parent_and_grant_checks']
    assert len(rows) == 12
    for row in rows:
        sid = row['record'].split('/')[1]
        assert c.SUBCLASSES[sid]['class']['index'] == row['parent_class']
        assert sorted(c.SUBCLASS_LEVELS[sid]) == row['subclass_level_records_expected_and_actual']
        for level, ids in row['granted_feature_ids_by_level'].items():
            assert [ref['index'] for ref in c.SUBCLASS_LEVELS[sid][int(level)]['features']] == ids


def test_choice_structure_is_reference_only_and_does_not_rewrite_legacy_or_prose():
    report = review()
    legacy = rules_packages.build_legacy_package()['records']['features']
    assert len(report['reference_only_proposals']) == 3
    for row in report['reference_only_proposals']:
        sid = row['record'].split('/')[1]
        assert c.FEATURES[sid]['selection_reference'] == row['proposed']
        assert c.FEATURES[sid]['selection_reference']['runtime_verified'] is False
        assert c.FEATURES[sid]['desc'] == row['current_text'] == legacy[sid]['desc']
        assert 'selection_reference' not in legacy[sid]
    for name,key in [('SRD_CC_v5.1.pdf','source_pdf_sha256'),('pages.json','source_pages_sha256')]:
        assert hashlib.sha256((c.DATA_DIR / 'official' / name).read_bytes()).hexdigest() == report[key]
    assert not report['confirmed_source_value_corrections']
    assert report['boundaries']

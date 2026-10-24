"""Independent source values must gate candidates without rewriting history."""
from copy import deepcopy
import json
import re

import pytest

from backend import compendium as c
from backend.class_growth import audit_growth, growth_issues
from backend.rules_packages import build_legacy_package, validate_records


def test_all_numeric_cells_and_fields_are_reviewed_without_mutation():
    before = deepcopy(c.COLLECTIONS)
    report = audit_growth(c.COLLECTIONS)
    assert report['summary']['numeric_field_comparisons'] == 2601
    assert report['summary']['machine_approved_grant_rows'] == 0
    assert not report['diffs'] and not report['unreviewed_fields']
    assert c.COLLECTIONS == before


@pytest.mark.parametrize('rid,path,value', [
    ('wizard-5', ['spellcasting', 'spell_slots_level_3'], 3),
    ('fighter-6', ['ability_score_bonuses'], 1),
    ('barbarian-1', ['class_specific', 'rage_count'], 9),
    ('druid-1', ['class_specific', 'wild_shape_swim'], 0),
])
def test_wrong_slot_asi_resource_and_boolean_are_rejected(rid, path, value):
    broken = deepcopy(c.COLLECTIONS)
    target = broken['levels'][rid]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert any(rid + '/' + '/'.join(path) in issue for issue in validate_records(broken))


def test_missing_unlimited_marker_and_unreviewed_fields_are_not_silently_accepted():
    broken = deepcopy(c.COLLECTIONS)
    del broken['levels']['barbarian-20']['class_specific']['rage_count']
    broken['levels']['fighter-1']['class_specific']['invented_resource'] = 5
    report = audit_growth(broken)
    row = next(r for r in report['diffs'] if r['record'] == 'barbarian-20')
    assert row['field_missing'] and row['expected_official_value'] is None
    assert any('invented_resource' in issue for issue in growth_issues(broken))


def test_malformed_record_is_a_structured_audit_failure():
    broken = deepcopy(c.COLLECTIONS)
    broken['levels']['wizard-1'] = None
    assert growth_issues(broken)[0].startswith('Official class growth source audit failed:')


@pytest.mark.parametrize('filename', ['SRD_CC_v5.1.pdf', 'pages.json'])
def test_source_digest_failure_is_explicit(tmp_path, filename):
    source = c.DATA_DIR / 'official'
    for name in ['SRD_CC_v5.1.pdf', 'pages.json']:
        (tmp_path / name).write_bytes((source / name).read_bytes() if name != filename else b'changed')
    with pytest.raises(ValueError, match='hash mismatch'):
        audit_growth(c.COLLECTIONS, tmp_path)


def test_holy_nimbus_source_tail_and_frozen_package():
    report = json.loads((c.DATA_DIR / 'official/feature-body-review.json').read_text(encoding='utf-8'))
    row = next(r for r in report['change_candidates'] if r['id'] == 'holy-nimbus')
    pages = json.loads((c.DATA_DIR / 'official/pages.json').read_text(encoding='utf-8'))
    words = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())
    source = words(' '.join(pages[32]['columns']))
    assert words(' '.join(row['value'])) in source
    assert c.FEATURES['holy-nimbus']['desc'] == row['value']
    legacy = build_legacy_package()
    assert legacy['records']['features']['holy-nimbus']['desc'] == row['expected']
    assert not validate_records(legacy['records'], inventory=legacy['records'])
    assert report['counts']['features'] == 407
    assert report['limitations']  # Evidence is explicitly not whole-block signoff.

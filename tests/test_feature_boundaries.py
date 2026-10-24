"""Heading interval evidence and asserted repairs, separate from execution status."""
import hashlib
import json
import re

from backend import compendium as c, rules_packages


def norm(text):
    return re.sub(r'\s+', ' ', text).strip()


def test_boundary_report_covers_every_feature_exactly_once_and_pins_sources():
    report = json.loads((c.DATA_DIR / 'official/feature-boundary-review.json').read_text(encoding='utf-8'))
    ids = [sid for group in report['groups'] for sid in group['ids']]
    assert len(ids) == len(set(ids)) == 407 and set(ids) == set(c.FEATURES)
    assert len(report['groups']) == 261
    assert all(group['status'] != 'remaining_layout_review' for group in report['groups'])
    for filename, digest in report['source_hashes'].items():
        assert hashlib.sha256((c.DATA_DIR / 'official' / filename).read_bytes()).hexdigest() == digest
    # These categories deliberately retain separate outstanding acceptance scopes.
    assert report['remaining_acceptance'] and report['limitations']


def test_destroy_undead_tail_is_complete_to_table_boundary_without_changing_thresholds():
    pages = json.loads((c.DATA_DIR / 'official/pages.json').read_text(encoding='utf-8'))
    column = next(col for col in pages[16]['columns'] if 'Starting at 5th level' in col)
    source = norm(column.split('Destroy Undead\n', 1)[1].split('\nDestroy Undead\n', 1)[0])
    review = json.loads((c.DATA_DIR / 'official/feature-boundary-review.json').read_text(encoding='utf-8'))
    for row in review['overlay_candidates'][:5]:
        assert norm(' '.join(c.FEATURES[row['id']]['desc'])) == source
        assert c.FEATURES[row['id']]['desc'] == row['value']


def test_related_invocation_and_flexible_casting_sections_match_full_intervals():
    pages = json.loads((c.DATA_DIR / 'official/pages.json').read_text(encoding='utf-8'))
    for page, heading, end, sid, tail in [
        (48, 'Eldritch Invocations', 'Agonizing Blast', 'eldritch-invocations', 1),
        (43, 'Flexible Casting', 'Creating Spell Slots.', 'font-of-magic', 1),
    ]:
        column = norm(next(col for col in pages[page-1]['columns'] if heading in col))
        source = column.split(heading + ' ', 1)[1].split(' ' + end, 1)[0]
        assert norm(' '.join(c.FEATURES[sid]['desc'][-tail:])) == source


def test_all_seven_repairs_keep_frozen_legacy_descriptions():
    review = json.loads((c.DATA_DIR / 'official/feature-boundary-review.json').read_text(encoding='utf-8'))
    legacy = rules_packages.build_legacy_package()['records']['features']
    assert len(review['overlay_candidates']) == 7
    for row in review['overlay_candidates']:
        assert c.FEATURES[row['id']]['desc'] == row['value']
        assert legacy[row['id']]['desc'] == row['expected']

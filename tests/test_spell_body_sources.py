"""Official text fidelity is independent of execution coverage."""
import hashlib
import json
import re
import unicodedata

from backend import compendium as c
from backend.rules_packages import build_legacy_package
from tools.normalize_spell_bodies import body_fields, corrections


def stream(text):
    return re.sub('[^a-z0-9]', '', unicodedata.normalize('NFKD', text).lower())


def test_reviewed_overlays_reproduce_and_all_reviewed_bodies_match_source():
    review = json.loads((c.DATA_DIR / 'official/spell-body-review.json').read_text(encoding='utf-8'))
    blocks_path = c.DATA_DIR / 'official/spell-blocks.json'
    assert hashlib.sha256(blocks_path.read_bytes()).hexdigest() == review['official_blocks_sha256']
    blocks = {b['official_title']: b for b in json.loads(blocks_path.read_text(encoding='utf-8'))}
    changes = corrections()
    assert len(changes) == 41 and len({r['records'][0] for r in changes}) == 34
    assert [r for r in c.CANONICAL_OVERLAY['corrections'] if r['id'].startswith('official-body-')] == changes
    for row in review['differences']:
        if row['status'] == 'ready_for_source_text_overlay':
            fields = body_fields(blocks[row['official_title']])
            assert {f: c.SPELLS[row['id']][f] for f in fields} == fields
    matched = review['surface_match_set']
    assert len(matched) == 280
    for row in matched:
        spell = c.SPELLS[row['id']]
        fields = body_fields(next(b for name, b in blocks.items() if stream(name) == stream(spell['name'])))
        for field, paragraphs in fields.items():
            assert stream(' '.join(spell[field])) == stream(' '.join(paragraphs)), (row['id'], field)


def test_rule_bearing_corrections_and_source_ambiguity_remain_explicit():
    assert 'At the end of each' in ' '.join(c.SPELLS['phantasmal-killer']['desc'])
    assert 'At the end of each' in ' '.join(c.SPELLS['weird']['desc'])
    assert 'four times as many with a 9th-level slot' in ' '.join(c.SPELLS['conjure-animals']['higher_level'])
    assert '1d10' in ' '.join(c.SPELLS['moonbeam']['higher_level'])
    assert '0 hit points' in ' '.join(c.SPELLS['polymorph']['desc'])
    assert 'until it is dispelled' in ' '.join(c.SPELLS['true-polymorph']['desc'])
    assert '2nd level' in ' '.join(c.SPELLS['heroism']['higher_level'])
    review = json.loads((c.DATA_DIR / 'official/spell-body-review.json').read_text(encoding='utf-8'))
    blocked = [r for r in review['differences'] if r['category'] == 'source_ambiguity']
    assert [r['id'] for r in blocked] == ['animal-friendship']
    assert blocked[0]['recommended_canonical_fields'] is None
    assert c.SPELLS['animal-friendship']['higher_level'] == []


def test_body_corrections_do_not_rewrite_installed_historical_data():
    legacy = build_legacy_package()['records']['spells']
    assert legacy['heroism']['higher_level'] == []
    assert 'At the start of each' in ' '.join(legacy['phantasmal-killer']['desc'])
    assert legacy['true-polymorph']['desc'] != c.SPELLS['true-polymorph']['desc']

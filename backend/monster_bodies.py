"""Complete, bounded official stat sources, before per-action reconciliation."""
import hashlib
import json
from pathlib import Path

from .armor_source import source, PDF_SHA
from .monster_inventory import expected as inventory, HEADINGS_SHA
from .monster_legendary import same

BLOCKS_SHA = '5a5b3c5caf776d5c70c0a4f2744280e32768a1882470ef510c9f361fdcc08422'


def document(source_dir=None):
    source(source_dir)
    root = Path(source_dir) if source_dir else Path(__file__).parent/'data/official'
    raw = (root/'monster-blocks.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=BLOCKS_SHA:
        raise ValueError('Official monster blocks hash mismatch')
    data = json.loads(raw)
    stats,_,variants = inventory(source_dir)
    if (data['source_document_sha256']!=PDF_SHA or data['headings_sha256']!=HEADINGS_SHA
            or [b['stat_header'] for b in data['blocks']]!=stats):
        raise ValueError('Official monster blocks inventory mismatch')
    want = [dict(**v,owner='Giant Rat' if v['heading']=='Variant: Diseased Giant Rats' else 'Swarm of Insects') for v in variants]
    if data['source_variants']!=want:
        raise ValueError('Official monster variant sidebar binding mismatch')
    return data


def reference(block,binding,variants):
    return dict(heading=block['title'],printed_pages=block['printed_pages'],text=block['text'],
        selected_binding=binding,source_document_sha256=PDF_SHA,source_blocks_sha256=BLOCKS_SHA,
        source_variants=[v for v in variants if v['owner']==block['title']],
        supporting_prose=[dict(printed_pages=sorted({s['page'] for s in e['segments']}),text=e['text'],
            boundary_basis=e['boundary_basis']) for e in block['events'] if e['kind']=='narrative'],
        status='reference_pending_execution',runtime_verified=False,derived_form_eligibility_verified=False,
        limitation='Complete bounded source only. Existing trait/action/reaction descriptions and parameters require separate reconciliation. Narrative is a font/layout category and may contain rules; it must not be discarded or treated as non-mechanical.')


def expected(source_dir=None):
    data = document(source_dir)
    result = {}
    for block in data['blocks']:
        for binding in block['stat_header']['bindings']:
            result[binding['record_id']] = reference(block,binding,data['source_variants'])
    if len(result)!=334:raise ValueError('Incomplete monster source binding')
    return result


def audit(records,source_dir=None):
    rows = expected(source_dir)
    monsters = records.get('monsters',{}) if isinstance(records,dict) else {}
    monsters = monsters if isinstance(monsters,dict) else {}
    checks = []
    for rid,want in rows.items():
        record = monsters.get(rid,{})
        actual = record.get('official_stat_block_reference') if isinstance(record,dict) else None
        checks.append(dict(record=rid,field='official_stat_block_reference',expected=want,actual=actual,match=same(want,actual)))
    return dict(profile='official-monster-complete-source-v1',official_stat_blocks=317,normalized_cards=334,
        checks=checks,differences=[r for r in checks if not r['match']],limitations=[
            'Full source preservation and boundaries only; per-action transcription, parameters, form eligibility and execution are not certified.',
            'All 47 supporting prose passages are retained, including rule-bearing statements outside the typographic stat rules.'])


def issues(records):
    return ['Official monster complete source differs: '+r['record'] for r in audit(records)['differences']]

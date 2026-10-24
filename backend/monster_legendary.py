"""Source-backed legendary budgets and costs; reference data, not an executor."""
import hashlib
import json
from pathlib import Path

from .armor_source import source, PDF_SHA
from .monster_inventory import expected as inventory, HEADINGS_SHA
from .equipment_source import normalize

BLOCKS_SHA = 'ee454d03695a028f506f82b9a33dcbb2073c7b0e74a64bc4c0de9df3c32f75a3'


def expected(source_dir=None):
    pages = source(source_dir)
    root = Path(source_dir) if source_dir else Path(__file__).parent/'data/official'
    raw = (root/'monster-legendary-blocks.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=BLOCKS_SHA:
        raise ValueError('Official legendary blocks hash mismatch')
    document = json.loads(raw)
    rows,_,_ = inventory(source_dir)
    by_title = {r['title']:r for r in rows}
    if (document['source_document_sha256']!=PDF_SHA or document['headings_sha256']!=HEADINGS_SHA
            or len(document['blocks'])!=30 or sum(len(r['options']) for r in document['blocks'])!=93):
        raise ValueError('Official legendary inventory mismatch')
    general = document['general_rules']
    page_text = pages[259]['columns'][0]
    general_text = page_text.split('Legendary Creatures\n',1)[1].split("A Legendary Creature’s Lair",1)[0]
    # Curly apostrophe in the extracted page is source typography, not a scope change.
    if "A Legendary Creature's Lair" in general_text:
        general_text = general_text.split("A Legendary Creature's Lair",1)[0]
    if normalize('Legendary Creatures '+general_text)!=normalize(general['text']):
        raise ValueError('Official legendary general-rule boundary mismatch')
    result = {}
    for block in document['blocks']:
        if block['stat_header']!=by_title.get(block['title']):
            raise ValueError('Official legendary stat binding mismatch')
        for binding in block['stat_header']['bindings']:
            result[binding['record_id']] = dict(block=block,general=general,binding=binding)
    if len(result)!=32:
        raise ValueError('Official legendary form mapping mismatch')
    return result


def reference(row):
    block = row['block']
    return dict(heading=block['title'],source_document_sha256=PDF_SHA,source_blocks_sha256=BLOCKS_SHA,
        general_rules=row['general'],per_creature_prelude=block['prelude'],
        creature_text='\n'.join(r['text'] for r in block['segments']),
        printed_pages=sorted({r['page'] for r in block['segments']}),options=block['options'],
        binding=row['binding'],status='reference_pending_execution',runtime_verified=False,
        limitation='A derived form binding is not permission to use these options in that form; form eligibility and combat timing require separate adjudication.')


def same(left,right):
    try:
        return json.dumps(left,sort_keys=True,allow_nan=False)==json.dumps(right,sort_keys=True,allow_nan=False)
    except (ValueError,TypeError):
        return False


def audit(records,source_dir=None):
    wanted = expected(source_dir)
    stat_rows,_,_ = inventory(source_dir)
    monsters = records.get('monsters',{}) if isinstance(records,dict) else {}
    monsters = monsters if isinstance(monsters,dict) else {}
    checks = []
    def check(rid,path,want,got):
        checks.append(dict(record=rid,path=path,expected=want,actual=got,match=same(want,got)))
    for stat in stat_rows:
        for binding in stat['bindings']:
            rid = binding['record_id']
            record = monsters.get(rid,{})
            record = record if isinstance(record,dict) else {}
            row = wanted.get(rid)
            actions = record.get('legendary_actions',[])
            names = [a.get('name') if isinstance(a,dict) else None for a in actions] if isinstance(actions,list) else None
            options = row['block']['options'] if row else []
            check(rid,['legendary_actions','names'],[o['name'] for o in options],names)
            check(rid,['legendary_actions_budget'],row['block']['budget'] if row else None,record.get('legendary_actions_budget'))
            check(rid,['legendary_rules_reference'],reference(row) if row else None,record.get('legendary_rules_reference'))
            if row and isinstance(actions,list):
                for i,option in enumerate(options):
                    action = actions[i] if i<len(actions) and isinstance(actions[i],dict) else {}
                    check(rid,['legendary_actions',i,'legendary_cost'],option['cost'],action.get('legendary_cost'))
    return dict(profile='official-monster-legendary-v1',source_blocks_sha256=BLOCKS_SHA,
        official_blocks=30,official_options=93,normalized_cards=len(wanted),normalized_options=99,
        checks=checks,differences=[r for r in checks if not r['match']],
        limitations=['Budgets and costs are source data only; no initiative, reactions, form eligibility or legendary-action execution is certified.',
            'A cost of one without a Costs label is derived from a single legendary-action option; explicit costs and provenance remain separate.',
            'Existing option descriptions and nested damage/DC/attack fields are not rewritten or certified by this profile.'])


def issues(records):
    return ['Official legendary data differs: '+r['record']+'/'+'.'.join(map(str,r['path'])) for r in audit(records)['differences']]

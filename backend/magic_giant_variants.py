"""Giant strength table derivations; ability effects remain reference only."""
import json
import re

from .armor_source import PDF_SHA
from .equipment_source import normalize
from .magic_bodies import expected as bodies, equivalent, BLOCKS_SHA
from .magic_headers import parse_header
from .magic_consumable_variants import replaced

FAMILIES = ('belt-of-giant-strength','potion-of-giant-strength')
TYPES = {'hill','stone','frost','fire','cloud','storm'}
ROW = re.compile(r'^(Hill|Stone/frost|Frost/stone|Fire|Cloud|Storm) giant (\d+) (Uncommon|Rare|Very rare|Legendary)$')


def expected(source_dir=None):
    source = bodies(source_dir)
    records = {}
    for parent in FAMILIES:
        block = source[parent]
        marker = '\nType Strength Rarity\n' if parent.startswith('belt-') else '\nType of Giant Strength Rarity\n'
        before, table = block['text'].split(marker)
        parsed = parse_header(block['text'])
        body = normalize(before)[len(parsed['header']):].strip()
        duration = None
        if parent.startswith('belt-'):
            body, classification = body.split(' Six varieties of this belt exist,',1)
            if not classification.endswith('they have the same effect.'):
                raise ValueError('Official belt family explanation changed')
        else:
            duration_match = re.search(r'changes for (\d+ hours?)\.',body)
            if not duration_match:
                raise ValueError('Official giant potion duration missing')
            duration = duration_match[1]
            body = replaced(body,'The type of giant determines the score (see the table below).','')
            body = replaced(body,'The potion of frost giant strength and the potion of stone giant strength have the same effect.','')
        seen = set()
        lines = table.splitlines()
        if len(lines) != 5:
            raise ValueError('Official giant table row count changed')
        for line in lines:
            match = ROW.fullmatch(normalize(line))
            if not match:
                raise ValueError('Unconsumed official giant table row')
            types, score, rarity = match.groups()
            for kind in types.lower().split('/'):
                if kind in seen:
                    raise ValueError('Duplicate official giant type')
                seen.add(kind)
                rid = parent+'-'+kind
                if parent.startswith('belt-'):
                    text = replaced(body,'changes to a score granted by the belt','changes to '+score)
                    name = 'Belt of '+kind.title()+' Giant Strength'
                else:
                    text = replaced(body,'changes for '+duration,'changes to '+score+' for '+duration)
                    text = replaced(text,'a giant of the appropriate type','a '+kind+' giant')
                    name = 'Potion of '+kind.title()+' Giant Strength'
                header = parsed['item_type']+', '+rarity.lower()
                if parsed['attunement_wording']:
                    header += ' ('+parsed['attunement_wording']+')'
                records[rid] = dict(name=name,equipment_category=parsed['category'],rarity=dict(name=rarity.title()),
                    variant=True,desc=[header,text],derived_from='magic-items/'+parent,source_text_kind='derived_table_variant',
                    official_variant_reference=dict(parent_id=parent,selection_row=normalize(line),
                        selection=dict(giant_type=kind,strength_score=int(score),duration_wording=duration),
                        complete_parent_text=block['text'],printed_pages=block['printed_pages'],
                        source_document_sha256=PDF_SHA,source_blocks_sha256=BLOCKS_SHA,
                        status='reference_pending_execution',runtime_verified=False))
        if seen != TYPES:
            raise ValueError('Official giant type inventory incomplete')
    return records


def audit(records, source_dir=None):
    official = expected(source_dir)
    magic = records.get('magic-items',{}) if isinstance(records,dict) else {}
    magic = magic if isinstance(magic,dict) else {}
    checks = []
    for rid, fields in official.items():
        row = magic.get(rid,{})
        row = row if isinstance(row,dict) else {}
        for field, want in fields.items():
            got = row.get(field)
            if field == 'desc':
                match = isinstance(got,list) and bool(got) and all(isinstance(s,str) for s in got) and equivalent(' '.join(got),' '.join(want))
            else:
                try:match = json.dumps(got,sort_keys=True,allow_nan=False) == json.dumps(want,sort_keys=True,allow_nan=False)
                except (TypeError,ValueError):match = False
            checks.append(dict(record=rid,field=field,expected=want,actual=got,match=match))
    return dict(profile='official-magic-giant-variants-v1',official_families=2,normalized_variants=len(official),checks=checks,
                differences=[row for row in checks if not row['match']],
                limitations=['Twelve source variants only; Strength replacement, equal-or-higher suppression, attunement and timed effects are not executed by this transcription.'])


def issues(records):
    return ['Official magic giant variant differs: '+row['record']+'/'+row['field'] for row in audit(records)['differences']]

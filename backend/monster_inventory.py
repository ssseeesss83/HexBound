"""Independent official stat headers and explicit derived-form identity map.

This inventory does not certify stat-block text, parameters or form eligibility.
"""
import hashlib
import json
from pathlib import Path
import re

from .armor_source import source, PDF_SHA
from .equipment_source import normalize, identifier

HEADINGS_SHA = '896c018bd844f0dc5e8f1759c9c8dd27d74856047d938c41ff132c7a110deb02'
FAMILY_TITLES = {color+' Dragon' for color in ('Black','Blue','Green','Red','White','Brass','Bronze','Copper','Gold','Silver')}
ALIASES = {'Elf, Drow':('drow','Drow'), 'Gnome, Deep (Svirfneblin)':('deep-gnome-svirfneblin','Deep Gnome (Svirfneblin)')}
FORMS = {
    'Werebear':('Bear','Human','Hybrid'), 'Wereboar':('Boar','Human','Hybrid'),
    'Wererat':('Human','Hybrid','Rat'), 'Weretiger':('Human','Hybrid','Tiger'),
    'Werewolf':('Human','Hybrid','Wolf'), 'Vampire':('Vampire','Bat','Mist'),
}
EXTRAS = {'Giant Rat':[('giant-rat-diseased','Giant Rat (Diseased)')],
    'Swarm of Insects':[(identifier('Swarm of '+kind),'Swarm of '+kind) for kind in ('Beetles','Centipedes','Spiders','Wasps')]}


def expected(source_dir=None):
    pages = source(source_dir)
    root = Path(source_dir) if source_dir else Path(__file__).parent/'data/official'
    raw = (root/'headings.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != HEADINGS_SHA:
        raise ValueError('Official monster headings hash mismatch')
    headings = [row for row in json.loads(raw) if row['size']==12 and
                (261<=row['page']<=357 or 366<=row['page']<=403)]
    items,dispositions = [],[]
    for heading in headings:
        lines = pages[heading['page']-1]['columns'][heading['column']].splitlines()
        matches = [i for i,line in enumerate(lines) if normalize(line)==normalize(heading['title'])
            and i+1<len(lines) and re.match(r'^(Tiny|Small|Medium|Large|Huge|Gargantuan)\s',normalize(lines[i+1]))]
        if not matches:
            if heading['title'] not in FAMILY_TITLES:
                raise ValueError('Unclassified official monster heading: '+heading['title'])
            dispositions.append(dict(**heading,disposition='dragon_family_title_not_statblock'))
            continue
        if len(matches) != 1:
            raise ValueError('Ambiguous official monster stat header')
        row = dict(**heading,size_type_alignment_line=normalize(lines[matches[0]+1]))
        title = heading['title']
        if title in ALIASES:
            rid,name = ALIASES[title]
            bindings = [dict(record_id=rid,name=name,mapping_type='explicit_title_alias')]
        elif title in FORMS:
            bindings = [dict(record_id=identifier(title)+'-'+identifier(form),name=title+', '+form+' Form',
                             mapping_type='derived_monster_form') for form in FORMS[title]]
        else:
            bindings = [dict(record_id=identifier(title),name=normalize(title),mapping_type='official_stat_header')]
        bindings += [dict(record_id=rid,name=name,mapping_type='explicit_source_variant') for rid,name in EXTRAS.get(title,[])]
        row['bindings'] = bindings
        items.append(row)
    if (len(items)!=317 or len({row['title'] for row in items})!=317 or len(dispositions)!=10
            or {row['title'] for row in dispositions}!=FAMILY_TITLES):
        raise ValueError('Official monster stat inventory incomplete')
    rat = pages[377]['columns'][1].split('Variant: Diseased Giant Rats\n',1)[1].split('\nGiant Scorpion',1)[0]
    insects = pages[390]['columns'][1].split('Variant: Insect Swarms\n',1)[1].split('\nTiger',1)[0]
    if ('A diseased giant rat has a challenge rating' not in rat
            or any(insects.count(name+'.')!=1 for _,name in EXTRAS['Swarm of Insects'])):
        raise ValueError('Official explicit monster variant identity evidence changed')
    references = [dict(heading='Variant: Diseased Giant Rats',page=378,column=1,text=rat),
                  dict(heading='Variant: Insect Swarms',page=391,column=1,text=insects)]
    return items,dispositions,references


def audit(records,source_dir=None):
    official,dispositions,references = expected(source_dir)
    monsters = records.get('monsters',{}) if isinstance(records,dict) else {}
    monsters = monsters if isinstance(monsters,dict) else {}
    checks = []; mapped = set(); duplicate = []
    for entry in official:
        for binding in entry['bindings']:
            rid = binding['record_id']
            if rid in mapped:duplicate.append(rid)
            mapped.add(rid)
            row = monsters.get(rid,{})
            row = row if isinstance(row,dict) else {}
            want = dict(index=rid,name=binding['name'],url='/api/2014/monsters/'+rid)
            got = {field:row.get(field) for field in want}
            match = got == want
            checks.append(dict(record=rid,official_title=entry['title'],official_page=entry['page'],column=entry['column'],
                top=entry['top'],mapping_type=binding['mapping_type'],expected=want,actual=got,match=match))
    return dict(profile='official-monster-inventory-v1',source_document_sha256=PDF_SHA,headings_sha256=HEADINGS_SHA,
        official_stat_headers=len(official),normalized_records=len(mapped),candidate_records=len(monsters),mappings=checks,
        heading_dispositions=dispositions,explicit_variant_source=references,duplicate_mappings=sorted(set(duplicate)),
        unmapped_records=sorted(set(monsters)-mapped),differences=[row for row in checks if not row['match']],
        limitations=['Identity inventory only: 317 base stat headers map to 334 normalized cards; no stat, action, variant trait or form-eligibility execution is certified.',
                     'Ten dragon family headings are classified only as non-stat titles; their content is not dropped from the complete official document.'])


def issues(records):
    report = audit(records)
    return (['Official monster identity differs: '+row['record'] for row in report['differences']]
            +['Unmapped monster record: '+rid for rid in report['unmapped_records']]
            +['Duplicate monster mapping: '+rid for rid in report['duplicate_mappings']])

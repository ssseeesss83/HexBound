"""Carpet, golem manual and Valhalla horn table choices; no effect execution."""
import json
import re

from .armor_source import PDF_SHA
from .equipment_source import normalize
from .magic_bodies import expected as bodies, equivalent, BLOCKS_SHA
from .magic_headers import parse_header
from .magic_consumable_variants import replaced


def _display(text):
    return normalize(normalize(text).replace('\xad',''))


def _range(low, high=None, d100=False):
    low = int(low)
    high = int(high) if high is not None else low
    if d100 and high == 0:high = 100
    if not 1 <= low <= high <= (100 if d100 else 20):
        raise ValueError('Invalid official random-table interval')
    return [low,high]


def expected(source_dir=None):
    source = bodies(source_dir)
    records = {}

    def add(parent,key,name,desc,selection,line,block,parsed,rarity=None):
        rid = parent+'-'+key
        if rid in records:raise ValueError('Duplicate official crafting variant')
        records[rid] = dict(name=name,equipment_category=parsed['category'],rarity=rarity or parsed['rarity'],
            variant=True,desc=desc,derived_from='magic-items/'+parent,source_text_kind='derived_table_variant',
            official_variant_reference=dict(parent_id=parent,selection_row=normalize(line),selection=selection,
                complete_parent_text=block['text'],printed_pages=block['printed_pages'],source_document_sha256=PDF_SHA,
                source_blocks_sha256=BLOCKS_SHA,status='reference_pending_execution',runtime_verified=False))

    parent = 'carpet-of-flying'
    block = source[parent]; parsed = parse_header(block['text'])
    before, rest = block['text'].split('\nd100 Size Capacity Flying Speed\n')
    table, tail = rest.split('\nA carpet can carry',1)
    tail = normalize('A carpet can carry'+tail)
    if tail != 'A carpet can carry up to twice the weight shown on the table, but it flies at half speed if it carries more than its normal capacity.':
        raise ValueError('Official carpet overload rule changed')
    shared = _display(before)[len(parsed['header']):].strip()
    shared = replaced(shared,'Four sizes of carpet of flying exist. The GM chooses the size of a given carpet or determines it randomly.','')
    intervals = set(); sizes = set()
    for line in table.splitlines():
        match = re.fullmatch(r'(\d+)[–-](\d+) (\d+) ft\. × (\d+) ft\. (\d+) lb\. (\d+) feet',normalize(line))
        if not match:raise ValueError('Unconsumed official carpet row')
        low,high,width,length,capacity,speed = map(int,match.groups())
        interval = _range(low,high,d100=True)
        if intervals & set(range(low,high+1)) or (width,length) in sizes or speed % 2:
            raise ValueError('Duplicate/unsupported carpet table choice')
        intervals.update(range(low,high+1)); sizes.add((width,length))
        desc = 'This carpet is '+str(width)+' feet by '+str(length)+' feet and has a flying speed of '+str(speed)+' feet. It can carry up to '+str(capacity*2)+' pounds, but its flying speed becomes '+str(speed//2)+' feet while carrying over '+str(capacity)+' pounds.'
        add(parent,str(width)+'x'+str(length),'Carpet of Flying ('+str(width)+' ft. × '+str(length)+' ft.)',
            [parsed['header'],shared,desc],dict(d100_range=interval,size_feet=[width,length],normal_capacity_lb=capacity,
                max_capacity_lb=capacity*2,flying_speed_ft=speed,overloaded_flying_speed_ft=speed//2),line,block,parsed)
    if intervals != set(range(1,101)) or len(sizes) != 4:raise ValueError('Official carpet table incomplete')

    parent = 'manual-of-golems'
    block = source[parent]; parsed = parse_header(block['text'])
    before,rest = block['text'].split('\nd20 Golem Time Cost\n')
    table,after = rest.split('\nTo create a golem,',1)
    after = _display('To create a golem,'+after)
    shared = _display(before)[len(parsed['header']):].strip()
    shared = replaced(shared,'The GM chooses the type or determines it randomly.','')
    intervals = set(); kinds = set()
    for line in table.splitlines():
        match = re.fullmatch(r'(\d+)(?:[–-](\d+))? (Clay|Flesh|Iron|Stone) (\d+) days ([\d,]+) gp',normalize(line))
        if not match:raise ValueError('Unconsumed official golem manual row')
        low,high,kind,days,cost = match.groups()
        interval = _range(low,high)
        covered = set(range(interval[0],interval[1]+1))
        if intervals & covered or kind in kinds:raise ValueError('Duplicate manual choice')
        intervals.update(covered); kinds.add(kind)
        text = replaced(shared,'a particular type of golem',('an ' if kind == 'Iron' else 'a ')+kind.lower()+' golem')
        selected = replaced(after,'the time shown on the table',days+' days')
        selected = replaced(selected,'the specified cost',cost+' gp')
        add(parent,kind.lower(),'Manual of '+kind+' Golems',[parsed['header'],text,selected],
            dict(d20_range=interval,golem_type=kind.lower(),time_days=int(days),cost_gp=int(cost.replace(',',''))),line,block,parsed)
    if intervals != set(range(1,21)) or kinds != {'Clay','Flesh','Iron','Stone'}:
        raise ValueError('Official golem manual inventory incomplete')

    parent = 'horn-of-valhalla'
    block = source[parent]; parsed = parse_header(block['text'])
    before,rest = block['text'].split('\nd100 Horn Berserkers Requirement\nType Summoned\n')
    table,after = rest.split('\nIf you blow the horn',1)
    after = normalize('If you blow the horn'+after)
    shared = _display(before)[len(parsed['header']):].strip()
    shared,classification = shared.split(' Four types of horn of Valhalla are known to exist,',1)
    if not classification.endswith('or determines it randomly.'):
        raise ValueError('Official horn family rule changed')
    rarity_by_metal = {}
    for rarity,metals in re.findall(r'\b(very rare|rare|legendary) \(([^)]+)\)',parsed['header']):
        for metal in metals.split(' or '):rarity_by_metal[metal] = rarity
    if set(rarity_by_metal) != {'silver','brass','bronze','iron'}:
        raise ValueError('Official horn rarity mapping incomplete')
    table = normalize(table)
    pattern = re.compile(r'(\d+)[–-](\d+) (Silver|Brass|Bronze|Iron) (\d+d\d+) \+ (\d+) (None|Proficiency with all (?:simple weapons|medium armor|martial weapons))')
    intervals = set(); metals = set()
    while table:
        match = pattern.match(table)
        if not match:raise ValueError('Unconsumed official horn table data')
        line = match[0]; table = table[match.end():].strip()
        low,high,metal,dice,bonus,requirement = match.groups()
        interval = _range(low,high,d100=True)
        covered = set(range(interval[0],interval[1]+1))
        if intervals & covered or metal in metals:raise ValueError('Duplicate horn choice')
        intervals.update(covered); metals.add(metal)
        text = replaced(shared,'warrior spirits',dice+' + '+bonus+' warrior spirits')
        if requirement == 'None':
            positive = 'If you meet the requirement, they are friendly to you and your companions and follow your commands.'
            if not after.endswith(positive):raise ValueError('Official horn friendly rule changed')
            requirement_text = 'The summoned berserkers are friendly to you and your companions and follow your commands.'
        else:
            requirement_text = replaced(after,'meeting its requirement','having '+requirement.lower())
        rarity = rarity_by_metal[metal.lower()]
        add(parent,metal.lower(),metal+' Horn of Valhalla',['Wondrous item, '+rarity,text,requirement_text],
            dict(d100_range=interval,metal=metal.lower(),berserker_dice=dice,berserker_bonus=int(bonus),
                requirement=None if requirement == 'None' else requirement),line,block,parsed,rarity=dict(name=rarity.title()))
    if intervals != set(range(1,101)) or metals != {'Silver','Brass','Bronze','Iron'}:
        raise ValueError('Official horn table inventory incomplete')
    return records


def audit(records,source_dir=None):
    official = expected(source_dir)
    magic = records.get('magic-items',{}) if isinstance(records,dict) else {}
    magic = magic if isinstance(magic,dict) else {}
    checks = []
    for rid,fields in official.items():
        row = magic.get(rid,{})
        row = row if isinstance(row,dict) else {}
        for field,want in fields.items():
            got = row.get(field)
            if field == 'desc':
                match = isinstance(got,list) and bool(got) and all(isinstance(s,str) for s in got) and equivalent(' '.join(got),' '.join(want))
            else:
                try:match = json.dumps(got,sort_keys=True,allow_nan=False) == json.dumps(want,sort_keys=True,allow_nan=False)
                except (TypeError,ValueError):match = False
            checks.append(dict(record=rid,field=field,expected=want,actual=got,match=match))
    return dict(profile='official-magic-crafting-variants-v1',official_families=3,normalized_variants=len(official),checks=checks,
        differences=[row for row in checks if not row['match']],
        limitations=['Source derivation only; flight/carrying, crafting, summons, eligibility, calendar cooldowns and destruction are pending execution.'])


def issues(records):
    return ['Official magic crafting variant differs: '+row['record']+'/'+row['field'] for row in audit(records)['differences']]

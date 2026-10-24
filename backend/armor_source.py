"""Independent extraction of official armor rows and reference-only timing."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .class_growth import OFFICIAL_PAGES_SHA

PDF_SHA = '2504d2a0abb0a4d491a939be4f17910a2dde0312570ab8d208080225ccf0a1f0'
NAMES = {
    'Padded':'padded-armor','Leather':'leather-armor','Studded leather':'studded-leather-armor',
    'Hide':'hide-armor','Chain shirt':'chain-shirt','Scale mail':'scale-mail','Breastplate':'breastplate',
    'Half plate':'half-plate-armor','Ring mail':'ring-mail','Chain mail':'chain-mail',
    'Splint':'splint-armor','Plate':'plate-armor','Shield':'shield',
}


def clean(text):
    return re.sub(r'\s+',' ',text).strip()


def source(source_dir=None):
    root = Path(source_dir) if source_dir else Path(__file__).parent/'data/official'
    if hashlib.sha256((root/'SRD_CC_v5.1.pdf').read_bytes()).hexdigest()!=PDF_SHA:
        raise ValueError('Official armor PDF hash mismatch')
    raw = (root/'pages.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=OFFICIAL_PAGES_SHA:
        raise ValueError('Official armor pages hash mismatch')
    return json.loads(raw)


def expected(source_dir=None):
    pages = source(source_dir)
    first = clean(pages[62]['raw_text']).split('Armor Armor Cost Armor Class (AC)',1)[1]
    second = clean(pages[63]['raw_text']).split('Getting Into and Out of Armor',1)[0]
    table = first+' '+second
    pattern = re.compile(r'\b(?P<name>'+ '|'.join(sorted(map(re.escape,NAMES),key=len,reverse=True)) +
        r') (?P<price>[\d,]+) gp (?P<ac>\+?\d+)'
        r'(?P<dex> \+ Dex modifier(?: \(max 2\))?)? (?P<strength>—|Str \d+) '
        r'(?P<stealth>—|Disadvantage) (?P<weight>\d+) lb\.')
    rows = {}
    for match in pattern.finditer(table):
        rid = NAMES[match['name']]
        if rid in rows:raise ValueError('Duplicate official armor table row')
        headings = list(re.finditer(r'Light Armor|Medium Armor|Heavy Armor|Shield',table[:match.start()+1]))
        if not headings:raise ValueError('Official armor row has no category')
        category = headings[-1].group().replace(' Armor','')
        ac = dict(base=int(match['ac']),dex_bonus=bool(match['dex']))
        if match['dex'] and '(max 2)' in match['dex']:ac['max_bonus']=2
        rows[rid] = dict(value=dict(cost=dict(quantity=int(match['price'].replace(',','')),unit='gp'),
            weight=int(match['weight']),armor_category=category,armor_class=ac,
            str_minimum=0 if match['strength']=='—' else int(match['strength'].split()[1]),
            stealth_disadvantage=match['stealth']=='Disadvantage'),
            official_row=match.group(),official_page=63 if rid=='padded-armor' else 64)
    if set(rows)!=set(NAMES.values()):raise ValueError('Official armor table is incomplete')
    column = clean(pages[63]['columns'][0])
    interval = column.split('Getting Into and Out of Armor',1)[1].split('Weapons',1)[0].strip()
    timings = {}
    for category,don,don_unit,doff,doff_unit in re.findall(
            r'\b(Light Armor|Medium Armor|Heavy Armor|Shield) (\d+) (minutes?|action) (\d+) (minutes?|action)',interval):
        key = category.replace(' Armor','').lower()
        if key in timings:raise ValueError('Duplicate official armor timing row')
        timings[key] = dict(don=dict(amount=int(don),unit='minutes' if don_unit.startswith('minute') else 'action'),
                            doff=dict(amount=int(doff),unit='minutes' if doff_unit.startswith('minute') else 'action'))
    if set(timings)!={'light','medium','heavy','shield'}:raise ValueError('Official armor timing table is incomplete')
    for required in ["benefit from the armor's AC only if you take the full time",'If you have help, reduce this time by half.']:
        if required not in interval:raise ValueError('Official armor timing prose changed')
    reference = dict(status='reference_pending_execution',runtime_verified=False,categories=timings,
        armor_ac_requires_full_don=True,
        assistance=dict(applies_to='doff',factor=dict(numerator=1,denominator=2),
                        interpretation_pending=['fractional_action_timing']),
        source_text=interval,source_refs=dict(official_document='official/SRD_CC_v5.1.pdf',printed_pages=[64],
            source_document_sha256=PDF_SHA,heading='Getting Into and Out of Armor',
            source_text_sha256=hashlib.sha256(interval.encode()).hexdigest()))
    return rows,reference


def audit(records,source_dir=None):
    rows,reference = expected(source_dir)
    checks,diffs = [],[]
    equipment = records.get('equipment',{})
    equipment = equipment if isinstance(equipment,dict) else {}
    actual = {rid for rid,row in equipment.items() if isinstance(row,dict) and 'armor_category' in row}
    missing = object()
    def check(rid,path,want,evidence,*,absent=False):
        got = equipment.get(rid,missing)
        for key in path:got=got.get(key,missing) if isinstance(got,dict) else missing
        matched = got is missing if absent else type(got) is type(want) and got==want
        row = dict(record='equipment/'+rid,path=path,expected=None if absent else deepcopy(want),
                   expected_absent=absent,actual=None if got is missing else deepcopy(got),
                   field_missing=got is missing,match=matched,**evidence)
        checks.append(row)
        if not matched:diffs.append(row)
    for rid,row in rows.items():
        evidence = dict(official_row=row['official_row'],official_page=row['official_page'])
        value = row['value']
        for path in [['cost','quantity'],['cost','unit'],['weight'],['armor_category'],['str_minimum'],
                     ['stealth_disadvantage'],['armor_class','base'],['armor_class','dex_bonus'],['armor_class','max_bonus']]:
            want = value
            for key in path:want=want.get(key,missing) if isinstance(want,dict) else missing
            check(rid,path,want,evidence,absent=want is missing)
        got_row = equipment.get(rid,{})
        got_ac = got_row.get('armor_class',{}) if isinstance(got_row,dict) else None
        if not isinstance(got_ac,dict) or set(got_ac)!=set(value['armor_class']):
            diffs.append(dict(record='equipment/'+rid,path=['armor_class'],reason='Exact AC field set differs'))
    categories = records.get('equipment-categories',{})
    armor = categories.get('armor') if isinstance(categories,dict) else None
    timing_actual = armor.get('timing_reference') if isinstance(armor,dict) else None
    # JSON encoding distinguishes bool/int, missing/null and nested shapes.
    timing_match = json.dumps(timing_actual,sort_keys=True,ensure_ascii=False)==json.dumps(reference,sort_keys=True,ensure_ascii=False)
    return dict(scope='13 mundane armor/shield rows and reference timing only',
        source_document_sha256=PDF_SHA,source_pages_sha256=OFFICIAL_PAGES_SHA,
        expected_ids=sorted(rows),actual_ids=sorted(actual),inventory_match=actual==set(rows),
        checks=checks,diffs=diffs,timing_reference=reference,timing_match=timing_match,
        summary=dict(armor_rows=len(rows),field_checks=len(checks),field_differences=len(diffs),
                     timing_categories=len(reference['categories']),runtime_verified=False))


def issues(records):
    report = audit(records)
    errors = ['Armor source field mismatch: '+row['record']+'/'+'.'.join(row['path']) for row in report['diffs']]
    if not report['inventory_match']:errors.append('Official mundane armor inventory differs')
    if not report['timing_match']:errors.append('Official armor timing reference differs')
    return errors

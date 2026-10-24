"""Official remaining equipment measurements, separate from effect execution.

Values are parsed from the pinned PDF text, never from candidate JSON. Mapping
aliases connect official table bundles/derived records to stable community IDs.
This module does not yet sign off special-rule prose or pack contents.
"""
from copy import deepcopy
from fractions import Fraction
import re

from .armor_source import source,expected as armor_expected,clean


ALIASES={
 'ball-bearings-bag-of-1-000':('ball-bearings-bag-of-1000',None),
 'arrows-20':('arrow',20),'blowgun-needles-50':('blowgun-needle',50),
 'crossbow-bolts-20':('crossbow-bolt',20),'sling-bullets-20':('sling-bullet',20),
 'caltrops-bag-of-20':('caltrops',20),'spikes-iron-10':('spike-iron',10),
 'feed-per-day':('animal-feed-1-day',None),'stabling-per-day':('stabling-1-day',None),
 'exotic':('saddle-exotic',None),'military':('saddle-military',None),
 'pack':('saddle-pack',None),'riding':('saddle-riding',None),
}
COMPONENTS={
 'alms-box':('priests-pack','an alms box'),
 'block-of-incense':('priests-pack','2 blocks of incense'),
 'censer':('priests-pack','a censer'),
 'vestments':('priests-pack','vestments'),
 'little-bag-of-sand':('scholars-pack','a little bag of sand'),
 'small-knife':('scholars-pack','a small knife'),
 'string-10-feet':('burglars-pack','10 feet of string'),
}


def normalize(value):
    return re.sub(r'[-‐‑]+','-',clean(value)).replace('’',"'").replace('‘',"'")


def identifier(name):
    return re.sub(r'[^a-z0-9]+','-',normalize(name).casefold().replace("'",'')).strip('-')


def number(text):
    text=text.replace(',','')
    mixed=re.fullmatch(r'(\d+)([1-9])⁄(\d+)',text)
    if mixed:value=Fraction(int(mixed[1]))+Fraction(int(mixed[2]),int(mixed[3]))
    else:value=Fraction(text.replace('⁄','/'))
    return int(value) if value.denominator==1 else float(value)


def expected(source_dir=None):
    pages=source(source_dir)
    rows={}
    table_rows=0
    pattern=re.compile(r'(?P<name>.+?) (?P<price>[\d,]+) (?P<currency>cp|sp|gp) '
        r'(?P<measure>—|[\d/⁄]+ lb\.(?: \(full\))?|[\d/⁄]+ ft\. [\d,]+ lb\.|[\d/⁄]+ mph)')
    for page,column in ((69,0),(69,1),(70,1),(71,1),(72,0)):
        for line in pages[page-1]['columns'][column].splitlines():
            line=normalize(line)
            match=pattern.fullmatch(line)
            if not match:continue
            table_rows+=1
            key=identifier(match['name'])
            rid,quantity=ALIASES.get(key,(key,None))
            ids=['donkey','mule'] if key=='donkey-or-mule' else [rid]
            value=dict(cost=dict(quantity=number(match['price']),unit=match['currency']))
            measure=match['measure']
            notes={}
            if ' ft.' in measure:
                speed,capacity=re.fullmatch(r'([\d/⁄]+) ft\. ([\d,]+ lb\.)',measure).groups()
                value.update(speed=dict(quantity=number(speed),unit='ft/round'),capacity=capacity)
            elif measure.endswith('mph'):
                value['speed']=dict(quantity=number(measure.split()[0]),unit='mph')
            elif measure!='—':
                value['weight']=number(measure.split()[0])
                if '(full)' in measure:notes['weight_condition']='full'
            else:
                # A printed dash is not an assertion of exact zero pounds.
                notes['weight_status']='not_stated'
            if quantity is not None:value['quantity']=quantity
            for item_id in ids:
                if item_id in rows:raise ValueError('Duplicate official equipment row')
                rows[item_id]=dict(value=deepcopy(value),official_page=page,official_row=line,notes=deepcopy(notes),
                                   derivation='shared_donkey_or_mule_row' if len(ids)>1 else None)
    if table_rows!=161:raise ValueError('Official equipment table inventory changed')
    healing=rows.pop('potion-of-healing')
    # This table row refers to the magical item, not an extra mundane duplicate.
    potion_body=normalize(pages[67]['columns'][1]).split('Potion of Healing.',1)[1].split('Pouch.',1)[0].strip()
    potion_table=normalize(pages[233]['columns'][1])
    if 'regains 2d4 + 2 hit points' not in potion_body or 'Healing Common 2d4 + 2' not in potion_table:
        raise ValueError('Ordinary healing potion identity evidence changed')
    healing.update(mapped_record='magic-items/potion-of-healing-common',rarity='Common',variant=True,
                   identity_evidence=dict(body_page=68,body=potion_body,table_page=234,table_row='Healing Common 2d4 + 2'),
                   limitation='Only ordinary/Common healing potion; never the Varies parent or stronger variants.')
    armor,_=armor_expected(source_dir)
    barding=normalize(pages[70]['columns'][1])
    required=('The cost is four times the equivalent armor made for humanoids, and it weighs twice as much.')
    if required not in barding:raise ValueError('Official barding derivation changed')
    for rid,row in armor.items():
        if rid=='shield':continue
        item='barding-'+rid.removesuffix('-armor')
        value=row['value']
        rows[item]=dict(value=dict(cost=dict(quantity=value['cost']['quantity']*4,unit=value['cost']['unit']),
                                  weight=value['weight']*2),official_page=71,official_row=required,notes={},
                       derivation=dict(armor_record=rid,cost_factor=4,weight_factor=2,armor_page=row['official_page']))
    text=normalize(pages[69]['columns'][0]).split('Equipment Packs',1)[1].split('Tools',1)[0]
    headers=list(re.finditer(r"([A-Za-z']+ Pack) \((\d+) gp\)\.",text))
    if len(headers)!=7:raise ValueError('Official equipment packs incomplete')
    for index,match in enumerate(headers):
        rid=identifier(match[1])
        body=text[match.start():headers[index+1].start() if index+1<len(headers) else len(text)].strip()
        rows[rid]=dict(value=dict(cost=dict(quantity=int(match[2]),unit='gp')),official_page=70,
                       official_row=body,notes=dict(weight_status='not_stated'),derivation=None)
    for rid,(pack,phrase) in COMPONENTS.items():
        if phrase not in rows[pack]['official_row']:raise ValueError('Official pack component mention changed')
        rows[rid]=dict(value={},official_page=70,official_row=rows[pack]['official_row'],
            notes=dict(cost_status='not_stated',weight_status='not_stated'),
            derivation=dict(pack=pack,mention=phrase))
    if len(rows)!=187:raise ValueError('Remaining equipment mapping incomplete')
    return rows,healing


def audit(records,source_dir=None):
    expected_rows,healing=expected(source_dir)
    records=records if isinstance(records,dict) else {}
    equipment=records.get('equipment',{})
    equipment=equipment if isinstance(equipment,dict) else {}
    actual={rid for rid,row in equipment.items()
            if isinstance(row,dict) and isinstance(row.get('equipment_category'),dict)
            and row['equipment_category'].get('index') in {'adventuring-gear','tools','mounts-and-vehicles'}}
    checks=[]
    unspecified=[]
    for rid,source_row in expected_rows.items():
        row=equipment.get(rid,{})
        row=row if isinstance(row,dict) else {}
        for field,want in source_row['value'].items():
            got=row.get(field)
            # JSON measurements can be integral or fractional numbers, but
            # booleans and strings must never pass numeric comparisons.
            def strict_equal(left,right):
                if isinstance(right,dict):return isinstance(left,dict) and set(left)==set(right) and all(strict_equal(left[k],v) for k,v in right.items())
                if type(right) in (int,float):return type(left) in (int,float) and left==right
                return type(left) is type(right) and left==right
            checks.append(dict(record='equipment/'+rid,path=[field],expected=deepcopy(want),actual=deepcopy(got),
                match=strict_equal(got,want),official_page=source_row['official_page'],official_row=source_row['official_row'],
                derivation=deepcopy(source_row['derivation'])))
        for field in ('cost','weight'):
            if source_row['notes'].get(field+'_status')!='not_stated':continue
            unspecified.append(dict(record='equipment/'+rid,path=[field],expected=None,actual=deepcopy(row.get(field)),
                match=row.get(field) is None,source_status='not_stated',official_page=source_row['official_page'],
                official_row=source_row['official_row'],derivation=deepcopy(source_row['derivation'])))
    magic=records.get('magic-items',{})
    magic=magic if isinstance(magic,dict) else {}
    potion=magic.get('potion-of-healing-common',{})
    potion=potion if isinstance(potion,dict) else {}
    rarity=potion.get('rarity',{})
    parent=magic.get('potion-of-healing',{})
    variants=parent.get('variants',[]) if isinstance(parent,dict) else []
    variants=variants if isinstance(variants,list) else []
    cross_checks=[dict(record=healing['mapped_record'],check='exists',match=bool(potion)),
        dict(record=healing['mapped_record'],check='common_variant',match=isinstance(rarity,dict) and rarity.get('name')=='Common' and potion.get('variant') is True),
        dict(record=healing['mapped_record'],check='parent_relation',match=any(isinstance(row,dict) and row.get('index')=='potion-of-healing-common' for row in variants))]
    return dict(profile='remaining-equipment-measurements-v1',inventory_match=actual==set(expected_rows),
        missing_records=sorted(set(expected_rows)-actual),unexpected_records=sorted(actual-set(expected_rows)),
        checks=checks,diffs=[row for row in checks if not row['match']],
        unspecified_measurement_checks=unspecified,unspecified_measurement_diffs=[row for row in unspecified if not row['match']],
        unspecified_measurements={rid:row['notes'] for rid,row in expected_rows.items() if row['notes']},
        cross_collection_rows=[healing],cross_collection_checks=cross_checks,
        cross_collection_diffs=[row for row in cross_checks if not row['match']],
        summary=dict(records=len(expected_rows),measurement_fields=len(checks),differences=sum(not row['match'] for row in checks)),
        limitations=['Special-rule prose and pack contents are not signed off by this numeric comparison.',
                     'Printed dashes and components mentioned without prices do not prove exact zero measurements.'])


def issues(records):
    report=audit(records)
    result=[]
    if not report['inventory_match']:result.append('Remaining equipment inventory differs from official source mapping')
    result.extend('Official equipment measurement differs: '+row['record']+'/'+'.'.join(row['path']) for row in report['diffs'])
    result.extend('Official equipment cross-reference differs: '+row['record']+'/'+row['check'] for row in report['cross_collection_diffs'])
    result.extend('Unknown equipment measurement must remain null/absent: '+row['record']+'/'+'.'.join(row['path']) for row in report['unspecified_measurement_diffs'])
    return result

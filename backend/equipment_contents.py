"""Closed parsing of all seven official pack lists, not shopping inference."""
from copy import deepcopy
import re
from .equipment_source import expected as equipment_expected

# Source phrases -> stable item identity and the amount represented by one
# record. Ten feet of string / fifty feet of rope are one packaged item each.
PHRASES={
 'backpack':('backpack',1),'bag of 1,000 ball bearings':('ball-bearings-bag-of-1000',1),
 'feet of string':('string-10-feet',10),'bell':('bell',1),'candles':('candle',1),
 'crowbar':('crowbar',1),'hammer':('hammer',1),'pitons':('piton',1),
 'hooded lantern':('lantern-hooded',1),'flasks of oil':('oil-flask',1),
 'days rations':('rations-1-day',1),'days of rations':('rations-1-day',1),
 'tinderbox':('tinderbox',1),'waterskin':('waterskin',1),
 'feet of hempen rope':('rope-hempen-50-feet',50),
 'chest':('chest',1),'cases for maps and scrolls':('case-map-or-scroll',1),
 'set of fine clothes':('clothes-fine',1),'bottle of ink':('ink-1-ounce-bottle',1),
 'ink pen':('ink-pen',1),'lamp':('lamp',1),'sheets of paper':('paper-one-sheet',1),
 'vial of perfume':('perfume-vial',1),'sealing wax':('sealing-wax',1),'soap':('soap',1),
 'torches':('torch',1),'bedroll':('bedroll',1),'costumes':('clothes-costume',1),
 'disguise kit':('disguise-kit',1),'mess kit':('mess-kit',1),'blanket':('blanket',1),
 'alms box':('alms-box',1),'blocks of incense':('block-of-incense',1),
 'censer':('censer',1),'vestments':('vestments',1),'book of lore':('book',1),
 'sheets of parchment':('parchment-one-sheet',1),'little bag of sand':('little-bag-of-sand',1),
 'small knife':('small-knife',1),
}


def parse_pack(body):
    text=body.split(' Includes ',1)[1]
    parts=text.split('. The pack also has ')
    if len(parts)>2:raise ValueError('Unexpected extra pack sentence')
    phrases=parts[0].removesuffix('.').split(', ')
    if len(parts)==2:
        suffix=' strapped to the side of it.'
        if not parts[1].endswith(suffix):raise ValueError('Unexpected strapped pack contents')
        phrases.append(parts[1][:-len(suffix)])
    rows=[]
    for original in phrases:
        phrase=original.removeprefix('and ')
        match=re.fullmatch(r'(?:(a|an|\d+) )?(.+)',phrase)
        quantity=1 if match[1] in (None,'a','an') else int(match[1])
        name=match[2]
        if name not in PHRASES:raise ValueError('Unmapped official pack phrase: '+name)
        rid,unit=PHRASES[name]
        if quantity<1 or quantity%unit:raise ValueError('Official amount is not a whole packaged item')
        rows.append(dict(item_id=rid,quantity=quantity//unit,official_phrase=original,source_amount=quantity,record_amount=unit))
    if len({row['item_id'] for row in rows})!=len(rows):raise ValueError('Duplicate official pack component')
    return rows


def expected(source_dir=None):
    rows,_=equipment_expected(source_dir)
    packs={rid:dict(contents=parse_pack(row['official_row']),official_page=70,official_body=row['official_row'])
           for rid,row in rows.items() if rid.endswith('-pack') and rid!='saddle-pack'}
    if len(packs)!=7 or sum(len(row['contents']) for row in packs.values())!=66:
        raise ValueError('Official pack relation inventory incomplete')
    return packs


def audit(records,source_dir=None):
    packs=expected(source_dir)
    records=records if isinstance(records,dict) else {}
    equipment=records.get('equipment',{})
    equipment=equipment if isinstance(equipment,dict) else {}
    checks=[]
    actual={rid for rid,row in equipment.items() if isinstance(row,dict)
            and isinstance(row.get('gear_category'),dict) and row['gear_category'].get('index')=='equipment-packs'}
    for rid,source in packs.items():
        record=equipment.get(rid,{})
        record=record if isinstance(record,dict) else {}
        contents=record.get('contents',[])
        contents=contents if isinstance(contents,list) else []
        got={}
        shape_ok=True
        for item in contents:
            if not isinstance(item,dict) or not isinstance(item.get('item'),dict):shape_ok=False;continue
            target=item['item'].get('index')
            if not isinstance(target,str) or target in got:shape_ok=False;continue
            got[target]=item
        want={item['item_id'] for item in source['contents']}
        checks.append(dict(record=rid,check='component_inventory',match=shape_ok and set(got)==want))
        for item in source['contents']:
            target=item['item_id']
            candidate=got.get(target,{})
            reference=candidate.get('item',{})
            exists=isinstance(equipment.get(target),dict)
            checks.append(dict(record=rid,item_id=target,official_phrase=item['official_phrase'],
                expected_quantity=item['quantity'],actual_quantity=candidate.get('quantity'),
                source_amount=item['source_amount'],record_amount=item['record_amount'],
                match=exists and type(candidate.get('quantity')) is int and candidate['quantity']==item['quantity']
                    and reference.get('url')=='/api/2014/equipment/'+target
                    and reference.get('name')==equipment[target].get('name')))
    return dict(profile='equipment-pack-contents-v1',official_page=70,inventory_match=actual==set(packs),
        checks=checks,diffs=[row for row in checks if not row['match']],source_packs=deepcopy(packs),
        summary=dict(packs=len(packs),relations=66,checks=len(checks),differences=sum(not row['match'] for row in checks)),
        limitations=['Pack list transcription only; does not prove inventory grants, carrying limits, prices of individual unnamed components or execution.'])


def issues(records):
    report=audit(records)
    result=[] if report['inventory_match'] else ['Official equipment pack inventory differs']
    result.extend('Official equipment pack relation differs: '+row['record']+'/'+row.get('item_id','inventory') for row in report['diffs'])
    return result

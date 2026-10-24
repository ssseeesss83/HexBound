"""Whole official equipment prose blocks; no effect executor is implied."""
import re
import json
from .armor_source import source
from .equipment_source import normalize,identifier,expected as measurements,COMPONENTS

GEAR={
 'Acid':['acid-vial'],"Alchemist's Fire":['alchemists-fire-flask'],'Antitoxin':['antitoxin-vial'],
 'Arcane Focus':['crystal','orb','rod','staff','wand'],'Ball Bearings':['ball-bearings-bag-of-1000'],
 'Block and Tackle':['block-and-tackle'],'Book':['book'],'Caltrops':['caltrops'],'Candle':['candle'],
 'Case, Crossbow Bolt':['case-crossbow-bolt'],'Case, Map or Scroll':['case-map-or-scroll'],'Chain':['chain-10-feet'],
 "Climber's Kit":['climbers-kit'],'Component Pouch':['component-pouch'],'Crowbar':['crowbar'],
 'Druidic Focus':['sprig-of-mistletoe','totem','wooden-staff','yew-wand'],'Fishing Tackle':['fishing-tackle'],
 "Healer's Kit":['healers-kit'],'Holy Symbol':['amulet','emblem','reliquary'],'Holy Water':['holy-water-flask'],
 'Hunting Trap':['hunting-trap'],'Lamp':['lamp'],'Lantern, Bullseye':['lantern-bullseye'],
 'Lantern, Hooded':['lantern-hooded'],'Lock':['lock'],'Magnifying Glass':['magnifying-glass'],
 'Manacles':['manacles'],'Mess Kit':['mess-kit'],'Oil':['oil-flask'],'Poison, Basic':['poison-basic-vial'],
 'Potion of Healing':[], 'Pouch':['pouch'],'Quiver':['quiver'],'Ram, Portable':['ram-portable'],
 'Rations':['rations-1-day'],'Rope':['rope-hempen-50-feet','rope-silk-50-feet'],
 "Scale, Merchant's":['scale-merchants'],'Spellbook':['spellbook'],'Spyglass':['spyglass'],
 'Tent':['tent-two-person'],'Tinderbox':['tinderbox'],'Torch':['torch'],
}
ARTISAN=['alchemists-supplies','brewers-supplies','calligraphers-supplies','carpenters-tools',
 'cartographers-tools','cobblers-tools','cooks-utensils','glassblowers-tools','jewelers-tools',
 'leatherworkers-tools','masons-tools','painters-supplies','potters-tools','smiths-tools',
 'tinkers-tools','weavers-tools','woodcarvers-tools']
MUSICAL=['bagpipes','drum','dulcimer','flute','lute','lyre','horn','pan-flute','shawm','viol']
TOOLS={"Artisan's Tools":ARTISAN,'Disguise Kit':['disguise-kit'],'Forgery Kit':['forgery-kit'],
 'Gaming Set':['dice-set','playing-card-set'],'Herbalism Kit':['herbalism-kit'],
 'Musical Instrument':MUSICAL,"Navigator's Tools":['navigators-tools'],
 "Poisoner's Kit":['poisoners-kit'],"Thieves' Tools":['thieves-tools']}


def strip_footer(text):
    return re.sub(r'\s*System Reference Document 5\.1 \d+\s*',' ',normalize(text)).strip()


def split_sections(text,headings):
    pattern=re.compile(r'(?<!\w)('+ '|'.join(re.escape(name) for name in sorted(headings,key=len,reverse=True))+r')\.\s+')
    matches=list(pattern.finditer(text))
    if len(matches)!=len(headings) or {m[1] for m in matches}!=set(headings):
        raise ValueError('Official equipment prose headings missing or duplicated')
    return {match[1]:text[match.end():matches[i+1].start() if i+1<len(matches) else len(text)].strip()
            for i,match in enumerate(matches)}


def equivalent(left,right):
    # PDF line wrapping/punctuation typography must not erase/add words or
    # numerical tokens. Exact source blocks are still retained in the report.
    def tokens(text):
        text=normalize(text).casefold().replace('−','-').replace('–','-')
        text=re.sub(r'([+-])\s+(?=\d)',r'\1',text)
        return re.findall(r'[+-]?\d+(?:[./⁄]\d+)*|[a-z]+\d*|[%=]',text)
    return tokens(left)==tokens(right)


def section_pages(pieces,headings):
    text=' '.join(body for _,body in pieces)
    positions=[]
    offset=0
    for page,body in pieces:
        positions.append((page,offset,offset+len(body)))
        offset+=len(body)+1
    pattern=re.compile(r'(?<!\w)('+ '|'.join(re.escape(name) for name in sorted(headings,key=len,reverse=True))+r')\.\s+')
    matches=list(pattern.finditer(text))
    return {match[1]:sorted({page for page,start,end in positions
             if start<(matches[index+1].start() if index+1<len(matches) else len(text)) and end>match.start()})
            for index,match in enumerate(matches)}


def expected(source_dir=None):
    pages=source(source_dir)
    def col(page,index):return strip_footer(pages[page-1]['columns'][index])
    first=col(66,0).split('Adventuring Gear',1)[1]
    continuation=col(66,1)
    continuation=continuation[continuation.index('ranged attack against a creature or object'):]
    gear_pieces=[(66,first),(66,continuation),(67,col(67,0)),(67,col(67,1)),(68,col(68,0)),(68,col(68,1).removesuffix('Adventuring Gear').strip())]
    gear=' '.join(body for _,body in gear_pieces)
    blocks=split_sections(gear,GEAR)
    locations=section_pages(gear_pieces,GEAR)
    records={rid:dict(body=blocks[heading],heading=heading,pages=locations[heading],kind='official_shared_rule' if len(ids)>1 else 'official_rule')
             for heading,ids in GEAR.items() for rid in ids}
    left=col(70,0).rsplit('Tools',1)[1]
    right=col(70,1)
    introduction=left+' '+right.split('Tools Item Cost Weight',1)[0]
    tool_pieces=[(70,right[right.index("Artisan's Tools."):]),(71,col(71,0)),(71,col(71,1).split('Mounts and Vehicles',1)[0])]
    tool_text=' '.join(body for _,body in tool_pieces)
    tools=split_sections(tool_text,TOOLS)
    tool_locations=section_pages(tool_pieces,TOOLS)
    records.update({rid:dict(body=tools[heading],heading=heading,pages=tool_locations[heading],kind='official_shared_rule' if len(ids)>1 else 'official_rule')
                    for heading,ids in TOOLS.items() for rid in ids})
    # The introductory sentence itself mentions the table; the actual table
    # heading follows the complete Rowed Vessels paragraph.
    vehicle=col(71,1).split('Mounts and Vehicles',1)[1]
    vehicle=vehicle[:vehicle.rindex('Mounts and Other Animals')]
    vehicle_blocks=split_sections(vehicle,['Barding','Saddles','Vehicle Proficiency','Rowed Vessels'])
    from .armor_source import expected as armor_expected
    armor,_=armor_expected(source_dir)
    for rid in armor:
        if rid=='shield':continue
        records['barding-'+rid.removesuffix('-armor')]=dict(body=vehicle_blocks['Barding'],heading='Barding',pages=[71],kind='official_shared_rule')
    saddle=vehicle_blocks['Saddles']
    military,exotic=saddle.split('An exotic saddle',1)
    records['saddle-military']=dict(body=military.strip(),heading='Saddles',pages=[71],kind='official_rule')
    records['saddle-exotic']=dict(body='An exotic saddle'+exotic,heading='Saddles',pages=[71],kind='official_rule')
    for rid in ('keelboat','rowboat'):
        records[rid]=dict(body=vehicle_blocks['Rowed Vessels'],heading='Rowed Vessels',pages=[71],kind='official_shared_rule')
    return records,dict(tools=introduction.strip(),mounts=vehicle.split('Barding.',1)[0].strip(),
                        vehicle_proficiency=vehicle_blocks['Vehicle Proficiency']),blocks['Potion of Healing']


def references(source_dir=None):
    """Prose references preserve capacity facts without claiming automation."""
    pages=source(source_dir)
    table=strip_footer(pages[68]['columns'][1]).split('Container Capacity',1)[1]
    next_page=strip_footer(pages[69]['columns'][0])
    continuation,footnote=re.split(r'\*\s*You can also strap items',next_page,maxsplit=1)
    table+=' '+continuation
    pattern=re.compile(r'(Backpack\*|Barrel|Basket|Bottle|Bucket|Chest|Flask or tankard|Jug or pitcher|Pot, iron|Pouch|Sack|Vial|Waterskin)\s+')
    matches=list(pattern.finditer(table))
    if len(matches)!=13 or len({row[1] for row in matches})!=13:raise ValueError('Official container capacity inventory incomplete')
    capacity={}
    for index,match in enumerate(matches):
        name=match[1]
        rid='bottle-glass' if name=='Bottle' else identifier(name.replace('*',''))
        text=table[match.end():matches[index+1].start() if index+1<len(matches) else len(table)].strip()
        capacity[rid]=text
    _,general,_=expected(source_dir)
    def reference(blocks,pages,heading):return dict(status='reference_pending_execution',runtime_verified=False,
        blocks=blocks,printed_pages=pages,heading=heading)
    result={
        'tools':reference([general['tools']],[70],'Tools'),
        'mounts-and-vehicles':reference([general['mounts'],general['vehicle_proficiency']],[71],'Mounts and Vehicles'),
        'adventuring-gear':dict(**reference([], [69,70], 'Container Capacity'),capacities=capacity,
            backpack_note='You can also strap items'+footnote.split('Equipment Packs',1)[0].strip()),
    }
    return result


def audit(records,source_dir=None):
    expected_rows,general,potion=expected(source_dir)
    records=records if isinstance(records,dict) else {}
    equipment=records.get('equipment',{})
    equipment=equipment if isinstance(equipment,dict) else {}
    checks=[]
    for rid,evidence in expected_rows.items():
        row=equipment.get(rid,{})
        row=row if isinstance(row,dict) else {}
        desc=row.get('desc',[])
        valid=isinstance(desc,list) and all(isinstance(text,str) for text in desc)
        actual=' '.join(desc) if valid else None
        checks.append(dict(record=rid,expected=evidence['body'],actual=actual,match=valid and equivalent(actual,evidence['body']),
                           heading=evidence['heading'],official_pages=evidence['pages'],source_text_kind=evidence['kind']))
    measurement_rows,_=measurements(source_dir)
    for rid,row in measurement_rows.items():
        if not rid.endswith('-pack') or rid=='saddle-pack':continue
        candidate=equipment.get(rid,{})
        desc=candidate.get('desc') if isinstance(candidate,dict) else None
        actual=' '.join(desc) if isinstance(desc,list) and all(isinstance(s,str) for s in desc) else None
        checks.append(dict(record=rid,expected=row['official_row'],actual=actual,match=actual is not None and equivalent(actual,row['official_row']),
                           heading='Equipment Packs',official_pages=[70],source_text_kind='official_pack_list'))
    category_refs=references(source_dir)
    categories=records.get('equipment-categories',{})
    categories=categories if isinstance(categories,dict) else {}
    reference_checks=[]
    def same(left,right):
        try:return json.dumps(left,sort_keys=True,allow_nan=False)==json.dumps(right,sort_keys=True,allow_nan=False)
        except (ValueError,TypeError):return False
    for rid,want in category_refs.items():
        category=categories.get(rid,{})
        got=category.get('source_rules_reference') if isinstance(category,dict) else None
        reference_checks.append(dict(kind='equipment-categories',record=rid,path=['source_rules_reference'],expected=want,actual=got,match=same(got,want)))
    for rid,(pack,_) in COMPONENTS.items():
        want=dict(source_text_kind='derived_pack_component_caption',official_page=70,pack_id=pack,
                  official_body=measurement_rows[pack]['official_row'],cost_status='not_stated',weight_status='not_stated',runtime_verified=False)
        candidate=equipment.get(rid,{})
        got=candidate.get('component_source_reference') if isinstance(candidate,dict) else None
        reference_checks.append(dict(kind='equipment',record=rid,path=['component_source_reference'],expected=want,actual=got,match=same(got,want)))
    return dict(profile='equipment-prose-blocks-v1',checks=checks,diffs=[row for row in checks if not row['match']],
                reference_checks=reference_checks,reference_diffs=[row for row in reference_checks if not row['match']],
                general_rules=general,ordinary_healing_potion_body=potion,
                summary=dict(records=len(checks),differences=sum(not row['match'] for row in checks),reference_checks=len(reference_checks),reference_differences=sum(not row['match'] for row in reference_checks)),
                limitations=['Only whole prose comparison; no automation or transcription sign-off is granted.',
                             'Pack-only component captions are derived presentation, not separate official price/weight rules.'])


def issues(records):
    report=audit(records)
    return ['Official equipment prose differs: '+row['record'] for row in report['diffs']]+[
        'Official equipment source reference differs: '+row['record'] for row in report['reference_diffs']]

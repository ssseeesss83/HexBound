"""Official monster movement/defence/skill headers with explicit form selection.

Header summaries do not execute conditional traits or certify action parameters.
"""
from fractions import Fraction
import re

from .armor_source import source, PDF_SHA
from .equipment_source import normalize, identifier
from .monster_inventory import expected as inventory, HEADINGS_SHA
from .monster_legendary import same

LABELS = ['Saving Throws','Skills','Damage Vulnerabilities','Damage Resistances','Damage Resistance',
          'Damage Immunities','Condition Immunities','Senses','Languages','Challenge']
DAMAGE = {'acid','bludgeoning','cold','fire','force','lightning','necrotic','piercing','poison','psychic','radiant','slashing','thunder'}
CONDITIONS = {'blinded','charmed','deafened','exhaustion','frightened','grappled','incapacitated','invisible',
              'paralyzed','petrified','poisoned','prone','restrained','stunned','unconscious'}
SKILLS = {'Acrobatics','Animal Handling','Arcana','Athletics','Deception','History','Insight','Intimidation',
          'Investigation','Medicine','Nature','Perception','Performance','Persuasion','Religion','Sleight of Hand','Stealth','Survival'}


def unfooter(text):
    return re.sub(r'System Reference Document 5\.1\s+\d+','',text)


def header(pages,stat):
    cid = (stat['page']-1)*2+stat['column']
    lines = pages[cid//2]['columns'][cid%2].splitlines()
    positions = [i for i,line in enumerate(lines) if normalize(line)==normalize(stat['title']) and i+1<len(lines)
                 and re.match(r'^(Tiny|Small|Medium|Large|Huge|Gargantuan) ',normalize(lines[i+1]))]
    if len(positions)!=1:
        raise ValueError('Ambiguous monster header')
    raw = '\n'.join(lines[positions[0]:])+'\n'+pages[(cid+1)//2]['columns'][(cid+1)%2]
    text = normalize(unfooter(raw))
    challenge = re.search(r'\bChallenge ([\d/]+) \([\d,]+ XP\)',text)
    if not challenge:
        raise ValueError('Missing challenge endpoint: '+stat['title'])
    text = text[:challenge.end()]
    matches = list(re.finditer(r'\b('+'|'.join(LABELS)+r') ',text))
    fields = {m[1]:text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)].strip()
              for i,m in enumerate(matches)}
    if 'Damage Resistance' in fields:
        if 'Damage Resistances' in fields:raise ValueError('Duplicate resistance heading')
        fields['Damage Resistances'] = fields.pop('Damage Resistance')
    if len(fields)!=len(matches) or not {'Senses','Languages','Challenge'}<=fields.keys():
        raise ValueError('Missing or repeated monster header fields')
    fields['Speed'] = text.split(' Speed ',1)[1].split(' STR ',1)[0]
    return text,fields


def speed(text):
    result = {}
    for i,part in enumerate(text.split(', ')):
        m = re.fullmatch(r'(?:(walk|burrow|climb|fly|swim) )?(\d+) ft\.( \(hover\))?',part)
        if not m or m[1] is None and i!=0 or m[1] in result:
            raise ValueError('Unparsed speed: '+text)
        mode = m[1] or 'walk'
        result[mode] = m[2]+' ft.'
        if m[3]:
            if mode!='fly':raise ValueError('Hover without flight')
            result['hover'] = True
    return result


def senses(text,form):
    result = {}
    for part in text.split(', '):
        passive = re.fullmatch(r'passive Perception (\d+)',part)
        if passive:
            result['passive_perception'] = int(passive[1])
            continue
        m = re.fullmatch(r'(blindsight|darkvision|tremorsense|truesight) (\d+ ft\.(?: or \d+ ft\. while deafened)?(?: \([^()]+\))?)',part)
        if not m:raise ValueError('Unparsed senses: '+text)
        value = m[2]
        if '(rat form only)' in value:
            if form!='Rat':continue
            value = value.replace(' (rat form only)','')
        if m[1] in result:raise ValueError('Duplicate sense')
        result[m[1]] = value
    if 'passive_perception' not in result:raise ValueError('Missing passive perception')
    return result


def defences(text):
    if not text:return []
    result = []
    for group in text.split('; '):
        if group in {'damage from spells','nonmagical bludgeoning, piercing, and slashing (from stoneskin)'}:
            result.append(group)
            continue
        if ' from ' in group:
            types,condition = group.split(' from ',1)
            if not set(re.split(r', | and ',types.replace(', and ',' and ')))<=DAMAGE or not condition:
                raise ValueError('Unparsed conditional damage: '+group)
            result.append(group)
        else:
            types = group.split(', ')
            if not set(types)<=DAMAGE:raise ValueError('Unparsed damage types: '+group)
            result.extend(types)
    return result


def proficiencies(fields):
    result = []
    for field in ['Saving Throws','Skills']:
        text = fields.get(field,'')
        for part in text.split(', ') if text else []:
            m = re.fullmatch(r'(.+?) ([+−-]\d+)(?: \(([+−-]\d+) (in dim light or darkness)\))?',part)
            if not m:raise ValueError('Unparsed proficiency: '+part)
            title = m[1]
            if field=='Saving Throws':
                if title not in {'Str','Dex','Con','Int','Wis','Cha'}:raise ValueError('Unknown save')
                rid,name = 'saving-throw-'+title.lower(),'Saving Throw: '+title.upper()
            else:
                if title not in SKILLS:raise ValueError('Unknown skill')
                rid,name = 'skill-'+identifier(title),'Skill: '+title
            entry = dict(value=int(m[2].replace('−','-')),proficiency=dict(index=rid,name=name,url='/api/2014/proficiencies/'+rid))
            if m[3]:
                entry['conditional_values'] = [dict(value=int(m[3].replace('−','-')),condition=m[4],
                    status='reference_pending_execution',runtime_verified=False)]
            result.append(entry)
    return result


def proficiency_table(pages):
    text = normalize(unfooter(' '.join(pages[255]['columns'])))
    table = text.split('Proficiency Bonus by Challenge Rating Proficiency Proficiency Challenge Bonus Challenge Bonus ',1)[1].split(' Skills ',1)[0]
    values = re.findall(r'(?<![\d/])(\d+(?:/\d+)?) \+(\d+)',table)
    result = {Fraction(cr):int(bonus) for cr,bonus in values}
    if len(values)!=34 or len(result)!=34 or set(result)!={Fraction(0),Fraction(1,8),Fraction(1,4),Fraction(1,2),*map(Fraction,range(1,31))}:
        raise ValueError('Incomplete official CR/proficiency table')
    return result,table


def expected(source_dir=None):
    pages = source(source_dir)
    stats,_,variant_refs = inventory(source_dir)
    bonus,bonus_text = proficiency_table(pages)
    vampire = normalize(unfooter(pages[351]['columns'][1].split('Shapechanger.',1)[1]+' '+pages[352]['columns'][0].split('Legendary Resistance',1)[0]))
    if ('walking speed is 5 feet' not in vampire or 'flying speed of 30 feet' not in vampire
            or 'flying speed of 20 feet, can hover' not in vampire):
        raise ValueError('Vampire form evidence changed')
    variants = {r['heading']:r for r in variant_refs}
    result = {}
    for stat in stats:
        full,fields = header(pages,stat)
        for binding in stat['bindings']:
            rid = binding['record_id']
            form = binding['name'].rsplit(', ',1)[-1].removesuffix(' Form') if binding['mapping_type']=='derived_monster_form' else None
            raw_speed = fields['Speed']
            evidence = []
            if ' in ' in raw_speed:
                m = re.fullmatch(r'(\d+ ft\.) \((\d+ ft\.(?:, climb \d+ ft\.)?) in (bear or hybrid|boar|tiger|wolf) form\)',raw_speed)
                if not m:raise ValueError('Unclassified conditional speed')
                selection = form and form.lower() in m[3].split(' or ')
                raw_speed = m[2] if selection else m[1]
                evidence.append(dict(kind='selected_form_speed',text=fields['Speed'],form=form))
            moves = speed(raw_speed)
            if stat['title']=='Vampire' and form in {'Bat','Mist'}:
                moves = speed('5 ft., fly 30 ft.' if form=='Bat' else 'fly 20 ft. (hover)')
                evidence.append(dict(kind='selected_vampire_shapechanger',printed_pages=[352,353],text=vampire,form=form))
            if rid=='swarm-of-beetles':
                if 'burrowing\nspeed of 5 feet' not in variants['Variant: Insect Swarms']['text']:raise ValueError('Beetle speed evidence changed')
                moves['burrow'] = '5 ft.'
            if rid=='swarm-of-wasps':
                if 'of 5 feet, a flying speed of 30 feet, and no climbing speed' not in normalize(variants['Variant: Insect Swarms']['text']):raise ValueError('Wasp speed evidence changed')
                moves = speed('5 ft., fly 30 ft.')
            cr = Fraction(fields['Challenge'].split(' ',1)[0])
            if rid=='giant-rat-diseased':
                rat_cr = re.search(r'challenge rating of ([\d/]+)',normalize(variants['Variant: Diseased Giant Rats']['text']))
                if not rat_cr:raise ValueError('Diseased rat challenge evidence changed')
                cr = Fraction(rat_cr[1])
            if binding['mapping_type']=='explicit_source_variant':
                evidence.append(variants['Variant: Diseased Giant Rats' if rid=='giant-rat-diseased' else 'Variant: Insect Swarms'])
            conditions = fields.get('Condition Immunities','').split(', ') if fields.get('Condition Immunities') else []
            if not set(conditions)<=CONDITIONS:raise ValueError('Unknown condition immunity')
            values = dict(speed=moves,proficiencies=proficiencies(fields),senses=senses(fields['Senses'],form),
                languages='' if fields['Languages']=='—' else fields['Languages'],
                challenge_rating=int(cr) if cr.denominator==1 else float(cr),proficiency_bonus=bonus[cr],
                condition_immunities=[dict(index=c,name=c.capitalize(),url='/api/2014/conditions/'+c) for c in conditions])
            for label in ['Damage Vulnerabilities','Damage Resistances','Damage Immunities']:
                values[identifier(label).replace('-','_')] = defences(fields.get(label,''))
            values['official_header_reference'] = dict(heading=stat['title'],page=stat['page'],column=stat['column'],
                text=full,fields=fields,binding=binding,selected_form_evidence=evidence,
                proficiency_bonus_basis=dict(page=256,heading='Proficiency Bonus by Challenge Rating',text=bonus_text),
                source_document_sha256=PDF_SHA,headings_sha256=HEADINGS_SHA,status='reference_pending_execution',runtime_verified=False,
                limitation='Header fields and explicit speed/sense selections only. Conditional trait modifiers, action eligibility, damage predicates, speech constraints and combat execution require separate adjudication; empty header lists are not proof that traits grant no effects.')
            result[rid] = values
    if len(result)!=334:raise ValueError('Incomplete monster header mapping')
    return result


def audit(records,source_dir=None):
    rows = expected(source_dir)
    monsters = records.get('monsters',{}) if isinstance(records,dict) else {}
    monsters = monsters if isinstance(monsters,dict) else {}
    checks = []
    for rid,values in rows.items():
        record = monsters.get(rid,{})
        record = record if isinstance(record,dict) else {}
        for field,want in values.items():
            actual = record.get(field)
            checks.append(dict(record=rid,field=field,expected=want,actual=actual,match=same(actual,want)))
    return dict(profile='official-monster-headers-v1',official_stat_headers=317,normalized_cards=len(rows),checks=checks,
        differences=[r for r in checks if not r['match']],limitations=[
            'Only the listed header fields and selected speed/sense variants are certified; traits/actions/reactions/legendary prose, conditional modifiers and execution are separate.',
            'Conditional resistance/immunity phrases are preserved as complete source strings; this is not a damage predicate executor.'])


def issues(records):
    return ['Official monster header differs: '+r['record']+'/'+r['field'] for r in audit(records)['differences']]

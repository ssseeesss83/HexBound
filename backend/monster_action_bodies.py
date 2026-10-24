"""Source-first monster trait/action prose, nested choices and form selection.

Names are stable catalog identities; source labels retain usage and form limits.
No nested attack/damage/DC/usage parameters or execution are certified here.
"""
from collections import Counter
import re

from .monster_bodies import document, BLOCKS_SHA
from .armor_source import PDF_SHA
from .equipment_source import normalize
from .monster_legendary import same
from .magic_bodies import equivalent

SECTIONS = ('special_abilities','actions','reactions','legendary_actions')
ALIASES = {
    ('Hezrou','actions','Claw'):'Claws',
    ('Quasit','actions','Claws (Bite in Beast Form)'):'Claw (Bite in Beast Form)',
    ('Ghast','special_abilities','Turning Defiance'):'Turn Defiance',
    ('Assassin','special_abilities','Sneak Attack'):'Sneak Attack (1/Turn)',
    ('Weretiger','special_abilities','Pounce (Tiger or Hybrid Form Only)'):'Pounce',
}


def display(text):
    return re.sub(r'-\s+(?=\w)','-',normalize(normalize(text).replace('\u00ad','')))


def primary_events(block):
    result=[]
    for index,event in enumerate(block['events']):
        if event['kind']!='label':continue
        if event['section']=='actions' and event['font'].endswith('+Calibri-Bold'):
            if not result:raise ValueError('Nested action without parent')
            parent=result[-1]
            base=parent['event']['name'].split(' (',1)[0]
            if base=='Breath Weapons' and 'Dragon' in block['title']:
                pass
            elif base=='Roar' and block['title']=='Androsphinx':
                pass
            else:raise ValueError('Unclassified plain-bold action: '+block['title']+' / '+event['name'])
            parent['nested'].append(event)
            continue
        result.append(dict(index=index,event=event,nested=[]))
    return result


def canonical_name(title,section,label):
    alias=ALIASES.get((title,section,label))
    if alias:return alias
    name=re.sub(r' \((?:Recharge [\d–-]+|Recharges after a Short or Long Rest|\d+/Day)\)$','',label)
    if title in {'Werebear','Wereboar','Wererat','Weretiger','Werewolf','Vampire'} and section=='actions':
        name=re.sub(r' \([A-Za-z ]+ Form Only\)$','',name)
    return name


def eligible(label,form):
    match=re.search(r' \(([A-Za-z ]+) Form Only\)$',label)
    if not match or form is None:return True
    choices=match[1].replace('Humanoid','Human').split(' or ')
    return form in choices


def content(text):
    text=display(text)
    if '.' not in text:raise ValueError('Source action label has no end')
    return text.split('.',1)[1].strip()


def action_reference(block,binding,entry,text,variant=None):
    event=entry['event']
    return dict(heading=block['title'],source_label=event['name'],section=event['section'],
        source_text=text,printed_pages=sorted({s['page'] for e in [event,*entry['nested']] for s in e['segments']}
            | ({variant['page']} if variant else set())),
        source_event_index=entry['index'],nested_labels=[e['name'] for e in entry['nested']],selected_binding=binding,
        source_document_sha256=PDF_SHA,source_blocks_sha256=BLOCKS_SHA,source_variant=variant,
        status='reference_pending_execution',runtime_verified=False,
        limitation='Complete prose and explicit source labels only; nested numeric parameters, conditional modifiers, form eligibility in play and timing/resource execution require separate reconciliation.')


def variant_sections(data):
    source=next(v for v in data['source_variants'] if v['owner']=='Swarm of Insects')
    text=display(source['text'])
    labels=['Swarm of Beetles','Swarm of Centipedes','Swarm of Spiders','Swarm of Wasps']
    result={}
    for i,label in enumerate(labels):
        selected=text.split(label+'. ',1)[1]
        if i+1<len(labels):selected=selected.split(labels[i+1]+'. ',1)[0].strip()
        result[label]=selected
    return source,result


def expected(source_dir=None):
    data=document(source_dir)
    insect_source,insects=variant_sections(data)
    rat_source=next(v for v in data['source_variants'] if v['owner']=='Giant Rat')
    rat_text='Bite. '+display(rat_source['text']).split('Bite. ',1)[1]
    rows={}; counts=Counter(); source_counts=Counter(); nested_count=0
    for block in data['blocks']:
        entries=primary_events(block)
        source_counts.update(e['event']['section'] for e in entries)
        nested_count+=sum(len(e['nested']) for e in entries)
        for binding in block['stat_header']['bindings']:
            rid=binding['record_id']
            form=binding['name'].rsplit(', ',1)[-1].removesuffix(' Form') if binding['mapping_type']=='derived_monster_form' else None
            selected={section:[] for section in SECTIONS}
            for entry in entries:
                event=entry['event']; section=event['section']; label=event['name']
                if not eligible(label,form):continue
                if block['title']=='Vampire' and form=='Mist' and section=='actions':
                    # The preserved Shapechanger source explicitly prohibits
                    # actions. Legendary entries remain reference metadata
                    # here, as in the separately reviewed cost profile.
                    if "can't take any actions" not in display(block['text']):raise ValueError('Mist action prohibition lost')
                    continue
                text='\n'.join(e['text'] for e in [event,*entry['nested']])
                variant=None
                if rid=='giant-rat-diseased' and section=='actions' and label=='Bite':
                    text=rat_text
                    variant=rat_source
                elif rid=='swarm-of-centipedes' and section=='actions' and label=='Bites':
                    text+='\n'+insects['Swarm of Centipedes']
                    variant=insect_source
                selected[section].append(dict(name=canonical_name(block['title'],section,label),desc=content(text),
                    official_action_reference=action_reference(block,binding,entry,text,variant)))
            if rid=='swarm-of-spiders':
                spider=insects['Swarm of Spiders']
                labels=['Spider Climb','Web Sense','Web Walker']
                for i,label in enumerate(labels):
                    body=spider.split(label+'. ',1)[1]
                    if i+1<len(labels):body=body.split(labels[i+1]+'. ',1)[0].strip()
                    selected['special_abilities'].append(dict(name=label,desc=body,official_action_reference=dict(
                        heading='Variant: Insect Swarms',source_label=label,section='special_abilities',source_text=label+'. '+body,
                        printed_pages=[insect_source['page']],source_variant=insect_source,selected_binding=binding,
                        source_document_sha256=PDF_SHA,source_blocks_sha256=BLOCKS_SHA,
                        status='reference_pending_execution',runtime_verified=False,
                        limitation='Explicit Swarm of Spiders source trait; no grant to ordinary Spider and no effect execution certified.')))
            for section,values in selected.items():
                if len({a['name'] for a in values})!=len(values):raise ValueError('Duplicate canonical action name')
                counts[section]+=len(values)
            rows[rid]=selected
    if (source_counts!={'special_abilities':507,'actions':817,'reactions':12,'legendary_actions':93}
            or nested_count!=43 or len(rows)!=334):
        raise ValueError('Incomplete primary action source inventory')
    return rows,dict(counts)


def audit(records,source_dir=None):
    rows,counts=expected(source_dir)
    monsters=records.get('monsters',{}) if isinstance(records,dict) else {}
    monsters=monsters if isinstance(monsters,dict) else {}
    checks=[]
    for rid,sections in rows.items():
        record=monsters.get(rid,{})
        record=record if isinstance(record,dict) else {}
        for section,wanted in sections.items():
            actions=record.get(section,[])
            actions=actions if isinstance(actions,list) else [None]
            names=[a.get('name') if isinstance(a,dict) else None for a in actions]
            want_names=[a['name'] for a in wanted]
            checks.append(dict(record=rid,section=section,action=None,field='names',expected=want_names,actual=names,
                comparison='unique_name_inventory',match=all(isinstance(n,str) for n in names) and Counter(names)==Counter(want_names)))
            for want in wanted:
                positions=[i for i,a in enumerate(actions) if isinstance(a,dict) and a.get('name')==want['name']]
                i=positions[0] if len(positions)==1 else None
                actual=actions[i] if i is not None else {}
                for field in ['desc','official_action_reference']:
                    got=actual.get(field)
                    match=isinstance(got,str) and equivalent(got,want[field]) if field=='desc' else same(got,want[field])
                    checks.append(dict(record=rid,section=section,action=want['name'],position=i,field=field,
                        expected=want[field],actual=got,match=match))
    return dict(profile='official-monster-action-prose-v1',normalized_cards=334,normalized_entries=counts,
        checks=checks,differences=[r for r in checks if not r['match']],limitations=[
            'Full prose/labels and selected source variants only; nested parameters and execution remain separate.',
            'Legendary metadata on a derived form is not permission to act in that form.'])


def issues(records):
    return ['Official monster action prose differs: '+r['record']+'/'+r['section']+'/'+str(r['action'])+'/'+r['field']
        for r in audit(records)['differences']]

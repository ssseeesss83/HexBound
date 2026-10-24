"""Limited new clue registration, not arbitrary goals, physical items or NPCs."""
from copy import deepcopy
import hashlib
import json
import re
from typing import Literal

from pydantic import Field

from .schemas import Identifier, StrictModel

PROFILE = 'clue-registration-v1'
# Server product recipes choose methods; only the typical DC table is a source
# transcription (SRD 5.1 p77). These groups do not claim universal skill rules.
METHODS = dict(observe=['investigation','perception'],trail=['perception','survival'],
               lore=['arcana','history','nature','religion'],behavior=['insight'])
DIFFICULTIES = dict(very_easy=5,easy=10,medium=15,hard=20,very_hard=25,nearly_impossible=30)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def compiler_digest():
    return digest(dict(profile=PROFILE,methods=METHODS,difficulties=DIFFICULTIES,
                       question='resolve-clue',scope='party',evidence=[],success='set_own_resolution_true',failure=[]))


class Clue(StrictModel):
    kind: Literal['clue']
    id: Identifier
    node_id: Identifier
    resolution_fact_id: Identifier
    name: str = Field(min_length=1,max_length=80)
    internal_description: str = Field(min_length=1,max_length=1000)


class RegisteredClue(Clue):
    source_job_id: Identifier
    source_frontier_id: Identifier
    lineage: list[Identifier] = Field(min_length=1,max_length=200)
    challenge_id: Identifier
    objective_key: Identifier
    skill_ids: list[str] = Field(min_length=1,max_length=6)
    dc: int = Field(ge=5,le=30)
    compiler_digest: str = Field(pattern=r'^[0-9a-f]{64}$')


class ClueRequest(StrictModel):
    node_id: Identifier
    target_clue_id: Identifier
    method_recipe: Literal['observe','trail','lore','behavior']
    difficulty: Literal['very_easy','easy','medium','hard','very_hard','nearly_impossible']
    label: str = Field(min_length=1,max_length=100)
    success_text: str = Field(min_length=1,max_length=2000)
    failure_text: str = Field(min_length=1,max_length=2000)


def compile_clues(patch,authorization,existing):
    """Return new node copies and immutable clue metadata, never state effects."""
    from .story_graph import StoryChallenge
    nodes = deepcopy(patch['new_nodes'])
    by_node = {row['id']:row for row in nodes}
    fact_rows = deepcopy(patch['new_fact_definitions'])
    facts = {row['id']:row for row in fact_rows}
    clues = patch['new_entities']
    requests = patch['new_challenges']
    if len({row['id'] for row in clues})!=len(clues) or len({row['resolution_fact_id'] for row in clues})!=len(clues):
        raise ValueError('线索及其解析标记必须一对一')
    if len({row['target_clue_id'] for row in requests})!=len(requests):
        raise ValueError('同一线索不能通过不同方法或难度创建多个挑战')
    request_map = {row['target_clue_id']:row for row in requests}
    if set(request_map)!={row['id'] for row in clues}:
        raise ValueError('每个新线索必须且只能登记一个挑战')
    prefix = authorization['namespace']
    results = []
    lineage = authorization['frontier_lineage']
    names = set()
    for clue in clues:
        node = by_node.get(clue['node_id'])
        fact = facts.get(clue['resolution_fact_id'])
        if (not clue['id'].startswith(prefix) or node is None or node['kind'] not in {'scene','key'}
                or node['place_id'] in authorization['allowed_existing_place_ids']):
            raise ValueError('新线索只能登记在任务新增的独立可玩地点')
        name_key = (node['place_id'] or node['id'],re.sub(r'\s+',' ',clue['name']).strip().casefold())
        if name_key in names or any(old['id']==clue['id'] or old['resolution_fact_id']==clue['resolution_fact_id'] for old in existing):
            raise ValueError('不能为同地点同名线索或已登记身份重新创建目标')
        names.add(name_key)
        if (fact is None or fact['value_type']!='boolean' or type(fact['initial']) is not bool
                or fact['initial'] or not fact['mutable'] or fact['kind']!='state'):
            raise ValueError('线索须绑定自身新增的未解析状态，不能把内容真假当解析标记')
        fact['description'] = 'Resolution marker for clue '+clue['id']+': false means unresolved; true means resolved. It does not assert clue truth, ownership, or any audience knowledge.'
        fact['visibility'] = 'dm_secret'
        request = request_map[clue['id']]
        if request['node_id']!=clue['node_id']:
            raise ValueError('线索与挑战不能跨节点登记')
        challenge_id = 'clue-'+digest(clue['id'])[:48]
        objective = 'clue-'+digest(dict(clue=clue['id'],question='resolve-clue'))[:48]
        # IDs and the only writable effect are server-derived. No model ID,
        # DC, evidence, attempt scope or arbitrary consequence is accepted.
        challenge = StoryChallenge(id=challenge_id,objective_key=objective,question_id='resolve-clue',
            label=request['label'],skill_ids=METHODS[request['method_recipe']],dc=DIFFICULTIES[request['difficulty']],
            success_text=request['success_text'],failure_text=request['failure_text'],
            success_effects=[dict(op='set_fact',ref=clue['resolution_fact_id'],value=True)],failure_effects=[]).model_dump(mode='json')
        node['challenges'].append(challenge)
        metadata = RegisteredClue(**clue,source_job_id=authorization['job_id'],
            source_frontier_id=authorization['frontier_id'],lineage=lineage,
            challenge_id=challenge_id,objective_key=objective,skill_ids=challenge['skill_ids'],dc=challenge['dc'],
            compiler_digest=compiler_digest()).model_dump(mode='json')
        results.append(metadata)
    for node in nodes:
        if node['kind']=='frontier':
            refs = node['continuation']['confirmed_fact_ids']
            node['continuation']['confirmed_fact_ids']=list(dict.fromkeys(refs+[row['resolution_fact_id'] for row in results]))
    return nodes,results,fact_rows


def validate_clues(clues,book):
    nodes = {row['id']:row for row in book['nodes']}
    facts = {row['id']:row for row in book['fact_definitions']}
    if len({row['id'] for row in clues})!=len(clues) or len({row['resolution_fact_id'] for row in clues})!=len(clues):
        raise ValueError('运行线索身份或解析标记冲突')
    for clue in clues:
        node = nodes.get(clue['node_id'])
        fact = facts.get(clue['resolution_fact_id'])
        if node is None or node['kind'] not in {'scene','key'} or fact is None:
            raise ValueError('运行线索引用不存在')
        if (len(set(clue['lineage']))!=len(clue['lineage']) or clue['lineage'][-1]!=clue['source_frontier_id']
                or any(ref not in nodes or nodes[ref]['kind']!='frontier' for ref in clue['lineage'])):
            raise ValueError('运行线索来源谱系无效')
        if fact['kind']!='state' or fact['value_type']!='boolean' or fact['initial'] is not False or not fact['mutable']:
            raise ValueError('运行线索解析标记无效')
        challenge = next((row for row in node['challenges'] if row['id']==clue['challenge_id']),None)
        if (challenge is None or challenge['question_id']!='resolve-clue' or challenge['evidence_fact_ids']
                or challenge['objective_key']!=clue['objective_key'] or challenge['skill_ids']!=clue['skill_ids']
                or challenge['dc']!=clue['dc'] or challenge['condition'] is not None
                or challenge['repeat_policy']!='once_per_evidence'
                or challenge['attempt_scope']!='party' or challenge['failure_effects']
                or challenge['success_effects']!=[dict(op='set_fact',ref=clue['resolution_fact_id'],value=True,state=None)]):
            raise ValueError('运行线索与服务器登记结果不一致')

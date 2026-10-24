"""Pure effective graph reads and condition snapshots for the v2 runtime.

No execution, publication or generation is enabled here. Frontier resolutions
are separate attachments; frozen author nodes are never rewritten in storage.
"""
from copy import deepcopy
import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, field_validator

from . import story_graph as g
from .schemas import Identifier, StrictModel
from .story_registration import RegisteredClue,validate_clues

Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class GraphCommit(StrictModel):
    job_id: Identifier
    revision: int = Field(ge=1)
    patch_digest: Digest
    frontier_id: Identifier
    entry_node_id: Identifier
    compiled_digest: Digest | None = None
    compiler_digest: Digest | None = None


class VersionOne(StrictModel):
    schema_version: Literal[1] = 1

    @field_validator('schema_version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('剧情状态版本必须是整数')
        return value


class RuntimeGraph(VersionOne):
    author_digest: Digest
    graph_revision: int = Field(default=0, ge=0)
    nodes: list[g.StoryNode] = Field(default_factory=list, max_length=200)
    edges: list[g.StoryEdge] = Field(default_factory=list, max_length=1200)
    fact_definitions: list[g.FactDefinition] = Field(default_factory=list, max_length=200)
    frontier_resolutions: dict[Identifier, Identifier] = Field(default_factory=dict, max_length=200)
    commits: list[GraphCommit] = Field(default_factory=list, max_length=200)
    narrative_entities: list[RegisteredClue] = Field(default_factory=list,max_length=200)


class ValueState(StrictModel):
    value: g.Value
    revision: int = Field(default=0, ge=0)


class MilestoneState(StrictModel):
    value: Literal['pending', 'achieved', 'failed', 'bypassed']
    revision: int = Field(default=0, ge=0)


class Presence(StrictModel):
    value: bool = False
    revision: int = Field(default=0, ge=0)


class StoryState(VersionOne):
    author_digest: Digest
    revision: int = Field(default=0, ge=0)
    facts: dict[Identifier, ValueState] = Field(max_length=200)
    milestones: dict[Identifier, MilestoneState] = Field(max_length=100)
    events: dict[Identifier, Presence] = Field(max_length=200)
    items: dict[Identifier, Presence] = Field(max_length=100)
    effect_receipts: dict[Identifier, Digest] = Field(default_factory=dict, max_length=10000)


def digest(book):
    return hashlib.sha256(json.dumps(book, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def initialize(book):
    """Return initial sparse state without mutating authors or entering a node."""
    author = g.parse_book(book)
    identity = digest(author)
    graph = RuntimeGraph(author_digest=identity).model_dump(mode='json', by_alias=True)
    state = StoryState(author_digest=identity,
        facts={row['id']: dict(value=row['initial']) for row in author['fact_definitions']},
        milestones={row['id']: dict(value=row['initial_state']) for row in author['milestones']},
        events={sid:dict(value=False) for sid in author['event_ids']},
        items={sid:dict(value=False) for sid in author['item_ids']}).model_dump(mode='json')
    return dict(runtime_graph=graph, story_state=state)


def effective_book(book, runtime_graph=None):
    """Validate a combined topology through a disposable resolved view.

    The returned book retains immutable frontiers and a separate attachment map.
    A temporary validation graph redirects incoming exits, never a playable
    frontier. Limits apply to the total author-plus-room graph.
    """
    author = g.parse_book(book)
    raw = initialize(author)['runtime_graph'] if runtime_graph is None else runtime_graph
    g._preflight(raw)
    extension = RuntimeGraph.model_validate(raw).model_dump(mode='json', by_alias=True)
    if extension['author_digest'] != digest(author):
        raise ValueError('运行图不属于这个冻结作者版本')
    commits = extension['commits']
    if (extension['graph_revision'] != len(commits)
            or [row['revision'] for row in commits] != list(range(1, len(commits) + 1))
            or len({row['job_id'] for row in commits}) != len(commits)
            or len({row['frontier_id'] for row in commits}) != len(commits)
            or {row['frontier_id']:row['entry_node_id'] for row in commits} != extension['frontier_resolutions']):
        raise ValueError('运行图版本与提交来源不一致')
    if not commits and any(extension[field] for field in ['nodes','edges','fact_definitions','narrative_entities']):
        raise ValueError('运行扩展缺少提交来源')
    for commit in commits:
        if (commit['compiled_digest'] is None)!=(commit['compiler_digest'] is None):
            raise ValueError('编译来源摘要不完整')
        if commit['compiled_digest'] is not None:
            prefix = 'r'+commit['job_id']+'_'
            increment = dict(nodes=[row for row in extension['nodes'] if row['id'].startswith(prefix)],
                edges=[row for row in extension['edges'] if row['id'].startswith(prefix)],
                fact_definitions=[row for row in extension['fact_definitions'] if row['id'].startswith(prefix)],
                narrative_entities=[row for row in extension['narrative_entities'] if row['source_job_id']==commit['job_id']],
                compiler_digest=commit['compiler_digest'])
            if digest(increment)!=commit['compiled_digest']:
                raise ValueError('运行图与已审查编译增量不一致')
    combined = deepcopy(author)
    for field in ['nodes', 'edges', 'fact_definitions']:
        ids = [row['id'] for row in author[field] + extension[field]]
        if len(ids) != len(set(ids)):
            raise ValueError('运行图不能覆盖已有 ' + field)
        combined[field] += deepcopy(extension[field])
    if len(combined['nodes']) > 200 or len(combined['edges']) > 1200 or len(combined['fact_definitions']) > 200:
        raise ValueError('运行图累计规模超过上限')
    nodes = {row['id']:row for row in combined['nodes']}
    resolutions = extension['frontier_resolutions']
    for frontier, destination in resolutions.items():
        if frontier not in nodes or nodes[frontier]['kind'] != 'frontier':
            raise ValueError('续写接入点必须是已有 frontier')
        if destination not in nodes or nodes[destination]['kind'] not in {'key', 'scene'}:
            raise ValueError('续写目的地必须是可玩节点')
    validation = deepcopy(combined)
    validation['nodes'] = [row for row in validation['nodes'] if row['id'] not in resolutions]
    for edge in validation['edges']:
        if edge['from'] in resolutions:
            raise ValueError('不能向冻结 frontier 添加后继边')
        edge['to'] = resolutions.get(edge['to'], edge['to'])
    for node in validation['nodes']:
        for action in node['legacy_actions']:
            for field in ['next_node_id', 'success_node_id', 'failure_node_id']:
                if action.get(field) in resolutions:
                    action[field] = resolutions[action[field]]
    g.parse_book(validation)
    validate_clues(extension['narrative_entities'],combined)
    for clue in extension['narrative_entities']:
        if not any(row['job_id']==clue['source_job_id'] and row['frontier_id']==clue['source_frontier_id']
                   and row['compiler_digest']==clue['compiler_digest']
                   and row['compiled_digest'] is not None for row in commits):
            raise ValueError('运行线索缺少对应编译来源')
    return dict(book=combined, frontier_resolutions=deepcopy(resolutions),
                graph_revision=extension['graph_revision'], author_digest=extension['author_digest'],
                narrative_entities=deepcopy(extension['narrative_entities']))


def destination(view, node_id):
    """An unresolved frontier is a wait target, never an empty scene or ending."""
    nodes = {row['id']:row for row in view['book']['nodes']}
    if node_id not in nodes:
        raise ValueError('目标节点不存在')
    row = nodes[node_id]
    if row['kind'] == 'frontier':
        resolved = view['frontier_resolutions'].get(node_id)
        if resolved is None:
            return dict(status='pending', frontier_id=node_id, node_id=None)
        return dict(status='ready', frontier_id=node_id, node_id=resolved)
    return dict(status='ready', frontier_id=None, node_id=node_id)


def node(state, node_id):
    """One frozen-node reader; v1 compatibility never calls entry hooks."""
    campaign = state['campaign']
    author = campaign['package']['scenario']
    version = author.get('schema_version', 1)
    if version == 1:
        nodes = author['nodes']
    elif version == 2:
        nodes = effective_book(author, campaign.get('runtime_graph'))['book']['nodes']
    else:
        raise ValueError('未知剧情运行版本')
    found = next((row for row in nodes if row['id'] == node_id), None)
    if found is None:
        raise ValueError('当前剧情节点不存在')
    return deepcopy(found)


def validate_state(view, story_state):
    """Return a typed copy of authoritative state without granting knowledge."""
    book = view['book']
    g._preflight(story_state)
    state = StoryState.model_validate(story_state).model_dump(mode='json')
    if state['author_digest'] != view['author_digest']:
        raise ValueError('剧情事实不属于这个作者版本')
    definitions = {row['id']:row for row in book['fact_definitions']}
    allowed = dict(facts=set(definitions), milestones={row['id'] for row in book['milestones']},
                   events=set(book['event_ids']), items=set(book['item_ids']))
    if any(set(state[kind]) != refs for kind, refs in allowed.items()):
        raise ValueError('剧情事实集合与运行图声明不一致')
    for sid, definition in definitions.items():
        if type(state['facts'][sid]['value']) is not {'boolean':bool, 'integer':int, 'string':str}[definition['value_type']]:
            raise ValueError('权威事实类型不匹配：' + sid)
        if not definition['mutable'] and state['facts'][sid]['value'] != definition['initial']:
            raise ValueError('不可变世界事实已被改写：' + sid)
        if isinstance(state['facts'][sid]['value'], str) and len(state['facts'][sid]['value']) > 500:
            raise ValueError('事实值过长：' + sid)
    return state


def evaluate(expression, view, story_state):
    """Evaluate only declared operators, returning an internal dependency snapshot."""
    state = validate_state(view, story_state)
    book = view['book']
    allowed = dict(facts={row['id'] for row in book['fact_definitions']},
                   milestones={row['id'] for row in book['milestones']},
                   events=set(book['event_ids']), items=set(book['item_ids']))
    if expression is None:
        return dict(value=True, read_set={})
    g._preflight(expression)
    condition = g.Condition.model_validate(expression).model_dump(mode='json')
    reads = {}

    def visit(row):
        op = row['op']
        if op in {'all','any','not'}:
            values = [visit(child) for child in row['children']]
            return all(values) if op == 'all' else any(values) if op == 'any' else not values[0]
        kind = {'fact_equals':'facts', 'has_item':'items', 'event_occurred':'events', 'milestone_state':'milestones'}[op]
        ref = row['ref']
        if ref not in allowed[kind]:
            raise ValueError('条件引用不存在：' + ref)
        actual = state[kind][ref]
        reads[kind + ':' + ref] = deepcopy(actual)
        expected = row['value'] if op == 'fact_equals' else row['state'] if op == 'milestone_state' else True
        if type(expected) is not type(actual['value']):
            raise ValueError('条件比较类型不一致：' + ref)
        return actual['value'] == expected

    return dict(value=visit(condition), read_set=reads)

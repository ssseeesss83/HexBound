"""Author graph v2: bounded declarative conditions and sparse continuation exits.

Pure authoring contracts. Parsing/migration never opens rooms, rolls dice or
publishes text. Runtime patches and frontier activation belong to P06.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import json
from typing import Literal

from pydantic import Field, model_validator

from .schemas import Card, Identifier, NodeAction, SceneObject, StrictModel, parse_card
from .rules_identity import RULESET_ID, LEGACY_PACKAGE

MAX_BYTES = 1_000_000
MAX_CONDITION_DEPTH = 12
MAX_CONDITION_NODES = 128
Value = str | int | bool


class Condition(StrictModel):
    op: Literal['all', 'any', 'not', 'fact_equals', 'has_item', 'event_occurred', 'milestone_state']
    children: list['Condition'] = Field(default_factory=list, max_length=32)
    ref: Identifier | None = None
    value: Value | None = None
    state: Literal['pending', 'achieved', 'failed', 'bypassed'] | None = None

    @model_validator(mode='after')
    def shape(self):
        if self.op in {'all', 'any', 'not'}:
            if not self.children or (self.op == 'not' and len(self.children) != 1):
                raise ValueError('逻辑条件需要子条件；not 只能有一个子条件')
            if self.ref is not None or self.value is not None or self.state is not None:
                raise ValueError('逻辑条件不能同时携带引用或值')
        else:
            if self.children or self.ref is None:
                raise ValueError('叶条件必须引用声明的 ID 且不能带子条件')
            if (self.op == 'fact_equals') != (self.value is not None):
                raise ValueError('只有 fact_equals 必须携带 value')
            if (self.op == 'milestone_state') != (self.state is not None):
                raise ValueError('只有 milestone_state 必须携带 state')
        if isinstance(self.value, str) and len(self.value) > 500:
            raise ValueError('事实值过长')
        return self


class FactDefinition(StrictModel):
    id: Identifier
    kind: Literal['premise', 'state', 'knowledge', 'secret']
    value_type: Literal['boolean', 'integer', 'string']
    mutable: bool
    visibility: Literal['public', 'scoped', 'dm_secret']
    initial: Value
    description: str = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def typed(self):
        if self.kind == 'premise' and self.mutable:
            raise ValueError('世界前提不能声明为可变事实')
        if type(self.initial) is not {'boolean': bool, 'integer': int, 'string': str}[self.value_type]:
            raise ValueError('事实初始值与声明类型不一致')
        if isinstance(self.initial, str) and len(self.initial) > 500:
            raise ValueError('事实值过长')
        return self


class NamedDefinition(StrictModel):
    id: Identifier
    description: str = Field(min_length=1, max_length=1000)


class Milestone(NamedDefinition):
    initial_state: Literal['pending', 'achieved', 'failed', 'bypassed'] = 'pending'


class Continuation(StrictModel):
    summary: str = Field(min_length=1, max_length=2000)
    confirmed_fact_ids: list[Identifier] = Field(max_length=100)
    unresolved_threads: list[str] = Field(min_length=1, max_length=20)
    npc_goal_ids: list[Identifier] = Field(max_length=40)
    allowed_monster_ids: list[Identifier] = Field(max_length=30)
    candidate_milestone_ids: list[Identifier] = Field(max_length=40)
    constraints: list[str] = Field(min_length=1, max_length=20)
    fallback_scene_id: Identifier | None = None

    @model_validator(mode='after')
    def bounded_text(self):
        for values in (self.unresolved_threads, self.constraints):
            if any(not value.strip() or len(value) > 1000 for value in values):
                raise ValueError('续写线索与约束不能为空或过长')
        for values in (self.confirmed_fact_ids, self.npc_goal_ids, self.allowed_monster_ids, self.candidate_milestone_ids):
            if len(set(values)) != len(values):
                raise ValueError('续写引用不能重复')
        return self


class StoryNode(StrictModel):
    id: Identifier
    kind: Literal['key', 'scene', 'frontier', 'ending']
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(default='', max_length=5000)
    objective: str = Field(default='', max_length=300)
    main_path: bool = False
    monster_ids: list[Identifier] = Field(default_factory=list, max_length=6)
    objects: list[SceneObject] = Field(default_factory=list, max_length=20)
    advancement_condition: Condition | None = None
    failure_consequences: str = Field(default='', max_length=2000)
    ending_condition: Condition | None = None
    continuation: Continuation | None = None
    # Source provenance for migrated routes, never executed by this module.
    legacy_actions: list[NodeAction] = Field(default_factory=list, max_length=12)

    @model_validator(mode='after')
    def roles(self):
        if len(set(self.monster_ids)) != len(self.monster_ids) or len({o.id for o in self.objects}) != len(self.objects):
            raise ValueError('节点的怪兽或对象引用不能重复')
        if len({a.id for a in self.legacy_actions}) != len(self.legacy_actions):
            raise ValueError('节点内旧行动 ID 不能重复')
        if self.kind != 'frontier' and not self.text:
            raise ValueError('可玩节点与结局需要正文')
        if (self.kind == 'frontier') != (self.continuation is not None):
            raise ValueError('只有 frontier 必须携带完整续写契约')
        if self.kind == 'frontier' and self.objects:
            raise ValueError('续写出口不能含环境对象')
        if self.kind in {'frontier', 'ending'} and (self.monster_ids or self.legacy_actions):
            raise ValueError('末端节点不能含遭遇或旧行动')
        if self.kind == 'key' and (self.advancement_condition is None or not self.objective or not self.failure_consequences):
            raise ValueError('关键节点需要冲突目标、推进条件与失败后果')
        if self.kind != 'key' and (self.advancement_condition is not None or self.failure_consequences):
            raise ValueError('推进条件与失败后果仅用于关键节点')
        if self.kind != 'ending' and self.ending_condition is not None:
            raise ValueError('结局条件只能用于结局节点')
        return self


class StoryEdge(StrictModel):
    id: Identifier
    source: Identifier = Field(alias='from')
    to: Identifier
    condition: Condition | None = None
    outcome: str = Field(default='', max_length=2000)
    visibility: Literal['public', 'known', 'secret'] = 'public'
    priority: int = Field(default=0, ge=-100, le=100)
    main_path: bool = False
    legacy_action_id: Identifier | None = None
    legacy_result: Literal['direct', 'success', 'failure'] | None = None

    @model_validator(mode='after')
    def bridge(self):
        if (self.legacy_action_id is None) != (self.legacy_result is None):
            raise ValueError('旧行动来源与结果必须一起提供')
        return self


class StoryBook(Card):
    schema_version: Literal[2]
    ruleset_id: Literal[RULESET_ID]
    rules_package_version: str = Field(min_length=1, max_length=100)
    starting_level: int = Field(default=3, ge=1, le=20)
    outline: str = Field(min_length=1, max_length=10000)
    entry_node_id: Identifier
    fact_definitions: list[FactDefinition] = Field(default_factory=list, max_length=200)
    milestones: list[Milestone] = Field(default_factory=list, max_length=100)
    npc_goals: list[NamedDefinition] = Field(default_factory=list, max_length=100)
    item_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    event_ids: list[Identifier] = Field(default_factory=list, max_length=200)
    ending_constraints: list[str] = Field(default_factory=list, max_length=30)
    skill_ids: list[Identifier] = Field(default_factory=list, max_length=40)
    monster_ids: list[Identifier] = Field(default_factory=list, max_length=30)
    nodes: list[StoryNode] = Field(min_length=2, max_length=200)
    # A valid v1 book may have 50 * 12 * 2 check exits.
    edges: list[StoryEdge] = Field(max_length=1200)


def _preflight(data):
    """Bound untrusted containers before recursive model construction/encoding."""
    pending = [(data, 0)]
    containers = 0
    while pending:
        value, depth = pending.pop()
        if depth > 40:
            raise ValueError('剧情结构嵌套过深')
        if isinstance(value, (dict, list)):
            containers += 1
            if containers > 20000:
                raise ValueError('剧情结构过大')
            pending.extend((v, depth+1) for v in (value.values() if isinstance(value, dict) else value))
    try:
        size = len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    except (TypeError, ValueError) as exc:
        raise ValueError('剧情必须是有效 JSON 数据') from exc
    if size > MAX_BYTES:
        raise ValueError('剧情超过大小限制')
    todo = [(data, 0, None)]
    while todo:
        value, depth, root = todo.pop()
        if isinstance(value, dict):
            if 'op' in value:
                if root is None:
                    root = [0]
                root[0] += 1
                depth += 1
                if depth > MAX_CONDITION_DEPTH or root[0] > MAX_CONDITION_NODES:
                    raise ValueError('条件树深度或大小超过限制')
            todo.extend((v, depth, root) for v in value.values())
        elif isinstance(value, list):
            todo.extend((v, depth, root) for v in value)


def graph_issues(book):
    """No expression evaluation: only types, dependencies and structural exits."""
    issues = []
    def unique(rows, name, key=None):
        ids = [row[key] for row in rows] if key else rows
        if len(set(ids)) != len(ids):
            issues.append(f'{name} ID 重复')
        return set(ids)
    nodes = {n['id']: n for n in book['nodes']}
    unique(book['nodes'], '节点', 'id')
    unique(book['edges'], '边', 'id')
    tables = {'fact_equals': {r['id']: r for r in book['fact_definitions']},
              'has_item': unique(book['item_ids'], '物品'),
              'event_occurred': unique(book['event_ids'], '事件'),
              'milestone_state': unique(book['milestones'], '里程碑', 'id')}
    unique(book['fact_definitions'], '事实', 'id')
    goals = unique(book['npc_goals'], 'NPC目标', 'id')
    monsters = unique(book['monster_ids'], '怪兽')
    skills = unique(book['skill_ids'], '技能')
    if book['entry_node_id'] not in nodes or nodes[book['entry_node_id']]['kind'] in {'frontier', 'ending'}:
        issues.append('入口必须是存在的可玩节点')
    def condition(expr, location):
        pending = [expr] if expr else []
        while pending:
            row = pending.pop()
            if row['op'] in {'all', 'any', 'not'}:
                pending.extend(row['children'])
                continue
            if row['ref'] not in tables[row['op']]:
                issues.append(f'{location} 条件引用不存在：{row["ref"]}')
            elif row['op'] == 'fact_equals':
                fact = tables['fact_equals'][row['ref']]
                if type(row['value']) is not {'boolean': bool, 'integer': int, 'string': str}[fact['value_type']]:
                    issues.append(f'{location} 条件值类型不匹配：{row["ref"]}')
    forward = {k: [] for k in nodes}
    reverse = {k: [] for k in nodes}
    legacy_edges = {}
    for edge in book['edges']:
        condition(edge['condition'], edge['id'])
        if edge['from'] not in nodes or edge['to'] not in nodes:
            issues.append(f'边 {edge["id"]} 引用不存在的节点')
            continue
        if nodes[edge['from']]['kind'] in {'frontier', 'ending'}:
            issues.append(f'末端节点 {edge["from"]} 不能有后继')
        forward[edge['from']].append(edge['to'])
        reverse[edge['to']].append(edge['from'])
        if edge['legacy_action_id'] is not None:
            key = (edge['from'], edge['legacy_action_id'], edge['legacy_result'])
            if key in legacy_edges:
                issues.append(f'边 {edge["id"]} 重复旧行动出口')
            legacy_edges[key] = edge
    for node in book['nodes']:
        if set(node['monster_ids']) - monsters:
            issues.append(f'节点 {node["id"]} 怪兽不在剧本依赖中')
        condition(node['advancement_condition'], node['id'])
        condition(node['ending_condition'], node['id'])
        for action in node['legacy_actions']:
            if action['skill_id'] and action['skill_id'] not in skills:
                issues.append(f'节点 {node["id"]} 旧技能不在依赖中')
            fields = [('direct', 'next_node_id')] if not action['skill_id'] else [('success', 'success_node_id'), ('failure', 'failure_node_id')]
            for result, field in fields:
                edge = legacy_edges.pop((node['id'], action['id'], result), None)
                if edge is None or edge['to'] != action[field] or edge['condition'] is not None:
                    issues.append(f'节点 {node["id"]} 旧行动 {action["id"]} 出口不完整或被改写')
        contract = node['continuation']
        if contract:
            for field, allowed in [('confirmed_fact_ids', tables['fact_equals']), ('npc_goal_ids', goals),
                                   ('allowed_monster_ids', monsters), ('candidate_milestone_ids', tables['milestone_state'])]:
                if set(contract[field]) - set(allowed):
                    issues.append(f'末端 {node["id"]} 的 {field} 有悬空引用')
            fallback = contract['fallback_scene_id']
            if fallback and (fallback not in nodes or nodes[fallback]['kind'] not in {'key', 'scene'}):
                issues.append(f'末端 {node["id"]} 的 fallback 必须是可玩场景')
    if legacy_edges:
        issues.append('边引用不存在的旧行动或多余结果')
    def reachable(starts, graph):
        seen, todo = set(), deque(starts)
        while todo:
            current = todo.popleft()
            if current in seen or current not in graph:
                continue
            seen.add(current)
            todo.extend(graph[current])
        return seen
    reached = reachable([book['entry_node_id']], forward)
    exits = {k for k, n in nodes.items() if n['kind'] in {'ending', 'frontier'}}
    can_exit = reachable(exits, reverse)
    for nid in sorted(nodes):
        if nid not in reached:
            issues.append(f'节点 {nid} 无法从入口到达')
        if nid not in can_exit:
            issues.append(f'节点 {nid} 无法到达结局或续写出口')
    return list(dict.fromkeys(issues))


def parse_draft(data):
    _preflight(data)
    return StoryBook.model_validate(data).model_dump(mode='json', by_alias=True)


def parse_book(data):
    book = parse_draft(data)
    issues = graph_issues(book)
    if issues:
        raise ValueError('；'.join(issues))
    return book


def migrate_legacy(data, *, rules_package_version=LEGACY_PACKAGE):
    """Return a separate author draft, preserving every old route and payload."""
    _preflight(data)
    if not isinstance(data, dict):
        raise ValueError('剧情必须是 JSON 对象')
    if data.get('schema_version') == 2:
        return parse_book(deepcopy(data))
    old = parse_card('scenario', deepcopy(data))
    edges, nodes = [], []
    for index, row in enumerate(old['nodes']):
        node = {key: deepcopy(value) for key, value in row.items() if key not in {'ending', 'actions'}}
        node.update(kind='ending' if row['ending'] else 'scene', legacy_actions=deepcopy(row['actions']))
        nodes.append(node)
        for action_index, action in enumerate(row['actions']):
            targets = [('direct', action['next_node_id'])] if not action['skill_id'] else [
                ('success', action['success_node_id']), ('failure', action['failure_node_id'])]
            for result, target in targets:
                edges.append({'id': f'legacy-{index}-{action_index}-{result}', 'from': row['id'], 'to': target,
                              'outcome': action['label'], 'legacy_action_id': action['id'], 'legacy_result': result})
    book = {key: deepcopy(value) for key, value in old.items() if key != 'nodes'}
    book.update(schema_version=2, ruleset_id=RULESET_ID, rules_package_version=rules_package_version,
                outline=old['description'] or old['name'], nodes=nodes, edges=edges)
    return parse_book(book)


def navigation_rows(book):
    """Finite tree navigation of a graph; merges/cycles become reference rows."""
    nodes = {n['id']: n for n in book['nodes']}
    edges = {nid: [] for nid in nodes}
    for edge in book['edges']:
        edges[edge['from']].append(edge)
    rows, seen = [], set()
    pending = [(book['entry_node_id'], 0, (), None)]
    while pending:
        nid, depth, ancestors, via = pending.pop()
        reference = 'cycle' if nid in ancestors else 'merge' if nid in seen else None
        rows.append({'node_id': nid, 'edge_id': via, 'depth': depth, 'reference': reference,
                     'main_path': nodes[nid]['main_path']})
        if reference:
            continue
        seen.add(nid)
        ordered = sorted(edges[nid], key=lambda e: (not e['main_path'], -e['priority'], e['id']))
        pending.extend((e['to'], depth+1, (*ancestors, nid), e['id']) for e in reversed(ordered))
    return rows

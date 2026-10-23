"""Strict, versionable authoring contracts; no executable code is accepted."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]
Dice = Annotated[str, Field(pattern=r"^(?:[1-9]|1[0-9]|20)d(?:4|6|8|10|12|20)$")]
Kind = Literal["skill", "monster", "scenario"]
Ability = Literal["str", "dex", "con", "int", "wis", "cha"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class Card(StrictModel):
    id: Identifier
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=3000)
    tags: list[Annotated[str, Field(min_length=1, max_length=30)]] = Field(default_factory=list, max_length=12)


class SkillCard(Card):
    effect: Literal["attack", "heal", "check", "defend"]
    ability: Ability = "str"
    dice: Dice = "1d8"
    bonus: int = Field(default=0, ge=-10, le=20)
    dc: int = Field(default=12, ge=5, le=30)
    uses: int | None = Field(default=None, ge=1, le=20)
    target: Literal["self", "ally", "enemy", "scene"]

    @model_validator(mode="after")
    def compatible_target(self):
        allowed = {"attack": {"enemy"}, "heal": {"self", "ally"}, "check": {"scene"}, "defend": {"self"}}
        if self.target not in allowed[self.effect]:
            raise ValueError(f"{self.effect} 的目标必须为 {', '.join(sorted(allowed[self.effect]))}")
        return self


class MonsterCard(Card):
    hp: int = Field(ge=1, le=500)
    ac: int = Field(ge=5, le=30)
    attack_bonus: int = Field(default=2, ge=-5, le=20)
    damage_dice: Dice = "1d4"
    damage_bonus: int = Field(default=0, ge=-5, le=20)
    initiative_bonus: int = Field(default=0, ge=-5, le=20)


class NodeAction(StrictModel):
    id: Identifier
    label: str = Field(min_length=1, max_length=120)
    skill_id: Identifier | None = None
    next_node_id: Identifier | None = None
    success_node_id: Identifier | None = None
    failure_node_id: Identifier | None = None

    @model_validator(mode="after")
    def transitions(self):
        if self.skill_id:
            if not self.success_node_id or not self.failure_node_id or self.next_node_id:
                raise ValueError("检定行动必须指定成功/失败节点，不能同时指定直接下一节点")
        elif not self.next_node_id or self.success_node_id or self.failure_node_id:
            raise ValueError("直接行动必须且只能指定 next_node_id")
        return self


class ScenarioNode(StrictModel):
    id: Identifier
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=5000)
    objective: str = Field(default="", max_length=300)
    actions: list[NodeAction] = Field(default_factory=list, max_length=12)
    monster_ids: list[Identifier] = Field(default_factory=list, max_length=6)
    ending: bool = False

    @model_validator(mode="after")
    def topology(self):
        if len({a.id for a in self.actions}) != len(self.actions):
            raise ValueError("节点内行动 ID 不能重复")
        if len(set(self.monster_ids)) != len(self.monster_ids):
            raise ValueError("节点内怪兽 ID 不能重复")
        if self.ending and (self.actions or self.monster_ids):
            raise ValueError("结局节点不能包含行动或怪兽")
        if not self.ending and not self.actions:
            raise ValueError("非结局节点必须有至少一个行动")
        return self


class ScenarioBook(Card):
    entry_node_id: Identifier
    nodes: list[ScenarioNode] = Field(min_length=2, max_length=50)
    skill_ids: list[Identifier] = Field(default_factory=list, max_length=40)
    monster_ids: list[Identifier] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({n.id for n in self.nodes}) != len(self.nodes):
            raise ValueError("剧情节点 ID 不能重复")
        if len(set(self.skill_ids)) != len(self.skill_ids) or len(set(self.monster_ids)) != len(self.monster_ids):
            raise ValueError("技能/怪兽引用不能重复")
        return self


MODELS = {"skill": SkillCard, "monster": MonsterCard, "scenario": ScenarioBook}


def parse_card(kind: str, data: dict) -> dict:
    if kind not in MODELS:
        raise ValueError("未知内容类型")
    return MODELS[kind].model_validate(data).model_dump(mode="json")


def references(kind: str, data: dict) -> list[tuple[str, str]]:
    if kind != "scenario":
        return []
    return [(ref, "skill") for ref in data["skill_ids"]] + [(ref, "monster") for ref in data["monster_ids"]]


def graph_issues(data: dict) -> list[str]:
    """Graph reachability and termination are checked independently of references."""
    issues = []
    nodes = {node["id"]: node for node in data["nodes"]}
    if data["entry_node_id"] not in nodes:
        issues.append("入口节点不存在")
    edges = {key: set() for key in nodes}
    ends = {key for key, node in nodes.items() if node["ending"]}
    if not ends:
        issues.append("剧情至少需要一个结局")
    for key, node in nodes.items():
        for monster_id in node["monster_ids"]:
            if monster_id not in data["monster_ids"]:
                issues.append(f"节点 {key} 的怪兽 {monster_id} 未列入剧情依赖")
        for action in node["actions"]:
            if action["skill_id"] and action["skill_id"] not in data["skill_ids"]:
                issues.append(f"节点 {key} 的技能 {action['skill_id']} 未列入剧情依赖")
            for field in ("next_node_id", "success_node_id", "failure_node_id"):
                target = action[field]
                if target:
                    if target not in nodes:
                        issues.append(f"节点 {key} 引用不存在的目标 {target}")
                    else:
                        edges[key].add(target)
    def visit(start):
        seen, todo = set(), [start]
        while todo:
            current = todo.pop()
            if current in seen or current not in nodes:
                continue
            seen.add(current)
            todo.extend(edges[current] - seen)
        return seen
    reachable = visit(data["entry_node_id"])
    for key in nodes.keys() - reachable:
        issues.append(f"节点 {key} 无法从入口到达")
    for key in nodes:
        if not visit(key).intersection(ends):
            issues.append(f"节点 {key} 无法到达任何结局")
    return issues

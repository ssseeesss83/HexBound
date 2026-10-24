"""Player declarations contain no dice, difficulty, cost, or promised outcome."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ActionIntent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    actor_id: str
    scene_instance_id: str
    membership_epoch: int = Field(ge=1)
    source: Literal['free_text', 'skill']
    text: str = Field(min_length=1, max_length=1500)
    preferred_skill_id: str | None = None


def declare(state, actor, text, skill_id=None):
    from .director import SKILL_ABILITIES
    if skill_id is not None and skill_id not in SKILL_ABILITIES:
        raise ValueError('请选择18项标准技能之一')
    return ActionIntent(
        actor_id=actor,
        scene_instance_id=state.get('_scene_execution_view', 'scene-main'),
        membership_epoch=state.get('member_contexts', {}).get(actor, {}).get('epoch', 1),
        source='skill' if skill_id else 'free_text', text=text, preferred_skill_id=skill_id,
    ).model_dump()

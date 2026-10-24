"""Player declarations contain no dice, difficulty, cost, or promised outcome."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .action_plans import Options


class ActionIntent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    actor_id: str
    scene_instance_id: str
    membership_epoch: int = Field(ge=1)
    source: Literal['free_text', 'skill', 'capability']
    text: str = Field(min_length=1, max_length=1500)
    preferred_skill_id: str | None = None
    capability_id: str | None = None
    target_id: str | None = None
    options: Options | None = None

    @model_validator(mode='after')
    def coherent(self):
        if self.source == 'capability':
            if not self.capability_id or self.preferred_skill_id or self.options is None:
                raise ValueError('所选能力声明必须有能力身份与合法选项')
        elif self.capability_id or self.target_id or (self.options and any([
                self.options.slot_level is not None, self.options.slot_source is not None,
                self.options.resource_amount is not None, self.options.target_ids,self.options.skill_id is not None])):
            raise ValueError('文字或技能意向不能混入能力参数')
        if (self.source == 'skill') != bool(self.preferred_skill_id):
            raise ValueError('技能来源与方法声明不一致')
        return self


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


def declare_selected(plan):
    """Input is the server-prepared plan, never a client-provided plan object."""
    return ActionIntent(actor_id=plan['actor_id'], scene_instance_id=plan['scene_instance_id'],
                        membership_epoch=plan['membership_epoch'], source='capability',
                        text=plan['label'], capability_id=plan['action_id'], target_id=plan['target_id'],
                        options=plan['options']).model_dump()

"""Safe checkpoint party split; callers transact membership and receipts."""
from copy import deepcopy
from dataclasses import dataclass
from . import world_state as world


@dataclass(frozen=True)
class SplitPlan:
    source: str
    target: str
    channel: str
    members: tuple
    place_id: str
    clock: int
    action_revision: int
    place_revision: int
    entity_versions: tuple
    member_epochs: tuple


def prepare_split(room, source, target, channel, members):
    if room.get('status') not in {'playing','paused'}:
        raise world.WorldConflict('请在活动冒险的安全检查点分队')
    scene = world._scene(room, source)
    occupants = world._members(room, source)
    if not isinstance(members, (tuple,list)) or not members or len(set(members)) != len(members) or not set(members) < set(occupants):
        raise world.WorldConflict('请选择部分本场成员，双方至少保留一人')
    if not isinstance(target,str) or not 1 <= len(target) <= 100 or target in room['scene_instances']:
        raise world.WorldConflict('新场景 ID 无效或已存在')
    if not isinstance(channel,str) or not 1 <= len(channel) <= 100 or channel in room['text_scope']['channels']:
        raise world.WorldConflict('新文字频道 ID 无效或已存在')
    local = scene['local']
    if local.get('completed') or (local.get('combat') or {}).get('active') or any(local.get(key) for key in ('pending_transition','pending_choice','reaction_windows')):
        raise world.WorldConflict('请先完成战斗、选择或待结算步骤')
    place = world._place(room, scene.get('place_id'))
    if place['active_encounter_id']:
        raise world.WorldConflict('地点仍有活动遭遇')
    if scene.get('channel_id') not in room['text_scope']['channels'] or any(room['text_scope']['members'][actor]['channel'] != scene['channel_id'] for actor in occupants):
        raise world.WorldConflict('成员场景与文字频道不一致')
    return SplitPlan(source, target, channel, tuple(sorted(members)), scene['place_id'],
        world._logical_seconds(scene), local.get('action_revision',0),
        place['revision'], world._entity_versions(room,place), world._epochs(room,(source,)))


def commit_split(room, plan):
    if not isinstance(plan,SplitPlan) or prepare_split(room, plan.source, plan.target, plan.channel, plan.members) != plan:
        raise world.WorldConflict('分队计划已过期')
    source = room['scene_instances'][plan.source]
    target = deepcopy(source)
    target.update(id=plan.target, channel_id=plan.channel, membership_revision=1)
    target['local']['combat'] = None
    # Scope-specific memories are not copied into a newly authorized audience.
    target['local']['director'] = {'memory':[], 'proposals':{}}
    room['scene_instances'][plan.target] = target
    room['text_scope']['channels'][plan.channel] = {'id':plan.channel,'name':'分队交流'}
    for actor in plan.members:
        context = room['member_contexts'][actor]
        context.update(scene_instance_id=plan.target, epoch=context['epoch']+1)
        scope = room['text_scope']['members'][actor]
        scope.update(channel=plan.channel, epoch=scope['epoch']+1, seq=0)
    for scene in (source,target):
        local = scene['local']
        local['action_revision'] = local.get('action_revision',0)+1
        local['dm_pending'] = None
        local.setdefault('director',{})['proposals'] = {}
    source['membership_revision'] = source.get('membership_revision',0)+1
    return {'operation':'scene_split','source':plan.source,'target':plan.target,'members':list(plan.members)}

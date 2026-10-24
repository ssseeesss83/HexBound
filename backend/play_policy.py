"""Product policy is separate from frozen legacy rule/content selectors."""
PLAY_MODE = 'script_ai_dm'
POLICY_VERSION = 1
DISABLED_COMMANDS = frozenset({'set_interaction', 'scene_edit'})


def validate_command(state, command):
    if command in DISABLED_COMMANDS:
        raise ValueError('房间固定使用剧本 + AI DM；请在工坊编辑独立剧本草稿')
    if (command == 'start' and state.get('mode') == 'free'
            and not state.get('scenes') and not state.get('campaign_package')):
        raise ValueError('这个旧房间没有已冻结的剧本，请先在工坊准备剧本并创建新房间')


def confirmed_events(rows):
    """Player conversation is not an authoritative world-state event."""
    # Historical DM prose has no pending marker; it is never a mechanical fact.
    # Confirmed dialogue continuity remains in the separately scoped DM memory.
    return [row for row in rows if row.get('kind') not in {'chat', 'intent', 'dm', 'narrative'}
            and not row.get('adjudication_pending')]

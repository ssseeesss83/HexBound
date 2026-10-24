"""One scoped menu for existing scenario and registered prototype actions."""
from . import abilities, campaign, content


def available(state, actor):
    base = (campaign if state.get('campaign') else content).available_actions(state, actor)
    if any(member['character'].get('class_id') for member in state['members']):
        base = [row for row in base if row['id'] != 'rest']
    return base + [row for row in abilities.available_actions(state, actor)
                   if row['id'] not in {item['id'] for item in base}]

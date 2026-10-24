"""One scoped menu for existing scenario and registered prototype actions."""
from . import abilities, campaign, content, attempts


def available(state, actor):
    base = (campaign if state.get('campaign') else content).available_actions(state, actor)
    base = [row for row in base if attempts.available(state, actor, row['id'])]
    if any(member['character'].get('class_id') for member in state['members']):
        base = [row for row in base if row['id'] != 'rest']
    from .story_challenges import menu
    from .story_transitions import menu as routes
    return base + [row for row in abilities.available_actions(state, actor)
                   if row['id'] not in {item['id'] for item in base}] + menu(state,actor) + routes(state,actor)

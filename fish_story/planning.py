"""Read-only capacity planning without returning future story content or rules."""
from __future__ import annotations

import math

from .service import PACKAGE, read_json


def _scene_capacity(player):
    """Count one visible context and one choice set, never all variants at once."""
    contexts = ([player['context']] if 'context' in player
                else list(player.get('context_variants', {}).values()))
    context = max((text for text in contexts if isinstance(text, str)),
                  key=lambda text: len(text.encode('utf-8')), default='')
    sets = []
    choice_fields = ({'choices': player['choices']} if 'choices' in player else
                     {'choices_variants': player['choices_variants']} if 'choices_variants' in player else player)
    for key, value in choice_fields.items():
        if not key.startswith('choices'):
            continue
        if isinstance(value, list):
            sets.append(value)
        elif isinstance(value, dict):
            sets.extend(item for item in value.values() if isinstance(item, list))
    rendered = []
    for choices in sets:
        rendered.append('\n'.join(str(index) + '. ' + choice.get('text', '')
                                  for index, choice in enumerate(choices, 1)
                                  if isinstance(choice, dict) and isinstance(choice.get('text', ''), str)))
    options = max(rendered, key=lambda text: len(text.encode('utf-8')), default='')
    return bool(options), len((context + '\n' + options).encode('utf-8'))


def story_plan(service, story_id, chapter=1, core_characters=0, max_output_tokens=256, play_style='self_aware'):
    """Estimate route scenarios and finite capacity, without predicting a bill.

    The native runner visits a node at most once. Different routes skip nodes.
    Only counts leave this helper: no node IDs, text, rules or ending details.
    Token scenarios include growing history and assume no cache discount.
    """
    if type(chapter) is not int or chapter < 1:
        raise ValueError('INVALID_GAME_CONFIGURATION')
    if play_style not in ('self_aware', 'immersive'):
        raise ValueError('INVALID_PLAY_STYLE')
    if (type(core_characters) is not int or not 0 <= core_characters <= 20_000
            or type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 100_000):
        raise ValueError('INVALID_CONFIG')
    story = next((s for s in service.stories() if s['id'] == story_id), None)
    if story is None:
        raise ValueError('NO_STORY')
    if chapter not in [c['chapter_number'] for c in story['chapters']]:
        raise ValueError('NO_CHAPTER')
    directory = PACKAGE / 'demo' if story_id == 'demo' else service.directory / 'stories' / story_id
    decisions = nodes = chapters = visible_bytes = recap_calls = 0
    for path in sorted(directory.glob('ch*.json')):
        doc = read_json(path)
        if doc['chapter']['chapter_number'] < chapter:
            continue
        chapters += 1
        actors = doc['chapter'].get('protagonist', [])
        actors = actors if isinstance(actors, list) else [actors] if actors else []
        roles = set(actors)
        if play_style == 'immersive':
            from .styles import _visible_label
            for node in doc['nodes']:
                player = node.get('player_facing', {})
                contexts = [player['context']] if 'context' in player else player.get('context_variants', {}).values()
                roles.update(actor for text in contexts if (actor := _visible_label(text, actors)))
        recap_calls += max(1, len(roles)) if play_style == 'immersive' else 1
        for node in doc['nodes']:
            nodes += 1
            has_choices, size = _scene_capacity(node.get('player_facing', {}))
            decisions += int(has_choices)
            visible_bytes += size + 256
        actor = doc['chapter'].get('protagonist', [])
        tracks = len(actor) if isinstance(actor, list) else 1
        ending_sizes = sorted((len((str(ending.get('title', '')) + '\n' +
                                  str(ending.get('narrative', ''))).encode('utf-8'))
                               for ending in doc.get('endings', {}).values()
                               if isinstance(ending, dict)), reverse=True)
        visible_bytes += sum(ending_sizes[:max(1, tracks)])
    choice_calls = max(1, decisions)
    calls = choice_calls + recap_calls
    recommended_calls = max(10, math.ceil(calls * 1.15))
    # Approximate UTF-8/3 tokens. Only one context/option variant contributes
    # to each turn. Four bytes per identity character is a UTF-8 allowance.
    core_bytes = core_characters * 4
    # Each completed chapter adds the same model's recap task and authored
    # response to history. Both choices and writing requests use the same
    # configured output ceiling and durable budget.
    per_turn_growth = (visible_bytes + recap_calls * 900) / (3 * calls) + max_output_tokens + 64
    # 157 is the existing full-campaign scripted reference, not a guaranteed
    # route length. Other stories use a clearly illustrative 75% scenario.
    reference_choices = min(157, choice_calls) if story.get('is_detroit') else max(1, math.ceil(choice_calls * .75))
    reference_calls = reference_choices + recap_calls

    def scenario(count):
        return math.ceil(count * (core_bytes / 3 + 1200)
                         + per_turn_growth * count * (count + 1) / 2)

    rough_input = scenario(calls)
    # The ledger reserves the final request by bytes. Include it once along
    # with estimated accumulated usage and 25% headroom, rather than multiplying
    # the full final byte reservation by every earlier request.
    final_reservation = core_bytes + visible_bytes + calls * (max_output_tokens * 4 + 512) + 4096
    suggested_tokens = math.ceil((rough_input + calls * max_output_tokens + final_reservation) * 1.25 / 1000) * 1000
    return {
        'story_id': story_id, 'starting_chapter': chapter,
        'chapter_count': chapters, 'decision_node_capacity': decisions,
        'play_style': play_style, 'recap_call_capacity': recap_calls,
        'model_call_capacity': decisions + recap_calls,
        'suggested_max_calls': recommended_calls,
        'suggested_token_budget': suggested_tokens,
        'rough_input_tokens': rough_input,
        'reference_route_calls': reference_choices,
        'reference_route_model_calls': reference_calls,
        'reference_route_input_tokens': scenario(reference_calls),
        'reference_route_output_tokens': reference_calls * max_output_tokens,
        'maximum_output_tokens': calls * max_output_tokens,
        'final_request_reservation_tokens': final_reservation,
        'basis': 'One applicable context/choice variant per node; chapter recap requests; triangular history growth.',
        'limitations': ('Planning scenarios include growing history without cache discounts. They are not '
                        'route predictions, playthrough guarantees or provider bills. Tokenization, '
                        'public-response lengths, retries and save branches affect actual usage.'),
        'makes_model_requests': False,
    }

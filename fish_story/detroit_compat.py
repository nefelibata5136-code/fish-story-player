"""Reviewed, hash-bound compatibility repairs for the pinned upstream story pack.

Only new imported copies/session snapshots are changed. Authored narrative and
choices stay intact. Continuity guards skip later Kara scenes after an actual
earlier death, with explicit software skip receipts rather than invented plot.
Existing session snapshots stay untouched.
The hashes are canonical JSON digests, independent of archive serialization.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

COMPATIBILITY_VERSION = 'detroit-compatibility/2'
PINNED_CHAPTER_REPAIRS = {
    # Pinned upstream commit 3c4ae839169df24d8934642037f27d2eb2bca9a2.
    # Chapter 13 opens on Kara's overnight shelter and her encounter with Ralph;
    # unlike its later scenes, these two nodes have no perspective heading.
    'e9e6849d06acc0711d4d0dc9477ceeb0fb8cae9b571dea11534194de6cf6d193': {
        'n001_morning_exploration': 'Kara',
        'n002_ralph_meal': 'Kara',
    },
}
PINNED_KARA_CONTINUITY_HASHES = {
    'e7d5576b5c9a9ac195b688d1d4ac02091cc4c11a64785feb2273e285897ba2e3': 10,
    'e9e6849d06acc0711d4d0dc9477ceeb0fb8cae9b571dea11534194de6cf6d193': 13,
    'f5d4baafd750eb31eb4531bf0f123af9d98d3dc796e2d0e0b84a983eba56d559': 17,
    '829d290a2928dd913e94d4718bd9bcfcdf680a72ca3e9513fa2e19c870a68127': 21,
    '7a1071d0fb38e4cd681977a360d7dfd94a65a8631ebbbf42ed82c67a90028606': 25,
    'eb51f507650feb3affe1db0b9cf9d799cbc19de9ba6eab2381310b284b8db058': 30,
    '00d6748f6c78fabb208eec9b333fc60fe3aa63d8f1b03beb6557b13ba9afa421': 32,
}


def canonical_story_hash(doc):
    return hashlib.sha256(json.dumps(doc, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def normalize_detroit_chapter(doc):
    """Return (document, audit changes); unknown or modified sources are untouched."""
    input_digest = digest = canonical_story_hash(doc)
    existing_reviewed_labels = False
    if digest not in PINNED_CHAPTER_REPAIRS and digest not in PINNED_KARA_CONTINUITY_HASHES:
        # Version 1 changed only the reviewed perspective fields. A previously
        # installed pack can receive v2 guards in a NEW session, but only after
        # removing exactly those expected labels recreates the pinned digest.
        # Any other user modification leaves the whole document untouched.
        for pinned_digest, reviewed_roles in PINNED_CHAPTER_REPAIRS.items():
            candidate = copy.deepcopy(doc)
            found = set()
            for node in candidate.get('nodes', []):
                if node.get('id') not in reviewed_roles:
                    continue
                actor = reviewed_roles[node['id']]
                if node.get('player_facing', {}).get('perspective') != actor:
                    break
                node['player_facing'].pop('perspective')
                found.add(node['id'])
            if found == set(reviewed_roles) and canonical_story_hash(candidate) == pinned_digest:
                digest, existing_reviewed_labels = pinned_digest, True
                break
    repairs = PINNED_CHAPTER_REPAIRS.get(digest, {})
    continuity_chapter = PINNED_KARA_CONTINUITY_HASHES.get(digest)
    if not repairs and continuity_chapter is None:
        return doc, []
    result = copy.deepcopy(doc)
    changes = []
    for node in result['nodes']:
        actor = repairs.get(node['id'])
        if actor is None:
            continue
        # A hash match already binds this shape. Keep the guard explicit so a
        # future repair table cannot silently overwrite authored attribution.
        if existing_reviewed_labels and node['player_facing'].get('perspective') == actor:
            continue
        if 'perspective' in node['player_facing']:
            raise ValueError('STORY_COMPATIBILITY_CONFLICT')
        node['player_facing']['perspective'] = actor
        changes.append({
            'version': COMPATIBILITY_VERSION,
            'source_chapter_sha256': digest,
            'chapter_number': doc['chapter']['chapter_number'],
            'node_id': node['id'], 'field': 'player_facing.perspective',
            'previous': None, 'value': actor,
            'reason': 'Reviewed controlled character of every source context variant; metadata only.',
        })
    if continuity_chapter is not None:
        changes.extend(_repair_kara_continuity(result, digest, continuity_chapter))
    if continuity_chapter == 13:
        changes.extend(_repair_shared_chapter_terminal(result, digest))
    if continuity_chapter == 30:
        changes.extend(_repair_connor_substitute_hold(result, digest))
    if input_digest != digest:
        for change in changes:
            change['input_chapter_sha256'] = input_digest
            change['upgraded_reviewed_metadata_version'] = 'detroit-metadata/1'
    return result, changes


def _ending_targets(value, endings):
    if isinstance(value, dict):
        for item in value.values():
            yield from _ending_targets(item, endings)
    elif isinstance(value, list):
        for item in value:
            yield from _ending_targets(item, endings)
    elif isinstance(value, str):
        if value in endings and value.startswith('ending_'):
            yield value
        for target in re.findall(r'→\s*(ending_[A-Za-z0-9_]+)', value):
            if target in endings:
                yield target


def _repair_shared_chapter_terminal(doc, digest):
    """Chapter 13 is a shared chase, not three independent finale tracks.

    Its source-authored rule notes say a terminal outcome ends this chapter.
    The native runner's generic multi-protagonist behavior would otherwise keep
    processing a later pursuit after Kara has already died at the crossing.
    """
    flag = '_compat_ch13_finished'
    guarded = 0
    for node in doc['nodes']:
        if node['id'].startswith('compat_'):
            continue
        _guard(node, flag + ' != true')
        guarded += 1
        system = node.setdefault('system', {})
        targets = set(_ending_targets(system, doc['endings']))
        for target in targets:
            system.setdefault('resolution_effects', {}).setdefault(target, {})[flag] = True
    return [{
        'version': COMPATIBILITY_VERSION, 'source_chapter_sha256': digest,
        'chapter_number': 13, 'field': 'shared_chapter_terminal_guard',
        'previous': None, 'value': {'guarded_authored_nodes': guarded},
        'reason': 'An actual shared-chase ending terminates the chapter; do not continue into contradictory later endings.',
    }]


def _replace_result_values(value, replacements):
    if isinstance(value, dict):
        return {key: _replace_result_values(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_result_values(item, replacements) for item in value]
    return replacements.get(value, value) if isinstance(value, str) else value


def _repair_connor_substitute_hold(doc, digest):
    """Keep the source's Connor substitute scene out of Markus's ending table."""
    original = next((node for node in doc['nodes'] if node['id'] == 'n011_markus_hold'), None)
    # Synthetic regression fixtures can bind a hash to a chapter subset. Real
    # pinned source always has this node; no loose title/name matching is used.
    if original is None:
        return []
    player = original['player_facing']
    if 'connor_takes_over' not in player.get('context_variants', {}):
        return []
    substitute = copy.deepcopy(original)
    substitute['id'] = 'compat_connor_substitute_hold'
    substitute['phase'] = 'connor_substitute_hold'
    substitute['player_facing'] = {
        'perspective': 'Connor', 'context': player['context_variants']['connor_takes_over'],
        'choices': copy.deepcopy(player['choices_variants']['standard']),
    }
    system = substitute['system']
    for key in ('context_condition', 'choices_condition'):
        system.pop(key, None)
    choice_ids = {choice['id'] for choice in substitute['player_facing']['choices']}
    system['effects'] = {key: value for key, value in system.get('effects', {}).items() if key in choice_ids}
    system['resolution_rule'] = _replace_result_values(
        {key: value for key, value in system['resolution_rule'].items() if key in choice_ids},
        {'ending_markus_killed': 'ending_connor_deviant_destroyed',
         'ending_markus_escaped': 'compat_connor_retreat_from_hold'})
    system['resolution_effects'] = {
        'bomb_armed': copy.deepcopy(system['resolution_effects']['bomb_armed']),
        'ending_connor_deviant_destroyed': {'connor_died_ch30': True, 'connor_wounded': True},
        'compat_connor_retreat_from_hold': {'markus_bomb_armed': False},
    }
    _guard(substitute, 'ch28_markus_alive == false')
    _guard(original, 'ch28_markus_alive != false')
    doc['nodes'].insert(doc['nodes'].index(original), substitute)
    return [{
        'version': COMPATIBILITY_VERSION, 'source_chapter_sha256': digest,
        'chapter_number': 30, 'field': 'controlled_character_outcome_mapping',
        'previous': 'Markus outcome rules were also used while Connor controlled the scene.',
        'value': {'split_source_node': 'n011_markus_hold', 'substitute': 'Connor',
                  'narrative_and_available_options': 'unchanged source-authored Connor variant',
                  'retreat': 'continue to the existing Connor escape scene',
                  'failed_check': 'existing Connor destroyed ending, prevent a second escape'},
        'reason': 'A substitute character cannot escape or die as the already-dead Markus.',
    }]


def _guard(node, expression):
    condition = node.get('condition')
    previous = condition.get('requires') if isinstance(condition, dict) else condition
    combined = f'({expression}) AND ({previous})' if previous else expression
    node['condition'] = {**(condition if isinstance(condition, dict) else {}), 'requires': combined}


def _repair_kara_continuity(doc, digest, number):
    """The source exports deaths early but otherwise starts later Kara chapters anew.

    Missing flags are deliberately neutral: starting directly at a later chapter
    remains a new game using its defaults. In a continuous campaign the existing
    exported flags persist and permanently retain the earlier factual outcome.
    """
    prior = [chapter for chapter in (7, 13, 17) if chapter < number]
    kara_dead = ' OR '.join(f'ch{chapter:02}_kara_alive == false' for chapter in prior)
    alice_dead = ' OR '.join(f'ch{chapter:02}_alice_alive == false' for chapter in prior)
    kara_alive = ' AND '.join(f'ch{chapter:02}_kara_alive != false' for chapter in prior)
    alice_alive = ' AND '.join(f'ch{chapter:02}_alice_alive != false' for chapter in prior)
    guard = f'({kara_alive}) AND ({alice_alive})'
    whole_chapter = number in (10, 13, 17, 21, 25)
    original_ending_ids = [key for key, value in doc['endings'].items()
                           if not key.startswith('_') and isinstance(value, dict)]
    explicit_fallback = False
    if whole_chapter and len(original_ending_ids) == 1:
        # The native runner uses the sole ending as an implicit fallback. New
        # skip receipts must not turn that formerly unique ending ambiguous.
        # Chapter 21 ends with a mandatory scene; bind its existing outcome.
        last = doc['nodes'][-1]
        if not any(key.startswith('choices') for key in last['player_facing']):
            last.setdefault('system', {}).setdefault('ending', original_ending_ids[0])
            explicit_fallback = True
    guarded = 0
    for node in doc['nodes']:
        is_kara_track = (node.get('phase') or '').startswith('kara_')
        # Chapter 30's phases are shared; the controlled role is reviewed from
        # every explicit first-line heading, not a narrative name mention.
        if number == 30:
            is_kara_track = node['id'].startswith(('n001_kara_', 'n006_kara_', 'n007_kara_', 'n008_kara_'))
        if whole_chapter or is_kara_track:
            _guard(node, guard)
            guarded += 1
        if number == 30 and node['id'] == 'n005_no_attack':
            # The shared text names Kara/Alice leaving, and its survivor list
            # also names Markus. It is incompatible with any of these earlier
            # terminal outcomes even though it has no Kara phase/name prefix.
            _guard(node, f'({guard}) AND ch28_markus_alive != false')
            guarded += 1
    additions = []
    if whole_chapter:
        # These are software continuity receipts. They report the prior outcome
        # and chapter skip; they do not narrate a fictional new event.
        statuses = [
            ('kara_dead', f'({kara_dead}) AND ({alice_alive})', ['Alice'], ['Kara']),
            ('alice_dead', f'({alice_dead}) AND ({kara_alive})', ['Kara'], ['Alice']),
            ('both_dead', f'({kara_dead}) AND ({alice_dead})', [], ['Kara', 'Alice']),
        ]
        for status, condition, survivors, deaths in statuses:
            ending_id = 'ending_compat_previous_' + status
            additions.append({
                'id': 'compat_previous_' + status, 'type': 'narrative',
                'phase': 'compatibility_skip', 'condition': {'requires': condition},
                'player_facing': {'context': '连续性记录：此前的实际结果已结束这条角色线路，本章跳过。'},
                'system': {'ending': ending_id},
            })
            doc['endings'][ending_id] = {
                'title': '此前已结束的线路 · 本章跳过',
                'narrative': '程序沿用此前已经确认的结果，未发生本章的新剧情或选择。',
                'survivors': survivors, 'deaths': deaths, 'tier': 'neutral',
                'compatibility_skip': True,
            }
    elif number == 30:
        # Ensure the finale's source-authored export rules cannot reset a death
        # to the chapter's default `True`, even though Kara's scenes are skipped.
        for actor, condition in [('kara', kara_dead), ('alice', alice_dead)]:
            additions.append({
                'id': f'compat_inherit_{actor}_death', 'type': 'narrative',
                'phase': 'compatibility_inheritance', 'condition': {'requires': condition},
                'player_facing': {'context': '连续性记录：本章沿用此前已经确认的角色状态。'},
                'system': {'effects': {actor + '_alive_override': False}},
            })
    doc['nodes'] = additions + doc['nodes']
    if number == 30:
        # Early deaths can leave no playable lead while the source still marks
        # Jericho found. The upstream document has no terminal mapping for that
        # combination. Record a software skip without inventing North's fate or
        # reviving a dead lead just to manufacture an ending.
        ending_id = 'ending_compat_no_active_track'
        doc['nodes'].append({
            'id': 'compat_no_active_track', 'type': 'narrative',
            'phase': 'compatibility_skip',
            'condition': {'requires': f'(({kara_dead}) OR ({alice_dead})) AND '
                          'ch28_markus_alive == false AND ch29_connor_alive == false AND ch29_jericho_found == true'},
            'player_facing': {'context': '连续性记录：此前的实际结果使本章没有可继续的主角线路。'},
            'system': {'ending': ending_id},
        })
        doc['endings'][ending_id] = {
            'title': '没有可继续的主角线路 · 保留已有结果',
            'narrative': '程序记录本章无新的主角选择，保留已有角色状态，未补写人物的新结局。',
            'survivors': [], 'deaths': [], 'tier': 'neutral', 'compatibility_skip': True,
        }
        no_attack_id = 'ending_compat_no_attack_previous_terminal'
        doc['nodes'].append({
            'id': 'compat_no_attack_previous_terminal', 'type': 'narrative',
            'phase': 'compatibility_skip',
            'condition': {'requires': f'(({kara_dead}) OR ({alice_dead}) OR ch28_markus_alive == false) '
                          'AND ch29_jericho_found == false'},
            'player_facing': {'context': '连续性记录：本章没有新的主角选择，沿用此前已经确认的角色结果。'},
            'system': {'ending': no_attack_id},
        })
        doc['endings'][no_attack_id] = {
            'title': '共同叙事不再适用 · 保留已有结果',
            'narrative': '程序保留此前的角色状态，未重播包含已终止线路的共同叙事，未补写人物的新结局。',
            'survivors': [], 'deaths': [], 'tier': 'neutral', 'compatibility_skip': True,
        }
    return [{
        'version': COMPATIBILITY_VERSION, 'source_chapter_sha256': digest,
        'chapter_number': number, 'field': 'prior_death_continuity_guards',
        'previous': None,
        'value': {'guarded_authored_nodes': guarded,
                  'software_receipt_nodes_added': len(additions) + 2 * (number == 30),
                  'preserved_original_single_ending_fallback': explicit_fallback,
                  'guarded_incompatible_shared_resolution': number == 30,
                  'preserves_prior_chapter_flags': prior},
        'reason': 'Do not replay later Kara/Alice scenes after an actual prior terminal outcome; new-session copies only.',
    }]

import copy
import json

import pytest

from fish_story import detroit_compat
from fish_story.service import GameService
from fish_story.styles import _visible_label


def synthetic_chapter():
    return {
        'chapter': {'id': 'synthetic_finale', 'chapter_number': 1,
                    'title': 'Synthetic role boundaries',
                    'protagonist': ['Markus', 'Connor']},
        'system_prompt': {'content': ''}, 'state': {'initial': {}},
        'nodes': [
            {'id': 'markus', 'phase': 'markus_introduction', 'type': 'choice',
             'player_facing': {'context': '【马库斯视角】\nMARKUS_PRIVATE',
                               'choices': [{'id': 'next', 'text': 'Continue'}]},
             'system': {}},
            {'id': 'north', 'phase': 'markus_substitute', 'type': 'choice',
             'player_facing': {'context': '【诺丝视角】\nNORTH_PRIVATE',
                               'choices': [{'id': 'next', 'text': 'Continue'}]},
             'system': {}},
            {'id': 'return', 'phase': 'markus_return', 'type': 'choice',
             'player_facing': {'context': '【马库斯视角】\nMARKUS_RETURN',
                               'choices': [{'id': 'finish', 'text': 'Finish'}]},
             'system': {'ending_resolution': {'finish': {'result': 'ending_done'}}}},
        ],
        'endings': {'ending_done': {'title': 'End', 'narrative': 'SHARED_UNATTRIBUTED_END'}},
    }


def test_hash_bound_repairs_only_add_reviewed_perspective_metadata(monkeypatch):
    original = synthetic_chapter()
    original['nodes'][0]['player_facing']['context'] = 'Synthetic unheaded context'
    digest = detroit_compat.canonical_story_hash(original)
    monkeypatch.setattr(detroit_compat, 'PINNED_CHAPTER_REPAIRS', {digest: {'markus': 'Markus'}})
    before = copy.deepcopy(original)
    fixed, changes = detroit_compat.normalize_detroit_chapter(original)
    assert original == before
    assert len(changes) == 1 and changes[0]['source_chapter_sha256'] == digest
    assert fixed['nodes'][0]['player_facing'].pop('perspective') == 'Markus'
    assert fixed == original
    altered = copy.deepcopy(original)
    altered['nodes'][0]['player_facing']['context'] += ' modified'
    assert detroit_compat.normalize_detroit_chapter(altered) == (altered, [])


def test_exact_v1_metadata_copy_upgrades_to_v2_and_v2_is_idempotent(monkeypatch):
    original = synthetic_chapter()
    original['chapter']['chapter_number'] = 13
    digest = detroit_compat.canonical_story_hash(original)
    reviewed = {'markus': 'Markus', 'north': 'Markus'}
    monkeypatch.setattr(detroit_compat, 'PINNED_CHAPTER_REPAIRS', {digest: reviewed})
    monkeypatch.setattr(detroit_compat, 'PINNED_KARA_CONTINUITY_HASHES', {digest: 13})
    version_one = copy.deepcopy(original)
    for node in version_one['nodes']:
        if node['id'] in reviewed:
            node['player_facing']['perspective'] = reviewed[node['id']]
    fixed, changes = detroit_compat.normalize_detroit_chapter(version_one)
    assert len(changes) == 2
    assert changes[0]['upgraded_reviewed_metadata_version'] == 'detroit-metadata/1'
    assert any(node['id'].startswith('compat_previous_') for node in fixed['nodes'])
    again, further = detroit_compat.normalize_detroit_chapter(fixed)
    assert again == fixed and further == []
    modified_v1 = copy.deepcopy(version_one)
    modified_v1['nodes'][-1]['player_facing']['context'] += ' user edit'
    assert detroit_compat.normalize_detroit_chapter(modified_v1) == (modified_v1, [])


def test_north_explicit_heading_has_own_stream_and_does_not_leak_to_markus(tmp_path):
    service = GameService(tmp_path / 'home')
    source = tmp_path / 'synthetic.json'
    source.write_text(json.dumps(synthetic_chapter()), encoding='utf-8')
    story = service.import_story([str(source)], 'Synthetic')['id']
    view = service.start('test-fish', story_id=story, play_style='immersive')
    session = view['session_id']
    north = service.choose(session, view['current']['request_id'], 1)
    assert north['perspective']['controlled_characters'] == ['North']
    assert 'MARKUS_PRIVATE' not in json.dumps(north)
    back = service.choose(session, north['current']['request_id'], 1)
    assert back['perspective']['controlled_characters'] == ['Markus']
    assert 'NORTH_PRIVATE' not in json.dumps(back)
    assert 'MARKUS_PRIVATE' in json.dumps(back)
    assert 'NORTH_PRIVATE' in json.dumps(service.observe(session))
    assert service.choose(session, back['current']['request_id'], 1)['status'] == 'complete'


def test_substitute_heading_requires_complete_visible_heading_in_multi_role_scene():
    assert _visible_label('【诺丝视角】\nScene', ['Markus', 'Connor']) == 'North'
    assert _visible_label('【North视角】\nScene', ['Markus', 'Connor']) == 'North'
    assert _visible_label('Markus heard 【诺丝视角】 in dialogue.', ['Markus', 'Connor']) is None
    assert _visible_label('【诺丝视角】\nScene', ['Markus']) is None


@pytest.mark.parametrize('earlier_death', ['Kara', 'Alice'])
def test_actual_prior_death_skips_later_kara_track_and_does_not_reset_finale(monkeypatch, tmp_path, earlier_death):
    def document(number, actors, node_id, scene, ending_id, deaths=()):
        return {
            'chapter': {'id': f'synthetic_{number}', 'chapter_number': number,
                        'title': f'Synthetic {number}', 'protagonist': actors},
            'system_prompt': {'content': ''}, 'state': {'initial': {}},
            'nodes': [{'id': node_id, 'type': 'choice',
                       'player_facing': {'context': scene, 'choices': [{'id': 'finish', 'text': 'Continue'}]},
                       'system': {'ending_resolution': {'finish': {'result': ending_id}}}}],
            'endings': {ending_id: {'title': 'Synthetic result', 'narrative': 'Synthetic outcome',
                                    'survivors': [actor for actor in ('Kara', 'Alice') if actor not in deaths],
                                    'deaths': list(deaths)}},
        }
    first = document(7, 'Kara', 'earlier', 'ACTUAL_EARLIER_SCENE', 'ending_earlier', [earlier_death])
    first['campaign'] = {
        'derived_exports': [{'target': f'ch07_{actor.lower()}_alive',
                             'from_ending_survivors': actor} for actor in ('Kara', 'Alice')],
        'cross_chapter_exports': ['ch07_kara_alive', 'ch07_alice_alive'],
    }
    later = document(10, 'Kara', 'later', 'SHOULD_NEVER_PLAY_LATER_KARA', 'ending_later')
    finale = document(30, ['Kara', 'Connor'], 'n001_kara_finale', 'SHOULD_NEVER_PLAY_FINALE_KARA', 'ending_kara')
    finale['state']['initial'] = {'kara_alive': True, 'alice_alive': True}
    finale['nodes'].append({
        'id': 'connor_finale', 'phase': 'connor_final', 'type': 'choice',
        'player_facing': {'context': '【康纳视角】\nCONNOR_FINALE',
                         'choices': [{'id': 'finish', 'text': 'Finish'}]},
        'system': {'ending_resolution': {'finish': {'result': 'ending_connor'}}},
    })
    finale['endings']['ending_connor'] = {'title': 'Connor end', 'narrative': 'Connor result'}
    finale['campaign'] = {'derived_exports': [{'target': 'ch30_kara_alive', 'source': 'kara_alive'},
                                             {'target': 'ch30_alice_alive', 'source': 'alice_alive'}],
                          'cross_chapter_exports': ['ch30_kara_alive', 'ch30_alice_alive']}
    monkeypatch.setattr(detroit_compat, 'PINNED_KARA_CONTINUITY_HASHES', {
        detroit_compat.canonical_story_hash(later): 10,
        detroit_compat.canonical_story_hash(finale): 30,
    })
    service = GameService(tmp_path / 'home')
    paths = []
    for doc in (first, later, finale):
        path = tmp_path / f"chapter{doc['chapter']['chapter_number']}.json"
        path.write_text(json.dumps(doc), encoding='utf-8')
        paths.append(str(path))
    story = service.import_story(paths, 'Synthetic continuity')['id']
    view = service.start('audit-fish', story_id=story, chapter=7, play_style='immersive')
    view = service.choose(view['session_id'], view['current']['request_id'], 1)
    assert view['current']['chapter']['chapter_number'] == 30
    assert view['perspective']['controlled_characters'] == ['Connor']
    assert 'SHOULD_NEVER_PLAY' not in json.dumps(service.observe(view['session_id']))
    view = service.choose(view['session_id'], view['current']['request_id'], 1)
    assert view['status'] == 'complete'
    store = service._store(view['session_id'])
    with store.connect() as database:
        run = store.load(database, 'player')
    final_state = run['answers'][-1]['internal_outcome']['state_after']
    assert final_state[earlier_death.lower() + '_alive'] is False


def test_added_skip_receipts_preserve_original_implicit_single_ending(monkeypatch, tmp_path):
    doc = {
        'chapter': {'id': 'synthetic21', 'chapter_number': 21, 'title': 'Synthetic', 'protagonist': 'Kara'},
        'system_prompt': {'content': ''}, 'state': {'initial': {}},
        'nodes': [
            {'id': 'choice', 'type': 'choice',
             'player_facing': {'context': 'A visible choice', 'choices': [{'id': 'continue', 'text': 'Continue'}]},
             'system': {}},
            {'id': 'final_mandatory', 'type': 'narrative',
             'player_facing': {'context': 'Already authored final scene'}, 'system': {}},
        ],
        'endings': {'ending_original': {'title': 'Original implicit result', 'narrative': 'Original result'}},
    }
    monkeypatch.setattr(detroit_compat, 'PINNED_KARA_CONTINUITY_HASHES', {detroit_compat.canonical_story_hash(doc): 21})
    source = tmp_path / 'source.json'
    source.write_text(json.dumps(doc), encoding='utf-8')
    service = GameService(tmp_path / 'home')
    story = service.import_story([str(source)], 'Synthetic fallback')['id']
    view = service.start('fish', story_id=story, chapter=21)
    view = service.choose(view['session_id'], view['current']['request_id'], 1)
    assert view['status'] == 'complete'
    endings = [item['ending'] for item in service.observe(view['session_id'])['history'] if item['type'] == 'chapter_end']
    assert [item['title'] for item in endings] == ['Original implicit result']


def test_no_active_lead_combination_records_software_skip_without_inventing_fate(monkeypatch, tmp_path):
    doc = synthetic_chapter()
    doc['chapter'].update(id='synthetic30', chapter_number=30, protagonist=['Kara', 'Markus', 'Connor'])
    doc['state']['initial'] = {'ch07_kara_alive': False, 'ch07_alice_alive': True,
                              'ch28_markus_alive': False, 'ch29_connor_alive': False,
                              'ch29_jericho_found': True, 'kara_alive': True, 'alice_alive': True}
    doc['nodes'] = [
        {'id': 'n002b_north_leads', 'type': 'narrative',
         'player_facing': {'context': '【马库斯视角——诺丝】\nA source-authored situation without a terminal result'},
         'system': {}},
        {'id': 'n001_kara_late', 'type': 'choice',
         'player_facing': {'context': 'MUST_NOT_REVIVE_KARA', 'choices': [{'id': 'continue', 'text': 'Continue'}]},
         'system': {'ending_resolution': {'continue': {'result': 'ending_done'}}}},
    ]
    monkeypatch.setattr(detroit_compat, 'PINNED_KARA_CONTINUITY_HASHES', {detroit_compat.canonical_story_hash(doc): 30})
    source = tmp_path / 'source.json'
    source.write_text(json.dumps(doc), encoding='utf-8')
    service = GameService(tmp_path / 'home')
    story = service.import_story([str(source)], 'Synthetic no active lead')['id']
    view = service.start('fish', story_id=story, chapter=30, play_style='immersive')
    assert view['status'] == 'complete' and view['accepted_choices'] == 0
    observed = service.observe(view['session_id'])
    assert 'MUST_NOT_REVIVE_KARA' not in json.dumps(observed)
    result = next(item['ending'] for item in observed['history'] if item['type'] == 'chapter_end')
    assert '没有可继续' in result['title'] and '未补写人物的新结局' in result['narrative']


@pytest.mark.parametrize('earlier_death', ['Kara', 'Alice', 'Markus'])
def test_shared_no_attack_text_and_survival_payload_cannot_revive_prior_terminal_character(monkeypatch, tmp_path, earlier_death):
    doc = synthetic_chapter()
    doc['chapter'].update(id='synthetic_shared30', chapter_number=30, protagonist=['Kara', 'Markus', 'Connor'])
    doc['state']['initial'] = {'ch07_kara_alive': earlier_death != 'Kara',
                              'ch07_alice_alive': earlier_death != 'Alice',
                              'ch28_markus_alive': earlier_death != 'Markus',
                              'ch29_connor_alive': True, 'ch29_jericho_found': False,
                              'kara_alive': True, 'alice_alive': True}
    doc['nodes'] = [{'id': 'n005_no_attack', 'type': 'narrative',
                     'condition': {'requires': 'ch29_jericho_found == false'},
                     'player_facing': {'context': 'WRONG_SHARED_SCENE_WITH_TERMINAL_CHARACTERS_ALIVE'},
                     'system': {'ending': 'ending_no_attack'}}]
    doc['endings'] = {'ending_no_attack': {'title': 'WRONG_SHARED_SURVIVAL',
                                         'narrative': 'WRONG_SHARED_ENDING_WITH_ALL_ALIVE',
                                         'survivors': ['Kara', 'Alice', 'Markus']}}
    monkeypatch.setattr(detroit_compat, 'PINNED_KARA_CONTINUITY_HASHES', {detroit_compat.canonical_story_hash(doc): 30})
    source = tmp_path / 'source.json'
    source.write_text(json.dumps(doc), encoding='utf-8')
    service = GameService(tmp_path / 'home')
    story = service.import_story([str(source)], 'Synthetic shared resolution')['id']
    view = service.start('fish', story_id=story, chapter=30, play_style='immersive')
    assert view['status'] == 'complete'
    observed = service.observe(view['session_id'])
    assert 'WRONG_SHARED' not in json.dumps(observed)
    result = next(item['ending'] for item in observed['history'] if item['type'] == 'chapter_end')
    assert '共同叙事不再适用' in result['title'] and '未补写人物的新结局' in result['narrative']


def test_shared_chase_stops_at_actual_terminal_result_before_contradictory_pursuit(monkeypatch, tmp_path):
    doc = synthetic_chapter()
    doc['chapter'].update(id='synthetic_chase13', chapter_number=13, protagonist=['Kara', 'Connor'])
    doc['nodes'] = [
        {'id': 'crossing', 'type': 'choice',
         'player_facing': {'perspective': 'Kara', 'context': 'Synthetic crossing', 'choices': [{'id': 'cross', 'text': 'Cross'}]},
         'system': {'resolution_rule': {'cross': {'casual': {'result': 'ending_terminal'}}}}},
        {'id': 'pursuit', 'type': 'choice',
         'player_facing': {'perspective': 'Connor', 'context': 'MUST_NOT_PURSUE_AFTER_TERMINAL',
                          'choices': [{'id': 'pursue', 'text': 'Pursue'}]},
         'system': {'ending_resolution': {'pursue': {'result': 'ending_alive_again'}}}},
    ]
    doc['endings'] = {'ending_terminal': {'title': 'Actual terminal result', 'narrative': 'Synthetic terminal', 'deaths': ['Kara']},
                      'ending_alive_again': {'title': 'False survival', 'narrative': 'Must not happen', 'survivors': ['Kara']}}
    monkeypatch.setattr(detroit_compat, 'PINNED_KARA_CONTINUITY_HASHES', {detroit_compat.canonical_story_hash(doc): 13})
    source = tmp_path / 'source.json'
    source.write_text(json.dumps(doc), encoding='utf-8')
    service = GameService(tmp_path / 'home')
    story = service.import_story([str(source)], 'Synthetic shared chase')['id']
    view = service.start('fish', story_id=story, chapter=13, play_style='immersive')
    view = service.choose(view['session_id'], view['current']['request_id'], 1)
    assert view['status'] == 'complete' and view['accepted_choices'] == 1
    observed = service.observe(view['session_id'])
    assert 'MUST_NOT_PURSUE' not in json.dumps(observed)
    assert [event['ending']['title'] for event in observed['history'] if event['type'] == 'chapter_end'] == ['Actual terminal result']


@pytest.mark.parametrize(('choice', 'expected'), [(1, 'Connor destroyed'), (2, 'Connor escaped')])
def test_connor_substitute_scene_uses_connor_results_and_stops_after_failure(monkeypatch, tmp_path, choice, expected):
    doc = synthetic_chapter()
    doc['chapter'].update(id='synthetic_substitute30', chapter_number=30, protagonist=['Kara', 'Markus', 'Connor'])
    doc['state']['initial'] = {'ch28_markus_alive': False, 'ch29_connor_alive': True,
                              'ch29_jericho_found': True, 'connor_deviant': True, 'connor_wounded': False}
    standard = [{'id': 'arm_bomb', 'text': 'Arm'}, {'id': 'retreat', 'text': 'Retreat'}]
    doc['nodes'] = [
        {'id': 'n011_markus_hold', 'type': 'choice', 'phase': 'attack',
         'condition': {'requires': 'connor_deviant == true'},
         'player_facing': {'context_variants': {'connor_takes_over': '【康纳视角】\nSynthetic substitute scene'},
                          'choices_variants': {'standard': standard}},
         'system': {'context_condition': {'connor_takes_over': 'ch28_markus_alive == false'},
                    'choices_condition': {'standard': 'connor_deviant == true'},
                    'effects': {'arm_bomb': {}, 'retreat': {}},
                    'resolution_rule': {'arm_bomb': {'casual': {'result': 'ending_markus_killed'}},
                                        'retreat': {'casual': {'result': 'ending_markus_escaped'}}},
                    'resolution_effects': {'bomb_armed': {'markus_bomb_armed': True}}}},
        {'id': 'n013_connor_deviant_escape', 'type': 'choice', 'phase': 'attack',
         'condition': {'requires': 'connor_wounded == false'},
         'player_facing': {'perspective': 'Connor', 'context': 'Existing Connor escape scene',
                          'choices': [{'id': 'escape', 'text': 'Escape'}]},
         'system': {'ending_resolution': {'escape': {'result': 'ending_connor_deviant_escaped'}}}},
    ]
    doc['endings'] = {
        'ending_markus_killed': {'title': 'Wrong Markus death', 'narrative': 'Wrong', 'deaths': ['Markus']},
        'ending_markus_escaped': {'title': 'Wrong Markus escape', 'narrative': 'Wrong', 'survivors': ['Markus']},
        'ending_connor_deviant_destroyed': {'title': 'Connor destroyed', 'narrative': 'Existing result', 'deaths': ['Connor']},
        'ending_connor_deviant_escaped': {'title': 'Connor escaped', 'narrative': 'Existing result', 'survivors': ['Connor']},
    }
    monkeypatch.setattr(detroit_compat, 'PINNED_KARA_CONTINUITY_HASHES', {detroit_compat.canonical_story_hash(doc): 30})
    source = tmp_path / 'source.json'
    source.write_text(json.dumps(doc), encoding='utf-8')
    service = GameService(tmp_path / 'home')
    story = service.import_story([str(source)], 'Synthetic controlled-character outcome')['id']
    view = service.start('fish', story_id=story, chapter=30, play_style='immersive')
    assert view['perspective']['controlled_characters'] == ['Connor']
    view = service.choose(view['session_id'], view['current']['request_id'], choice)
    if choice == 2:
        assert 'Existing Connor escape' in view['current']['context']
        view = service.choose(view['session_id'], view['current']['request_id'], 1)
    assert view['status'] == 'complete'
    endings = [event['ending']['title'] for event in service.observe(view['session_id'])['history'] if event['type'] == 'chapter_end']
    assert endings == [expected]

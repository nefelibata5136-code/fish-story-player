"""Same-player recap requests through real fake-provider HTTP and durable ledgers."""
import json
import os
from unittest.mock import patch

import pytest

from fish_story.model import IndependentPlayer
from fish_story.recaps import RecapStore
from fish_story.service import GameService
from test_model import Provider


def recap_answer(text, limit=None):
    response = Provider.answer()
    answer = {'recap': text}
    if limit is not None:
        answer['max_characters'] = limit
    response['choices'][0]['message']['content'] = json.dumps(answer)
    return response


@pytest.fixture
def recap_game(tmp_path):
    service = GameService(tmp_path / 'game')
    paths = []
    for number, actor in ((1, 'Actor-A'), (2, 'Actor-B'), (3, 'Actor-A')):
        doc = {'chapter': {'id': f'chapter{number}', 'chapter_number': number,
                           'title': f'Original chapter {number}', 'protagonist': actor},
               'system_prompt': {'content': 'PRIVATE_AUTHORED_ROLE_PROMPT'}, 'state': {'initial': {}},
               'nodes': [{'id': f'choice{number}', 'type': 'choice',
                          'player_facing': {'context': f'{actor}_SCENE_{number}',
                                            'choices': [{'id': 'continue', 'text': 'Continue'}]},
                          'system': {'ending_resolution': {'continue': {'result': 'ending_done'}}}}],
               'endings': {'ending_done': {'title': f'Original result {number}',
                                            'narrative': f'{actor}_RESULT_{number}'}}}
        path = tmp_path / f'chapter{number}.json'
        path.write_text(json.dumps(doc), encoding='utf-8')
        paths.append(str(path))
    story = service.import_story(paths, 'Original recap fixture')
    provider = Provider()
    config = {'base_url': provider.base, 'model': 'same-player-model', 'api_key_env': 'FISH_RECAP_TEST_KEY',
              'max_calls': 12, 'token_budget': 2_000_000, 'max_cost': 10,
              'input_per_million': 1, 'output_per_million': 2, 'max_output_tokens': 256, 'timeout': 2}
    def start(style='self_aware', **changes):
        view = service.start('same-fish', story_id=story['id'], mode='independent',
                             core_text='ORIGINAL_PLAYER_CORE', play_style=style)
        return IndependentPlayer(service, view['session_id'], {**config, **changes})
    with patch.dict(os.environ, {'FISH_RECAP_TEST_KEY': 'local-test-key'}):
        yield service, provider, config, start
    provider.close()


def answers(provider):
    provider.responses = [Provider.answer(), recap_answer('MY_RECAP_1', 6000),
                          Provider.answer(), recap_answer('MY_RECAP_2'),
                          Provider.answer(), recap_answer('MY_RECAP_3')]


def test_same_player_authors_every_chapter_and_final_recap_with_stable_prefix(recap_game):
    service, provider, config, start = recap_game
    answers(provider)
    player = start()
    first = player.step()
    assert first['recap_pending'] and not first['recap_updated']
    final = IndependentPlayer(GameService(service.directory), player.session_id, config).run()
    assert final['view']['status'] == 'complete' and final['recap_updated']
    assert not final['recap_pending']
    assert final['view']['accepted_choices'] == 3
    assert final['budget']['call_count'] == 6
    assert [row['kind'] for row in final['budget']['calls']] == ['choice', 'recap'] * 3
    wire = [request['body']['messages'] for request in provider.requests]
    for before, after in zip(wire, wire[1:]):
        assert after[:len(before)] == before
    first_recap = json.dumps(wire[1])
    assert 'Actor-A_RESULT_1' in first_recap
    assert 'Actor-B_SCENE_2' not in first_recap
    assert json.loads(wire[1][-1]['content'])['max_characters'] == 5000
    assert json.loads(wire[3][-1]['content'])['max_characters'] == 6000
    latest = RecapStore(service).read(player.session_id)
    assert latest['text'] == 'MY_RECAP_3' and latest['revision'] == 3
    assert latest['max_characters'] == 6000
    for messages in wire:
        assert messages[0] == wire[0][0]
        assert 'ORIGINAL_PLAYER_CORE' in messages[0]['content']
        assert 'PRIVATE_AUTHORED_ROLE_PROMPT' not in json.dumps(messages)


def test_immersive_recap_uses_ended_role_without_next_role_and_resumes_own_prefix(recap_game):
    service, provider, config, start = recap_game
    answers(provider)
    final = start('immersive').run()
    assert final['view']['status'] == 'complete' and final['budget']['call_count'] == 6
    wire = [request['body']['messages'] for request in provider.requests]
    for index in (0, 1, 4, 5):
        assert 'Actor-B_' not in json.dumps(wire[index])
    for index in (2, 3):
        assert 'Actor-A_' not in json.dumps(wire[index])
    for earlier, later in ((0, 1), (1, 4), (4, 5), (2, 3)):
        assert wire[later][:len(wire[earlier])] == wire[earlier]
    assert 'MY_RECAP_1' in json.dumps(wire[4])
    assert 'MY_RECAP_2' not in json.dumps(wire[4])


def test_recap_commit_crash_replays_saved_result_without_another_model_call(recap_game, monkeypatch):
    service, provider, config, start = recap_game
    answers(provider)
    player = start()
    player.step()
    update = player.recaps.update
    def committed_then_crash(*args, **kwargs):
        update(*args, **kwargs)
        raise RuntimeError('simulated crash after durable recap commit')
    monkeypatch.setattr(player.recaps, 'update', committed_then_crash)
    with pytest.raises(RuntimeError):
        player.step()
    assert player.status()['calls'][-1]['status'] == 'ready'
    resumed = IndependentPlayer(GameService(service.directory), player.session_id, config).step()
    assert resumed['recap_updated'] and not resumed['recap_pending']
    assert len(provider.requests) == 2
    assert len(RecapStore(service).entries(player.session_id)) == 1
    assert resumed['budget']['calls'][-1]['status'] == 'applied'


def test_overlimit_recap_is_charged_untruncated_and_can_be_adjusted_by_player(recap_game):
    service, provider, config, start = recap_game
    provider.responses = [Provider.answer(), recap_answer('x' * 5001), recap_answer('x' * 5001, 6000)]
    player = start()
    player.step()
    with pytest.raises(ValueError, match='RECAP_TOO_LONG'):
        player.step()
    assert player.status()['calls'][-1]['status'] == 'rejected'
    assert player.status()['accounted_tokens'] == 350
    assert service.view(player.session_id)['accepted_choices'] == 1
    assert RecapStore(service).read(player.session_id)['text'] == ''
    updated = player.step()
    assert updated['recap_updated']
    assert RecapStore(service).read(player.session_id)['text'] == 'x' * 5001
    assert RecapStore(service).read(player.session_id)['max_characters'] == 6000
    assert service.view(player.session_id)['accepted_choices'] == 1


def test_recap_respects_same_finite_budget_without_advancing_next_scene(recap_game):
    service, provider, config, start = recap_game
    player = start(max_calls=1)
    with pytest.raises(ValueError, match='MODEL_BUDGET_EXHAUSTED'):
        player.run()
    assert len(provider.requests) == 1
    assert service.view(player.session_id)['accepted_choices'] == 1
    assert len(RecapStore(service).tasks(player.session_id)) == 1


def test_checkpoint_inherits_authored_exchange_and_shared_budget_without_rewriting_prefix(recap_game):
    service, provider, config, start = recap_game
    answers(provider)
    player = start()
    player.step()
    player.step()
    before = player.messages()
    branch = service.load_save_point(player.session_id, 'auto:1', operation_id='recap-branch')
    branch_player = IndependentPlayer(service, branch['session_id'], config)
    assert branch_player.messages() == before
    assert not branch_player._pending_recaps()
    assert branch_player.status()['call_count'] == 2
    assert len(provider.requests) == 2


def test_branch_before_parent_recap_can_author_same_stable_task_independently(recap_game):
    service, provider, config, start = recap_game
    provider.responses = [Provider.answer(), recap_answer('PARENT_RECAP'), recap_answer('BRANCH_RECAP')]
    parent = start()
    parent.step()
    task_id = parent._pending_recaps()[0]['task_id']
    point = service.save_point(parent.session_id, 'Before recap', operation_id='before-parent-recap')
    parent.step()
    branch = service.load_save_point(parent.session_id, point['id'], operation_id='fork-before-recap')
    child = IndependentPlayer(service, branch['session_id'], config)
    assert child._pending_recaps()[0]['task_id'] == task_id
    assert child.step()['recap_updated']
    assert len(provider.requests) == 3
    assert RecapStore(service).read(parent.session_id)['text'] == 'PARENT_RECAP'
    assert RecapStore(service).read(branch['session_id'])['text'] == 'BRANCH_RECAP'
    assert child.status()['call_count'] == parent.status()['call_count'] == 3

"""Branches preserve real evidence and share one durable independent-model budget."""
import json
import os
import sqlite3
import threading
from unittest.mock import patch

import pytest

from fish_story.model import IndependentPlayer, load_config
from fish_story.saves import SaveManager
from fish_story.service import GameService
from test_model import Provider
from test_styles import chapter, imported


@pytest.fixture
def model_game(tmp_path):
    service = GameService(tmp_path / 'data')
    source = service.start('fish', mode='independent', core_text='Generic player core.', save_name='Original')
    provider = Provider()
    config = {'base_url': provider.base, 'model': 'fake', 'api_key_env': 'FISH_BRANCH_TEST_KEY',
              'max_calls': 2, 'token_budget': 100000, 'max_cost': 1,
              'input_per_million': 1, 'output_per_million': 2, 'max_output_tokens': 128, 'timeout': 2}
    with patch.dict(os.environ, {'FISH_BRANCH_TEST_KEY': 'local-fixture-value'}):
        yield service, source, provider, config
    provider.close()


def test_loading_a_point_cannot_reset_model_budget_or_pinned_config(model_game):
    service, source, provider, config = model_game
    sid = source['session_id']
    first = IndependentPlayer(service, sid, config)
    first.step()
    branch = service.load_save_point(sid, 'auto:0', 'Alternative', 'fork-budget')
    bid = branch['session_id']
    second = IndependentPlayer(service, bid, config)
    assert second.db_path == first.db_path
    assert not (service.session_dir(bid) / 'model.sqlite').exists()
    assert second.status()['call_count'] == 1
    assert load_config(service, bid)['max_calls'] == config['max_calls']
    with pytest.raises(ValueError, match='MODEL_CONFIG_OR_CORE_CHANGED'):
        IndependentPlayer(service, bid, {**config, 'max_calls': 20})
    second.step()
    assert first.status()['call_count'] == second.status()['call_count'] == 2
    assert {c['session_id'] for c in first.status()['calls']} == {sid, bid}
    with pytest.raises(ValueError, match='MODEL_BUDGET_EXHAUSTED'):
        first.step()
    assert len(provider.requests) == 2


def test_unresolved_family_request_blocks_fork_and_other_branch_requests(model_game):
    service, source, provider, config = model_game
    sid = source['session_id']
    first = IndependentPlayer(service, sid, config)
    point = service.save_point(sid, 'Before request', operation_id='point-before')
    call_id, _ = first._reserve(source['current']['request_id'], first.messages())
    with pytest.raises(ValueError, match='MODEL_FAMILY_BUSY'):
        service.load_save_point(sid, point['id'], operation_id='must-not-fork')
    # Simulates a fork that passed the check just before another request reserved.
    # Even that race cannot escape the shared ledger at the actual API boundary.
    branch = SaveManager(service).fork(sid, point['id'], operation_id='concurrent-fork')
    second = IndependentPlayer(service, branch['session_id'], config)
    with pytest.raises(ValueError, match='UNRESOLVED_MODEL_CALL'):
        second.step()
    with pytest.raises(ValueError, match='NO_UNRESOLVED_CALL'):
        second.acknowledge_unknown(call_id)
    assert not provider.requests
    first.acknowledge_unknown(call_id)
    assert second.status()['call_count'] == 1  # Full reservation remains charged.


def test_ready_answer_only_recovers_into_its_owning_branch(model_game):
    service, source, provider, config = model_game
    sid = source['session_id']
    first = IndependentPlayer(service, sid, config)
    point = service.save_point(sid, 'Initial', operation_id='initial')
    call, _ = first._reserve(source['current']['request_id'], first.messages())
    first._update(call, status='ready', result=json.dumps({'choice': 1, 'public_reason': 'Saved public response'}))
    branch = SaveManager(service).fork(sid, point['id'], operation_id='ready-race')
    second = IndependentPlayer(service, branch['session_id'], config)
    assert second.status()['blocked']
    assert second.status()['pending_ready_session_ids'] == [sid]
    with pytest.raises(ValueError, match='UNRESOLVED_MODEL_CALL'):
        second.step()
    assert service.view(branch['session_id'])['accepted_choices'] == 0
    result = first.step()
    assert result['view']['accepted_choices'] == 1
    assert service.view(branch['session_id'])['accepted_choices'] == 0
    assert first.status()['calls'][0]['status'] == 'applied'
    assert not provider.requests  # Recovered saved answer without another request.


def test_budget_family_missing_or_foreign_root_is_rejected(model_game):
    service, source, provider, config = model_game
    sid = source['session_id']
    first = IndependentPlayer(service, sid, config)
    branch = service.load_save_point(sid, 'auto:0', operation_id='family-protection')
    path = service.session_dir(branch['session_id']) / 'session.json'
    meta = json.loads(path.read_text(encoding='utf-8'))
    foreign = service.start('another-player')
    changed = {**meta, 'budget_family_id': foreign['session_id']}
    path.write_text(json.dumps(changed), encoding='utf-8')
    with pytest.raises(ValueError, match='BUDGET_FAMILY_NOT_OWNED'):
        load_config(service, branch['session_id'])
    path.write_text(json.dumps(meta), encoding='utf-8')
    first.db_path.unlink()
    with pytest.raises(ValueError, match='BUDGET_FAMILY_INVALID'):
        IndependentPlayer(service, branch['session_id'], config)
    assert not (service.session_dir(branch['session_id']) / 'model.sqlite').exists()


def test_initialized_budget_cannot_restart_from_a_truncated_ledger(model_game):
    service, source, provider, config = model_game
    player = IndependentPlayer(service, source['session_id'], config)
    player.db_path.write_bytes(b'')
    with pytest.raises(ValueError, match='BUDGET_FAMILY_INVALID'):
        IndependentPlayer(service, source['session_id'], config)
    assert player.db_path.read_bytes() == b'' and not provider.requests


def test_old_ledger_migration_preserves_usage_and_routes_existing_calls(model_game):
    service, source, provider, config = model_game
    sid = source['session_id']
    first = IndependentPlayer(service, sid, config)
    with first._db() as db:
        db.execute('DROP TABLE calls')
        db.execute('''CREATE TABLE calls (
            id TEXT PRIMARY KEY, request_id TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            reserved_tokens INTEGER NOT NULL,reserved_cost REAL NOT NULL,
            charged_tokens INTEGER NOT NULL,charged_cost REAL NOT NULL,
            prompt_bound INTEGER NOT NULL,result TEXT,usage TEXT,error TEXT)''')
        db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('old-call', 'old-request', 'applied', 'old-time', 'old-time', 100, 0.1, 75, 0.05, 90, None, None, None))
    restored = IndependentPlayer(service, sid, config)
    assert restored.status()['accounted_tokens'] == 75
    assert restored.status()['accounted_cost'] == 0.05
    assert restored.status()['calls'][0]['session_id'] == sid


def test_inherited_choices_are_references_not_new_dots_events(tmp_path):
    service = GameService(tmp_path / 'data')
    v = service.start('fish', save_name='PRIVATE_ROOT_NAME')
    sid = v['session_id']
    v = service.choose(sid, v['current']['request_id'], 1, 'Original explanation')
    branch = service.load_save_point(sid, 'auto:1', 'PRIVATE_BRANCH_NAME', 'lineage')
    bid = branch['session_id']
    assert branch['inherited_choices'] == 1 and branch['new_choice_count'] == 0
    assert '继承' in service.export(bid, 'memory')
    before = service.export_evidence(bid, tmp_path / 'export')
    assert before['count'] == 0
    assert len(before['lineage']['inherited_event_references']) == 1
    branch = service.choose(bid, branch['current']['request_id'], 1)
    one = service.export_evidence(bid, tmp_path / 'export')
    two = service.export_evidence(bid, tmp_path / 'export')
    assert one == two and one['count'] == 1
    shared = json.dumps(service.export(bid, share=True))
    for secret in ('PRIVATE_ROOT_NAME', 'PRIVATE_BRANCH_NAME', sid, v['records'][0]['record_id']):
        assert secret not in shared


def test_same_fork_operation_can_reconcile_after_source_role_changes(tmp_path):
    service = GameService(tmp_path / 'data')
    story = imported(service, tmp_path, [chapter(1, 'A', 'A_PRIVATE'), chapter(2, 'B', 'B_PRIVATE')])
    source = service.start('fish', story, play_style='immersive')
    sid = source['session_id']
    point = service.save_point(sid, 'A point', operation_id='a-point')
    branch = service.load_save_point(sid, point['id'], 'A branch', 'same-load')
    service.choose(sid, source['current']['request_id'], 1)
    assert service.view(sid)['perspective']['controlled_characters'] == ['B']
    again = service.load_save_point(sid, point['id'], 'A branch', 'same-load')
    assert again == branch and 'B_PRIVATE' not in json.dumps(again)
    assert len(service.sessions()) == 2


def test_save_current_operation_freezes_first_progress_on_retry(tmp_path):
    service = GameService(tmp_path)
    source = service.start('fish')
    point = service.save_point(source['session_id'], 'Initial point', operation_id='same-point')
    service.choose(source['session_id'], source['current']['request_id'], 1)
    assert service.save_point(source['session_id'], 'Initial point', operation_id='same-point') == point


def test_immersive_player_can_choose_own_earlier_role_point_without_plot_labels(tmp_path):
    service = GameService(tmp_path / 'data')
    story = imported(service, tmp_path, [chapter(1, 'A', 'A_PRIVATE'), chapter(2, 'B', 'B_PRIVATE')])
    source = service.start('fish', story, play_style='immersive')
    sid = source['session_id']
    point = service.save_point(sid, 'A_PRIVATE_CUSTOM_LABEL', operation_id='a-label')
    service.choose(sid, source['current']['request_id'], 1)
    player_controls = service.save_points(sid)
    assert point['id'] in [p['id'] for p in player_controls['points']]
    assert 'A_PRIVATE_CUSTOM_LABEL' not in json.dumps(player_controls)
    assert 'A_PRIVATE_CUSTOM_LABEL' in json.dumps(service.save_points(sid, audience='observer'))
    branch = service.load_save_point(sid, point['id'], operation_id='own-role-return')
    assert branch['perspective']['controlled_characters'] == ['A']
    assert 'A_PRIVATE' in json.dumps(branch) and 'B_PRIVATE' not in json.dumps(branch)

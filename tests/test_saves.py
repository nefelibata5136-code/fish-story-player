"""Real local checkpoint/branch persistence, with no model or private stories."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from fish_story.service import GameService
from fish_story.saves import SaveManager


def answer(service, view, choice=1, reason='A real fixture choice'):
    return service.choose(view['session_id'], view['current']['request_id'], choice, reason)


def test_named_points_multiple_branches_and_original_save_unchanged(tmp_path):
    service = GameService(tmp_path)
    saves = SaveManager(service)
    source = service.start('fish')
    start = saves.create_point(source['session_id'], 'Before opening', operation_id='point-zero')
    source = answer(service, source, 1)
    one = saves.create_point(source['session_id'], 'After clue', operation_id='point-one')
    source = answer(service, source, 2)
    original = service.observe(source['session_id'])
    original_db = (service.session_dir(source['session_id']) / 'games.sqlite').read_bytes()
    branch_a = saves.fork(source['session_id'], start['id'], 'Other approach', 'fork-a')
    branch_b = saves.fork(source['session_id'], one['id'], 'Another route', 'fork-b')
    assert branch_a['accepted_choices'] == 0
    assert branch_b['accepted_choices'] == 1
    assert branch_a['session_id'] != branch_b['session_id'] != source['session_id']
    assert branch_a['save_name'] == 'Other approach'
    assert branch_b['parent_session_id'] == source['session_id']
    assert branch_b['inherited_choices'] == 1
    assert branch_b['records'][0]['inherited']
    assert branch_b['records'][0]['occurred_at'] == original['records'][0]['occurred_at']
    assert branch_b['records'][0]['origin_record_id'] == original['records'][0]['record_id']
    assert branch_b['records'][0]['record_id'] != original['records'][0]['record_id']
    assert branch_b['current']['request_id'] != original['records'][1]['request_id']
    answer(service, branch_a, 2)
    answer(service, branch_b, 1)
    assert service.observe(source['session_id']) == original
    assert (service.session_dir(source['session_id']) / 'games.sqlite').read_bytes() == original_db


def test_auto_points_current_and_historical_locations(tmp_path):
    service = GameService(tmp_path)
    saves = SaveManager(service)
    view = service.start('fish')
    initial = view['current']
    view = answer(service, view)
    middle = copy.deepcopy(view)
    view = answer(service, view)
    points = saves.list_points(view['session_id'])['points']
    auto = [point for point in points if point['kind'] == 'automatic']
    assert [point['id'] for point in auto] == ['auto:0', 'auto:1', 'auto:2']
    assert auto[0]['current_node_ref'] == initial['node_ref']
    assert auto[1]['current_node_ref'] == middle['current']['node_ref']
    assert auto[2]['current_node_ref'] == view['current']['node_ref']
    assert all('scene' not in point and 'options' not in point for point in auto)
    branch = saves.fork(view['session_id'], 'auto:1', operation_id='automatic-fork')
    assert branch['current']['context'] == middle['current']['context']
    assert branch['accepted_choices'] == 1
    manual = saves.create_point(view['session_id'], 'Past point', choice_count=0)
    assert manual['choice_count'] == 0
    assert saves.fork(view['session_id'], manual['id'])['accepted_choices'] == 0


def test_operation_ids_are_idempotent_and_conflicts_refused(tmp_path):
    service = GameService(tmp_path)
    saves = SaveManager(service)
    view = service.start('fish')
    point = saves.create_point(view['session_id'], 'Beginning', operation_id='create-stable')
    assert saves.create_point(view['session_id'], 'Beginning', operation_id='create-stable') == point
    answer(service, view)
    # Omitted count is frozen on the first request, not re-evaluated on retry.
    assert saves.create_point(view['session_id'], 'Beginning', operation_id='create-stable') == point
    with pytest.raises(ValueError, match='OPERATION_CONFLICT'):
        saves.create_point(view['session_id'], 'Different', operation_id='create-stable')
    first = saves.fork(view['session_id'], point['id'], 'Branch', 'fork-stable')
    repeated = SaveManager(GameService(tmp_path)).fork(view['session_id'], point['id'], 'Branch', 'fork-stable')
    assert repeated == first
    assert len(service.sessions()) == 2
    with pytest.raises(ValueError, match='OPERATION_CONFLICT'):
        saves.fork(view['session_id'], point['id'], 'Other branch', 'fork-stable')


def test_pause_restore_and_checkpoint_rename(tmp_path):
    service = GameService(tmp_path)
    view = answer(service, service.start('fish'))
    service.pause(view['session_id'])
    saves = SaveManager(service)
    point = saves.create_point(view['session_id'], 'Paused here')
    renamed = saves.rename_point(view['session_id'], point['id'], 'Keep this moment')
    assert renamed['name'] == 'Keep this moment'
    assert renamed['name_history'][0]['name'] == 'Paused here'
    recovered = SaveManager(GameService(tmp_path)).list_points(view['session_id'])
    assert any(p['name'] == 'Keep this moment' for p in recovered['points'])
    branch = saves.fork(view['session_id'], point['id'])
    assert branch['status'] == 'paused'
    service.resume(branch['session_id'])
    assert answer(service, service.view(branch['session_id']))['accepted_choices'] == 2


def test_inherited_origin_survives_multiple_generations(tmp_path):
    service = GameService(tmp_path)
    saves = SaveManager(service)
    root = answer(service, service.start('fish'))
    first = saves.fork(root['session_id'], 'auto:1', operation_id='generation-one')
    first = answer(service, first)
    second = saves.fork(first['session_id'], 'auto:2', operation_id='generation-two')
    assert second['budget_family_id'] == root['session_id']
    assert second['save_family_id'] == root['session_id']
    assert second['records'][0]['origin_session_id'] == root['session_id']
    assert second['records'][0]['origin_record_id'] == root['records'][0]['record_id']
    assert second['records'][0]['inherited_from_session_id'] == first['session_id']
    assert second['records'][1]['origin_session_id'] == first['session_id']
    assert all(r['inherited'] for r in second['records'])


def test_prefix_does_not_inherit_later_plot_notes_or_later_core_edits(tmp_path):
    service = GameService(tmp_path)
    source = service.start('fish', mode='independent', core_text='ORIGINAL_CORE')
    saves = SaveManager(service)
    point = saves.create_point(source['session_id'], 'Fresh identity', operation_id='freeze')
    source = answer(service, source)
    source = answer(service, source)
    source_dir = service.session_dir(source['session_id'])
    (source_dir / 'core.txt').write_text('LATER_EDIT', encoding='utf-8')
    service._store(source['session_id']).mutate('player', 'note', {'note_id': 'later-note', 'text': 'LATER_NOTE'})
    branch = saves.fork(source['session_id'], point['id'])
    assert branch['accepted_choices'] == 0 and branch['notes'] == []
    assert not branch['records']
    assert (service.session_dir(branch['session_id']) / 'core.txt').read_text(encoding='utf-8') == 'ORIGINAL_CORE'
    assert 'LATER_NOTE' not in json.dumps(branch)
    assert source['current']['context'] not in json.dumps(branch)


def test_invalid_future_points_and_bad_names_leave_game_unchanged(tmp_path):
    service = GameService(tmp_path)
    source = service.start('fish')
    saves = SaveManager(service)
    for count in (-1, 1, True, '0'):
        with pytest.raises(ValueError, match='INVALID_SAVE_POINT'):
            saves.create_point(source['session_id'], 'Invalid', count)
    for name in ('', ' ', 'x' * 101, '\x00'):
        with pytest.raises(ValueError, match='INVALID_SAVE_NAME'):
            saves.create_point(source['session_id'], name)
    with pytest.raises(ValueError, match='INVALID_SAVE_POINT'):
        saves.fork(source['session_id'], 'auto:99')
    assert service.view(source['session_id']) == source
    assert len(service.sessions()) == 1


def test_published_target_is_reconciled_after_response_or_receipt_crash(tmp_path):
    service = GameService(tmp_path)
    source = answer(service, service.start('fish'))
    saves = SaveManager(service)
    real_build = saves._build_branch

    def crash_after_publish(*args):
        real_build(*args)
        raise RuntimeError('SIMULATED_CRASH_AFTER_PUBLISH')

    with patch.object(saves, '_build_branch', side_effect=crash_after_publish):
        with pytest.raises(RuntimeError, match='SIMULATED_CRASH'):
            saves.fork(source['session_id'], 'auto:1', operation_id='recover-published')
    assert len(service.sessions()) == 2
    branch = SaveManager(GameService(tmp_path)).fork(source['session_id'], 'auto:1', operation_id='recover-published')
    assert branch['accepted_choices'] == 1 and len(service.sessions()) == 2


def test_partial_build_retries_same_target_without_publishing_incomplete_game(tmp_path):
    service = GameService(tmp_path)
    source = service.start('fish')
    saves = SaveManager(service)
    with patch('fish_story.saves.shutil.copyfile', side_effect=OSError('SIMULATED_COPY_FAILURE')):
        with pytest.raises(OSError):
            saves.fork(source['session_id'], 'auto:0', operation_id='recover-partial')
    assert len(service.sessions()) == 1
    branch = saves.fork(source['session_id'], 'auto:0', operation_id='recover-partial')
    assert len(service.sessions()) == 2 and branch['accepted_choices'] == 0


def test_changed_pinned_story_refuses_fork_without_changing_checkpoint(tmp_path):
    service = GameService(tmp_path)
    source = service.start('fish')
    saves = SaveManager(service)
    point = saves.create_point(source['session_id'], 'Pinned')
    chapter = next((service.session_dir(source['session_id']) / 'story').glob('*.json'))
    chapter.write_bytes(chapter.read_bytes() + b' ')
    with pytest.raises(ValueError, match='ENGINE_CHANGED'):
        saves.fork(source['session_id'], point['id'])
    assert len(service.sessions()) == 1


def test_random_seed_and_native_internal_result_are_preserved_across_fork(tmp_path):
    doc = {
        'chapter': {'id': 'random-fixture', 'chapter_number': 1, 'title': 'A chance crossing', 'protagonist': 'Courier'},
        'system_prompt': {'content': ''}, 'state': {'initial': {'crossed': False}},
        'nodes': [
            {'id': 'n001_attempt', 'type': 'qte_converted',
             'player_facing': {'context': 'Try to cross the fictional stream?', 'choices': [{'id': 'try', 'text': 'Try'}]},
             'system': {'resolution_rule': {'try': {'experienced': {'probability_success': 0.5, 'success': 'won', 'failure': 'lost'}}},
                        'resolution_effects': {'won': {'crossed': True}, 'lost': {'crossed': False}}}},
            {'id': 'n002_after', 'type': 'choice',
             'player_facing': {'context_variants': {'won': 'The courier crossed.', 'lost': 'The courier stayed.'},
                               'choices': [{'id': 'finish', 'text': 'Finish'}]},
             'system': {'context_condition': {'won': 'crossed == true', 'lost': 'crossed == false'},
                        'ending_resolution': {'finish': {'result': 'ending_done'}}}}
        ], 'endings': {'ending_done': {'title': 'Done', 'narrative': 'The crossing story ended.'}}
    }
    chapter = tmp_path / 'random.json'; chapter.write_text(json.dumps(doc), encoding='utf-8')
    service = GameService(tmp_path / 'home'); saves = SaveManager(service)
    story = service.import_story([str(chapter)], 'Random fixture')
    initial = service.start('fish', story_id=story['id'], difficulty='experienced')
    source = answer(service, initial)
    before = saves.fork(source['session_id'], 'auto:0', operation_id='same-random-before')
    repeated = answer(service, before)
    assert repeated['current']['context'] == source['current']['context']
    inherited = saves.fork(source['session_id'], 'auto:1', operation_id='same-random-after')
    assert inherited['current']['context'] == source['current']['context']
    runs = []
    for sid in (source['session_id'], repeated['session_id'], inherited['session_id']):
        with service._store(sid).connect() as db:
            runs.append(service._store(sid).load(db, 'player'))
    assert len({run['seed'] for run in runs}) == 1
    assert runs[0]['answers'][0]['internal_outcome'] == runs[1]['answers'][0]['internal_outcome'] == runs[2]['answers'][0]['internal_outcome']


def test_legacy_v010_save_can_checkpoint_and_branch_without_rewriting_source(tmp_path):
    from fish_story.service import write_json

    service = GameService(tmp_path)
    source = service.start('legacy-player')
    directory = service.session_dir(source['session_id'])
    meta = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
    for key in ('play_style', 'play_style_version', 'save_name', 'budget_family_id', 'inherited_choices'):
        meta.pop(key, None)
    write_json(directory / 'session.json', meta)
    source = answer(service, service.view(source['session_id']))
    assert source['play_style'] == 'legacy_unspecified' and 'play_style' not in source['records'][0]
    old_bytes = (directory / 'games.sqlite').read_bytes()
    saves = SaveManager(service)
    point = saves.create_point(source['session_id'], 'Legacy checkpoint')
    branch = saves.fork(source['session_id'], point['id'], operation_id='legacy-fork')
    assert branch['play_style'] == 'legacy_unspecified'
    assert branch['accepted_choices'] == 1 and branch['new_choice_count'] == 0
    assert branch['records'][0]['inherited']
    assert branch['records'][0]['occurred_at'] == source['records'][0]['occurred_at']
    assert branch['budget_family_id'] == source['session_id']
    assert (directory / 'games.sqlite').read_bytes() == old_bytes


def test_manual_checkpoint_snapshot_corruption_is_refused(tmp_path):
    service = GameService(tmp_path)
    source = answer(service, service.start('fish', mode='independent', core_text='Original core'))
    saves = SaveManager(service)
    point = saves.create_point(source['session_id'], 'Do not mutate')
    with saves._db(source['session_id']) as db:
        snapshot = json.loads(db.execute('SELECT snapshot FROM points WHERE id=?', (point['id'],)).fetchone()[0])
        snapshot['run']['answers'][0]['reason'] = 'ALTERED_AFTER_CHECKPOINT'
        db.execute('UPDATE points SET snapshot=? WHERE id=?', (json.dumps(snapshot), point['id']))
    before = (service.session_dir(source['session_id']) / 'games.sqlite').read_bytes()
    with pytest.raises(ValueError, match='SAVE_SNAPSHOT_CHANGED'):
        saves.fork(source['session_id'], point['id'], operation_id='corruption-test')
    assert len(service.sessions()) == 1
    assert (service.session_dir(source['session_id']) / 'games.sqlite').read_bytes() == before


def test_reserved_operation_snapshot_corruption_is_refused_on_retry(tmp_path):
    service = GameService(tmp_path)
    source = service.start('fish', mode='independent', core_text='Original core')
    saves = SaveManager(service)
    with patch.object(saves, '_build_branch', side_effect=OSError('SIMULATED_STOP')):
        with pytest.raises(OSError):
            saves.fork(source['session_id'], 'auto:0', operation_id='reserved-corruption')
    with saves._db(source['session_id']) as db:
        data = json.loads(db.execute('SELECT data FROM operations WHERE id=?', ('reserved-corruption',)).fetchone()[0])
        data['snapshot']['core_hex'] = b'Changed core'.hex()
        db.execute('UPDATE operations SET data=? WHERE id=?', (json.dumps(data), 'reserved-corruption'))
    with pytest.raises(ValueError, match='SAVE_SNAPSHOT_CHANGED'):
        saves.fork(source['session_id'], 'auto:0', operation_id='reserved-corruption')
    assert len(service.sessions()) == 1


def test_reconcile_fork_is_read_only_and_does_not_create_missing_operations(tmp_path):
    service = GameService(tmp_path)
    source = service.start('fish')
    saves = SaveManager(service)
    directory = service.session_dir(source['session_id'])
    assert saves.reconcile_fork(source['session_id'], 'auto:0', operation_id='not-created') is None
    assert not (directory / 'points.sqlite').exists()
    branch = saves.fork(source['session_id'], 'auto:0', 'Named', 'published-op')
    before = (directory / 'points.sqlite').read_bytes()
    assert saves.reconcile_fork(source['session_id'], 'auto:0', 'Named', 'published-op') == branch
    assert (directory / 'points.sqlite').read_bytes() == before
    assert len(service.sessions()) == 2
    with pytest.raises(ValueError, match='OPERATION_CONFLICT'):
        saves.reconcile_fork(source['session_id'], 'auto:0', 'Other name', 'published-op')


def test_reconcile_reserved_but_published_target_does_not_mark_complete(tmp_path):
    service = GameService(tmp_path)
    source = answer(service, service.start('fish'))
    saves = SaveManager(service)
    build = saves._build_branch

    def crash(*args):
        build(*args)
        raise RuntimeError('SIMULATED_RECEIPT_CRASH')

    with patch.object(saves, '_build_branch', side_effect=crash):
        with pytest.raises(RuntimeError):
            saves.fork(source['session_id'], 'auto:1', operation_id='unknown-receipt')
    path = service.session_dir(source['session_id']) / 'points.sqlite'
    before = path.read_bytes()
    branch = saves.reconcile_fork(source['session_id'], 'auto:1', operation_id='unknown-receipt')
    assert branch['accepted_choices'] == 1
    assert path.read_bytes() == before
    with saves._db(source['session_id']) as db:
        assert db.execute('SELECT state FROM operations WHERE id=?', ('unknown-receipt',)).fetchone()[0] == 'reserved'


def test_reconcile_never_publishes_an_incomplete_staging_target(tmp_path):
    service = GameService(tmp_path)
    source = service.start('fish')
    saves = SaveManager(service)
    with patch('fish_story.saves.shutil.copyfile', side_effect=OSError('INCOMPLETE')):
        with pytest.raises(OSError):
            saves.fork(source['session_id'], 'auto:0', operation_id='incomplete-op')
    assert saves.reconcile_fork(source['session_id'], 'auto:0', operation_id='incomplete-op') is None
    assert len(service.sessions()) == 1


@pytest.mark.parametrize('operation_id', [False, 0, ''])
def test_invalid_empty_like_operation_ids_are_not_silently_replaced(tmp_path, operation_id):
    service = GameService(tmp_path)
    source = service.start('fish')
    saves = SaveManager(service)
    with pytest.raises(ValueError, match='INVALID_OPERATION_ID'):
        saves.create_point(source['session_id'], 'Named', operation_id=operation_id)
    with pytest.raises(ValueError, match='INVALID_OPERATION_ID'):
        saves.fork(source['session_id'], 'auto:0', operation_id=operation_id)
    assert len(service.sessions()) == 1


def test_reconcile_checks_snapshot_integrity_and_published_metadata(tmp_path):
    from fish_story.service import write_json

    service = GameService(tmp_path)
    source = service.start('fish')
    saves = SaveManager(service)
    branch = saves.fork(source['session_id'], 'auto:0', operation_id='check-markers')
    meta_path = service.session_dir(branch['session_id']) / 'session.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    meta['parent_session_id'] = branch['session_id']
    write_json(meta_path, meta)
    with pytest.raises(ValueError, match='SAVE_RECOVERY_CONFLICT'):
        saves.reconcile_fork(source['session_id'], 'auto:0', operation_id='check-markers')
    meta['parent_session_id'] = source['session_id']; write_json(meta_path, meta)
    with saves._db(source['session_id']) as db:
        data = json.loads(db.execute('SELECT data FROM operations WHERE id=?', ('check-markers',)).fetchone()[0])
        data['snapshot']['meta']['player_id'] = 'Edited metadata'
        db.execute('UPDATE operations SET data=? WHERE id=?', (json.dumps(data), 'check-markers'))
    with pytest.raises(ValueError, match='SAVE_SNAPSHOT_CHANGED'):
        saves.reconcile_fork(source['session_id'], 'auto:0', operation_id='check-markers')


def test_reconcile_point_reads_original_none_count_receipt_without_writes_or_gate(tmp_path):
    service = GameService(tmp_path)
    source = service.start('fish')
    saves = SaveManager(service)
    directory = service.session_dir(source['session_id'])
    assert saves.reconcile_point(source['session_id'], 'Unknown', operation_id='no-create') is None
    assert not (directory / 'points.sqlite').exists()
    point = saves.create_point(source['session_id'], 'Keep current', operation_id='create-known')
    answer(service, source)
    points_before = (directory / 'points.sqlite').read_bytes()
    game_before = (directory / 'games.sqlite').read_bytes()
    with patch.object(service, '_save_model_gate', side_effect=AssertionError('A read receipt must not enter a write gate')):
        assert saves.reconcile_point(source['session_id'], 'Keep current', operation_id='create-known') == point
    assert point['choice_count'] == 0
    assert (directory / 'points.sqlite').read_bytes() == points_before
    assert (directory / 'games.sqlite').read_bytes() == game_before
    with pytest.raises(ValueError, match='OPERATION_CONFLICT'):
        saves.reconcile_point(source['session_id'], 'Keep current', choice_count=0, operation_id='create-known')


def test_reconcile_point_checks_frozen_snapshot_hash(tmp_path):
    service = GameService(tmp_path)
    source = service.start('fish')
    saves = SaveManager(service)
    point = saves.create_point(source['session_id'], 'Point', operation_id='check-point')
    with saves._db(source['session_id']) as db:
        snapshot = json.loads(db.execute('SELECT snapshot FROM points WHERE id=?', (point['id'],)).fetchone()[0])
        snapshot['meta']['player_id'] = 'Accidental edit'
        db.execute('UPDATE points SET snapshot=? WHERE id=?', (json.dumps(snapshot), point['id']))
    with pytest.raises(ValueError, match='SAVE_SNAPSHOT_CHANGED'):
        saves.reconcile_point(source['session_id'], 'Point', operation_id='check-point')

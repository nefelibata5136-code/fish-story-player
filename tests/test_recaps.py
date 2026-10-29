"""Authored recap boundaries, role isolation and historical branch inheritance."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import threading

import pytest

from fish_story.recaps import RecapStore
from fish_story.service import GameService, read_json, write_json


def game(tmp_path, style='self_aware', enabled=True):
    service = GameService(tmp_path / 'private')
    paths = []
    for number, actor in enumerate(('Kara', 'Connor', 'Kara'), 1):
        path = tmp_path / f'chapter-{number}.json'
        write_json(path, {
            'chapter': {'id': f'original-recap-{number}', 'chapter_number': number, 'title': f'Chapter {number}', 'protagonist': actor},
            'system_prompt': {'content': ''}, 'state': {'initial': {}},
            'nodes': [{'id': 'choose', 'type': 'choice',
                       'player_facing': {'context': f'{actor}_PRIVATE_CHAPTER_{number}',
                                         'choices': [{'id': 'go', 'text': 'Continue'}]},
                       'system': {'ending_resolution': {'go': {'result': 'done'}}}}],
            'endings': {'done': {'title': f'Done {number}', 'narrative': f'{actor}_END_{number}'}},
            'campaign': {'cross_chapter_exports': [], 'summary_segments': []},
        })
        paths.append(str(path))
    story = service.import_story(paths, 'Original recap fixture')
    view = service.start('fish', story_id=story['id'], play_style=style)
    meta = service._meta(view['session_id'])
    if enabled:
        meta['recap_version'] = 1
    else:
        meta.pop('recap_version', None)
    write_json(service.session_dir(view['session_id']) / 'session.json', meta)
    return service, service.view(view['session_id']), RecapStore(service)


def choose(service, view):
    return service.choose(view['session_id'], view['current']['request_id'], 1)


def test_recaps_are_authored_exact_unicode_files_and_durable_idempotent_versions(tmp_path):
    service, view, recaps = game(tmp_path)
    sid = view['session_id']
    assert recaps.read(sid)['max_characters'] == 5000
    assert recaps.tasks(sid) == []
    assert not (service.session_dir(sid) / 'recaps.sqlite').exists()
    view = choose(service, view)
    task = recaps.tasks(sid)[0]
    assert task['chapter_number'] == 1 and task['actor'] == 'player'
    text = '鱼🐟\n' * 1666 + '鱼🐟'
    assert len(text) == 5000
    entry = recaps.update(sid, text, task_id=task['task_id'], operation_id='first')
    assert entry['characters'] == 5000
    assert Path(entry['file_path']).read_text(encoding='utf-8') == text
    assert Path(entry['latest_file_path']).read_text(encoding='utf-8') == text
    assert RecapStore(GameService(service.directory)).read(sid)['text'] == text
    assert recaps.update(sid, text, task_id=task['task_id'], operation_id='first') == entry
    assert len(recaps.entries(sid)) == 1 and recaps.tasks(sid) == []
    with pytest.raises(ValueError, match='OPERATION_CONFLICT'):
        recaps.update(sid, 'other', task_id=task['task_id'], operation_id='first')
    with pytest.raises(ValueError, match='RECAP_STALE_TASK'):
        recaps.update(sid, 'other', task_id=task['task_id'], operation_id='new')
    with pytest.raises(ValueError, match='RECAP_TOO_LONG'):
        recaps.update(sid, text + 'x', operation_id='over')
    assert recaps.read(sid)['text'] == text
    changed = recaps.update(sid, text + '🐟', max_characters=5001, operation_id='raise-limit', expected_revision=1)
    assert changed['characters'] == changed['max_characters'] == 5001
    assert recaps.read(sid)['revision'] == 2
    with pytest.raises(ValueError, match='RECAP_STALE_REVISION'):
        recaps.update(sid, 'stale replacement', expected_revision=1)
    for limit in (0, -1, True, 1_000_001):
        with pytest.raises(ValueError, match='INVALID_RECAP_LIMIT'):
            recaps.update(sid, 'valid', max_characters=limit)


def test_task_view_hides_upcoming_material_even_nested_in_choice_receipts(tmp_path):
    service, view, recaps = game(tmp_path)
    view = choose(service, view)
    sid = view['session_id']
    task = recaps.tasks(sid)[0]
    assert 'Connor_PRIVATE_CHAPTER_2' in json.dumps(service.observe(sid))
    bounded = recaps.task_view(sid, task['task_id'])
    assert bounded['current'] is None
    assert 'Kara_PRIVATE_CHAPTER_1' in json.dumps(bounded)
    assert 'Connor_PRIVATE_CHAPTER_2' not in json.dumps(bounded)
    assert len(bounded['history_event_indices']) == len(bounded['history'])
    assert bounded['history_event_indices'][-1] == task['end_event_index']
    recaps.update(sid, 'My own first chapter recap', task_id=task['task_id'])
    assert recaps.task_view(sid, task['task_id'])['chapter_number'] == 1


def test_immersive_recaps_are_separate_and_old_task_view_never_sees_later_role(tmp_path):
    service, view, recaps = game(tmp_path, style='immersive')
    view = choose(service, view)
    sid = view['session_id']
    first = recaps.tasks(sid)[0]
    assert recaps.read(sid)['actor'] == 'Kara'
    recaps.update(sid, 'KARA_PRIVATE_RECAP', task_id=first['task_id'])
    view = choose(service, view)
    second = recaps.tasks(sid)[0]
    assert second['actor'] == 'Connor'
    bounded = recaps.task_view(sid, second['task_id'])
    assert bounded['perspective']['controlled_characters'] == ['Connor']
    assert 'Connor_PRIVATE_CHAPTER_2' in json.dumps(bounded)
    assert 'Kara_PRIVATE_CHAPTER_1' not in json.dumps(bounded)
    assert 'Kara_PRIVATE_CHAPTER_3' not in json.dumps(bounded)
    assert bounded['previous_recap']['text'] == ''
    recaps.update(sid, 'CONNOR_PRIVATE_RECAP', task_id=second['task_id'])
    assert recaps.read(sid, actor='Kara')['text'] == 'KARA_PRIVATE_RECAP'
    assert recaps.read(sid, actor='Connor')['text'] == 'CONNOR_PRIVATE_RECAP'
    old = recaps.task_view(sid, first['task_id'])
    assert 'CONNOR_PRIVATE_RECAP' not in json.dumps(old)
    assert 'Connor_PRIVATE_CHAPTER_2' not in json.dumps(old)


def test_named_and_automatic_branches_keep_only_recap_versions_authored_at_that_progress(tmp_path):
    service, view, recaps = game(tmp_path)
    view = choose(service, view)
    sid = view['session_id']
    recaps.update(sid, 'FIRST_ONLY', operation_id='first')
    point = service.save_point(sid, 'First chapter recap')
    view = choose(service, view)
    recaps.update(sid, 'SECOND_FUTURE_SENTINEL', operation_id='second')
    original = recaps.entries(sid)
    branch = service.load_save_point(sid, point['id'])
    target = branch['session_id']
    assert recaps.read(target)['text'] == 'FIRST_ONLY'
    assert recaps.tasks(target) == []
    assert 'SECOND_FUTURE_SENTINEL' not in json.dumps(recaps.entries(target))
    assert Path(recaps.read(target)['file_path']).read_text(encoding='utf-8') == 'FIRST_ONLY'
    assert recaps.entries(sid) == original
    assert service.view(sid)['accepted_choices'] == 2
    start = service.load_save_point(sid, 'auto:0')
    assert recaps.entries(start['session_id']) == []


def test_late_authored_old_task_cannot_leak_hindsight_into_historical_branch(tmp_path):
    service, view, recaps = game(tmp_path)
    view = choose(service, view)
    sid = view['session_id']
    first = recaps.tasks(sid)[0]
    view = choose(service, view)  # Internal engine call intentionally bypasses the public recap gate.
    entry = recaps.update(sid, 'LATER_HINDSIGHT_SENTINEL', task_id=first['task_id'])
    assert entry['task_choice_count'] == 1
    assert entry['authored_choice_count'] == entry['choice_count'] == 2
    branch = service.load_save_point(sid, 'auto:1')
    assert recaps.entries(branch['session_id']) == []
    assert recaps.read(branch['session_id'])['text'] == ''
    assert recaps.tasks(branch['session_id'])[0]['chapter_number'] == 1


def test_legacy_read_has_no_pending_tasks_or_files(tmp_path):
    service, view, recaps = game(tmp_path, enabled=False)
    view = choose(service, view)
    sid = view['session_id']
    assert recaps.tasks(sid) == []
    assert recaps.read(sid)['text'] == ''
    assert not (service.session_dir(sid) / 'recaps.sqlite').exists()


def test_concurrent_same_task_is_not_written_twice(tmp_path):
    service, view, recaps = game(tmp_path)
    view = choose(service, view)
    sid = view['session_id']
    task = recaps.tasks(sid)[0]
    barrier = threading.Barrier(2)

    def submit(index):
        barrier.wait()
        try:
            return recaps.update(sid, f'Author {index}', task_id=task['task_id'], operation_id=f'concurrent-{index}')
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, (1, 2)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert len(recaps.entries(sid)) == 1
    assert any(result in ('RECAP_BUSY', 'RECAP_STALE_TASK') for result in results if isinstance(result, str))


@pytest.mark.parametrize('mutation', ['edit', 'delete'])
def test_changed_immutable_recap_fails_closed_on_read_and_historical_snapshot(tmp_path, mutation):
    service, view, recaps = game(tmp_path)
    view = choose(service, view)
    sid = view['session_id']
    entry = recaps.update(sid, 'Original authored text')
    path = Path(entry['file_path'])
    if mutation == 'edit':
        path.write_text('External change must not become accepted text', encoding='utf-8')
    else:
        path.unlink()
    for operation in (lambda: recaps.read(sid), lambda: recaps.entries(sid), lambda: recaps.snapshot(sid, 1)):
        with pytest.raises(ValueError, match='RECAP_STORAGE_CHANGED'):
            operation()
    assert not path.exists() if mutation == 'delete' else path.read_text(encoding='utf-8').startswith('External change')

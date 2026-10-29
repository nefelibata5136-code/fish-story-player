import hashlib
import json

import pytest

from fish_story.engine import Store
from fish_story.service import GameService, write_json
from fish_story.styles import Attribution, content_hash


def chapter(number, actor, scene):
    return {'chapter': {'id': f'c{number}', 'chapter_number': number, 'title': f'Chapter {number}', 'protagonist': actor},
            'system_prompt': {'content': 'HIDDEN_ROLE_PROMPT'}, 'state': {'initial': {}},
            'nodes': [{'id': f'node{number}', 'type': 'choice',
                       'player_facing': {'context': scene, 'choices': [{'id': 'next', 'text': 'Continue'}]},
                       'system': {'ending_resolution': {'next': {'result': f'ending_{number}'}}}}],
            'endings': {f'ending_{number}': {'title': f'Result {number}', 'narrative': f'{actor} visible result {number}'}}}


def imported(service, tmp_path, docs):
    paths = []
    for n, doc in enumerate(docs):
        path = tmp_path / f'chapter{n}.json'
        path.write_text(json.dumps(doc), encoding='utf-8')
        paths.append(str(path))
    return service.import_story(paths, 'Synthetic perspective test')['id']


def choose(service, view):
    return service.choose(view['session_id'], view['current']['request_id'], 1, 'Public choice')


def test_two_styles_player_vs_full_observer_and_receipt_persistence(tmp_path):
    service = GameService(tmp_path / 'home')
    story = imported(service, tmp_path, [chapter(1, 'A', 'A_PRIVATE'), chapter(2, 'B', 'B_PRIVATE'), chapter(3, 'A', 'A_RETURN')])
    a = service.start('fish', story, play_style='immersive')
    sid = a['session_id']
    assert a['play_style_label'] == '角色沉浸' and a['perspective']['controlled_characters'] == ['A']
    b = choose(service, a)
    assert b['perspective']['controlled_characters'] == ['B']
    assert 'A_PRIVATE' not in json.dumps(b)
    back = choose(service, b)
    assert back['perspective']['controlled_characters'] == ['A']
    assert 'B_PRIVATE' not in json.dumps(back)
    assert 'A_PRIVATE' in json.dumps(back) and 'A_RETURN' in json.dumps(back)
    observer = service.observe(sid)
    assert 'A_PRIVATE' in json.dumps(observer) and 'B_PRIVATE' in json.dumps(observer)
    # A's receipt contains a transition into B in the complete evidence, but that
    # outcome must not leak through A's filtered records/export when A returns.
    assert 'B_PRIVATE' in json.dumps(observer['records'][0]['outcome'])
    assert 'B_PRIVATE' not in json.dumps(back['records'][0]['outcome'])
    assert back['records'][0]['source_content_hash'] == observer['records'][0]['content_hash']
    for record in observer['records'] + back['records']:
        assert content_hash(record) == record['content_hash']
    with service._store(sid).connect() as db:
        run = service._store(sid).load(db, 'player')
    assert all(answer['receipt']['play_style'] == 'immersive' for answer in run['answers'])
    assert GameService(tmp_path / 'home').view(sid) == back
    assert 'B_PRIVATE' not in json.dumps(service.export(sid))
    assert 'B_PRIVATE' in service.export(sid, 'markdown', audience='observer')
    assert '角色沉浸' in service.export(sid, 'memory')
    final = choose(service, back)
    assert final['status'] == 'complete' and 'B_PRIVATE' not in json.dumps(final)
    selfaware = service.start('fish', story, play_style='self_aware')
    selfaware = choose(service, selfaware)
    assert 'A_PRIVATE' in json.dumps(selfaware) and 'B_PRIVATE' in json.dumps(selfaware)
    assert selfaware['play_style_label'] == '自知玩家'


def test_unknown_multi_character_cannot_choose_or_dump_history(tmp_path):
    service = GameService(tmp_path / 'home')
    doc = chapter(1, ['A', 'B'], 'A and B are mentioned without a perspective heading.')
    story = imported(service, tmp_path, [doc])
    view = service.start('fish', story, play_style='immersive')
    assert view['perspective']['unavailable'] and not view['history']
    before = (service.session_dir(view['session_id']) / 'games.sqlite').read_bytes()
    with pytest.raises(ValueError, match='ROLE_PERSPECTIVE_UNAVAILABLE'):
        choose(service, view)
    assert (service.session_dir(view['session_id']) / 'games.sqlite').read_bytes() == before
    assert 'mentioned' in json.dumps(service.observe(view['session_id']))
    aware = service.start('fish', story, play_style='self_aware')
    assert choose(service, aware)['status'] == 'complete'


@pytest.mark.parametrize(('scene', 'expected'), [
    ('当前角色：A\nVisible facts', 'A'),
    ('【A视角】\nVisible facts', 'A'),
    ('【A视角——Substitute】\nVisible facts', 'Substitute'),
    ('A says 当前角色：B in dialogue.', None),
    ('Introductory narrative\n当前角色：B', None),
])
def test_explicit_heading_only_uses_the_resolved_current_context(tmp_path, scene, expected):
    service = GameService(tmp_path / 'home')
    doc = chapter(1, ['A', 'B'], scene)
    story = imported(service, tmp_path, [doc])
    view = service.start('fish', story, play_style='immersive')
    assert view['perspective']['controlled_characters'] == ([expected] if expected else [])


def test_multi_character_ending_unattributed_is_observer_only(tmp_path):
    service = GameService(tmp_path / 'home')
    doc = chapter(1, ['A', 'B'], '当前角色：A\nA visible scene')
    doc['endings']['ending_1']['narrative'] = 'UNATTRIBUTED_ENDING_SECRET'
    story = imported(service, tmp_path, [doc])
    view = choose(service, service.start('fish', story, play_style='immersive'))
    assert view['status'] == 'complete'
    assert 'UNATTRIBUTED_ENDING_SECRET' not in json.dumps(view)
    assert 'UNATTRIBUTED_ENDING_SECRET' in json.dumps(service.observe(view['session_id']))


def test_explicit_node_and_ending_metadata(tmp_path):
    service = GameService(tmp_path / 'home')
    doc = chapter(1, ['A', 'B'], 'Scene without a role heading')
    doc['nodes'][0]['player_facing']['perspective'] = 'B'
    doc['endings']['ending_1']['player_perspective'] = 'B'
    story = imported(service, tmp_path, [doc])
    view = service.start('fish', story, play_style='immersive')
    assert view['perspective']['controlled_characters'] == ['B']
    final = choose(service, view)
    assert any(e['type'] == 'chapter_end' for e in final['history'])


def test_v010_legacy_save_preserves_fingerprint_and_receipts(tmp_path):
    service = GameService(tmp_path / 'home')
    view = service.start('legacy-setup', story_id='demo')
    directory = service.session_dir(view['session_id'])
    meta = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
    meta.pop('play_style'); meta.pop('play_style_version')
    write_json(directory / 'session.json', meta)
    original = Store(directory).view('player')
    legacy = service.view(view['session_id'])
    assert legacy['play_style'] == 'legacy_unspecified'
    assert legacy['history'] == original['history']
    next_view = choose(service, legacy)
    assert 'play_style' not in next_view['records'][0]
    assert service.export(view['session_id'])['play_style_label'] == '旧存档 · 未声明玩法'


def test_invalid_style_does_not_create_session(tmp_path):
    service = GameService(tmp_path)
    with pytest.raises(ValueError, match='INVALID_PLAY_STYLE'):
        service.start('fish', story_id='demo', play_style='become-character-forever')
    assert not service.sessions()


def test_accepted_receipt_is_idempotent_after_transition_to_unknown_actor(tmp_path):
    service = GameService(tmp_path / 'home')
    story = imported(service, tmp_path, [chapter(1, 'A', 'A_SCENE'), chapter(2, ['A', 'B'], 'Unattributed scene')])
    initial = service.start('fish', story, play_style='immersive')
    current = initial['current']
    after = choose(service, initial)
    assert after['accepted_choices'] == 1 and after['perspective']['unavailable']
    assert service.choose(initial['session_id'], current['request_id'], 1, 'Public choice') == after
    with pytest.raises(ValueError, match='ROLE_PERSPECTIVE_UNAVAILABLE'):
        choose(service, after)


def test_identical_ending_text_with_conflicting_actors_is_not_assigned(tmp_path):
    service = GameService(tmp_path / 'home')
    doc = chapter(1, ['A', 'B'], '当前角色：A\nVisible scene')
    doc['endings']['ending_1'].update(player_perspective='A', narrative='SAME_ENDING_TEXT')
    doc['endings']['unreached'] = {**doc['endings']['ending_1'], 'player_perspective': 'B'}
    story = imported(service, tmp_path, [doc])
    final = choose(service, service.start('fish', story, play_style='immersive'))
    assert 'SAME_ENDING_TEXT' not in json.dumps(final)
    assert 'SAME_ENDING_TEXT' in json.dumps(service.observe(final['session_id']))


@pytest.mark.parametrize(('declared', 'scene'), [('missing-person', 'Plain scene'), ('A', '当前角色：B\nContradiction')])
def test_invalid_or_conflicting_explicit_role_does_not_silently_fall_back(tmp_path, declared, scene):
    service = GameService(tmp_path / 'home')
    doc = chapter(1, ['A', 'B'], scene)
    doc['nodes'][0]['player_facing']['perspective'] = declared
    story = imported(service, tmp_path, [doc])
    view = service.start('fish', story, play_style='immersive')
    assert view['perspective']['unavailable']
    with pytest.raises(ValueError, match='ROLE_PERSPECTIVE_UNAVAILABLE'):
        choose(service, view)

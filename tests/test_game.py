import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from fish_story.service import GameService, PACKAGE


def play(service, view, first=1):
    while view['status'] == 'waiting':
        current = view['current']
        view = service.choose(view['session_id'], current['request_id'], first, 'A public explanation')
    return view


def synthetic(path):
    doc = {
        '_meta': {'language': 'en'}, 'chapter': {'id': 'test', 'chapter_number': 1, 'title': 'Present'},
        'system_prompt': {'content': 'HIDDEN_ROLE_NEVER_FORWARD'},
        'state': {'initial': {'HIDDEN_SCORE': 0}},
        'nodes': [
            {'id': 'HIDDEN_NODE', 'type': 'choice', 'player_facing': {'context': 'Visible now', 'choices': [
                {'id': 'HIDDEN_CHOICE', 'text': 'Try'}, {'id': 'HIDDEN_OTHER', 'text': 'Wait'}]},
             'system': {'effects': {'HIDDEN_CHOICE': {'HIDDEN_SCORE': 5}}, 'resolution_rule': {'HIDDEN_CHOICE': {
                 'experienced': {'probability_success': 0.5, 'success': 'ok', 'failure': 'bad'}}}}},
            {'id': 'later', 'type': 'choice', 'player_facing': {'context': 'FUTURE_SECRET', 'choices': [
                {'id': 'finish', 'text': 'Finish'}]}, 'system': {'ending_resolution': {'finish': {'result': 'ending_a'}}}}
        ], 'endings': {'ending_a': {'title': 'A visible result', 'narrative': 'What actually happened', 'tier': 'HIDDEN_TIER'}}}
    path.write_text(json.dumps(doc), encoding='utf-8')
    return path


def test_demo_complete_results_and_reboot(tmp_path):
    service = GameService(tmp_path)
    view = service.start('fish-A')
    sid = view['session_id']
    view = play(service, view)
    assert view['status'] == 'complete'
    assert view['accepted_choices'] == 4
    assert len(view['records']) == 4
    assert GameService(tmp_path).view(sid) == view
    assert any('管理员陪' in e.get('context', '') for e in view['history'])  # cross-chapter export
    for record in view['records']:
        hashed = {k: v for k, v in record.items() if k != 'content_hash'}
        assert record['content_hash'] == hashlib.sha256(json.dumps(hashed, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        assert record['choice_text'] == record['visible_options'][record['choice'] - 1]['text']
        assert record['outcome']
        assert record['occurred_at'] == record['observed_at']
    markdown = service.export(sid, 'markdown')
    for e in view['history']:
        if e['type'] == 'node_shown':
            assert e['context'] in markdown
        elif e['type'] == 'chapter_end':
            assert e['ending']['narrative'] in markdown
    memory = service.export(sid, 'memory')
    assert '尚未成为玩家认可' in memory and '虚构' in memory
    assert all(r['choice_text'] in memory for r in view['records'])


def test_invalid_duplicate_and_cross_player_isolation(tmp_path):
    service = GameService(tmp_path)
    a, b = service.start('A'), service.start('B')
    sid, rid = a['session_id'], a['current']['request_id']
    db = service.session_dir(sid) / 'games.sqlite'
    before = db.read_bytes()
    for invalid in (0, 999, True, '1', None):
        with pytest.raises(ValueError):
            service.choose(sid, rid, invalid)
        assert db.read_bytes() == before
        assert service.view(sid) == a
    with pytest.raises(ValueError, match='STALE_REQUEST'):
        service.choose(b['session_id'], rid, 1)
    accepted = service.choose(sid, rid, 1, '')
    assert service.choose(sid, rid, 1, '') == accepted
    with pytest.raises(ValueError, match='ANSWER_ALREADY_ACCEPTED'):
        service.choose(sid, rid, 2, '')
    assert service.view(b['session_id']) == b
    c = service.start('A')
    assert c['session_id'] != sid and c['accepted_choices'] == 0


def test_pause_resume_persist_and_original_receipt(tmp_path):
    s = GameService(tmp_path)
    v = s.start('pause')
    sid, c = v['session_id'], v['current']
    paused = s.pause(sid)
    assert GameService(tmp_path).view(sid)['status'] == 'paused'
    with pytest.raises(ValueError, match='GAME_PAUSED'):
        s.choose(sid, c['request_id'], 1)
    s.resume(sid)
    v = s.choose(sid, c['request_id'], 1)
    s.pause(sid)
    assert s.choose(sid, c['request_id'], 1)['accepted_choices'] == 1
    assert paused['current'] == c


def test_blind_native_replay_and_internal_result(tmp_path):
    source = synthetic(tmp_path / 'test.json')
    s = GameService(tmp_path / 'home')
    story = s.import_story([str(source)], 'Local synthetic')
    v = s.start('private', story['id'], difficulty='experienced')
    initial = json.dumps(v)
    assert 'HIDDEN_' not in initial and 'FUTURE_SECRET' not in initial
    c = v['current']
    v = s.choose(v['session_id'], c['request_id'], 1, 'chosen')
    assert 'FUTURE_SECRET' in json.dumps(v) and 'HIDDEN_' not in json.dumps(v)
    r = v['records'][0]
    assert r['outcome'][0]['context'] == v['current']['context']
    with s._store(v['session_id']).connect() as db:
        run = s._store(v['session_id']).load(db, 'player')
    assert 'HIDDEN_SCORE' in run['answers'][0]['internal_outcome']['state_after']
    final = play(s, v)
    assert 'HIDDEN_' not in json.dumps(s.export(final['session_id']))
    assert 'What actually happened' in s.export(final['session_id'], 'markdown')


def test_import_snapshot_and_tamper_refusal(tmp_path):
    source = synthetic(tmp_path / 'test.json')
    s = GameService(tmp_path / 'home')
    story = s.import_story([str(source)], 'Local')
    v = s.start('A', story['id'])
    source.write_text('{}', encoding='utf-8')
    assert s.view(v['session_id']) == v
    pinned = next((s.session_dir(v['session_id']) / 'story').glob('*.json'))
    pinned.write_text(pinned.read_text(encoding='utf-8') + ' ', encoding='utf-8')
    with pytest.raises(ValueError, match='ENGINE_CHANGED'):
        s.view(v['session_id'])


def test_export_privacy_and_unknown_story_rights(tmp_path):
    s = GameService(tmp_path / 'home')
    a = s.start('PRIVATE_PLAYER')
    a = s.choose(a['session_id'], a['current']['request_id'], 1, 'PRIVATE_EXPLANATION')
    private = json.dumps(s.export(a['session_id']), ensure_ascii=False)
    assert 'PRIVATE_EXPLANATION' in private
    shared = json.dumps(s.export(a['session_id'], share=True), ensure_ascii=False)
    assert 'PRIVATE_PLAYER' not in shared and 'PRIVATE_EXPLANATION' not in shared
    assert str(s.directory) not in shared and a['session_id'] not in shared
    imported = s.import_story([str(synthetic(tmp_path / 'story.json'))], 'Private')
    b = s.start('B', imported['id'])
    with pytest.raises(ValueError, match='SHARE_REQUIRES_STORY_RIGHTS'):
        s.export(b['session_id'], share=True)
    for invalid in ('../secret', '..\\secret', None):
        with pytest.raises(ValueError, match='INVALID_SESSION_ID'):
            s.view(invalid)


def test_lock_and_evidence_export_idempotency(tmp_path):
    s = GameService(tmp_path / 'home')
    v = s.start('A')
    sid = v['session_id']
    with s._store(sid).connect() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError):
            s.choose(sid, v['current']['request_id'], 1)
    assert s.view(sid)['accepted_choices'] == 0
    v = play(s, s.view(sid))
    out = tmp_path / 'evidence'
    one, two = s.export_evidence(sid, out), s.export_evidence(sid, out)
    assert one == two and one['count'] == 4
    lines = []
    for f in one['files']:
        raw = (out / one['snapshot_id'] / f['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == f['sha256']
        lines.extend(json.loads(line) for line in raw.decode().splitlines())
    assert len(lines) == len({r['id'] for r in lines}) == 4
    assert all(r['privacy'] == 'local_private_unreviewed' for r in lines)


def test_start_chapter_does_not_invent_prior_choices(tmp_path):
    s = GameService(tmp_path)
    v = s.start('A', chapter=2)
    assert v['accepted_choices'] == 0
    assert 'fresh initial state' in v['prior_chapters']
    assert '没有继承此前的选择' in v['current']['context']

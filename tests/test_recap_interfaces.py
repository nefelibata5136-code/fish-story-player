import asyncio
import json
from pathlib import Path

import pytest

from fish_story.mcp_server import build_server
from fish_story.service import GameService


def chapter_boundary(tmp_path):
    service = GameService(tmp_path / 'private')
    game = service.start('fish', story_id='demo')
    chapter = game['current']['chapter']['chapter_number']
    while game['current']['chapter']['chapter_number'] == chapter:
        game = service.choose(game['session_id'], game['current']['request_id'], 1)
    return service, game


def test_mcp_requires_own_recap_before_next_chapter_and_does_not_leak_upcoming_scene(tmp_path):
    service, raw = chapter_boundary(tmp_path)
    session, upcoming = raw['session_id'], raw['current']['context']
    server = build_server(service, 'fish')

    async def call(name, args):
        result = await server.call_tool(name, args)
        return json.loads(result[0].text)

    async def exercise():
        gated = await call('game_view', {'session_id': session})
        assert gated['status'] == 'recap_required' and gated['current'] is None
        task = gated['recap']['pending_tasks'][0]
        for name in ('game_view', 'game_choices', 'game_history'):
            assert upcoming not in json.dumps(await call(name, {'session_id': session}), ensure_ascii=False)
        with pytest.raises(Exception, match='RECAP_UPDATE_REQUIRED'):
            await call('game_choose', {'session_id': session, 'request_id': raw['current']['request_id'], 'choice': 1})
        with pytest.raises(Exception, match='RECAP_UPDATE_REQUIRED'):
            await call('game_export', {'session_id': session})
        material = await call('game_recap_read', {'session_id': session, 'task_id': task['task_id']})
        assert material['max_characters'] == 5000
        assert upcoming not in json.dumps(material, ensure_ascii=False)
        with pytest.raises(Exception, match='RECAP_TOO_LONG'):
            await call('game_recap_update', {'session_id': session, 'task_id': task['task_id'], 'text': '字' * 5001})
        saved = await call('game_recap_update', {'session_id': session, 'task_id': task['task_id'],
            'text': '字' * 5500, 'max_characters': 6000, 'operation_id': 'my-own-recap'})
        assert saved['recap']['characters'] == 5500
        assert Path(saved['recap']['file_path']).read_text(encoding='utf-8') == '字' * 5500
        restored = await call('game_view', {'session_id': session})
        assert restored['current']['context'] == upcoming and restored['recap']['text'] == '字' * 5500
    asyncio.run(exercise())


def test_cli_also_gates_without_compact_flag_and_accepts_authored_file(tmp_path, capsys):
    from fish_story.cli import main
    service, raw = chapter_boundary(tmp_path)
    args = ['--home', str(service.directory)]
    assert main(args + ['view', raw['session_id']]) == 0
    gated = json.loads(capsys.readouterr().out)
    assert gated['status'] == 'recap_required'
    own = tmp_path / 'my-recap.md'
    own.write_text('这是玩家自己整理的前情。', encoding='utf-8')
    task = gated['recap']['pending_tasks'][0]['task_id']
    assert main(args + ['recap-update', raw['session_id'], '--task-id', task, '--text-file', str(own)]) == 0
    assert json.loads(capsys.readouterr().out)['text'] == own.read_text(encoding='utf-8')

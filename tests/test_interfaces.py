"""Real local HTTP / terminal / official MCP adapter checks; no paid API."""
import asyncio
import json
import os
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from fish_story.server import make_server


class FixtureService:
    def __init__(self, directory):
        self.directory = directory
        self.current = {'session_id': 'one', 'player_id': 'fish-one', 'status': 'waiting', 'mode': 'agent',
                        'current': {'request_id': 'r1', 'context': 'Visible scene', 'chapter': {'title': 'Demo'},
                                    'choices': [{'number': 1, 'text': 'Visible option'}]}, 'history': [], 'accepted_choices': 0}
        self.started = []

    def stories(self): return [{'id': 'demo', 'title': 'Demo', 'chapters': [{'chapter_number': 1, 'title': 'One'}]}]
    def sessions(self): return [self.current]
    def view(self, sid):
        if sid != 'one': raise ValueError('NO_GAME')
        return self.current
    def _meta(self, sid):
        if sid != 'one': raise ValueError('NO_SESSION')
        return {'player_id': self.current['player_id']}
    def start(self, **kwargs): self.started.append(kwargs); return self.current
    def choose(self, sid, request_id, choice, reason=''):
        if request_id != 'r1' or choice != 1: raise ValueError('CHOICE_NOT_AVAILABLE')
        self.current = {**self.current, 'accepted_choices': 1}
        return self.current
    def pause(self, sid): self.current = {**self.current, 'status': 'paused'}; return self.current
    def resume(self, sid): self.current = {**self.current, 'status': 'waiting'}; return self.current
    def export(self, sid, format='json', share=False): return {'format': format, 'share': share}
    def session_dir(self, sid): return self.directory


@pytest.fixture
def running(tmp_path):
    service = FixtureService(tmp_path)
    (tmp_path / 'core.txt').write_text('PRIVATE_CORE_SENTINEL', encoding='utf-8')
    server = make_server(service, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}', service
    server.shutdown(); server.server_close(); thread.join()


def send(base, path, payload=None, headers=None):
    headers = headers or {}
    if payload is not None:
        headers = {'Content-Type': 'application/json', **headers}
    request = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
    with urlopen(request) as response:
        return json.load(response)


def test_http_real_flow_and_security(running):
    base, service = running
    boot = send(base, '/api/bootstrap')
    assert boot['stories'][0]['id'] == 'demo'
    token = boot['csrf']
    with pytest.raises(HTTPError) as denied:
        send(base, '/api/new', {'player_id': 'fish-one'})
    assert denied.value.code == 403
    assert service.started == []
    for headers in ({'Origin': 'https://attacker.invalid'}, {'Host': 'attacker.invalid'}, {'Origin': 'null'}):
        with pytest.raises(HTTPError) as denied:
            send(base, '/api/core?session_id=one', headers=headers)
        assert denied.value.code == 403
        assert b'PRIVATE_CORE_SENTINEL' not in denied.value.read()
    created = send(base, '/api/new', {'player_id': 'fish-one'}, {'X-Fish-CSRF': token})
    assert created['accepted_choices'] == 0
    chosen = send(base, '/api/choose', {'session_id': 'one', 'request_id': 'r1', 'choice': 1}, {'X-Fish-CSRF': token})
    assert chosen['accepted_choices'] == 1
    paused = send(base, '/api/pause', {'session_id': 'one'}, {'X-Fish-CSRF': token})
    assert paused['status'] == 'paused'
    resumed = send(base, '/api/resume', {'session_id': 'one'}, {'X-Fish-CSRF': token})
    assert resumed['status'] == 'waiting'
    assert send(base, '/api/export?session_id=one&format=memory&share=1')['result'] == {'format': 'memory', 'share': True}
    assert 'PRIVATE_CORE_SENTINEL' not in json.dumps(send(base, '/api/view?session_id=one'))


def test_bad_json_does_not_mutate_or_echo(running):
    base, service = running
    token = send(base, '/api/bootstrap')['csrf']
    request = Request(base + '/api/new', data=b'{"private":"PRIVATE_SENTINEL",broken',
                      headers={'Content-Type': 'application/json', 'X-Fish-CSRF': token})
    with pytest.raises(HTTPError) as denied:
        urlopen(request)
    assert b'PRIVATE_SENTINEL' not in denied.value.read()
    assert service.started == []


def test_web_asset_is_self_contained_and_safe(running):
    base, _ = running
    with urlopen(base) as response:
        html = response.read().decode('utf-8')
        assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert 'Georgia' not in html
    assert '.innerHTML' not in html
    assert 'devicePixelRatio' not in html
    assert 'api-key' not in html
    assert '核心资料' in html and '记忆候选' in html


def test_official_mcp_tools_bind_player_and_never_call_model(tmp_path):
    pytest.importorskip('mcp.server.fastmcp')
    from fish_story.mcp_server import build_server
    service = FixtureService(tmp_path)
    server = build_server(service, 'fish-one')

    async def exercise():
        tools = await server.list_tools()
        names = {tool.name for tool in tools}
        assert {'story_list', 'game_start', 'game_view', 'game_choose', 'game_history', 'game_pause', 'game_resume', 'game_export'} <= names
        result = await server.call_tool('game_view', {'session_id': 'one'})
        assert 'Visible scene' in str(result)
        await server.call_tool('game_choose', {'session_id': 'one', 'request_id': 'r1', 'choice': 1})
        assert service.current['accepted_choices'] == 1
        service.current['player_id'] = 'different-fish'
        with pytest.raises(Exception, match='SESSION_NOT_OWNED'):
            await server.call_tool('game_view', {'session_id': 'one'})
        with pytest.raises(Exception, match='SESSION_NOT_OWNED'):
            await server.call_tool('game_pause', {'session_id': 'one'})
        service.current['player_id'] = 'fish-one'
        def broken_view(sid):
            raise RuntimeError('HIDDEN_BRANCH condition=future_secret')
        service.view = broken_view
        with pytest.raises(Exception, match='OPERATION_FAILED_CHECK_LOCAL_SAVE') as denied:
            await server.call_tool('game_view', {'session_id': 'one'})
        assert 'future_secret' not in str(denied.value)
    asyncio.run(exercise())


def test_cli_expands_windows_glob_and_emits_utf8(tmp_path, monkeypatch, capsys):
    from fish_story import cli, service as service_module
    fixture = FixtureService(tmp_path)
    imported = []
    fixture.import_story = lambda paths, title: imported.extend(paths) or {'title': '演示'}
    monkeypatch.setattr(service_module, 'GameService', lambda directory: fixture)
    (tmp_path / 'ch02.json').write_text('{}', encoding='utf-8')
    (tmp_path / 'ch01.json').write_text('{}', encoding='utf-8')
    assert cli.main(['--home', str(tmp_path), 'import-story', str(tmp_path / 'ch*.json')]) == 0
    assert [__import__('pathlib').Path(p).name for p in imported] == ['ch01.json', 'ch02.json']
    assert '演示' in capsys.readouterr().out


def test_official_stdio_subprocess_full_agent_flow(tmp_path):
    pytest.importorskip('mcp')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from fish_story.service import GameService

    service = GameService(tmp_path / 'private-home')
    foreign = service.start('another-player')
    # No API credential is needed or inherited by the direct-play server process.
    env = {k: v for k, v in os.environ.items()
           if k.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'}}
    env.update(PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    params = StdioServerParameters(command=sys.executable,
                                  args=['-m', 'fish_story.cli', '--home', str(service.directory), 'mcp', '--player', 'stdio-player'],
                                  env=env)

    def data(result):
        assert not result.isError, str(result.content)
        if result.structuredContent is not None:
            return result.structuredContent
        return json.loads(next(c.text for c in result.content if c.type == 'text'))

    async def exercise():
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert 'game_choose' in {tool.name for tool in tools.tools}
                started = data(await session.call_tool('game_start', {}))
                sid = started['session_id']
                current = data(await session.call_tool('game_choices', {'session_id': sid}))['current']
                assert current['context'] and current['choices']
                rejected = await session.call_tool('game_choose', {'session_id': sid, 'request_id': current['request_id'], 'choice': 999})
                assert rejected.isError
                assert 'CHOICE_NOT_AVAILABLE' in str(rejected.content)
                assert data(await session.call_tool('game_view', {'session_id': sid}))['accepted_choices'] == 0
                accepted = data(await session.call_tool('game_choose', {'session_id': sid, 'request_id': current['request_id'],
                                                                         'choice': 1, 'reason': '公开的合成测试说明'}))
                assert accepted['accepted_choices'] == 1
                history = data(await session.call_tool('game_history', {'session_id': sid}))
                assert len([event for event in history['history'] if event['type'] == 'decision']) == 1
                assert history['records'][0]['choice'] == 1
                denied = await session.call_tool('game_view', {'session_id': foreign['session_id']})
                assert denied.isError
                assert 'SESSION_NOT_OWNED_BY_BOUND_PLAYER' in str(denied.content)
                assert foreign['current']['context'] not in str(denied.content)
    asyncio.run(exercise())

"""Real local HTTP / terminal / official MCP adapter checks; no paid API."""
import asyncio
import json
import os
import sys
import threading
import uuid
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
        self.points = []
        self.save_calls = []

    def stories(self): return [{'id': 'demo', 'title': 'Demo', 'chapters': [{'chapter_number': 1, 'title': 'One'}]}]
    def sessions(self): return [self.current]
    def view(self, sid):
        if sid != 'one': raise ValueError('NO_GAME')
        return self.current
    def observe(self, sid): return self.view(sid)
    def _meta(self, sid):
        if sid != 'one': raise ValueError('NO_SESSION')
        return {'player_id': self.current['player_id']}
    def start(self, **kwargs):
        self.started.append(kwargs)
        self.current = {**self.current, 'play_style': kwargs.get('play_style', 'self_aware'), 'save_name': kwargs.get('save_name')}
        return self.current
    def choose(self, sid, request_id, choice, reason=''):
        if request_id != 'r1' or choice != 1: raise ValueError('CHOICE_NOT_AVAILABLE')
        self.current = {**self.current, 'accepted_choices': 1}
        return self.current
    def pause(self, sid): self.current = {**self.current, 'status': 'paused'}; return self.current
    def resume(self, sid): self.current = {**self.current, 'status': 'waiting'}; return self.current
    def export(self, sid, format='json', share=False, audience='player'): return {'format': format, 'share': share, 'audience': audience}
    def session_dir(self, sid): return self.directory
    def save_points(self, sid, audience='player'):
        self.save_calls.append(('list', sid, audience))
        return {'session_id': sid, 'points': self.points}
    def save_point(self, sid, name, choice_count=None, operation_id=None, audience='player'):
        self.save_calls.append(('save', sid, name, choice_count, operation_id, audience))
        value = {'id': 'point-one', 'name': name, 'choice_count': choice_count or 0, 'kind': 'manual'}
        self.points.append(value)
        return value
    def load_save_point(self, sid, point_id, name=None, operation_id=None, audience='player'):
        self.save_calls.append(('load', sid, point_id, name, operation_id, audience))
        return self.current
    def rename_save(self, sid, name):
        self.current = {**self.current, 'save_name': name}
        return self.current
    def rename_save_point(self, sid, point_id, name, audience='player'):
        value = next(p for p in self.points if p['id'] == point_id)
        value['name'] = name
        return value


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
    created = send(base, '/api/new', {'player_id': 'fish-one', 'play_style': 'immersive'}, {'X-Fish-CSRF': token})
    assert created['accepted_choices'] == 0
    assert service.started[-1]['play_style'] == created['play_style'] == 'immersive'
    chosen = send(base, '/api/choose', {'session_id': 'one', 'request_id': 'r1', 'choice': 1}, {'X-Fish-CSRF': token})
    assert chosen['accepted_choices'] == 1
    paused = send(base, '/api/pause', {'session_id': 'one'}, {'X-Fish-CSRF': token})
    assert paused['status'] == 'paused'
    resumed = send(base, '/api/resume', {'session_id': 'one'}, {'X-Fish-CSRF': token})
    assert resumed['status'] == 'waiting'
    assert send(base, '/api/export?session_id=one&format=memory&share=1')['result'] == {'format': 'memory', 'share': True, 'audience': 'observer'}
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
    assert 'id="play-style"' in html and '角色沉浸' in html and '自知玩家' in html
    assert 'id="save-points"' in html and '原局和原选择保留' in html
    assert 'crypto.randomUUID()' in html and 'contextVersion' in html


def test_http_named_checkpoint_routes_are_explicit_human_operations(running):
    base, service = running
    token = send(base, '/api/bootstrap')['csrf']
    headers = {'X-Fish-CSRF': token}
    point = send(base, '/api/save-point', {'session_id': 'one', 'name': '决策前', 'choice_count': 0, 'operation_id': 'checkpoint-operation'}, headers)
    assert point['name'] == '决策前'
    assert service.save_calls[-1] == ('save', 'one', '决策前', 0, 'checkpoint-operation', 'observer')
    listed = send(base, '/api/save-points?session_id=one')
    assert listed['points'][0]['id'] == point['id']
    assert service.save_calls[-1] == ('list', 'one', 'observer')
    send(base, '/api/load-point', {'session_id': 'one', 'point_id': point['id'], 'name': '另一条路', 'operation_id': 'branch-operation'}, headers)
    assert service.save_calls[-1] == ('load', 'one', point['id'], '另一条路', 'branch-operation', 'observer')
    assert send(base, '/api/rename-save', {'session_id': 'one', 'name': '命名存档'}, headers)['save_name'] == '命名存档'
    assert send(base, '/api/rename-point', {'session_id': 'one', 'point_id': point['id'], 'name': '新名称'}, headers)['name'] == '新名称'


def test_http_human_observer_and_player_projection_are_separate(running):
    base, service = running
    original = service.view
    service.observe = lambda sid: {**original(sid), 'history': [{'type': 'node_shown', 'context': 'OBSERVER_ONLY_OTHER_ACTOR'}]}
    assert 'OBSERVER_ONLY_OTHER_ACTOR' in json.dumps(send(base, '/api/view?session_id=one'))
    assert 'OBSERVER_ONLY_OTHER_ACTOR' not in json.dumps(send(base, '/api/player-view?session_id=one'))
    token = send(base, '/api/bootstrap')['csrf']
    chosen = send(base, '/api/choose', {'session_id': 'one', 'request_id': 'r1', 'choice': 1}, {'X-Fish-CSRF': token})
    assert chosen['history'][0]['context'] == 'OBSERVER_ONLY_OTHER_ACTOR'


def test_cli_new_persists_explicit_play_style(tmp_path, monkeypatch, capsys):
    from fish_story import cli, service as service_module
    fixture = FixtureService(tmp_path)
    monkeypatch.setattr(service_module, 'GameService', lambda directory: fixture)
    assert cli.main(['--home', str(tmp_path), 'new', '--player', 'fish-one', '--play-style', 'immersive']) == 0
    assert fixture.started[-1]['play_style'] == 'immersive'
    assert json.loads(capsys.readouterr().out)['play_style'] == 'immersive'
    assert cli.main(['--home', str(tmp_path), 'export', 'one', '--format', 'json', '--observer']) == 0
    assert json.loads(capsys.readouterr().out)['audience'] == 'observer'


def test_cli_checkpoint_commands_preserve_player_default_and_operation_id(tmp_path, monkeypatch, capsys):
    from fish_story import cli, service as service_module
    fixture = FixtureService(tmp_path)
    monkeypatch.setattr(service_module, 'GameService', lambda directory: fixture)
    prefix = ['--home', str(tmp_path)]
    assert cli.main(prefix + ['save-point', 'one', '--name', 'Before', '--choice-count', '0', '--operation-id', 'fixed-op']) == 0
    assert json.loads(capsys.readouterr().out)['id'] == 'point-one'
    assert fixture.save_calls[-1] == ('save', 'one', 'Before', 0, 'fixed-op', 'player')
    assert cli.main(prefix + ['save-points', 'one']) == 0
    capsys.readouterr()
    assert fixture.save_calls[-1] == ('list', 'one', 'player')
    assert cli.main(prefix + ['load-point', 'one', 'point-one', '--name', 'Branch', '--operation-id', 'fork-op', '--observer']) == 0
    capsys.readouterr()
    assert fixture.save_calls[-1] == ('load', 'one', 'point-one', 'Branch', 'fork-op', 'observer')
    assert cli.main(prefix + ['rename-save', 'one', 'Renamed']) == 0
    assert json.loads(capsys.readouterr().out)['save_name'] == 'Renamed'


def test_official_mcp_tools_bind_player_and_never_call_model(tmp_path):
    pytest.importorskip('mcp.server.fastmcp')
    from fish_story.mcp_server import build_server
    service = FixtureService(tmp_path)
    server = build_server(service, 'fish-one')

    async def exercise():
        tools = await server.list_tools()
        names = {tool.name for tool in tools}
        assert {'story_list', 'game_start', 'game_view', 'game_choose', 'game_history', 'game_pause', 'game_resume', 'game_export',
                'game_saves', 'game_open', 'game_save_points', 'game_save_checkpoint', 'game_load_checkpoint', 'game_rename_save'} <= names
        start_schema = next(tool.inputSchema for tool in tools if tool.name == 'game_start')
        assert start_schema['properties']['play_style']['default'] == 'self_aware'
        assert start_schema['properties']['story_id']['default'] == 'detroit'
        result = await server.call_tool('game_view', {'session_id': 'one'})
        assert 'Visible scene' in str(result)
        service.observe = lambda sid: (_ for _ in ()).throw(RuntimeError('OBSERVER_MUST_NOT_BE_USED_BY_MCP'))
        exported = await server.call_tool('game_export', {'session_id': 'one'})
        assert 'player' in str(exported) and 'observer' not in str(exported)
        await server.call_tool('game_save_checkpoint', {'session_id': 'one', 'name': 'Before', 'operation_id': 'mcp-save'})
        assert service.save_calls[-1] == ('save', 'one', 'Before', None, 'mcp-save', 'player')
        await server.call_tool('game_load_checkpoint', {'session_id': 'one', 'point_id': 'point-one', 'operation_id': 'mcp-load'})
        assert service.save_calls[-1] == ('load', 'one', 'point-one', None, 'mcp-load', 'player')
        await server.call_tool('game_choose', {'session_id': 'one', 'request_id': 'r1', 'choice': 1})
        assert service.current['accepted_choices'] == 1
        service.current['player_id'] = 'different-fish'
        with pytest.raises(Exception, match='SESSION_NOT_OWNED'):
            await server.call_tool('game_view', {'session_id': 'one'})
        with pytest.raises(Exception, match='SESSION_NOT_OWNED'):
            await server.call_tool('game_pause', {'session_id': 'one'})
        with pytest.raises(Exception, match='SESSION_NOT_OWNED'):
            await server.call_tool('game_load_checkpoint', {'session_id': 'one', 'point_id': 'point-one'})
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
    foreign = service.start('another-player', story_id='demo')
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
                started = data(await session.call_tool('game_start', {'story_id': 'demo', 'play_style': 'immersive', 'save_name': '第一条路线'}))
                sid = started['session_id']
                assert started['play_style'] == 'immersive'
                assert service._meta(sid)['play_style'] == 'immersive'
                assert service._meta(sid)['save_name'] == '第一条路线'
                choice_result = data(await session.call_tool('game_choices', {'session_id': sid}))
                assert choice_result['play_style'] == 'immersive' and choice_result['perspective']
                current = choice_result['current']
                assert current['context'] and current['choices']
                point = data(await session.call_tool('game_save_checkpoint', {'session_id': sid, 'name': '选择之前', 'operation_id': str(uuid.uuid4())}))
                assert point['choice_count'] == 0
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
                branch = data(await session.call_tool('game_load_checkpoint', {'session_id': sid, 'point_id': point['id'],
                                                                                 'name': '另一种可能', 'operation_id': str(uuid.uuid4())}))
                assert branch['session_id'] != sid and branch['accepted_choices'] == 0
                assert service.view(sid)['accepted_choices'] == 1
                renamed = data(await session.call_tool('game_rename_save', {'session_id': branch['session_id'], 'name': '备用路线'}))
                assert renamed['save_name'] == '备用路线'
                points = data(await session.call_tool('game_save_points', {'session_id': sid}))
                assert any(p['id'] == point['id'] for p in points['points'])
                owned_saves = await session.call_tool('game_saves', {})
                assert not owned_saves.isError and '备用路线' in str(owned_saves)
                assert 'another-player' not in str(owned_saves)
                denied_load = await session.call_tool('game_load_checkpoint', {'session_id': foreign['session_id'], 'point_id': point['id']})
                assert denied_load.isError and 'SESSION_NOT_OWNED' in str(denied_load.content)
                denied = await session.call_tool('game_view', {'session_id': foreign['session_id']})
                assert denied.isError
                assert 'SESSION_NOT_OWNED_BY_BOUND_PLAYER' in str(denied.content)
                assert foreign['current']['context'] not in str(denied.content)
    asyncio.run(exercise())

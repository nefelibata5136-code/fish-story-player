"""Exercise quick setup through real local HTTP/CLI/MCP, without network or API."""
import asyncio
import copy
import io
import json
import sys
import threading
import types
import zipfile
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from fish_story.import_pack import MAX_ARCHIVE_BYTES, import_story_pack
from fish_story.server import make_server
from fish_story.service import GameService, PACKAGE, read_json


def synthetic_archive():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for number in (1, 2):
            doc = copy.deepcopy(read_json(PACKAGE / 'demo' / 'ch01_fog_letter.json'))
            doc['chapter']['chapter_number'] = number
            if number == 2:
                doc['nodes'][0]['player_facing']['context'] = 'UNSEEN_SECOND_CHAPTER_SENTINEL'
            archive.writestr(f'original-fixture/01_json/zh/ch{number:02}.json', json.dumps(doc, ensure_ascii=False))
    return stream.getvalue()


@pytest.fixture
def setup_source(monkeypatch):
    """Stub only the remote source acquisition; exercise the real private import."""
    module = types.ModuleType('fish_story.source')
    module.SOURCE_ID = 'synthetic-original-source'
    module.SOURCE_SHA256 = '0' * 64
    module.SOURCE_TITLE = 'Original synthetic source'
    calls = []
    installed = {}

    def source_info():
        return {'name': 'Original test source', 'license': 'CC0-1.0', 'requires_explicit_request': True}

    def acquire_detroit(service, accepted=False):
        if accepted is not True:
            raise ValueError('SOURCE_TERMS_REQUIRED')
        calls.append({'accepted': accepted, 'home': service.directory})
        key = str(service.directory)
        if key not in installed:
            installed[key] = import_story_pack(service, synthetic_archive(), title='原创测试来源')
        return installed[key]

    module.source_info = source_info
    module.acquire_detroit = acquire_detroit
    monkeypatch.setitem(sys.modules, 'fish_story.source', module)
    # Any accidentally added model call must fail this no-paid-API acceptance.
    from fish_story import model
    monkeypatch.setattr(model, 'IndependentPlayer', lambda *a, **k: pytest.fail('setup must not construct a model player'))
    return module, calls


@pytest.fixture
def quick_server(tmp_path, setup_source):
    service = GameService(tmp_path / 'private-home')
    previous = service.start('existing-player', story_id='demo', save_name='保留已有存档')
    request = previous['current']
    previous = service.choose(previous['session_id'], request['request_id'], 1, '已有真实选择')
    server = make_server(service, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}', service, copy.deepcopy(previous), setup_source[1]
    server.shutdown()
    server.server_close()
    thread.join()


def http(base, path, payload=None, *, raw=None, headers=None):
    headers = dict(headers or {})
    if payload is not None:
        raw = json.dumps(payload).encode('utf-8')
        headers.setdefault('Content-Type', 'application/json')
    with urlopen(Request(base + path, data=raw, headers=headers), timeout=5) as response:
        return json.load(response)


def assert_prior_save_untouched(service, previous):
    current = service.view(previous['session_id'])
    assert current == previous
    assert current['accepted_choices'] == 1
    assert current['save_name'] == '保留已有存档'


def test_bootstrap_source_metadata_and_page_do_not_acquire(quick_server):
    base, service, previous, calls = quick_server
    http(base, '/api/bootstrap')
    assert http(base, '/api/story-source')['requires_explicit_request'] is True
    with urlopen(base, timeout=5) as response:
        html = response.read().decode('utf-8')
    assert 'id="setup-detroit"' in html and 'id="quick-demo"' in html
    assert 'id="story-pack"' in html and 'application/zip' in html
    assert calls == []
    assert_prior_save_untouched(service, previous)


def test_source_setup_requires_same_origin_csrf_and_explicit_true(quick_server):
    base, service, previous, calls = quick_server
    csrf = http(base, '/api/bootstrap')['csrf']
    for extra in ({}, {'X-Fish-CSRF': 'wrong'}, {'X-Fish-CSRF': csrf, 'Origin': 'https://elsewhere.invalid'},
                  {'X-Fish-CSRF': csrf, 'Host': 'elsewhere.invalid'}):
        with pytest.raises(HTTPError) as denied:
            http(base, '/api/acquire-detroit', {'accept_source_terms': True}, headers=extra)
        assert denied.value.code == 403
    assert calls == []
    headers = {'X-Fish-CSRF': csrf}
    for payload in ({}, {'accept_source_terms': False}, {'accept_source_terms': 'true'}, {'accept_source_terms': 1}):
        with pytest.raises(HTTPError) as denied:
            http(base, '/api/acquire-detroit', payload, headers=headers)
        assert denied.value.code == 400
        assert json.load(denied.value)['error'] == 'SOURCE_TERMS_REQUIRED'
    assert calls == []
    prepared = http(base, '/api/acquire-detroit', {'accept_source_terms': True}, headers=headers)
    repeated = http(base, '/api/acquire-detroit', {'accept_source_terms': True}, headers=headers)
    assert prepared == repeated
    assert len(calls) == 2
    assert len(service.stories()) == 2
    assert len(service.sessions()) == 1
    assert prepared['public_distribution'] is False
    assert 'UNSEEN_SECOND_CHAPTER_SENTINEL' not in json.dumps(prepared)
    assert_prior_save_untouched(service, previous)


def test_raw_zip_http_import_does_not_need_paths_or_touch_existing_games(quick_server):
    base, service, previous, calls = quick_server
    headers = {'Content-Type': 'application/zip', 'X-Fish-CSRF': http(base, '/api/bootstrap')['csrf']}
    raw = synthetic_archive()
    prepared = http(base, '/api/import-pack?' + urlencode({'title': '整包导入的故事', 'language': 'zh'}), raw=raw, headers=headers)
    assert prepared['title'] == '整包导入的故事'
    assert len(prepared['chapters']) == 2
    assert prepared['public_distribution'] is False
    assert 'UNSEEN_SECOND_CHAPTER_SENTINEL' not in json.dumps(prepared)
    assert calls == []
    assert_prior_save_untouched(service, previous)
    new = http(base, '/api/new', {'player_id': 'new-player', 'story_id': prepared['id'], 'mode': 'agent'}, headers=headers | {'Content-Type': 'application/json'})
    assert new['session_id'] != previous['session_id']
    assert new['accepted_choices'] == 0
    assert 'UNSEEN_SECOND_CHAPTER_SENTINEL' not in json.dumps(new)
    assert_prior_save_untouched(service, previous)


def test_raw_zip_route_rejects_wrong_origin_type_and_size_before_import(quick_server):
    base, service, previous, calls = quick_server
    csrf = http(base, '/api/bootstrap')['csrf']
    raw = synthetic_archive()
    for headers in ({'Content-Type': 'application/zip'},
                    {'Content-Type': 'application/zip', 'X-Fish-CSRF': csrf, 'Origin': 'null'}):
        with pytest.raises(HTTPError) as denied:
            http(base, '/api/import-pack', raw=raw, headers=headers)
        assert denied.value.code == 403
    with pytest.raises(HTTPError) as denied:
        http(base, '/api/import-pack', raw=raw, headers={'Content-Type': 'application/json', 'X-Fish-CSRF': csrf})
    assert json.load(denied.value)['error'] == 'INVALID_STORY_ARCHIVE'
    with pytest.raises(HTTPError) as denied:
        http(base, '/api/import-pack', raw=b'PRIVATE_SENTINEL', headers={
            'Content-Type': 'application/zip', 'X-Fish-CSRF': csrf, 'Content-Length': str(MAX_ARCHIVE_BYTES + 1)})
    assert json.load(denied.value)['error'] == 'STORY_ARCHIVE_TOO_LARGE'
    with pytest.raises(HTTPError) as denied:
        http(base, '/api/import-pack', raw=b'PRIVATE_SENTINEL_NOT_ZIP', headers={'Content-Type': 'application/zip', 'X-Fish-CSRF': csrf})
    assert json.load(denied.value)['error'] == 'INVALID_STORY_ARCHIVE'
    assert len(service.stories()) == 1
    assert calls == []
    assert_prior_save_untouched(service, previous)


def test_cli_setup_play_and_pack_import_have_explicit_boundaries(tmp_path, setup_source, capsys):
    from fish_story import cli
    prefix = ['--home', str(tmp_path / 'private-home')]
    assert cli.main(prefix + ['story-source']) == 0
    assert json.loads(capsys.readouterr().out)['requires_explicit_request'] is True
    assert setup_source[1] == []
    assert cli.main(prefix + ['setup-detroit']) == 1
    assert json.loads(capsys.readouterr().err)['error'] == 'SOURCE_TERMS_REQUIRED'
    assert setup_source[1] == []
    assert cli.main(prefix + ['setup-detroit', '--accept-source-terms']) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert 'UNSEEN_SECOND_CHAPTER_SENTINEL' not in json.dumps(prepared)
    assert cli.main(prefix + ['play-detroit', '--player', 'direct-player', '--accept-source-terms',
                              '--play-style', 'immersive', '--save-name', '本鱼的首次游玩']) == 0
    playing = json.loads(capsys.readouterr().out)
    assert playing['mode'] == 'agent' and playing['player_id'] == 'direct-player'
    assert playing['story_id'] == prepared['id'] and playing['play_style'] == 'immersive'
    assert playing['save_name'] == '本鱼的首次游玩'
    assert playing['current']['choices']
    assert 'UNSEEN_SECOND_CHAPTER_SENTINEL' not in json.dumps(playing)
    archive = tmp_path / 'whole-source.zip'
    archive.write_bytes(synthetic_archive())
    assert cli.main(prefix + ['import-pack', str(archive), '--title', '本地整包导入']) == 0
    assert json.loads(capsys.readouterr().out)['title'] == '本地整包导入'


def test_mcp_source_setup_never_uses_observer_or_replacement_model(tmp_path, setup_source):
    pytest.importorskip('mcp')
    from fish_story.mcp_server import build_server
    service = GameService(tmp_path)
    server = build_server(service, 'bound-player')
    # Source metadata/import do not need any private game projection at all.
    service.observe = lambda *args: pytest.fail('setup must not inspect another game')

    async def exercise():
        tools = await server.list_tools()
        setup = next(tool for tool in tools if tool.name == 'story_setup_detroit')
        assert setup.inputSchema['properties']['accept_source_terms']['default'] is False
        assert setup_source[1] == []
        info = await server.call_tool('story_source', {})
        assert 'Original test source' in str(info)
        assert setup_source[1] == []
        with pytest.raises(Exception, match='SOURCE_TERMS_REQUIRED'):
            await server.call_tool('story_setup_detroit', {})
        assert setup_source[1] == []
        prepared = await server.call_tool('story_setup_detroit', {'accept_source_terms': True})
        assert '原创测试来源' in str(prepared)
        assert 'UNSEEN_SECOND_CHAPTER_SENTINEL' not in str(prepared)
        assert len(setup_source[1]) == 1
        assert service.sessions() == []

    asyncio.run(exercise())

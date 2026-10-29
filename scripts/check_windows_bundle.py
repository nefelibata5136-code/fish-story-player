"""Exercise the actual frozen CLI/MCP using an isolated, temporary player home."""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import hashlib
import json
import os
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def tool_value(result):
    assert not result.isError, str(result.content)
    return json.loads(next(item.text for item in result.content if item.type == 'text'))


async def check_mcp(executable, home, environment, *, detroit=False):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = StdioServerParameters(command=str(executable),
                                  args=['--home', str(home), 'mcp', '--player', 'portable-mcp'],
                                  env=environment)
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            tools = {item.name for item in (await client.list_tools()).tools}
            assert {'game_start', 'game_view', 'game_choose', 'story_list',
                    'story_source', 'story_setup_detroit', 'game_recap_read', 'game_recap_update'} <= tools
            source = await client.call_tool('story_source', {})
            assert not source.isError
            source_info = json.loads(next(item.text for item in source.content if item.type == 'text'))
            assert source_info['chapter_count'] == 32 and source_info['requires_explicit_acceptance']
            denied = await client.call_tool('story_setup_detroit', {'accept_source_terms': False})
            assert denied.isError
            result = await client.call_tool('game_start', {'story_id': 'demo', 'play_style': 'self_aware'})
            assert not result.isError
            value = json.loads(next(item.text for item in result.content if item.type == 'text'))
            result = await client.call_tool('game_choose', {
                'session_id': value['session_id'], 'request_id': value['current']['request_id'],
                'choice': 1, 'reason': 'Frozen MCP smoke check using original demo.'})
            assert not result.isError
            chosen = json.loads(next(item.text for item in result.content if item.type == 'text'))
            assert chosen['accepted_choices'] == 1
            if detroit:
                prepared = tool_value(await client.call_tool('story_setup_detroit', {'accept_source_terms': True}))
                assert len(prepared['chapters']) == 32
                for style in ('self_aware', 'immersive'):
                    value = tool_value(await client.call_tool('game_start', {'play_style': style}))
                    assert value['story_id'] == prepared['id']
                    sid = value['session_id']
                    point = tool_value(await client.call_tool('game_save_checkpoint', {
                        'session_id': sid, 'name': 'Frozen Detroit first scene', 'operation_id': 'first-scene'}))
                    value = tool_value(await client.call_tool('game_pause', {'session_id': sid}))
                    assert value['status'] == 'paused'
                    value = tool_value(await client.call_tool('game_resume', {'session_id': sid}))
                    assert value['status'] == 'waiting'
                    for _ in range(60):
                        if value['status'] == 'recap_required':
                            task = value['recap']['pending_tasks'][0]
                            evidence = tool_value(await client.call_tool('game_recap_read', {
                                'session_id': sid, 'task_id': task['task_id']}))
                            assert evidence['task']['chapter_number'] >= 1
                            text = '脚本构件验收记录：本章已经走完。此文字由验收脚本明确提交，用于验证本人摘要写入协议，不冒充模型自主撰写的剧情梗概。'
                            saved = tool_value(await client.call_tool('game_recap_update', {
                                'session_id': sid, 'task_id': task['task_id'], 'text': text,
                                'operation_id': 'frozen-recap-' + task['task_id']}))
                            assert saved['recap']['characters'] == len(text)
                            assert Path(saved['recap']['file_path']).read_text(encoding='utf-8') == text
                            value = tool_value(await client.call_tool('game_view', {'session_id': sid}))
                            continue
                        if value['status'] == 'complete' or value['current']['chapter'].get('chapter_number') != 1:
                            break
                        value = tool_value(await client.call_tool('game_choose', {
                            'session_id': sid, 'request_id': value['current']['request_id'],
                            'choice': 1, 'reason': 'Scripted artifact compatibility check, not Agent judgment.'}))
                    assert value['accepted_choices'] > 0
                    assert value['status'] == 'complete' or value['current']['chapter']['chapter_number'] > 1
                    branch = tool_value(await client.call_tool('game_load_checkpoint', {
                        'session_id': sid, 'point_id': point['id'], 'name': 'Frozen Detroit replay', 'operation_id': 'first-branch'}))
                    assert branch['session_id'] != sid
                    assert branch['accepted_choices'] == 0
                    restored = tool_value(await client.call_tool('game_view', {'session_id': sid}))
                    assert restored['accepted_choices'] == value['accepted_choices']
            return len(tools)


def main(argv=None, *, archive_checked=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path, help='The frozen fish-story.exe or the complete Windows ZIP')
    parser.add_argument('--detroit', action='store_true',
                        help='Explicitly accept upstream noncommercial terms and download the pinned 32-chapter pack; test chapter 1 through frozen MCP in both styles. No model calls.')
    args = parser.parse_args(argv)
    executable = args.executable.resolve()
    if executable.suffix.lower() == '.zip':
        checksum = executable.with_suffix('.zip.sha256')
        assert checksum.is_file(), 'The ZIP checksum sidecar is required.'
        expected = checksum.read_text(encoding='ascii').split()[0]
        assert hashlib.sha256(executable.read_bytes()).hexdigest() == expected, 'ZIP checksum mismatch.'
        with tempfile.TemporaryDirectory(prefix='fish-story-extracted-') as temporary:
            destination = Path(temporary) / '新电脑 空间'
            with zipfile.ZipFile(executable) as archive:
                archive.extractall(destination)
            frozen = destination / 'FishStoryPlayer-Windows-x64' / 'fish-story.exe'
            assert frozen.is_file()
            arguments = [str(frozen)] + (['--detroit'] if args.detroit else [])
            return main(arguments, archive_checked=True)
    environment = dict(os.environ)
    for name in ('PYTHONHOME', 'PYTHONPATH', 'FISH_STORY_HOME', 'FISH_PLAYER_ID'):
        environment.pop(name, None)
    # The child cannot discover the build Python, Git or pip through PATH.
    environment['PATH'] = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32')
    checks = ['SHA256-verified ZIP extracted into a Chinese/space-containing path'] if archive_checked else []
    with tempfile.TemporaryDirectory(prefix='fish-story-frozen-') as temporary:
        home = Path(temporary) / 'private-home'

        def cli(*arguments, successful=True):
            result = subprocess.run([str(executable), '--home', str(home), *arguments],
                                    cwd=temporary, env=environment, capture_output=True,
                                    text=True, encoding='utf-8', timeout=45)
            assert (result.returncode == 0) == successful, result.stderr
            if successful:
                return json.loads(result.stdout)
            assert result.stdout == ''
            return json.loads(result.stderr)

        assert any(story['id'] == 'demo' for story in cli('stories'))
        missing = cli('new', '--player', 'portable-smoke', '--mode', 'manual', successful=False)
        assert missing['error'] == 'DETROIT_NOT_INSTALLED'
        first = cli('new', '--player', 'portable-smoke', '--mode', 'agent', '--story', 'demo')
        sid = first['session_id']
        assert cli('view', sid) == first
        checks.append('isolated startup and source fingerprint')
        rejected = cli('choose', sid, first['current']['request_id'], '999', successful=False)
        assert rejected['error'] == 'CHOICE_NOT_AVAILABLE'
        assert cli('view', sid) == first
        checks.append('illegal choice leaves save unchanged')
        assert cli('pause', sid)['status'] == 'paused'
        assert cli('view', sid)['status'] == 'paused'
        cli('resume', sid)
        next_view = cli('choose', sid, first['current']['request_id'], '1', '--reason', 'Portable demo check.')
        assert next_view['accepted_choices'] == 1
        observed = cli('view', sid)
        assert (observed['accepted_choices'], observed['current'], observed['status']) == (next_view['accepted_choices'], next_view['current'], next_view['status'])
        point = cli('save-point', sid, '--name', 'Portable checkpoint')
        branch = cli('load-point', sid, point['id'], '--name', 'Portable branch')
        assert branch['session_id'] != sid
        assert cli('view', sid)['current'] == next_view['current']
        checks.append('pause, restart, checkpoint and independent branch')
        final = next_view
        for _ in range(30):
            if final['status'] == 'recap_required':
                task = final['recap']['pending_tasks'][0]
                text = '脚本便携版验收记录：本人显式提交章节摘要测试文字，用于验证持久保存、字数限制与下一章恢复，不冒充模型生成的剧情梗概。'
                draft = Path(temporary) / 'authored-recap.md'
                draft.write_text(text, encoding='utf-8')
                saved = cli('recap-update', sid, '--task-id', task['task_id'], '--text-file', str(draft),
                            '--operation-id', 'portable-' + task['task_id'])
                assert saved['characters'] == len(text)
                assert Path(saved['file_path']).read_text(encoding='utf-8') == text
                final = cli('view', sid)
                continue
            if final['status'] == 'complete':
                break
            final = cli('choose', sid, final['current']['request_id'], '1')
        assert final['status'] == 'complete'
        assert cli('view', sid) == final
        report = cli('export', sid, '--format', 'json')
        assert len(report['records']) == final['accepted_choices']
        memory = subprocess.run([str(executable), '--home', str(home), 'export', sid, '--format', 'memory'],
                                cwd=temporary, env=environment, capture_output=True,
                                text=True, encoding='utf-8', timeout=45)
        assert memory.returncode == 0 and '虚构' in memory.stdout
        checks.append('Agent CLI completes original demo with authored recap files and accurate JSON/memory export')
        tool_count = asyncio.run(check_mcp(executable, home, environment, detroit=args.detroit))
        checks.append('real frozen MCP stdio reads and submits choices')
        if args.detroit:
            checks.append('explicit pinned 32-chapter acquisition; frozen MCP chapter 1 in both styles with pause, authored recap file, restore and independent branch')
        desktop = executable.with_name('FishStoryPlayer.exe')
        process = subprocess.Popen([str(desktop), '--home', str(home), 'serve', '--port', '0'],
                                   cwd=temporary, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding='utf-8')
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            line = pool.submit(process.stdout.readline).result(timeout=25)
            assert line.startswith('Fish Story Player: http://127.0.0.1:'), line
            url = line.strip().split('Fish Story Player: ', 1)[1]
            with urllib.request.urlopen(url, timeout=10) as response:
                html = response.read().decode('utf-8')
                assert '底特律' in html and '核心资料' in html
            with urllib.request.urlopen(url + '/api/bootstrap', timeout=10) as response:
                bootstrap = json.load(response)
                assert any(item['id'] == 'demo' for item in bootstrap['stories'])
                if args.detroit:
                    assert bootstrap['stories'][0]['id'] != 'demo'
            checks.append('desktop executable serves packaged Detroit-first browser UI')
        finally:
            process.terminate()
            process.communicate(timeout=15)
            pool.shutdown(wait=True, cancel_futures=True)
    print(json.dumps({'passed': True, 'checks': checks, 'mcp_tools': tool_count,
                      'paid_api_calls': 0,
                      'limits': 'Isolated artifact checks; not an unknown clean Windows installation or signed binary.'},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Generated configs are exercised through actual MCP stdio in another cwd."""
import asyncio
import json
import os
from pathlib import Path

import pytest

from fish_story.agent_setup import connection_info
from fish_story.service import GameService


def test_default_is_detroit_and_demo_is_explicit(tmp_path):
    service = GameService(tmp_path)
    assert service.default_story_id() is None
    with pytest.raises(ValueError, match='DETROIT_NOT_INSTALLED'):
        service.start('fish')
    assert service.sessions() == []
    assert service.start('fish', story_id='demo')['story_id'] == 'demo'


def test_setup_validates_owned_session_without_model_or_core_access(tmp_path):
    service = GameService(tmp_path)
    game = service.start('owner', story_id='demo', play_style='immersive')
    session = game['session_id']
    with pytest.raises(PermissionError, match='NOT_OWNED'):
        connection_info(service, 'other', session_id=session)
    result = connection_info(service, 'owner', session_id=session)
    assert result['play_style'] == 'immersive'
    assert 'game_open' in result['agent_instructions']
    assert session in result['agent_instructions']
    assert result['cli_command'][-2:] == ['view', session]
    assert 'play-detroit' not in result['cli_command']
    native = result['dsh_config'][0]['config']
    assert native['transport'] == 'stdio' and native['toolCallTimeoutMs'] >= 120000
    assert not any('KEY' in key or 'TOKEN' in key for key in native['env'])
    assert len(service.sessions()) == 1


def test_generated_mcp_config_runs_from_unrelated_directory(tmp_path, monkeypatch):
    pytest.importorskip('mcp')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    service = GameService(tmp_path / 'private')
    result = connection_info(service, 'bound player')
    config = result['mcp_config']['mcpServers']['fish-story']
    monkeypatch.chdir(tmp_path)

    async def exercise():
        parameters = StdioServerParameters(**config)
        async with stdio_client(parameters) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                assert {'game_start', 'game_choose', 'game_save_checkpoint'} <= {tool.name for tool in tools}
                default = await client.call_tool('game_start', {})
                assert default.isError and 'DETROIT_NOT_INSTALLED' in str(default.content)
                started = await client.call_tool('game_start', {'story_id': 'demo'})
                assert not started.isError
                payload = started.structuredContent
                if not payload:
                    payload = json.loads(started.content[0].text)
                assert payload['player_id'] == 'bound player'
                current = payload['current']
                choice = await client.call_tool('game_choose', {'session_id': payload['session_id'],
                    'request_id': current['request_id'], 'choice': current['choices'][0]['number']})
                assert not choice.isError
    asyncio.run(exercise())


def test_cli_config_export_never_overwrites_existing_file(tmp_path, capsys):
    from fish_story.cli import main
    output = tmp_path / 'mcp.json'
    arguments = ['--home', str(tmp_path / 'private'), 'agent-config', '--player', 'fish',
                 '--format', 'mcp', '--output', str(output)]
    assert main(arguments) == 0
    capsys.readouterr()
    data = output.read_bytes()
    assert json.loads(data)['mcpServers']['fish-story']['command']
    assert main(arguments) == 1
    capsys.readouterr()
    assert output.read_bytes() == data

"""Generate working, local connection instructions without reading any Core/key.

DSH uses a native cordis plugin entry; a generic mcpServers object is also
provided for clients using that configuration format. Nothing is installed into
an existing Agent and no session/model is started by this module.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _powershell(command):
    return '& ' + ' '.join("'" + str(value).replace("'", "''") + "'" for value in command)


def connection_info(service, player_id, play_style='self_aware', session_id=None):
    if not isinstance(player_id, str) or not 1 <= len(player_id.strip()) <= 100 or '\x00' in player_id:
        raise ValueError('INVALID_PLAYER_ID')
    if play_style not in ('self_aware', 'immersive'):
        raise ValueError('INVALID_PLAY_STYLE')
    player_id = player_id.strip()
    if session_id:
        meta = service._meta(session_id)
        if meta.get('player_id') != player_id:
            raise PermissionError('SESSION_NOT_OWNED_BY_BOUND_PLAYER')
        play_style = meta.get('play_style', play_style)

    root = Path(__file__).resolve().parents[1]
    executable = Path(sys.executable).resolve()
    if getattr(sys, 'frozen', False):
        command = executable.with_name('fish-story.exe')
        if not command.is_file():
            raise ValueError('AGENT_EXECUTABLE_MISSING')
        prefix = [str(command)]
        environment = {}
        cwd = str(command.parent)
    else:
        prefix = [str(executable), '-m', 'fish_story.cli']
        # MCP clients do not all implement cwd. Pin our module path explicitly;
        # do not copy the parent's environment (which can contain credentials).
        environment = {'PYTHONPATH': str(root), 'PYTHONIOENCODING': 'utf-8'}
        cwd = str(root)
    prefix += ['--compact', '--home', str(Path(service.directory).resolve())]
    mcp_command = prefix + ['mcp', '--player', player_id]
    native = {'transport': 'stdio', 'serverName': 'fish-story',
              'command': mcp_command[0], 'args': mcp_command[1:],
              'cwd': cwd, 'env': environment, 'toolCallTimeoutMs': 150000,
              'failOnStartupError': True}
    generic = {key: native[key] for key in ('command', 'args', 'env')}
    dsh_entry = {'id': 'fish-story', 'name': '@deepseek-ai/dsh-mcp-client', 'config': native}
    # JSON is valid YAML 1.2. Scalar encoding safely handles Windows paths and
    # user-chosen player names; there is no shell/string-built YAML evaluation.
    dsh_yaml = ('- id: fish-story\n  name: "@deepseek-ai/dsh-mcp-client"\n  config: '
                + json.dumps(native, ensure_ascii=False) + '\n')
    start = (prefix + ['view', session_id] if session_id else
             prefix + ['play-detroit', '--player', player_id, '--play-style', play_style,
                       '--accept-source-terms'])
    if session_id:
        begin = ('打开现有存档，不要重新开局：game_open(session_id='
                 + json.dumps(session_id) + ')。')
    else:
        begin = ('先调用 story_source 查看来源说明；经主人同意获取后调用 '
                 'story_setup_detroit(accept_source_terms=true)，然后 '
                 'game_start(story_id="detroit", play_style='
                 + json.dumps(play_style) + ')。')
    instructions = (
        '请以你原来的身份亲自玩《底特律：变人》，使用本机 fish-story 工具；'
        '不创建替身模型，不修改你的 Core。\n' + begin + '\n'
        '每次只读 game_view 提供的当前剧情和合法选项，再用返回的 session_id、request_id '
        '调用 game_choose。不要读取剧情 JSON、隐藏规则或未来章节；角色沉浸遵守当前角色知识范围。\n'
        '每步工具只返回当前场景和本次回执，避免反复复制整部历史。恢复或切换角色需回顾时，'
        '调用 game_history(offset=0, limit=20)，按 next_offset 分页读取当前角色获知的历史。\n'
        '每完成一章，你必须亲自更新本地前情摘要。收到 recap_required 后调用 game_recap_read(task_id=...)，'
        '用旧摘要和该章已见材料自己撰写，再调用 game_recap_update。默认最多5000字，'
        '你可用 max_characters 自行调整；不得把程序生成的文本当成你已经认可的理解。'
        '沉浸时分别维护角色摘要。更新后 game_view 继续，最终章结束也要更新。\n'
        '每次选择自动保存。用 game_pause / game_resume 暂停继续；需要换路线时，'
        'game_save_checkpoint / game_load_checkpoint 会保留原存档并新建分支。'
        '结果不明先查原存档，保留同一 operation_id，不反复开新局。\n'
        '结束后调用 game_export(format="memory")，由你审核候选后决定是否纳入自己的记忆。'
        '虚构游戏事件不等于现实经历。\n'
        '若尚未连接 MCP，使用下面的本机 CLI（不会调用额外模型）。'
        + ('此命令恢复现有存档，不另开新局：\n' if session_id else '首次下载须确认来源条款：\n')
        + _powershell(start) + '\n'
        '后续用同一运行器的 view / choose / pause / resume 命令和返回的会话、请求 ID 继续。')
    dsh_instructions = (
        '把下方条目添加到你实际使用的 DSH cordis.yml 插件列表，保留原来的模型、身份和其他插件。'
        '条目中的路径和玩家标识已经按本机生成，无需手填。重新加载该配置后，'
        '工具名以 mcp__fish-story__ 开头。请先确认能发现 game_start / game_choose，再开始游玩。'
        '本程序不会擅自改动已有 DSH 配置或唤醒主对话。')
    return {'player_id': player_id, 'play_style': play_style, 'session_id': session_id,
            'mcp_config': {'mcpServers': {'fish-story': generic}},
            'dsh_config': [dsh_entry], 'dsh_config_yaml': dsh_yaml,
            'agent_instructions': instructions, 'dsh_instructions': dsh_instructions,
            'cli_command': start, 'mcp_command': mcp_command}

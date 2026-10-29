"""Local sessions around the existing deterministic engine. No model calls here."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from .engine import Store, now
from .styles import ContextStore, STYLES, PROMPT_VERSION, decorate, player_projection

PACKAGE = Path(__file__).parent
IDENTITY_NOTICE = '基于核心身份资料创建的独立游玩会话；不保证复现原系统的认知状态和长期经历。'
MEMORY_NOTICE = ('以下剧情发生在虚构游戏中。实际发生的是玩家阅读、选择和评价。'
                 '本摘要由程序依据已保存证据生成，尚未成为玩家认可的个人记忆；请本人审核后自行导入。')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def chapter_info(doc):
    c = doc.get('chapter', {})
    return {'chapter_number': c.get('chapter_number'), 'title': c.get('title_zh') or c.get('title', '')}


def validate_story(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get('chapter'), dict):
        raise ValueError('INVALID_STORY_CHAPTER')
    number = doc['chapter'].get('chapter_number')
    if type(number) is not int or number < 1:
        raise ValueError('INVALID_CHAPTER_NUMBER')
    if not isinstance(doc.get('nodes'), list) or not doc['nodes'] or len(doc['nodes']) > 10000:
        raise ValueError('INVALID_STORY_NODES')
    if not isinstance(doc.get('endings'), dict) or not doc['endings']:
        raise ValueError('INVALID_STORY_ENDINGS')
    seen = set()
    for node in doc['nodes']:
        if not isinstance(node, dict) or not isinstance(node.get('id'), str) or node['id'] in seen:
            raise ValueError('INVALID_NODE_ID')
        seen.add(node['id'])
        if not isinstance(node.get('player_facing'), dict):
            raise ValueError('INVALID_PLAYER_FACING')
    # Story-authored role instructions are never forwarded to the player.
    doc.setdefault('system_prompt', {'content': ''})
    return doc


class GameService:
    def __init__(self, directory=None):
        self.directory = Path(directory or os.environ.get('FISH_STORY_HOME') or Path.home() / '.fish-story-player').resolve()
        (self.directory / 'sessions').mkdir(parents=True, exist_ok=True)
        (self.directory / 'stories').mkdir(exist_ok=True)

    def session_dir(self, session_id):
        try:
            if str(uuid.UUID(str(session_id))) != session_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError('INVALID_SESSION_ID') from None
        path = self.directory / 'sessions' / session_id
        if not (path / 'session.json').is_file():
            raise ValueError('NO_SESSION')
        return path

    def _meta(self, session_id):
        return read_json(self.session_dir(session_id) / 'session.json')

    def _store(self, session_id):
        style = self._meta(session_id).get('play_style', 'legacy_unspecified')
        if style == 'legacy_unspecified':
            return Store(self.session_dir(session_id))
        if style not in ('immersive', 'self_aware'):
            raise ValueError('INVALID_PLAY_STYLE')
        return ContextStore(self.session_dir(session_id), style)

    def stories(self):
        docs = [read_json(p) for p in sorted((PACKAGE / 'demo').glob('ch*.json'))]
        result = [{'id': 'demo', 'title': '雾港来信 · 原创演示', 'chapters': [chapter_info(d) for d in docs],
                   'public_distribution': True, 'license': 'CC0-1.0'}]
        for path in sorted((self.directory / 'stories').glob('*/manifest.json')):
            m = read_json(path)
            result.append({k: m[k] for k in ('id', 'title', 'chapters', 'public_distribution')})
        return result

    def import_story(self, paths, title='本地故事'):
        if not isinstance(paths, list) or not 1 <= len(paths) <= 100:
            raise ValueError('INVALID_STORY_FILES')
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
            raise ValueError('INVALID_STORY_TITLE')
        docs = []
        for raw in paths:
            path = Path(raw)
            if path.suffix.lower() != '.json' or path.stat().st_size > 20_000_000:
                raise ValueError('STORY_FILE_TOO_LARGE_OR_NOT_JSON')
            docs.append(validate_story(read_json(path)))
        docs.sort(key=lambda d: d['chapter']['chapter_number'])
        numbers = [d['chapter']['chapter_number'] for d in docs]
        if len(set(numbers)) != len(numbers):
            raise ValueError('DUPLICATE_CHAPTER')
        story_id = str(uuid.uuid4())
        directory = self.directory / 'stories' / story_id
        directory.mkdir()
        for i, doc in enumerate(docs):
            write_json(directory / f'ch{i:03}.json', doc)
        manifest = {'id': story_id, 'title': title.strip(), 'chapters': [chapter_info(d) for d in docs],
                    'public_distribution': False, 'imported_at': now(),
                    'rights_status': 'Local user-supplied material; redistribution permission has not been established.'}
        write_json(directory / 'manifest.json', manifest)
        return {k: manifest[k] for k in ('id', 'title', 'chapters', 'public_distribution')}

    def start(self, player_id, story_id='demo', chapter=1, mode='agent', core_text=None, difficulty='casual', play_style='self_aware'):
        if not isinstance(player_id, str) or not 1 <= len(player_id.strip()) <= 100:
            raise ValueError('INVALID_PLAYER_ID')
        if mode not in ('agent', 'independent', 'manual'):
            raise ValueError('INVALID_MODE')
        if play_style not in ('immersive', 'self_aware'):
            raise ValueError('INVALID_PLAY_STYLE')
        if difficulty not in ('casual', 'experienced', 'hardcore') or type(chapter) is not int:
            raise ValueError('INVALID_GAME_CONFIGURATION')
        if mode == 'independent':
            from .model import validate_core
            validate_core(core_text)
        elif core_text not in (None, ''):
            raise ValueError('CORE_ONLY_FOR_INDEPENDENT_SESSION')
        story = next((s for s in self.stories() if s['id'] == story_id), None)
        if story is None:
            raise ValueError('NO_STORY')
        source = PACKAGE / 'demo' if story_id == 'demo' else self.directory / 'stories' / story_id
        paths = [p for p in sorted(source.glob('ch*.json')) if read_json(p)['chapter']['chapter_number'] >= chapter]
        if chapter not in [c['chapter_number'] for c in story['chapters']] or not paths:
            raise ValueError('NO_CHAPTER')
        session_id = str(uuid.uuid4())
        directory = self.directory / 'sessions' / session_id
        (directory / 'story').mkdir(parents=True)
        pinned = []
        for path in paths:
            target = directory / 'story' / path.name
            shutil.copyfile(path, target)
            pinned.append(target)
        if mode == 'independent':
            (directory / 'core.txt').write_text(core_text, encoding='utf-8')
        ContextStore(directory, play_style).start('player', pinned, difficulty)
        write_json(directory / 'session.json', {
            'session_id': session_id, 'player_id': player_id.strip(), 'mode': mode, 'story_id': story_id,
            'story_title': story['title'], 'public_distribution': story['public_distribution'],
            'start_chapter': chapter, 'created_at': now(), 'difficulty': difficulty,
            'play_style': play_style, 'play_style_version': PROMPT_VERSION,
            'identity_notice': IDENTITY_NOTICE if mode == 'independent' else '原 Agent 或手动玩家作出选择；程序不创建替代玩家。',
            'prior_chapters': 'fresh initial state; earlier chapters were not played in this session' if chapter > 1 else None,
        })
        return self.view(session_id)

    def sessions(self):
        result = []
        for path in sorted((self.directory / 'sessions').glob('*/session.json')):
            meta = read_json(path)
            style = meta.get('play_style', 'legacy_unspecified')
            meta.update(play_style=style, play_style_label=STYLES.get(style, STYLES['legacy_unspecified'])['label'])
            result.append(meta)
        return result

    def view(self, session_id):
        return player_projection(self.observe(session_id))

    def observe(self, session_id):
        meta = self._meta(session_id)
        return decorate({**meta, **self._store(session_id).view('player')}, self.session_dir(session_id))

    def choose(self, session_id, request_id, choice, reason=''):
        current = self.view(session_id)
        if (current.get('play_style') == 'immersive' and current.get('perspective', {}).get('unavailable')
                and request_id == (current.get('current') or {}).get('request_id')):
            raise ValueError('ROLE_PERSPECTIVE_UNAVAILABLE')
        self._store(session_id).mutate('player', 'choose', {'request_id': request_id, 'choice': choice, 'reason': reason})
        return self.view(session_id)

    def pause(self, session_id):
        self._store(session_id).mutate('player', 'pause', {})
        return self.view(session_id)

    def resume(self, session_id):
        self._store(session_id).mutate('player', 'resume', {})
        return self.view(session_id)

    def export(self, session_id, format='json', share=False, audience='player'):
        if audience not in ('player', 'observer'):
            raise ValueError('INVALID_EXPORT_AUDIENCE')
        view = self.observe(session_id) if audience == 'observer' else self.view(session_id)
        if share and not view['public_distribution']:
            raise ValueError('SHARE_REQUIRES_STORY_RIGHTS: local imported story is not cleared for redistribution')
        data = {'schema': 'fish-story-experience/1', 'session_id': session_id,
                'player_id': view['player_id'], 'mode': view['mode'], 'identity_notice': view['identity_notice'],
                'play_style': view['play_style'], 'play_style_label': view['play_style_label'], 'audience': audience,
                'perspective': view.get('perspective'),
                'story_title': view['story_title'], 'status': view['status'], 'exported_at': now(),
                'memory_status': 'program_generated_candidate_not_player_endorsed',
                'fiction_notice': MEMORY_NOTICE, 'save_location': str(self.session_dir(session_id) / 'games.sqlite'),
                'records': view['records'], 'visible_history': view['history'], 'current': view['current'],
                'privacy': {'local_private': not share, 'contains_core': False,
                            'review_required': True, 'story_rights_cleared': view['public_distribution']}}
        if share:
            # No core ever enters exports. Drop freely authored reasons and identifiers before scanning.
            data = copy.deepcopy(data)
            data['player_id'], data['session_id'], data['save_location'] = 'player', 'shared-session', '[local save omitted]'
            for record in data['records']:
                for key in ('record_id', 'request_id', 'content_hash'):
                    record.pop(key, None)
                record['public_reason'] = '[public explanation omitted; review locally]'
                record['after'].pop('next_request_id', None)
                record['after']['save_location'] = '[omitted]'
            for event in data['visible_history']:
                if event['type'] == 'decision':
                    event['reasoning'] = '[public explanation omitted; review locally]'
                    event.pop('request_id', None)
            data['current'] = None
            data['privacy']['redaction'] = 'identity, save paths, free-form explanations and correlation IDs removed; review required'
        if format == 'json':
            return data
        if format not in ('markdown', 'memory'):
            raise ValueError('INVALID_EXPORT_FORMAT')
        lines = [f"# {data['story_title']} · {'经历摘要候选' if format == 'memory' else '游玩报告'}", '', MEMORY_NOTICE, '',
                 f"玩家：{data['player_id']} · 会话：{data['session_id']}", f"模式：{data['mode']} · {data['identity_notice']}",
                 f"玩法：{data['play_style_label']} · 阅读范围：{'完整人类观测' if audience == 'observer' else '玩家当前视角'}",
                 f"状态：{data['status']} · 已保存选择：{len(data['records'])}", '',
                 '隐私：本地私人导出，分享前须审核。' if not share else '已做基础脱敏；分享前仍须审核正文和时间等个人信息。', '']
        if format == 'markdown':
            for event in data['visible_history']:
                if event['type'] == 'node_shown':
                    chapter = event.get('chapter') or {}
                    lines.extend([f"## 第 {chapter.get('chapter_number', '?')} 章 · 节点 {event.get('node_ref', '')}", '',
                                  event['context'], ''])
                    lines.extend(f"- {i}. {c['text']}" for i, c in enumerate(event['choices'], 1))
                    lines.append('')
                elif event['type'] == 'decision':
                    lines.extend([f"**玩家实际选择：{event['choice_text']}**", f"时间：{event['occurred_at']}",
                                  f"公开说明：{event['reasoning'] or '未提供'}", ''])
                elif event['type'] == 'chapter_end':
                    lines.extend([f"### 虚构章节结果：{event['ending']['title']}", '', event['ending']['narrative'], ''])
        else:
            lines.extend(['## 玩家真实行为与公开评价', ''])
            for r in data['records']:
                lines.extend([f"- 第 {r['chapter'].get('chapter_number', '?')} 章，{r['occurred_at']}：玩家选择“{r['choice_text']}”。",
                              f"  玩家公开说明：{r['public_reason'] or '未提供；程序不推测动机。'}"])
            lines.extend(['', '## 游戏中的虚构结果（仅限实际已展示）', ''])
            for event in data['visible_history']:
                if event['type'] == 'chapter_end':
                    lines.append(f"- {event['ending']['title']}：{event['ending']['narrative']}")
            if not any(e['type'] == 'chapter_end' for e in data['visible_history']):
                lines.append('- 尚未完成章节；请以JSON记录中的outcome和已展示场景为依据，不推断结局。')
            lines.extend(['', '证据：结构化JSON内records保存每次实际选项、选择、可见结果、时间、稳定ID与hash。',
                          '请玩家审核这份候选摘要；程序不会改写核心资料或自动写入长期记忆。'])
        return '\n'.join(lines) + '\n'

    def export_evidence(self, session_id, output_dir):
        """Small, local-only dots source adapter. Stable IDs/hashes; repeatable snapshots."""
        view = self.observe(session_id)
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        records = []
        for r in view['records']:
            records.append({'id': r['record_id'], 'source': 'fish-story-player', 'occurred_at': r['occurred_at'],
                            'observed_at': r['observed_at'], 'content_hash': r['content_hash'], 'deleted': False,
                            'evidence': {'session_id': session_id, 'node_ref': r['node_ref'], 'record_id': r['record_id']},
                            'content': r, 'privacy': 'local_private_unreviewed', 'fiction': True})
        content = ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in records)
        digest = hashlib.sha256(content.encode()).hexdigest()
        snapshot = output_dir / digest
        snapshot.mkdir(exist_ok=True)
        # Split only between complete records; an unusually large record remains intact.
        parts, chunk = [], ''
        for line in content.splitlines(keepends=True):
            if chunk and len((chunk + line).encode()) > 1_000_000:
                parts.append(chunk)
                chunk = ''
            chunk += line
        if chunk or not parts:
            parts.append(chunk)
        files = []
        for i, part in enumerate(parts):
            name = f'records.{i:03}.jsonl'
            (snapshot / name).write_bytes(part.encode('utf-8'))
            files.append({'path': name, 'sha256': hashlib.sha256(part.encode()).hexdigest()})
        manifest = {'source': 'fish-story-player', 'snapshot_id': digest, 'count': len(records), 'files': files,
                    'privacy': 'local_private_unreviewed', 'automatic_upload': False,
                    'schema': 'fish-story-dots-source/1', 'supports_deletion': 'no deletion API; records immutable',
                    'versions': 'immutable content-addressed snapshots; compare stable record IDs and content_hash'}
        write_json(snapshot / 'manifest.json', manifest)
        write_json(output_dir / 'LATEST.json', {'snapshot_id': digest, 'manifest': f'{digest}/manifest.json'})
        return manifest

"""Decision perspectives, distinct from player identity and connection mode.

The native engine stays byte-for-byte unchanged. Human observation is complete;
an immersive player receives only explicitly attributed character information.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from .engine import Store

PROMPT_VERSION = 'play-style/1'
STYLES = {
    'immersive': {'label': '角色沉浸', 'description': '以当前角色当时掌握的信息和处境作判断；玩家身份与核心保持独立。'},
    'self_aware': {'label': '自知玩家', 'description': '知道自己在玩游戏，携原本的经历与理解面对已见剧情。'},
    'legacy_unspecified': {'label': '旧存档 · 未声明玩法', 'description': '保留旧版提示与上下文，不追溯宣称采用了新玩法。'},
}
ALIASES = {'Connor': ('Connor', '康纳'), 'Kara': ('Kara', '卡拉'), 'Markus': ('Markus', '马库斯'),
           'North': ('North', '诺丝')}
RULES = {
    'immersive': (
        'Decision perspective: CHARACTER IMMERSION. Remain the original player with your own identity; '
        'this is temporary fictional role-taking, never an identity or core replacement. '
        'For each choice, take the controlled character\'s situation and knowledge at that moment as the basis. '
        'The role-specific transcript contains only that character\'s explicitly attributed visible scenes and choices. '
        'Do not import private facts learned through another character, unseen plot, endings, or walkthrough knowledge. '
        'Your own understanding can help interpret the situation, but is not evidence that the character knows a game fact. '
        'Unknown character background remains unknown. No morality, personality trait or ending is prescribed.'),
    'self_aware': (
        'Decision perspective: SELF-AWARE PLAYER. You know you are playing a fictional interactive story. '
        'Bring your own background, experiences and understanding to the choices; you need not imitate a character\'s personality. '
        'All already witnessed game scenes may inform your interpretation, but do not use unseen future events, '
        'hidden conditions or walkthrough knowledge. Characters remain fictional and do not replace your identity. '
        'No morality, personality trait or ending is prescribed.'),
}


def style_instructions(style):
    return RULES.get(style, '')


def content_hash(record):
    return hashlib.sha256(json.dumps({k: v for k, v in record.items() if k != 'content_hash'},
                                    ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _names(value):
    values = value if isinstance(value, list) else [value] if value else []
    return [s for s in values if isinstance(s, str) and s.strip()]


def _canonical(value, candidates):
    if not isinstance(value, str):
        return None
    for candidate in candidates:
        if value.casefold() in [s.casefold() for s in ALIASES.get(candidate, (candidate,))]:
            return candidate
    return None


def _visible_label(context, candidates):
    """Recognize only a complete first-line heading, never a narrative name mention."""
    # Some multi-character finales place North's scene on the Markus engine
    # track. A visible North heading denotes North's own knowledge stream. It
    # must override that phase fallback instead of leaking her scene to Markus.
    if len(candidates) > 1 and 'Markus' in candidates and 'North' not in candidates:
        candidates = [*candidates, 'North']
    aliases = {alias: candidate for candidate in candidates for alias in ALIASES.get(candidate, (candidate,))}
    if not aliases:
        return None
    names = '|'.join(re.escape(s) for s in sorted(aliases, key=len, reverse=True))
    lines = (context or '').lstrip('\ufeff \t\r\n').splitlines()
    if not lines:
        return None
    line = lines[0].strip()
    colon = re.fullmatch(r'(?:视角切换|当前视角|当前角色|Perspective|POV|Character)\s*[:：]\s*('
                         + names + r')\s*[。.!！]?', line, re.IGNORECASE)
    bracket = re.fullmatch(r'【(' + names + r')视角】', line, re.IGNORECASE)
    match = colon or bracket
    if match:
        return _canonical(match.group(1), candidates)
    # An explicitly named substitute is its own knowledge stream, never the base character.
    substitute = re.fullmatch(r'【(' + names + r')视角[—\-]+([^【】\r\n]{1,60})】', line, re.IGNORECASE)
    if substitute:
        name = substitute.group(2).strip()
        return 'North' if name in ('诺丝', 'North') else name
    return None


class Attribution:
    def __init__(self, directory):
        self.nodes = {}
        self.endings = {}
        for path in sorted((Path(directory) / 'story').glob('*.json')):
            doc = json.loads(path.read_text(encoding='utf-8-sig'))
            c = doc['chapter']
            # Native _chapter_meta emits these keys even when a source field is absent.
            chapter = {k: c.get(k) for k in ('chapter_number', 'title', 'title_zh', 'protagonist')}
            candidates = _names(chapter.get('protagonist'))
            for node in doc['nodes']:
                ref = hashlib.sha256(f"{chapter}:{node['id']}".encode()).hexdigest()[:20]
                if ref in self.nodes:
                    raise ValueError('ROLE_PERSPECTIVE_UNAVAILABLE: ambiguous story node attribution')
                player_facing = node.get('player_facing', {})
                explicit = player_facing.get('perspective')
                actor = _canonical(explicit, candidates)
                source = 'explicit_player_facing_perspective' if actor else None
                declared_invalid = 'perspective' in player_facing and actor is None
                if declared_invalid:
                    source = 'invalid_explicit_perspective'
                if actor is None and not declared_invalid and len(candidates) == 1:
                    actor, source = candidates[0], 'single_chapter_protagonist'
                if actor is None and not declared_invalid:
                    phase = node.get('phase') or ''
                    prefix = phase.split('_', 1)[0]
                    # Same documented phase-prefix convention as native runner._node_track.
                    actor = next((n for n in candidates if n.lower() == prefix), None)
                    if actor:
                        source = 'native_phase_track'
                self.nodes[ref] = (actor, source, candidates)
            for ending in doc.get('endings', {}).values():
                if not isinstance(ending, dict):
                    continue
                actor = _canonical(ending.get('player_perspective'), candidates)
                if 'player_perspective' not in ending and actor is None and len(candidates) == 1:
                    actor = candidates[0]
                key = (chapter.get('chapter_number'), ending.get('title'), ending.get('narrative'))
                if key in self.endings and self.endings[key] != actor:
                    actor = None  # Native projection has no ending ID: collisions are ambiguous.
                self.endings[key] = actor

    def actor(self, node_ref, context=''):
        actor, source, candidates = self.nodes.get(node_ref, (None, None, []))
        if source == 'invalid_explicit_perspective':
            return None, source
        label = _visible_label(context, candidates)
        if label and source == 'explicit_player_facing_perspective' and label != actor:
            return None, 'conflicting_explicit_perspective'
        if label and source != 'explicit_player_facing_perspective':
            return label, 'explicit_visible_perspective_heading'
        if actor is None:
            actor = label
            source = 'explicit_visible_perspective_heading' if actor else 'unattributed'
        return actor, source or 'unattributed'

    def event(self, event):
        value = copy.deepcopy(event)
        actor, source = self.actor(event.get('node_ref'), event.get('context', ''))
        if event.get('type') == 'chapter_end':
            ending, chapter = event.get('ending') or {}, event.get('chapter') or {}
            actor = self.endings.get((chapter.get('chapter_number'), ending.get('title'), ending.get('narrative')))
            source = 'explicit_or_single_character_ending' if actor else 'unattributed_ending'
        value['controlled_characters'] = [actor] if actor else []
        value['perspective_source'] = source
        return value

    def history(self, history):
        result, previous = [], None
        for event in history:
            value = self.event(event)
            if value.get('type') == 'decision' and previous and previous.get('node_ref') == value.get('node_ref'):
                value['controlled_characters'] = previous['controlled_characters']
                value['perspective_source'] = previous['perspective_source']
            result.append(value)
            if value.get('type') == 'node_shown':
                previous = value
        return result

    def receipt(self, receipt, style):
        value = copy.deepcopy(receipt)
        actor, source = self.actor(value['node_ref'], value['scene'])
        value.setdefault('native_content_hash', value['content_hash'])
        value.update(play_style=style, play_style_version=PROMPT_VERSION,
                     controlled_characters=[actor] if actor else [], perspective_source=source)
        value['outcome'] = self.history(value['outcome'])
        value['content_hash'] = content_hash(value)
        return value


class ContextStore(Store):
    """Add immutable play context to each receipt before the native transaction commits."""
    def __init__(self, directory, style):
        self.play_style = style
        self.attribution = Attribution(directory)
        super().__init__(directory)

    def replay(self, run):
        projection = super().replay(run)
        for answer in run['answers']:
            if 'receipt' in answer:
                # Update the existing dict: the native projection holds its reference.
                receipt = answer['receipt']
                enriched = self.attribution.receipt(receipt, self.play_style)
                receipt.clear()
                receipt.update(enriched)
        return projection


def decorate(view, directory):
    """Complete operator timeline. Does not filter or change the source records."""
    value = copy.deepcopy(view)
    style = value.get('play_style', 'legacy_unspecified')
    info = STYLES.get(style)
    if info is None:
        raise ValueError('INVALID_PLAY_STYLE')
    value.update(play_style=style, play_style_label=info['label'], play_style_description=info['description'])
    if style == 'legacy_unspecified':
        return value
    attribution = Attribution(directory)
    value['history'] = attribution.history(value['history'])
    if value['current']:
        current = attribution.event({'type': 'node_shown', **value['current']})
        current.pop('type', None)
        value['current'] = current
    focus = value['current'] or next((e for e in reversed(value['history']) if e['type'] == 'node_shown'), {})
    actors = focus.get('controlled_characters', [])
    value['perspective'] = {
        'style': style, 'label': info['label'], 'controlled_characters': actors,
        'instructions': style_instructions(style),
        'information_boundary': 'current_character_visible_history' if style == 'immersive' else 'all_already_witnessed_history',
        'limitations': ('原 Agent 已有记忆无法被程序擦除；须自行遵守角色知识边界。'
                       '本地剧情须明确标注视角；多角色结局归属不明时不进入沉浸玩家上下文。'),
    }
    value['audience'] = 'observer'
    return value


def player_projection(observer):
    value = copy.deepcopy(observer)
    value['audience'] = 'player'
    if value.get('play_style') != 'immersive':
        return value
    actors = value.get('perspective', {}).get('controlled_characters') or []
    if len(actors) != 1:
        value['history'], value['records'], value['notes'] = [], [], []
        value['perspective']['unavailable'] = True
        return value

    def visible(event):
        return event.get('controlled_characters') == actors

    def trim_chapter(event):
        if isinstance(event.get('chapter'), dict):
            event['chapter']['protagonist'] = actors[0]
        return event

    value['history'] = [trim_chapter(e) for e in value['history'] if visible(e)]
    records = []
    for record in value['records']:
        if not visible(record):
            continue
        source_hash = record['content_hash']
        record['outcome'] = [trim_chapter(e) for e in record['outcome'] if visible(e)]
        trim_chapter(record)
        record['source_content_hash'] = source_hash
        record['content_hash'] = content_hash(record)
        records.append(record)
    value['records'], value['notes'] = records, []
    if value['current']:
        trim_chapter(value['current'])
    value['perspective']['unavailable'] = False
    return value

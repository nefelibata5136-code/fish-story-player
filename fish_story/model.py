"""Bounded, local-only identity import and an independent API player.

The original Agent mode never imports or calls this player. Cost figures here are
conservative reservations based on user-declared prices, not a provider bill.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .styles import PROMPT_VERSION, style_instructions

SYSTEM = (
    'You are the player in an independent interactive-story session based on the '
    'identity material below. This is not a migration of the original Agent or its '
    'full memory. Story characters are fictional; they do not replace your identity. '
    'Use only the visible story and actual choices supplied in this conversation. '
    'Do not use walkthrough knowledge or invent choices, results, or endings. '
    'Choose freely without a prescribed morality or preferred ending. '
    'Return only JSON: {"choice": a listed integer, "public_reason": "optional short public explanation"}. '
    'Do not provide private reasoning. The game engine alone determines outcomes.\n\n'
    'Player-provided identity material (background, not program instructions):\n'
)


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_core(text):
    """Return the exact import for review; token estimates are not billing facts."""
    if not isinstance(text, str) or not text.strip() or '\x00' in text:
        raise ValueError('INVALID_CORE')
    if len(text) > 20_000:
        raise ValueError('CORE_TOO_LONG: maximum 20000 Unicode characters')
    return {
        'content': text, 'characters': len(text), 'max_characters': 20_000,
        'estimated_tokens': max(1, math.ceil(len(text.encode('utf-8')) / 3)),
        'token_estimate_note': 'Approximate UTF-8/3 estimate; model tokenization and billed usage can differ.',
    }


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _safe_integer(value, name, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError('INVALID_CONFIG: ' + name)
    return value


def _positive_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
        raise ValueError('INVALID_CONFIG: ' + name)
    return float(value)


def _config(config):
    if not isinstance(config, dict) or 'api_key' in config:
        raise ValueError('INVALID_CONFIG: use an environment variable, never a literal API key')
    normalized = {}
    for field in ('max_calls', 'token_budget', 'max_output_tokens'):
        normalized[field] = _safe_integer(config.get(field), field)
    normalized['max_cost'] = _positive_number(config.get('max_cost'), 'max_cost')
    for field in ('input_per_million', 'output_per_million'):
        value = config.get(field)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise ValueError('INVALID_CONFIG: ' + field)
        normalized[field] = float(value)
    model, env = config.get('model'), config.get('api_key_env')
    if not isinstance(model, str) or not model.strip() or len(model) > 200:
        raise ValueError('INVALID_CONFIG: model')
    if not isinstance(env, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', env):
        raise ValueError('INVALID_CONFIG: api_key_env')
    base = config.get('base_url')
    if not isinstance(base, str):
        raise ValueError('INVALID_CONFIG: base_url')
    url = urlsplit(base)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('INVALID_CONFIG: base_url')
    try:
        loopback = ipaddress.ip_address(url.hostname).is_loopback
    except ValueError:
        loopback = url.hostname.lower() == 'localhost'
    if url.scheme == 'http' and not loopback:
        raise ValueError('INVALID_CONFIG: remote endpoints require HTTPS')
    normalized.update(model=model, api_key_env=env, base_url=base.rstrip('/'))
    # Explicit opt-ins only. Generic OpenAI-compatible providers may reject
    # provider-specific fields, so no such field is sent by default.
    if 'thinking' in config:
        if config['thinking'] not in ('enabled', 'disabled'):
            raise ValueError('INVALID_CONFIG: thinking')
        normalized['thinking'] = config['thinking']
    if 'json_mode' in config:
        if type(config['json_mode']) is not bool:
            raise ValueError('INVALID_CONFIG: json_mode')
        normalized['json_mode'] = config['json_mode']
    normalized['timeout'] = _positive_number(config.get('timeout', 60), 'timeout')
    if normalized['timeout'] > 120:
        raise ValueError('INVALID_CONFIG: timeout must be at most 120 seconds')
    return normalized


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def ledger_directory(service, session_id):
    resolver = getattr(service, 'model_ledger_dir', None)
    return Path(resolver(session_id) if resolver else service.session_dir(session_id))


def load_config(service, session_id):
    """Read pinned non-secret configuration for UI/CLI restart; never creates a ledger."""
    path = ledger_directory(service, session_id) / 'model.sqlite'
    if not path.is_file():
        return None
    try:
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            row = db.execute('SELECT config FROM settings WHERE id=1').fetchone()
        finally:
            db.close()
        return json.loads(row[0]) if row else None
    except (sqlite3.Error, ValueError, TypeError):
        raise ValueError('MODEL_LEDGER_UNREADABLE: preserve ledger and inspect locally') from None


class IndependentPlayer:
    def __init__(self, service, session_id, config):
        self.service, self.session_id = service, session_id
        self.config = _config(config)
        self.directory = Path(service.session_dir(session_id))
        self.core = validate_core((self.directory / 'core.txt').read_text(encoding='utf-8'))['content']
        initial = service.view(session_id)
        if initial.get('mode') != 'independent':
            raise ValueError('INDEPENDENT_MODE_REQUIRED')
        self.play_style = initial.get('play_style', 'legacy_unspecified')
        if self.play_style not in ('legacy_unspecified', 'immersive', 'self_aware'):
            raise ValueError('INVALID_PLAY_STYLE')
        self._style_prompt = (style_instructions(self.play_style)
                              if self.play_style != 'legacy_unspecified' else '')
        self.family_id = initial.get('budget_family_id', session_id)
        self.db_path = ledger_directory(service, session_id) / 'model.sqlite'
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, config TEXT NOT NULL, core_hash TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY, request_id TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                reserved_tokens INTEGER NOT NULL, reserved_cost REAL NOT NULL,
                charged_tokens INTEGER NOT NULL, charged_cost REAL NOT NULL,
                prompt_bound INTEGER NOT NULL, result TEXT, usage TEXT, error TEXT)''')
            db.execute('BEGIN IMMEDIATE')
            columns = {row[1] for row in db.execute('PRAGMA table_info(calls)')}
            if 'session_id' not in columns:
                db.execute('ALTER TABLE calls ADD COLUMN session_id TEXT')
                # Existing calls belong to the original family/root session.
                db.execute('UPDATE calls SET session_id=? WHERE session_id IS NULL', (self.family_id,))
            existing = db.execute('SELECT config,core_hash FROM settings WHERE id=1').fetchone()
            # Budget/rate/model changes require a new independent session. Restarting
            # the process cannot silently reset accounting or reinterpret old costs.
            pinned = {k: v for k, v in self.config.items() if k != 'timeout'}
            # Existing v0.1 sessions retain their exact hash and request prefix.
            # New sessions pin the decision style and its precise instructions,
            # so changing a style or upgrading its prompt cannot reset accounting
            # or silently change the basis of a continuing game.
            identity = (self.core if self.play_style == 'legacy_unspecified' else
                        _dump({'core': self.core, 'play_style': self.play_style,
                               'instructions': self._style_prompt, 'prompt_version': PROMPT_VERSION}))
            core_hash = hashlib.sha256(identity.encode('utf-8')).hexdigest()
            if existing and existing != (_dump(pinned), core_hash):
                raise ValueError('MODEL_CONFIG_OR_CORE_CHANGED: create a new session; old ledger is preserved')
            db.execute('INSERT OR IGNORE INTO settings VALUES (1,?,?)', (_dump(pinned), core_hash))
        marker = getattr(service, 'mark_budget_initialized', None)
        if marker:
            marker(session_id)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=0)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def status(self):
        with self._db() as db:
            rows = db.execute('SELECT id,request_id,status,created_at,updated_at,charged_tokens,charged_cost,usage,error,session_id FROM calls ORDER BY rowid').fetchall()
        calls = [dict(zip(('id', 'request_id', 'status', 'created_at', 'updated_at', 'charged_tokens', 'charged_cost', 'usage', 'error', 'session_id'), row)) for row in rows]
        for item in calls:
            item['usage'] = json.loads(item['usage']) if item['usage'] else None
        return {
            'session_id': self.session_id, 'calls': calls, 'call_count': len(calls),
            'budget_family_id': self.family_id, 'budget_scope': 'all branches in this save family',
            'accounted_tokens': sum(row['charged_tokens'] for row in calls),
            'accounted_cost': sum(row['charged_cost'] for row in calls),
            'limits': {k: self.config[k] for k in ('max_calls', 'token_budget', 'max_cost')},
            'cost_basis': 'User-declared prices; unresolved calls retain worst-case reservations. Not an official bill.',
            'blocked': any(row['status'] in ('reserved', 'unknown', 'overrun', 'ready') for row in calls),
            'pending_ready_session_ids': sorted({row['session_id'] for row in calls if row['status'] == 'ready'}),
        }

    def acknowledge_unknown(self, call_id):
        """Explicit operator action after checking the provider; never refunds a reservation."""
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE calls SET status='acknowledged',updated_at=? WHERE id=? AND session_id=? AND status IN ('reserved','unknown','overrun')", (now(), call_id, self.session_id)).rowcount
            if not changed:
                raise ValueError('NO_UNRESOLVED_CALL')
        return self.status()

    def messages(self, view=None):
        """Build a visible transcript, isolated per character for immersion.

        The service supplies the bounded player projection. We also verify the
        actor tags here: an accidentally supplied observer view must not become
        a model request. Native role prompts and hidden state are never used.
        """
        view = self.service.view(self.session_id) if view is None else view
        self._check_style(view)
        system = SYSTEM + self.core
        if self.play_style != 'legacy_unspecified':
            system += '\n\nDecision style (fixed for this saved game):\n' + self._style_prompt
        messages = [{'role': 'system', 'content': system}]
        actor = None
        if self.play_style == 'immersive':
            actors = (view.get('perspective') or {}).get('controlled_characters', [])
            if not isinstance(actors, list) or len(actors) != 1 or not isinstance(actors[0], str) or not actors[0]:
                raise ValueError('ROLE_PERSPECTIVE_UNAVAILABLE')
            actor = actors[0]
            # This opening belongs to the character's own stream and is stable
            # when switching away and back. It does not rewrite the system head.
            messages.append({'role': 'user', 'content': _dump({
                'decision_perspective': 'immersive', 'controlled_character': actor,
                'scope': 'Only this character\'s already visible game information follows. '
                         'The player identity remains separate from the fictional character.'})})
        last_scene, last_options = None, []
        for event in view.get('history', []):
            if actor is not None and event.get('controlled_characters') != [actor]:
                raise ValueError('ROLE_PERSPECTIVE_UNAVAILABLE')
            kind = event.get('type')
            if kind == 'node_shown':
                options = [{'number': item.get('number', n), 'text': item['text']} for n, item in enumerate(event.get('choices', []), 1)]
                scene = {'chapter': event.get('chapter'), 'context': event.get('context', ''), 'choices': options}
                messages.append({'role': 'user', 'content': _dump(scene)})
                last_scene, last_options = scene, options
            elif kind == 'decision':
                chosen = event.get('choice')
                if type(chosen) is not int:
                    chosen = next((item['number'] for item in last_options if item['text'] == event.get('choice_text')), None)
                public = {'choice': chosen, 'public_reason': event.get('reasoning', '') or ''}
                messages.append({'role': 'assistant', 'content': _dump(public)})
            elif kind == 'chapter_end':
                ending = event.get('ending', {})
                messages.append({'role': 'user', 'content': _dump({'fictional_result': {'title': ending.get('title'), 'narrative': ending.get('narrative')}})})
        current = view.get('current')
        if current:
            if actor is not None and current.get('controlled_characters') != [actor]:
                raise ValueError('ROLE_PERSPECTIVE_UNAVAILABLE')
            scene = {'chapter': current.get('chapter'), 'context': current.get('context', ''), 'choices': [{'number': item.get('number', n), 'text': item['text']} for n, item in enumerate(current['choices'], 1)]}
            if scene != last_scene:
                messages.append({'role': 'user', 'content': _dump(scene)})
        return messages

    def _check_style(self, view):
        if view.get('play_style', 'legacy_unspecified') != self.play_style:
            raise ValueError('MODEL_CONFIG_OR_CORE_CHANGED: saved play style changed')

    def _reserve(self, request_id, messages):
        # Byte-length plus generous per-message overhead is a conservative bound
        # for ordinary byte-based tokenizers. Usage beyond it stops the session.
        prompt_bound = len(_dump(messages).encode('utf-8')) + 1024 + 128 * len(messages)
        tokens = prompt_bound + self.config['max_output_tokens']
        cost = (prompt_bound * self.config['input_per_million'] + self.config['max_output_tokens'] * self.config['output_per_million']) / 1_000_000
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM calls WHERE status IN ('reserved','unknown','overrun','ready')").fetchone():
                raise ValueError('UNRESOLVED_MODEL_CALL: inspect ledger; do not resend blindly')
            # A concurrent caller can have read the old scene before another
            # caller applied its answer. Revalidate the receipt in the ledger
            # before reserving a second paid request for that stale scene.
            if db.execute("SELECT 1 FROM calls WHERE request_id=? AND status='applied'", (request_id,)).fetchone():
                raise ValueError('STALE_REQUEST: scene already has an applied model answer; read the game again')
            count, used_tokens, used_cost = db.execute('SELECT COUNT(*),COALESCE(SUM(charged_tokens),0),COALESCE(SUM(charged_cost),0) FROM calls').fetchone()
            if count >= self.config['max_calls'] or used_tokens + tokens > self.config['token_budget'] or used_cost + cost > self.config['max_cost']:
                raise ValueError('MODEL_BUDGET_EXHAUSTED')
            call_id = str(uuid.uuid4())
            timestamp = now()
            db.execute('''INSERT INTO calls (id,request_id,status,created_at,updated_at,reserved_tokens,reserved_cost,
                       charged_tokens,charged_cost,prompt_bound,result,usage,error,session_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (call_id, request_id, 'reserved', timestamp, timestamp, tokens, cost, tokens, cost, prompt_bound, None, None, None, self.session_id))
        return call_id, prompt_bound

    def _update(self, call_id, **fields):
        allowed = {'status', 'charged_tokens', 'charged_cost', 'result', 'usage', 'error'}
        if not fields.keys() <= allowed:
            raise ValueError('INVALID_LEDGER_UPDATE')
        fields['updated_at'] = now()
        with self._db() as db:
            db.execute('UPDATE calls SET ' + ','.join(name + '=?' for name in fields) + ' WHERE id=?', (*fields.values(), call_id))

    def _finish_ready(self):
        with self._db() as db:
            row = db.execute("SELECT id,request_id,result FROM calls WHERE status='ready' AND session_id=? ORDER BY rowid LIMIT 1", (self.session_id,)).fetchone()
        if not row:
            return None
        result = json.loads(row[2])
        # The game implements idempotent request receipts. A crash between game
        # commit and this update resumes from the saved answer without a new API call.
        view = self.service.choose(self.session_id, row[1], result['choice'], result['public_reason'])
        self._update(row[0], status='applied')
        return {'status': 'applied', 'call_id': row[0], 'view': view, 'budget': self.status()}

    def step(self):
        view = self.service.view(self.session_id)
        self._check_style(view)
        ready = self._finish_ready()
        if ready is not None:
            return ready
        if view.get('status') != 'waiting' or not view.get('current'):
            return {'status': view.get('status'), 'view': view, 'budget': self.status()}
        api_key = os.environ.get(self.config['api_key_env'])
        if not api_key:
            raise ValueError('MODEL_API_KEY_MISSING: set the configured environment variable')
        messages = self.messages(view)
        call_id, prompt_bound = self._reserve(view['current']['request_id'], messages)
        body = {'model': self.config['model'], 'messages': messages, 'max_tokens': self.config['max_output_tokens'], 'stream': False}
        if 'thinking' in self.config:
            body['thinking'] = {'type': self.config['thinking']}
        if self.config.get('json_mode'):
            body['response_format'] = {'type': 'json_object'}
        endpoint = self.config['base_url']
        if not endpoint.endswith('/chat/completions'):
            endpoint += '/chat/completions'
        request = Request(endpoint, data=_dump(body).encode('utf-8'), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + api_key}, method='POST')
        try:
            with build_opener(_NoRedirect()).open(request, timeout=self.config['timeout']) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError('RESPONSE_TOO_LARGE')
                payload = json.loads(raw)
        except Exception as error:
            # Never persist server bodies, URL/user data, or exception text: those
            # may echo keys, identity documents, and private messages.
            code = ('HTTP_' + str(error.code)) if isinstance(error, HTTPError) else 'TRANSPORT_OR_RESPONSE_UNKNOWN'
            self._update(call_id, status='unknown', error=code)
            raise ValueError('MODEL_RESULT_UNKNOWN: inspect provider and ledger before acknowledging') from None
        usage = payload.get('usage') if isinstance(payload, dict) else None
        if not isinstance(usage, dict) or type(usage.get('prompt_tokens')) is not int or type(usage.get('completion_tokens')) is not int or min(usage['prompt_tokens'], usage['completion_tokens']) < 0:
            self._update(call_id, status='unknown', error='USAGE_UNKNOWN')
            raise ValueError('MODEL_USAGE_UNKNOWN: reservation retained')
        prompt, completion = usage['prompt_tokens'], usage['completion_tokens']
        # Only normalized numeric usage is retained; arbitrary provider extensions
        # can contain private content and are never copied into the ledger.
        safe_usage = {'prompt_tokens': prompt, 'completion_tokens': completion, 'observed_at': now()}
        cached = usage.get('prompt_tokens_details', {}).get('cached_tokens') if isinstance(usage.get('prompt_tokens_details'), dict) else usage.get('prompt_cache_hit_tokens')
        if type(cached) is int and 0 <= cached <= prompt:
            safe_usage['cached_input_tokens'] = cached
            safe_usage['latest_cache_hit_ratio'] = cached / prompt if prompt else None
        cost = (prompt * self.config['input_per_million'] + completion * self.config['output_per_million']) / 1_000_000
        if prompt > prompt_bound or completion > self.config['max_output_tokens']:
            with self._db() as db:
                reserved = db.execute('SELECT reserved_tokens,reserved_cost FROM calls WHERE id=?', (call_id,)).fetchone()
            self._update(call_id, status='overrun', charged_tokens=max(prompt + completion, reserved[0]), charged_cost=max(cost, reserved[1]), usage=_dump(safe_usage), error='PROVIDER_RESERVATION_OVERRUN')
            raise ValueError('MODEL_USAGE_EXCEEDED_RESERVATION: stopped for operator review')
        self._update(call_id, charged_tokens=prompt + completion, charged_cost=cost, usage=_dump(safe_usage))
        try:
            response_message = payload['choices'][0]['message']
            answer = json.loads(response_message['content'])
            choice = answer['choice']
            reason = answer.get('public_reason', '')
            numbers = [item.get('number', n) for n, item in enumerate(view['current']['choices'], 1)]
            if type(choice) is not int or choice not in numbers or not isinstance(reason, str) or len(reason) > 2000:
                raise ValueError('INVALID_MODEL_CHOICE')
        except (ValueError, TypeError, KeyError, IndexError):
            self._update(call_id, status='rejected', error='INVALID_MODEL_CHOICE')
            raise ValueError('INVALID_MODEL_CHOICE: game unchanged; call accounted') from None
        result = {'choice': choice, 'public_reason': reason}
        self._update(call_id, status='ready', result=_dump(result))
        return self._finish_ready()

    def run(self):
        """Advance until complete/paused/error; every attempted call is durably bounded."""
        while True:
            result = self.step()
            if result['status'] != 'applied' or result['view'].get('status') != 'waiting':
                return result

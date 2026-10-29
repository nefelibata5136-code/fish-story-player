"""Durable human/Agent player seam around the repository's native campaign runner."""
import hashlib
import json
import random
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
NATIVE = REPO / 'vendor' / 'native'
sys.path.insert(0, str(NATIVE))
from campaign_runner import run_campaign


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(paths):
    files = [*paths, *NATIVE.glob('*.py'), Path(__file__)]
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(path.name.encode()); h.update(path.read_bytes())
    return h.hexdigest()


class Waiting(BaseException):
    """Normal suspension, outside the native runner's failure handler."""


class Player:
    model = 'external-player'
    resolved_model = None

    def __init__(self, run, history):
        self.run, self.history = run, history
        self.index, self.pending = 0, None
        self.chapter = None
        self.node_ref = None
        self.internal_outcomes = []

    def event(self, e):
        kind = e['type']
        if kind == 'chapter_start':
            c = e['chapter']
            self.chapter = {k: c[k] for k in ('chapter_number', 'title', 'title_zh', 'protagonist') if k in c}
        elif kind == 'node_shown':
            self.node_ref = hashlib.sha256(f"{self.chapter}:{e['node_id']}".encode()).hexdigest()[:20]
            self.history.append({'type': 'node_shown', 'chapter': self.chapter,
                                 'node_ref': self.node_ref,
                                 'context': e['context'], 'choices': [{'text': c['text']} for c in e['choices']]})
        elif kind == 'decision':
            answer = self.run['answers'][self.index - 1]
            self.history.append({'type': 'decision', 'chapter': self.chapter, 'node_ref': self.node_ref,
                                 'request_id': answer['request_id'], 'occurred_at': answer['time'],
                                 'choice': answer['choice'], 'choice_text': e['choice_text'], 'reasoning': e['reasoning']})
            self.internal_outcomes.append({k: e.get(k) for k in ('node_id', 'resolution_result', 'effects_applied', 'state_after')})
        elif kind == 'chapter_end':
            for ending in e.get('all_endings') or [e['ending']]:
                self.history.append({'type': 'chapter_end', 'chapter': self.chapter, 'ending': {
                    'title': ending['title'], 'narrative': ending['narrative']}})

    def choose(self, node_id, context, choices, messages):
        # No hidden node IDs, system state, effects, future scenes or full prompts in public view.
        public = {'chapter': self.chapter, 'node_ref': self.node_ref, 'context': context,
                  'choices': [{'number': i, 'text': c['text']} for i, c in enumerate(choices, 1)]}
        digest = hashlib.sha256(json.dumps(public, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        request_id = hashlib.sha256(f"{self.run['id']}:{self.index}:{digest}".encode()).hexdigest()[:24]
        self.pending = {'request_id': request_id, **public}
        if self.index >= len(self.run['answers']):
            raise Waiting()
        answer = self.run['answers'][self.index]
        if answer['request_id'] != request_id:
            raise ValueError('REPLAY_MISMATCH: preserve records and inspect engine version')
        self.index += 1
        raw = json.dumps({'choice': answer['choice'], 'reasoning': answer['reason']}, ensure_ascii=False)
        return {'choice_id': choices[answer['choice'] - 1]['id'], 'reasoning': answer['reason'], 'raw': raw}


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS games (owner TEXT PRIMARY KEY, data TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.directory / 'games.sqlite', timeout=0)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def start(self, owner, paths, difficulty='casual'):
        paths = [str(Path(p).resolve()) for p in paths]
        run = {'id': str(uuid.uuid4()), 'paths': paths, 'difficulty': difficulty,
               'fingerprint': fingerprint([Path(p) for p in paths]), 'seed': uuid.uuid4().int,
               'answers': [], 'notes': [], 'paused': False, 'created_at': now()}
        with self.connect() as db:
            db.execute('INSERT INTO games VALUES (?,?)', (owner, json.dumps(run, ensure_ascii=False)))
        return self.view(owner)

    def replay(self, run):
        paths = [Path(p) for p in run['paths']]
        if fingerprint(paths) != run['fingerprint']:
            raise ValueError('ENGINE_CHANGED: existing records preserved; restore pinned source before continuing')
        history = []
        player = Player(run, history)
        try:
            run_campaign(paths, player, difficulty=run['difficulty'], on_event=player.event,
                         rng=random.Random(run['seed']))
            current, status = None, 'complete'
        except Waiting:
            current, status = player.pending, 'waiting'
        self._internal_outcomes = player.internal_outcomes
        return {'run_id': run['id'], 'status': 'paused' if run['paused'] else status,
                'current': current, 'history': history, 'notes': run['notes'],
                'accepted_choices': len(run['answers']),
                'records': [a['receipt'] for a in run['answers'] if 'receipt' in a],
                'updated': run.get('updated_at', run['created_at'])}

    def load(self, db, owner):
        row = db.execute('SELECT data FROM games WHERE owner=?', (owner,)).fetchone()
        if row is None:
            raise ValueError('NO_GAME')
        return json.loads(row[0])

    def view(self, owner):
        with self.connect() as db:
            return self.replay(self.load(db, owner))

    def mutate(self, owner, action, value):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run = self.load(db, owner)
            if action == 'choose':
                rid, choice, reason = value.get('request_id'), value.get('choice'), value.get('reason')
                if type(choice) is not int or not isinstance(reason, str) or len(reason) > 2000:
                    raise ValueError('INVALID_ANSWER')
                for old in run['answers']:
                    if old['request_id'] == rid:
                        if old['choice'] != choice or old['reason'] != reason:
                            raise ValueError('ANSWER_ALREADY_ACCEPTED')
                        return self.replay(run)  # Idempotent receipt, even after a pause/restart.
                if run['paused']:
                    raise ValueError('GAME_PAUSED')
                before = self.replay(run)
                current = before['current']
                if current is None or rid != current['request_id']:
                    raise ValueError('STALE_REQUEST')
                if not 1 <= choice <= len(current['choices']):
                    raise ValueError('CHOICE_NOT_AVAILABLE')
                timestamp = now()
                answer = {'request_id': rid, 'choice': choice, 'reason': reason, 'time': timestamp}
                run['answers'].append(answer)
                after = self.replay(run)
                # Events after this accepted decision are the actual visible consequences.
                index = next(i for i, e in enumerate(after['history'])
                             if e.get('type') == 'decision' and e.get('request_id') == rid)
                receipt = {'record_id': f"{run['id']}:{rid}", 'source': 'fish-story-player',
                           'occurred_at': timestamp, 'observed_at': timestamp, 'deleted': False,
                           'chapter': current['chapter'], 'node_ref': current['node_ref'],
                           'request_id': rid, 'scene': current['context'], 'visible_options': current['choices'],
                           'choice': choice, 'choice_text': current['choices'][choice - 1]['text'],
                           'public_reason': reason, 'outcome': after['history'][index + 1:],
                           'after': {'status': after['status'], 'accepted_choices': after['accepted_choices'],
                                     'next_request_id': (after['current'] or {}).get('request_id'),
                                     'save_location': 'games.sqlite'}}
                receipt['content_hash'] = hashlib.sha256(json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                answer['receipt'] = receipt
                # Retained locally for reproducibility; never part of player-facing projection/export.
                answer['internal_outcome'] = self._internal_outcomes[-1]
            elif action in ('pause', 'resume'):
                run['paused'] = action == 'pause'
            elif action == 'note':
                content = value.get('text')
                note_id = value.get('note_id')
                if not isinstance(content, str) or not content.strip() or not isinstance(note_id, str) or not note_id:
                    raise ValueError('INVALID_NOTE')
                for old in run['notes']:
                    if old['id'] == note_id:
                        if old['text'] != content:
                            raise ValueError('NOTE_ALREADY_SAVED')
                        return self.replay(run)
                run['notes'].append({'id': note_id, 'text': content, 'time': now(), 'source': '本人提交'})
            else:
                raise ValueError('INVALID_ACTION')
            run['updated_at'] = now()
            projection = self.replay(run)  # Validate before commit; rollback on failure.
            db.execute('UPDATE games SET data=? WHERE owner=?', (json.dumps(run, ensure_ascii=False), owner))
            return projection

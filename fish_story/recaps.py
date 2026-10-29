"""Private, player-authored chapter recaps. No model or generated prose lives here."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sqlite3
import uuid
from pathlib import Path

from .engine import now
from .styles import decorate, player_projection

DEFAULT_MAX_CHARACTERS = 5000
MAX_CHARACTERS = 1_000_000


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8', newline='') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class RecapStore:
    def __init__(self, service):
        self.service = service

    def _observer(self, session_id, *, store=None, run=None):
        # Do not call service.view/observe: those may themselves decorate recap metadata.
        meta = self.service._meta(session_id)
        store = store or self.service._store(session_id)
        raw = store.replay(run) if run is not None else store.view('player')
        return decorate({**meta, **raw}, self.service.session_dir(session_id))

    def _entries(self, session_id):
        path = self.service.session_dir(session_id) / 'recaps.sqlite'
        if not path.is_file():
            return []
        try:
            db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                values = [json.loads(row[0]) for row in db.execute('SELECT data FROM versions ORDER BY ordinal')]
                self._validate_entries(self.service.session_dir(session_id), values)
                return values
            finally:
                db.close()
        except ValueError as error:
            if str(error) == 'RECAP_STORAGE_CHANGED':
                raise
            raise ValueError('RECAP_STORAGE_INVALID') from None
        except sqlite3.Error:
            raise ValueError('RECAP_STORAGE_INVALID') from None

    def _validate_entries(self, directory, entries):
        try:
            for entry in entries:
                if (str(uuid.UUID(entry['id'])) != entry['id'] or not isinstance(entry['actor'], str)
                        or type(entry['revision']) is not int or entry['revision'] < 1
                        or type(entry['max_characters']) is not int or not 1 <= entry['max_characters'] <= MAX_CHARACTERS
                        or not isinstance(entry['text'], str) or type(entry['characters']) is not int
                        or len(entry['text']) != entry['characters']
                        or len(entry['text']) > entry['max_characters'] or _hash(entry['text']) != entry['content_hash']):
                    raise ValueError()
                path = Path(directory) / self._relative(entry)
                if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['content_hash']:
                    raise ValueError()
        except (ValueError, TypeError, KeyError, OSError, UnicodeError):
            raise ValueError('RECAP_STORAGE_CHANGED') from None

    @staticmethod
    def _all_tasks(observer):
        if observer.get('recap_version') != 1:
            return []
        chapters, choice_count = {}, 0
        history = observer['history']
        for index, event in enumerate(history):
            choice_count += int(event['type'] == 'decision')
            if event['type'] != 'chapter_end':
                continue
            number = event['chapter']['chapter_number']
            chapters[number] = {'chapter_number': number, 'choice_count': choice_count,
                                'end_event_index': index}
        result = []
        for number, boundary in chapters.items():
            material = [e for e in history[:boundary['end_event_index'] + 1]
                        if e.get('chapter', {}).get('chapter_number') == number]
            actors = ['player']
            if observer.get('play_style') == 'immersive':
                actors = list(dict.fromkeys(e['controlled_characters'][0] for e in material
                                           if len(e.get('controlled_characters', [])) == 1))
            for actor in actors:
                visible = [e for e in material if actor == 'player' or e.get('controlled_characters') == [actor]]
                # Request IDs change when a save is branched; the actual reached material does not.
                stable = [{k: v for k, v in e.items() if k not in ('request_id', 'occurred_at')}
                          for e in visible]
                identity = {**boundary, 'actor': actor, 'material': stable}
                result.append({**boundary, 'actor': actor, 'task_id': 'recap-' + _hash(_dump(identity))[:24]})
        return result

    def _pending(self, observer, entries):
        done = {entry.get('task_id') for entry in entries if entry.get('task_id')}
        return [task for task in self._all_tasks(observer) if task['task_id'] not in done]

    def tasks(self, session_id):
        return self._pending(self._observer(session_id), self._entries(session_id))

    @staticmethod
    def _actor(observer, pending, actor=None):
        if observer.get('play_style') != 'immersive':
            if actor not in (None, 'player'):
                raise ValueError('INVALID_RECAP_ACTOR')
            return 'player'
        known = {e['controlled_characters'][0] for e in observer['history']
                 if len(e.get('controlled_characters', [])) == 1}
        current = observer.get('perspective', {}).get('controlled_characters', [])
        known.update(current)
        if actor is None:
            actor = pending[0]['actor'] if pending else (current[0] if len(current) == 1 else None)
        if actor is not None and actor not in known:
            raise ValueError('INVALID_RECAP_ACTOR')
        return actor

    @staticmethod
    def _relative(entry):
        actor_key = _hash(entry['actor'])[:24]
        return Path('recaps') / actor_key / (str(entry['revision']).zfill(6) + '-' + entry['id'] + '.md')

    def _published(self, directory, entry):
        value = copy.deepcopy(entry)
        value['file_path'] = str(Path(directory) / self._relative(entry))
        value['latest_file_path'] = str(Path(directory) / 'recaps' / _hash(entry['actor'])[:24] / 'latest.md')
        return value

    def read(self, session_id, actor=None):
        observer, entries = self._observer(session_id), self._entries(session_id)
        pending = self._pending(observer, entries)
        actor = self._actor(observer, pending, actor)
        own = [entry for entry in entries if entry['actor'] == actor]
        latest = own[-1] if own else None
        text = latest['text'] if latest else ''
        result = {'actor': actor, 'text': text, 'characters': len(text),
                  'max_characters': latest['max_characters'] if latest else DEFAULT_MAX_CHARACTERS,
                  'revision': latest['revision'] if latest else 0, 'file_path': None,
                  'pending_tasks': pending, 'task': pending[0] if pending else None,
                  'current_task': pending[0] if pending else None}
        if latest:
            result.update({key: value for key, value in self._published(self.service.session_dir(session_id), latest).items()
                           if key in ('file_path', 'latest_file_path')})
        return result

    def entries(self, session_id, actor=None):
        values = self._entries(session_id)
        if actor is not None:
            observer = self._observer(session_id)
            self._actor(observer, self._pending(observer, values), actor)
            values = [entry for entry in values if entry['actor'] == actor]
        return [self._published(self.service.session_dir(session_id), entry) for entry in values]

    def task_view(self, session_id, task_id):
        observer = self._observer(session_id)
        task = next((task for task in self._all_tasks(observer) if task['task_id'] == task_id), None)
        if task is None:
            raise ValueError('RECAP_STALE_TASK')
        end = task['end_event_index']
        value = copy.deepcopy(observer)
        value.update(current=None, history=value['history'][:end + 1], notes=[], status='chapter_complete',
                     accepted_choices=task['choice_count'])
        allowed = {_dump(event) for event in value['history']}
        records = []
        for record in value['records'][:task['choice_count']]:
            # Receipts can contain the next chapter's first scene in their outcome.
            record['outcome'] = [event for event in record.get('outcome', []) if _dump(event) in allowed]
            record.get('after', {}).pop('next_request_id', None)
            records.append(record)
        value['records'] = records
        actor = task['actor']
        if observer.get('play_style') == 'immersive':
            value['perspective']['controlled_characters'] = [actor]
        indices = [i for i, event in enumerate(value['history'])
                   if actor == 'player' or event.get('controlled_characters') == [actor]]
        value = player_projection(value)
        value.update(task=task, task_id=task_id, actor=actor, chapter_number=task['chapter_number'],
                     history_event_indices=indices, current=None)
        # Previous authored versions only; never expose a later chapter recap when rereading an old task.
        prior = [entry for entry in self._entries(session_id) if entry['actor'] == actor
                 and entry['end_event_index'] < end and entry['choice_count'] <= task['choice_count']]
        previous = prior[-1] if prior else None
        value['previous_recap'] = {'text': previous['text'] if previous else '',
                                   'max_characters': previous['max_characters'] if previous else DEFAULT_MAX_CHARACTERS,
                                   'characters': len(previous['text']) if previous else 0,
                                   'revision': previous['revision'] if previous else 0}
        return value

    @staticmethod
    def _schema(db):
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS versions (ordinal INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, data TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, arguments TEXT NOT NULL, version_id TEXT NOT NULL)')
        db.commit()

    def update(self, session_id, text, task_id=None, max_characters=None, operation_id=None, expected_revision=None):
        if not isinstance(text, str) or not text.strip() or '\x00' in text:
            raise ValueError('INVALID_RECAP_TEXT')
        try:
            text.encode('utf-8')
        except UnicodeError:
            raise ValueError('INVALID_RECAP_TEXT') from None
        if max_characters is not None and (type(max_characters) is not int or not 1 <= max_characters <= MAX_CHARACTERS):
            raise ValueError('INVALID_RECAP_LIMIT')
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise ValueError('RECAP_STALE_REVISION')
        operation_id = str(uuid.uuid4()) if operation_id is None else operation_id
        if not isinstance(operation_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', operation_id):
            raise ValueError('INVALID_OPERATION_ID')
        arguments = _hash(_dump({'text': text, 'task_id': task_id, 'max_characters': max_characters,
                                 'expected_revision': expected_revision}))
        directory = self.service.session_dir(session_id)
        store = self.service._store(session_id)
        db = sqlite3.connect(directory / 'recaps.sqlite', timeout=0)
        try:
            self._schema(db)
            with store.connect() as game_db:
                # Serialize against choice submission as well as concurrent recap updates.
                game_db.execute('BEGIN IMMEDIATE')
                db.execute('BEGIN IMMEDIATE')
                existing = db.execute('SELECT arguments,version_id FROM operations WHERE id=?', (operation_id,)).fetchone()
                if existing:
                    if existing[0] != arguments:
                        raise ValueError('OPERATION_CONFLICT')
                    entry = json.loads(db.execute('SELECT data FROM versions WHERE id=?', (existing[1],)).fetchone()[0])
                    self._validate_entries(directory, [entry])
                else:
                    observer = self._observer(session_id, store=store, run=store.load(game_db, 'player'))
                    entries = [json.loads(row[0]) for row in db.execute('SELECT data FROM versions ORDER BY ordinal')]
                    self._validate_entries(directory, entries)
                    pending = self._pending(observer, entries)
                    task = pending[0] if pending else None
                    if task_id is not None and (task is None or task['task_id'] != task_id):
                        raise ValueError('RECAP_STALE_TASK')
                    actor = task['actor'] if task else self._actor(observer, pending)
                    if actor is None:
                        raise ValueError('INVALID_RECAP_ACTOR')
                    own = [entry for entry in entries if entry['actor'] == actor]
                    previous = own[-1] if own else None
                    revision = previous['revision'] if previous else 0
                    if expected_revision is not None and expected_revision != revision:
                        raise ValueError('RECAP_STALE_REVISION')
                    limit = max_characters if max_characters is not None else (previous['max_characters'] if previous else DEFAULT_MAX_CHARACTERS)
                    if len(text) > limit:
                        raise ValueError('RECAP_TOO_LONG')
                    count = observer['accepted_choices']
                    end = task['end_event_index'] if task and task['choice_count'] == count else len(observer['history']) - 1
                    visible_count = sum(actor == 'player' or event.get('controlled_characters') == [actor]
                                        for event in observer['history'][:end + 1])
                    entry = {'id': str(uuid.uuid4()), 'actor': actor, 'revision': revision + 1,
                             'text': text, 'characters': len(text), 'max_characters': limit,
                             'content_hash': _hash(text), 'operation_id': operation_id,
                             'task_id': task['task_id'] if task else None,
                             'chapter_number': task['chapter_number'] if task else None,
                             'choice_count': count, 'end_event_index': end,
                             'authored_choice_count': count, 'authored_end_event_index': end,
                             'visible_history_count': visible_count, 'occurred_at': now()}
                    if task:
                        entry.update(task_choice_count=task['choice_count'], task_end_event_index=task['end_event_index'])
                    _atomic(directory / self._relative(entry), text)
                    db.execute('INSERT INTO versions(id,data) VALUES (?,?)', (entry['id'], _dump(entry)))
                    db.execute('INSERT INTO operations VALUES (?,?,?)', (operation_id, arguments, entry['id']))
                db.commit()
                # Keep the game lock until the projection is materialized, so two
                # concurrent authors cannot leave latest.md at an older revision.
                latest = json.loads(db.execute('SELECT data FROM versions WHERE json_extract(data,\'$.actor\')=? ORDER BY ordinal DESC LIMIT 1',
                                              (entry['actor'],)).fetchone()[0])
                _atomic(directory / 'recaps' / _hash(entry['actor'])[:24] / 'latest.md', latest['text'])
            return self._published(directory, entry)
        except sqlite3.OperationalError as error:
            db.rollback()
            if (getattr(error, 'sqlite_errorcode', -1) in (5, 6)
                or str(error).lower() in ('database is locked', 'database table is locked', 'database schema is locked')):
                raise ValueError('RECAP_BUSY') from None
            raise ValueError('RECAP_STORAGE_INVALID') from None
        finally:
            db.close()

    def snapshot(self, session_id, choice_count):
        if type(choice_count) is not int or choice_count < 0:
            raise ValueError('INVALID_CHOICE_COUNT')
        store = self.service._store(session_id)
        with store.connect() as db:
            run = store.load(db, 'player')
        if choice_count > len(run['answers']):
            raise ValueError('INVALID_CHOICE_COUNT')
        run['answers'] = run['answers'][:choice_count]
        end = len(store.replay(run)['history']) - 1
        entries = [entry for entry in self._entries(session_id)
                   if entry['choice_count'] <= choice_count and entry['authored_end_event_index'] <= end]
        ids = {entry['id'] for entry in entries}
        operations = []
        path = self.service.session_dir(session_id) / 'recaps.sqlite'
        if path.is_file():
            db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                operations = [list(row) for row in db.execute('SELECT id,arguments,version_id FROM operations') if row[2] in ids]
            finally:
                db.close()
        return {'schema': 'fish-story-recaps/1', 'entries': entries, 'operations': operations}

    @classmethod
    def restore(cls, directory, state):
        if state is None:
            return
        if state.get('schema') != 'fish-story-recaps/1':
            raise ValueError('RECAP_STORAGE_INVALID')
        directory = Path(directory)
        entries = state['entries']
        if not entries:
            return
        store = cls(None)
        db = sqlite3.connect(directory / 'recaps.sqlite', timeout=0)
        try:
            cls._schema(db)
            with db:
                for entry in entries:
                    if _hash(entry['text']) != entry['content_hash'] or len(entry['text']) > entry['max_characters']:
                        raise ValueError('RECAP_STORAGE_INVALID')
                    _atomic(directory / store._relative(entry), entry['text'])
                    db.execute('INSERT INTO versions(id,data) VALUES (?,?)', (entry['id'], _dump(entry)))
                for operation in state.get('operations', []):
                    db.execute('INSERT INTO operations VALUES (?,?,?)', operation)
            for actor in dict.fromkeys(entry['actor'] for entry in entries):
                latest = next(entry for entry in reversed(entries) if entry['actor'] == actor)
                _atomic(directory / 'recaps' / _hash(actor)[:24] / 'latest.md', latest['text'])
        finally:
            db.close()

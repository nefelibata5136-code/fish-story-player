"""Named local checkpoints and non-destructive replay branches.

The native engine stays unchanged. A branch preserves the source seed and actual
inherited choices, but rebinds run/request IDs and records their provenance.
No models or external services are called by this module.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .engine import Store, fingerprint, now
from .styles import ContextStore, content_hash, decorate


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 100 or '\x00' in value:
        raise ValueError('INVALID_SAVE_NAME')
    return value.strip()


def _operation_id(value):
    value = str(uuid.uuid4()) if value is None else value
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value):
        raise ValueError('INVALID_OPERATION_ID')
    return value


class SaveManager:
    def __init__(self, service):
        self.service = service

    @contextmanager
    def _db(self, session_id):
        path = self.service.session_dir(session_id) / 'points.sqlite'
        db = sqlite3.connect(path, timeout=0)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS points (id TEXT PRIMARY KEY, data TEXT NOT NULL, snapshot TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, kind TEXT NOT NULL, args TEXT NOT NULL, data TEXT NOT NULL, state TEXT NOT NULL)')
            with db:
                yield db
        finally:
            db.close()

    def _read_run(self, session_id):
        store = self.service._store(session_id)
        with store.connect() as db:
            run = store.load(db, 'player')
        # Verifies pinned story and engine bytes. No source game write occurs.
        projection = store.replay(run)
        return store, run, projection

    @staticmethod
    def _count(value, total):
        if type(value) is not int or not 0 <= value <= total:
            raise ValueError('INVALID_SAVE_POINT')
        return value

    def _snapshot(self, session_id, count=None):
        store, run, _ = self._read_run(session_id)
        count = len(run['answers']) if count is None else self._count(count, len(run['answers']))
        run['answers'] = run['answers'][:count]
        # Legacy notes have no reliable choice locator; keep them only in source.
        run['notes'] = []
        projection = store.replay(run)
        directory = self.service.session_dir(session_id)
        core = directory / 'core.txt'
        snapshot = {'run': run, 'meta': copy.deepcopy(self.service._meta(session_id)),
                    'core_hex': core.read_bytes().hex() if core.exists() else None,
                    'source_session_id': session_id, 'choice_count': count,
                    'captured_at': now()}
        return snapshot, projection

    @staticmethod
    def _location(projection):
        current = projection.get('current')
        if current:
            return current.get('chapter'), current.get('node_ref')
        last = next((e for e in reversed(projection['history']) if e['type'] == 'node_shown'), {})
        return last.get('chapter'), last.get('node_ref')

    @staticmethod
    def _args(kind, value):
        return hashlib.sha256(_dump({'kind': kind, **value}).encode()).hexdigest()

    @staticmethod
    def _existing(db, operation_id, kind, args):
        row = db.execute('SELECT kind,args,data,state FROM operations WHERE id=?', (operation_id,)).fetchone()
        if row is None:
            return None
        if row[0] != kind or row[1] != args:
            raise ValueError('OPERATION_CONFLICT')
        return json.loads(row[2]), row[3]

    def list_points(self, session_id):
        store, run, projection = self._read_run(session_id)
        decorated = decorate({**self.service._meta(session_id), **projection}, self.service.session_dir(session_id))
        points = []
        total = len(run['answers'])
        for count in range(total + 1):
            if count < total:
                receipt = run['answers'][count].get('receipt') or {}
                chapter, node = receipt.get('chapter'), receipt.get('node_ref')
                actors = receipt.get('controlled_characters', [])
            else:
                chapter, node = self._location(projection)
                actors = (decorated.get('perspective') or {}).get('controlled_characters', [])
            moment = run['created_at'] if count == 0 else run['answers'][count - 1]['time']
            points.append({'id': f'auto:{count}', 'name': '开始位置' if count == 0 else f'第 {count} 次选择后',
                           'kind': 'automatic', 'choice_count': count, 'created_at': moment,
                           'current_chapter': chapter, 'current_node_ref': node,
                           'controlled_characters': actors, 'status': projection['status'] if count == total else 'waiting'})
        db_path = self.service.session_dir(session_id) / 'points.sqlite'
        if db_path.exists():
            db = sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                points.extend(json.loads(row[0]) for row in db.execute('SELECT data FROM points ORDER BY rowid'))
            finally:
                db.close()
        return {'session_id': session_id, 'points': points, 'accepted_choices': total}

    def create_point(self, session_id, name, choice_count=None, operation_id=None):
        name, operation_id = _name(name), _operation_id(operation_id)
        args = self._args('create', {'name': name, 'choice_count': choice_count})
        with self._db(session_id) as db:
            db.execute('BEGIN IMMEDIATE')
            previous = self._existing(db, operation_id, 'create', args)
            if previous:
                return previous[0]
            snapshot, projection = self._snapshot(session_id, choice_count)
            chapter, node = self._location(projection)
            # Only already resolved player metadata, never hidden engine state.
            decorated = decorate({**snapshot['meta'], **projection}, self.service.session_dir(session_id))
            actors = (decorated.get('perspective') or {}).get('controlled_characters', [])
            point = {'id': str(uuid.uuid4()), 'name': name, 'kind': 'manual',
                     'choice_count': snapshot['choice_count'], 'created_at': snapshot['captured_at'],
                     'current_chapter': chapter, 'current_node_ref': node,
                     'controlled_characters': actors, 'status': projection['status'],
                     'operation_id': operation_id,
                     'snapshot_hash': hashlib.sha256(_dump(snapshot).encode()).hexdigest()}
            db.execute('INSERT INTO points VALUES (?,?,?)', (point['id'], _dump(point), _dump(snapshot)))
            db.execute('INSERT INTO operations VALUES (?,?,?,?,?)', (operation_id, 'create', args, _dump(point), 'complete'))
        return point

    def rename_point(self, session_id, point_id, name):
        name = _name(name)
        with self._db(session_id) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM points WHERE id=?', (point_id,)).fetchone()
            if row is None:
                raise ValueError('NO_SAVE_POINT')
            point = json.loads(row[0])
            if point['name'] == name:
                return point
            timestamp = now()
            point.setdefault('name_history', []).append({'name': point['name'], 'changed_at': timestamp})
            point.update(name=name, updated_at=timestamp)
            db.execute('UPDATE points SET data=? WHERE id=?', (_dump(point), point_id))
        return point

    def reconcile_point(self, session_id, name, choice_count=None, operation_id=None):
        """Read an already-committed create receipt without freezing another point."""
        name = _name(name)
        if operation_id is None:
            return None
        operation_id = _operation_id(operation_id)
        args = self._args('create', {'name': name, 'choice_count': choice_count})
        database = self.service.session_dir(session_id) / 'points.sqlite'
        if not database.is_file():
            return None
        db = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            existing = self._existing(db, operation_id, 'create', args)
            if existing is None or existing[1] != 'complete':
                return None
            receipt = existing[0]
            row = db.execute('SELECT data,snapshot FROM points WHERE id=?', (receipt['id'],)).fetchone()
            if row is None:
                raise ValueError('SAVE_RECOVERY_CONFLICT')
            point, snapshot = json.loads(row[0]), json.loads(row[1])
            digest = hashlib.sha256(_dump(snapshot).encode()).hexdigest()
            if point.get('snapshot_hash') != digest or receipt.get('snapshot_hash') != digest:
                raise ValueError('SAVE_SNAPSHOT_CHANGED')
            return receipt
        finally:
            db.close()

    def _point_snapshot(self, session_id, point_id):
        if isinstance(point_id, str) and re.fullmatch(r'auto:(0|[1-9][0-9]*)', point_id):
            return self._snapshot(session_id, int(point_id[5:]))[0]
        with self._db(session_id) as db:
            row = db.execute('SELECT data,snapshot FROM points WHERE id=?', (point_id,)).fetchone()
        if row is None:
            raise ValueError('NO_SAVE_POINT')
        point, snapshot = json.loads(row[0]), json.loads(row[1])
        if point.get('snapshot_hash') != hashlib.sha256(_dump(snapshot).encode()).hexdigest():
            raise ValueError('SAVE_SNAPSHOT_CHANGED')
        return snapshot

    @staticmethod
    def _target_id(data):
        target_id = data.get('target_session_id')
        try:
            if str(uuid.UUID(target_id)) != target_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError('SAVE_RECOVERY_CONFLICT') from None
        return target_id

    @staticmethod
    def _snapshot_intact(data):
        if data.get('snapshot_hash') != hashlib.sha256(_dump(data['snapshot']).encode()).hexdigest():
            raise ValueError('SAVE_SNAPSHOT_CHANGED')

    @staticmethod
    def _published_meta(target, source_id, operation_id):
        marker = target / 'session.json'
        if not marker.is_file():
            return None
        meta = json.loads(marker.read_text(encoding='utf-8'))
        if meta.get('fork_operation_id') != operation_id or meta.get('parent_session_id') != source_id:
            raise ValueError('SAVE_RECOVERY_CONFLICT')
        return meta

    def reconcile_fork(self, session_id, point_id, name=None, operation_id=None):
        """Read an already-published operation without changing gates, state or files.

        A caller can safely recover an uncertain response even when the source
        subsequently advanced, switched character or has an in-flight model call.
        It cannot create an unseen branch or publish an incomplete staging tree.
        """
        if operation_id is None:
            return None
        operation_id = _operation_id(operation_id)
        name = _name(name) if name is not None else None
        args = self._args('fork', {'point_id': point_id, 'name': name})
        database = self.service.session_dir(session_id) / 'points.sqlite'
        if not database.is_file():
            return None
        db = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            existing = self._existing(db, operation_id, 'fork', args)
        finally:
            db.close()
        if existing is None:
            return None
        data, _state = existing
        self._snapshot_intact(data)
        target_id = self._target_id(data)
        target = self.service.directory / 'sessions' / target_id
        if self._published_meta(target, session_id, operation_id) is None:
            return None
        return self.service.view(target_id)

    def fork(self, session_id, point_id, name=None, operation_id=None):
        operation_id = _operation_id(operation_id)
        name = _name(name) if name is not None else None
        args = self._args('fork', {'point_id': point_id, 'name': name})
        # Reserve a deterministic target before touching files. Retrying this exact
        # operation can finish/reconcile the same target instead of making duplicates.
        with self._db(session_id) as db:
            db.execute('BEGIN IMMEDIATE')
            old = self._existing(db, operation_id, 'fork', args)
            if old is None:
                snapshot = self._point_snapshot(session_id, point_id)
                data = {'target_session_id': str(uuid.uuid4()), 'snapshot': snapshot,
                        'snapshot_hash': hashlib.sha256(_dump(snapshot).encode()).hexdigest(),
                        'point_id': point_id, 'save_name': name, 'created_at': now()}
                db.execute('INSERT INTO operations VALUES (?,?,?,?,?)', (operation_id, 'fork', args, _dump(data), 'reserved'))
            else:
                data = old[0]
        with self._db(session_id) as db:
            db.execute('BEGIN IMMEDIATE')
            data, state = self._existing(db, operation_id, 'fork', args)
            self._snapshot_intact(data)
            target_id = self._target_id(data)
            target = self.service.directory / 'sessions' / target_id
            if self._published_meta(target, session_id, operation_id) is not None:
                pass
            elif target.exists():
                raise ValueError('SAVE_RECOVERY_CONFLICT')
            else:
                self._build_branch(target, data, session_id, operation_id)
            if state != 'complete':
                db.execute("UPDATE operations SET state='complete' WHERE id=?", (operation_id,))
        return self.service.view(target_id)

    def _build_branch(self, target, operation, source_id, operation_id):
        from .service import write_json

        snapshot = operation['snapshot']
        if target.parent.resolve() != (self.service.directory / 'sessions').resolve():
            raise ValueError('SAVE_RECOVERY_CONFLICT')
        source_run = copy.deepcopy(snapshot['run'])
        source_meta = snapshot['meta']
        source_directory = self.service.session_dir(source_id)
        # Validate snapshot against the original pinned bytes before copying.
        check = self.service._store(source_id)
        check.replay(copy.deepcopy(source_run))
        paths = [Path(p).resolve() for p in source_run['paths']]
        if any(p.parent != (source_directory / 'story').resolve() for p in paths) or len({p.name for p in paths}) != len(paths):
            raise ValueError('INVALID_SAVE_POINT')
        staging_root = self.service.directory / '.fork-staging'
        staging_root.mkdir(exist_ok=True)
        stage = staging_root / f'{target.name}.{uuid.uuid4()}'
        (stage / 'story').mkdir(parents=True)
        staged_paths = []
        for source in paths:
            dest = stage / 'story' / source.name
            shutil.copyfile(source, dest)
            staged_paths.append(dest)
        if fingerprint(staged_paths) != source_run['fingerprint']:
            raise ValueError('ENGINE_CHANGED: checkpoint source bytes no longer match')
        if snapshot['core_hex'] is not None:
            (stage / 'core.txt').write_bytes(bytes.fromhex(snapshot['core_hex']))
        style = source_meta.get('play_style', 'legacy_unspecified')
        store = Store(stage) if style == 'legacy_unspecified' else ContextStore(stage, style)
        run = copy.deepcopy(source_run)
        originals = run['answers']
        run.update(id=str(uuid.uuid4()), paths=[str(p) for p in staged_paths], answers=[], notes=[],
                   created_at=operation['created_at'], updated_at=operation['created_at'], paused=False)
        for original in originals:
            before = store.replay(run)
            current = before['current']
            choice = original['choice']
            if current is None or type(choice) is not int or not 1 <= choice <= len(current['choices']):
                raise ValueError('REPLAY_MISMATCH')
            old_receipt = original.get('receipt') or {}
            if old_receipt and (old_receipt.get('scene') != current['context'] or old_receipt.get('choice_text') != current['choices'][choice - 1]['text']):
                raise ValueError('REPLAY_MISMATCH')
            answer = {'request_id': current['request_id'], 'choice': choice, 'reason': original['reason'],
                      'time': original['time'], 'inherited': True}
            run['answers'].append(answer)
            after = store.replay(run)
            index = next(i for i, e in enumerate(after['history'])
                         if e['type'] == 'decision' and e['request_id'] == current['request_id'])
            receipt = {'record_id': f"{run['id']}:{current['request_id']}", 'source': 'fish-story-player',
                       'occurred_at': original['time'], 'observed_at': operation['created_at'], 'deleted': False,
                       'chapter': current['chapter'], 'node_ref': current['node_ref'],
                       'request_id': current['request_id'], 'scene': current['context'], 'visible_options': current['choices'],
                       'choice': choice, 'choice_text': current['choices'][choice - 1]['text'], 'public_reason': original['reason'],
                       'outcome': after['history'][index + 1:],
                       'after': {'status': after['status'], 'accepted_choices': len(run['answers']),
                                 'next_request_id': (after['current'] or {}).get('request_id'), 'save_location': 'games.sqlite'},
                       'inherited': True, 'origin_session_id': old_receipt.get('origin_session_id', source_id),
                       'origin_record_id': old_receipt.get('origin_record_id', old_receipt.get('record_id', f"{source_run['id']}:{original['request_id']}")),
                       'origin_content_hash': old_receipt.get('origin_content_hash', old_receipt.get('content_hash')),
                       'inherited_from_session_id': source_id, 'inherited_from_record_id': old_receipt.get('record_id'),
                       'inherited_at': operation['created_at']}
            receipt['content_hash'] = content_hash(receipt)
            answer['receipt'] = receipt
            answer['internal_outcome'] = copy.deepcopy(store._internal_outcomes[-1])
        run['paused'] = source_run['paused']
        store.replay(run)  # Adds style context to inherited receipts and validates the full prefix.
        run['paths'] = [str(target / 'story' / p.name) for p in paths]
        with store.connect() as target_db:
            target_db.execute('INSERT INTO games VALUES (?,?)', ('player', json.dumps(run, ensure_ascii=False)))
        meta = copy.deepcopy(source_meta)
        meta.update(session_id=target.name, created_at=operation['created_at'],
                    parent_session_id=source_id, parent_checkpoint_id=operation['point_id'],
                    inherited_choices=len(originals), save_name=operation['save_name'] or '未命名分支',
                    budget_family_id=source_meta.get('budget_family_id', source_id),
                    save_family_id=source_meta.get('save_family_id', source_id),
                    fork_operation_id=operation_id)
        write_json(stage / 'session.json', meta)
        # Publish a fully closed SQLite database and metadata atomically. Partial
        # staging directories are left private for inspection, never force-deleted.
        os.replace(stage, target)

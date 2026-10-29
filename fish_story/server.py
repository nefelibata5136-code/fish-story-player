"""Small loopback-only UI server. No model is created for Agent play."""
from __future__ import annotations

import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


SAFE_ERRORS = frozenset('''INVALID_HOST INVALID_ORIGIN INVALID_CSRF JSON_REQUIRED REQUEST_TOO_LARGE PORT_UNAVAILABLE
INVALID_REQUEST NOT_FOUND PROVIDER_CHECK_REQUIRED FISH_PLAYER_ID_REQUIRED SESSION_NOT_OWNED_BY_BOUND_PLAYER
INVALID_CORE CORE_TOO_LONG INVALID_CONFIG MODEL_LEDGER_UNREADABLE INDEPENDENT_MODE_REQUIRED ROLE_PERSPECTIVE_UNAVAILABLE
MODEL_CONFIG_OR_CORE_CHANGED NO_UNRESOLVED_CALL UNRESOLVED_MODEL_CALL MODEL_BUDGET_EXHAUSTED
MODEL_API_KEY_MISSING MODEL_RESULT_UNKNOWN MODEL_USAGE_UNKNOWN MODEL_USAGE_EXCEEDED_RESERVATION
INVALID_MODEL_CHOICE REPLAY_MISMATCH ENGINE_CHANGED NO_GAME INVALID_ANSWER ANSWER_ALREADY_ACCEPTED
GAME_PAUSED STALE_REQUEST CHOICE_NOT_AVAILABLE INVALID_NOTE NOTE_ALREADY_SAVED INVALID_ACTION
INVALID_STORY_CHAPTER INVALID_CHAPTER_NUMBER INVALID_STORY_NODES INVALID_STORY_ENDINGS INVALID_NODE_ID
INVALID_PLAYER_FACING INVALID_SESSION_ID NO_SESSION INVALID_STORY_FILES INVALID_STORY_TITLE
STORY_FILE_TOO_LARGE_OR_NOT_JSON DUPLICATE_CHAPTER INVALID_PLAYER_ID INVALID_MODE INVALID_PLAY_STYLE INVALID_GAME_CONFIGURATION
CORE_ONLY_FOR_INDEPENDENT_SESSION NO_STORY NO_CHAPTER SHARE_REQUIRES_STORY_RIGHTS INVALID_EXPORT_FORMAT INVALID_EXPORT_AUDIENCE
INVALID_SAVE_NAME INVALID_SAVE_POINT INVALID_CHOICE_COUNT SAVE_POINT_NOT_FOUND SAVE_OPERATION_CONFLICT
OPERATION_CONFLICT INVALID_OPERATION_ID INVALID_CHECKPOINT_ID INVALID_CHECKPOINT_NAME NO_CHECKPOINT
SAVE_POINT_NOT_VISIBLE MODEL_FAMILY_BUSY MODEL_CALL_UNRESOLVED CHECKPOINT_CORRUPT SAVE_SOURCE_CHANGED
BUDGET_FAMILY_INVALID BUDGET_FAMILY_NOT_OWNED IN_FLIGHT_SESSION_CHANGED
NO_SAVE_POINT SAVE_RECOVERY_CONFLICT SAVE_SNAPSHOT_CHANGED
INVALID_STORY_ARCHIVE STORY_ARCHIVE_TOO_LARGE STORY_ARCHIVE_UNSAFE STORY_ARCHIVE_AMBIGUOUS
STORY_ARCHIVE_NO_CHAPTERS INVALID_STORY_LANGUAGE SOURCE_TERMS_REQUIRED SOURCE_DOWNLOAD_FAILED
SOURCE_BUSY SOURCE_REDIRECT_BLOCKED SOURCE_DOWNLOAD_TOO_LARGE SOURCE_DOWNLOAD_TIMEOUT
SOURCE_HASH_MISMATCH SOURCE_CONTENT_INVALID SOURCE_LOCAL_COPY_INCOMPLETE SOURCE_LOCAL_COPY_CHANGED
SOURCE_STORAGE_FAILED SOURCE_IMPORT_FAILED INVALID_HISTORY_PAGE RECAP_UPDATE_REQUIRED RECAP_TASK_NOT_AVAILABLE RECAP_TOO_LONG INVALID_RECAP_LIMIT RECAP_OPERATION_CONFLICT RECAP_STALE_TASK INVALID_RECAP_TEXT RECAP_STORAGE_CORRUPT RECAP_STORAGE_INVALID RECAP_STORAGE_CHANGED INVALID_MODEL_RECAP INVALID_RECAP_ACTOR RECAP_STALE_REVISION RECAP_BUSY DETROIT_NOT_INSTALLED AGENT_EXECUTABLE_MISSING STORY_COMPATIBILITY_CONFLICT
'''.split())


def safe_error(exc):
    """Only established public error codes may leave the player boundary."""
    code = str(exc).split(':', 1)[0].strip("'\"")
    return code if code in SAFE_ERRORS else 'OPERATION_FAILED_CHECK_LOCAL_SAVE'


def make_server(service, port=8765):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'FishStory/0.1'

        def log_message(self, *_):
            pass  # URLs, request bodies and imported identities stay out of logs.

        def check_origin(self, write=False):
            expected = f'127.0.0.1:{self.server.server_port}'
            alternate = f'localhost:{self.server.server_port}'
            if self.headers.get('Host') not in (expected, alternate):
                raise PermissionError('INVALID_HOST')
            origin = self.headers.get('Origin')
            if origin and origin not in ('http://' + expected, 'http://' + alternate):
                raise PermissionError('INVALID_ORIGIN')
            if write and not secrets.compare_digest(self.headers.get('X-Fish-CSRF', ''), token):
                raise PermissionError('INVALID_CSRF')

        def reply(self, value, status=200, content_type='application/json; charset=utf-8'):
            body = (json.dumps(value, ensure_ascii=False).encode('utf-8')
                    if content_type.startswith('application/json') else value.encode('utf-8'))
            try:
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy',
                                 "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                 "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass  # A closed/reloaded browser tab is an ordinary disconnect.

        def fail(self, exc):
            # Provider errors can embed credentials / private request text: never echo them.
            if isinstance(exc, PermissionError):
                self.reply({'error': safe_error(exc)}, 403)
            elif isinstance(exc, (ValueError, KeyError, FileNotFoundError, TypeError)):
                self.reply({'error': safe_error(exc)}, 400)
            else:
                self.reply({'error': 'OPERATION_FAILED_CHECK_LOCAL_SAVE'}, 409)

        def do_GET(self):
            try:
                self.check_origin()
                route = urlsplit(self.path)
                query = parse_qs(route.query)
                if route.path == '/':
                    html = (Path(__file__).parent / 'web' / 'index.html').read_text(encoding='utf-8')
                    self.reply(html, content_type='text/html; charset=utf-8')
                elif route.path == '/api/bootstrap':
                    self.reply({'csrf': token, 'stories': service.stories(), 'sessions': service.sessions(),
                                'default_story_id': getattr(service, 'default_story_id', lambda: None)()})
                elif route.path == '/api/story-source':
                    from .source import source_info
                    self.reply(source_info())
                elif route.path == '/api/agent-setup':
                    from .agent_setup import connection_info
                    self.reply(connection_info(service, query.get('player_id', ['my-fish'])[0],
                               play_style=query.get('play_style', ['self_aware'])[0],
                               session_id=query.get('session_id', [None])[0]))
                elif route.path == '/api/recap':
                    from .recaps import RecapStore
                    self.reply(RecapStore(service).read(query['session_id'][0]))
                elif route.path == '/api/recap-task':
                    from .player_output import recap_read
                    self.reply(recap_read(service, query['session_id'][0], query['task_id'][0],
                               offset=int(query.get('offset', ['0'])[0]), limit=int(query.get('limit', ['50'])[0])))
                elif route.path == '/api/story-plan':
                    from .planning import story_plan
                    self.reply(story_plan(service, query['story_id'][0],
                               chapter=int(query.get('chapter', ['1'])[0]),
                               core_characters=int(query.get('core_characters', ['0'])[0]),
                               max_output_tokens=int(query.get('max_output_tokens', ['256'])[0]),
                               play_style=query.get('play_style', ['self_aware'])[0]))
                elif route.path == '/api/view':
                    self.reply(service.observe(query['session_id'][0]))
                elif route.path == '/api/player-view':
                    from .player_output import agent_view
                    self.reply(agent_view(service, service.view(query['session_id'][0]), include_recap=True))
                elif route.path == '/api/save-points':
                    self.reply(service.save_points(query['session_id'][0], audience='observer'))
                elif route.path == '/api/core':
                    sid = query['session_id'][0]
                    core = service.session_dir(sid) / 'core.txt'
                    self.reply({'text': core.read_text(encoding='utf-8') if core.exists() else ''})
                elif route.path == '/api/model-config':
                    from .model import load_config
                    self.reply({'config': load_config(service, query['session_id'][0])})
                elif route.path == '/api/export':
                    self.reply({'result': service.export(query['session_id'][0],
                               format=query.get('format', ['json'])[0], share=query.get('share', ['0'])[0] == '1',
                               audience='observer')})
                else:
                    self.reply({'error': 'NOT_FOUND'}, 404)
            except Exception as exc:
                self.fail(exc)

        def do_POST(self):
            try:
                self.check_origin(write=True)
                route = urlsplit(self.path)
                if route.path == '/api/import-pack':
                    from .import_pack import import_story_pack, MAX_ARCHIVE_BYTES
                    if self.headers.get('Content-Type', '').split(';')[0] != 'application/zip':
                        raise ValueError('INVALID_STORY_ARCHIVE')
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= MAX_ARCHIVE_BYTES:
                        raise ValueError('STORY_ARCHIVE_TOO_LARGE')
                    query = parse_qs(route.query)
                    archive = self.rfile.read(length)
                    if len(archive) != length:
                        raise ValueError('INVALID_STORY_ARCHIVE')
                    self.reply(import_story_pack(service, archive,
                               title=query.get('title', ['本地故事'])[0],
                               language=query.get('language', ['zh'])[0]))
                    return
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('JSON_REQUIRED')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2_000_000:
                    raise ValueError('REQUEST_TOO_LARGE')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('INVALID_REQUEST')
                route = urlsplit(self.path).path
                if route == '/api/new':
                    result = service.start(player_id=payload['player_id'], story_id=payload.get('story_id'),
                                           chapter=int(payload.get('chapter', 1)), mode=payload.get('mode', 'agent'),
                                           core_text=payload.get('core_text'), difficulty=payload.get('difficulty', 'casual'),
                                           play_style=payload.get('play_style', 'self_aware'), save_name=payload.get('save_name'))
                    result = service.observe(result['session_id'])
                elif route == '/api/import-story':
                    result = service.import_story(payload['paths'], payload.get('title', '本地章节'))
                elif route == '/api/acquire-detroit':
                    from .source import acquire_detroit
                    result = acquire_detroit(service, accepted=payload.get('accept_source_terms') is True)
                elif route == '/api/core-preview':
                    from .model import validate_core
                    result = validate_core(payload['text'])
                elif route == '/api/recap-update':
                    from .recaps import RecapStore
                    result = RecapStore(service).update(payload['session_id'], payload['text'],
                        task_id=payload.get('task_id'), max_characters=payload.get('max_characters'),
                        operation_id=payload.get('operation_id'))
                elif route == '/api/choose':
                    result = service.choose(payload['session_id'], payload['request_id'], payload['choice'], payload.get('reason', ''))
                    result = service.observe(payload['session_id'])
                elif route in ('/api/pause', '/api/resume'):
                    result = getattr(service, route.rsplit('/', 1)[-1])(payload['session_id'])
                    result = service.observe(payload['session_id'])
                elif route == '/api/save-point':
                    result = service.save_point(payload['session_id'], payload['name'],
                                                choice_count=payload.get('choice_count'), operation_id=payload.get('operation_id'), audience='observer')
                elif route == '/api/load-point':
                    result = service.load_save_point(payload['session_id'], payload['point_id'],
                                                     name=payload.get('name'), operation_id=payload.get('operation_id'), audience='observer')
                    result = service.observe(result['session_id'])
                elif route == '/api/rename-save':
                    result = service.rename_save(payload['session_id'], payload['name'])
                    result = service.observe(payload['session_id'])
                elif route == '/api/rename-point':
                    result = service.rename_save_point(payload['session_id'], payload['point_id'], payload['name'], audience='observer')
                elif route in ('/api/model-step', '/api/model-status', '/api/model-ack'):
                    from .model import IndependentPlayer
                    player = IndependentPlayer(service, payload['session_id'], payload['config'])
                    if route == '/api/model-ack':
                        if payload.get('provider_checked') is not True:
                            raise ValueError('PROVIDER_CHECK_REQUIRED')
                        result = player.acknowledge_unknown(payload['call_id'])
                    else:
                        result = player.step() if route == '/api/model-step' else player.status()
                else:
                    self.reply({'error': 'NOT_FOUND'}, 404)
                    return
                self.reply(result)
            except Exception as exc:
                self.fail(exc)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)

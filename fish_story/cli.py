"""Terminal and MCP entry points for the portable story runner."""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import webbrowser
from pathlib import Path


def default_home():
    return Path(os.environ.get('FISH_STORY_HOME', str(Path.home() / '.fish-story-player')))


def parser():
    p = argparse.ArgumentParser(description='Let your fish bring their identity into an interactive story.')
    p.add_argument('--home', type=Path, default=default_home(), help='Private local saves directory')
    p.add_argument('--compact', action='store_true', help='Return current scene/receipt only; complete history remains in local export')
    sub = p.add_subparsers(dest='command', required=True)
    srv = sub.add_parser('serve'); srv.add_argument('--port', type=int, help='Default 8765, or a free port if busy'); srv.add_argument('--open', action='store_true')
    sub.add_parser('stories'); sub.add_parser('sessions')
    imp = sub.add_parser('import-story'); imp.add_argument('paths', nargs='+'); imp.add_argument('--title', default='Local story')
    pack = sub.add_parser('import-pack', help='Import an entire local repository/chapter ZIP in one operation')
    pack.add_argument('archive', type=Path); pack.add_argument('--title', default='本地故事'); pack.add_argument('--language', choices=['zh', 'en'], default='zh')
    sub.add_parser('story-source', help='Show the fixed upstream source and its noncommercial terms; no download')
    for command in ('setup-detroit', 'play-detroit'):
        setup = sub.add_parser(command, help='Explicitly fetch the fixed upstream story into local private storage')
        setup.add_argument('--accept-source-terms', action='store_true', help='Request the third-party CC BY-NC story; no original-game rights are granted')
        if command == 'play-detroit':
            setup.add_argument('--player', required=True); setup.add_argument('--save-name')
            setup.add_argument('--play-style', choices=['immersive', 'self_aware'], default='self_aware')
    connection = sub.add_parser('agent-config', help='Generate MCP JSON and native DSH configuration with real absolute paths')
    connection.add_argument('--player', required=True)
    connection.add_argument('--play-style', choices=['immersive', 'self_aware'], default='self_aware')
    connection.add_argument('--session-id')
    connection.add_argument('--format', choices=['json', 'mcp', 'dsh', 'instructions'], default='json')
    connection.add_argument('--output', type=Path)
    new = sub.add_parser('new'); new.add_argument('--player', required=True); new.add_argument('--story', default='detroit')
    new.add_argument('--save-name', help='Optional local display name; never used as a path')
    new.add_argument('--chapter', type=int, default=1); new.add_argument('--mode', choices=['agent', 'independent', 'manual'], default='agent')
    new.add_argument('--play-style', choices=['immersive', 'self_aware'], default='self_aware',
                     help='immersive uses the controlled character perspective; self_aware retains player perspective')
    new.add_argument('--core', type=Path); new.add_argument('--difficulty', choices=['casual', 'experienced', 'hardcore'], default='casual')
    for name in ('view', 'pause', 'resume'):
        x = sub.add_parser(name); x.add_argument('session_id')
    choose = sub.add_parser('choose'); choose.add_argument('session_id'); choose.add_argument('request_id')
    choose.add_argument('choice', type=int); choose.add_argument('--reason', default='')
    recap = sub.add_parser('recap-read', help='Read your recap file and paginated completed-chapter evidence')
    recap.add_argument('session_id'); recap.add_argument('--task-id')
    recap.add_argument('--offset', type=int, default=0); recap.add_argument('--limit', type=int, default=20)
    recap_update = sub.add_parser('recap-update', help='Save the recap authored by the player, not an automatic synopsis')
    recap_update.add_argument('session_id'); recap_update.add_argument('--task-id')
    recap_update.add_argument('--text-file', type=Path, required=True)
    recap_update.add_argument('--max-characters', type=int); recap_update.add_argument('--operation-id')
    points = sub.add_parser('save-points'); points.add_argument('session_id'); points.add_argument('--observer', action='store_true')
    point = sub.add_parser('save-point'); point.add_argument('session_id'); point.add_argument('--name', required=True)
    point.add_argument('--choice-count', type=int); point.add_argument('--operation-id'); point.add_argument('--observer', action='store_true')
    load = sub.add_parser('load-point'); load.add_argument('session_id'); load.add_argument('point_id')
    load.add_argument('--name'); load.add_argument('--operation-id'); load.add_argument('--observer', action='store_true')
    rename = sub.add_parser('rename-save'); rename.add_argument('session_id'); rename.add_argument('name')
    rename_point = sub.add_parser('rename-point'); rename_point.add_argument('session_id'); rename_point.add_argument('point_id'); rename_point.add_argument('name'); rename_point.add_argument('--observer', action='store_true')
    exp = sub.add_parser('export'); exp.add_argument('session_id'); exp.add_argument('--format', choices=['json', 'markdown', 'memory'], default='markdown')
    exp.add_argument('--share', action='store_true'); exp.add_argument('--output', type=Path)
    exp.add_argument('--observer', action='store_true', help='Human operator export of the complete witnessed timeline; never feed it to an immersive player')
    core = sub.add_parser('core-preview'); core.add_argument('path', type=Path)
    for name in ('model-step', 'model-run', 'model-status', 'model-ack'):
        x = sub.add_parser(name); x.add_argument('session_id'); x.add_argument('--config', type=Path, required=True, help='JSON config using api_key_env; never store a key')
        if name == 'model-ack':
            x.add_argument('--call-id', required=True)
            x.add_argument('--acknowledge-provider-checked', required=True, action='store_true',
                           help='You checked provider usage and the save. Uncertain cost reservations are retained.')
    mcp = sub.add_parser('mcp'); mcp.add_argument('--player', default=os.environ.get('FISH_PLAYER_ID'))
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args = parser().parse_args(argv)
    from .service import GameService
    service = GameService(args.home)
    try:
        if args.command == 'serve':
            from .server import make_server
            try:
                server = make_server(service, args.port if args.port is not None else 8765)
            except OSError:
                if args.port is not None:
                    raise ValueError('PORT_UNAVAILABLE') from None
                server = make_server(service, 0)
                print('Preferred port is unavailable; using a free local port.', flush=True)
            url = f'http://127.0.0.1:{server.server_port}'
            print(f'Fish Story Player: {url}\nPrivate data: {args.home}', flush=True)
            if args.open:
                webbrowser.open(url)
            try:
                server.serve_forever()
            finally:
                server.server_close()
            return 0
        if args.command == 'mcp':
            from .mcp_server import run
            run(service, args.player)
            return 0
        if args.command == 'agent-config':
            from .agent_setup import connection_info
            result = connection_info(service, args.player, args.play_style, args.session_id)
            if args.format == 'mcp': result = result['mcp_config']
            elif args.format == 'dsh': result = result['dsh_config_yaml']
            elif args.format == 'instructions': result = result['agent_instructions']
            if args.output:
                content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                # Never overwrite an existing Agent configuration implicitly.
                with args.output.open('x', encoding='utf-8') as handle:
                    handle.write(content)
                print(str(args.output.resolve()))
                return 0
        elif args.command == 'stories': result = service.stories()
        elif args.command == 'sessions': result = service.sessions()
        elif args.command == 'story-source':
            from .source import source_info
            result = source_info()
        elif args.command in ('setup-detroit', 'play-detroit'):
            from .source import acquire_detroit
            result = acquire_detroit(service, accepted=args.accept_source_terms)
            if args.command == 'play-detroit':
                result = service.start(player_id=args.player, story_id=result['id'], mode='agent',
                                       play_style=args.play_style, save_name=args.save_name)
        elif args.command == 'import-pack':
            from .import_pack import import_story_pack
            result = import_story_pack(service, args.archive, title=args.title, language=args.language)
        elif args.command == 'import-story':
            paths = []
            for value in args.paths:
                expanded = sorted(glob.glob(value)) if glob.has_magic(value) else [value]
                if not expanded:
                    raise ValueError('INVALID_STORY_FILES')
                paths.extend(expanded)
            result = service.import_story(paths, args.title)
        elif args.command == 'new':
            result = service.start(player_id=args.player, story_id=args.story, chapter=args.chapter,
                                   mode=args.mode, core_text=args.core.read_text(encoding='utf-8-sig') if args.core else None,
                                   difficulty=args.difficulty, play_style=args.play_style, save_name=args.save_name)
        elif args.command in ('view', 'pause', 'resume'): result = getattr(service, args.command)(args.session_id)
        elif args.command == 'choose':
            current = service.view(args.session_id)
            if service._meta(args.session_id).get('mode') == 'agent' and args.request_id == (current.get('current') or {}).get('request_id'):
                from .recaps import RecapStore
                if RecapStore(service).tasks(args.session_id):
                    raise ValueError('RECAP_UPDATE_REQUIRED')
            result = service.choose(args.session_id, args.request_id, args.choice, args.reason)
        elif args.command == 'recap-read':
            from .player_output import recap_read
            result = recap_read(service, args.session_id, args.task_id, args.offset, args.limit)
        elif args.command == 'recap-update':
            from .recaps import RecapStore
            result = RecapStore(service).update(args.session_id, args.text_file.read_text(encoding='utf-8-sig'),
                                               task_id=args.task_id, max_characters=args.max_characters,
                                               operation_id=args.operation_id)
        elif args.command == 'save-points': result = service.save_points(args.session_id, audience='observer' if args.observer else 'player')
        elif args.command == 'save-point':
            result = service.save_point(args.session_id, args.name, choice_count=args.choice_count, operation_id=args.operation_id,
                                        audience='observer' if args.observer else 'player')
        elif args.command == 'load-point':
            result = service.load_save_point(args.session_id, args.point_id, name=args.name, operation_id=args.operation_id,
                                             audience='observer' if args.observer else 'player')
        elif args.command == 'rename-save': result = service.rename_save(args.session_id, args.name)
        elif args.command == 'rename-point': result = service.rename_save_point(args.session_id, args.point_id, args.name,
                                                                             audience='observer' if args.observer else 'player')
        elif args.command == 'core-preview':
            from .model import validate_core
            text = args.path.read_text(encoding='utf-8-sig')
            result = {'preview': validate_core(text), 'imported_text': text}
        elif args.command in ('model-step', 'model-run', 'model-status', 'model-ack'):
            from .model import IndependentPlayer
            config = json.loads(args.config.read_text(encoding='utf-8-sig'))
            player = IndependentPlayer(service, args.session_id, config)
            methods = {'model-step': 'step', 'model-run': 'run', 'model-status': 'status'}
            result = player.acknowledge_unknown(args.call_id) if args.command == 'model-ack' else getattr(player, methods[args.command])()
        elif args.command == 'export':
            if not args.observer and service._meta(args.session_id).get('mode') == 'agent':
                from .recaps import RecapStore
                if RecapStore(service).tasks(args.session_id):
                    raise ValueError('RECAP_UPDATE_REQUIRED')
            result = service.export(args.session_id, format=args.format, share=args.share,
                                    audience='observer' if args.observer else 'player')
            if args.output:
                content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(content, encoding='utf-8')
                print(str(args.output.resolve()))
                return 0
        if (args.command in ('new', 'play-detroit', 'view', 'choose', 'pause', 'resume', 'load-point', 'rename-save')
                and isinstance(result, dict) and 'status' in result and 'session_id' in result):
            from .player_output import agent_view
            meta = service._meta(result['session_id'])
            if args.compact or meta.get('mode') == 'agent':
                result = agent_view(service, result, request_id=args.request_id if args.command == 'choose' else None,
                                    choice=args.choice if args.command == 'choose' else None,
                                    include_recap=args.command in ('view', 'new', 'play-detroit'))
        print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        # No provider response, imported text, secret value or traceback on the console.
        from .server import safe_error
        print(json.dumps({'error': safe_error(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

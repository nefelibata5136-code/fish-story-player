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
    sub = p.add_subparsers(dest='command', required=True)
    srv = sub.add_parser('serve'); srv.add_argument('--port', type=int, help='Default 8765, or a free port if busy'); srv.add_argument('--open', action='store_true')
    sub.add_parser('stories'); sub.add_parser('sessions')
    imp = sub.add_parser('import-story'); imp.add_argument('paths', nargs='+'); imp.add_argument('--title', default='Local story')
    new = sub.add_parser('new'); new.add_argument('--player', required=True); new.add_argument('--story', default='demo')
    new.add_argument('--chapter', type=int, default=1); new.add_argument('--mode', choices=['agent', 'independent', 'manual'], default='agent')
    new.add_argument('--core', type=Path); new.add_argument('--difficulty', choices=['casual', 'experienced', 'hardcore'], default='casual')
    for name in ('view', 'pause', 'resume'):
        x = sub.add_parser(name); x.add_argument('session_id')
    choose = sub.add_parser('choose'); choose.add_argument('session_id'); choose.add_argument('request_id')
    choose.add_argument('choice', type=int); choose.add_argument('--reason', default='')
    exp = sub.add_parser('export'); exp.add_argument('session_id'); exp.add_argument('--format', choices=['json', 'markdown', 'memory'], default='markdown')
    exp.add_argument('--share', action='store_true'); exp.add_argument('--output', type=Path)
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
        if args.command == 'stories': result = service.stories()
        elif args.command == 'sessions': result = service.sessions()
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
                                   difficulty=args.difficulty)
        elif args.command in ('view', 'pause', 'resume'): result = getattr(service, args.command)(args.session_id)
        elif args.command == 'choose': result = service.choose(args.session_id, args.request_id, args.choice, args.reason)
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
            result = service.export(args.session_id, format=args.format, share=args.share)
            if args.output:
                content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(content, encoding='utf-8')
                print(str(args.output.resolve()))
                return 0
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

"""Official MCP stdio adapter; each process is bound to exactly one player."""
from __future__ import annotations

import os
from functools import wraps

from .server import safe_error


def build_server(service, player_id=None):
    from mcp.server.fastmcp import FastMCP
    player = player_id or os.environ.get('FISH_PLAYER_ID')
    if not player:
        raise ValueError('FISH_PLAYER_ID_REQUIRED')
    mcp = FastMCP('fish-story-player')

    def tool(fn):
        @wraps(fn)
        def protected(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                raise ValueError(safe_error(exc)) from None
        return mcp.tool()(protected)

    def view_owned(session_id):
        # Check immutable ownership before invoking the private engine/replay.
        meta = service._meta(session_id)
        if meta.get('player_id') != player:
            raise PermissionError('SESSION_NOT_OWNED_BY_BOUND_PLAYER')
        return service.view(session_id)

    @tool
    def story_list() -> list[dict]:
        """List installed local stories and chapter titles, without future scenes."""
        return service.stories()

    @tool
    def game_start(story_id: str = 'demo', chapter: int = 1, difficulty: str = 'casual', play_style: str = 'self_aware') -> dict:
        """Start direct play: self_aware carries your understanding; immersive judges from the controlled character's information. Both retain your identity. The style is fixed for this save; this tool never calls a model."""
        return service.start(player_id=player, story_id=story_id, chapter=chapter, mode='agent', difficulty=difficulty,
                             play_style=play_style)

    @tool
    def game_list() -> list[dict]:
        """List this bound player's saved sessions."""
        return [s for s in service.sessions() if s.get('player_id') == player]

    @tool
    def game_view(session_id: str) -> dict:
        """Read the current player perspective. Immersive play filters game knowledge to the current character; follow perspective instructions. Your existing Agent memory cannot be erased, so do not use another character's private knowledge. No hidden mechanics or future content."""
        return view_owned(session_id)

    @tool
    def game_choices(session_id: str) -> dict:
        """Read the pending request and its legal numbered options."""
        view = view_owned(session_id)
        return {'session_id': session_id, 'status': view['status'], 'current': view.get('current'),
                'play_style': view.get('play_style'), 'perspective': view.get('perspective')}

    @tool
    def game_choose(session_id: str, request_id: str, choice: int, reason: str = '') -> dict:
        """Submit an actual option. reason is an optional brief public explanation, not private reasoning."""
        view_owned(session_id)
        return service.choose(session_id, request_id, choice, reason)

    @tool
    def game_history(session_id: str) -> dict:
        """Read actual choices and visible history allowed by this save's player perspective; immersive play omits other characters' private game information."""
        view = view_owned(session_id)
        return {'session_id': session_id, 'history': view.get('history', []), 'records': view.get('records', []),
                'play_style': view.get('play_style'), 'perspective': view.get('perspective')}

    @tool
    def game_pause(session_id: str) -> dict:
        """Pause this game without replacing the player or discarding progress."""
        view_owned(session_id)
        return service.pause(session_id)

    @tool
    def game_resume(session_id: str) -> dict:
        """Resume the saved pending scene after a pause or restart."""
        view_owned(session_id)
        return service.resume(session_id)

    @tool
    def game_export(session_id: str, format: str = 'json', share: bool = False) -> dict:
        """Export local JSON, markdown, or unapproved memory candidate. share requests redaction, not publication."""
        view_owned(session_id)
        return {'format': format, 'result': service.export(session_id, format=format, share=share)}

    return mcp


def run(service, player_id=None):
    build_server(service, player_id).run(transport='stdio')

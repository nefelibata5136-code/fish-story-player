"""Official MCP stdio adapter; each process is bound to exactly one player."""
from __future__ import annotations

import os
from functools import wraps

from .server import safe_error
from .player_output import agent_view, history_page, recap_read


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

    def output(view, request_id=None, choice=None, include_recap=False):
        return agent_view(service, view, request_id, choice, include_recap)

    def bounded_view(session_id):
        view = view_owned(session_id)
        if service._meta(session_id).get('recap_version') == 1:
            from .recaps import RecapStore
            store = RecapStore(service)
            tasks = store.tasks(session_id)
            if tasks:
                return store.task_view(session_id, tasks[0]['task_id'])
        return view

    @tool
    def story_list() -> list[dict]:
        """List installed local stories and chapter titles, without future scenes."""
        return service.stories()

    @tool
    def story_source() -> dict:
        """Read the pinned Detroit AI Player source, attribution and noncommercial terms. This does not download anything or expose future story scenes."""
        from .source import source_info
        return source_info()

    @tool
    def story_setup_detroit(accept_source_terms: bool = False) -> dict:
        """Explicitly request the pinned third-party Chinese story from upstream into local storage. Read story_source first. True accepts its CC BY-NC terms; original-game rights are not granted. Returns story_id for game_start; no model is called. Already installed chapters are reused."""
        from .source import acquire_detroit
        return acquire_detroit(service, accepted=accept_source_terms)

    @tool
    def game_start(story_id: str = 'detroit', chapter: int = 1, difficulty: str = 'casual', play_style: str = 'self_aware', save_name: str | None = None) -> dict:
        """Start direct play: self_aware carries your understanding; immersive judges from the controlled character's information. Both retain your identity. The style is fixed for this save; this tool never calls a model."""
        return output(service.start(player_id=player, story_id=story_id, chapter=chapter, mode='agent', difficulty=difficulty,
                                    play_style=play_style, save_name=save_name), include_recap=True)

    @tool
    def game_list() -> list[dict]:
        """List this bound player's saved sessions."""
        return [s for s in service.sessions() if s.get('player_id') == player]

    @tool
    def game_saves() -> list[dict]:
        """List your independent named saves and branches; no model call or active-save switch."""
        return [s for s in service.sessions() if s.get('player_id') == player]

    @tool
    def game_open(session_id: str) -> dict:
        """Open a chosen owned save. Pass this session ID explicitly in later tools; other saves stay intact."""
        return output(view_owned(session_id), include_recap=True)

    @tool
    def game_save_points(session_id: str) -> dict:
        """List all your already reached save points. Role-specific labels may be redacted; choosing a point opens a separate branch with that target role's bounded history."""
        view_owned(session_id)
        return service.save_points(session_id)

    @tool
    def game_save_checkpoint(session_id: str, name: str, choice_count: int | None = None,
                             operation_id: str | None = None) -> dict:
        """Save a named immutable checkpoint at current or previously reached choice count. Supply a unique operation_id; unknown results must be checked, not blindly repeated."""
        view_owned(session_id)
        return service.save_point(session_id, name, choice_count=choice_count, operation_id=operation_id)

    @tool
    def game_load_checkpoint(session_id: str, point_id: str, name: str | None = None,
                             operation_id: str | None = None) -> dict:
        """Create a new branch from your reached checkpoint. The old save remains; inherited choices are not new choices. Independent branches share their original API budget."""
        view_owned(session_id)
        return output(service.load_save_point(session_id, point_id, name=name, operation_id=operation_id), include_recap=True)

    @tool
    def game_rename_save(session_id: str, name: str) -> dict:
        """Rename one owned save for display without altering its identity or history."""
        view_owned(session_id)
        return output(service.rename_save(session_id, name))

    @tool
    def game_rename_checkpoint(session_id: str, point_id: str, name: str) -> dict:
        """Rename a reached checkpoint; its saved position and source history remain immutable."""
        view_owned(session_id)
        return service.rename_save_point(session_id, point_id, name)

    @tool
    def game_view(session_id: str) -> dict:
        """Read the current player perspective. Immersive play filters game knowledge to the current character; follow perspective instructions. Your existing Agent memory cannot be erased, so do not use another character's private knowledge. No hidden mechanics or future content."""
        return output(view_owned(session_id), include_recap=True)

    @tool
    def game_choices(session_id: str) -> dict:
        """Read the pending request and its legal numbered options."""
        view = output(view_owned(session_id))
        return {'session_id': session_id, 'status': view['status'], 'current': view.get('current'),
                'play_style': view.get('play_style'), 'perspective': view.get('perspective'), 'recap': view.get('recap')}

    @tool
    def game_choose(session_id: str, request_id: str, choice: int, reason: str = '') -> dict:
        """Submit an actual option. reason is an optional brief public explanation, not private reasoning."""
        view = view_owned(session_id)
        if request_id == (view.get('current') or {}).get('request_id'):
            if output(view).get('status') == 'recap_required':
                raise ValueError('RECAP_UPDATE_REQUIRED')
        return output(service.choose(session_id, request_id, choice, reason), request_id=request_id, choice=choice)

    @tool
    def game_history(session_id: str, offset: int = 0, limit: int = 20) -> dict:
        """Read paginated actual choices/visible events (20 each by default, max50). Follow next_offset until null. Immersive play only returns the current character's game knowledge."""
        view = bounded_view(session_id)
        return history_page(view, offset, limit)

    @tool
    def game_recap_read(session_id: str, task_id: str | None = None, offset: int = 0, limit: int = 20) -> dict:
        """Read your own local prior-story recap (default5000characters) and optional completed-chapter evidence page. The task fixes the role and excludes the upcoming chapter. Follow evidence.next_offset."""
        view_owned(session_id)
        return recap_read(service, session_id, task_id, offset, limit)

    @tool
    def game_recap_update(session_id: str, text: str, task_id: str | None = None,
                          max_characters: int | None = None, operation_id: str | None = None) -> dict:
        """After each chapter, YOU author/update the recap file from seen evidence. Default limit5000characters; adjust max_characters yourself. No silent truncation or invented summary. Use operation_id to reconcile unknown writes, then game_view to continue."""
        view_owned(session_id)
        from .recaps import RecapStore
        result = RecapStore(service).update(session_id, text, task_id=task_id,
                                          max_characters=max_characters, operation_id=operation_id)
        return {'session_id': session_id, 'recap': result, 'next_action': 'game_view'}

    @tool
    def game_pause(session_id: str) -> dict:
        """Pause this game without replacing the player or discarding progress."""
        view_owned(session_id)
        return output(service.pause(session_id))

    @tool
    def game_resume(session_id: str) -> dict:
        """Resume the saved pending scene after a pause or restart."""
        view_owned(session_id)
        return output(service.resume(session_id))

    @tool
    def game_export(session_id: str, format: str = 'json', share: bool = False) -> dict:
        """Export local JSON, markdown, or unapproved memory candidate. share requests redaction, not publication."""
        view_owned(session_id)
        if output(view_owned(session_id)).get('status') == 'recap_required':
            raise ValueError('RECAP_UPDATE_REQUIRED')
        return {'format': format, 'result': service.export(session_id, format=format, share=share)}

    return mcp


def run(service, player_id=None):
    build_server(service, player_id).run(transport='stdio')

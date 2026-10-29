"""Bounded step responses for Agents; complete evidence stays in the store."""
from __future__ import annotations


STEP_FIELDS = frozenset('''session_id run_id player_id mode story_id story_title
save_name status accepted_choices new_choice_count inherited_choices play_style
play_style_label play_style_description audience perspective current identity_notice
budget_family_id parent_session_id parent_checkpoint_id start_chapter difficulty'''.split())


def compact_view(view, request_id=None, choice=None):
    result = {key: value for key, value in view.items() if key in STEP_FIELDS}
    result['history_access'] = 'game_history (paginated) or local private export; full evidence remains saved'
    if request_id is not None:
        result['acceptance'] = {'accepted': True, 'request_id': request_id, 'choice': choice,
                                'accepted_choices': view['accepted_choices']}
        # Already role-filtered by service.view: a role switch must not copy
        # the previous character's private receipt into the new stream.
        receipt = next((record for record in view.get('records', [])
                        if record.get('request_id') == request_id), None)
        if receipt:
            result['visible_outcomes'] = receipt.get('outcome', [])
    return result


def history_page(view, offset=0, limit=20):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('INVALID_HISTORY_PAGE')
    history, records = view.get('history', []), view.get('records', [])
    total = max(len(history), len(records))
    return {'session_id': view['session_id'], 'play_style': view.get('play_style'),
            'perspective': view.get('perspective'), 'offset': offset, 'limit': limit,
            'history': history[offset:offset + limit], 'records': records[offset:offset + limit],
            'total_events': len(history), 'total_records': len(records),
            'next_offset': offset + limit if offset + limit < total else None}


def agent_view(service, view, request_id=None, choice=None, include_recap=False):
    """Pause the Agent at a chapter boundary until it authors its own recap."""
    result = compact_view(view, request_id, choice)
    if service._meta(view['session_id']).get('recap_version') != 1:
        return result
    from .recaps import RecapStore
    store = RecapStore(service)
    tasks = store.tasks(view['session_id'])
    if tasks:
        task = tasks[0]
        previous_view = store.task_view(view['session_id'], task['task_id'])
        result = compact_view(previous_view, request_id, choice)
        result.pop('visible_outcomes', None)
        summary = store.read(view['session_id'], actor=task['actor'])
        result.update(status='recap_required', underlying_game_status=view['status'], current=None)
        result['recap'] = {key: summary.get(key) for key in
                          ('actor', 'max_characters', 'characters', 'revision', 'file_path')}
        result['recap'].update(pending_tasks=tasks, required=True,
            instruction='本章已结束。请用 game_recap_read 读取该任务的已见材料和旧摘要，由你本人更新前情摘要；'
                        '默认最多5000字，可用 max_characters 自行调整。game_recap_update 后继续读当前剧情。')
    else:
        summary = store.read(view['session_id'])
        fields = ['actor', 'max_characters', 'characters', 'revision', 'file_path']
        if include_recap:
            fields.append('text')
        result['recap'] = {key: summary.get(key) for key in fields}
        result['recap']['required'] = False
    return result


def recap_read(service, session_id, task_id=None, offset=0, limit=20):
    from .recaps import RecapStore
    store = RecapStore(service)
    if task_id is None:
        return store.read(session_id)
    task = next((item for item in store.tasks(session_id) if item['task_id'] == task_id), None)
    if task is None:
        raise ValueError('RECAP_TASK_NOT_AVAILABLE')
    task_view = store.task_view(session_id, task_id)
    # A rolling recap uses the previous file plus this completed chapter. Do
    # not repeatedly ship every earlier chapter's complete transcript.
    chapter = task['chapter_number']
    visible = {**task_view,
               'history': [event for event in task_view.get('history', [])
                           if (event.get('chapter') or {}).get('chapter_number') == chapter],
               'records': [record for record in task_view.get('records', [])
                           if (record.get('chapter') or {}).get('chapter_number') == chapter]}
    summary = store.read(session_id, actor=task['actor'])
    previous = task_view.get('previous_recap', {})
    if previous:
        if previous.get('revision') != summary.get('revision'):
            summary['file_path'] = None
            summary.pop('latest_file_path', None)
        summary.update(previous)
    return {**summary, 'task': task,
            'evidence': history_page(visible, offset, limit),
            'instruction': '由玩家本人更新前情摘要，只用本角色已见事实；区分不确定推断。保留后续理解情节需要的人物、关系和未决事项。'}

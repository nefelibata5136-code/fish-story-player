import json

import pytest

from fish_story.player_output import compact_view, history_page


def test_step_response_never_repeats_whole_history_or_previous_role_receipt():
    view = {'session_id': 'local', 'status': 'waiting', 'accepted_choices': 900,
            'current': {'context': 'CURRENT_ROLE_SCENE'},
            'perspective': {'controlled_characters': ['Kara']},
            'history': [{'context': 'OLD_HISTORY_SENTINEL'}] * 1000,
            'records': [{'request_id': 'earlier', 'outcome': ['EARLIER_ROLE_SENTINEL']}] * 1000}
    compact = compact_view(view, request_id='just-chosen-other-role', choice=1)
    encoded = json.dumps(compact)
    assert len(encoded) < 1500
    assert 'CURRENT_ROLE_SCENE' in encoded
    assert 'OLD_HISTORY_SENTINEL' not in encoded and 'EARLIER_ROLE_SENTINEL' not in encoded
    assert compact['acceptance']['accepted'] is True
    assert 'visible_outcomes' not in compact
    view['records'].append({'request_id': 'this-role', 'outcome': ['VISIBLE_ACTUAL_RESULT']})
    assert compact_view(view, 'this-role', 1)['visible_outcomes'] == ['VISIBLE_ACTUAL_RESULT']


def test_history_pages_reassemble_complete_bounded_evidence_without_silent_truncation():
    view = {'session_id': 'local', 'history': list(range(73)), 'records': list(range(31))}
    events, records, offset = [], [], 0
    while offset is not None:
        page = history_page(view, offset, 20)
        assert len(page['history']) <= 20 and len(page['records']) <= 20
        events.extend(page['history']); records.extend(page['records'])
        offset = page['next_offset']
    assert events == view['history'] and records == view['records']
    for offset, limit in ((-1, 20), (0, 0), (0, 51), (True, 20)):
        with pytest.raises(ValueError, match='INVALID_HISTORY_PAGE'):
            history_page(view, offset, limit)

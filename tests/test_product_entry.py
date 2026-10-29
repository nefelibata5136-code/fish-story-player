"""Product entry checks through real loopback HTTP, without story/API networks."""
import copy
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from fish_story.planning import story_plan
from fish_story.server import make_server
from fish_story.service import GameService, PACKAGE, read_json


def request(base, path, body=None, headers=None):
    headers = headers or {}
    if body is not None:
        body = json.dumps(body).encode()
        headers = {'Content-Type': 'application/json', **headers}
    with urlopen(Request(base + path, data=body, headers=headers), timeout=5) as response:
        return json.load(response)


@pytest.fixture
def product_server(tmp_path):
    service = GameService(tmp_path / 'private')
    server = make_server(service, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}', service
    server.shutdown()
    server.server_close()
    thread.join()


def test_fresh_http_start_does_not_silently_open_demo(product_server):
    base, service = product_server
    boot = request(base, '/api/bootstrap')
    assert boot['default_story_id'] is None
    with pytest.raises(HTTPError) as failed:
        request(base, '/api/new', {'player_id': 'fish'}, {'X-Fish-CSRF': boot['csrf']})
    assert failed.value.code == 400
    assert json.load(failed.value)['error'] in {'DETROIT_NOT_INSTALLED', 'NO_DEFAULT_STORY'}
    assert service.sessions() == []
    # The existing original demonstration remains usable by explicit selection.
    demo = request(base, '/api/new', {'player_id': 'fish', 'story_id': 'demo'}, {'X-Fish-CSRF': boot['csrf']})
    assert demo['story_id'] == 'demo'


def test_planning_counts_variants_without_exposing_future_text_or_rules(tmp_path):
    service = GameService(tmp_path / 'private')
    doc = copy.deepcopy(read_json(PACKAGE / 'demo' / 'ch01_fog_letter.json'))
    doc['nodes'][0]['player_facing'] = {
        'context': 'FUTURE_NARRATIVE_SENTINEL',
        'choices_variants': {'arbitrary-name': [{'id': 'secret', 'text': 'FUTURE_CHOICE_SENTINEL'}]},
    }
    doc['nodes'][0]['system'] = {'choices_condition': {'arbitrary-name': 'SECRET_RULE_SENTINEL'}}
    path = tmp_path / 'original.json'
    path.write_text(json.dumps(doc), encoding='utf-8')
    imported = service.import_story([str(path)], 'Original synthetic source')
    result = story_plan(service, imported['id'])
    assert result['decision_node_capacity'] == 2
    assert result['suggested_max_calls'] >= result['decision_node_capacity']
    assert result['suggested_token_budget'] > result['maximum_output_tokens']
    serialized = json.dumps(result)
    assert 'FUTURE_' not in serialized and 'SECRET_RULE' not in serialized
    assert service.sessions() == []
    larger = story_plan(service, imported['id'], core_characters=20_000)
    assert larger['suggested_token_budget'] > result['suggested_token_budget']
    # Mutually exclusive variants never accumulate into one visible scene.
    doc['nodes'][0]['player_facing']['choices_variants'].update({
        'alternative-' + str(i): [{'id': 'secret', 'text': 'FUTURE_CHOICE_SENTINEL'}]
        for i in range(30)
    })
    path.write_text(json.dumps(doc), encoding='utf-8')
    repeated = service.import_story([str(path)], 'Same-sized exclusive alternatives')
    same_capacity = story_plan(service, repeated['id'])
    assert same_capacity['rough_input_tokens'] == result['rough_input_tokens']
    assert same_capacity['suggested_token_budget'] == result['suggested_token_budget']


def test_http_plan_is_readonly_and_still_checks_local_origin(product_server):
    base, service = product_server
    result = request(base, '/api/story-plan?story_id=demo&chapter=1')
    assert result['chapter_count'] == 2
    assert result['decision_node_capacity'] == 4
    assert result['makes_model_requests'] is False
    assert service.sessions() == []
    for query in ('chapter=0', 'core_characters=20001', 'max_output_tokens=0'):
        with pytest.raises(HTTPError):
            request(base, '/api/story-plan?story_id=demo&' + query)
    with pytest.raises(HTTPError) as denied:
        request(base, '/api/story-plan?story_id=demo', headers={'Origin': 'https://other.invalid'})
    assert denied.value.code == 403


def test_agent_setup_route_delegates_only_explicit_bound_parameters(product_server, monkeypatch):
    import sys
    import types
    base, service = product_server
    calls = []
    module = types.ModuleType('fish_story.agent_setup')
    def connection_info(actual_service, player_id, play_style, session_id):
        assert actual_service is service
        calls.append((player_id, play_style, session_id))
        return {'mcp_config': {'mcpServers': {}}, 'agent_instructions': 'BOUND_AGENT_SETUP'}
    module.connection_info = connection_info
    monkeypatch.setitem(sys.modules, 'fish_story.agent_setup', module)
    result = request(base, '/api/agent-setup?player_id=fish&play_style=immersive&session_id=selected')
    assert result['agent_instructions'] == 'BOUND_AGENT_SETUP'
    assert calls == [('fish', 'immersive', 'selected')]
    assert service.sessions() == []
    with pytest.raises(HTTPError) as denied:
        request(base, '/api/agent-setup', headers={'Origin': 'null'})
    assert denied.value.code == 403
    assert len(calls) == 1

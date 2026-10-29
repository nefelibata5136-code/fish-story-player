"""No paid calls: exercise the actual HTTP wire against a local fake provider."""
import copy
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fish_story.model import IndependentPlayer, SYSTEM, validate_core, load_config


class StubService:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(exist_ok=True)
        (self.directory / 'core.txt').write_text('A player with private background.', encoding='utf-8')
        self.state = {
            'session_id': 'session', 'mode': 'independent', 'status': 'waiting', 'accepted_choices': 0,
            'current': self.scene(1), 'history': [self.event(1)],
        }
        self.receipts = {}

    @staticmethod
    def scene(n):
        return {'request_id': 'request-' + str(n), 'chapter': {'chapter_number': 1, 'protagonist': 'Fictional courier'},
                'context': 'Visible scene ' + str(n), 'choices': [{'number': 1, 'text': 'Look'}, {'number': 2, 'text': 'Leave'}]}

    @classmethod
    def event(cls, n):
        return {'type': 'node_shown', **{k: v for k, v in cls.scene(n).items() if k != 'request_id'}}

    def session_dir(self, session_id):
        return self.directory

    def view(self, session_id):
        return copy.deepcopy(self.state)

    def choose(self, session_id, request_id, choice, reason=''):
        if request_id in self.receipts:
            if self.receipts[request_id] != (choice, reason):
                raise ValueError('ANSWER_ALREADY_ACCEPTED')
            return self.view(session_id)
        if self.state['status'] != 'waiting' or request_id != self.state['current']['request_id']:
            raise ValueError('STALE_REQUEST')
        self.receipts[request_id] = (choice, reason)
        self.state['history'].append({'type': 'decision', 'choice_text': self.state['current']['choices'][choice - 1]['text'], 'reasoning': reason})
        self.state['accepted_choices'] += 1
        if self.state['accepted_choices'] == 2:
            self.state.update(status='complete', current=None)
            self.state['history'].append({'type': 'chapter_end', 'ending': {'title': 'Arrival', 'narrative': 'The courier reached the island.'}})
        else:
            self.state['current'] = self.scene(2)
            self.state['history'].append(self.event(2))
        return self.view(session_id)


class Provider:
    def __init__(self):
        self.requests, self.responses = [], []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append({'path': self.path, 'body': body})
                response = owner.responses.pop(0) if owner.responses else owner.answer()
                if isinstance(response, int):
                    self.send_response(response)
                    if response == 302:
                        self.send_header('Location', owner.base + '/redirected')
                    self.end_headers()
                    self.wfile.write(b'PRIVATE_ERROR_DO_NOT_SAVE')
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.base = 'http://127.0.0.1:' + str(self.server.server_port) + '/v1'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @staticmethod
    def answer(choice=1, reason='I prefer to look.', usage=True):
        value = {'choices': [{'message': {'content': json.dumps({'choice': choice, 'public_reason': reason, 'invented_ending': 'IGNORE_THIS'}), 'reasoning_content': 'SECRET_REASONING'}}]}
        if usage:
            value['usage'] = {'prompt_tokens': 150, 'completion_tokens': 25, 'prompt_tokens_details': {'cached_tokens': 100}, 'private': 'SECRET_USAGE'}
        return value

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = StubService(self.temp.name)
        self.provider = Provider()
        self.env = patch.dict(os.environ, {'FISH_TEST_KEY': 'local-test-key'})
        self.env.start()
        self.config = {'base_url': self.provider.base, 'model': 'fake-model', 'api_key_env': 'FISH_TEST_KEY',
                       'max_calls': 4, 'token_budget': 100000, 'max_cost': 1.0, 'input_per_million': 1,
                       'output_per_million': 2, 'max_output_tokens': 128, 'timeout': 2}

    def tearDown(self):
        self.env.stop()
        self.provider.close()
        self.temp.cleanup()

    def player(self, **changes):
        return IndependentPlayer(self.service, 'session', {**self.config, **changes})

    def test_core_preview_exact_and_limits(self):
        text = '身份\n' * 6666
        result = validate_core(text)
        self.assertEqual(result['content'], text)
        self.assertEqual(result['characters'], len(text))
        self.assertGreater(result['estimated_tokens'], 0)
        with self.assertRaisesRegex(ValueError, 'CORE_TOO_LONG'):
            validate_core('x' * 20001)
        with self.assertRaisesRegex(ValueError, 'INVALID_CORE'):
            validate_core(' ')

    def test_actual_http_progress_prefix_and_private_fields(self):
        player = self.player()
        first = player.step()
        self.assertEqual(first['status'], 'applied')
        second = self.player().run()
        self.assertEqual(second['view']['status'], 'complete')
        self.assertEqual(len(self.provider.requests), 2)
        before, after = [item['body']['messages'] for item in self.provider.requests]
        self.assertEqual(after[:len(before)], before)
        self.assertTrue(before[0]['content'].startswith(SYSTEM))
        self.assertNotIn('Visible scene 2', json.dumps(before))
        self.assertNotIn('The courier reached', json.dumps(after))
        status = self.player().status()
        self.assertEqual(status['call_count'], 2)
        self.assertAlmostEqual(status['calls'][-1]['usage']['latest_cache_hit_ratio'], 2 / 3)
        db_bytes = (Path(self.temp.name) / 'model.sqlite').read_bytes()
        for private in (b'local-test-key', b'SECRET_REASONING', b'SECRET_USAGE', b'IGNORE_THIS'):
            self.assertNotIn(private, db_bytes)
        self.assertEqual(status['accounted_tokens'], 350)

    def test_actual_game_service_full_demo_and_restart(self):
        from fish_story.service import GameService
        service = GameService(Path(self.temp.name) / 'actual-game')
        view = service.start('test-player', mode='independent', core_text='An original player, separate from story roles.')
        config = {**self.config, 'max_calls': 20, 'token_budget': 500000}
        session_id = view['session_id']
        first = IndependentPlayer(service, session_id, config).step()
        self.assertEqual(first['status'], 'applied')
        final = IndependentPlayer(GameService(service.directory), session_id, config).run()
        self.assertEqual(final['view']['status'], 'complete')
        self.assertEqual(final['view']['accepted_choices'], len(self.provider.requests))
        wire = [item['body']['messages'] for item in self.provider.requests]
        for earlier, later in zip(wire, wire[1:]):
            self.assertEqual(later[:len(earlier)], earlier)
        self.assertGreaterEqual(len(final['view']['records']), 2)

    def test_provider_options_are_explicit_and_pinned(self):
        player = self.player(thinking='disabled', json_mode=True)
        player.step()
        body = self.provider.requests[0]['body']
        self.assertEqual(body['thinking'], {'type': 'disabled'})
        self.assertEqual(body['response_format'], {'type': 'json_object'})
        config = load_config(self.service, 'session')
        self.assertEqual(config['thinking'], 'disabled')
        self.assertIs(config['json_mode'], True)
        with self.assertRaisesRegex(ValueError, 'MODEL_CONFIG_OR_CORE_CHANGED'):
            self.player(thinking='enabled', json_mode=True)

    def test_free_local_provider_still_has_finite_call_and_token_limits(self):
        player = self.player(input_per_million=0, output_per_million=0, max_calls=1)
        player.step()
        self.assertEqual(player.status()['accounted_cost'], 0)
        with self.assertRaisesRegex(ValueError, 'MODEL_BUDGET_EXHAUSTED'):
            self.player(input_per_million=0, output_per_million=0, max_calls=1).step()
        self.assertNotIn('thinking', self.provider.requests[0]['body'])
        self.assertNotIn('response_format', self.provider.requests[0]['body'])
        self.assertEqual(len(self.provider.requests), 1)

    def test_load_config_is_read_only_and_contains_no_key(self):
        self.assertIsNone(load_config(self.service, 'session'))
        self.assertFalse((Path(self.temp.name) / 'model.sqlite').exists())
        self.player()
        config = load_config(self.service, 'session')
        self.assertEqual(config['model'], 'fake-model')
        self.assertEqual(config['api_key_env'], 'FISH_TEST_KEY')
        self.assertNotIn('local-test-key', json.dumps(config))

    def test_call_limit_persists_restart(self):
        self.player(max_calls=1).step()
        with self.assertRaisesRegex(ValueError, 'MODEL_BUDGET_EXHAUSTED'):
            self.player(max_calls=1).step()
        self.assertEqual(len(self.provider.requests), 1)

    def test_no_request_when_reservation_exceeds_token_or_cost_limit(self):
        with self.assertRaisesRegex(ValueError, 'MODEL_BUDGET_EXHAUSTED'):
            self.player(token_budget=1).step()
        self.assertEqual(len(self.provider.requests), 0)

    def test_cost_reservation_limit_prevents_network(self):
        with self.assertRaisesRegex(ValueError, 'MODEL_BUDGET_EXHAUSTED'):
            self.player(max_cost=0.000001).step()
        self.assertEqual(len(self.provider.requests), 0)
        self.assertEqual(self.player(max_cost=0.000001).status()['call_count'], 0)

    def test_first_configuration_is_atomic_under_concurrent_initialization(self):
        gate = threading.Barrier(2)
        results = []
        def initialize(max_calls):
            gate.wait()
            try:
                player = self.player(max_calls=max_calls)
                results.append(('ok', max_calls))
            except (ValueError, sqlite3.OperationalError) as error:
                results.append(('error', str(error)))
        workers = [threading.Thread(target=initialize, args=(limit,)) for limit in (2, 3)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        winners = [value for status, value in results if status == 'ok']
        self.assertLessEqual(len(winners), 1, results)
        if not winners:
            # Both first-time creators may fail closed on a zero-timeout SQLite
            # lock. An explicit later retry pins one configuration, never both.
            self.player(max_calls=2)
            winners = [2]
        other = 3 if winners[0] == 2 else 2
        with self.assertRaisesRegex(ValueError, 'MODEL_CONFIG_OR_CORE_CHANGED'):
            self.player(max_calls=other)
        self.assertEqual(len(self.provider.requests), 0)

    def test_unknown_usage_stops_and_preserves_reservation(self):
        self.provider.responses = [Provider.answer(usage=False)]
        player = self.player()
        with self.assertRaisesRegex(ValueError, 'MODEL_USAGE_UNKNOWN'):
            player.step()
        status = player.status()
        self.assertTrue(status['blocked'])
        self.assertGreater(status['accounted_tokens'], 0)
        with self.assertRaisesRegex(ValueError, 'UNRESOLVED_MODEL_CALL'):
            self.player().step()
        self.assertEqual(len(self.provider.requests), 1)
        call = status['calls'][0]
        player.acknowledge_unknown(call['id'])
        self.assertEqual(player.status()['accounted_tokens'], status['accounted_tokens'])
        self.player().step()
        self.assertEqual(len(self.provider.requests), 2)

    def test_invalid_choice_does_not_modify_game_or_refund_call(self):
        self.provider.responses = [Provider.answer(choice=99)]
        with self.assertRaisesRegex(ValueError, 'INVALID_MODEL_CHOICE'):
            self.player().step()
        self.assertEqual(self.service.state['accepted_choices'], 0)
        status = self.player().status()
        self.assertEqual(status['call_count'], 1)
        self.assertEqual(status['accounted_tokens'], 175)
        self.assertEqual(status['calls'][0]['status'], 'rejected')

    def test_redirect_is_not_followed_and_body_not_logged(self):
        self.provider.responses = [302]
        with self.assertRaisesRegex(ValueError, 'MODEL_RESULT_UNKNOWN'):
            self.player().step()
        self.assertEqual(len(self.provider.requests), 1)
        status = self.player().status()
        self.assertEqual(status['calls'][0]['error'], 'HTTP_302')
        self.assertNotIn(b'PRIVATE_ERROR', (Path(self.temp.name) / 'model.sqlite').read_bytes())

    def test_usage_overrun_blocks_and_accounts_actual(self):
        response = Provider.answer()
        response['usage'].update(prompt_tokens=200000, completion_tokens=1000)
        self.provider.responses = [response]
        with self.assertRaisesRegex(ValueError, 'MODEL_USAGE_EXCEEDED_RESERVATION'):
            self.player().step()
        status = self.player().status()
        self.assertTrue(status['blocked'])
        self.assertEqual(status['accounted_tokens'], 201000)
        self.assertEqual(self.service.state['accepted_choices'], 0)

    def test_config_and_core_pinned_across_restart(self):
        self.player().step()
        with self.assertRaisesRegex(ValueError, 'MODEL_CONFIG_OR_CORE_CHANGED'):
            self.player(max_calls=10)
        (Path(self.temp.name) / 'core.txt').write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'MODEL_CONFIG_OR_CORE_CHANGED'):
            self.player()

    def test_ready_receipt_after_crash_never_repeats_api(self):
        player = self.player()
        choose = self.service.choose
        def committed_then_crash(*args):
            choose(*args)
            raise RuntimeError('simulated process death after game commit')
        with patch.object(self.service, 'choose', side_effect=committed_then_crash):
            with self.assertRaises(RuntimeError):
                player.step()
        self.assertEqual(self.service.state['accepted_choices'], 1)
        resumed = self.player().step()
        self.assertEqual(resumed['status'], 'applied')
        self.assertEqual(self.service.state['accepted_choices'], 1)
        self.assertEqual(len(self.provider.requests), 1)

    def test_reserved_crash_blocks_without_request(self):
        player = self.player()
        player._reserve('request-1', player.messages())
        with self.assertRaisesRegex(ValueError, 'UNRESOLVED_MODEL_CALL'):
            self.player().step()
        self.assertEqual(len(self.provider.requests), 0)

    def test_stale_concurrent_scene_cannot_reserve_a_second_paid_call(self):
        stale = self.service.view('session')
        player = self.player()
        player.step()
        self.assertEqual(self.service.state['accepted_choices'], 1)
        before = player.status()
        # Reproduce a second caller's already-read scene after the first caller
        # committed. The actual SQLite transaction must reject before HTTP.
        with patch.object(self.service, 'view', return_value=stale):
            with self.assertRaisesRegex(ValueError, 'STALE_REQUEST'):
                self.player().step()
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(player.status(), before)

    def test_mode_and_endpoint_budget_validation(self):
        for change in ({'max_calls': 0}, {'input_per_million': -1}, {'max_cost': float('nan')},
                       {'base_url': 'http://example.com/v1'}, {'api_key': 'literal'}, {'timeout': 200}):
            with self.assertRaises(ValueError):
                self.player(**change)
        self.service.state['mode'] = 'agent'
        with self.assertRaisesRegex(ValueError, 'INDEPENDENT_MODE_REQUIRED'):
            self.player()
        self.assertEqual(len(self.provider.requests), 0)


if __name__ == '__main__':
    unittest.main()

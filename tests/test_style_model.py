"""Decision-style wire checks against a real local HTTP transport; no paid API."""
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fish_story.model import IndependentPlayer, SYSTEM
from fish_story.service import GameService
from test_model import Provider, StubService


class StyleModelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.service = GameService(self.root / 'game')
        self.provider = Provider()
        self.env = patch.dict(os.environ, {'FISH_STYLE_TEST_KEY': 'local-fake-key'})
        self.env.start()
        self.config = {'base_url': self.provider.base, 'model': 'fake-model', 'api_key_env': 'FISH_STYLE_TEST_KEY',
                       'max_calls': 10, 'token_budget': 500000, 'max_cost': 1.0,
                       'input_per_million': 1.0, 'output_per_million': 2.0,
                       'max_output_tokens': 128, 'timeout': 2}

    def tearDown(self):
        self.env.stop()
        self.provider.close()
        self.temporary.cleanup()

    def start(self, style):
        paths = []
        for chapter, actor in ((1, 'Actor-A'), (2, 'Actor-B'), (3, 'Actor-A')):
            path = self.root / f'ch{chapter}.json'
            doc = {'_meta': {'language': 'en'},
                   'chapter': {'id': f'chapter-{chapter}', 'chapter_number': chapter,
                               'title': f'Visible chapter {chapter}', 'protagonist': actor},
                   'system_prompt': {'content': 'HIDDEN_ROLE_PROMPT_DO_NOT_FORWARD'},
                   'state': {'initial': {}},
                   'nodes': [{'id': f'choice-{chapter}', 'type': 'choice',
                              'player_facing': {'context': f'{actor}_SCENE_SECRET_{chapter}',
                                                'choices': [{'id': 'continue', 'text': 'Continue'}]},
                              'system': {'ending_resolution': {'continue': {'result': 'ending_a'}}}}],
                   'endings': {'ending_a': {'title': f'{actor} chapter result',
                                            'narrative': f'{actor}_ENDING_SECRET_{chapter}'}}}
            path.write_text(json.dumps(doc), encoding='utf-8')
            paths.append(str(path))
        story = self.service.import_story(paths, 'Synthetic alternating actors')
        view = self.service.start('generic-test-player', story_id=story['id'], mode='independent',
                                  core_text='CORE_IDENTITY_SENTINEL: a player separate from every story role.',
                                  play_style=style)
        return view['session_id']

    def test_immersive_actual_wire_is_per_character_and_resumes_its_prefix(self):
        session_id = self.start('immersive')
        player = IndependentPlayer(self.service, session_id, self.config)
        player.step()
        IndependentPlayer(GameService(self.service.directory), session_id, self.config).step()
        final = IndependentPlayer(GameService(self.service.directory), session_id, self.config).run()
        self.assertEqual(final['view']['status'], 'complete')
        wire = [request['body']['messages'] for request in self.provider.requests]
        self.assertEqual(len(wire), 3)
        first, second, third = [json.dumps(messages) for messages in wire]
        self.assertIn('Actor-A_SCENE_SECRET_1', first)
        self.assertNotIn('Actor-B_', first)
        self.assertIn('Actor-B_SCENE_SECRET_2', second)
        self.assertNotIn('Actor-A_SCENE_SECRET_1', second)
        self.assertNotIn('Actor-A_ENDING_SECRET_1', second)
        self.assertIn('Actor-A_SCENE_SECRET_1', third)
        self.assertIn('Actor-A_SCENE_SECRET_3', third)
        self.assertNotIn('Actor-B_SCENE_SECRET_2', third)
        self.assertNotIn('Actor-B_ENDING_SECRET_2', third)
        self.assertEqual(wire[2][:len(wire[0])], wire[0])
        self.assertEqual(wire[0][0], wire[1][0])
        self.assertEqual(wire[1][0], wire[2][0])
        for messages in wire:
            serialized = json.dumps(messages)
            self.assertIn('CORE_IDENTITY_SENTINEL', serialized)
            self.assertNotIn('HIDDEN_ROLE_PROMPT', serialized)
        self.assertEqual(len(self.service.observe(session_id)['records']), 3)
        self.assertEqual(final['budget']['call_count'], 3)

    def test_self_aware_actual_wire_retains_all_seen_characters(self):
        session_id = self.start('self_aware')
        final = IndependentPlayer(self.service, session_id, self.config).run()
        self.assertEqual(final['view']['status'], 'complete')
        wire = [request['body']['messages'] for request in self.provider.requests]
        self.assertIn('Actor-A_SCENE_SECRET_1', json.dumps(wire[1]))
        self.assertIn('Actor-A_ENDING_SECRET_1', json.dumps(wire[1]))
        self.assertIn('Actor-B_SCENE_SECRET_2', json.dumps(wire[2]))
        for earlier, later in zip(wire, wire[1:]):
            self.assertEqual(later[:len(earlier)], earlier)

    def test_style_is_pinned_and_cannot_change_on_existing_player(self):
        session_id = self.start('immersive')
        player = IndependentPlayer(self.service, session_id, self.config)
        player.step()
        path = self.service.session_dir(session_id) / 'session.json'
        meta = json.loads(path.read_text(encoding='utf-8'))
        meta['play_style'] = 'self_aware'
        path.write_text(json.dumps(meta), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'MODEL_CONFIG_OR_CORE_CHANGED'):
            IndependentPlayer(self.service, session_id, self.config)
        with self.assertRaisesRegex(ValueError, 'MODEL_CONFIG_OR_CORE_CHANGED'):
            player.step()
        self.assertEqual(len(self.provider.requests), 1)

    def test_observer_history_cannot_accidentally_become_an_immersive_request(self):
        session_id = self.start('immersive')
        player = IndependentPlayer(self.service, session_id, self.config)
        player.step()  # Now controlling Actor-B; observer still includes Actor-A.
        observer = self.service.observe(session_id)
        with patch.object(self.service, 'view', return_value=observer):
            with self.assertRaisesRegex(ValueError, 'ROLE_PERSPECTIVE_UNAVAILABLE'):
                player.step()
        self.assertEqual(len(self.provider.requests), 1)

    def test_ambiguous_actor_stops_before_reserving_or_requesting(self):
        session_id = self.start('immersive')
        player = IndependentPlayer(self.service, session_id, self.config)
        ambiguous = self.service.view(session_id)
        ambiguous['perspective']['controlled_characters'] = []
        with patch.object(self.service, 'view', return_value=ambiguous):
            with self.assertRaisesRegex(ValueError, 'ROLE_PERSPECTIVE_UNAVAILABLE'):
                player.step()
        self.assertEqual(player.status()['call_count'], 0)
        self.assertEqual(len(self.provider.requests), 0)

    def test_legacy_session_keeps_old_core_hash_prefix_and_ledger(self):
        service = StubService(self.root / 'legacy')
        first = IndependentPlayer(service, 'session', self.config)
        self.assertEqual(first.messages()[0]['content'], SYSTEM + first.core)
        first.step()
        with closing(sqlite3.connect(service.directory / 'model.sqlite')) as db:
            saved_hash = db.execute('SELECT core_hash FROM settings WHERE id=1').fetchone()[0]
        self.assertEqual(saved_hash, hashlib.sha256(first.core.encode('utf-8')).hexdigest())
        old_wire = self.provider.requests[0]['body']['messages']
        second = IndependentPlayer(service, 'session', self.config).run()
        self.assertEqual(second['budget']['call_count'], 2)
        self.assertEqual(self.provider.requests[1]['body']['messages'][:len(old_wire)], old_wire)


if __name__ == '__main__':
    unittest.main()

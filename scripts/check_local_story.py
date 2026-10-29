"""Optional read-only compatibility check for user-supplied local chapters.

Never used by public CI; no chapters or transcripts are copied into this repo.
The first-option scripted run is a software fixture, not a real Agent's game.
"""
import argparse
import glob
import json
import random
import tempfile
from pathlib import Path

from fish_story.service import GameService
from fish_story.engine import Player, Store
from campaign_runner import run_campaign
from runner import ScriptedAI


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pattern')
    parser.add_argument('--limit', type=int, default=3)
    args = parser.parse_args()
    paths = sorted(glob.glob(args.pattern))[:args.limit]
    if not paths:
        raise SystemExit('NO_CHAPTERS')
    with tempfile.TemporaryDirectory(prefix='fish-story-compat-') as temporary:
        service = GameService(temporary)
        story = service.import_story(paths, 'Local compatibility fixture')
        start = service.start('compatibility-fixture', story['id'], difficulty='experienced',
                              chapter=json.loads(Path(paths[0]).read_text(encoding='utf-8'))['chapter']['chapter_number'])
        store = service._store(start['session_id'])
        with store.connect() as db:
            run = store.load(db, 'player')
        native = []
        run_campaign(paths, ScriptedAI(), difficulty='experienced', rng=random.Random(run['seed']), on_event=native.append)
        view = start
        while view['status'] == 'waiting':
            current = view['current']
            view = service.choose(view['session_id'], current['request_id'], 1, 'scripted choice')
        assert [e['context'] for e in native if e['type'] == 'node_shown'] == [e['context'] for e in view['history'] if e['type'] == 'node_shown']
        expected = [ending['narrative'] for e in native if e['type'] == 'chapter_end' for ending in (e.get('all_endings') or [e['ending']])]
        assert expected == [e['ending']['narrative'] for e in view['history'] if e['type'] == 'chapter_end']
        assert GameService(temporary).view(start['session_id']) == view
        print(json.dumps({'passed': True, 'chapters': len(paths), 'scripted_choices': view['accepted_choices'],
                          'native_contexts_equal': True, 'native_endings_equal': True, 'restart_equal': True,
                          'real_agent_choices': False, 'model_calls': 0}))


if __name__ == '__main__':
    main()

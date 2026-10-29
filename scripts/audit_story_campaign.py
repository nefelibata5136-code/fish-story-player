"""Audit privately supplied chapters without copying their text into the report.

Static checks cover every declared context variant and ending reference. Seeded
scripted routes sample state combinations; this is never called exhaustive
branch verification or an actual model/DSH Agent playthrough. No model calls.
"""
from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
import random
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fish_story.detroit_compat import COMPATIBILITY_VERSION, normalize_detroit_chapter
from fish_story.engine import Player  # Installs the native engine import seam.
from fish_story.service import GameService
from fish_story.styles import _canonical, _names, _visible_label
from campaign_runner import run_campaign


def ending_references(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from ending_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from ending_references(item)
    elif isinstance(value, str):
        if re.fullmatch(r'ending_[A-Za-z0-9_]+', value):
            yield value
        yield from re.findall(r'→\s*(ending_[A-Za-z0-9_]+)', value)


def static_audit(docs):
    decisions, contexts, nodes, references = 0, 0, 0, 0
    missing_roles, observer_only_narratives, missing_endings, variants = [], [], [], []
    for doc in docs:
        number = doc['chapter']['chapter_number']
        candidates = _names(doc['chapter'].get('protagonist'))
        for node in doc['nodes']:
            nodes += 1
            player = node['player_facing']
            has_choices = any(key.startswith('choices') for key in player)
            decisions += has_choices
            scenes = {'default': player['context']} if 'context' in player else player.get('context_variants', {})
            for variant, text in scenes.items():
                contexts += 1
                explicit = _canonical(player.get('perspective'), candidates)
                invalid = 'perspective' in player and explicit is None
                heading = _visible_label(text, candidates)
                phase = (node.get('phase') or '').split('_', 1)[0]
                track = next((actor for actor in candidates if actor.lower() == phase), None)
                actor = explicit or (candidates[0] if len(candidates) == 1 else None) or heading or track
                if invalid or (explicit and heading and explicit != heading):
                    actor = None
                item = {'chapter': number, 'node_id': node['id'], 'variant': variant}
                if actor is None:
                    (missing_roles if has_choices else observer_only_narratives).append(item)
                if heading == 'North':
                    variants.append({**item, 'actor': 'North', 'separate_from_track': track})
            for target in ending_references(node.get('system', {})):
                references += 1
                if not isinstance(doc['endings'].get(target), dict):
                    missing_endings.append({'chapter': number, 'node_id': node['id'], 'target': target})
    return {'chapters': len(docs), 'nodes': nodes, 'decision_nodes': decisions,
            'context_variants': contexts, 'ending_references': references,
            'unattributed_decision_variants': missing_roles,
            'observer_only_narrative_variants': observer_only_narratives,
            'missing_ending_targets': missing_endings,
            'separate_substitute_variants': variants}


class SeededPolicy:
    """Fixture chooses from available options, never consults hidden outcome data."""
    def __init__(self, seed, policy='random'):
        self.rng = random.Random(seed)
        self.policy = policy

    def choose(self, node_id, context, choices, messages):
        index = (0 if self.policy == 'first' else len(choices) - 1 if self.policy == 'last'
                 else self.rng.randrange(len(choices)))
        return {'choice_id': choices[index]['id'], 'reasoning': 'scripted audit fixture',
                'raw': json.dumps({'choice': index + 1})}


def sampled_campaigns(paths, runs):
    visited, endings, errors = set(), set(), []
    completed, death_outcomes, decisions = 0, 0, 0
    inherited_chapter_starts = 0
    terminal_chapter = None
    routes_with_terminal_kara_outcome = 0
    authored_kara_nodes = set()
    role_metadata, chapter_numbers = {}, {}
    markus_terminal_at, connor_death_at = None, None
    prior_terminal_characters = set()
    north_after_death, connor_replacement = False, False
    markus_death_routes = north_substitute_routes = connor_death_routes = connor_replacement_routes = 0
    for index, path in enumerate(paths, 1):
        doc = json.loads(path.read_text(encoding='utf-8'))
        number = doc['chapter']['chapter_number']
        chapter_numbers[index] = number
        for node in doc['nodes']:
            role_metadata[number, node['id']] = (_names(doc['chapter'].get('protagonist')),
                                                  node['player_facing'].get('perspective'),
                                                  (node.get('phase') or '').split('_', 1)[0])
            if node['id'].startswith('compat_'):
                continue
            if (doc['chapter'].get('protagonist') == 'Kara' or number == 13
                    or node['id'] == 'n005_no_attack' and number == 30
                    or node['id'].startswith(('n001_kara_', 'n006_kara_', 'n007_kara_', 'n008_kara_'))
                    or (node.get('phase') or '').startswith('kara_')):
                authored_kara_nodes.add((number, node['id']))
    def event(value):
        nonlocal decisions, death_outcomes, inherited_chapter_starts, terminal_chapter
        nonlocal markus_terminal_at, connor_death_at, north_after_death, connor_replacement
        chapter = chapter_numbers.get(value.get('chapter_index'))
        if value['type'] == 'node_shown':
            visited.add((chapter, value['node_id']))
            if terminal_chapter and chapter > terminal_chapter:
                assert (chapter, value['node_id']) not in authored_kara_nodes, 'KARA_STORY_RESURRECTED'
            candidates, explicit, track = role_metadata[chapter, value['node_id']]
            actor = (_canonical(explicit, candidates) or _visible_label(value['context'], candidates)
                     or (candidates[0] if len(candidates) == 1 else None)
                     or next((actor for actor in candidates if actor.lower() == track), None))
            if markus_terminal_at and chapter > markus_terminal_at:
                assert actor != 'Markus', 'MARKUS_RESURRECTED_AFTER_FINAL_DEATH'
                north_after_death |= actor == 'North'
            if connor_death_at and chapter > connor_death_at and actor == 'Connor':
                connor_replacement = True
        elif value['type'] == 'decision':
            decisions += 1
        elif value['type'] == 'chapter_start' and value.get('config', {}).get('cross_chapter_state_injected'):
            inherited_chapter_starts += 1
        elif value['type'] == 'chapter_end':
            for ending in value.get('all_endings') or [value['ending']]:
                assert not prior_terminal_characters & set(ending.get('survivors', [])), 'ENDING_REVIVES_TERMINAL_CHARACTER'
                endings.add((chapter, ending['id']))
                death_outcomes += bool(ending.get('deaths'))
                if chapter in (7, 13, 17) and {'Kara', 'Alice'} & set(ending.get('deaths', [])):
                    terminal_chapter = terminal_chapter or chapter
                    prior_terminal_characters.update({'Kara', 'Alice'} & set(ending.get('deaths', [])))
                if chapter in (28, 30) and 'Markus' in ending.get('deaths', []):
                    markus_terminal_at = markus_terminal_at or chapter
                    prior_terminal_characters.add('Markus')
                if chapter < 29 and any(str(name).startswith('Connor') for name in ending.get('deaths', [])):
                    connor_death_at = connor_death_at or chapter
    for seed in range(runs):
        terminal_chapter = None
        prior_terminal_characters = set()
        markus_terminal_at, connor_death_at = None, None
        north_after_death, connor_replacement = False, False
        difficulty = ('casual', 'experienced', 'hardcore')[seed % 3]
        try:
            result = run_campaign(paths, SeededPolicy(seed), difficulty=difficulty,
                                  rng=random.Random(seed), on_event=event)
            if len(result['chapters']) != len(paths):
                raise AssertionError('INCOMPLETE_CAMPAIGN')
            completed += 1
            routes_with_terminal_kara_outcome += terminal_chapter is not None
            markus_death_routes += markus_terminal_at is not None
            north_substitute_routes += north_after_death
            connor_death_routes += connor_death_at is not None
            connor_replacement_routes += connor_replacement
        except Exception as error:
            errors.append({'seed': seed, 'difficulty': difficulty, 'error_type': type(error).__name__})
    return {'runs_requested': runs, 'runs_complete': completed,
            'distinct_nodes_observed': len(visited), 'distinct_endings_observed': len(endings),
            'scripted_decisions': decisions, 'death_endings_observed': death_outcomes,
            'cross_chapter_injections_observed': inherited_chapter_starts,
            'terminal_kara_routes_without_resurrection': routes_with_terminal_kara_outcome,
            'markus_final_death_routes_without_resurrection': markus_death_routes,
            'north_substitute_routes_after_markus_death': north_substitute_routes,
            'connor_early_death_routes': connor_death_routes,
            'connor_authored_replacement_routes_observed': connor_replacement_routes,
            'errors': errors, 'model_calls': 0,
            'state_space_exhaustive': False}


def service_campaign(paths, style, policy):
    """Complete public service path, including pause/reopen/fork without resets."""
    with tempfile.TemporaryDirectory(prefix='fish-service-audit-') as home:
        service = GameService(home)
        story = service.import_story([str(path) for path in paths], 'Private audit chapters')
        view = service.start('audit-fixture', story_id=story['id'], play_style=style)
        session = view['session_id']
        point, original_at_fork, branch = None, None, None
        paused = restored = forked = False
        chapters = set()
        count = 0
        while view['status'] == 'waiting':
            current = view['current']
            chapters.add(current['chapter']['chapter_number'])
            if style == 'immersive':
                assert not view['perspective'].get('unavailable'), 'UNATTRIBUTED_DECISION'
                actor = view['perspective']['controlled_characters']
                assert all(event.get('controlled_characters') == actor for event in view['history'])
            if count == 4:
                paused_view = service.pause(session)
                assert paused_view['status'] == 'paused'
                service = GameService(home)
                assert service.view(session) == paused_view
                view = service.resume(session)
                paused = restored = True
                point = service.save_point(session, 'Audit checkpoint', operation_id='audit-checkpoint')
            if count == 6:
                original_at_fork = service.view(session)
                branch = service.load_save_point(session, point['id'], name='Audit alternate route',
                                                 operation_id='audit-fork')
                assert service.view(session) == original_at_fork
                assert branch['session_id'] != session
                branch_current = branch['current']
                branch_choice = len(branch_current['choices'])
                branch = service.choose(branch['session_id'], branch_current['request_id'], branch_choice)
                assert service.view(session) == original_at_fork
                forked = True
            choice = 1 if policy == 'first' else len(current['choices'])
            view = service.choose(session, current['request_id'], choice, 'scripted audit fixture')
            count += 1
            assert count <= 1000, 'RUN_LIMIT'
        assert view['status'] == 'complete'
        assert GameService(home).view(session) == view
        observer = service.observe(session)
        ended_chapters = {event['chapter']['chapter_number'] for event in observer['history']
                          if event['type'] == 'chapter_end'}
        assert len(ended_chapters) == len(paths), 'MISSING_CHAPTER_END'
        assert len(observer['records']) == count, 'RECORD_COUNT'
        authored_kara_refs = set()
        for path in paths:
            doc = json.loads(path.read_text(encoding='utf-8'))
            meta = {key: doc['chapter'].get(key) for key in ('chapter_number', 'title', 'title_zh', 'protagonist')}
            for node in doc['nodes']:
                if node['id'].startswith('compat_'):
                    continue
                if doc['chapter'].get('protagonist') == 'Kara' or doc['chapter']['chapter_number'] == 30 and node['id'] == 'n005_no_attack' or node['id'].startswith(('n001_kara_', 'n006_kara_', 'n007_kara_', 'n008_kara_')) or (node.get('phase') or '').startswith('kara_'):
                    authored_kara_refs.add(hashlib.sha256(f"{meta}:{node['id']}".encode()).hexdigest()[:20])
        terminal_at = None
        for event in observer['history']:
            number = event['chapter']['chapter_number']
            if (event['type'] == 'chapter_end'
                    and ('此前已结束' in (event['ending'].get('title') or ''))):
                terminal_at = terminal_at or number
            if terminal_at and number > terminal_at and event['type'] == 'node_shown':
                assert event['node_ref'] not in authored_kara_refs, 'KARA_STORY_RESURRECTED'
        return {'style': style, 'policy': policy, 'complete': True, 'choices': count,
                'chapters_completed': len(ended_chapters), 'pause_resume': paused,
                'restart_equal': restored, 'checkpoint_fork_keeps_original': forked,
                'all_visible_history_respects_actor': style == 'immersive',
                'prior_terminal_route_skip_observed': terminal_at is not None,
                'model_calls': 0, 'actual_dsh_agent': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pattern', help='Quoted local chapter glob; source files remain read-only')
    parser.add_argument('--runs', type=int, default=64)
    parser.add_argument('--service-routes', action='store_true', help='Also run 4 full durable service campaigns')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    paths = [Path(path) for path in sorted(glob.glob(args.pattern))]
    if not paths or not 1 <= args.runs <= 4096:
        parser.error('Need chapters and 1..4096 sample routes.')
    report = {'schema_version': 1, 'kind': 'private_source_software_compatibility_audit',
              'compatibility_version': COMPATIBILITY_VERSION, 'paid_model_calls': 0,
              'actual_dsh_agent': False, 'clean_windows_machine': False}
    with tempfile.TemporaryDirectory(prefix='fish-normalized-audit-') as temporary:
        prepared, docs, changes = [], [], []
        for index, path in enumerate(paths):
            doc, updates = normalize_detroit_chapter(json.loads(path.read_text(encoding='utf-8-sig')))
            changes.extend(updates)
            docs.append(doc)
            target = Path(temporary) / f'chapter{index:03}.json'
            target.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
            prepared.append(target)
        report['metadata_repairs'] = changes
        report['static'] = static_audit(docs)
        report['sampled_routes'] = sampled_campaigns(prepared, args.runs)
        report['service_routes'] = []
        if args.service_routes:
            for style in ('self_aware', 'immersive'):
                for policy in ('first', 'last'):
                    result = service_campaign(prepared, style, policy)
                    report['service_routes'].append(result)
                    print(json.dumps({'service_route_completed': result}), flush=True)
    report['passed'] = (not report['static']['unattributed_decision_variants']
                        and not report['static']['missing_ending_targets']
                        and not report['sampled_routes']['errors'])
    report['limits'] = [
        'Static attribution inspects every declared context variant, including unreachable variants.',
        'Seeded routes sample reachable state combinations; all branches and all random outcomes are not proven.',
        'Human-visible multi-character narratives without attribution remain outside immersive role history.',
        'Software fixtures do not establish original Agent decisions or clean-machine installation.',
    ]
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + '\n', encoding='utf-8')
    print(output)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

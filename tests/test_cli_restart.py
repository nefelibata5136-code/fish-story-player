"""A new OS process reads each step: actual CLI shutdown/restart persistence."""
import json
import os
import subprocess
import sys


def test_cli_across_separate_processes(tmp_path):
    def cli(*args):
        result = subprocess.run([sys.executable, '-m', 'fish_story.cli', '--home', str(tmp_path), *args],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    first = cli('new', '--player', 'cli-fixture')
    sid = first['session_id']
    assert cli('view', sid) == first
    assert cli('pause', sid)['status'] == 'paused'
    assert cli('view', sid)['status'] == 'paused'
    cli('resume', sid)
    next_view = cli('choose', sid, first['current']['request_id'], '1')
    assert next_view['accepted_choices'] == 1
    assert cli('view', sid) == next_view
    exported = cli('export', sid, '--format', 'json')
    assert exported['records'][0]['choice'] == 1

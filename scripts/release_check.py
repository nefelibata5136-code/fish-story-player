"""Read-only publication check. Never opens ignored private runtime directories."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOT = {'README.md', 'AGENT_START.md', 'LICENSE', 'pyproject.toml', '.gitignore', 'start.cmd', 'AGENTS.md', 'MANIFEST.in'}
ALLOWED_DIRS = {'fish_story', 'tests', 'docs', 'scripts', 'examples', 'integrations', '.github'}
BLOCKED = {'state', 'data', 'exports', 'checkpoint', 'home', 'sessions', 'node_modules', '.venv', '__pycache__'}
SECRET = re.compile(r'(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
PERSONAL = re.compile(r'C:[/\\]Users[/\\](?!YOUR_NAME|your-name)[^/\\\s"\']+|life-[0-9a-f]{8}-[0-9a-f-]{27,}')


def check(paths):
    issues = []
    for name in paths:
        path = Path(name)
        parts = path.parts
        if not parts:
            continue
        if parts[0] not in ALLOWED_DIRS and name not in ALLOWED_ROOT:
            issues.append(f'{name}: outside publication allowlist')
        if any(p in BLOCKED for p in parts) or path.suffix.lower() in {'.sqlite', '.db', '.key', '.log'} or path.name.startswith('.env'):
            issues.append(f'{name}: private/runtime file type')
        if path.suffix.lower() == '.json' and not (parts[:2] == ('fish_story', 'demo') or parts[0] in {'examples', 'integrations'}):
            issues.append(f'{name}: unexpected JSON data')
        if '01_json' in parts or '02_setting' in parts or '04_execution' in parts:
            issues.append(f'{name}: excluded upstream story/config/result material')
        content = (ROOT / path).read_bytes()
        if path.suffix.lower() in {'.png', '.jpg', '.webp'}:
            continue
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            issues.append(f'{name}: unreviewed binary')
            continue
        if SECRET.search(text):
            issues.append(f'{name}: credential-shaped content; inspect locally without echoing it')
        if PERSONAL.search(text):
            issues.append(f'{name}: personal absolute path or life identifier')
    return issues


def main():
    output = subprocess.run(['git', 'ls-files', '--cached'], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    paths = [p for p in output.splitlines() if p]
    if not paths:
        print('No staged/tracked release files. Stage explicit publication paths first.', file=sys.stderr)
        return 1
    issues = check(paths)
    print(json.dumps({'checked_files': len(paths), 'passed': not issues, 'issues': issues,
                      'scope': 'tracked/staged source only; ignored private directories were not read',
                      'limits': 'Heuristic credential scan plus allowlist; license and visual artifact review remain manual.'}, indent=2))
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Startup failures and environment probes must be understandable and non-destructive."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fish_story import cli, desktop

ROOT = Path(__file__).resolve().parents[1]


def test_double_click_reports_early_storage_failure_without_private_traceback(monkeypatch, capsys):
    def unavailable(_):
        raise PermissionError('PRIVATE_PATH_OR_TOKEN_SENTINEL')

    monkeypatch.setattr(cli, 'main', unavailable)
    monkeypatch.setattr(sys, 'stdin', None)
    assert desktop.main([]) == 1
    result = capsys.readouterr()
    assert '底特律' in result.out
    assert '存档' in result.err and '重新完整解压' in result.err
    assert 'PRIVATE_PATH_OR_TOKEN_SENTINEL' not in result.err
    assert 'Traceback' not in result.err


def test_intentional_console_stop_does_not_show_reinstall_instructions(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'main', lambda _: 130)
    assert desktop.main([]) == 130
    assert capsys.readouterr().err == ''


@pytest.fixture
def powershell():
    if sys.platform != 'win32':
        pytest.skip('PowerShell launcher is Windows-specific')
    return Path(os.environ['SystemRoot']) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'


def run_powershell(powershell, script, *arguments, environment=None):
    return subprocess.run([str(powershell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                           str(script), *arguments], env=environment, capture_output=True,
                          text=True, encoding='utf-8', timeout=20)


def test_source_launcher_without_python_gives_chinese_portable_guidance(powershell, tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    launcher = scripts / 'launch_windows.ps1'
    shutil.copyfile(ROOT / 'scripts' / launcher.name, launcher)
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="synthetic-source"', encoding='utf-8')
    environment = dict(os.environ)
    environment['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    result = run_powershell(powershell, launcher, '-CheckOnly', environment=environment)
    assert result.returncode == 1
    assert '便携包' in result.stdout and 'Python' in result.stdout
    assert 'Traceback' not in result.stderr and result.stderr == ''
    assert not (tmp_path / '.venv').exists()


def test_portable_launcher_reports_incomplete_extraction_without_creating_environment(powershell, tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    launcher = scripts / 'launch_windows.ps1'
    shutil.copyfile(ROOT / 'scripts' / launcher.name, launcher)
    result = run_powershell(powershell, launcher, '-CheckOnly')
    assert result.returncode == 1
    assert '没有完整解压' in result.stdout
    assert result.stderr == ''
    assert not (tmp_path / '.venv').exists()


def test_installer_preserves_incomplete_existing_version_without_network(powershell, tmp_path):
    directory = tmp_path / 'installation' / '0.4.1'
    directory.mkdir(parents=True)
    sentinel = directory / 'keep.txt'
    sentinel.write_text('existing installation must remain', encoding='utf-8')
    result = run_powershell(powershell, ROOT / 'scripts' / 'install_windows.ps1',
                            '-InstallRoot', str(directory.parent))
    assert result.returncode == 1
    assert '保留该目录' in result.stdout
    assert result.stderr == ''
    assert sentinel.read_text(encoding='utf-8') == 'existing installation must remain'
    assert sorted(item.name for item in directory.iterdir()) == ['keep.txt']


def test_installer_reuses_complete_runtime_without_python_or_download(powershell, tmp_path):
    directory = tmp_path / 'installation' / '0.4.1'
    directory.mkdir(parents=True)
    for name in ('FishStoryPlayer.exe', 'fish-story.exe'):
        (directory / name).write_bytes(b'not launched in this read-only reuse check')
    (directory / '_internal').mkdir()
    result = run_powershell(powershell, ROOT / 'scripts' / 'install_windows.ps1',
                            '-InstallRoot', str(directory.parent))
    assert result.returncode == 0
    assert str(directory / 'fish-story.exe') in result.stdout
    assert result.stderr == ''
